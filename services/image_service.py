"""
Suchit Catalog - Image Processing and Validation Service
Handles image validation, sanitization, EXIF orientation correction, resizing, and optimization.
"""
import os
import uuid
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename
import logging

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tiff'}
MAX_DIMENSION = 1920
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16 MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_and_save_image(file_storage, upload_folder):
    """
    Validates an uploaded image file, applies EXIF auto-rotation and dimension optimization,
    and saves it securely to the upload directory.
    
    Returns:
        tuple: (relative_url, absolute_path, metadata, error_message)
    """
    if not file_storage or file_storage.filename == '':
        return None, None, None, "No file provided"

    orig_filename = secure_filename(file_storage.filename)
    if not allowed_file(orig_filename):
        return None, None, None, f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

    os.makedirs(upload_folder, exist_ok=True)

    try:
        # Verify image content using PIL
        img = Image.open(file_storage.stream)
        img.verify()

        # Reopen after verify() because verify() invalidates the image instance
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)

        # Correct orientation based on EXIF tags (e.g. smartphone photos)
        try:
            img = ImageOps.exif_transpose(img)
        except Exception as e:
            logger.debug(f"EXIF transpose skipped: {e}")

        orig_w, orig_h = img.size
        orig_format = img.format or "JPEG"

        # Downscale gracefully if image is enormous
        if max(orig_w, orig_h) > MAX_DIMENSION:
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)

        # Generate unique collision-resistant filename
        unique_prefix = uuid.uuid4().hex[:10]
        ext = orig_filename.rsplit('.', 1)[1].lower() if '.' in orig_filename else 'jpg'
        if ext not in ALLOWED_EXTENSIONS:
            ext = 'jpg'
            
        save_filename = f"suchit_{unique_prefix}_{orig_filename}"
        if not save_filename.endswith(f".{ext}"):
            save_filename = f"{save_filename}.{ext}"

        save_path = os.path.join(upload_folder, save_filename)

        # Convert to RGB if saving RGBA/P to JPEG
        save_format = 'PNG' if ext in ('png', 'webp') else 'JPEG'
        if save_format == 'JPEG' and img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')

        img.save(save_path, format=save_format, quality=90, optimize=True)

        final_w, final_h = img.size
        file_size = os.path.getsize(save_path)

        metadata = {
            "filename": save_filename,
            "original_filename": orig_filename,
            "width": final_w,
            "height": final_h,
            "aspect_ratio": round(final_w / max(final_h, 1), 2),
            "format": save_format,
            "file_size_bytes": file_size,
            "file_size_formatted": f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.2f} MB"
        }

        # Flask static URL
        relative_url = f"/static/uploads/{save_filename}"

        return relative_url, save_path, metadata, None

    except Exception as e:
        logger.error(f"Image validation/processing failed: {e}", exc_info=True)
        return None, None, None, f"Image processing error: {str(e)}"
