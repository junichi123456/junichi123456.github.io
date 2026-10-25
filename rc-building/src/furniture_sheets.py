"""内装の図面 I-03（1階家具配置図）・I-04（2階家具配置図）・I-05（家具表・内装色彩計画）。

家具は仮置き（後日差し替え）。指定商品2点の寸法は仮定（商品ページ未確認）。A-03・A-04 には家具を描き足さない。
"""
from __future__ import annotations

import math

from shapely.geometry import Polygon, box as sbox

import furniture as FU
import furniture_shapes as FS
from house_sheets import _hex_rgb, frame, grid, plan_dims, room_labels, sbox_, stair_marks, tp
from sheetlib import T, door_symbol, emit, opening_tag, side_panel, window_symbol
from views import project

NOTE = ("家具は仮置き（後日差し替え）。指定商品（OSB テーブル・スクールチェア）の寸法は仮定（商品ページ未確認）。"
        "チェアは LDK の1脚のみ。色はいずれも仮定")


def _plan_base(h, floor, sh, t):
    """A-03・A-04 と同じ壁・通り芯・建具・階段（家具を描き足す下地）。"""
    fl = h.fl[floor]
    cut = fl + 1100
    zmin = fl - 1 if floor == "1F" else fl - h.H["1F"] / 2 - 1
    proj = project(h.boxes, "plan", cut=-cut, depth_limit=-zmin if floor == "2F" else -(h.fgl - 1),
                   filt=lambda b: not ((b.cat in ("glass", "door") and b.z0 < cut < b.z1)
                                       or (b.cat == "stair" and b.level != "EXT" and b.z1 > cut)))
    emit(sh, proj, t)
    grid(h, sh, t)
    plan_dims(h, sh, t, floor)
    for w in h.walls:
        if w.cat == "insul":
            continue
        for op in w.openings:
            if op.floor == floor and op.kind == "window" and op.z0 >= cut:
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


def _id_text(sh, t, it, dy=0.0):
    x0, y0, x1, y1 = it.rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vert = (y1 - y0) > (x1 - x0) * 1.6
    small = min(x1 - x0, y1 - y0) < 450 and max(x1 - x0, y1 - y0) < 900
    if small:                                   # 小さいものは外側に出す
        sh.text(it.id, t(x1 + 60, cy + dy), 1.3, "A-FURN", "MIDDLE_LEFT")
    else:
        sh.text(it.id, t(cx, cy + dy), 1.4, "A-FURN", "MIDDLE_CENTER", rot=90 if vert else 0)


