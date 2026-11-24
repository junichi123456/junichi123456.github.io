"""固定資産税 概算（河沿要）。単位: 円, m2。仮定はすべて本スクリプト内に明記。"""
import csv, os
REPO = "/home/user/junichi123456.github.io/rc-building"

# ---------- 1. 面積（現行モデル） ----------
W = 18.25  # 壁芯 m（grid 6.125+6.0+6.125）
floor = W * W
total = 2 * floor
rooms = list(csv.DictReader(open(f"{REPO}/dist/export/csv/rooms.csv", encoding="utf-8-sig")))
net = {}
for r in rooms:
    net[r["階"]] = net.get(r["階"], 0) + float(r["面積m2"])
print(f"各階 壁芯 {floor:.2f} m2, 延べ {total:.2f} m2, 室内法合計 {net}")

# ---------- 2. 躯体数量（概算・推定） ----------
per = 4 * W
ext = per * (3.4 * 2 + 0.6) * 0.25 - 30 * 0.25          # 外周壁（開口 約30m2 控除）
thick = 6.25 * 3.4 * (0.10 + 0.05 + 0.05 + 0.05)        # 1F 増し打ち
inner = ((54.5 + 56.0 - per) + (61.1 + 62.7 - per)) * 3.4 * 0.25
slab = floor * 0.22 * 2
base = (W + 0.5) ** 2 * 0.35
fbeam = (per + 4 * W) * 0.4 * 1.8
conc = ext + thick + inner + slab + base + fbeam
print(f"コンクリート 外周{ext:.0f} 増打{thick:.0f} 内壁{inner:.0f} スラブ{slab:.0f} 底版{base:.0f} 基礎梁{fbeam:.0f} 計{conc:.0f} m3 = {conc/total:.2f} m3/m2（R6 戸建RC標準量 0.69）比 {conc/total/0.69:.2f}")
wall_area = (ext + thick + inner) / 0.25
reb = (wall_area * 19.9 + total * 19.9 + 15000) * 1.10 / 1000
print(f"鉄筋 概算 {reb:.0f} t = {reb/total:.3f} t/m2")
print(f"窓ガラス 26.4m2 / 延べ = {26.4/total:.3f} m2/m2")

# ---------- 3. 部分別 補正（推定） ----------
parts = [  # 名称, 標準RC戸建の構成比(推定), 本件倍率 low, high, 根拠
 ("主体構造部（柱・壁体・床版）", .30, 1.15, 1.35),
 ("基礎", .08, 1.20, 1.60),
 ("屋根仕上（防水）", .03, 1.05, 1.25),
 ("外部仕上（外壁）", .08, 1.15, 1.45),
 ("内壁仕上", .06, 1.00, 1.20),
 ("床仕上", .05, 1.05, 1.30),
 ("天井仕上", .03, 0.95, 1.10),
 ("建具", .10, 0.65, 0.95),
 ("建築設備: 電気", .04, 1.10, 1.60),
 ("建築設備: 給排水・衛生", .08, 0.70, 1.00),
 ("建築設備: 空調・換気", .03, 1.60, 2.50),
 ("建築設備: 防災・その他", .02, 1.50, 3.00),
 ("仮設工事", .04, 1.00, 1.10),
 ("その他工事（階段・庇・雑）", .06, 0.90, 1.30),
]
assert abs(sum(p[1] for p in parts) - 1) < 1e-9
lo = sum(p[1] * p[2] for p in parts); hi = sum(p[1] * p[3] for p in parts)
print("\n部分別 寄与（構成比×倍率）")
for n, s, a, b in parts:
    print(f"  {n:22s} {s*100:4.0f}%  x{a:.2f}〜{b:.2f}  -> {s*a*100:5.1f}〜{s*b*100:5.1f}")
print(f"  合計（標準=1.00）: {lo:.3f}〜{hi:.3f}")

# ---------- 4. 家屋評価額 ----------
STD = 166_000      # 東京法務局 新築建物課税標準価格認定基準表 R6 RC居宅 円/m2（列対応は推定）
R9 = (1.00, 1.10)  # R6基準→R9基準 の再建築費水準（仮定）
V_lo = total * STD * lo * R9[0]
V_hi = total * STD * hi * R9[1]
V_mid = total * STD * (lo + hi) / 2 * sum(R9) / 2
print(f"\n家屋評価額（初年度・経年1年込み）: 下限 {V_lo/1e8:.2f} 億 / 中央 {V_mid/1e8:.2f} 億 / 上限 {V_hi/1e8:.2f} 億")
print(f"  m2あたり {V_lo/total:,.0f}〜{V_hi/total:,.0f} 円（中央 {V_mid/total:,.0f}）")
P_mid = V_mid / 0.80
print(f"  逆算 再建築費（評点×1.10円）中央 {P_mid/1e8:.2f} 億, 再建築費評点/m2 {P_mid/1.10/total:,.0f} 点")

