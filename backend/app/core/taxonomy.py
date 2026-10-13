"""Build the CURRENT taxonomy tree from imported category rows.

The uploaded taxonomy is the source of truth: breadcrumbs are only parsed,
never rewritten. Ancestors that appear in breadcrumbs but have no row of their
own become `is_inferred` nodes.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Category, CategoryNode, Project
from .lexicon import HOME_LABEL_HINTS
from .normalize import join_breadcrumb, norm_key, split_breadcrumb
from .translate import glossary_en

PATH_SEP = "␟"  # unit separator used inside path keys


@dataclass
class _Draft:
    labels: tuple[str, ...]
    labels_en: list[str | None] = field(default_factory=list)
    category: Category | None = None


def path_key(labels: list[str] | tuple[str, ...]) -> str:
    return PATH_SEP.join(norm_key(l) for l in labels)


def _detect_home(first_labels: list[str]) -> str | None:
    if not first_labels:
        return None
    label, count = Counter(first_labels).most_common(1)[0]
    if count / len(first_labels) >= 0.6 or any(h in label.lower() for h in HOME_LABEL_HINTS):
        return label
    return None


def _labels_for_row(c: Category, by_ext: dict[str, Category], cache: dict[int, list[str]], seen: set[int] | None = None) -> list[str]:
    """CN labels for a row: from breadcrumb, else from the Parent ID chain."""
    if c.id in cache:
        return cache[c.id]
    name = (c.name_cn or c.h1_cn or c.name_en or "").strip()
    labels = split_breadcrumb(c.breadcrumb_cn)
    if not labels:
        seen = seen or set()
        parent = by_ext.get(c.parent_external_id or "") if c.parent_external_id else None
        if parent is not None and parent.id not in seen:
            seen.add(c.id)
            labels = _labels_for_row(parent, by_ext, cache, seen) + [name]
        elif c.parent_ref:
            labels = split_breadcrumb(c.parent_ref) + [name]
        else:
            labels = [name]
    elif name and norm_key(labels[-1]) != norm_key(name):
        # Breadcrumb ends at the parent -> append the page itself.
        labels = labels + [name]
    cache[c.id] = labels
    return labels


def build_tree(db: Session, project: Project) -> dict:
    cats = db.scalars(select(Category).where(Category.project_id == project.id)).all()
    db.execute(delete(CategoryNode).where(CategoryNode.project_id == project.id))
    db.flush()

    by_ext = {c.external_id: c for c in cats if c.external_id}
    cache: dict[int, list[str]] = {}
    rows = [(c, _labels_for_row(c, by_ext, cache)) for c in cats]
    rows = [(c, l) for c, l in rows if l]

    home = project.home_label_cn or _detect_home([l[0] for _, l in rows if len(l) > 1])
    if home and not project.home_label_cn:
        project.home_label_cn = home
    home_key = norm_key(home) if home else None

    drafts: dict[str, _Draft] = {}
    conflicts: list[dict] = []
    for c, labels in rows:
        if home_key and norm_key(labels[0]) != home_key:
            labels = [home] + labels
        en_labels = split_breadcrumb(c.breadcrumb_en)
        if en_labels and len(en_labels) == len(labels) - 1:
            en_labels = en_labels + [c.name_en or c.h1_en]
        for i in range(1, len(labels) + 1):
            pk = path_key(labels[:i])
            d = drafts.get(pk)
            if d is None:
                d = drafts[pk] = _Draft(labels=tuple(labels[:i]), labels_en=[None] * i)
            if len(en_labels) == len(labels):
                d.labels_en = [d.labels_en[j] or en_labels[j] for j in range(i)]
        own = drafts[path_key(labels)]
        if own.category is not None and own.category.id != c.id:
            conflicts.append({"path": join_breadcrumb(labels), "rows": [own.category.external_id or own.category.url, c.external_id or c.url]})
        else:
            own.category = c

    # Insert parents before children.
    node_by_pk: dict[str, CategoryNode] = {}
    for pk, d in sorted(drafts.items(), key=lambda kv: len(kv[1].labels)):
        labels = list(d.labels)
        parent = node_by_pk.get(path_key(labels[:-1])) if len(labels) > 1 else None
        c = d.category
        name = labels[-1]
        name_en = (c.name_en or c.h1_en) if c else None
        name_en = name_en or d.labels_en[-1] or glossary_en(name)
        en_path = None
        if parent is not None and parent.breadcrumb_en and name_en:
            en_path = f"{parent.breadcrumb_en} > {name_en}"
        elif parent is None and name_en:
            en_path = name_en
        if c and c.breadcrumb_en:
            en_labels = split_breadcrumb(c.breadcrumb_en)
            if len(en_labels) == len(labels) - 1 and name_en:
                en_labels.append(name_en)
            if len(en_labels) == len(labels):
                en_path = join_breadcrumb(en_labels)
        node = CategoryNode(
            project_id=project.id,
            category_id=c.id if c else None,
            external_id=c.external_id if c else None,
            url=c.url if c else None,
            name_cn=name,
            name_en=name_en,
            norm_key=norm_key(name),
            parent_id=parent.id if parent else None,
            parent_name=parent.name_cn if parent else None,
            depth=len(labels) - 1,
            breadcrumb_cn=join_breadcrumb(labels),
            breadcrumb_en=en_path,
            path_key=pk,
            product_count=c.product_count if c else None,
            status=c.status if c else None,
            is_root=(len(labels) == 1 and home_key is not None and norm_key(name) == home_key),
            is_inferred=c is None,
        )
        db.add(node)
        db.flush()
        node_by_pk[pk] = node

    # Child / descendant counts.
    children: dict[int, list[CategoryNode]] = defaultdict(list)
    for n in node_by_pk.values():
        if n.parent_id:
            children[n.parent_id].append(n)
    for n in sorted(node_by_pk.values(), key=lambda n: -n.depth):
        kids = children.get(n.id, [])
        n.children_count = len(kids)
        n.descendant_count = sum(1 + k.descendant_count for k in kids)

    db.flush()
    return {
        "nodes": len(node_by_pk),
        "category_rows": len(cats),
        "inferred_nodes": sum(1 for n in node_by_pk.values() if n.is_inferred),
        "home_label": home,
        "path_conflicts": conflicts[:50],
        "max_depth": max((n.depth for n in node_by_pk.values()), default=0),
    }


class TaxonomyIndex:
    """In-memory view of category_nodes used by the engines."""

    def __init__(self, nodes: list[CategoryNode]):
        self.nodes = {n.id: n for n in nodes}
        self.children: dict[int, list[CategoryNode]] = defaultdict(list)
        for n in nodes:
            if n.parent_id:
                self.children[n.parent_id].append(n)
        self.by_key: dict[str, list[CategoryNode]] = defaultdict(list)
        for n in nodes:
            if not n.is_root:
                self.by_key[n.norm_key].append(n)
                if n.name_en:
                    k = norm_key(n.name_en)
                    if k and k != n.norm_key:
                        self.by_key[k].append(n)
        self.by_path = {n.path_key: n for n in nodes}

    @classmethod
    def load(cls, db: Session, project_id: int) -> "TaxonomyIndex":
        return cls(db.scalars(select(CategoryNode).where(CategoryNode.project_id == project_id)).all())

    def ancestors(self, node: CategoryNode, include_root: bool = False) -> list[CategoryNode]:
        out: list[CategoryNode] = []
        cur = self.nodes.get(node.parent_id) if node.parent_id else None
        while cur is not None:
            if include_root or not cur.is_root:
                out.append(cur)
            cur = self.nodes.get(cur.parent_id) if cur.parent_id else None
        return list(reversed(out))

    def is_ancestor(self, maybe_anc: CategoryNode, node: CategoryNode) -> bool:
        cur = self.nodes.get(node.parent_id) if node.parent_id else None
        while cur is not None:
            if cur.id == maybe_anc.id:
                return True
            cur = self.nodes.get(cur.parent_id) if cur.parent_id else None
        return False

    def descendants(self, node: CategoryNode) -> list[CategoryNode]:
        out, stack = [], list(self.children.get(node.id, []))
        while stack:
            n = stack.pop()
            out.append(n)
            stack.extend(self.children.get(n.id, []))
        return out

    def top_branch(self, node: CategoryNode) -> CategoryNode | None:
        anc = self.ancestors(node)
        return anc[0] if anc else (None if node.is_root else node)

    def lca(self, nodes: list[CategoryNode]) -> CategoryNode | None:
        if not nodes:
            return None
        paths = [self.ancestors(n, include_root=True) for n in nodes]
        common: CategoryNode | None = None
        for level in zip(*paths):
            if all(x.id == level[0].id for x in level):
                common = level[0]
            else:
                break
        return common

    @property
    def root(self) -> CategoryNode | None:
        return next((n for n in self.nodes.values() if n.is_root), None)

    def real_nodes(self) -> list[CategoryNode]:
        return [n for n in self.nodes.values() if not n.is_root]
