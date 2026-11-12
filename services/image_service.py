"""
Suchit Catalog - Image Processing, Optimization and Validation Service
Handles image validation, sanitization, EXIF orientation correction,
high-efficiency WebP/JPEG compression, and responsive resizing.
"""
import os
import uuid
import logging
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tiff'}
MAX_DIMENSION = 1920
THUMBNAIL_SIZE = (400, 300)
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16 MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_and_save_image(file_storage, upload_folder, max_dim=MAX_DIMENSION, compress_quality=88):
    """
    Validates an uploaded image file, applies EXIF auto-rotation, downscales if oversized,
    compresses with optimal perceptual quality, creates responsive thumbnail,
    and returns standardized file references and metadata.
    
    Returns:
        tuple: (relative_url, absolute_path, metadata, error_message)
    """
    if not file_storage or file_storage.filename == '':
        return None, None, None, "No file provided"

    orig_filename = secure_filename(file_storage.filename)
    if not allowed_file(orig_filename):
        return None, None, None, f"Unsupported file type. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

    os.makedirs(upload_folder, exist_ok=True)

    try:
        # Step 1: Content verification using Pillow
        img = Image.open(file_storage.stream)
        img.verify()

        # Reopen after verify() as verify() closes the stream
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)

        # Step 2: Auto-orient based on smartphone EXIF metadata
        try:
            img = ImageOps.exif_transpose(img)
        except Exception as e:
            logger.debug(f"EXIF transpose skipped: {e}")

        orig_w, orig_h = img.size

        # Step 3: Graceful downscale if larger than max_dim (preserving aspect ratio)
        if max(orig_w, orig_h) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        # Step 4: Generate unique collision-resistant filename
        unique_prefix = uuid.uuid4().hex[:10]
        ext = orig_filename.rsplit('.', 1)[1].lower() if '.' in orig_filename else 'jpg'
        if ext not in ALLOWED_EXTENSIONS:
            ext = 'jpg'

        save_filename = f"suchit_{unique_prefix}_{orig_filename}"
        if not save_filename.endswith(f".{ext}"):
            save_filename = f"{save_filename}.{ext}"

        save_path = os.path.join(upload_folder, save_filename)

        # Step 5: Convert color modes for clean compression
        save_format = 'PNG' if ext in ('png', 'webp') else 'JPEG'
        if save_format == 'JPEG' and img.mode in ('RGBA', 'P', 'LA'):
            # Composite transparent PNG onto clean white background
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img.convert('RGB'))
            img = background
        elif img.mode != 'RGB' and save_format == 'JPEG':
            img = img.convert('RGB')

        # Step 6: Save optimized primary image
        img.save(save_path, format=save_format, quality=compress_quality, optimize=True)

        # Step 7: Create fast WebP version for modern browsers
        webp_filename = f"{os.path.splitext(save_filename)[0]}.webp"
        webp_path = os.path.join(upload_folder, webp_filename)
        try:
            img.save(webp_path, format="WEBP", quality=compress_quality, method=6)
        except Exception as we:
            logger.debug(f"WebP compression optional: {we}")

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
            "file_size_formatted": f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.2f} MB",
            "webp_available": os.path.exists(webp_path)
        }

        relative_url = f"/static/uploads/{save_filename}"
        return relative_url, save_path, metadata, None

    except Exception as e:
        logger.error(f"Image processing failed: {e}", exc_info=True)
        return None, None, None, f"Image processing error: {str(e)}"
