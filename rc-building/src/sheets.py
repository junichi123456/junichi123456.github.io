"""各図面シートの作図。すべて建物モデル (design.Building) から生成する。"""
from __future__ import annotations

import math

from shapely.geometry import box as sbox

import legal
from cadlib import Sheet, _text_width
from views import VIEWS, iter_lines, iter_polygons, project

VIS_LAYER = {"concrete": "A-VIS", "lgs": "A-VIS", "glass": "A-GLAZ", "door": "A-DOOR", "stair": "A-STRS"}


class T:
    """ビュー座標 (u, v)[mm] → シートのモデル座標。anchor のモデル点を用紙 paper 位置に置く。"""

    def __init__(self, sheet, anchor, paper):
        self.s = sheet
        self.ax, self.ay = anchor
        self.px, self.py = paper[0] * sheet.S, paper[1] * sheet.S

    def __call__(self, u, v):
        return (self.px + u - self.ax, self.py + v - self.ay)

    def pts(self, seq):
        return [self(u, v) for u, v in seq]


def uv_fn(view):
    ua, us, va, vs, _, _ = VIEWS[view]
    return lambda x, y, z: (us * {"x": x, "y": y, "z": z}[ua], vs * {"x": x, "y": y, "z": z}[va])


def emit(sh: Sheet, proj, t: T, cut_lw=None, vis_lw=None):
    from shapely.affinity import translate
    dx, dy = t(0, 0)
    for k, g in proj.cut.items():
        g2 = translate(g, dx, dy)
        polys = list(iter_polygons(g2))
        if k in ("concrete", "stair"):
            if polys:
                sh.hatch_polys(polys, spacing=1.0 if sh.S <= 100 else 0.8)
            for pts in iter_lines(g2):
                sh.pline(pts, "A-CUT", **({"lineweight": cut_lw} if cut_lw else {}))
        elif k == "lgs":
            for pts in iter_lines(g2):
                sh.pline(pts, "A-CUT-LGS")
        else:
            for pts in iter_lines(g2):
                sh.pline(pts, VIS_LAYER[k])
    for k, g in proj.visible:
        g2 = translate(g, dx, dy)
        for pts in iter_lines(g2):
            sh.pline(pts, VIS_LAYER[k], **({"lineweight": vis_lw} if vis_lw else {}))


# ======================================================================= plans
PLAN_ANCHOR_PAPER = (24.0, 56.0)   # 敷地南西角の用紙位置


def plan_frame(b, number, title, scale=100):
    sh = Sheet(number, title, scale, b.spec["project"])
    sx0, sy0, _, _ = b.site_rect()
    t = T(sh, (sx0, sy0), PLAN_ANCHOR_PAPER)
    sh.frame()
    return sh, t


def draw_site_lines(sh, b, t, label=True):
    x0, y0, x1, y1 = b.site_rect()
    sh.pline(t.pts([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]), "A-SITE", closed=True)
    rw = b.spec["site"]["road"]["width"]
    if label:
        sh.text(f"道路境界線", t((x1 - 4200), y0 + 250), 2.0, "A-TEXT")
        sh.text(f"前面道路（{b.spec['site']['road']['kind']}） 幅員 {rw / 1000:.1f}m", t((x0 + x1) / 2, y0 - 1100), 2.6,
                "A-TEXT", "MIDDLE_CENTER")
        sh.text("隣地境界線", t(x0 + 250, y1 - 700), 2.0, "A-TEXT")


def draw_grid(sh, b, t, view="plan", ext=(2900, 2900, 2900, 2900), bubble_r=4.0, sides=("S", "W", "N", "E")):
    """平面の通り芯。ext: (南, 西, 北, 東) の外側距離。"""
    es, ew, en, ee = ext
    r = bubble_r * sh.S
    for x, name in zip(b.gx, b.gx_names):
        y_lo = -es if "S" in sides else -600
        y_hi = b.D + en if "N" in sides else b.D + 600
        sh.line(t(x, y_lo + r), t(x, y_hi - r), "A-GRID")
        if "S" in sides:
            sh.grid_bubble(t(x, y_lo), name, bubble_r)
        if "N" in sides:
            sh.grid_bubble(t(x, y_hi), name, bubble_r)
    for y, name in zip(b.gy, b.gy_names):
        x_lo = -ew if "W" in sides else -600
        x_hi = b.W + ee if "E" in sides else b.W + 600
        sh.line(t(x_lo + r, y), t(x_hi - r, y), "A-GRID")
        if "W" in sides:
            sh.grid_bubble(t(x_lo, y), name, bubble_r)
        if "E" in sides:
            sh.grid_bubble(t(x_hi, y), name, bubble_r)


def hdim(sh, t, xs, y):
    for a, c in zip(xs, xs[1:]):
        if c - a < 1:
            continue
        p1, p2 = t(a, y), t(c, y)
        sh.dim(p1, p2, p1, 0)


def vdim(sh, t, ys, x):
    for a, c in zip(ys, ys[1:]):
        if c - a < 1:
            continue
        p1, p2 = t(x, a), t(x, c)
        sh.dim(p1, p2, p1, 90)


def plan_dims(b, sh, t, floor):
    e = b.wt / 2
    hb = b.col[0] / 2
    # 南・西: 開口寸法 / スパン / 全体
    for side in ("S", "W"):
        ops = [op for op in b.openings(floor=floor, exterior=True) if op.side == side]
        grid = b.gx if side == "S" else b.gy
        pts = sorted({*grid, *[op.u0 for op in ops], *[op.u1 for op in ops]})
        if side == "S":
            hdim(sh, t, pts, -1000)
            hdim(sh, t, grid, -1600)
            hdim(sh, t, [grid[0] - hb, grid[-1] + hb], -2200)
        else:
            vdim(sh, t, pts, -1000)
            vdim(sh, t, grid, -1600)
            vdim(sh, t, [grid[0] - hb, grid[-1] + hb], -2200)
    hdim(sh, t, b.gx, b.D + 1000)
    hdim(sh, t, [0, b.W], b.D + 1600)
    vdim(sh, t, b.gy, b.W + 1000)
    vdim(sh, t, [0, b.D], b.W + 1600)


def door_symbol(sh, t, op, label=True):
    w = op.wall
    c, th = w.c, w.t
    u0, u1 = op.u0, op.u1
    if w.axis == "x":
        P = lambda u, n: t(u, n)
    else:
        P = lambda u, n: t(n, u)
    if op.operation == "swing":
        uh = u0 if op.hinge == 0 else u1
        uo = u1 if op.hinge == 0 else u0
        s = op.swing
        n0 = c + s * th / 2
        hp = P(uh, n0)
        op_pt = P(uh, n0 + s * op.width)
        sh.line(hp, op_pt, "A-DOOR", lineweight=35)
        cl = P(uo, n0)
        a_c = math.degrees(math.atan2(cl[1] - hp[1], cl[0] - hp[0])) % 360
        a_o = math.degrees(math.atan2(op_pt[1] - hp[1], op_pt[0] - hp[0])) % 360
        if (a_o - a_c) % 360 == 90:
            sh.arc(hp, op.width, a_c, a_o, "A-DOOR")
        else:
            sh.arc(hp, op.width, a_o, a_c, "A-DOOR")
    elif op.operation in ("auto", "sliding"):
        if op.operation == "auto":
            m = (u0 + u1) / 2
            sh.pline([P(u0 - op.width * 0.15, c - 25), P(m + 30, c - 25)], "A-DOOR", lineweight=35)
            sh.pline([P(m - 30, c + 25), P(u1 + op.width * 0.15, c + 25)], "A-DOOR", lineweight=35)
        else:
            sh.pline([P(u0, c + th / 2 + 40), P(u1 + 100, c + th / 2 + 40)], "A-DOOR", lineweight=35)
            sh.line(P(u0, c + th / 2 + 40), P(u0, c - th / 2), "A-DOOR")
    elif op.operation == "ev":
        sh.pline([P(u0, c - 30), P(u1, c - 30)], "A-DOOR", lineweight=35)
        sh.pline([P(u0, c + 30), P(u1, c + 30)], "A-DOOR", lineweight=35)


