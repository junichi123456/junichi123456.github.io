"""v4.34 各階の天井視点（T1・T2）と各室の斜めカット（R 37 枚）の定義・マスター・色温度の試験。bpy が無い項目は skip。

    cd rc-building && BPY_PYTHON=/tmp/claude-0/venv-bpy/bin/python python3 -m pytest tests/test_interior_rooms.py -q
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import blend_master as BM  # noqa: E402
import furniture  # noqa: E402
import render_interior as RI  # noqa: E402
import render_rooms as RR  # noqa: E402
from house import House  # noqa: E402

BPY = Path(os.environ.get("BPY_PYTHON") or "/tmp/claude-0/venv-bpy/bin/python")
if not BPY.exists():
    BPY = ROOT / ".venv-bpy" / "bin" / "python"
needs_bpy = pytest.mark.skipif(not BPY.exists() or not BM.MASTER.exists(), reason="bpy の入った python かマスターが無い")
_C = {}
# R1-03 は玄関土間 8.0㎡＋式台 1.7㎡（仕様書の 8.0 は土間のみ）
AREAS = {"R1-01_ld": 33.6, "R1-02_kitchen": 33.8, "R1-03_doma": 9.7, "R1-04_hall": 15.3, "R1-05_gym": 51.6, "R1-06_stair1": 20.4, "R1-07_wc1a": 3.9, "R1-08_mechW": 8.6,
         "R1-09_mechE": 8.8, "R1-10_battery": 5.2, "R1-11_laundry": 16.2, "R1-12_fcl": 11.4, "R1-13_wash": 8.3, "R1-14_bath": 10.2, "R1-15_corr1": 7.8, "R1-16_wc1b": 6.1,
         "R1-17_roomA": 20.1, "R1-18_wic1": 10.6, "R2-01_roomB": 12.5, "R2-02_roomC": 11.9, "R2-03_corr2w": 6.5, "R2-04_roomD": 17.1, "R2-05_wicD": 9.3, "R2-06_corr2s": 6.3,
         "R2-07_theater": 34.5, "R2-08_ante": 10.9, "R2-09_wicM": 22.3, "R2-10_library": 33.8, "R2-11_stair1": 20.4, "R2-12_wc2a": 3.9, "R2-13_roomE": 19.6, "R2-14_stair2": 5.5,
         "R2-15_corr2n": 8.3, "R2-16_dress": 7.0, "R2-17_shower": 9.5, "R2-18_wc2b": 6.0, "R2-19_master": 34.5}


def ctx():
    if not _C:
        h = House(ROOT)
        Y = RR.load()
        _C.update(h=h, Y=Y, defs=RR.cut_defs(h, Y), its=furniture.items(h))
    return _C


def bpy_json(code, *args):
    r = subprocess.run([str(BPY), "-c", code, *args], capture_output=True, text=True, timeout=600)
    line = next((l for l in r.stdout.splitlines() if l.startswith("JSON:")), None)
    assert line, r.stderr[-500:] + r.stdout[-500:]
    return json.loads(line[5:])


# ------------------------------------------------------------------ 定義（Blender 不要）
def test_counts_and_ids():
    c = ctx()
    R = [k for k, d in c["defs"].items() if d["kind"] == "R"]
    T = [k for k, d in c["defs"].items() if d["kind"] == "T"]
    assert len(R) == 37 and sorted(T) == ["T1_plan_1F", "T2_plan_2F"]
    assert sum(1 for k in R if k.startswith("R1-")) == 18 and sum(1 for k in R if k.startswith("R2-")) == 19
    assert all(re.fullmatch(r"R[12]-\d\d_[A-Za-z0-9]+", k) for k in R)
    assert set(R) == set(AREAS)
    assert len(c["Y"]["excluded"]) == 7
    for k, a in AREAS.items():
        assert abs(c["defs"][k]["cut"]["area"] - a) <= 0.15, (k, c["defs"][k]["cut"]["area"], a)


def test_room_cuts_geometry():
    c = ctx()
    h, Y, its = c["h"], c["Y"], c["its"]
    ck = Y["checks"]
    R = {k: d for k, d in c["defs"].items() if d["kind"] == "R"}
    clear = RI.camera_clearance(h, its, [dict(id=k, cam_mm=d["spec"]["cam"]) for k, d in R.items()])
    for k, d in R.items():
        cu, sp = d["cut"], d["spec"]
        assert sp["cam"][2] == h.fl[d["floor"]] + 1600, k                                                          # 身長 160cm の目線
        assert sp["target"][2] == sp["cam"][2] and sp["pitch"] == 0 and sp["shift_y"] == -0.06
        ang = RR.wall_angle(cu["yaw"])
        assert 25 - 0.01 <= ang <= 65 + 0.01, (k, ang)                                                               # 壁に水平にならない
        assert clear[k]["mm"] >= ck["clearance_min_mm"] and cu["clearance_mm"] == clear[k]["mm"], (k, clear[k])
        fr = RR.front_dist(h, its, sp["cam"], cu["yaw"])
        if fr < ck["front_min_mm"]:
            assert cu.get("alt"), (k, fr)
        if cu.get("alt"):                                                                                            # 例外は理由つき・22mm
            assert sp["lens"] == 22 and len(cu["alt"]) > 20, k
        else:
            assert sp["lens"] in (24, 26) and (sp["lens"] == 24) == (cu["area"] < 10 or fr < 2500), (k, sp["lens"], cu["area"], fr)
        assert sp["when"] == "2026-06-21T08:00" and sp["wb"] == 5500 and sp["screens"] == "auto" and sp["sun_k"] == Y["settings"]["sun_k"]
        assert sp["exposure"] == (0.5 if cu.get("theater") and "exposure" not in cu else sp["exposure"])
        assert RR.rooms_of(h, Y["targets"][k])[0][0] <= sp["cam"][0] <= RR.rooms_of(h, Y["targets"][k])[0][2]


def test_top_down_cuts():
    c = ctx()
    h, Y = c["h"], c["Y"]
    pl = Y["settings"]["plan"]
    for k, fl in (("T1_plan_1F", "1F"), ("T2_plan_2F", "2F")):
        sp = c["defs"][k]["spec"]
        assert sp["cam"][2] == h.fl[fl] + 2800 and sp["pitch"] == -90 and sp["ortho_scale"] == 20.0 and sp["cam"][:2] == [9125, 9125]
        assert abs((sp["cam"][2] - sp["clip_start"] * 1000) - (h.fl[fl] + 2400)) < 1e-6                              # 手前 400mm を切ると FL+2,400 の水平断面
        assert sp["target"][0] == sp["cam"][0] and sp["target"][1] > sp["cam"][1]                                    # 北（+Y）が画像の上
        assert sp["section"] == "Section_" + fl and sp["hide_pergola"] is True
        assert max(h.W, h.D) / 1000.0 + 1.2 <= sp["ortho_scale"]                                                     # 外形＋両側 0.6m の余白が枠内
    assert pl["resolution"] == [1600, 1600] and pl["time_limit"] == 300
    caps = RR.section_boxes(h, Y)
    assert {b["floor"] for b in caps} == {"1F", "2F"} and sum(1 for b in caps if b["kind"] == "wall") > 20 and all(b["z"] in (3900, 7300) for b in caps)


def test_light_conditions():
    Y = ctx()["Y"]
    st = Y["settings"]
    el, az, azb = RR.sun_info(Y)
    assert abs(el - 40.4) < 0.3 and abs(az - 88.1) < 0.3 and abs(azb - 75.8) < 0.4                                    # 夏至 8:00
    import lighting as LG
    h = ctx()["h"]
    ch = LG.channels(h.spec, 8.0, "")
    assert round(ch["L"][0]) == 5000 and round(ch["L"][1]) == 100 and ch["D"][1] == 0 and ch["F"][1] == 0           # 8:00 の既存スケジュールと一致
    assert st["channels"]["L"] == [5000, 100] and st["wb"] == 5500


def test_direct_and_screens_prediction():
    c = ctx()
    d = c["defs"]
    assert d["R1-05_gym"]["cut"]["direct"] and d["R1-05_gym"]["cut"]["screens_down"]                                 # ジム高窓（東）は下ろす
    assert d["R1-17_roomA"]["cut"]["direct"] and not d["R1-17_roomA"]["cut"]["screens_down"] and d["R1-17_roomA"]["cut"]["blackout_raised"]
    assert d["R2-19_master"]["cut"]["blackout_raised"] and not d["R2-19_master"]["cut"]["screens_down"]
    assert not d["R1-01_ld"]["cut"]["direct"] and not d["R2-10_library"]["cut"]["direct"]                           # 南・西の窓に直射なし


def test_yaml_plan_is_current(tmp_path):
    """--plan を再実行しても yaml が変わらない（決定的）。"""
    before = RR.YAML.read_text(encoding="utf-8")
    try:
        RR.plan(None)
        assert RR.YAML.read_text(encoding="utf-8") == before
    finally:
        RR.YAML.write_text(before, encoding="utf-8")


def test_existing_cut_defs_untouched():
    h = ctx()["h"]
    import render_zones as RZ
    fam = BM.cut_families(h, RZ.load())
    base = json.loads((ROOT / "tests" / "baseline_cam_hashes.json").read_text(encoding="utf-8"))
    assert len(base) == 57
    for k, v in base.items():
        assert fam[k]["hash"] == v, k


# ------------------------------------------------------------------ マスター（bpy）
@needs_bpy
def test_master_has_96_cameras_and_old_hashes():
    base = json.loads((ROOT / "tests" / "baseline_cam_hashes.json").read_text(encoding="utf-8"))
    code = ("import bpy,json,sys\nbpy.ops.wm.open_mainfile(filepath=sys.argv[1])\n"
            "cams={o.name:dict(h=o.get('def_hash'),fam=o.get('family'),type=o.data.type,z=o.location.z,clip=o.data.clip_start,os=o.data.ortho_scale) for o in bpy.data.objects if o.type=='CAMERA'}\n"
            "cols=[c.name for c in bpy.data.collections]\n"
            "caps=[o.name for o in bpy.data.objects if o.get('kind')=='section_cap']\n"
            "print('JSON:'+json.dumps(dict(cams=cams,cols=cols,caps=caps,mh=bpy.context.scene['model_hash'])))")
    r = bpy_json(code, str(BM.MASTER))
    cams = r["cams"]
    assert len(cams) == 96
    assert sum(1 for c in cams.values() if c["fam"] == "R") == 37 and sum(1 for c in cams.values() if c["fam"] == "T") == 2
    for k, v in base.items():
        assert cams[k]["h"] == v, k                                                                              # 既存 57 の def_hash は不変
    for k in ("T1_plan_1F", "T2_plan_2F"):
        assert cams[k]["type"] == "ORTHO" and abs(cams[k]["os"] - 20.0) < 1e-6 and abs(cams[k]["clip"] - 0.4) < 1e-6
    h = ctx()["h"]
    assert abs(cams["T1_plan_1F"]["z"] - (h.fl["1F"] + 2800) / 1000.0) < 1e-6 and abs(cams["T2_plan_2F"]["z"] - (h.fl["2F"] + 2800) / 1000.0) < 1e-6
    assert {"Section_1F", "Section_2F", "Int_R", "Int_T"} <= set(r["cols"]) and len(r["caps"]) >= 4
    assert r["mh"] == BM.model_hash(), "マスターが古い（python3 src/build.py --blend-only）"


@needs_bpy
def test_screens_auto_only_east_goes_down():
    code = ("import bpy,json,sys\nsys.path.insert(0,sys.argv[1]+'/src')\nbpy.ops.wm.open_mainfile(filepath=sys.argv[2])\nimport cg_interior as CI, render_rooms as RR\n"
            "from house import House\nfrom pathlib import Path\nimport render_cg as RC\nh=House(Path(sys.argv[1]))\nY=RR.load()\nst=Y['settings']\nsp=h.spec['cg']['site']\n"
            "el,az=RC.sun_position(st['when'],sp['lat'],sp['lon'],sp['tz'])\ncut=dict(screens='auto',sun=dict(el=el,az=az))\ncfg=dict(alpha=h.alpha)\n"
            "rows=[]\nfor o in bpy.data.objects:\n    if o.get('grp')=='外付けスクリーン生地':\n        rows.append((CI.fabric_side(o),CI.fabric_blackout(o),CI.screen_down(CI.fabric_side(o),CI.fabric_blackout(o),cut,cfg)))\n"
            "print('JSON:'+json.dumps(dict(rows=rows,up=CI.screen_down('E',False,dict(screens='up'),cfg),down=CI.screen_down('N',True,dict(screens='down'),cfg))))")
    r = bpy_json(code, str(ROOT), str(BM.MASTER))
    rows = r["rows"]
    assert rows and any(s == "E" for s, b, d in rows)
    for side, blackout, down in rows:
        assert down == (side == "E" and not blackout), (side, blackout, down)                                       # 東面（遮光生地を除く）だけ下りる
    assert r["up"] is False and r["down"] is True


@needs_bpy
def test_white_plate_color_temperature():
    """屋外の白い拡散板を 64×64 で撮り、線形 RGB から McCamy 式で出した相関色温度が 5,500±300K。"""
    Y = ctx()["Y"]
    res = RR.white_plate(type("A", (), dict(sun_k_list=""))())
    k = Y["settings"]["sun_k"]
    cct = res[k]["cct_k"]
    assert abs(cct - Y["settings"]["white_plate"]["target_k"]) <= Y["settings"]["white_plate"]["tol_k"], cct
    assert 3500 <= k <= 5800


@needs_bpy
def test_smoke_shoot_R1_01(tmp_path):
    cmd = [sys.executable, str(ROOT / "src" / "shoot.py"), "--camera", "R1-01_ld", "--date", "06-21", "--time", "08:00", "--eye", "1600", "--screens", "auto", "--sun-k", "3900",
           "--channels", "L", "--dim", "100", "--res", "160", "90", "--samples", "4", "--out", str(tmp_path), "--force"]
    env = dict(os.environ, BPY_PYTHON=str(BPY))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, env=env)
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-600:]
    from PIL import Image
    import numpy as np
    im = Image.open(tmp_path / "R1-01_ld.png")
    assert im.size == (160, 90) and float(np.asarray(im.convert("L")).mean()) > 5
