"""AP 配置の探索（オフライン。build では動かさない）。焼きなまし法・乱数の種を固定。

    cd rc-building && python3 tools/wifi_search.py [--iters 30000] [--seed 1]

候補は 1m 格子の天井点（水回り・水回りブロック内の廊下・機械室を除く）× 出力 6〜20dBm。
spec.yaml の現行配置を初期解にして、上質な室・水回り・一般の目標との差（ペナルティ）を最小にする。
出力は最終の AP 表（spec.yaml の aps に貼る形）と区分ごとの要約だけ。
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import wifi as WF  # noqa: E402
from house import House  # noqa: E402

WET_CORR = {"1F": (9600, 12250, 12000, 15500), "2F": (6250, 12250, 12000, 13700)}   # 水回りブロック内の廊下


def inside(r, x, y, m=0):
    return r[0] + m <= x <= r[2] - m and r[1] + m <= y <= r[3] - m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    h = House(ROOT)
    w = h.spec["wifi"]
    M = WF.Model(h)
    # 全受信点（階をまたいで連結）
    pts, floors, room_idx = [], [], []
    for f in ("1F", "2F"):
        for r, p in M.room_points(f, 250):
            room_idx.append((f, r.name, len(pts), len(pts) + len(p), WF.room_class(w, f"{f} {r.name}")))
            pts.extend(map(tuple, p))
            floors.extend([f] * len(p))
    pts = np.array(pts)
    fl = np.array(floors)
    # 候補（1m 格子、250 オフセット）
    cands = {"1F": [], "2F": []}
    for f in ("1F", "2F"):
        for r in h.rooms:
            if r.floor != f or "機械室" in r.name:
                continue
            if WF.room_class(w, f"{f} {r.name}") == "quiet" or inside(WET_CORR[f], (r.rect[0] + r.rect[2]) / 2, (r.rect[1] + r.rect[3]) / 2):
                continue
            for x in range(250, int(h.W), 1000):
                for y in range(250, int(h.D), 1000):
                    if inside(r.rect, x, y, 200) and not any((c[0], c[1]) == (x, y) for c in cands[f]) and not any(inside(sl, x, y, -100) for sl in M.solid[f]):
                        cands[f].append((x, y, r.rect))
    for sp in w["aps"]:                      # 現行配置も候補に入れる
        f, (x, y) = sp["floor"], sp["xy"]
        if not any((c[0], c[1]) == (x, y) for c in cands[f]):
            cands[f].append((x, y, None))
    allc = [(f, x, y) for f in ("1F", "2F") for x, y, _ in cands[f]]
    print("候補", len(allc), "受信点", len(pts))
    base = np.zeros((len(allc), len(pts)))
    for i, (f, x, y) in enumerate(allc):
        for g in ("1F", "2F"):
            m = fl == g
            base[i, m] = M.rssi(dict(floor=f, xy=(x, y), eirp=0), g, pts[m])
    # 初期解
    cur = []
    for s in w["aps"]:
        j = min((k for k, c in enumerate(allc) if c[0] == s["floor"]), key=lambda k: (allc[k][1] - s["xy"][0]) ** 2 + (allc[k][2] - s["xy"][1]) ** 2)
        cur.append([j, s["eirp"], s["floor"]])
    pq = w["quiet"]

    def score(state):
        v = np.full(len(pts), -200.0)
        for j, e, _ in state:
            v = np.maximum(v, base[j] + e)
        pen = 0.0
        for f, nm, i0, i1, cls in room_idx:
            x = v[i0:i1]
            if cls == "premium":
                pen += 10 * np.sum(np.maximum(0, -53.5 - x) ** 2)
            elif cls == "quiet":
                med = np.median(x)
                pen += 3 * max(0, abs(med + 67.5) - 1.5) ** 2 * len(x) / 10
                pen += 3 * max(0, np.percentile(x, 90) + 63.5) ** 2 * len(x) / 10
                pen += 3 * max(0, -73.5 - x.min()) ** 2
            else:
                pen += 0.05 * np.sum(np.maximum(0, -65.5 - x) ** 2) + 1.0 * np.sum(np.maximum(0, -72.5 - x) ** 2)
        return pen

    rnd = random.Random(a.seed)
    # 各 AP は初期位置と同じ室の候補だけを動く（役割＝室を保つ）
    def room_of(f, x, y):
        return next(r.rect for r in h.rooms if r.floor == f and inside(r.rect, x, y) and "機械室" not in r.name)
    pidx = []
    for s_, (j0, _, f) in zip(w["aps"], cur):
        rr = room_of(f, *s_["xy"])
        pidx.append([k for k, c in enumerate(allc) if c[0] == f and inside(rr, c[1], c[2], 150)])
    best, bs = [list(s) for s in cur], score(cur)
    print("初期（spec の現行配置）ペナルティ", round(bs, 2))
    cs = bs
    T0, T1 = max(bs, 1) * 0.02, 0.05
    for it in range(a.iters):
        T = T0 * (T1 / T0) ** (it / a.iters)
        new = [list(s) for s in cur]
        k = rnd.randrange(len(new))
        if rnd.random() < 0.5:
            new[k][1] = min(20, max(6, new[k][1] + rnd.choice((-3, -2, -1, 1, 2, 3))))
        else:
            new[k][0] = rnd.choice(pidx[k])
        ns = score(new)
        if ns < cs or rnd.random() < math.exp((cs - ns) / T):
            cur, cs = new, ns
            if cs < bs:
                best, bs = [list(s) for s in cur], cs
    print("最終ペナルティ", round(bs, 2))
    for n, (j, e, f) in enumerate(best):
        s = w["aps"][n]
        print(f"    - {{id: {s['id']}, floor: {f}, xy: [{allc[j][1]}, {allc[j][2]}], eirp: {e}, role: {s['role']}}}")
    aps = [dict(floor=f, xy=(allc[j][1], allc[j][2]), eirp=e) for j, e, f in best]
    st = WF.room_stats(h, aps, 250, M)
    sm = WF.summarize(st, w)
    for r in st:
        if r["cls"] == "quiet":
            print(f"  {r['floor']} {r['name']}: min {r['min']:.1f} 中央値 {r['med']:.1f} 上位10% {r['p90']:.1f}")
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in sm.items()})


if __name__ == "__main__":
    main()
