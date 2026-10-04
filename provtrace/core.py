"""Record collection and the single-call trace: every record that mentions an entity in the AI Village
database plus nearby human chat, in time order, and one model call that separates sources, retellings and outbound text."""
import argparse,bisect,datetime as dt,gzip,hashlib,json,os,re,shutil,subprocess,urllib.request,time
MODEL=os.environ.get("PROVTRACE_MODEL","gemini-3.8-flash")
def gemini(prompt,model=None):
    model=model or MODEL
    key=open(os.path.expanduser(os.environ.get("GEMINI_KEY_FILE","~/.config/gemini/key"))).read().strip()
    body=json.dumps({"model":model,"input":prompt}).encode()
    for a in range(8):
        try:
            req=urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/interactions",data=body,
                headers={"x-goog-api-key":key,"Content-Type":"application/json"})
            d=json.loads(urllib.request.urlopen(req,timeout=300).read())
            return "".join(c.get("text","") for s in d.get("steps",[]) if s.get("type")=="model_output" for c in s.get("content",[]))
        except Exception as e:
            err=e; time.sleep(min(60,5*2**a))
    raise err
def turn_texts(r):
    a=r.get("agent_action") or {}; out=[]
    if isinstance(a,dict):
        if a.get("action")=="send_message_back_to_chat": out.append(("CHAT_POST",a.get("content") or ""))
        elif a.get("action")=="type" and isinstance(a.get("text"),str): out.append(("TYPED",a["text"]))
        elif a.get("command"): out.append(("COMMAND",str(a["command"])))
    if r.get("output"): out.append(("TOOL_OUTPUT",str(r["output"])))
    for m in re.finditer(r'"(?:thinking|text|summary_text)": "((?:[^"\\]|\\.)*)',json.dumps(r.get("agent_messages"))):
        try: out.append(("NARRATION",json.loads('"'+m.group(1)+'"')))
        except Exception: pass
    return out
def collect(data,pat,start,end):
    rx=re.compile(pat,re.I); rxb=re.compile(pat.encode(),re.I)
    agents={a["id"]:a["name"] for a in map(json.loads,gzip.open(f"{data}/agents.jsonl.gz","rt"))}
    sess={}
    for l in gzip.open(f"{data}/computer_use_sessions.jsonl.gz","rt"):
        s=json.loads(l); sess[s["id"]]=agents.get(s.get("agent_id"),"?")
    recs=[]
    p=subprocess.Popen([shutil.which("gzcat") or "zcat",f"{data}/computer_use_turns.jsonl.gz"],stdout=subprocess.PIPE,bufsize=1<<24)
    for line in p.stdout:
        if not rxb.search(line): continue
        r=json.loads(line); t=r["created_at"][:19].replace("T"," ")
        if not start<=t<=end: continue
        for kind,s in turn_texts(r):
            if rx.search(s): recs.append({"t":t,"who":sess.get(r["session_id"],"?"),"kind":kind,"text":s})
    humans=[]
    for l in gzip.open(f"{data}/chat_messages.jsonl.gz","rt"):
        r=json.loads(l); t=r["created_at"][:19].replace("T"," ")
        if not start<=t<=end: continue
        if r["speaker_type"]=="user": humans.append((t,r["content"]))
        elif rx.search(r["content"]): recs.append({"t":t,"who":agents.get(r.get("agent_speaker_id"),"?"),"kind":"CHAT_MESSAGE","text":r["content"]})
    return recs,sorted(humans)
def build(recs,humans,pat,w=1000,cap=150000,nh=30):
    f=dt.datetime.fromisoformat; seen=set(); items=[]
    for r in sorted(recs,key=lambda r:r["t"]):
        idx=[m.start() for m in re.finditer(pat,r["text"],re.I)]
        segs=[]; a=b=None
        for i in idx:
            if a is not None and i-w<=b: b=i+w
            else:
                if a is not None: segs.append(r["text"][a:b])
                a,b=max(0,i-w),i+w
        if a is not None: segs.append(r["text"][a:b])
        for s in segs:
            h=(r["who"],r["t"],hashlib.md5(s.encode()).hexdigest())  # drop only exact repeats from the same speaker and moment
            if h not in seen: seen.add(h); items.append({**r,"seg":s})
    ts=[h[0] for h in humans]; near={}
    for r in recs:
        t=f(r["t"])
        for i in range(bisect.bisect_left(ts,(t-dt.timedelta(minutes=5)).isoformat(sep=" ")),bisect.bisect_right(ts,(t+dt.timedelta(minutes=2)).isoformat(sep=" "))):
            near[humans[i]]=min(near.get(humans[i],1e9),abs((f(humans[i][0])-t).total_seconds()))
    for (t,c),_ in sorted(near.items(),key=lambda kv:kv[1])[:nh]:
        items.append({"t":t,"who":"human (name not recorded)","kind":"HUMAN_CHAT","seg":c[:600]})
    items.sort(key=lambda i:i["t"])
    while sum(len(i["seg"]) for i in items)>cap and len(items)>1: items.pop()  # over the cap, drop the latest records and keep the earliest (sources come first)
    return "\n\n".join(f"[R{k+1}] {i['t']} | {i['who']} | {i['kind']}\n{i['seg']}" for k,i in enumerate(items))
HERE=os.path.dirname(os.path.abspath(__file__))
def default_pattern(entity): return r"\b"+re.escape(entity)+r"\b"
def stem_for(out,entity):
    os.makedirs(out,exist_ok=True); return os.path.join(out,re.sub(r"[^A-Za-z0-9]+","_",entity).strip("_"))
def fix_end(end): return end+" 23:59:59" if len(end)==10 else end
def prompt_for(entity,records): return open(os.path.join(HERE,"prompt.md")).read().replace("{ENTITY}",entity).replace("{RECORDS}",records)
def trace(entity,data,pattern=None,start="0000",end="9999",out="runs",cap=150000):
    """Collect, build the time-ordered record list, run one model call. Returns (input_path, report_path, n_records_collected, chars)."""
    pat=pattern or default_pattern(entity)
    recs,humans=collect(data,pat,start,fix_end(end))
    txt=build(recs,humans,pat,cap=cap)
    stem=stem_for(out,entity)
    open(stem+".input.txt","w").write(txt)
    open(stem+".report.md","w").write(gemini(prompt_for(entity,txt)))
    return stem+".input.txt",stem+".report.md",len(recs),len(txt)
def estimate(entity,data,pattern=None,start="0000",end="9999",chunk=140000):
    """No model call: how many records mention the entity and whether one read can hold them."""
    pat=pattern or default_pattern(entity)
    recs,humans=collect(data,pat,start,fix_end(end))
    full=build(recs,humans,pat,cap=10**12)
    n=len(full); return {"records":len(recs),"chars":n,"fits_one_read":n<=150000,"chunks_if_scanned":max(1,-(-n//chunk)),
        "est_usd_one_read":round(min(n,150000)/4*0.75e-6+3000*3.75e-6,3),"est_usd_scan":round(n/4*0.75e-6+max(1,-(-n//chunk))*3000*3.75e-6,3)}
