import json, urllib.request
key=None
for line in open(r"D:\deepsearch\.env",encoding="utf-8"):
    if line.startswith("DEEPSEEK_API_KEY="):
        key=line.split("=",1)[1].strip().strip('"').strip("'")
req=urllib.request.Request("https://api.deepseek.com/models",headers={"Authorization":f"Bearer {key}"})
with urllib.request.urlopen(req,timeout=30) as r:
    data=json.loads(r.read().decode())
for m in data.get("data",[]):
    print(m.get("id"))
