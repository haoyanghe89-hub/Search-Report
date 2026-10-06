import os, time, json, urllib.request
# 从 .env 读取 key（不打印）
key=None
with open(r"D:\deepsearch\.env","r",encoding="utf-8") as f:
    for line in f:
        if line.startswith("DEEPSEEK_API_KEY="):
            key=line.split("=",1)[1].strip().strip('"').strip("'")
assert key, "no key"
url="https://api.deepseek.com/chat/completions"
body=json.dumps({"model":"deepseek-chat","messages":[{"role":"user","content":"ping, reply with: ok"}],"max_tokens":10,"stream":False}).encode()
for i in range(6):
    t=time.time()
    req=urllib.request.Request(url,data=body,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=60) as r:
            data=json.loads(r.read().decode())
            dt=time.time()-t
            print(f"#{i+1} HTTP {r.status} {dt:.2f}s content={data.get('choices',[{}])[0].get('message',{}).get('content','')!r} usage={data.get('usage',{}).get('total_tokens')}")
    except urllib.error.HTTPError as e:
        print(f"#{i+1} HTTPError {e.code} {time.time()-t:.2f}s {e.read().decode()[:200]}")
    except Exception as e:
        print(f"#{i+1} {type(e).__name__} {time.time()-t:.2f}s {e}")
    time.sleep(1.5)
