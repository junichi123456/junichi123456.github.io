"""河沿要（仮称）図面シート。すべて house.House モデルから生成する。"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon, box as sbox

from cadlib import Sheet, _text_width, _wrap
from sheetlib import T, emit, hdim, vdim, door_symbol, window_symbol, opening_tag, side_panel, uv_fn
from views import VIEWS, iter_lines, iter_polygons, project
import performance as PF

TATAMI = 1.62


def tp(h, z):
    return h.gl_tp + z / 1000.0


# ================================================================ helpers
def fit(h, sh, center_paper, margin=0):
    """敷地の外接矩形の中心を用紙上 center_paper に置く。"""
    x0, y0, x1, y1 = h.site_gross.bounds       # v4.22: 寄付地を含む旧境界の外接矩形（用紙上の配置を保つ）
    return T(sh, ((x0 + x1) / 2, (y0 + y1) / 2), center_paper)

def frame(h, number, title, scale, label=None):
    sh = Sheet(number, title, scale, h.spec["project"], scale_label=label)
    sh.frame()
    return sh


def grid(h, sh, t, ext=2300, r=3.6):
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


def _equip_by_id(h, prefix):
    return [e for e in h.spec["mech_rooms"]["equipment"] if e[0].startswith(prefix)]


def battery_room_draw(h, sh, t):
    """蓄電室（v4.26）: 間仕切り（LGS＋強化PB 1時間耐火）・特定防火設備・室名と面積・蓄電池ラック・蓄電 PCS・RC 束壁（破線）。
    ラック・PCS の位置は spec の mech_rooms から読む。"""
    x0, y0, x1, y1 = h.battery_room.rect
    for w in h.battery_walls:
        if w.axis == "x":
            sh.rect(*t(w.a, w.c - w.t / 2), *t(w.b, w.c + w.t / 2), "A-CUT-LGS")
        else:
            u = w.a
            for a_, b_ in sorted((op.u0, op.u1) for op in w.openings) + [(w.b, w.b)]:
                if a_ > u:
                    sh.rect(*t(w.c - w.t / 2, u), *t(w.c + w.t / 2, a_), "A-CUT-LGS")
                u = max(u, b_)
    door_symbol(sh, t, h.battery_door)
    sh.hatch_polys([sbox(*t(x0, y0), *t(x1, y1))], layer="E-BATT", pattern="ANSI31", spacing=2.5, color=1)
    sh.rect(*t(x0, y0), *t(x1, y1), "E-BATT")
    for e in _equip_by_id(h, "MB-"):
        sh.rect(*t(*e[3][:2]), *t(*e[3][2:]), "E-BATT" if "ラック" in e[2] else "E-PV", lineweight=35)
    for xb in (17550, 17850):                                         # RC 束壁（床下ピット、2列）
        sh.line(t(xb, y0 + 100), t(xb, y1 - 100), "A-HIDDEN", lineweight=25)
    sh.text("蓄電室", t(16900, 7700), 1.6, "A-ROOM", "MIDDLE_CENTER")
    sh.text(f"{h.battery_room.area:.1f}m²", t(16900, 7400), 1.3, "A-ROOM", "MIDDLE_CENTER")


def gym_clearance_draw(h, sh, t):
    """離隔帯（A-HIDDEN の破線）と搬入動線 R1・R2（A-FLOW）。"""
    cr = h.clearance_report()
    for g in iter_polygons(cr["zone"]):
        sh.pline([t(*p) for p in g.exterior.coords], "A-HIDDEN", closed=True)
    sh.text(f"離隔帯 {cr['need']}", t(14500, 8500), 1.2, "A-TEXT", "MIDDLE_CENTER")
    gl = h.spec["gym_layout"]["lanes"]
    r1, r2 = gl["R1"], gl["R2"]
    xm, yc = (r2[0] + r2[2]) / 2, (r1[1] + r1[3]) / 2
    pts = [(r1[0] + 150, yc), (xm, yc), (xm, r2[3] - 250)]
    sh.pline([t(*p) for p in pts], "A-FLOW")
    ex, ey = t(*pts[-1])
    a = 0.9 * sh.S
    sh.line((ex, ey), (ex - a * 0.5, ey - a), "A-FLOW")
    sh.line((ex, ey), (ex + a * 0.5, ey - a), "A-FLOW")
    sh.text("搬入 R1 W1,500 → R2 W800", t(13600, yc + 120), 1.2, "A-FLOW", "BOTTOM_CENTER")


def _swing_leaf(sh, t2, hinge, open_dir, closed_dir, width, scale):
    """詳細図（縮尺 scale）の開き戸: 蝶番 hinge、開いた戸 open_dir、閉じた戸 closed_dir は単位ベクトル（建物座標）。"""
    hp = t2(*hinge)
    R = width / scale * sh.S
    sh.line(hp, (hp[0] + open_dir[0] * R, hp[1] + open_dir[1] * R), "A-DOOR", lineweight=35)
    a0 = math.degrees(math.atan2(closed_dir[1], closed_dir[0])) % 360
    a1 = math.degrees(math.atan2(open_dir[1], open_dir[0])) % 360
    sh.arc(hp, R, a0, a1, "A-DOOR") if (a1 - a0) % 360 == 90 else sh.arc(hp, R, a1, a0, "A-DOOR")


def machine_battery_detail(h, sh, number_xy, scale=75):
    """A-03 の差込み拡大詳細（機械室2室＋蓄電室）。number_xy＝見出しの用紙座標。縮尺 1:scale（本図は 1:100）。
    室・扉・機器・スリーブはすべて spec の mech_rooms から読む。位置はいずれも仮置き（要確認）。
    戻り値: 枠の下端（用紙 y）。"""
    mr = h.spec["mech_rooms"]
    x0, y0, x1, y1 = 12250, 6075, 18125, 12000
    pw, ph = (x1 - x0) / scale, (y1 - y0) / scale
    left, top = number_xy[0], number_xy[1] - 8

    class _T:
        def __call__(self, u, v):
            return sh.P(left + 2 + (u - x0) / scale, top - 2 - (y1 - v) / scale)
    t2 = _T()
    sh.text(f"拡大詳細（機械室2室＋蓄電室）1:{scale}", (left, number_xy[1] - 3), 2.0, "A-TEXT", paper=True)
    bottom = top - ph - 4
    sh.rect(*sh.P(left, bottom), *sh.P(left + pw + 4, top), "G-TABLE")
    face = mr["wall_x_y"] + h.pt / 2                                     # 機械室側の壁面 9,000
    for name, r in (("機械室（西系統）", (12250, 9000, 15100, 12000)), ("機械室（東系統）", (15200, 9000, 18125, 12000))):
        sh.rect(*t2(r[0], r[1]), *t2(r[2], r[3]), "A-CUT-LGS")
        sh.text(name, t2((r[0] + r[2]) / 2, r[3] - 450), 1.3, "A-ROOM", "MIDDLE_CENTER")
    w89 = h.mech_doors[0][2].wall
    u = w89.a
    for a_, b_ in sorted((op.u0, op.u1) for op in w89.openings) + [(w89.b, w89.b)]:
        if a_ > u:
            sh.rect(*t2(u, w89.c - w89.t / 2), *t2(a_, w89.c + w89.t / 2), "A-CUT-LGS")
        u = max(u, b_)
    sh.rect(*t2(15100, 9000), *t2(15200, 12000), "A-CUT-LGS")                  # x15,150 の LGS（扉なし）
    sh.text("ジム", t2(13400, 7000), 1.5, "A-ROOM", "MIDDLE_CENTER")
    # 機械室の扉 W800（内開き・蝶番は西）
    for did, room, op in h.mech_doors:
        _swing_leaf(sh, t2, (op.u0, face), (0, 1), (1, 0), op.width, scale)
        sh.text(f"{did} W{op.width:.0f} 内開き", t2((op.u0 + op.u1) / 2, 8700), 1.1, "A-TEXT", "MIDDLE_CENTER")
    # 蓄電室
    bx0, by0, bx1, by1 = h.battery_room.rect
    sh.hatch_polys([sbox(*t2(bx0, by0), *t2(bx1, by1))], layer="E-BATT", pattern="ANSI31", spacing=2.0, color=1)
    sh.rect(*t2(bx0, by0), *t2(bx1, by1), "E-BATT")
    for w in h.battery_walls:
        if w.axis == "x":
            sh.rect(*t2(w.a, w.c - w.t / 2), *t2(w.b, w.c + w.t / 2), "A-CUT-LGS")
        else:
            u = w.a
            for a_, b_ in sorted((op.u0, op.u1) for op in w.openings) + [(w.b, w.b)]:
                if a_ > u:
                    sh.rect(*t2(w.c - w.t / 2, u), *t2(w.c + w.t / 2, a_), "A-CUT-LGS")
                u = max(u, b_)
    d = h.battery_door
    gx_ = bx0 - h.pt / 2
    _swing_leaf(sh, t2, (gx_, d.u0), (-1, 0), (0, 1), d.width, scale)
    sh.text("特定防火設備 W900", t2(gx_ - d.width - 60, d.u0 + 450), 1.1, "A-TEXT", "MIDDLE_RIGHT")
    sh.text("外開き・自閉", t2(gx_ - d.width - 60, d.u0 + 250), 1.1, "A-TEXT", "MIDDLE_RIGHT")
    for xb in (17550, 17850):
        sh.line(t2(xb, by0 + 100), t2(xb, by1 - 100), "A-HIDDEN", lineweight=25)
    # 機器（spec の mech_rooms.equipment）
    short = {"蓄電池ラック": "ラック", "蓄電 PCS（壁掛け）": "PCS", "空調・全熱交換（西系統）": "空調・全熱交換", "排煙機（西）": "排煙機", "排煙機（東）": "排煙機",
             "ネットワークラック（防振マット）": "ラック", "特定負荷分電盤": "特定負荷", "主分電盤": "主分電盤"}
    for eid, room, nm, r, hh in mr["equipment"]:
        pw_ = (r[2] - r[0]) / scale
        lay = "E-BATT" if eid.startswith("MB-") and "ラック" in nm else ("E-POWER" if "分電盤" in nm else ("E-PV" if "PCS" in nm else "A-VIS"))
        sh.rect(*t2(r[0], r[1]), *t2(r[2], r[3]), lay, lineweight=35)
        lab = next((v for k, v in short.items() if nm.startswith(k)), nm)
        vert = (r[3] - r[1]) > (r[2] - r[0]) * 1.3 and pw_ < 9
        sh.text(lab, t2((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), 1.0, "A-TEXT", "MIDDLE_CENTER", rot=90 if vert else 0)
    # 離隔帯（窓内）
    z = h.clearance_report()["zone"].intersection(sbox(x0, y0, x1, y1))
    for g in iter_polygons(z):
        sh.pline([t2(*p) for p in g.exterior.coords], "A-HIDDEN", closed=True)
    sh.text("離隔 800", t2(13700, 8450), 1.1, "A-TEXT", "MIDDLE_CENTER")
    # スリーブ（○ と記号のみ）
    for sid, wall, (sx, sy), dia, z_, use in mr["sleeves"]:
        c = t2(min(max(sx, x0), x1), min(max(sy, y0), y1))
        sh.circle(c, 0.7 * sh.S, "A-SYMB")
        dx = 1.1 if sx < 16000 else -1.1
        sh.text(sid, (c[0] + dx * sh.S, c[1] + (0.9 if sy >= 12000 else 0) * -sh.S), 0.9, "A-SYMB", "MIDDLE_LEFT" if dx > 0 else "MIDDLE_RIGHT")
    return bottom


def room_labels(h, sh, t, floor, hgt=2.6):
    for r in h.rooms:
        if r.floor != floor:
            continue
        x, y = r.label_at
        small = (r.rect[2] - r.rect[0]) < 1800 or (r.rect[3] - r.rect[1]) < 1500
        th = 2.0 if small else hgt
        sh.text(getattr(r, "label_name", r.name), t(x, y + 150), th, "A-ROOM", "MIDDLE_CENTER")
        sub = f"{r.area:.1f}m²"
        if r is getattr(h, "gym", None) and floor == "1F":
            sub = f"{r.area:.1f}m²（計{r.daylight_area:.1f}m²）"
        elif r.habitable or r.area > 12:
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


FLOWS = {
    "1F": [("回遊①", [(8600, 3400), (3500, 3400), (3800, 7800), (7200, 7000), (9500, 7000), (9500, 3400), (8600, 3400)]),
           ("回遊②", [(3000, 9500), (800, 11200), (800, 13000), (7600, 12950), (10800, 12900), (11350, 12900), (11350, 9000),
                      (7200, 7000), (3000, 9500)]),
           ("搬入", [(13100, -4800), (13100, -4300), (9100, -4300), (9100, 5150), (11350, 5150), (11350, 3500), (13300, 3500)])],   # v4.27: 搬入はホール→北西の扉（y5,150）→拡張部を南へ→X3 開口
    "2F": [("回遊③", [(9500, 7000), (3000, 7600), (1400, 5450), (9000, 5450), (9000, 7000), (9500, 7000)]),
           ("回遊④", [(11350, 9000), (11350, 12900), (7600, 12950), (5000, 13500), (4900, 10000), (7200, 7000), (11350, 9000)])],
}


def flows(h, sh, t, floor):
    S = sh.S
    for name, pts in FLOWS.get(floor, []):
        sh.pline(t.pts(pts), "A-FLOW")
        for (a, b) in zip(pts, pts[1:]):
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            ang = math.atan2(b[1] - a[1], b[0] - a[0])
            L = 350
            for s_ in (2.6, -2.6):
                sh.line(t(*m), t(m[0] - L * math.cos(ang + s_ / 4.5), m[1] - L * math.sin(ang + s_ / 4.5)), "A-FLOW")
        p = pts[0]
        sh.text(name, t(p[0] + 150, p[1] + 250), 1.7, "A-FLOW")


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
        elif kind in ("cw", "sw"):          # 車道・歩道（#333333）
            poly = sbox(a[0], a[1] - 1.1 * S, c[0], c[1] + 1.1 * S)
            sh.hatch_polys([poly], pattern="ANSI31", spacing=3.0 if kind == "cw" else 1.5, layer=lay, rgb=ROAD_RGB)
            sh.rect(a[0], a[1] - 1.1 * S, c[0], c[1] + 1.1 * S, lay, lineweight=35, true_color=ROAD_TC)
        elif kind == "don":                 # 寄付地: 45°・135° の斜め格子 間隔2.0mm（v4.22）
            poly = sbox(a[0], a[1] - 1.1 * S, c[0], c[1] + 1.1 * S)
            for ang in (0.0, 90.0):
                sh.hatch_polys([poly], pattern="ANSI31", spacing=2.0, layer=lay, rgb=ROAD_RGB, angle=ang)
            sh.rect(a[0], a[1] - 1.1 * S, c[0], c[1] + 1.1 * S, lay, true_color=ROAD_TC)
        elif kind == "plnt":                # 植栽: 高木（葉張りの円＋中心の点）と地被（点）
            m = P(x + 3.5, cy)
            sh.circle(m, 1.8 * S, lay)
            sh.hatch_polys([Point(*m).buffer(0.35 * S)], solid=True, color=3, layer=lay)
            sh.hatch_polys([Point(*P(x + 9.5, cy)).buffer(1.5 * S)], pattern="DOTS", spacing=1.6, layer=lay)
        elif kind == "fence":
            sh.rect(a[0], a[1] - 0.5 * S, c[0], c[1] + 0.5 * S, lay)
            sh.hatch_polys([sbox(a[0], a[1] - 0.5 * S, c[0], c[1] + 0.5 * S)])
        else:
            sh.line(a, c, lay)
        sh.text(lab, P(x + 15, cy - 0.9), 2.0, "A-TEXT")
        cy -= 4.6
    return cy


# ================================================================ site
ROAD_RGB = (0x33, 0x33, 0x33)
ROAD_TC = 0x333333


def road_draw(h, sh, t, win, avoid=None):
    """車道（ハッチ間隔 3.0mm）と歩道（同 1.5mm）を #333333 で描く（v4.21）。形状は spec.yaml の roads。"""
    for name, r in h.roads.items():
        if name == "color":
            continue
        for key, lay, sp in (("cw", "A-ROAD-CW", 3.0), ("sw", "A-ROAD-SW", 1.5)):
            if not r.get(key):
                continue
            for p in iter_polygons(Polygon(r[key]).difference(h.site).difference(h.donation_poly).intersection(win)):   # 敷地・寄付地と重なる分は差し引く（v4.22）
                q0 = Polygon(t.pts(p.exterior.coords))
                if avoid:                  # 表題・注記（用紙mm の箱）に重ならないよう道路の描画から除く
                    q0 = q0.difference(sbox(*sh.P(avoid[0], avoid[1]), *sh.P(avoid[2], avoid[3])))
                for q in iter_polygons(q0):
                    sh.hatch_polys([q], pattern="ANSI31", spacing=sp, layer=lay, rgb=ROAD_RGB)
                    sh.pline(list(q.exterior.coords), lay, closed=True, lineweight=35, true_color=ROAD_TC)


DONATE_LABEL = "歩行者専用道路（市へ割譲・舗装要件協議）"


def donation_draw(h, sh, t, label_h=1.6, labels=True):
    """寄付地（塀外の帯）: 45°・135° の斜め格子（間隔2.0mm、#333333）、寄付地境界（旧敷地境界）の破線、ラベル（v4.22）。
    車道（平行 3.0mm）・歩道（平行 1.5mm）と見分けられる。ラベルは東辺（帯に沿って回転）と北東角に1か所ずつ。"""
    polys = [Polygon(t.pts(p.exterior.coords)) for p in iter_polygons(h.donation_poly)]
    for ang in (0.0, 90.0):
        sh.hatch_polys(polys, pattern="ANSI31", spacing=2.0, layer="A-DONATE", rgb=ROAD_RGB, angle=ang)
    for q in polys:
        sh.pline(list(q.exterior.coords), "A-DONATE", closed=True, true_color=ROAD_TC)
    sh.pline(t.pts([p for p in h.gross_edges_pts]), "A-DONATE-BND", closed=True)
    if not labels:
        return
    fl = h.fence_line_pts
    (x1, y1), (x2, y2), (x3, y3) = fl[1], fl[2], fl[3]
    ang = math.degrees(math.atan2(y2 - y3, x2 - x3))             # 東辺（F3→F2）に沿って下から上へ読む
    mx, my = (x2 + x3) / 2, (y2 + y3) / 2
    nx, ny = (y3 - y2), -(x3 - x2)                                 # 塀から外向き（東）の法線
    n = math.hypot(nx, ny) or 1
    sh.text(DONATE_LABEL + "　約%dm²（要確認）" % round(h.donation_poly.area / 1e6), t(mx + nx / n * 1200, my + ny / n * 1200), label_h, "A-DONATE", "MIDDLE_CENTER", rot=ang, true_color=ROAD_TC)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    sh.text("歩行者専用道路", t(cx + 2600, cy + 1500), label_h, "A-DONATE", "MIDDLE_CENTER", true_color=ROAD_TC)
    sh.text("約%dm²（要確認）" % round(h.donation_poly.area / 1e6), t(cx + 2600, cy - 400), label_h, "A-DONATE", "MIDDLE_CENTER", true_color=ROAD_TC)


def site_base(h, sh, t, neighbors=True, contours=False, margin=9000, roads=False, margin_top=None, road_avoid=None, donation=False, label_h=1.6):
    x0, y0, x1, y1 = h.site_gross.bounds
    win = sbox(x0 - margin, y0 - margin, x1 + margin, y1 + (margin if margin_top is None else margin_top))
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
    if roads:
        road_draw(h, sh, t, win, road_avoid)
    if donation:
        donation_draw(h, sh, t, label_h=label_h)
    for wi, w in enumerate(h.water):
        if roads and wi == 0 and (h.roads.get("north") or {}).get("sw"):
            continue                       # 歩道（水路の蓋掛け部）として描くので水路のハッチは重ねない
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


def fence_draw(h, sh, t, label=False, clip=None):
    from shapely.ops import unary_union
    parts = []
    for ln in h.fence_lines:                 # 塀の芯線を敷地の内側へ t/2 寄せた帯
        for k in range(len(ln.coords) - 1):
            seg = LineString(ln.coords[k:k + 2])
            if seg.length < 1:
                continue
            o = seg.parallel_offset(h.fence_t / 2, "left")
            if not h.fence_poly.contains(o.interpolate(0.5, normalized=True)):
                o = seg.parallel_offset(h.fence_t / 2, "right")
            parts.append(o.buffer(h.fence_t / 2, cap_style=2, join_style=2))
    band = unary_union(parts).buffer(1, join_style=2).buffer(-1, join_style=2)
    if clip is not None:
        band = band.intersection(clip)
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
    site_base(h, sh, t, contours=True, roads=True, donation=True, label_h=1.7)
    fence_draw(h, sh, t)
    proj = project(h.boxes, "plan", filt=lambda b: b.z1 > h.fgl and b.level != "FDN")
    emit(sh, proj, t, cut_lw=25, vis_lw=9)
    house_outline(h, sh, t)
    # 駐車場・ソーラーパーゴラ
    sh.hatch_polys([Polygon(t.pts(h.dotcon.exterior.coords))], pattern="NET", spacing=1.0, layer="A-PAVE")
    sh.hatch_polys([Polygon(t.pts(p.exterior.coords), [t.pts(r.coords) for r in p.interiors]) for p in iter_polygons(h.dotcon_garden)],
                   pattern="NET", spacing=1.0, layer="A-PAVE")
    cp = h.carport
    pg = h.pergola
    sh.rect(*t(pg[0], pg[1]), *t(pg[2], pg[3]), "A-VIS", lineweight=25)
    sh.line(t(pg[0], pg[1]), t(pg[2], pg[3]), "A-VIS")
    sh.line(t(pg[0], pg[3]), t(pg[2], pg[1]), "A-VIS")
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
    sh.text("ソーラーパーゴラ（菜園）", t((pg[0] + pg[2]) / 2, pg[1] - 2000), 1.8, "A-TEXT", "MIDDLE_CENTER")
    sh.text("庭・雨水貯留浸透", t(-17000, 27500), 1.9, "A-TEXT", "MIDDLE_CENTER")
    sh.text("破線: 既存建物（解体）", t(-8000, 26000), 1.7, "A-TEXT", "MIDDLE_CENTER")
    for (x, y) in [(8600, 8600), (-18000, 18000), (8000, -24000), (8000, 40000), (30000, 15000), (-10000, -40000), (25000, -25000)]:
        z = h.ground(x, y)
        sh.text(f"+{tp(h, z):.1f}", t(x, y - 1800), 1.6, "A-TERRAIN", "MIDDLE_CENTER")
        sh.line(t(x - 400, y), t(x + 400, y), "A-TERRAIN")
        sh.line(t(x, y - 400), t(x, y + 400), "A-TERRAIN")
    sh.north_arrow(sh.P(30, 270), 6, rot=h.facade_az)
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
             ["敷地面積（新境界＝塀の外面）", f"{sm['site_area']:,.2f} m²（{sm['site_area'] / 3.305785:,.1f}坪）"],
             ["旧境界（寄付地境界）の面積", f"{h.site_gross.area / 1e6:,.2f} m²"],
             ["寄付地（塀外の帯・市へ割譲の提案）", f"約{h.donation_poly.area / 1e6:,.2f} m²（要確認）"],
             ["（検算）新 + 寄付地", f"{sm['site_area']:,.2f} + {h.site_gross.area / 1e6 - sm['site_area']:,.2f} = {h.site_gross.area / 1e6:,.2f}"],
             ["建築面積（壁芯＋庇の先端から1m後退）", f"{sm['building_area']:.2f} m²"],
             ["延べ面積", f"{sm['total']:.2f} m²"],
             ["建ぺい率", f"{sm['coverage'] * 100:.2f}%（≦60%）"],
             ["容積率", f"{sm['far'] * 100:.2f}%（≦200%）"]]
    sh.table(250, 150, [52, 68], rows2, row_h=5.2, h=2.1)
    sh.text("※ 西側境界は標高109.6の点を通り駐車場白線に平行な直線（ご指定）。13〜15は隣接建物からの推定（要測量）。", (250, 98), 1.9, "A-TEXT", paper=True)
    sh.text("※ 塀の外面を新しい敷地境界とし、塀外の帯（寄付地）は市へ割譲し歩行者専用道路とする提案（寄付・道路認定は要確認）。", (250, 93), 1.9, "A-TEXT", paper=True)
    sh.text("   赤線の座標は概算・要確認（±0.7m）。破線: 寄付地境界（旧敷地境界）。斜め格子: 寄付地。", (250, 88), 1.9, "A-TEXT", paper=True)
    sh.text("※ 道路・歩道（#333333）は基盤地図の道路縁・水路から作図（歩道の有無・幅は要確認）。", (250, 83), 1.9, "A-TEXT", paper=True)
    return sh


