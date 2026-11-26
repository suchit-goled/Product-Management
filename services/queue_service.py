"""
Product Catalog - Persistent Message Queue Layer ("Message queue: Async jobs, emails")
Stores asynchronous background jobs (verification emails, order receipts, contact
acknowledgments, scheduled backups) cleanly in SQLite so workers process them safely.
"""
import json
import sqlite3
import logging
import threading
from datetime import datetime
from config import Config

logger = logging.getLogger("product_catalog.queue")
_QLOCK = threading.RLock()


def _get_conn():
    conn = sqlite3.connect(Config.DATABASE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_queue_tables():
    """Initializes persistent message queue and email outbox tables."""
    with _QLOCK:
        conn = _get_conn()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            last_error TEXT,
            created_at TEXT NOT NULL,
            processed_at TEXT
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON job_queue(status, id);")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS email_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body_preview TEXT NOT NULL,
            job_id INTEGER,
            delivery_mode TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        conn.commit()
        conn.close()


def enqueue_job(job_type: str, payload: dict, max_attempts: int = 3) -> int:
    """Enqueues an async job onto the persistent Message Queue."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    serialized = json.dumps(payload, ensure_ascii=False)
    with _QLOCK:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO job_queue (job_type, payload_json, status, attempts, max_attempts, created_at)
        VALUES (?, ?, 'pending', 0, ?, ?)
        """, (job_type, serialized, max_attempts, now_str))
        job_id = cur.lastrowid
        conn.commit()
        conn.close()
    logger.info(f"Enqueued async job #{job_id}: {job_type}")
    return job_id


def claim_next_pending_job():
    """Atomically claims one pending job for worker execution."""
    with _QLOCK:
        conn = _get_conn()
        cur = conn.cursor()
        row = cur.execute("""
        SELECT * FROM job_queue
        WHERE status = 'pending' AND attempts < max_attempts
        ORDER BY id ASC LIMIT 1
        """).fetchone()

        if not row:
            conn.close()
            return None

        cur.execute("""
        UPDATE job_queue
        SET status = 'processing', attempts = attempts + 1
        WHERE id = ? AND status = 'pending'
        """, (row["id"],))
        conn.commit()
        updated = cur.execute("SELECT * FROM job_queue WHERE id = ?", (row["id"],)).fetchone()
        conn.close()

        if updated:
            job = dict(updated)
            job["payload"] = json.loads(job["payload_json"])
            return job
        return None


def mark_job_completed(job_id: int):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _QLOCK:
        conn = _get_conn()
        conn.execute(
            "UPDATE job_queue SET status = 'completed', processed_at = ?, last_error = NULL WHERE id = ?",
            (now_str, job_id)
        )
        conn.commit()
        conn.close()


def mark_job_failed(job_id: int, error_msg: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _QLOCK:
        conn = _get_conn()
        row = conn.execute("SELECT attempts, max_attempts FROM job_queue WHERE id = ?", (job_id,)).fetchone()
        next_status = "pending" if (row and row["attempts"] < row["max_attempts"]) else "failed"
        conn.execute(
            "UPDATE job_queue SET status = ?, last_error = ?, processed_at = ? WHERE id = ?",
            (next_status, str(error_msg)[:500], now_str, job_id)
        )
        conn.commit()
        conn.close()


def record_outbox_email(recipient: str, subject: str, body_preview: str, delivery_mode: str, status: str, job_id: int = None):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _QLOCK:
        conn = _get_conn()
        conn.execute("""
        INSERT INTO email_outbox (recipient, subject, body_preview, job_id, delivery_mode, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (recipient, subject, body_preview[:1000], job_id, delivery_mode, status, now_str))
        conn.commit()
        conn.close()


def get_queue_metrics() -> dict:
    with _QLOCK:
        conn = _get_conn()
        pending = conn.execute("SELECT count(*) FROM job_queue WHERE status = 'pending'").fetchone()[0]
        processing = conn.execute("SELECT count(*) FROM job_queue WHERE status = 'processing'").fetchone()[0]
        completed = conn.execute("SELECT count(*) FROM job_queue WHERE status = 'completed'").fetchone()[0]
        failed = conn.execute("SELECT count(*) FROM job_queue WHERE status = 'failed'").fetchone()[0]
        outbox_count = conn.execute("SELECT count(*) FROM email_outbox").fetchone()[0]
        conn.close()
    return {
        "pending": pending,
        "processing": processing,
        "completed": completed,
        "failed": failed,
        "outbox_total": outbox_count
    }


def get_recent_outbox(limit: int = 25) -> list:
    with _QLOCK:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM email_outbox ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
    return [dict(r) for r in rows]


def get_recent_outbox_summary(limit: int = 25) -> list:
    """Returns redacted delivery status logs without exposing customer emails or bodies to frontend."""
    with _QLOCK:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, delivery_mode, status, created_at FROM email_outbox ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
    return [
        {
            "event_id": f"MSG-{r['id']:04d}",
            "delivery_mode": r["delivery_mode"],
            "status": r["status"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
