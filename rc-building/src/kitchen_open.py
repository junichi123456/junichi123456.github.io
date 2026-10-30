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
KS_TIERS = (1700, 2000, 2300)      # 吊り棚の棚板の下面
PANTRY_SHELF_Z = (300, 700, 1100, 1500, 1900)
KNIFE_Z = (1580, 1620)
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


def kb_knife(mb, rect, z0):
    """マグネット式ナイフバー W450×H40×D20（壁に密着）。"""
    x0, y0, x1, y1 = rect
    mb.box("stainless", x0, y1 - 20, z0, x1, y1, z0 + 40)


def kb_shelves(mb, rect, z0):
    """吊り棚 3 段（奥行 300、棚板 t12、前縁から 60 上に落下防止バー φ8、棚の下面にライン照明（lighting.py））。z0 は最下段の下面。"""
    x0, y0, x1, y1 = rect
    for k, zb in enumerate(KS_TIERS):
        zz = z0 + (zb - KS_TIERS[0])
        mb.box("stainless", x0, y0, zz, x1, y1, zz + KB_SHELF_T)
        for xb in (x0 + 20, (x0 + x1) / 2, x1 - 26):                        # 壁側の受け板（壁に付く細い板）
            mb.box("stainless", xb, y1 - 280, zz - 60, xb + 6, y1, zz)
        yb = y0 + 8
        mb.tube("stainless", (x0 + 8, yb, zz + KB_SHELF_T + 60), (x1 - 8, yb, zz + KB_SHELF_T + 60), 4, 8)     # 落下防止バー
        for xe in (x0 + 8, x1 - 8):
            mb.tube("stainless", (xe, yb, zz + KB_SHELF_T), (xe, yb, zz + KB_SHELF_T + 60), 4, 8)


def kb_fridge(mb, rect, z0):
    """独立型の冷蔵庫（ステンレス扉 W700×D600×H1800）＋上部ふさぎ板（冷蔵庫の天板〜天井、前面と面一）。前は南（-y）。"""
    x0, y0, x1, y1 = rect
    mb.box("stainless", x0, y0, z0, x1, y1, z0 + 1800)
    mb.box("stainless", x0, y0, z0 + 1800, x1, y1, z0 + CH)
    mb.box("joint", x0 + 10, y0 - 1, z0 + 1180, x1 - 10, y0, z0 + 1184)
    mb.box("joint", x0 + 340, y0 - 1, z0 + 20, x0 + 344, y0, z0 + 1170)
    mb.box("joint", x0 + 10, y0 - 1, z0 + 1795, x1 - 10, y0, z0 + 1800)
    mb.tube("stainless", (x1 - 50, y0 - 20, z0 + 1300), (x1 - 50, y0 - 20, z0 + 1700), 12, 8)


def pantry_open(mb, rect, z0):
    """パントリーの突っ張りオープン棚（奥行 450、棚板 FL+300・700・1,100・1,500・1,900）。"""
    x0, y0, x1, y1 = rect
    for zz in PANTRY_SHELF_Z:
        mb.box("stainless", x0, y0, z0 + zz, x1, y1, z0 + zz + KB_SHELF_T)
    n = 5
    for k in range(n):
        yy = y0 + (y1 - y0 - 30) * k / (n - 1)
        mb.box("stainless", x0 + 10, yy, z0, x0 + 40, yy + 30, z0 + CH)           # 突っ張り支柱 □30（床〜天井）
        mb.box("stainless", x1 - 40, yy, z0, x1 - 10, yy + 30, z0 + CH)


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
    # ---- KB-K ナイフバー（FL+1,580〜1,620）の包丁 5 本
    zk = FL + 1600
    for k, Lk in enumerate((350, 300, 240, 300, 220)):
        x = 2700 + k * 85
        mb.box(st, x, 11924, zk + 20 - Lk * 0.55, x + 28, 11930, zk + 20)                 # 刃
        mb.box(bk, x + 6, 11922, zk + 20 - Lk, x + 22, 11932, zk + 20 - Lk * 0.55)        # 柄
    # ---- KB-S 吊り棚（棚板の上面 = 下面 + 12）
    z1, z2, z3 = (FL + t + KB_SHELF_T for t in KS_TIERS)
    yy = 11800
    x = 2650
    for d, n, each in ((270, 6, 18), (210, 8, 15), (150, 6, 25)):     # 大皿・中皿・鉢
        _stack(mb, cr, x + d / 2, yy, z1, d, n, each)
        x += d + 40
    for k in range(4):                                                  # 飯碗
        _cyl(mb, cr, x + 60 + k * 130, yy, 60, z1, z1 + 60, 14)
    for k in range(4):                                                  # 汁椀（木）
        _cyl(mb, ow, x + 60 + k * 130, yy - 110, 55, z1, z1 + 55, 14)
    for k in range(8):                                                  # グラス
        _cyl(mb, gl, 2680 + k * 95, 11850, 37, z2, z2 + 110, 12)
    for k in range(6):                                                  # マグ
        _cyl(mb, cr, 2700 + k * 110, 11740, 42, z2, z2 + 95, 12)
    for k in range(8):                                                  # 乾物の保存容器（ふた付き）
        _cyl(mb, gl, 2700 + k * 125, 11800, 50, z3, z3 + 200, 14)
        _cyl(mb, st, 2700 + k * 125, 11800, 52, z3 + 200, z3 + 215, 14)
    # ---- K-I1 調理側のまな板 2 枚（北面のオープン棚の中、立てて置く）
    zi = FL + ISLAND_BAY_Z[0] + KB_SHELF_T
    # island は rect (2300,9400)-(5300,10400)、-y 向き。局所 u は x0 から、v は北（奥）から
    x0i = 2300 + ISLAND_BAY[0]
    for k in range(2):
        mb.box(ow, x0i + 100, 10400 - 100 - 20 * k - 30 * k, zi, x0i + 500, 10400 - 100 - 20 * k - 30 * k + 20, zi + 250)
    # ---- P-O1 パントリー（x 125〜575、y 6250〜10900）
    px0 = 140
    zs = [FL + t + KB_SHELF_T for t in PANTRY_SHELF_Z]
    mb.box(gl, px0, 6330, zs[0], px0 + 300, 6730, zs[0] + 450)         # 米びつ
    for k in range(2):                                                   # 飲料水の箱
        mb.box(ap, px0, 6900 + k * 260, zs[0], px0 + 220, 6900 + k * 260 + 250, zs[0] + 310)
    for k in range(6):                                                   # ワイヤーバスケット（最下段）
        _basket(mb, px0, 7500 + k * 340, zs[0])
    for k in range(6):                                                   # 2 段目
        _basket(mb, px0, 6330 + k * 340, zs[1])
    for s in (2, 3):                                                     # 透明の保存容器 24
        for k in range(12):
            _cyl(mb, gl, 350, 6380 + k * 375, 55, zs[s], zs[s] + 200, 12)
            _cyl(mb, st, 350, 6380 + k * 375, 57, zs[s] + 200, zs[s] + 212, 12)
    return mb


def _basket(mb, x, y, z):
    """ワイヤーバスケット 400×300×200（薄板の簡略形）。"""
    w, d, hh, t = 400, 300, 200, 3
    mb.box("stainless", x, y, z, x + w, y + d, z + t)
    for (a, b, c, e) in ((x, y, x + w, y + t), (x, y + d - t, x + w, y + d), (x, y, x + t, y + d), (x + w - t, y, x + w, y + d)):
        mb.box("stainless", a, b, z + t, c, e, z + hh)