def exterior_plan(h, number):
    sh = frame(h, number, "外構・給排水計画図", 400)
    t = fit(h, sh, (150, 168))
    site_base(h, sh, t, contours=False, roads=True, donation=True)
    # 舗装
    sh.hatch_polys([Polygon(t.pts(h.dotcon.exterior.coords))], pattern="NET", spacing=0.9, layer="A-PAVE")
    sh.pline(t.pts(h.dotcon.exterior.coords), "A-PAVE", closed=True)
    fr = h.farm                                      # 日なたのプランター菜園（Dotcon+ の上）
    sh.hatch_polys([sbox(*t(fr[0], fr[1]), *t(fr[2], fr[3]))], pattern="NET", spacing=0.9, layer="A-PAVE")
    sh.rect(*t(fr[0], fr[1]), *t(fr[2], fr[3]), "A-PAVE")
    for pl in h.planters:
        sh.rect(*t(pl[0], pl[1]), *t(pl[2], pl[3]), "A-VIS", lineweight=25)
    sh.text("日なたのプランター菜園", t(fr[2] + 600, (fr[1] + fr[3]) / 2), 1.6, "A-TEXT", "MIDDLE_LEFT")
    for p in iter_polygons(h.dotcon_garden):          # 菜園まわりの Dotcon+（通路・北と西の帯）
        sh.hatch_polys([Polygon(t.pts(p.exterior.coords), [t.pts(r.coords) for r in p.interiors])], pattern="NET", spacing=0.9, layer="A-PAVE")
        sh.pline(t.pts(p.exterior.coords), "A-PAVE", closed=True)
        for r in p.interiors:
            sh.pline(t.pts(r.coords), "A-PAVE", closed=True)
    ap = h.approach.intersection(h.fence_poly.buffer(-h.fence_t))
    for p in iter_polygons(ap):
        sh.pline(t.pts(p.exterior.coords), "A-PAVE", closed=True)
        sh.hatch_polys([Polygon(t.pts(p.exterior.coords))], pattern="ANSI37", spacing=2.5, layer="A-PAVE")
    fence_draw(h, sh, t, label=True)
    proj = project(h.boxes, "plan", filt=lambda b: b.z1 > h.fgl and b.level != "FDN")
    emit(sh, proj, t, cut_lw=25, vis_lw=9)
    house_outline(h, sh, t)
    cp = h.carport
    pg = h.pergola
    sh.rect(*t(pg[0], pg[1]), *t(pg[2], pg[3]), "A-HIDDEN")
    for i in range(1, 7):
        yy = pg[1] + i * (pg[3] - pg[1]) / 7
        sh.line(t(pg[0], yy), t(pg[2], yy), "A-VIS", lineweight=9)
    sh.text("日よけ付き菜園（ソーラーパーゴラ・独立架台 18×10m）", t((pg[0] + pg[2]) / 2, pg[1] - 900), 1.7, "A-TEXT", "MIDDLE_CENTER")
    for s in h.stalls:
        sh.rect(*t(s[0], s[1]), *t(s[2], s[3]), "A-VIS")
    sh.rect(*t(cp[0], cp[1]), *t(cp[2], cp[3]), "A-HIDDEN")
    sh.text(f"3台用ソーラーカーポート {(cp[2] - cp[0]) / 1000:.1f}×{(cp[3] - cp[1]) / 1000:.1f}m", t(cp[2] + 1500, (cp[1] + cp[3]) / 2), 1.7, "A-TEXT", "MIDDLE_LEFT")
    sw_ = h.screen[0]
    sh.text(f"目隠し壁（自立・独立基礎）L{(sw_[2] - sw_[0]) / 1000:.1f}m H{(h.screen_top - h.fgl) / 1000:.1f}m", t(sw_[0] - 600, sw_[1] - 300), 1.5, "A-TEXT", "MIDDLE_RIGHT")
    sh.text("建物（壁式RC造 2階建て）", t(h.W / 2, h.D / 2), 2.0, "A-ROOM", "MIDDLE_CENTER")
    sh.text("Dotcon+ 透水舗装", t(cp[2] + 1500, cp[1] - 1500), 1.7, "A-TEXT", "MIDDLE_LEFT")
    sh.text("アプローチ（Dotcon+）", t(14500, -10200), 1.6, "A-TEXT", "MIDDLE_LEFT")
    sh.text("アプローチ → 玄関（ジム搬入も同じ）", t(14500, -8400), 1.6, "A-TEXT", "MIDDLE_LEFT")
    gbx = h.garbage_box
    sh.text(f"門を道路境界から{h.spec['exterior']['gate_setback'] / 1000:.1f}m 後退（門前スペース）", t(23500, h.y_gate - 1800), 1.5, "A-TEXT", "MIDDLE_LEFT")
    sh.text("ゴミ収集ボックス（門の外・L形の目隠し壁の裏、A-02D）", t(gbx[0] - 300, gbx[3] + 900), 1.4, "A-TEXT", "MIDDLE_RIGHT")
    # 貯留槽・浸透
    tk = h.tank
    sh.rect(*t(tk[0], tk[1]), *t(tk[2], tk[3]), "A-DRAIN")
    sh.line(t(tk[0], tk[1]), t(tk[2], tk[3]), "A-DRAIN")
    sh.text(f"地下雨水貯留槽 {h.spec['exterior']['retention_tank_m3']}m³（密閉・防虫網0.4mm・フラップ弁）", t((tk[0] + tk[2]) / 2, tk[3] + 900), 1.7, "A-TEXT", "MIDDLE_CENTER")
    st_ = h.ext_storage
    sh.text(f"菜園・北・東 Dotcon+ 約{st_['dotcon_area_garden']:.0f}m²", t(-20000, 31000), 1.7, "A-TEXT", "MIDDLE_CENTER")
    for p in h.infil_pits:
        sh.circle(t(*p), 0.9 * sh.S, "A-DRAIN")
    for p in h.flap:
        sh.rect(*t(p[0] - 500, p[1] - 500), *t(p[0] + 500, p[1] + 500), "A-DRAIN")
        sh.text("排水口（フラップ弁）", t(p[0] + 800, p[1]), 1.5, "A-TEXT", "MIDDLE_LEFT")
    # 外からの流入方向（高い側 → 敷地）
    for (a, b) in [((0, 44000), (0, 36000)), ((-20000, 46000), (-20000, 40000)), ((30000, 22000), (22000, 18000)),
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
    for (x, y, s) in [(8600, -1500 - 1800, f"1FL GL+{h.fl['1F']:,}"), (-12000, 4000, f"FGL GL+{h.fgl}（現況維持）"),
                      (6000, -31800, "設計GL±0（南側道路 TP+109.0）")]:
        sh.text(s, t(x, y), 1.6, "A-SYMB", "MIDDLE_CENTER")
    for cn in h.canopies:                               # 連続庇（v4.18）
        sh.rect(*t(cn[0], cn[1]), *t(cn[2], cn[3]), "A-HIDDEN")
    for (px, py) in h.spec["exterior"]["canopy"]["downpipes"]:
        sh.circle(t(px, py), abs(t(500, 0)[0] - t(0, 0)[0]), "A-DRAIN")
    sh.text("連続庇 縦樋（西→雨水貯留槽、東→浸透桝）", t(-9000, 5500), 1.5, "A-TEXT", "MIDDLE_CENTER")
    _planting_draw(h, sh, t)
    _utilities_draw(h, sh, t, labels=True)
    sh.north_arrow(sh.P(282, 60), 6, rot=h.facade_az)
    sh.view_title("外構・給排水計画図", "1:400", (18, 22))
    ly_ = legend(sh, 300, 280, [("A-FENCE", "RC塀 t=150（数値=FGLからの天端高 m）", "fence"),
                          ("A-PAVE", "Dotcon+ 透水舗装", "pave"),
                          ("A-DRAIN", "浸透桝・貯留槽", "line"),
                          ("A-FLOOD", "表流水の流入方向", "line"),
                          ("A-SITE", "敷地境界（新・塀の外面）", "line"),
                          ("A-ROAD-CW", "車道（#333333）", "cw"), ("A-ROAD-SW", "歩道（#333333・要確認）", "sw"),
            ("A-DONATE", "寄付地（市へ割譲の提案・要確認）", "don"), ("A-DONATE-BND", "寄付地境界（旧敷地境界）", "line"),
                          ("E-PLNT", "植栽（仮置き・要確認）", "plnt"),
                          ("E-WATER", "上水（給水管・量水器 □）", "line"), ("E-SEWER", "汚水（○×は汚水桝 汚1〜）", "line")])
    st = h.ext_storage
    notes = [("h", "内水対策"),
             ("t", f"1. RC塀の基礎〜FGL+{h.spec['requirements']['fence_watertight']}を止水構造。門扉には着脱式止水板 H600"),
             ("t", f"2. Dotcon+ 約{st['dotcon_area']:.0f}m²（駐車場・アプローチ {st['dotcon_area_parking']:.0f}m²＋菜園・北・東の帯 {st['dotcon_area_garden']:.0f}m²）× 13L/m² ≒ {st['dotcon_l'] / 1000:.1f}m³ の一時貯留"),
             ("t", f"3. 地下貯留槽 {st['tank_m3']}m³（菜園の散水に利用）。菜園まわりの透水設備は浸透トレンチに代えて全て Dotcon+（透水係数は地盤調査で確認）"),
             ("t", "4. 塀の低い位置にフラップ弁付き排水口（道路側溝からの逆流防止）"),
             ("t", "5. 建物: 1FL=GL+1,500、床下は設備ピット、逆流防止弁・排水ポンプ（非常電源）"),
             ("t", f"参考: 時間雨量50mmで敷地全体の流出量は約{h.site.area / 1e6 * 0.05:.0f}m³/h。貯留・浸透は初期雨水の抑制が主目的で、超過分は止水と排水ポンプで対応"),
             ("h", "防犯"),
             ("t", "RC塀 H2.0m（東側の坂道沿いは道路面+1.2m以上）。上部に侵入防止金物、センサーライト・防犯カメラ、門扉は塀と同じ高さ"),
             ("h", "給排水（仮置き・要確認）"),
             ("t", "管径・勾配は下表。汚水と雨水は別の管・別の最終桝（分流式と仮定）。公共管の位置・深さ、分流式かどうかは上下水道局で確認。壁・塀・目隠し壁の基礎はスリーブ貫通"),
             ("t", "レベル: 設計GL±0（南側道路 TP+109.0）、FGL=GL+450（TP+109.45）、1FL=GL+1,500。土かぶり 宅地内300mm以上。" + h.spec["utilities"]["levels"]["final_invert"])]
    cy = side_panel(sh, 300, ly_ - 4, notes, width=105)
    u = h.spec["utilities"]
    ln = lambda key: sum(g.length for g in h.pipes[key]) / 1000
    pr = [["管", "管種・口径", "勾配", "延長"],
          ["上水（量水器→機械室）", u["water"]["dia"], "—", f"約{ln('water'):.0f}m"],
          ["汚水（汚1〜汚%d）" % len(h.sewer_manholes), u["sewer"]["pipe"], u["sewer"]["slope"], f"約{ln('sewer'):.0f}m"],
          ["雨水 西（縦樋→貯留槽→浸透桝）", "塩ビ " + u["storm"]["pipe"], u["storm"]["slope"], f"約{ln('storm_w'):.0f}m"],
          ["雨水 東（縦樋→浸透桝→雨水最終桝）", "塩ビ " + u["storm"]["pipe"], u["storm"]["slope"], f"約{ln('storm_e'):.0f}m"]]
    cy = sh.table(300, cy - 1, [48, 33, 11, 13], pr, row_h=4.4, h=1.8)
    sh.text("植栽（仮置き・要確認）", (300, cy - 4), 2.6, "A-TEXT", paper=True)
    plr = [["記号", "樹種", "寸法", "数量"]]
    for k, nm in (("高木", "T"), ("中木", "M")):
        ps = [p for p in h.plants if p["kind"] == k]
        plr.append([f"{ps[0]['id']}" + (f"〜{ps[-1]['id']}" if len(ps) > 1 else ""), f"{k}: {ps[0]['species']}",
                    f"H{ps[0]['h'] / 1000:.1f}m・葉張り{ps[0]['crown'] / 1000:.1f}m", f"{len(ps)}本"])
    sp = h.shrub
    plr.append([sp["id"], f"低木: {sp['species']}", f"H{sp['h'] / 1000:.1f}m・延長{sp['line'].length / 1000:.0f}m", "1列"])
    plr.append(["G", f"地被: {h.spec['planting']['groundcover']['species']}", f"T1・T2の根元 φ{h.spec['planting']['groundcover']['dia'] / 1000:.1f}m", "2か所"])
    cy = sh.table(300, cy - 6, [14, 47, 34, 10], plr, row_h=4.4, h=1.8)
    side_panel(sh, 300, cy - 4, [("t", "防草シート＋砂利: 建物まわり1.0m・北の2H範囲（植えない）。塀外の帯は寄付地（歩行者専用道路の提案・要確認）で、植栽・設備は置かない。避ける樹種: ツバキ・サザンカ・サクラ・ウメ・柑橘")], width=105)
    return sh


# ================================================================ plans
def plan_projection(h, floor):
    """平面図の切断投影（FL+1,100 で切る）。floor_plan と site_integrated が共用する。"""
    fl = h.fl[floor]
    cut = fl + 1100
    zmin = fl - 1 if floor == "1F" else fl - h.H["1F"] / 2 - 1
    return project(h.boxes, "plan", cut=-cut, depth_limit=-zmin if floor == "2F" else -(h.fgl - 1),
                   filt=lambda b: not ((b.cat in ("glass", "door") and b.z0 < cut < b.z1)
                                       or (b.cat == "stair" and b.level != "EXT" and b.z1 > cut)))


def floor_plan(h, floor, number):
    names = {"1F": "1階平面図", "2F": "2階平面図"}
    sh = frame(h, number, names[floor], 100)
    t = T(sh, (0, 0), (52, 73))
    fl = h.fl[floor]
    cut = fl + 1100
    proj = plan_projection(h, floor)
    emit(sh, proj, t)
    grid(h, sh, t)
    plan_dims(h, sh, t, floor)
    for w in h.walls:
        if w.cat == "insul":
            continue
        for op in w.openings:
            if op.floor == floor and op.kind == "window" and op.z0 >= cut:
                # 切断面より上の高窓は破線で表示
                w_ = op.wall
                p0 = t(op.u0, w_.c) if w_.axis == "x" else t(w_.c, op.u0)
                p1 = t(op.u1, w_.c) if w_.axis == "x" else t(w_.c, op.u1)
                sh.line(p0, p1, "A-HIDDEN", lineweight=35)
                opening_tag(sh, t, op, offset=650)
                continue
            if op.floor != floor or not (op.z0 < cut < op.z1) or op.operation == "opening":
                continue
            if op.kind == "door":
                door_symbol(sh, t, op)
            else:
                window_symbol(sh, t, op)
            if op.label:
                opening_tag(sh, t, op, offset=650)
    stair_marks(h, sh, t, floor)
    if floor == "2F":
        # 階段まわりの手すり壁（すき間なしのパネル）を塗りつぶしで示す
        from shapely.geometry import box as sbox
        gs = [b for _, b in h.guards] + [b for b in h.boxes if b.tag == "手すり壁"]
        polys = [sbox(*t(b.x0, b.y0), *t(b.x1, b.y1)) for b in gs]
        sh.hatch_polys(polys, solid=True, color=8)
        for _, b in h.guards[:1]:
            p = t((b.x0 + b.x1) / 2, b.y0)
            q = (p[0] + 1 * sh.S, p[1] - 3 * sh.S)
            sh.line(p, q, "A-SYMB")
            sh.text(f"手すり壁 H{h.spec['interior']['guard_height']:,}（すき間なし）", (q[0] + 0.5 * sh.S, q[1]), 1.6, "A-TEXT", "MIDDLE_LEFT")
    room_labels(h, sh, t, floor)
    flows(h, sh, t, floor)
    if floor == "1F":
        sh.text(f"玄関ポーチ・外部階段 {h.ext_stair['n']}段", t(7600, -3600), 1.4, "A-TEXT", "MIDDLE_RIGHT")
        for cn in h.canopies:
            sh.rect(*t(cn[0], cn[1]), *t(cn[2], cn[3]), "A-HIDDEN")
        cs = h.canopies[0]
        sh.text("連続庇 南の出2,000・西の出1,000（破線、下端 FL+2,900）", t(cs[2] + 300, cs[1] + 300), 1.4, "A-TEXT", "MIDDLE_LEFT")
        for (lx, ly, _) in h.canopy_lights:
            sh.circle(t(lx, ly), abs(t(60, 0)[0] - t(0, 0)[0]), "A-SYMB")
        sw = h.screen[0]
        sh.text(f"玄関南 約{(h.porch[1] - sw[3]) / 1000:.1f}mに目隠し壁（自立・独立基礎 L{(sw[2] - sw[0]):,.0f}×H{h.spec['exterior']['screen_wall']['height']:,}、A-02参照）", t(11000, -3600), 1.3, "A-TEXT", "MIDDLE_LEFT")
        # 二重框・下足入れ
        g = h.genkan
        sh.line(t(g["doma"][0], g["doma"][3]), t(g["doma"][2], g["doma"][3]), "A-VIS", lineweight=35)
        sh.text(f"框1 +{g['step']}", t(9800, 1850), 1.4, "A-TEXT", "TOP_CENTER")
        sh.text(f"框2 +{g['step']}", t(9800, 2550), 1.4, "A-TEXT", "BOTTOM_CENTER")
        sh.rect(*t(*h.shoe[:2]), *t(*h.shoe[2:]), "A-VIS")
        sh.line(t(*h.shoe[:2]), t(*h.shoe[2:]), "A-VIS")
        sh.text("下足入れ", t(6475, 1100), 1.4, "A-TEXT", "MIDDLE_CENTER", rot=90)
        sh.text(f"土間 1FL-{2 * g['step']}", t(8000, 600), 1.5, "A-TEXT", "MIDDLE_CENTER")
        sh.rect(*t(*h.bench[:2]), *t(*h.bench[2:]), "A-VIS")
        sh.text("ベンチ", t((h.bench[0] + h.bench[2]) / 2, 800), 1.3, "A-TEXT", "MIDDLE_CENTER", rot=90)
        # ジム機器
        for name, r, hh, kg in h.equipment:
            sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "A-VIS", lineweight=25)
            vert = (r[3] - r[1]) > (r[2] - r[0]) * 1.3
            sh.text(name, t((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), 1.3, "A-TEXT", "MIDDLE_CENTER", rot=90 if vert else 0)
        battery_room_draw(h, sh, t)
        gym_clearance_draw(h, sh, t)
        z = h.treadmill_zone
        sh.rect(*t(z[0], z[1]), *t(z[2], z[3]), "A-HIDDEN")
        sh.text("トレッドミル後方 安全帯2.0m", t((z[0] + z[2]) / 2, z[1] + 300), 1.3, "A-TEXT", "MIDDLE_CENTER")

    sh.north_arrow(sh.P(395, 268), 7, rot=h.facade_az)
    sh.view_title(names[floor], "1:100", (24, 22))
    sh.text(f"{floor[:-1]}FL = 設計GL+{fl:,}（TP+{tp(h, fl):.2f}）／天井高 CH={h.ch[floor]:,}", (24, 15), 2.4, "A-TEXT", paper=True)
    cy = side_panel(sh, 284, 282, [("h", "凡例")])
    cy = legend(sh, 285, cy - 1, [("A-CUT", "RC壁 t=250（耐力壁）", "hatch"), ("A-CUT-LGS", "外断熱100＋外装20", "ins"),
                                    ("A-CUT-LGS", "乾式間仕切（LGS）t=100", "line"), ("A-GRID", "通り芯（壁芯）", "line"),
                                    ("A-FLOW", "動線（回遊・家事・搬入）", "line")])
    notes = [("h", "計画の考え方（v4・B案 内寸18.0m角）")]
    if floor == "1F":
        cr = h.clearance_report()
        import house_legal
        cr_wq = house_legal.wall_quantity(h)[("1F", "Y方向")][1]
        cr_ecc = PF.seismic(h)["stories"][("1F", "Y方向")]["ecc"]
        notes += [("t", "回遊①（家族）: 玄関ホール→LDK→キッチン→ホール→玄関。行き止まりのない一周動線"),
                  ("t", "回遊②（家事）: キッチン→ランドリー→洗面脱衣→廊下→ホール→キッチン"),
                  ("t", "洗う→干す→しまう: ランドリー・室内干し → 隣のファミリークローゼット／階段2で2階ファミクロへ直行"),
                  ("t", f"ジム {h.gym.daylight_area:.1f}m²（本体{h.gym.area:.1f}＋拡張部{h.gym_annex.area:.1f}）。S・E 外壁 t300（室内側+50・LDK 並み）。扉 北西 W1,200 Ts-45、IW-1 は南 u1,000〜2,415 へ。X3 開口 W4,035（壁量 {cr_wq:.1f}cm/m²・偏心 {cr_ecc:.3f}）"),
                  ("t", f"機械室・蓄電室: 3室ともジムに開口（扉1か所ずつ）。機器との離隔 最小 {cr['min'][1] / 1000:.2f}m（≧0.80）、有効面積 {cr['usable']:.1f}m²（≧44.85）。破線=離隔帯、搬入動線 R1・R2"),
                  ("t", "要確認: ①X3 北端 4,850（提出線 4,830 と前回 5,650 の差の解釈）②機械室の扉は内開きと読んだ③蓄電室の扉位置（書き込みなし）／外壁t300・扉W1,200・IW-1再配置／ベンチ・居室A窓・浴室壁t200／機器の隙間200〜300／スリーブ SL1〜12 の径と補強"),
                  ("t", "玄関: SICなし（土間に下足入れ・ベンチ）。二重框: 土間 1FL-360 → 式台 1FL-180 → ホール 1FL。中央スパン6.0mで土間幅5.75m"),
                  ("t", "階段1: 有効幅1,150・蹴上177.8・踏面260。中央のトイレは手洗い付き 3.9m²"),
                  ("t", "ジム床: 5,000N/m²（提案）・浮き床。直天井（CH 約2,900）を推奨"),
                  ("t", "ジムの窓: 外部扉なし。天井際の FIX 高窓（窓台 FL+2,000）に集約"),
                  ("t", "防音: ジムは浮き床＋遮音ドア Ts-45（二重壁D-55相当）、機械室・WIC を緩衝帯として居室Aと分離。真上は2階シアター（騒音ゾーンを上下に集約）"),
                  ("t", "排煙: LDK・ジム・居室Aは機械排煙（令126条の3）。窓は全窓 FIX の樹脂サッシ・Low-E トリプル（UVカット防犯合わせ CP、全窓）。南・東・西は外付け電動スクリーン（M-03）")]
    else:
        notes += [("t", "回遊③: ホール→図書室→南廊下→ホール。回遊④: ホール→洗面→階段2ホール→図書室→ホール"),
                  ("t", "窓: 全窓 FIX（樹脂サッシ・Low-E トリプル・UVカット合わせガラス、Uw≦0.90）。南・東・西は外付け電動スクリーン（M-03）。排煙は各居室の天井排煙口による機械排煙（A-10 参照）"),
                  ("t", "防音: シアターは前室（音響ロック）＋両開き遮音扉 Ts-40。主寝室とは前室・WIC の2層で分離"),
                  ("t", "居室B・C・D は収納・WIC を間に挟んで隣室と分離（戸境に収納）"),
                  ("t", "ファミリークローゼット: 1階ランドリーから階段2で直結")]
    notes += [("t", "寸法: mm、面積: 壁芯内法の概算")]
    cy = side_panel(sh, 284, cy - 3, notes, width=118)
    if floor == "1F":                                   # v4.26 拡大詳細は注記欄の下端から 4mm 下（凡例・注記と重ねない）
        btm = machine_battery_detail(h, sh, (284, cy - 4 + 8))
        tb_top = sh.MARGIN + sh.TB[1]
        assert btm >= tb_top + 3, (btm, tb_top)         # 表題欄の上端から 3mm 以上離す
        sh.detail_frame = (btm, cy)
    return sh


def roof_plan(h, number):
    sh = frame(h, number, "屋根伏図", 100)
    t = T(sh, (0, 0), (52, 73))
    proj = project(h.boxes, "plan", cut=-(h.fl["RF"] + 300), depth_limit=-(h.fl["RF"] - 1))
    emit(sh, proj, t)
    grid(h, sh, t)
    hdim(sh, t, h.gx, -1450)
    vdim(sh, t, h.gy, -1450)
    # ドレン（太陽光は屋根に設置しない）
    for (x, y) in [(500, 500), (h.W - 500, 500), (500, h.D - 500), (h.W - 500, h.D - 500)]:
        sh.circle(t(x, y), 1.4 * sh.S, "A-SYMB")
        sh.text("RD", t(x + 300, y + 300), 1.5, "A-SYMB")
    sh.text("屋上: 外断熱防水（シート防水）、水勾配 1/50", t(h.W / 2, h.D / 2), 2.2, "A-TEXT", "MIDDLE_CENTER")
    sh.text("太陽光パネルは設置しない（庭のソーラーパーゴラに集約）", t(h.W / 2, h.D / 2 - 1200), 1.8, "A-TEXT", "MIDDLE_CENTER")
    sh.text("排煙機の排気口・給気ダンパーは外壁面（機械室）に設置", t(h.W / 2, h.D / 2 - 2200), 1.6, "A-TEXT", "MIDDLE_CENTER")
    sh.north_arrow(sh.P(395, 268), 7, rot=h.facade_az)
    sh.view_title("屋根伏図", "1:100", (24, 22))
    sh.text(f"RFL = 設計GL+{h.fl['RF']:,}／パラペット天端 GL+{h.parapet_top:,}", (24, 15), 2.4, "A-TEXT", paper=True)
    return sh


# ================================================================ elevations / sections
def facade_fill(h, sh, t, view, o):
    """立面の塗り（印刷で淡く出るよう、指定色を白と混ぜる）。ガラス・扉の開口は塗らない。"""
    from shapely.ops import unary_union
    uv = uv_fn(view)
    us = [uv(x, y, 0)[0] for x in (o[0], o[2]) for y in (o[1], o[3])]
    u0, u1 = min(us), max(us)
    z = h.spec["facade_zones"]
    c = h.spec["colors"]
    holes = []
    side = {"S": "S", "N": "N", "E": "E", "W": "W"}[view]
    for op in h.openings(exterior=True):
        if op.wall.side != side:
            continue
        a, b = (op.u0, op.u1) if view in ("S", "E") else (-op.u1, -op.u0)
        holes.append(sbox(a, op.z0, b, op.z1))
    hole = unary_union(holes) if holes else Polygon()

    def soft(hx, k=0.55):
        return tuple(round(v + (255 - v) * k) for v in _hex_rgb(hx))

    def fill(a0, a1, z0, z1, key, k=0.55):
        poly = sbox(a0, z0, a1, z1).difference(hole)
        polys = [Polygon([t(*p) for p in g.exterior.coords], [[t(*p) for p in r.coords] for r in g.interiors]) for g in iter_polygons(poly)]
        if polys:
            sh.hatch_polys(polys, layer="A-COLOR", solid=True, rgb=soft(c[key], k))
    fill(u0, u1, h.fgl, z["tile"]["z"][1], "assort")
    fill(u0, u1, z["tile"]["z"][1], z["top_band"]["z"][0], "base", 0.0)
    fill(u0, u1, z["top_band"]["z"][0], h.parapet_top + 50, "assort")
    fill(u0, u1, z["floor_line"]["z"][0], z["floor_line"]["z"][1], "accent")
    if view == "S":
        en = z["entrance"]
        fill(en["x"][0], en["x"][1], en["z"][0], en["z"][1], "accent")


def elevations(h, number):
    sh = frame(h, number, "立面図", 200)
    o = h.outer_dims()
    g = h.facade_az

    def lab(k, base):
        card = {"S": "南", "W": "西", "N": "北", "E": "東"}[k]
        return f"{card}立面図（{card}から{abs(g):.1f}°{'西' if g > 0 else '東'}回りの面）"
    layout = [("S", lab("S", 0), (40, 175)), ("E", lab("E", -90), (240, 175)), ("N", lab("N", 180), (40, 70)), ("W", lab("W", 90), (240, 70))]
    for view, title, paper in layout:
        uv = uv_fn(view)
        us = [uv(x, y, 0)[0] for x in (o[0], o[2]) for y in (o[1], o[3])]
        t = T(sh, (min(us), 0), paper)
        facade_fill(h, sh, t, view, o)
        proj = project(h.boxes, view, ground=h.fgl, filt=lambda b: b.level != "EXT" or view == "S")
        emit(sh, proj, t, cut_lw=35, vis_lw=18)
        zb = h.spec["facade_zones"]
        for zz in (zb["top_band"]["z"][0], *zb["floor_line"]["z"]):
            sh.line(t(min(us), zz), t(max(us), zz), "A-VIS")
        if view == "S":
            en = zb["entrance"]
            sh.rect(*t(en["x"][0], en["z"][0]), *t(en["x"][1], en["z"][1]), "A-VIS")
            sh.text(f"アクセント {h.spec['colors']['accent']}", t(en["x"][1] + 200, en["z"][0] + 600), 1.5, "A-TEXT", "LEFT")
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
        sh.text(f"腰壁 二丁掛タイル {h.spec['colors']['assort']}（FGL〜1FL）", t(max(us) - 300, h.fgl + 250), 1.4, "A-TEXT", "BOTTOM_RIGHT")
        sh.text(f"頂部帯 {h.spec['colors']['assort']}（z7,600〜）／2FL見切り {h.spec['colors']['accent']}", t(max(us) - 300, zb["top_band"]["z"][0] - 450), 1.4, "A-TEXT", "BOTTOM_RIGHT")
        p = t(u_lo, -2400)
        sh.text(title, p, 3.2, "A-TEXT", "BOTTOM_LEFT")
    ext_txt = h.spec["finish"]["exterior"]
    k = ext_txt.index("、腰壁") + 1
    sh.text(f"外壁: {ext_txt[:k]}", (18, 38), 2.2, "A-TEXT", paper=True)
    sh.text(f"　　　{ext_txt[k:]}", (18, 34), 2.2, "A-TEXT", paper=True)
    sh.text("窓: 全窓 FIX 樹脂サッシ・Low-E トリプル（UVカット合わせ）。南・東・西の窓上の箱は外付け電動スクリーンのボックス（M-03）", (18, 29), 2.2, "A-TEXT", paper=True)
    return sh


def building_sections(h, number):
    sh = frame(h, number, "断面図（建物）", 100)
    o = h.outer_dims()
    defs = [("A", "W", 7000.0, (75, 170), "A-A（X2–X3間、階段1を通る南北断面）"),
            ("B", "S", 1500.0, (75, 55), "B-B（Y1–Y2間、LDK・玄関土間・ジム搬入扉を通る東西断面）")]
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
                              ("t", f"天井高 CH={h.ch['1F']:,}（破線）。天井懐にダクト・浮き床"),
                              ("t", f"1FL=GL+{h.fl['1F']:,}: 想定浸水深(FGL+1.0m)より上"),
                              ("t", "基礎: べた基礎 t=350＋地中梁（RC壁を基礎まで連続）"),
                              ("t", f"階段: 蹴上 {h.stairs[1].riser:.0f} × {h.stairs[1].n}段、踏面 {h.stairs[1].tread}（階段1 は {h.stairs[0].tread}）、有効幅 950（令23条 住宅）")], width=105)
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
        for (e0, e1, te, sg) in w.extra:             # 局所の増し打ち（LDK の南・西）
            lo, hi = sorted((w.c + sg * w.t / 2, w.c + sg * (w.t / 2 + te)))
            ex = (e0, lo, e1, hi) if w.axis == "x" else (lo, e0, hi, e1)
            polys.append(sbox(*t(ex[0], ex[1]), *t(ex[2], ex[3])))
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
    cpx, cpy = t(0, 0)
    sh.circle((cpx, cpy), abs(t(45, 0)[0] - t(0, 0)[0]), "S-COLS")
    sh.text("角柱 φ90（鋼製・耐火塗料1h・鉛直荷重のみ）", t(300, -300), 1.6, "S-TEXT", "MIDDLE_LEFT")
    sh.text("網掛け=RC耐力壁 t=250（1・2階 同位置。1階 LDK の南 350・西 300 は室内側へ増し打ち）、破線=開口", (24, 15), 2.2, "A-TEXT", paper=True)
    sh.text(f"階高 {h.H['1F']:,}（構造スラブ天端の間隔 {h.H['1F']:,} 固定。令78条の2・告示1026号の上限 3,500）。壁厚 250 ≧ max(150, {h.H['1F'] / 22:.0f})", (24, 10), 2.0, "A-TEXT", paper=True)
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
    sh.text("車両門扉 W5,000・人用 W1,200（勝手口なし）。止水板は門扉の近くに保管", P(25, 272), 1.9, "A-TEXT")
    # (5) 連続庇のブラケット（南の断面。外断熱の外側へ鋼製片持ち。熱橋を断熱パッドで切る）
    x, y = P(385, 130)
    hatch_rect(x - 125, y - 900, x + 125, y + 600)                         # RC 壁 t250
    sh.rect(x - 245, y - 900, x - 125, y + 600, "A-CUT")                    # 外断熱 120
    cn = h.spec["exterior"]["canopy"]
    sh.line((x - 245 - 2000, y + 150), (x - 245, y + 150), "A-CUT", lineweight=50)                          # 屋根鋼板（下端）
    sh.line((x - 245 - 2000, y + 150 + cn["t"]), (x - 245, y + 150 + cn["t"]), "A-CUT", lineweight=50)    # 屋根鋼板（上端・勾配 1/100）
    sh.pline([(x - 245, y + 150), (x - 245, y + 150 - 220), (x - 245 - 2000, y + 150)], "A-CUT", closed=True)  # テーパー H 形鋼（根元せい 150→先端 100 の目安）
    sh.rect(x - 245, y + 20, x - 215, y + 280, "A-HIDDEN")                  # 断熱パッド
    sh.text("(5) 連続庇ブラケット断面（南）S=1:30", P(300, 185), 3.0, "A-TEXT")
    sh.text("テーパー H 形鋼 @1,500＋鋼板屋根 1/100", P(300, 179), 1.6, "A-TEXT")
    sh.text("RC へはステンレスボルト＋断熱パッド（熱橋を切る）", P(300, 175), 1.6, "A-TEXT")
    sh.text("先端に内樋（立上り 50）。軒天は LDK 側ベース色", P(300, 171), 1.6, "A-TEXT")
    side_panel(sh, 250, 270, [("h", "特記"),
                              ("t", "RC塀は令62条の8（補強コンクリートブロック造の塀）の対象外。風圧力・地震力に対する構造計算で安全を確認する"),
                              ("t", "東側の坂道沿いで塀が道路との高低差（2m超）を受ける区間は、擁壁として工作物確認申請の対象（令138条）"),
                              ("t", "塀は境界の内側に設置。北側は水路の管理境界との協議に従う"),
                              ("t", "玄関前の目隠し壁（L4.4m・H2.7m・t180）は(1)と同じ断面の自立壁とし、本館・ポーチとは基礎から縁を切る（離隔1.5m以上）。単体で補修・更新・撤去ができる"),
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
            ["階高・床高", f"1FL GL+{h.fl['1F']:,}／階高 {h.H['1F']:,}×2"],
            ["地盤", f"設計GL＝南側道路 TP+{h.gl_tp}／FGL GL+{h.fgl}（現況維持）"],
            ["外構", "RC塀 H2.0m（止水構造）・Dotcon+ 透水舗装・雨水貯留浸透"],
            ["根拠資料", "docs/kawazanyo_design_brief_v3.md、国土地理院 基盤地図情報・DEM5A"]]
    sh.text("計画概要", (24, 238), 4.0, "A-TEXT", paper=True)
    sh.table(24, 233, [36, 160], rows, row_h=7.0, h=2.5)
    sh.text("図面リスト", (236, 238), 4.0, "A-TEXT", paper=True)
    half = (len(dl) + 1) // 2                      # 2段組（表題欄・用紙下端にかからない）
    for x, part in ((236, dl[:half]), (322, dl[half:])):
        sh.table(x, 233, [16, 58, 12], [["図番", "図面名称", "縮尺"]] + [list(r) for r in part], row_h=6.6, h=2.0)
    return sh


def openings_smoke_sheet(h, number):
    """開口部仕様・排煙計画（2階窓・排煙方式の検討、ジム開口の改善）。"""
    import house_legal as HL
    sh = frame(h, number, "開口部仕様・排煙計画", 1, label="—")
    sh.text("開口部仕様・排煙計画（2階の窓仕様と排煙方式の検討、ジム開口部の改善）", (12, 280), 3.6, "A-TEXT", paper=True)
    # (1) 採光
    wt = HL.window_table(h)
    rows = [["階", "居室", "床面積", "必要 15.29%", "ガラス", "有効(K3.0)", "余裕"]]
    for w in wt:
        rows.append([w["floor"], w["room"], f"{w['area']:.1f}", f"{w['need']:.2f}", f"{w['glass']:.2f}", f"{w['eff']:.2f}", f"{w['margin']:.2f}倍"])
    sh.text("(1) 居室の窓と採光（m²）", (12, 271), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, 268, [10, 40, 17, 22, 15, 20, 16], rows, row_h=5.0, h=2.0)
    # (2) 排煙
    srows, cap = HL.smoke_systems(h)
    rows = [["階", "防煙区画（居室）", "面積", "方式", "系統", "排煙口→最遠", "参考:自然排煙の必要開放"]]
    for r in srows:
        rows.append([r["floor"], r["room"], f"{r['area']:.1f}", "機械排煙", r["system"], f"{r['inlet_dist']:.1f}m", f"{r['natural_need']:.2f}m²"])
    sh.text("(2) 排煙計画（令126条の2・3）", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [10, 40, 14, 18, 16, 20, 30], rows, row_h=5.0, h=2.0)
    rows = [["系統", "区画数", "最大区画", "必要能力", "計画"]]
    for k, c in sorted(cap.items()):
        rows.append([k, str(c["rooms"]), f"{c['max_area']:.1f}m²", f"{c['need']:.0f}m³/分", f"{c['plan']:.0f}m³/分×1台"])
    y = sh.table(12, y - 4, [20, 16, 24, 26, 30], rows, row_h=5.0, h=2.0)
    # (3) 2階の排煙方式の比較
    rows = [["比較項目", "A 機械排煙（採用）", "B 自然排煙（高窓の一部を開閉式）"],
            ["窓", "全室 FIX のまま", "各室に内倒し窓（天井下80cm以内、床面積1/50以上）"],
            ["防犯", "開閉部なし（侵入経路にならない）", "開閉部が増え、2階でも足場があれば弱点"],
            ["気密・断熱", "サッシ開閉部の隙間なし", "開閉部の気密・熱貫流が劣る（Uw 約+0.2）"],
            ["設備", "排煙機・ダクト・予備電源（1階と共用）", "手動開放装置のみ（設備は少ない）"],
            ["維持管理", "年1回の作動点検", "開閉装置の点検・雨仕舞"],
            ["判定", "防犯・断熱・FIX方針と整合 → 採用", "不採用"]]
    sh.text("(3) 2階の排煙方式の比較", (190, 271), 2.8, "A-TEXT", paper=True)
    y2 = sh.table(190, 268, [24, 82, 102], rows, row_h=5.0, h=2.0)
    # (4) ジム開口部の改善
    ge = HL.gym_envelope(h)
    b, a = ge["before"], ge["after"]
    rows = [["項目", "改善前（v3.1）", "改善後（v3.2）"],
            ["窓", "腰高窓 1.5×1.0m ×2（窓台 FL+1,000）", "FIX 高窓 2.1×0.6m ×2（窓台 FL+2,000）"],
            ["外部扉", "南面 両開き搬入扉 1.8×2.4m", "廃止（搬入は玄関から）"],
            ["開口面積", f"{b['win'] + b['door']:.2f} m²", f"{a['win']:.2f} m²"],
            ["開口まわり熱損失", f"{ge['q_before']:.1f} W/K", f"{ge['q_after']:.1f} W/K（{(1 - ge['q_after'] / ge['q_before']) * 100:.0f}%減）"],
            ["防犯", "外部から手の届く窓・扉", "窓下端 地盤+3.05m・防犯合わせガラス（CP、耐貫通5分以上）・開閉部なし"],
            ["採光", "9.00 m²（有効）", f"{a['win'] * 3:.2f} m²（必要 {h.gym.area * 0.1529:.2f}）"]]
    sh.text("(4) ジム開口部の改善（防犯・熱貫流）", (190, y2 - 6), 2.8, "A-TEXT", paper=True)
    y2 = sh.table(190, y2 - 9, [32, 80, 96], rows, row_h=5.0, h=2.0)
    notes = [("h", "窓の仕様（全窓 FIX）"),
             ("t", f"枠: 樹脂サッシ、ガラス: 全窓 Low-E トリプル（アルゴン）＋室外側 UVカット合わせガラス（紫外線約99%カット）、Uw≦{HL.U_WIN:.2f} W/m²K。南・東・西は外付け電動スクリーン（M-03）"),
             ("t", "全窓（1・2階）: 外側を防犯合わせガラス（CP 認定品）。窓台: 居室 FL+1,000、ジム FL+2,000"),
             ("t", "換気は全館空調・全熱交換（窓に依存しない）。排煙時は機械室の給気ダンパーが連動して開く"),
             ("t", "開口 H2,200 で天井 2,800 のため防煙垂れ壁 600（≧500）。欄間パネル100 は不要（ガラス扉の欄間は意匠として残す）（要確認）"),
             ("t", "排煙機: 西・東系統の各機械室に 120m³/分×1台。排煙口は各居室の天井、手動開放装置は床から0.8〜1.5m。予備電源は蓄電池 200kWh 級（蓄電室、PV と連携、30分以上）")]
    side_panel(sh, 190, y2 - 6, notes, width=210)
    return sh


def energy_sheet(h, number):
    import performance as PF
    sh = frame(h, number, "室内環境・冷暖房負荷・必要発電量（概算）", 1, label="—")
    ind = PF.indoor(h)
    sh.text("室内環境目標・冷暖房負荷・年間電力需要・必要発電量（概算）— 内寸18.0m角", (12, 280), 3.6, "A-TEXT", paper=True)
    old, new = PF.heat_load(h, ind=PF.OLD_INDOOR), PF.heat_load(h)
    c = PF.CLIMATE
    d = h.spec["requirements"]["indoor"]
    rows = [["室内環境目標（全室・通年）", "温度", "湿度", "絶対湿度", "露点"],
            ["夏（冷房・除湿）", f"{d['summer_t'][0]:.0f}〜{d['summer_t'][1]:.0f}℃", f"{d['rh'][0]}〜{d['rh'][1]}%",
             f"{PF.abs_humidity(d['summer_t'][0], d['rh'][0]):.1f}〜{PF.abs_humidity(d['summer_t'][1], d['rh'][1]):.1f}g/kg",
             f"{PF.dew_point(d['summer_t'][0], d['rh'][0]):.1f}〜{PF.dew_point(d['summer_t'][1], d['rh'][1]):.1f}℃"],
            ["冬（暖房・加湿）", f"{d['winter_t'][0]:.0f}〜{d['winter_t'][1]:.0f}℃", f"{d['rh'][0]}〜{d['rh'][1]}%",
             f"{PF.abs_humidity(d['winter_t'][0], d['rh'][0]):.1f}〜{PF.abs_humidity(d['winter_t'][1], d['rh'][1]):.1f}g/kg",
             f"{PF.dew_point(d['winter_t'][0], d['rh'][0]):.1f}〜{PF.dew_point(d['winter_t'][1], d['rh'][1]):.1f}℃"]]
    sh.text("(1) 室内環境目標", (12, 271), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, 268, [44, 26, 22, 40, 34], rows, row_h=5.0, h=2.0)
    win_in = ind["t_win"] - PF.U["window"] * 0.13 * (ind["t_win"] - c["t_win"])
    rows = [["項目", "旧目標", "新目標", "増減"]]

    def r(lab, k, fmt="{:.2f}"):
        a_, b_ = old[k], new[k]
        rows.append([lab, fmt.format(a_), fmt.format(b_), f"{(b_ / a_ - 1) * 100:+.1f}%"])
    r("暖房 設計負荷 kW（冬 上限21℃）", "heat")
    r("冷房 顕熱 kW（夏 下限25℃）", "cool_s")
    r("冷房 潜熱（除湿）kW", "cool_l")
    r("除湿量 L/日（ピーク）", "dehum", "{:.0f}")
    r("加湿量 L/日（ピーク）", "hum", "{:.0f}")
    r("年間 暖房熱量 kWh", "heat_kwh", "{:,.0f}")
    r("年間 冷房・除湿熱量 kWh", "cool_kwh", "{:,.0f}")
    r("年間 加湿熱量 kWh", "hum_kwh", "{:,.0f}")
    sh.text("(2) 冷暖房負荷（旧目標 冬22℃/60%・夏26℃/45% との比較）", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [62, 32, 32, 22], rows, row_h=5.0, h=2.0)
    rows = [["系統", "暖房", "冷房（顕熱＋潜熱）", "機器選定（提案）"],
            ["西系統（X1–X3）", f"{new['heat'] * 0.5:.1f}kW", f"{new['cool'] * 0.45:.1f}kW", "全館空調 5.6kW級＋デシカント調湿"],
            ["東系統（X3–X4・ジム/シアター）", f"{new['heat'] * 0.5:.1f}kW", f"{new['cool'] * 0.55:.1f}kW", "全館空調 7.1kW級＋デシカント調湿"]]
    sh.text("(3) 空調機の容量（2系統）", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [50, 24, 34, 66], rows, row_h=5.0, h=2.0)
    notes = [("t", f"湿度55〜60%を通年保つため、夏は除湿（露点 約{PF.dew_point(25, 55):.0f}℃まで）、冬は加湿が主な負荷。湿度幅は狭いので、全熱交換＋デシカント（調湿）を各系統に設け、室ごとの湿度センサーで制御する"),
             ("t", f"結露: 冬（外気{c['t_win']}℃）の窓の室内表面温度は約{win_in:.1f}℃で、室内露点 {PF.dew_point(21, 60):.1f}℃を上回る。外断熱のため躯体の熱橋も小さい"),
             ("t", f"条件: {c['name']}、外気 冬{c['t_win']}℃・夏{c['t_sum']}℃（{c['x_sum']}g/kg）、換気 {PF.ACH}回/h（全熱交換 {PF.RECOVERY * 100:.0f}%回収）、HDD {new['hdd']:.0f}・CDD {new['cdd']:.0f}")]
    side_panel(sh, 12, y - 6, notes, width=175)
    en = PF.energy(h, new)
    bsz = PF.battery_sizing(h, en)
    rows = [["用途", "年間電力 kWh"]] + [[k, f"{v:,.0f}"] for k, v in en["items"]] + [["合計", f"{en['total']:,.0f}"]]
    sh.text("(4) 年間電力需要", (200, 271), 2.8, "A-TEXT", paper=True)
    y2 = sh.table(200, 268, [120, 40], rows, row_h=5.0, h=2.0)
    pg = h.pergola
    rows = [["項目", "値"],
            ["必要容量（需要÷{:.0f}kWh/kWp）".format(c["pv_yield"]), f"{en['need_kwp']:.1f} kWp"],
            ["必要容量（余裕20%・劣化/天候）", f"{en['need_kwp_margin']:.1f} kWp"],
            ["必要な架台面積（被覆率{:.0f}%）".format(en["coverage"] * 100), f"{en['need_area']:.0f} m²"],
            ["ソーラーパーゴラ（菜園）", f"{(pg[2] - pg[0]) / 1000:.0f}×{(pg[3] - pg[1]) / 1000:.0f}m・パネル{en['panel_area']:.0f}m² → {en['pg_kwp']:.1f}kWp・影損失{en['shade']['pergola']['loss'] * 100:.1f}% → {en['pg_gen']:,.0f}kWh"],
            ["3台用ソーラーカーポート", f"{en['cp_area']:.0f}m² → {en['cp_kwp']:.1f}kWp・影損失{en['shade']['carport']['loss'] * 100:.1f}% → {en['cp_gen']:,.0f}kWh"],
            ["パーゴラの損失（被覆率70%＋影）", f"全面被覆に対し 約{en['coverage_deficit'] + en['shade_deficit']:,.0f}kWh → カーポートで{en['cp_gen'] / (en['coverage_deficit'] + en['shade_deficit']) * 100:.0f}%を補う"],
            ["合計 年間発電量", f"{en['pv_kwp']:.1f}kWp・{en['pv_gen']:,.0f} kWh（需要の {en['pv_gen'] / en['total'] * 100:.0f}%）"],
            ["拡張後（予約ゾーン RZ）", f"RZ {h.pv_reserve.area / 1e6:.0f}m² → {en['rz_kwp']:.1f}kWp・{en['rz_gen']:,.0f}kWh（影3%は推定）。合計 {en['pv_kwp_ext']:.1f}kWp・約{en['pv_gen_ext']:,.0f}kWh（需要の {en['pv_gen_ext'] / en['total'] * 100:.0f}%）"],
            ["蓄電池（停電時）", f"{bsz['rows']['C']['kwh']:.1f}kWh/日の防災モードで7日 → 必要公称 {bsz['rows']['C']['nominal']:.0f}kWh → 200kWh級（蓄電室 {h.battery_room.area:.1f}m²）。A年平均 {bsz['rows']['A']['nominal']:.0f}・B冬 {bsz['rows']['B']['nominal']:.0f}kWh は南半分に収まらない"]]
    sh.text("(5) 必要発電量 — 日よけ付き菜園（ソーラーパーゴラ）＋3台用ソーラーカーポート", (200, y2 - 6), 2.8, "A-TEXT", paper=True)
    y2 = sh.table(200, y2 - 9, [62, 140], rows, row_h=5.0, h=2.0)
    side_panel(sh, 200, y2 - 6, [("t", "本館とは構造的に分離した独立架台（鉄骨・軒高2.8m・南向き10°）。パネルを列状にすき間をあけて並べ（被覆率70%）、光と雨を下の菜園・庭に落とす。営農型太陽光（ソーラーシェアリング）やソーラーパーゴラとして実例がある"),
                                 ("t", "下は半日陰を好む作物（葉物・ハーブ・ミョウガ・シソ・ベリー類）向き。パネルの雨水は雨どいで地下貯留槽へ集め、散水に使う（内水対策と兼用）"),
                                 ("t", "影損失は各月21日・30分ごとの太陽位置で本館・塀・隣家（高さ6.5m仮定）の影を追跡して算定。パーゴラは本館の西9mで、冬の朝に一部が影に入る（12月 直達の約5%）"),
                                 ("t", "パーゴラ・カーポートとも屋根と柱をもつため建築物として扱われる見込み（建築面積に算入・確認申請が必要）。余剰電力は売電または将来のEV充電に充てる"),
                                 ("t", "実施設計で、発電量シミュレーション（建物・塀の影）と住宅の一次エネルギー計算で確定する")], width=205)
    return sh


def orientation_sheet(h, number):
    import performance as PF
    import sightshade as SS
    sh = frame(h, number, "建物の向きと日射取得", 1, label="—")
    g = h.facade_az
    sh.text(f"建物の向きと日射取得 — 南側道路に平行・直交（南面は真南から {abs(g):.1f}° {'西' if g > 0 else '東'}向き）", (12, 280), 3.6, "A-TEXT", paper=True)
    w0, w1 = SS.window_solar(h, 0.0), SS.window_solar(h)
    names = {"S": "南面", "E": "東面", "N": "北面", "W": "西面"}
    rows = [["外壁面", "窓ガラス m²", "向き（真北基準→道路基準）", "暖房期 取得 kWh", "冷房期 取得 kWh"]]
    for k in ("S", "E", "N", "W"):
        a0 = PF.SHGC
        base = SS.SIDE_AZ[k]
        rows.append([names[k], f"{w1['glass'][k]:.2f}", f"{base:+.0f}° → {base + g:+.1f}°（真南から西回り）",
                     f"{w0['heat'][k]:,.0f} → {w1['heat'][k]:,.0f}", f"{w0['cool'][k]:,.0f} → {w1['cool'][k]:,.0f}"])
    rows.append(["合計", f"{sum(w1['glass'].values()):.2f}", "", f"{sum(w0['heat'].values()):,.0f} → {sum(w1['heat'].values()):,.0f}",
                 f"{sum(w0['cool'].values()):,.0f} → {sum(w1['cool'].values()):,.0f}"])
    sh.text("(1) 窓からの日射取得（Low-E 南北 g0.45・東西 g0.28、外付けスクリーン 5〜9月、日照率 45%）", (12, 271), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, 268, [24, 26, 66, 40, 40], rows, row_h=5.2, h=2.0)
    h0, h1 = PF.heat_load(h, gamma=0.0), PF.heat_load(h)
    e1 = PF.energy(h, h1)
    rows = [["項目", "真北基準（回転前）", "南側道路基準（計画）", "差"],
            ["冷房ピークの窓日射取得 kW", f"{w0['peak']:.2f}", f"{w1['peak']:.2f}", f"{(w1['peak'] - w0['peak']) * 1000:+.0f} W"],
            ["冷房 顕熱 設計負荷 kW", f"{h0['cool_s']:.2f}", f"{h1['cool_s']:.2f}", f"{(h1['cool_s'] - h0['cool_s']) * 1000:+.0f} W"],
            ["年間 暖房熱量 kWh（日射取得控除後）", f"{h0['heat_kwh']:,.0f}", f"{h1['heat_kwh']:,.0f}", f"{h1['heat_kwh'] - h0['heat_kwh']:+,.0f}"],
            ["年間 冷房・除湿熱量 kWh", f"{h0['cool_kwh']:,.0f}", f"{h1['cool_kwh']:,.0f}", f"{h1['cool_kwh'] - h0['cool_kwh']:+,.0f}"],
            ["パーゴラ（傾斜10°）の年間日射 kWh/m²", f"{SS.annual_poa(10, 0):,.0f}", f"{SS.annual_poa(10, g):,.0f}", f"{(e1['f_pg'] - 1) * 100:+.2f}%"],
            ["カーポート（傾斜3°）の年間日射 kWh/m²", f"{SS.annual_poa(3, 0):,.0f}", f"{SS.annual_poa(3, g):,.0f}", f"{(e1['f_cp'] - 1) * 100:+.2f}%"],
            ["影損失（パーゴラ／カーポート）", "—", f"{e1['shade']['pergola']['loss'] * 100:.2f}%／{e1['shade']['carport']['loss'] * 100:.2f}%", ""],
            ["年間発電量 kWh", "—", f"{e1['pv_gen']:,.0f}（需要 {e1['total']:,.0f} の {e1['pv_gen'] / e1['total'] * 100:.0f}%）", ""]]
    sh.text("(2) 冷暖房負荷・発電量への影響", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [70, 40, 64, 30], rows, row_h=5.2, h=2.0)
    side_panel(sh, 12, y - 6, [("h", "評価"),
        ("t", f"建物・ソーラーパーゴラ・カーポート・目隠し壁を、南側道路の道路境界線（真東西から{abs(g):.1f}°傾く）に平行・直交させた。南面は真南から{abs(g):.1f}°{'西' if g > 0 else '東'}を向く"),
        ("t", "窓の日射取得は、東面が冬に少し増え、西面が冬・夏とも少し減る。合計ではほぼ変わらない（窓が小さい FIX 窓中心の外皮のため、方位の影響は小さい）"),
        ("t", "太陽光は真南から12°程度の振れでは年間日射の減少が 0.2%未満で、発電量への影響は無視できる"),
        ("t", "敷地との関係では、建物と道路・塀が平行になり、南側の駐車場・アプローチの配置に無駄がなくなる。北側水路から11.0m、東側道路から10.0m、隣地から9.8m（いずれも がけ条例の2H 以上）")], width=300)
    return sh


def glazing_uv_sheet(h, number):
    """窓仕様（全窓 樹脂サッシ・Low-E トリプル）と紫外線対策（UVカット合わせガラス・外付け電動スクリーン）。"""
    import performance as PF
    import sightshade as SS
    from shapely.geometry import box as sbox
    gz, us = h.spec["glazing"], h.spec["uv_shading"]
    sh = frame(h, number, "窓仕様・紫外線対策", 1, label="—")
    sh.text("窓仕様・紫外線対策 — 全窓 樹脂サッシ＋Low-E トリプルガラス、UVカット合わせガラス＋外付け電動スクリーン", (12, 280), 3.6, "A-TEXT", paper=True)
    names = {"S": "南", "E": "東", "N": "北", "W": "西"}
    blinded = {id(op) for op, _ in h.blinds}
    rows = [["記号", "階", "名称", "方位", "W×H", "Low-E の種類", "g", "外付けスクリーン"]]
    for op in sorted((o for o in h.openings(exterior=True) if o.kind == "window"), key=lambda o: (o.floor, "SEWN".index(o.side), o.u0)):
        t = gz["types"][gz["side_type"][op.side]]
        rows.append([op.label, op.floor, op.name.replace("FIX", "FIX "), names[op.side], f"{op.width:,.0f}×{op.height:,.0f}",
                     t["name"].replace(" Low-E トリプル", ""), f"{t['g']:.2f}", "あり（電動）" if id(op) in blinded else "—"])
    sh.text(f"(1) 窓の一覧（全{len(rows) - 1}か所・すべて FIX）", (12, 271), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, 268, [14, 10, 36, 12, 24, 24, 12, 30], rows, row_h=4.8, h=2.0)
    rows = [["項目", "仕様"],
            ["サッシ", gz["frame"] + f"、Uw≦{gz['uw']:.2f} W/m²K"],
            ["ガラス（1階）", gz["build_1f"]],
            ["ガラス（2階）", gz["build_2f"]],
            ["Low-E", f"膜 {gz['low_e']}面、Ug {gz['ug']:.2f} W/m²K。南・北は日射取得型（冬の日射を取り込む）、東・西は遮熱型（朝夕の低い日射を防ぐ）"],
            ["紫外線", f"室外側の合わせガラス中間膜で紫外線を約{(1 - gz['tuv']) * 100:.0f}%カット（透過率 {gz['tuv'] * 100:.0f}%以下）。全窓共通"],
            ["外付けスクリーン", f"{us['type']}。{'・'.join(names[k] for k in us['sides'])}面の窓 {len(h.blinds)}か所、{us['months'][0]}〜{us['months'][-1]}月は日射センサーで自動降下（遮蔽係数 {us['fc']:.2f}）"]]
    sh.text("(2) 窓の仕様（全窓共通）", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [30, 142], rows, row_h=5.0, h=2.0)
    # (3) 紫外線
    uv = SS.uv_exposure(h)
    rows = [["ガラスの種類", "紫外線透過率", "室内に入る紫外線 kWh/年", "カット率"]]
    for n_, t_, kwh in uv["cases"]:
        rows.append([n_, f"{t_ * 100:.1f}%", f"{kwh:.2f}", f"{(1 - kwh / uv['tot_inc']) * 100:.1f}%"])
    sh.text(f"(3) 紫外線のカット効果（窓面に当たる紫外線 年 {uv['tot_inc']:.1f} kWh = 日射の{uv['frac'] * 100:.0f}%）", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [70, 26, 46, 30], rows, row_h=5.0, h=2.0)
    # (4) 冷暖房への影響
    base = PF.heat_load(h, shgc=PF.SHGC, blinds=False)
    noblind = PF.heat_load(h, blinds=False)
    plan = PF.heat_load(h)
    rows = [["項目", "旧（全窓 遮熱型・スクリーンなし）", "Low-E 使い分けのみ", "本計画（＋外付けスクリーン）"],
            ["冷房ピークの窓日射取得 kW", f"{base['solar']:.2f}", f"{noblind['solar']:.2f}", f"{plan['solar']:.2f}"],
            ["冷房 顕熱 設計負荷 kW", f"{base['cool_s']:.2f}", f"{noblind['cool_s']:.2f}", f"{plan['cool_s']:.2f}"],
            ["暖房期の窓日射取得 kWh", f"{sum(base['ws']['heat'].values()):,.0f}", f"{sum(noblind['ws']['heat'].values()):,.0f}", f"{sum(plan['ws']['heat'].values()):,.0f}"],
            ["冷房期の窓日射取得 kWh", f"{sum(base['ws']['cool'].values()):,.0f}", f"{sum(noblind['ws']['cool'].values()):,.0f}", f"{sum(plan['ws']['cool'].values()):,.0f}"],
            ["年間 暖房熱量 kWh", f"{base['heat_kwh']:,.0f}", f"{noblind['heat_kwh']:,.0f}", f"{plan['heat_kwh']:,.0f}"],
            ["年間 冷房・除湿熱量 kWh", f"{base['cool_kwh']:,.0f}", f"{noblind['cool_kwh']:,.0f}", f"{plan['cool_kwh']:,.0f}"]]
    sh.text("(4) 冷暖房負荷への影響", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [52, 46, 36, 46], rows, row_h=5.0, h=2.0)
        # (5) 窓上部の詳細（模式図 1:5）
    px0, py0, k = 228, 212, 1 / 8.0

    def Q(x, z):
        return sh.P(px0 + x * k, py0 + z * k)

    def R(x0, z0, x1, z1, layer="A-VIS", **kw):
        a, b = Q(x0, z0), Q(x1, z1)
        sh.rect(a[0], a[1], b[0], b[1], layer, **kw)
        return sbox(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
    sh.text("(5) 窓上部 断面詳細（模式図 1:8）", (200, 271), 2.8, "A-TEXT", paper=True)
    rc = R(120, 0, 370, 420, "A-CUT", lineweight=50)
    sh.hatch_polys([rc], spacing=1.0)
    ins = R(20, 200, 120, 420, "A-CUT-LGS")
    sh.hatch_polys([ins], pattern="ANSI37", spacing=0.6, layer="A-CUT-INS")
    R(0, 200, 20, 420, "A-CUT-LGS")
    R(-30, 0, 120, 200, "A-DOOR", lineweight=35)                       # スクリーンボックス
    sh.circle(Q(45, 110), 55 * k, "A-DOOR")                            # 巻き取った生地（ローラー）
    sh.circle(Q(45, 110), 20 * k, "A-DOOR")
    R(125, -80, 205, 0, "A-DOOR", lineweight=35)                       # サッシ枠（上枠）
    R(140, -420, 190, -80, "A-GLAZ", lineweight=25)                    # ガラス（トリプル 約50mm）
    for xg in (148, 168):
        sh.line(Q(xg, -420), Q(xg, -80), "A-GLAZ")
    sh.line(Q(45, 55), Q(45, -400), "A-DOOR", lineweight=35)           # 下ろした生地
    R(15, -420, 75, -400, "A-DOOR")                                    # 下端バー
    R(30, -400, 60, 0, "A-HIDDEN")                                     # 両側の ZIP レール（奥）
    sh.line(Q(370, -420), Q(370, 420), "A-VIS")
    sh.line(Q(-60, -430), Q(400, -430), "A-HIDDEN")
    labels = [((300, 400), "RC 壁 250"), ((70, 340), "外断熱 100"), ((10, 270), "外装 20"),
              ((60, 100), f"スクリーンボックス H{us['box']['h']}×D{us['box']['d']}（外断熱層に埋込）"),
              ((180, -40), "樹脂サッシ（FIX）"), ((165, -170), "Low-E トリプル（Ar）＋室外側 UVカット合わせ"),
              ((45, -290), "生地（開口率5%・UVカット・雨で洗われる）"), ((60, -390), "ZIP レール（生地端を保持・羽根なし）")]
    for (x_, z_), t_ in labels:
        p = Q(x_, z_)
        q = sh.P(px0 + 58, py0 + z_ * k)
        sh.line(p, q, "A-SYMB")
        sh.circle(p, 0.4, "A-SYMB")
        sh.text(t_, (q[0] + 1, q[1] - 0.8), 1.9, "A-TEXT")
    sh.text("屋外", Q(-60, 430), 2.2, "A-TEXT")
    sh.text("室内", Q(390, 430), 2.2, "A-TEXT")
    notes = [("h", "紫外線対策の考え方"),
             ("t", "① ガラス: 全窓の室外側を UVカット中間膜の合わせガラスとし、紫外線を約99%止める（家具・床の退色、肌への影響を抑える）。1・2階とも防犯合わせガラス（CP）を兼ねる"),
             ("t", "② 外付け電動スクリーン（ZIP型）: 南・東・西の窓は、日射と紫外線をガラスの外で止める。羽根（スラット）がなく、ほこりが溜まらず清掃不要に近い。夏（5〜9月）は日射センサーで自動降下、冬は上げて日射を取り込む。強風時は自動で巻き上げる"),
             ("t", "③ Low-E の使い分け: 南・北は日射取得型で冬の暖房を助け、夏の南面はスクリーンで遮る。東・西は低い朝夕日を防ぐ遮熱型"),
             ("t", "④ 屋外: 玄関庇（出2.0m）、ソーラーパーゴラ（被覆率70%）、カーポート屋根が、屋外の作業・乗降時の日よけになる"),
             ("t", "数値は概算（日射の5%を紫外線とし、ガラスの透過率は代表値）。実施設計でガラス・スクリーンのメーカー値により確定する")]
    side_panel(sh, 200, 146, notes, width=195)
    return sh


def interior_policy_sheet(h, number):
    """内装設計方針: 安全（子どもの挟み込み・転落ほか）と清掃・メンテナンスの容易さ。"""
    import interior as IN
    sp = h.spec["interior"]
    sh = frame(h, number, "内装設計方針（安全・清掃性）", 1, label="—")
    sh.text("内装設計方針 — 「すばらしいデザインは安全であるべき」「清掃とメンテナンスが簡易であるべき」", (12, 280), 3.6, "A-TEXT", paper=True)
    rows = [["危険", "対策（設計で決めること）", "対象"]] + [list(r) for r in IN.SAFETY]
    sh.text("(1) 安全 — 危険をデザインでなくす", (12, 271), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, 268, [24, 136, 28], rows, row_h=5.2, h=1.8)
    rows = [["部位", "清掃・メンテナンスを簡単にする選び方"]] + [list(r) for r in IN.MAINTENANCE]
    sh.text("(2) 清掃・メンテナンス — 手入れの頻度を減らす", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [24, 164], rows, row_h=5.2, h=1.8)
    st = sp["stair"]
    rows = [["階段", "蹴上 R", "踏面 T", "勾配 R/T（≦6/7）", f"2R+T（{st['step_rule'][0]}〜{st['step_rule'][1]}）", "有効幅", "蹴込み", "判定"]]
    for c in IN.stair_checks(h):
        rows.append([c["name"], f"{c['riser']:.1f}", f"{c['tread']:.0f}", f"{c['slope']:.3f}", f"{c['rule']:.0f}", f"{c['width']:,.0f}",
                     f"{st['max_nosing_gap']}以下（蹴込み板あり）", "OK" if c["ok_slope"] and c["ok_rule"] else "NG"])
    sh.text("(3) 階段の寸法（品確法 高齢者等配慮 等級5相当で確認）", (205, 271), 2.8, "A-TEXT", paper=True)
    y2 = sh.table(205, 268, [16, 16, 16, 30, 30, 16, 40, 12], rows, row_h=5.0, h=2.0)
    hg = sp["head_gap"]
    rows = [["位置", "長さ", "高さ", "端部のすき間", "判定"]]
    for g in IN.guard_gaps(h):
        gaps = "・".join("0（壁に接する）" if v < 1 else (f"{v:,.0f}（降り口の通路）" if v > hg[1] else f"{v:.0f}") for v in g["gaps"])
        bad = any(hg[0] <= v <= hg[1] or sp["finger_gap"][0] <= v <= sp["finger_gap"][1] for v in g["gaps"])
        rows.append([f"{g['stair']} 2階開口", f"{g['length']:,.0f}", f"{g['height']:,.0f}", gaps, "NG" if bad else "OK"])
    rows.append(["階段の間の手すり壁", "全長", f"2FL+{sp['guard_height']:,}", "上下の階段で連続（すき間なし）", "OK"])
    sh.text(f"(4) 手すり壁・腰壁（頭部 {hg[0]}〜{hg[1]}mm・指 {sp['finger_gap'][0]}〜{sp['finger_gap'][1]}mm のすき間をつくらない）", (205, y2 - 6), 2.8, "A-TEXT", paper=True)
    y2 = sh.table(205, y2 - 9, [40, 18, 22, 80, 16], rows, row_h=5.0, h=2.0)
    # 手すり壁の模式図（手すり子・横桟なしのパネル）
    bx, by = 215, y2 - 52
    sh.text("(5) 手すり壁の考え方（模式図）", (205, y2 - 6), 2.8, "A-TEXT", paper=True)
    for k, (title, panel) in enumerate((("採用: すき間のないパネル", True), ("不採用: 手すり子・横桟", False))):
        x0 = bx + k * 60
        sh.rect(*sh.P(x0, by), *sh.P(x0 + 40, by + 30), "A-VIS" if panel else "A-HIDDEN", lineweight=35)
        if panel:
            sh.hatch_polys([sbox_(sh, x0, by, x0 + 40, by + 30)], pattern="ANSI37", spacing=1.2, layer="A-CUT-INS")
        else:
            for xx in range(1, 8):
                sh.line(sh.P(x0 + xx * 5, by), sh.P(x0 + xx * 5, by + 30), "A-HIDDEN")
            sh.line(sh.P(x0, by + 8), sh.P(x0 + 40, by + 8), "A-HIDDEN")
            sh.text("すき間に頭・足がかり", (x0 + 20, by + 14), 1.8, "A-TEXT", "MIDDLE_CENTER", paper=True)
        sh.line(sh.P(x0 - 2, by + 30), sh.P(x0 + 42, by + 30), "A-VIS", lineweight=50)
        sh.text(title, (x0, by - 5), 2.0, "A-TEXT", paper=True)
    sh.text(f"H{sp['guard_height']:,}", (bx - 2, by + 15), 1.8, "A-TEXT", "MIDDLE_RIGHT", paper=True)
    side_panel(sh, 205, by - 12, [("h", "一貫させること"),
        ("t", sp["principles"][0]), ("t", sp["principles"][1]),
        ("t", "見た目のための凹凸（オープン棚・間接照明の溝・格子・スリット）は、危険かほこり溜まりになるなら採用しない。意匠は素材の質感・色・光（窓の位置）でつくる"),
        ("t", "各室の仕上げは I-02 内装仕上表による。建具金物（指はさみ防止・ソフトクローズ・非常解錠）は A-09 建具表の全建具に適用")], width=195)
    return sh


def sbox_(sh, x0, y0, x1, y1):
    from shapely.geometry import box as sbox
    a, b = sh.P(x0, y0), sh.P(x1, y1)
    return sbox(a[0], a[1], b[0], b[1])


def finish_sheet(h, number):
    import interior as IN
    sh = frame(h, number, "内装仕上表", 1, label="—")
    sh.text("内装仕上表 — 安全で、掃除と手入れが簡単な仕上げに統一", (12, 280), 3.6, "A-TEXT", paper=True)
    rows = [["階", "室名", "面積", "床", "巾木", "壁", "天井", "安全・清掃の要点"]]
    for f, n, c, a, (fl, sk, wa, ce, note) in IN.finish_schedule(h):
        rows.append([f, n + (f" ×{c}" if c > 1 else ""), f"{a:.1f}", fl, sk, wa, ce, note])
    y = sh.table(12, 272, [8, 32, 10, 72, 44, 64, 36, 126], rows, row_h=4.4, h=1.65)
    sh.text("共通: 出隅 R10（手の届く高さ）、コンセントはシャッター付き、床の段差5mm以下（掃除ロボット走行）、照明は調光・調色 LED、家具は突っ張り式（RC 壁に固定しない）。数量・品番は実施設計で決める",
            (12, y - 5), 2.2, "A-TEXT", paper=True)
    exterior_finish_table(h, sh, y - 14)
    return sh


def _hex_rgb(hx):
    return tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))