def window_symbol(sh, t, op):
    w = op.wall
    c = w.c
    P = (lambda u, n: t(u, n)) if w.axis == "x" else (lambda u, n: t(n, u))
    u0, u1 = op.u0, op.u1
    m = (u0 + u1) / 2
    if op.name == "引違い窓":
        sh.pline([P(u0, c - 20), P(m + 40, c - 20)], "A-GLAZ", lineweight=25)
        sh.pline([P(m - 40, c + 20), P(u1, c + 20)], "A-GLAZ", lineweight=25)
    else:
        sh.pline([P(u0, c), P(u1, c)], "A-GLAZ", lineweight=25)


def opening_tag(sh, t, op, offset=750):
    w = op.wall
    m = (op.u0 + op.u1) / 2
    if op.exterior:
        out = {"S": 1, "W": 1, "N": -1, "E": -1}.get(op.side, -op.swing)
    else:
        out = -op.swing if op.operation == "swing" else -1
    n = w.c + out * (w.t / 2 + offset)
    if op.kind == "door" and op.operation == "swing" and out == op.swing:
        n = w.c + out * (w.t / 2 + op.width + 300)
    p = t(m, n) if w.axis == "x" else t(n, m)
    S = sh.S
    lab = op.label
    tw = _text_width(lab, 1.8) + 1.6
    sh.rect(p[0] - tw / 2 * S, p[1] - 1.5 * S, p[0] + tw / 2 * S, p[1] + 1.5 * S, "A-TEXT")
    sh.text(lab, p, 1.8, "A-TEXT", "MIDDLE_CENTER")
    if op.alt_entry:
        q = (p[0] + (tw / 2 + 3.0) * S, p[1])
        tri = [(q[0] - 2.0 * S, q[1] + 1.6 * S), (q[0] + 2.0 * S, q[1] + 1.6 * S), (q[0], q[1] - 1.8 * S)]
        sh.pline(tri, "A-ALT", closed=True)
        h = sh.msp.add_hatch(color=1, dxfattribs={"layer": "A-ALT"})
        h.paths.add_polyline_path(tri)


def stair_marks(b, sh, t, floor, cut_z):
    """階段の昇降表示（UP/DN 矢印・切断線）。"""
    fls = [f for f in b.flights if f.floor == floor]
    S = sh.S
    if fls:
        fa = fls[0]
        k = int((cut_z - fa.z_start) / fa.riser)
        yc = fa.y_start + min(k, fa.risers - 1) * fa.tread
        xm = (fa.x0 + fa.x1) / 2
        # 切断線（二重斜線）
        for dy in (0, 180):
            sh.line(t(fa.x0 - 50, yc - 250 + dy), t(fa.x1 + 50, yc + 250 + dy), "A-STRS", lineweight=25)
        sh.pline(t.pts([(xm, fa.y_start + 100), (xm, yc - 200)]), "A-STRS")
        sh.pline(t.pts([(xm - 120, yc - 450), (xm, yc - 200), (xm + 120, yc - 450)]), "A-STRS")
        sh.circle(t(xm, fa.y_start + 100), 0.5 * S, "A-STRS")
        sh.text("UP", t(xm + 150, fa.y_start + 300), 2.0, "A-STRS")
    order = b.floors + ["RF"]
    i = order.index(floor)
    if i > 0:
        below = [f for f in b.flights if f.floor == order[i - 1]]
        fb = below[1]
        xm = (fb.x0 + fb.x1) / 2
        y0, y1 = 7600, fb.y_start - 200
        sh.circle(t(xm, y0), 0.5 * S, "A-STRS")
        sh.pline(t.pts([(xm, y0), (xm, y1)]), "A-STRS")
        sh.pline(t.pts([(xm - 120, y1 - 250), (xm, y1), (xm + 120, y1 - 250)]), "A-STRS")
        sh.text("DN", t(xm + 150, y0 + 200), 2.0, "A-STRS")


def ev_mark(b, sh, t, floor=True):
    ex0, ey0, ex1, ey1 = b.ev
    e = b.wt / 2
    a, c = (ex0 + e, ey0 + e), (ex1 - e, ey1 - e)
    sh.line(t(*a), t(*c), "A-SYMB")
    sh.line(t(a[0], c[1]), t(c[0], a[1]), "A-SYMB")
    if floor:
        sh.rect(*t(a[0] + 150, a[1] + 250), *t(c[0] - 150, c[1] - 150), "A-SYMB")


def fire_lines(b, sh, t, dist, label):
    x0, y0, x1, y1 = b.site_rect()
    rc = y0 - b.spec["site"]["road"]["width"] / 2
    ys = rc + dist
    pts = [(x0 + dist, max(ys, y0)), (x0 + dist, y1 - dist), (x1 - dist, y1 - dist), (x1 - dist, max(ys, y0))]
    sh.pline(t.pts(pts), "A-FIRE")
    if ys > y0:
        sh.line(t(x0, ys), t(x1, ys), "A-FIRE")
    sh.text(label, t(x0 + dist + 150, y1 - dist - 600), 1.9, "A-LEGAL-TEXT")


def room_labels(b, sh, t, floor):
    for r in b.rooms:
        if r.floor != floor or not r.label_at:
            continue
        x, y = r.label_at
        hgt = 3.2 if r.habitable else 2.4
        sh.text(r.name, t(x, y), hgt, "A-ROOM", "MIDDLE_CENTER")
        sub = f"{r.area:.2f}m²"
        if r.habitable:
            sub += f"  CH={r.ch:,.0f}"
        sh.text(sub, t(x, y - (hgt + 1.6) * sh.S), 1.9, "A-ROOM", "MIDDLE_CENTER")


def side_panel(sh, x=284, y=282, items=(), width=120):
    """右側の凡例・注記欄。"""
    cy = y
    for kind, val in items:
        if kind == "h":
            sh.text(val, (x, cy), 3.0, "A-TEXT", paper=True)
            cy -= 5.5
        elif kind == "t":
            from cadlib import _wrap
            for line in _wrap(val, width, 2.1):
                sh.text(line, (x + 1, cy), 2.1, "A-TEXT", paper=True)
                cy -= 3.8
            cy -= 1.0
        elif kind == "gap":
            cy -= val
    return cy


def legend(sh, x, y):
    P = sh.P
    S = sh.S
    rows = [("A-CUT", "切断面（RC）", "hatch"), ("A-CUT-LGS", "軽量鉄骨間仕切 t=100", "line"),
            ("A-GRID", "通り芯", "line"), ("A-SITE", "敷地境界線", "line"),
            ("A-FIRE", "延焼のおそれのある部分", "line"), ("A-ALT", "代替進入口（令126条の7）", "tri")]
    cy = y
    for lay, lab, kind in rows:
        a, c = P(x, cy), P(x + 14, cy)
        if kind == "hatch":
            poly = sbox(a[0], a[1] - 1.2 * S, c[0], c[1] + 1.2 * S)
            sh.hatch_polys([poly])
            sh.rect(a[0], a[1] - 1.2 * S, c[0], c[1] + 1.2 * S, lay)
        elif kind == "tri":
            q = P(x + 7, cy)
            tri = [(q[0] - 2 * S, q[1] + 1.6 * S), (q[0] + 2 * S, q[1] + 1.6 * S), (q[0], q[1] - 1.8 * S)]
            sh.pline(tri, lay, closed=True)
            h = sh.msp.add_hatch(color=1, dxfattribs={"layer": lay})
            h.paths.add_polyline_path(tri)
        else:
            sh.line(a, c, lay)
        sh.text(lab, P(x + 17, cy - 1.0), 2.1, "A-TEXT")
        cy -= 5.0
    return cy


