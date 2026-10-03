"""図面シート共通の作図ヘルパー（投影の出力・寸法・建具記号・表）。"""
from __future__ import annotations

import math

from shapely.geometry import box as sbox

from cadlib import Sheet, _text_width
from views import VIEWS, iter_lines, iter_polygons, project

VIS_LAYER = {"concrete": "A-VIS", "lgs": "A-VIS", "glass": "A-GLAZ", "door": "A-DOOR", "stair": "A-STRS", "insul": "A-VIS"}


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
        elif k == "insul":
            if polys:
                sh.hatch_polys(polys, pattern="ANSI37", spacing=0.6, layer="A-CUT-INS")
            for pts in iter_lines(g2):
                sh.pline(pts, "A-CUT-LGS", lineweight=18)
        else:
            for pts in iter_lines(g2):
                sh.pline(pts, VIS_LAYER[k])
    for k, g in proj.visible:
        g2 = translate(g, dx, dy)
        for pts in iter_lines(g2):
            sh.pline(pts, VIS_LAYER[k], **({"lineweight": vis_lw} if vis_lw else {}))


# ======================================================================= plans
PLAN_ANCHOR_PAPER = (24.0, 56.0)   # 敷地南西角の用紙位置


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


def fittings_sheet(b, number):
    sh = Sheet(number, "建具表", 50, b.spec["project"], scale_label="1:50・1:100")
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
        mat = {"AW": "樹脂（アルミ樹脂複合）", "AD": "アルミ製 自動", "SD": "鋼製（断熱）", "WD": "木製", "SS": "鋼製 遮音"}[f["label"][:2]]
        if f["name"].startswith("EV"):
            mat = "EV メーカー標準"
        glass = ""
        if f["label"].startswith(("AW", "AD")) and f["label"][:2] != "SS":
            glass = "Low-E トリプルガラス（UVカット）・FIX"
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


def legal_sheets(b, start_number, rows):
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
    return sheets


