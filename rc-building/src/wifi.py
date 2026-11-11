"""館内 Wi-Fi の電波計画（v4.32）: 5GHz 帯の受信強度を壁・スラブの減衰込みで概算する簡易モデル。

壁式 RC は内部にも耐力壁が多く、5GHz は RC 壁 1 枚で大きく減衰する。
・自由空間損失（3 次元距離。AP は FL+2,800・受信点は FL+1,200）＋通過する壁の減衰
・上下階の AP はスラブ 30dB を加えて足す（簡易モデル。受信階の壁だけを数える）
・AP ごとに EIRP（6〜20dBm）。アンテナは天井型の無指向が基本、予備策として sector（前後比）
AP は spec.yaml の固定配置。探索（焼きなまし法）は tools/wifi_search.py（build では動かさない）。
上質な室は全面で目標以上、水回りは「悪くする」ために RC 壁・スラブ越しの漏れ電波だけを届ける。
受信強度の点群は出力・保存せず、室ごとの集計（room_stats）だけを返す。
"""
from __future__ import annotations

import math

import numpy as np

AP_H = 2800       # 天井 AP の高さ（FL から）
RX_H = 1200       # 受信点の高さ（FL から）
MARGIN = 150      # 室の内側に取る余白（壁面の点を除く）
EPS = 1e-9


def _pl(d_m, f_mhz):
    d = np.maximum(d_m, 0.5)
    return 20 * np.log10(d) + 20 * math.log10(f_mhz) - 27.55


def _kind(b):
    return "glass_door" if (b.cat == "door" and b.mat == "glass") else b.cat


def _rng(a, b, s):
    out, v = [], a
    while v <= b:
        out.append(v)
        v += s
    return out


class Model:
    def __init__(self, h):
        self.h = h
        self.w = h.spec["wifi"]
        L = self.w["loss"]
        self.walls = {}
        for f in ("1F", "2F"):
            z = h.fl[f] + RX_H
            rows = [(b.x0, b.y0, b.x1, b.y1, L[_kind(b)]) for b in h.boxes
                    if _kind(b) in L and b.z0 < z < b.z1 and b.level != "EXT"]
            self.walls[f] = np.array(rows, dtype=float)
        self.solid = {f: [(b.x0, b.y0, b.x1, b.y1) for b in h.boxes if b.cat in ("stair", "wall", "partition", "column")
                          and b.z0 < h.fl[f] + RX_H < b.z1 and b.level != "EXT"] for f in ("1F", "2F")}
        self._pts = {}

    def room_points(self, floor, step=250):
        """[(room, 受信点 ndarray)]。室の内側 MARGIN を除いた step 格子（小さい室は中心 1 点）。機械室は除く。"""
        key = (floor, step)
        if key not in self._pts:
            out = []
            for r in self.h.rooms:
                if r.floor != floor or "機械室" in r.name:
                    continue
                x0, y0, x1, y1 = r.rect
                xs = _rng(x0 + MARGIN, x1 - MARGIN, step) or [(x0 + x1) / 2]
                ys = _rng(y0 + MARGIN, y1 - MARGIN, step) or [(y0 + y1) / 2]
                sol = self.solid[floor]
                pts = [(x, y) for x in xs for y in ys if not any(a - 50 <= x <= c + 50 and b - 50 <= y <= d + 50 for a, b, c, d in sol)]
                out.append((r, np.array(pts or [((x0 + x1) / 2, (y0 + y1) / 2)], dtype=float)))
            self._pts[key] = out
        return self._pts[key]

    def wall_loss(self, floor, ap_xy, pts):
        """AP→各点の線分が横切る壁の減衰の合計（スラブ法）。"""
        W = self.walls[floor]
        ax, ay = ap_xy
        dx = pts[:, 0] - ax
        dy = pts[:, 1] - ay
        dx = np.where(np.abs(dx) < EPS, EPS, dx)[:, None]
        dy = np.where(np.abs(dy) < EPS, EPS, dy)[:, None]
        tx1, tx2 = (W[None, :, 0] - ax) / dx, (W[None, :, 2] - ax) / dx
        ty1, ty2 = (W[None, :, 1] - ay) / dy, (W[None, :, 3] - ay) / dy
        lo = np.maximum(np.maximum(np.minimum(tx1, tx2), np.minimum(ty1, ty2)), 0.0)
        hi = np.minimum(np.minimum(np.maximum(tx1, tx2), np.maximum(ty1, ty2)), 1.0)
        return ((lo <= hi) * W[None, :, 4]).sum(axis=1)

    def rssi(self, ap, floor, pts):
        """AP（dict: floor, xy, eirp, sector）から floor 階の pts への受信強度 dBm。"""
        ax, ay = ap["xy"]
        dz = (self.h.fl[ap["floor"]] + AP_H) - (self.h.fl[floor] + RX_H)
        d = np.sqrt((pts[:, 0] - ax) ** 2 + (pts[:, 1] - ay) ** 2 + dz ** 2) / 1000
        loss = self.wall_loss(floor, (ax, ay), pts)
        if ap["floor"] != floor:
            loss = loss + self.w["loss"]["slab"]
        v = ap["eirp"] - _pl(d, self.w["freq_mhz"]) - loss
        sec = ap.get("sector")
        if sec:
            ang = np.degrees(np.arctan2(pts[:, 1] - ay, pts[:, 0] - ax))
            rel = np.abs((ang - sec["az"] + 180) % 360 - 180)
            v = v - sec.get("fb", 10) * (1 - np.cos(np.radians(rel))) / 2
        return v

    def best(self, aps, floor, pts):
        v = np.full(len(pts), -200.0)
        for a in aps:
            v = np.maximum(v, self.rssi(a, floor, pts))
        return v


