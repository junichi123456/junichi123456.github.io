"""3D DXF（MESH エンティティ）の書き出し。AutoCAD 2010+・FreeCAD・BricsCAD。Jw_cad・LibreCAD は 3D 非対応。

建物ローカル mm（原点 = X1・Y1 壁芯交点、z=0 = 設計 GL）で、既存の平面 DXF（dist/dxf/*.dxf）と同じ原点・向き。
レイヤー名 3D-<階>-<カテゴリ>（例 3D-1F-WALL、3D-SITE-FENCE、3D-SITE-BOUNDARY-OLD）。色は材質表の true color。
"""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from pathlib import Path

import ezdxf
import numpy as np
from ezdxf.colors import rgb2int
from shapely.geometry import LineString, Point, Polygon, box as sbox

import model3d as M

from . import common as C
from .manifest import COORD_LOCAL

CAT = {"wall": "WALL", "partition": "PARTITION", "insul": "INSULATION", "slab": "SLAB", "glass": "WINDOW", "door": "DOOR", "stair": "STAIR",
       "footing": "FOOTING", "column": "COLUMN", "mullion": "MULLION", "blind": "BLIND", "parapet": "PARAPET"}


class Collector:
    """(レイヤー, 材質キー) ごとに三角形メッシュ（mm）を集める。"""

    def __init__(self):
        self.d = defaultdict(list)

    def add(self, layer, key, mesh_m):
        if mesh_m is not None and len(mesh_m.faces):
            v = np.asarray(mesh_m.vertices) * 1000.0
            self.d[(layer, key)].append((v, np.asarray(mesh_m.faces)))

    def add_box(self, layer, key, q):
        self.add(layer, key, M.mbox(*q))


