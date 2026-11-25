"""
Suchit Catalog - Cache & Stateless Session Layer ("Cache: Hot reads, sessions")
Provides a thread-safe L1 memory cache backed by SQLite persistence so hot catalog
queries, rate-limiting counters, and opaque server-side sessions remain fast and stateless.
"""
import json
import time
import hmac
import hashlib
import secrets
import sqlite3
import logging
import threading
from datetime import datetime, timedelta
from config import Config

logger = logging.getLogger("suchit.cache")

_LOCK = threading.RLock()
_MEMORY_CACHE = {}  # key -> (expires_at_epoch, value)


def _get_conn():
    conn = sqlite3.connect(Config.DATABASE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_cache_tables():
    """Creates distributed cache, session store, and sliding-window rate limit tables."""
    with _LOCK:
        conn = _get_conn()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS app_cache (
            cache_key TEXT PRIMARY KEY,
            cache_value TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_app_cache_exp ON app_cache(expires_at);")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            csrf_token TEXT NOT NULL,
            ip_fingerprint TEXT,
            ua_fingerprint TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            expires_at REAL NOT NULL,
            revoked INTEGER DEFAULT 0
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_exp ON user_sessions(expires_at);")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            bucket_key TEXT PRIMARY KEY,
            hits INTEGER NOT NULL DEFAULT 0,
            window_start REAL NOT NULL
        )
        """)

        conn.commit()
        conn.close()


# ==============================================================================
# HOT-READ CACHE (Catalog Lists, Stats)
# ==============================================================================

def cache_get(key: str):
    """Returns cached object from L1 memory or L2 SQLite cache, or None if expired."""
    now = time.time()
    with _LOCK:
        item = _MEMORY_CACHE.get(key)
        if item:
            exp, val = item
            if exp > now:
                return val
            del _MEMORY_CACHE[key]

        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT cache_value, expires_at FROM app_cache WHERE cache_key = ?",
                (key,)
            ).fetchone()
            conn.close()
            if row and row["expires_at"] > now:
                val = json.loads(row["cache_value"])
                _MEMORY_CACHE[key] = (row["expires_at"], val)
                return val
        except Exception as exc:
            logger.debug(f"Cache read skipped for {key}: {exc}")
    return None


def cache_set(key: str, value, ttl_seconds: int = None):
    """Stores JSON-serializable object into L1 + L2 cache with explicit TTL."""
    ttl = ttl_seconds if ttl_seconds is not None else Config.CATALOG_CACHE_TTL_SECONDS
    expires_at = time.time() + max(1, int(ttl))
    with _LOCK:
        _MEMORY_CACHE[key] = (expires_at, value)
        try:
            serialized = json.dumps(value, ensure_ascii=False)
            conn = _get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO app_cache (cache_key, cache_value, expires_at) VALUES (?, ?, ?)",
                (key, serialized, expires_at)
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug(f"Cache write fallback for {key}: {exc}")


def cache_invalidate_prefix(prefix: str):
    """Invalidates all cache keys sharing a prefix on data mutation."""
    with _LOCK:
        for k in list(_MEMORY_CACHE.keys()):
            if k.startswith(prefix):
                del _MEMORY_CACHE[k]
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM app_cache WHERE cache_key LIKE ?", (f"{prefix}%",))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug(f"Cache invalidate skipped for {prefix}: {exc}")


# ==============================================================================
# OPAQUE SERVER-SIDE SESSIONS (Zero Client Cookie Claims)
# ==============================================================================

def _hash_token(raw_token: str) -> str:
    return hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def _fingerprint(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def create_server_session(user_id: int, role: str, client_ip: str = "", user_agent: str = "", ttl_seconds: int = None) -> tuple:
    """
    Issues a high-entropy CSPRNG opaque session token + per-session CSRF token.
    Only the opaque session ID goes in the HttpOnly cookie; user_id & role stay server-side.
    Returns (raw_session_token, csrf_token).
    """
    ttl = ttl_seconds if ttl_seconds is not None else Config.PERMANENT_SESSION_LIFETIME
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    now_epoch = time.time()
    expires_at = now_epoch + ttl
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _LOCK:
        conn = _get_conn()
        # Clean up expired sessions opportunistically
        conn.execute("DELETE FROM user_sessions WHERE expires_at < ? OR revoked = 1", (now_epoch,))
        conn.execute("""
        INSERT INTO user_sessions (
            token_hash, user_id, role, csrf_token, ip_fingerprint, ua_fingerprint,
            created_at, last_seen_at, expires_at, revoked
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            token_hash, user_id, role, csrf_token,
            _fingerprint(client_ip), _fingerprint(user_agent),
            now_str, now_str, expires_at
        ))
        conn.commit()
        conn.close()

        cache_set(f"sid:{token_hash}", {
            "user_id": user_id,
            "role": role,
            "csrf_token": csrf_token,
            "ua_fingerprint": _fingerprint(user_agent),
            "expires_at": expires_at
        }, ttl_seconds=min(ttl, 300))

    return raw_token, csrf_token


