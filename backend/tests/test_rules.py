"""Rule tests for the deterministic engine (no network, no LLM).

Run:  cd backend && .venv/Scripts/python -m pytest -q
"""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp, 'test.db').as_posix()}"
os.environ["LLM_ENABLED"] = "false"
os.environ["DATA_DIR"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.core.audit import run_audit  # noqa: E402
from app.core.context import ensure_default_synonyms, load_context  # noqa: E402
from app.core.fileio import import_rows, read_table, suggest_mapping  # noqa: E402
from app.core.normalize import norm_key, normalize, split_breadcrumb  # noqa: E402
from app.core.review import apply_review  # noqa: E402
from app.core.srp_mapping import map_srps  # noqa: E402
from app.core.taxonomy import build_tree  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import SRP, BreadcrumbAudit, CategoryNode, Project  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture(scope="module")
def env():
    init_db()
    db = SessionLocal()
    p = Project(name="test")
    db.add(p)
    db.flush()
    for kind, f in (("TAXONOMY", "current_taxonomy.xlsx"), ("SRP", "srp_data.csv")):
        cols, _ = read_table(SAMPLES / f)
        import_rows(db, kind, p.id, str(SAMPLES / f), suggest_mapping(kind, cols))
    build_tree(db, p)
    ensure_default_synonyms(db, p.id)
    ctx = load_context(db, p)
    map_srps(db, ctx)
    run_audit(db, load_context(db, p))
    db.commit()
    yield db, p
    db.close()


def srp(db, kw) -> SRP:
    return db.query(SRP).filter(SRP.keyword == kw).one()


def node_name(db, nid):
    return db.get(CategoryNode, nid).name_cn if nid else None


# ---------------------------------------------------------------- normalization
@pytest.mark.parametrize("raw,expected", [
    ("128 gb", "128gb"), ("1 TB", "1tb"), ("Wi Fi", "wifi"), ("Wi-Fi 6", "wifi 6"),
    ("ＡＳＵＳ　筆電", "asus 筆電"), ("micro SD", "microsd"), ("電腦/週邊", "電腦/周邊"),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_breadcrumb_split():
    assert split_breadcrumb("酷澎首頁 > 電腦3C > 電腦/平板周邊 > 儲存裝置 > 記憶卡") == ["酷澎首頁", "電腦3C", "電腦/平板周邊", "儲存裝置", "記憶卡"]


# ---------------------------------------------------------------- tree
def test_tree_built_from_breadcrumbs(env):
    db, p = env
    n = db.query(CategoryNode).filter(CategoryNode.name_cn == "記憶卡").one()
    assert n.breadcrumb_cn == "酷澎首頁 > 電腦3C > 電腦/平板周邊 > 儲存裝置 > 記憶卡"
    assert n.depth == 4 and n.parent_name == "儲存裝置"
    assert db.query(CategoryNode).filter(CategoryNode.is_root.is_(True)).one().name_cn == "酷澎首頁"


# ---------------------------------------------------------------- core product extraction
@pytest.mark.parametrize("kw,core,mods", [
    ("128g記憶卡", "記憶卡", ["128g"]),
    ("asus筆電", "筆電", ["asus"]),
    ("asus 筆電充電器", "筆電充電器", ["asus"]),   # longest match: 筆電充電器, not 筆電
    ("羅技滑鼠", "滑鼠", ["羅技"]),
    ("筆電支架", "支架", ["筆電"]),                 # head-final: 支架 is the product
])
def test_core_extraction(env, kw, core, mods):
    db, p = env
    ext = load_context(db, p).vocab.extract(kw)
    assert norm_key(ext.core_label) == norm_key(core)
    assert ext.modifiers == mods


# ---------------------------------------------------------------- SRP mapping
def test_deepest_valid_category(env):
    db, _ = env
    assert node_name(db, srp(db, "256gb microsd").matched_node_id) == "microSD"


def test_breadcrumb_inherits_existing_category_breadcrumb(env):
    db, _ = env
    s = srp(db, "128g記憶卡")
    assert node_name(db, s.matched_node_id) == "記憶卡"
    assert s.breadcrumb_cn == "酷澎首頁 > 電腦3C > 電腦/平板周邊 > 儲存裝置 > 記憶卡 > 128g記憶卡"
    assert s.breadcrumb_en.startswith("Coupang Home > Computers & Electronics > Computer & Tablet Accessories > Storage Devices > Memory Cards > ")


def test_longest_match_concept(env):
    db, _ = env
    assert node_name(db, srp(db, "asus 筆電充電器").matched_node_id) == "筆電充電器"


def test_poe_switch_never_nintendo(env):
    db, _ = env
    s = srp(db, "poe switch")
    assert node_name(db, s.matched_node_id) != "Nintendo Switch"
    assert s.potential_gap and s.confidence_band == "NO_MATCH"


def test_duplicate_intent(env):
    db, _ = env
    assert srp(db, "ssd").duplicate_intent == "YES"
    assert srp(db, "電腦喇叭").duplicate_intent in ("YES", "POTENTIAL")
    assert srp(db, "1tb ssd").duplicate_intent == "NO"


def test_confidence_bands(env):
    db, _ = env
    assert srp(db, "128g記憶卡").confidence_band == "AUTO_APPROVED"
    assert srp(db, "顯示卡").confidence_band == "NO_MATCH"


# ---------------------------------------------------------------- audit
def audit(db, name, contains=None) -> BreadcrumbAudit:
    rows = db.query(BreadcrumbAudit).filter(BreadcrumbAudit.category_name == name).all()
    if contains:
        rows = [r for r in rows if contains in r.current_breadcrumb_cn]
    return rows[0]


def test_audit_duplicate_level_flatten(env):
    db, _ = env
    a = audit(db, "讀卡機", "讀卡機 > 讀卡機")
    assert a.action == "FLATTEN"
    assert a.recommended_breadcrumb_cn.endswith("儲存裝置 > 讀卡機")


def test_audit_more_specific_parent(env):
    db, _ = env
    a = audit(db, "無線滑鼠")
    assert a.action == "MOVE" and a.recommended_breadcrumb_cn.endswith("滑鼠 > 無線滑鼠")


def test_audit_wrong_parent_flagged(env):
    db, _ = env
    a = audit(db, "變壓器")
    assert a.action in ("REVIEW", "MOVE")  # without competitor evidence / LLM: REVIEW
    assert any("not a type of" in i or "not semantically" in i for i in a.issues)


def test_audit_missing_logical_parent(env):
    db, _ = env
    a = audit(db, "筆電充電器")
    assert a.action == "MOVE + CREATE PARENT" and "筆電配件" in a.recommended_breadcrumb_cn
    assert any(x["label"] == "筆電配件" for x in a.links_added)


def test_existing_breadcrumbs_never_modified(env):
    db, _ = env
    n = db.query(CategoryNode).filter(CategoryNode.name_cn == "變壓器").one()
    assert n.breadcrumb_cn.endswith("讀卡機 > 變壓器")  # proposal only, source of truth untouched


# ---------------------------------------------------------------- human overrides
def test_human_mapping_overrides_future_runs(env):
    db, p = env
    s = srp(db, "wifi分享器")
    target = db.query(CategoryNode).filter(CategoryNode.name_cn == "網路/分享器").one()
    apply_review(db, p.id, "srp", s.id, "CHANGE_CATEGORY", {"node_id": target.id}, "tester")
    db.commit()
    map_srps(db, load_context(db, p))
    db.commit()
    s = srp(db, "wifi分享器")
    assert s.matched_node_id == target.id and s.match_method == "HUMAN" and s.review_status == "APPROVED"


# ---------------------------------------------------------------- entity relations (is-a vs accessory-of)
from app.core.relations import ACCESSORY, IS_A, SIBLING, relation  # noqa: E402


@pytest.mark.parametrize("child,parent,rel", [
    ("無線滑鼠", "滑鼠", IS_A),
    ("電競螢幕", "螢幕", IS_A),
    ("筆電充電器", "充電器", IS_A),
    ("滑鼠墊", "滑鼠", ACCESSORY),
    ("手機殼", "手機", ACCESSORY),
    ("無線滑鼠", "電競滑鼠", SIBLING),
])
def test_relation(child, parent, rel):
    assert relation(child, parent) == rel


def test_accessory_not_mapped_to_its_product(env):
    db, p = env
    m = load_context(db, p).matcher
    for kw, wrong in (("滑鼠墊", "滑鼠"), ("手機殼", "手機"), ("記憶卡盒", "記憶卡")):
        r = m.match(kw)
        assert r.top is None or r.top.node.name_cn != wrong, (kw, r.top.node.name_cn if r.top else None)


def test_subtype_still_mapped_to_parent(env):
    db, p = env
    m = load_context(db, p).matcher
    assert m.match("電競滑鼠").top.node.name_cn == "滑鼠"
    assert m.match("羅技 無線滑鼠").top.node.name_cn == "無線滑鼠"


def test_srp_support_uses_is_a(env):
    from app.core.gaps import SrpIndex

    db, p = env
    ctx = load_context(db, p)
    sidx = SrpIndex(db.query(SRP).all() + [SRP(id=-1, keyword="滑鼠墊", keyword_norm="滑鼠墊", modifiers=[])], ctx)
    kws = {s.keyword for s, _ in sidx.support(["滑鼠"])}
    assert {"羅技滑鼠", "電競滑鼠", "無線滑鼠"} <= kws
    assert "滑鼠墊" not in kws
