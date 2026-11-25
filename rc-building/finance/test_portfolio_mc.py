"""簡易試験（N=5,000）。pytest でも `python3 finance/test_portfolio_mc.py` でも動く。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portfolio_mc as pm  # noqa: E402

N = 5000
Z = pm.make_shocks(N, pm.T_YEARS, seed=pm.SEED)


def dep(**kw):
    p, _ = pm.case_params(kw.pop("case", "中"), **kw)
    return float(np.mean(pm.simulate(p, Z)["depl_year"] <= 50) * 100)


def test_acquisition_totals():
    assert round(pm.acquisition_cost("低")[1]) == 34276
    assert round(pm.acquisition_cost("中")[1]) == 43976
    assert round(pm.acquisition_cost("高")[1]) == 56512


def test_t0_reproduction():
    for mu, target in ((0.05, 11), (0.04, 19), (0.03, 31)):
        p = dict(w0=97000.0, mu=mu, rule="R1", spend_total=1800.0, prop_tax=False, nisa=0.0, spend_gross=True)
        v = np.mean(pm.simulate(p, Z)["depl_year"] <= 50) * 100
        assert abs(v - target) <= 3.5, (mu, v)  # N=5,000 の誤差を見込む


def test_reproducible():
    a = pm.simulate(dict(w0=50000.0, rule="R3"), pm.make_shocks(N, pm.T_YEARS, seed=7))
    b = pm.simulate(dict(w0=50000.0, rule="R3"), pm.make_shocks(N, pm.T_YEARS, seed=7))
    assert np.array_equal(a["final"], b["final"]) and np.array_equal(a["depl_year"], b["depl_year"])


def test_monotonic():
    assert dep(mu=0.03) >= dep(mu=0.04) >= dep(mu=0.05)
    assert dep(case="低") <= dep(case="中") <= dep(case="高")
    assert dep(kokuho=30.0) <= dep(kokuho=130.0) <= dep(kokuho=230.0)
    lo = pm.simulate(dict(w0=60000.0, sigma=0.10), Z)["final"]
    hi = pm.simulate(dict(w0=60000.0, sigma=0.20), Z)["final"]
    # σ が上がっても(算術平均固定で)中央値は上がらない: 0.5pt 相当の許容
    assert np.median(hi) <= np.median(lo) * 1.005


def test_tax():
    # 簿価 0 なら売却額の 20.315% が税
    S = np.array([1000.0]); B = np.array([0.0])
    net, tax = pm.stock_sale(S, B, np.array([400.0]))
    sale = 1000.0 - S[0]
    assert abs(tax[0] - sale * pm.TAU) < 1e-9 and abs(net[0] - 400.0) < 1e-9
    # 含み益 0 なら税 0
    S = np.array([1000.0]); B = np.array([1000.0])
    assert pm.stock_sale(S, B, np.array([300.0]))[1][0] == 0.0
    # μ=σ=インフレ=0（債券・現金も 0）なら税 0
    p = dict(w0=60000.0, mu=0.0, cost=0.0, sigma=0.0, infl_mean=0.0, infl_sd=0.0, bond_mu=0.0, bond_sd=0.0,
             cash_rate=0.0, bond_w=0.2, buffer_years=2, rule="R0")
    assert pm.simulate(p, Z)["tax"].max() == 0.0
    # NISA からの取り崩しは非課税（課税口座が空）
    p = dict(w0=1800.0, nisa=1800.0, mu=0.04, bond_w=0.0, rule="R0", spend_total=100.0)
    r = pm.simulate(p, Z)
    assert r["tax"].max() == 0.0


def test_land_cost():
    assert [pm.land_cost(c)[1] for c in "低中高"] == [36560, 48227, 62665]
    assert [pm.pre_occupancy_cost(c)[1] for c in "低中高"] == [2578, 3376, 4539]
    assert [round(pm.acquisition_cost(c, buy_land=True)[1]) for c in "低中高"] == [34276, 43476, 55012]
    # 旧動作は変わらない
    assert round(pm.acquisition_cost("中", land=True)[1]) == 84734


def test_total_matrix():
    exp = {("低", "低"): 23586, ("低", "中"): 11121, ("低", "高"): -4480,
           ("中", "低"): 14386, ("中", "中"): 1921, ("中", "高"): -13680,
           ("高", "低"): 2850, ("高", "中"): -9615, ("高", "高"): -25216}
    for (b, l), w in exp.items():
        assert pm.total_cost(b, l)["W0"] == w, (b, l)
    pos = [k for k, w in exp.items() if w > 0]
    assert len(pos) == 5
    assert sorted(k for k in pos if pm.total_cost(*k)["判定"] == "実質不成立") == [("中", "中"), ("高", "低")]
    assert all(pm.total_cost(*k)["判定"] == "不成立" for k, w in exp.items() if w <= 0)
    assert all(pm.total_cost(b, l)["W0"] > 0 for b, l in pm.G4_PAIRS)
    # 案の W0
    assert [pm.alt_totals(n)["W0"] for n in pm.ALT_CASES] == [22838, 38702, 65682, 43602]


def test_prop_tax_split():
    pt = pm.property_tax_path("中", 50, land_case="中")
    assert abs(pt[0] - 390) <= 1 and abs(pt[9] - 369) <= 1 and pt[49] == pt[9]
    for c, v in (("低", 128), ("中", 158), ("高", 196)):
        assert abs(pm.land_tax_resid(pm.LAND_RES_AREA, pm.LAND_EVAL_UNIT[c]) - v) <= 1
    for c in "低中高":
        a, b = pm.PROP_TAX[c]
        old = np.array([a + (b - a) * min(k, 9) / 9 for k in range(50)], dtype=float)
        assert np.array_equal(pm.property_tax_path(c, 50), old)
    assert abs(pm.land_tax_resid(800, 10.5) - 47.5) <= 0.5


def test_legacy_bitwise():
    base = dict(w0=50000.0, rule="R3", bond_w=0.2, buffer_years=1, nisa=1800.0)
    a = pm.simulate(base, Z)
    b = pm.simulate(dict(base, land_case=None, land_area=pm.LAND_RES_AREA, prop_tax_flat=None, lumps=None), Z)
    for k in ("depl_year", "final", "min_ratio", "tax"):
        assert np.array_equal(a[k], b[k]), k


def _dep_land(bc, lc, **kw):
    p, _ = pm.case_params_land(bc, lc, **kw)
    return float(np.mean(pm.simulate(p, Z)["depl_year"] <= 50) * 100)


def test_monotonic_land():
    assert _dep_land("低", "低") <= _dep_land("低", "中")
    assert _dep_land("低", "中") <= _dep_land("低", "高")
    assert _dep_land("低", "低") <= _dep_land("中", "低")
    p = dict(w0=60000.0, nisa=1800.0)
    d0 = np.mean(pm.simulate(p, Z)["depl_year"] <= 50)
    d1 = np.mean(pm.simulate(dict(p, lumps={4: 4900.0}), Z)["depl_year"] <= 50)
    assert d1 >= d0


def test_bis2_consistency():
    kb = pm.REC
    P = pm.pre_occupancy_cost("中")[1]
    r = pm.max_total(0.04, N, pm.SEED, kb, "R3", (10.0, 15.0, 20.0), P)
    old = pm.max_cost(0.04, N, pm.SEED, kb, "R3", 10.0)
    assert abs(r[10.0] - (old - P)) <= 6
    assert r[10.0] <= r[15.0] <= r[20.0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
