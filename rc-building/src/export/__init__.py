"""操作可能なデータ形式の書き出し（v4.31）。図面・GLB の出力には影響しない。

    export_all(h, outdir)  — build.py の最後から呼ぶ。形式ごとに try で囲み、失敗しても他の形式と既存出力は壊さない。
"""
from __future__ import annotations

import importlib
import traceback
from pathlib import Path

from .manifest import Manifest

# (モジュール名, 形式名)。上から順に実行する。モジュールが無い段階では静かに飛ばす。
STEPS = [("ifc", "IFC4"), ("obj", "OBJ+MTL"), ("tables", "CSV/XLSX"), ("geo", "GeoJSON+KML"), ("dxf3d", "3D DXF")]


def export_all(h, outdir, only=None, ifc_schema="IFC4", with_blend=False, force_blend=False):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    mf = Manifest(outdir, merge=only is not None)
    for mod, label in STEPS:
        if only is not None and mod not in only:
            continue
        try:
            m = importlib.import_module(f"{__name__}.{mod}")
        except ModuleNotFoundError as e:
            if e.name == f"{__name__}.{mod}":
                continue
            mf.skip(label, f"依存モジュールなし: {e.name}")
            continue
        try:
            kw = dict(ifc_schema=ifc_schema) if mod == "ifc" else {}
            m.write(h, outdir, mf, **kw)
        except Exception as e:                      # noqa: BLE001  形式単位で失敗を隔離する
            mf.skip(label, f"失敗: {type(e).__name__}: {e}")
            traceback.print_exc(limit=3)
    if with_blend:
        try:
            from . import blender
            blender.write(h, outdir, mf, force=force_blend)
        except Exception as e:                      # noqa: BLE001
            mf.skip("blend/FBX/USDZ", f"失敗: {type(e).__name__}: {e}")
    mf.write()
    return mf
