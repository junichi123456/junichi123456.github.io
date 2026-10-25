"""家具・設備の形状（trimesh の頂点配列）。furniture.py と interior_shell.py が使う。

入力は建物座標 mm。MB は材質キーごとに頂点・面をためて、最後に m の trimesh にする。
曲面は使わず、円管・円柱・楕円球（低ポリゴン）と箱だけで作る。
"""
from __future__ import annotations

import math
import random
import zlib
from collections import defaultdict

import numpy as np
import trimesh

_CUBE_V = np.array([[i & 1, (i >> 1) & 1, (i >> 2) & 1] for i in range(8)], float)
_CUBE_F = np.array([[0, 2, 3], [0, 3, 1], [4, 5, 7], [4, 7, 6], [0, 1, 5], [0, 5, 4],
                    [2, 6, 7], [2, 7, 3], [0, 4, 6], [0, 6, 2], [1, 3, 7], [1, 7, 5]])


def _rot_to(d):
    """z 軸を方向 d に向ける回転行列（3x3）。"""
    z = np.asarray(d, float)
    z = z / np.linalg.norm(z)
    ref = np.array([0.0, 0.0, 1.0]) if abs(z[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    x = np.cross(ref, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.stack([x, y, z], axis=1)


class MB:
    """材質キーごとのメッシュ・ビルダー（mm）。"""

    def __init__(self):
        self.parts = defaultdict(list)          # key -> [(V (n,3), F (m,3))]

    # ---------------------------------------------------------------- 基本形
    def add(self, key, V, F):
        self.parts[key].append((np.asarray(V, float), np.asarray(F, int)))

    def box(self, key, x0, y0, z0, x1, y1, z1):
        if x1 - x0 <= 1e-6 or y1 - y0 <= 1e-6 or z1 - z0 <= 1e-6:
            return
        V = _CUBE_V * np.array([x1 - x0, y1 - y0, z1 - z0]) + np.array([x0, y0, z0])
        self.add(key, V, _CUBE_F)

    def hexa(self, key, P):
        """8 点の六面体（立方体の頂点番号と同じ並び: 下面 0,1,2,3 = (x0y0, x1y0, x0y1, x1y1)、上面 4〜7）。"""
        self.add(key, np.asarray(P, float), _CUBE_F)

    def tube(self, key, p0, p1, r, n=12):
        a, b = np.asarray(p0, float), np.asarray(p1, float)
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-6:
            return
        R = _rot_to(d)
        ang = np.linspace(0, 2 * math.pi, n, endpoint=False)
        ring = np.stack([np.cos(ang) * r, np.sin(ang) * r, np.zeros(n)], axis=1)
        V0 = ring @ R.T + a
        V1 = (ring + np.array([0, 0, L])) @ R.T + a
        V = np.vstack([V0, V1, [a], [b]])
        c0, c1 = 2 * n, 2 * n + 1
        F = []
        for k in range(n):
            k2 = (k + 1) % n
            F += [[k, k2, n + k2], [k, n + k2, n + k], [c1, n + k, n + k2], [c0, k2, k]]
        self.add(key, V, F)

    def cyl(self, key, cx, cy, r, z0, z1, n=24):
        self.tube(key, (cx, cy, z0), (cx, cy, z1), r, n)

    def sphere(self, key, cx, cy, cz, r, sx=1.0, sy=1.0, sz=1.0, seg=8):
        m = trimesh.creation.uv_sphere(radius=1.0, count=[seg, seg])
        V = np.asarray(m.vertices) * np.array([r * sx, r * sy, r * sz]) + np.array([cx, cy, cz])
        self.add(key, V, np.asarray(m.faces))

    def slab_poly(self, key, poly, z0, z1):
        """shapely Polygon（mm）を z0〜z1 に押し出す。"""
        if poly.is_empty or z1 <= z0:
            return
        ext = list(poly.exterior.coords)
        holes = [list(r.coords) for r in poly.interiors]
        from shapely.geometry import Polygon
        m = trimesh.creation.extrude_polygon(Polygon(ext, holes), z1 - z0)
        V = np.asarray(m.vertices) + np.array([0, 0, z0])
        self.add(key, V, np.asarray(m.faces))

    # ---------------------------------------------------------------- 変換・出力
    def rotate_z(self, deg, cx, cy):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        for key, lst in self.parts.items():
            out = []
            for V, F in lst:
                x, y = V[:, 0] - cx, V[:, 1] - cy
                V2 = V.copy()
                V2[:, 0] = x * c - y * s + cx
                V2[:, 1] = x * s + y * c + cy
                out.append((V2, F))
            self.parts[key] = out

    def meshes(self):
        """{材質キー: trimesh（m）}。"""
        out = {}
        for key, lst in self.parts.items():
            Vs, Fs, off = [], [], 0
            for V, F in lst:
                Vs.append(V)
                Fs.append(F + off)
                off += len(V)
            if not Vs:
                continue
            m = trimesh.Trimesh(vertices=np.vstack(Vs) / 1000.0, faces=np.vstack(Fs), process=False)
            out[key] = m
        return out

    def bounds(self):
        allv = [V for lst in self.parts.values() for V, _ in lst]
        if not allv:
            return None
        A = np.vstack(allv)
        return A.min(axis=0), A.max(axis=0)


# ====================================================================== 局所座標（壁側=奥 v=0、正面側 v=D）
class LF:
    """矩形 rect の局所座標。u: 幅方向（長辺側）、v: 奥（壁側）から正面へ、z: 絶対高さ。front は正面の向き '-y','+y','-x','+x'。"""

    def __init__(self, mb, rect, front):
        self.mb, self.rect, self.front = mb, rect, front
        x0, y0, x1, y1 = rect
        if front in ("-y", "+y"):
            self.W, self.D = x1 - x0, y1 - y0
        else:
            self.W, self.D = y1 - y0, x1 - x0

    def xy(self, u0, u1, v0, v1):
        x0, y0, x1, y1 = self.rect
        f = self.front
        if f == "-y":
            return x0 + u0, y1 - v1, x0 + u1, y1 - v0
        if f == "+y":
            return x0 + u0, y0 + v0, x0 + u1, y0 + v1
        if f == "-x":
            return x1 - v1, y0 + u0, x1 - v0, y0 + u1
        return x0 + v0, y0 + u0, x0 + v1, y0 + u1

    def box(self, key, u0, u1, v0, v1, z0, z1):
        a, b, c, d = self.xy(u0, u1, v0, v1)
        self.mb.box(key, a, b, z0, c, d, z1)

    def pt(self, u, v):
        a, b, c, d = self.xy(u, u, v, v)
        return a, b


def front_of(rect, room_c):
    """部屋の中心を向く面を正面とする（長辺方向に沿って並べ、短辺側が壁側）。"""
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if (x1 - x0) >= (y1 - y0):
        return "+y" if room_c[1] > cy else "-y"
    return "+x" if room_c[0] > cx else "-x"


# ====================================================================== 造作・箱物
def case(mb, rect, z0, H, front, key, plinth=60, setback=40, pitch=450, joints=True, top=None):
    """台輪付きの箱。扉面に細い目地。top: (材質, 厚さ) 天板を別材質にする。"""
    L = LF(mb, rect, front)
    L.box("plinth", 0, L.W, 0, L.D - setback, z0, z0 + plinth + 1)
    zt = z0 + H
    if top:
        L.box(key, 0, L.W, 0, L.D, z0 + plinth, zt - top[1])
        L.box(top[0], 0, L.W, 0, L.D + 10, zt - top[1], zt)
    else:
        L.box(key, 0, L.W, 0, L.D, z0 + plinth, zt)
    if joints and H > plinth + 200:
        n = max(1, round(L.W / pitch))
        for k in range(1, n):
            u = L.W * k / n
            L.box("joint", u - 2, u + 2, L.D, L.D + 1, z0 + plinth + 5, zt - 5)
        # 上下端の水平目地は省く（面が単調になるのを避けるため中段に1本）
        if H > 1800:
            L.box("joint", 3, L.W - 3, L.D, L.D + 1, z0 + 1100, z0 + 1104)


def bookcase(mb, rect, z0, H, front, key="case_oak", seed=7):
    L = LF(mb, rect, front)
    t = 20
    L.box("plinth", 0, L.W, 0, L.D - 40, z0, z0 + 61)
    zb = z0 + 60
    L.box(key, 0, t, 0, L.D, zb, z0 + H)                 # 側板
    L.box(key, L.W - t, L.W, 0, L.D, zb, z0 + H)
    L.box(key, t, L.W - t, 0, 12, zb, z0 + H)           # 背板
    L.box(key, t, L.W - t, 0, L.D, z0 + H - t, z0 + H)  # 天板
    pitch = 400
    levels = list(range(0, 6))
    rnd = random.Random(seed + int(L.W))
    keys = ["book_a", "book_b", "book_c", "book_d", "book_e"]
    for lev in levels:
        zs = zb + lev * pitch
        L.box(key, t, L.W - t, 0, L.D, zs, zs + t)      # 棚板
        u = t + 8
        while u < L.W - t - 70:
            w = rnd.uniform(18, 60)
            hh = rnd.uniform(200, 330)
            if rnd.random() < 0.06:                       # 倒れた本の束で単調さをなくす
                u += 40
                continue
            L.box(rnd.choice(keys), u, u + w - 2, 14, 14 + min(L.D - 90, 230), zs + t, zs + t + hh)
            u += w
    # 最上段の上の空き（天井まで）は扉で隠れる想定で、棚を6段 + 天板


def tall_kitchen(mb, rect, z0, front, p):
    """背面収納: 冷蔵庫・家電ニッチ・天井までの収納。"""
    L = LF(mb, rect, front)
    H = 2600
    pl = 60
    L.box("plinth", 0, L.W, 0, L.D - 40, z0, z0 + pl + 1)
    jt = lambda u: L.box("joint", u - 2, u + 2, L.D, L.D + 1, z0 + pl + 5, z0 + H - 5)
    # 左: 天井までの収納 u 0〜1200
    L.box("case_ash", 0, 1200, 0, L.D, z0 + pl, z0 + H)
    jt(600)
    # ニッチ（u 1200〜2400）: 下は引き出し、天板 H900、ニッチ H600、上は吊り戸
    L.box("case_ash", 1200, 2400, 0, L.D, z0 + pl, z0 + 880)
    jt(1800)
    L.box("countertop", 1200, 2400, 0, L.D + 10, z0 + 880, z0 + 900)
    L.box("backpanel", 1200, 2400, 0, 300, z0 + 900, z0 + 1500)
    L.box("case_ash", 1200, 2400, 0, L.D, z0 + 1500, z0 + H)
    jt(1800)
    L.box("appliance_white", 1300, 1900, 300, 640, z0 + 900, z0 + 1230)             # 電子レンジ
    L.box("glass_dark", 1330, 1700, 640, 641, z0 + 930, z0 + 1200)
    L.box("appliance_white", 2000, 2300, 300, 520, z0 + 900, z0 + 1050)             # 小型家電（ケトル等）
    # 中右: 収納 u 2400〜2800
    L.box("case_ash", 2400, 2800, 0, L.D, z0 + pl, z0 + H)
    # 冷蔵庫 u 2800〜3500（扉はステンレス）
    L.box("stainless", 2800, L.W, 0, L.D, z0, z0 + 1850)
    L.box("joint", 2800 + 340, 2800 + 344, L.D, L.D + 1, z0 + 20, z0 + 1830)
    L.box("joint", 2810, L.W - 10, L.D, L.D + 1, z0 + 1180, z0 + 1184)
    L.box("case_ash", 2800, L.W, 0, L.D, z0 + 1850, z0 + H)


def island(mb, rect, z0, p):
    """アイランドキッチン（南向きに調理）。"""
    x0, y0, x1, y1 = rect
    L = LF(mb, rect, "-y")                    # 背は北、正面は南（LDK 側）
    W, D = L.W, L.D
    L.box("plinth", 0, W, 0, D - 40, z0, z0 + 61)
    L.box("olive_case", 0, W, 0, D, z0 + 60, z0 + 880)
    n = max(1, round(W / 600))
    for k in range(1, n):
        u = W * k / n
        L.box("joint", u - 2, u + 2, D, D + 1, z0 + 65, z0 + 875)
    # 天板: シンクの開口と IH の面一ガラス
    su0, su1, sv0, sv1 = 450, 1250, 330, 780                      # シンク（u, 奥からの v）
    iu0, iu1, iv0, iv1 = 1950, 2650, 300, 820                     # IH
    zt = z0 + 900
    pieces = [(-10, W + 10, -10, sv0), (-10, W + 10, sv1, D + 10), (-10, su0, sv0, sv1), (su1, W + 10, sv0, sv1)]
    for (a, b, c, d) in pieces:
        # 天板（IH の範囲は別に抜く）
        if a < iu1 and b > iu0 and d > iv0 and c < iv1:
            for (a2, b2, c2, d2) in ((a, iu0, c, d), (iu1, b, c, d), (max(a, iu0), min(b, iu1), c, iv0), (max(a, iu0), min(b, iu1), iv1, d)):
                if b2 > a2 and d2 > c2:
                    L.box("countertop", a2, b2, c2, d2, z0 + 880, zt)
        else:
            L.box("countertop", a, b, c, d, z0 + 880, zt)
    L.box("ih_glass", iu0, iu1, iv0, iv1, z0 + 880, zt + 3)
    L.box("ih_glass", iu0, iu1, 130, 190, z0 + 892, zt + 1)                    # ダウンドラフトの吸込口（IH の奥の暗い溝）
    for (a, b, c, d) in ((su0, su1, sv0, sv0 + 12), (su0, su1, sv1 - 12, sv1), (su0, su0 + 12, sv0, sv1), (su1 - 12, su1, sv0, sv1)):
        L.box("countertop", a, b, c, d, z0 + 780, zt)                            # シンクの壁（一体成形）
    L.box("countertop", su0, su1, sv0, sv1, z0 + 770, z0 + 790)                  # シンクの底
    fu, fv = (su0 + su1) / 2, sv1 + 60
    fx, fy = L.pt(fu, fv)
    mb.tube("stainless", (fx, fy, zt), (fx, fy, zt + 260), 14, 12)               # 水栓（グースネック）
    gx, gy = L.pt(fu, fv - 130)
    mb.tube("stainless", (fx, fy, zt + 260), (gx, gy, zt + 260), 12, 12)
    mb.tube("stainless", (gx, gy, zt + 260), (gx, gy, zt + 215), 10, 12)


def counter_float(mb, rect, z0, H, front, key="solid_surface"):
    """浮かせた洗面・手洗いカウンター（下端 FL+650）。ボウルは一体成形の凹み。"""
    L = LF(mb, rect, front)
    zb, zt = z0 + 650, z0 + H
    bu0, bu1 = L.W * 0.18, L.W * 0.82
    bv0, bv1 = L.D * 0.2, L.D * 0.72
    if L.W < 400:                                     # 手洗い（幅の狭いもの）は小さな凹み
        bu0, bu1 = 40, L.W - 40
        bv0, bv1 = L.D * 0.2, L.D * 0.8
    for (a, b, c, d) in ((0, L.W, 0, bv0), (0, L.W, bv1, L.D), (0, bu0, bv0, bv1), (bu1, L.W, bv0, bv1)):
        L.box(key, a, b, c, d, zb, zt)
    L.box(key, bu0, bu1, bv0, bv1, zb, zb + (H - 650) - 110)       # ボウルの底
    u = (bu0 + bu1) / 2
    px, py = L.pt(u, bv0 * 0.5)
    mb.tube("stainless", (px, py, zt), (px, py, zt + 180), 12, 12)
    # 前面の厚み方向のスリットは設けない（ほこり溜まり防止）


def toilet(mb, rect, z0):
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) / 2
    mb.box("ceramic", cx - 200, y0 + 150, z0, cx + 200, y1 - 200, z0 + 400)
    mb.box("ceramic", cx - 170, y0 + 130, z0 + 100, cx + 170, y0 + 152, z0 + 400)
    mb.box("seat", cx - 190, y0 + 120, z0 + 400, cx + 190, y1 - 200, z0 + 430)
    mb.box("ceramic", cx - 210, y1 - 200, z0 + 250, cx + 210, y1, z0 + 800)


def washer2(mb, rect, z0, front):
    L = LF(mb, rect, front)
    H = 1060
    for i in range(2):
        u0 = i * 650
        u1 = u0 + 640
        L.box("appliance_white", u0, u1, 0, L.D, z0, z0 + H)
        L.box("steel_black", u0 + 20, u1 - 20, L.D, L.D + 1, z0 + H - 140, z0 + H - 40)       # 操作パネル
        cx, cy = L.pt((u0 + u1) / 2, L.D)
        d = {"-y": (0, -1), "+y": (0, 1), "-x": (-1, 0), "+x": (1, 0)}[front]
        z = z0 + 480
        # 軸が水平の円盤は、向きに合わせた短い円管で作る
        mb.tube("glass_dark", (cx - d[0] * 2, cy - d[1] * 2, z), (cx + d[0] * 6, cy + d[1] * 6, z), 170, 20)
        mb.tube("steel_black", (cx - d[0] * 2, cy - d[1] * 2, z), (cx + d[0] * 3, cy + d[1] * 3, z), 195, 20)


def plant(mb, rect, z0, H, name_id, pot_h=380):
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = (x1 - x0) / 2
    rnd = random.Random(zlib.crc32(name_id.encode()))
    mb.cyl("pot", cx, cy, r, z0, z0 + pot_h, 24)
    mb.tube("trunk", (cx, cy, z0 + pot_h - 40), (cx + 30, cy - 25, z0 + H * 0.62), 20, 8)
    top = (cx + 30, cy - 25)
    for k in range(10):
        a = rnd.uniform(0, 2 * math.pi)
        rr = rnd.uniform(0.0, 0.7) * r
        zz = z0 + H * rnd.uniform(0.58, 0.95)
        mb.sphere("leaf", top[0] + math.cos(a) * rr, top[1] + math.sin(a) * rr, zz, r * rnd.uniform(0.36, 0.55), 1, 1, 0.75, 8)


def dock(mb, rect, z0, H):
    x0, y0, x1, y1 = rect
    mb.box("appliance_white", x0, y0, z0, x1, y1, z0 + H)
    mb.box("steel_black", x0 + 40, y0 + 40, z0 + H - 90, x1 - 40, y1 - 30, z0 + H - 80)


def sofa(mb, rect, z0, front, mat="sofa_olive"):
    L = LF(mb, rect, front)
    L.box("plinth", 40, L.W - 40, 40, L.D - 40, z0, z0 + 61)
    L.box(mat, 0, L.W, 0, L.D, z0 + 60, z0 + 330)
    L.box(mat, 0, L.W, 0, 200, z0 + 330, z0 + 780)                        # 背
    L.box(mat, 0, 180, 200, L.D, z0 + 330, z0 + 600)                      # 肘
    L.box(mat, L.W - 180, L.W, 200, L.D, z0 + 330, z0 + 600)
    n = 3
    iw = (L.W - 360) / n
    for k in range(n):
        L.box(mat, 180 + k * iw + 2, 180 + (k + 1) * iw - 2, 200, L.D - 20, z0 + 330, z0 + 430)    # 座クッション（3mm 目地）
    cu = [(190, "cushion"), (L.W - 190 - 380, "throw")]
    for u, k in cu:
        L.box(k, u, u + 380, 210, 330, z0 + 430, z0 + 700)                # 背クッション（からし）


def bed(mb, rect, z0, head):
    """head: 頭側の向き '+y','-y','+x','-x'。"""
    front = {"+y": "-y", "-y": "+y", "+x": "-x", "-x": "+x"}[head]
    L = LF(mb, rect, front)                    # 奥 = 頭側
    clear, H = 260, 520
    for u in (60, L.W - 100):
        for v in (40, L.D - 80):
            L.box("case_oak", u, u + 40, v, v + 40, z0, z0 + clear + 1)
    L.box("case_oak", 0, L.W, 0, L.D, z0 + clear, z0 + clear + 80)
    L.box("mattress", 15, L.W - 15, 15, L.D - 15, z0 + clear + 80, z0 + H - 40)
    L.box("case_oak", 0, L.W, 0, 30, z0 + clear, z0 + 950)               # 頭板
    L.box("duvet", 5, L.W - 5, L.D * 0.28, L.D - 5, z0 + H - 55, z0 + H + 15)
    pw = min(560, (L.W - 240) / (1 if L.W < 1100 else 2))
    if L.W < 1100:
        L.box("pillow", 120, L.W - 120, 60, 320, z0 + H - 40, z0 + H + 70)
    else:
        for k in range(2):
            u0 = 120 + k * (L.W - 240) / 2 + 20
            L.box("pillow", u0, u0 + (L.W - 240) / 2 - 40, 60, 320, z0 + H - 40, z0 + H + 70)
    L.box("throw", -10, L.W + 10, L.D - 560, L.D - 140, z0 + H - 25, z0 + H + 22)


# ====================================================================== 指定商品 2 点
def table_osb(mb, rect, z0, prod):
    x0, y0, x1, y1 = rect
    top_t, H = prod["top_t"], prod["h"]
    pipe, inset = prod["leg_pipe"], prod["leg_inset"]
    part = prod.get("stainless_part", "edge")
    cy = (y0 + y1) / 2
    zt = z0 + H
    edge_key = "stainless" if part == "edge" else "osb"
    leg_key = "stainless" if part == "legs" else "steel_black"
    mb.box("osb", x0, y0, zt - top_t, x1, y1, zt - (1 if part == "top" else 0))
    if part == "top":
        mb.box("stainless_paint", x0, y0, zt - 1, x1, y1, zt)
    if part == "edge":
        e = 1.0
        for q in ((x0 - e, y0 - e, x1 + e, y0), (x0 - e, y1, x1 + e, y1 + e), (x0 - e, y0, x0, y1), (x1, y0, x1 + e, y1)):
            mb.box(edge_key, q[0], q[1], zt - top_t, q[2], q[3], zt)
    a = pipe
    ys0, ys1 = cy - (prod["d"] - 100) / 2, cy + (prod["d"] - 100) / 2          # ロの字の幅（天板より 50 ずつ内側）
    ztop = zt - top_t                                                            # 上枠の上面
    for xs in (x0 + inset, x1 - inset - a):
        mb.box(leg_key, xs, ys0, z0 + 5, xs + a, ys1, z0 + 5 + a)               # 下枠
        mb.box(leg_key, xs, ys0, ztop - a, xs + a, ys1, ztop)                   # 上枠
        mb.box(leg_key, xs, ys0, z0 + 5, xs + a, ys0 + a, ztop)                 # 縦枠
        mb.box(leg_key, xs, ys1 - a, z0 + 5, xs + a, ys1, ztop)
        for yy in (ys0 + a / 2 + 5, ys1 - a / 2 - 5):
            mb.cyl("glide", xs + a / 2, yy, 10, z0, z0 + 6, 12)                 # アジャスター φ20×5
    for yy in (cy - 225, cy + 225):                                              # 補強 □20×40
        mb.box("steel_black", x0 + inset + a, yy - 10, ztop - 40, x1 - inset - a, yy + 10, ztop)


def school_chair(mb, rect, z0, prod):
    x0, y0, x1, y1 = rect
    w, d, Ht, sh, pipe = prod["w"], prod["d"], prod["h"], prod["seat_h"], prod["pipe"]
    cx = (x0 + x1) / 2
    r = pipe / 2
    xo = w / 2 - 30                                   # 脚の x
    yf = y0 + 30                                      # 前脚の y
    sd = d - 65
    yk = y0 + 5 + sd                                  # 座の後端（後脚の折れ点）
    tilt = math.tan(math.radians(8)) * (Ht - (sh - 20))
    ytop = y1 - r - 1
    ykink = ytop - tilt
    yb = ykink - 15
    zk = z0 + sh - 20
    for sx in (-1, 1):
        xl = cx + sx * xo
        mb.tube("chair_frame", (xl, yf, z0 + 8), (xl, yf, zk), r, 12)                                 # 前脚
        mb.tube("chair_frame", (xl, yb, z0 + 8), (xl, ykink, zk), r, 12)                              # 後脚（下）
        mb.tube("chair_frame", (xl, ykink, zk), (xl, ytop, z0 + Ht), r, 12)                           # 後脚（背の支柱）
        mb.tube("chair_frame", (xl, yf, zk), (xl, ykink, zk), r, 12)                                  # 座枠
        yr = yb + (ykink - yb) * (180 - 8) / (zk - z0 - 8)
        mb.tube("chair_frame", (xl, yf, z0 + 180), (xl, yr, z0 + 180), r * 0.8, 10)                 # 貫（左右）
        mb.cyl("glide", xl, yf, 13, z0, z0 + 8, 14)
        mb.cyl("glide", xl, yb, 13, z0, z0 + 8, 14)
    mb.tube("chair_frame", (cx - xo, yf, z0 + 180), (cx + xo, yf, z0 + 180), r * 0.8, 10)            # 前の貫
    mb.tube("chair_frame", (cx - xo, ykink, zk), (cx + xo, ykink, zk), r * 0.8, 10)                  # 座枠の後ろ
    mb.tube("chair_frame", (cx - xo, yf, zk), (cx + xo, yf, zk), r * 0.8, 10)
    sw = w - 10
    mb.box("chair_wood", cx - sw / 2, y0 + 5, z0 + sh - 12, cx + sw / 2, yk, z0 + sh)                 # 座面 t12
    mb.box("chair_wood", cx - sw / 2, y0, z0 + sh - 20, cx + sw / 2, y0 + 10, z0 + sh - 8)           # 前縁を丸めた見え方
    # 背板: 3 分割で横方向の湾曲を近似
    ys = ykink + (ytop - ykink) * ((z0 + 685 - zk) / (z0 + Ht - zk))
    bw = w - 10
    seg = [(-bw / 2, -bw / 6, -8), (-bw / 6, bw / 6, 0), (bw / 6, bw / 2, -8)]
    for u0, u1, dy in seg:
        mb.box("chair_wood", cx + u0, ys + dy - 5, z0 + 600, cx + u1, ys + dy + 5, z0 + 770)


# ====================================================================== その他
def mirror(mb, rect, z0, H, ceil_z, floor_z):
    x0, y0, x1, y1 = rect
    mb.box("mirror", x0, y0, z0, x1, y1, z0 + H)
    for xx in (x0 - 30, x1):
        mb.box("steel_black", xx, y0, floor_z, xx + 30, y1, ceil_z)
    mb.box("steel_black", x0 - 30, y0, z0 - 30, x1 + 30, y1, z0)
    mb.box("steel_black", x0 - 30, y0, z0 + H, x1 + 30, y1, z0 + H + 30)


def screen_panel(mb, rect, z0, H):
    x0, y0, x1, y1 = rect
    mb.box("screen", x0, y0, z0, x1, y1, z0 + H)
    f = 25
    mb.box("steel_black", x0, y1, z0, x1, y1 + 6, z0 + f)
    mb.box("steel_black", x0, y1, z0 + H - f, x1, y1 + 6, z0 + H)
    mb.box("steel_black", x0, y1, z0 + f, x0 + f, y1 + 6, z0 + H - f)
    mb.box("steel_black", x1 - f, y1, z0 + f, x1, y1 + 6, z0 + H - f)


def art_panel(mb, rect, z0, H):
    x0, y0, x1, y1 = rect
    mb.box("art_bg", x0, y0, z0, x1, y1, z0 + H)
    # 西向きの面（x0 側）に、からしとオリーブの面を重ねる
    h = H
    w = y1 - y0
    mb.box("art", x0 - 2, y0 + w * 0.10, z0 + h * 0.12, x0, y0 + w * 0.55, z0 + h * 0.70)
    mb.box("art_olive", x0 - 2, y0 + w * 0.45, z0 + h * 0.30, x0, y0 + w * 0.90, z0 + h * 0.88)
    mb.box("art", x0 - 3, y0 + w * 0.45, z0 + h * 0.30, x0 - 1, y0 + w * 0.55, z0 + h * 0.70)


def hang_pole(mb, rect, z_pole, z_ceil):
    x0, y0, x1, y1 = rect[0], rect[1], rect[2], rect[3]
    for yy in (y0, y1):
        mb.tube("stainless", (x0, yy, z_pole), (x1, yy, z_pole), 15, 12)
        for xx in (x0 + 100, x1 - 100):
            mb.tube("stainless", (xx, yy, z_pole), (xx, yy, z_ceil), 6, 8)


def tub(mb, rect, z0, H):
    x0, y0, x1, y1 = rect
    t = 80
    mb.box("tub", x0, y0, z0, x1, y1, z0 + 150)
    mb.box("tub", x0, y0, z0 + 150, x1, y0 + t, z0 + H)
    mb.box("tub", x0, y1 - t, z0 + 150, x1, y1, z0 + H)
    mb.box("tub", x0, y0 + t, z0 + 150, x0 + t, y1 - t, z0 + H)
    mb.box("tub", x1 - t, y0 + t, z0 + 150, x1, y1 - t, z0 + H)


def shower_unit(mb, rect, z0, H):
    x0, y0, x1, y1 = rect
    mb.box("tub", x0, y0, z0, x1, y1, z0 + 100)
    mb.box("wet_panel", x0, y1 - 20, z0 + 100, x1, y1, z0 + H)
    mb.box("wet_panel", x0, y0, z0 + 100, x0 + 20, y1, z0 + H)
    mb.tube("stainless", ((x0 + x1) / 2, y1 - 40, z0 + 1100), ((x0 + x1) / 2, y1 - 40, z0 + 1900), 10, 8)
    mb.tube("stainless", ((x0 + x1) / 2, y1 - 40, z0 + 1900), ((x0 + x1) / 2, y1 - 160, z0 + 1900), 10, 8)
    mb.tube("stainless", ((x0 + x1) / 2, y1 - 160, z0 + 1900), ((x0 + x1) / 2, y1 - 200, z0 + 1860), 40, 12)


def machine_box(mb, rect, z0, H):
    x0, y0, x1, y1 = rect
    mb.box("machine", x0, y0, z0, x1, y1, z0 + H)
    mb.box("steel_black", x0 + 100, y0, z0 + H - 400, x1 - 100, y0 + 1, z0 + H - 100)


# ====================================================================== ジム機器（既存の矩形の内側に収める）
def gym_equipment(mb, name, r, H, z0):
    x0, y0, x1, y1 = r
    F, P, S = "gym_frame", "gym_pad", "steel_black"
    if name.startswith("パワーラック"):
        mb.box(P, x0, y0, z0, x1, y1, z0 + 40)                                       # デッドリフト台
        px0, px1 = x0 + 250, x1 - 250
        py0, py1 = y1 - 750, y1 - 120
        for xx in (px0, px1 - 75):
            for yy in (py0, py1 - 75):
                mb.box(F, xx, yy, z0 + 40, xx + 75, yy + 75, z0 + H)
        for yy in (py0, py1 - 75):
            mb.box(F, px0, yy, z0 + H - 75, px1, yy + 75, z0 + H)                    # 横梁（東西）
        for xx in (px0, px1 - 75):
            mb.box(F, xx, py0, z0 + H - 75, xx + 75, py1, z0 + H)                    # 横梁（南北）
            mb.tube(F, (xx + 37, py0, z0 + 40 + 800), (xx + 37, py1, z0 + 40 + 800), 15, 10)   # セーフティバー
        mb.tube(S, (x0 + 80, (py0 + py1) / 2 - 150, z0 + 1350), (x1 - 80, (py0 + py1) / 2 - 150, z0 + 1350), 14, 10)   # バーベル
        for xx in (x0 + 140, x0 + 175, x1 - 175, x1 - 140):
            mb.tube(S, (xx, (py0 + py1) / 2 - 150, z0 + 1350), (xx + 26, (py0 + py1) / 2 - 150, z0 + 1350), 225, 20)
    elif name.startswith("トレッドミル"):
        cx = (x0 + x1) / 2
        mb.box(S, x0 + 40, y0 + 480, z0 + 130, x1 - 40, y1 - 20, z0 + 330)         # ベルト
        mb.box(F, x0 + 20, y0 + 480, z0 + 130, x0 + 40, y1 - 20, z0 + 360)
        mb.box(F, x1 - 40, y0 + 480, z0 + 130, x1 - 20, y1 - 20, z0 + 360)
        mb.box(F, x0 + 20, y0 + 20, z0 + 130, x1 - 20, y0 + 480, z0 + 560)         # モーターカバー（前）
        for xx in (x0 + 45, x1 - 45):
            mb.tube(F, (xx, y0 + 300, z0 + 560), (xx, y0 + 300, z0 + 1350), 16, 10)
            mb.tube(F, (xx, y0 + 300, z0 + 1000), (xx, y0 + 1400, z0 + 1000), 16, 10)  # 手すり（後方へ伸びる）
        mb.hexa(S, [(x0 + 80, y0 + 250, z0 + 1150), (x1 - 80, y0 + 250, z0 + 1150), (x0 + 80, y0 + 300, z0 + 1450), (x1 - 80, y0 + 300, z0 + 1450),
                    (x0 + 80, y0 + 330, z0 + 1150), (x1 - 80, y0 + 330, z0 + 1150), (x0 + 80, y0 + 380, z0 + 1450), (x1 - 80, y0 + 380, z0 + 1450)])
    elif name.startswith("クロス"):
        cx = (x0 + x1) / 2
        mb.box(F, x0 + 30, y0 + 500, z0 + 60, x1 - 30, y1 - 30, z0 + 300)
        mb.box(F, x0 + 150, y0 + 30, z0 + 60, x1 - 150, y0 + 500, z0 + 260)
        mb.tube(F, (cx, y0 + 300, z0 + 260), (cx, y0 + 380, z0 + 1500), 40, 12)
        mb.box(S, cx - 150, y0 + 330, z0 + 1450, cx + 150, y0 + 460, z0 + 1700)
        for xx in (x0 + 60, x1 - 60):
            mb.tube(F, (xx, y0 + 330, z0 + 1450), (xx, y0 + 900, z0 + 1000), 18, 10)
            mb.box(P, xx - 70, y0 + 800 + (0 if xx < cx else 300), z0 + 300, xx + 70, y0 + 1250 + (0 if xx < cx else 300), z0 + 330)
    elif name.startswith("ダンベル"):
        for xx in (x0 + 40, x1 - 80):
            for yy in (y0 + 40, y1 - 80):
                mb.box(F, xx, yy, z0, xx + 40, yy + 40, z0 + 780)
        for zz, tilt in ((z0 + 430, 0), (z0 + 760, 0)):
            mb.box(F, x0 + 20, y0 + 20, zz, x1 - 20, y1 - 20, zz + 20)
            mb.box(F, x0 + 20, y0 + 20, zz + 20, x1 - 20, y0 + 40, zz + 70)
            mb.box(F, x0 + 20, y1 - 40, zz + 20, x1 - 20, y1 - 20, zz + 70)
            n = 14
            pit = (y1 - y0 - 120) / n
            for k in range(n):
                yy = y0 + 60 + pit * (k + 0.5)
                zc = zz + 20 + 55
                mb.tube(S, (x0 + 60, yy, zc), (x1 - 60, yy, zc), 12, 8)
                for xa in (x0 + 60, x1 - 130):
                    mb.tube(S, (xa, yy, zc), (xa + 70, yy, zc), 55, 10)
    elif name.startswith("ベンチ"):
        cx = (x0 + x1) / 2
        mb.box(P, cx - 190, y0 + 60, z0 + 420, cx + 190, y1 - 60, z0 + 500)
        mb.box(F, cx - 30, y0 + 80, z0 + 300, cx + 30, y1 - 80, z0 + 420)
        for yy in (y0 + 80, y1 - 140):
            mb.box(F, cx - 220, yy, z0, cx + 220, yy + 60, z0 + 60)
            mb.box(F, cx - 30, yy, z0 + 60, cx + 30, yy + 60, z0 + 300)
    elif name.startswith("ラットプル"):
        py = y1 - 100
        for xx in (x0 + 60, x1 - 140):
            mb.box(F, xx, py - 40, z0, xx + 80, py + 40, z0 + H)
        mb.box(F, x0 + 60, py - 40, z0 + H - 80, x1 - 60, py + 40, z0 + H)
        mb.box(S, (x0 + x1) / 2 - 150, py - 70, z0 + 100, (x0 + x1) / 2 + 150, py + 70, z0 + 1500)  # ウエイト
        cx = (x0 + x1) / 2
        mb.tube(S, (cx, py - 100, z0 + H - 80), (cx, py - 600, z0 + 1700), 5, 6)
        mb.tube(F, (cx - 450, py - 600, z0 + 1700), (cx + 450, py - 600, z0 + 1700), 16, 10)
        mb.box(P, cx - 190, py - 900, z0 + 430, cx + 190, py - 540, z0 + 500)
        mb.box(F, cx - 30, py - 900, z0 + 60, cx + 30, py - 540, z0 + 430)
        mb.box(F, cx - 250, py - 900, z0, cx + 250, py - 840, z0 + 60)
        mb.box(F, cx - 250, py - 600, z0, cx + 250, py - 540, z0 + 60)
    elif name.startswith("レッグプレス"):
        cy = (y0 + y1) / 2
        for yy in (y0 + 60, y1 - 100):
            mb.box(F, x0 + 30, yy, z0, x1 - 30, yy + 40, z0 + 60)
            mb.hexa(F, [(x0 + 100, yy, z0 + 60), (x1 - 300, yy, z0 + 60), (x0 + 100, yy + 40, z0 + 60), (x1 - 300, yy + 40, z0 + 60),
                        (x0 + 100, yy, z0 + 260), (x1 - 300, yy, z0 + 760), (x0 + 100, yy + 40, z0 + 260), (x1 - 300, yy + 40, z0 + 760)])
        mb.hexa(P, [(x0 + 120, cy - 280, z0 + 300), (x0 + 700, cy - 280, z0 + 300), (x0 + 120, cy + 280, z0 + 300), (x0 + 700, cy + 280, z0 + 300),
                    (x0 + 120, cy - 280, z0 + 380), (x0 + 700, cy - 280, z0 + 420), (x0 + 120, cy + 280, z0 + 380), (x0 + 700, cy + 280, z0 + 420)])
        mb.box(P, x0 + 60, cy - 280, z0 + 300, x0 + 120, cy + 280, z0 + 900)
        mb.box(S, x1 - 560, cy - 330, z0 + 380, x1 - 480, cy + 330, z0 + 1450)      # 足板
        mb.box(F, x1 - 480, cy - 330, z0 + 380, x1 - 460, cy + 330, z0 + 1450)
    elif name.startswith("ケーブル"):
        for xx in (x0 + 50, x1 - 130):
            for yy in (y1 - 130, y1 - 560):
                mb.box(F, xx, yy, z0, xx + 80, yy + 80, z0 + H)
            mb.box(S, xx - 150, y1 - 520, z0 + 100, xx + 230, y1 - 190, z0 + 1500 if xx < x1 / 2 + x0 / 2 else z0 + 1500)
        mb.box(F, x0 + 50, y1 - 130, z0 + H - 80, x1 - 50, y1 - 50, z0 + H)
        mb.box(F, x0 + 50, y1 - 560, z0 + H - 80, x1 - 50, y1 - 480, z0 + H)
        for xx in (x0 + 90, x1 - 90):
            mb.tube(S, (xx, y1 - 300, z0 + H - 60), (xx, y1 - 300, z0 + 1300), 4, 6)
            mb.tube(F, (xx - 70, y1 - 300, z0 + 1300), (xx + 70, y1 - 300, z0 + 1300), 12, 8)
    elif name.startswith("ストレッチ"):
        mb.box(P, x0, y0, z0, x1, y1, z0 + H)
    else:
        mb.box(F, x0, y0, z0, x1, y1, z0 + H)