def exterior_finish_table(h, sh, y):
    """外部仕上表・色彩計画（色はいずれも仮定。施主指定 2026-10-23）。"""
    c = h.spec["colors"]
    sh.text("外部仕上表・色彩計画 — 色はいずれも仮定（実物の見本板で確認）", (12, y + 4), 3.0, "A-TEXT", paper=True)
    rows = [["部位", "範囲", "仕上げ", "色", "見本"],
            ["外壁 ベース（約70%）", "一般部 1FL〜RFL−300、窓の抱き", "外装塗装（微弾性・つや消し、砂骨の塗り肌）", c["base"], ""],
            ["外壁 アソート（約25%）腰壁", "FGL〜1FL（GL+1,500）外周4面", "磁器質タイル 二丁掛 227×60・半つや・目地8（目地 " + c["tile_joint"] + "）", c["assort"], ""],
            ["アソート 頂部帯・笠木・窓枠・ZIPボックス", "RFL−300〜パラペット天端／窓枠 見付60", "外装塗装／アルミ笠木 フッ素樹脂焼付／樹脂サッシ外観色", c["assort"], ""],
            ["外壁 アクセント（約5%）", "玄関まわり 南面 x7,300〜10,900・庇・玄関扉・2FL見切り", "外装塗装／鋼製防犯扉 焼付／アルミ見切り", c["accent"], ""],
            ["塀（RC＋外装塗装）", "H2.0m以上、区間2mごとに5段階の個体差", "微弾性・つや消し。指定範囲 " + c["fence_range"][0] + "〜" + c["fence_range"][1], c["fence"], ""],
            ["Dotcon+", "駐車場・アプローチ・菜園まわり", "600角・目地10", c["dotcon"], ""],
            ["コンクリート（指定のない面）", "門柱・目隠し壁・外部階段・ポーチ・基礎・見切り", "RC打放し（撥水クリア）／金ごて・刷毛引き", c["concrete"], ""],
            ["透水性コンクリート（要施主確認）", "指定のない地面・門前の広場", "粗面・ダミー目地3m", c["porous_concrete"], ""],
            ["門扉・忍び返し", "電動スライド／人用 H2,000", "アルミ形材 目隠しパネル（アソート色）／スチール黒", c["assort"], ""],
            ["防草砂利", "外壁まわり 幅1,000", "砕石 5〜13号", c["gravel"], ""]]
    cols = [46, 58, 76, 14, 10]
    bottom = sh.table(12, y, cols, rows, row_h=4.0, h=1.5)
    for ri, row in enumerate(rows):          # 色見本
        if ri == 0:
            continue
        top, bot = sh.last_table_rows[ri]
        x0 = 12 + sum(cols[:4]) + 2
        sh.hatch_polys([sbox_(sh, x0, bot + 0.4, x0 + 6, min(top - 0.4, bot + 4.4))], layer="A-COLOR", solid=True, rgb=_hex_rgb(row[3]))
    return bottom


