"""内装の3D部材（床仕上げ・天井・内壁ライニング・巾木・框・階段の段鼻と段裏と手すり・窓台・扉・照明器具・ZIP生地）。

furniture.py の interior_meshes() から呼ばれる。座標は建物座標 mm、出力は m の trimesh。
面が同じ高さで重なると Cycles で真っ黒な帯になるため、床仕上げの板（厚 2）は開口部の床（壁の厚み分）にも敷く。
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import box as sbox, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

import furniture_shapes as FS
from geom import decompose

# ---------------------------------------------------------------- 室名 → 仕上げ（C.3）
FLOOR_OF = [("浴室", "floor_sheet"), ("シャワー", "floor_sheet"), ("トイレ", "floor_sheet"), ("洗面", "floor_sheet"), ("ランドリー", "floor_sheet"),
            ("玄関土間", "floor_tile_genkan"), ("ジム", "floor_rubber"), ("シアター", "floor_carpet"), ("前室", "floor_carpet"),
            ("機械室", "floor_machine")]
FLOOR_PRIORITY = ["floor_sheet", "floor_tile_genkan", "floor_rubber", "floor_carpet", "floor_machine", "floor_oak"]
SKIRT_OF = {"floor_oak": ("skirt", 60), "floor_sheet": ("floor_sheet", 100), "floor_rubber": ("floor_rubber", 100), "floor_carpet": ("skirt_theater", 60),
            "floor_machine": None, "floor_tile_genkan": None}


def floor_mat(name):
    for k, m in FLOOR_OF:
        if k in name:
            return m
    return "floor_oak"


def ceiling_mat(name):
    return "ceiling_theater" if "シアター" in name else "ceiling_paint"


def lining_of(name, ch):
    """(材質, 高さ) のリスト。上に壁塗装（ライニングなし）が続く場合は高さが ch より低い。"""
    if "浴室" in name or "シャワー" in name:
        return [("wet_panel", ch)]
    if "洗面" in name or "ランドリー" in name:
        return [("wet_panel", ch)]
    if "トイレ" in name or "玄関土間" in name:
        return [("wainscot", 1000)]
    if "ジム" in name:
        return [("wainscot_gym", 1200)]
    if "シアター" in name or "前室" in name:
        return [("wall_theater", ch)]
    return []


class Cell:
    """床・天井を敷く単位（室、または室の外の空き）。"""

    def __init__(self, floor, name, rect, z, fmat, cmat, extra=False):
        self.floor, self.name, self.rect, self.z, self.fmat, self.cmat, self.extra = floor, name, rect, z, fmat, cmat, extra


def cells(h):
    out = []
    g = h.genkan
    DOMA = h.fl["1F"] - 2 * g["step"]
    SHIKI = h.fl["1F"] - g["step"]
    for r in h.rooms:
        z = DOMA if r.name == "玄関土間" else SHIKI if r.name.startswith("式台") else h.fl[r.floor]
        out.append(Cell(r.floor, r.name, tuple(r.rect), z, floor_mat(r.name), ceiling_mat(r.name)))
    # 室の外の空き（階段の下・階段脇のホール）
    for s in h.stairs:
        out.append(Cell("1F", s.name + "の下", (s.x0, min(s.y_entry, 12000 if s.name == "階段1" else 18125), s.x1, max(s.y_entry, 12000 if s.name == "階段1" else 18125)),
                        h.fl["1F"], "floor_oak", "ceiling_paint", extra=True))
    for fl in ("1F", "2F"):
        out.append(Cell(fl, "ホール（階段脇）", (10650, 9800, 12000, 12000), h.fl[fl], "floor_oak", "ceiling_paint", extra=True))
    out.append(Cell("1F", "階段2前", (3950, 15000, 6000, 15100), h.fl["1F"], "floor_oak", "ceiling_paint", extra=True))
    return out


def _walls_union(h, fl):
    from furniture import wall_rects
    return unary_union(wall_rects(h, fl))


def cell_polys(h):
    """[(Cell, 床ポリゴン, 天井ポリゴン)] 壁の面までぴったり敷く（矩形を 30 広げて壁・別材質の隣室を引く）。"""
    holes2 = [sbox(*s.hole) for s in h.stairs]
    cs = cells(h)
    walls = {fl: _walls_union(h, fl) for fl in ("1F", "2F")}
    out = []
    for c in cs:
        base = sbox(*c.rect).buffer(0 if c.extra else 30, join_style=2)
        others = unary_union([sbox(*o.rect) for o in cs if o is not c and o.floor == c.floor and (o.fmat != c.fmat or o.z != c.z or o.extra != c.extra)])
        fp = base.difference(walls[c.floor]).difference(others)
        cp = base.difference(walls[c.floor]).difference(unary_union([sbox(*o.rect) for o in cs if o is not c and o.floor == c.floor and (o.cmat != c.cmat)]))
        if c.floor == "2F":
            fp = fp.difference(unary_union(holes2))
        if c.floor == "1F":
            cp = cp.difference(unary_union(holes2))
        if c.extra and c.name.endswith("の下"):
            cp = Polygon()
        out.append((c, fp, cp))
    return out


def _polys(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g] if g.area > 100 else []
    return [p for gg in g.geoms for p in _polys(gg)]


# ---------------------------------------------------------------- 壁の面（ライニング・巾木用）
def wall_faces(h, fl):
    """階 fl の壁の「全長の矩形」と、その開口 [(u0,u1,z0,z1)]。 [(軸, c, t, a, b, ops)]"""
    out = []
    for w in h.walls:
        if w.cat not in ("wall", "partition") or w.floor != fl:
            continue
        ops = [(op.u0, op.u1, op.z0, op.z1, op) for op in w.openings]
        out.append((w.axis, w.c, w.t, w.a, w.b, ops))
    return out


def room_edges(h, fl, poly):
    """空気側ポリゴンの辺のうち、壁の面にあるもの: [(軸 'x'|'y', 固定座標 k, u0, u1, 内向き符号 s)]。"""
    poly = orient(poly, 1.0)
    walls = _walls_union(h, fl).buffer(1.0)
    out = []
    rings = [poly.exterior] + list(poly.interiors)
    for ring in rings:
        pts = list(ring.coords)
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            dx, dy = x1 - x0, y1 - y0
            L = math.hypot(dx, dy)
            if L < 5:
                continue
            nx, ny = -dy / L, dx / L              # 左（内側）
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            if not walls.contains(sbox(mx - nx * 2 - 0.5, my - ny * 2 - 0.5, mx - nx * 2 + 0.5, my - ny * 2 + 0.5)):
                continue
            if abs(dy) < 1e-6:
                out.append(("x", y0, min(x0, x1), max(x0, x1), 1 if ny > 0 else -1))
            elif abs(dx) < 1e-6:
                out.append(("y", x0, min(y0, y1), max(y0, y1), 1 if nx > 0 else -1))
    return out


def _holes_for_edge(faces, axis, k, u0, u1, zmax=None):
    """辺と同じ面にある壁の開口（u, z の範囲）。"""
    holes = []
    for (wax, c, t, a, b, ops) in faces:
        if wax != axis:
            continue
        if abs(abs(k - c) - t / 2) > 2:
            continue
        for (o0, o1, z0, z1, op) in ops:
            if o1 <= u0 or o0 >= u1:
                continue
            holes.append((max(o0, u0), z0, min(o1, u1), z1, op))
    return holes


# ---------------------------------------------------------------- 本体
def interior_parts(h, its):
    """{(グループ, 階, 材質キー): MB}  ID なしの内装（階・材質ごとに 1 ノード）と、個別ノード用の {(グループ, 階, 材質キー, ID): MB}。"""
    merged, single = {}, {}

    def MBfor(grp, lvl, key):
        if (grp, lvl, key) not in merged:
            merged[(grp, lvl, key)] = FS.MB()
        return merged[(grp, lvl, key)]

    G = "内装仕上げ"
    cp_all = cell_polys(h)
    faces = {fl: wall_faces(h, fl) for fl in ("1F", "2F")}

    # ---------------- 床・天井
    for c, fp, cp in cp_all:
        for p in _polys(fp):
            MBfor(G, c.floor, c.fmat).slab_poly(c.fmat, p, c.z, c.z + 2)
        if c.name == "ジム":
            zc = h.fl["2F"] - h.slab_t
            for p in _polys(cp):
                MBfor(G, c.floor, "ceiling_paint").slab_poly("ceiling_paint", p, zc - 2, zc)
        elif not c.name.endswith("の下"):
            zc = h.fl[c.floor] + h.ch[c.floor]
            for p in _polys(cp):
                MBfor(G, c.floor, c.cmat).slab_poly(c.cmat, p, zc, zc + 20)

    # ---------------- 開口部の床（壁の厚み分、扉・開口の幅）。黒い帯の対策
    for w in h.walls:
        if w.cat == "insul":
            continue
        for op in w.openings:
            if op.kind != "door" or op.exterior or op.floor not in ("1F", "2F"):
                continue
            # 両側の室の床のうち、ぬれる室を優先
            mats = set()
            for s in (-1, 1):
                off = w.t / 2 + 40
                pt = ((op.u0 + op.u1) / 2, w.c + s * off) if w.axis == "x" else (w.c + s * off, (op.u0 + op.u1) / 2)
                for c in cs_of(cp_all, op.floor):
                    if sbox(*c.rect).buffer(30).contains(sbox(pt[0] - 1, pt[1] - 1, pt[0] + 1, pt[1] + 1)):
                        mats.add(c.fmat)
            mat = next((m for m in FLOOR_PRIORITY if m in mats), "floor_oak")
            q = (op.u0, w.c - w.t / 2, op.u1, w.c + w.t / 2) if w.axis == "x" else (w.c - w.t / 2, op.u0, w.c + w.t / 2, op.u1)
            MBfor(G, op.floor, mat).box(mat, q[0], q[1], op.z0, q[2], q[3], op.z0 + 2)

    # ---------------- ライニング（特殊仕上げ）と巾木
    for c, fp, cp in cp_all:
        if c.extra:
            continue
        fl = c.floor
        ch = h.ch[fl]
        pol = unary_union(_polys(fp)) if not fp.is_empty else Polygon()
        # 室の空気側ポリゴンは「壁の面まで」。床 z の違う玄関土間などは z 基準を c.z にする
        lin = lining_of(c.name, ch)
        sk = None if ("浴室" in c.name or "シャワー" in c.name) else SKIRT_OF.get(c.fmat)
        for p in _polys(pol):
            for (ax, k, u0, u1, s) in room_edges(h, fl, p):
                zf = c.z
                for (mat, hh) in lin:
                    top = zf + hh if hh < ch else h.fl[fl] + ch
                    holes = [(a, b, e, f_) for (a, b, e, f_, op) in _holes_for_edge(faces[fl], ax, k, u0, u1)]
                    for (ua, za, ub, zb_) in decompose((u0, zf, u1, top), holes):
                        t = 3
                        if ax == "x":
                            MBfor(G, fl, mat).box(mat, ua, k if s > 0 else k - t, za, ub, k + t if s > 0 else k, zb_)
                        else:
                            MBfor(G, fl, mat).box(mat, k if s > 0 else k - t, ua, za, k + t if s > 0 else k, ub, zb_)
                if sk:
                    mat, hh = sk
                    holes = [(a, b, e, f_) for (a, b, e, f_, op) in _holes_for_edge(faces[fl], ax, k, u0, u1) if e < zf + 150]
                    for (ua, za, ub, zb_) in decompose((u0, zf + 2, u1, zf + hh), holes):
                        t = 8
                        d0 = 3 if lin else 0               # ライニングの前に出る
                        if ax == "x":
                            MBfor(G, fl, mat).box(mat, ua, (k + d0) if s > 0 else k - d0 - t, za, ub, (k + d0 + t) if s > 0 else k - d0, zb_)
                        else:
                            MBfor(G, fl, mat).box(mat, (k + d0) if s > 0 else k - d0 - t, ua, za, (k + d0 + t) if s > 0 else k - d0, ub, zb_)

    # ---------------- 框（玄関の二重框）と縦手すり
    g = h.genkan
    DOMA = h.fl["1F"] - 2 * g["step"]
    SHIKI = h.fl["1F"] - g["step"]
    FLL = h.fl["1F"]
    x0, x1 = g["doma"][0], g["doma"][2]
    yA = g["doma"][3]                      # 土間と式台の境
    yB = g["shikidai"][3]                  # 式台とホールの境
    mk = MBfor(G, "1F", "kamachi")
    mk.box("kamachi", x0, yA - 10, DOMA, x1, yA + 60, SHIKI + 3)
    mk.box("kamachi", x0, yB - 10, SHIKI, x1, yB + 60, FLL + 3)
    mn = MBfor(G, "1F", "nosing")
    mn.box("nosing", x0, yA - 10, SHIKI + 3, x1, yA + 20, SHIKI + 3.6)
    mn.box("nosing", x0, yB - 10, FLL + 3, x1, yB + 20, FLL + 3.6)
    mh = MBfor(G, "1F", "handrail")
    mh.tube("handrail", (x1 - 57, yA - 100, DOMA + 700), (x1 - 57, yA - 100, FLL + 1700), 17.5, 14)
    for zz in (DOMA + 800, FLL + 1500):
        mh.box("handrail", x1 - 57 - 8, yA - 108, zz, x1, yA - 92, zz + 30)

    # ---------------- 階段: 段鼻・段裏・手すり
    for s in h.stairs:
        stair_parts(h, s, MBfor, G)

    # ---------------- 窓台（額縁: 人造大理石 t20、室内へ 15 出す）
    for w in h.walls:
        if w.cat != "wall" or w.floor not in ("1F", "2F"):
            continue
        for op in w.openings:
            if op.kind != "window" or not op.exterior:
                continue
            s = _inward(h, w)
            cin = w.c + s * (w.t / 2 + 15)
            cmid = w.c
            a, b = sorted((cmid, cin))
            q = (op.u0 - 15, a, op.u1 + 15, b) if w.axis == "x" else (a, op.u0 - 15, b, op.u1 + 15)
            MBfor(G, w.floor, "kamachi").box("kamachi", q[0], q[1], op.z0 - 18, q[2], q[3], op.z0 + 2)

    # ---------------- 照明器具（埋込ダウンライト）
    from furniture import downlights
    for d in downlights(h, its):
        x, y, z = d["p"]
        if d["room"] == "ジム":
            z = h.fl["2F"] - h.slab_t - 2
        m = MBfor("照明器具", d["floor"], "lamp_trim")
        m.cyl("lamp_trim", x, y, 50, z - 3, z + 3, 20)
        f = MBfor("照明器具", d["floor"], "lamp_face")
        f.cyl("lamp_face", x, y, 38, z - 4, z - 3, 20)

    # ---------------- ZIP スクリーンの生地（下ろした状態。昼のカットでは非表示）
    for key, mbx in screen_fabrics(h).items():
        single[key] = mbx
    # ---------------- 扉
    for key, mbx in door_parts(h)[0].items():
        single[key] = mbx
    return merged, single


def cs_of(cp_all, fl):
    return [c for c, _, _ in cp_all if c.floor == fl]


def _inward(h, w):
    """壁 w の内側（建物の中心側）の向き（±1、壁の法線方向の符号）。"""
    c = h.W / 2 if w.axis == "y" else h.D / 2
    return 1 if c > w.c else -1


def stair_parts(h, s, MBfor, G):
    r, T = s.riser, s.tread
    d = s.direction
    half = s.half
    z0 = s.z0
    zl = z0 + half * r
    # --- 段鼻（各段の先端 30、面一＋0.6）
    mn = MBfor(G, "1F", "nosing")
    xa0, xa1 = (s.x0, s.x0 + s.width) if d > 0 else (s.x1 - s.width, s.x1)
    xb0, xb1 = (s.x1 - s.width, s.x1) if d > 0 else (s.x0, s.x0 + s.width)
    for i in range(1, half):
        zt = z0 + i * r
        ya = s.y_entry + d * (i - 1) * T
        y0, y1 = (ya, ya + 30) if d > 0 else (ya - 30, ya)
        mn.box("nosing", xa0, y0, zt, xa1, y1, zt + 0.6)
    for j in range(1, s.n - half):
        zt = zl + j * r
        yb = s.y_turn - d * (j - 1) * T                      # 先端（下り側ではなく登る側の端）
        y0, y1 = (yb - 30, yb) if d > 0 else (yb, yb + 30)
        mn.box("nosing", xb0, y0, zt, xb1, y1, zt + 0.6)
    # --- 段裏の斜めの板（各段の箱の下端を結ぶ。t20、天井塗装）
    ms = MBfor(G, "1F", "ceiling_paint")

    def soffit(xa, xb, y_from, y_to, z_from, slope):
        """斜めの板（厚 20）。上面は y_from で z_from、離れるほど slope で上がる。"""
        ya_, yb_ = sorted((y_from, y_to))
        zt = lambda yy: z_from + slope * abs(yy - y_from)
        corners = []
        for k in range(8):
            xx = xb if (k & 1) else xa
            yy = yb_ if (k & 2) else ya_
            corners.append((xx, yy, zt(yy) if (k & 4) else zt(yy) - 20))
        ms.hexa("ceiling_paint", corners)

    slope = r / T
    # 下の flight（昇り方向 d）。板の上面は「後縁の下端」を通る面: z(y) = z0 - 150 + (|y - y_entry| - T) * slope
    y_s, y_e = s.y_entry + d * T, s.y_turn
    zs = z0 - 150
    soffit(xa0, xa1, y_s, y_e, zs, slope)
    # 上の flight（登る向きは -d）。後縁の下端を通る面: z(y) = zl - 150 + (|y_turn - y| - T) * slope
    y_s2, y_e2 = s.y_turn - d * T, s.y_turn - d * (s.n - half) * T
    soffit(xb0, xb1, y_s2, y_e2, zl - 150, slope)
    # --- 手すり（壁側、段鼻から H800、両端は水平に 300 延ばして壁へ曲げ込む）
    mh = MBfor(G, "1F", "handrail")
    rr = 17.5
    xw = s.x0 + 60 if d > 0 else s.x1 - 60
    xw2 = s.x1 - 60 if d > 0 else s.x0 + 60
    wallx, wallx2 = (s.x0, s.x1) if d > 0 else (s.x1, s.x0)
    # flight a: 先端 y_entry の段鼻 (i=1) の上 800 → 踊場側へ
    za0 = z0 + r + 800
    ya_s = s.y_entry
    ya_e = s.y_turn
    za1 = za0 + (half - 1) * r
    mh.tube("handrail", (xw, ya_s - d * 300, za0), (xw, ya_s, za0), rr, 12)
    mh.tube("handrail", (xw, ya_s, za0), (xw, ya_e, za1), rr, 12)
    mh.tube("handrail", (xw, ya_e, za1), (xw, ya_e + d * 300, za1), rr, 12)
    mh.sphere("handrail", xw, ya_s, za0, rr, seg=8)
    mh.sphere("handrail", xw, ya_e, za1, rr, seg=8)
    mh.tube("handrail", (xw, ya_s - d * 300, za0), (wallx, ya_s - d * 300, za0), rr, 12)
    # flight b: 降りる側（登る向きは -d）
    zb0 = zl + r + 800
    yb_s = s.y_turn
    yb_e = s.y_turn - d * (s.n - half - 1) * T
    zb1 = zb0 + (s.n - half - 1) * r
    mh.tube("handrail", (xw2, yb_s + d * 300, zb0), (xw2, yb_s, zb0), rr, 12)
    mh.tube("handrail", (xw2, yb_s, zb0), (xw2, yb_e, zb1), rr, 12)
    mh.tube("handrail", (xw2, yb_e, zb1), (xw2, yb_e - d * 300, zb1), rr, 12)
    mh.sphere("handrail", xw2, yb_s, zb0, rr, seg=8)
    mh.sphere("handrail", xw2, yb_e, zb1, rr, seg=8)
    mh.tube("handrail", (xw2, yb_e - d * 300, zb1), (wallx2, yb_e - d * 300, zb1), rr, 12)
    # 手すりの支持金物（壁から出る小さな箱、約 1,000 ピッチ）
    for k in range(1, 6):
        t = k / 6
        yy = ya_s + (ya_e - ya_s) * t
        zz = za0 + (za1 - za0) * t
        mh.box("handrail", min(wallx, xw), yy - 12, zz - 50, max(wallx, xw), yy + 12, zz - rr)


# ---------------------------------------------------------------- 扉
def doors(h):
    """内部の扉（片開き・引戸・両開き）の一覧: dict(id, floor, wall, op, type, ...)。"""
    out = []
    for w in h.walls:
        if w.cat == "insul":
            continue
        for op in w.openings:
            if op.kind != "door" or op.exterior or op.floor not in ("1F", "2F") or op.operation == "opening":
                continue
            cx = int((op.u0 + op.u1) / 2) if w.axis == "x" else int(w.c)
            cy = int(w.c) if w.axis == "x" else int((op.u0 + op.u1) / 2)
            out.append(dict(tag=f"x{cx}y{cy}", label=op.label or "D", floor=op.floor, wall=w, op=op,
                            type="slide" if op.operation == "sliding" else ("double" if op.width >= 1400 else "swing")))
    return out


def door_parts(h):
    """個別ノード {(扉, 階, 材質キー, ID): MB} と、開閉の情報 {ID: dict}。"""
    single, info = {}, {}

    def MBfor(floor, key, did):
        if ("扉", floor, key, did) not in single:
            single[("扉", floor, key, did)] = FS.MB()
        return single[("扉", floor, key, did)]

    for dd in doors(h):
        w, op = dd["wall"], dd["op"]
        did = f"{dd['label']}@{dd['tag']}"
        fl = dd["floor"]
        ax = w.axis
        t = w.t
        c = w.c
        u0, u1, z0, z1 = op.u0, op.u1, op.z0, op.z1

        def B(mbb, key, a0, a1, v0, v1, zz0, zz1):
            """壁座標 (u, v=壁芯からの距離) の箱 → 建物座標。"""
            if ax == "x":
                mbb.box(key, a0, c + v0, zz0, a1, c + v1, zz1)
            else:
                mbb.box(key, c + v0, a0, zz0, c + v1, a1, zz1)

        def T_(mbb, key, p0, p1, r, n=10):
            """壁座標 (u, v, z) の円管。"""
            def X(p):
                return (p[0], c + p[1], p[2]) if ax == "x" else (c + p[1], p[0], p[2])
            mbb.tube(key, X(p0), X(p1), r, n)

        mf = MBfor(fl, "door_oak", did)
        ms = MBfor(fl, "stainless", did)
        fw = 20
        # 枠（見付 20、壁の厚み全体）
        B(mf, "door_oak", u0, u0 + fw, -t / 2, t / 2, z0, z1)
        B(mf, "door_oak", u1 - fw, u1, -t / 2, t / 2, z0, z1)
        B(mf, "door_oak", u0 + fw, u1 - fw, -t / 2, t / 2, z1 - fw, z1)
        if dd["type"] == "slide":
            side = 1
            vc = side * (t / 2 + 20)
            B(mf, "door_oak", u0 - 30, u1 + 30, vc - 18, vc + 18, z0 + 10, z1 + 10)
            # 取っ手（縦長の彫り込み = 暗い細い箱）
            mp = MBfor(fl, "joint", did)
            pu = u0 + 130
            B(mp, "joint", pu, pu + 22, vc + 17, vc + 19, z0 + 800, z0 + 1100)
            others = [o for o in w.openings if o is not op]
            prev_end = max([o.u1 for o in others if o.u1 <= u0] + [w.a])
            next_start = min([o.u0 for o in others if o.u0 >= u1] + [w.b])
            sdir = 1 if (next_start - u1) >= (u0 - prev_end) else -1       # 壁の空きが広い側へ引く
            info[did] = dict(type="slide", floor=fl, tag=dd["tag"], axis=ax, side=side, width=op.width, c=c, u0=u0, u1=u1, dir=sdir)
        elif dd["type"] == "double":
            mid = (u0 + u1) / 2
            for k, (a0, a1) in enumerate(((u0 + fw, mid), (mid, u1 - fw))):
                did_k = did + ("a" if k == 0 else "b")
                mf_k = MBfor(fl, "door_oak", did_k)
                ms_k = MBfor(fl, "stainless", did_k)
                B(mf_k, "door_oak", a0 + 1, a1 - 1, -20, 20, z0, z1 - fw)
                lever_u = (a1 - 70) if k == 0 else (a0 + 70)
                for vv in (22, -22):
                    T_(ms_k, "stainless", (lever_u, vv * 0.45, z0 + 1000), (lever_u, vv, z0 + 1000), 26, 12)
                    T_(ms_k, "stainless", (lever_u, vv, z0 + 1000), (lever_u + (-120 if k == 0 else 120), vv, z0 + 1000), 8, 8)
                hinge_u = a0 if k == 0 else a1
                sign = _swing_sign(w, op, 0 if k == 0 else 1)
                px, py = (hinge_u, c) if ax == "x" else (c, hinge_u)
                info[did_k] = dict(type="swing", floor=fl, tag=dd["tag"], axis=ax, pivot=[px, py], sign=sign)
            continue
        else:
            B(mf, "door_oak", u0 + fw + 1, u1 - fw - 1, -20, 20, z0, z1 - fw)
            lever_u = (u1 - fw - 70) if op.hinge == 0 else (u0 + fw + 70)
            dirn = -1 if op.hinge == 0 else 1
            for vv in (22, -22):
                T_(ms, "stainless", (lever_u, vv * 0.45, z0 + 1000), (lever_u, vv, z0 + 1000), 26, 12)
                T_(ms, "stainless", (lever_u, vv, z0 + 1000), (lever_u + dirn * 120, vv, z0 + 1000), 8, 8)
            hinge_u = u0 + fw if op.hinge == 0 else u1 - fw
            px, py = (hinge_u, c) if ax == "x" else (c, hinge_u)
            info[did] = dict(type="swing", floor=fl, tag=dd["tag"], axis=ax, pivot=[px, py], sign=_swing_sign(w, op, op.hinge))
    return single, info


def _swing_sign(w, op, hinge):
    """開く向き（度の符号）。壁が x 向きで u0 側が吊元、swing=+1（+y 側へ開く）なら +90°。"""
    s = (1 if hinge == 0 else -1) * op.swing
    return s if w.axis == "x" else -s


# ---------------------------------------------------------------- ZIP スクリーンの生地
def screen_fabrics(h, north_blackout=True):
    """外付け ZIP スクリーンの下ろした状態の生地。{('外付けスクリーン生地', 階, 材質, ID): MB}"""
    out = {}
    us = h.spec.get("uv_shading", {})
    sides = set(us.get("sides", []))
    e = h.t / 2 + h.ins
    prop = h.spec.get("interior_cg", {}).get("propose_north_blackout", True) if north_blackout else False
    for op in h.openings(exterior=True):
        if op.kind != "window":
            continue
        proposed = False
        if op.side not in sides:
            if prop and op.side == "N" and "主寝室" in op.name:
                proposed = True
            else:
                continue
        blackout = any(k in op.name for k in ("居室", "主寝室"))
        key = "zip_blackout" if blackout else "zip_fabric"
        did = f"{op.floor}-{op.side}-{int(op.u0)}" + ("-proposed" if proposed else "")
        mb = FS.MB()
        a, b = op.u0 - 50, op.u1 + 50
        z0, z1 = op.z0 - 30, op.z1 + 100
        if op.side == "S":
            mb.box(key, a, -e - 18, z0, b, -e - 15, z1)
        elif op.side == "N":
            mb.box(key, a, h.D + e + 15, z0, b, h.D + e + 18, z1)
        elif op.side == "W":
            mb.box(key, -e - 18, a, z0, -e - 15, b, z1)
        else:
            mb.box(key, h.W + e + 15, a, z0, h.W + e + 18, b, z1)
        out[("外付けスクリーン生地", op.floor, key, did)] = mb
    return out