def floor_plan(b, floor, number):
    names = {"1F": "1階平面図", "2F": "2階平面図", "3F": "3階平面図", "RF": "R階平面図（屋上・塔屋）"}
    sh, t = plan_frame(b, number, names[floor])
    fl = b.fl[floor]
    if floor == "RF":
        cut_z = fl + 1000
        zmin = fl - b.H["3F"] / 2 - 1
    else:
        cut_z = fl + 1100
        order = b.floors
        i = order.index(floor)
        zmin = fl - (b.H[order[i - 1]] / 2 if i > 0 else 0) - 1
    proj = project(b.boxes, "plan", cut=-cut_z, depth_limit=-zmin,
                   filt=lambda bx: not ((bx.cat in ("glass", "door") and bx.z0 < cut_z < bx.z1)
                                        or (bx.cat == "stair" and bx.z1 > cut_z)))
    emit(sh, proj, t)
    draw_site_lines(sh, b, t)
    draw_grid(sh, b, t)
    plan_dims(b, sh, t, floor)
    lvl = floor if floor != "RF" else "PH"
    for w in b.walls:
        for op in w.openings:
            if op.floor != lvl and not (floor == "RF" and op.floor == "PH"):
                continue
            if not (op.z0 < cut_z < op.z1):
                continue
            if op.kind == "door":
                door_symbol(sh, t, op)
            else:
                window_symbol(sh, t, op)
            if op.label != "EV":
                opening_tag(sh, t, op)
    stair_marks(b, sh, t, floor if floor != "RF" else "RF", cut_z)
    ev_mark(b, sh, t, floor != "RF")
    if floor == "RF":
        _roof_notes(b, sh, t)
    else:
        room_labels(b, sh, t, floor)
    dist = 3000 if floor == "1F" else 5000
    fire_lines(b, sh, t, dist, f"延焼ライン（{'1階 3m' if floor == '1F' else '2階以上 5m'}）")
    if floor == "1F":
        _site_works(b, sh, t)
        _section_marks(b, sh, t)
    # 方位・タイトル
    sh.north_arrow(sh.P(395, 268), 7)
    lv = f"{floor[:-1] if floor != 'RF' else 'R'}FL = 設計GL + {fl:,.0f}"
    sh.view_title(names[floor], "1:100", (24, 22))
    sh.text(lv, (24, 15), 2.6, "A-TEXT", paper=True)
    cy = side_panel(sh, 284, 282, [("h", "凡例")])
    cy = legend(sh, 285, cy - 1)
    notes = _plan_notes(b, floor)
    side_panel(sh, 284, cy - 3, notes)
    return sh


def _plan_notes(b, floor):
    fin = b.spec["finish"]
    items = [("h", "特記")]
    if floor == "RF":
        items += [("t", f"屋上: {fin['roof']}\n水勾配 1/50 以上、ルーフドレン 4か所\nパラペット H=1,100（令126条 手すり兼用）\n塔屋: 階段室 18.00m² + EV機械スペース\n塔屋 水平投影面積 {b.penthouse_area():.2f}m²\n≦ 建築面積の1/8 = {b.building_area() / 8:.2f}m²\n→ 階数・高さ(5m以内)に算入しない")]
    else:
        items += [("t", f"事務室: {fin['office']}"), ("t", f"階段: {fin['stair']}"),
                  ("t", "階段室・EVは竪穴区画（令112条11項）\nSD-2: 防火設備・遮煙性能付・常時閉鎖式\nEV乗場戸: 遮煙性能（令112条19項2号）"),
                  ("t", "排煙: 天井高-800 以内の窓の開放部分で\n自然排煙（令126条の3）")]
        if floor in ("2F", "3F"):
            items += [("t", "西・東面の窓は延焼のおそれのある部分に\n該当するため防火設備（網入りガラス等）")]
        if floor == "3F":
            items += [("t", "南面の窓（赤▽）は非常用進入口に代わる\n開口（有効 2,000×1,800、10m以内ごと）")]
        if floor == "1F":
            items += [("t", "主出入口: 段差解消スロープ 1/12（バリアフリー）\n1FL = 設計GL+150")]
    items += [("t", "寸法の単位: mm、面積は壁芯")]
    return items


def _site_works(b, sh, t):
    # アプローチ・スロープ
    x0, y0, x1, y1 = b.site_rect()
    sh.rect(*t(7000, y0), *t(11000, -300), "A-VIS")
    sh.text("アプローチ（スロープ 1/12）", t(9000, -2900), 2.0, "A-TEXT", "MIDDLE_CENTER")
    sh.pline(t.pts([(9000, -3600), (9000, -1600)]), "A-SYMB")
    sh.pline(t.pts([(8850, -1850), (9000, -1600), (9150, -1850)]), "A-SYMB")
    sh.text("主出入口", t(9000, -3800), 2.0, "A-TEXT", "MIDDLE_CENTER")
    sh.text("敷地内通路 有効1.5m以上", t(19900, 9000), 1.8, "A-TEXT", "MIDDLE_CENTER", rot=90)


def _section_marks(b, sh, t):
    S = sh.S
    for (p, q, lab, d) in [((15700, -3300), (15700, 15400), "A", (1, 0)), ((-3000, 3000), (20800, 3000), "B", (0, 1))]:
        for pt in (p, q):
            c = t(*pt)
            sh.circle(c, 2.6 * S, "A-SYMB")
            sh.text(lab, c, 2.6, "A-SYMB", "MIDDLE_CENTER")
            a = (c[0] + d[0] * 2.6 * S, c[1] + d[1] * 2.6 * S)
            tip = (c[0] + d[0] * 6 * S, c[1] + d[1] * 6 * S)
            nrm = (-d[1], d[0])
            sh.pline([(a[0] + nrm[0] * 1.2 * S, a[1] + nrm[1] * 1.2 * S), tip,
                      (a[0] - nrm[0] * 1.2 * S, a[1] - nrm[1] * 1.2 * S)], "A-SYMB", closed=True)
        sh.line(t(*p), t(*(p[0] + (q[0] - p[0]) * 0.06, p[1] + (q[1] - p[1]) * 0.06)), "A-SYMB", lineweight=50)
        sh.line(t(*q), t(*(q[0] - (q[0] - p[0]) * 0.06, q[1] - (q[1] - p[1]) * 0.06)), "A-SYMB", lineweight=50)


def _roof_notes(b, sh, t):
    sx0, sy0, sx1, sy1 = b.stair
    e = b.wt / 2
    sh.rect(*t(sx0 - e, sy0 - e), *t(sx1 + e, sy1 + e), "A-HIDDEN")
    sh.text("塔屋（階段室）", t(16500, 10900), 2.4, "A-ROOM", "MIDDLE_CENTER")
    sh.text(f"PHRFL +{b.fl['PHRF']:,.0f}", t(16500, 10400), 1.8, "A-ROOM", "MIDDLE_CENTER")
    sh.text("EV機械スペース", t(16900, 5300), 1.8, "A-ROOM", "MIDDLE_CENTER")
    sh.text("屋上（設備置場）", t(6000, 7000), 3.2, "A-ROOM", "MIDDLE_CENTER")
    sh.text(f"RFL +{b.fl['RF']:,.0f}", t(6000, 6400), 1.9, "A-ROOM", "MIDDLE_CENTER")
    for (x, y) in [(500, 500), (500, 11500), (14500, 11500), (14500, 500)]:
        sh.circle(t(x, y), 1.5 * sh.S, "A-SYMB")
        sh.text("RD", t(x + 300, y + 200), 1.6, "A-SYMB")
    for (p, q) in [((7500, 3000), (7500, 900)), ((7500, 9000), (7500, 11100)), ((4000, 6000), (1100, 6000)),
                   ((11000, 6000), (13900, 6000))]:
        sh.pline(t.pts([p, q]), "A-SYMB")
        sh.text("1/50", t((p[0] + q[0]) / 2 + 150, (p[1] + q[1]) / 2 + 150), 1.6, "A-SYMB")
    sh.rect(*t(2000, 8500), *t(6000, 10500), "A-VIS")
    sh.text("屋外機置場（架台）", t(4000, 9500), 1.8, "A-TEXT", "MIDDLE_CENTER")