def wifi_sheet(h, number):
    """館内 Wi-Fi の電波計画（受信強度の分布と AP 配置）。"""
    import wifi as WF
    from shapely.geometry import box as sbox
    from shapely.ops import unary_union
    w = h.spec["wifi"]
    sh = frame(h, number, "Wi-Fi 電波計画", 200)
    sh.text(f"館内 Wi-Fi 電波計画 — 5GHz 帯で受信 {w['target_dbm']}dBm 以上を床面の{w['target_cover'] * 100:.0f}%以上（壁の減衰込みの概算）", (12, 280), 3.6, "A-TEXT", paper=True)
    bands = [(-60, 999, 3, "−60dBm 以上（高速）"), (w["target_dbm"], -60, 4, f"{w['target_dbm']}〜−60dBm（快適）"),
             (-75, w["target_dbm"], 2, f"−75〜{w['target_dbm']}dBm（つながるが遅い）"), (-999, -75, 1, "−75dBm 未満（不安定）")]
    res = []
    for k, f in enumerate(("1F", "2F")):
        r = WF.plan(h, f)
        res.append(r)
        t = T(sh, (0, 0), (22 + k * 112, 150))
        g = r["grid"] / 2
        cut = h.fl[f] + 1200
        solid = unary_union([sbox(*t(b.x0, b.y0), *t(b.x1, b.y1)) for b in h.boxes
                             if b.cat == "wall" and b.level != "EXT" and b.z0 < cut < b.z1])
        for lo, hi, col, _ in bands:
            polys = [sbox(*t(x - g, y - g), *t(x + g, y + g)) for (x, y), v in zip(r["pts"], r["rssi"]) if lo <= v < hi]
            if polys:
                u = unary_union(polys).difference(solid)
                sh.hatch_polys(list(iter_polygons(u)), solid=True, color=col)
        for b in h.boxes:
            if b.cat in ("wall", "partition") and b.level != "EXT" and b.z0 < cut < b.z1 and b.mat != "insul":
                sh.rect(*t(b.x0, b.y0), *t(b.x1, b.y1), "A-CUT" if b.cat == "wall" else "A-CUT-LGS", lineweight=35 if b.cat == "wall" else 18)
        for n, (x, y, name) in enumerate(r["aps"], 1):
            sh.circle(t(x, y), 1.6 * sh.S, "A-CUT", lineweight=35)
            sh.text(f"AP{f[0]}-{n}", t(x, y), 1.4, "A-TEXT", "MIDDLE_CENTER")
        sh.text(f"{'1階' if f == '1F' else '2階'}（AP {len(r['aps'])}台・目標を満たす面積 {r['cover'] * 100:.0f}%）", t(0, -1500), 2.6, "A-TEXT", "TOP_LEFT")
    y = 128
    for lo, hi, col, lab in bands:
        sh.hatch_polys([sbox(*sh.P(22, y), *sh.P(28, y + 3.5))], solid=True, color=col)
        sh.text(lab, (30, y + 0.5), 2.0, "A-TEXT", paper=True)
        y -= 5.5
    rows = [["AP", "設置位置（天井）", "階"]]
    for r in res:
        for n, (x, y_, name) in enumerate(r["aps"], 1):
            rows.append([f"AP{r['floor'][0]}-{n}", name, r["floor"]])
    sh.text("(1) アクセスポイント", (250, 271), 2.8, "A-TEXT", paper=True)
    yy = sh.table(250, 268, [18, 64, 12], rows, row_h=4.6, h=1.9)
    side_panel(sh, 250, yy - 6, [("h", "計画の考え方"),
        ("t", f"機器: {w['standard']}。各 AP は PoE＋の有線（Cat6A）で機械室（東系統）のネットワークラックに集める（無線中継に頼らない）"),
        ("t", "壁式 RC は内部の耐力壁も RC 250mm で、5GHz は1枚で約25dB 減衰する。床スラブも厚いため、各階に AP を置き、RC 壁で囲まれた区画ごとに電波を届ける"),
        ("t", f"計算: 送信 {w['eirp_dbm']}dBm、自由空間損失＋通過する壁の減衰（RC 25dB・間仕切 4dB・扉 4dB・透明扉 3dB）。0.5m メッシュで受信強度を求め、目標を満たす面積が最大になる位置に AP を1台ずつ追加"),
        ("t", "シアター・ジムは遮音のため扉が重く、それぞれ室内に AP を置くと安定する（必要に応じて実施設計で追加）。外構（菜園・駐車場）は屋外用 AP を別途"),
        ("t", "実施設計で、機種の送信出力・アンテナ特性を用いて現地測定（竣工後のサイトサーベイ）で確認する")], width=150)
    return sh


