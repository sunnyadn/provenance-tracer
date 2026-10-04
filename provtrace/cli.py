"""provtrace command line: trace, scan, estimate, leads, render. See README for examples."""
import argparse, os, re, sys, textwrap
from . import core, render as R

def summarize(entity, inp, rep, html_path=None, pattern=None):
    recs = {r["id"]: r for r in R.parse_records(open(inp).read())}
    report = open(rep).read(); dep = R.departures(report); cl = R.classes(report)
    first = [i for i in sorted(R.ids(R.section(report, 4))) if i in recs][:1]
    n = lambda k: sum(v == k for v in cl.values())
    print(f"\n{entity}: {len(recs)} records · {n('SOURCE')} source · {n('RETELLING')} retelling · {n('OUTBOUND')} outbound")
    if not dep and not first:
        print("No departure from the sources reported.")
    else:
        print(f"{len(dep)} record(s) flagged as departing from the sources.")
        if first:
            r = recs[first[0]]
            print(f"Earliest departure: R{r['id']}  {r['t']}  {r['who']}  {r['kind']}")
            t = " ".join(r["text"].split()); m = re.search(pattern or re.escape(entity), t, re.I); st = max(0, m.start() - 120) if m else 0
            print(textwrap.indent(textwrap.fill(("… " if st else "") + t[st:st + 320] + " …", 96), "    "))
    print(f"\nreport: {rep}\nrecords: {inp}" + (f"\npage: {html_path}" if html_path else ""))
    print("Flags are leads: check them against the cited records.")

def page(entity, inp, rep, pattern):
    out = os.path.splitext(rep)[0].removesuffix(".report") + ".html"
    R.render("Provenance trace for " + entity, "", inp, rep, out, pattern=pattern)
    return out

def main(argv=None):
    ap = argparse.ArgumentParser(prog="provtrace", description="Trace how an AI swarm's account of a person or organization changes.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p):
        p.add_argument("entity", help="person or organization, e.g. \"Heifer International\"")
        p.add_argument("--data", default=os.environ.get("PROVTRACE_DATA", "./data"), help="AI Village transcript export directory (*.jsonl.gz)")
        p.add_argument("--pattern", help="regex for name variants (default: the name as a whole word)")
        p.add_argument("--start", default="0000", help="YYYY-MM-DD"); p.add_argument("--end", default="9999", help="YYYY-MM-DD")
        p.add_argument("--out", default="runs")
    p = sub.add_parser("trace", help="one read of every record that mentions a name"); common(p)
    p.add_argument("--no-html", action="store_true")
    p = sub.add_parser("scan", help="read a long history chunk by chunk and keep every flag"); common(p)
    p.add_argument("--cap-usd", type=float, required=True, help="hard spending cap for this scan")
    p.add_argument("--parts", default="", help="only these chunks, e.g. 1,2"); p.add_argument("--no-html", action="store_true")
    p = sub.add_parser("estimate", help="record count and cost estimate, no model call"); common(p)
    p = sub.add_parser("leads", help="find corrections the agents posted themselves")
    p.add_argument("--data", default=os.environ.get("PROVTRACE_DATA", "./data")); p.add_argument("--classify", action="store_true"); p.add_argument("--out", default="leads.json")
    p = sub.add_parser("render", help="render a saved run as an HTML page")
    p.add_argument("input"); p.add_argument("report"); p.add_argument("--out", required=True); p.add_argument("--title", default="Provenance trace")
    a = ap.parse_args(argv)

    if a.cmd == "estimate":
        e = core.estimate(a.entity, a.data, a.pattern, a.start, a.end)
        print(f"{a.entity}: {e['records']} records, {e['chars']:,} characters")
        print(f"one read: {'fits' if e['fits_one_read'] else 'too long, keeps the earliest 150k characters'} (~${e['est_usd_one_read']})")
        if not e["fits_one_read"]: print(f"scan: {e['chunks_if_scanned']} chunks (~${e['est_usd_scan']})")
    elif a.cmd == "trace":
        inp, rep, n, chars = core.trace(a.entity, a.data, a.pattern, a.start, a.end, a.out)
        if n and chars >= 149000: print("Note: history longer than one read; the earliest records were kept. Try `provtrace scan`.", file=sys.stderr)
        summarize(a.entity, inp, rep, None if a.no_html else page(a.entity, inp, rep, a.pattern or core.default_pattern(a.entity)), a.pattern or core.default_pattern(a.entity))
    elif a.cmd == "scan":
        from . import scan
        inp, rep, meta = scan.scan(a.entity, a.data, a.pattern, a.start, a.end, a.out, a.cap_usd, a.parts)
        print(f"{meta['chunks_run']} of {meta['chunks']} chunks read, {meta['chunks_not_run']} skipped, ${meta['spent_usd']} spent")
        summarize(a.entity, inp, rep, None if a.no_html else page(a.entity, inp, rep, a.pattern or core.default_pattern(a.entity)), a.pattern or core.default_pattern(a.entity))
    elif a.cmd == "leads":
        from . import leads
        n, L = leads.leads(a.data, a.classify, a.out)
        print(f"{n} correction candidates" + (f", {len(L)} about outside people, organizations or public facts" if a.classify else "") + f" -> {a.out}")
        for r in L[:10]:
            lab = r.get("label", {})
            print(f"  {r['t']}  {r['who']}: {lab.get('false_claim') or ' '.join(r['text'].split())[:100]}" + (f"  [search: {', '.join(lab.get('search_terms', []))}]" if lab else ""))
    elif a.cmd == "render":
        R.render(a.title, "", a.input, a.report, a.out); print(a.out)

if __name__ == "__main__":
    main()
