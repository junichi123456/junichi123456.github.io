"""Blender（bpy）で .blend・FBX・USDZ を書き出す（描画はしない）。システムの python3 ではなく bpy の入った python で実行する:

    .venv-bpy/bin/python src/export_blender.py <ext.json> <int.json> <出力ディレクトリ> [--only blend,fbx,usdz]

ext.json・int.json は src/export/blender.py が render_cg.py／render_interior.py と同じ関数で作る設定（テクスチャなし）。
.blend は cg_blender.build_scene と cg_interior.prepare で作ったシーン（材質・照明器具・太陽・カメラ全カット）を描画せずに保存する。
FBX・USDZ は dist/model*.glb を取り込み直して書く（単位 m、axis_forward -Z、axis_up Y）。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import cg_blender as CB  # noqa: E402
import cg_interior as CI  # noqa: E402


def add_cameras(sc, cuts, interior):
    first = None
    for cut in cuts:
        cd = bpy.data.cameras.new(cut["id"])
        cd.sensor_width = 36.0
        cd.clip_start = 0.05
        cd.clip_end = 2000.0 if interior else 5000.0
        cd.lens = cut["lens"]
        ob = bpy.data.objects.new(cut["id"], cd)
        sc.collection.objects.link(ob)
        ob.location = Vector(cut["cam"])
        if interior:
            d = Vector(cut["target"]) - ob.location
            yaw = math.atan2(d.y, d.x)
            pitch = math.atan2(d.z, math.hypot(d.x, d.y)) if cut.get("pitch") is None else math.radians(cut["pitch"])
            ob.rotation_euler = (math.pi / 2 + pitch, 0, yaw - math.pi / 2)
            cd.shift_y = cut.get("shift_y", 0.0)
            cd.shift_x = cut.get("shift_x", 0.0)
        else:
            ob.rotation_euler = (Vector(cut["target"]) - ob.location).to_track_quat("-Z", "Y").to_euler()
        ob["title"] = cut.get("title", cut["id"])
        ob["when"] = cut.get("when", "")
        first = first or ob
    sc.camera = first
    return first


def build_blend(cfg, interior, path):
    sc, lib, meshes, M = CB.build_scene(cfg)
    state = {}
    cuts = cfg["cuts"]
    if interior:
        st = CI.prepare(CB, sc, lib, meshes, M, cfg)
        CB.add_plants(cfg, lib, M)
        CI.add_scenery(CB, cfg, M)
        CI.configure_cut(CB, sc, lib, st, cfg, cuts[0], M)       # 先頭カットの照明状態（調光・色温度・扉）
    else:
        CB.add_plants(cfg, lib, M)
        glow = CB.add_window_glow(cfg, M) if cfg["window_lights"] else None
        ext = CB.add_ext_lights(cfg)
        for ob in ext:
            ob.hide_render = True
        if glow is not None:
            glow[0].hide_render = True
    day = next((c for c in cuts if c["kind"] == "day"), cuts[0])
    CB.setup_world(sc, day, cfg, state)
    CB.setup_sun(sc, day, state)                               # v4.30 のカットと同じ時刻の太陽
    add_cameras(sc, cuts, interior)
    sc.render.engine = "CYCLES"
    sc.render.resolution_x, sc.render.resolution_y = day["res"]
    sc.cycles.samples = day["samples"]
    sc.view_settings.exposure = day["exposure"]
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    try:
        bpy.ops.file.pack_all()
    except Exception as e:                                     # noqa: BLE001
        print("pack_all:", e)
    bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=True)
    return dict(meshes=len([o for o in bpy.data.objects if o.type == "MESH"]), cameras=len([o for o in bpy.data.objects if o.type == "CAMERA"]),
                materials=len(bpy.data.materials), lights=len([o for o in bpy.data.objects if o.type == "LIGHT"]))


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
    if sys.argv[1] == "master":                       # v4.33: マスター .blend（master_build.py）。旧 .blend 2 本は段階 3 まで並存
        import master_build
        job = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        res = master_build.build_master(job, sys.argv[3])
        Path(sys.argv[4]).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print("export_blender master done", res)
        return
    ext_j, int_j, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else {"blend", "fbx", "usdz"}
    res = {}
    root = Path(__file__).resolve().parent.parent
    if "blend" in only:
        for name, j, inter in (("exterior", ext_j, False), ("interior", int_j, True)):
            cfg = json.loads(j.read_text(encoding="utf-8"))
            res[f"{name}.blend"] = build_blend(cfg, inter, out / f"kawazanyo_{name}.blend")
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