# ================================================================== elevations
def elevation_view(b, sh, t, view, title):
    proj = project(b.boxes, view, ground=0)
    emit(sh, proj, t, cut_lw=35, vis_lw=18)
    uv = uv_fn(view)
    S = sh.S
    # GL
    us = [uv(x, y, 0)[0] for x in (-300, b.W + 300) for y in (-300, b.D + 300)]
    u_lo, u_hi = min(us) - 2500, max(us) + 2500
    sh.line(t(u_lo, 0), t(u_hi, 0), "A-GROUND", lineweight=50)
    # 窓の召合せ
    face = {"S": ("x", 0.0), "N": ("x", b.D), "W": ("y", 0.0), "E": ("y", b.W)}[view]
    for w in b.walls:
        if w.axis != face[0] or abs(w.c - face[1]) > 1:
            continue
        for op in w.openings:
            if op.kind == "window" and op.name == "引違い窓":
                m = (op.u0 + op.u1) / 2
                p = uv(m, w.c, 0) if w.axis == "x" else uv(w.c, m, 0)
                sh.line(t(p[0], op.z0), t(p[0], op.z1), "A-GLAZ")
            if op.alt_entry:
                m = (op.u0 + op.u1) / 2
                p = uv(m, w.c, 0)
                q = t(p[0], op.z1 - 350)
                tri = [(q[0] - 1.6 * S, q[1] + 1.2 * S), (q[0] + 1.6 * S, q[1] + 1.2 * S), (q[0], q[1] - 1.4 * S)]
                sh.pline(tri, "A-ALT", closed=True)
                h = sh.msp.add_hatch(color=1, dxfattribs={"layer": "A-ALT"})
                h.paths.add_polyline_path(tri)
    # 通り芯
    grid = b.gx if view in ("S", "N") else b.gy
    names = b.gx_names if view in ("S", "N") else b.gy_names
    top = b.ph_parapet_top + 2500
    for g, n in zip(grid, names):
        u = uv(g, 0, 0)[0] if view in ("S", "N") else uv(0, g, 0)[0]
        sh.line(t(u, b.ph_parapet_top + 800), t(u, top - 4.0 * S), "A-GRID")
        sh.grid_bubble(t(u, top), n, 3.2)
    # レベル
    xl = u_lo - 200
    for name, z in [("最高高さ", b.ph_parapet_top), ("パラペット天端", b.parapet_top), ("RFL", b.fl["RF"]),
                    ("3FL", b.fl["3F"]), ("2FL", b.fl["2F"]), ("1FL", b.fl["1F"]), ("設計GL", 0)]:
        sh.line(t(xl, z), t(u_lo + 1800, z), "A-SYMB")
        sh.text(f"{name} {'+' if z else '±'}{z:,.0f}", t(xl - 400, z + 120 if z else z - 120), 1.8, "A-SYMB",
                "BOTTOM_RIGHT" if z else "TOP_RIGHT")
    p = t(u_lo, -2600)
    sh.text(title, p, 3.4, "A-TEXT", "BOTTOM_LEFT")
    w = _text_width(title, 3.4) * S
    sh.line((p[0], p[1] - 1.0 * S), (p[0] + w, p[1] - 1.0 * S), "A-SYMB", lineweight=35)


def elevations_sheet(b, number):
    sh = Sheet(number, "立面図", 200, b.spec["project"])
    sh.frame()
    layout = [("S", "南立面図", (62, 190), 0), ("E", "東立面図", (262, 190), 0),
              ("N", "北立面図", (62, 72), 1), ("W", "西立面図", (262, 72), 1)]
    for view, title, paper, _ in layout:
        uv = uv_fn(view)
        us = [uv(x, y, 0)[0] for x in (0, b.W) for y in (0, b.D)]
        anchor = (min(us), 0)
        t = T(sh, anchor, paper)
        elevation_view(b, sh, t, view, title)
    fin = b.spec["finish"]
    side_panel(sh, 18, 46, [("t", f"外壁: {fin['exterior']}　／　屋根: {fin['roof']}"),
                            ("t", "サッシ: アルミ製（AW）、2・3階 西・東面は防火設備　／　赤▽: 代替進入口（3階南面）")], width=200)
    return sh


# ==================================================================== sections
def section_sheet(b, number, which):
    sh = Sheet(number, f"断面図 {which}-{which}" + ("（道路斜線検討）" if which == "A" else ""), 100, b.spec["project"])
    sh.frame()
    x0, y0, x1, y1 = b.site_rect()
    if which == "A":
        view, cut = "W", 15700.0
        anchor, paper = (-y1, 0.0), (22, 86)
        span = (-y1, -(y0 - b.spec["site"]["road"]["width"]))
    else:
        view, cut = "S", 3000.0
        anchor, paper = (x0, 0.0), (40, 86)
        span = (x0, x1)
    t = T(sh, anchor, paper)
    ds = VIEWS[view][5]
    proj = project(b.boxes, view, cut=ds * cut, ground=0)
    emit(sh, proj, t)
    uv = uv_fn(view)
    S = sh.S
    # 地盤
    sh.line(t(span[0], 0), t(span[1], 0), "A-GROUND", lineweight=50)
    # 天井（破線）
    for f in b.floors:
        z = b.fl[f] + b.ch[f]
        if which == "A":
            a, c = uv(0, 100, 0)[0], uv(0, 5800, 0)[0]
        else:
            a, c = uv(100, 0, 0)[0], uv(11900, 0, 0)[0]
        sh.line(t(min(a, c), z), t(max(a, c), z), "A-HIDDEN")
        sh.text(f"CH={b.ch[f]:,}", t((a + c) / 2, z - 450), 2.0, "A-TEXT", "MIDDLE_CENTER")
        sh.text("事務室", t((a + c) / 2, b.fl[f] + 900), 2.8, "A-ROOM", "MIDDLE_CENTER")
    # 通り芯
    grid = b.gy if which == "A" else b.gx
    names = b.gy_names if which == "A" else b.gx_names
    zb = b.fdn_bot - 1600
    for g, n in zip(grid, names):
        u = uv(0, g, 0)[0] if which == "A" else uv(g, 0, 0)[0]
        sh.line(t(u, b.ph_parapet_top + 600), t(u, zb + 3.5 * S), "A-GRID")
        sh.grid_bubble(t(u, zb), n, 3.5)
    us = sorted(uv(0, g, 0)[0] if which == "A" else uv(g, 0, 0)[0] for g in grid)
    hdim(sh, t, us, zb + 1100)
    # レベル・階高
    u_b = min(uv(x, y, 0)[0] for x in (0, b.W) for y in (0, b.D))
    xl = u_b - 2400
    zs = [0, b.fl["1F"], b.fl["2F"], b.fl["3F"], b.fl["RF"], b.parapet_top, b.ph_parapet_top]
    for name, z in zip(["設計GL", "1FL", "2FL", "3FL", "RFL", "パラペット", "最高高さ"], zs):
        sh.line(t(xl - 900, z), t(u_b - 700, z), "A-SYMB")
        sh.text(f"{name} {'+' if z else '±'}{z:,.0f}", t(xl - 900, z + 100 if z else z - 100), 1.9, "A-SYMB",
                "BOTTOM_LEFT" if z else "TOP_LEFT")
    vdim(sh, t, zs[:5], xl + 600)
    vdim(sh, t, [0, b.parapet_top], xl + 1300)
    sh.text("建築物の高さ", t(xl + 1700, b.parapet_top / 2), 1.9, "A-TEXT", "MIDDLE_LEFT", rot=90)
    # 敷地境界
    for (yy, lab) in ([(y0, "道路境界線"), (y1, "隣地境界線")] if which == "A" else [(x0, "隣地境界線"), (x1, "隣地境界線")]):
        u = uv(0, yy, 0)[0] if which == "A" else uv(yy, 0, 0)[0]
        sh.line(t(u, -1500), t(u, 16000), "A-SITE")
        sh.text(lab, t(u + 150, 15600), 2.0, "A-TEXT", "TOP_LEFT", rot=-90)
    if which == "A":
        _road_slope(b, sh, t, uv)
        sh.text("階段室", t(uv(0, 9000, 0)[0], b.fl["3F"] + 2600), 2.4, "A-ROOM", "MIDDLE_CENTER")
    else:
        _adjacent_note(b, sh)
    sh.view_title(f"断面図 {which}-{which}", "1:100", (22, 22))
    return sh


