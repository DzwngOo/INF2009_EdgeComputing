import sqlite3, os, time
DB_PATH = os.path.join(os.path.dirname(__file__), "lora_cache.db")

# =========================
# SQLite helper functions
# =========================
def init_db():
    """Create a table that stores only the latest unsent LoRa message."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_state (
            cache_key TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def cache_latest_message(payload):
    """
    Store only the latest unsent state.
    If a cached message already exists, overwrite it.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pending_state (cache_key, created_at, payload)
        VALUES ('latest', ?, ?)
        ON CONFLICT(cache_key)
        DO UPDATE SET
            created_at = excluded.created_at,
            payload = excluded.payload
    """, (time.time(), payload))
    conn.commit()
    conn.close()
    print("[SQLITE] Cached latest message.")


def get_cached_message():
    """Return the latest cached message if it exists."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT payload
        FROM pending_state
        WHERE cache_key = 'latest'
    """)
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def clear_cached_message():
    """Remove cached message after successful resend."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM pending_state WHERE cache_key = 'latest'")
    conn.commit()
    conn.close()
    print("[SQLITE] Cleared cached message.")