"""v4.30 内装CG 18区画×2方向（36カット）の定義の試験（Blender 不要）。

    python3 tests/test_interior_zones.py        （pytest があれば pytest tests/ でもよい）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import furniture  # noqa: E402
import render_cg as RC  # noqa: E402
import render_zones as RZ  # noqa: E402
from house import House  # noqa: E402

_C = {}
ALT_ZONES = {"Z1-32", "Z1-13", "Z1-23", "Z2-11", "Z2-21", "Z2-31", "Z2-12", "Z2-32", "Z2-23"}   # 仕様書の表で「代」を付けた区画
BRIEF = ROOT / "docs" / "kawazanyo_design_brief_v3.md"


def ctx():
    if not _C:
        h = House(ROOT)
        Z = RZ.load()
        defs = RZ.cut_defs(h, Z)
        _C.update(h=h, Z=Z, defs=defs, pre=RZ.pre_checks(h, furniture.items(h), defs, Z))
    return _C


def test_36_cuts_18_zones_ab():
    Z = ctx()["Z"]
    ids = list(Z["cuts"])
    assert len(ids) == 36 and len(set(ids)) == 36
    assert all(re.fullmatch(r"Z[12]-[123][123][ab]", i) for i in ids)
    zones = sorted({i[:-1] for i in ids})
    assert len(zones) == 18
    assert all(f"{z}a" in ids and f"{z}b" in ids for z in zones)
    assert all(i[1] == Z["cuts"][i]["floor"][0] and Z["cuts"][i]["zone"] == i[:-1] for i in ids)
    assert sum(1 for i in ids if i.startswith("Z1")) == 18


def test_file_names():
    Z = ctx()["Z"]
    names = [RZ.jpg_name(i, c) for i, c in Z["cuts"].items()]
    assert len(set(names)) == 36 and RZ.jpg_name("Z1-11a", Z["cuts"]["Z1-11a"]) == "Z1-11a_ld_s.jpg"


def test_alternates_have_reasons():
    Z = ctx()["Z"]
    for i, c in Z["cuts"].items():
        if c["zone"] in ALT_ZONES:
            assert c.get("alt") and len(c["alt"]) > 10, i
        if c.get("moved"):
            assert c["moved"].get("reason"), i
            if "back_mm" in c["moved"]:                       # v4.35 の移動（家具の北移動）は from だけを持つ
                assert c["moved"]["back_mm"] % 300 == 0 and c["moved"]["back_mm"] <= 900, i
            else:
                assert c["moved"].get("from"), i


def test_clearance_and_position():
    c = ctx()
    ck = c["Z"]["checks"]
    for i, p in c["pre"].items():
        assert p["clearance"] >= ck["clearance_min_mm"], (i, p)
        assert p["front_mm"] >= ck["front_min_mm"], (i, p)
        assert p["in_room"] and not p["over_void"], (i, p)
        assert not p["errors"], (i, p)


def test_direction_difference():
    c = ctx()
    for z in {i[:-1] for i in c["defs"]}:
        df = RZ.dir_diff(c["defs"][z + "a"]["dir"], c["defs"][z + "b"]["dir"])
        assert min(abs(df - 90), abs(df - 180)) <= 10, (z, df)


def test_height_time_fov():
    c = ctx()
    h, Z = c["h"], c["Z"]
    for i, d in c["defs"].items():
        s = d["spec"]
        assert s["cam"][2] == h.fl[d["floor"]] + 1600 == s["target"][2], i
        assert s["when"] == "2026-03-21T15:30", i
        assert 60 <= RZ.hfov(s["lens"]) <= 75, i
        assert s["pitch"] == 0 and s["wb"] == 5000
        base = Z["settings"]["exposure_theater"] if d["theater"] else Z["settings"]["exposure"]
        if "exposure" in Z["cuts"][i]:
            assert abs(s["exposure"] - base) == 0.5 and Z["cuts"][i].get("exp_note"), i       # 調整は 0.5 刻み・1 回・理由つき
        else:
            assert s["exposure"] == base, i
        assert -1.0 <= s["exposure"] <= 2.5, i
    assert {d["cam"][2] for d in [dict(cam=v["spec"]["cam"]) for v in c["defs"].values()]} == {3100, 6500}
    assert [i for i, d in c["defs"].items() if d["theater"]] == ["Z2-31a", "Z2-31b"]
    assert set(Z["settings"]["resolution"]) == {1280, 720}


def test_sun_and_channels():
    c = ctx()
    h, st = c["h"], c["Z"]["settings"]
    s = h.spec["cg"]["site"]
    el, az = RC.sun_position(st["when"], s["lat"], s["lon"], s["tz"])
    assert abs(el - 27.8) < 0.06 and abs(az - 247.7) < 0.06
    assert abs((az - h.facade_az) - 235.4) < 0.1
    import lighting as LG
    ch = LG.channels(h.spec, 15.5, "")
    assert round(ch["L"][0]) == 4531 and ch["L"][1] == 100 and ch["D"][1] == 0 and ch["F"][1] == 0


def test_exceptions():
    d = ctx()["defs"]
    assert d["Z1-23a"]["spec"]["open_doors"] == {"x7400y14850": 1.0}
    assert d["Z2-22a"]["spec"]["also_1f"] is True
    assert sum(1 for x in d.values() if x["spec"].get("open_doors") or x["spec"].get("also_1f")) == 2


def test_def_hash_changes():
    d = ctx()["defs"]["Z1-11a"]
    h0 = RZ.def_hash(d)
    import copy
    d2 = copy.deepcopy(d)
    d2["spec"]["cam"][0] += 1
    assert RZ.def_hash(d2) != h0 and RZ.def_hash(d) == h0


def test_spec_I01_I14_untouched():
    cuts = ctx()["h"].spec["interior_cg"]["cuts"]
    assert [k for k in cuts if re.fullmatch(r"I\d\d", k)] and len(cuts) == 14
    assert all(not k.startswith("Z") for k in cuts)
    assert cuts["I01"]["when"] == "2026-03-21T14:00" and cuts["I01"]["file"] == "I01_ldk_south"
    assert cuts["I14"]["cam"] == [4800, 4600, 3000] and cuts["I07"]["when"] == "2026-10-24T20:00"


def test_brief_table_matches_yaml():
    """ブリーフ38章（あれば）の区画表の位置・向きが yaml と一致する。"""
    txt = BRIEF.read_text(encoding="utf-8")
    m = re.search(r"^## 38\. .*?(?=^## 39\.|\Z)", txt, re.S | re.M)
    if not m:
        return
    ch = m.group(0)
    for i, c in ctx()["Z"]["cuts"].items():
        assert re.search(rf"\b{i}\b[^\n]*\({c['x']},\s?{c['y']}\)[^\n]*{RZ.DIR_JA[c['dir']]}", ch), i


def test_log_if_present():
    p = RZ.log_path()
    if not p.exists():
        return
    lg = json.loads(p.read_text(encoding="utf-8"))
    done = [c for c in lg["cuts"].values() if c.get("status") in ("ok", "flag")]
    floors = {f for f in ("1F", "2F") if all(RZ.jpg_path(i).exists() for i, c in ctx()["Z"]["cuts"].items() if c["floor"] == f and i in lg["cuts"])}
    for e in done:
        assert RZ.jpg_path(e["id"]).exists(), e["id"]
        assert e["eye_mm"] == 1600 and e["when"] == "2026-03-21T15:30" and abs(e["sun"]["el"] - 27.8) < 0.06
        assert e["status"] == "ok" or e["issues"], e["id"]
    if len(done) == 36:
        assert sum(RZ.jpg_path(e["id"]).stat().st_size for e in done) <= 15 * 1024 * 1024
    assert floors is not None


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
    print("OK", n)
