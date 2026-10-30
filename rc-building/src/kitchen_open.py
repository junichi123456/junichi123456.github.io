"""キッチン・パントリーの全露出化（施主指示 v4.17）: 背面（ふかし壁・カウンター・レール・ナイフバー・吊り棚・冷蔵庫）、アイランドの調理側のオープン棚、
パントリーのオープン棚の形と、露出する物（台所小物）。寸法は一般的な製品の仮定値。座標は建物座標 mm。

A.3 の ID: KB-W（ふかし壁）・KB-C（背面カウンター＋下部オープン棚）・KB-R（レール）・KB-K（ナイフバー）・KB-S（吊り棚 3 段）・KB-F（冷蔵庫＋ふさぎ板）・P-O1（パントリー）
"""
from __future__ import annotations

import math

import furniture_shapes as FS

# 背面カウンター下部の棚板・上部の高さ（FL+）
KB_SHELF_Z = (300, 600)            # 底板・中段の下面
KB_TOP_UNDER = 860                 # 天板の下面
KB_SHELF_T = 12
CH = 2800                       # 天井高（build_item が spec から設定する）
SHELF_MAX_Z = 1550                 # v4.18: 物を載せる・掛ける面の上端の上限（FL+）
KS_TIERS = (1538,)                 # 吊り棚（1 段）の棚板の下面（天端 1,550）
KNIFE_Z = (1250, 1550)             # 施錠式ナイフケースの下端・上端
KSW_Z = 1550                       # 目隠し収納 KS-W の本体の天端
KSW_SHELF_Z = (300, 620, 940, 1260)   # 可動棚の下面（天端は +18）
RAIL_Z = 1300
ISLAND_BAY = (1300, 1900)          # アイランド調理側（北面）のオープン棚の幅の範囲（island の局所 u）
ISLAND_BAY_Z = (300, 600)


def _cyl(mb, key, cx, cy, r, z0, z1, n=16):
    mb.tube(key, (cx, cy, z0), (cx, cy, z1), r, n)


def _handle(mb, key, cx, cy, z, r, L, dy=-1):
    """鍋・フライパンの柄（手前 = -y へ L）。"""
    mb.tube(key, (cx, cy + dy * r * 0.9, z), (cx, cy + dy * (r + L), z), 6, 8)


# ------------------------------------------------------------------ 本体
def kb_wall(mb, rect, z0):
    x0, y0, x1, y1 = rect
    mb.box("wall_paint", x0, y0, z0, x1, y1, z0 + 900)
    mb.box("stainless", x0, y0, z0 + 900, x1, y1, z0 + CH)          # ヘアライン一枚貼り（目地なし）


def kb_counter(mb, rect, z0):
    """ステンレス一体天板（バックガード立上り 50）＋脚 4 本＋オープン棚 2 段（底板 FL+300・中段 FL+600、背板・側板なし）。"""
    x0, y0, x1, y1 = rect
    t = KB_SHELF_T
    mb.box("stainless", x0, y0, z0 + 888, x1, y1, z0 + 900)
    mb.box("stainless", x0, y1 - 12, z0 + 900, x1, y1, z0 + 950)       # バックガード
    for zz in KB_SHELF_Z:
        mb.box("stainless", x0, y0, z0 + zz, x1, y1, z0 + zz + t)
    for (cx, cy) in ((x0, y0), (x1 - 25, y0), (x0, y1 - 25), (x1 - 25, y1 - 25)):
        mb.box("stainless", cx, cy, z0, cx + 25, cy + 25, z0 + 888)


def kb_rail(mb, rect, z0):
    """壁付けレール φ12（両端は壁に曲げ込み）。rect の y1 が壁面。"""
    x0, y0, x1, y1 = rect
    yc = y1 - 36
    zr = z0
    mb.tube("stainless", (x0, yc, zr), (x1, yc, zr), 6, 10)
    for xe in (x0, x1):
        mb.tube("stainless", (xe, yc, zr), (xe, y1, zr), 6, 10)


def kb_knife_case(mb, rect, z0):
    """壁付けの施錠式ナイフケース W450×H300×D80（上開きの透明アクリル蓋、チャイルドロック、内部は磁石バー）。z0 = FL+1,250。rect の y1 が壁面。"""
    x0, y0, x1, y1 = rect
    H = KNIFE_Z[1] - KNIFE_Z[0]
    mb.box("steel_black", x0, y0, z0, x1, y1, z0 + H)                   # 本体（背板・側板・底板）
    mb.box("glass_clear", x0 + 6, y0 - 4, z0 + 6, x1 - 6, y0, z0 + H - 6)  # 透明アクリルの蓋（前面）
    mb.box("stainless", x1 - 60, y0 - 10, z0 + H - 40, x1 - 20, y0, z0 + H - 20)  # 錠（磁石キー）


def kb_shelves(mb, rect, z0):
    """吊り棚 1 段（奥行 300、棚板 t12、天端 FL+1,550、前縁から 60 上に落下防止バー φ8、両端の側板を立ち上げる）。z0 は棚板の下面。"""
    x0, y0, x1, y1 = rect
    zz = z0
    mb.box("stainless", x0, y0, zz, x1, y1, zz + KB_SHELF_T)
    for xb in (x0 + 20, (x0 + x1) / 2, x1 - 26):                            # 壁側の受け板（壁に付く細い板）
        mb.box("stainless", xb, y1 - 280, zz - 60, xb + 6, y1, zz)
    yb = y0 + 8
    mb.tube("stainless", (x0 + 8, yb, zz + KB_SHELF_T + 60), (x1 - 8, yb, zz + KB_SHELF_T + 60), 4, 8)         # 落下防止バー
    for xe in (x0 + 8, x1 - 8):
        mb.tube("stainless", (xe, yb, zz + KB_SHELF_T), (xe, yb, zz + KB_SHELF_T + 60), 4, 8)
        mb.box("stainless", xe - 8, y0, zz + KB_SHELF_T, xe + 8, y1, zz + KB_SHELF_T + 60)               # 側板の立上り


def kb_fridge(mb, rect, z0):
    """独立型の冷蔵庫（ステンレス扉 W700×D600×H1800）＋上部ふさぎ板（冷蔵庫の天板〜天井、前面と面一）。前は南（-y）。"""
    x0, y0, x1, y1 = rect
    mb.box("stainless", x0, y0, z0, x1, y1, z0 + 1800)
    mb.box("stainless", x0, y0, z0 + 1800, x1, y1, z0 + CH)
    mb.box("joint", x0 + 10, y0 - 1, z0 + 1180, x1 - 10, y0, z0 + 1184)
    mb.box("joint", x0 + 340, y0 - 1, z0 + 20, x0 + 344, y0, z0 + 1170)
    mb.box("joint", x0 + 10, y0 - 1, z0 + 1795, x1 - 10, y0, z0 + 1800)
    mb.tube("stainless", (x1 - 50, y0 - 20, z0 + 1300), (x1 - 50, y0 - 20, z0 + 1700), 12, 8)


def ks_wall(mb, rect, z0):
    """西の RC 壁に面した目隠し収納 KS-W（奥行 450、H1,550、引違い戸 4 スパン×2 枚、台輪 H80、可動棚 4 枚）＋上部の化粧パネル（1,550〜天井、天井へ突っ張り、壁から 10 離す）。"""
    x0, y0, x1, y1 = rect
    n = 4
    span = (y1 - y0) / n
    mb.box("plinth", x0, y0, z0, x1 - 20, y1, z0 + 80)                   # 台輪（床までふさぐ）
    mb.box("case_ash", x0, y0, z0 + 80, x0 + 18, y1, z0 + KSW_Z)         # 背板
    mb.box("case_ash", x0, y0, z0 + KSW_Z - 18, x1, y1, z0 + KSW_Z)      # 天板
    for k in range(n + 1):
        yy = y0 + k * span
        mb.box("case_ash", x0, max(y0, yy - 9), z0 + 80, x1, min(y1, yy + 9), z0 + KSW_Z)   # 縦仕切り
    for zb in KSW_SHELF_Z:
        mb.box("case_ash", x0, y0, z0 + zb, x1 - 30, y1, z0 + zb + 18)  # 可動棚
    for k in range(n):                                                      # 引違い戸 2 枚（前後 2 レール、召し合わせ 30 重ね）
        ya = y0 + k * span
        mb.box("case_ash", x1 - 22, ya + 12, z0 + 80, x1 - 11, ya + span / 2 + 15, z0 + KSW_Z - 18)
        mb.box("case_ash", x1 - 11, ya + span / 2 - 15, z0 + 80, x1, ya + span - 12, z0 + KSW_Z - 18)
    mb.box("case_ash", x0 + 10, y0, z0 + KSW_Z, x1, y1, z0 + CH)       # 上部パネル（開かない・物を置けない）。壁から 10


def island_bay(L, z0, D):
    """アイランド調理側（背＝北）のオープン棚 2 段。L は island() の LF。局所 u（幅方向）ISLAND_BAY、v（奥から正面へ）。"""
    u0, u1 = ISLAND_BAY
    for zz in ISLAND_BAY_Z:
        L.box("stainless", u0, u1, 0, D - 60, z0 + zz, z0 + zz + KB_SHELF_T)
    L.box("stainless", u0, u0 + 12, 0, D - 60, z0 + 60, z0 + 880)
    L.box("stainless", u1 - 12, u1, 0, D - 60, z0 + 60, z0 + 880)
    L.box("olive_case", u0, u1, D - 60, D, z0 + 60, z0 + 880)               # 南面（LDK 側）は化粧パネルのまま


# ------------------------------------------------------------------ 露出する物（台所小物）
def _pot(mb, key, cx, cy, z, d, hgt, handle=None, two=False):
    _cyl(mb, key, cx, cy, d / 2, z, z + hgt, 18)
    if handle:
        _handle(mb, key, cx, cy, z + hgt * 0.8, d / 2, handle)
    if two:
        for s in (-1, 1):
            mb.tube(key, (cx + s * d / 2, cy, z + hgt * 0.8), (cx + s * (d / 2 + 35), cy, z + hgt * 0.8), 6, 8)


def _stack(mb, key, cx, cy, z, d, n, each):
    for k in range(n):
        _cyl(mb, key, cx, cy, d / 2, z + k * each, z + (k + 1) * each - 1, 16)
    return z + n * each