# 経年減点補正率（RC住宅: 1年0.80、10年0.6386、以後 -0.008772/年、60年0.20。1〜9年は直線補間＝推定）
def keinen(n):
    if n <= 10:
        return 0.80 + (0.6386 - 0.80) * (n - 1) / 9
    return max(0.20, 0.6386 - (n - 10) * (0.6386 - 0.2) / 50)

# ---------- 5. 土地 ----------
A = 2426.42
def land_tax(u, kind="residential"):
    E = A * u
    if kind == "residential":
        fx = (200 * u / 6 + (A - 200) * u / 3) * 0.014
        tc = (200 * u / 3 + (A - 200) * u * 2 / 3) * 0.0027
    else:
        fx = E * 0.7 * 0.014; tc = E * 0.7 * 0.0027
    return E, fx, tc
print("\n土地（新敷地 2,426.42m2）")
for u in (85_000, 105_000, 130_000):
    E, fx, tc = land_tax(u)
    E2, fx2, tc2 = land_tax(u, "non")
    print(f"  単価{u:,}: 評価額 {E/1e8:.2f}億  住宅用地 固定{fx/1e4:.0f}万+都計{tc/1e4:.0f}万={(fx+tc)/1e4:.0f}万 / 非住宅(×0.7) {(fx2+tc2)/1e4:.0f}万")
for u in (70_000, 105_000):
    s = 203.2 * u * 0.7 * (0.014 + 0.0027)
    print(f"  割譲帯 203.2m2 単価{u:,} 非住宅扱い: {s/1e4:.1f}万/年")
# 二住戸化した場合の差（参考）
u = 105_000
d = 200 * u * (1/3 - 1/6) * 0.014 + 200 * u * (2/3 - 1/3) * 0.0027
print(f"  参考: 小規模住宅用地 +200m2 の差 {d/1e4:.1f}万/年")

# ---------- 6. 償却資産（参考: 太陽光を余剰売電にした場合。v4.39 は全量自家消費で 0）
r = 0.127  # 耐用年数17年の減価率
def dep(C, n):  # n=1: 取得翌年度
    v = C * (1 - r / 2) * (1 - r) ** (n - 1)
    return max(v, C * 0.05)
print("\n太陽光（参考: 余剰売電の場合。取得価額 1,200万〜2,000万と仮定）償却資産税 1年目/5年目/10年目")
for C in (12e6, 20e6):
    print(f"  {C/1e4:.0f}万: " + " / ".join(f"{dep(C,n)*0.014/1e4:.1f}万" for n in (1, 5, 10)))

# ---------- 7. 10年推移 ----------
# 竣工 2027年中 → 初課税 令和10年度(2028)。基準年度 R12(2030), R15(2033), R18(2036)。
# 在来分補正率: R12・R15・R18 で 非木造 1.00〜1.07（仮定）。評価額が前回を上回れば据置。
print("\n年税額の推移（家屋 固定1.4%+都計0.27%、土地 住宅用地 本則、減額なし）")
def series(V1, corr, u, pvC):
    out = []
    P = V1 / 0.80; v = V1; prev = V1
    for i, y in enumerate(range(2028, 2038), start=1):
        if y in (2030, 2033, 2036):
            P *= corr
            cand = P * keinen(i)
            v = min(cand, prev)
        prev = v
        _, fx, tc = land_tax(u)
        pv = dep(pvC, i) * 0.014 if pvC else 0
        out.append((y, i, v, v * 0.0167, fx + tc, pv))
    return out
cases = {"下限": (V_lo, 1.00, 85_000, 0), "中央": (V_mid, 1.035, 105_000, 0), "上限": (V_hi, 1.07, 130_000, 0)}   # v4.39 全量自家消費: 償却資産なし
res = {k: series(*v) for k, v in cases.items()}
print("年度 年目 | " + " | ".join(f"{k}: 家屋評価/家屋税/土地税/PV/計" for k in cases))
for j in range(10):
    row = []
    for k in cases:
        y, i, v, ht, lt, pv = res[k][j]
        row.append(f"{v/1e8:.2f}億 {ht/1e4:.0f} {lt/1e4:.0f} {pv/1e4:.0f} = {(ht+lt+pv)/1e4:.0f}万")
    print(f"{res['中央'][j][0]} {j+1:2d} | " + " | ".join(row))
for k in cases:
    print(k, "10年計", round(sum(h + l + p for _, _, _, h, l, p in res[k]) / 1e4), "万")
print("\n経年減点補正率（推定）:", [round(keinen(n), 4) for n in range(1, 11)])
# 参考: 仮に新築減額が使えた場合（使えない）120m2分 1/2 の額
print(f"参考: 減額が適用されたと仮定した場合の1年あたり軽減 {V_mid*120/total*0.014/2/1e4:.1f}万（実際は面積要件外で0）")
