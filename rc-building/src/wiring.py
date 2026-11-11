"""通信・LAN 配線の計画（v4.32）: ラック・縦配線・RC スリーブ・AP への配線長・有線 LAN 口。

すべて spec.yaml の wifi（rack・riser・sleeves・lan_outlets・aps[].via）から読む。
RC のスリーブは打設前に入れ、後から穴をあけない（配置の衝突は check で確認する）。
"""
from __future__ import annotations

import math


def cfg(h):
    return h.spec["wifi"]


def sleeve_pairs(h):
    """{id: (floor, wall, [(x, y), (x, y)])}。壁（X=x 一定／Y=y 一定）に沿って pitch ずつ。"""
    w = cfg(h)
    sp = w["sleeve_spec"]
    out = {}
    for s in w["sleeves"]:
        x, y = s["xy"]
        along = (0, 1) if s["wall"].startswith("X") else (1, 0)
        out[s["id"]] = (s["floor"], s["wall"], [(x + along[0] * sp["pitch"] * k, y + along[1] * sp["pitch"] * k) for k in range(sp["n"])])
    return out


def wet_rects(h):
    import wifi as WF
    w = cfg(h)
    return [(r.floor, r.rect) for r in h.rooms if WF.room_class(w, f"{r.floor} {r.name}") == "quiet"]


def _hits(a, b, rects):
    from shapely.geometry import LineString, box
    ln = LineString([a, b])
    return any(ln.intersects(box(*r).buffer(-1)) for r in rects)


def _manhattan(p, q, rects):
    """p→q を直角の 2〜3 辺で結ぶ。水回りの室を避けられる最短の向きを選ぶ（天井内の迂回）。"""
    cands = [[p, (q[0], p[1]), q], [p, (p[0], q[1]), q]]
    for v in range(250, 18250, 250):
        cands.append([p, (p[0], v), (q[0], v), q])
        cands.append([p, (v, p[1]), (v, q[1]), q])
    cands.sort(key=lambda c: sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(c, c[1:])))
    for c in cands:
        if not any(_hits(a, b, rects) for a, b in zip(c, c[1:])):
            return c
    return cands[0]


def routes(h):
    """AP ごとの配線経路: [dict(id, floor, pts, horiz_m, vert_m, length_m, via)]。長さ＝水平（迂回 detour 倍）＋垂直＋両端の余長。"""
    w = cfg(h)
    c = w["cable"]
    rack = tuple(w["rack"]["xy"])
    riser = tuple(w["riser"]["box"]["xy"])
    sl = {k: v[2][0] for k, v in sleeve_pairs(h).items()}
    out = []
    for a in w["aps"]:
        pts = [rack]
        vert = (c["ceiling_h"] - c["rack_h"]) / 1000 + 0.3
        if a["floor"] == "2F":
            pts += [tuple(w["riser"]["xy"]), riser]
            vert += (h.fl["2F"] - h.fl["1F"]) / 1000
        pts += [sl["SL-" + v] for v in a.get("via", [])]
        pts.append(tuple(a["xy"]))
        rects = [r for f, r in wet_rects(h) if f == a["floor"]]
        path = [pts[0]]
        for p, q in zip(pts, pts[1:]):
            path += _manhattan(p, q, rects)[1:]
        horiz = sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(path, path[1:])) / 1000 * c["detour"]
        out.append(dict(id=a["id"], floor=a["floor"], pts=pts, path=path, horiz_m=horiz, vert_m=vert, via=a.get("via", []),
                        length_m=horiz + vert + 2 * c["slack_m"]))
    return out


def poe_load_w(h):
    return sum(n * p for _, n, p in cfg(h)["rack"]["poe_loads"])


def lan_total(h):
    return sum(o["n"] for o in cfg(h)["lan_outlets"])


def check(h):
    """問題の一覧（空なら適合）: スリーブが RC 壁の中にあり開口端から 300 以上離れ既存 SL と重ならない、LAN 口が室内・水回りでない等。"""
    import wifi as WF
    w = cfg(h)
    sp = w["sleeve_spec"]
    bad = []
    existing = [(s[0], s[2][0] if False else s[2], s[3]) for s in h.spec["mech_rooms"]["sleeves"]]
    for sid, (f, wall, pairs) in sleeve_pairs(h).items():
        z = h.fl[f] + sp["z"]
        for (x, y) in pairs:
            ok = False
            for b in h.boxes:
                if b.cat != "wall" or b.level != f or not (b.z0 < z < b.z1) or b.mat == "insul":
                    continue
                if b.x0 <= x <= b.x1 and b.y0 <= y <= b.y1:
                    u0, u1, p = (b.y0, b.y1, y) if wall.startswith("X") else (b.x0, b.x1, x)
                    ok = min(p - u0, u1 - p) >= sp["edge_clear"] + sp["dia"] / 2
            if not ok:
                bad.append(f"{sid}: RC 壁の中・開口端から {sp['edge_clear']} 以上でない {(x, y)}")
            for name, xy, d in existing:
                if f == "1F" and math.hypot(x - xy[0], y - xy[1]) < (d + sp["dia"]) / 2 + sp["edge_clear"]:
                    bad.append(f"{sid}: 既存 {name} と近い")
    sleeve_ids = {"SL-" + v for a in w["aps"] for v in a.get("via", [])}
    if not sleeve_ids <= set(sleeve_pairs(h)):
        bad.append("via に未定義のスリーブ")
    rooms = {(r.floor, r.name): r.rect for r in h.rooms}
    for o in w["lan_outlets"]:
        r = rooms[(o["floor"], o["room"])]
        x, y = o["xy"]
        if not (r[0] <= x <= r[2] and r[1] <= y <= r[3]):
            bad.append(f"{o['id']}: 室の外")
        if WF.room_class(w, f"{o['floor']} {o['room']}") == "quiet":
            bad.append(f"{o['id']}: 水回り")
    return bad