def _road_slope(b, sh, t, uv):
    rs = legal.road_slope(b)
    site = b.spec["site"]
    rw = site["road"]["width"]
    y_rb = rs["y_rb"]
    yv = rs["y_virtual"]
    S = sh.S
    # 道路
    u_rb, u_far = uv(0, y_rb, 0)[0], uv(0, y_rb - rw, 0)[0]
    sh.line(t(u_rb, -300), t(u_far, -300), "A-ROAD")
    uc = uv(0, y_rb - rw / 2, 0)[0]
    sh.line(t(uc, -800), t(uc, 1200), "A-GRID")
    sh.text("道路中心線", t(uc + 150, 1300), 1.8, "A-TEXT")
    sh.text(f"前面道路 W={rw / 1000:.1f}m", t((u_rb + u_far) / 2, -900), 2.2, "A-TEXT", "MIDDLE_CENTER")
    sh.line(t(u_far, -1500), t(u_far, 3000), "A-SITE")
    sh.text("道路反対側の境界線", t(u_far + 150, 3300), 1.8, "A-TEXT", "BOTTOM_LEFT")
    uv_ = uv(0, yv, 0)[0]
    sh.line(t(uv_, -1500), t(uv_, 3000), "A-LEGAL")
    sh.text("みなし境界線（法56条2項）", t(uv_ + 150, 1800), 1.8, "A-LEGAL-TEXT", "BOTTOM_LEFT")
    hdim(sh, t, sorted([uv_, u_far, u_rb, uv(0, y_rb + rs["setback"], 0)[0]]), -2300)
    # 斜線
    zmax = 16500
    y_end = yv + zmax / rs["slope"]
    p, q = t(uv_, 0), t(uv(0, y_end, 0)[0], zmax)
    sh.line(p, q, "A-LEGAL", lineweight=35)
    mid = t(uv(0, yv + 8000 / rs["slope"], 0)[0], 8000)
    sh.text(f"道路斜線 {rs['slope']}／1（適用距離 {rs['range'] / 1000:.0f}m）", (mid[0] - 2 * S, mid[1]), 2.4,
            "A-LEGAL-TEXT", "BOTTOM_RIGHT")
    # チェック点
    bx = rs["box"]
    ck = t(uv(0, bx.y0, 0)[0], bx.z1)
    sh.circle(ck, 1.0 * S, "A-LEGAL")
    al = t(uv(0, bx.y0, 0)[0], rs["allow"]) if rs["allow"] < zmax else None
    sh.text(f"検討点: H={bx.z1:,.0f} ≦ 許容 {rs['allow']:,.0f}（余裕 {rs['margin']:,.0f}）", (ck[0] + 2 * S, ck[1] + 1.5 * S),
            2.0, "A-LEGAL-TEXT", "BOTTOM_LEFT")
    sh.text(f"許容高さ = {rs['slope']} × ({rw:,.0f} + 2×{rs['setback']:,.0f} + 後退距離からの距離)", (ck[0] + 2 * S, ck[1] + 5 * S),
            1.8, "A-LEGAL-TEXT", "BOTTOM_LEFT")


def _adjacent_note(b, sh):
    sm = legal.summary(b)
    adj = b.spec["site"]["adjacent_slope"]
    side_panel(sh, 230, 280, [("t", f"隣地斜線: {adj['rise'] / 1000:.0f}m + {adj['slope']}／1（法56条1項2号）\n最高高さ {sm['max_height']:.2f}m < 立上り {adj['rise'] / 1000:.0f}m → 制限を受けない")])


# ===================================================================== site
def site_plan(b, number):
    sh = Sheet(number, "配置図・求積図", 200, b.spec["project"])
    sh.frame()
    x0, y0, x1, y1 = b.site_rect()
    t = T(sh, (x0, y0), (40, 92))
    proj = project(b.boxes, "plan", filt=lambda bx: bx.z1 > 0)
    emit(sh, proj, t, cut_lw=35, vis_lw=13)
    # 建物外形（太線）
    hb = b.col[0] / 2
    sh.rect(*t(-hb, -hb), *t(b.W + hb, b.D + hb), "A-CUT", lineweight=50)
    draw_site_lines(sh, b, t, label=False)
    rw = b.spec["site"]["road"]["width"]
    sh.line(t(x0 - 3000, y0 - rw), t(x1 + 3000, y0 - rw), "A-ROAD")
    sh.line(t(x0 - 3000, y0), t(x0, y0), "A-ROAD")
    sh.line(t(x1, y0), t(x1 + 3000, y0), "A-ROAD")
    sh.line(t(x0 - 3000, y0 - rw / 2), t(x1 + 3000, y0 - rw / 2), "A-GRID")
    sh.text(f"前面道路 {b.spec['site']['road']['kind']} W={rw / 1000:.1f}m", t((x0 + x1) / 2, y0 - rw / 2 - 1200), 2.6, "A-TEXT", "MIDDLE_CENTER")
    # 敷地寸法
    hdim(sh, t, [x0, x1], y1 + 1800)
    vdim(sh, t, [y0, y1], x1 + 1800)
    vdim(sh, t, [y0 - rw, y0], x1 + 1800)
    # 建物配置寸法（外壁芯まで）
    hdim(sh, t, [x0, 0, b.W, x1], y1 - 900)
    vdim(sh, t, [y0, 0, b.D, y1], x0 + 1600)
    fire_lines(b, sh, t, 3000, "延焼ライン 1階")
    fire_lines(b, sh, t, 5000, "延焼ライン 2階以上")
    # 外構
    sh.rect(*t(7000, y0), *t(11000, -300), "A-VIS")
    sh.text("アプローチ", t(9000, -2200), 2.0, "A-TEXT", "MIDDLE_CENTER")
    for xx in range(-1500, 19500, 3000):
        sh.circle(t(xx, b.D + 2700), 1.8 * sh.S, "A-VIS")
    sh.text("植栽帯", t(9000, b.D + 1300), 2.0, "A-TEXT", "MIDDLE_CENTER")
    sh.text("建物", t(6000, 6000), 4.0, "A-ROOM", "MIDDLE_CENTER")
    sh.text("RC造 地上3階 塔屋1階", t(6000, 4200), 2.2, "A-ROOM", "MIDDLE_CENTER")
    sh.pline(t.pts([(9000, y0 - 600), (9000, -600)]), "A-SYMB")
    sh.pline(t.pts([(8700, -1100), (9000, -600), (9300, -1100)]), "A-SYMB")
    sh.text("設計GL = 前面道路中心高さ ±0（平坦地）", t(x0, y0 - rw - 2200), 2.0, "A-TEXT")
    sh.north_arrow(t(x1 + 4200, y1 - 2500), 6)
    sh.view_title("配置図", "1:200", (24, 22))
    # 面積表・求積
    sm = legal.summary(b)
    fa = sm["floor_areas"]
    rows = [["項目", "算定式", "面積・比率"],
            ["敷地面積", f"{b.spec['site']['width'] / 1000:.2f} × {b.spec['site']['depth'] / 1000:.2f}", f"{sm['site_area']:.2f} m²"],
            ["建築面積", f"{b.W / 1000:.2f} × {b.D / 1000:.2f}（壁芯）", f"{sm['building_area']:.2f} m²"]]
    for f in b.floors:
        rows.append([f"{f} 床面積", f"{b.W / 1000:.2f} × {b.D / 1000:.2f}", f"{fa[f]:.2f} m²"])
    rows += [["塔屋 床面積", "3.00 × 6.00（階段室）", f"{fa['PH']:.2f} m²"],
             ["延べ面積", "各階の合計", f"{sm['total']:.2f} m²"],
             ["容積対象面積", f"延べ − EV昇降路 {b.ev_shaft_area():.2f}×{len(b.floors)}", f"{sm['far_area']:.2f} m²"],
             ["建ぺい率", f"{sm['building_area']:.2f} / {sm['site_area']:.2f}", f"{sm['coverage'] * 100:.2f}% ≦ {b.spec['site']['coverage_limit'] * 100:.0f}%"],
             ["容積率", f"{sm['far_area']:.2f} / {sm['site_area']:.2f}", f"{sm['far'] * 100:.2f}% ≦ {sm['far_limit'] * 100:.0f}%"],
             ["塔屋 水平投影", f"{sm['ph_area']:.2f} ≦ {sm['building_area']:.2f}/8", f"{sm['building_area'] / 8:.2f} m²"],
             ["建築物の高さ", "設計GL〜パラペット天端", f"{sm['height']:.2f} m"],
             ["軒の高さ", "設計GL〜屋上スラブ上端", f"{sm['eave']:.2f} m"]]
    sh.text("求積表（壁芯）", (220, 278), 3.2, "A-TEXT", paper=True)
    sh.table(220, 274, [36, 74, 78], rows, row_h=6.2, h=2.3)
    # 求積図
    t2 = T(sh, (0, 0), (300, 66))
    sh.rect(*t2(0, 0), *t2(b.W, b.D), "A-VIS", lineweight=25)
    poly = sbox(*t2(0, 0), *t2(b.W, b.D))
    sh.hatch_polys([poly], pattern="ANSI31", spacing=4.0)
    hdim(sh, t2, [0, b.W], -1200)
    vdim(sh, t2, [0, b.D], -1200)
    sh.text("建築面積 求積図", t2(0, b.D + 1600), 2.4, "A-TEXT")
    sh.text(f"{b.W / 1000:.2f}×{b.D / 1000:.2f}={sm['building_area']:.2f}m²", t2(b.W / 2, b.D / 2), 2.4, "A-TEXT", "MIDDLE_CENTER")
    return sh


