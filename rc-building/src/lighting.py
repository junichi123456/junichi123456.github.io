"""照明計画（v4.17）: 主照明＝天井直付けの棒状（ライン）LED、埋込ダウンライト＝弱い補助灯、階段の足元灯。

- lines(h, its): ライン器具の列（室ごと。長手方向に平行、器具の出力区分は光束法で決める）
- downlights(h, its, lns): 弱いダウンライト（ライン軸から 450 以上・壁から 400 以上）
- footlights(h): 階段の足元灯（各段の踏面から 300、2 段おき＋踊場 1 台）
- channels(spec, hour, room): 時刻ごとの L（ライン）・D（ダウンライト）・F（足元灯）の（色温度 K, 明るさ %）
- illuminance_table(h, its): 照度計算表（光束法）

製品は未確定で、器具の寸法・光束・効率はすべて仮定値（spec.yaml の lighting）。
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, box as sbox
from shapely.ops import unary_union

CODE = {"リビング・ダイニング": "LDK", "キッチン": "KIT", "パントリー": "PAN", "玄関土間": "GEN", "ホール・階段1": "HS1", "ホール・階段2": "HS2", "ホール": "HAL",
        "ジム": "GYM", "ランドリー・室内干し": "LDY", "ファミリークローゼット": "FCL", "洗面・脱衣": "WSH", "浴室": "BTH", "シャワー": "SHW", "居室": "RM",
        "WIC（主寝室）": "MWC", "WIC": "WIC", "シアター": "THR", "前室（音響ロック）": "ANT", "図書室": "LIB", "主寝室": "MBR", "廊下": "COR", "トイレ（手洗い付）": "TLH",
        "トイレ": "TLT", "機械室（西系統）": "MCW", "機械室（東系統）": "MCE"}

# 光束法の利用率 U（直付・乳白拡散、反射率 天井0.7/壁0.5/床0.2 を仮定した概略値）
_UT = [(0.6, .33), (0.8, .40), (1.0, .45), (1.25, .50), (1.5, .54), (2.0, .59), (2.5, .63), (3.0, .66), (4.0, .70), (5.0, .72)]
DARK = {"シアター": 0.6}      # 暗色仕上げの補正


def _U(k):
    if k <= _UT[0][0]:
        return _UT[0][1]
    for (a, ua), (b, ub) in zip(_UT, _UT[1:]):
        if a <= k <= b:
            return ua + (ub - ua) * (k - a) / (b - a)
    return _UT[-1][1]


def _cfg(h):
    return h.spec["lighting"]


def target_lx(h, name):
    t = _cfg(h)["targets_lx"]
    for k in sorted(t, key=len, reverse=True):          # 長い名前を先に（「ホール・階段」を「ホール」より先に）
        if k in name:
            return t[k]
    return 150


def room_code(h, r):
    """室の記号（同じ名前の室が複数あるときは連番）。"""
    name = next((v for k, v in sorted(CODE.items(), key=lambda kv: -len(kv[0])) if k in r.name), r.name)
    same = [x for x in h.rooms if x.floor == r.floor and x.name == r.name]
    if len(same) > 1:
        name += str(same.index(r) + 1)
    return name


def ceiling_z(h, r):
    """器具取付面の高さ（絶対 z）。ジムは直天井（スラブ下面）。"""
    return h.fl["2F"] - h.slab_t if r.name == "ジム" else h.fl[r.floor] + h.ch[r.floor]


def _no_line(h, r):
    return any(k in r.name for k in _cfg(h)["no_line_rooms"])


def _blockers(h, its, r):
    holes = [sbox(*s.hole) for s in h.stairs] if r.floor == "1F" else []
    clr = _cfg(h)["line"]["hole_clear"]
    tall = [sbox(*i.rect).buffer(clr) for i in its if i.floor == r.floor and i.room == r.name
            and i.z0 + i.h >= h.fl[r.floor] + h.ch[r.floor] - 100 and not i.stack]
    return unary_union(tall + [p.buffer(clr) for p in holes])


# 室ごとの上書き（C-1.3 の表）: (向き, [(中心線, 端a, 端b)], lm/m)
def _override(h, r):
    if r.floor == "1F" and r.name == "キッチン":
        return [("x", y, 2000, 5600) for y in (7600, 9900)], 3000
    if r.floor == "1F" and r.name.startswith("ランドリー"):
        return [("x", y, 600, 5400) for y in (13000, 14000)], 2000
    if r.floor == "2F" and r.name == "主寝室":
        return [("x", y, 12788, 17588) for y in (13500, 17000)], 2500
    return None


def _generic(h, its, r):
    x0, y0, x1, y1 = r.rect
    w, d = x1 - x0, y1 - y0
    cfg = _cfg(h)["line"]
    along_x = w >= d
    long_, short = (w, d) if along_x else (d, w)
    n = max(1, round(short / cfg["row_pitch"]))
    if short < 1600:
        n = 1
    block = _blockers(h, its, r)
    segs = []
    for j in range(n):
        c = (y0 + d * (j + 0.5) / n) if along_x else (x0 + w * (j + 0.5) / n)
        a, b = ((x0 + cfg["end_clear"], x1 - cfg["end_clear"]) if along_x else (y0 + cfg["end_clear"], y1 - cfg["end_clear"]))
        L = LineString([(a, c), (b, c)] if along_x else [(c, a), (c, b)])
        rest = L.difference(block) if not block.is_empty else L
        parts = [g for g in getattr(rest, "geoms", [rest]) if g.length >= 600]
        if not parts:
            continue
        g = max(parts, key=lambda g: g.length)
        Lm = math.floor(g.length / cfg["cut_unit"]) * cfg["cut_unit"]
        cx, cy = g.centroid.x, g.centroid.y
        if along_x:
            segs.append(("x", cy, cx - Lm / 2, cx + Lm / 2))
        else:
            segs.append(("y", cx, cy - Lm / 2, cy + Lm / 2))
    return segs


def _room_need(h, r):
    x0, y0, x1, y1 = r.rect
    w, d = (x1 - x0) / 1000, (y1 - y0) / 1000
    A = w * d
    Hc = (h.fl["2F"] - h.slab_t - h.fl["1F"] if r.name == "ジム" else h.ch[r.floor]) / 1000
    k = A / (Hc * (w + d))
    u = _U(k) * DARK.get(next((kk for kk in DARK if kk in r.name), ""), 1.0)
    E = target_lx(h, r.name)
    return A, k, u, E, E * A / (u * _cfg(h)["maintenance_factor"])


def lines(h, its):
    """ライン器具: dict(id, floor, room, p0, p1, L, lm_per_m, kind)。座標は建物座標 mm（z は絶対高さ＝取付面）。"""
    cfg = _cfg(h)
    out = []
    for r in h.rooms:
        if _no_line(h, r):
            continue
        z = ceiling_z(h, r)
        ov = _override(h, r)
        if ov:
            segs = [(ax, c, a, b) for ax, c, a, b in ov[0]]
            cls = ov[1]
        else:
            segs = _generic(h, its, r)
            if not segs:
                continue
            A, k, u, E, need = _room_need(h, r)
            tot = sum(b - a for _, _, a, b in segs) / 1000
            lmpm = need / tot
            cls = next((c for c in cfg["line"]["classes_lm_per_m"] if c >= lmpm), cfg["line"]["classes_lm_per_m"][-1])
        code = room_code(h, r)
        for n, (ax, c, a, b) in enumerate(segs, 1):
            p0, p1 = ([a, c, z], [b, c, z]) if ax == "x" else ([c, a, z], [c, b, z])
            out.append(dict(id=f"{r.floor}-{code}-L{n}", code=code, floor=r.floor, room=r.name, p0=[round(v) for v in p0], p1=[round(v) for v in p1],
                            L=round(b - a), lm_per_m=cls, kind="line", axis=ax, group="L"))
        if "洗面" in r.name:                              # 鏡の上（カウンター W1-C の上の壁際）にも 1 本（鏡前 300lx 以上）
            out.append(dict(id=f"{r.floor}-{code}-L{len(segs) + 1}", code=code, floor=r.floor, room=r.name, p0=[9250, 13675, z], p1=[9250, 14575, z], L=900,
                            lm_per_m=1500, kind="line", axis="y", group="L"))
        if r.floor == "1F" and r.name == "キッチン":      # 背面の吊り棚（KB-S）の最下段の下面
            zs = h.fl["1F"] + 1700 - 20
            out.append(dict(id=f"1F-{code}-S1", code=code, floor="1F", room=r.name, p0=[2600, 11800, zs], p1=[5200, 11800, zs], L=2600, lm_per_m=1000,
                            kind="shelf", axis="x", group="L"))
    return out


def downlights(h, its, lns=None):
    """弱いダウンライト: ライン列の中間線上に長手方向 1,800 ピッチ。ライン軸から 450 以上・壁から 400 以上。"""
    cfg = _cfg(h)["downlight"]
    lns = lns if lns is not None else lines(h, its)
    out = []
    for r in h.rooms:
        if _no_line(h, r):
            continue
        rl = [l for l in lns if l["code"] == room_code(h, r) and l["floor"] == r.floor and l["kind"] == "line"]
        if not rl:
            continue
        x0, y0, x1, y1 = r.rect
        along_x = rl[0]["axis"] == "x"
        lo, hi = (y0, y1) if along_x else (x0, x1)
        a0, a1 = (x0, x1) if along_x else (y0, y1)
        cs = sorted({l["p0"][1] if along_x else l["p0"][0] for l in rl})
        if len(cs) >= 2:
            cross = [(p + q) / 2 for p, q in zip(cs, cs[1:])]
        elif hi - lo >= 2400:
            cross = [cs[0] - (hi - lo) / 4, cs[0] + (hi - lo) / 4]
        elif hi - lo >= 1700:                       # 幅の狭い室: 列の片側に 1 筋
            q = cs[0] + max(450, (hi - lo) / 4)
            cross = [q if q <= hi - cfg["min_from_wall"] else cs[0] - max(450, (hi - lo) / 4)]
        else:
            cross = []
        n = max(1, int((a1 - a0) // cfg["pitch"]))
        along = [a0 + (a1 - a0) * (i + 0.5) / n for i in range(n)]
        blk = _blockers(h, its, r)
        z = ceiling_z(h, r)
        lgeo = [LineString([l["p0"][:2], l["p1"][:2]]) for l in rl]
        for c in cross:
            for a in along:
                x, y = (a, c) if along_x else (c, a)
                if min(x - x0, x1 - x, y - y0, y1 - y) < cfg["min_from_wall"]:
                    continue
                pt = Point(x, y)
                if any(g.distance(pt) < cfg["min_from_line"] for g in lgeo) or (not blk.is_empty and blk.contains(pt)):
                    continue
                out.append(dict(p=[x, y, z], floor=r.floor, room=r.name, code=room_code(h, r), w=1.0, group="D"))
    return out


def footlights(h):
    """階段の足元灯 18 台。各段の踏面から 300（灯具の中心）、2 段おき（下の flight の 2・4・6・8 段、上の flight の 2・4・6・8 段）＋踊場 1 台。
    壁は上下の階段の間の手すり壁（LGS t100）の両面と、踊場の LGS 間仕切の面。"""
    ft = _cfg(h)["foot"]
    hh = ft["height_from_tread"]
    out = []
    for s in h.stairs:
        R, T = s.riser, s.tread
        xm = (s.x0 + s.x1) / 2
        dr = s.direction
        z1 = h.fl["1F"]
        zl = z1 + (s.half) * R                        # 踊場の床（1FL + 9R）
        for i in range(2, s.half, ft["every_steps"]):       # 下の flight 2,4,6,8 段
            out.append(dict(stair=s.name, flight="下", step=i, p=[xm - 50, s.y_entry + dr * (i - 0.5) * T, z1 + i * R + hh], n=[-1, 0]))
        # 踊場: 奥の LGS 間仕切の面（階段1 は東の x1 側＝西面、階段2 は西の x0 側＝東面）
        xl, nl = (s.x1, -1) if s.name == "階段1" else (s.x0, +1)
        yl_mid = (s.y_turn + s.hole[3]) / 2
        out.append(dict(stair=s.name, flight="踊場", step=s.half, p=[xl, yl_mid, zl + hh], n=[nl, 0]))
        for j in range(2, s.half, ft["every_steps"]):       # 上の flight 2,4,6,8 段
            out.append(dict(stair=s.name, flight="上", step=j, p=[xm + 50, s.y_turn - dr * (j - 0.5) * T, zl + j * R + hh], n=[+1, 0]))
    for i, f in enumerate(out, 1):
        f["id"] = f"{f['stair']}-F{i:02d}"
        f["floor"] = "1F"
        f["p"] = [round(v, 1) for v in f["p"]]
    return out


def tread_top(h, f):
    """足元灯のある段（踊場は床）の踏面の上面の高さ（絶対 z）。"""
    s = next(s for s in h.stairs if s.name == f["stair"])
    z1 = h.fl["1F"]
    zl = z1 + s.half * s.riser
    if f["flight"] == "下":
        return z1 + f["step"] * s.riser
    if f["flight"] == "上":
        return zl + f["step"] * s.riser
    return zl


# ------------------------------------------------------------------ 時刻ごとのチャネル
def _interp(pts, hour):
    """pts: [(時, K, %)]。同じ時刻が 2 つ並ぶときは階段状（後ろを採る）。それ以外は線形補間。"""
    hour = hour % 24
    i = max(j for j, p in enumerate(pts) if p[0] <= hour)
    a = pts[i]
    if i + 1 >= len(pts) or pts[i + 1][0] == a[0]:
        return a[1], a[2]
    b = pts[i + 1]
    t = (hour - a[0]) / (b[0] - a[0])
    return a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t


def channels(spec, hour, room=""):
    """L（ライン）・D（ダウンライト）・F（足元灯）の (色温度 K, 明るさ %)。smart.lighting_schedule の値は変えない。"""
    ch = spec["lighting"]["channels"]
    out = {k: _interp(ch[k], hour) for k in ("L", "D", "F")}
    h24 = hour % 24
    if "居室" in room or room == "主寝室":              # 寝室: 21 時以降 L 消灯、D は 20% 以下
        if h24 >= 21 or h24 < 6:
            out["L"] = (out["L"][0], 0.0)
            out["D"] = (out["D"][0], min(out["D"][1], 20.0))
    if room == "ジム":                                   # 使用中は 5000K・100%
        out["L"] = (5000, 100.0) if 6 <= h24 < 22 else (out["L"][0], 0.0)
    return {k: (round(v[0]), round(v[1], 1)) for k, v in out.items()}


# ------------------------------------------------------------------ 照度計算表（E-06）
def illuminance_table(h, its):
    lns = lines(h, its)
    dl = downlights(h, its, lns)
    rows = []
    for r in h.rooms:
        rl = [l for l in lns if l["floor"] == r.floor and l["code"] == room_code(h, r)]
        A, k, u, E, need = _room_need(h, r)
        if not rl:
            rows.append(dict(floor=r.floor, room=r.name, area=A, k=k, U=u, target=E, need=0, n=0, lengths="—", lm_per_m=0, lm=0, E=0, dl=0))
            continue
        tot = sum(l["L"] * l["lm_per_m"] for l in rl)
        # 棚下ライン（作業用）は床面平均には数えない
        lm = sum(l["L"] / 1000 * l["lm_per_m"] for l in rl if l["kind"] == "line")
        rows.append(dict(floor=r.floor, room=r.name, area=A, k=k, U=u, target=E, need=need, n=len(rl), lengths="＋".join(f"{l['L']:,}" for l in rl),
                         lm_per_m=max(l["lm_per_m"] for l in rl), lm=lm, E=lm * u * _cfg(h)["maintenance_factor"] / A,
                         dl=sum(1 for d in dl if d["floor"] == r.floor and d["code"] == room_code(h, r))))
    return rows


# ------------------------------------------------------------------ DALI 系統・グループ（E-06）
def device_count(l):
    """ライン器具 1 列を 1,200〜2,400 の器具に分けた台数（1 台ずつドライバー内蔵）。"""
    return max(1, math.ceil(l["L"] / 2400))


def dali_groups(h, its):
    """階ごとに、室×チャネル（L・D・F）をグループにして DALI-2 の系統（64 台・16 グループ）へ順に割り付ける。
    戻り値: [dict(floor, system, group, name, ch, devices)]。"""
    lns = lines(h, its)
    dl = downlights(h, its, lns)
    ft = footlights(h)
    out = []
    for fl in ("1F", "2F"):
        groups = []
        for r in h.rooms:
            if r.floor != fl:
                continue
            code = room_code(h, r)
            n_l = sum(device_count(l) for l in lns if l["floor"] == fl and l["code"] == code and l["kind"] == "line")
            n_s = sum(device_count(l) for l in lns if l["floor"] == fl and l["code"] == code and l["kind"] == "shelf")
            n_d = sum(1 for d in dl if d["floor"] == fl and d["code"] == code)
            if n_l:
                groups.append((f"{code}-L", "L", n_l))
            if n_s:
                groups.append((f"{code}-棚下", "L", n_s))
            if n_d:
                groups.append((f"{code}-D", "D", n_d))
        if fl == "1F":
            for s in h.stairs:
                groups.append((f"{s.name}-F", "F", sum(1 for f in ft if f["stair"] == s.name)))
        sysn, gi, dev = 1, 0, 0
        for name, ch, n in groups:
            if gi >= _cfg(h)["dali"]["groups_per_system"] or dev + n > _cfg(h)["dali"]["devices_per_system"]:
                sysn, gi, dev = sysn + 1, 0, 0
            out.append(dict(floor=fl, system=f"{fl}-{sysn}", group=f"G{gi}", name=name, ch=ch, devices=n))
            gi += 1
            dev += n
    return out