def control_sheet(h, number):
    """制御（bot 連携）・時刻で変わる照明・掃除ロボット。"""
    import services as SV
    sm = h.spec["smart"]
    sh = frame(h, number, "制御・照明・掃除ロボット計画", 1, label="—")
    sh.text("制御・照明・掃除ロボット計画 — スクリーン・照明・空調・ロボットを bot から操作できる共通の制御基盤", (12, 280), 3.6, "A-TEXT", paper=True)
    # (1) 構成図
    sh.text("(1) 制御の構成", (12, 271), 2.8, "A-TEXT", paper=True)
    boxes = [("bot（AI エージェント・スマホ）", 14, 252), ("ゲートウェイ（ローカル API・認証）", 14, 236),
             ("KNX（有線）", 14, 220), ("Matter（Thread/Wi-Fi）", 74, 220), ("ECHONET Lite（HEMS）", 134, 220)]
    for lab, x, y in boxes:
        sh.rect(*sh.P(x, y), *sh.P(x + (178 if lab.startswith(("bot", "ゲート")) else 56), y + 9), "A-VIS", lineweight=35)
        sh.text(lab, (x + 3, y + 3), 2.2, "A-TEXT", paper=True)
    for x in (42, 102, 162):
        sh.line(sh.P(x, 236), sh.P(x, 229), "A-VIS", lineweight=25)
    sh.line(sh.P(103, 252), sh.P(103, 245), "A-VIS", lineweight=25)
    devs = [(14, f"外付けスクリーン {len(h.blinds)}台", "照明（調光・調色）", "日射・風・雨センサー"),
            (74, "掃除ロボット 2台", "スマートロック（ジム）", ""), (134, "全館空調 2系統", "全熱交換・調湿", "太陽光・蓄電池")]
    for x, *ds in devs:
        sh.line(sh.P(x + 28, 220), sh.P(x + 28, 214), "A-VIS", lineweight=25)
        yy = 210
        for d in ds:
            if d:
                sh.text("・" + d, (x + 2, yy), 2.0, "A-TEXT", paper=True)
                yy -= 4.5
    sh.text(f"優先順位: {sm['safety']}", (14, 192), 2.0, "A-LEGAL-TEXT", paper=True)
    rows = [["対象", "機器", "操作", "優先・安全"]] + [list(r) for r in SV.CONTROL]
    y = sh.table(12, 186, [22, 62, 52, 56], rows, row_h=5.2, h=1.65)
    # (2) 照明スケジュールのグラフ
    gx0, gy0, gw, gh = 222, 196, 170, 62
    sh.text("(2) 照明の時刻スケジュール（全室共通の初期値・室ごと/bot で変更可）", (gx0 - 10, 271), 2.8, "A-TEXT", paper=True)
    sh.rect(*sh.P(gx0, gy0), *sh.P(gx0 + gw, gy0 + gh), "G-TABLE")
    cur = SV.lighting_curve(h)
    for hr in range(0, 25, 3):
        x = gx0 + gw * hr / 24
        sh.line(sh.P(x, gy0), sh.P(x, gy0 + gh), "A-HIDDEN")
        sh.text(f"{hr}時", (x, gy0 - 4), 1.8, "A-TEXT", "MIDDLE_CENTER", paper=True)
    kmin, kmax = 2000, 5500
    ptsK = [sh.P(gx0 + gw * hr / 24, gy0 + gh * (k - kmin) / (kmax - kmin)) for hr, k, _ in cur]
    ptsB = [sh.P(gx0 + gw * hr / 24, gy0 + gh * b / 100) for hr, _, b in cur]
    sh.pline(ptsK, "A-FLOOD", lineweight=50)
    sh.pline(ptsB, "A-CUT", lineweight=50)
    for k in (2200, 3000, 4000, 5000):
        yk = gy0 + gh * (k - kmin) / (kmax - kmin)
        sh.text(f"{k}K", (gx0 - 2, yk), 1.7, "A-TEXT", "MIDDLE_RIGHT", paper=True)
    for b in (0, 50, 100):
        sh.text(f"{b}%", (gx0 + gw + 2, gy0 + gh * b / 100), 1.7, "A-TEXT", "MIDDLE_LEFT", paper=True)
    sh.text("── 色温度（左軸）", (gx0, gy0 - 10), 2.0, "A-FLOOD", paper=True)
    sh.text("── 明るさ（右軸）", (gx0 + 50, gy0 - 10), 2.0, "A-TEXT", paper=True)
    rows = [["時刻", "色温度", "明るさ", "ねらい"],
            ["0〜5時", "2200K", "10%", "夜間の移動は足元だけ（眠りを妨げない）"],
            ["6〜8時", "3000→5000K", "50→100%", "朝日に合わせて上げる（目覚め）"],
            ["8〜16時", "5000→4500K", "100%", "昼の活動・ジム"],
            ["18〜22時", "3000→2200K", "70→15%", "夕方から暖色・暗めへ（就寝前）"]]
    y2 = sh.table(212, gy0 - 14, [24, 30, 26, 100], rows, row_h=5.0, h=1.8)
    # (3) 掃除ロボット
    rp = SV.robot_plan(h)
    rows = [["階", "清掃範囲", "室数", "ドック"]] + [[f, f"{v['area']:.0f}m²", str(v["rooms"]), v["dock"]] for f, v in rp.items()]
    sh.text("(3) 掃除ロボット（床清掃はロボットが行う）", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [14, 30, 16, 60], rows, row_h=5.0, h=1.9)
    side_panel(sh, 12, y - 5, [("t", r) for r in SV.ROBOT_RULES], width=190)
    side_panel(sh, 212, y2 - 6, [("h", "照明の仕様"),
        ("t", "主照明は天井直付けのライン LED（調光 1〜100%・調色 2200〜5000K、DALI-2 DT8、製品未確定）、埋込ダウンライトは弱い補助灯（最大250lm・2200〜3000K）、階段は踏面から300の足元灯（停電時点灯）。L・D・F の3チャネルを時刻で自動変化させ、室ごと・bot から変更できる（E-04〜E-06）"),
        ("t", "シアターは上映時に自動で消灯・足元灯のみ。ジムは運動時 5000K・100%"),
        ("h", "スクリーンの bot 制御"),
        ("t", f"全{len(h.blinds)}台を個別・グループ（方位・室）で操作でき、位置を bot に返す。日没後の自動降下で光漏れを防ぐ（虫を寄せない、E-03）"),
        ("t", "強風（10m/s 以上）・凍結時はセンサーで自動巻上げ、この間は bot の降下指令を受け付けない")], width=190)
    return sh


def insect_sheet(h, number):
    """外構の防虫計画（照明の色・向き・時間、たまり水、建物まわり）。"""
    import services as SV
    el = h.spec["exterior_lighting"]
    sh = frame(h, number, "外構照明・防虫計画図", 500)
    t = fit(h, sh, (110, 158))
    site_base(h, sh, t, contours=False)
    fence_draw(h, sh, t)
    house_outline(h, sh, t)
    ap = h.approach.intersection(h.fence_poly.buffer(-h.fence_t))
    for p in iter_polygons(ap):
        sh.pline(t.pts(p.exterior.coords), "A-PAVE", closed=True)
    cp, pg = h.carport, h.pergola
    sh.rect(*t(cp[0], cp[1]), *t(cp[2], cp[3]), "A-HIDDEN")
    sh.rect(*t(pg[0], pg[1]), *t(pg[2], pg[3]), "A-HIDDEN")
    # 防草砂利帯（建物まわり 1.0m）
    o = h.outer_dims()
    from shapely.geometry import box as sbox
    band = sbox(o[0] - 1000, o[1] - 1000, o[2] + 1000, o[3] + 1000).difference(sbox(*o))
    sh.hatch_polys([Polygon(t.pts(p.exterior.coords), [t.pts(r.coords) for r in p.interiors]) for p in iter_polygons(band)],
                   pattern="DOTS", spacing=1.0, layer="A-PAVE")
    for name, (x, y) in h.ext_lights:
        c = t(x, y)
        sh.circle(c, 0.9 * sh.S, "A-FLOOD", lineweight=35)
        sh.line((c[0] - 0.9 * sh.S, c[1]), (c[0] + 0.9 * sh.S, c[1]), "A-FLOOD")
    sh.text(f"外構照明 {len(h.ext_lights)}台（{el['cct']}K・下向き・人感センサー）", t(15500, -9000), 1.6, "A-TEXT", "MIDDLE_LEFT")
    sh.text("北側（水路側）は照明なし", t(-10000, 33000), 1.6, "A-TEXT", "MIDDLE_CENTER")
    sh.text("建物まわり 防草砂利帯 幅1.0m", t(h.W / 2, o[3] + 2500), 1.5, "A-TEXT", "MIDDLE_CENTER")
    tk = h.tank
    sh.rect(*t(tk[0], tk[1]), *t(tk[2], tk[3]), "A-DRAIN")
    sh.text("貯留槽（密閉・防虫網）", t((tk[0] + tk[2]) / 2, tk[3] + 1500), 1.5, "A-TEXT", "MIDDLE_CENTER")
    sh.north_arrow(sh.P(205, 60), 6, rot=h.facade_az)
    sh.view_title("外構照明・防虫計画図", "1:500", (18, 22))
    rows = [["項目", "虫を寄せない・発生させない工夫"]] + [list(r) for r in SV.INSECT]
    sh.text("防虫の工夫", (222, 271), 2.8, "A-TEXT", paper=True)
    y = sh.table(222, 268, [24, 160], rows, row_h=5.2, h=1.8)
    cnt = {}
    for n, _ in h.ext_lights:
        k = n.split("（")[0]
        cnt[k] = cnt.get(k, 0) + 1
    rows = [["器具", "台数", "仕様"]] + [[k, str(v), f"{el['cct']}K・全カットオフ・人感" + ("・H600" if k == "ボラード" else "")] for k, v in cnt.items()]
    sh.text("外構照明の器具", (222, y - 6), 2.8, "A-TEXT", paper=True)
    sh.table(222, y - 9, [60, 16, 108], rows, row_h=5.0, h=1.9)
    return sh


def gate_detail(h, number):
    """門まわり詳細図: 門の後退・ゴミ収集ボックスと目隠し壁・道路からの視線。"""
    import sightshade as SS
    ex = h.spec["exterior"]
    gb, gs = ex["garbage_box"], ex["garbage_screen"]
    sh = frame(h, number, "門まわり詳細図（ゴミ収集ボックス）", 100)
    t = T(sh, (7000, -33500), (22, 100))
    view = sbox(7000, -33500, 27500, -18000)
    for (a, b, k), c in zip(h.site_edges, h.edge_class):
        seg = LineString([a, b]).intersection(view)
        if not seg.is_empty:
            for g in getattr(seg, "geoms", [seg]):
                sh.pline(t.pts(g.coords), "A-SITE", lineweight=25)
    road = [e for e, c in zip(h.site_edges, h.edge_class) if c == "南側道路"][0]
    sh.text("南側道路（幅員 7.4m）", t(17000, -33000), 2.4, "A-TEXT", "MIDDLE_CENTER")
    # 舗装・カーポート・アプローチ
    for geom, lay in ((h.dotcon.intersection(view), "A-PAVE"), (h.approach.intersection(h.fence_poly.buffer(-h.fence_t)).intersection(view), "A-PAVE")):
        for p in iter_polygons(geom):
            sh.pline(t.pts(p.exterior.coords), lay, closed=True)
    cp = h.carport
    sh.rect(*t(cp[0], cp[1]), *t(cp[2], -18000), "A-HIDDEN")
    for st in h.stalls:
        sh.rect(*t(st[0], st[1]), *t(st[2], -18100), "A-VIS")
    sh.text("3台用ソーラーカーポート（北へ続く）", t((cp[0] + cp[2]) / 2, cp[1] + 1200), 2.2, "A-TEXT", "MIDDLE_CENTER")
    # 塀・門扉
    fence_draw(h, sh, t, clip=view)
    for name, a, b in h.gates[:2]:
        sh.text(name, t((a[0] + b[0]) / 2, a[1] + 700), 2.2, "A-TEXT", "MIDDLE_CENTER")
    # 目隠し壁・ボックス
    walls = [sbox(*t(r[0], r[1]), *t(r[2], r[3])) for r in h.garbage_screens]
    sh.hatch_polys(walls)
    for wpoly in walls:
        sh.pline(list(wpoly.exterior.coords), "A-CUT", closed=True, lineweight=50)
    x0, y0, x1, y1 = h.garbage_box
    sh.rect(*t(x0, y0), *t(x1, y1), "A-DOOR", lineweight=35)
    sh.line(t(x0, y0), t(x1, y1), "A-DOOR")
    sh.line(t(x0, y1), t(x1, y0), "A-DOOR")
    sh.text("ゴミ収集ボックス", t((x0 + x1) / 2, y1 + 450), 2.0, "A-TEXT", "MIDDLE_CENTER")
    # 道路からの視線（ボックスの角へ）。壁に当たる所で止める
    scr = [sbox(*r) for r in h.garbage_screens] + [ln.buffer(h.fence_t) for ln in h.fence_lines]   # 視線は目隠し壁か塀で止まる
    for vx, vy in [(7145, road[0][1] - 1500), (10000, road[0][1] - 1500), (14000, road[0][1] - 1500), (19000, road[0][1] - 1500), (23932, -32403)]:
        for tx in (x0, x1):
            ln = LineString([(vx, vy), (tx, y0)])
            hits = [ln.intersection(s_) for s_ in scr]
            ds = [min(ln.project(Point(c)) for g_ in getattr(g, "geoms", [g]) for c in (g_.exterior.coords if g_.geom_type == "Polygon" else g_.coords))
                  for g in hits if not g.is_empty]
            end = ln.interpolate(min(ds)) if ds else Point(tx, y0)
            sh.line(t(vx, vy), t(end.x, end.y), "A-FLOOD")
        sh.circle(t(vx, vy), 0.8 * sh.S, "A-FLOOD")
    gv = SS.garbage_visibility(h)
    sh.text(f"視線（目の高さ1.5m）: 道路から {gv['n']}地点で判定 → ボックスの一部が見える地点 {len(gv['visible'])}（南東の角から斜めに・判定点16のうち最大{max([p[2] for p in gv['visible']], default=0)}点）", t(7200, -34400), 2.0, "A-LEGAL-TEXT", "TOP_LEFT")
    for vx, vy, n in gv["visible"]:
        sh.circle(t(vx, vy), 0.5 * sh.S, "A-LEGAL-TEXT")
    # 寸法
    vdim(sh, t, [road[0][1], h.y_gate], 26500)
    sh.text(f"門の後退 {ex['gate_setback'] / 1000:.1f}m", t(26900, (road[0][1] + h.y_gate) / 2), 1.8, "A-TEXT", "MIDDLE_LEFT")
    w0, wg = h.garbage_screens[0], h.garbage_screens[-1]
    hdim(sh, t, [w0[0], x0, x1, w0[2]], w0[1] - 900)
    vdim(sh, t, [w0[1], w0[3], wg[3], h.y_gate], w0[2] + 900)
    sh.text(f"出入口 {(h.y_gate - wg[3]) / 1000:.2f}m", t(w0[2] + 1500, (wg[3] + h.y_gate) / 2), 1.6, "A-TEXT", "MIDDLE_LEFT")
    hdim(sh, t, [h.gates[1][1][0], h.gates[1][2][0], h.gates[0][1][0], h.gates[0][2][0]], h.y_gate + 1800)
    # 車両盗難対策: 電動昇降ボラード・カメラ
    vs = h.spec["vehicle_security"]
    for bx, by in h.bollards:
        sh.circle(t(bx, by), vs["bollards"]["d"] / 2, "A-CUT", lineweight=35)
        sh.hatch_polys([Point(*t(bx, by)).buffer(vs["bollards"]["d"] / 2)], solid=True, color=8)
    sh.text(f"電動昇降ボラード ×{len(h.bollards)}（門の内側）", t(h.bollards[-1][0] + 600, h.bollards[-1][1]), 1.8, "A-TEXT", "MIDDLE_LEFT")
    for cx, cy, lab in [(h.gates[1][1][0] - 300, h.y_gate + 400, "CAM"), (h.gates[0][2][0] + 300, h.y_gate + 400, "CAM")]:
        sh.rect(*t(cx - 200, cy - 150), *t(cx + 200, cy + 150), "A-FLOOD")
        sh.text(lab, t(cx, cy + 500), 1.4, "A-FLOOD", "MIDDLE_CENTER")
    sh.view_title("門まわり平面詳細図", "1:100", (18, 22))
    notes = [("h", "計画の考え方"),
             ("t", f"南側の門（人用・車両）を道路境界から {ex['gate_setback'] / 1000:.1f}m 後退させ、門の前を車1台分の待避・ゴミ出しのスペースとする（門を開ける間、車が道路に止まらない）"),
             ("t", f"ゴミ収集ボックス W{gb['w']:,}×D{gb['d']:,}×H{gb['h']:,} を門の外・西の角に、西の塀に沿わせ南の目隠し壁に寄せて置く（壁から{gb['south_gap']}）。扉は東向き。収集作業者は門を通らずに出し入れできる"),
             ("t", f"ボックスの南に自立目隠し壁（西の塀から X{gs['x_end'] / 1000:.1f}m まで）H{gs['h'] / 1000:.1f}m、東端に北へ {gs['wing'] / 1000:.1f}m の短い袖壁。袖壁と門の塀の間（約{(h.y_gate - h.garbage_screens[-1][3]) / 1000:.2f}m）から出し入れする"),
             ("t", "正面（南側道路）からは壁しか見えない。南東の角（東側道路の南端付近）から斜めに見ると、袖壁の脇からボックスの一部がわずかに見える（施主了承）"),
             ("t", "壁は RC（独立基礎）で門・塀と同じ仕上げ。ボックスは金属製の置き型（基礎に固定しない＝建築物に当たらない想定）。中は臭気がこもらないよう上部に通気"),
             ("t", "防虫: ボックスは密閉型・蓋付き、近くに照明を置かない（収集は日中）"),
             ("t", "人用門扉は東へ移し（X12.4〜13.6m）、アプローチは門を入ってすぐ西へ寄せ、西の塀沿いを北へ進む"),
             ("h", "車両盗難対策"),
             ("t", f"門: {vs['gate']}"),
             ("t", f"電動昇降ボラード {vs['bollards']['n']}本（φ{vs['bollards']['d']}・地上高{vs['bollards']['h']}）を車両門扉の内側に設け、夜間・不在時は上げる。門扉を壊されても車を出せない"),
             ("t", f"駐車: {vs['wheel_stop']}"),
             ("t", f"鍵: {vs['key_box']}（リレーアタック対策）"),
             ("t", f"監視: {vs['camera']}。{vs['sensor']}。勝手口は廃止し、出入口は南の2か所に限る")]
    side_panel(sh, 250, 270, notes, width=150)
    return sh


