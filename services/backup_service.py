"""
Suchit Catalog - Database Backup & Disaster Recovery Service
Provides scheduled and on-demand snapshots of SQLite catalog data,
integrity checks, and safe restore operations.
"""
import os
import shutil
import sqlite3
import datetime
import logging
from config import Config

logger = logging.getLogger(__name__)

BACKUP_DIR = Config.BACKUP_FOLDER
os.makedirs(BACKUP_DIR, exist_ok=True)


def create_backup(label: str = "manual") -> dict:
    """
    Creates a consistent SQLite online backup snapshot using the sqlite3 backup API.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"suchit_backup_{label}_{timestamp}.db"
    dest_path = os.path.join(BACKUP_DIR, filename)

    try:
        # Use sqlite3 online backup API to ensure ACID consistency without locking
        source_conn = sqlite3.connect(Config.DATABASE)
        dest_conn = sqlite3.connect(dest_path)

        with dest_conn:
            source_conn.backup(dest_conn)

        dest_conn.close()
        source_conn.close()

        file_size = os.path.getsize(dest_path)

        # Inspect row count in snapshot
        check_conn = sqlite3.connect(dest_path)
        cur = check_conn.cursor()
        cur.execute("SELECT count(*) FROM products")
        product_count = cur.fetchone()[0]
        check_conn.close()

        logger.info(f"Database backup created: {filename} ({file_size} bytes, {product_count} products)")

        return {
            "success": True,
            "filename": filename,
            "path": dest_path,
            "size_bytes": file_size,
            "size_formatted": f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.2f} MB",
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
    """Returns a list of all existing database snapshots with metadata."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = []

    for fname in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if fname.endswith(".db"):
            fpath = os.path.join(BACKUP_DIR, fname)
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
                "size_formatted": f"{size / 1024:.1f} KB" if size < 1024*1024 else f"{size / (1024*1024):.2f} MB",
                "created_at": mod_time,
                "product_count": prod_count
            })

    return backups


def restore_backup(filename: str) -> dict:
    """Restores database from specified snapshot after taking a pre-restore safety snapshot."""
    clean_filename = os.path.basename(filename)
    source_path = os.path.join(BACKUP_DIR, clean_filename)

    if not os.path.exists(source_path):
        return {"success": False, "message": f"Snapshot file {clean_filename} not found"}

    try:
        # Step 1: Create automatic safety snapshot of current state
        pre_backup = create_backup(label="pre_restore_safety")

        # Step 2: Restore from target
        src_conn = sqlite3.connect(source_path)
        dest_conn = sqlite3.connect(Config.DATABASE)

        with dest_conn:
            src_conn.backup(dest_conn)

        dest_conn.close()
        src_conn.close()

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