# ================================================================ structure
def struct_plan(b, number, level):
    names = {"FDN": "基礎伏図", "2F": "2階梁伏図", "3F": "3階梁伏図", "RF": "R階梁伏図"}
    sh, t = plan_frame(b, number, names[level])
    S = sh.S
    hb = b.col[0] / 2
    # 柱（切断）
    polys = []
    for x in b.gx:
        for y in b.gy:
            p = sbox(*t(x - hb, y - hb), *t(x + hb, y + hb))
            polys.append(p)
            sh.rect(*t(x - hb, y - hb), *t(x + hb, y + hb), "S-COLS")
    sh.hatch_polys(polys)
    beams = [bx for bx in b.boxes if bx.level == level and bx.cat in ("beam", "fg")]
    lay = "S-BEAM" if level != "FDN" else "S-BEAM-V"
    for bx in beams:
        sh.rect(*t(bx.x0, bx.y0), *t(bx.x1, bx.y1), lay)
        cx, cy = (bx.x0 + bx.x1) / 2, (bx.y0 + bx.y1) / 2
        horiz = (bx.x1 - bx.x0) > (bx.y1 - bx.y0)
        off = 450
        p = t(cx, cy + off) if horiz else t(cx - off, cy)
        sh.text(bx.tag, p, 2.2, "S-TEXT", "MIDDLE_CENTER", rot=0 if horiz else 90)
    if level == "FDN":
        for bx in b.boxes:
            if bx.cat == "footing":
                sh.rect(*t(bx.x0, bx.y0), *t(bx.x1, bx.y1), "S-FNDN")
        for x in b.gx:
            for y in b.gy:
                sh.text("F1", t(x + 650, y - 900), 2.2, "S-TEXT")
        ex0, ey0, ex1, ey1 = b.ev
        sh.rect(*t(ex0 - 100, ey0 - 100), *t(ex1 + 100, ey1 + 100), "S-SLAB")
        sh.text("EVピット 深さ1,200", t((ex0 + ex1) / 2, (ey0 + ey1) / 2), 1.8, "S-TEXT", "MIDDLE_CENTER")
        sh.text("1階床 S1 t=180（基礎梁上）", t(6000, 9000), 2.6, "S-TEXT", "MIDDLE_CENTER")
        # RC 壁
        for w in b.walls:
            if w.floor == "1F" and w.cat == "wall" and w.side == "I":
                x0, y0, z0, x1, y1, z1 = w.rect(w.a, w.b, w.z0, w.z1)
                sh.rect(*t(x0, y0), *t(x1, y1), "S-SLAB")
    else:
        # スラブ記号・開口
        for gx0, gx1 in zip(b.gx, b.gx[1:]):
            for gy0, gy1 in zip(b.gy, b.gy[1:]):
                cx, cy = (gx0 + gx1) / 2, (gy0 + gy1) / 2
                if gx0 == 12000 and gy0 == 6000:
                    continue
                sh.line(t(gx0 + 900, gy0 + 900), t(gx0 + 2000, gy0 + 2000), "S-SLAB")
                sh.text("S1", t(cx, cy), 2.6, "S-TEXT", "MIDDLE_CENTER")
        e = b.wt / 2
        sx0, sy0, sx1, sy1 = b.stair
        ex0, ey0, ex1, ey1 = b.ev
        for (a, c) in [((sx0 + e, 7500), (sx1 - e, sy1 - e)), ((ex0 + e, ey0 + e), (ex1 - e, ey1 - e))]:
            sh.rect(*t(*a), *t(*c), "S-SLAB", lineweight=35)
            sh.line(t(*a), t(*c), "S-SLAB")
            sh.line(t(a[0], c[1]), t(c[0], a[1]), "S-SLAB")
        sh.text("開口（階段）", t(16500, 9700), 2.0, "S-TEXT", "MIDDLE_CENTER")
        sh.text("S1", t(13500, 9000), 2.6, "S-TEXT", "MIDDLE_CENTER")
        for w in b.walls:
            order = b.floors + ["RF"]
            if w.floor == order[order.index(level) - 1] and w.cat == "wall" and w.side == "I":
                x0, y0, z0, x1, y1, z1 = w.rect(w.a, w.b, w.z0, w.z1)
                sh.rect(*t(x0, y0), *t(x1, y1), "S-SLAB")
        sh.text(f"{level}FL = GL+{b.fl[level]:,.0f}（梁天端 = スラブ天端）", (24, 15), 2.6, "A-TEXT", paper=True)
    draw_grid(sh, b, t)
    hdim(sh, t, b.gx, -1600)
    hdim(sh, t, [0, b.W], -2200)
    vdim(sh, t, b.gy, -1600)
    vdim(sh, t, [0, b.D], -2200)
    sh.north_arrow(sh.P(395, 268), 7)
    sh.view_title(names[level], "1:100", (24, 22))
    st = b.spec["structure"]
    items = [("h", "構造概要"), ("t", st["system"]),
             ("t", f"コンクリート Fc{st['concrete']['Fc']}（スランプ{st['concrete']['slump']}cm）\n鉄筋 D10〜D16: {st['rebar']['D10-D16']}\n　　 D19〜D25: {st['rebar']['D19-D25']}"),
             ("t", f"基礎: {st['foundation']}")]
    if level == "FDN":
        items += [("t", "F1: 2,800×2,800×800（底盤 GL-2,150）\nFG1: 500×1,500（天端 1FL）\nFB1: 300×1,000（階段・EV壁下）")]
    else:
        items += [("t", "G1: 400×700（天端 = スラブ天端）\nS1: t=180 四辺固定スラブ\n梁は破線（スラブ下・隠れ線）で表示")]
    items += [("t", "部材断面は S-05 部材断面リストによる")]
    side_panel(sh, 284, 282, items)
    return sh


