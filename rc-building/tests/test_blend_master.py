"""v4.33 マスター .blend（dist/export/kawazanyo_master.blend）と撮影（src/shoot.py）の試験。bpy が無ければ skip。

    cd rc-building && python3 -m pytest tests/test_blend_master.py -q
(a) 読み戻し／(b) GLB・IFC・CSV との一致（(c) スモーク撮影ほかは段階 3 の shoot.py と一緒に追加）
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import blend_master as BM  # noqa: E402

BPY = Path(os.environ.get("BPY_PYTHON") or "/tmp/claude-0/venv-bpy/bin/python")
if not BPY.exists():
    BPY = ROOT / ".venv-bpy" / "bin" / "python"
needs_bpy = pytest.mark.skipif(not BPY.exists(), reason="bpy の入った python が無い")


def bpy_check(path):
    r = subprocess.run([str(BPY), str(ROOT / "tests" / "bpy_check.py"), "master", str(path)], capture_output=True, text=True, timeout=600)
    return json.loads(next(l for l in r.stdout.splitlines() if l.startswith("JSON:"))[5:])


def rows(name):
    return list(csv.DictReader((ROOT / "dist" / "export" / "csv" / f"{name}.csv").read_text(encoding="utf-8-sig").splitlines()))


@pytest.fixture(scope="session")
def master(tmp_path_factory):
    """現在のコードでマスターを 1 つ作る（一時ディレクトリ）。"""
    from house import House
    from export import blender as EB
    d = tmp_path_factory.mktemp("master")

    class MF:
        skipped, files = [], []

        def skip(self, *a):
            self.skipped.append(a)

        def add(self, *a, **k):
            self.files.append(a)
    mf = MF()
    mp = pytest.MonkeyPatch()
    mp.setenv("BPY_PYTHON", str(BPY))
    try:
        res = EB.write_master(House(ROOT), d, mf)
    finally:
        mp.undo()
    assert res is not None and not mf.skipped, mf.skipped
    return d / "kawazanyo_master.blend", res


@pytest.fixture(scope="session")
def info(master):
    return bpy_check(master[0])


# ------------------------------------------------------------------ (a) 読み戻し
@needs_bpy
def test_master_readback(info, master):
    from export.common import VERSION
    assert info["cameras"] == 57 and len(info["camera_names"]) == 57
    assert {"C01", "C07" if "C07" in info["camera_names"] else "C06", "I01", "I14", "Z1-11a", "Z2-33b"} <= set(info["camera_names"])
    assert info["top_collections"] == ["Exterior", "Interior_1F", "Interior_2F", "Furniture", "Lighting", "Site", "Cameras", "Overlay"]
    assert info["props"]["model_version"] == VERSION and info["props"]["model_hash"] == BM.model_hash()
    assert info["props"]["gen_signature"] and info["props"]["git_commit"] and info["props"]["generated_at"]
    assert info["packed"] == 0 and all(p.startswith("//") for p in info["images"])           # テクスチャはパックしない（相対パス）
    assert info["materials"] > 150 and info["meshes"] > 700 and info["unit"] == "METRIC"
    assert master[1]["cameras"] == 57
    assert (master[0].stat().st_size) < 10e6                                                  # 目標 10MB 以下
    p = info["cam_props"]["Z1-11a"]
    assert p["kind"] == "int" and p["floor"] == "1F" and p["eye_mm"] == 1600 and p["def_hash"] and json.loads(p["channels"])["L"][1] == 100
    assert info["cam_props"]["C01"]["kind"] == "ext" and info["cam_props"]["I07"]["theater"] in (1, True)


@needs_bpy
def test_repo_master_is_fresh():
    """コミットされたマスターが現在のソース・data・spec と一致する（古いまま残さない。build で再生成）。"""
    p = ROOT / "dist" / "export" / "kawazanyo_master.blend"
    assert p.exists()
    i = bpy_check(p)
    assert i["props"]["model_hash"] == BM.model_hash(), "マスターが古い: python3 src/build.py --blend-only"
    assert i["cameras"] == 57 and i["packed"] == 0 and p.stat().st_size < 10e6


# ------------------------------------------------------------------ (b) GLB・IFC・CSV との一致
@needs_bpy
def test_glb_names_match(info):
    want = set(BM.glb_node_names(ROOT / "dist" / "model.glb")) | set(BM.glb_node_names(ROOT / "dist" / "model_interior.glb"))
    got = set(info["glb_names"])
    assert got == want and len(info["glb_names"]) == len(got)


@needs_bpy
def test_tags_match_csv(info):
    t = info["tags"]
    assert len(t["room"]) == len(rows("rooms")) and len(t["opening"]) == len(rows("openings"))
    assert set(t["opening"]) == {r["記号"] for r in rows("openings")}
    fu = {r["ID"] for r in rows("furniture")}
    assert fu <= set(t["furniture"]) and all(x.startswith("GYM") for x in set(t["furniture"]) - fu)      # 家具 68 ＋ ジム機器の形状
    lt = rows("lights")
    by = {k: [r["ID"] for r in lt if r["種別"] == k] for k in ("ライン照明", "ダウンライト", "足元灯（階段）")}      # ID は室の記号が同じ室で重なることがある（個数は行数で比べる）
    assert sorted(t["light"]) == sorted(by["ライン照明"] + by["ダウンライト"] + by["足元灯（階段）"])
    assert info["channels"] == {"L": len(by["ライン照明"]), "D": len(by["ダウンライト"]), "F": len(by["足元灯（階段）"])}


@needs_bpy
def test_counts_match_ifc(info):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    m = ifcopenshell.open(str(ROOT / "dist" / "export" / "kawazanyo_IFC4.ifc"))
    assert len(info["tags"]["room"]) == len(m.by_type("IfcSpace"))
    assert len(info["tags"]["opening"]) == len(m.by_type("IfcDoor")) + len(m.by_type("IfcWindow"))
