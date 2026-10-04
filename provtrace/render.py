"""Render a tracer run (records input + model report) as a self-contained HTML timeline."""
import re,html,sys,json
import os
ANON=json.load(open('anon.json')) if os.path.exists('anon.json') else {}  # {"real name": "placeholder"}, kept private
PUBLIC=os.environ.get('PUBLIC')=='1'  # public mode: only source + flagged records, 300-char excerpts
EMAIL=re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w.]+)?')
def anon(s):
    s=EMAIL.sub('[email]',s)
    for k,v in sorted(ANON.items(),key=lambda kv:-len(kv[0])): s=re.sub(re.escape(k),v,s,flags=re.I)
    return s
AGENT_IDS={}
def _who(w):
    m=re.fullmatch(r'agent-([0-9a-f]{6})',w.strip())
    if not m: return w
    if not AGENT_IDS:
        import gzip
        for p in ('../data/agents.jsonl.gz','data/agents.jsonl.gz'):
            if os.path.exists(p):
                for l in gzip.open(p,'rt'):
                    d=json.loads(l); AGENT_IDS[d['id'][:6]]=d.get('name')
                break
    return AGENT_IDS.get(m.group(1),w)
def parse_records(txt):
    out=[]
    for rec in re.split(r'\n\n(?=\[R\d+\] )',txt.strip()):
        m=re.match(r'\[R(\d+)\] (\S+ \S+) \| (.*?) \| (\S+)\n?(.*)',rec,re.S)
        if m: out.append(dict(id=int(m.group(1)),t=m.group(2),who=_who(m.group(3)),kind=m.group(4),text=m.group(5)))
    return out
def ids(s):
    res=set()
    for a,b in re.findall(r'R(\d+)\s*[–-]\s*R?(\d+)',s): res|=set(range(int(a),int(b)+1))
    res|={int(x) for x in re.findall(r'R(\d+)',s)}
    return res
def classes(report):
    sec=report.split('### 2')[0]; cl={}; cur=None
    for line in sec.splitlines():
        m=re.search(r'\b(SOURCE|RETELLING|OUTBOUND|OTHER)\b',line)
        if m and re.match(r'\s*[*-]?\s*\**\s*(SOURCE|RETELLING|OUTBOUND|OTHER)',line): cur=m.group(1)
        m2=re.match(r'\s*[*-]\s*\**\[?R(\d+)\]?\**\s*:?\s*\**(SOURCE|RETELLING|OUTBOUND|OTHER)',line)
        if m2: cl.setdefault(int(m2.group(1)),m2.group(2)); continue
        if cur:
            for i in ids(line): cl.setdefault(i,cur)
    return cl
def departures(report):
    i=report.find('### 3'); j=report.find('### 4')
    if i<0:  # tolerate other heading styles: find the departures section by its title
        m=re.search(r'(?im)^\W*3\W.*depart',report); n=re.search(r'(?im)^\W*4\W.*(earliest|first)',report)
        i=m.start() if m else -1; j=n.start() if n else len(report)
    sec=report[i:j] if i>=0 else ''
    flagged=set()
    for m in re.finditer(r'\*\*\[?R(\d+)\]?\*\*|Record(?: ID)?\**\s*:?\s*\**\s*\[?R(\d+)|^\* \*\*\[R(\d+)\]',sec,re.M):
        flagged.add(int(next(g for g in m.groups() if g)))
    for line in sec.splitlines():
        if re.match(r'\*\*Departing Records?\*\*',line): flagged|={int(x) for x in re.findall(r'R(\d+)',line)}
        if re.match(r'(\*|\d+\.) +\*\*`?\[?R\d+',line): flagged|={int(x) for x in re.findall(r'R(\d+)',line.split(':')[0])}
    return flagged

def section(report,n):
    """Text of numbered section n (### n. ...) of a tracer report, or ''."""
    m=re.search(rf'(?m)^#+\s*\**{n}\b.*$',report)
    if not m: return ''
    e=re.search(rf'(?m)^#+\s*\**{n+1}\b',report[m.end():])
    return report[m.end():m.end()+e.start() if e else len(report)].strip()