def draw_item(sh, t, it, h):
    """家具 1 点の平面記号（A-FURN、細線）。"""
    x0, y0, x1, y1 = it.rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    L = "A-FURN"
    k = it.kind
    if k == "plant":
        sh.circle(t(cx, cy), (x1 - x0) / 2, L)
        sh.circle(t(cx, cy), (x1 - x0) / 5, L)
        _id_text(sh, t, it)
        return
    if k == "school_chair":
        poly = it.poly()
        pts = [t(x, y) for x, y in list(poly.exterior.coords)[:-1]]
        sh.hatch_polys([Polygon(pts)], layer=L, solid=True, color=8)
        sh.pline(pts, L, closed=True)
        # 背（後ろ辺）を太線で
        back = sbox(x0, y1 - 40, x1, y1)
        from shapely.affinity import rotate as sr
        back = sr(back, it.rot, origin=poly.centroid)
        sh.pline([t(x, y) for x, y in list(back.exterior.coords)[:-1]], L, closed=True, lineweight=35)
        return
    if k == "table_osb":
        sh.rect(*t(x0, y0), *t(x1, y1), L)
        prod = h.spec["furniture"]["products"]["table_osb"]
        a = prod["leg_pipe"]
        inset = prod["leg_inset"]
        for xs in (x0 + inset, x1 - inset - a):             # ロの字脚の位置（破線）
            sh.rect(*t(xs, y0 + 50), *t(xs + a, y1 - 50), "A-HIDDEN")
        sh.text(it.id, t(cx, cy + 120), 1.5, L, "MIDDLE_CENTER")
        sh.text("OSB テーブル W1,775×D850（仮置き・寸法は仮定）", t(cx, cy - 130), 1.2, L, "MIDDLE_CENTER")
        return
    sh.rect(*t(x0, y0), *t(x1, y1), L)
    if k in ("tall", "tall_kitchen", "bookcase") or (k == "cabinet" and it.h > 800):
        sh.line(t(x0, y0), t(x1, y1), L)                       # 収納は対角線
    elif k == "bed":
        head = it.head
        if head in ("+y", "-y"):
            yy = y1 - 300 if head == "+y" else y0 + 300
            n = 2 if (x1 - x0) > 1100 else 1
            for i in range(n):
                xa = x0 + 100 + i * (x1 - x0 - 200) / n
                sh.rect(*t(xa + 20, min(yy, yy + (260 if head == "-y" else -260))), *t(xa + (x1 - x0 - 200) / n - 20, max(yy, yy + (260 if head == "-y" else -260))), L)
            sh.line(t(x0, yy + (-300 if head == "+y" else 300) * 0 + (320 if head == "-y" else -320)), t(x1, yy + (320 if head == "-y" else -320)), L)
        else:
            xx = x0 + 300 if head == "-x" else x1 - 300
            n = 2 if (y1 - y0) > 1100 else 1
            for i in range(n):
                ya = y0 + 100 + i * (y1 - y0 - 200) / n
                sh.rect(*t(xx - 130, ya + 20), *t(xx + 130, ya + (y1 - y0 - 200) / n - 20), L)
    elif k == "toilet":
        sh.circle(t(cx, y0 + 260), 180, L)
        sh.rect(*t(cx - 200, y1 - 200), *t(cx + 200, y1), L)
    elif k == "washer2":
        for i in range(2):
            sh.circle(t(x0 + 320 + i * 650, (y0 + y1) / 2), 170, L)
    elif k == "counter_float":
        w_, d_ = x1 - x0, y1 - y0
        sh.rect(*t(x0 + w_ * 0.2, y0 + d_ * 0.2), *t(x1 - w_ * 0.2, y1 - d_ * 0.2), L)
    elif k == "island":
        sh.rect(*t(x1 - 1000, y0 + 250), *t(x1 - 300, y0 + 770), L)                    # IH
        sh.rect(*t(x0 + 450, y0 + 330), *t(x0 + 1250, y0 + 780), L)                     # シンク
        sh.rect(*t(x0 + 1300, y0 + 60), *t(x0 + 1900, y1), "A-HIDDEN")                  # 調理側（北）のオープン棚
    elif k == "sofa":
        sh.rect(*t(x0 + 180, y0), *t(x1 - 180, y1 - 200), L)
        for i in (1, 2):
            sh.line(t(x0 + 180 + (x1 - x0 - 360) * i / 3, y0), t(x0 + 180 + (x1 - x0 - 360) * i / 3, y1 - 200), L)
    elif k == "hang_pole":
        sh.line(t(x0, y0), t(x1, y0), "A-HIDDEN")
        sh.line(t(x0, y1), t(x1, y1), "A-HIDDEN")
    elif k in ("kb_counter", "pantry_open"):
        sh.line(t(x0, y0), t(x1, y0 + (y1 - y0) * 0.0 + 0), "A-HIDDEN")                 # 下部・棚はオープン（対角線なし）
    elif k == "bench":
        sh.line(t(x0, y0), t(x1, y1), L)
    elif k in ("dock",):
        sh.line(t(x0, y0), t(x1, y1), L)
    if k != "hang_pole":
        _id_text(sh, t, it)
    else:
        sh.text(it.id, t(x0 - 150, (y0 + y1) / 2), 1.3, L, "MIDDLE_RIGHT")


