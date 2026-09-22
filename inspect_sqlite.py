import sqlite3, json

conn = sqlite3.connect(r'C:\Users\lenovo\.codex\thread_history_1.sqlite')
cur = conn.cursor()

print("=== latest turns ===")
cur.execute("SELECT thread_id, turn_id, status, started_at, completed_at FROM thread_turns ORDER BY started_at DESC LIMIT 5")
for r in cur.fetchall():
    print(r)

print("\n=== latest items ===")
cur.execute("SELECT thread_id, item_type, created_at_ms, substr(item_json,1,300) FROM thread_items ORDER BY created_at_ms DESC LIMIT 6")
for r in cur.fetchall():
    print(r)
