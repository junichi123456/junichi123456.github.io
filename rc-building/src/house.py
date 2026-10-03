"""河沿要（仮称）— 壁式RC造 2階建て専用住宅のモデル。

spec.yaml（設計条件）と data/site_gsi.json（国土地理院の地図・標高）から、
敷地・外構・建物の要素を生成する。図面・法規チェック・3D はすべてこのモデルから導出する。

座標: mm。原点 = 建物の X1・Y1 壁芯交点。X=東, Y=北, Z=上（Z=0 は設計GL＝南側道路面）。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import yaml
from shapely.geometry import LineString, Point, Polygon

from geom import Box, Opening, Room, Wall, decompose


class Stair:
    def __init__(self, name, x0, x1, y_entry, direction, floor_from, z0, height, riser_n, tread, gap=100):
        self.name = name
        self.x0, self.x1 = x0, x1
        self.y_entry = y_entry          # 昇り口（踏み出し）の Y
        self.direction = direction      # +1: 北へ昇る, -1: 南へ昇る
        self.floor = floor_from
        self.z0 = z0
        self.height = height
        self.n = riser_n
        self.riser = height / riser_n
        self.tread = tread
        self.gap = gap
        half = riser_n // 2
        self.half = half
        self.run = (half - 1) * tread
        w = (x1 - x0 - gap) / 2
        self.width = w
        self.y_turn = y_entry + direction * self.run           # 踊場の手前
        self.landing_depth = None

    def boxes(self, y_end_wall):
        """y_end_wall: 踊場の奥の壁面 Y。"""
        out = []
        d = self.direction
        r, T = self.riser, self.tread
        xa0, xa1 = (self.x0, self.x0 + self.width) if d > 0 else (self.x1 - self.width, self.x1)
        xb0, xb1 = (self.x1 - self.width, self.x1) if d > 0 else (self.x0, self.x0 + self.width)
        for i in range(1, self.half):
            zt = self.z0 + i * r
            ya, yb = sorted([self.y_entry + d * (i - 1) * T, self.y_entry + d * i * T])
            out.append(Box(xa0, ya, zt - r - 150, xa1, yb, zt, "stair", level=self.floor, tag=self.name))
        zl = self.z0 + self.half * r
        y0, y1 = sorted([self.y_turn, y_end_wall])
        self.landing_depth = abs(y_end_wall - self.y_turn)
        out.append(Box(self.x0, y0, zl - 200, self.x1, y1, zl, "stair", level=self.floor, tag=self.name + "踊場"))
        for j in range(1, self.n - self.half):
            zt = zl + j * r
            ya, yb = sorted([self.y_turn - d * (j - 1) * T, self.y_turn - d * j * T])
            out.append(Box(xb0, ya, zt - r - 150, xb1, yb, zt, "stair", level=self.floor, tag=self.name))
        return out

    def footprint(self, y_end_wall):
        y0, y1 = sorted([self.y_entry, y_end_wall])
        return (self.x0, y0, self.x1, y1)


class House:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.spec = yaml.safe_load((self.root / "spec.yaml").read_text(encoding="utf-8"))
        self.gsi = json.loads((self.root / self.spec["site"]["data"]).read_text(encoding="utf-8"))
        s, b = self.spec, self.spec["building"]
        self.ox, self.oy = s["site"]["building_origin_m"]
        self.gl_tp = s["site"]["gl_tp"]
        self.fgl = s["site"]["fgl"]
        self.gx = [0.0]
        for d in b["grid_x"]:
            self.gx.append(self.gx[-1] + d)
        self.gy = [0.0]
        for d in b["grid_y"]:
            self.gy.append(self.gy[-1] + d)
        self.gx_names = [f"X{i + 1}" for i in range(4)]
        self.gy_names = [f"Y{i + 1}" for i in range(4)]
        self.W, self.D = self.gx[-1], self.gy[-1]
        self.t = b["wall_rc"]
        self.ins = b["insulation"] + b["cladding"]
        self.slab_t = b["slab"]
        self.pt = b["partition"]
        self.floors = ["1F", "2F"]
        self.H = dict(b["story_heights"])
        self.fl = {"1F": b["fl_1f"]}
        self.fl["2F"] = self.fl["1F"] + self.H["1F"]
        self.fl["RF"] = self.fl["2F"] + self.H["2F"]
        self.parapet_top = self.fl["RF"] + b["parapet"]
        self.ch = dict(b["ceiling"])
        self.base_t = b["base_slab"]

        self.walls: list[Wall] = []
        self.boxes: list[Box] = []
        self.rooms: list[Room] = []
        self.stairs: list[Stair] = []
        self.ext = {}            # 外構要素（ポリゴン類）
        self._site()
        self._structure()
        self._rooms_and_partitions()
        self._openings_rc()
        self._stairs()
        self._entrance()
        self._exterior()
        self._label_openings()
        for w in self.walls:
            self.boxes.extend(self._wall_boxes(w))

    # ------------------------------------------------------------ site
    def m2mm(self, x, y):
        return ((x - self.ox) * 1000.0, (y - self.oy) * 1000.0)

    def _site(self):
        pts = [self.m2mm(*p) for p in self.gsi["site"]["pts"]]
        self.site_pts = pts
        self.site_kind = self.gsi["site"]["kind"]
        self.site = Polygon(pts)
        n = len(pts)
        self.site_edges = [(pts[i], pts[(i + 1) % n], self.site_kind[i]) for i in range(n)]
        # 辺の分類（北=水路, 東=東側道路, 南=南側道路, 他=隣地）
        cls = []
        for i in range(n):
            if i < 7:
                cls.append("水路")
            elif i == 7:
                cls.append("水路")
            elif i < 13:
                cls.append("東側道路")
            elif i == 13:
                cls.append("南側道路")
            else:
                cls.append("隣地")
        self.edge_class = cls
        self.road_edges = [dict(ft=r["ft"], pts=[self.m2mm(*p) for p in r["pts"]]) for r in self.gsi["road_edges"]]
        self.water = [[self.m2mm(*p) for p in w] for w in self.gsi["water"]]
        blds = [[self.m2mm(*p) for p in bd["pts"]] for bd in self.gsi["buildings"]]
        inside = lambda pts: self.site.contains(Polygon(pts).representative_point())
        self.neighbors = [b for b in blds if not inside(b)]
        self.existing = [b for b in blds if inside(b)]       # 既存建物（解体予定）
        self.contours = [dict(alti=c["alti"], pts=[self.m2mm(*p) for p in c["pts"]]) for c in self.gsi["contours"]]
        d = self.gsi["dem"]
        self._dem = d

    def ground(self, x, y):
        """DEM による地盤高（設計GL基準 mm）。x, y はモデル座標 mm。"""
        d = self._dem
        xm, ym = x / 1000.0 + self.ox, y / 1000.0 + self.oy
        fx, fy = (xm - d["x0"]) / d["step"], (ym - d["y0"]) / d["step"]
        i0, j0 = int(math.floor(fx)), int(math.floor(fy))
        i0 = max(0, min(d["nx"] - 2, i0))
        j0 = max(0, min(d["ny"] - 2, j0))
        tx, ty = fx - i0, fy - j0
        z = d["z"]
        v = (z[j0][i0] * (1 - tx) * (1 - ty) + z[j0][i0 + 1] * tx * (1 - ty)
             + z[j0 + 1][i0] * (1 - tx) * ty + z[j0 + 1][i0 + 1] * tx * ty)
        return (v - self.gl_tp) * 1000.0

    # -------------------------------------------------------- structure
    def _structure(self):
        t, W, D = self.t, self.W, self.D
        e = t / 2
        levels = [("FDN", 0.0, self.fl["1F"]), ("1F", self.fl["1F"], self.fl["2F"]), ("2F", self.fl["2F"], self.fl["RF"])]
        self.rc_walls = {}
        for lv, z0, z1 in levels:
            ws = []
            # 外周
            ws.append(Wall("x", 0.0, -e, W + e, t, z0, z1, "wall", floor=lv, side="S"))
            ws.append(Wall("x", D, -e, W + e, t, z0, z1, "wall", floor=lv, side="N"))
            ws.append(Wall("y", 0.0, e, D - e, t, z0, z1, "wall", floor=lv, side="W"))
            ws.append(Wall("y", W, e, D - e, t, z0, z1, "wall", floor=lv, side="E"))
            # 中央十字（X2・X3・Y2・Y3）
            for x, n in [(self.gx[1], "X2"), (self.gx[2], "X3")]:
                ws.append(Wall("y", x, e, D - e, t, z0, z1, "wall", floor=lv, side=n))
            for y, n in [(self.gy[1], "Y2"), (self.gy[2], "Y3")]:
                ws.append(Wall("x", y, e, W - e, t, z0, z1, "wall", floor=lv, side=n))
            self.rc_walls[lv] = {w.side: w for w in ws}
            self.walls += ws
            # 外断熱＋外装（RC 外側）
            o = e + self.ins / 2
            ins = [Wall("x", -o, -e - self.ins, W + e + self.ins, self.ins, max(z0, self.fgl), z1, "insul", "insul", floor=lv, side="S"),
                   Wall("x", D + o, -e - self.ins, W + e + self.ins, self.ins, max(z0, self.fgl), z1, "insul", "insul", floor=lv, side="N"),
                   Wall("y", -o, -e, D + e, self.ins, max(z0, self.fgl), z1, "insul", "insul", floor=lv, side="W"),
                   Wall("y", W + o, -e, D + e, self.ins, max(z0, self.fgl), z1, "insul", "insul", floor=lv, side="E")]
            for w in ins:
                self.rc_walls[lv]["ins_" + w.side] = w
            self.walls += ins
        # パラペット
        z0, z1 = self.fl["RF"], self.parapet_top
        for w in [Wall("x", 0.0, -e, W + e, t, z0, z1, "parapet", floor="RF", side="S"),
                  Wall("x", D, -e, W + e, t, z0, z1, "parapet", floor="RF", side="N"),
                  Wall("y", 0.0, e, D - e, t, z0, z1, "parapet", floor="RF", side="W"),
                  Wall("y", W, e, D - e, t, z0, z1, "parapet", floor="RF", side="E")]:
            self.walls.append(w)
        o = e + self.ins / 2
        for w in [Wall("x", -o, -e - self.ins, W + e + self.ins, self.ins, z0, z1 + 50, "insul", "insul", floor="RF"),
                  Wall("x", D + o, -e - self.ins, W + e + self.ins, self.ins, z0, z1 + 50, "insul", "insul", floor="RF"),
                  Wall("y", -o, -e, D + e, self.ins, z0, z1 + 50, "insul", "insul", floor="RF"),
                  Wall("y", W + o, -e, D + e, self.ins, z0, z1 + 50, "insul", "insul", floor="RF")]:
            self.walls.append(w)
        # 基礎スラブ（べた基礎）
        self.boxes.append(Box(-e - 500, -e - 500, -self.base_t, W + e + 500, D + e + 500, 0.0, "footing", level="FDN", tag="基礎スラブ"))

    def slab_holes(self, lv):
        if lv == "2F":
            return [s.hole for s in self.stairs]
        return []

    # ------------------------------------------------------------ rooms
    def _room(self, name, floor, rect, habitable=False, label=None, ch=None):
        r = Room(name, floor, rect, habitable, label or ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2),
                 ch or (self.ch.get(floor, 0) if habitable else 0))
        self.rooms.append(r)
        return r

    def _lgs(self, floor, axis, c, a, b_, doors=(), cat="partition"):
        z0 = self.fl[floor]
        z1 = self.fl["2F" if floor == "1F" else "RF"] - self.slab_t
        w = Wall(axis, c, a, b_, self.pt, z0, z1, cat, "lgs", floor=floor, side="I")
        for d in doors:
            u0, u1 = d[0], d[1]
            op = d[2] if len(d) > 2 else "swing"
            sw = d[3] if len(d) > 3 else 1
            hg = d[4] if len(d) > 4 else 0
            name = {"swing": "木製片開き戸", "sliding": "木製引戸", "double": "遮音ドア（両開き）"}[op]
            w.add(Opening("door", u0, u1, z0, z0 + 2000, floor, "I", name, "sliding" if op == "sliding" else "swing",
                          swing=sw, hinge=hg))
        self.walls.append(w)
        return w

    def _rooms_and_partitions(self):
        R, L = self._room, self._lgs
        # ---------------- 1F
        f = "1F"
        R("ジム", f, (125, 11250, 6000, 17125), True)
        R("階段ホール", f, (6250, 11250, 8250, 13125))
        R("機械室（西系統）", f, (8350, 11250, 11000, 14150))
        R("機械室（東系統）", f, (8350, 14250, 11000, 17125))
        L(f, "y", 8300, 11250, 17125, [(11500, 12300, "swing", -1, 0)])
        L(f, "x", 14200, 8350, 11000, [(9000, 9800, "swing", 1, 0)])
        self.room_A = R("居室A", f, (11250, 14400, 14100, 17125), True)
        self.room_B = R("居室B", f, (14200, 14400, 17125, 17125), True)
        R("ホール", f, (11250, 11250, 15500, 14300))
        R("トイレ", f, (15600, 12300, 17125, 14300))
        R("収納", f, (15600, 11250, 17125, 12200))
        L(f, "x", 14350, 11250, 17125, [(12000, 12800, "swing", 1, 0), (14600, 15400, "swing", 1, 1)])
        L(f, "y", 14150, 14400, 17125)
        L(f, "y", 15550, 11250, 14300, [(12700, 13500, "swing", 1, 0), (11350, 12100, "sliding")])
        L(f, "x", 12250, 15600, 17125)
        R("廊下", f, (11250, 6250, 12500, 11000))
        R("収納・予備", f, (12600, 6250, 17125, 11000))
        L(f, "y", 12550, 6250, 11000, [(9800, 10600, "sliding")])
        R("ランドリー", f, (125, 6250, 3500, 11000))
        R("浴室", f, (3600, 8250, 6000, 11000))
        R("脱衣所", f, (3600, 7150, 6000, 8150))
        R("洗面・化粧", f, (3600, 6250, 6000, 7050))
        L(f, "y", 3550, 6250, 11000, [(6300, 7000, "sliding")])
        L(f, "x", 8200, 3600, 6000, [(4400, 5100, "sliding")])
        L(f, "x", 7100, 3600, 6000, [(4400, 5100, "sliding")])
        R("廊下（コア）", f, (6250, 6250, 11000, 11000))
        self.ldk = R("LDK", f, (125, 125, 6000, 6000), True, label=(3100, 3400))
        self.ldk.area_override = ((6000 - 125) * (6000 - 125) + (7400 - 6250) * (6000 - 125)) / 1e6
        L(f, "y", 7450, 125, 6000, [(3000, 3800, "sliding")])
        R("玄関", f, (7500, 125, 11000, 2500))
        R("ホール", f, (7500, 2600, 9100, 6000))
        R("SIC", f, (9200, 2600, 11000, 5000))
        R("洗面所", f, (9200, 5100, 11000, 6000))
        L(f, "x", 2550, 7500, 11000)
        L(f, "y", 9150, 2600, 6000, [(3200, 4000, "sliding"), (5200, 5900, "sliding")])
        L(f, "x", 5050, 9200, 11000)
        R("トイレ", f, (11250, 125, 12700, 4000))
        R("収納", f, (12800, 125, 15025, 4000))
        R("ホール", f, (11250, 4100, 15025, 6000))
        L(f, "x", 4050, 11250, 15025, [(11500, 12300, "swing", -1, 0), (13300, 14100, "sliding")])
        L(f, "y", 12750, 125, 4000)
        L(f, "y", 15075, 125, 4000)
        # ---------------- 2F
        f = "2F"
        self.theater = R("シアター", f, (125, 12500, 6000, 17125), False)
        R("緩衝廊下", f, (125, 11250, 6000, 12400))
        L(f, "x", 12450, 125, 6000, [(4800, 5600, "double")])
        R("階段ホール", f, (6250, 11250, 8250, 13125))
        R("廊下・収納", f, (8350, 11250, 11000, 13650))
        R("居室C", f, (8350, 13750, 11000, 17125), True)
        L(f, "y", 8300, 11250, 17125, [(11500, 12300, "swing", -1, 0)])
        L(f, "x", 13700, 8350, 11000, [(9000, 9800, "swing", 1, 0)])
        R("居室D", f, (11250, 14000, 14100, 17125), True)
        R("居室E", f, (14200, 14000, 17125, 17125), True)
        R("ホール", f, (11250, 11250, 15500, 13950))
        R("トイレ", f, (15600, 12300, 17125, 13950))
        R("収納", f, (15600, 11250, 17125, 12200))
        L(f, "x", 13950, 11250, 17125, [(12000, 12800, "swing", 1, 0), (14600, 15400, "swing", 1, 1)])
        L(f, "y", 14150, 14000, 17125)
        L(f, "y", 15550, 11250, 13950, [(12500, 13300, "swing", 1, 0), (11350, 12100, "sliding")])
        L(f, "x", 12250, 15600, 17125)
        R("廊下", f, (125, 6250, 6000, 7400))
        R("図書室", f, (125, 7500, 3000, 11000), True)
        R("トイレ", f, (3100, 7500, 6000, 8800))
        R("WIC", f, (3100, 8900, 6000, 11000))
        L(f, "x", 7450, 125, 6000, [(1000, 1800, "swing", 1, 0), (4000, 4800, "swing", 1, 0)])
        L(f, "y", 3050, 7500, 11000, [(9500, 10300, "swing", 1, 0)])
        L(f, "x", 8850, 3100, 6000)
        R("廊下（コア）", f, (6250, 6250, 11000, 11000))
        R("廊下", f, (11250, 6250, 12500, 11000))
        R("WIC", f, (12600, 6250, 17125, 8800))
        R("脱衣所", f, (12600, 8900, 14800, 11000))
        R("シャワー", f, (14900, 8900, 17125, 11000))
        L(f, "y", 12550, 6250, 11000, [(7200, 8000, "swing", 1, 0), (9500, 10300, "swing", 1, 0)])
        L(f, "x", 8850, 12600, 17125)
        L(f, "y", 14850, 8900, 11000, [(9300, 10000, "sliding")])
        for n, (x0, x1) in zip("FGH", [(125, 2000), (2100, 4000), (4100, 6000)]):
            R("居室" + n, f, (x0, 125, x1, 3850), True)
        R("廊下", f, (125, 3950, 6000, 6000))
        L(f, "x", 3900, 125, 6000, [(600, 1400, "swing", -1, 0), (2600, 3400, "swing", -1, 0), (4600, 5400, "swing", -1, 0)])
        L(f, "y", 2050, 125, 3850)
        L(f, "y", 4050, 125, 3850)
        R("廊下（コア）", f, (6250, 6250, 11000, 11000))
        R("廊下収納（予備）", f, (6250, 125, 11000, 6000))
        R("予備室・収納", f, (11250, 125, 15025, 4000))
        R("ホール", f, (11250, 4100, 15025, 6000))
        L(f, "x", 4050, 11250, 15025, [(12500, 13300, "swing", -1, 0)])
        L(f, "y", 15075, 125, 4000)

    def _door(self, lv, wname, u0, u1, name="木製片開き戸", op="swing", swing=1, hinge=0, h=2000, fire=False):
        w = self.rc_walls[lv][wname]
        z0 = self.fl[lv]
        return w.add(Opening("door", u0, u1, z0, z0 + h, lv, "I", name, op, swing=swing, hinge=hinge, fire=fire))

    def _window(self, lv, side, u0, u1, sill, h, name="FIX窓", glass=None):
        z0 = self.fl[lv] + sill
        op = Opening("window", u0, u1, z0, z0 + h, lv, side, name, "fixed", exterior=True)
        op.glass = glass if glass is not None else (u1 - u0) * h / 1e6
        self.rc_walls[lv][side].add(op)
        o2 = Opening("window", u0, u1, z0, z0 + h, lv, side, name, "fixed", exterior=True)
        o2.glass = 0
        self.rc_walls[lv]["ins_" + side].add(o2)
        return op

    def _openings_rc(self):
        D = self._door
        # 1F
        ent = self.rc_walls["1F"]["S"].add(Opening("door", 8800, 9800, self.fl["1F"], self.fl["1F"] + 2200, "1F", "S",
                                                     "玄関ドア（断熱・防犯）", "swing", exterior=True, swing=-1, hinge=0))
        self.rc_walls["1F"]["ins_S"].add(Opening("door", 8800, 9800, self.fl["1F"], self.fl["1F"] + 2200, "1F", "S", "", "swing"))
        self.entrance = ent
        D("1F", "X2", 11500, 12300, "遮音ドア（Ts-35）", swing=-1, hinge=0)
        D("1F", "X2", 6350, 7050, op="sliding", name="木製引戸")
        self.rc_walls["1F"]["X2"].add(Opening("door", 1000, 5000, self.fl["1F"], self.fl["1F"] + 2400, "1F", "I", "開口（LDK）", "opening"))
        D("1F", "X3", 8000, 8900)
        D("1F", "Y2", 7800, 8700, swing=1)
        D("1F", "Y2", 11400, 12200, swing=-1)
        D("1F", "Y3", 6400, 7300, swing=1)
        D("1F", "Y3", 11400, 12200, swing=1)
        win = self.spec["windows"]
        # LDK: 南 2.0×1.31 + 西 1.2×1.2 = 4.06 m²
        self._window("1F", "S", 1500, 3500, 600, 1310, "FIX窓（LDK）")
        self._window("1F", "W", 2400, 3600, 700, 1200, "FIX窓（LDK）")
        self._window("1F", "W", 13500, 15000, 900, 1200, "FIX窓（ジム）")
        self._window("1F", "N", 12100, 13100, 1000, 700, "FIX窓（居室）")
        self._window("1F", "E", 15200, 16200, 1000, 700, "FIX窓（居室）")
        # 2F
        D("2F", "X2", 11400, 12200, "遮音ドア（Ts-35）", swing=-1, hinge=0)
        D("2F", "X2", 6400, 7200, swing=-1)
        D("2F", "X2", 4100, 4900, swing=-1)
        D("2F", "X3", 8000, 8900)
        D("2F", "Y2", 7800, 8700, swing=-1)
        D("2F", "Y2", 11400, 12200, swing=-1)
        D("2F", "Y3", 6400, 7300, swing=1)
        D("2F", "Y3", 9000, 9800, swing=1)
        D("2F", "Y3", 11400, 12200, swing=1)
        for u in (600, 2550, 4550):
            self._window("2F", "S", u, u + 1000, 1000, 700, "FIX窓（居室）")
        self._window("2F", "W", 8800, 9800, 1000, 700, "FIX窓（図書室）")
        self._window("2F", "N", 9200, 10200, 1000, 700, "FIX窓（居室）")
        self._window("2F", "N", 12200, 13200, 1000, 700, "FIX窓（居室）")
        self._window("2F", "E", 15000, 16000, 1000, 700, "FIX窓（居室）")
        # 床下ピット 点検口・換気口（基礎立上り）
        self.rc_walls["FDN"]["S"].add(Opening("door", 13000, 13800, self.fgl + 150, self.fgl + 750, "FDN", "S", "床下点検口（防水扉）", "swing",
                                              exterior=True, swing=-1))
        self.rc_walls["FDN"]["ins_S"].add(Opening("door", 13000, 13800, self.fgl + 150, self.fgl + 750, "FDN", "S", "", "swing"))

    def _stairs(self):
        sp = self.spec["requirements"]["stair"]
        H = self.H["1F"]
        n = 18
        T = 240
        s1 = Stair("階段1", 6250, 8250, 13125, +1, "1F", self.fl["1F"], H, n, T)
        s2 = Stair("階段2", 15125, 17125, 4000, -1, "1F", self.fl["1F"], H, n, T)
        self.boxes += s1.boxes(17125)
        self.boxes += s2.boxes(125)
        s1.hole = (6250, 13125, 8250, 17125)
        s2.hole = (15125, 125, 17125, 4000)
        self.stairs = [s1, s2]
        for s in self.stairs:
            self._room(s.name, "1F", s.hole)
            self._room(s.name, "2F", s.hole)
        # 階段の手すり壁（LGS）
        for s in self.stairs:
            xm = (s.x0 + s.x1) / 2
            y0, y1 = sorted([s.y_entry, s.y_turn])
            self.boxes.append(Box(xm - 50, y0, self.fl["1F"], xm + 50, y1, self.fl["1F"] + 1100 + H / 2, "partition", "lgs",
                                  level="1F", tag="手すり壁"))
        # スラブ
        e = self.t / 2
        outer = (-e, -e, self.W + e, self.D + e)
        for lv in ("1F", "2F", "RF"):
            holes = self.slab_holes(lv)
            for r in decompose(outer, holes):
                self.boxes.append(Box(r[0], r[1], self.fl[lv] - self.slab_t, r[2], r[3], self.fl[lv], "slab", level=lv, tag="S1"))

    def _entrance(self):
        """玄関前の外部階段（FGL → 1FL）。"""
        rise = self.fl["1F"] - self.fgl
        n = 6
        r = rise / n
        T = 300
        x0, x1 = 8300, 10300
        y_land = -self.t / 2 - self.ins
        land_d = 1500
        self.boxes.append(Box(x0 - 300, y_land - land_d, self.fgl, x1 + 300, y_land, self.fl["1F"] - 30, "stair", level="EXT", tag="玄関ポーチ"))
        for i in range(1, n):
            z = self.fgl + i * r
            y1 = y_land - land_d - (n - 1 - i) * T
            self.boxes.append(Box(x0, y1 - T, self.fgl, x1, y1, z, "stair", level="EXT", tag="外部階段"))
        self.porch = (x0 - 300, y_land - land_d - (n - 1) * T, x1 + 300, y_land)
        self.ext_stair = dict(n=n, riser=r, tread=T)

    # -------------------------------------------------------- exterior
    def _exterior(self):
        ex = self.spec["exterior"]
        req = self.spec["requirements"]
        site = self.site
        # 門扉（南側道路・東側道路の南端）
        s_edge = [e for e, c in zip(self.site_edges, self.edge_class) if c == "南側道路"][0]
        a, b_ = s_edge[0], s_edge[1]
        L = LineString([a, b_])
        gates = []
        # 南側：車両門扉（東寄り）＋人用門扉
        gv = ex["gate_vehicle"]
        gp = ex["gate_person"]
        d0 = 900
        gates.append(("車両門扉", L.interpolate(d0).coords[0], L.interpolate(d0 + gv).coords[0]))
        gates.append(("門扉（人）", L.interpolate(L.length - 2600).coords[0], L.interpolate(L.length - 2600 + gp).coords[0]))
        # 東側道路の南端（地盤差の小さい位置）勝手口
        e_edges = [e for e, c in zip(self.site_edges, self.edge_class) if c == "東側道路"]
        Le = LineString([p for e in e_edges for p in (e[0], e[1])])
        tot = Le.length
        gates.append(("勝手口", Le.interpolate(tot - 9000).coords[0], Le.interpolate(tot - 8000).coords[0]))
        self.gates = gates
        # 塀（敷地境界の内側に厚さ 150）
        self.fence_t = 150
        self.fence_h = req["fence_height"]
        segs = []
        boundary = LineString(list(site.exterior.coords))
        gate_lines = [LineString([g[1], g[2]]) for g in gates]
        cut = boundary
        for gl in gate_lines:
            cut = cut.difference(gl.buffer(5))
        self.fence_lines = [g for g in getattr(cut, "geoms", [cut])]
        # 塀の高さ: FGL+2.0m と 外側地盤+1.2m の高い方（東側の坂道沿いは道路面から 1.2m 以上）
        self.fence_top = lambda x, y: max(self.fgl + self.fence_h, self.ground_outside(x, y) + 1200)
        # 駐車場（南側の帯状部分）＋ソーラーカーポート
        cp = ex["carport"]
        cx0, cy0 = 6000, -26500
        self.carport = (cx0, cy0, cx0 + cp["w"], cy0 + cp["d"])
        self.stalls = [(cx0 + 300 + i * 2800, cy0 + 2000, cx0 + 300 + i * 2800 + 2600, cy0 + 2000 + 5500) for i in range(3)]
        pave = Polygon([(cx0 - 1200, -31000), (cx0 + cp["w"] + 1500, -31000), (cx0 + cp["w"] + 1500, cy0 + cp["d"] + 600),
                        (cx0 - 1200, cy0 + cp["d"] + 600)]).intersection(site.buffer(-self.fence_t))
        self.dotcon = pave
        # アプローチ（人用門扉 → 玄関ポーチ）
        gp0 = gates[1][1]
        gp1 = gates[1][2]
        gm = ((gp0[0] + gp1[0]) / 2, (gp0[1] + gp1[1]) / 2)
        self.approach = LineString([(gm[0], gm[1] + 200), (3300, -22000), (4800, -16000), (4800, -6000), (9300, -6000),
                                    (9300, self.porch[1])]).buffer(750, cap_style=2, join_style=2)
        # 雨水貯留槽・浸透施設（西側の庭）
        self.tank = (-32000, 22000, -27000, 27000)
        self.trench = [LineString([(-42000, 45000), (-29000, 39500), (-6000, 31500)]),
                       LineString([(-42500, 44500), (-35500, 11500)])]
        self.infil_pits = [(-42000, 45000), (-29000, 39500), (-6000, 31500), (-35500, 11500), (3000, -25000)]
        # 塀の排水口（フラップ弁）＝ 低い位置
        self.flap = [(-35600, 10200), (1000, -29200)]
        self.ext_storage = dict(
            dotcon_area=pave.area / 1e6,
            dotcon_l=pave.area / 1e6 * ex["dotcon_storage_l_per_m2"],
            tank_m3=ex["retention_tank_m3"])

    def ground_outside(self, x, y):
        """境界点 (x, y) の外側 2.5m の地盤高。"""
        p = Point(x, y)
        best = None
        for ang in range(0, 360, 30):
            q = (x + 2500 * math.cos(math.radians(ang)), y + 2500 * math.sin(math.radians(ang)))
            if not self.site.contains(Point(q)):
                z = self.ground(*q)
                best = z if best is None else max(best, z)
        return best if best is not None else self.fgl

    # --------------------------------------------------------- openings
    def _label_openings(self):
        groups = {}
        for w in self.walls:
            if w.cat == "insul":
                continue
            for op in w.openings:
                if op.operation == "opening":
                    op.label = ""
                    continue
                if op.kind == "window":
                    prefix = "AW"
                elif "玄関" in op.name or "点検" in op.name:
                    prefix = "SD"
                elif "遮音" in op.name:
                    prefix = "SSD"
                else:
                    prefix = "WD"
                key = (prefix, op.name, round(op.width), round(op.height), op.exterior)
                groups.setdefault(key, []).append(op)
        counters = {}
        self.fittings = []
        for key in sorted(groups, key=lambda k: (k[0], -k[2] * k[3])):
            prefix = key[0]
            counters[prefix] = counters.get(prefix, 0) + 1
            label = f"{prefix}-{counters[prefix]}"
            for op in groups[key]:
                op.label = label
            self.fittings.append(dict(label=label, name=key[1], w=key[2], h=key[3], fire=False, smoke=False,
                                      exterior=key[4], count=len(groups[key]),
                                      floors=sorted({o.floor for o in groups[key]}), alt_entry=False))

    def _wall_boxes(self, w: Wall):
        holes = [(op.u0, op.z0, op.u1, op.z1) for op in w.openings]
        out = []
        for u0, v0, u1, v1 in decompose((w.a, w.z0, w.b, w.z1), holes):
            x0, y0, z0, x1, y1, z1 = w.rect(u0, u1, v0, v1)
            out.append(Box(x0, y0, z0, x1, y1, z1, w.cat, w.mat, level=w.floor))
        if w.cat == "insul":
            return out
        for op in w.openings:
            if op.operation == "opening":
                continue
            th, cat, mat = (30, "glass", "glass") if op.kind == "window" else (50, "door", "door")
            h = th / 2
            if w.axis == "x":
                out.append(Box(op.u0, w.c - h, op.z0, op.u1, w.c + h, op.z1, cat, mat, level=w.floor, tag=op.label))
            else:
                out.append(Box(w.c - h, op.u0, op.z0, w.c + h, op.u1, op.z1, cat, mat, level=w.floor, tag=op.label))
        return out

    # ------------------------------------------------------------ areas
    def openings(self, floor=None, exterior=None):
        for w in self.walls:
            if w.cat == "insul":
                continue
            for op in w.openings:
                if floor and op.floor != floor:
                    continue
                if exterior is not None and op.exterior != exterior:
                    continue
                yield op

    def building_area(self):
        return self.W * self.D / 1e6

    def floor_area(self, f):
        return self.W * self.D / 1e6

    def outer_dims(self):
        e = self.t / 2 + self.ins
        return (-e, -e, self.W + e, self.D + e)

    def room_windows(self, room):
        """室に面する外壁窓（ガラス面積の合計）。"""
        x0, y0, x1, y1 = room.rect
        tot = 0.0
        for w in self.walls:
            if w.cat != "wall" or w.floor != room.floor:
                continue
            for op in w.openings:
                if op.kind != "window":
                    continue
                if w.axis == "x":
                    inside = x0 - 1 <= op.u0 and op.u1 <= x1 + 1 and abs(w.c - (y0 if w.c < y0 else y1)) < 300
                else:
                    inside = y0 - 1 <= op.u0 and op.u1 <= y1 + 1 and abs(w.c - (x0 if w.c < x0 else x1)) < 300
                if inside:
                    tot += getattr(op, "glass", op.width * op.height / 1e6)
        return tot
