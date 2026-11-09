"""外装・外構の色とマテリアル、外観CG の受け入れ試験。

    python3 tests/test_colors.py        （pytest があれば pytest tests/ でもよい）
"""
from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

import model3d as M  # noqa: E402
import render_cg  # noqa: E402
from house import House  # noqa: E402

_H = None
_GLB = None


def house():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def glb_path():
    """試験用に GLB を一時ファイルへ書き出す（dist/model.glb は触らない）。"""
    global _GLB
    if _GLB is None:
        d = tempfile.mkdtemp()
        _GLB = Path(d) / "model.glb"
        M.export_glb(house(), _GLB)
    return _GLB


def lin(hx):
    out = []
    for i in (1, 3, 5):
        c = int(hx[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def glb_json(path):
    data = Path(path).read_bytes()
    jl, _ = struct.unpack("<II", data[12:20])
    return json.loads(data[20:20 + jl].decode("utf-8"))


# ---------------------------------------------------------------- 1. 指定色
def test_spec_colors():
    c = house().spec["colors"]
    assert c["base"] == "#F5EFE3" and c["assort"] == "#4F5B2A" and c["accent"] == "#B8892D" and c["dotcon"] == "#D8C9A8"
    assert c["concrete"] == "#A8A49B" and c["porous_concrete"] == "#B3AFA6"


# ---------------------------------------------------------------- 2. 塀の色の範囲
def test_fence_colors_in_range():
    sp = house().spec
    a, b = sp["colors"]["fence_range"]
    ca = np.array([int(a[i:i + 2], 16) for i in (1, 3, 5)])
    cb = np.array([int(b[i:i + 2], 16) for i in (1, 3, 5)])
    lo, hi = np.minimum(ca, cb), np.maximum(ca, cb)
    assert tuple(lo) == (236, 231, 209) and tuple(hi) == (255, 248, 240)
    cols = [sp["colors"]["fence"]] + list(sp["colors"]["fence_shades"])
    assert len(cols) == 6
    for hx in cols:
        v = np.array([int(hx[i:i + 2], 16) for i in (1, 3, 5)])
        assert (v >= lo).all() and (v <= hi).all(), hx
        # 端点 #FFF8F0 〜 #ECE7D1 の線形補間の上にある（各チャンネルの t が近い）
        t = (ca - v) / (ca - cb)
        assert t.max() - t.min() < 0.12, (hx, t)
    for k, hx in enumerate(sp["colors"]["fence_shades"]):
        t = 0.70 + 0.06 * k
        want = M.fence_range_color(sp, t)
        got = tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))
        assert max(abs(a - b) for a, b in zip(want, got)) <= 1, (hx, want)


# ---------------------------------------------------------------- 3. GLB の色（リニア）
def test_glb_base_colors_linear():
    sp = house().spec
    js = glb_json(glb_path())
    mats = js["materials"]
    meshes = js["meshes"]
    checked = 0
    for n in js["nodes"]:
        nm = n.get("name", "")
        if "mesh" not in n or nm.count("|") != 2:
            continue
        mk = nm.split("|")[2]
        if mk.startswith("neighbor"):
            mk = "neighbor"
        elif mk.startswith("water"):
            mk = "water"
        elif mk.startswith("rev"):
            mk = "concrete"
        m = mats[meshes[n["mesh"]]["primitives"][0]["material"]]
        got = m["pbrMetallicRoughness"]["baseColorFactor"][:3]
        if mk in sp["materials"]:
            want = lin(M.color_hex(sp, sp["materials"][mk]["color"]))
        elif mk in M.EXTRA_MATERIALS:
            want = lin(M.color_hex(sp, M.EXTRA_MATERIALS[mk][0]))
        elif mk in M.STYLE:
            want = lin("#%02X%02X%02X" % tuple(round(v * 255) for v in M.STYLE[mk][1][:3]))
        elif mk in ("water", "concrete", "ground_wild", "porous_concrete"):
            want = lin(M.color_hex(sp, sp["materials"][mk]["color"]))
        else:
            raise AssertionError(f"材質キー未定義: {mk}")
        assert max(abs(a - b) for a, b in zip(got, want)) <= 0.002, (nm, got, want)
        checked += 1
    assert checked > 100
    # 指定色そのもの
    byname = {m.get("name"): m for m in mats}
    for k, hx in (("base", "#F5EFE3"), ("assort", "#4F5B2A"), ("accent", "#B8892D"), ("dotcon", "#D8C9A8")):
        got = byname[k]["pbrMetallicRoughness"]["baseColorFactor"][:3]
        assert max(abs(a - b) for a, b in zip(got, lin(hx))) <= 0.002, k


# ---------------------------------------------------------------- 4. 外壁の比率
def facade_ratio():
    h = house()
    sc = trimesh.load(str(glb_path()))
    rz = trimesh.transformations.rotation_matrix(h.alpha, [0, 0, 1], [h.W / 2000, h.D / 2000, 0])
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]) @ rz
    inv = np.linalg.inv(rot)
    res = {"base": 0.0, "assort": 0.0, "accent": 0.0}
    for name, g in sc.geometry.items():
        grp, lvl, mk = name.split("|")
        if mk not in M.FACADE_COLOR or grp not in ("外装（外断熱）", "建具", "外付けスクリーン", "床スラブ"):
            continue
        m = g.copy()
        m.apply_transform(inv)
        m.vertices = m.vertices * 1000
        n, c, a = m.face_normals, m.triangles_center, m.area_faces
        out = ((n[:, 1] < -.9) & (c[:, 1] < 0)) | ((n[:, 1] > .9) & (c[:, 1] > h.D)) | \
              ((n[:, 0] < -.9) & (c[:, 0] < 0)) | ((n[:, 0] > .9) & (c[:, 0] > h.W))
        if grp == "床スラブ" and mk == "accent":           # 玄関庇の下面
            out = out | (n[:, 2] < -.9)
        res[M.FACADE_COLOR[mk]] += a[out].sum() / 1e6
    tot = sum(res.values())
    return {k: v / tot for k, v in res.items()}, tot


def test_facade_ratio():
    r, tot = facade_ratio()
    assert 0.66 <= r["base"] <= 0.74, r
    assert 0.22 <= r["assort"] <= 0.30, r
    assert 0.03 <= r["accent"] <= 0.07, r


# ---------------------------------------------------------------- 5. 指定のない面はコンクリート
def test_unspecified_is_concrete():
    h = house()
    sp = h.spec
    n = 0
    for bx in h.boxes:
        if bx.level != "EXT":
            continue
        for q, mk in M.classify(h, bx):
            if bx.cat in ("wall", "parapet"):
                assert mk == "concrete", (bx.tag, mk)
                n += 1
            if bx.cat == "stair":
                assert mk.startswith("concrete"), (bx.tag, mk)
                n += 1
            assert mk in sp["materials"], (bx.tag, mk)     # STYLE のフォールバックに落ちていない
    assert n >= 5
    js = glb_json(glb_path())
    groups_ext = ("外構", "門扉", "忍び返し", "ボラード", "外構照明", "防犯カメラ", "ソーラーパーゴラ", "カーポート", "菜園", "RC塀", "道路", "水路", "地形")
    for nd in js["nodes"]:
        nm = nd.get("name", "")
        if nm.count("|") != 2:
            continue
        grp, lvl, mk = nm.split("|")
        if lvl == "EXT" or grp.startswith(groups_ext):
            base = "neighbor" if mk.startswith("neighbor") else mk
            assert base in sp["materials"] or base in M.EXTRA_MATERIALS or base.startswith(("water", "rev")), nm
    # 3章の表の要素がモデルに存在する
    names = {nd.get("name", "") for nd in js["nodes"]}
    for need in ("門扉|-|concrete", "外構基礎|-|concrete", "ボラード|-|concrete", "外構（見切り）|-|concrete", "外構（土間）|-|porous_concrete",
                 "地形（敷地）|-|porous_concrete", "外構（砂利）|-|gravel", "外構（Dotcon+舗装）|-|dotcon", "忍び返し|-|steel_frame",
                 "門扉|-|gate_panel", "建具|EXT|stainless", "建具|EXT|garbage_box", "階段|EXT|concrete_broom", "躯体（RC壁）|EXT|concrete",
                 "防犯カメラ|-|camera", "外構照明|-|fixture", "外構照明|-|lamp_2200k", "ソーラーパーゴラ|-|pv", "カーポート|-|pv",
                 "菜園|-|planter", "菜園|-|soil", "道路|-|asphalt", "屋上防水|RF|roof_sheet", "外装（外断熱）|RF|assort_metal"):
        assert need in names, need


# ---------------------------------------------------------------- 6. カメラ
def test_cameras_clear_of_neighbors():
    with tempfile.TemporaryDirectory():
        render_cg.main(["--scene-only", "--no-glb"])
    cfg = json.loads((ROOT / "dist" / "render" / "scene.json").read_text(encoding="utf-8"))
    h = house()
    from shapely.geometry import Point, Polygon
    assert len(cfg["cuts"]) == 7
    for c in cfg["cuts"]:
        x, y, z = c["cam_mm"]
        for b in h.neighbors:
            p = Polygon(b)
            if p.is_valid and p.area >= 4e6:
                assert p.distance(Point(x, y)) >= 1500, (c["id"], p.distance(Point(x, y)))
        if h.site_gross.contains(Point(x, y)):          # v4.22: CG は旧境界（寄付地を含む）で判定。C06 は塀の外面から28mm 内側（CG は変更しない）
            assert h.site_gross.buffer(-h.fence_t).contains(Point(x, y)), c["id"]
        else:
            assert z >= h.ground(x, y) + 500 or c["id"] == "C02"


# ---------------------------------------------------------------- 7. 太陽位置が sightshade と矛盾しない
def test_sun_matches_sightshade():
    import sightshade
    lat, lon, tz = 35.667, 139.36, 9
    for date, n in (("2026-10-24", 297), ("2026-06-21", 172), ("2026-05-15", 135)):
        best = max(render_cg.sun_position(f"{date}T{h:02d}:{m:02d}", lat, lon, tz)[0] for h in range(10, 14) for m in range(0, 60, 2))
        d = math.radians(23.45 * math.sin(math.radians(360 * (284 + n) / 365)))
        ref = math.degrees(math.asin(math.sin(math.radians(lat)) * math.sin(d) + math.cos(math.radians(lat)) * math.cos(d)))
        assert abs(best - ref) <= 1.5, (date, best, ref)   # sightshade は赤緯に Cooper の近似式を使うため、NOAA 式との差は最大 1.4°
    assert sightshade.LAT == lat


# ---------------------------------------------------------------- 8. 段階2（bpy がなければスキップ）
def test_stage2_preview():
    py = ROOT / ".venv-bpy" / "bin" / "python"
    import os
    if not (py.exists() or os.environ.get("BPY_PYTHON")):
        print("  (bpy なし: スキップ)")
        return
    rc = render_cg.main(["--preview", "--only", "C03", "--no-glb"])
    assert rc == 0
    from PIL import Image
    png = ROOT / ".cache" / "cg" / "preview" / "C03_approach.png"
    im = Image.open(png)
    assert im.size == (960, 540) and not im.info, im.info


# ---------------------------------------------------------------- 9. 内装の配色（v4.29）
OWNER_WALLS = {"W1": "#080C0F", "W2": "#212A31", "W3": "#3E4C58", "W4": "#43433F", "W5": "#383B3D"}
OWNER_FLOORS = {"F1": "#917440", "F2": "#F7E4C4", "F3": "#CED9E2", "F4": "#C2C9CC", "F5": "#9BA3A8"}


def _lrv(hx):
    out = 0.0
    for i, w in zip((1, 3, 5), (0.2126, 0.7152, 0.0722)):
        c = int(hx[i:i + 2], 16) / 255
        out += w * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out * 100


def _lstar(hx):
    y = _lrv(hx) / 100
    f = y ** (1 / 3) if y > 216 / 24389 else (24389 / 27 * y + 16) / 116
    return 116 * f - 16


def test_interior_colors_as_specified():
    """(a) 施主の10色・明るい壁 IV1／IV2・天井 C2 が spec にそのままある。"""
    h = house()
    cp, pal = h.spec["interior_color_plan"], h.spec["interior_palette"]
    assert cp["walls_dark"] == OWNER_WALLS and cp["floors"] == OWNER_FLOORS
    assert cp["light"] == {"IV1": "#F5F1E6", "IV2": "#F3EEDD"} and cp["ceiling"]["C2"] == "#F6F5F1"
    for code, hx in OWNER_WALLS.items():
        assert pal[cp["materials"][code]]["color"] == hx, code
    assert pal["wall_paint"]["color"] == "#F5F1E6" and pal["wall_iv2"]["color"] == "#F3EEDD" and pal["ceiling_paint"]["color"] == "#F6F5F1"
    assert pal["stair_riser"]["color"] == OWNER_WALLS["W5"] and pal["nosing"]["color"] == OWNER_FLOORS["F1"] and pal["ceiling_theater"]["color"] == OWNER_WALLS["W2"]
    assert {pal[k]["color"] for k in ("floor_oak", "floor_sheet", "floor_tile_genkan", "floor_rubber", "floor_carpet", "floor_machine")} == set(OWNER_FLOORS.values())


def test_all_ten_colors_used():
    """(b) 暗い壁5色はどこかの室で使われ、床5色はどこかの床に敷かれている。"""
    import interior_shell as IS
    h = house()
    cp, pal = h.spec["interior_color_plan"], h.spec["interior_palette"]
    used_w = {e["rp"]["dark"] for e in IS.wall_plan(h)}
    assert used_w == set(OWNER_WALLS), used_w
    used_f = {pal[c.fmat]["color"] for c in IS.cells(h)}
    assert used_f == set(OWNER_FLOORS.values()), used_f
    assert {e["rp"]["light"] for e in IS.wall_plan(h)} == {"IV1", "IV2"}


def test_light_wall_share_50_to_70():
    """(c) 明るい壁（アイボリー・オフホワイト系）の正味面積の割合が、各室・全体で 50〜70%。全体は 60±5%。"""
    import interior_shell as IS
    rows = IS.wall_color_table(house())
    bad = [(r["floor"], r["room"], round(r["share"], 3)) for r in rows if not (0.5 - 1e-6 <= r["share"] <= 0.7 + 1e-6)]
    assert not bad, bad
    assert 0.55 <= rows[-1]["share"] <= 0.65, rows[-1]["share"]
    assert all(r["ok"] for r in rows)


def test_dark_walls_keep_clear_of_corners_doors_stairs():
    """(d) 廊下・ホール・階段室の全高の暗い壁は、角・戸口・階段口から 600 以上離す（不足分は H1,400 以下の腰で補う）。"""
    import interior_shell as IS
    h = house()
    m = h.spec["interior_color_plan"]["safe_mm"]
    n = 0
    for ent in IS.wall_plan(h):
        if not ent["rp"].get("circ"):
            continue
        assert ent.get("band_top", ent["z0"]) - ent["z0"] <= 1400 + 1
        for e in ent["edges"]:
            for (a, b, kd) in e["spans"]:
                if kd != "dark":
                    continue
                n += 1
                assert a >= e["u0"] + m - 1 and b <= e["u1"] - m + 1, (ent["cell"].name, a, b)
                for (x0, za, x1, zb, op) in e["ops"]:
                    if op.kind == "door":
                        assert b <= x0 - m + 1 or a >= x1 + m - 1, (ent["cell"].name, "door", a, b, x0, x1)
                for (hx0, hy0, hx1, hy1) in [s.hole for s in h.stairs]:
                    if e["ax"] == "y" and hx0 - 1 <= e["k"] <= hx1 + 1:
                        assert b <= hy0 - m + 1 or a >= hy1 + m - 1
                    if ent["rp"].get("stair"):
                        assert e["ax"] == "y"             # 階段に直交する面（上り口・下り口の正面）には置かない
    assert n > 0


def test_contrast_floor_ceiling_stairs():
    """(e) 床と巾木（なければ明るい壁）の LRV 差 30 以上（ユニットバスは近似色で要確認）、踏面と段鼻・蹴込みの差 30 以上、床の L* 40 以上、天井の LRV 85 以上（シアターを除く）。"""
    import interior_shell as IS
    h = house()
    pal = h.spec["interior_palette"]
    cm = h.spec["interior_color_plan"]["materials"]
    for e in IS.wall_plan(h):
        c = e["cell"]
        fl = pal[c.fmat]["color"]
        assert _lstar(fl) >= 40, (c.name, _lstar(fl))
        sk = IS.SKIRT_OF.get(c.fmat)
        lower = pal[cm[e["rp"]["dark"] if e["rp"]["mode"] == "wainscot" else e["rp"]["light"]]]["color"]       # 壁の下端の色（腰があれば腰）
        edge = pal[sk[0]]["color"] if sk and pal[sk[0]]["color"] != fl else lower
        if "浴室" not in c.name and "シャワー" not in c.name:
            assert abs(_lrv(fl) - _lrv(edge)) >= 30, (c.name, _lrv(fl), _lrv(edge))
        if "シアター" not in c.name:
            assert _lrv(pal[c.cmat]["color"]) >= 85, c.name
    tread = _lrv(pal["floor_oak"]["color"])
    assert tread - _lrv(pal["nosing"]["color"]) >= 30 and tread - _lrv(pal["stair_riser"]["color"]) >= 30


def test_exterior_unchanged_and_refl():
    """(f) 外観の色は不変。refl_table の反射率は palette の LRV と一致し、全室で照度が目標以上。"""
    import lighting
    h = house()
    assert h.spec["colors"]["base"] == "#F5EFE3"
    cp = h.spec["interior_color_plan"]
    allc = {**cp["walls_dark"], **cp["floors"], **cp["light"], "C2": cp["ceiling"]["C2"]}
    for k, v in h.spec["lighting"]["refl_table"].items():
        assert abs(lighting.lrv(allc[k]) - v) < 0.0015, k
    import interior_shell as IS
    assert all(lighting.refl_factor(h, r) > 0 for r in h.rooms)
    import furniture
    rows = lighting.illuminance_table(h, furniture.items(h))
    assert all(r["E"] >= r["target"] for r in rows if r.get("target") and r["E"]), [r["room"] for r in rows if r.get("target") and r["E"] and r["E"] < r["target"]]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:          # noqa: BLE001
                fails += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
