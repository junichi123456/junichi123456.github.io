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
