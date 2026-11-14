import requests, re, json, concurrent.futures as cf
names="""Anthropic|OpenAI|Databricks|Stripe|Waymo|Cognition|Anduril|Ramp|Fireworks|ElevenLabs|Baseten|Canva|Applied Intuition|Isomorphic Labs|Mercor|Fal|Sierra|ClickHouse|Perplexity|Modal|Thinking Machines Lab|Crusoe|Together AI|Physical Intelligence|Reflection|Skild|Notion|Lovable|Vercel|Helsing|Supabase|Mistral|Prometheus|Temporal|Shield AI|Lambda|Safe Superintelligence|Fluidstack|Harvey|Instinct|Saronic|Nscale|Zipline|OpenEvidence|Legora|Atoms|Replit|Handshake|VAST Data|Cyera|Cohere|TypeSafe AI|Rippling|Skydio|Figure|Abnormal AI|Etched|Higgsfield|Wayve|Abridge|Grafana|Decagon|Turbopuffer|Suno|Exa|Cribl|Fractile|EliseAI|Positron AI|Runway AI|MatX|Wonderful|Factory|DensityAI|Glean|Halter|Arena|Parallel|LangChain|Granola|Black Forest Labs|Rogo|Profound|Gamma|Generalist|Periodic Labs|Flapping Airplanes|Chai Discovery|DriveNets|Upwind|Mind Robotics|n8n|EvenUp|Applied Compute|Synthesia|Serval|Render|Clay|Bedrock Robotics|Simile""".split("|")
extra={"Fireworks":["fireworksai"],"Fal":["fal","falai"],"Thinking Machines Lab":["thinkingmachines"],"Together AI":["togetherai"],"Physical Intelligence":["physicalintelligence","pi"],"Reflection":["reflectionai","reflection"],"Skild":["skildai","skild"],"Safe Superintelligence":["ssi","safesuperintelligence"],"Shield AI":["shieldai"],"VAST Data":["vastdata"],"Abnormal AI":["abnormalsecurity","abnormal"],"Runway AI":["runwayml","runway"],"Positron AI":["positron"],"Black Forest Labs":["blackforestlabs","bfl"],"Chai Discovery":["chaidiscovery","chai"],"Mind Robotics":["mindrobotics"],"Applied Compute":["appliedcompute"],"Bedrock Robotics":["bedrockrobotics"],"Isomorphic Labs":["isomorphiclabs"],"Applied Intuition":["appliedintuition"],"Periodic Labs":["periodiclabs"],"Flapping Airplanes":["flappingairplanes"],"TypeSafe AI":["typesafe"],"DensityAI":["densityai"],"Runway":["runway"],"Parallel":["parallel","parallelweb"],"Arena":["arena","lmarena"],"Factory":["factory","factoryai"],"Wonderful":["wonderful","wonderfulai"],"Instinct":["instinct"],"Atoms":["atoms"],"Generalist":["generalist","generalistai"],"Waymo":["waymo"],"Exa":["exa"],"Prometheus":["prometheus"],"Halter":["halter"],"Profound":["profound","tryprofound"],"Serval":["serval"],"Simile":["simile"],"Glean":["gleanwork","glean"],"Temporal":["temporal","temporaltechnologies"],"Figure":["figureai","figure"],"Clay":["claylabs","clay"],"Cohere":["cohere"],"Etched":["etched"],"Granola":["granola"],"EvenUp":["evenup","evenuplaw"],"Gamma":["gamma"],"Rogo":["rogo"],"Wayve":["wayve"],"Suno":["suno"],"Harvey":["harvey"],"Perplexity":["perplexity","perplexityai"],"Cognition":["cognition"],"Mercor":["mercor"],"Lovable":["lovable"],"Notion":["notion"],"Mistral":["mistral","mistralai"],"ElevenLabs":["elevenlabs"],"OpenEvidence":["openevidence"],"Decagon":["decagon","decagonai"],"Sierra":["sierra"],"n8n":["n8n"],"Helsing":["helsing"],"Saronic":["saronic"],"Nscale":["nscale"],"Fluidstack":["fluidstack"],"Higgsfield":["higgsfield","higgsfieldai"]}
def slugs(n):
    b=re.sub(r"[^a-z0-9]","",n.lower()); h=re.sub(r"[^a-z0-9]+","-",n.lower()).strip("-")
    out=extra.get(n,[])+[b,h]
    return list(dict.fromkeys(out))
S=requests.Session(); S.headers["User-Agent"]="job-radar"
def gh(s):
    r=S.get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs",timeout=15); return len(r.json().get("jobs",[])) if r.ok else None
def ashby(s):
    r=S.get(f"https://api.ashbyhq.com/posting-api/job-board/{s}",timeout=15)
    return len(r.json().get("jobs",[])) if r.ok and "jobs" in r.text else None
def lever(s):
    r=S.get(f"https://api.lever.co/v0/postings/{s}?mode=json",timeout=15)
    try: j=r.json(); return len(j) if r.ok and isinstance(j,list) else None
    except Exception: return None
def resolve(n):
    best=None
    for s in slugs(n):
        for kind,f in (("greenhouse",gh),("ashby",ashby),("lever",lever)):
            try: c=f(s)
            except Exception: c=None
            if c: 
                if not best or c>best[2]: best=(kind,s,c)
        if best: return n,best
    return n,None
with cf.ThreadPoolExecutor(12) as ex: res=list(ex.map(resolve,names))
json.dump({n:b for n,b in res},open("data/ai100-resolved.json","w"),indent=1)
for n,b in res: print(f"{n:24} {b}")
print(sum(1 for _,b in res if b),"resolved of",len(res))
