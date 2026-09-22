import sqlite3, json

conn = sqlite3.connect(r'C:\Users\lenovo\.codex\thread_history_1.sqlite')
cur = conn.cursor()
tid = '01a0a9dc-5b8d-7aa0-ab59-d0504031d271'
cur.execute("SELECT item_type, created_at_ms, item_json FROM thread_items WHERE thread_id=? ORDER BY created_at_ms ASC LIMIT 30", (tid,))
rows = cur.fetchall()
for r in rows:
    try:
        j = json.loads(r[2])
        t = j.get('type')
        if t == 'agentMessage':
            print(f"[{r[1]}] AGENT: {j.get('text','')[:200]}")
        elif t == 'userMessage':
            print(f"[{r[1]}] USER: {str(j.get('content',''))[:200]}")
        else:
            print(f"[{r[1]}] {t}: {str(j)[:120]}")
    except Exception as e:
        print(r[0], 'ERR', e)
conn.close()
