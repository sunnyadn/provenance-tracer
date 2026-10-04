"""Long histories: run the standard single-call prompt on each time-ordered chunk (no summaries in between)
and keep every flag. Record ids are global, so the merged report renders like a single trace.
Repeated runs on the same chunk flag different things: use the flags as leads."""
import hashlib, json, os, re, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from . import core as T

PIN, POUT, MAXOUT = 0.75e-6, 3.75e-6, 8000
URL = "https://generativelanguage.googleapis.com/v1beta"

def post(path, body):
    key = open(os.path.expanduser(os.environ.get("GEMINI_KEY_FILE", "~/.config/gemini/key"))).read().strip()
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"{URL}/{path}", data=json.dumps(body).encode(),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"}), timeout=300).read())

class Budget:
    """Hard cap: exact input tokens (countTokens) + max output reserved before each attempt; missing usage keeps the reservation."""
    def __init__(self, cap): self.cap, self.spent, self.held, self.lock, self.log = cap, 0.0, 0.0, threading.Lock(), []
    def call(self, prompt, tag):
        ntok = post(f"models/{T.MODEL}:countTokens", {"contents": [{"parts": [{"text": prompt}]}]})["totalTokens"]
        worst = ntok * PIN + MAXOUT * POUT
        for attempt in range(3):
            with self.lock:
                if self.spent + self.held + worst > self.cap:
                    self.log.append({"tag": tag, "status": "skipped: budget"}); return None
                self.held += worst
            try:
                d = post("interactions", {"model": T.MODEL, "input": prompt, "generation_config": {"max_output_tokens": MAXOUT, "thinking_level": "low"}})
                u = d.get("usage") or {}
                cost = (u.get("total_input_tokens", 0) * PIN + (u.get("total_tokens", 0) - u.get("total_input_tokens", 0)) * POUT) if u.get("total_tokens") else worst
                with self.lock: self.held -= worst; self.spent += cost; self.log.append({"tag": tag, "status": d.get("status"), "cost": round(cost, 5), "input_tokens": ntok, "usage_missing": not u.get("total_tokens")})
                return "".join(c.get("text", "") for st in d.get("steps", []) if st.get("type") == "model_output" for c in st.get("content", []))
            except Exception as e:
                with self.lock: self.held -= worst; self.spent += worst; self.log.append({"tag": tag, "status": "error " + type(e).__name__, "cost_assumed": round(worst, 5)})
                time.sleep(10 * (attempt + 1))
        return None

def items_for(recs, humans, pat):
    seen = set(); keep = []
    for r in sorted(recs, key=lambda r: r["t"]):
        h = (r["who"], r["t"], hashlib.md5(r["text"].encode()).hexdigest())
        if h in seen: continue
        seen.add(h); keep.append(r)
    txt = T.build(keep, humans, pat, cap=10 ** 12)
    return [x for x in re.split(r"\n\n(?=\[R\d+\] )", txt) if x.strip()]

def chunks(items, size=140000):
    out, cur, n = [], [], 0
    for it in items:
        if cur and n + len(it) > size: out.append(cur); cur, n = [], 0
        cur.append(it); n += len(it)
    if cur: out.append(cur)
    return out

def section(report, n):
    """Text of numbered section n (### n. ...) of a tracer report, or ''."""
    m = re.search(rf"(?m)^#+\s*{n}\b.*$", report)
    if not m: return ""
    e = re.search(rf"(?m)^#+\s*{n + 1}\b", report[m.end():])
    return report[m.end(): m.end() + e.start() if e else len(report)].strip()

def merge(reports):
    """One report in the standard four-section layout from per-chunk reports (sections concatenated, chunk-labelled)."""
    out = []
    for n, name in [(1, "Record classification"), (2, "What the sources show"), (3, "Departures"), (4, "Earliest departure")]:
        parts = [f"*Chunk {k}:*\n{section(r, n)}" for k, r in reports if r and section(r, n)]
        out.append(f"### {n}. {name}\n\n" + "\n\n".join(parts))
    return "\n\n".join(out)

def scan(entity, data, pattern=None, start="0000", end="9999", out="runs", cap_usd=3.5, parts="", chunk=140000, workers=4):
    pat = pattern or T.default_pattern(entity)
    recs, humans = T.collect(data, pat, start, T.fix_end(end))
    items = items_for(recs, humans, pat); C = chunks(items, chunk)
    stem = T.stem_for(out, entity)
    open(stem + ".input.txt", "w").write("\n\n".join(items))
    todo = [int(x) - 1 for x in parts.split(",")] if parts else list(range(len(C)))
    B = Budget(cap_usd)
    def job(k):
        hdr = f"(This is part {k + 1} of {len(C)} of the records, in time order. Record ids are global.)\n"
        return B.call(T.prompt_for(entity, hdr + "\n\n".join(C[k])), f"part {k + 1}")
    with ThreadPoolExecutor(workers) as ex: reps = list(ex.map(job, todo))
    os.makedirs(stem + ".parts", exist_ok=True)
    for k, r in zip(todo, reps): open(os.path.join(stem + ".parts", f"part{k + 1:03d}.report.md"), "w").write(r or "(not run: budget or error)")
    open(stem + ".report.md", "w").write(merge([(k + 1, r) for k, r in zip(todo, reps)]))
    meta = {"entity": entity, "records": len(recs), "items": len(items), "chunks": len(C), "chunks_run": len(todo),
            "chunks_not_run": sum(r is None for r in reps), "spent_usd": round(B.spent, 4), "calls": B.log}
    json.dump(meta, open(stem + ".scan.json", "w"), indent=1)
    return stem + ".input.txt", stem + ".report.md", meta
