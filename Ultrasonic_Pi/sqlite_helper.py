import sqlite3, os, time

RETRY_BATCH_SIZE = 10

DB_PATH = os.path.join(os.path.dirname(__file__), "lora_cache.db")

def init_db():
    """Create local SQLite cache for pending LoRa messages."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_messages (
            msg_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

# def cache_message(msg_id, payload):
#     """Store outgoing message before trying to send it."""
#     conn = sqlite3.connect(DB_PATH)
#     cur = conn.cursor()
#     cur.execute("""
#         INSERT OR IGNORE INTO pending_messages (msg_id, created_at, payload)
#         VALUES (?, ?, ?)
#     """, (msg_id, time.time(), payload))
#     conn.commit()
#     conn.close()
def cache_message(msg_id, payload):
    """Keep only the latest pending message."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DELETE FROM pending_messages")

    cur.execute("""
        INSERT INTO pending_messages (msg_id, created_at, payload)
        VALUES (?, ?, ?)
    """, (msg_id, time.time(), payload))

    conn.commit()
    conn.close()
# def get_pending_messages(limit=RETRY_BATCH_SIZE):
#     """Read oldest unsent messages first (FIFO retransmission)."""
#     conn = sqlite3.connect(DB_PATH)
#     cur = conn.cursor()
#     cur.execute("""
#         SELECT msg_id, payload
#         FROM pending_messages
#         ORDER BY created_at ASC
#         LIMIT ?
#     """, (limit,))
#     rows = cur.fetchall()
#     conn.close()
#     return rows
def get_one_pending_message():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT msg_id, payload
        FROM pending_messages
        ORDER BY created_at DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    return row

def delete_cached_message(msg_id):
    """Remove message from cache only after successful send."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM pending_messages WHERE msg_id = ?", (msg_id,))
    conn.commit()
    conn.close()


def count_pending_messages():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM pending_messages")
    count = cur.fetchone()[0]
    conn.close()
    return count