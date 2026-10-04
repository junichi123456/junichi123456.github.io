"""館内 Wi-Fi の電波計画（5GHz 帯の受信強度を壁の減衰込みで概算し、天井AP の位置を決める）。

壁式 RC は内部にも耐力壁が多く、5GHz は RC 壁 1 枚で大きく減衰する。
自由空間損失＋通過する壁ごとの減衰で受信強度を求め、目標値を満たす面積が
最大になるよう AP を 1 台ずつ追加する（貪欲法）。
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree

LOSS = {"wall": 25.0, "partition": 4.0, "door": 4.0, "stair": 6.0}   # dB（5GHz、RC250・LGS間仕切・木製/遮音扉）


def _pl(d_m, f_mhz):
    d = max(d_m, 0.5)
    return 20 * math.log10(d) + 20 * math.log10(f_mhz) - 27.55


class Floor:
    def __init__(self, h, floor):
        w = h.spec["wifi"]
        self.h, self.floor, self.w = h, floor, w
        z = h.fl[floor] + 1200
        self.items = [(box(b.x0, b.y0, b.x1, b.y1), LOSS[b.cat]) for b in h.boxes
                      if b.cat in LOSS and b.z0 < z < b.z1 and b.level != "EXT"]
        self.tree = STRtree([p for p, _ in self.items])
        step = w["grid"]
        rc = [p for p, l in self.items if l == LOSS["wall"]]
        self.pts = [(x, y) for x in _rng(step / 2, h.W, step) for y in _rng(step / 2, h.D, step)
                    if all(p.distance(Point(x, y)) > 130 for p in rc)]          # 壁の中・壁際（表面）の点は除く

    def rssi(self, ap, p):
        seg = LineString([ap, p])
        loss = sum(self.items[int(i)][1] for i in self.tree.query(seg) if seg.intersects(self.items[int(i)][0]))
        d = math.hypot(ap[0] - p[0], ap[1] - p[1]) / 1000
        return self.w["eirp_dbm"] - _pl(d, self.w["freq_mhz"]) - loss

    def best(self, aps):
        return [max((self.rssi(a, p) for a in aps), default=-200.0) for p in self.pts]


def _rng(a, b, s):
    v = a
    while v < b:
        yield v
        v += s


def plan(h, floor):
    """AP を目標カバー率に達するまで追加する。候補は各室の中心（機械室・収納を除く）。"""
    w = h.spec["wifi"]
    F = Floor(h, floor)
    cands = [((r.rect[0] + r.rect[2]) / 2, (r.rect[1] + r.rect[3]) / 2, r.name) for r in h.rooms
             if r.floor == floor and r.area >= 6 and not any(k in r.name for k in ("機械室", "収納", "WIC", "浴室", "シャワー"))]
    cache = {c[:2]: [F.rssi(c[:2], p) for p in F.pts] for c in cands}
    aps, cur = [], [-200.0] * len(F.pts)
    while True:
        cov = sum(v >= w["target_dbm"] for v in cur) / len(cur)
        if cov >= w["target_cover"] or len(aps) >= 8:
            break
        best = max(cands, key=lambda c: sum(max(a, b) >= w["target_dbm"] for a, b in zip(cur, cache[c[:2]])))
        aps.append(best)
        cur = [max(a, b) for a, b in zip(cur, cache[best[:2]])]
        cands.remove(best)
    cov = sum(v >= w["target_dbm"] for v in cur) / len(cur)
    return dict(floor=floor, aps=aps, pts=F.pts, rssi=cur, cover=cov, min=min(cur), grid=w["grid"])