def member_list(b, number):
    sh = Sheet(number, "部材断面リスト・構造特記", 20, b.spec["project"])
    sh.frame()
    st = b.spec["structure"]
    S = sh.S
    cov = st["cover"]
    P = sh.P

    def bars_rect(x0, y0, bw, bd, nx, ny_top, ny_bot, dia, hoop, cover, sides=None):
        # 外形・帯筋
        sh.rect(x0, y0, x0 + bw, y0 + bd, "A-CUT", lineweight=50)
        c = cover + hoop / 2
        sh.rect(x0 + c, y0 + c, x0 + bw - c, y0 + bd - c, "S-REBAR", lineweight=25)
        g = cover + hoop + dia / 2
        pts = []

        def row(y, n):
            for i in range(n):
                xx = x0 + g + (bw - 2 * g) * (i / (n - 1) if n > 1 else 0.5)
                pts.append((xx, y))
        row(y0 + bd - g, ny_top)
        row(y0 + g, ny_bot)
        if sides:
            for j in range(1, sides + 1):
                yy = y0 + g + (bd - 2 * g) * j / (sides + 1)
                pts += [(x0 + g, yy), (x0 + bw - g, yy)]
        for p in pts:
            sh.circle(p, dia / 2, "S-REBAR")
            h = sh.msp.add_hatch(color=1, dxfattribs={"layer": "S-REBAR"})
            h.set_solid_fill(color=1)
            h.paths.add_edge_path().add_arc(p, dia / 2, 0, 360)

    c1 = st["column"]["C1"]
    g1 = st["girder"]["G1"]
    fg = st["fgirder"]["FG1"]
    f1 = st["footing"]["F1"]
    # C1
    x, y = P(30, 190)
    bars_rect(x, y, c1["b"], c1["d"], 4, 4, 4, c1["main_dia"], c1["hoop_dia"], cov["column_beam"], sides=2)
    sh.text("C1（柱）", P(30, 230), 3.2, "A-TEXT")
    # G1
    x, y = P(105, 190)
    bars_rect(x, y, g1["b"], g1["d"], 4, g1["top"], g1["bottom"], g1["main_dia"], g1["stirrup_dia"], cov["column_beam"])
    sh.text("G1（大梁）", P(105, 230), 3.2, "A-TEXT")
    # FG1
    x, y = P(160, 160)
    bars_rect(x, y, fg["b"], fg["d"], 5, fg["top"], fg["bottom"], fg["main_dia"], fg["stirrup_dia"], cov["earth_contact"], sides=2)
    sh.text("FG1（基礎梁）", P(160, 240), 3.2, "A-TEXT")
    # F1 断面
    x, y = P(222, 122)
    sh.rect(x, y, x + f1["b"], y + f1["t"], "A-CUT", lineweight=50)
    sh.rect(x + f1["b"] / 2 - 300, y + f1["t"], x + f1["b"] / 2 + 300, y + f1["t"] + 700, "A-CUT", lineweight=50)
    sh.rect(x - 100, y - 50, x + f1["b"] + 100, y, "A-VIS")
    sh.text("捨てコン t=50", (x + f1["b"] + 200, y - 50), 1.8, "A-TEXT")
    cv = cov["foundation"]
    for i in range(14):
        px = x + cv + 20 + i * (f1["b"] - 2 * cv - 40) / 13
        for py in (y + cv + 10, y + cv + 40):
            if py == y + cv + 40:
                continue
            sh.circle((px, py), 9.5, "S-REBAR")
    sh.line((x + cv, y + cv + 30), (x + f1["b"] - cv, y + cv + 30), "S-REBAR")
    sh.line((x + cv, y + f1["t"] - cv), (x + f1["b"] - cv, y + f1["t"] - cv), "S-REBAR")
    sh.text("F1（独立基礎）断面", P(222, 192), 3.2, "A-TEXT")
    sh.dim((x, y - 200), (x + f1["b"], y - 200), (x, y - 200), 0)
    sh.dim((x - 200, y), (x - 200, y + f1["t"]), (x - 200, y), 90)
    # 寸法
    for (px, py, bw, bd) in [(30, 190, c1["b"], c1["d"]), (105, 190, g1["b"], g1["d"]), (160, 160, fg["b"], fg["d"])]:
        x, y = P(px, py)
        sh.dim((x, y - 150), (x + bw, y - 150), (x, y - 150), 0)
        sh.dim((x - 150, y), (x - 150, y + bd), (x - 150, y), 90)
    # スラブ
    x, y = P(30, 120)
    sh.rect(x, y, x + 2500, y + b.slab_t, "A-CUT", lineweight=50)
    for i in range(13):
        px = x + 100 + i * 200
        sh.circle((px, y + 30 + 6.5), 6.5, "S-REBAR")
        sh.circle((px, y + b.slab_t - 30 - 6.5), 6.5, "S-REBAR")
    sh.line((x, y + 30 + 19), (x + 2500, y + 30 + 19), "S-REBAR")
    sh.line((x, y + b.slab_t - 30 - 19), (x + 2500, y + b.slab_t - 30 - 19), "S-REBAR")
    sh.dim((x - 150, y), (x - 150, y + b.slab_t), (x - 150, y), 90)
    sh.text("S1（床版）t=180", P(30, 133), 3.2, "A-TEXT")
    # 部材表
    rows = [["符号", "断面 B×D", "主筋", "せん断補強筋", "備考"],
            ["C1", f"{c1['b']}×{c1['d']}", f"{c1['main']}-D{c1['main_dia']}", f"□-D{c1['hoop_dia']}@{c1['hoop_pitch']}", "全階共通（柱頭・柱脚とも）"],
            ["G1", f"{g1['b']}×{g1['d']}", f"上{g1['top']}-D{g1['main_dia']} 下{g1['bottom']}-D{g1['main_dia']}", f"□-D{g1['stirrup_dia']}@{g1['stirrup_pitch']}", "2F・3F・RF 大梁（端部・中央共通）"],
            ["FG1", f"{fg['b']}×{fg['d']}", f"上{fg['top']}-D{fg['main_dia']} 下{fg['bottom']}-D{fg['main_dia']}", f"□-D{fg['stirrup_dia']}@{fg['stirrup_pitch']}", "腹筋 2-D13（各側）"],
            ["FB1", "300×1,000", "上下 3-D19", "□-D10@200", "階段・EV壁下 基礎梁"],
            ["F1", f"{f1['b']}×{f1['d']}×{f1['t']}", f1["bars"], "—", "長期 地耐力150kN/m²"],
            ["S1", f"t={b.slab_t}", st["slab"]["S1"]["bars"], "—", "四辺固定"],
            ["W20", f"t={b.wt}", st["wall"]["W20"]["bars"], "—", "階段室・EVシャフト"]]
    sh.table(18, 100, [16, 30, 52, 34, 66], rows, row_h=6.0, h=2.2)
    notes = [("h", "構造特記事項"),
             ("t", f"1. コンクリート: 普通コンクリート Fc={st['concrete']['Fc']}N/mm²、スランプ{st['concrete']['slump']}cm\n   {st['concrete']['cement']}、JASS5 に準拠"),
             ("t", f"2. 鉄筋: 異形鉄筋 D10〜D16 {st['rebar']['D10-D16']}、D19〜D25 {st['rebar']['D19-D25']}"),
             ("t", f"3. 設計かぶり厚さ（令79条の最小値+10mm）\n   柱・梁 {cov['column_beam']}／床・壁 {cov['slab_wall']}／土に接する部分 {cov['earth_contact']}／基礎 {cov['foundation']}"),
             ("t", "4. 継手: D19以上はガス圧接、D16以下は重ね継手 40d\n5. 定着: 大梁主筋の柱内定着 40d（折曲げ定着 L2 は 30d）"),
             ("t", "6. 帯筋・あばら筋の末端は 135° フック（余長 6d 以上）"),
             ("t", "7. 本図は仮定断面であり、許容応力度計算（ルート1）等の\n   構造計算により確定する（法20条1項3号）"),
             ("t", "8. 地盤: 地盤調査（ボーリング・平板載荷試験）により\n   長期許容支持力度 150kN/m² 以上を確認すること")]
    side_panel(sh, 268, 282, notes, width=138)
    sh.view_title("部材断面", "1:20", (24, 22))
    return sh