def furniture_plan(h, floor, number):
    names = {"1F": "1階 家具配置図（仮置き）", "2F": "2階 家具配置図（仮置き）"}
    sh = frame(h, number, names[floor], 100)
    t = T(sh, (0, 0), (52, 73))
    fl = h.fl[floor]
    its = [i for i in FU.items(h) if i.floor == floor]
    _plan_base(h, floor, sh, t)
    room_labels(h, sh, t, floor, hgt=2.2)
    # ダウンライト（○ φ1.5mm）
    for d in FU.downlights(h, FU.items(h)):
        if d["floor"] == floor:
            sh.circle(t(d["p"][0], d["p"][1]), 0.75 * sh.S, "E-LITE")
    import lighting as LG
    for l in LG.lines(h, FU.items(h)):
        if l["floor"] == floor:
            sh.pline([t(l["p0"][0], l["p0"][1]), t(l["p1"][0], l["p1"][1])], "E-LINE", lineweight=50)
    if floor == "1F":
        for f in LG.footlights(h):
            c = t(f["p"][0], f["p"][1])
            sh.pline([(c[0] - 0.8 * sh.S, c[1] + 0.8 * sh.S), (c[0] + 0.8 * sh.S, c[1] + 0.8 * sh.S), (c[0], c[1] - 0.8 * sh.S)], "E-FOOT", closed=True)
    # 家具
    for it in its:
        draw_item(sh, t, it, h)
    if floor == "1F":
        for name, r, hh, kg in h.equipment:
            sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "A-VIS", lineweight=25)
            vert = (r[3] - r[1]) > (r[2] - r[0]) * 1.3
            sh.text(name, t((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), 1.2, "A-TEXT", "MIDDLE_CENTER", rot=90 if vert else 0)
        z = h.treadmill_zone
        sh.rect(*t(z[0], z[1]), *t(z[2], z[3]), "A-HIDDEN")
        # 縦手すり
        sh.circle(t(11943, 1898), 17.5, "A-FURN")
        sh.text("縦手すり φ35", t(11850, 1898), 1.2, "A-TEXT", "MIDDLE_RIGHT")
    # チェアの注記（引出線）
    ch = next((i for i in its if i.chair), None)
    if ch:
        x0, y0, x1, y1 = ch.rect
        p = t((x0 + x1) / 2 + 150, (y0 + y1) / 2)
        q = (p[0] + 5 * sh.S, p[1] + 4 * sh.S)
        sh.line(p, q, "A-SYMB")
        sh.text("チェア（この1脚のみ）スクールチェア 仮置き", (q[0] + 0.5 * sh.S, q[1]), 1.7, "A-TEXT", "MIDDLE_LEFT")
    # 座る家具・提案の注記
    for it in its:
        if it.note:
            x0, y0, x1, y1 = it.rect
            sh.text("要施主確認", t((x0 + x1) / 2, y0 - 120), 1.3, "A-TEXT", "TOP_CENTER") if it.id != "LB-B1" else \
                sh.text("要施主確認", t(x1 + 80, y0 + 300), 1.3, "A-TEXT", "MIDDLE_LEFT")
    if floor == "2F":
        sh.text("主寝室 北窓 AW-5: 遮光 ZIP スクリーンを追加する提案（要施主確認・CG のみ描画）", t(14800, h.D + 700), 1.5, "A-TEXT", "MIDDLE_CENTER")
    sh.north_arrow(sh.P(395, 268), 7, rot=h.facade_az)
    sh.view_title(names[floor], "1:100", (24, 22))
    sh.text(f"{floor[:-1]}FL = 設計GL+{fl:,}（TP+{tp(h, fl):.2f}）／天井高 CH={h.ch[floor]:,}／○ = 埋込ダウンライト（弱）、太線 = 直付ライン LED", (24, 15), 2.4, "A-TEXT", paper=True)
    cy = side_panel(sh, 284, 282, [("h", "凡例・注記")])
    # 凡例
    from house_sheets import legend
    cy = legend(sh, 285, cy - 1, [("A-FURN", "家具（外形・細線）", "line"), ("A-FURN", "チェア（外形を塗り）", "line"), ("E-LITE", "埋込ダウンライト（弱）φ100", "line"), ("E-LINE", "直付ライン LED（主照明）", "line"), ("E-FOOT", "階段の足元灯（踏面+300）", "line"),
                                   ("A-HIDDEN", "テーブルの脚位置・物干しパイプ", "line"), ("A-DOOR", "開き戸の軌跡", "line")])
    notes = [("h", "仮置きの前提"),
             ("t", NOTE),
             ("t", "ID は I-05 家具表の ID。収納は対角線、ベッドは枕の線、ソファは座クッションの割付を示す"),
             ("t", "床置きの家具は、台輪で床まで塞ぐ（掃除ロボット）、脚下 250mm 以上、洗面・手洗いは床から 650 浮かせる、のいずれか。壁との間は密着か 250mm 以上（頭・指が挟まるすき間をつくらない）"),
             ("t", "扉の軌跡と、扉・開口の前後 600 の通行帯には家具を置かない。コンセント・スイッチ（シャッター付き）は FL+250／FL+1,100、床コンセントなし"),
             ("t", "ジム機器は既存の配置のまま。安全帯（トレッドミル後方 2.0m）と重ねない")]
    if floor == "1F":
        notes += [("t", "LDK: チェアは1脚だけ（施主指示）。テーブルは回遊①の通り道から 1,600 以上離す"),
                  ("t", "玄関のベンチ・下足入れは既存（A-03）。座る家具の扱い（ベンチ）は要施主確認。下足入れは台輪で床まで塞ぐ（ブリーフ17章の「床から浮かせる」との食い違いは要施主確認）"),
                  ("t", "キッチンの換気は IH 一体のダウンドラフト（天井はフラットのまま。要施主確認）")]
    else:
        notes += [("t", "シアターの箱型ソファ・図書室の窓下ベンチは座る家具（要施主確認）。設定 furniture.optional_seating で一括して外せる"),
                  ("t", "ベッドは1部屋1台。頭は窓のない壁側。チェア・スツールは LDK の1脚のほか置かない")]
    side_panel(sh, 284, cy - 3, notes, width=118)
    return sh


# ===================================================================== I-05 家具表・内装色彩計画
PALETTE_ROWS = [
    ("wall_paint", "壁", "PB＋耐汚染塗装（拭き取り可）"), ("ceiling_paint", "天井", "PB＋EP（フラット・溝なし）＋直付ライン LED（主）・埋込 LED（弱）"),
    ("floor_oak", "床 居室・LDK・キッチン・図書室・階段", "複合フローリング（ノンワックス・ややつや）"), ("floor_sheet", "床 トイレ・洗面・ランドリー・浴室", "塩ビシームレスシート（石目調）"),
    ("floor_tile_genkan", "床 玄関土間", "大判磁器タイル 600角・細目地"), ("floor_rubber", "床 ジム", "ゴムシート t15（灰色。黒にしない）"),
    ("floor_carpet", "床 シアター・前室", "タイルカーペット（暗すぎない）"), ("wall_theater", "壁 シアター・前室", "PET 吸音ボード"),
    ("ceiling_theater", "天井 シアター", "吸音 PB（映写のため暗め）"), ("wainscot_gym", "腰 ジム H1,200", "耐衝撃化粧パネル"),
    ("wainscot", "腰 トイレ・玄関 H1,000", "化粧パネル"), ("wet_panel", "壁 洗面・ランドリー・浴室", "耐水化粧パネル（目地なし）"),
    ("door_oak", "内部建具", "オーク突板（現行 #73614D を置き換える提案）"), ("kamachi", "框・窓台", "人造大理石"),
    ("nosing", "段鼻の色差", "階段・框に幅30"), ("handrail", "手すり", "オーク φ35"),
    ("case_ash", "造作収納の扉", "アッシュ突板"), ("case_oak", "本棚・ベッド・ベンチ", "オーク"),
    ("olive_case", "アイランドの扉", "オリーブ色（外観のアソートに合わせる）"), ("sofa_olive", "ソファ・ジムのパッド", "布張り（オリーブ）"),
    ("osb", "指定: テーブル天板", "OSB t30 クリア塗装（仮定）"), ("steel_black", "指定: テーブル脚", "鋼管 □40 黒の粉体塗装（仮定）"),
    ("chair_wood", "指定: チェア座・背", "合板 チャコールブラウン（仮定）"), ("chair_frame", "指定: チェアのフレーム", "鋼管 φ22 暗褐色（仮定）"),
]


def furniture_schedule_sheet(h, number):
    sp = h.spec["furniture"]
    its = FU.items(h)
    sh = frame(h, number, "家具表・内装色彩計画（仮置き）", 1, label="—")
    sh.text("家具表・内装色彩計画 — 家具は仮置き（後日差し替え）。指定商品の寸法は仮定、色はいずれも仮定", (12, 281), 3.6, "A-TEXT", paper=True)
    # ---- 上段: 家具表（2 分割）
    rows = FU.schedule_rows(h, its, short=True)
    half = (len(rows) + 1) // 2
    cols = [10, 22, 36, 27, 6, 46, 40]
    head = ["ID", "室", "名称", "W×D×H(mm)", "数", "材質・色", "床との納まり"]
    sh.text("(1) 家具表（建物座標・mm。座る家具は要施主確認）", (12, 275), 2.4, "A-TEXT", paper=True)
    y1 = sh.table(12, 273, cols, [head] + [[r[0], r[1], r[2], r[3], r[4], r[5], r[7]] for r in rows[:half]], row_h=3.9, h=1.3)
    y2 = sh.table(12 + sum(cols) + 4, 273, cols, [head] + [[r[0], r[1], r[2], r[3], r[4], r[5], r[7]] for r in rows[half:]], row_h=3.9, h=1.3)
    ybot = min(y1, y2)
    # ---- 中段: 指定商品 2 点
    pr = sp["products"]
    T_, C_ = pr["table_osb"], pr["school_chair"]
    sh.text("(2) 指定商品2点 — 寸法・色・解釈はすべて仮定（商品ページ未確認。要施主確認）", (12, ybot - 3), 2.4, "A-TEXT", paper=True)
    part = {"edge": "天板の木口に巻いたステンレス縁（採用）", "legs": "脚がステンレス（ヘアライン）", "top": "天板の色名がステンレス（金属調塗装）"}[T_["stainless_part"]]
    prow = [["商品", "仮定した寸法・形", "色・材質（仮定）", "解釈・要確認"],
            [T_["name"], f"外寸 W{T_['w']:,}×D{T_['d']}×H{T_['h']}。天板 OSB t{T_['top_t']}。ロの字脚 2組（角パイプ □{T_['leg_pipe']}、天板端から {T_['leg_inset']} 内側）。天板下に □20×40 の補強2本",
             "天板: OSB・クリア塗装（#C9A878 の平均色）。脚: 黒の粉体塗装 #1F1E1C。縁: ステンレス（ヘアライン）",
             f"「カラー:ステンレス」は {part}。ほかの解釈（脚／天板色）は spec.yaml furniture.products.table_osb.stainless_part で切替。奥行・高さ・厚さ・角パイプ寸法も要確認"],
            [C_["name"], f"外寸 W{C_['w']}×D{C_['d']}×H{C_['h']}、座面高 SH{C_['seat_h']}。鋼管 φ{C_['pipe']}のフレーム、成形合板の座面 t12、湾曲した背板 t10（3分割で近似）",
             f"座面・背板: チャコールブラウン {C_['wood']}。フレーム: {C_['frame']}（暗褐色の粉体塗装）",
             "寸法（大人用の学童椅子型）・形・フレーム色（チャコールブラウンか、木部はナチュラルか）を要確認。LDK に1脚だけ"]]
    y3 = sh.table(12, ybot - 6, [64, 98, 72, 160], prow, row_h=4.6, h=1.4)
    # ---- 下段: 内装パレット
    sh.text("(3) 内装パレット（sRGB。いずれも仮定。実物の見本板で確認）", (12, y3 - 3), 2.4, "A-TEXT", paper=True)
    pal = h.spec["interior_palette"]
    rows2 = [[k, u, f, pal[k]["color"], ""] for k, u, f in PALETTE_ROWS if k in pal]
    hp = (len(rows2) + 1) // 2
    cols2 = [28, 56, 82, 17, 10]
    head2 = ["キー", "部位", "仕上げ", "色", "見本"]
    yy = y3 - 6
    for n, (part_rows, x) in enumerate(((rows2[:hp], 12), (rows2[hp:], 12 + sum(cols2) + 6))):
        sh.table(x, yy, cols2, [head2] + part_rows, row_h=3.7, h=1.3)
        for ri, row in enumerate(part_rows, start=1):
            top, bot = sh.last_table_rows[ri]
            x0 = x + sum(cols2[:4]) + 1.5
            sh.hatch_polys([sbox_(sh, x0, bot + 0.4, x0 + 7, top - 0.4)], layer="A-COLOR", solid=True, rgb=_hex_rgb(row[3]))
    return sh


# ===================================================================== I-06 キッチン・パントリー展開図（全露出）
def _elev_rects(mb, t, ax, sh, layer, lw=13, zbase=0.0, flip=False):
    """MB の各部品の外形（水平 = x または y、鉛直 = z）を矩形で描く。ax: 0 → x、1 → y。"""
    for key, lst in mb.parts.items():
        for V, F in lst:
            u0, u1 = V[:, ax].min(), V[:, ax].max()
            z0, z1 = V[:, 2].min() - zbase, V[:, 2].max() - zbase
            if u1 - u0 < 2 or z1 - z0 < 2:
                continue
            sh.rect(*t(u0, z0), *t(u1, z1), layer, lineweight=lw)


def kitchen_sheet(h, number):
    import kitchen_open as KO
    sh = frame(h, number, "キッチン・パントリー展開図（全露出）", 30, label="1:30")
    FL = h.fl["1F"]
    sh.text("キッチン・パントリー展開図 — 扉付きの収納をなくし、調理器具・食器・小型家電・調味料・食材をすべて見える形にする（施主指示 v4.17）", (12, 281), 3.4, "A-TEXT", paper=True)
    its = {i.id: i for i in FU.items(h)}
    # (1) 背面（y=12,000 の面を南から見る）
    t1 = T(sh, (2500, 0), (62, 165))
    sh.text("(1) キッチン背面（北の壁 Y3 を南から見る）", (12, 274), 2.8, "A-TEXT", paper=True)
    body = FS.MB()
    for iid in ("KB-W", "KB-C", "KB-F", "KB-R", "KB-K", "KB-S"):
        it = its[iid]
        mb = FU.build_item(h, it)
        _elev_rects(mb, t1, 0, sh, "A-FURN", 25, zbase=FL)
    _elev_rects(KO.props(h), t1, 0, sh, "A-VIS", 13, zbase=FL)
    sh.line(t1(2400, 0), t1(6100, 0), "A-CUT", lineweight=35)
    for zz, lab in ((900, "天板 FL+900（バックガード 50）"), (KO.RAIL_Z, "レール φ12 FL+1,300"), (1600, "ナイフバー（磁石）FL+1,600"),
                    (KO.KS_TIERS[0], "吊り棚 FL+1,700"), (KO.KS_TIERS[1], "FL+2,000"), (KO.KS_TIERS[2], "FL+2,300 ＋落下防止バー"), (300, "底板 FL+300"), (600, "中段 FL+600")):
        sh.line(t1(2380, zz), t1(2480, zz), "A-SYMB")
        sh.text(lab, t1(2370, zz), 1.3, "A-TEXT", "MIDDLE_RIGHT")
    sh.text("冷蔵庫（W700×H1,800）＋上部ふさぎ板（ステンレス）", t1(5650, 2680), 1.3, "A-TEXT", "BOTTOM_CENTER")
    sh.text("ふかし壁 KB-W（下 0〜900 耐汚染塗装、900〜2,600 ステンレス一枚貼り）", t1(3500, 2680), 1.3, "A-TEXT", "BOTTOM_CENTER")
    sh.dim(t1(6150, 0), t1(6150, 2600), t1(6150, 0), 90, text="2,600")
    # (2) パントリー（東の面から西を見る）
    t2 = T(sh, (6250, 0), (220, 165))
    sh.text("(2) パントリー（東から西の壁を見る）", (200, 274), 2.8, "A-TEXT", paper=True)
    mb = FU.build_item(h, its["P-O1"])
    _elev_rects(mb, t2, 1, sh, "A-FURN", 25, zbase=FL)
    pr = KO.props(h)
    pp = FS.MB()
    for key, lst in pr.parts.items():
        for V, F in lst:
            if V[:, 0].max() < 700 and V[:, 1].min() > 6200:
                pp.parts[key].append((V, F))
    _elev_rects(pp, t2, 1, sh, "A-VIS", 13, zbase=FL)
    sh.line(t2(6200, 0), t2(10950, 0), "A-CUT", lineweight=35)
    for zz in KO.PANTRY_SHELF_Z:
        sh.text(f"FL+{zz:,}", t2(6180, zz), 1.3, "A-TEXT", "MIDDLE_RIGHT")
    sh.text("突っ張り・ステンレス棚 奥行450、ワイヤーバスケット 12、透明の保存容器 24、米びつ、飲料水", t2(8600, 2680), 1.3, "A-TEXT", "BOTTOM_CENTER")
    # (3) アイランド調理側（北面を北から見る）
    t3 = T(sh, (2300, 0), (62, 78))
    sh.text("(3) アイランド調理側（北面を北から見る）", (12, 118), 2.8, "A-TEXT", paper=True)
    mb = FU.build_item(h, its["K-I1"])
    _elev_rects(mb, t3, 0, sh, "A-FURN", 25, zbase=FL)
    sh.line(t3(2200, 0), t3(5400, 0), "A-CUT", lineweight=35)
    sh.text("オープン棚（FL+300・600）まな板 2 枚を立てて置く", t3(3600 - 700, 1000), 1.3, "A-TEXT", "BOTTOM_CENTER")
    sh.text("IH＋ダウンドラフト／シンク下／食洗機の扉・点検パネルは機器のため残す", t3(3800, 1100), 1.3, "A-TEXT", "BOTTOM_LEFT")
    # (4) 露出する物の一覧・注記
    rows = [["区分", "物", "個数", "置き場所"],
            ["調理器具", "片手鍋 2・両手鍋 2・フライパン 2・ボウル/ざる 2組・台所用具 7", "15", "背面カウンター下部の棚／レール"],
            ["刃物", "牛刀・三徳・ペティ・パン切り・はさみ", "5", f"ナイフバー FL+{KO.KNIFE_Z[0]:,}〜{KO.KNIFE_Z[1]:,}"],
            ["まな板", "400×250×20", "2", "アイランド北面のオープン棚"],
            ["食器", "皿 14・鉢 6・飯碗 4・汁椀 4・グラス 8・マグ 6", "42", "吊り棚 1段目 FL+1,700・2段目 FL+2,000"],
            ["食材", "乾物のガラス保存容器（ふた付き）8、調味料の瓶 10", "18", "吊り棚 3段目 FL+2,300／天板のトレー"],
            ["小型家電", "電子レンジ・炊飯器・電気ケトル（マグネットプラグ）", "3", "背面カウンター天板の奥（前縁から 250 以上）"],
            ["パントリー", "バスケット 12・透明容器 24・米びつ・飲料水 2 箱", "39", "オープン棚 5 段（FL+300〜1,900）"]]
    sh.text("(4) 露出する物（約130点）", (176, 118), 2.8, "A-TEXT", paper=True)
    y = sh.table(176, 114, [20, 76, 10, 52], rows, row_h=4.2, h=1.35)
    side_panel(sh, 12, 62, [("h", "安全・清掃の対応と要施主確認（製品未確定・仮定値）"),
        ("t", "包丁は FL+1,600 の磁石バー（床の子どもは届かない目安）。代替は施錠ケース。要施主確認"),
        ("t", "天井吊りのポットラックは、落下・頭の衝突・油はね・フラット天井のため不採用。要施主確認"),
        ("t", "棚は一枚板・前縁 R3・背板なし。段の間隔は 230 超。底板 FL+300 でロボットが入る。吊り棚は落下防止バー付き"),
        ("t", "パントリーの引戸（WD-6）は残す。外す／透明扉は要施主確認。収納量は約 5.9m³ 減る"),
        ("t", "電子レンジは前縁から 250 以上奥に置くため奥行 340（仮定）。太線: 本体、細線: 露出する物")], width=160)
    return sh
