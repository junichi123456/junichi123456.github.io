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
        self._gym_equipment()
        self._exterior()
        self._label_openings()
        for w in self.walls:
            self.boxes.extend(self._wall_boxes(w))

    # ------------------------------------------------------------ site
    def _orientation(self):
        """建物の向き: south_road のとき南側道路の道路境界線に X 軸を合わせる（回転角 alpha、反時計回り正）。"""
        mode = self.spec["building"].get("orientation", "north")
        self.alpha = 0.0
        if mode == "south_road":
            P, C = self.gsi["site"]["pts"], self.gsi["site"]["cls"]
            for i, c in enumerate(C):
                if c == "南側道路":
                    p, q = P[i], P[(i + 1) % len(P)]
                    ang = math.atan2(q[1] - p[1], q[0] - p[0])
                    if ang > math.pi / 2:
                        ang -= math.pi
                    elif ang < -math.pi / 2:
                        ang += math.pi
                    self.alpha = ang
        # 建物中心（世界座標 m）を回転の中心とする
        self.pivot = (self.ox + self.W / 2000.0, self.oy + self.D / 2000.0)
        # 南面の方位角（真南から西回り正、度）
        self.facade_az = -math.degrees(self.alpha)

    def m2mm(self, x, y):
        """世界座標（国土地理院ローカル m）→ 建物座標 mm（建物の軸に合わせて回転）。"""
        dx, dy = x - self.pivot[0], y - self.pivot[1]
        c, s = math.cos(-self.alpha), math.sin(-self.alpha)
        return ((dx * c - dy * s) * 1000.0 + self.W / 2, (dx * s + dy * c) * 1000.0 + self.D / 2)

    def mm2m(self, x, y):
        dx, dy = (x - self.W / 2) / 1000.0, (y - self.D / 2) / 1000.0
        c, s = math.cos(self.alpha), math.sin(self.alpha)
        return (dx * c - dy * s + self.pivot[0], dx * s + dy * c + self.pivot[1])

    def _site(self):
        self._orientation()
        pts = [self.m2mm(*p) for p in self.gsi["site"]["pts"]]
        self.site_pts = pts
        self.site_kind = self.gsi["site"]["kind"]
        self.site = Polygon(pts)
        n = len(pts)
        self.site_edges = [(pts[i], pts[(i + 1) % n], self.site_kind[i]) for i in range(n)]
        # 辺の分類（水路／東側道路／南側道路／隣地）
        cls = list(self.gsi["site"]["cls"])
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
        xm, ym = self.mm2m(x, y)
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
        """部屋割り（v4・B案）: 壁芯 X1–X4 / Y1–Y4 = 0 / 6,125 / 12,125 / 18,250（中央スパン 6.0m）。

        西列 x 125–6000 ／ 中央列 x 6250–12000（5.75m）／ 東列 x 12250–18125
        南行 y 125–6000 ／ 中行 y 6250–12000（5.75m）／ 北行 y 12250–18125
        """
        R, L = self._room, self._lgs
        # ================= 1F
        f = "1F"
        self.ldk = R("リビング・ダイニング", f, (125, 125, 6000, 6000), True, label=(3100, 3000))
        kit = R("キッチン", f, (1600, 6250, 6000, 12000), False)
        self.ldk.daylight_area = self.ldk.area + kit.area
        self.ldk.daylight_name = "LDK（キッチン含む）"
        R("パントリー", f, (125, 6250, 1500, 12000))
        L(f, "y", 1550, 6250, 12000, [(10800, 11600, "sliding")])
        R("玄関土間", f, (6250, 125, 12000, 2000), label=(9400, 1100))
        R("式台（框1）", f, (6250, 2000, 12000, 2400), label=(11000, 2200))
        R("ホール", f, (6250, 2400, 12000, 6000), label=(8600, 4600))
        self.genkan = dict(doma=(6250, 125, 12000, 2000), shikidai=(6250, 2000, 12000, 2400), step=180)
        self.shoe = (6250, 125, 6700, 2000)          # 下足入れ（造作）
        self.bench = (11300, 125, 12000, 1500)       # 腰掛けベンチ
        self.gym = R("ジム", f, (12250, 125, 18125, 8900), True, label=(17300, 7600))
        R("ホール・階段1", f, (6250, 6250, 12000, 9800), label=(10000, 7600))
        R("トイレ（手洗い付）", f, (8750, 9900, 10600, 12000))
        L(f, "x", 9850, 8750, 10650, [(9200, 10000, "swing", 1, 0)])
        L(f, "y", 8700, 9850, 12000)
        L(f, "y", 10650, 9850, 12000)
        R("機械室（西系統）", f, (12250, 9000, 15100, 12000))
        R("機械室（東系統）", f, (15200, 9000, 18125, 12000))
        L(f, "x", 8950, 12250, 18125)                 # ジム｜機械室（遮音二重壁）
        L(f, "y", 15150, 9000, 12000, [(10000, 10800, "swing", 1, 0)])
        R("ランドリー・室内干し", f, (125, 12250, 6000, 15000), label=(2400, 13600))
        R("ファミリークローゼット", f, (125, 15100, 3900, 18125))
        L(f, "x", 15050, 125, 3950, [(1000, 1800, "sliding")])
        L(f, "y", 3950, 15100, 18125)
        R("洗面・脱衣", f, (6250, 12250, 9500, 14800))
        R("浴室", f, (6250, 14900, 9500, 18125))
        R("廊下", f, (9600, 12250, 12000, 15500))
        R("トイレ", f, (9600, 15600, 12000, 18125))
        L(f, "y", 9550, 12250, 18125, [(12500, 13300, "sliding")])
        L(f, "x", 14850, 6250, 9500, [(7000, 7800, "sliding")])
        L(f, "x", 15550, 9600, 12000, [(10300, 11100, "swing", 1, 0)])
        self.room_A = R("居室A", f, (13600, 14300, 18125, 18125), True)
        R("WIC", f, (13600, 12250, 18125, 14200))
        R("廊下", f, (12250, 12250, 13500, 18125))
        L(f, "y", 13550, 12250, 18125, [(15500, 16300, "swing", 1, 0), (12800, 13600, "sliding")])
        L(f, "x", 14250, 13600, 18125)
        # ================= 2F
        f = "2F"
        R("居室B", f, (125, 125, 2800, 4800), True)
        R("収納", f, (2850, 125, 3400, 4800))
        R("居室C", f, (3450, 125, 6000, 4800), True)
        R("廊下", f, (125, 4900, 6000, 6000))
        L(f, "y", 2825, 125, 4800)
        L(f, "y", 3425, 125, 4800)
        L(f, "x", 4850, 125, 6000, [(1000, 1800, "swing", -1, 0), (4200, 5000, "swing", -1, 0)])
        R("居室D", f, (6250, 125, 9900, 4800), True)
        R("WIC", f, (10000, 125, 12000, 4800))
        R("廊下", f, (6250, 4900, 12000, 6000))
        L(f, "x", 4850, 6250, 12000, [(7000, 7800, "swing", -1, 0)])
        L(f, "y", 9950, 125, 4800, [(3800, 4600, "sliding")])
        self.theater = R("シアター", f, (12250, 125, 18125, 6000), False, label=(15200, 3000))
        R("前室（音響ロック）", f, (12250, 6250, 18125, 8100))
        R("WIC（主寝室）", f, (12250, 8200, 18125, 12000))
        L(f, "x", 8150, 12250, 18125)
        R("図書室", f, (125, 6250, 6000, 12000), True)
        R("ホール・階段1", f, (6250, 6250, 12000, 9800), label=(10000, 7600))
        R("トイレ（手洗い付）", f, (8750, 9900, 10600, 12000))
        L(f, "x", 9850, 8750, 10650, [(9200, 10000, "swing", 1, 0)])
        L(f, "y", 8700, 9850, 12000)
        L(f, "y", 10650, 9850, 12000)
        R("ファミリークローゼット", f, (125, 12250, 3900, 18125))
        R("ホール・階段2", f, (4000, 12250, 6000, 15000))
        L(f, "y", 3950, 12250, 18125, [(13000, 13800, "sliding")])
        R("洗面・脱衣", f, (6250, 12250, 9500, 14800))
        R("シャワー", f, (6250, 14900, 9500, 18125))
        R("廊下", f, (9600, 12250, 12000, 15500))
        R("トイレ", f, (9600, 15600, 12000, 18125))
        L(f, "y", 9550, 12250, 18125, [(12500, 13300, "sliding")])
        L(f, "x", 14850, 6250, 9500, [(7000, 7800, "sliding")])
        L(f, "x", 15550, 9600, 12000, [(10300, 11100, "swing", 1, 0)])
        R("主寝室", f, (12250, 12250, 18125, 18125), True)

    def _gym_equipment(self):
        """ジム機器（エニタイムフィットネス等の商業ジム相当）。(名称, 矩形, 高さ, 重量kg の目安)"""
        self.equipment = [
            ("パワーラック＋デッドリフト台", (12300, 300, 14500, 2700), 2300, 350),
            ("トレッドミル", (14700, 300, 15600, 2400), 1500, 200),
            ("トレッドミル", (16000, 300, 16900, 2400), 1500, 200),
            ("クロストレーナー", (17250, 300, 18050, 2200), 1700, 150),
            ("ダンベルラック", (12300, 4600, 12900, 6600), 1000, 450),
            ("ベンチ", (13300, 4800, 13900, 6100), 500, 40),
            ("ラットプル・ロー", (14300, 4800, 15400, 6300), 2200, 300),
            ("レッグプレス", (15900, 4800, 18000, 6200), 1500, 400),
            ("ケーブルクロスオーバー", (12600, 7700, 16100, 8500), 2300, 450),
            ("ストレッチマット", (17250, 2700, 18050, 4500), 20, 5),
        ]
        self.treadmill_zone = (14700, 2400, 17000, 4400)

    def _door(self, lv, wname, u0, u1, name="木製片開き戸", op="swing", swing=1, hinge=0, h=2000, fire=False):
        w = self.rc_walls[lv][wname]
        z0 = self.fl[lv]
        return w.add(Opening("door", u0, u1, z0, z0 + h, lv, "I", name, op, swing=swing, hinge=hinge, fire=fire))

    def _gap(self, lv, wname, u0, u1, h=2200, name="開口"):
        w = self.rc_walls[lv][wname]
        z0 = self.fl[lv]
        return w.add(Opening("door", u0, u1, z0, z0 + h, lv, "I", name, "opening"))

    def _window(self, lv, side, u0, u1, sill, h, name="FIX窓", glass=None):
        z0 = self.fl[lv] + sill
        op = Opening("window", u0, u1, z0, z0 + h, lv, side, name, "fixed", exterior=True)
        op.glass = glass if glass is not None else (u1 - u0) * h / 1e6
        self.rc_walls[lv][side].add(op)
        o2 = Opening("window", u0, u1, z0, z0 + h, lv, side, name, "fixed", exterior=True)
        o2.glass = 0
        self.rc_walls[lv]["ins_" + side].add(o2)
        return op

    def _ext_door(self, lv, side, u0, u1, h, name, swing=-1):
        z0 = self.fl[lv]
        op = self.rc_walls[lv][side].add(Opening("door", u0, u1, z0, z0 + h, lv, side, name, "swing", exterior=True, swing=swing, hinge=0))
        self.rc_walls[lv]["ins_" + side].add(Opening("door", u0, u1, z0, z0 + h, lv, side, "", "swing"))
        return op

    def _openings_rc(self):
        D, G = self._door, self._gap
        # ---------------- 1F
        self.entrance = self._ext_door("1F", "S", 8600, 9600, 2300, "玄関ドア（断熱・防犯CP）")
        D("1F", "X3", 3000, 4000, "遮音ドア（Ts-35・搬入兼用）", swing=1, h=2300)
        G("1F", "X2", 2800, 4000, name="開口（LDK↔ホール）")
        G("1F", "X2", 6400, 7300, name="開口（キッチン↔ホール）")
        D("1F", "X2", 12500, 13400, op="sliding", name="木製引戸")
        D("1F", "X3", 9300, 10100, swing=1, hinge=0)
        D("1F", "X3", 13000, 13800, swing=1, hinge=1)
        G("1F", "Y2", 1800, 5800, name="開口（ダイニング↔キッチン）")
        G("1F", "Y2", 7500, 10500, name="開口（ホール）")
        self.rc_walls["1F"]["Y2"].add(Opening("door", 12600, 17800, self.fl["1F"], self.fl["1F"] + 2600, "1F", "I", "開口（ジム）", "opening"))
        D("1F", "Y3", 300, 1300, op="sliding", name="木製引戸")
        G("1F", "Y3", 10900, 11800, name="開口（ホール↔廊下）")
        self._window("1F", "S", 1500, 3500, 600, 1310, "FIX窓（LDK）")
        self._window("1F", "W", 2400, 3600, 700, 1200, "FIX窓（LDK）")
        self._window("1F", "E", 700, 2900, 2000, 650, "FIX高窓（ジム）")
        self._window("1F", "E", 3400, 5600, 2000, 650, "FIX高窓（ジム）")
        self._window("1F", "E", 15500, 16700, 1000, 800, "FIX窓（居室）")
        # ---------------- 2F
        D("2F", "X2", 6400, 7300, swing=-1)
        D("2F", "X2", 5000, 5900, swing=-1)
        D("2F", "X2", 12500, 13400, op="sliding", name="木製引戸")
        D("2F", "X3", 6400, 7300, "遮音ドア（Ts-35）", swing=1, hinge=0)
        D("2F", "X3", 13000, 13800, swing=1, hinge=1)
        D("2F", "Y2", 8500, 9500, swing=1)
        D("2F", "Y2", 1000, 1800, swing=-1)
        D("2F", "Y2", 14000, 15600, "遮音ドア（両開き Ts-40）", swing=1)
        G("2F", "Y3", 10900, 11800, name="開口（ホール↔廊下）")
        D("2F", "Y3", 4500, 5300, swing=1)
        D("2F", "Y3", 16500, 17300, swing=-1)
        self._window("2F", "S", 900, 1900, 1000, 700, "FIX窓（居室）")
        self._window("2F", "S", 4200, 5200, 1000, 700, "FIX窓（居室）")
        self._window("2F", "S", 7200, 8800, 1000, 800, "FIX窓（居室）")
        self._window("2F", "W", 7200, 8800, 1000, 700, "FIX窓（図書室）")
        self._window("2F", "W", 9800, 10800, 1000, 700, "FIX窓（図書室）")
        self._window("2F", "N", 14000, 15600, 1000, 800, "FIX窓（主寝室）")
        self._window("2F", "E", 15500, 16500, 1000, 800, "FIX窓（主寝室）")
        self.rc_walls["FDN"]["S"].add(Opening("door", 4200, 5000, self.fgl + 150, self.fgl + 750, "FDN", "S", "床下点検口（防水扉）", "swing",
                                              exterior=True, swing=-1))
        self.rc_walls["FDN"]["ins_S"].add(Opening("door", 4200, 5000, self.fgl + 150, self.fgl + 750, "FDN", "S", "", "swing"))

    def _stairs(self):
        H = self.H["1F"]
        s1 = Stair("階段1", 6250, 8650, 8500, +1, "1F", self.fl["1F"], H, 18, 260)
        s2 = Stair("階段2", 4000, 6000, 15100, +1, "1F", self.fl["1F"], H, 18, 240)
        self.boxes += s1.boxes(12000)
        self.boxes += s2.boxes(18125)
        s1.hole = (6250, 8500, 8650, 12000)
        s2.hole = (4000, 15100, 6000, 18125)
        self.stairs = [s1, s2]
        for s in self.stairs:
            xm = (s.x0 + s.x1) / 2
            y0, y1 = sorted([s.y_entry, s.y_turn])
            self.boxes.append(Box(xm - 50, y0, self.fl["1F"], xm + 50, y1, self.fl["1F"] + 1100 + H / 2, "partition", "lgs",
                                  level="1F", tag="手すり壁"))
        e = self.t / 2
        outer = (-e, -e, self.W + e, self.D + e)
        g = self.genkan
        for key, dz in (("doma", 2 * g["step"]), ("shikidai", g["step"])):
            x0, y0, x1, y1 = g[key]
            self.boxes.append(Box(x0, y0, self.fl["1F"] - dz - self.slab_t, x1, y1, self.fl["1F"] - dz, "slab", level="1F", tag=key))
        for lv in ("1F", "2F", "RF"):
            holes = self.slab_holes(lv) + ([g["doma"], g["shikidai"]] if lv == "1F" else [])
            for r in decompose(outer, holes):
                self.boxes.append(Box(r[0], r[1], self.fl[lv] - self.slab_t, r[2], r[3], self.fl[lv], "slab", level=lv, tag="S1"))

    def _entrance(self):
        """玄関前の外部階段（FGL → 1FL）。"""
        porch_z = self.fl["1F"] - 2 * 180 - 20          # 土間 FL-360 よりポーチ 20 下げ
        rise = porch_z - self.fgl
        n = 4
        r = rise / n
        T = 300
        x0, x1 = 8100, 10100
        y_land = -self.t / 2 - self.ins
        land_d = 2000
        self.boxes.append(Box(x0 - 300, y_land - land_d, self.fgl, x1 + 300, y_land, porch_z, "stair", level="EXT", tag="玄関ポーチ"))
        for i in range(1, n):
            z = self.fgl + i * r
            y1 = y_land - land_d - (n - 1 - i) * T
            self.boxes.append(Box(x0, y1 - T, self.fgl, x1, y1, z, "stair", level="EXT", tag="外部階段"))
        self.porch = (x0 - 300, y_land - land_d - (n - 1) * T, x1 + 300, y_land)
        self.ext_stair = dict(n=n, riser=r, tread=T)
        # 目隠し壁（RC・本館から独立した自立壁、単体で補修・更新可能）: 南側道路からの視線だけを遮る1枚壁
        sw = self.spec["exterior"]["screen_wall"]
        tt, top = sw["t"], self.fgl + sw["height"]
        xa, xb = sw["x"]
        yc = sw["y"]
        self.screen = [(xa, yc - tt, xb, yc)]
        self.louver = None
        for (a0, b0, a1, b1) in self.screen:
            self.boxes.append(Box(a0, b0, self.fgl - 400, a1, b1, top, "wall", level="EXT", tag="目隠し壁"))
        self.screen_top = top
        # 玄関庇（本館から片持ち、出 2.0m）
        cn = self.spec["exterior"]["canopy"]
        y_face = -self.t / 2 - self.ins
        self.canopy = (cn["x"][0], y_face - cn["depth"], cn["x"][1], y_face)
        zc = self.fl["1F"] + cn["z"]
        self.boxes.append(Box(*self.canopy[:2], zc, *self.canopy[2:], zc + 150, "slab", level="EXT", tag="庇"))
        self.canopy_z = zc

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
        # 日よけ付き菜園（ソーラーパーゴラ）— 本館と構造的に分離した独立架台
        pg = ex["solar_pergola"]
        self.pergola = tuple(pg["rect"])
        self.pergola_h = pg["height"]
        # 駐車場（南側の帯状部分）＋3台用ソーラーカーポート
        cp = ex["carport"]
        cx0, cy0 = 13000, -27400
        self.carport = (cx0, cy0, cx0 + cp["w"], cy0 + cp["d"])
        self.stalls = [(cx0 + 300 + i * 2800, cy0 + 300, cx0 + 300 + i * 2800 + 2600, cy0 + 300 + 5500) for i in range(3)]
        pave = Polygon([(cx0 - 1200, -31000), (cx0 + cp["w"] + 1500, -31000), (cx0 + cp["w"] + 1500, cy0 + cp["d"] + 900),
                        (cx0 - 1200, cy0 + cp["d"] + 900)]).intersection(site.buffer(-self.fence_t))
        pave = pave.intersection(site.buffer(-self.fence_t))
        self.dotcon = pave
        # アプローチ（人用門扉 → 玄関ポーチ）
        gp0 = gates[1][1]
        gp1 = gates[1][2]
        gm = ((gp0[0] + gp1[0]) / 2, (gp0[1] + gp1[1]) / 2)
        # アプローチ: 目隠し壁の西側から回り込み、壁の内側で玄関階段に至る（クランク）
        self.approach = LineString([(gm[0], gm[1] + 200), (gm[0], -26000), (12000, -21000), (13900, -17000), (13900, -4300), (9100, -4300),
                                    (9100, self.porch[1])]).buffer(750, cap_style=2, join_style=2)
        # 雨水貯留槽・浸透施設（西側の庭）
        self.tank = (-23500, 22000, -18500, 27000)
        self.trench = [LineString([(-29500, 28000), (-15000, 28100), (-1000, 27800)]),
                       LineString([(-30500, 26500), (-31500, 13000), (-32300, 1000)])]
        self.infil_pits = [(-29500, 28000), (-15000, 28100), (-1000, 27800), (-31500, 13000), (-32300, 1000), (11000, -16000)]
        # 塀の排水口（フラップ弁）＝ 低い位置
        self.flap = [(-33200, -600), (12000, -30600)]
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
