import sqlite3, json

conn = sqlite3.connect(r'C:\Users\lenovo\.codex\queue_1.sqlite')
cur = conn.cursor()
cur.execute("SELECT id, thread_id, payload_json, created_at_ms FROM queued_items")
for r in cur.fetchall():
    try:
        j = json.loads(r[2])
        text = j.get('UserInput', {}).get('content', [{}])[0].get('text', '')
        print(f"id={r[0]} created={r[3]}")
        print(f"  text: {text[:150]}")
    except Exception as e:
        print(r[0], 'ERR', e, str(r[2])[:100])
conn.close()
