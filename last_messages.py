import sqlite3, json

conn = sqlite3.connect(r'C:\Users\lenovo\.codex\thread_history_1.sqlite')
cur = conn.cursor()
cur.execute("SELECT item_type, created_at_ms, item_json FROM thread_items WHERE thread_id='01a0acff-dd2b-7792-bbb9-0cbdac1e508b' ORDER BY created_at_ms DESC LIMIT 8")
for r in cur.fetchall():
    j = json.loads(r[2])
    t = j.get('type')
    if t == 'agentMessage':
        print(f"[{r[1]}] AGENT:\n{j.get('text','')}\n---")
    else:
        print(f"[{r[1]}] {t}")
conn.close()
