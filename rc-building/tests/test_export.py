"""v4.31 操作可能なデータ形式の書き出しの試験。

    cd rc-building && python3 -m pytest tests/test_export.py -q
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from house import House  # noqa: E402
import model3d  # noqa: E402
from export import common  # noqa: E402


@pytest.fixture(scope="session")
def h():
    return House(ROOT)


@pytest.fixture(scope="session")
def outdir(h, tmp_path_factory):
    """export_all を一度だけ実行する（試験用の一時ディレクトリ）。"""
    from export import export_all
    d = tmp_path_factory.mktemp("export")
    mf = export_all(h, d)
    return d, mf


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ------------------------------------------------------------------ 段階1: 共通基盤・既存出力の不変
def test_existing_outputs_unchanged():
    base = json.loads((ROOT / "tests" / "baseline_outputs.json").read_text())
    for p, hx in base.items():
        assert sha(ROOT / p) == hx, p


@pytest.mark.parametrize("interior,name", [(False, "model.glb"), (True, "model_interior.glb")])
def test_glb_byte_identical(h, tmp_path, interior, name):
    base = json.loads((ROOT / "tests" / "baseline_outputs.json").read_text())
    model3d.export_glb(h, tmp_path / name, interior=interior)
    assert sha(tmp_path / name) == base[f"dist/{name}"]


def test_build_scene_matches_export(h):
    sc, table = model3d.build_scene(h)
    assert len(sc.geometry) > 20 and "glass" in table


def test_common_geometry(h):
    nx, ny = common.truenorth_dir(h)
    assert abs(nx * nx + ny * ny - 1) < 1e-12
    assert abs(common.true_north_deg(h) - (-12.28)) < 0.01 and abs(h.facade_az - 12.279) < 0.01
    assert [n for n, _ in common.storeys(h)] == ["FDN", "1F", "2F", "RF"]
    lon, lat = common.enu_to_lonlat(h, 0, 0)
    assert abs(lat - 35.66773) < 1e-9
    assert abs(lon - 139.34047) < 1e-9


def test_flags(h):
    f = common.Flags(ROOT)
    assert f.get(tag="IW-1")["confirm"] and not f.get(tag="AW-1")["confirm"]
    assert f.get(group="家具")["provisional"]
    assert f.get(room="ジム（拡張部）")["confirm"]


def test_manifest_written(outdir):
    d, mf = outdir
    assert (d / "manifest.json").exists()


# ------------------------------------------------------------------ 段階2: IFC4
def _open_ifc(d):
    import zipfile
    import ifcopenshell
    p = next(iter(d.glob("kawazanyo_IFC4.ifc")), None)
    if p is None:
        z = d / "kawazanyo_IFC4.ifc.zip"
        with zipfile.ZipFile(z) as zf:
            zf.extract("kawazanyo_IFC4.ifc", d)
        p = d / "kawazanyo_IFC4.ifc"
    return ifcopenshell.open(str(p)), p


@pytest.fixture(scope="session")
def ifc(outdir):
    d, _ = outdir
    return _open_ifc(d)


def _vol(shape_settings, e):
    import ifcopenshell.geom
    import ifcopenshell.util.shape as US
    return US.get_volume(ifcopenshell.geom.create_shape(shape_settings, e).geometry)


def test_ifc_counts(h, ifc):
    m, _ = ifc
    ext_walls = sum(1 for b in h.boxes if b.cat == "wall" and b.level == "EXT")
    assert len(m.by_type("IfcBuildingStorey")) == 4
    assert len(m.by_type("IfcWall")) == len(h.walls) + len(h.fence_lines) + ext_walls
    assert len(m.by_type("IfcSpace")) == len(h.rooms)
    n_fit = sum(1 for o in h.openings() if o.operation != "opening")
    assert len(m.by_type("IfcWindow")) + len(m.by_type("IfcDoor")) == n_fit == 54
    assert len(m.by_type("IfcOpeningElement")) == sum(1 for _ in h.openings())
    assert len(m.by_type("IfcFurniture")) == 68
    assert len(m.by_type("IfcLightFixture")) >= 260
    assert {s.Name for s in m.by_type("IfcBuildingStorey")} == {"FDN", "1F", "2F", "RF"}
    assert len(m.by_type("IfcSolarDevice")) == 2 and len(m.by_type("IfcStair")) == 3


def test_ifc_windows_doors_filled_and_hosted(ifc):
    m, _ = ifc
    for e in m.by_type("IfcWindow") + m.by_type("IfcDoor"):
        rel = [r for r in m.by_type("IfcRelFillsElement") if r.RelatedBuildingElement == e]
        assert len(rel) == 1, e.Name
        op = rel[0].RelatingOpeningElement
        host = [r.RelatingBuildingElement for r in m.by_type("IfcRelVoidsElement") if r.RelatedOpeningElement == op]
        assert len(host) == 1 and host[0].is_a("IfcWall")
        assert e.ContainedInStructure and e.ContainedInStructure[0].RelatingStructure.is_a("IfcBuildingStorey")


def test_ifc_fitting_symbols_match_schedule(h, ifc):
    m, _ = ifc
    got = {e.Name for e in m.by_type("IfcWindow") + m.by_type("IfcDoor")}
    assert got == {f["label"] for f in h.fittings}


def test_ifc_geometry_volume_and_area(h, ifc):
    import ifcopenshell.geom
    m, _ = ifc
    s = ifcopenshell.geom.settings()
    s.set("disable-opening-subtractions", True)
    walls = [e for e in m.by_type("IfcWall") + m.by_type("IfcRailing") if not e.Name.startswith("塀")]
    vw = sum(_vol(s, e) for e in walls)
    bw = sum(common.box_volume_m3(b) for b in h.boxes if b.cat in ("wall", "partition", "parapet", "insul"))
    assert abs(vw / bw - 1) < 0.005
    slabs = [e for e in m.by_type("IfcSlab") if e.ObjectType != "透水舗装"]
    vs = sum(_vol(s, e) for e in slabs)
    bs = sum(common.box_volume_m3(b) for b in h.boxes if b.cat in ("slab", "footing") or b.tag == "玄関ポーチ" or b.tag.endswith("踊場"))
    assert abs(vs / bs - 1) < 0.005
    area = 0.0
    for sp in m.by_type("IfcSpace"):
        q = [q for d in sp.IsDefinedBy if d.RelatingPropertyDefinition.is_a("IfcElementQuantity") for q in d.RelatingPropertyDefinition.Quantities]
        area += next(x.AreaValue for x in q if x.Name == "NetFloorArea")
    assert abs(area - sum(r.area for r in h.rooms)) < 0.01


def test_ifc_georeference_and_flags(h, ifc):
    import math
    m, _ = ifc
    mc = m.by_type("IfcMapConversion")[0]
    assert abs(mc.XAxisAbscissa - math.cos(h.alpha)) < 1e-9 and abs(mc.XAxisOrdinate - math.sin(h.alpha)) < 1e-9
    assert abs(mc.OrthogonalHeight - 109.0) < 1e-9
    ctx = m.by_type("IfcGeometricRepresentationContext")[0]
    nx, ny = common.truenorth_dir(h)
    assert abs(ctx.TrueNorth.DirectionRatios[0] - nx) < 1e-9 and abs(ctx.TrueNorth.DirectionRatios[1] - ny) < 1e-9
    site = m.by_type("IfcSite")[0]
    assert site.RefElevation == 109000.0 and site.RefLatitude[0] == 35
    import ifcopenshell.util.element as UE
    iw = next(e for e in m.by_type("IfcWindow") if e.Name == "IW-1")
    ps = UE.get_psets(iw)["Pset_Kawazanyo"]
    assert ps["要確認"] is True and ps["Version"] == "v4.31" and "IW-1" not in ps["材質キー"]
    f = next(e for e in m.by_type("IfcFurniture"))
    assert UE.get_psets(f)["Pset_Kawazanyo"]["仮置き"] is True


def test_ifc_schema_validation(ifc):
    import subprocess
    _, p = ifc
    r = subprocess.run([sys.executable, "-m", "ifcopenshell.validate", "--rules", str(p)], capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert "0 error(s) found" in out, out[-600:]


def test_ifc_all_bodies_triangulate(ifc):
    import ifcopenshell.geom
    m, _ = ifc
    it = ifcopenshell.geom.iterator(ifcopenshell.geom.settings(), m, 2)
    n = 0
    if it.initialize():
        while True:
            n += 1
            if not it.next():
                break
    bodies = [e for e in m.by_type("IfcProduct") if e.Representation and any(r.RepresentationIdentifier == "Body" for r in e.Representation.Representations)]
    assert n == len(bodies)


# ------------------------------------------------------------------ 段階3: OBJ+MTL と bpy 系（.blend・FBX・USDZ）
def _glb(name):
    import trimesh
    return trimesh.load(ROOT / "dist" / name, process=False)


@pytest.mark.parametrize("stem,glb", [("model_exterior", "model.glb"), ("model_interior", "model_interior.glb")])
def test_obj_matches_glb(outdir, stem, glb):
    import re
    import trimesh
    import zipfile
    d, _ = outdir
    ex = d / f"x_{stem}"
    with zipfile.ZipFile(d / f"{stem}_obj.zip") as z:
        z.extractall(ex)
    g = _glb(glb)
    sc = trimesh.load(ex / f"{stem}.obj", process=False)
    obj = (ex / f"{stem}.obj").read_text(encoding="utf-8")
    mtl = (ex / f"{stem}.mtl").read_text(encoding="utf-8")
    assert obj.startswith("# 河沿要") and "-Z が真北" in obj.split("\n")[1]
    names = re.findall(r"^o (.+)$", obj, re.M)
    assert len(names) == len(g.geometry) and set(names) == set(g.geometry)
    assert sum(len(m.vertices) for m in sc.geometry.values()) == sum(len(m.vertices) for m in g.geometry.values())
    assert sum(len(m.faces) for m in sc.geometry.values()) == sum(len(m.faces) for m in g.geometry.values())
    assert abs(sc.bounds - g.bounds).max() < 0.001                        # ±1mm（単位 m）
    used = set(re.findall(r"^usemtl (.+)$", obj, re.M))
    assert used == {m.visual.material.name for m in g.geometry.values()}
    assert used == set(re.findall(r"^newmtl (.+)$", mtl, re.M))
    assert "Kd 0.9608 0.9373 0.8902" in mtl                                 # base #F5EFE3 の sRGB


BPY = Path(__import__("os").environ.get("BPY_PYTHON") or "/tmp/claude-0/venv-bpy/bin/python")
if not BPY.exists():
    BPY = ROOT / ".venv-bpy" / "bin" / "python"
needs_bpy = pytest.mark.skipif(not BPY.exists(), reason="bpy の入った python が無い")


def bpy_check(kind, path):
    import subprocess
    r = subprocess.run([str(BPY), str(ROOT / "tests" / "bpy_check.py"), kind, str(path)], capture_output=True, text=True, timeout=600)
    line = next(l for l in r.stdout.splitlines() if l.startswith("JSON:"))
    return json.loads(line[5:])


@pytest.fixture(scope="session")
def blend_out(h, tmp_path_factory):
    from export import export_all
    d = tmp_path_factory.mktemp("export_bpy")
    with pytest.MonkeyPatch.context() as mp:
        if BPY.exists():
            mp.setenv("BPY_PYTHON", str(BPY))
        mf = export_all(h, d, only=[], with_blend=True)
    return d, mf


@needs_bpy
def test_blend_cameras_and_materials(blend_out):
    d, _ = blend_out
    e = bpy_check("blend", d / "kawazanyo_exterior.blend")
    i = bpy_check("blend", d / "kawazanyo_interior.blend")
    assert e["cameras"] == 7 and i["cameras"] == 36
    assert "C01" in e["camera_names"] and "Z1-11a" in i["camera_names"] and "Z2-33b" in i["camera_names"]
    assert e["meshes"] > 150 and i["meshes"] > 700 and e["materials"] > 40 and i["materials"] > 100
    assert i["lights"] > 100 and e["unit"] == "METRIC"


@needs_bpy
@pytest.mark.parametrize("fname,glb", [("model_exterior.fbx", "model.glb"), ("model_interior.fbx", "model_interior.glb"), ("model_exterior.usdz", "model.glb")])
def test_fbx_usdz_readback(blend_out, fname, glb):
    d, _ = blend_out
    a = bpy_check("mesh", d / fname)
    b = bpy_check("mesh", ROOT / "dist" / glb)
    assert a["meshes"] == b["meshes"] and a["vertices"] == b["vertices"]
    assert max(abs(x - y) for x, y in zip(a["lo"] + a["hi"], b["lo"] + b["hi"])) < 0.001      # ±1mm


def test_bpy_missing_is_skipped(h, tmp_path, monkeypatch):
    from export import export_all, blender
    monkeypatch.setattr(blender, "find_python", lambda: None)
    mf = export_all(h, tmp_path, only=[], with_blend=True)
    assert mf.skipped and "bpy" in mf.skipped[0]["reason"] and not list(tmp_path.glob("*.blend"))
