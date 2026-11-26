"""家具の仮置き（後日差し替え）と内装の3D部材。House を読むだけで、House には入れない。

- ITEMS 相当の一覧は items(h)。spec.yaml の furniture（商品・切替）を反映する
- check(h, items): 室の内側／壁・扉の軌跡／階段／ジム機器／家具同士／すき間／チェアの総数 を検査してエラー一覧を返す
- meshes(h, items): 家具の形状（(グループ, 階, 材質キー, ID, trimesh)）
- downlights(h, items): 埋込ダウンライトの位置
- schedule_rows(h, items): 家具表（図面 I-05）

寸法・色のうち、指定商品2点（OSB テーブル・スクールチェア）は商品ページ未確認の仮定値。spec.yaml の
furniture.products だけを直せば、図面・CG・家具表が連動する。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.affinity import rotate as srotate
from shapely.geometry import box as sbox, Polygon
from shapely.ops import unary_union

import furniture_shapes as FS

import kitchen_open as KO

CHAIR_KINDS = ("chair", "stool", "school_chair")
LDK = "リビング・ダイニング"

BASE_TEXT = {
    "plinth": "台輪（H60）", "legs": "脚（座下430）", "legs690": "脚（天板下690・ロの字脚）", "legs260": "脚下260",
    "float650": "浮かせ（下端 FL+650）", "none": "床置き", "ceiling": "天井から吊り", "frame": "突っ張り枠", "pot": "鉢を床に直置き",
    "unit": "ユニット", "stack": "上に立て掛け・載せ置き",
    "legs25": "脚 □25・底板 FL+300", "wallfix": "ふかし壁に固定",
}


@dataclass
class Item:
    id: str
    floor: str
    room: str
    name: str
    kind: str
    rect: tuple
    z0: float
    h: float
    mat: str
    base: str = "plinth"
    chair: bool = False
    seat: bool = False
    rot: float = 0.0
    product: str = ""
    qty: int = 1
    head: str = ""
    front: str = ""
    stack: bool = False          # 他の家具の上・壁際に載るもの（重なり・すき間の検査から除く）
    provisional: bool = True
    note: str = ""
    slot: tuple | None = None    # v4.36: 窓辺の収納の吹出しスリットの範囲（建物座標 mm、幅方向）
    under: str = ""              # v4.37: 階段下の収納（階段名）。室の矩形・階段の検査の代わりに段裏との離隔を検査する
    pocket: float = 0.0          # v4.37: 背面の戸袋の奥行（GD-1 の引込み）
    footline: bool = False       # v4.38: 家具の外周に足元灯ラインを回す（H-S3 の台輪）
    plinth: float = 60.0         # v4.38: 台輪の高さ（350 のときは固定パネルで引込み 0）
    leaves: int = 0              # v4.38: 扉の枚数（0 は従来の 450 ピッチ）
    hjoint: float = 1100.0       # v4.38: 扉の横目地の高さ（0 は無し）

    @property
    def w(self):
        return self.rect[2] - self.rect[0]

    @property
    def d(self):
        return self.rect[3] - self.rect[1]

    def poly(self):
        p = sbox(*self.rect)
        if self.rot:
            p = srotate(p, self.rot, origin=p.centroid)
        return p


# ------------------------------------------------------------------ 家具表（建物座標 mm）
def items(h):
    """spec.furniture を反映した家具の一覧（A.2）。"""
    sp = h.spec["furniture"]
    P = sp["products"]
    T, C = P["table_osb"], P["school_chair"]
    FL = h.fl
    DOMA = FL["1F"] - 2 * h.genkan["step"]
    out = []

    def add(i, fl, room, name, kind, rect, H, mat, z0=None, base="plinth", **kw):
        out.append(Item(i, fl, room, name, kind, tuple(float(v) for v in rect), FL[fl] if z0 is None else z0, H, mat, base, **kw))

    # ---- 1F LDK（指定商品 2 点・チェアはこの 1 脚だけ）。v4.44: 通り芯の均等化でキッチンは x125〜5300・y5300〜10700（Y2 の開口 x1,000〜5,100）
    tx, ty = 2337.5, 3150.0           # v4.45: テーブルを LDK へ戻す（x1,450〜3,225・y2,725〜3,575）。西の LDK-C2 と 275、南の LDK-C1 前面と 1,500、北は Y2 面まで 1,725
    add("L-T1", "1F", "リビング・ダイニング", T["name"], "table_osb", (tx - T["w"] / 2, ty - T["d"] / 2, tx + T["w"] / 2, ty + T["d"] / 2), T["h"], "osb",
        base="legs690", product="table_osb")
    # チェアはテーブルの東の短辺側に、西（テーブル）向きに置く（v4.45: 西は LDK-C2 との間が狭い）。さらに −8° 振る（rot −98°）
    ccx = tx + T["w"] / 2 + 60 + C["d"] / 2
    add("L-C1", "1F", "リビング・ダイニング", C["name"], "school_chair", (ccx - C["w"] / 2, ty - C["d"] / 2, ccx + C["w"] / 2, ty + C["d"] / 2), C["h"], "chair_wood",
        base="legs", chair=True, rot=-98.0, product="school_chair")
    add("L-S1", "1F", LDK, "サイドボード（台輪）", "cabinet", (4850, 225, 5300, 2475), 700, "case_ash")
    add("L-K1", "1F", LDK, "リビング収納（天井まで・開き戸＋天袋 FL+2,200〜・W825）", "tall", (175, 4850, 1000, 5300), h.ch["1F"], "case_ash", hjoint=2200.0)
    add("LDK-C1", "1F", LDK, "窓辺の造作収納 南（FL+700・奥行 1,000・オーク天板 t40・前面は引出し・奥は跳ね上げ蓋）", "sill_storage", (175, 225, 4000, 1225), 700, "sill_panel", base="none", front="+y",
        slot=None, note="v4.36 施主指示で台→収納。仕様は要施主確認")
    add("LDK-C2", "1F", LDK, "窓辺の造作収納 西（同上・L 字でつながる）", "sill_storage", (175, 1225, 1175, 4000), 700, "sill_panel", base="none", front="+x",
        slot=None, note="v4.36 施主指示で台→収納。v4.38 クアッドガラスで吹出しを廃止")
    add("L-K2", "1F", LDK, "リビング収納 南（天井まで・D825・開き戸 2 枚＋天袋・可動棚・人感 LED）", "tall", (175, 4000, 1000, 4850), h.ch["1F"], "case_ash", front="+x", leaves=2, hjoint=2200.0)
    add("L-K3", "1F", LDK, "リビング収納 東（天井まで・引違い戸 2 枚（上吊り）・可動棚・背面 130 は GD-1 の戸袋）", "tall", (4850, 4050, 5300, 4700), h.ch["1F"], "case_ash", front="-x", pocket=130.0, leaves=2, hjoint=0.0)
    add("L-A1", "1F", LDK, "アートパネル（サイドボードの上に立て掛け）", "art", (5170, 700, 5200, 1600), 640, "art", z0=FL["1F"] + 700, base="stack", stack=True)
    # ---- キッチン（v4.45: 一式を dy −1,650、アイランドは南へ、東カウンター L1,750。v4.44: v4.43 の背面側の一式を dx −475・dy −1,300、アイランドは W2,275・dy −1,200、KS-W は撤去）
    add("K-I1", "1F", "キッチン", "アイランドキッチン W2,275（IH 3口・一体成形シンク・ダウンドラフト換気、南＝LDK を向いて調理）", "island", (1325, 6200, 3600, 7200), 900, "olive_case")
    add("KB-W", "1F", "キッチン", "背面のふかし壁（ステンレス）", "kb_wall", (1325, 9000, 5300, 9050), h.ch["1F"], "stainless", base="none")
    add("KB-C", "1F", "キッチン", "背面カウンター（下部オープン棚・L 字の北辺）", "kb_counter", (2025, 8400, 5300, 9000), 900, "stainless", base="legs25", front="-y")
    add("KB-C2", "1F", "キッチン", "L 字の東カウンター（下部オープン棚・D500）", "kb_counter", (4800, 6650, 5300, 8400), 900, "stainless", base="legs25", front="-x")
    add("KB-R", "1F", "キッチン", "壁付けレール φ12（台所用具）", "kb_rail", (2825, 8950, 4725, 9000), 12, "stainless", z0=FL["1F"] + KO.RAIL_Z, base="wallfix", stack=True)
    add("KB-N", "1F", "キッチン", "施錠式ナイフケース W450×H300×D80（FL+1,250〜1,550）", "kb_knife_case", (2175, 8920, 2625, 9000), 300, "steel_black", z0=FL["1F"] + KO.KNIFE_Z[0],
        base="wallfix", stack=True, note="包丁の扱い（施錠ケース／磁石バー／引出し）は要施主確認")
    add("KB-S", "1F", "キッチン", "吊り棚 1 段（天端 FL+1,550・落下防止バー）", "kb_shelves", (2725, 8700, 4825, 9000), 72, "stainless", z0=FL["1F"] + KO.KS_TIERS[0],
        base="wallfix", stack=True)
    add("KB-F", "1F", "キッチン", "冷蔵庫＋上部ふさぎ板", "kb_fridge", (1325, 8400, 2025, 9000), h.ch["1F"], "stainless", base="none")
    # ---- 玄関・ホール（v4.44: 玄関収納は GD-1 の降り口 y2,700〜4,100 を空けた造作）
    add("G-S1", "1F", "玄関土間", "下足入れ（造作・天井まで・扉付き・電波遮断キーボックス内蔵）", "tall", h.shoe, FL["1F"] + h.ch["1F"] - DOMA, "case_ash", z0=DOMA, front="+x")
    add("G-B1", "1F", "玄関土間", "腰掛けベンチ（造作、座 H420＋クッション）", "bench", h.bench, 420, "case_ash", z0=DOMA, seat=True, front="+y", note="座る家具。要施主確認")
    add("H-S2", "1F", "玄関収納", "コート収納（造作・天井まで）", "tall", (5550, 4100, 5925, 5300), h.ch["1F"], "case_ash", front="+x")
    add("H-S4", "1F", "ホール・階段1", "階段1 下の収納（H1,500・両開き戸・棚 1 段＋キャスター付きワゴン 2・人感 LED・内装不燃）", "tall", (6600, 8500, 7550, 9540), 1500, "case_ash", front="-y", under="階段1", leaves=2)
    # ---- ジム（機器は h.equipment）
    add("J-M1", "1F", "ジム", "鏡（突っ張り枠・飛散防止フィルム。S 壁の内面・トレッドミルの正面）", "mirror", tuple(h.spec["gym_layout"]["mirror"]), 2000, "mirror", z0=FL["1F"] + 300, base="frame", stack=True)
    add("J-K1", "1F", "ジム", "測定コーナーのカウンター（体組成計は床、血圧計は天板）", "cabinet", tuple(h.spec["gym_layout"]["counter"]), 900, "case_ash")
    add("J-S1", "1F", "ジム収納", "器具・マットの棚（天井まで・扉付き）", "tall", (10950, 10250, 13100, 10700), h.ch["1F"], "case_ash", front="-y")
    # ---- 水回り
    add("T1-W", "1F", "トイレ（手洗い付）", "タンク式便器（フチなし）", "toilet", (9700, 7100, 10200, 7600), 800, "ceramic", base="none")
    add("T1-H", "1F", "トイレ（手洗い付）", "手洗いカウンター（一体成形・浮かせ）", "counter_float", (10400, 5550, 10700, 6550), 850, "solid_surface", base="float650")
    # v4.40 PS（パイプスペース）: LGS＋耐水PB・EP、点検扉 1 枚（FL+60〜2,700）。2F の排水・給水を通す（long_life.ps、48章）
    for pid, room, rect, front, note in h.spec["long_life"]["ps"]:
        add(pid, "1F", room, f"PS（パイプスペース）LGS＋耐水PB・点検扉 1 枚 FL+60〜2,700・{note}", "ps", tuple(rect), h.ch["1F"], "wet_panel",
            base="none", front=front, leaves=1, hjoint=0.0)
    add("W1-C", "1F", "洗面・脱衣", "洗面カウンター（一体成形ボウル・浮かせ。鏡は突っ張り枠で天井まで）", "counter_float", (5550, 13500, 6100, 14900), 850, "solid_surface", base="float650")
    add("W1-S", "1F", "洗面・脱衣", "リネン収納（天井まで）", "tall", (6000, 15675, 7650, 16125), h.ch["1F"], "case_ash")
    add("B1-U", "1F", "浴室", "ユニットバスの浴槽（エプロン一体）", "tub", (8900, 14450, 10700, 15250), 550, "tub", base="unit")
    add("R-WD", "1F", "ランドリー・室内干し", "ドラム式洗濯乾燥機 ×2（W640×D720×H1060 各）", "washer2", (4000, 14705, 5300, 15425), 1060, "appliance_white", base="none", qty=2)
    add("R-SK", "1F", "ランドリー・室内干し", "作業カウンター＋スロップシンク", "cabinet", (3150, 14775, 4000, 15425), 900, "solid_surface")
    add("R-DK", "1F", "ランドリー・室内干し", "掃除ロボットのドック（1階、自動ゴミ収集・給排水直結）", "dock", (2225, 13400, 2675, 13900), 600, "appliance_white", base="none")
    add("R-HP", "1F", "ランドリー・室内干し", "物干しパイプ（天井付け・取外し式）×2", "hang_pole", (2400, 11600, 4900, 12400), 30, "stainless", z0=FL["1F"] + h.ch["1F"] - 450,
        base="ceiling", qty=2, stack=True)
    add("R-S1", "1F", "ホール・階段2", "階段2 下の収納（H2,350・両開き戸・チャイルドロック・スチール可動棚・人感 LED・内装不燃）", "tall", (1175, 13100, 2125, 13900), 2350, "case_ash", front="-y", under="階段2", leaves=2, hjoint=0.0)
    add("M1-A", "1F", "機械室（西系統）", "空調機・全熱交換器（簡易ボリューム）", "machine", (10950, 14900, 13487, 16125), 1900, "machine", base="none")
    add("M2-A", "1F", "機械室（東系統）", "浄水器・ネットワークラック・排煙機（簡易ボリューム）", "machine", (13587, 15100, 16125, 16125), 1900, "machine", base="none")
    # ---- 2F
    add("B-B1", "2F", "居室B", "ベッド シングル", "bed", (1245, 2300, 2245, 4300), 520, "case_oak", base="legs260", head="+y")
    add("C-B1", "2F", "居室C", "ベッド シングル", "bed", (9700, 2300, 10700, 4300), 520, "case_oak", base="legs260", head="+y")
    add("D-B1", "2F", "居室D", "ベッド シングル", "bed", (1500, 8300, 2500, 10300), 520, "case_oak", base="legs260", head="+y")
    add("D-C1", "2F", "居室D", "チェスト", "cabinet", (1955, 10300, 2755, 10700), 700, "case_ash")
    add("TH-S", "2F", "シアター", "スクリーン 120型（16:9・2,657×1,494、南の壁の前）", "screen", (12150, 125, 14950, 225), 1700, "screen", z0=FL["2F"] + 700, base="frame", stack=True)
    add("TH-A", "2F", "シアター", "AV ボード（スピーカー内蔵）", "cabinet", (11950, 125, 15150, 575), 450, "theater_case")
    add("TH-F", "2F", "シアター", "箱型ソファ 3人掛け（背・肘あり、台輪で床まで塞ぐ）", "sofa", (12040, 3500, 15040, 4450), 780, "sofa_olive", seat=True, front="-y",
        note="座る家具。要施主確認")
    add("LB-S1", "2F", "図書室", "本棚（天井まで突っ張り・背面連結）東", "bookcase", (15775, 8759, 16125, 10009), h.ch["2F"], "case_oak")
    add("LB-S2", "2F", "図書室", "本棚（天井まで突っ張り・背面連結）北", "bookcase", (13000, 14687, 15700, 15037), h.ch["2F"], "case_oak")
    add("LB-B1", "2F", "図書室", "窓下の造作ベンチ（収納兼用、座 H420、からし色のクッション）", "bench", (15675, 11600, 16125, 13400), 420, "case_oak", seat=True, front="-x", note="座る家具。要施主確認")
    add("LB-T1", "2F", "図書室", "閲覧台（立って読む H950）", "cabinet", (12000, 12100, 13500, 12900), 950, "case_oak")
    add("LB-P1", "2F", "図書室", "鉢植え（フィカス）φ400", "plant", (10950, 14637, 11350, 15037), 1500, "leaf", base="pot")
    add("MB-B1", "2F", "主寝室", "ベッド セミダブル 1200×2000（1台、頭は北の壁）", "bed", (3333, 2300, 4533, 4300), 520, "case_oak", base="legs260", head="+y")
    add("MB-N1", "2F", "主寝室", "ナイトテーブル", "cabinet", (2883, 3900, 3333, 4350), 450, "case_ash")
    add("A-B1", "2F", "居室A", "ベッド シングル 1000×2000（頭は北）", "bed", (6716, 2300, 7716, 4300), 520, "case_oak", base="legs260", head="+y")
    add("A-C1", "2F", "居室A", "チェスト", "cabinet", (5550, 1000, 5950, 1800), 700, "case_ash")
    add("MB-C1", "2F", "主寝室", "チェスト", "cabinet", (2345, 1000, 2795, 1800), 700, "case_ash")
    add("D2-DK", "2F", "廊下（北）", "掃除ロボットのドック（2階。トイレの給排水から壁越しに直結）", "dock", (10250, 12950, 10700, 13400), 600, "appliance_white", base="none")
    add("T3-W", "2F", "トイレ（手洗い付）", "タンク式便器（フチなし）", "toilet", (9700, 7100, 10200, 7600), 800, "ceramic", base="none")
    add("T3-H", "2F", "トイレ（手洗い付）", "手洗いカウンター（浮かせ）", "counter_float", (10400, 5550, 10700, 6550), 850, "solid_surface", base="float650")
    add("T4-W", "2F", "トイレ", "タンク式便器（フチなし）", "toilet", (8700, 15050, 9200, 15550), 800, "ceramic", base="none")
    add("T4-H", "2F", "トイレ", "手洗いカウンター（浮かせ）", "counter_float", (10400, 14000, 10700, 15000), 850, "solid_surface", base="float650")
    # ---- 切替: 座る家具をまとめて外す（シアターのソファ・図書室のベンチ・玄関ベンチ）
    if not sp.get("optional_seating", True):
        out = [i for i in out if not i.seat]
    # 床置きの家具の正面の向き（部屋の中心側）
    rc = {(r.floor, r.name): ((r.rect[0] + r.rect[2]) / 2, (r.rect[1] + r.rect[3]) / 2) for r in h.rooms}
    for it in out:
        if not it.front:
            it.front = FS.front_of(it.rect, rc[(it.floor, it.room)])
        it.provisional = bool(sp.get("provisional", True))
    return out


# ------------------------------------------------------------------ 干渉検査
def room_polys(h, fl, name):
    return [sbox(*r.rect) for r in h.rooms if r.floor == fl and r.name == name]


def wall_rects(h, fl):
    """階 fl の RC 壁・間仕切りの全長の矩形（開口を抜かない）。"""
    out = []
    for w in h.walls:
        if w.cat not in ("wall", "partition") or w.floor != fl:
            continue
        t2 = w.t / 2
        out.append(sbox(w.a, w.c - t2, w.b, w.c + t2) if w.axis == "x" else sbox(w.c - t2, w.a, w.c + t2, w.b))
        for (e0, e1, te, sg) in w.extra:                 # 局所の増し打ち（v4.18）
            lo, hi = sorted((w.c + sg * t2, w.c + sg * (t2 + te)))
            out.append(sbox(e0, lo, e1, hi) if w.axis == "x" else sbox(lo, e0, hi, e1))
    return out


def door_zones(h, fl):
    """(名前, ポリゴン, 種別) 開き戸の軌跡と、扉・開口の前後 600 の通行帯。"""
    zs = []
    for w in h.walls:
        if w.cat == "insul":
            continue
        for op in w.openings:
            if op.floor != fl or op.kind != "door" or op.exterior:
                continue
            nm = op.label or op.name
            if op.operation == "swing" and op.width < 1400:
                r = op.width
                hu = op.u0 if op.hinge == 0 else op.u1
                pts = [(hu, 0)]
                for k in range(17):
                    a = math.radians(90 * k / 16)
                    pts.append((hu + r * math.cos(a) * (1 if op.hinge == 0 else -1), r * math.sin(a) * op.swing))
                off = w.t / 2 * op.swing
                poly = [(u, w.c + off + v) if w.axis == "x" else (w.c + off + v, u) for u, v in pts]
                zs.append((nm + "の軌跡", Polygon(poly).buffer(0)))
            q = (op.u0, w.c - w.t / 2 - 600, op.u1, w.c + w.t / 2 + 600) if w.axis == "x" else (w.c - w.t / 2 - 600, op.u0, w.c + w.t / 2 + 600, op.u1)
            zs.append((nm + "の通行帯", sbox(*q)))
    return zs


def stair_zone(h, fl):
    out = []
    for s in h.stairs:
        out.append(sbox(*s.footprint(h.stair_end(s))) if fl == "1F" else sbox(*s.hole))
    return out


def stair_soffit(h, name, poly):
    """階段 name の段板・踊場の箱のうち、平面で poly と重なるものの下端の最小（絶対 z）。v4.37 階段下の収納。"""
    import house as HM
    s = [x for x in h.stairs if x.name == name][0]
    zs = [b.z0 for b in s.boxes(h.stair_end(s)) if sbox(b.x0, b.y0, b.x1, b.y1).intersection(poly).area > 1]
    return min(zs) if zs else float("inf")


def gap_errors(h, its):
    """家具と壁・家具どうしの間のすき間: 0〜5mm（密着）か 250mm 以上。8〜25（指）・100〜230（頭）のすき間をつくらない。"""
    errs = []
    forbid = [i for i in its if not i.stack and i.base != "ceiling"]
    for it in forbid:
        if it.rot:
            continue
        x0, y0, x1, y1 = it.rect
        walls = [w.bounds for w in wall_rects(h, it.floor)]
        others = [o.rect for o in forbid if o is not it and o.floor == it.floor and not o.rot]
        sides = [("W", x0, (y0, y1), -1, 0), ("E", x1, (y0, y1), +1, 0), ("S", y0, (x0, x1), -1, 1), ("N", y1, (x0, x1), +1, 1)]
        for nm, c, (a, b), sgn, ax in sides:
            best = None
            for bx in walls + others:
                lo, hi = (bx[1], bx[3]) if ax == 0 else (bx[0], bx[2])
                if min(b, hi) - max(a, lo) < 1:
                    continue
                face = (bx[0] if sgn > 0 else bx[2]) if ax == 0 else (bx[1] if sgn > 0 else bx[3])
                g = (face - c) * sgn
                if g < -1:
                    continue
                if best is None or g < best:
                    best = g
            if best is not None and 5 < best < 250:
                errs.append((it.id, f"{nm}側のすき間 {best:.0f}mm（0〜5 か 250 以上にする）"))
    return errs


def check(h, its):
    """干渉・すき間・チェアの総数。エラーの一覧 [(ID, 内容)] を返す（空なら適合）。"""
    errs = []
    solids = {fl: wall_rects(h, fl) for fl in ("1F", "2F")}
    for it in its:
        p = it.poly()
        rp = room_polys(h, it.floor, it.room)
        if it.under:
            rp = rp + [sbox(*s.footprint(h.stair_end(s))) for s in h.stairs if s.name == it.under]
            rp = [unary_union(rp)]
        if not any(r.buffer(1).contains(p) for r in rp):
            errs.append((it.id, "室の外にはみ出す"))
        for wp in solids[it.floor]:
            if wp.intersection(p).area > 1:
                errs.append((it.id, "壁と重なる"))
                break
        if not it.stack and it.base != "ceiling" and it.z0 < h.fl[it.floor] + 1900:
            for nm, z in door_zones(h, it.floor):
                if z.intersection(p).area > 100:
                    errs.append((it.id, "扉・開口と重なる: " + nm))
        if it.under:
            sf = stair_soffit(h, it.under, p)
            if it.z0 + it.h > sf - 50:
                errs.append((it.id, f"段裏との離隔が 50 未満（段裏 FL+{sf - h.fl[it.floor]:.0f}）"))
        else:
            for s in stair_zone(h, it.floor):
                if s.intersection(p).area > 1:
                    errs.append((it.id, "階段と重なる"))
        if it.floor == "1F":
            for name, r, hh, kg in h.equipment:
                if sbox(*r).intersection(p).area > 1:
                    errs.append((it.id, "ジム機器と重なる: " + name))
            if sbox(*h.battery_room.rect).intersection(p).area > 1:
                errs.append((it.id, "蓄電室と重なる"))
            if sbox(*h.treadmill_zone).intersection(p).area > 1:
                errs.append((it.id, "トレッドミル後方の安全帯と重なる"))
        if it.z0 + it.h > h.fl[it.floor] + h.ch[it.floor] + 1:
            errs.append((it.id, "天井より高い"))
    for a in range(len(its)):
        for b in range(a + 1, len(its)):
            A, B = its[a], its[b]
            if A.stack or B.stack or A.floor != B.floor:
                continue
            if A.poly().intersection(B.poly()).area > 1:
                errs.append((A.id, "家具同士が重なる: " + B.id))
    errs += gap_errors(h, its)
    # チェアの総数（施主指示: LDK に 1 脚だけ）
    limit = h.spec["furniture"].get("chair_limit", 1)
    ch = [i for i in its if i.chair]
    if len(ch) != limit:
        errs.append(("chair", f"チェアの数が {len(ch)}（指定 {limit}）"))
    for i in ch:
        if i.room not in (LDK, "キッチン"):
            errs.append((i.id, "チェアが LDK（キッチン含む）にない"))
    for i in its:
        if i.kind in CHAIR_KINDS and not i.chair:
            errs.append((i.id, "チェア類がチェアとして登録されていない"))
    return errs


# ------------------------------------------------------------------ 形状
def build_item(h, it, prod=None):
    """1 点の家具を MB（mm）に作る。"""
    P = h.spec["furniture"]["products"]
    mb = FS.MB()
    KO.CH = h.ch["1F"]
    k, rect, z0, H = it.kind, it.rect, it.z0, it.h
    x0, y0, x1, y1 = rect
    if k == "table_osb":
        FS.table_osb(mb, rect, z0, P["table_osb"])
    elif k == "school_chair":
        FS.school_chair(mb, rect, z0, P["school_chair"])
    elif k == "bed":
        FS.bed(mb, rect, z0, it.head)
    elif k == "plant":
        FS.plant(mb, rect, z0, H, it.id, pot_h=380 if H > 1700 else 330)
    elif k == "bookcase":
        FS.bookcase(mb, rect, z0, H, it.front, it.mat if it.mat in ("case_oak", "case_ash") else "case_oak")
    elif k == "tall_kitchen":
        FS.tall_kitchen(mb, rect, z0, it.front, P)
    elif k in ("kb_wall", "kb_counter", "kb_rail", "kb_knife_case", "kb_shelves", "kb_fridge", "ks_wall"):
        fz = z0 if k not in ("kb_wall", "kb_counter", "kb_fridge", "ks_wall") else h.fl[it.floor]
        if k == "kb_counter":
            KO.kb_counter(mb, rect, fz, front=it.front or "-y")
        else:
            getattr(KO, k)(mb, rect, fz)
    elif k == "island":
        FS.island(mb, rect, z0, P)
    elif k in ("tall", "cabinet", "bench", "ps"):
        top = None
        if it.id in ("R-SK", "J-K1"):
            top = ("countertop", 20)
        if it.id in ("LB-T1",):
            top = ("case_oak", 30)
        crect = rect
        if it.pocket > 0:    # v4.37: 背面の戸袋（GD-1 の開いた戸が入る）。本体は背面から pocket だけ縮める
            Lp = FS.LF(mb, rect, it.front)
            ux0, uy0, ux1, uy1 = Lp.xy(0, Lp.W, it.pocket, Lp.D)
            crect = (ux0, uy0, ux1, uy1)
        FS.case(mb, crect, z0, H, it.front, it.mat if it.id != "R-SK" else "case_ash", top=top, pitch=(abs(FS.LF(mb, crect, it.front).W) / it.leaves if it.leaves else (450 if k != "bench" else 600)), plinth=it.plinth, setback=0 if it.plinth > 60 else 40, hj=it.hjoint)
        if it.pocket > 0:
            Lp = FS.LF(mb, rect, it.front)
            Lp.box("case_ash", Lp.W - 20, Lp.W, 0, it.pocket, z0, z0 + H)          # 戸袋の北の端板
            Lp.box("case_ash", 0, Lp.W, 60, it.pocket, z0 + 2150, z0 + H)           # 戸袋の上の幕板（壁から 60 はレールカバー）
        if k == "bench":
            L = FS.LF(mb, rect, it.front)
            ck = "cushion" if it.id == "LB-B1" else "throw"
            L.box(ck, 15, L.W - 15, 15, L.D - 15, z0 + H, z0 + H + 45)
    elif k == "sill_counter":
        FS.sill_counter(mb, rect, z0, H, it.front)
    elif k == "sill_storage":
        FS.sill_storage(mb, rect, z0, H, it.front, slot=it.slot)
    elif k == "counter_float":
        FS.counter_float(mb, rect, z0, H, it.front)
    elif k == "toilet":
        FS.toilet(mb, rect, z0)
    elif k == "washer2":
        FS.washer2(mb, rect, z0, it.front)
    elif k == "dock":
        FS.dock(mb, rect, z0, H)
    elif k == "machine":
        FS.machine_box(mb, rect, z0, H)
    elif k == "hang_pole":
        FS.hang_pole(mb, rect, z0, h.fl[it.floor] + h.ch[it.floor])
    elif k == "mirror":
        fz = h.fl[it.floor]
        FS.mirror(mb, rect, z0, H, fz + h.ch[it.floor] + 380, fz)
    elif k == "screen":
        FS.screen_panel(mb, rect, z0, H)
    elif k == "sofa":
        FS.sofa(mb, rect, z0, it.front)
    elif k == "art":
        FS.art_panel(mb, rect, z0, H)
    elif k == "tub":
        FS.tub(mb, rect, z0, H)
    elif k == "shower":
        FS.shower_unit(mb, rect, z0, H)
    else:
        mb.box(it.mat, x0, y0, z0, x1, y1, z0 + H)
    if it.rot:
        mb.rotate_z(it.rot, (x0 + x1) / 2, (y0 + y1) / 2)
    return mb


def meshes(h, its):
    """[(グループ, 階, 材質キー, ID, trimesh（m）)] 家具とジム機器。"""
    out = []
    for it in its:
        mb = build_item(h, it)
        for key, m in mb.meshes().items():
            out.append(("家具", it.floor, key, it.id, m))
    # 台所小物（露出する物。材質ごとに 1 ノード）
    for key, m in KO.props(h).meshes().items():
        out.append(("台所小物", "1F", key, None, m))
    # ジム機器（既存の矩形の内側に形を作る）
    f1 = h.fl["1F"]
    for n, (name, r, hh, kg) in enumerate(getattr(h, "equipment_cg", h.equipment)):
        mb = FS.MB()
        FS.gym_equipment(mb, name, r, hh, f1)
        for key, m in mb.meshes().items():
            out.append(("家具", "1F", key, f"GYM{n + 1:02d}", m))
    return out


# ------------------------------------------------------------------ ダウンライト
def downlights(h, its):
    """埋込ダウンライト（弱い補助灯 φ100）の位置。v4.17 から lighting.downlights（ライン照明の中間線上・ライン軸から 450 以上・壁から 400 以上）。"""
    import lighting
    return lighting.downlights(h, its)


# ------------------------------------------------------------------ 家具表
def schedule_rows(h, its, short=False):
    """家具表の行: ID／室／名称／W×D×H／数量／材質・色／商品名／床との納まり。"""
    pal = h.spec["interior_palette"]

    def mat_text(it):
        m = pal.get(it.mat, {})
        hx = m.get("color", "")
        label = {"osb": "OSB t30（クリア塗装）＋ステンレス縁", "chair_wood": "座・背 合板（チャコールブラウン）／フレーム 鋼管（黒に近い暗褐色）",
                 "case_ash": "アッシュ突板", "case_oak": "オーク突板", "olive_case": "オリーブ色の扉", "solid_surface": "人造大理石（一体成形）", "sill_panel": "前面 人造大理石（艶消し・巾木と同色）／天板 オーク無垢積層 t40",
                 "leaf": "植物（鉢は生成り）", "art": "アート（からし・オリーブ）", "ceramic": "陶器", "tub": "ユニットバス", "mirror": "鏡",
                 "screen": "スクリーン（白）", "stainless": "ステンレス", "sofa_olive": "布張り（オリーブ）", "appliance_white": "家電（白）",
                 "theater_case": "AV 台（暗褐色）", "machine": "機器（灰）"}.get(it.mat, it.mat)
        return f"{label} {hx}".strip()

    rows = []
    for it in its:
        W, D = round(it.w), round(it.d)
        if it.kind == "plant":
            size = f"φ{W}×H{round(it.h)}"
        elif it.kind == "art":
            size = f"{round(D)}×{W}×H{round(it.h)}".replace(f"{round(D)}×{W}", f"W{round(D)}×D{W}")
        else:
            size = f"{W}×{D}×H{round(it.h)}"
        prod = ""
        if it.product:
            prod = h.spec["furniture"]["products"][it.product]["name"] + "（指定商品・寸法は仮定）"
        nm = it.name.split("（")[0] if short else it.name
        if short and it.product:
            nm += "（指定・仮置き）"
        rows.append([it.id, f"{it.floor} {it.room}", nm, size, str(it.qty), mat_text(it), prod or "—", BASE_TEXT.get(it.base, it.base)
                     + ("　要施主確認" if it.note else "")])
    return rows


def seating(its):
    """座る家具（要施主確認）の ID 一覧。"""
    return [i.id for i in its if i.seat]


# ------------------------------------------------------------------ 内装（床・天井・ライニング・扉・照明器具ほか）
def interior_meshes(h, its):
    """[(グループ, 階, 材質キー, ID または None, trimesh（m）)]。ID ありは個別ノード（扉・スクリーン生地）。"""
    import interior_shell as IS
    merged, single = IS.interior_parts(h, its)
    out = []
    for (g, lvl, _k), mb in merged.items():
        for key, m in mb.meshes().items():
            out.append((g, lvl, key, None, m))
    for (g, lvl, _k, did), mb in single.items():
        for key, m in mb.meshes().items():
            out.append((g, lvl, key, did, m))
    return out


def door_info(h):
    """扉の開閉情報 {ID: dict}（吊元の位置と回す向き、引戸の移動など）。"""
    import interior_shell as IS
    return IS.door_parts(h)[1]
