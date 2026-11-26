"""
Product Catalog - Background Worker Service ("Workers: Background jobs")
Consumes asynchronous jobs from Message Queue: dispatches SMTP/sandbox emails,
runs scheduled database snapshots, and performs housekeeping tasks off the HTTP thread.
"""
import smtplib
import logging
import threading
import time
from email.message import EmailMessage
from config import Config
from services import queue_service, backup_service

logger = logging.getLogger("product_catalog.worker")

_WORKER_THREAD = None
_STOP_EVENT = threading.Event()


def _send_email(recipient: str, subject: str, body_text: str, job_id: int = None, mask_body_in_outbox: str = None):
    """
    Sends email via configured Domain SMTP TLS server when credentials exist,
    or safely delivers into server-side worker outbox log when SMTP is unconfigured locally.
    """
    preview = mask_body_in_outbox if mask_body_in_outbox is not None else body_text

    if Config.MAIL_PASSWORD and Config.MAIL_SERVER and Config.MAIL_USERNAME:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = Config.MAIL_DEFAULT_SENDER
            msg["To"] = recipient
            msg.set_content(body_text)

            with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT, timeout=15) as server:
                if Config.MAIL_USE_TLS:
                    server.starttls()
                server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
                server.send_message(msg)

            queue_service.record_outbox_email(recipient, subject, preview, "smtp_tls", "sent", job_id)
            logger.info(f"[WORKER] Sent SMTP email job #{job_id}: {subject}")
            return True
        except Exception as exc:
            logger.error(f"[WORKER] SMTP send error for job #{job_id}: {exc}")
            raise

    # Local dev / no SMTP password configured: safely record server-side delivery without logging PII
    logger.info(f"[WORKER SANDBOX EMAIL] job_id={job_id} | Subject={subject}")
    queue_service.record_outbox_email(recipient, subject, preview, "worker_sandbox", "delivered_sandbox", job_id)
    return True


def _execute_job(job: dict):
    job_id = job["id"]
    job_type = job["job_type"]
    payload = job["payload"]

    if job_type == "email.verification":
        recipient = payload["email"]
        username = payload.get("username", "User")
        code = payload["code"]
        body = (
            f"Hello {username},\n\n"
            f"Your Product Catalog email verification code is: {code}\n"
            f"This code expires in 15 minutes.\n\n"
            f"If you did not register on Product Catalog, ignore this message.\n"
        )
        # Never store the raw OTP code or full email body in unmasked preview logs
        safe_preview = f"Verification email dispatched for job #{job_id} (valid 15 min)."
        logger.info(f"[EMAIL WORKER] Dispatched verification job #{job_id}")
        _send_email(recipient, "Verify Your Product Catalog Email", body, job_id=job_id, mask_body_in_outbox=safe_preview)

    elif job_type == "email.order_receipt":
        recipient = payload["customer_email"]
        order_number = payload["order_number"]
        product_name = payload["product_name"]
        amount = payload["amount"]
        body = (
            f"Thank you for your order!\n\n"
            f"Order Reference: {order_number}\n"
            f"Item: {product_name}\n"
            f"Total Charged: {amount}\n"
            f"Status: Confirmed\n\n"
            f"Support: {Config.DOMAIN_EMAIL}\n"
        )
        safe_preview = f"Order receipt {order_number} ({product_name}, {amount}) sent to {recipient}."
        _send_email(recipient, f"Order Receipt #{order_number} - Product Catalog", body, job_id=job_id, mask_body_in_outbox=safe_preview)

    elif job_type == "email.contact_ack":
        recipient = payload["email"]
        ref_code = payload["reference_code"]
        name = payload.get("name", "Customer")
        body = (
            f"Hello {name},\n\n"
            f"We received your inquiry ({ref_code}). Our team will reply via {Config.DOMAIN_EMAIL}.\n"
        )
        _send_email(
            recipient,
            f"Inquiry Received [{ref_code}] - Product Catalog",
            body,
            job_id=job_id,
            mask_body_in_outbox=f"Inquiry acknowledgment {ref_code} sent to {recipient}."
        )

    elif job_type == "backup.scheduled":
        label = payload.get("label", "scheduled")
        res = backup_service.create_backup(label=label)
        if not res.get("success"):
            raise RuntimeError(res.get("message", "Scheduled backup failed"))

    else:
        logger.warning(f"[WORKER] Unknown job type skipped: {job_type}")


def process_pending_once(max_jobs: int = 20) -> int:
    """Processes up to max_jobs pending jobs synchronously. Returns count completed."""
    processed = 0
    while processed < max_jobs:
        job = queue_service.claim_next_pending_job()
        if not job:
            break
        try:
            _execute_job(job)
            queue_service.mark_job_completed(job["id"])
            processed += 1
        except Exception as exc:
            logger.error(f"[WORKER] Job #{job['id']} failed: {exc}")
            queue_service.mark_job_failed(job["id"], str(exc))
    return processed


def _worker_loop():
    logger.info("Background Worker Pool started.")
    last_backup_ts = 0.0
    while not _STOP_EVENT.is_set():
        try:
            process_pending_once(max_jobs=10)
            # Trigger automatic daily safety backup every 24h while server runs
            now = time.time()
            if now - last_backup_ts > 86400:
                backups = backup_service.list_backups()
                if not backups:
                    backup_service.create_backup(label="auto")
                last_backup_ts = now
        except Exception as exc:
            logger.error(f"Worker loop error: {exc}")
        _STOP_EVENT.wait(2.0)


def start_background_worker():
    """Starts singleton background worker daemon if not already running."""
    global _WORKER_THREAD
    if _WORKER_THREAD and _WORKER_THREAD.is_alive():
        return
    _STOP_EVENT.clear()
    _WORKER_THREAD = threading.Thread(target=_worker_loop, name="CatalogJobWorker", daemon=True)
    _WORKER_THREAD.start()
