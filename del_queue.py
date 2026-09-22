import sqlite3

conn = sqlite3.connect(r'C:\Users\lenovo\.codex\queue_1.sqlite')
cur = conn.cursor()
cur.execute("DELETE FROM queued_items WHERE id='01a0ad25-947b-7b51-9b7f-488946de0b87'")
conn.commit()
print('deleted:', cur.rowcount)
cur.execute("SELECT id, thread_id FROM queued_items")
print('remaining:', cur.fetchall())
conn.close()
