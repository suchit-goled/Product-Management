"""
Product Catalog - Database Backup & Disaster Recovery Service
Provides scheduled and on-demand ACID snapshots using sqlite3.backup,
path traversal protection, and cache invalidation after restore.
"""
import os
import sqlite3
import datetime
import logging
from config import Config
from services import cache_service, security_service

logger = logging.getLogger("product_catalog.backup")

BACKUP_DIR = Config.BACKUP_FOLDER
os.makedirs(BACKUP_DIR, exist_ok=True)


def create_backup(label: str = "manual") -> dict:
    """Creates a consistent SQLite online backup snapshot using sqlite3.backup API."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    safe_label = "".join(c for c in label if c.isalnum() or c in ("_", "-"))[:24] or "manual"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"catalog_backup_{safe_label}_{timestamp}.db"
    dest_path = os.path.join(BACKUP_DIR, filename)

    try:
        source_conn = sqlite3.connect(Config.DATABASE)
        dest_conn = sqlite3.connect(dest_path)

        with dest_conn:
            source_conn.backup(dest_conn)

        dest_conn.close()
        source_conn.close()

        file_size = os.path.getsize(dest_path)
        check_conn = sqlite3.connect(dest_path)
        product_count = check_conn.cursor().execute("SELECT count(*) FROM products").fetchone()[0]
        check_conn.close()

        logger.info(f"Database backup created: {filename} ({file_size} bytes, {product_count} products)")

        return {
            "success": True,
            "filename": filename,
            "size_bytes": file_size,
            "size_formatted": f"{file_size / 1024:.1f} KB" if file_size < 1024 * 1024 else f"{file_size / (1024 * 1024):.2f} MB",
            "product_count": product_count,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": f"Backup {filename} generated successfully"
        }
    except Exception as e:
        logger.error(f"Backup creation failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to create backup: {str(e)}"
        }


def list_backups() -> list:
    """Returns metadata for existing snapshots inside BACKUP_DIR."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = []

    for fname in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if fname.endswith(".db"):
            ok, fpath = security_service.is_safe_contained_path(BACKUP_DIR, fname)
            if not ok or not os.path.isfile(fpath):
                continue
            size = os.path.getsize(fpath)
            mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M:%S")

            prod_count = 0
            try:
                c = sqlite3.connect(fpath)
                prod_count = c.cursor().execute("SELECT count(*) FROM products").fetchone()[0]
                c.close()
            except Exception:
                pass

            backups.append({
                "filename": fname,
                "size_bytes": size,
                "size_formatted": f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.2f} MB",
                "created_at": mod_time,
                "product_count": prod_count
            })

    return backups


def restore_backup(filename: str) -> dict:
    """Restores DB safely with path containment, pre-restore snapshot, and cache flush."""
    ok, source_path = security_service.is_safe_contained_path(BACKUP_DIR, filename)
    clean_filename = os.path.basename(filename or "")

    if not ok or not clean_filename.endswith(".db") or not os.path.exists(source_path):
        return {"success": False, "message": f"Snapshot file {clean_filename} not found"}

    try:
        # Verify backup integrity before overwriting source of truth
        test_conn = sqlite3.connect(source_path)
        integrity = test_conn.execute("PRAGMA integrity_check;").fetchone()[0]
        test_conn.close()
        if integrity != "ok":
            return {"success": False, "message": "Backup integrity check failed; restore aborted"}

        pre_backup = create_backup(label="pre_restore_safety")

        src_conn = sqlite3.connect(source_path)
        dest_conn = sqlite3.connect(Config.DATABASE)
        with dest_conn:
            src_conn.backup(dest_conn)
        dest_conn.close()
        src_conn.close()

        # Invalidate entire Cache layer after restore
        cache_service.cache_invalidate_prefix("catalog:")
        logger.info(f"Database successfully restored from snapshot {clean_filename}")
        return {
            "success": True,
            "restored_from": clean_filename,
            "safety_backup": pre_backup.get("filename"),
            "message": f"Database successfully restored from {clean_filename}"
        }
    except Exception as e:
        logger.error(f"Restore failed: {e}", exc_info=True)
        return {"success": False, "message": f"Restore failed: {str(e)}"}
