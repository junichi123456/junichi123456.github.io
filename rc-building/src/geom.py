"""建物モデルの基本要素（Box・壁・開口・室）と矩形分解ユーティリティ。

座標系: X=東, Y=北, Z=上。単位 mm。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path



# ---------------------------------------------------------------- primitives
@dataclass
class Box:
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float
    cat: str            # column / beam / slab / wall / partition / parapet / glass / door / stair / footing / fg / roof
    mat: str = "concrete"   # concrete / lgs / glass / door / sash
    level: str = ""
    tag: str = ""

    def contains_z(self, z):
        return self.z0 < z < self.z1


@dataclass
class Opening:
    kind: str           # window / door
    u0: float           # 壁軸方向の範囲（絶対座標）
    u1: float
    z0: float           # 絶対高さ
    z1: float
    floor: str
    side: str           # S/N/E/W（外壁）または I（内部）
    name: str = ""      # 引違い窓・片開き戸 など
    operation: str = "sliding"   # sliding / swing / auto / fixed / ev
    fire: bool = False           # 防火設備
    smoke_seal: bool = False     # 遮煙性能
    exterior: bool = False
    alt_entry: bool = False      # 非常用進入口に代わる開口（代替進入口）
    swing: int = 1               # 開き方向（壁法線の +1/-1 側）
    hinge: int = 0               # 吊元（0: u0 側, 1: u1 側）
    label: str = ""              # 建具記号（AW-1 等、自動採番）
    wall: "Wall" = None

    @property
    def width(self):
        return self.u1 - self.u0

    @property
    def height(self):
        return self.z1 - self.z0


@dataclass
class Wall:
    axis: str           # 'x'（X方向に延びる壁, 座標 c は y）/ 'y'
    c: float            # 壁芯座標
    a: float            # 始点（軸方向）
    b: float            # 終点
    t: float
    z0: float
    z1: float
    cat: str = "wall"   # wall / partition / parapet / glasswall
    mat: str = "concrete"
    floor: str = ""
    side: str = "I"
    openings: list = field(default_factory=list)

    def add(self, op: Opening):
        op.wall = self
        self.openings.append(op)
        return op

    def rect(self, u0, u1, v0, v1):
        """壁座標系 (u: 軸方向, v: 高さ) → Box 座標。"""
        h = self.t / 2
        if self.axis == "x":
            return (u0, self.c - h, v0, u1, self.c + h, v1)
        return (self.c - h, u0, v0, self.c + h, u1, v1)


@dataclass
class Room:
    name: str
    floor: str
    rect: tuple          # 壁芯による矩形 (x0, y0, x1, y1)
    habitable: bool = False
    label_at: tuple = None
    ch: float = 0
    area_override: float = None

    @property
    def area(self):
        if self.area_override is not None:
            return self.area_override
        x0, y0, x1, y1 = self.rect
        return (x1 - x0) * (y1 - y0) / 1e6


@dataclass
class Flight:
    floor: str
    x0: float
    x1: float
    y_start: float       # 昇り始めの踏面端
    direction: int       # +1: 北へ昇る, -1: 南へ昇る
    z_start: float
    risers: int          # この段の蹴上数（踊場/床への最後の1段を含む）
    riser: float
    tread: float


# ------------------------------------------------------------ rectangle utils
def decompose(outer, holes):
    """矩形 outer から矩形 holes を除いた領域を矩形群に分解（帯状に統合）。"""
    x0, y0, x1, y1 = outer
    hs = [(max(a, x0), max(b, y0), min(c, x1), min(d, y1)) for a, b, c, d in holes]
    hs = [h for h in hs if h[0] < h[2] and h[1] < h[3]]
    xs = sorted({x0, x1, *[h[0] for h in hs], *[h[2] for h in hs]})
    ys = sorted({y0, y1, *[h[1] for h in hs], *[h[3] for h in hs]})
    strips = []   # x 方向の帯ごとに y の実体区間
    for xa, xb in zip(xs, xs[1:]):
        xm = (xa + xb) / 2
        solid = []
        for ya, yb in zip(ys, ys[1:]):
            ym = (ya + yb) / 2
            if any(h[0] < xm < h[2] and h[1] < ym < h[3] for h in hs):
                continue
            if solid and solid[-1][1] == ya:
                solid[-1][1] = yb
            else:
                solid.append([ya, yb])
        strips.append([xa, xb, [tuple(s) for s in solid]])
    merged = []
    for s in strips:
        if merged and merged[-1][2] == s[2] and merged[-1][1] == s[0]:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    out = []
    for xa, xb, solid in merged:
        for ya, yb in solid:
            out.append((xa, ya, xb, yb))
    return out


# ------------------------------------------------------------------ building