def _integrated_building(h, sh, t):
    """総合配置図の建物: 1階切断（壁・開口の線）＋屋根・庇の外形＋室名＋玄関▲。"""
    cut = h.fl["1F"] + 1100
    emit(sh, plan_projection(h, "1F"), t)
    for w in h.walls:                                # 外壁の開口だけを線で示す
        if w.cat == "insul":
            continue
        ext = (w.axis == "x" and (abs(w.c) < 400 or abs(w.c - h.D) < 400)) or (w.axis == "y" and (abs(w.c) < 400 or abs(w.c - h.W) < 400))
        for op in w.openings:
            if not ext or op.floor != "1F" or op.operation == "opening" or not (op.z0 < cut < op.z1):
                continue
            p0 = t(op.u0, w.c) if w.axis == "x" else t(w.c, op.u0)
            p1 = t(op.u1, w.c) if w.axis == "x" else t(w.c, op.u1)
            sh.line(p0, p1, "A-GLAZ" if op.kind == "window" else "A-DOOR", lineweight=35)
    bx0, by0, bx1, by1 = h.battery_room.rect          # v4.23 蓄電室（E-BATT 塗り）
    sh.hatch_polys([sbox(*t(bx0, by0), *t(bx1, by1))], solid=True, color=1, layer="E-BATT")
    sh.rect(*t(bx0, by0), *t(bx1, by1), "E-BATT")
    o = h.outer_dims()                               # 屋根（パラペット）外形
    sh.rect(*t(o[0], o[1]), *t(o[2], o[3]), "A-HIDDEN")
    for cn in h.canopies:                            # 連続庇
        sh.rect(*t(cn[0], cn[1]), *t(cn[2], cn[3]), "A-HIDDEN")
    for r in h.rooms:                                # 室名（面積なし・小室は省略）
        if r.floor != "1F" or "階段" in r.name:
            continue
        rw, rd = r.rect[2] - r.rect[0], r.rect[3] - r.rect[1]
        if min(rw, rd) < 1800 or _text_width(r.name, 2.0) * sh.S > rw - 300:
            continue
        sh.text(r.name, t(*r.label_at), 2.0, "A-ROOM", "MIDDLE_CENTER")
    ex = h.entrance                                  # 玄関 ▲
    cx = (ex.u0 + ex.u1) / 2
    r = 1.6 * sh.S
    c = t(cx, -900)
    sh.pline([(c[0] - r, c[1] - r), (c[0] + r, c[1] - r), (c[0], c[1] + r)], "A-SYMB", closed=True)
    sh.hatch_polys([Polygon([(c[0] - r, c[1] - r), (c[0] + r, c[1] - r), (c[0], c[1] + r)])], solid=True, color=7)


def _reserve_draw(h, sh, t, foundations=False):
    """将来ソーラー予約ゾーン RZ（A-PVRES: 外形 DASHED＋細かい点ハッチ）。foundations=True は基礎候補点（□）も描く（A-02Z）。"""
    polys = [Polygon(t.pts(p.exterior.coords)) for p in iter_polygons(h.pv_reserve)]
    sh.hatch_polys(polys, layer="A-PVRES", pattern="DOTS", spacing=3.0)
    for q in polys:
        sh.pline(list(q.exterior.coords), "A-PVRES", closed=True)
    c = h.pv_reserve_a.centroid
    sh.text(f"将来ソーラー予約ゾーン {h.pv_reserve.area / 1e6:.1f}m²", t(c.x - 2500, c.y + 600), 1.8, "A-PVRES", "MIDDLE_CENTER")
    sh.text("（塀内面から1.3m・今回は範囲のみ）", t(c.x - 2500, c.y - 600), 1.4, "A-PVRES", "MIDDLE_CENTER")
    if foundations:
        for (x, y) in h.pv_reserve_foundations:
            sh.rect(*t(x - 250, y - 250), *t(x + 250, y + 250), "A-PVRES", lineweight=35)


def _integrated_exterior(h, sh, t):
    """総合配置図の外構: 舗装・カーポート・パーゴラ・菜園・雨水施設・外構照明。小物の位置は _integrated_items が返す。"""
    S = sh.S
    hatch = lambda polys: sh.hatch_polys(polys, pattern="NET", spacing=1.0, layer="A-PAVE")
    hatch([Polygon(t.pts(h.dotcon.exterior.coords))])
    sh.pline(t.pts(h.dotcon.exterior.coords), "A-PAVE", closed=True)
    for p in iter_polygons(h.dotcon_garden):
        hatch([Polygon(t.pts(p.exterior.coords), [t.pts(r.coords) for r in p.interiors])])
    ap = h.approach.intersection(h.fence_poly.buffer(-h.fence_t))
    for p in iter_polygons(ap):
        sh.pline(t.pts(p.exterior.coords), "A-PAVE", closed=True)
        sh.hatch_polys([Polygon(t.pts(p.exterior.coords))], pattern="ANSI37", spacing=2.5, layer="A-PAVE")
    fr = h.farm
    for pl in h.planters:
        sh.rect(*t(pl[0], pl[1]), *t(pl[2], pl[3]), "A-VIS")
    pg, cp = h.pergola, h.carport
    sh.rect(*t(pg[0], pg[1]), *t(pg[2], pg[3]), "A-VIS")
    sh.rect(*t(cp[0], cp[1]), *t(cp[2], cp[3]), "A-VIS")
    for st in h.stalls:
        sh.rect(*t(st[0], st[1]), *t(st[2], st[3]), "A-VIS")
    # 雨水施設
    tk = h.tank
    sh.rect(*t(tk[0], tk[1]), *t(tk[2], tk[3]), "A-DRAIN")
    sh.line(t(tk[0], tk[1]), t(tk[2], tk[3]), "A-DRAIN")
    for p in h.infil_pits:
        sh.circle(t(*p), 0.9 * S, "A-DRAIN")
    for p in h.flap:
        sh.rect(*t(p[0] - 500, p[1] - 500), *t(p[0] + 500, p[1] + 500), "A-DRAIN")
    for p in h.spec["exterior"]["canopy"]["downpipes"]:
        sh.circle(t(*p), 0.7 * S, "A-DRAIN")
    # 小物
    sh.text("ソーラーパーゴラ（日よけ付き菜園）", t((pg[0] + pg[2]) / 2, pg[3] - 1500), 2.0, "A-TEXT", "MIDDLE_CENTER")
    sh.text("ソーラーカーポート（3台）", t((cp[0] + cp[2]) / 2, cp[3] + 900), 1.8, "A-TEXT", "MIDDLE_CENTER")
    sh.text(f"雨水貯留槽 {h.spec['exterior']['retention_tank_m3']}m³（密閉・防虫網0.4mm・フラップ弁）", t((tk[0] + tk[2]) / 2, tk[3] + 1000), 1.5, "A-TEXT", "MIDDLE_CENTER")
    _reserve_draw(h, sh, t)
    for bx, by in h.bollards:
        sh.circle(t(bx, by), 0.7 * S, "A-VIS")
    for r in (h.delivery_box, h.garbage_box):
        sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "A-VIS")
    for r in h.garbage_screens:
        sh.hatch_polys([sbox(*t(r[0], r[1]), *t(r[2], r[3]))])
        sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "A-FENCE")
    _planting_draw(h, sh, t)
    _utilities_draw(h, sh, t)
    for _, p in h.ext_lights:                        # 外構照明 ● φ1.2mm
        sh.hatch_polys([Point(*t(*p)).buffer(0.6 * S)], solid=True, color=6, layer="E-EXLT")
        sh.circle(t(*p), 0.6 * S, "E-EXLT")


def _flow_arrows(sh, t, ln, layer, every=10000, size=650):
    """管に沿って every ごとに流れの向き（→）を描く（線の向き＝流れの向き）。"""
    d = every / 2
    while d < ln.length - 300:
        p, q = ln.interpolate(d), ln.interpolate(d + 50)
        ang = math.atan2(q.y - p.y, q.x - p.x)
        for s_ in (0.45, -0.45):
            sh.line(t(p.x + 150 * math.cos(ang), p.y + 150 * math.sin(ang)),
                    t(p.x + 150 * math.cos(ang) - size * math.cos(ang + s_), p.y + 150 * math.sin(ang) - size * math.sin(ang + s_)), layer)
        d += every


def _utilities_draw(h, sh, t, labels=False):
    """給排水（上水 E-WATER・汚水 E-SEWER・雨水 A-DRAIN）。管径は書かない（A-02 の右欄表）。記号: 量水器 □、汚水桝 ○に×、雨水桝 ○。"""
    S = sh.S
    for key, lay in (("water", "E-WATER"), ("sewer", "E-SEWER"), ("storm_w", "A-DRAIN"), ("storm_e", "A-DRAIN")):
        for ln in h.pipes[key]:
            sh.pline(t.pts(ln.coords), lay)
            _flow_arrows(sh, t, ln, lay)
    x, y = h.water_meter
    sh.rect(*t(x - 450, y - 450), *t(x + 450, y + 450), "E-WATER", lineweight=35)
    for i, p in enumerate(h.sewer_manholes, 1):
        r = 0.9 * S
        c = t(*p)
        sh.circle(c, r, "E-SEWER")
        sh.line((c[0] - r * 0.7, c[1] - r * 0.7), (c[0] + r * 0.7, c[1] + r * 0.7), "E-SEWER")
        sh.line((c[0] - r * 0.7, c[1] + r * 0.7), (c[0] + r * 0.7, c[1] - r * 0.7), "E-SEWER")
        if labels:
            sh.text(f"汚{i}", (c[0] + 1.3 * S, c[1] + 0.2 * S), 1.4, "A-TEXT", "MIDDLE_LEFT")
    for i, p in enumerate(h.storm_manholes, 1):
        sh.circle(t(*p), 0.9 * S, "A-DRAIN")
        if labels:
            c = t(*p)
            sh.text(f"雨{i}", (c[0] + 1.3 * S, c[1] + 0.2 * S), 1.4, "A-TEXT", "MIDDLE_LEFT")
    for p in h.storm_pits:
        sh.circle(t(*p), 0.9 * S, "A-DRAIN")
        sh.circle(t(*p), 0.45 * S, "A-DRAIN")


