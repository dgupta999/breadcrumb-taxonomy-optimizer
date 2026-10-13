from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project


def to_dict(obj, exclude: set[str] | None = None) -> dict[str, Any]:
    out = {}
    for c in obj.__table__.columns:
        if exclude and c.name in exclude:
            continue
        v = getattr(obj, c.name)
        if isinstance(v, datetime):
            v = v.isoformat()
        out[c.name] = v
    return out


def get_project(project_id: int, db: Session = Depends(get_db)) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "Project not found")
    return p


class Page:
    def __init__(self, limit: int = Query(100, ge=1, le=5000), offset: int = Query(0, ge=0), q: str | None = None,
                 sort: str | None = None, order: str = Query("asc", pattern="^(asc|desc)$")):
        self.limit, self.offset, self.q, self.sort, self.order = limit, offset, q, sort, order


def paginate(db: Session, query, model, page: Page, search_cols: list = (), default_sort=None, exclude: set[str] | None = None, extra=None) -> dict:
    if page.q and search_cols:
        like = f"%{page.q}%"
        query = query.where(or_(*[c.ilike(like) for c in search_cols]))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    col = getattr(model, page.sort, None) if page.sort else None
    if col is not None and hasattr(col, "desc"):
        query = query.order_by(col.desc() if page.order == "desc" else col.asc())
    elif default_sort is not None:
        query = query.order_by(*default_sort if isinstance(default_sort, (list, tuple)) else [default_sort])
    rows = db.scalars(query.limit(page.limit).offset(page.offset)).all()
    items = [to_dict(r, exclude) for r in rows]
    if extra:
        items = extra(rows, items)
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset}


def multi(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []
