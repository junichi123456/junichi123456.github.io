"""3D モデル出力（glTF バイナリ .glb）。図面と同じ House モデル＋国土地理院の地形・周辺データから生成する。

ノード名は「グループ|階|材質キー」。グループ名は index.html のレイヤー、材質キーは外観CG（render_cg.py）の材質割り当てに使う。
色は spec.yaml の colors（sRGB 16進）をリニア値に直して baseColorFactor に書く。
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from collections import defaultdict

import numpy as np
import trimesh
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box as sbox
from shapely.ops import unary_union

S = 1 / 1000.0

# 材質キーが spec.yaml の materials に無いときのフォールバック（従来の色）。グループ名と RGBA
STYLE = {
    "wall": ("躯体（RC壁）", (0.80, 0.79, 0.76, 1.0)),
    "parapet": ("躯体（RC壁）", (0.80, 0.79, 0.76, 1.0)),
    "insul": ("外装（外断熱）", (0.93, 0.91, 0.86, 1.0)),
    "slab": ("床スラブ", (0.72, 0.71, 0.68, 1.0)),
    "partition": ("間仕切", (0.95, 0.94, 0.90, 1.0)),
    "glass": ("建具", (0.40, 0.60, 0.80, 0.55)),
    "door": ("建具", (0.45, 0.38, 0.30, 1.0)),
    "stair": ("階段", (0.66, 0.62, 0.56, 1.0)),
    "footing": ("基礎", (0.55, 0.53, 0.50, 1.0)),
    "blind": ("外付けスクリーン", (0.30, 0.31, 0.33, 1.0)),
}
EXTRA_COLORS = {          # spec.yaml の colors に無い補助色（sRGB 16進）
    "bollard_band": "#D9D2B5", "camera_lens": "#0B0B0D", "road_line": "#E8E6DF", "equipment": "#40454D",
}
EXTRA_MATERIALS = {       # matkey: (色キー, 粗さ, 金属度)
    "bollard_band": ("bollard_band", 0.2, 0.0), "camera_lens": ("camera_lens", 0.05, 0.0),
    "road_line": ("road_line", 0.85, 0.0), "equipment": ("equipment", 0.6, 0.0),
}
# 外壁の比率の集計で、どの指定色に属するか
FACADE_COLOR = {"base": "base", "assort": "assort", "tile": "assort", "assort_metal": "assort", "assort_frame": "assort",
                "accent": "accent", "accent_door": "accent"}


def srgb_to_lin(hx):
    out = []
    for i in (1, 3, 5):
        c = int(hx[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def color_hex(spec, key):
    """色キー → sRGB 16進。fence_1〜fence_5 は個体差の色。"""
    col = spec["colors"]
    if key.startswith("fence_") and key[6:].isdigit():
        return col["fence_shades"][int(key[6:]) - 1]
    return col.get(key) or EXTRA_COLORS[key]


def fence_range_color(spec, t):
    a, b = (spec["colors"]["fence_range"][0], spec["colors"]["fence_range"][1])
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def material_table(spec, interior=False):
    """matkey → dict(rgba_linear, roughness, metallic, emissive)。interior=True で内装パレット（spec.interior_palette）を加える。"""
    out = {}
    for k, m in spec["materials"].items():
        out[k] = dict(color=color_hex(spec, m["color"]), roughness=m.get("roughness", 0.9), metallic=m.get("metallic", 0.0),
                      emissive=bool(m.get("emissive")))
    for k, (ck, r, me) in EXTRA_MATERIALS.items():
        out[k] = dict(color=color_hex(spec, ck), roughness=r, metallic=me, emissive=False)
    if interior:
        for k, m in spec.get("interior_palette", {}).items():
            if k not in out:             # 外観と共用のキー（stainless など）は外観の値のまま
                out[k] = dict(color=m["color"], roughness=m.get("roughness", 0.8), metallic=m.get("metallic", 0.0),
                              emissive=bool(m.get("emissive")))
    for cat, (_, rgba) in STYLE.items():
        if cat not in out:
            hx = "#%02X%02X%02X" % tuple(round(v * 255) for v in rgba[:3])
            out[cat] = dict(color=hx, roughness=0.9, metallic=0.0, emissive=False, fallback=True)
    for k in out:
        out[k]["rgb"] = srgb_to_lin(out[k]["color"])
    out["glass"]["alpha"] = 0.55
    return out


# ------------------------------------------------------------------ 形状ユーティリティ（mm 入力 → m のメッシュ）
def mbox(x0, y0, z0, x1, y1, z1):
    ext = np.array([x1 - x0, y1 - y0, z1 - z0]) * S
    if (ext <= 0).any():
        return None
    m = trimesh.creation.box(extents=ext)
    m.apply_translation(np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]) * S)
    return m


def tbox(cx, cy, cz, ex, ey, ez, tilt_deg=0.0):
    """X 軸まわりに tilt 度傾けた箱（中心 cx,cy,cz、寸法 ex,ey,ez。mm）。"""
    m = trimesh.creation.box(extents=np.array([ex, ey, ez]) * S)
    if tilt_deg:
        m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(tilt_deg), [1, 0, 0]))
    m.apply_translation(np.array([cx, cy, cz]) * S)
    return m


def cyl(x, y, r, z0, z1, n=16):
    m = trimesh.creation.cylinder(radius=r * S, height=(z1 - z0) * S, sections=n)
    m.apply_translation([x * S, y * S, (z0 + z1) / 2 * S])
    return m


def poly_m(pts):
    return Polygon([(x * S, y * S) for x, y in pts])


def prism(poly, z0, z1):
    """mm の shapely Polygon（穴あり可）→ 角柱。"""
    if poly.is_empty or z1 <= z0:
        return None
    ext = [(x * S, y * S) for x, y in poly.exterior.coords]
    holes = [[(x * S, y * S) for x, y in r.coords] for r in poly.interiors]
    m = trimesh.creation.extrude_polygon(Polygon(ext, holes), (z1 - z0) * S)
    m.apply_translation([0, 0, z0 * S])
    return m


def polys_of(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for gg in getattr(g, "geoms", []) for p in polys_of(gg)]


def split_box(q, axis, cuts):
    """箱 q=(x0,y0,z0,x1,y1,z1) を axis(0/1/2) の位置 cuts で切って複数の箱にする。"""
    lo, hi = q[axis], q[axis + 3]
    pts = [lo] + sorted(c for c in cuts if lo + 1e-6 < c < hi - 1e-6) + [hi]
    out = []
    for a, b in zip(pts, pts[1:]):
        r = list(q)
        r[axis], r[axis + 3] = a, b
        out.append(tuple(r))
    return out


class Parts:
    def __init__(self):
        self.d = defaultdict(list)

    def add(self, grp, lvl, matkey, mesh):
        if mesh is not None:
            self.d[(grp, lvl or "-", matkey)].append(mesh)

    def add_box(self, grp, lvl, matkey, q):
        self.add(grp, lvl, matkey, mbox(*q))


# ------------------------------------------------------------------ 外壁・建具の材質判定
def classify(h, bx):
    """Box → [(箱の座標 6 値, 材質キー)]。上から順に最初に当たった規則を採る。"""
    q = (bx.x0, bx.y0, bx.z0, bx.x1, bx.y1, bx.z1)
    t = h.t
    if bx.mat == "glass":
        return [(q, "glass")]
    if bx.cat == "door":
        if bx.tag == "SD-1":
            return [(q, "accent_door")]
        if bx.tag == "ゴミ収集ボックス":
            return [(q, "garbage_box")]
        if bx.tag == "宅配ボックス":
            return [(q, "stainless")]
        if bx.level == "FDN":
            return [(q, "assort")]
        return [(q, "interior_door")]
    if bx.cat == "blind":
        return [(q, "assort_metal")]
    if bx.cat == "insul":
        return classify_insul(h, bx)
    if bx.cat in ("wall", "parapet") and bx.level == "EXT":
        return [(q, "concrete")]
    if bx.cat == "stair" and bx.level == "EXT":
        return [(q, "concrete_broom")]
    if bx.cat == "slab" and bx.tag == "庇":
        return [(q, "accent")]
    if bx.cat in ("wall", "parapet"):
        return [(q, "base")]
    return [(q, bx.cat)]


def classify_insul(h, bx):
    z = h.spec["facade_zones"]
    q = (bx.x0, bx.y0, bx.z0, bx.x1, bx.y1, bx.z1)
    south = bx.y1 <= -h.t / 2 + 1e-6
    zcuts = [z["tile"]["z"][1], z["floor_line"]["z"][0], z["floor_line"]["z"][1], z["top_band"]["z"][0]]
    ent = z["entrance"]
    if south:
        zcuts.append(ent["z"][1])
    pieces = split_box(q, 2, zcuts)
    if south:
        pieces = [p for pp in pieces for p in split_box(pp, 0, ent["x"])]
    out = []
    for p in pieces:
        cx, cz = (p[0] + p[3]) / 2, (p[2] + p[5]) / 2
        if p[5] <= z["tile"]["z"][1] + 1e-6:
            k = "tile"
        elif cz >= z["top_band"]["z"][0]:
            k = "assort"
        elif south and ent["x"][0] <= cx <= ent["x"][1] and ent["z"][0] <= cz < ent["z"][1]:
            k = "accent"
        else:
            k = "base"
        out.append((p, k))
    return out


def facade_extras(h, P):
    """CG 用に足す外装の要素: 2FL 見切り・笠木・屋上防水・窓枠。"""
    z = h.spec["facade_zones"]
    e = h.t / 2 + h.ins
    W, D = h.W, h.D
    g = "外装（外断熱）"
    # 2FL の水平見切り（外装面から 10mm 出す）
    pj = z["floor_line"]["projection"]
    z0, z1 = z["floor_line"]["z"]
    for q in [(-e - pj, -e - pj, z0, W + e + pj, -e, z1), (-e - pj, D + e, z0, W + e + pj, D + e + pj, z1),
              (-e - pj, -e, z0, -e, D + e, z1), (W + e, -e, z0, W + e + pj, D + e, z1)]:
        P.add_box(g, "2F", "accent", q)
    # 笠木（パラペット天端、躯体の内面から外装面＋20mm まで）
    c0, c1 = z["coping"]["z"]
    ov = z["coping"]["overhang"]
    o, i = e + ov, h.t / 2
    for q in [(-o, -o, c0, W + o, i, c1), (-o, D - i, c0, W + o, D + o, c1),
              (-o, i, c0, i, D - i, c1), (W - i, i, c0, W + o, D - i, c1)]:
        P.add_box(g, "RF", "assort_metal", q)
    # 屋上防水（パラペットの内側）
    P.add_box("屋上防水", "RF", "roof_sheet", (i, i, h.fl["RF"], W - i, D - i, h.fl["RF"] + 100))
    # 窓枠（外装面側、見付 60・見込 70）
    fw, fd = z["window_frame"]["face"], z["window_frame"]["depth"]
    for op in h.openings(exterior=True):
        if op.kind != "window":
            continue
        s = op.wall.side
        for (u0, u1, v0, v1) in [(op.u0, op.u1, op.z0, op.z0 + fw), (op.u0, op.u1, op.z1 - fw, op.z1),
                                 (op.u0, op.u0 + fw, op.z0 + fw, op.z1 - fw), (op.u1 - fw, op.u1, op.z0 + fw, op.z1 - fw)]:
            if s == "S":
                q = (u0, -e, v0, u1, -e + fd, v1)
            elif s == "N":
                q = (u0, D + e - fd, v0, u1, D + e, v1)
            elif s == "W":
                q = (-e, u0, v0, -e + fd, u1, v1)
            else:
                q = (W + e - fd, u0, v0, W + e, u1, v1)
            P.add_box("建具", op.floor, "assort_frame", q)
    # 玄関庇の上面（防水）
    cx0, cy0, cx1, cy1 = h.canopy
    P.add_box("床スラブ", "EXT", "roof_sheet", (cx0, cy0, h.canopy_z + 150, cx1, cy1, h.canopy_z + 160))


# ------------------------------------------------------------------ 外構
def exterior_parts(h, P, spec):
    fgl = h.fgl
    site_in = h.site.buffer(-h.fence_t)

    # ---- 塀（区間ごとの個体差の色）と忍び返し
    for li, ln in enumerate(h.fence_lines):
        L = ln.length
        d = 0.0
        pi = 0
        while d < L - 1:
            d2 = min(L, d + 2000)
            seg = LineString([ln.interpolate(d).coords[0], ln.interpolate(d2).coords[0]])
            c = seg.interpolate(0.5, normalized=True)
            top = h.fence_top(c.x, c.y)
            base = min(h.fgl, h.ground(c.x, c.y)) - 100
            off = seg.parallel_offset(h.fence_t / 2, "left")
            if not h.site.contains(off.interpolate(0.5, normalized=True)):
                off = seg.parallel_offset(h.fence_t / 2, "right")
            poly = off.buffer(h.fence_t / 2, cap_style=2)
            k = int(hashlib.sha1(f"{li}-{pi}".encode()).hexdigest(), 16) % 5 + 1
            P.add("RC塀", "-", f"fence_{k}", prism(poly, base, top))
            P.add("忍び返し", "-", "steel_frame", prism(off.buffer(10, cap_style=2), top, top + 150))
            d = d2
            pi += 1

    # ---- 門扉・門柱（閉じた状態）
    for name, x0, x1, yg, hh in h.gate_leaves:
        yc = yg + 75
        P.add_box("門扉", "-", "gate_panel", (x0, yc - 30, fgl + 30, x1, yc + 30, fgl + hh))
        P.add_box("忍び返し", "-", "steel_frame", (x0, yc - 10, fgl + hh, x1, yc + 10, fgl + hh + 150))
        P.add_box("門扉", "-", "steel_frame", (x0, yc - 40, fgl + 30, x1, yc + 40, fgl + 80))        # レール・下枠
    for (x0, y0, x1, y1) in h.gate_piers:
        P.add_box("門扉", "-", "concrete", (x0, y0, fgl - 150, x1, y1, fgl + 2050))
        P.add_box("忍び返し", "-", "steel_frame", (x0 + 140, y0 + 140, fgl + 2050, x1 - 140, y1 - 140, fgl + 2200))
    # ---- 忍び返し: 玄関の目隠し壁・ゴミ置きの目隠し壁の天端
    for bx in h.boxes:
        if bx.level == "EXT" and bx.cat == "wall":
            cx, cy = (bx.x0 + bx.x1) / 2, (bx.y0 + bx.y1) / 2
            if bx.x1 - bx.x0 >= bx.y1 - bx.y0:
                q = (bx.x0, cy - 10, bx.z1, bx.x1, cy + 10, bx.z1 + 150)
            else:
                q = (cx - 10, bx.y0, bx.z1, cx + 10, bx.y1, bx.z1 + 150)
            P.add_box("忍び返し", "-", "steel_frame", q)

    # ---- Dotcon+ 舗装・アプローチ・見切り
    dot_polys = list(polys_of(h.dotcon))
    for p in dot_polys:
        P.add("外構（Dotcon+舗装）", "-", "dotcon", prism(p, fgl - 150, fgl + 20))
    ap = h.approach.intersection(site_in)
    for p in polys_of(ap):
        P.add("外構（Dotcon+舗装）", "-", "dotcon", prism(p, fgl - 100, fgl + 25))
    P.add("外構（Dotcon+舗装）", "-", "dotcon", prism(h.dotcon_farm, fgl - 150, fgl + 20))
    for p in polys_of(h.dotcon_garden):
        P.add("外構（Dotcon+舗装）", "-", "dotcon", prism(p, fgl - 150, fgl + 20))
    dot_union = unary_union([*dot_polys, ap, h.dotcon_farm, h.dotcon_garden]).buffer(0)
    edging = dot_union.buffer(100).difference(dot_union).intersection(site_in)
    for p in polys_of(edging):
        P.add("外構（見切り）", "-", "concrete", prism(p, fgl - 150, fgl + 20))

    # ---- 防草砂利帯（外壁面から幅 1,000。ポーチ・外部階段の下は除く）
    e = h.t / 2 + h.ins
    foot = sbox(-e, -e, h.W + e, h.D + e)
    porch = sbox(*h.porch).buffer(50)
    gravel = foot.buffer(1000, join_style=2).difference(foot).difference(porch).difference(dot_union).intersection(site_in)
    for p in polys_of(gravel):
        P.add("外構（砂利）", "-", "gravel", prism(p, fgl - 100, fgl + 30))

    # ---- 門前の広場（透水性コンクリート）
    for p in polys_of(h.forecourt):
        P.add("外構（土間）", "-", "porous_concrete", prism(p, fgl - 100, fgl + 20))

    # ---- ソーラーパーゴラ
    pg = spec["exterior"]["solar_pergola"]
    x0, y0, x1, y1 = h.pergola
    ph = h.pergola_h
    zb = max(h.ground((x0 + x1) / 2, (y0 + y1) / 2), fgl)
    tn = math.tan(math.radians(pg["tilt"]))
    head = lambda y: zb + ph + (y - y0) * tn
    xs = [x0 + i * (x1 - x0) / 4 for i in range(5)]
    G = "ソーラーパーゴラ"
    for x in xs:
        for y in (y0, y1):
            P.add_box(G, "-", "steel_frame", (x - 75, y - 75, zb, x + 75, y + 75, head(y)))
            P.add_box("外構基礎", "-", "concrete", (x - 200, y - 200, zb - 100, x + 200, y + 200, zb + 150))
        L = (y1 - y0) / math.cos(math.radians(pg["tilt"]))
        P.add(G, "-", "steel_frame", tbox(x, (y0 + y1) / 2, (head(y0) + head(y1)) / 2 - 75, 100, L, 150, pg["tilt"]))
    rows = 7
    pitch = (y1 - y0) / rows
    pw = pitch * pg["coverage"]
    nmod = 16
    mw = (x1 - x0) / nmod
    for r in range(rows):
        yc = y0 + (r + 0.5) * pitch
        for ye in (yc - pw / 2, yc + pw / 2):
            P.add(G, "-", "steel_frame", tbox((x0 + x1) / 2, ye, head(ye) + 30, x1 - x0 + 200, 60, 60, pg["tilt"]))
        zc = head(yc) + 80
        for i in range(nmod):
            xc = x0 + (i + 0.5) * mw
            P.add(G, "-", "pv_frame", tbox(xc, yc, zc, mw - 20, pw, 40, pg["tilt"]))
            P.add(G, "-", "pv", tbox(xc, yc, zc + 1.5, mw - 20 - 50, pw - 50, 40, pg["tilt"]))

    # ---- 日なた・パーゴラ下の脚付きプランター（箱形のプランター＋土）
    fm = spec["farm"]
    def planter(b, z_base):
        px0, py0, px1, py1 = b
        z0 = z_base + fm["leg"]
        z1 = z0 + fm["planter_h"]
        w = 30
        P.add_box("菜園", "-", "planter", (px0, py0, z0, px1, py1, z0 + w))
        for q in [(px0, py0, z0, px1, py0 + w, z1), (px0, py1 - w, z0, px1, py1, z1),
                  (px0, py0, z0, px0 + w, py1, z1), (px1 - w, py0, z0, px1, py1, z1)]:
            P.add_box("菜園", "-", "planter", q)
        P.add_box("菜園", "-", "soil", (px0 + w, py0 + w, z0 + w, px1 - w, py1 - w, z1 - 50))
        for lx in (px0 + 60, px1 - 60):
            for ly in (py0 + 60, py1 - 60):
                P.add_box("菜園", "-", "planter", (lx - 30, ly - 30, z_base, lx + 30, ly + 30, z0))
    for b in h.garden_beds:
        planter(b, zb)
    for b in h.planters:
        planter(b, fgl + 20)

    # ---- 3台用ソーラーカーポート
    cp = h.carport
    cph = spec["exterior"]["carport"]["h"]
    G = "カーポート"
    for (x, y) in [(cp[0], cp[1]), (cp[2] - 200, cp[1]), (cp[0], cp[3] - 200), (cp[2] - 200, cp[3] - 200)]:
        P.add_box(G, "-", "steel_frame", (x, y, fgl, x + 200, y + 200, fgl + cph))
        P.add_box("外構基礎", "-", "concrete", (x - 100, y - 100, fgl - 100, x + 300, y + 300, fgl + 150))
    P.add_box(G, "-", "steel_frame", (cp[0], cp[1], fgl + cph, cp[2], cp[3], fgl + cph + 80))
    nx, ny = 8, 4
    mw, md = (cp[2] - cp[0]) / nx, (cp[3] - cp[1]) / ny
    for i in range(nx):
        for j in range(ny):
            xc, yc = cp[0] + (i + 0.5) * mw, cp[1] + (j + 0.5) * md
            P.add_box(G, "-", "pv_frame", (xc - mw / 2 + 10, yc - md / 2 + 10, fgl + cph + 80, xc + mw / 2 - 10, yc + md / 2 - 10, fgl + cph + 120))
            P.add_box(G, "-", "pv", (xc - mw / 2 + 35, yc - md / 2 + 35, fgl + cph + 80, xc + mw / 2 - 35, yc + md / 2 - 35, fgl + cph + 122))

    # ---- 昇降ボラード（φ220×H800）と台座
    vs = spec["vehicle_security"]["bollards"]
    for (x, y) in h.bollards:
        P.add("ボラード", "-", "bollard", cyl(x, y, vs["d"] / 2, fgl, fgl + vs["h"]))
        P.add("ボラード", "-", "bollard_band", cyl(x, y, vs["d"] / 2 + 1, fgl + vs["h"] - 150, fgl + vs["h"] - 100))
        P.add_box("ボラード", "-", "concrete", (x - 300, y - 300, fgl - 150, x + 300, y + 300, fgl + 20))

    # ---- 外構照明（2200K）
    P_el = "外構照明"
    porch_top = h.fl["1F"] - 2 * 180 - 20
    for name, (x, y) in h.ext_lights:
        if name == "ボラード":
            P.add_box("外構基礎", "-", "concrete", (x - 150, y - 150, fgl - 100, x + 150, y + 150, fgl + 20))
            P.add("外構照明", "-", "fixture", cyl(x, y, 75, fgl + 20, fgl + 560))
            P.add("外構照明", "-", "lamp_2200k", cyl(x, y, 70, fgl + 560, fgl + 600))
        elif name.startswith("足元灯"):
            P.add_box(P_el, "-", "fixture", (x - 75, y - 75, porch_top, x + 75, y + 75, porch_top + 300))
            P.add_box(P_el, "-", "lamp_2200k", (x - 70, y - 70, porch_top + 260, x + 70, y + 70, porch_top + 296))
        elif name.startswith("カーポート"):
            zu = fgl + cph
            P.add(P_el, "-", "fixture", cyl(x, y, 80, zu - 40, zu))
            P.add(P_el, "-", "lamp_2200k", cyl(x, y, 70, zu - 45, zu - 40))
        else:   # 門灯（低位置 0.4m）
            P.add_box(P_el, "-", "fixture", (x - 75, y - 75, fgl + 20, x + 75, y + 75, fgl + 420))
            P.add_box(P_el, "-", "lamp_2200k", (x - 70, y - 70, fgl + 340, x + 70, y + 70, fgl + 416))

    # ---- 防犯カメラ
    mounts = []
    e2 = h.t / 2 + h.ins
    for (x, y) in [(-e2, -e2), (h.W + e2, -e2), (-e2, h.D + e2), (h.W + e2, h.D + e2)]:
        mounts.append((x, y, 4200))
    for (x0_, y0_, x1_, y1_) in h.gate_piers:
        mounts.append(((x0_ + x1_) / 2, (y0_ + y1_) / 2, fgl + 1950))
    for (x, y) in [(cp[0] + 100, cp[1] + 100), (cp[2] - 100, cp[1] + 100), (cp[0] + 100, cp[3] - 100), (cp[2] - 100, cp[3] - 100)]:
        mounts.append((x, y, fgl + 1950))
    for (cx, cy) in spec["security"]["cameras"]:
        mx, my, mz = min(mounts, key=lambda m: (m[0] - cx) ** 2 + (m[1] - cy) ** 2)
        ang = math.atan2(cy - my, cx - mx)
        ux, uy = math.cos(ang), math.sin(ang)
        px, py = mx + ux * 130, my + uy * 130
        m = trimesh.creation.box(extents=[0.20, 0.09, 0.09])
        m.apply_transform(trimesh.transformations.rotation_matrix(ang, [0, 0, 1]))
        m.apply_translation([px * S, py * S, mz * S + 0.05])
        P.add("防犯カメラ", "-", "camera", m)
        lens = trimesh.creation.box(extents=[0.012, 0.07, 0.07])
        lens.apply_transform(trimesh.transformations.rotation_matrix(ang, [0, 0, 1]))
        lens.apply_translation([(px + ux * 100) * S, (py + uy * 100) * S, mz * S + 0.05])
        P.add("防犯カメラ", "-", "camera_lens", lens)


# ------------------------------------------------------------------ 地形・道路・水路
def _site_road_polys(h):
    """南側道路（境界から 7,400）・東側道路（境界から東へ 5,500）の帯。"""
    pts = {}
    for (a, b, k), c in zip(h.site_edges, h.edge_class):
        pts.setdefault(c, []).append((a, b))
    def band(segs, width):
        coords = [segs[0][0]] + [s[1] for s in segs]
        ln = LineString(coords)
        d0 = np.array(coords[1]) - np.array(coords[0]); d0 /= np.linalg.norm(d0)
        d1 = np.array(coords[-1]) - np.array(coords[-2]); d1 /= np.linalg.norm(d1)
        ext = [tuple(np.array(coords[0]) - d0 * 65000)] + coords + [tuple(np.array(coords[-1]) + d1 * 65000)]
        ln = LineString(ext)
        cands = [ln.buffer(width, single_sided=True), LineString(ext[::-1]).buffer(width, single_sided=True)]
        for c in cands:
            if not c.buffer(-10).intersects(h.site):
                return c
        return cands[0]
    south = band(pts["南側道路"], h.spec["site"]["south_road_width"])
    east = band(pts["東側道路"], h.spec["site"]["east_road_width"])
    return south.union(east).buffer(0), pts["南側道路"][0]


def terrain_parts(h):
    xs = np.arange(-70, 61, 2.0)
    ys = np.arange(-70, 66, 2.0)
    V = {}
    for j, ym in enumerate(ys):
        for i, xm in enumerate(xs):
            x, y = (xm - h.ox) * 1000, (ym - h.oy) * 1000
            z = h.fgl if h.site.contains(Point(x, y)) else h.ground(x, y)
            V[(i, j)] = (x, y, z - 30)
    road, s_edge = _site_road_polys(h)
    water = unary_union([Polygon(w).buffer(0) for w in h.water]).buffer(0)
    tris_in, tris_out = [], []
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            a, b, c, e = V[(i, j)], V[(i + 1, j)], V[(i + 1, j + 1)], V[(i, j + 1)]
            cx, cy = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
            (tris_in if h.site.contains(Point(cx, cy)) else tris_out).extend([(a, b, c), (a, c, e)])

    def plane_z(tri):
        A = np.array([[p[0], p[1], 1.0] for p in tri])
        co = np.linalg.solve(A, np.array([p[2] for p in tri])) if abs(np.linalg.det(A)) > 1e-6 else np.array([0, 0, tri[0][2]])
        return lambda x, y: co[0] * x + co[1] * y + co[2]

    def clipped(tri_list, region, mode, lift=0.0):
        """三角形群を region で切り抜く（mode='int': 内側のみ, 'diff': 外側のみ）。戻り値は (頂点, 面)。"""
        V_, F_ = [], []
        for tri in tri_list:
            tp = Polygon([(p[0], p[1]) for p in tri])
            if not tp.intersects(region):
                continue
            r = tp.intersection(region) if mode == "int" else tp.difference(region)
            f = plane_z(tri)
            for pg in polys_of(r):
                if pg.area < 1:
                    continue
                vv, ff = trimesh.creation.triangulate_polygon(pg, engine="earcut")
                base = len(V_)
                V_.extend([[x * S, y * S, (f(x, y) + lift) * S] for x, y in vv])
                F_.extend([[base + a, base + b, base + c] for a, b, c in ff])
        return V_, F_
    return tris_in, tris_out, road, water, plane_z, clipped, s_edge


def apron_mesh(h, xs, ys, far=1200.0):
    """DEM の範囲の外側に、地平線まで続く地面（縁の標高から遠景の標高へなだらかにつなぐ）を作る。建物座標 mm → (頂点 m, 面)。"""
    X = [(xm - h.ox) * 1000 for xm in xs]
    Y = [(ym - h.oy) * 1000 for ym in ys]
    per = [(X[i], Y[0], "S") for i in range(len(X))] + [(X[-1], Y[j], "E") for j in range(1, len(Y))] + \
          [(X[i], Y[-1], "N") for i in range(len(X) - 2, -1, -1)] + [(X[0], Y[j], "W") for j in range(len(Y) - 2, 0, -1)]
    z0 = [h.ground(x, y) for x, y, _ in per]
    layers = [0, 20, 60, 150, 350, 700, far]
    zfar = 500.0
    V, rows = [], []
    for d in layers:
        row = []
        s = min(1.0, d / 1000.0)
        for (x, y, side), zz in zip(per, z0):
            dx = {"E": d, "W": -d}.get(side, 0)
            dy = {"N": d, "S": -d}.get(side, 0)
            if (x, y) == (X[-1], Y[0]):
                dx, dy = d, -d
            elif (x, y) == (X[-1], Y[-1]):
                dx, dy = d, d
            elif (x, y) == (X[0], Y[-1]):
                dx, dy = -d, d
            elif (x, y) == (X[0], Y[0]):
                dx, dy = -d, -d
            row.append(len(V))
            V.append([(x + dx * 1000) * S, (y + dy * 1000) * S, (zz * (1 - s) + zfar * s - 30) * S])
        rows.append(row)
    F = []
    n = len(per)
    for r0, r1 in zip(rows, rows[1:]):
        for i in range(n):
            a, b = r0[i], r0[(i + 1) % n]
            c, e = r1[(i + 1) % n], r1[i]
            F += [[a, b, c], [a, c, e]]
    return np.array(V), np.array(F)


def build_terrain(h, scene, rot):
    """地形（敷地・周辺）・道路・白線・水路。"""
    tris_in, tris_out, road, water, plane_z, clipped, s_edge = terrain_parts(h)

    def mesh_from_tris(tris, region=None, mode=None, lift=0.0):
        if region is None:
            Vv = np.array([[p[0] * S, p[1] * S, (p[2] + lift) * S] for t in tris for p in t])
            Ff = np.arange(len(Vv)).reshape(-1, 3)
            return Vv, Ff
        Vv, Ff = clipped(tris, region, mode, lift)
        return np.array(Vv), np.array(Ff)

    # 敷地内
    out = {}
    out["地形（敷地）|-|porous_concrete"] = mesh_from_tris(tris_in)
    # 周辺（道路・水面を抜く）
    near = [t for t in tris_out if not Polygon([(p[0], p[1]) for p in t]).intersects(water)]
    cut = [t for t in tris_out if Polygon([(p[0], p[1]) for p in t]).intersects(water)]
    Va, Fa = mesh_from_tris(near)
    Vb, Fb = mesh_from_tris(cut, water, "diff")
    if len(Vb):
        Va, Fa = np.vstack([Va, Vb]), np.vstack([Fa, Fb + len(Va)])
    out["地形（周辺）|-|ground_wild"] = (Va, Fa)
    out["地形（遠景）|-|ground_wild"] = apron_mesh(h, np.arange(-70, 61, 2.0), np.arange(-70, 66, 2.0))
    # 道路（地形より 20mm 上）と路側の白線（南側道路の両端）
    rt = [t for t in tris_out if Polygon([(p[0], p[1]) for p in t]).intersects(road)]
    out["道路|-|asphalt"] = mesh_from_tris(rt, road, "int", 20.0)
    (pa, pb) = s_edge
    ln = LineString([pa, pb])
    dx, dy = np.array(pb) - np.array(pa)
    dirv = np.array([dx, dy]) / math.hypot(dx, dy)
    ext = LineString([tuple(np.array(pa) - dirv * 65000), tuple(np.array(pb) + dirv * 65000)])
    w = h.spec["site"]["south_road_width"]
    nrm = np.array([-dirv[1], dirv[0]])
    if nrm[1] > 0:
        nrm = -nrm
    lines = []
    for off in (300, w - 450):       # 境界側と対向側の路側線（幅150）
        c = ext.parallel_offset(off, "left" if np.cross(dirv, nrm) > 0 else "right")
        lines.append(c.buffer(75, cap_style=2))
    lines_poly = unary_union(lines)
    out["道路|-|road_line"] = mesh_from_tris(rt, lines_poly, "int", 24.0)
    # 水路（水面 z=-1.5m）と護岸
    for k, wp in enumerate(h.water):
        poly = Polygon(wp).buffer(0)
        c = poly.representative_point()
        scene_wp = prism(poly, -1600, -1500)
        out[f"水路|-|water_{k}"] = (np.array(scene_wp.vertices), np.array(scene_wp.faces))
        band = poly.buffer(150).difference(poly)
        wm = prism(band, -1600, max(h.ground(c.x, c.y), -1400))
        if wm is not None:
            out[f"水路|-|rev_{k}"] = (np.array(wm.vertices), np.array(wm.faces))
    for name, v in out.items():
        if v is None or len(v[0]) == 0:
            continue
        mesh = trimesh.Trimesh(vertices=v[0], faces=v[1], process=False)
        mesh.merge_vertices()
        mesh.remove_unreferenced_vertices()
        grp, lvl, mk = name.split("|")
        mk = "water" if mk.startswith("water") else "concrete" if mk.startswith("rev") else mk
        mesh.apply_transform(rot)
        yield grp, lvl, mk, name, mesh


# ------------------------------------------------------------------ GLB 書き出し
def _patch_glb(path, table):
    """材質名（=材質キー）ごとの baseColorFactor / emissiveFactor を、量子化しない float で書き直す。"""
    data = open(path, "rb").read()
    magic, ver, total = struct.unpack("<4sII", data[:12])
    jl, jt = struct.unpack("<II", data[12:20])
    js = json.loads(data[20:20 + jl].decode("utf-8"))
    for m in js.get("materials", []):
        t = table.get(m.get("name"))
        if not t:
            continue
        pbr = m.setdefault("pbrMetallicRoughness", {})
        pbr["baseColorFactor"] = [round(v, 6) for v in t["rgb"]] + [t.get("alpha", 1.0)]
        pbr["metallicFactor"] = t["metallic"]
        pbr["roughnessFactor"] = t["roughness"]
        if t.get("emissive"):
            m["emissiveFactor"] = [round(v, 6) for v in t["rgb"]]
    body = json.dumps(js, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body += b" " * (-len(body) % 4)
    rest = data[20 + jl:]
    out = struct.pack("<4sII", magic, ver, 12 + 8 + len(body) + len(rest)) + struct.pack("<II", len(body), jt) + body + rest
    open(path, "wb").write(out)


def _mat(key, table):
    t = table[key]
    a = t.get("alpha", 1.0)
    return trimesh.visual.material.PBRMaterial(
        name=key, baseColorFactor=[*t["rgb"], a], metallicFactor=t["metallic"], roughnessFactor=t["roughness"],
        emissiveFactor=t["rgb"] if t.get("emissive") else None,
        alphaMode="BLEND" if a < 1 else "OPAQUE", doubleSided=a < 1)


def build_parts(h, interior=False):
    """GLB に出す要素を Parts に集める（建物座標 mm → m）。interior=True のときは、内装CG 用に扉（個別ノードで別に出す）とジム機器（形を作る）を除く。"""
    spec = h.spec
    P = Parts()
    for bx in h.boxes:
        grp = STYLE.get(bx.cat, ("その他", None))[0]
        if bx.mat == "glass":
            grp = STYLE["glass"][0]
        for q, mk in classify(h, bx):
            if interior and (mk == "interior_door" or (bx.cat == "door" and bx.tag in ("GD-1", "GD-2"))):
                continue
            P.add_box(grp, bx.level, mk, q)
    facade_extras(h, P)
    exterior_parts(h, P, spec)
    # ジム機器（簡易ボリューム）
    if not interior:
        for name, r, hh, kg in getattr(h, "equipment", []):
            P.add_box("ジム機器", "1F", "equipment", (r[0], r[1], h.fl["1F"], r[2], r[3], h.fl["1F"] + hh))
    return P


def export_glb(h, path, interior=False):
    """interior=True: 内装CG 用（家具・天井・床仕上げ・内壁仕上げ・扉・照明器具を加える。ノード名は「グループ|階|材質キー|ID」）。
    既定は False（dist/model.glb とビューアは従来どおり）。"""
    spec = h.spec
    table = material_table(spec, interior=interior)
    P = build_parts(h, interior=interior)
    scene = trimesh.Scene()
    # 建物座標 → 真北基準（建物中心まわりに alpha 回転）→ Y-up
    rz = trimesh.transformations.rotation_matrix(h.alpha, [0, 0, 1], [h.W / 2000, h.D / 2000, 0])
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]) @ rz
    missing = set()
    for (grp, lvl, mk), ms in sorted(P.d.items(), key=lambda kv: kv[0]):
        mesh = trimesh.util.concatenate(ms)
        mesh.apply_transform(rot)
        if mk not in table:
            missing.add(mk)
            continue
        mesh.visual = trimesh.visual.TextureVisuals(material=_mat(mk, table))
        scene.add_geometry(mesh, node_name=f"{grp}|{lvl}|{mk}", geom_name=f"{grp}|{lvl}|{mk}")
    if interior:
        import furniture
        its = furniture.items(h)
        for grp, lvl, mk, nid, mesh in furniture.meshes(h, its) + furniture.interior_meshes(h, its):
            if mk not in table:
                missing.add(mk)
                continue
            mesh.apply_transform(rot)
            mesh.visual = trimesh.visual.TextureVisuals(material=_mat(mk, table))
            nm = f"{grp}|{lvl}|{mk}" + (f"|{nid}" if nid else "")
            scene.add_geometry(mesh, node_name=nm, geom_name=nm)
    assert not missing, f"材質キーが未定義: {missing}"
    # 隣接建物（高さ 6.5m の簡易ボリューム）— 建物ごとに別ノード（CG で明度を変えるため）
    k = 0
    for pts in h.neighbors:
        poly = Polygon(pts)
        if not poly.is_valid or poly.area < 4e6:
            continue
        c = poly.representative_point()
        base = h.ground(c.x, c.y)
        mesh = prism(poly, base, base + 6500)
        mesh.apply_transform(rot)
        mesh.visual = trimesh.visual.TextureVisuals(material=_mat("neighbor", table))
        nm = f"周辺建物|-|neighbor_{k}"
        scene.add_geometry(mesh, node_name=nm, geom_name=nm)
        k += 1
    # 地形・道路・水路
    for grp, lvl, mk, name, mesh in build_terrain(h, scene, rot):
        mesh.visual = trimesh.visual.TextureVisuals(material=_mat(mk, table))
        mesh.visual.material.doubleSided = True
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.export(path)
    _patch_glb(path, table)
    return scene