def _planting_draw(h, sh, t):
    """植栽（E-PLNT）: 高木・中木は葉張りの円（高木は中心に点）、低木は波線、地被は点ハッチ。位置は仮置き（要確認）。"""
    S = sh.S
    for (x, y), r in h.groundcover:
        sh.hatch_polys([Polygon(t.pts(Point(x, y).buffer(r, 32).exterior.coords))], pattern="DOTS", spacing=1.6, layer="E-PLNT")
    for p in h.plants:
        x, y = p["xy"]
        sh.circle(t(x, y), p["crown"] / 2, "E-PLNT")
        if p["kind"] == "高木":
            sh.hatch_polys([Point(*t(x, y)).buffer(0.4 * S)], solid=True, color=3, layer="E-PLNT")
        sh.text(p["id"], t(x + p["crown"] / 2 + 250, y), 1.5, "A-TEXT", "MIDDLE_LEFT")
    ln = h.shrub["line"]
    n = int(ln.length // 400)
    pts = []
    for i in range(n + 1):
        q = ln.interpolate(min(ln.length, i * 400))
        pts.append(t(q.x, q.y + (160 if i % 2 else -160)))
    sh.pline(pts, "E-PLNT")
    m = ln.interpolate(0.5, normalized=True)
    sh.text(h.shrub["id"], t(m.x, m.y + 700), 1.5, "A-TEXT", "MIDDLE_CENTER")


def _integrated_items(h):
    """番号引出しの対象（名称・数量/寸法・詳細図・位置）。位置はモデル値から取る。"""
    ex = h.spec["exterior"]
    vs = h.spec["vehicle_security"]
    ctr = lambda r: [((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)]
    gb = h.garbage_box
    items = [
        (f"電動昇降ボラード ×{len(h.bollards)}", f"φ{vs['bollards']['d']}・地上高{vs['bollards']['h']}", "A-02D", list(h.bollards)),
        ("宅配ボックス", f"W{h.delivery_box[2] - h.delivery_box[0]:,.0f}×D{h.delivery_box[3] - h.delivery_box[1]:,.0f}", "A-02D", ctr(h.delivery_box)),
        ("ゴミ収集ボックス＋目隠し壁", f"W{gb[2] - gb[0]:,.0f}×D{gb[3] - gb[1]:,.0f}、壁H{ex['garbage_screen']['h']:,}", "A-02D", ctr(gb)),
        ("人用門扉", f"W{abs(h.gates[1][2][0] - h.gates[1][1][0]):,.0f}（後退{ex['gate_setback'] / 1000:.1f}m）", "A-02D", ctr(h.gates[1][1] + h.gates[1][2])),
        ("車両門扉", f"W{abs(h.gates[0][2][0] - h.gates[0][1][0]):,.0f} 電動スライド", "A-02D", ctr(h.gates[0][1] + h.gates[0][2])),
        ("高木 T1・T2（アオダモ）", "H4.0m・葉張り3.0m ×2（仮置き）", "—", [p["xy"] for p in h.plants if p["kind"] == "高木"]),
        ("量水器（上水）", "□ 門の外・南側道路から引込（仮置き）", "—", [h.water_meter]),
        ("汚水最終桝", "○× 塩ビφ150 → 公共下水（仮置き）", "—", [h.sewer_final]),
        ("雨水最終桝", "○ φ150 → 公共雨水（仮置き）", "—", [h.storm_final]),
        (f"フラップ弁付き排水口 ×{len(h.flap)}", "塀の低位置・逆流防止", "A-02", list(h.flap)),
        (f"浸透桝 ×{len(h.infil_pits)}", "Dotcon+ 帯・東系統", "A-02", list(h.infil_pits)),
        (f"縦樋 ×{len(ex['canopy']['downpipes'])}", "西系統→貯留槽・東系統→浸透桝", "A-02", [tuple(p) for p in ex["canopy"]["downpipes"]]),
        ("防犯カメラ ×2（門）", "赤外線 940nm", "A-02D",
         [(h.gates[1][1][0] - 300, h.y_gate + 400), (h.gates[0][2][0] + 300, h.y_gate + 400)]),
        ("蓄電室（1階・ジム北東角）", f"{h.spec['battery']['nominal_kwh']}kWh級・{h.battery_room.area:.1f}m²", "A-03", ctr(h.battery_room.rect)),
        ("将来ソーラー予約ゾーン", f"{h.pv_reserve.area / 1e6:.1f}m²（塀内面から1.3m）", "A-02Z", [(h.pv_reserve_a.centroid.x, h.pv_reserve_a.centroid.y - 2500)]),
        ("雨水貯留槽（密閉・防虫）", f"{h.spec['exterior']['retention_tank_m3']}m³・パーゴラの下へ移設", "A-02Z", ctr(h.tank)),
    ]
    kinds = {}
    for name, p in h.ext_lights:
        k = "門灯" if name.startswith("門灯") else name.split("（")[0]
        kinds.setdefault(k, []).append(p)
    for k, pts in kinds.items():
        items.append((f"外構照明 {k} ×{len(pts)}", "● 低色温度・下向き・人感", "E-03", pts))
    return items


def _dim_line(sh, p0, p1, label, h=1.8):
    """寸法線（用紙上 p0→p1 はモデル座標）。端部に斜線、中央に寸法値。"""
    sh.line(p0, p1, "A-DIMS")
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    k = 1.0 * sh.S
    for q in (p0, p1):
        sh.line((q[0] - k * math.cos(ang + 0.785), q[1] - k * math.sin(ang + 0.785)),
                (q[0] + k * math.cos(ang + 0.785), q[1] + k * math.sin(ang + 0.785)), "A-DIMS")
    m = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    vert = abs(math.sin(ang)) > 0.7
    off = 1.4 * sh.S
    sh.text(label, (m[0] - off, m[1]) if vert else (m[0], m[1] + off), h, "A-DIMS", "MIDDLE_CENTER", rot=90 if vert else 0)


def _integrated_dims(h, sh, t):
    """建物外形〜敷地境界の離れ（S・E・N・W の4本）。"""
    o = h.outer_dims()
    my, mx = (o[1] + o[3]) / 2, (o[0] + o[2]) / 2
    edge = h.site.exterior
    for name, a, b in (("S", (11500, o[1]), (11500, -1e6)), ("N", (mx, o[3]), (mx, 1e6)),
                       ("E", (o[2], my), (1e6, my)), ("W", (o[0], my), (-1e6, my))):
        pt = LineString([a, b]).intersection(edge)
        hits = [g for g in getattr(pt, "geoms", [pt]) if not g.is_empty]
        if not hits:
            continue
        q = min(hits, key=lambda g: Point(a).distance(g))
        d = Point(a).distance(q) / 1000.0
        _dim_line(sh, t(*a), t(q.x, q.y), f"{d:.2f}m")


def _integrated_cliff(h, sh, t):
    """がけ条例の2H範囲線（水路端から 2×北のがけ高、東側道路境界から 2×東のがけ高）。"""
    cl = h.spec["site"]["cliff"]
    out = []
    for cls, hh, tag in (("水路", cl["north_h"], "水路"), ("東側道路", cl["east_h"], "東側道路")):
        d = 2 * hh
        for (a, b, _), c in zip(h.site_edges, h.edge_class):
            if c != cls:
                continue
            seg = LineString([a, b])
            for side in ("left", "right"):
                o = seg.parallel_offset(d, side)
                if h.site.contains(o.interpolate(0.5, normalized=True)):
                    g = o.intersection(h.site)
                    for part in getattr(g, "geoms", [g]):
                        if part.geom_type == "LineString" and part.length > 1000:
                            sh.pline(t.pts(part.coords), "A-LEGAL")
                            out.append((tag, d, part))
                    break
    seen = set()
    for tag, d, part in out:                         # 区間ごとに1つ、中央に短い注記
        if tag in seen:
            continue
        seen.add(tag)
        m = part.interpolate(0.12 if tag == "東側道路" else 0.5, normalized=True)
        sh.text(f"がけ2H {d / 1000:.1f}m（{tag}から）", t(m.x, m.y), 1.7, "A-LEGAL-TEXT", "MIDDLE_CENTER")


def _integrated_levels(h, sh, t):
    """道路・水路の TP 点（4点）と、建物まわりのレベル注記。"""
    c = h.site.centroid
    for i in (7, 4, 3, 0):
        x, y = h.site_pts[i]
        dx, dy = c.x - x, c.y - y
        n = math.hypot(dx, dy) or 1
        x2, y2 = x + dx / n * 2200, y + dy / n * 2200
        sh.line(t(x2 - 400, y2), t(x2 + 400, y2), "A-SYMB")
        sh.line(t(x2, y2 - 400), t(x2, y2 + 400), "A-SYMB")
        sh.text(f"TP+{tp(h, h.ground(x, y)):.1f}", t(x2, y2 - 1500), 1.5, "A-SYMB", "MIDDLE_CENTER")
    sh.text(f"1FL=GL+{h.fl['1F']:,}／FGL=GL+{h.fgl}", t(h.W + 1800, h.D / 2 + 3200), 1.5, "A-SYMB", "MIDDLE_LEFT")
    sh.text("設計GL±0（TP+%.1f・南側道路）" % h.gl_tp, t(h.W + 1800, h.D / 2 + 2300), 1.5, "A-SYMB", "MIDDLE_LEFT")


def _integrated_callouts(h, sh, t, items):
    """番号丸 φ3mm を引出し先の近くへ自動配置（建物中心から離れる向き、丸どうしは離す）。戻り値: 描いた番号丸の数。"""
    S = sh.S
    inv = lambda p: ((p[0] - sh.ox) / S, (p[1] - sh.oy) / S)
    bc = inv(t(h.W / 2, h.D / 2))
    anchors, bub = [], []
    for it in items:
        a = inv(t(*it[3][0]))
        dx, dy = a[0] - bc[0], a[1] - bc[1]
        n = math.hypot(dx, dy) or 1
        anchors.append(a)
        bub.append([a[0] + dx / n * 6.0, a[1] + dy / n * 6.0])
    obst = []                                        # すでに描いた文字の外形（用紙mm）。丸はこれを避ける
    for e in sh.msp:
        if e.dxftype() == "TEXT" and e.dxf.layer not in ("G-FRAME", "G-TITLE"):
            hp = e.dxf.height / S
            w = _text_width(e.dxf.text, hp)
            al, p1, _ = e.get_placement()
            x0 = (p1[0] - sh.ox) / S
            y0 = (p1[1] - sh.oy) / S
            x0 -= w / 2 if "CENTER" in al.name else (w if "RIGHT" in al.name else 0)
            y0 -= hp / 2 if al.name.startswith("MIDDLE") else (hp if al.name.startswith("TOP") else 0)
            if e.dxf.get("rotation", 0) % 180 == 90:
                x0, w, hp = x0 + w / 2 - hp / 2, hp, w
                y0 -= hp / 2 - w * 0
            obst.append((x0, y0, x0 + w, y0 + hp))
    lo, hi = (16.0, 54.0), (248.0, 282.0)
    clamp = lambda b: [min(max(b[0], lo[0]), hi[0]), min(max(b[1], lo[1]), hi[1])]
    for _ in range(80):
        moved = False
        for i in range(len(bub)):
            for j in range(i + 1, len(bub)):
                dx, dy = bub[j][0] - bub[i][0], bub[j][1] - bub[i][1]
                d = math.hypot(dx, dy)
                if d < 4.6:
                    ux, uy = (dx / d, dy / d) if d > 1e-6 else (1.0, 0.0)
                    k = (4.6 - d) / 2 + 0.05
                    bub[i][0] -= ux * k; bub[i][1] -= uy * k
                    bub[j][0] += ux * k; bub[j][1] += uy * k
                    moved = True
        for b in bub:
            for (x0, y0, x1, y1) in obst:
                nx, ny = min(max(b[0], x0), x1), min(max(b[1], y0), y1)
                dx, dy = b[0] - nx, b[1] - ny
                d = math.hypot(dx, dy)
                if d < 2.0:                              # 丸の半径1.5＋余白
                    if d < 1e-6:                         # 文字の内側: 最寄りの辺へ出す
                        dx, dy = 0.0, (1.0 if b[1] >= (y0 + y1) / 2 else -1.0)
                        d, nx, ny = 1.0, b[0], (y1 if dy > 0 else y0)
                        dx, dy = 0.0, dy * 1.0
                    k = (2.0 - d) / d if d > 0 else 1.0
                    b[0] += dx * k
                    b[1] += dy * k
                    moved = True
        bub = [clamp(b) for b in bub]
        if not moved:
            break
    for i, (a, b) in enumerate(zip(anchors, bub), 1):
        P = sh.P
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        sh.line(P(*a), P(b[0] - 1.5 * math.cos(ang), b[1] - 1.5 * math.sin(ang)), "A-SYMB")
        sh.circle(P(*b), 1.5 * S, "A-SYMB")
        sh.text(str(i), P(*b), 1.8, "A-SYMB", "MIDDLE_CENTER")
    return len(items)


def site_integrated(h, number, legal_summary):
    """総合配置・外構統合図（A3 横1枚・S=1:300）: 建物1階切断と外構要素を1枚に統合する。
    用紙・縮尺: 1:250 では敷地南東（門・ボラード）が表題欄にかかるため 1:300 とした。"""
    sm = legal_summary
    sh = frame(h, number, "総合配置・外構統合図", 300)
    t = fit(h, sh, (131, 165))
    site_base(h, sh, t, contours=False, margin=3000, roads=True, margin_top=4500, road_avoid=(14, 266, 112, 288), donation=True)
    _integrated_exterior(h, sh, t)
    fence_draw(h, sh, t)
    _integrated_building(h, sh, t)
    _integrated_cliff(h, sh, t)
    _integrated_levels(h, sh, t)
    _integrated_dims(h, sh, t)
    for i, p in enumerate(h.site_pts):                # 頂点番号
        sh.circle(t(*p), 0.7 * sh.S, "A-SYMB")
        c = h.site.centroid
        dx, dy = p[0] - c.x, p[1] - c.y
        n = math.hypot(dx, dy) or 1
        sh.text(str(i + 1), t(p[0] + dx / n * 1800, p[1] + dy / n * 1800), 1.5, "A-SYMB", "MIDDLE_CENTER")
    for cls, txt in (("水路", "水路・北側道路"), ("東側道路", "東側道路"), ("南側道路", "南側道路")):
        es = [(LineString([a, b]), a, b) for (a, b, _), c in zip(h.site_edges, h.edge_class) if c == cls]
        ln, a, b = max(es, key=lambda e: e[0].length)
        m = ln.interpolate(0.5, normalized=True)
        c = h.site.centroid
        dx, dy = m.x - c.x, m.y - c.y
        n = math.hypot(dx, dy) or 1
        sh.text(txt, t(m.x + dx / n * 4000, m.y + dy / n * 4000), 2.0, "A-TEXT", "MIDDLE_CENTER")
    items = _integrated_items(h)
    nb = _integrated_callouts(h, sh, t, items)
    sh.north_arrow(sh.P(364, 268), 6, rot=h.facade_az)
    sh.view_title("総合配置・外構統合図", "1:300", (18, 280))
    # ---- 右欄: 凡例・番号表・注記
    X = 262
    sh.text("凡例", (X, 280), 3.0, "A-TEXT", paper=True)
    rows = [("A-FENCE", "RC塀 t=150", "fence"), ("A-PAVE", "Dotcon+ 透水舗装", "pave"),
            ("A-PAVE", "アプローチ（ANSI37）", "ins"), ("A-DRAIN", "雨水施設（貯留槽・浸透桝等）", "line"),
            ("A-SITE", "敷地境界（新・塀の外面）", "line"), ("A-LEGAL", "がけ条例 2H 範囲", "line"),
            ("E-EXLT", "外構照明（●）", "line"), ("A-SYMB", "番号丸（下表）", "line"),
            ("A-ROAD-CW", "車道（#333333）", "cw"), ("A-ROAD-SW", "歩道（#333333・要確認）", "sw"),
            ("A-DONATE", "寄付地（市へ割譲の提案・要確認）", "don"), ("A-DONATE-BND", "寄付地境界（旧敷地境界）", "line"),
            ("E-PLNT", "植栽（仮置き・要確認）", "plnt"), ("A-PVRES", "将来ソーラー予約ゾーン（破線＋点）", "line"), ("E-BATT", "蓄電室（1階・塗り）", "line"),
            ("E-WATER", "上水（給水管・量水器 □）", "line"), ("E-SEWER", "汚水（○×は汚水桝）", "line")]
    cy = legend(sh, X, 276, rows)
    ly = 276 - 4.6 * 6
    sh.hatch_polys([Point(*sh.P(X + 6, ly)).buffer(0.6 * sh.S)], solid=True, color=6, layer="E-EXLT")
    sh.circle(sh.P(X + 6, ly - 4.6), 1.5 * sh.S, "A-SYMB")
    tab = [["番号", "名称", "寸法・数量", "詳細図"]] + [[str(i), it[0], it[1], it[2]] for i, it in enumerate(items, 1)]
    sh.text("番号表", (X, cy - 2), 3.0, "A-TEXT", paper=True)
    cy = sh.table(X, cy - 4, [9, 56, 48, 14], tab, row_h=4.4, h=1.8)
    notes = [("t", f"敷地面積 {sm['site_area']:,.2f}m²（推定）／建築面積 {sm['building_area']:.2f}m²／建ぺい率 {sm['coverage'] * 100:.2f}%（求積は A-01）"),
             ("t", "植栽・給排水の位置は仮置き（要確認）。引込位置・口径・公共管の深さは上下水道局との協議後に確定"),
             ("t", "門まわりの詳細は A-02D。雨水・止水は A-02、外構照明は E-03"),
             ("t", "がけ2H範囲の線上・内側に塀が入る区間のうち、東側の坂道沿いで道路との段差が2m超となる区間は擁壁兼用塀（令138条・工作物確認申請の対象となる可能性）"),
             ("t", "建物は1階切断（FL+1,100）。破線は屋根（パラペット）・連続庇の外形"),
             ("t", "敷地境界・道路縁・水路・隣接建物: 国土地理院 基盤地図情報／標高: DEM5A（TP m）")]
    side_panel(sh, X, cy - 4, notes, width=132)
    return sh


def security_sheet(h, number):
    """強盗（闇バイト型）対策: 手口ごとの評価と、敷地〜避難室までの防御の層。"""
    import security as SC
    sec = h.spec["security"]
    sh = frame(h, number, "防犯計画（強盗対策）", 500)
    t = fit(h, sh, (95, 150))
    site_base(h, sh, t, contours=False)
    fence_draw(h, sh, t)
    house_outline(h, sh, t)
    # 塀の内側のビームセンサー（塀から 0.6m 内側の破線）
    inner = h.fence_poly.buffer(-h.fence_t - 600, join_style=2)
    for p in iter_polygons(inner):
        sh.pline(t.pts(p.exterior.coords), "A-DRAIN")
    for x, y in sec["cameras"]:
        c = t(x, y)
        sh.rect(c[0] - 0.8 * sh.S, c[1] - 0.6 * sh.S, c[0] + 0.8 * sh.S, c[1] + 0.6 * sh.S, "A-FLOOD", lineweight=35)
    db = h.delivery_box
    sh.rect(*t(db[0], db[1]), *t(db[2], db[3]), "A-DOOR", lineweight=35)
    ic = t(sec["intercom_x"], h.y_gate - 300)
    sh.circle(ic, 0.6 * sh.S, "A-DOOR")
    sh.text("インターホン・宅配ボックス", t(sec["intercom_x"] + 3000, h.y_gate - 2600), 1.5, "A-TEXT", "MIDDLE_LEFT")
    for bx, by in h.bollards:
        sh.circle(t(bx, by), 0.4 * sh.S, "A-CUT")
    # 避難室
    r = [r_ for r_ in h.rooms if r_.name == sec["safe_room"]][0]
    sh.hatch_polys([sbox(*t(r.rect[0], r.rect[1]), *t(r.rect[2], r.rect[3]))], solid=True, color=1)
    sh.text("2階 避難室（WIC）", t(r.rect[2] + 1500, (r.rect[1] + r.rect[3]) / 2), 1.6, "A-LEGAL-TEXT", "MIDDLE_LEFT")
    sh.text("玄関（唯一の出入口・CP 防犯扉）", t(h.entrance.u1 + 4500, -1500), 1.5, "A-TEXT", "MIDDLE_LEFT")
    sh.north_arrow(sh.P(185, 60), 6, rot=h.facade_az)
    sh.view_title("防犯計画図", "1:500", (18, 22))
    legend(sh, 18, 46, [("A-FLOOD", "赤外線カメラ", "line"), ("A-DRAIN", "赤外線ビームセンサー（塀の内側）", "line"),
                        ("A-LEGAL-TEXT", "避難室", "line")])
    rows = [["層", "対策"]] + [list(r_) for r_ in SC.LAYERS]
    sh.text("(1) 防御の層 — 見せて諦めさせる → 入らせない → 時間をかけさせる → 知らせる → 逃げ込む", (200, 271), 2.6, "A-TEXT", paper=True)
    y = sh.table(200, 268, [22, 186], rows, row_h=5.0, h=1.8)
    rows = [["手口", "これまでの構成", "追加する対策", "判定"]] + [list(r_) for r_ in SC.THREATS]
    sh.text("(2) 手口ごとの評価（これまでの構成で十分か）", (200, y - 5), 2.6, "A-TEXT", paper=True)
    y = sh.table(200, y - 8, [38, 40, 112, 18], rows, row_h=5.0, h=1.55, pad=6.0)
    side_panel(sh, 200, y - 5, [("h", "住まい方（設備だけでは防げない部分）")] + [("t", o) for o in SC.OPERATION], width=208)
    return sh


def lifestyle_sheet(h, number):
    """Blueprint 型の暮らしへの対応: 寝室の換気（1部屋1人）、睡眠、水、日なたのプランター菜園。"""
    import lifestyle as LS
    ls, fm = h.spec["lifestyle"], h.spec["farm"]
    sh = frame(h, number, "暮らし方への対応（睡眠・空気・水・菜園）", 1, label="—")
    sh.text("暮らし方への対応 — 睡眠・空気・水・食（菜園）・運動・測定（寝室は1部屋に1人）", (12, 280), 3.6, "A-TEXT", paper=True)
    bv = LS.bedroom_ventilation(h)
    rows = [["寝室", "階", "容積", "基本換気 0.5回/h", "就寝中 CO2", "計画換気", "就寝中 CO2"]]
    for r in bv["rows"]:
        rows.append([r["name"], r["floor"], f"{r['V']:.0f}m³", f"{r['q0']:.0f}m³/h", f"{r['c_base']:,.0f}ppm",
                     f"{r['q']:.0f}m³/h（{r['ach']:.2f}回/h）", f"{r['c_plan']:,.0f}ppm"])
    sh.text(f"(1) 寝室の空気 — 就寝中の CO2 を {ls['co2_target']}ppm 以下に（1人 {ls['co2_sleep_m3h'] * 1000:.0f}L/h、外気 {ls['co2_outdoor']}ppm）", (12, 271), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, 268, [22, 10, 18, 30, 24, 42, 24], rows, row_h=5.0, h=1.9)
    side_panel(sh, 12, y - 4, [
        ("t", f"寝室ごとに CO2 センサーで換気量を自動で増やす（需要制御）。必要量は1人 約{bv['need']:.0f}m³/h。増える換気は合計 約{bv['dq']:.0f}m³/h で、"
              f"全熱交換で回収するため冷暖房の増加は年 約{bv['extra_kwh']:,.0f}kWh"),
        ("t", ls["filter"])], width=180)
    sp = [("睡眠", f"{ls['blackout']}。{ls['bedroom_setpoint']}。夜（{ls['night'][0]}〜{ls['night'][1]}時）は照明 2200K・10% 以下、寝室の Wi-Fi AP は表示灯を消し電波を止める"),
          ("水", ls["water"]),
          ("運動・測定", ls["measure"]),
          ("温冷浴", "サウナは設けない（施主判断）")]
    sh.text("(2) 睡眠・水・測定", (12, y - 26), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 29, [24, 158], [["項目", "計画"]] + [list(r) for r in sp], row_h=5.0, h=1.9, pad=6.0)
    # 菜園
    fs = LS.farm_sun(h)
    rows = [["場所", "面積", "直達日射の影損失（年）", "12月", "6月"],
            ["日なたのプランター菜園（建物の南）", f"植付 {fs['area']:.1f}m²", f"{fs['farm']['direct_loss'] * 100:.1f}%",
             f"{fs['farm']['by_month'][12] * 100:.0f}%", f"{fs['farm']['by_month'][6] * 100:.0f}%"],
            ["パーゴラの下（パネル被覆70%）", "—", f"約{fs['under_pergola'] * 100:.0f}%（半日陰）", "—", "—"]]
    sh.text("(3) 菜園 — 基本はプランター、日当たりで作物を分ける", (200, 271), 2.8, "A-TEXT", paper=True)
    y2 = sh.table(200, 268, [62, 26, 46, 22, 22], rows, row_h=5.0, h=1.9)
    y2 = sh.table(200, y2 - 4, [40, 138], [["場所", "向く作物（家庭菜園で育てられるもの）"]] + [list(r) for r in LS.CROPS], row_h=5.0, h=1.9, pad=6.0)
    # プランターの断面（模式図）
    sh.text("(4) プランターと床（模式図 1:20）— 床を傷めない置き方", (200, y2 - 6), 2.8, "A-TEXT", paper=True)
    k = 1 / 20.0
    for n, (x0p, title, slab) in enumerate(((210, "標準: Dotcon+ の上に脚付きプランター", False), (310, "将来: RC 土間（基礎）の上の農場", True))):
        by = y2 - 50

        def Q(x, z, x0p=x0p, by=by):
            return sh.P(x0p + x * k, by + z * k)
        base = sbox(*Q(0, -150), *Q(1500, 0))
        sh.hatch_polys([base], pattern="ANSI31" if slab else "NET", spacing=0.8, layer="A-PAVE")
        sh.rect(*Q(0, -150), *Q(1500, 0), "A-CUT", lineweight=35)
        for xl in (250, 1150):
            sh.rect(*Q(xl, 0), *Q(xl + 60, fm["leg"]), "A-VIS")
        sh.rect(*Q(200, fm["leg"]), *Q(1300, fm["leg"] + fm["planter_h"]), "A-VIS", lineweight=35)
        sh.rect(*Q(240, fm["leg"] + 60), *Q(1260, fm["leg"] + fm["planter_h"] - 80), "A-HIDDEN")
        sh.text(title, (x0p, by - 13), 2.0, "A-TEXT", paper=True)
        sh.text(f"脚で {fm['leg']}mm 浮かせる（土・水が床に触れない）", (x0p, by - 17), 1.7, "A-TEXT", paper=True)
        sh.text("Dotcon+（透水・水が溜まらない）" if not slab else "RC 土間 t150・勾配1/100・吸水防止材", (x0p, by - 21), 1.7, "A-TEXT", paper=True)
    side_panel(sh, 200, y2 - 80, [("h", "床（基礎）の劣化を抑える考え方"),
        ("t", "土・肥料・水を床に直接触れさせない（脚で浮かせ、受け皿は置かない）。コンクリートを傷めるのは、長く湿った状態と肥料の酸・塩分、根の侵入"),
        ("t", f"将来 RC 土間の上を農場にする場合: {fm['slab_option']}"),
        ("t", "受け皿・水たまりをつくらない（蚊の発生を防ぐ、E-03）。プランターは底から排水し、水は Dotcon+ に浸透させる"),
        ("t", "土は購入した培養土を使う（旧店舗跡地の土は検査するまで使わない）")], width=205)
    return sh


def seismic_sheet(h, number):
    import performance as PF
    se = PF.seismic(h)
    sh = frame(h, number, "耐震検討（壁式RC・概算）", 1, label="—")
    sh.text("耐震検討（壁式鉄筋コンクリート造・概算）— B案 構造グリッド 6.125 / 6.0 / 6.125", (12, 280), 3.6, "A-TEXT", paper=True)
    rows = [["項目", "値"],
            ["R階 重量 W2", f"{se['W2']:,.0f} kN"], ["2階 重量 W1", f"{se['W1']:,.0f} kN"],
            ["建物重量 ΣW", f"{se['Wt']:,.0f} kN（単位床面積あたり {se['w_unit']:.1f} kN/m²）"],
            ["固有周期 T", f"{se['T']:.3f} s（Rt=1.0、Z=1.0）"],
            ["2階の Ai", f"{se['A2']:.3f}（α={se['alpha2']:.3f}）"],
            ["短期許容せん断応力度 fs", f"{se['fs']:.2f} N/mm²（Fc24）"],
            ["接地圧（長期）", f"{se['bearing']:.1f} kN/m²（基礎面積 {se['base_area']:.0f}m²、許容150）"]]
    sh.text("(1) 地震力の算定", (12, 271), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, 268, [60, 110], rows, row_h=5.0, h=2.0)
    rows = [["階・方向", "壁長 m", "壁量 cm/m²", "Q (Co0.2) kN", "τ N/mm²", "余裕", "Q (等級3) kN", "τ", "余裕", "Qu/Qun", "偏心率"]]
    for (f, d), v in sorted(se["stories"].items()):
        a = v["建築基準法（Co=0.2）"]
        b = v["耐震等級3（Co=0.3）"]
        rows.append([f"{f} {d}", f"{v['Lw']:.1f}", f"{v['wall_rate']:.1f}", f"{a['Q']:,.0f}", f"{a['tau']:.3f}", f"{a['ratio']:.1f}",
                     f"{b['Q']:,.0f}", f"{b['tau']:.3f}", f"{b['ratio']:.1f}", f"{v['qu_ratio']:.1f}", f"{v['ecc']:.3f}"])
    sh.text("(2) 層せん断力と壁のせん断応力度", (12, y - 6), 2.8, "A-TEXT", paper=True)
    y = sh.table(12, y - 9, [22, 15, 19, 23, 17, 13, 23, 15, 13, 17, 17], rows, row_h=5.0, h=1.9)
    rows = [["区画（壁芯 m）", "短辺内法", "積載＋仕上", "必要厚", "計画"]]
    for x in se["slabs"]:
        rows.append([x["cell"] + ("（ジム）" if x["gym"] else ""), f"{x['lx'] / 1000:.2f}m", f"{x['wp']:.1f}kN/m²", f"{x['t_req']:.0f}mm", f"{h.slab_t}mm"])
    sh.text("(3) 床スラブ（日本建築学会 RC規準の床厚算定式）", (12, y - 6), 2.8, "A-TEXT", paper=True)
    sh.table(12, y - 9, [62, 20, 24, 20, 18], rows, row_h=4.8, h=1.9)
    notes = [("h", "評価"),
             ("t", "B案で中央スパンを5.0→6.0mにしても、耐力壁で囲まれた面積は最大37.5m²（告示上限60m²）、壁量は15.8〜19.1cm/m²（基準12）で、壁式構造の規定を満たす"),
             ("t", "地震力に対する壁のせん断応力度は、耐震等級3相当（Co=0.3）でも短期許容値の5倍以上の余裕がある。壁式RCは壁量が多く、地震に対して非常に強い構造である"),
             ("t", f"偏心率が最も大きいのは1階X方向（{PF.seismic(h)['stories'][('1F', 'X方向')]['ecc']:.3f}。Y方向{PF.seismic(h)['stories'][('1F', 'Y方向')]['ecc']:.3f}）。Y2通りのジムの開口（幅5.2m）で北側に剛性が偏るためで、0.15以下に収まる。開口上部の2階の壁は壁梁として設計する"),
             ("t", "床スラブ t=220 は全区画で必要厚を満たす。ジム床（積載5kN/m²）の必要厚は約193mm"),
             ("t", "接地圧は約42kN/m²で小さいが、河川近接のため地盤調査（液状化・地下水位）で基礎形式を確定する"),
             ("h", "前提・注意"),
             ("t", "地盤種別は第2種（Rt=1.0）を仮定。重量はモデルの躯体体積×24kN/m³＋仕上・積載。壁の終局せん断強度は2.0N/mm²、Ds=0.55 の目安で、構造計算（許容応力度計算ルート1）で確定する"),
             ("t", "耐震等級3を取得する場合は、品確法の評価（壁量・偏心・床倍率に相当する検討）を別途行う")]
    side_panel(sh, 205, 182, notes, width=195)
    return sh


# ================================================================ 歩行者専用道路 舗装要件（v4.22）
def donation_sheet(h, number):
    """A-02Y 歩行者専用道路 舗装要件（提案）A3 1枚: 舗装要件表＋帯の位置図（縮図 1:1000）＋手続きの流れ。
    市へ割譲する帯の法的扱い・最終の舗装仕様は八王子市との協議で決まる（提案・要確認）。"""
    d = h.spec["site"]["donation"]
    sh = frame(h, number, "歩行者専用道路 舗装要件（提案）", 1000, label="1:1000（位置図）")
    sh.text("歩行者専用道路 舗装要件（市への指定・協議事項の提案）", (15, 280), 3.4, "A-TEXT", paper=True)
    sh.text(f"{d['label']}　寄付地 約{h.donation_poly.area / 1e6:,.0f}m²（要確認）。帯の座標は赤線の概算（±0.7m）。", (15, 273), 2.0, "A-TEXT", paper=True)
    rows = [["項目", "提案値", "備考"]] + [list(r) for r in d["pave"]]
    cy = sh.table(15, 268, [27, 82, 70], rows, row_h=7.0, h=1.8)
    notes = [("t", "本表は提案であり、寄付（採納）か譲渡か、道路認定・区域変更、歩行者専用道路の指定の可否、舗装の最終仕様は八王子市の道路部局・建築指導課との協議で決まる（すべて要確認）。"),
             ("t", "採納されない場合は私道（施主所有のまま一般開放、または通路として敷地に戻す）とし、敷地面積を旧境界に戻す選択肢を残す。"),
             ("t", "塀・基礎・根固めは施主、舗装・側溝・照明・車止め・除草・清掃の区分は協定書で定める（要確認）。")]
    side_panel(sh, 15, cy - 5, notes, width=176)
    # ---- 位置図（縮図）
    x0, y0, x1, y1 = h.site_gross.bounds
    t = T(sh, ((x0 + x1) / 2, (y0 + y1) / 2), (320, 218))
    sh.text("位置図（帯の位置）", (268, 281), 2.8, "A-TEXT", paper=True)
    sh.pline(t.pts(h.gross_edges_pts), "A-DONATE-BND", closed=True)
    win = sbox(x0 - 4000, y0 - 4000, x1 + 4000, y1 + 4000)
    for r in h.road_edges:
        g = LineString(r["pts"]).intersection(win)
        for part in getattr(g, "geoms", [g]):
            if part.geom_type == "LineString" and not part.is_empty:
                sh.pline(t.pts(part.coords), "A-ROAD")
    donation_draw(h, sh, t, labels=False)
    sh.pline(t.pts(h.site_pts), "A-SITE", closed=True)
    fence_draw(h, sh, t)
    house_outline(h, sh, t, lw=25)
    for txt, (mx, my) in (("北の歩道・水路", (-2000, 33500)), ("東側道路", (36000, 12000)), ("南側道路", (4000, -49000))):
        sh.text(txt, t(mx, my), 1.8, "A-TEXT", "MIDDLE_CENTER")
    sh.text("斜め格子: 寄付地（帯）／破線: 寄付地境界（旧敷地境界）／二点鎖線: 新敷地境界", (268, 177), 1.7, "A-TEXT", paper=True)
    sh.text("北東角 幅約6.6m（楔形）・東辺 幅2.36〜2.61m・南東角で幅0。北端は北の歩道と、東端は東側道路と接続", (268, 173), 1.7, "A-TEXT", paper=True)
    sh.north_arrow(sh.P(386, 268), 5, rot=h.facade_az)
    # ---- 手続きの流れ（すべて要確認）
    sh.text("手続きの流れ（想定・すべて要確認）", (268, 160), 2.8, "A-TEXT", paper=True)
    steps = ["事前協議: 八王子市の道路部局・建築指導課（開発許可の対象か、寄付採納の受入基準）",
             "境界確定測量: 隣地・水路管理者・道路管理者の立会い",
             "分筆登記（地積測量図）: 帯を別筆にする",
             "寄付採納（または譲渡）: 道路認定・区域変更・歩行者専用道路の指定の可否",
             "所有権移転登記・固定資産税の扱い（公衆用道路の非課税申告）",
             "協定書: 舗装要件・維持管理区分・照明の管理者・鍵の管理"]
    y = 156
    for i, s_ in enumerate(steps, 1):
        sh.rect(*sh.P(268, y - 9), *sh.P(405, y), "G-TABLE")
        sh.circle(sh.P(274, y - 4.5), 2.6 * sh.S, "A-SYMB")
        sh.text(str(i), (274, y - 4.5), 2.2, "A-SYMB", "MIDDLE_CENTER", paper=True)
        for k, line in enumerate(_wrap(s_, 120, 2.0)):
            sh.text(line, (280, y - 3.2 - k * 3.4), 2.0, "A-TEXT", paper=True)
        if i < len(steps):
            sh.line(sh.P(274, y - 9), sh.P(274, y - 12), "A-SYMB")
            sh.line(sh.P(274, y - 12), sh.P(273, y - 10.6), "A-SYMB")
            sh.line(sh.P(274, y - 12), sh.P(275, y - 10.6), "A-SYMB")
        y -= 12
    return sh


# ================================================================ v4.23 ライフライン別紙（A-02Z・A-02Z2）
def _leader(sh, t, target, pos, text, layer="A-TEXT", h_=1.6, align="MIDDLE_LEFT"):
    """引出し線＋文字。target・pos はモデル座標 mm。"""
    sh.line(t(*target), t(*pos), "A-SYMB", lineweight=9)
    sh.text(text, t(*pos), h_, layer, align)


def _section_box(sh, x, y, w, hh, title, items, notes):
    """管路断面の模式図（縮尺なし）。用紙 mm の左上 (x, y)。items: (名称, 地表からの深さ m, 左端からの位置 0〜1, 径 mm, layer)。"""
    sh.text(title, (x, y), 2.0, "A-TEXT", paper=True)
    top = y - 4
    sh.rect(*sh.P(x, top - hh), *sh.P(x + w, top), "G-TABLE")
    gl = top - 6
    sh.line(sh.P(x, gl), sh.P(x + w, gl), "A-GROUND")
    sh.text("GL±0", (x + 1, gl + 1.2), 1.3, "A-TEXT", paper=True)
    k = 20.0                                           # 1m あたり用紙 mm（模式）
    for name, d, fx, dia, lay in items:
        cx, cy = x + fx * w, gl - d * k
        sh.circle(sh.P(cx, cy), max(dia, 50) / 1000 * k / 2 * sh.S * 1.0 + 0.6 * sh.S, lay)
        sh.text(name, (cx, cy - 3.2), 1.3, "A-TEXT", "MIDDLE_CENTER", paper=True)
        sh.text(f"-{d:.2f}", (cx, cy + 2.4), 1.2, "A-TEXT", "MIDDLE_CENTER", paper=True)
    cy = top - hh - 3
    for n in notes:
        sh.text(n, (x, cy), 1.4, "A-TEXT", paper=True)
        cy -= 2.8
    return cy


def lifeline_sheet(h, number):
    """A-02Z ライフライン配置・経路図（A3 横・1:300）。引込点・経路・HH・盤・PCS・上下水・雨水・予約ゾーン・蓄電室・寄付地。
    すべて新しい境界の内側に置き、東・北の寄付地には何も入れない。位置・深さはすべて仮置き（要確認）。"""
    ll = h.spec["lifeline"]
    pw = ll["power"]
    sh = frame(h, number, "ライフライン配置・経路図", 300)
    t = fit(h, sh, (131, 165))
    site_base(h, sh, t, contours=False, margin=3000, roads=True, margin_top=4500, road_avoid=(14, 266, 112, 288), donation=True)
    fence_draw(h, sh, t)
    house_outline(h, sh, t)
    bx0, by0, bx1, by1 = h.battery_room.rect
    sh.hatch_polys([sbox(*t(bx0, by0), *t(bx1, by1))], solid=True, color=1, layer="E-BATT")
    pg, cp = h.pergola, h.carport
    sh.rect(*t(pg[0], pg[1]), *t(pg[2], pg[3]), "A-VIS")
    sh.rect(*t(cp[0], cp[1]), *t(cp[2], cp[3]), "A-VIS")
    sh.text("ソーラーパーゴラ 27kWp", t((pg[0] + pg[2]) / 2, pg[3] - 1300), 1.6, "A-TEXT", "MIDDLE_CENTER")
    sh.text("ソーラーカーポート", t((cp[0] + cp[2]) / 2, cp[3] + 800), 1.5, "A-TEXT", "MIDDLE_CENTER")
    _integrated_cliff(h, sh, t)
    _utilities_draw(h, sh, t)
    tk = h.tank
    sh.rect(*t(tk[0], tk[1]), *t(tk[2], tk[3]), "A-DRAIN")
    sh.line(t(tk[0], tk[1]), t(tk[2], tk[3]), "A-DRAIN")
    sh.text("雨水貯留槽 25m³（密閉・防虫網0.4mm・フラップ弁）", t((tk[0] + tk[2]) / 2, tk[3] + 1100), 1.4, "A-TEXT", "MIDDLE_CENTER")
    _reserve_draw(h, sh, t, foundations=True)
    # ---- 電力・通信・PV
    sh.pline(t.pts(pw["trunk"]), "E-POWER", lineweight=35)
    sh.pline(t.pts(ll["comm"]["line"]), "E-COMM", lineweight=25)
    sh.pline(t.pts(pw["pv_pergola"]), "E-PV", lineweight=35)
    sh.pline(t.pts(pw["pv_reserve_spare"]), "E-SPARE", lineweight=25)
    sh.line(t(*pw["entry"]), t(pw["trunk"][0][0], pw["trunk"][0][1]), "E-POWER", lineweight=35)
    for p in pw["hh"] + [pw["pv_reserve_hh"]]:
        sh.rect(*t(p[0] - 450, p[1] - 450), *t(p[0] + 450, p[1] + 450), "E-POWER", lineweight=35)
    sw = pw["switchboard"]
    sh.rect(*t(sw[0], sw[1] - 250), *t(sw[2], sw[1] + 250), "E-POWER", lineweight=50)
    for nm in ("pergola", "carport"):
        x, y = pw["pcs"][nm]
        sh.rect(*t(x - 400, y - 400), *t(x + 400, y + 400), "E-PV", lineweight=35)
    for key in ("main", "essential"):
        x, y = pw["panels"][key]
        sh.rect(*t(x - 350, y - 125), *t(x + 350, y + 125), "E-POWER", lineweight=35)
    x, y = pw["pcs"]["battery"]
    sh.rect(*t(x - 300, y - 250), *t(x + 300, y + 250), "E-PV", lineweight=35)
    # ---- 番号引出し（番号表は右欄）
    S = sh.S
    call = [("電力・通信 地中引込点（南側道路の電柱から。電柱位置は要確認）", (15500, -31589), (17700, -31000)),
            ("引込開閉器盤＋電力量計（門の塀に組込む・下端 FGL+1,200 以上・外面を門前広場へ）", (15500, -27589), (16900, -25800)),
            ("幹線 PE φ65×2（1本予備）＋通信 別管 φ50×2。駐車場区画1の下を北へ", (14200, -22000), (15900, -22000)),
            ("HH ハンドホール（曲がり・約30m ごと）", (14200, -14000), (15800, -14000)),
            ("建物南面で基礎スリーブ（止水）→ 床下ピット → 機械室（東）", (14200, -245), (15600, -1800)),
            ("PCS（カーポートの柱）", (13000, -19400), (13000, -21200)),
            ("主分電盤・特定負荷分電盤（機械室・東）", (16500, 9175), (19500, 10500)),
            ("蓄電室 200kWh 級・蓄電 PCS（双方向、AC 結合）", (17100, 7600), (19500, 7600)),
            ("PCS（パーゴラ東端・屋外）", (-9000, 15000), (-7000, 13500)),
            ("PV AC 配線 → 西面スリーブ。雨水管と交差（上下 0.3m）", (-4000, 16000), (-2800, 17500)),
            ("HH（予約ゾーン）と予備管路 PE φ65×2 → パーゴラの溝へ合流", (-9500, 9000), (-8000, 8000)),
            ("量水器（上水 φ25・門前広場）", (13000, -30900), (13200, -33000)),
            ("汚水最終桝（φ150・1/100、1.5/100 を推奨・要確認）", (9900, -30900), (9400, -33000)),
            ("雨水最終桝（汚水と別桝・分流式と仮定）", (11300, -30900), (11300, -33000)),
            ("雨水貯留槽 25m³（パーゴラの下・密閉・防虫）。越流 → 西の浸透桝2基", ((h.tank[0] + h.tank[2]) / 2, h.tank[1]), ((h.tank[0] + h.tank[2]) / 2, h.tank[1] - 2200))]
    for i, (txt, tg, bp) in enumerate(call, 1):
        sh.line(t(*tg), t(*bp), "A-SYMB", lineweight=9)
        sh.circle(t(*bp), 1.5 * S, "A-SYMB")
        sh.text(str(i), t(*bp), 1.5, "A-SYMB", "MIDDLE_CENTER")
    sh.text("ガス引込なし（オール電化）", t(5000, -25000), 1.6, "A-TEXT", "MIDDLE_CENTER")
    sh.north_arrow(sh.P(370, 120), 6, rot=h.facade_az)
    sh.view_title("ライフライン配置・経路図", "1:300", (18, 280))
    # ---- 右欄: 凡例・管路断面・注記
    X = 262
    sh.text("凡例", (X, 280), 3.0, "A-TEXT", paper=True)
    rows = [("E-POWER", "電力 引込・幹線（地中管路）", "line"), ("E-COMM", "通信 引込（光・別管）", "line"),
            ("E-PV", "太陽光 AC 配線・PCS", "line"), ("E-SPARE", "予備管路（予約ゾーン→パーゴラ）", "line"),
            ("E-WATER", "上水", "line"), ("E-SEWER", "汚水", "line"), ("A-DRAIN", "雨水（貯留槽・浸透桝）", "line"),
            ("A-PVRES", "将来ソーラー予約ゾーン・基礎候補 □", "line"), ("E-BATT", "蓄電室（1階）", "line"),
            ("A-DONATE", "寄付地（設備なし）", "don"), ("A-LEGAL", "がけ条例 2H 範囲", "line"),
            ("A-SITE", "敷地境界（新・塀の外面）", "line")]
    cy = legend(sh, X, 276, rows)
    sh.text("管路断面（模式・縮尺なし）", (X, cy - 1), 2.2, "A-TEXT", paper=True)
    cy -= 6
    cy = _section_box(sh, X, cy, 64, 30, "① 門前（x=14,200）",
                      [("電力φ65×2", 0.6, 0.30, 65, "E-POWER"), ("通信φ50×2", 0.6, 0.50, 50, "E-COMM"), ("上水φ25", 0.45, 0.88, 25, "E-WATER")],
                      ["電力と通信 水平 0.3m（同溝・別管）", "上水まで 1.6m"])
    cy -= 2
    cy = _section_box(sh, X, cy, 64, 30, "② 駐車場下（Dotcon+ 路盤の下）",
                      [("電力φ65×2", 0.6, 0.35, 65, "E-POWER"), ("通信φ50×2", 0.6, 0.65, 50, "E-COMM")],
                      ["重量物の圧力を受ける場所は 0.6m 以上（管路式・要確認）"])
    cy -= 2
    cy = _section_box(sh, X, cy, 64, 30, "③ 西の庭（雨水管との交差）",
                      [("PV電力", 0.6, 0.30, 65, "E-PV"), ("雨水φ150", 0.9, 0.70, 150, "A-DRAIN")],
                      ["交差は上下 0.3m 以上（要確認）"])
    sh.text("番号表", (332, 280), 3.0, "A-TEXT", paper=True)
    sh.table(332, 276, [8, 66], [["番号", "内容（位置・深さは仮置き・要確認）"]] + [[str(i), c[0]] for i, c in enumerate(call, 1)], row_h=4.4, h=1.7)
    return sh


LIFELINE_STANDARDS = [
    ["項目", "代表値", "出典", "計画"],
    ["地中電線 埋設深さ（直接埋設）", "重量物の圧力を受ける場所 1.2m、その他 0.6m", "電気設備技術基準の解釈 第120条（改正の有無 要確認）", "管路式とし、駐車場下 0.6m 以上・その他 0.3m 以上（管路式の値は要確認）。安全側に一律 0.6m"],
    ["地中電線と弱電流電線の離隔", "低圧・高圧 0.3m", "電技解釈 第125条（要確認）", "0.3m（同溝・別管）"],
    ["地中電線と水道管・下水管", "規定値は要確認。内線規程の推奨 0.3m 程度（推定）", "内線規程（要確認）", "水平 0.3m 以上、交差は上下 0.3m"],
    ["給水管の土被り（宅地内）", "0.3m 以上（車両部 0.6m、推定）", "東京都水道局 給水装置工事設計施工指針（八王子市域は都水道。要確認）", "0.45m（凍結深 約0.2〜0.3m 推定）"],
    ["量水器の位置", "宅地内・道路境界の近く・検針と交換が容易", "同上（要確認）", "境界から0.69m"],
    ["排水管 勾配", "1/100 以上（やむを得ない場合を除く）", "下水道法施行令 第8条", "汚水 φ150 1/100 → 1.5/100 を推奨（排水設備指針の一般値、要確認）。最終桝の管底 GL-700 → 約GL-980"],
    ["排水管 最小管径", "汚水 100mm 以上（排水人口による）", "施行令 第8条（要確認）", "φ150"],
    ["桝の間隔", "管内径の120倍以下（φ150 で18m）、起点・曲がり・合流に設置", "施行令 第8条", "最大 13.7m（適合）"],
    ["汚水桝と雨水桝", "法定値なし（推定: 1.0m 以上・別系統）", "市の排水設備基準（要確認）", "1.4m"],
    ["最終桝", "境界から1m 以内（推定）", "八王子市 排水設備（要確認）", "0.69m"],
    ["系統連系", "低圧連系は 50kW 未満", "電技解釈 第8章（分散型電源）・系統連系規程 JEAC 9701", "拡張後は PCS 合計を 49.5kW 以下に制限（パネル過積載）。電気事業法の区分（小規模事業用電気工作物の届出・使用前自己確認、50kW 以上は自家用）は要確認"],
    ["蓄電池の届出・離隔", "定格 10kWh 超で届出・位置構造基準（従前 4,800Ah・セル）。20kWh 超で不燃区画等の可能性", "対象火気省令（令和5年改正）・東京都火災予防条例（閾値・条番号とも要確認）", "200kWh 級 → 所轄消防署（八王子消防署）と事前協議"],
    ["蓄電池（建築基準法）", "建築設備（法2条3号）。専用の離隔規定は見当たらない（要確認）", "—", "1時間耐火の区画を自主設定"],
    ["排煙の予備電源", "30分以上", "令126条の3（告示の適合は要確認）", "特定負荷に排煙機"],
]


def _flow_box(sh, x, y, w, hh, text, layer="G-TABLE", dashed=False):
    sh.rect(*sh.P(x, y - hh), *sh.P(x + w, y), "A-HIDDEN" if dashed else layer, lineweight=25)
    lines = _wrap(text, w - 2, 1.6)
    y0 = y - hh / 2 + (len(lines) - 1) * 1.4
    for k, ln in enumerate(lines):
        sh.text(ln, (x + w / 2, y0 - k * 2.8), 1.6, "A-TEXT", "MIDDLE_CENTER", paper=True)


def _flow_line(sh, pts, layer="E-POWER", arrow=True):
    sh.pline([sh.P(*p) for p in pts], layer, lineweight=25)
    if arrow:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        d = math.hypot(x1 - x0, y1 - y0) or 1
        ux, uy = (x1 - x0) / d, (y1 - y0) / d
        for sg in (1, -1):
            sh.line(sh.P(x1, y1), sh.P(x1 - 1.6 * ux - sg * 0.8 * uy, y1 - 1.6 * uy + sg * 0.8 * ux), layer)


def lifeline_tables(h, number):
    """A-02Z2 ライフラインの基準表（法定基準・代表値・計画）・電気の系統図（単線結線の簡略）・蓄電容量表・要確認。
    条項は確信のあるものだけ。他は「要確認」「推定」と明記する。"""
    en = PF.energy(h, PF.heat_load(h))
    bs = PF.battery_sizing(h, en)
    sh = frame(h, number, "ライフライン基準表・系統図", 1, label="—")
    sh.text("ライフライン 法定基準・代表値と計画（条項は確信のあるものだけ。他は要確認・推定）", (12, 282), 3.0, "A-TEXT", paper=True)
    y = sh.table(12, 277, [32, 50, 50, 68], LIFELINE_STANDARDS, row_h=5.0, h=1.7)
    side_panel(sh, 12, y - 5, [("t", "代表値は一般的な値の記憶によるもので、最新の条文・自治体の指針・事業者の約款で確認する（すべて要確認）。電柱・公共桝・配水管の位置と深さ、分流式かどうかも未確認。")], width=200)
    # ---- 系統図
    X0 = 228
    sh.text("電気の系統図（単線結線の簡略）", (X0, 282), 3.0, "A-TEXT", paper=True)
    W, H_ = 38, 9
    cx = [X0, X0 + 45, X0 + 90, X0 + 135]
    r1, r2, r3 = 276, 259, 242
    _flow_box(sh, cx[0], r1, W, H_, "配電線（南側道路・地中引込）")
    _flow_box(sh, cx[1], r1, W, H_, "引込開閉器盤＋電力量計（門の塀）")
    _flow_box(sh, cx[2], r1, W, H_, "主分電盤（機械室・東）")
    _flow_box(sh, cx[3], r1, W, H_, "一般負荷（照明・空調・IH ほか）")
    _flow_line(sh, [(cx[0] + W, r1 - 4.5), (cx[1], r1 - 4.5)])
    _flow_line(sh, [(cx[1] + W, r1 - 4.5), (cx[2], r1 - 4.5)])
    _flow_line(sh, [(cx[2] + W, r1 - 4.5), (cx[3], r1 - 4.5)])
    _flow_box(sh, cx[2], r2, W, H_, "蓄電 PCS（双方向・AC 結合）", "E-BATT")
    _flow_box(sh, cx[3], r2, W, H_, "蓄電池 200kWh 級（LFP・蓄電室）", "E-BATT")
    _flow_line(sh, [(cx[2] + W / 2, r1 - H_), (cx[2] + W / 2, r2)])
    _flow_line(sh, [(cx[2] + W, r2 - 4.5), (cx[3], r2 - 4.5)], "E-BATT")
    _flow_box(sh, cx[2], r3, W, H_, "特定負荷分電盤（機械室・東）")
    _flow_box(sh, cx[3], r3, W, H_, "特定負荷: 排煙機・排水ポンプ・冷蔵庫・通信警備・照明・HP空調1系統・給湯・IH1口")
    _flow_line(sh, [(cx[2] + W / 2, r2 - H_), (cx[2] + W / 2, r3)])
    _flow_line(sh, [(cx[2] + W, r3 - 4.5), (cx[3], r3 - 4.5)])
    _flow_box(sh, cx[0], r2, W, H_, "PCS パーゴラ 27.1kWp（屋外・AC 連系）", "E-PV")
    _flow_box(sh, cx[1], r2, W, H_, "PCS カーポート 10.2kWp（柱）", "E-PV")
    _flow_box(sh, cx[0], r3, W, H_, "予約ゾーン 41.0kWp（将来・PCS 追加。合計 49.5kW 以下）", "E-PV", dashed=True)
    bus = r1 - H_ - 4
    _flow_line(sh, [(cx[0] + W / 2, r2), (cx[0] + W / 2, bus), (cx[2] + W / 2, bus)], "E-PV", arrow=False)
    _flow_line(sh, [(cx[1] + W / 2, r2), (cx[1] + W / 2, bus)], "E-PV", arrow=False)
    _flow_line(sh, [(cx[0] + W / 2, r3), (cx[0] + W / 2, r2 - H_)], "E-SPARE", arrow=False)
    sh.text("商用停電時は蓄電 PCS が自立出力に切り替え、特定負荷だけに給電。PV は日中の充電・給電に連系", (X0, r3 - H_ - 4), 1.6, "A-TEXT", paper=True)
    # ---- 蓄電容量表
    yy = r3 - H_ - 11
    sh.text("蓄電容量（7日分・公称 = 必要値 ÷ (DoD 0.9 × 寿命末期 SOH 0.8 × 効率 0.95 = %.3f)）" % bs["factor"], (X0, yy), 2.2, "A-TEXT", paper=True)
    rows = [["ケース", "kWh/日", "7日 使用可能量", "公称容量", "面積（推定）", "重量（推定）"]]
    for k in "ABCD":
        r = bs["rows"][k]
        rows.append([f"{k} {r['name']}", f"{r['kwh']:.1f}", f"{r['use']:.0f}kWh", f"{r['nominal']:.0f}kWh", f"{r['area']:.1f}m²", f"{r['tons']:.1f}t"])
    yy = sh.table(X0, yy - 3, [50, 16, 28, 22, 24, 24], rows, row_h=4.6, h=1.7)
    a = bs["autonomy"]
    fmt = lambda v: "収支プラス" if v is None else f"約{v:.1f}日"
    notes = [("t", f"推奨: 公称 200kWh 級（防災モード C）。日射ゼロ・寿命末期で {bs['days_eol']:.1f}日（新品 {bs['days_new']:.1f}日、排煙・ポンプ 6.1kWh 控除後 {bs['days_eol_net']:.1f}日）。A・B は室が12〜18m²・7〜10t になり南半分に入らない。"),
             ("t", f"12月に太陽光で毎日充電する場合（日射は年の5.5%・曇天は平均の20%、推定）。防災モード: 現状 平均日 {fmt(a[('C', 'now')]['avg'])}・曇天 {fmt(a[('C', 'now')]['cloudy'])}、拡張後 曇天でも{fmt(a[('C', 'ext')]['cloudy'])}。通常の冬: 現状 平均日 {fmt(a[('B', 'now')]['avg'])}・曇天 {fmt(a[('B', 'now')]['cloudy'])}、拡張後 平均日 {fmt(a[('B', 'ext')]['avg'])}・曇天 {fmt(a[('B', 'ext')]['cloudy'])}。")]
    yy = side_panel(sh, X0, yy - 4, notes, width=176)
    sh.text("要確認（追加）", (X0, yy - 1), 2.4, "A-TEXT", paper=True)
    chk = ["1 南側道路の電柱・通信柱・公共汚水/雨水桝・配水管の位置と深さ、分流式か", "2 地中電線の埋設深さ（電技解釈120条の改正）と離隔", "3 東京都水道局の土被り・量水器位置",
           "4 排水管 φ150 の勾配（1/100 か 1.5/100）", "5 蓄電池の火災予防条例上の閾値・届出・区画（八王子消防署）", "6 電気事業法の区分と低圧連系の上限（PCS 49.5kW 制限）",
           "7 地上置きパネルの建築物該当性", "8 蓄電室の束壁と S-03 の偏心率", "9 ジム機器の移動の了承（施主）", "10 現地の浸透試験（雨水貯留槽の要否）"]
    side_panel(sh, X0, yy - 6, [("t", "　".join(chk))], width=176)
    return sh
