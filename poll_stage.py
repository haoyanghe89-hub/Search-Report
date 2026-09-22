import sqlite3, json, time

THREAD = '01a0acff-dd2b-7792-bbb9-0cbdac1e508b'

def check():
    conn = sqlite3.connect(r'C:\Users\lenovo\.codex\queue_1.sqlite')
    cur = conn.cursor()
    cur.execute("SELECT id, thread_id FROM queued_items WHERE thread_id=?", (THREAD,))
    queued = cur.fetchall()
    conn.close()

    conn = sqlite3.connect(r'C:\Users\lenovo\.codex\thread_history_1.sqlite')
    cur = conn.cursor()
    cur.execute("SELECT turn_id, status, started_at, completed_at FROM thread_turns WHERE thread_id=? ORDER BY started_at DESC LIMIT 3", (THREAD,))
    turns = cur.fetchall()
    cur.execute("SELECT item_type, created_at_ms, item_json FROM thread_items WHERE thread_id=? ORDER BY created_at_ms DESC LIMIT 5", (THREAD,))
    items = []
    for r in cur.fetchall():
        try:
            j = json.loads(r[2])
            txt = j.get('text', '') if j.get('type') == 'agentMessage' else j.get('type', '')
            items.append((r[0], r[1], txt[:200]))
        except Exception:
            items.append((r[0], r[1], 'parse-err'))
    conn.close()
    return queued, turns, items

for i in range(12):
    queued, turns, items = check()
    print(f"--- poll {i+1} ---")
    print("queued:", queued)
    print("turns:", turns)
    if items:
        print("latest item:", items[0][0], items[0][1], items[0][2])
    if not queued and turns and turns[0][1] == 'completed':
        print("MESSAGE CONSUMED AND TURN COMPLETED")
        break
    time.sleep(15)
