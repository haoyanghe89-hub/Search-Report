import sqlite3

conn = sqlite3.connect(r'C:\Users\lenovo\.codex\queue_1.sqlite')
cur = conn.cursor()
cur.execute("DELETE FROM queued_items WHERE id='01a0aa99-a31c-76a3-8eb0-2ac1f2c528ca'")
print('deleted items:', cur.rowcount)
cur.execute("DELETE FROM queued_thread_revisions WHERE thread_id='01a0a5ac-9715-75a2-8906-3bd5096d0477'")
print('deleted revisions:', cur.rowcount)
conn.commit()
cur.execute("SELECT id, thread_id FROM queued_items")
print('remaining:', cur.fetchall())
conn.close()
