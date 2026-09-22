import sqlite3

conn = sqlite3.connect(r'C:\Users\lenovo\.codex\queue_1.sqlite')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print('tables:', tables)
for t in tables:
    try:
        cur.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 5")
        rows = cur.fetchall()
        print(f'\n=== {t} (latest {len(rows)}) ===')
        for r in rows:
            print(str(r)[:400])
    except Exception as e:
        print(t, 'ERR', e)
