"""Files on a person or an enquiry (Sales CRM 2.0, run 4a).

The bytes live in PRIVATE_UPLOAD_FOLDER/crm/<random name> -- never under static -- and are only handed out by
the permission-checked download route. Allowed: pdf, jpg, jpeg, png, webp, doc, docx, xls, xlsx, csv, txt;
at most 10 MB. A file kept on an enquiry that is deleted for good (the bin's purge) STAYS on the person:
its lead_id is emptied (a passport copy is not lost because an old enquiry was cleaned up). Erasing a
person deletes their files from disk.
"""
import os
import secrets

from flask import current_app
from sqlalchemy import update

from app import db
from app.models import CrmFile

FOLDER = 'crm'
MAX_BYTES = 10 * 1024 * 1024
TYPES = {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
         'webp': 'image/webp', 'doc': 'application/msword',
         'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         'xls': 'application/vnd.ms-excel',
         'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         'csv': 'text/csv', 'txt': 'text/plain'}
BAD_TYPE = 'That kind of file is not allowed. Use PDF, JPG, PNG, WEBP, DOC, DOCX, XLS, XLSX, CSV or TXT.'
TOO_BIG = 'That file is bigger than 10 MB.'
NOTHING = 'Choose a file first.'
EMPTY = 'That file is empty.'


def folder(create=True):
    path = os.path.join(os.path.abspath(current_app.config['PRIVATE_UPLOAD_FOLDER']), FOLDER)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def path_of(row):
    # stored names are ours (hex + extension), never a path: still, only ever the base name
    return os.path.join(folder(create=False), os.path.basename(row.stored_name))


def extension(filename):
    return os.path.splitext(filename or '')[1].lstrip('.').lower()


def clean_name(filename):
    name = os.path.basename((filename or '').replace(chr(92), '/')).strip()
    name = ''.join(ch for ch in name if ch >= ' ' and ch not in '<>:"|?*')
    return name[:190] or 'file'


def save_upload(storage, person, lead=None, user=None):
    """Store an uploaded file (werkzeug FileStorage). Returns (CrmFile, None) or (None, error text). No commit."""
    if storage is None or not getattr(storage, 'filename', ''):
        return None, NOTHING
    name = clean_name(storage.filename)
    ext = extension(name)
    if ext not in TYPES:
        return None, BAD_TYPE
    data = storage.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        return None, TOO_BIG
    if not data:
        return None, EMPTY
    stored = '%s.%s' % (secrets.token_hex(16), ext)
    with open(os.path.join(folder(), stored), 'wb') as fh:
        fh.write(data)
    row = CrmFile(person_id=person.id, lead_id=lead.id if lead is not None else None, filename=name,
                  stored_name=stored, size=len(data), content_type=TYPES[ext],
                  uploaded_by_id=getattr(user, 'id', None))
    db.session.add(row)
    db.session.flush()
    return row, None


def remove_from_disk(paths):
    """Delete files after the database change is saved (a failed save must not lose a file)."""
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def delete(row):
    """Forget the row now; returns the disk path to remove after commit."""
    p = path_of(row)
    db.session.delete(row)
    return p


def paths_for_person(person_id):
    return [path_of(f) for f in CrmFile.query.filter_by(person_id=person_id).all()]


def delete_for_person(person_id):
    """Erase this person: their file rows go; returns the disk paths to remove after commit."""
    rows = CrmFile.query.filter_by(person_id=person_id).all()
    paths = [path_of(f) for f in rows]
    CrmFile.query.filter_by(person_id=person_id).delete(synchronize_session=False)
    return paths


def keep_on_person(lead_id):
    """A lead goes for good: its files stay on the person (lead_id emptied)."""
    db.session.execute(update(CrmFile).where(CrmFile.lead_id == lead_id).values(lead_id=None)
                       .execution_options(synchronize_session=False))


def for_person(person_id):
    """Their files, newest first -- those on an enquiry the viewer cannot see (or that sits in the bin) are left
    out: the lead query of a signed-in GET already hides those leads."""
    from app.models import CrmLead
    rows = CrmFile.query.filter_by(person_id=person_id).order_by(CrmFile.uploaded_at.desc(), CrmFile.id.desc()).all()
    ids = {f.lead_id for f in rows if f.lead_id}
    seen = {l.id for l in CrmLead.query.filter(CrmLead.id.in_(ids)).all()} if ids else set()
    return [f for f in rows if f.lead_id is None or f.lead_id in seen]


def for_lead(lead_id):
    return CrmFile.query.filter_by(lead_id=lead_id).order_by(CrmFile.uploaded_at.desc(), CrmFile.id.desc()).all()


def size_text(n):
    n = n or 0
    if n >= 1024 * 1024:
        return '%.1f MB' % (n / (1024 * 1024))
    if n >= 1024:
        return '%d KB' % round(n / 1024)
    return '%d B' % n