# ================================================================ schedules
def fittings_sheet(b, number):
    sh = Sheet(number, "建具表", 50, b.spec["project"])
    sh.frame()
    S = sh.S
    fits = b.fittings
    cols = 6
    cw, chh = 65, 118
    for i, f in enumerate(fits):
        r, c = divmod(i, cols)
        x0, ytop = 12 + c * cw, 284 - r * chh
        sh.rect(*sh.P(x0, ytop - chh), *sh.P(x0 + cw, ytop), "G-TABLE")
        sh.line(sh.P(x0, ytop - 8), sh.P(x0 + cw, ytop - 8), "G-TABLE")
        sh.text(f["label"], (x0 + cw / 2, ytop - 6), 4.0, "A-TEXT", "BOTTOM_CENTER", paper=True)
        # 姿図（1:50 だと大きいので 1:100 相当で描く）
        sc = 0.5 if f["w"] > 2600 else 1.0
        w, h = f["w"] * sc, f["h"] * sc
        cx, by = sh.P(x0 + cw / 2, ytop - 66)
        x_ = cx - w / 2
        sh.rect(x_, by, x_ + w, by + h, "A-GLAZ", lineweight=35)
        if f["name"] == "引違い窓" or "両引き" in f["name"]:
            sh.line((cx, by), (cx, by + h), "A-GLAZ")
        if "片開き" in f["name"]:
            sh.line((x_ + w, by + h / 2), (x_, by + h), "A-DOOR")
            sh.line((x_ + w, by + h / 2), (x_, by), "A-DOOR")
        if "すべり出し" in f["name"]:
            sh.line((x_, by), (cx, by + h), "A-DOOR")
            sh.line((x_ + w, by), (cx, by + h), "A-DOOR")
        if f["alt_entry"]:
            q = (x_ + w * 0.25, by + h - 300 * sc)
            tri = [(q[0] - 1.6 * S, q[1] + 1.2 * S), (q[0] + 1.6 * S, q[1] + 1.2 * S), (q[0], q[1] - 1.4 * S)]
            sh.pline(tri, "A-ALT", closed=True)
        sh.dim((x_, by - 4 * S), (x_ + w, by - 4 * S), (x_, by - 4 * S), 0, text=f"{f['w']:,}")
        sh.dim((x_ - 3 * S, by), (x_ - 3 * S, by + h), (x_ - 3 * S, by), 90, text=f"{f['h']:,}")
        mat = {"AW": "アルミ製", "AD": "アルミ製 自動", "SD": "鋼製", "WD": "木製"}[f["label"][:2]]
        if f["name"].startswith("EV"):
            mat = "EV メーカー標準"
        glass = ""
        if f["label"].startswith(("AW", "AD")):
            glass = "網入り複層ガラス" if f["fire"] else "Low-E 複層ガラス"
        spec = [f"名称: {f['name']}", f"材質: {mat}", f"W{f['w']:,}×H{f['h']:,}", f"数量: {f['count']}か所（{'・'.join(f['floors'])}）"]
        if glass:
            spec.append(f"ガラス: {glass}")
        if f["fire"]:
            spec.append("防火設備（法2条9号の2ロ）" + ("・遮煙" if f["smoke"] else ""))
        if f["alt_entry"]:
            spec.append("3F南面は代替進入口（赤▽）")
        if "片開き" in f["name"] and f["label"].startswith("SD"):
            spec.append("ドアクローザー・常時閉鎖")
        yy = ytop - 82
        for line in spec:
            sh.text(line, (x0 + 2, yy), 2.0, "A-TEXT", paper=True)
            yy -= 4.0
    sh.text("姿図は W2,600 を超えるものを 1:100、その他を 1:50 で表示", (12, 46), 2.2, "A-TEXT", paper=True)
    return sh


def legal_sheets(b, start_number):
    rows, sm = legal.checks(b)
    head = ["区分", "項目", "根拠条文", "規定・要求", "計画", "判定"]
    cols = [18, 36, 38, 108, 160, 18]
    sheets = []
    page = []
    pages = []
    budget = 212.0
    used = 0.0
    from cadlib import _wrap
    for r in rows:
        cells = [r["cat"], r["item"], r["basis"], r["required"], r["planned"], r["result"]]
        n = max(len(_wrap(str(c), w - 2.0, 2.1)) for c, w in zip(cells, cols))
        hgt = max(5.6, n * 2.1 * 1.45 + 1.8)
        if used + hgt > budget:
            pages.append(page)
            page, used = [], 0.0
        page.append(cells)
        used += hgt
    pages.append(page)
    for i, pg in enumerate(pages):
        num = f"A-{start_number + i:02d}"
        sh = Sheet(num, f"法規チェックリスト（{i + 1}/{len(pages)}）", 1, b.spec["project"])
        sh.frame()
        sh.text("法規チェックリスト（建築基準法・同施行令・関連法令／設計仕様書）", (12, 280), 4.0, "A-TEXT", paper=True)
        sh.table(12, 274, cols, [head] + pg, row_h=5.6, h=2.1)
        sh.text("判定: 適合／要確認（条例・関係機関協議・別途計算による）／対象外。数値はすべて建物モデルから自動算定。",
                (12, 44), 2.2, "A-TEXT", paper=True)
        sheets.append(sh)
    return sheets, rows, sm


def cover_sheet(b, drawing_list):
    sh = Sheet("A-00", "表紙・図面リスト・建築概要", 1, b.spec["project"])
    sh.frame()
    pr = b.spec["project"]
    s = b.spec
    sm = legal.summary(b)
    sh.text(pr["name"], (24, 262), 9.0, "A-TEXT", paper=True)
    sh.text(f"{pr['phase']}図　／　{pr['date']}　／　{pr['designer']}", (24, 250), 3.6, "A-TEXT", paper=True)
    sh.line(sh.P(24, 246), sh.P(396, 246), "A-SYMB", lineweight=50)
    rows = [["項目", "内容"],
            ["建設地", pr["location"]],
            ["主要用途", s["requirements"]["use"]],
            ["用途地域・防火", f"{s['site']['zoning']}・{s['site']['fire_zone']}"],
            ["指定建ぺい率・容積率", f"{s['site']['coverage_limit'] * 100:.0f}%・{s['site']['far_limit'] * 100:.0f}%"],
            ["前面道路", f"南側 {s['site']['road']['kind']} 幅員 {s['site']['road']['width'] / 1000:.1f}m"],
            ["敷地面積", f"{sm['site_area']:.2f} m²"],
            ["建築面積", f"{sm['building_area']:.2f} m²（建ぺい率 {sm['coverage'] * 100:.2f}%）"],
            ["延べ面積", f"{sm['total']:.2f} m²（容積対象 {sm['far_area']:.2f} m²・容積率 {sm['far'] * 100:.2f}%）"],
            ["構造・階数", f"鉄筋コンクリート造 地上{len(b.floors)}階 塔屋1階"],
            ["耐火性能", "耐火建築物"],
            ["高さ", f"建築物の高さ {sm['height']:.2f}m／軒の高さ {sm['eave']:.2f}m／最高 {sm['max_height']:.2f}m（塔屋）"],
            ["階高", " / ".join(f"{f} {b.H[f]:,}" for f in b.floors)],
            ["基礎", s["structure"]["foundation"]],
            ["昇降機", "乗用 11人乗 機械室なし 1基"],
            ["作図基準", "JIS A 0150 建築製図通則（線・記号）、モデル空間 1:1・単位mm、レイヤ分け（A-/S-/G-）"]]
    sh.text("建築概要", (24, 238), 4.0, "A-TEXT", paper=True)
    sh.table(24, 233, [40, 150], rows, row_h=7.0, h=2.6)
    sh.text("図面リスト", (232, 238), 4.0, "A-TEXT", paper=True)
    dl = [["図番", "図面名称", "縮尺"]] + [[n, t, sc] for n, t, sc in drawing_list]
    sh.table(232, 233, [22, 110, 32], dl, row_h=7.0, h=2.6)
    return sh
