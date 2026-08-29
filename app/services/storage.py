"""File storage with two backends.

STORAGE_BACKEND=local  (default) — public images under app/static/uploads, private documents outside /static,
                        served by /files/private/<key> to the owner/CS.
STORAGE_BACKEND=s3     — any S3-compatible bucket (AWS S3, Cloudflare R2, Backblaze B2, MinIO) via boto3.
                        Public objects live under public/ and are addressed by S3_PUBLIC_BASE_URL; private
                        objects live under private/ and are served through short-lived presigned URLs.

Callers only ever deal with the returned URL (public) or storage key (private).
"""
import os
import uuid
from flask import current_app
from werkzeug.utils import secure_filename

PUBLIC_IMAGE_EXT = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
PRIVATE_DOC_EXT = {'pdf', 'jpg', 'jpeg', 'png', 'webp'}
CHAT_FILE_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'mp4', 'mov'}
PRESIGN_SECONDS = 15 * 60


def _ext(filename):
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''


def _is_real_image(stream):
    try:
        from PIL import Image
        pos = stream.tell()
        Image.open(stream).verify()
        stream.seek(pos)
        return True
    except Exception:
        try:
            stream.seek(0)
        except Exception:
            pass
        return False


def _new_name(prefix, ext):
    return f"{secure_filename(prefix)[:40] or 'file'}_{uuid.uuid4().hex[:12]}.{ext}"


def backend():
    return current_app.config.get('STORAGE_BACKEND', 'local')


# ---------------------------------------------------------------------------
# S3 helpers (boto3 is optional; only imported when the backend is selected)
# ---------------------------------------------------------------------------

def _s3_client():
    try:
        import boto3
    except ImportError as e:  # pragma: no cover
        raise RuntimeError('STORAGE_BACKEND=s3 requires boto3 (pip install boto3)') from e
    kw = {'region_name': current_app.config.get('S3_REGION') or None}
    if current_app.config.get('S3_ENDPOINT_URL'):
        kw['endpoint_url'] = current_app.config['S3_ENDPOINT_URL']
    if current_app.config.get('S3_ACCESS_KEY_ID'):
        kw['aws_access_key_id'] = current_app.config['S3_ACCESS_KEY_ID']
        kw['aws_secret_access_key'] = current_app.config.get('S3_SECRET_ACCESS_KEY')
    return boto3.client('s3', **kw)


def _s3_put(key, fileobj, content_type=None):
    extra = {'ContentType': content_type} if content_type else {}
    _s3_client().upload_fileobj(fileobj, current_app.config['S3_BUCKET'], key, ExtraArgs=extra or None)


def _content_type(ext):
    return {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif',
            'webp': 'image/webp', 'pdf': 'application/pdf', 'mp4': 'video/mp4', 'mov': 'video/quicktime'}.get(ext)


def _public_url(name):
    base = (current_app.config.get('S3_PUBLIC_BASE_URL') or '').rstrip('/')
    return f"{base}/public/{name}"


def _store_public(fileobj, name, ext):
    if backend() == 's3':
        _s3_put(f'public/{name}', fileobj.stream, _content_type(ext))
        return _public_url(name)
    folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    fileobj.save(os.path.join(folder, name))
    return f"/static/uploads/{name}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_public_image(fileobj, prefix='img'):
    """Validate an uploaded image and store it publicly. Returns URL or None."""
    if not fileobj or not fileobj.filename:
        return None
    ext = _ext(fileobj.filename)
    if ext not in PUBLIC_IMAGE_EXT or not _is_real_image(fileobj.stream):
        return None
    return _store_public(fileobj, _new_name(prefix, ext), ext)


def save_chat_file(fileobj, prefix='chat'):
    """Store a chat attachment. Returns (url, message_type) or (None, None)."""
    if not fileobj or not fileobj.filename:
        return None, None
    ext = _ext(fileobj.filename)
    if ext not in CHAT_FILE_EXT:
        return None, None
    if ext in PUBLIC_IMAGE_EXT and not _is_real_image(fileobj.stream):
        return None, None
    url = _store_public(fileobj, _new_name(prefix, ext), ext)
    mtype = 'video' if ext in ('mp4', 'mov') else 'file' if ext == 'pdf' else 'image'
    return url, mtype


def save_private_document(fileobj, prefix='doc'):
    """Store a sensitive document privately. Returns the storage key or None."""
    if not fileobj or not fileobj.filename:
        return None
    ext = _ext(fileobj.filename)
    if ext not in PRIVATE_DOC_EXT:
        return None
    if ext in PUBLIC_IMAGE_EXT and not _is_real_image(fileobj.stream):
        return None
    name = _new_name(prefix, ext)
    if backend() == 's3':
        _s3_put(f'private/{name}', fileobj.stream, _content_type(ext))
        return name
    folder = current_app.config['PRIVATE_UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    fileobj.save(os.path.join(folder, name))
    return name


def private_path(key):
    """Absolute local path for a private key (local backend), or None if the key is malformed."""
    if not key or secure_filename(key) != key:
        return None
    return os.path.join(os.path.abspath(current_app.config['PRIVATE_UPLOAD_FOLDER']), key)


def private_url(key):
    """Short-lived presigned URL for a private key (s3 backend only)."""
    if not key or secure_filename(key) != key:
        return None
    return _s3_client().generate_presigned_url(
        'get_object', Params={'Bucket': current_app.config['S3_BUCKET'], 'Key': f'private/{key}'},
        ExpiresIn=PRESIGN_SECONDS)


def delete_private(key):
    if not key or secure_filename(key) != key:
        return
    if backend() == 's3':
        try:
            _s3_client().delete_object(Bucket=current_app.config['S3_BUCKET'], Key=f'private/{key}')
        except Exception:  # pragma: no cover
            current_app.logger.exception('Could not delete private object %s', key)
        return
    p = private_path(key)
    if p and os.path.exists(p):
        os.remove(p)