def head(s,n=900):
    """The first lines of a report section, cut at a line boundary."""
    out=[]
    for line in s.splitlines():
        if out and sum(map(len,out))+len(line)>n: out.append('…'); break
        out.append(line)
    return '\n'.join(out)
def md(s,shown=None):
    """Minimal markdown to HTML for tracer report text; record ids link to the records table when shown."""
    out=[]; lst=0
    for line in anon(s).splitlines():
        t=line.strip()
        if not t or set(t)<=set('-*_'):
            if lst: out.append('</ul>'*lst); lst=0
            continue
        h=html.escape(t)
        h=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',h); h=re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)',r'<i>\1</i>',h); h=re.sub(r'`([^`]+)`',r'<code>\1</code>',h)
        h=re.sub(r'\[?R(\d+)\]?',lambda m:f"<a href='#r{m.group(1)}'>R{m.group(1)}</a>" if (shown is None or int(m.group(1)) in shown) else f"R{m.group(1)}",h)
        ind=(len(line)-len(line.lstrip()))//2
        if re.match(r'([*-]|\d+\.) ',t):
            want=ind+1
            while lst<want: out.append('<ul>'); lst+=1
            while lst>want: out.append('</ul>'); lst-=1
            out.append('<li>'+re.sub(r'^([*-]|\d+\.)\s+','',h)+'</li>')
        else:
            if lst: out.append('</ul>'*lst); lst=0
            out.append(f"<h4>{re.sub(r'^#+ *','',h)}</h4>" if t.startswith('#') else f'<p>{h}</p>')
    if lst: out.append('</ul>'*lst)
    return ''.join(out)

def timeline(recs,cl,dep,show=set(),shown=None):
    """Swim-lane SVG: one lane per speaker, records in time order (x = order, dated ticks), colour = class, red ring = flagged departure."""
    R=[r for r in recs if cl.get(r['id'],'OTHER')!='OTHER' or r['id'] in dep or r['id'] in show]
    if not R: return ''
    who=[];
    for r in R:
        w=anon(r['who'])
        if w not in who: who.append(w)
    W,LH,L=900,22,170; H=LH*len(who)+40
    X=lambda k:L+10+(W-L-70)*(k/(max(1,len(R)-1)))
    out=[f"<svg width='{W}' height='{H}' style='font:11px system-ui;margin:8px 0'>"]
    for j,w in enumerate(who):
        y=20+LH*j; out.append(f"<text x='{L}' y='{y+4}' text-anchor='end'>{html.escape(w[:26])}</text><line x1='{L+5}' y1='{y}' x2='{W-10}' y2='{y}' stroke='#ddd'/>")
    span=len({r['t'][:10] for r in R})>6
    for k in sorted({round(x*(len(R)-1)/5) for x in range(6)}):
        t=R[k]['t']; lab=t[5:10] if span else t[5:16]
        out.append(f"<text x='{X(k):.0f}' y='{H-6}' text-anchor='middle' fill='#666'>{lab}</text>")
    for k,r in enumerate(R):
        y=20+LH*who.index(anon(r['who'])); c=cl.get(r['id'],'OTHER')
        col={'SOURCE':'#2e9d4a','RETELLING':'#e0a400','OUTBOUND':'#c62828','OTHER':'#999'}[c]
        if c=='SOURCE' and r['id'] in dep: col='#e0a400'  # the agent misread the source while observing it: show as a retelling
        ring=" stroke='#b00' stroke-width='2.5'" if r['id'] in dep else ''
        circ=f"<circle cx='{X(k):.1f}' cy='{y}' r='5' fill='{col}'{ring}{'' if (shown is None or r['id'] in shown) else ' opacity=0.45'}><title>R{r['id']} {r['t']} {c}{' (flagged)' if r['id'] in dep else ''}{'' if (shown is None or r['id'] in shown) else ' (not shown in the table)'}</title></circle>"
        out.append(f"<a href='#r{r['id']}'>{circ}</a>" if (shown is None or r['id'] in shown) else circ)
    out.append('</svg>')
    leg="<div style='font-size:12px;color:#444'>Each dot is a record, in time order; rows are speakers. <span style='color:#2e9d4a'>●</span> source <span style='color:#e0a400'>●</span> retelling <span style='color:#c62828'>●</span> outbound; a red ring marks a record the tracer flags as departing from the sources (including an agent misreading the source as it looks at it). Faded dots are records not shown in the table below.</div>"
    return leg+''.join(out)
