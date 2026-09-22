import sqlite3, json, time, sys

THREAD = '01a0acff-dd2b-7792-bbb9-0cbdac1e508b'
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 40
INTERVAL = int(sys.argv[2]) if len(sys.argv) > 2 else 20

def check():
    conn = sqlite3.connect(r'C:\Users\lenovo\.codex\queue_1.sqlite')
    cur = conn.cursor()
    cur.execute("SELECT id FROM queued_items WHERE thread_id=?", (THREAD,))
    queued = cur.fetchall()
    conn.close()

    conn = sqlite3.connect(r'C:\Users\lenovo\.codex\thread_history_1.sqlite')
    cur = conn.cursor()
    cur.execute("SELECT turn_id, status, started_at, completed_at FROM thread_turns WHERE thread_id=? ORDER BY started_at DESC LIMIT 2", (THREAD,))
    turns = cur.fetchall()
    cur.execute("SELECT item_type, created_at_ms, item_json FROM thread_items WHERE thread_id=? ORDER BY created_at_ms DESC LIMIT 4", (THREAD,))
    items = []
    for r in cur.fetchall():
        try:
            j = json.loads(r[2])
            if j.get('type') == 'agentMessage':
                txt = j.get('text', '')[:300]
            else:
                txt = j.get('type', '')
            items.append((r[0], r[1], txt))
        except Exception:
            items.append((r[0], r[1], 'parse-err'))
    conn.close()
    return queued, turns, items

last_turn = None
for i in range(ROUNDS):
    queued, turns, items = check()
    cur_turn = turns[0] if turns else None
    status = cur_turn[1] if cur_turn else 'none'
    print(f"[{i+1}/{ROUNDS}] queued={len(queued)} turn_status={status}", flush=True)
    if items and items[0][0] != last_turn:
        print(f"  latest: {items[0][0]} @{items[0][1]} {items[0][2]}", flush=True)
        last_turn = items[0][0]
    if cur_turn and status == 'completed':
        print("TURN COMPLETED", flush=True)
        break
    time.sleep(INTERVAL)
