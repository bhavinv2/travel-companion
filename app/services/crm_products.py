"""Products and services a lead can ask about (crm_products), read everywhere through here.

Made on screen (Set-up -> Pipelines -> Products, U6); the seed (crm_defaults.products()) is used only to
write the table the first time, and as the answer when there is no app context (pure-function tests) or
the table is still empty. Cached per request; any save of a product clears it (models._forget_products).
"""
import re
from dataclasses import dataclass

from flask import has_app_context

from app import db
from app.models import CrmPipeline, CrmProduct, request_cache

ICON_DEFAULT = 'fa-layer-group'
CODE_RE = re.compile(r'^[A-Z][A-Z0-9]{1,7}$')   # 2-8 letters or digits, starting with a letter (the KPI and the
                                                # step kinds read the longest product code first)
# follow-up kinds, milestone and quick-message codes: never a product code (U6 refuses them)
RESERVED = frozenset({'PI', 'CE', 'BW', 'FM', 'OM', 'PM', 'ER', 'PF', 'FU', 'CL', 'NR', 'Q', 'PLS',
                      'CM', 'HJ', 'SA', 'CS', 'SE'})


@dataclass(frozen=True)
class Product:
    id: object
    code: str
    name: str
    icon: str
    offered: bool
    default_pipeline_id: object
    pipeline_key: object
    currency: str
    kpi_row: object
    position: int


def _seed():
    from app.services import crm_defaults
    return [Product(None, c, n, i, o, None, k, 'INR', kr, pos)
            for pos, (c, n, i, o, k, kr) in enumerate(crm_defaults.products())]


def all():
    """Every product, in order. The seed without an app context or while the table is empty."""
    if not has_app_context():
        return _seed()
    cache = request_cache('crm_products')
    if 'all' in cache:
        return cache['all']
    rows = CrmProduct.query.order_by(CrmProduct.position, CrmProduct.id).all()
    if rows:
        keys = {}
        ids = [r.default_pipeline_id for r in rows if r.default_pipeline_id]
        if ids:
            keys = {pid: key for pid, key in db.session.query(CrmPipeline.id, CrmPipeline.key)
                    .filter(CrmPipeline.id.in_(ids))}
        out = [Product(r.id, r.code, r.name, r.icon or ICON_DEFAULT, bool(r.offered), r.default_pipeline_id,
                       keys.get(r.default_pipeline_id), r.currency or 'INR', r.kpi_row, r.position or 0)
               for r in rows]
    else:
        out = _seed()
    cache['all'] = out
    return out


def invalidate():
    request_cache('crm_products').clear()


def by_code(code):
    c = (code or '').strip().upper()
    return next((p for p in all() if p.code == c), None) if c else None


def codes():
    return [p.code for p in all()]


def labels():
    return {p.code: p.name for p in all()}


def icon(code):
    p = by_code(code)
    return p.icon if p is not None else ICON_DEFAULT


def icons():
    return {p.code: p.icon for p in all()}


def kpi_rows():
    return {p.code: p.kpi_row for p in all() if p.kpi_row}


def offered():
    return [p for p in all() if p.offered]


def _catch_alls():
    if not has_app_context():
        return []
    return CrmPipeline.query.filter_by(catch_all=True).order_by(CrmPipeline.id).all()


def general_code():
    """The product of the first catch-all pipeline, else GEN."""
    pipes = _catch_alls()
    return pipes[0].product if pipes else 'GEN'


def tiles():
    """The products to ask about on screen: the offered ones minus the catch-all pipelines' own
    product -- "Something else" stands for those."""
    skip = {p.product for p in _catch_alls()} or {'GEN'}
    return [p for p in offered() if p.code not in skip]


def default_pipeline(code):
    """The pipeline whose first stage a lead of this product starts in: the product's chosen one, else
    the first active pipeline of that product, else the catch-all."""
    if code is None:
        code = general_code()
    prod = by_code(code)
    pipe = None
    if prod is not None:
        if prod.default_pipeline_id:
            pipe = db.session.get(CrmPipeline, prod.default_pipeline_id)
        elif prod.pipeline_key:
            pipe = CrmPipeline.query.filter_by(key=prod.pipeline_key).first()
        if pipe is not None and not pipe.is_active:
            pipe = None
    if pipe is None:
        pipe = (CrmPipeline.query.filter_by(product=(code or '').strip().upper(), is_active=True,
                                            catch_all=False).order_by(CrmPipeline.id).first())
    if pipe is None:
        pipe = CrmPipeline.query.filter_by(catch_all=True).order_by(CrmPipeline.is_active.desc(),
                                                                    CrmPipeline.id).first()
    return pipe


def ensure_seeded():
    """If there is no product row, write the seed. True when it wrote."""
    if CrmProduct.query.first() is not None:
        return False
    from app.services import crm_defaults
    keys = {k: i for i, k in db.session.query(CrmPipeline.key, CrmPipeline.id)}
    for pos, (c, n, i, o, k, kr) in enumerate(crm_defaults.products()):
        db.session.add(CrmProduct(code=c, name=n, icon=i, offered=o, default_pipeline_id=keys.get(k),
                                  kpi_row=kr, position=pos))
    db.session.flush()
    invalidate()
    return True


def valid_code(code):
    """2-8 letters or digits starting with a letter, and not a code the follow-up kinds or buttons use."""
    c = (code or '').strip().upper()
    return bool(CODE_RE.match(c)) and c not in RESERVED
