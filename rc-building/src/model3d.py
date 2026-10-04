"""3D モデル出力（glTF バイナリ .glb）。図面と同じ House モデル＋国土地理院の地形・周辺データから生成する。"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import trimesh
from shapely.geometry import LineString, Point, Polygon

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
}


def _mat(rgba, double=False):
    return trimesh.visual.material.PBRMaterial(
        baseColorFactor=[int(v * 255) for v in rgba], metallicFactor=0.0, roughnessFactor=0.9,
        alphaMode="BLEND" if rgba[3] < 1 else "OPAQUE", doubleSided=double or rgba[3] < 1)


def _prism(poly, z0, z1):
    m = trimesh.creation.extrude_polygon(poly, (z1 - z0))
    m.apply_translation([0, 0, z0])
    return m


def export_glb(h, path):
    S = 1 / 1000.0
    parts = defaultdict(list)
    for bx in h.boxes:
        grp, rgba = STYLE.get(bx.cat, ("その他", (0.8, 0.8, 0.8, 1.0)))
        if bx.mat == "glass":
            grp, rgba = STYLE["glass"]
        ext = np.array([bx.x1 - bx.x0, bx.y1 - bx.y0, bx.z1 - bx.z0]) * S
        if (ext <= 0).any():
            continue
        m = trimesh.creation.box(extents=ext)
        m.apply_translation(np.array([(bx.x0 + bx.x1) / 2, (bx.y0 + bx.y1) / 2, (bx.z0 + bx.z1) / 2]) * S)
        parts[(grp, bx.level or "-", rgba)].append(m)

    def poly_m(pts):
        return Polygon([(x * S, y * S) for x, y in pts])

    # 塀（区間ごとに天端高を変える）
    for ln in h.fence_lines:
        L = ln.length
        d = 0.0
        while d < L - 1:
            d2 = min(L, d + 2000)
            seg = LineString([ln.interpolate(d).coords[0], ln.interpolate(d2).coords[0]])
            c = seg.interpolate(0.5, normalized=True)
            top = h.fence_top(c.x, c.y)
            base = min(h.fgl, h.ground(c.x, c.y)) - 100
            # 敷地の内側へ t/2 寄せた位置に配置
            off = seg.parallel_offset(h.fence_t / 2, "left")
            if not h.site.contains(off.interpolate(0.5, normalized=True)):
                off = seg.parallel_offset(h.fence_t / 2, "right")
            poly = off.buffer(h.fence_t / 2, cap_style=2)
            parts[("RC塀", "-", (0.70, 0.69, 0.66, 1.0))].append(_prism(poly_m(poly.exterior.coords), base * S, top * S))
            d = d2
    # 駐車場（Dotcon+）・アプローチ
    for p in [h.dotcon]:
        parts[("外構（Dotcon+舗装）", "-", (0.62, 0.66, 0.60, 1.0))].append(_prism(poly_m(p.exterior.coords), (h.fgl - 150) * S, (h.fgl + 20) * S))
    ap = h.approach.intersection(h.site.buffer(-h.fence_t))
    for p in getattr(ap, "geoms", [ap]):
        if p.geom_type == "Polygon":
            parts[("外構（Dotcon+舗装）", "-", (0.78, 0.75, 0.68, 1.0))].append(_prism(poly_m(p.exterior.coords), (h.fgl - 100) * S, (h.fgl + 25) * S))
    # ソーラーパーゴラ（日よけ付き菜園）: 柱＋梁＋すき間をあけたパネル列（南向き傾斜）
    pg = h.spec["exterior"]["solar_pergola"]
    x0, y0, x1, y1 = h.pergola
    ph = h.pergola_h
    zb = h.ground((x0 + x1) / 2, (y0 + y1) / 2)
    zb = max(zb, h.fgl)
    import math as _m
    for x in [x0 + i * (x1 - x0) / 4 for i in range(5)]:
        for y in (y0, y1):
            hh = ph + (y - y0) * _m.tan(_m.radians(pg["tilt"]))
            m = trimesh.creation.box(extents=[0.15, 0.15, hh * S])
            m.apply_translation([x * S, y * S, (zb + hh / 2) * S])
            parts[("ソーラーパーゴラ", "-", (0.40, 0.33, 0.25, 1.0))].append(m)
    rows = 7
    pitch = (y1 - y0) / rows
    pw = pitch * pg["coverage"]
    for r in range(rows):
        yc = y0 + (r + 0.5) * pitch
        z = zb + ph + (yc - y0) * _m.tan(_m.radians(pg["tilt"])) + 100
        m = trimesh.creation.box(extents=[(x1 - x0) * S, pw * S, 0.05])
        rot_t = trimesh.transformations.rotation_matrix(_m.radians(pg["tilt"]), [1, 0, 0])
        m.apply_transform(rot_t)
        m.apply_translation([(x0 + x1) / 2 * S, yc * S, z * S])
        parts[("ソーラーパーゴラ", "-", (0.12, 0.18, 0.32, 1.0))].append(m)
    # 菜園の畝
    for k in range(4):
        yb = y0 + 800 + k * (y1 - y0 - 1600) / 3.6
        m = trimesh.creation.box(extents=[(x1 - x0 - 2000) * S, 0.9, 0.25])
        m.apply_translation([(x0 + x1) / 2 * S, (yb + 450) * S, (zb + 125) * S])
        parts[("菜園", "-", (0.45, 0.33, 0.20, 1.0))].append(m)
    # 3台用ソーラーカーポート
    cp = h.carport
    cph = h.spec["exterior"]["carport"]["h"]
    for (x, y) in [(cp[0], cp[1]), (cp[2] - 200, cp[1]), (cp[0], cp[3] - 200), (cp[2] - 200, cp[3] - 200)]:
        m = trimesh.creation.box(extents=[0.2, 0.2, cph * S])
        m.apply_translation([(x + 100) * S, (y + 100) * S, (h.fgl + cph / 2) * S])
        parts[("カーポート", "-", (0.35, 0.37, 0.40, 1.0))].append(m)
    m = trimesh.creation.box(extents=[(cp[2] - cp[0]) * S, (cp[3] - cp[1]) * S, 0.12])
    m.apply_translation([(cp[0] + cp[2]) / 2 * S, (cp[1] + cp[3]) / 2 * S, (h.fgl + cph + 60) * S])
    parts[("カーポート", "-", (0.12, 0.18, 0.32, 1.0))].append(m)
    # ジム機器（簡易ボリューム）
    for name, r, hh, kg in getattr(h, "equipment", []):
        m = trimesh.creation.box(extents=[(r[2] - r[0]) * S, (r[3] - r[1]) * S, hh * S])
        m.apply_translation([(r[0] + r[2]) / 2 * S, (r[1] + r[3]) / 2 * S, (h.fl["1F"] + hh / 2) * S])
        parts[("ジム機器", "1F", (0.25, 0.27, 0.30, 1.0))].append(m)
    # 隣接建物（高さ 6.5m の簡易ボリューム）
    for pts in h.neighbors:
        poly = Polygon(pts)
        if not poly.is_valid or poly.area < 4e6:
            continue
        c = poly.representative_point()
        base = h.ground(c.x, c.y)
        parts[("周辺建物", "-", (0.86, 0.86, 0.88, 1.0))].append(_prism(poly_m(poly.exterior.coords), base * S, (base + 6500) * S))
    # 水路
    for w in h.water:
        poly = Polygon(w)
        c = poly.representative_point()
        parts[("水路", "-", (0.30, 0.55, 0.80, 1.0))].append(_prism(poly_m(poly.exterior.coords), -1600 * S, -1500 * S))

    scene = trimesh.Scene()
    # 建物座標 → 真北基準（建物中心まわりに alpha 回転）→ Y-up
    rz = trimesh.transformations.rotation_matrix(h.alpha, [0, 0, 1], [h.W / 2000, h.D / 2000, 0])
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]) @ rz
    for (grp, lvl, rgba), ms in sorted(parts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        mesh = trimesh.util.concatenate(ms)
        mesh.apply_transform(rot)
        mesh.visual = trimesh.visual.TextureVisuals(material=_mat(rgba))
        scene.add_geometry(mesh, node_name=f"{grp}|{lvl}", geom_name=f"{grp}|{lvl}")
    # 地形（DEM、2m グリッド）— 敷地内は FGL、建物下は除外
    d = h._dem
    xs = np.arange(-70, 61, 2.0)
    ys = np.arange(-70, 66, 2.0)
    V, F = [], {True: [], False: []}
    idx = {}
    for j, ym in enumerate(ys):
        for i, xm in enumerate(xs):
            x, y = (xm - h.ox) * 1000, (ym - h.oy) * 1000
            z = h.fgl if h.site.contains(Point(x, y)) else h.ground(x, y)
            idx[(i, j)] = len(V)
            V.append([x * S, y * S, (z - 30) * S])
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            a, b, c, e = idx[(i, j)], idx[(i + 1, j)], idx[(i + 1, j + 1)], idx[(i, j + 1)]
            cx = (V[a][0] + V[c][0]) / 2 * 1000
            cy = (V[a][1] + V[c][1]) / 2 * 1000
            F[h.site.contains(Point(cx, cy))] += [[a, b, c], [a, c, e]]
    for inside, name, col in ((True, "地形（敷地）|-", (0.77, 0.82, 0.67, 1.0)), (False, "地形（周辺）|-", (0.80, 0.78, 0.74, 1.0))):
        terr = trimesh.Trimesh(vertices=np.array(V), faces=np.array(F[inside]), process=False)
        terr.remove_unreferenced_vertices()
        terr.visual = trimesh.visual.TextureVisuals(material=_mat(col, double=True))
        terr.apply_transform(rot)
        scene.add_geometry(terr, node_name=name, geom_name=name)
    scene.export(path)
    return scene
