"""河沿要（仮称）図面シート。すべて house.House モデルから生成する。"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon, box as sbox

from cadlib import Sheet, _text_width, _wrap
from sheetlib import T, emit, hdim, vdim, door_symbol, window_symbol, opening_tag, side_panel, uv_fn
from views import VIEWS, iter_lines, iter_polygons, project

TATAMI = 1.62


def tp(h, z):
    return h.gl_tp + z / 1000.0


# ================================================================ helpers
def fit(h, sh, center_paper, margin=0):
    """敷地の外接矩形の中心を用紙上 center_paper に置く。"""
    x0, y0, x1, y1 = h.site.bounds
    return T(sh, ((x0 + x1) / 2, (y0 + y1) / 2), center_paper)

def frame(h, number, title, scale, label=None):
    sh = Sheet(number, title, scale, h.spec["project"], scale_label=label)
    sh.frame()
    return sh


def grid(h, sh, t, ext=2600, r=3.6):
    R = r * sh.S
    for x, n in zip(h.gx, h.gx_names):
        sh.line(t(x, -ext + R), t(x, h.D + ext - R), "A-GRID")
        sh.grid_bubble(t(x, -ext), n, r)
        sh.grid_bubble(t(x, h.D + ext), n, r)
    for y, n in zip(h.gy, h.gy_names):
        sh.line(t(-ext + R, y), t(h.W + ext - R, y), "A-GRID")
        sh.grid_bubble(t(-ext, y), n, r)
        sh.grid_bubble(t(h.W + ext, y), n, r)


def plan_dims(h, sh, t, floor):
    o = h.outer_dims()
    for side in ("S", "W"):
        ops = [op for op in h.openings(floor=floor, exterior=True) if op.side == side]
        pts = sorted({*h.gx, *[op.u0 for op in ops], *[op.u1 for op in ops]}) if side == "S" else \
            sorted({*h.gy, *[op.u0 for op in ops], *[op.u1 for op in ops]})
        if side == "S":
            hdim(sh, t, pts, -900)
            hdim(sh, t, h.gx, -1450)
            hdim(sh, t, [o[0], o[2]], -2000)
        else:
            vdim(sh, t, pts, -900)
            vdim(sh, t, h.gy, -1450)
            vdim(sh, t, [o[1], o[3]], -2000)
    hdim(sh, t, h.gx, h.D + 1200)
    vdim(sh, t, h.gy, h.W + 1200)


def room_labels(h, sh, t, floor, hgt=2.6):
    for r in h.rooms:
        if r.floor != floor:
            continue
        x, y = r.label_at
        small = (r.rect[2] - r.rect[0]) < 1800 or (r.rect[3] - r.rect[1]) < 1500
        th = 2.0 if small else hgt
        sh.text(r.name, t(x, y + 150), th, "A-ROOM", "MIDDLE_CENTER")
        sub = f"{r.area:.1f}m²"
        if r.habitable or r.area > 12:
            sub += f"（{r.area / TATAMI:.1f}畳）"
        sh.text(sub, t(x, y - (th + 1.2) * sh.S * 0.75), 1.6, "A-ROOM", "MIDDLE_CENTER")


def stair_marks(h, sh, t, floor):
    S = sh.S
    for s in h.stairs:
        d = s.direction
        xa = (s.x0 + s.width / 2) if d > 0 else (s.x1 - s.width / 2)
        xb = (s.x1 - s.width / 2) if d > 0 else (s.x0 + s.width / 2)
        y0 = s.y_entry
        if floor == "1F":
            yc = y0 + d * 5 * s.tread
            sh.circle(t(xa, y0 + d * 150), 0.5 * S, "A-STRS")
            sh.pline(t.pts([(xa, y0 + d * 150), (xa, yc)]), "A-STRS")
            sh.pline(t.pts([(xa - 120, yc - d * 250), (xa, yc), (xa + 120, yc - d * 250)]), "A-STRS")
            for k in (0, 160):
                sh.line(t(s.x0 + 20, yc + d * (180 + k)), t(xa + s.width / 2, yc + d * (480 + k)), "A-STRS", lineweight=25)
            sh.text("UP", t(xa + 120, y0 + d * 400), 1.8, "A-STRS", "MIDDLE_LEFT")
        else:
            yt = s.y_turn
            sh.circle(t(xb, y0 + d * 150), 0.5 * S, "A-STRS")
            sh.pline(t.pts([(xb, y0 + d * 150), (xb, yt - d * 200)]), "A-STRS")
            sh.pline(t.pts([(xb - 120, yt - d * 450), (xb, yt - d * 200), (xb + 120, yt - d * 450)]), "A-STRS")
            sh.text("DN", t(xb - 120, y0 + d * 400), 1.8, "A-STRS", "MIDDLE_RIGHT")


def north_arrow_true(sh, p, r=7):
    sh.north_arrow(p, r)


def legend(sh, x, y, rows):
    P, S = sh.P, sh.S
    cy = y
    for lay, lab, kind in rows:
        a, c = P(x, cy), P(x + 12, cy)
        if kind == "hatch":
            poly = sbox(a[0], a[1] - 1.1 * S, c[0], c[1] + 1.1 * S)
            sh.hatch_polys([poly], layer="A-CUT-HATCH")
            sh.rect(a[0], a[1] - 1.1 * S, c[0], c[1] + 1.1 * S, lay)
        elif kind == "ins":
            poly = sbox(a[0], a[1] - 0.6 * S, c[0], c[1] + 0.6 * S)
            sh.hatch_polys([poly], pattern="ANSI37", spacing=0.6, layer="A-CUT-INS")
            sh.rect(a[0], a[1] - 0.6 * S, c[0], c[1] + 0.6 * S, "A-CUT-LGS", lineweight=18)
        elif kind == "pave":
            poly = sbox(a[0], a[1] - 1.1 * S, c[0], c[1] + 1.1 * S)
            sh.hatch_polys([poly], pattern="NET", spacing=1.2, layer="A-PAVE")
            sh.rect(a[0], a[1] - 1.1 * S, c[0], c[1] + 1.1 * S, lay)
        elif kind == "fence":
            sh.rect(a[0], a[1] - 0.5 * S, c[0], c[1] + 0.5 * S, lay)
            sh.hatch_polys([sbox(a[0], a[1] - 0.5 * S, c[0], c[1] + 0.5 * S)])
        else:
            sh.line(a, c, lay)
        sh.text(lab, P(x + 15, cy - 0.9), 2.0, "A-TEXT")
        cy -= 4.6
    return cy


# ================================================================ site
def site_base(h, sh, t, neighbors=True, contours=False, margin=9000):
    x0, y0, x1, y1 = h.site.bounds
    win = sbox(x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    sh.pline(t.pts(list(win.exterior.coords)), "A-NEIGH", closed=True, lineweight=9)

    def clip_lines(pts, closed=False, layer="A-ROAD", lw=None):
        g = Polygon(pts).exterior if closed else LineString(pts)
        g = g.intersection(win)
        for part in getattr(g, "geoms", [g]):
            if part.is_empty or part.geom_type not in ("LineString", "LinearRing"):
                continue
            kw = {"lineweight": lw} if lw else {}
            sh.pline(t.pts(part.coords), layer, **kw)

    if neighbors:
        for pts in h.neighbors:
            clip_lines(pts, True, "A-NEIGH")
    for r in h.road_edges:
        clip_lines(r["pts"], False, "A-ROAD")
    for w in h.water:
        poly = Polygon(w).intersection(win)
        for p in iter_polygons(poly):
            sh.hatch_polys([Polygon(t.pts(p.exterior.coords))], pattern="ANSI31", spacing=1.5, layer="A-WATER")
            sh.pline(t.pts(p.exterior.coords), "A-WATER", closed=True)
    for pts in h.existing:
        sh.pline(t.pts(pts), "A-HIDDEN", closed=True)
    if contours:
        for c in h.contours:
            clip_lines(c["pts"], False, "A-TERRAIN", 9)
    sh.pline(t.pts(h.site_pts), "A-SITE", closed=True)


def fence_draw(h, sh, t, label=False):
    off = h.fence_t
    inner = h.site.buffer(-off, join_style=2)
    band = h.site.difference(inner)
    for gl in [LineString([g[1], g[2]]).buffer(60, cap_style=2) for g in h.gates]:
        band = band.difference(gl.buffer(off * 2))
    polys = []
    for p in iter_polygons(band):
        polys.append(Polygon(t.pts(p.exterior.coords), [t.pts(r.coords) for r in p.interiors]))
    if polys:
        sh.hatch_polys(polys)
    for p in polys:
        sh.pline(list(p.exterior.coords), "A-FENCE", closed=True)
    for name, a, b in h.gates:
        sh.line(t(*a), t(*b), "A-DOOR", lineweight=35)
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if label:
            sh.text(name, t(m[0], m[1] - 1500), 1.9, "A-TEXT", "MIDDLE_CENTER")


def house_outline(h, sh, t, lw=50):
    o = h.outer_dims()
    sh.rect(*t(o[0], o[1]), *t(o[2], o[3]), "A-CUT", lineweight=lw)


def site_plan(h, number, legal_summary):
    sh = frame(h, number, "配置図・求積図", 500)
    t = fit(h, sh, (125, 160))
    site_base(h, sh, t, contours=True)
    fence_draw(h, sh, t)
    proj = project(h.boxes, "plan", filt=lambda b: b.z1 > h.fgl and b.level != "FDN")
    emit(sh, proj, t, cut_lw=25, vis_lw=9)
    house_outline(h, sh, t)
    # 駐車場・カーポート
    sh.hatch_polys([Polygon(t.pts(h.dotcon.exterior.coords))], pattern="NET", spacing=1.0, layer="A-PAVE")
    cp = h.carport
    sh.rect(*t(cp[0], cp[1]), *t(cp[2], cp[3]), "A-HIDDEN")
    # 頂点番号
    for i, p in enumerate(h.site_pts):
        sh.circle(t(*p), 0.9 * sh.S, "A-SYMB")
        q = Point(p)
        c = h.site.centroid
        dx, dy = p[0] - c.x, p[1] - c.y
        n = math.hypot(dx, dy) or 1
        sh.text(str(i + 1), t(p[0] + dx / n * 2200, p[1] + dy / n * 2200), 1.8, "A-SYMB", "MIDDLE_CENTER")
    # 接道・境界の注記
    labels = [((-30000, 52000), "水路（法定外公共物）／北側道路（幅員4m未満）TP+112.5〜113.0"),
              ((40000, -5000), f"東側道路 幅員約{h.spec['site']['east_road_width'] / 1000:.1f}m（北へ上り TP+109.0→112.9）"),
              ((-20000, -42000), f"南側道路 幅員約{h.spec['site']['south_road_width'] / 1000:.1f}m TP+109.0（設計GL±0）")]
    for (x, y), s in labels:
        sh.text(s, t(x, y), 2.0, "A-TEXT", "MIDDLE_CENTER")
    sh.text("建物（壁式RC造 2階建て）", t(h.W / 2, h.D / 2 + 1500), 2.2, "A-ROOM", "MIDDLE_CENTER")
    sh.text("駐車場（Dotcon+）", t((cp[0] + cp[2]) / 2, cp[1] - 2500), 1.9, "A-TEXT", "MIDDLE_CENTER")
    sh.text("庭・雨水貯留浸透", t(-17000, 28000), 1.9, "A-TEXT", "MIDDLE_CENTER")
    sh.text("破線: 既存建物（解体）", t(-8000, 26000), 1.7, "A-TEXT", "MIDDLE_CENTER")
    for (x, y) in [(8600, 8600), (-18000, 18000), (8000, -24000), (8000, 40000), (30000, 15000), (-10000, -40000), (25000, -25000)]:
        z = h.ground(x, y)
        sh.text(f"+{tp(h, z):.1f}", t(x, y - 1800), 1.6, "A-TERRAIN", "MIDDLE_CENTER")
        sh.line(t(x - 400, y), t(x + 400, y), "A-TERRAIN")
        sh.line(t(x, y - 400), t(x, y + 400), "A-TERRAIN")
    sh.north_arrow(sh.P(30, 270), 6)
    sh.view_title("配置図", "1:500", (18, 22))
    sh.text("敷地境界・道路縁・水路・隣接建物・等高線: 国土地理院 基盤地図情報／標高: DEM5A（TP m）", (18, 15), 2.0, "A-TEXT", paper=True)
    # 座標求積表
    pts = [(p[0] / 1000.0, p[1] / 1000.0) for p in h.site_pts]
    n = len(pts)
    rows = [["点", "X(m)", "Y(m)", "Xn(Yn+1−Yn−1)"]]
    tot = 0.0
    for i in range(n):
        x, y = pts[i]
        v = x * (pts[(i + 1) % n][1] - pts[i - 1][1])
        tot += v
        rows.append([str(i + 1), f"{x:.2f}", f"{y:.2f}", f"{v:.2f}"])
    rows.append(["", "", "倍面積", f"{abs(tot):.2f}"])
    rows.append(["", "", "面積", f"{abs(tot) / 2:.2f} m²"])
    sh.text("座標求積表（建物 X1・Y1 壁芯交点を原点、m）", (250, 280), 2.6, "A-TEXT", paper=True)
    sh.table(250, 277, [12, 30, 30, 48], rows, row_h=4.6, h=1.85)
    sm = legal_summary
    rows2 = [["項目", "面積・比率"],
             ["敷地面積（推定）", f"{sm['site_area']:,.2f} m²（{sm['site_area'] / 3.305785:,.1f}坪）"],
             ["建築面積（壁芯）", f"{sm['building_area']:.2f} m²"],
             ["延べ面積", f"{sm['total']:.2f} m²"],
             ["建ぺい率", f"{sm['coverage'] * 100:.2f}%（≦60%）"],
             ["容積率", f"{sm['far'] * 100:.2f}%（≦200%）"]]
    sh.table(250, 150, [40, 80], rows2, row_h=5.2, h=2.1)
    sh.text("※ 西側境界は標高109.6の点を通り駐車場白線に平行な直線（ご指定）。13〜15は隣接建物からの推定（要測量）。", (250, 115), 1.9, "A-TEXT", paper=True)
    return sh


def exterior_plan(h, number):
    sh = frame(h, number, "外構・雨水排水計画図", 400)
    t = fit(h, sh, (150, 168))
    site_base(h, sh, t, contours=False)
    # 舗装
    sh.hatch_polys([Polygon(t.pts(h.dotcon.exterior.coords))], pattern="NET", spacing=0.9, layer="A-PAVE")
    sh.pline(t.pts(h.dotcon.exterior.coords), "A-PAVE", closed=True)
    ap = h.approach.intersection(h.site.buffer(-h.fence_t))
    for p in iter_polygons(ap):
        sh.pline(t.pts(p.exterior.coords), "A-PAVE", closed=True)
        sh.hatch_polys([Polygon(t.pts(p.exterior.coords))], pattern="ANSI37", spacing=2.5, layer="A-PAVE")
    fence_draw(h, sh, t, label=True)
    proj = project(h.boxes, "plan", filt=lambda b: b.z1 > h.fgl and b.level != "FDN")
    emit(sh, proj, t, cut_lw=25, vis_lw=9)
    house_outline(h, sh, t)
    cp = h.carport
    sh.rect(*t(cp[0], cp[1]), *t(cp[2], cp[3]), "A-HIDDEN")
    for s in h.stalls:
        sh.rect(*t(s[0], s[1]), *t(s[2], s[3]), "A-VIS")
    sh.text("ソーラーカーポート 約90m²／駐車3台", t(cp[2] + 1500, (cp[1] + cp[3]) / 2), 1.7, "A-TEXT", "MIDDLE_LEFT")
    sh.text("建物（壁式RC造 2階建て）", t(h.W / 2, h.D / 2), 2.0, "A-ROOM", "MIDDLE_CENTER")
    sh.text("Dotcon+ 透水舗装", t(cp[2] + 1500, cp[1] - 1500), 1.7, "A-TEXT", "MIDDLE_LEFT")
    sh.text("アプローチ（透水性舗装）", t(5800, -12000), 1.6, "A-TEXT", "MIDDLE_LEFT")
    # 貯留槽・浸透
    tk = h.tank
    sh.rect(*t(tk[0], tk[1]), *t(tk[2], tk[3]), "A-DRAIN")
    sh.line(t(tk[0], tk[1]), t(tk[2], tk[3]), "A-DRAIN")
    sh.text(f"地下雨水貯留槽 {h.spec['exterior']['retention_tank_m3']}m³", t((tk[0] + tk[2]) / 2, tk[1] - 1200), 1.7, "A-TEXT", "MIDDLE_CENTER")
    for ln in h.trench:
        sh.pline(t.pts(ln.coords), "A-DRAIN", lineweight=35)
    sh.text("浸透トレンチ", t(-20000, 38000), 1.7, "A-TEXT", "MIDDLE_CENTER")
    for p in h.infil_pits:
        sh.circle(t(*p), 0.9 * sh.S, "A-DRAIN")
    for p in h.flap:
        sh.rect(*t(p[0] - 500, p[1] - 500), *t(p[0] + 500, p[1] + 500), "A-DRAIN")
        sh.text("排水口（フラップ弁）", t(p[0] + 800, p[1]), 1.5, "A-TEXT", "MIDDLE_LEFT")
    # 外からの流入方向（高い側 → 敷地）
    for (a, b) in [((0, 44000), (0, 36000)), ((-20000, 50000), (-20000, 40000)), ((30000, 22000), (22000, 18000)),
                   ((28000, 0), (21000, -2000))]:
        sh.pline(t.pts([a, b]), "A-FLOOD", lineweight=35)
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        L = 1200
        for s in (2.6, -2.6):
            sh.line(t(*b), t(b[0] - L * math.cos(ang + s / 4), b[1] - L * math.sin(ang + s / 4)), "A-FLOOD", lineweight=35)
    sh.text("表流水の流入（北・東の高い側）", t(14000, 45000), 1.8, "A-LEGAL-TEXT", "MIDDLE_CENTER")
    # 塀天端高さ
    for ln in h.fence_lines:
        L = ln.length
        k = 0
        d = 6000
        while d < L:
            p = ln.interpolate(d).coords[0]
            top = h.fence_top(*p)
            sh.text(f"{(top - h.fgl) / 1000:.1f}", t(*p), 1.4, "A-SYMB", "MIDDLE_CENTER")
            d += 14000
    # レベル
    for (x, y, s) in [(8600, -1500 - 1800, f"1FL GL+{h.fl['1F']:,}"), (-12000, 10000, f"FGL GL+{h.fgl}（現況維持）"),
                      (6000, -31800, "設計GL±0（南側道路 TP+109.0）")]:
        sh.text(s, t(x, y), 1.6, "A-SYMB", "MIDDLE_CENTER")
    sh.north_arrow(sh.P(282, 60), 6)
    sh.view_title("外構・雨水排水計画図", "1:400", (18, 22))
    legend(sh, 300, 280, [("A-FENCE", "RC塀 t=150（数値=FGLからの天端高 m）", "fence"),
                          ("A-PAVE", "Dotcon+ 透水舗装", "pave"),
                          ("A-DRAIN", "浸透トレンチ・浸透桝・貯留槽", "line"),
                          ("A-FLOOD", "表流水の流入方向", "line"),
                          ("A-SITE", "敷地境界（推定）", "line")])
    st = h.ext_storage
    notes = [("h", "内水対策"),
             ("t", f"1. RC塀の基礎〜FGL+{h.spec['requirements']['fence_watertight']}を止水構造。門扉には着脱式止水板 H600"),
             ("t", f"2. Dotcon+ 約{st['dotcon_area']:.0f}m² × 13L/m² ≒ {st['dotcon_l'] / 1000:.1f}m³ の一時貯留"),
             ("t", f"3. 地下貯留槽 {st['tank_m3']}m³＋浸透トレンチ・浸透桝（透水係数は地盤調査で確認）"),
             ("t", "4. 塀の低い位置にフラップ弁付き排水口（道路側溝からの逆流防止）"),
             ("t", "5. 建物: 1FL=GL+1,500、床下は設備ピット、逆流防止弁・排水ポンプ（非常電源）"),
             ("t", f"参考: 時間雨量50mmで敷地全体の流出量は約{h.site.area / 1e6 * 0.05:.0f}m³/h。貯留・浸透は初期雨水の抑制が主目的で、超過分は止水と排水ポンプで対応"),
             ("h", "防犯"),
             ("t", "RC塀 H2.0m（東側の坂道沿いは道路面+1.2m以上）。上部に侵入防止金物、センサーライト・防犯カメラ、門扉は塀と同じ高さ")]
    side_panel(sh, 300, 252, notes, width=105)
    return sh


# ================================================================ plans
def floor_plan(h, floor, number):
    names = {"1F": "1階平面図", "2F": "2階平面図"}
    sh = frame(h, number, names[floor], 100)
    t = T(sh, (0, 0), (52, 78))
    fl = h.fl[floor]
    cut = fl + 1100
    zmin = fl - 1 if floor == "1F" else fl - h.H["1F"] / 2 - 1
    proj = project(h.boxes, "plan", cut=-cut, depth_limit=-zmin if floor == "2F" else -(h.fgl - 1),
                   filt=lambda b: not ((b.cat in ("glass", "door") and b.z0 < cut < b.z1)
                                       or (b.cat == "stair" and b.level != "EXT" and b.z1 > cut)
                                       or (b.cat == "partition" and b.tag == "手すり壁" and floor == "2F")))
    emit(sh, proj, t)
    grid(h, sh, t)
    plan_dims(h, sh, t, floor)
    for w in h.walls:
        if w.cat == "insul":
            continue
        for op in w.openings:
            if op.floor != floor or not (op.z0 < cut < op.z1) or op.operation == "opening":
                continue
            if op.kind == "door":
                door_symbol(sh, t, op)
            else:
                window_symbol(sh, t, op)
            if op.label:
                opening_tag(sh, t, op, offset=650)
    stair_marks(h, sh, t, floor)
    room_labels(h, sh, t, floor)
    if floor == "1F":
        sh.text(f"玄関ポーチ・外部階段 {h.ext_stair['n']}段 蹴上{h.ext_stair['riser']:.0f}（FGL+{h.fgl}→1FL）", t(11200, -3000), 1.7, "A-TEXT", "MIDDLE_LEFT")
    sh.north_arrow(sh.P(395, 268), 7)
    sh.view_title(names[floor], "1:100", (24, 22))
    sh.text(f"{floor[:-1]}FL = 設計GL+{fl:,}（TP+{tp(h, fl):.2f}）／天井高 CH={h.ch[floor]:,}", (24, 15), 2.4, "A-TEXT", paper=True)
    cy = side_panel(sh, 284, 282, [("h", "凡例")])
    cy = legend(sh, 285, cy - 1, [("A-CUT", "RC壁 t=250（耐力壁）", "hatch"), ("A-CUT-LGS", "外断熱100＋外装20", "ins"),
                                    ("A-CUT-LGS", "乾式間仕切（LGS）t=100", "line"), ("A-GRID", "通り芯（壁芯）", "line")])
    notes = [("h", "特記")]
    if floor == "1F":
        notes += [("t", "耐力壁: 外周＋X2・X3・Y2・Y3通り（2階と同じ位置）"),
                  ("t", "窓: FIX（トリプルガラス・樹脂枠・UVカット）。採光=ガラス面積×補正係数3.0"),
                  ("t", "排煙: LDK・居室A・居室B・ジムは機械排煙（令126条の3）"),
                  ("t", "ジム: 浮き床（防振）、遮音ドア Ts-35"),
                  ("t", "床下: 設備ピット（高基礎）。床下点検口は防水扉"),
                  ("t", "機械室: 西系統・東系統（全熱交換・調湿・排煙機）")]
    else:
        notes += [("t", "シアター: 浮き床＋二重壁、前室（緩衝廊下）で二重扉"),
                  ("t", "2階の窓は提案値（各 1.0×0.7m FIX）。無窓居室の排煙は要検討"),
                  ("t", "間仕切: 乾式（LGS＋ボード）、耐震壁は1階と同位置")]
    notes += [("t", "寸法: mm、面積: 壁芯内法の概算")]
    side_panel(sh, 284, cy - 3, notes, width=118)
    return sh


def roof_plan(h, number):
    sh = frame(h, number, "屋根伏図", 100)
    t = T(sh, (0, 0), (52, 78))
    proj = project(h.boxes, "plan", cut=-(h.fl["RF"] + 300), depth_limit=-(h.fl["RF"] - 1))
    emit(sh, proj, t)
    grid(h, sh, t)
    hdim(sh, t, h.gx, -1450)
    vdim(sh, t, h.gy, -1450)
    # 太陽光パネル（屋上）・ドレン
    for i in range(6):
        for j in range(3):
            x0 = 800 + i * 2700
            y0 = 1500 + j * 5000
            sh.rect(*t(x0, y0), *t(x0 + 2500, y0 + 4000), "A-VIS")
            sh.line(t(x0, y0 + 2000), t(x0 + 2500, y0 + 2000), "A-VIS")
    for (x, y) in [(500, 500), (h.W - 500, 500), (500, h.D - 500), (h.W - 500, h.D - 500)]:
        sh.circle(t(x, y), 1.4 * sh.S, "A-SYMB")
        sh.text("RD", t(x + 300, y + 300), 1.5, "A-SYMB")
    sh.text("屋上: 外断熱防水（シート防水）、水勾配 1/50", t(h.W / 2, h.D / 2), 2.2, "A-TEXT", "MIDDLE_CENTER")
    sh.text("太陽光パネル（架台）", t(h.W / 2, h.D / 2 - 1200), 1.8, "A-TEXT", "MIDDLE_CENTER")
    sh.north_arrow(sh.P(395, 268), 7)
    sh.view_title("屋根伏図", "1:100", (24, 22))
    sh.text(f"RFL = 設計GL+{h.fl['RF']:,}／パラペット天端 GL+{h.parapet_top:,}", (24, 15), 2.4, "A-TEXT", paper=True)
    return sh


# ================================================================ elevations / sections
def elevations(h, number):
    sh = frame(h, number, "立面図", 200)
    o = h.outer_dims()
    layout = [("S", "南立面図", (40, 175)), ("E", "東立面図", (240, 175)), ("N", "北立面図", (40, 70)), ("W", "西立面図", (240, 70))]
    for view, title, paper in layout:
        uv = uv_fn(view)
        us = [uv(x, y, 0)[0] for x in (o[0], o[2]) for y in (o[1], o[3])]
        t = T(sh, (min(us), 0), paper)
        proj = project(h.boxes, view, ground=h.fgl, filt=lambda b: b.level != "EXT" or view == "S")
        emit(sh, proj, t, cut_lw=35, vis_lw=18)
        u_lo, u_hi = min(us) - 2500, max(us) + 2500
        sh.line(t(u_lo, h.fgl), t(u_hi, h.fgl), "A-GROUND", lineweight=50)
        sh.line(t(u_lo, 0), t(u_hi, 0), "A-HIDDEN")
        sh.line(t(u_lo, h.fgl + h.spec["site"]["flood_depth"]), t(u_hi, h.fgl + h.spec["site"]["flood_depth"]), "A-FLOOD")
        for name, z in [("パラペット", h.parapet_top), ("RFL", h.fl["RF"]), ("2FL", h.fl["2F"]), ("1FL", h.fl["1F"]),
                        ("FGL", h.fgl), ("設計GL", 0)]:
            sh.line(t(u_lo - 200, z), t(u_lo + 1500, z), "A-SYMB")
            va = "BOTTOM_RIGHT" if name != "設計GL" else "TOP_RIGHT"
            sh.text(f"{name} {'+' if z else '±'}{z:,.0f}", t(u_lo - 400, z + (100 if name != "設計GL" else -100)), 1.6, "A-SYMB", va)
        sh.text("想定浸水深 FGL+1.0m", t(u_hi - 200, h.fgl + h.spec["site"]["flood_depth"] + 150), 1.5, "A-FLOOD", "BOTTOM_RIGHT")
        sh.line(t(min(us), h.fl["1F"]), t(max(us), h.fl["1F"]), "A-VIS")
        sh.text("腰壁 タイル張り", t(max(us) - 300, h.fgl + 250), 1.4, "A-TEXT", "BOTTOM_RIGHT")
        p = t(u_lo, -2400)
        sh.text(title, p, 3.2, "A-TEXT", "BOTTOM_LEFT")
    sh.text(f"外壁: {h.spec['finish']['exterior']}　窓: FIX（トリプルガラス）", (18, 30), 2.2, "A-TEXT", paper=True)
    return sh


def building_sections(h, number):
    sh = frame(h, number, "断面図（建物）", 100)
    o = h.outer_dims()
    defs = [("A", "W", 7000.0, (75, 170), "A-A（X2–X3間、階段1を通る南北断面）"),
            ("B", "S", 3000.0, (75, 55), "B-B（Y1–Y2間、LDK・階段2を通る東西断面）")]
    for key, view, c, paper, title in defs:
        uv = uv_fn(view)
        us = [uv(x, y, 0)[0] for x in (o[0], o[2]) for y in (o[1], o[3])]
        t = T(sh, (min(us), 0), paper)
        ds = VIEWS[view][5]
        proj = project(h.boxes, view, cut=ds * c, ground=-h.base_t,
                       filt=lambda b: b.level != "EXT")
        emit(sh, proj, t)
        u_lo, u_hi = min(us) - 3000, max(us) + 3000
        sh.line(t(u_lo, h.fgl), t(u_hi, h.fgl), "A-GROUND", lineweight=50)
        sh.line(t(u_lo, h.fgl + h.spec["site"]["flood_depth"]), t(u_hi, h.fgl + h.spec["site"]["flood_depth"]), "A-FLOOD")
        for f in h.floors:
            z = h.fl[f] + h.ch[f]
            sh.line(t(min(us) + 400, z), t(max(us) - 400, z), "A-HIDDEN")
        zs = [0, h.fgl, h.fl["1F"], h.fl["2F"], h.fl["RF"], h.parapet_top]
        xl = u_lo + 600
        vdim(sh, t, [h.fgl, h.fl["1F"], h.fl["2F"], h.fl["RF"], h.parapet_top], xl + 900)
        for name, z in zip(["設計GL", "FGL", "1FL", "2FL", "RFL", "パラペット"], zs):
            sh.line(t(xl - 600, z), t(xl + 700, z), "A-SYMB")
            sh.text(f"{name} {'+' if z else '±'}{z:,.0f}", t(xl - 700, z + 80), 1.6, "A-SYMB", "BOTTOM_RIGHT")
        sh.text("想定浸水深 FGL+1.0m", t(u_hi - 200, h.fgl + h.spec["site"]["flood_depth"] + 120), 1.5, "A-FLOOD", "BOTTOM_RIGHT")
        sh.text("床下 設備ピット", t((min(us) + max(us)) / 2, h.fl["1F"] - 800), 1.8, "A-TEXT", "MIDDLE_CENTER")
        grid_u = [(uv(0, g, 0)[0] if view == "W" else uv(g, 0, 0)[0], n) for g, n in zip(h.gy if view == "W" else h.gx,
                                                                                 h.gy_names if view == "W" else h.gx_names)]
        for u, n in grid_u:
            sh.line(t(u, -h.base_t - 300), t(u, h.parapet_top + 800), "A-GRID")
            sh.grid_bubble(t(u, h.parapet_top + 1100), n, 3.0)
        sh.text(f"断面図 {title}", t(u_lo, h.parapet_top + 1700), 3.0, "A-TEXT", "BOTTOM_LEFT")
    side_panel(sh, 300, 282, [("h", "特記"),
                              ("t", f"階高 {h.H['1F']:,}×2／スラブ t={h.slab_t}／壁 RC t={h.t}"),
                              ("t", "天井高 CH=2,600（破線）。天井懐にダクト・浮き床"),
                              ("t", f"1FL=GL+{h.fl['1F']:,}: 想定浸水深(FGL+1.0m)より上"),
                              ("t", "基礎: べた基礎 t=350＋地中梁（RC壁を基礎まで連続）"),
                              ("t", "階段: 蹴上 177.8 × 18段、踏面 240、有効幅 950（令23条 住宅）")], width=105)
    return sh


def site_sections(h, number):
    sh = frame(h, number, "敷地断面図（地形・浸水）", 300)
    defs = [("N", "S", 8625.0, (-40000, 50000), (22, 175), "南北断面（建物中央 X2–X3間）"),
            ("E", "W", 8625.0, (-45000, 35000), (22, 62), "東西断面（建物中央 Y2–Y3間）")]
    for key, view, c, (a0, a1), paper, title in defs:
        if key == "N":
            pts = [(c, y) for y in range(int(a0), int(a1) + 1, 500)]
            uofs = lambda x, y: y - a0
        else:
            pts = [(x, c) for x in range(int(a0), int(a1) + 1, 500)]
            uofs = lambda x, y: x - a0
        t = T(sh, (0, 0), paper)
        prof = [(uofs(x, y), h.ground(x, y)) for x, y in pts]
        sh.pline(t.pts(prof), "A-TERRAIN", lineweight=35)
        # 建物断面（簡易: 外形）
        o = h.outer_dims()
        if key == "N":
            u0, u1 = o[1] - a0, o[3] - a0
        else:
            u0, u1 = o[0] - a0, o[2] - a0
        poly = sbox(*t(u0, h.fgl), *t(u1, h.parapet_top))
        sh.hatch_polys([poly], pattern="ANSI31", spacing=1.5)
        sh.rect(*t(u0, h.fgl), *t(u1, h.parapet_top), "A-CUT", lineweight=35)
        for f in ("1F", "2F", "RF"):
            sh.line(t(u0, h.fl[f]), t(u1, h.fl[f]), "A-VIS")
        # 敷地境界・塀
        line = LineString(pts)
        inter = line.intersection(h.site.boundary)
        for p in getattr(inter, "geoms", [inter]):
            if p.is_empty:
                continue
            u = uofs(p.x, p.y)
            top = h.fence_top(p.x, p.y)
            sh.rect(*t(u - 150, min(h.fgl, h.ground(p.x, p.y)) - 300), *t(u + 150, top), "A-FENCE")
            sh.text(f"RC塀 天端GL+{top / 1000:.2f}", t(u, top + 400), 1.5, "A-TEXT", "BOTTOM_CENTER")
        # 水路
        for w in h.water:
            wl = line.intersection(Polygon(w))
            if not wl.is_empty:
                for seg in getattr(wl, "geoms", [wl]):
                    us_ = [uofs(*q) for q in seg.coords]
                    sh.rect(*t(min(us_), -1500), *t(max(us_), h.fgl - 600), "A-WATER")
                    sh.text("水路", t((min(us_) + max(us_)) / 2, -2400), 1.6, "A-WATER", "MIDDLE_CENTER")
        # 浸水・GL
        L = prof[-1][0]
        sh.line(t(0, 0), t(L, 0), "A-HIDDEN")
        sh.line(t(0, h.fgl + h.spec["site"]["flood_depth"]), t(L, h.fgl + h.spec["site"]["flood_depth"]), "A-FLOOD")
        sh.text("想定浸水深 FGL+1.0m（TP+{:.2f}）".format(tp(h, h.fgl + 1000)), t(L, h.fgl + 1100), 1.6, "A-FLOOD", "BOTTOM_RIGHT")
        sh.text("設計GL±0（TP+109.0）", t(L, 100), 1.6, "A-TEXT", "BOTTOM_RIGHT")
        for (u, z) in prof[::16]:
            sh.text(f"{tp(h, z):.1f}", t(u, z - 900), 1.3, "A-TERRAIN", "MIDDLE_CENTER")
        sh.text(title + "（縦横同縮尺）", t(0, h.parapet_top + 3500), 2.8, "A-TEXT", "BOTTOM_LEFT")
        lab = (("南側道路", 2000), ("北側道路", L - 4000)) if key == "N" else (("西側隣地", 2000), ("東側道路", L - 6000))
        for s, u in lab:
            sh.text(s, t(u, 6500), 1.8, "A-TEXT", "MIDDLE_CENTER")
    side_panel(sh, 300, 282, [("h", "地形（DEM5A）"),
                              ("t", "敷地 TP+109.3〜109.6（ほぼ平坦）"),
                              ("t", "北側道路 TP+112.5〜113.0（敷地より約3.2m高い）"),
                              ("t", "東側道路 TP+109.0→112.9（北へ上り）"),
                              ("t", "→ 敷地は北・東からの表流水が集まる低い側。RC塀下部の止水と排水で対応"),
                              ("t", "がけ（高さ2m超）からの離れ: 北 約11.1m ≧ 2H=6.4m、東 約9.4m ≧ 2H=6.6m（東京都建築安全条例6条）")], width=105)
    return sh


# ================================================================ structure / details
def wall_plan(h, number, wall_rows):
    sh = frame(h, number, "基礎伏図・耐力壁配置図", 100)
    t = T(sh, (0, 0), (45, 64))
    e = h.t / 2
    polys = []
    for w in h.walls:
        if w.floor != "1F" or w.cat != "wall":
            continue
        x0, y0, _, x1, y1, _ = w.rect(w.a, w.b, 0, 1)
        polys.append(sbox(*t(x0, y0), *t(x1, y1)))
        for op in w.openings:
            ox0, oy0, _, ox1, oy1, _ = w.rect(op.u0, op.u1, 0, 1)
            sh.rect(*t(ox0, oy0), *t(ox1, oy1), "A-HIDDEN")
    from shapely.ops import unary_union
    u = unary_union(polys)
    sh.hatch_polys(list(iter_polygons(u)))
    for pts in iter_lines(u):
        sh.pline(pts, "S-COLS")
    b = [bx for bx in h.boxes if bx.tag == "基礎スラブ"][0]
    sh.rect(*t(b.x0, b.y0), *t(b.x1, b.y1), "S-FNDN")
    grid(h, sh, t)
    hdim(sh, t, h.gx, -1450)
    vdim(sh, t, h.gy, -1450)
    sh.text("べた基礎 t=350（外周 500 張出し）", t(h.W / 2, -1000), 1.8, "S-TEXT", "MIDDLE_CENTER")
    sh.view_title("基礎伏図・耐力壁配置図（1階）", "1:100", (24, 22))
    sh.text("網掛け=RC耐力壁 t=250（1・2階 同位置）、破線=開口", (24, 15), 2.2, "A-TEXT", paper=True)
    sh.text("壁量・壁式構造の規定（平13国交告1026号）", (250, 280), 2.6, "A-TEXT", paper=True)
    sh.table(250, 276, [26, 26, 34, 36, 36], wall_rows, row_h=5.4, h=1.9)
    return sh


def details(h, number):
    sh = frame(h, number, "RC塀・止水・透水舗装 詳細図", 30)
    P, S = sh.P, sh.S

    def hatch_rect(x0, y0, x1, y1):
        sh.rect(x0, y0, x1, y1, "A-CUT", lineweight=50)
        sh.hatch_polys([sbox(x0, y0, x1, y1)])

    # (1) RC塀 断面
    x, y = P(55, 100)
    hatch_rect(x - 600, y - 900, x + 600, y - 500)
    hatch_rect(x - 75, y - 500, x + 75, y + 2000)
    sh.line((x - 1500, y), (x + 1500, y), "A-GROUND", lineweight=50)
    sh.text("FGL", (x - 1500, y + 60), 1.8, "A-SYMB")
    sh.line((x - 75, y + 600), (x - 900, y + 600), "A-FLOOD")
    sh.text("止水範囲 FGL+600", (x - 900, y + 650), 1.6, "A-FLOOD")
    for zz in range(0, 2400, 200):
        sh.circle((x - 35, y - 450 + zz), 6, "S-REBAR")
        sh.circle((x + 35, y - 450 + zz), 6, "S-REBAR")
    sh.dim((x + 500, y), (x + 500, y + 2000), (x + 500, y), 90)
    sh.dim((x + 1000, y - 900), (x + 1000, y), (x + 1000, y - 900), 90)
    sh.dim((x - 600, y - 1200), (x + 600, y - 1200), (x - 600, y - 1200), 0)
    sh.text("(1) RC塀 断面 S=1:30", P(25, 185), 3.0, "A-TEXT")
    sh.text("壁 t=150 縦横 D10@200 ダブル／基礎 1,200×400・根入れ 900", P(25, 179), 1.9, "A-TEXT")
    sh.text("天端に笠木・侵入防止金物、打継ぎ部に止水板", P(25, 175), 1.9, "A-TEXT")
    # (2) 排水口＋フラップ弁
    x, y = P(135, 100)
    hatch_rect(x - 75, y - 500, x + 75, y + 1500)
    sh.rect(x - 75, y + 50, x + 75, y + 200, "A-DRAIN")
    sh.line((x + 75, y + 200), (x + 200, y + 20), "A-DRAIN", lineweight=35)
    sh.line((x - 1500, y), (x + 1500, y), "A-GROUND", lineweight=50)
    sh.text("敷地側", (x - 1300, y + 300), 1.9, "A-TEXT")
    sh.text("道路・水路側", (x + 300, y + 300), 1.9, "A-TEXT")
    sh.text("(2) 排水口 □150＋フラップ弁 S=1:30", P(108, 185), 3.0, "A-TEXT")
    sh.text("外側からの逆流を防ぐ。点検・清掃が可能な位置に設置", P(108, 179), 1.9, "A-TEXT")
    # (3) Dotcon+ 断面
    x, y = P(190, 110)
    layers = [("Dotcon+ 600角 t=150（目地10mm から浸透）", 150), ("砕石路盤 t=150（単粒度砕石）", 150),
              ("透水シート", 10), ("路床（現況土・透水試験で確認）", 300)]
    cy = y
    for i, (name, th) in enumerate(layers):
        sh.rect(x, cy - th, x + 2440, cy, "A-CUT" if i == 0 else "A-VIS")
        if i == 0:
            for k in range(4):
                sh.rect(x + k * 610, cy - th, x + k * 610 + 600, cy, "A-CUT", lineweight=35)
        sh.text(name, (x + 2600, cy - th / 2), 1.8, "A-TEXT", "MIDDLE_LEFT")
        cy -= th
    sh.text("(3) 透水舗装（駐車場）断面 S=1:30", P(190, 185), 3.0, "A-TEXT")
    sh.text("一時貯留 約13L/m²。車両荷重に応じた製品仕様を確認", P(190, 179), 1.9, "A-TEXT")
    # (4) 止水板（門扉部 立面）
    x, y = P(120, 222)
    hatch_rect(x - 2650, y, x - 2500, y + 1300)
    hatch_rect(x + 2500, y, x + 2650, y + 1300)
    sh.text("（塀端部 H2,000 の下部を表示）", (x + 2700, y + 1100), 1.6, "A-TEXT")
    sh.rect(x - 2500, y, x + 2500, y + 600, "A-DOOR", lineweight=35)
    sh.line((x - 3200, y), (x + 3200, y), "A-GROUND", lineweight=50)
    sh.dim((x - 2500, y - 300), (x + 2500, y - 300), (x - 2500, y - 300), 0)
    sh.dim((x + 2900, y), (x + 2900, y + 600), (x + 2900, y), 90)
    sh.text("着脱式止水板", (x, y + 300), 2.0, "A-TEXT", "MIDDLE_CENTER")
    sh.text("(4) 車両門扉部 着脱式止水板 H600（立面）S=1:30", P(25, 278), 3.0, "A-TEXT")
    sh.text("車両門扉 W5,000・人用 W1,200・勝手口 W1,000。止水板は門扉の近くに保管", P(25, 272), 1.9, "A-TEXT")
    side_panel(sh, 250, 270, [("h", "特記"),
                              ("t", "RC塀は令62条の8（補強コンクリートブロック造の塀）の対象外。風圧力・地震力に対する構造計算で安全を確認する"),
                              ("t", "東側の坂道沿いで塀が道路との高低差（2m超）を受ける区間は、擁壁として工作物確認申請の対象（令138条）"),
                              ("t", "塀は境界の内側に設置。北側は水路の管理境界との協議に従う"),
                              ("t", "雨水浸透施設は、地盤調査（透水係数・地下水位）と八王子市の指導・助成制度を確認して決定")], width=150)
    return sh


def cover(h, dl, sm):
    sh = frame(h, "A-00", "表紙・図面リスト・計画概要", 1, label="—")
    pr = h.spec["project"]
    sh.text(pr["name"], (24, 262), 9.0, "A-TEXT", paper=True)
    sh.text(f"{pr['phase']}図　／　{pr['date']}　／　{pr['designer']}", (24, 250), 3.6, "A-TEXT", paper=True)
    sh.line(sh.P(24, 246), sh.P(396, 246), "A-SYMB", lineweight=50)
    rows = [["項目", "内容"],
            ["建設地", pr["location"]],
            ["主要用途", h.spec["requirements"]["use"]],
            ["用途地域", h.spec["site"]["zoning"]],
            ["敷地面積", f"{sm['site_area']:,.2f} m²（推定・要測量）"],
            ["建築面積", f"{sm['building_area']:.2f} m²（建ぺい率 {sm['coverage'] * 100:.2f}%）"],
            ["延べ面積", f"{sm['total']:.2f} m²（容積率 {sm['far'] * 100:.2f}%）"],
            ["構造・階数", "壁式鉄筋コンクリート造 地上2階"],
            ["高さ", f"最高高さ {h.parapet_top / 1000:.2f}m（設計GL基準）"],
            ["階高・床高", f"1FL GL+{h.fl['1F']:,}／階高 3,200×2"],
            ["地盤", f"設計GL＝南側道路 TP+{h.gl_tp}／FGL GL+{h.fgl}（現況維持）"],
            ["外構", "RC塀 H2.0m（止水構造）・Dotcon+ 透水舗装・雨水貯留浸透"],
            ["根拠資料", "docs/kawazanyo_design_brief_v3.md、国土地理院 基盤地図情報・DEM5A"]]
    sh.text("計画概要", (24, 238), 4.0, "A-TEXT", paper=True)
    sh.table(24, 233, [36, 160], rows, row_h=7.0, h=2.5)
    sh.text("図面リスト", (236, 238), 4.0, "A-TEXT", paper=True)
    sh.table(236, 233, [20, 112, 30], [["図番", "図面名称", "縮尺"]] + [list(r) for r in dl], row_h=6.6, h=2.4)
    return sh