def collect(h):
    col = Collector()
    for bx in h.boxes:
        if bx.level == "EXT":
            lay = "3D-SITE-" + CAT.get(bx.cat, bx.cat.upper()) + ("-" + bx.tag if False else "")
        else:
            lay = f"3D-{bx.level}-{CAT.get(bx.cat, bx.cat.upper())}"
        for q, mk in M.classify(h, bx):
            col.add_box(lay, mk, q)
    fgl = h.fgl
    # 塀（2m 区間）
    for li, ln in enumerate(h.fence_lines):
        L = ln.length
        d, pi = 0.0, 0
        while d < L - 1:
            d2 = min(L, d + 2000)
            seg = LineString([ln.interpolate(d).coords[0], ln.interpolate(d2).coords[0]])
            c = seg.interpolate(0.5, normalized=True)
            top = h.fence_top(c.x, c.y)
            base = min(h.fgl, h.ground(c.x, c.y)) - 100
            off = seg.parallel_offset(h.fence_t / 2, "left")
            if not h.fence_poly.contains(off.interpolate(0.5, normalized=True)):
                off = seg.parallel_offset(h.fence_t / 2, "right")
            k = int(hashlib.sha1(f"{li}-{pi}".encode()).hexdigest(), 16) % 5 + 1
            col.add("3D-SITE-FENCE", f"fence_{k}", M.prism(off.buffer(h.fence_t / 2, cap_style=2), base, top))
            d, pi = d2, pi + 1
    for name, x0, x1, yg, hh in h.gate_leaves:
        yc = yg + 75
        col.add_box("3D-SITE-GATE", "gate_panel", (x0, yc - 30, fgl + 30, x1, yc + 30, fgl + hh))
    for (x0, y0, x1, y1) in h.gate_piers:
        col.add_box("3D-SITE-GATE", "concrete", (x0, y0, fgl - 150, x1, y1, fgl + 2050))
    # 舗装
    site_in = h.fence_poly.buffer(-h.fence_t)
    for p in list(M.polys_of(h.dotcon)) + list(M.polys_of(h.approach.intersection(site_in))) + [h.dotcon_farm] + list(M.polys_of(h.dotcon_garden)):
        if isinstance(p, Polygon):
            col.add("3D-SITE-PAVING", "dotcon", M.prism(p, fgl - 150, fgl + 20))
    for p in M.polys_of(h.forecourt):
        col.add("3D-SITE-PAVING", "porous_concrete", M.prism(p, fgl - 100, fgl + 20))
    # パーゴラ・カーポート（架台は箱、PV は傾斜箱）
    spec = h.spec
    pg = spec["exterior"]["solar_pergola"]
    x0, y0, x1, y1 = h.pergola
    zb = max(h.ground((x0 + x1) / 2, (y0 + y1) / 2), fgl)
    tn = math.tan(math.radians(pg["tilt"]))
    head = lambda y: zb + h.pergola_h + (y - y0) * tn
    for i in range(5):
        x = x0 + i * (x1 - x0) / 4
        for y in (y0, y1):
            col.add_box("3D-SITE-PERGOLA", "steel_frame", (x - 75, y - 75, zb, x + 75, y + 75, head(y)))
        col.add("3D-SITE-PERGOLA", "steel_frame", M.tbox(x, (y0 + y1) / 2, (head(y0) + head(y1)) / 2 - 75, 100, (y1 - y0) / math.cos(math.radians(pg["tilt"])), 150, pg["tilt"]))
    rows, nmod = 7, 16
    pitch = (y1 - y0) / rows
    pw = pitch * pg["coverage"]
    mw = (x1 - x0) / nmod
    for r in range(rows):
        yc = y0 + (r + 0.5) * pitch
        for i in range(nmod):
            col.add("3D-SITE-PV", "pv", M.tbox(x0 + (i + 0.5) * mw, yc, head(yc) + 81.5, mw - 70, pw - 50, 40, pg["tilt"]))
    cp = h.carport
    cph = spec["exterior"]["carport"]["h"]
    for (x, y) in [(cp[0], cp[1]), (cp[2] - 200, cp[1]), (cp[0], cp[3] - 200), (cp[2] - 200, cp[3] - 200)]:
        col.add_box("3D-SITE-CARPORT", "steel_frame", (x, y, fgl, x + 200, y + 200, fgl + cph))
    col.add_box("3D-SITE-CARPORT", "steel_frame", (cp[0], cp[1], fgl + cph, cp[2], cp[3], fgl + cph + 80))
    nx, ny = 8, 4
    mw2, md = (cp[2] - cp[0]) / nx, (cp[3] - cp[1]) / ny
    for i in range(nx):
        for j in range(ny):
            xc, yc = cp[0] + (i + 0.5) * mw2, cp[1] + (j + 0.5) * md
            col.add_box("3D-SITE-PV", "pv", (xc - mw2 / 2 + 35, yc - md / 2 + 35, fgl + cph + 80, xc + mw2 / 2 - 35, yc + md / 2 - 35, fgl + cph + 122))
    # 地形（敷地内 2m グリッド）
    import trimesh
    minx, miny, maxx, maxy = h.site.bounds
    step = 2000.0
    idx, verts, tris = {}, [], []
    def vid(i, j):
        if (i, j) not in idx:
            x, y = minx + i * step, miny + j * step
            idx[(i, j)] = len(verts)
            verts.append((x * 1e-3, y * 1e-3, h.ground(x, y) * 1e-3))
        return idx[(i, j)]
    for i in range(int((maxx - minx) // step) + 2):
        for j in range(int((maxy - miny) // step) + 2):
            if h.site.contains(Point(minx + (i + .5) * step, miny + (j + .5) * step)):
                a, b, c, d = vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)
                tris += [(a, b, c), (a, c, d)]
    if tris:
        col.add("3D-SITE-TERRAIN", "ground_wild", trimesh.Trimesh(np.array(verts), np.array(tris), process=False))
    # 家具（面数上限つき）
    import furniture as FU
    from .ifc import _decimate
    for it in FU.items(h):
        meshes, _ = _decimate(FU.build_item(h, it).meshes())
        for k, m in meshes.items():
            col.add(f"3D-{it.floor}-FURNITURE", k, m)
    return col


def build_doc(h):
    table = M.material_table(h.spec, interior=True)
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4                      # mm
    doc.header["$MEASUREMENT"] = 1
    msp = doc.modelspace()
    col = collect(h)
    n = 0
    for (layer, key), parts in sorted(col.d.items()):
        if layer not in doc.layers:
            doc.layers.add(layer)
        vs, fs, base = [], [], 0
        for v, f in parts:
            vs.append(v)
            fs.append(f + base)
            base += len(v)
        V, Fc = np.vstack(vs), np.vstack(fs)
        # 頂点を丸め・統合（MESH のサイズを抑える）
        Vr = np.round(V, 1)
        uniq, inv = np.unique(Vr, axis=0, return_inverse=True)
        Fi = inv.reshape(-1)[Fc]
        ok = (Fi[:, 0] != Fi[:, 1]) & (Fi[:, 1] != Fi[:, 2]) & (Fi[:, 0] != Fi[:, 2])
        mesh = msp.add_mesh(dxfattribs={"layer": layer, "true_color": rgb2int(C.hex_rgb(table[key]["color"]))})
        with mesh.edit_data() as md:
            md.vertices = [tuple(map(float, p)) for p in uniq]
            md.faces = [tuple(int(i) for i in f) for f in Fi[ok]]
        n += 1
    # 敷地境界・寄付地の線（z=0）
    for lay, geom, tc in (("3D-SITE-BOUNDARY", h.site, "#2F5B4F"), ("3D-SITE-BOUNDARY-OLD", h.site_gross, "#C0392B"), ("3D-SITE-DONATION", h.donation_poly, "#E67E22")):
        if lay not in doc.layers:
            doc.layers.add(lay)
        msp.add_polyline3d([(x, y, 0.0) for x, y in geom.exterior.coords], close=True, dxfattribs={"layer": lay, "true_color": rgb2int(C.hex_rgb(tc))})
    return doc, n


def write(h, outdir, mf):
    doc, n = build_doc(h)
    p = Path(outdir) / "model_3d.dxf"
    doc.saveas(p)
    mf.add(p, "3D DXF(MESH, R2010)", COORD_LOCAL + "。既存の平面 DXF と同じ原点・向き", note=f"{n} MESH, {len(doc.layers)} レイヤー")
