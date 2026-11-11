"""Blender（bpy）でマスター .blend・FBX・USDZ を書き出す（描画はしない）。システムの python3 ではなく bpy の入った python で実行する（src/export/blender.py が呼ぶ）:

    .venv-bpy/bin/python src/export_blender.py master <job.json> <out.blend> <result.json>
    .venv-bpy/bin/python src/export_blender.py conv <出力ディレクトリ> [--only fbx,usdz]

マスター .blend の生成は master_build.py（v4.33。旧 kawazanyo_exterior.blend・kawazanyo_interior.blend はマスターに置き換えて削除）。
FBX・USDZ は dist/model*.glb を取り込み直して書く（単位 m、axis_forward -Z、axis_up Y）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402


def glb_to(glb, fbx=None, usdz=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    if fbx:
        bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=False, object_types={"MESH"}, apply_unit_scale=True, global_scale=1.0,
                                 apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y", bake_space_transform=False,
                                 path_mode="AUTO", embed_textures=False, mesh_smooth_type="FACE")
    if usdz:
        bpy.ops.wm.usd_export(filepath=str(usdz), export_materials=True, export_uvmaps=True, export_normals=True, generate_preview_surface=True)


def main():
    """    export_blender.py master <job.json> <out.blend> <result.json>   — マスター .blend（master_build.py）
    export_blender.py conv <出力ディレクトリ> [--only fbx,usdz]       — GLB から FBX・USDZ"""
    if sys.argv[1] == "master":
        import master_build
        job = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        res = master_build.build_master(job, sys.argv[3])
        Path(sys.argv[4]).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print("export_blender master done", res)
        return
    out = Path(sys.argv[2])
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else {"fbx", "usdz"}
    res = {}
    root = Path(__file__).resolve().parent.parent
    if "fbx" in only:
        for name, glb in (("exterior", "model.glb"), ("interior", "model_interior.glb")):
            glb_to(root / "dist" / glb, fbx=out / f"model_{name}.fbx")
            res[f"{name}.fbx"] = "ok"
    if "usdz" in only:
        glb_to(root / "dist" / "model.glb", usdz=out / "model_exterior.usdz")
        res["exterior.usdz"] = "ok"
    (out / "_blender_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("export_blender done", res)


if __name__ == "__main__":
    main()
