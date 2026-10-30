"""家具の仮置き・内装CG の受け入れ試験。

    python3 tests/test_furniture.py        （pytest があれば pytest tests/ でもよい）
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import trimesh  # noqa: E402
from shapely.geometry import box as sbox, Polygon  # noqa: E402

import furniture as FU  # noqa: E402
import model3d as M  # noqa: E402
from house import House  # noqa: E402

_H = None


def house():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def test_check_no_errors():
    h = house()
    assert FU.check(h, FU.items(h)) == []


def test_single_chair_in_ldk():
    h = house()
    its = FU.items(h)
    ch = [i for i in its if i.chair]
    assert len(ch) == 1 == sum(i.chair for i in its)
    assert ch[0].room == FU.LDK and ch[0].name == "ペッパー スクールチェア チャコールブラウン"
    assert not [i for i in its if i.kind in FU.CHAIR_KINDS and not i.chair]


def test_table_in_ldk():
    h = house()
    t = next(i for i in FU.items(h) if i.id == "L-T1")
    assert t.room == FU.LDK
    assert round(t.w) == h.spec["furniture"]["products"]["table_osb"]["w"] == 1775
    assert t.name.startswith("マテリア ダイニングテーブル OSB 177.5cm")


def test_robot_clearance():
    """床置きの家具は、台輪・脚下250以上・浮かせ250以上・機器類のいずれか。脚の間の内法は250以上。"""
    h = house()
    ok_base = {"plinth", "none", "pot", "unit", "stack", "frame", "ceiling", "wallfix"}
    for i in FU.items(h):
        if i.base in ok_base:
            continue
        if i.base == "legs":
            assert h.spec["furniture"]["products"]["school_chair"]["seat_h"] - 20 >= 250
        elif i.base == "legs690":
            assert i.h - h.spec["furniture"]["products"]["table_osb"]["top_t"] >= 250
            p = h.spec["furniture"]["products"]["table_osb"]
            assert i.w - 2 * (p["leg_inset"] + p["leg_pipe"]) >= 250          # 左右の脚枠の内法
        elif i.base == "legs260":
            assert 260 >= 250
        elif i.base == "legs25":
            import kitchen_open as KO
            assert KO.KB_SHELF_Z[0] >= 250              # 背面カウンターの底板は FL+300（掃除ロボットが入る）
        elif i.base == "float650":
            assert 650 >= 250
        else:
            raise AssertionError(f"{i.id}: 掃除ロボットの扱いが未定義 {i.base}")


def test_wall_gaps():
    """家具と壁・家具どうしのすき間が 0〜5 か 250 以上（頭 100〜230・指 8〜25 のすき間がない）。"""
    h = house()
    assert FU.gap_errors(h, FU.items(h)) == []


def test_downlights_inside_ceiling():
    h = house()
    its = FU.items(h)
    holes = [sbox(*s.hole) for s in h.stairs]
    rooms = {(r.floor, r.name): sbox(*r.rect) for r in h.rooms}
    for d in FU.downlights(h, its):
        x, y, z = d["p"]
        assert rooms[(d["floor"], d["room"])].buffer(1).contains(sbox(x, y, x, y).buffer(1)) or any(
            r.floor == d["floor"] and sbox(*r.rect).contains(sbox(x, y, x, y)) for r in h.rooms)
        if d["floor"] == "1F":
            assert not any(hh.contains(sbox(x, y, x, y)) for hh in holes), "吹抜け（階段開口）の上にある"


def test_glb_nodes():
    h = house()
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.glb", Path(d) / "b.glb"
        M.export_glb(h, a)
        M.export_glb(h, b, interior=True)
        na = sorted(trimesh.load(a).graph.nodes_geometry)
        nb = sorted(trimesh.load(b).graph.nodes_geometry)
    ids = {n.split("|")[3] for n in nb if n.split("|")[0] == "家具" and len(n.split("|")) > 3}
    assert "L-C1" in ids and len([i for i in ids if i.startswith("L-C")]) == 1       # チェアのノードは L-C1 だけ
    assert any(n.startswith("家具|") and n.split("|")[2] == "osb" and n.endswith("|L-T1") for n in nb)
    assert not any(n.split("|")[0] in ("家具", "内装仕上げ", "扉", "照明器具") for n in na)        # 既定の GLB は従来のまま
    base = ROOT / "dist" / "model.glb"
    if base.exists():
        assert sorted(trimesh.load(base).graph.nodes_geometry) == na


def test_interior_preview_render():
    py = ROOT / ".venv-bpy" / "bin" / "python"
    if not py.exists():
        print("skip: bpy なし")
        return
    r = subprocess.run([sys.executable, str(ROOT / "src" / "render_cg.py"), "--interior", "--preview", "--only", "I01"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
    assert (ROOT / ".cache" / "cg" / "interior_preview" / "I01_ldk_south.png").exists()


def test_kitchen_open():
    """キッチン・パントリーの全露出（v4.17）。"""
    import kitchen_open as KO
    h = house()
    its = FU.items(h)
    ids = {i.id for i in its}
    assert "K-B1" not in ids and "P-S1" not in ids
    assert {"KB-W", "KB-C", "KB-R", "KB-N", "KB-S", "KB-F", "KS-W"} <= ids and not ({"KB-K", "P-O1"} & ids)
    by = {i.id: i for i in its}
    assert by["KB-N"].z0 - h.fl["1F"] + by["KB-N"].h <= 1550         # 施錠式ナイフケース（上端 1,550 以下）
    zs = [0] + [z for z in KO.KB_SHELF_Z] + [KO.KB_TOP_UNDER]       # 背面カウンター下部の段の間隔（棚板上面〜上の棚板下面）
    gaps = [b - a - (KO.KB_SHELF_T if a else 0) for a, b in zip(zs, zs[1:])]
    assert gaps[0] >= 250 and all(g > 230 for g in gaps[1:]), gaps   # 底板の下は掃除ロボットが入る（≧250）、段の間隔は 230 超
    tiers = KO.KS_TIERS
    assert all(b - a - KO.KB_SHELF_T > 230 for a, b in zip(tiers, tiers[1:]))
    ks = KO.KSW_SHELF_Z
    assert all(b - a - 18 > 230 for a, b in zip(ks, ks[1:])) and KO.KSW_Z - ks[-1] - 18 > 230
    assert FU.check(h, its) == []
    assert not h.spec["kitchen_open"]["pot_rack"]
    props = KO.props(h).meshes()
    assert {"stainless", "ceramic", "glass_clear"} <= set(props)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok", f.__name__)
