"""Find tracing leads from the agents' own corrections: chat messages saying an earlier claim was wrong.
Optionally classify them with a model and keep those about outside people, organizations or public facts."""
import argparse,gzip,json,os,re
from concurrent.futures import ThreadPoolExecutor
from .core import gemini

PHRASES=re.compile(r"(?i)my (data|memory|notes|assumption|records?|tracking|claim|report) (was|were|is) (wrong|false|incorrect|mistaken)"
    r"|I was (wrong|mistaken) about|I incorrectly (stated|reported|claimed|said|told|wrote)|(quick |important |critical |small )?correction:? (I|my|on my|to my)"
    r"|I need to correct|that was (my )?(error|mistake)|I (misread|misreported|misremembered|conflated|fabricated|hallucinated|mis-?attributed)"
    r"|\bI retract|\berratum\b|(claim|report) (is|was) (FALSE|false|wrong|incorrect)|never actually (sent|happened|replied|existed)"
    r"|turned out (to be )?(false|wrong)|was a misread|phantom (reply|response|email|comment)")
PROMPT='''Below are chat messages written by AI agents in a multi-agent village. Each may or may not report that an earlier claim was wrong.
For EACH item output one JSON object per line (JSON Lines, no prose), with keys:
"k": item number,
"correction": true if the message states that an earlier factual claim (made by this agent or another agent) was wrong, else false,
"trivial": true if the claim is about the current time/deadline, a chess/game move, a typo or duplicate post, a line/word count, or an internal file path/command detail,
"external": true if the wrong claim concerned an outside person, organization, public event or world fact (not the agents' own tooling/repos/tasks),
"false_claim": the wrong claim in <=20 words ("" if none),
"corrected_to": what is actually true in <=20 words,
"who_erred": name of the agent who made the wrong claim, or "unknown",
"search_terms": 2-4 short literal strings likely to appear in earlier records that state the wrong claim,
"left_village": true if the message says the wrong claim had been sent, posted or published outside the agents' chat, else false.
Use only what the message says.

'''
def candidates(data):
    agents={}
    for l in gzip.open(os.path.join(data,"agents.jsonl.gz"),"rt"):
        a=json.loads(l); agents[a["id"]]=a.get("name")
    out=[]
    for l in gzip.open(os.path.join(data,"chat_messages.jsonl.gz"),"rt"):
        d=json.loads(l)
        if d.get("speaker_type")!="agent": continue
        c=d.get("content") or ""; m=PHRASES.search(c)
        if m: out.append({"id":d["id"],"t":d["created_at"][:19],"who":agents.get(d.get("agent_speaker_id"),"?"),"text":c[max(0,m.start()-700):m.end()+500]})
    return sorted(out,key=lambda r:r["t"])
def classify(R,batch=25):
    def job(i):
        items=R[i:i+batch]
        txt="".join(f"\n### item {i+j}\n[{r['t']}] {r['who']}: {r['text']}\n" for j,r in enumerate(items))
        res={}
        for line in gemini(PROMPT+txt).splitlines():
            line=line.strip().strip(",")
            if line.startswith("{"):
                try: d=json.loads(line); res[int(d["k"])]=d
                except Exception: pass
        return res
    out={}
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(job,range(0,len(R),batch)): out.update(r)
    for k,v in out.items():
        if 0<=k<len(R): R[k]["label"]=v
    return R
def leads(data,do_classify=False,out="leads.json"):
    R=candidates(data); n=len(R)
    if do_classify:
        R=[r for r in classify(R) if r.get("label",{}).get("correction") and not r["label"].get("trivial") and r["label"].get("external")]
    json.dump(R,open(out,"w"),indent=1,ensure_ascii=False)
    return n,R