def get_server_session(raw_token: str, user_agent: str = ""):
    """
    Validates opaque session token against Cache + Database.
    Returns dict {user_id, role, csrf_token} or None if missing/expired/revoked.
    """
    if not raw_token or len(raw_token) < 20:
        return None

    token_hash = _hash_token(raw_token)
    now_epoch = time.time()

    with _LOCK:
        cached = cache_get(f"sid:{token_hash}")
        if cached and cached.get("expires_at", 0) > now_epoch:
            # Verify optional User-Agent binding if present on session
            stored_ua = cached.get("ua_fingerprint", "")
            if stored_ua and user_agent and _fingerprint(user_agent) != stored_ua:
                logger.warning("Session User-Agent mismatch rejected")
                return None
            return cached

        conn = _get_conn()
        row = conn.execute("""
        SELECT s.user_id, u.role, s.csrf_token, s.ua_fingerprint, s.expires_at, s.revoked
        FROM user_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ?
        """, (token_hash,)).fetchone()
        conn.close()

        if not row or row["revoked"] or row["expires_at"] <= now_epoch:
            return None

        if row["ua_fingerprint"] and user_agent and _fingerprint(user_agent) != row["ua_fingerprint"]:
            logger.warning("Session User-Agent mismatch rejected from DB check")
            return None

        session_data = {
            "user_id": row["user_id"],
            "role": row["role"],  # Authoritative live role from users table!
            "csrf_token": row["csrf_token"],
            "ua_fingerprint": row["ua_fingerprint"],
            "expires_at": row["expires_at"]
        }
        cache_set(f"sid:{token_hash}", session_data, ttl_seconds=300)
        return session_data


def revoke_server_session(raw_token: str):
    """Immediately revokes session token in Cache + Database."""
    if not raw_token:
        return
    token_hash = _hash_token(raw_token)
    with _LOCK:
        cache_invalidate_prefix(f"sid:{token_hash}")
        try:
            conn = _get_conn()
            conn.execute("UPDATE user_sessions SET revoked = 1 WHERE token_hash = ?", (token_hash,))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug(f"Session revoke failed: {exc}")


def revoke_all_user_sessions(user_id: int):
    """Revokes every session belonging to a user (e.g., on password/role change)."""
    with _LOCK:
        cache_invalidate_prefix("sid:")
        try:
            conn = _get_conn()
            conn.execute("UPDATE user_sessions SET revoked = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug(f"Bulk session revoke failed: {exc}")


# ==============================================================================
# SLIDING WINDOW RATE LIMITER
# ==============================================================================

def check_rate_limit(bucket_key: str, max_requests: int, window_seconds: int) -> tuple:
    """
    Thread-safe rate limiting algorithm stored in persistent rate_limits table.
    Returns (allowed: bool, remaining: int, retry_after_seconds: int).
    """
    now = time.time()
    with _LOCK:
        conn = _get_conn()
        row = conn.execute(
            "SELECT hits, window_start FROM rate_limits WHERE bucket_key = ?",
            (bucket_key,)
        ).fetchone()

        if not row or (now - row["window_start"]) >= window_seconds:
            conn.execute(
                "INSERT OR REPLACE INTO rate_limits (bucket_key, hits, window_start) VALUES (?, 1, ?)",
                (bucket_key, now)
            )
            conn.commit()
            conn.close()
            return True, max(0, max_requests - 1), 0

        hits = row["hits"] + 1
        if hits > max_requests:
            retry_after = max(1, int(window_seconds - (now - row["window_start"])))
            conn.close()
            return False, 0, retry_after

        conn.execute(
            "UPDATE rate_limits SET hits = ? WHERE bucket_key = ?",
            (hits, bucket_key)
        )
        conn.commit()
        conn.close()
        return True, max(0, max_requests - hits), 0


def reset_rate_limit(bucket_key: str):
    """Clears rate limit bucket (e.g., after successful login)."""
    with _LOCK:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM rate_limits WHERE bucket_key = ?", (bucket_key,))
            conn.commit()
            conn.close()
        except Exception:
            pass
