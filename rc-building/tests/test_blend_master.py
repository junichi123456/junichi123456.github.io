"""v4.33 マスター .blend（dist/export/kawazanyo_master.blend）と撮影（src/shoot.py）の試験。bpy が無ければ skip。

    cd rc-building && python3 -m pytest tests/test_blend_master.py -q
(a) 読み戻し／(b) GLB・IFC・CSV との一致／(c) スモーク撮影（I01 を 160×90・4spp）／古いマスターの拒否・スキップ・オーバーレイ
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


# ------------------------------------------------------------------ (c) スモーク撮影・スキップ・古いマスター・オーバーレイ
def shoot(master_path, *args, env=None, timeout=300):
    e = dict(os.environ, BPY_PYTHON=str(BPY), KAWAZANYO_MASTER=str(master_path), **(env or {}))
    return subprocess.run([sys.executable, str(ROOT / "src" / "shoot.py"), *args], capture_output=True, text=True, env=e, timeout=timeout)


@needs_bpy
def test_smoke_shoot_and_skip(master, tmp_path):
    import time
    from PIL import Image
    import numpy as np
    out = tmp_path / "out"
    t = time.time()
    r = shoot(master[0], "--camera", "I01", "--res", "160", "90", "--samples", "4", "--out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert time.time() - t < 60                                                                # 1 分以内
    png = out / "I01_ldk_south.png"
    a = np.asarray(Image.open(png).convert("L"), dtype=float)[:-36] / 255.0                    # 注記の帯（36px）を除く
    assert a.shape == (90, 160) and 0.05 < a.mean() < 0.95
    lg = json.loads((out / "render_log.json").read_text(encoding="utf-8"))
    assert lg["master"]["model_hash"] == BM.model_hash() and lg["master"]["model_version"]
    e = lg["cuts"][0]
    assert e["master"]["file"] == "kawazanyo_master.blend" and e["shoot"]["def_hash"] and e["palette_mismatch"] == []
    # 同じ条件でもう一度 → 飛ばす（render_log の def_hash・model_hash・引数が一致）
    r2 = shoot(master[0], "--camera", "I01", "--res", "160", "90", "--samples", "4", "--out", str(out))
    assert r2.returncode == 0 and "撮るのは 0 カット" in r2.stdout
    # 引数が違えば撮り直す
    r3 = shoot(master[0], "--camera", "I01", "--res", "160", "90", "--samples", "5", "--out", str(out), "--dry-run")
    assert "撮る: I01" in r3.stdout


@needs_bpy
def test_camera_selection(master, tmp_path):
    r = shoot(master[0], "--list")
    assert r.returncode == 0 and len([l for l in r.stdout.splitlines() if l.strip()]) == 57
    out = ["--out", str(tmp_path), "--dry-run"]
    assert "撮る: I04,I05,I06,I07,I08,I09,I10,I11,I12,I13" in shoot(master[0], "--camera", "I04-I13", *out).stdout
    assert shoot(master[0], "--camera", "Z1-11*", *out).stdout.count("Z1-11") >= 2
    n = len(shoot(master[0], "--all", "--kind", "int", "--floor", "2F", *out).stdout.split("撮る:")[1].split("／")[0].split(","))
    assert n > 10
    assert shoot(master[0], "--camera", "NOPE", *out).returncode == 5


@needs_bpy
def test_stale_master_rejected(master, tmp_path):
    stale = tmp_path / "stale.blend"
    code = ("import bpy\nbpy.ops.wm.open_mainfile(filepath=%r)\nbpy.context.scene['model_hash']='0'*64\n"
            "bpy.context.preferences.filepaths.save_version=0\nbpy.ops.wm.save_as_mainfile(filepath=%r, compress=True)\n" % (str(master[0]), str(stale)))
    subprocess.run([str(BPY), "-c", code], check=True, capture_output=True)
    r = shoot(stale, "--camera", "I01", "--preview")
    assert r.returncode == 3 and "古い" in r.stdout
    r = shoot(stale, "--camera", "I01", "--dry-run", "--allow-stale")
    assert r.returncode == 0 and "撮る: I01" in r.stdout


@needs_bpy
def test_overlay_camera_and_object(master, tmp_path):
    ov = tmp_path / "overlay.blend"
    env = dict(os.environ, BPY_PYTHON=str(BPY), KAWAZANYO_OVERLAY=str(ov))
    subprocess.run([sys.executable, str(ROOT / "src" / "shoot.py"), "--init-overlay"], check=True, capture_output=True, env=env)
    code = ("import bpy\nbpy.ops.wm.open_mainfile(filepath=%r)\nc=bpy.data.collections['Overlay']\n"
            "bpy.ops.mesh.primitive_cube_add(size=0.4, location=(5.5, 3.0, 1.2))\nc.objects.link(bpy.context.object)\nbpy.context.scene.collection.objects.unlink(bpy.context.object)\n"
            "cd=bpy.data.cameras.new('X1'); cd.lens=22; o=bpy.data.objects.new('X1', cd); o.location=(8.0, -2.0, 1.6); o.rotation_euler=(1.5708, 0, 0.6); c.objects.link(o)\n"
            "bpy.context.preferences.filepaths.save_version=0\nbpy.ops.wm.save_as_mainfile(filepath=%r, compress=True)\n" % (str(ov), str(ov)))
    subprocess.run([str(BPY), "-c", code], check=True, capture_output=True)
    r = shoot(master[0], "--camera", "X1", "--res", "128", "72", "--samples", "4", "--out", str(tmp_path / "o"), env=dict(KAWAZANYO_OVERLAY=str(ov)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "o" / "X1.png").exists()
    r = shoot(master[0], "--camera", "X1", "--no-overlay", "--dry-run", env=dict(KAWAZANYO_OVERLAY=str(ov)))
    assert r.returncode == 5                                                                    # --no-overlay ではオーバーレイのカメラは無い


@needs_bpy
def test_build_reuses_fresh_master(master, tmp_path):
    """model_hash が同じなら build はマスターを作り直さない（バイト列が変わらない）。--blend-only（force）で作り直す。"""
    import shutil
    from house import House
    from export import blender as EB
    shutil.copy(master[0], tmp_path / "kawazanyo_master.blend")
    (tmp_path / "manifest.json").write_text(json.dumps(dict(files=[dict(file="kawazanyo_master.blend", note=f"model_hash={BM.model_hash()}")])), encoding="utf-8")

    class MF:
        skipped = []

        def skip(self, *a):
            self.skipped.append(a)

        def add(self, *a, **k):
            pass
    before = (tmp_path / "kawazanyo_master.blend").read_bytes()
    assert EB.write_master(House(ROOT), tmp_path, MF()) == dict(reused=True)
    assert (tmp_path / "kawazanyo_master.blend").read_bytes() == before