def room_class(w, key):
    """premium（上質）／quiet（水回り）／general（一般）。key は「1F 浴室」の形。"""
    for k in ("premium", "quiet"):
        if key in w[k]["rooms"]:
            return k
    return "general"


def room_stats(h, aps=None, step=250, model=None):
    """室ごとの集計（点群は返さない）: floor, name, cls, n, min, med, p90, c55, c60, c67, c75。"""
    M = model or Model(h)
    w = h.spec["wifi"]
    aps = w["aps"] if aps is None else aps
    out = []
    for f in ("1F", "2F"):
        for r, pts in M.room_points(f, step):
            v = M.best(aps, f, pts)
            out.append(dict(floor=f, name=r.name, cls=room_class(w, f"{f} {r.name}"), n=len(v), min=float(v.min()),
                            med=float(np.median(v)), p90=float(np.percentile(v, 90)),
                            c55=float((v >= -55).mean()), c60=float((v >= -60).mean()),
                            c67=float((v >= -67).mean()), c75=float((v >= -75).mean())))
    return out


def summarize(stats, w):
    """区分ごとの合否（試験・LEGAL_CHECK・E-01 で共通）。"""
    g, q = w["general"], w["quiet"]
    prem = [s for s in stats if s["cls"] == "premium"]
    quiet = [s for s in stats if s["cls"] == "quiet"]
    gen = [s for s in stats if s["cls"] == "general"]
    out = dict(
        n_premium=len(prem), n_quiet=len(quiet),
        premium_min=min(s["min"] for s in prem),
        premium_ok=all(s["min"] >= w["premium"]["dbm"] for s in prem),
        quiet_ok=all(q["median"][0] <= s["med"] <= q["median"][1] and s["p90"] <= q["p90_max"] and s["min"] >= q["min"] for s in quiet),
        general_min=min(s["min"] for s in gen),
    )
    for f in ("1F", "2F"):
        sel = [s for s in gen if s["floor"] == f]
        out[f"general_cover_{f}"] = sum(s["c67"] * s["n"] for s in sel) / sum(s["n"] for s in sel)
    out["general_ok"] = out["general_min"] >= g["min"] and all(out[f"general_cover_{f}"] >= g["cover"] for f in ("1F", "2F"))
    return out


# ---------------------------------------------------------------- 旧計画（段階2で削除）
from shapely.geometry import LineString, Point, box  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

_LEGACY_LOSS = {"wall": 25.0, "partition": 4.0, "door": 4.0, "stair": 6.0, "glass_door": 3.0}   # dB（5GHz、RC250・LGS間仕切・木製/遮音扉・合わせガラス扉）


def _lkind(b):
    return "glass_door" if (b.cat == "door" and b.mat == "glass") else b.cat


def _lpl(d_m, f_mhz):
    d = max(d_m, 0.5)
    return 20 * math.log10(d) + 20 * math.log10(f_mhz) - 27.55


class LegacyFloor:
    def __init__(self, h, floor):
        w = h.spec["wifi"]
        self.h, self.floor, self.w = h, floor, w
        z = h.fl[floor] + 1200
        self.items = [(box(b.x0, b.y0, b.x1, b.y1), _LEGACY_LOSS[_lkind(b)]) for b in h.boxes
                      if b.cat in _LEGACY_LOSS and b.z0 < z < b.z1 and b.level != "EXT"]
        self.tree = STRtree([p for p, _ in self.items])
        step = w["grid"]
        rc = [p for p, l in self.items if l == _LEGACY_LOSS["wall"]]
        self.pts = [(x, y) for x in _lrng(step / 2, h.W, step) for y in _lrng(step / 2, h.D, step)
                    if all(p.distance(Point(x, y)) > 130 for p in rc)]          # 壁の中・壁際（表面）の点は除く

    def rssi(self, ap, p):
        seg = LineString([ap, p])
        loss = sum(self.items[int(i)][1] for i in self.tree.query(seg) if seg.intersects(self.items[int(i)][0]))
        d = math.hypot(ap[0] - p[0], ap[1] - p[1]) / 1000
        return self.w["eirp_dbm"] - _lpl(d, self.w["freq_mhz"]) - loss

    def best(self, aps):
        return [max((self.rssi(a, p) for a in aps), default=-200.0) for p in self.pts]


def _lrng(a, b, s):
    v = a
    while v < b:
        yield v
        v += s


def plan(h, floor):  # v4.31 の貪欲法（段階2で E-01 を差し替えるまで build 用に残す）
    """AP を目標カバー率に達するまで追加する。候補は各室の中心（機械室・収納を除く）。"""
    w = h.spec["wifi"]
    F = LegacyFloor(h, floor)
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
