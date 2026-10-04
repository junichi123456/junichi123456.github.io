"""投影エンジン：建物モデルの Box 群から平面・立面・断面の 2D 線分を生成する。

- 切断面（cut）にかかる要素 → 材料ごとに和集合をとった切断形状（RC はハッチング）
- 切断面より奥の要素 → 手前から順に描き、手前の形状で隠れる部分を除去（隠線処理）
"""
from __future__ import annotations

from collections import defaultdict

from shapely.geometry import LineString, MultiLineString, Polygon, box as sbox
from shapely.ops import unary_union

# ビュー定義: (u軸, u符号, v軸, v符号, 奥行軸, 奥行符号)
VIEWS = {
    "plan": ("x", 1, "y", 1, "z", -1),   # 上から見下ろす
    "S": ("x", 1, "z", 1, "y", 1),       # 南から北を見る
    "N": ("x", -1, "z", 1, "y", -1),     # 北から南を見る
    "E": ("y", 1, "z", 1, "x", -1),      # 東から西を見る
    "W": ("y", -1, "z", 1, "x", 1),      # 西から東を見る
}


def _rng(b, axis, sign):
    a0, a1 = getattr(b, axis + "0"), getattr(b, axis + "1")
    v0, v1 = sign * a0, sign * a1
    return (min(v0, v1), max(v0, v1))


def klass(b):
    if b.mat == "insul":
        return "insul"
    if b.mat == "glass":
        return "glass"
    if b.cat in ("door", "blind"):
        return "door"
    if b.cat == "stair":
        return "stair"
    if b.mat == "lgs":
        return "lgs"
    return "concrete"


class Projection:
    def __init__(self, cut_polys, visible):
        self.cut = cut_polys      # {klass: geometry}
        self.visible = visible    # [(klass, geometry)]

    def transformed(self, fn):
        from shapely.affinity import affine_transform
        return Projection({k: fn(g) for k, g in self.cut.items()}, [(k, fn(g)) for k, g in self.visible])


def project(boxes, view, cut=None, depth_limit=None, ground=None, filt=None):
    """cut / depth_limit は奥行座標（符号付き）。ground: v<ground を地中として隠す。"""
    ua, us, va, vs, da, ds = VIEWS[view]
    cut_parts = defaultdict(list)
    groups = defaultdict(list)
    for b in boxes:
        if filt and not filt(b):
            continue
        u0, u1 = _rng(b, ua, us)
        v0, v1 = _rng(b, va, vs)
        d0, d1 = _rng(b, da, ds)
        if u1 - u0 < 1e-6 or v1 - v0 < 1e-6:
            continue
        rect = sbox(u0, v0, u1, v1)
        k = klass(b)
        if cut is not None and d0 < cut < d1:
            cut_parts[k].append(rect)
            continue
        if cut is not None and d1 <= cut:
            continue       # 視点側（切断面より手前）
        if depth_limit is not None and d0 > depth_limit:
            continue
        groups[(round(d0, 1), k)].append(rect)
    cut_geo = {k: unary_union(v).buffer(0) for k, v in cut_parts.items()}
    occ = unary_union(list(cut_geo.values())) if cut_geo else Polygon()
    if ground is not None:
        occ = occ.union(sbox(-1e7, -1e7, 1e7, ground))
    visible = []
    for key in sorted(groups):
        _, k = key
        g = unary_union(groups[key]).buffer(0)
        vis = g.difference(occ)
        if not vis.is_empty:
            # 可視部分の輪郭のうち、もとの形状の境界上にある線だけを描く
            lines = vis.boundary.intersection(g.boundary.buffer(0.5))
            lines = _lines_only(lines)
            if not lines.is_empty:
                visible.append((k, lines))
        occ = occ.union(g)
    return Projection(cut_geo, visible)


def _lines_only(geom):
    out = []
    stack = [geom]
    while stack:
        g = stack.pop()
        if g.is_empty:
            continue
        if isinstance(g, LineString):
            out.append(g)
        elif isinstance(g, MultiLineString) or hasattr(g, "geoms"):
            stack.extend(g.geoms)
    from shapely.ops import linemerge
    if not out:
        return MultiLineString()
    m = linemerge(MultiLineString(out))
    return m


def iter_lines(geom):
    """幾何形状から座標列（ポリライン）を列挙。"""
    if geom is None or geom.is_empty:
        return
    t = geom.geom_type
    if t == "LineString" or t == "LinearRing":
        yield list(geom.coords)
    elif t == "Polygon":
        yield list(geom.exterior.coords)
        for r in geom.interiors:
            yield list(r.coords)
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from iter_lines(g)


def iter_polygons(geom):
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield geom
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from iter_polygons(g)
