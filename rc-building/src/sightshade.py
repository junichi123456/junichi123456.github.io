"""日影（太陽光パネルの影損失）と視線（敷地外から玄関が見えるか）の検討。

障害物は鉛直プリズム（2D ポリゴン＋下端高さ・上端高さ）で表し、
光線・視線との交差を厳密に求める（2D の交差区間で高さの範囲が重なるか）。
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.strtree import STRtree

LAT = 35.667


class Prisms:
    def __init__(self, items):
        self.items = [(p, z0, z1, name) for p, z0, z1, name in items if p.is_valid and not p.is_empty]
        self.tree = STRtree([it[0] for it in self.items])

    def blocked(self, a, b, za, zb):
        """3D 線分 a(za)→b(zb) がいずれかの障害物を通るか。"""
        seg = LineString([a, b])
        L = seg.length
        if L == 0:
            return None
        for idx in self.tree.query(seg):
            poly, z0, z1, name = self.items[int(idx)]
            inter = seg.intersection(poly)
            if inter.is_empty:
                continue
            parts = getattr(inter, "geoms", [inter])
            for part in parts:
                coords = list(part.coords) if hasattr(part, "coords") else []
                if not coords:
                    continue
                ts = [seg.project(Point(c)) / L for c in coords]
                t0, t1 = min(ts), max(ts)
                if t1 - t0 < 1e-6 and part.geom_type != "Point":
                    continue
                zlo = za + (zb - za) * t0
                zhi = za + (zb - za) * t1
                lo, hi = min(zlo, zhi), max(zlo, zhi)
                if hi >= z0 and lo <= z1:
                    return name
        return None


# ---------------------------------------------------------------- 日射
def sun_positions(step_h=0.5):
    """各月21日の太陽位置（高度, 方位[南=0, 西=+]）と重み（快晴時の法線面直達日射）。"""
    phi = math.radians(LAT)
    out = []
    for m in range(12):
        n = 21 + int(30.4 * m)
        d = math.radians(23.45 * math.sin(math.radians(360 * (284 + n) / 365)))
        t = 4.0
        while t <= 20.0:
            H = math.radians(15 * (t - 12))
            sa = math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.cos(H)
            if sa > 0.05:
                alt = math.asin(sa)
                az = math.atan2(math.sin(H), math.cos(H) * math.sin(phi) - math.tan(d) * math.cos(phi))
                am = 1 / sa
                dni = 1000 * 0.7 ** (am ** 0.678)
                out.append((alt, az, dni, m + 1))
            t += step_h
    return out


def shading_loss(h, rect, z_panel, tilt_deg, obstacles, nx=6, ny=4, diffuse=0.4):
    """パネル面（rect, 高さ z_panel）の年間影損失率（直達のみ影響、散乱 diffuse は損失なしと仮定）。"""
    x0, y0, x1, y1 = rect
    tilt = math.radians(tilt_deg)
    pts = [(x0 + (i + 0.5) * (x1 - x0) / nx, y0 + (j + 0.5) * (y1 - y0) / ny) for i in range(nx) for j in range(ny)]
    tot = lost = 0.0
    by_month = {}
    for alt, az, dni, m in sun_positions():
        cos_inc = math.sin(alt) * math.cos(tilt) + math.cos(alt) * math.sin(tilt) * math.cos(az)
        if cos_inc <= 0:
            continue
        w = dni * cos_inc
        dx, dy = -math.sin(az) * math.cos(alt), -math.cos(az) * math.cos(alt)
        horiz = math.cos(alt)
        reach = 60000.0
        n_sh = 0
        for (px, py) in pts:
            zp = z_panel + (py - y0) * math.tan(tilt)
            b = (px + dx / horiz * reach, py + dy / horiz * reach)
            zb = zp + reach * math.tan(alt)
            if obstacles.blocked((px, py), b, zp, zb):
                n_sh += 1
        frac = n_sh / len(pts)
        tot += w
        lost += w * frac
        bm = by_month.setdefault(m, [0.0, 0.0])
        bm[0] += w
        bm[1] += w * frac
    direct_loss = lost / tot if tot else 0
    return dict(direct_loss=direct_loss, loss=direct_loss * (1 - diffuse),
                by_month={m: (v[1] / v[0] if v[0] else 0) for m, v in sorted(by_month.items())})


def solar_obstacles(h):
    items = []
    o = h.outer_dims()
    items.append((box(o[0], o[1], o[2], o[3]), -1e4, h.parapet_top, "本館"))
    for pts in h.neighbors:
        p = Polygon(pts)
        c = p.representative_point()
        g = h.ground(c.x, c.y)
        items.append((p, g - 100, g + 6500, "隣接建物（高さ6.5m仮定）"))
    for (a0, b0, a1, b1) in h.screen:
        items.append((box(a0, b0, a1, b1), h.fgl - 400, h.screen_top, "目隠し壁"))
    items += fence_prisms(h)
    return Prisms(items)


def fence_prisms(h, gates_open=True):
    items = []
    for ln in h.fence_lines:
        L = ln.length
        d = 0.0
        while d < L - 1:
            d2 = min(L, d + 2000)
            seg = LineString([ln.interpolate(d).coords[0], ln.interpolate(d2).coords[0]])
            c = seg.interpolate(0.5, normalized=True)
            off = seg.parallel_offset(h.fence_t / 2, "left")
            if not h.site.contains(off.interpolate(0.5, normalized=True)):
                off = seg.parallel_offset(h.fence_t / 2, "right")
            items.append((off.buffer(h.fence_t / 2 + 20, cap_style=2), -1e4, h.fence_top(c.x, c.y), "RC塀"))
            d = d2
    return items


def pv_shading(h):
    obs = solar_obstacles(h)
    pg = h.spec["exterior"]["solar_pergola"]
    z_pg = max(h.fgl, h.ground((h.pergola[0] + h.pergola[2]) / 2, (h.pergola[1] + h.pergola[3]) / 2)) + pg["height"] + 100
    r_pg = shading_loss(h, h.pergola, z_pg, pg["tilt"], obs)
    cp = h.spec["exterior"]["carport"]
    r_cp = shading_loss(h, h.carport, h.fgl + cp["h"] + 100, 3, obs)
    return dict(pergola=r_pg, carport=r_cp)


# ---------------------------------------------------------------- 視線
def view_obstacles(h, with_screen=True):
    items = []
    o = h.outer_dims()
    items.append((box(o[0], o[1], o[2], o[3]), -1e4, h.parapet_top, "本館"))
    items += fence_prisms(h)
    if with_screen:
        for (a0, b0, a1, b1) in h.screen:
            items.append((box(a0, b0, a1, b1), h.fgl - 400, h.screen_top, "目隠し壁"))
    cp = h.carport
    items.append((box(*cp), h.fgl + 2400, h.fgl + 2650, "カーポート屋根"))
    if getattr(h, "canopy", None):
        items.append((box(*h.canopy), h.canopy_z, h.canopy_z + 150, "庇"))
    return Prisms(items)


def edge_class_of(h, x, y):
    best = None
    for (a, b, k), c in zip(h.site_edges, h.edge_class):
        d = LineString([a, b]).distance(Point(x, y))
        if best is None or d < best[0]:
            best = (d, c)
    return best[1]


def entrance_visibility(h, eye=1500, with_screen=True, step=1000, only=None):
    """敷地境界の外側 1.5m の線上（道路・隣地）から、玄関ドア面が見えるか。"""
    obs = view_obstacles(h, with_screen)
    door = h.entrance
    y_face = -h.t / 2 - h.ins - 20
    targets = [(door.u0 + (door.u1 - door.u0) * fx, y_face, h.fl["1F"] + dz)
               for fx in (0.1, 0.5, 0.9) for dz in (300, 1100, 1900)]
    ring = h.site.exterior.parallel_offset(1500, "right") if False else h.site.buffer(1500, join_style=2).exterior
    L = ring.length
    vis = []
    n = int(L // step)
    for i in range(n):
        p = ring.interpolate(i * step)
        if only and edge_class_of(h, p.x, p.y) not in only:
            continue
        ze = h.ground(p.x, p.y) + eye
        seen = [t for t in targets if obs.blocked((p.x, p.y), (t[0], t[1]), ze, t[2]) is None]
        if seen:
            vis.append((p.x, p.y, len(seen)))
    nn = n if not only else sum(1 for i in range(n) if edge_class_of(h, *ring.interpolate(i * step).coords[0]) in only)
    return dict(n=nn, visible=vis, ratio=len(vis) / nn if nn else 0)
