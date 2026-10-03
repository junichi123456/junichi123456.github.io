"""建物モデル（単一の設計データ）。

仕様書 spec.yaml から通り芯・レベル・部材・開口・室を生成し、
2D 図面・法規チェック・3D モデルはすべてこのモデルから導出する。

座標系: X=東, Y=北, Z=上。原点は X1・Y1 通り芯交点、Z=0 は設計GL。単位 mm。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml


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
class Building:
    def __init__(self, spec_path: Path):
        self.spec = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
        s = self.spec
        b = s["building"]
        st = s["structure"]
        self.ox, self.oy = b["origin"]
        self.gx = [0.0]
        for d in b["grid_x"]:
            self.gx.append(self.gx[-1] + d)
        self.gy = [0.0]
        for d in b["grid_y"]:
            self.gy.append(self.gy[-1] + d)
        self.gx_names = [f"X{i + 1}" for i in range(len(self.gx))]
        self.gy_names = [f"Y{i + 1}" for i in range(len(self.gy))]
        self.W = self.gx[-1]
        self.D = self.gy[-1]

        # レベル
        self.floors = list(b["story_heights"].keys())          # 1F 2F 3F
        self.fl = {}
        z = b["fl_1f"]
        for f in self.floors:
            self.fl[f] = z
            z += b["story_heights"][f]
        self.fl["RF"] = z
        self.H = dict(b["story_heights"])
        ph = b["penthouse"]
        self.fl["PHRF"] = self.fl["RF"] + ph["height"]
        self.parapet_top = self.fl["RF"] + b["parapet"]
        self.ph_parapet_top = self.fl["PHRF"] + ph["parapet"]
        self.ev_top = self.fl["RF"] + ph["ev_overhead"]
        self.ch = dict(s["requirements"]["ceiling_height"])

        c1 = st["column"]["C1"]
        g1 = st["girder"]["G1"]
        fg = st["fgirder"]["FG1"]
        f1 = st["footing"]["F1"]
        self.col = (c1["b"], c1["d"])
        self.gb, self.gd = g1["b"], g1["d"]
        self.fgb, self.fgd = fg["b"], fg["d"]
        self.fb, self.ft = f1["b"], f1["t"]
        self.slab_t = st["slab"]["S1"]["t"]
        self.wt = st["wall"]["W20"]["t"]
        self.pt = st["wall"]["W_lgs"]["t"]
        self.fg_top = self.fl["1F"]
        self.fg_bot = self.fg_top - self.fgd
        self.fdn_bot = self.fg_bot - self.ft

        # 平面計画（コア）
        self.stair = (15000.0, 6000.0, 18000.0, 12000.0)       # 階段室（壁芯）
        self.ev = (15800.0, 3800.0, 18000.0, 6000.0)           # EV シャフト（壁芯）
        self.wc = (12000.0, 8000.0, 15000.0, 12000.0)          # 便所ブロック
        self.windbreak = (7000.0, 0.0, 11000.0, 2500.0)        # 風除室（1F）

        self.walls: list[Wall] = []
        self.boxes: list[Box] = []
        self.rooms: list[Room] = []
        self.flights: list[Flight] = []
        self.landings: list[tuple] = []
        self._build()

    # ------------------------------------------------------------ helpers
    def site_rect(self):
        s = self.spec["site"]
        return (-self.ox, -self.oy, -self.ox + s["width"], -self.oy + s["depth"])

    def road_rect(self):
        x0, y0, x1, _ = self.site_rect()
        w = self.spec["site"]["road"]["width"]
        return (x0 - 3000, y0 - w, x1 + 3000, y0)

    def next_level(self, f):
        order = self.floors + ["RF"]
        return order[order.index(f) + 1]

    def floor_of_z(self, z):
        for f in self.floors:
            if self.fl[f] <= z < self.fl[self.next_level(f)]:
                return f
        return "RF"

    # ------------------------------------------------------------- build
    def _build(self):
        self._structure()
        self._exterior_walls()
        self._core_walls()
        self._penthouse()
        self._stairs()
        self._rooms()
        self._label_openings()
        for w in self.walls:
            self.boxes.extend(self._wall_boxes(w))

    def _structure(self):
        cb, cd = self.col
        hb = cb / 2
        # 柱（基礎上端〜R階）
        for x in self.gx:
            for y in self.gy:
                self.boxes.append(Box(x - hb, y - hb, self.fg_bot, x + hb, y + hb, self.fg_top, "column", level="FDN", tag="C1"))
                for f in self.floors:
                    self.boxes.append(Box(x - hb, y - hb, self.fl[f], x + hb, y + hb,
                                          self.fl[self.next_level(f)], "column", level=f, tag="C1"))
                fb = self.fb / 2
                self.boxes.append(Box(x - fb, y - fb, self.fdn_bot, x + fb, y + fb, self.fg_bot, "footing", level="FDN", tag="F1"))
        # 梁・基礎梁
        levels = [("FDN", self.fg_top, self.fgb, self.fgd, "fg", "FG1")] + [
            (lv, self.fl[lv], self.gb, self.gd, "beam", "G1") for lv in self.floors[1:] + ["RF"]]
        for lv, ztop, bw, bd, cat, tag in levels:
            for y in self.gy:
                for xa, xb in zip(self.gx, self.gx[1:]):
                    self.boxes.append(Box(xa + hb, y - bw / 2, ztop - bd, xb - hb, y + bw / 2, ztop, cat, level=lv, tag=tag))
            for x in self.gx:
                for ya, yb in zip(self.gy, self.gy[1:]):
                    self.boxes.append(Box(x - bw / 2, ya + hb, ztop - bd, x + bw / 2, yb - hb, ztop, cat, level=lv, tag=tag))
        # 階段・EV 壁下の基礎梁（FB1）
        for (x0, y0, x1, y1) in [(15000 - 150, 6000, 15000 + 150, 12000), (15800 - 150, 3800, 15800 + 150, 6000),
                                 (15800, 3800 - 150, 18000, 3800 + 150)]:
            self.boxes.append(Box(x0, y0, self.fg_top - 1000, x1, y1, self.fg_top, "fg", level="FDN", tag="FB1"))
        # スラブ
        e = self.wt / 2
        outer = (-e, -e, self.W + e, self.D + e)
        sx0, sy0, sx1, sy1 = self.stair
        stair_hole = (sx0 + e, 7500.0, sx1 - e, sy1 - e)
        ex0, ey0, ex1, ey1 = self.ev
        ev_hole = (ex0 + e, ey0 + e, ex1 - e, ey1 - e)
        for lv in self.floors + ["RF"]:
            holes = [ev_hole] + ([stair_hole] if lv != "1F" else [])
            for r in decompose(outer, holes):
                self.boxes.append(Box(r[0], r[1], self.fl[lv] - self.slab_t, r[2], r[3], self.fl[lv], "slab", level=lv, tag="S1"))
        # EV ピット
        self.boxes.append(Box(ex0 - e, ey0 - e, self.fl["1F"] - 1400, ex1 + e, ey1 + e, self.fl["1F"] - 1200, "slab", level="FDN", tag="EVピット"))

    def _exterior_walls(self):
        hb = self.col[0] / 2
        t = self.wt
        W, D = self.W, self.D
        for f in self.floors:
            z0, z1 = self.fl[f], self.fl[self.next_level(f)]
            fl = self.fl[f]
            ch = self.ch[f]
            win_h = 2000 if f == "1F" else 1800
            head = fl + ch
            for (axis, c, side) in [("x", 0.0, "S"), ("x", D, "N"), ("y", 0.0, "W"), ("y", W, "E")]:
                grid = self.gx if axis == "x" else self.gy
                for gi, (a, b_) in enumerate(zip(grid, grid[1:])):
                    w = Wall(axis, c, a + hb, b_ - hb, t, z0, z1, "wall", floor=f, side=side)
                    self.walls.append(w)
                    mid = (a + b_) / 2
                    fire = self._in_fire_spread(side, f)
                    if side == "S":
                        if f == "1F" and gi == 1:
                            w.add(Opening("door", 8000, 10000, fl, fl + 2400, f, side, "自動ドア（両引き）", "auto", exterior=True))
                        else:
                            w.add(Opening("window", mid - 2000, mid + 2000, head - win_h, head, f, side, "引違い窓",
                                          fire=fire, exterior=True, alt_entry=(f == "3F")))
                    elif side == "N":
                        if gi < 2:
                            w.add(Opening("window", mid - 2000, mid + 2000, head - win_h, head, f, side, "引違い窓", fire=fire, exterior=True))
                        else:
                            # 階段室 窓（踊場上部）
                            zl = fl + self.H[f] / 2
                            w.add(Opening("window", 16100, 17400, zl + 200, zl + 1000, f, side, "すべり出し窓", fire=fire, exterior=True))
                    elif side == "W":
                        w.add(Opening("window", mid - 2000, mid + 2000, head - win_h, head, f, side, "引違い窓", fire=fire, exterior=True))
                    elif side == "E":
                        if gi == 0:
                            w.add(Opening("window", 900, 3300, head - win_h, head, f, side, "引違い窓", fire=fire, exterior=True))
                        elif f == "1F":
                            w.add(Opening("door", 6400, 7300, fl, fl + 2000, f, side, "鋼製片開き戸", "swing", fire=fire,
                                          exterior=True, swing=+1, hinge=1))
        # パラペット（塔屋部分を除く）
        z0, z1 = self.fl["RF"], self.parapet_top
        pe = t / 2
        segs = [("x", 0.0, -pe, W + pe), ("y", 0.0, -pe, D + pe), ("x", D, -pe, 15000.0 - pe),
                ("y", W, -pe, 3800.0 - pe)]
        for axis, c, a, b_ in segs:
            self.walls.append(Wall(axis, c, a, b_, t, z0, z1, "parapet", floor="RF", side="P"))

    def _in_fire_spread(self, side, floor):
        """延焼のおそれのある部分（隣地境界線・道路中心線から 1階3m／2階以上5m）に外壁面が入るか。"""
        lim = 3000 if floor == "1F" else 5000
        x0, y0, x1, y1 = self.site_rect()
        e = self.wt / 2
        road_c = y0 - self.spec["site"]["road"]["width"] / 2
        d = {"W": 0 - e - x0, "E": x1 - (self.W + e), "N": y1 - (self.D + e), "S": 0 - e - road_c}[side]
        return d < lim

    def fire_spread_distance(self, side):
        x0, y0, x1, y1 = self.site_rect()
        e = self.wt / 2
        road_c = y0 - self.spec["site"]["road"]["width"] / 2
        return {"W": 0 - e - x0, "E": x1 - (self.W + e), "N": y1 - (self.D + e), "S": 0 - e - road_c}[side]

    def _core_walls(self):
        t, pt = self.wt, self.pt
        sx0, sy0, sx1, sy1 = self.stair
        ex0, ey0, ex1, ey1 = self.ev
        hb = self.col[0] / 2
        for f in self.floors:
            fl = self.fl[f]
            z0, z1 = fl, self.fl[self.next_level(f)]
            zs = z1 - self.slab_t
            # 階段室（RC）
            w = Wall("y", sx0, sy0 - t / 2, sy1 - t / 2, t, z0, z1, "wall", floor=f)
            w.add(Opening("door", 6300, 7200, fl, fl + 2000, f, "I", "鋼製片開き戸", "swing", fire=True, smoke_seal=True,
                          swing=+1, hinge=0))
            self.walls.append(w)
            self.walls.append(Wall("x", sy0, sx0 + t / 2, sx1 - hb, t, z0, z1, "wall", floor=f))
            # EV シャフト（RC）
            w = Wall("y", ex0, ey0 - t / 2, ey1 - t / 2, t, z0 if f != "1F" else self.fg_bot, z1, "wall", floor=f)
            w.add(Opening("door", 4500, 5400, fl, fl + 2100, f, "I", "EV乗場戸（遮煙）", "ev", fire=True, smoke_seal=True))
            self.walls.append(w)
            self.walls.append(Wall("x", ey0, ex0 + t / 2, ex1 - t / 2, t, z0 if f != "1F" else self.fg_bot, z1, "wall", floor=f))
            # 便所まわり（LGS）
            wx0, wy0, wx1, wy1 = self.wc
            w = Wall("y", wx0, wy0 - pt / 2, wy1 - hb, pt, z0, zs, "partition", "lgs", floor=f)
            self.walls.append(w)
            ws = Wall("x", wy0, wx0 - pt / 2, wx1 - t / 2, pt, z0, zs, "partition", "lgs", floor=f)
            self.walls.append(ws)
            if f == "1F":
                ws.add(Opening("door", 12500, 13500, fl, fl + 2000, f, "I", "木製引戸", "sliding"))
                w.add(Opening("door", 10700, 11500, fl, fl + 2000, f, "I", "木製片開き戸", "swing", swing=+1, hinge=1))
                self.walls.append(Wall("x", 10400, wx0 + pt / 2, wx1 - t / 2, pt, z0, zs, "partition", "lgs", floor=f))
                # 風除室（ガラススクリーン）
                bx0, by0, bx1, by1 = self.windbreak
                g = Wall("x", by1, bx0, bx1, 60, z0, fl + 2800, "glasswall", "glass", floor=f)
                g.add(Opening("door", 8000, 10000, fl, fl + 2400, f, "I", "自動ドア（両引き）", "auto"))
                self.walls.append(g)
                self.walls.append(Wall("y", bx0, t / 2, by1, 60, z0, fl + 2800, "glasswall", "glass", floor=f))
                self.walls.append(Wall("y", bx1, t / 2, by1, 60, z0, fl + 2800, "glasswall", "glass", floor=f))
            else:
                ws.add(Opening("door", 12350, 13150, fl, fl + 2000, f, "I", "木製片開き戸", "swing", swing=+1, hinge=0))
                ws.add(Opening("door", 13850, 14650, fl, fl + 2000, f, "I", "木製片開き戸", "swing", swing=+1, hinge=1))
                self.walls.append(Wall("y", 13500, wy0 + pt / 2, wy1 - t / 2, pt, z0, zs, "partition", "lgs", floor=f))

    def _penthouse(self):
        t = self.wt
        sx0, sy0, sx1, sy1 = self.stair
        ex0, ey0, ex1, ey1 = self.ev
        r = self.fl["RF"]
        p = self.fl["PHRF"]
        w = Wall("y", sx0, sy0 - t / 2, sy1 + t / 2, t, r, p, "wall", floor="PH", side="W")
        w.add(Opening("door", 6300, 7200, r + 150, r + 2150, "PH", "W", "鋼製片開き戸", "swing", fire=False,
                      exterior=True, swing=-1, hinge=0))
        self.walls.append(w)
        self.walls.append(Wall("y", sx1, sy0 - t / 2, sy1 + t / 2, t, r, p, "wall", floor="PH", side="E"))
        self.walls.append(Wall("x", sy1, sx0 + t / 2, sx1 - t / 2, t, r, p, "wall", floor="PH", side="N"))
        self.walls.append(Wall("x", sy0, sx0 + t / 2, sx1 - t / 2, t, r, p, "wall", floor="PH", side="I"))
        # EV オーバーヘッド
        top = self.ev_top
        self.walls.append(Wall("y", ex0, ey0 - t / 2, ey1 - t / 2, t, r, top, "wall", floor="PH", side="W"))
        self.walls.append(Wall("x", ey0, ex0 - t / 2, ex1 + t / 2, t, r, top, "wall", floor="PH", side="S"))
        self.walls.append(Wall("y", ex1, ey0 + t / 2, ey1 - t / 2, t, r, top, "wall", floor="PH", side="E"))
        e = t / 2
        self.boxes.append(Box(sx0 - e, sy0 - e, p - self.slab_t, sx1 + e, sy1 + e, p, "slab", level="PH", tag="S1"))
        self.boxes.append(Box(ex0 - e, ey0 - e, top - 200, ex1 + e, ey1 - e, top, "slab", level="PH", tag="EV頂部"))
        # 塔屋パラペット
        pp = self.ph_parapet_top
        for axis, c, a, b_ in [("x", sy0, sx0 - e, sx1 + e), ("x", sy1, sx0 - e, sx1 + e),
                               ("y", sx0, sy0 + e, sy1 - e), ("y", sx1, sy0 + e, sy1 - e)]:
            self.walls.append(Wall(axis, c, a, b_, 150, p, pp, "parapet", floor="PH", side="P"))

    def _stairs(self):
        sp = self.spec["requirements"]["stair"]
        sx0, sy0, sx1, sy1 = self.stair
        e = self.wt / 2
        ix0, ix1 = sx0 + e, sx1 - e
        gap = 200
        wflight = (ix1 - ix0 - gap) / 2
        self.stair_flight_width = wflight
        y_start = 7500.0
        for f in self.floors:
            H = self.H[f]
            half = math.ceil((H / 2) / sp["max_riser"])
            r = H / (2 * half)
            T = sp["min_tread"]
            fl = self.fl[f]
            # 昇り1（西側, 北へ）
            fa = Flight(f, ix0, ix0 + wflight, y_start, +1, fl, half, r, T)
            ya_end = y_start + (half - 1) * T
            # 昇り2（東側, 南へ）
            fb = Flight(f, ix1 - wflight, ix1, ya_end, -1, fl + H / 2, half, r, T)
            self.flights += [fa, fb]
            zl = fl + H / 2
            self.landings.append((f, ix0, ya_end, ix1, sy1 - e, zl))
            self.boxes.append(Box(ix0, ya_end, zl - 200, ix1, sy1 - e, zl, "stair", level=f, tag="踊場"))
            for fl_ in (fa, fb):
                for i in range(1, fl_.risers):
                    ztop = fl_.z_start + i * r
                    if fl_.direction > 0:
                        y0, y1 = fl_.y_start + (i - 1) * T, fl_.y_start + i * T
                    else:
                        y0, y1 = fl_.y_start - i * T, fl_.y_start - (i - 1) * T
                    self.boxes.append(Box(fl_.x0, y0, ztop - r - 160, fl_.x1, y1, ztop, "stair", level=f, tag="段"))
        self.stair_info = {}
        for f in self.floors:
            half = math.ceil((self.H[f] / 2) / sp["max_riser"])
            self.stair_info[f] = dict(risers=2 * half, riser=self.H[f] / (2 * half), tread=sp["min_tread"],
                                      width=wflight, landing_h=self.H[f] / 2,
                                      landing_depth=(sy1 - e) - (y_start + (half - 1) * sp["min_tread"]))

    def _rooms(self):
        W, D = self.W, self.D
        st, ev, wc, wb = self.stair, self.ev, self.wc, self.windbreak
        A = lambda r: (r[2] - r[0]) * (r[3] - r[1]) / 1e6
        for f in self.floors:
            ch = self.ch[f]
            core = A(st) + A(ev) + A(wc) + (A(wb) if f == "1F" else 0)
            self.rooms.append(Room("事務室", f, (0, 0, W, D), True, (4500, 7800), ch, area_override=W * D / 1e6 - core))
            self.rooms.append(Room("階段室", f, st, False, (16500, 11250)))
            self.rooms.append(Room("EV(11人乗)", f, ev, False, (16900, 5300)))
            if f == "1F":
                self.rooms.append(Room("多機能WC", f, (12000, 8000, 15000, 10400), False, (13500, 9300)))
                self.rooms.append(Room("倉庫", f, (12000, 10400, 15000, 12000), False, (13500, 11200)))
                self.rooms.append(Room("風除室", f, wb, False, (9000, 1250)))
            else:
                self.rooms.append(Room("WC(男)", f, (12000, 8000, 13500, 12000), False, (12750, 10300)))
                self.rooms.append(Room("WC(女)", f, (13500, 8000, 15000, 12000), False, (14250, 10300)))
        self.rooms.append(Room("階段室(塔屋)", "PH", st, False, (16500, 9000)))

    def _label_openings(self):
        """開口を仕様ごとに分類し建具記号を自動採番（AW: アルミ窓, AD: アルミ/自動扉, SD: 鋼製扉, WD: 木製扉）。"""
        groups = {}
        for w in self.walls:
            for op in w.openings:
                if op.operation == "ev":
                    op.label = "EV"
                    continue
                if op.kind == "window":
                    prefix = "AW"
                elif op.operation == "auto":
                    prefix = "AD"
                elif op.name.startswith("鋼製"):
                    prefix = "SD"
                else:
                    prefix = "WD"
                key = (prefix, op.name, round(op.width), round(op.height), op.fire, op.smoke_seal, op.exterior)
                groups.setdefault(key, []).append(op)
        counters = {}
        self.fittings = []
        for key in sorted(groups, key=lambda k: (k[0], -k[2] * k[3], k[4])):
            prefix = key[0]
            counters[prefix] = counters.get(prefix, 0) + 1
            label = f"{prefix}-{counters[prefix]}"
            for op in groups[key]:
                op.label = label
            self.fittings.append(dict(label=label, name=key[1], w=key[2], h=key[3], fire=key[4], smoke=key[5],
                                      exterior=key[6], count=len(groups[key]),
                                      floors=sorted({o.floor for o in groups[key]}),
                                      alt_entry=any(o.alt_entry for o in groups[key])))

    # ------------------------------------------------------- wall → boxes
    def _wall_boxes(self, w: Wall):
        holes = [(op.u0, op.z0, op.u1, op.z1) for op in w.openings]
        out = []
        for u0, v0, u1, v1 in decompose((w.a, w.z0, w.b, w.z1), holes):
            x0, y0, z0, x1, y1, z1 = w.rect(u0, u1, v0, v1)
            out.append(Box(x0, y0, z0, x1, y1, z1, w.cat, w.mat, level=w.floor))
        # 建具（ガラス・扉）を薄い板として配置
        for op in w.openings:
            if op.kind == "window" or op.operation == "auto":
                th = 30
                cat, mat = "glass", "glass"
            else:
                th = 50
                cat, mat = "door", "door"
            h = th / 2
            if w.axis == "x":
                out.append(Box(op.u0, w.c - h, op.z0, op.u1, w.c + h, op.z1, cat, mat, level=w.floor, tag=op.label))
            else:
                out.append(Box(w.c - h, op.u0, op.z0, w.c + h, op.u1, op.z1, cat, mat, level=w.floor, tag=op.label))
        return out

    # -------------------------------------------------------------- areas
    def openings(self, floor=None, exterior=None):
        for w in self.walls:
            for op in w.openings:
                if floor and op.floor != floor:
                    continue
                if exterior is not None and op.exterior != exterior:
                    continue
                yield op

    def building_area(self):
        return self.W * self.D / 1e6

    def penthouse_area(self):
        sx0, sy0, sx1, sy1 = self.stair
        ex0, ey0, ex1, ey1 = self.ev
        return ((sx1 - sx0) * (sy1 - sy0) + (ex1 - ex0) * (ey1 - ey0)) / 1e6

    def floor_areas(self):
        a = {f: self.W * self.D / 1e6 for f in self.floors}
        sx0, sy0, sx1, sy1 = self.stair
        a["PH"] = (sx1 - sx0) * (sy1 - sy0) / 1e6
        return a

    def ev_shaft_area(self):
        ex0, ey0, ex1, ey1 = self.ev
        return (ex1 - ex0) * (ey1 - ey0) / 1e6

    def habitable_area(self, f):
        return sum(r.area for r in self.rooms if r.floor == f and r.habitable)
