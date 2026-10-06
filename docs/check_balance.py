import json, urllib.request
key=None
for line in open(r"D:\deepsearch\.env",encoding="utf-8"):
    if line.startswith("DEEPSEEK_API_KEY="):
        key=line.split("=",1)[1].strip().strip('"').strip("'")
def test(model):
    body=json.dumps({"model":model,"messages":[{"role":"user","content":"hi"}],"max_tokens":1}).encode()
    req=urllib.request.Request("https://api.deepseek.com/chat/completions",data=body,
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=40) as r:
            print(model,"OK",r.status)
    except urllib.error.HTTPError as e:
        print(model,"HTTP",e.code,e.read().decode()[:200])
    except Exception as e:
        print(model,"ERR",e)
test("deepseek-flash")
test("deepseek-v4-pro")