def props(h):
    """露出する物（約 130 点）。{材質キー: MB} ではなく、1 つの MB（材質ごとにまとまる）を返す。"""
    FL = h.fl["1F"]
    mb = FS.MB()
    st, cr, bk, ow, ap, gl = "stainless", "ceramic", "steel_black", "case_oak", "appliance_white", "glass_clear"
    cx0 = 0
    # ---- KB-C 下部の棚（x 2500〜5300、y 11350〜11950）
    zm = FL + KB_SHELF_Z[1] + KB_SHELF_T          # 中段の上面
    zb = FL + KB_SHELF_Z[0] + KB_SHELF_T          # 底板の上面
    y = 11650
    _pot(mb, st, 2800, y, zm, 180, 90, 180)       # 片手鍋
    _pot(mb, st, 3250, y, zm, 160, 80, 180)
    _pot(mb, bk, 3800, y, zm, 260, 55, 200)       # フライパン
    _pot(mb, bk, 4350, y, zm, 200, 50, 200)
    _pot(mb, st, 2800, y, zb, 200, 110, None, True)    # 両手鍋
    _pot(mb, st, 3350, y, zb, 240, 140, None, True)
    for cx in (4000, 4650):                        # ボウル・ざる（入れ子）
        _stack(mb, st, cx, y, zb, 240, 2, 50)
    # ---- KB-C 天板（上面 FL+900）
    zt = FL + 900
    mb.box(st, 3300, 11700, zt, 3750, 11850, zt + 15)                  # 調味料のトレー（縁の立上り 15）
    for k in range(10):
        _cyl(mb, gl, 3350 + (k % 5) * 80, 11740 + (k // 5) * 70, 30, zt + 15, zt + 165, 12)
    mb.box(ap, 2600, 11600, zt, 3080, 11930, zt + 300)                 # 電子レンジ（前縁から 250 以上奥）
    mb.box("glass_dark", 2630, 11599, zt + 30, 2990, 11600, zt + 270)
    mb.box(ap, 3900, 11600, zt, 4160, 11930, zt + 220)                 # 炊飯器
    _cyl(mb, ap, 4800, 11780, 80, zt, zt + 250, 16)                    # 電気ケトル
    # ---- KB-R レール（FL+1,300）の台所用具 7 点
    zr = FL + 1300
    for k in range(7):
        x = 3350 + k * 250
        L = 240 + (k * 13) % 80
        mb.tube(st, (x, 11914, zr), (x, 11905, zr - 30), 3, 6)        # S 字フック
        mb.tube(st, (x, 11905, zr - 30), (x, 11905, zr - 30 - L), 5, 8)
        mb.box(st, x - 25, 11895, zr - 30 - L - 70, x + 25, 11910, zr - 30 - L)
    # ---- KB-S 吊り棚（1 段、棚板の上面 = 下面 + 12）。グラス・マグ・乾物の容器は KS-W の中（扉の内側）に移した
    z1 = FL + KS_TIERS[0] + KB_SHELF_T
    yy = 11800
    x = 3250
    for d, n, each in ((270, 6, 18), (210, 8, 15), (150, 6, 25)):     # 大皿・中皿・鉢
        _stack(mb, cr, x + d / 2, yy, z1, d, n, each)
        x += d + 40
    for k in range(3):                                                  # 飯碗
        _cyl(mb, cr, x + 60 + k * 130, yy, 60, z1, z1 + 60, 14)
    for k in range(3):                                                  # 汁椀（木）
        _cyl(mb, ow, x + 60 + k * 130, yy - 110, 55, z1, z1 + 55, 14)
    # ---- K-I1 調理側のまな板 2 枚（北面のオープン棚の中、立てて置く）
    zi = FL + ISLAND_BAY_Z[0] + KB_SHELF_T
    # island は rect (1875,9050)-(4675,10050)、-y 向き。局所 u は x0 から、v は北（奥）から
    x0i = 1875 + ISLAND_BAY[0]
    for k in range(2):
        mb.box(ow, x0i + 100, 10050 - 100 - 20 * k - 30 * k, zi, x0i + 500, 10050 - 100 - 20 * k - 30 * k + 20, zi + 250)
    return mb


def _basket(mb, x, y, z):
    """ワイヤーバスケット 400×300×200（薄板の簡略形）。"""
    w, d, hh, t = 400, 300, 200, 3
    mb.box("stainless", x, y, z, x + w, y + d, z + t)
    for (a, b, c, e) in ((x, y, x + w, y + t), (x, y + d - t, x + w, y + d), (x, y, x + t, y + d), (x + w - t, y, x + w, y + d)):
        mb.box("stainless", a, b, z + t, c, e, z + hh)


# ------------------------------------------------------------------ v4.18: 検証（通路 ≧1,300・棚の上端 ≦1,550）
AISLE_MIN = 1300


def aisles(h, its=None):
    """固定物の仕上げ面どうしの水平の内法（mm）。[(ラベル, 値)]。出入口の戸は数えない（要施主確認 F-4）。"""
    import furniture as FU
    its = {i.id: i for i in (its or FU.items(h))}
    isl, kbc, kbf, ksw = its["K-I1"].rect, its["KB-C"].rect, its["KB-F"].rect, its["KS-W"].rect
    kit = next(r for r in h.rooms if r.name == "キッチン")
    kx0, ky0, kx1, ky1 = kit.rect
    return [("アイランド北面 ↔ 背面カウンター前面", kbc[1] - isl[3]),
            ("アイランド北面 ↔ 冷蔵庫前面", kbf[1] - isl[3]),
            ("アイランド西面 ↔ 目隠し収納 KS-W 扉面", isl[0] - ksw[2]),
            ("アイランド東面 ↔ X2 壁面", kx1 - isl[2]),
            ("アイランド南面 ↔ Y2 壁面", isl[1] - ky0),
            ("KS-W 北端 ↔ Y3 壁面", ky1 - ksw[3])]


def support_tops(h):
    """物を載せる・掛ける面の上端（FL+ mm）。[(ID, 内容, 値)]。落下防止バー（天端+60）は面ではなく縁の部材。"""
    return [("KB-C", "背面カウンター天板（バックガード立上り 50 を含む）", 950),
            ("KB-C", "下部の棚（中段）", KB_SHELF_Z[1] + KB_SHELF_T),
            ("KB-R", "レール", RAIL_Z + 12),
            ("KB-S", "吊り棚の棚板天端", KS_TIERS[0] + KB_SHELF_T),
            ("KB-N", "ナイフケース上端", KNIFE_Z[1]),
            ("K-I1", "アイランド天板", 900),
            ("K-I1", "アイランド北面のオープン棚", ISLAND_BAY_Z[1] + KB_SHELF_T),
            ("KS-W", "目隠し収納の天板・最上段の棚板天端", max(KSW_Z, max(KSW_SHELF_Z) + 18))]