COL={'SOURCE':'#d9f2d9','RETELLING':'#fff4cc','OUTBOUND':'#ffd9d9','OTHER':'#eeeeee'}
def render(title,summary,inp,rep,out,pattern=None):
    recs=parse_records(open(inp).read()); report=open(rep).read()
    cl=classes(report); dep=departures(report)
    stem=os.path.splitext(os.path.basename(out))[0]
    AT={a['id']:a for a in json.load(open('atlas.json'))} if os.path.exists('atlas.json') else {}
    a=AT.get(stem,{}); KEY=re.compile(a['key'],re.I) if a.get('key') else None; SHOW=set(a.get('show',[]))
    if KEY is None and pattern: KEY=re.compile(pattern,re.I)
    if summary=='t' and a: summary=html.escape(anon('Source: '+a['source']+' Became: '+a['became']))
    if a.get('scope'): summary+='</p><p style="color:#555;font-size:13px">'+html.escape(a['scope'])
    for i in SHOW: cl.setdefault(i,'SOURCE')
    KEYEV=''
    ef=os.path.join('evidence',stem+'.json')
    if os.path.exists(ef):
        X=json.load(open(ef))
        if X:
            KEYEV="<h2>Key evidence</h2><p class='muted'>The decisive passages in time order, quoted from the original records and checked against the raw logs by our analysis agent (an AI). Record numbers refer to the records list below unless stated.</p>"+''.join(
                f"<div class='ev {('src' if x['label'].lower().startswith('source') else 'dep')}'><div class='evh'><b>{html.escape(x['label'])}</b> · {html.escape(x['t'])} · {html.escape(anon(x['who']))} · {html.escape(x.get('kind',''))} · {html.escape(x.get('ref',''))}</div><pre>{html.escape(anon(x['text']))}</pre></div>" for x in X)
    EXTRA=''
    if a.get('extra') and os.path.exists(a['extra']):
        X=json.load(open(a['extra']))
        EXTRA="<h3>"+html.escape(a.get('extra_title','More records'))+"</h3><table>"+''.join(f"<tr><td>{html.escape(x['t'])}</td><td>{html.escape(anon(x['who'] or ''))}</td><td>to: {html.escape(anon(x.get('to','')))}</td><td><pre>{html.escape(anon(x['text']))}</pre></td></tr>" for x in X)+"</table>"
    rows=[]; SHOWN=set()
    for r in recs:
        c=cl.get(r['id'],'OTHER'); d=r['id'] in dep
        if r['id'] in SHOW and c=='OTHER': c='SOURCE'
        if PUBLIC and not (d or c=='SOURCE' or r['id'] in SHOW): continue
        if PUBLIC and KEY and c=='SOURCE' and not d and r['id'] not in SHOW and not KEY.search(r['text']): continue
        if PUBLIC:
            t=anon(r['text']); r=dict(r); m=KEY.search(t) if KEY else None
            st=max(0,m.start()-120) if m else 0
            r['text']=('[...] ' if st else '')+t[st:st+300]+(' [...]' if len(t)>st+300 else '')
        SHOWN.add(r['id'])
        rows.append(f"<tr id='r{r['id']}' style='background:{COL[c]}'><td>R{r['id']}</td><td>{r['t']}</td><td>{html.escape(anon(r['who']))}</td><td>{r['kind']}</td><td>{'agent misread the source ⚠' if (c=='SOURCE' and d) else c+(' ⚠ departs' if d else '')}</td><td><pre>{html.escape(anon(r['text']))}</pre></td></tr>")
    rep_html=html.escape(anon(report))
    byid={r['id']:r for r in recs}
    s2,s3,s4=section(report,2),section(report,3),section(report,4)
    def excerpt(r,n=600):
        t=anon(r['text']); m=KEY.search(t) if KEY else None; st=max(0,m.start()-150) if m else 0
        return ('… ' if st else '')+t[st:st+n]+(' …' if len(t)>st+n else '')
    if not KEYEV:
        first=[i for i in sorted(ids(s4)) if i in byid][:1]
        srcs=[i for i in sorted(ids(s2)) if i in byid and i not in dep][:2]
        flg=[i for i in sorted(dep) if i in byid and i not in first][:3]
        pick=sorted(set(first+srcs+flg),key=lambda i:byid[i]['t'])
        if pick:
            KEYEV="<h2>Key records</h2><p class='muted'>Selected automatically from the tracer's report: source records it cites, the earliest departure it names, and the first records it flags.</p>"+''.join(
                f"<div class='ev {('dep' if i in dep or i in first else 'src')}'><div class='evh'><b>{'Earliest departure' if i in first else ('Flagged' if i in dep else 'Source')}</b> · {html.escape(byid[i]['t'])} · {html.escape(anon(byid[i]['who']))} · {byid[i]['kind']} · R{i}</div><pre>{html.escape(excerpt(byid[i]))}</pre></div>" for i in pick)
    TRACER=''
    if s3:
        TRACER=("<details class='trd'><summary>What the tracer reported (raw tool output)</summary><p class='muted'>"+("The tracer's own findings for this run, unedited apart from anonymization. They are leads: the summary and key evidence above were written after checking them against the records." if a else "The tracer's findings, unedited. Every flag is a lead to check against the cited records.")
            +"</p><div class='tr'>"+(f"<h4>Earliest departure</h4>{md(s4,SHOWN)}" if (s4 and not a) else '')+f"<h4>Departures</h4>{md(s3,SHOWN)}</div></details>")
    CSS="""
:root{--ink:#1c1c1a;--muted:#6b675e;--bg:#faf8f3;--card:#fff;--line:#e7e2d6;--red:#b3261e;--green:#2e7d4f;--amber:#b7791f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:22px 28px 70px}nav a{color:var(--muted);text-decoration:none;font-size:14px}
.kind{font-size:12.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--red);font-weight:700;margin-top:18px}
h1{font-family:Georgia,'Iowan Old Style',serif;font-size:40px;line-height:1.12;margin:8px 0 14px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:22px}.chip{background:#efeadf;border-radius:999px;padding:4px 12px;font-size:13px;color:#46423a}.chip.out{background:var(--red);color:#fff;font-weight:600}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:16px}.box{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;font-size:15.5px}
.box h3{margin:0 0 8px;font-size:12.5px;text-transform:uppercase;letter-spacing:.07em}.box.src{border-top:4px solid var(--green)}.box.src h3{color:var(--green)}.box.dep{border-top:4px solid var(--red)}.box.dep h3{color:var(--red)}
.scope{font-size:13.5px;color:var(--muted);margin:12px 0 0}
h2{font-family:Georgia,serif;font-size:26px;margin:38px 0 6px}.muted{color:var(--muted);font-size:14px;margin:0 0 14px}
.ev{position:relative;padding:0 0 18px 26px;border-left:2px solid var(--line);margin-left:8px}.ev:last-child{border-left-color:transparent}
.ev:before{content:'';position:absolute;left:-8px;top:4px;width:14px;height:14px;border-radius:50%;background:var(--amber);border:2px solid var(--bg)}.ev.src:before{background:var(--green)}
.evh{font-size:13.5px;color:#46423a;margin-bottom:6px}.evh b{color:var(--ink);font-size:14.5px}
.ev pre{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0;white-space:pre-wrap;font:13px/1.5 ui-monospace,Menlo,monospace;max-height:260px;overflow:auto}
.tl{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px;overflow-x:auto}.tl svg{border:none;padding:0;background:none}
details{margin-top:14px}summary{cursor:pointer;font-weight:600;font-size:15px;padding:10px 0}
table{border-collapse:separate;border-spacing:0 6px;width:100%}td{vertical-align:top;padding:8px 10px;font-size:13px}td:first-child{border-radius:8px 0 0 8px;font-weight:600}td:last-child{border-radius:0 8px 8px 0}
pre{white-space:pre-wrap;margin:0;font:12.5px/1.45 ui-monospace,Menlo,monospace}.legend{font-size:13px;color:var(--muted)}
.tr{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 20px 12px;font-size:14.5px;max-height:520px;overflow:auto}.tr h4,.mdb h4{margin:12px 0 4px;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}.tr ul,.mdb ul{padding-left:20px;margin:4px 0}.tr p,.mdb p{margin:6px 0}.mdb{max-height:420px;overflow:auto;font-size:14.5px}
@media(max-width:800px){.cmp{grid-template-columns:1fr}h1{font-size:30px}}
"""
    chips=''
    if a:
        chips="<div class='chips'>"+(f"<span class='chip out'>Reached outside the village</span>" if a.get('outbound','').startswith('Yes') else '')+f"<span class='chip'>First departure: {html.escape(a.get('first',''))}</span><span class='chip'>{a.get('agents')} agent{'s' if a.get('agents')!=1 else ''} stated it</span><span class='chip'>Outbound: {html.escape(a.get('outbound',''))}</span></div>"
    cmp=(f"<div class='cmp'><div class='box src'><h3>What the source said</h3>{html.escape(anon(a['source']))}</div><div class='box dep'><h3>What it became</h3>{html.escape(anon(a['became']))}</div></div>"+(f"<p class='scope'>{html.escape(a['scope'])}</p>" if a.get('scope') else '')) if a else (f"<div class='cmp'><div class='box src'><h3>What the sources show (tracer)</h3><div class='mdb'>{md(s2,SHOWN)}</div></div><div class='box dep'><h3>Where the account departs (tracer)</h3><div class='mdb'>{(md(head(s3),SHOWN)+'<h4>Earliest departure</h4>'+md(s4,SHOWN)) if s3 else 'No departure reported.'}</div></div></div>" if s2 else f"<p>{summary}</p>")
    leg=f"<p class='legend'>Row colours: <span style='background:{COL['SOURCE']}'>source</span> <span style='background:{COL['RETELLING']}'>retelling</span> <span style='background:{COL['OUTBOUND']}'>outbound</span> <span style='background:{COL['OTHER']}'>other</span>. ⚠ = the tracer flags this record as departing from the sources (unreviewed tool output).</p>"
    doc=f"""<!doctype html><html lang='en'><meta charset=utf-8><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)} · Provenance Tracer</title><style>{CSS}</style>
<div class='wrap'><nav><a href='../index.html'>← Provenance Tracer · Drift atlas</a></nav>
<div class='kind'>{html.escape(a.get('kind','')) if a else ''}</div><h1>{html.escape(title)}</h1>{chips}{cmp}
{KEYEV}
<h2>Who repeated it, and when</h2><div class='tl'>{timeline(recs,cl,dep,SHOW,SHOWN)}</div>
{TRACER}
<details><summary>Records ({len(rows)} shown, of {len(recs)} the tracer collected)</summary>{leg}{'' if PUBLIC else '<details><summary>Tracer report (model output)</summary><pre>'+rep_html+'</pre></details>'}<table>{''.join(rows)}</table></details>{EXTRA}</div></html>"""
    open(out,'w').write(doc)
    return len(recs),len(dep),{k:list(cl.values()).count(k) for k in COL}
if __name__=='__main__':
    print(render(*sys.argv[1:6]))

