"""bpy 側の読み戻し検証（tests/test_export.py から bpy の入った python で呼ぶ）。標準出力に JSON を 1 行出す。

    bpy_check.py blend <file.blend>
    bpy_check.py mesh  <file.glb|.fbx|.usdz>   — 取り込んでメッシュ数・頂点数・世界座標の境界箱（m）を返す
"""
import json
import sys

import bpy
from mathutils import Vector


def bounds():
    lo, hi = [1e18] * 3, [-1e18] * 3
    n = v = 0
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        n += 1
        v += len(o.data.vertices)
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            for i in range(3):
                lo[i], hi[i] = min(lo[i], w[i]), max(hi[i], w[i])
    return n, v, lo, hi


kind, path = sys.argv[-2], sys.argv[-1]
if kind == "blend":
    bpy.ops.wm.open_mainfile(filepath=path)
    out = dict(meshes=sum(o.type == "MESH" for o in bpy.data.objects), cameras=sum(o.type == "CAMERA" for o in bpy.data.objects),
               lights=sum(o.type == "LIGHT" for o in bpy.data.objects), materials=len([m for m in bpy.data.materials if m.users]),
               camera_names=sorted(o.name for o in bpy.data.objects if o.type == "CAMERA"), unit=bpy.context.scene.unit_settings.system)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext = path.rsplit(".", 1)[1].lower()
    if ext == "glb":
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == "fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        bpy.ops.wm.usd_import(filepath=path)
    n, v, lo, hi = bounds()
    out = dict(meshes=n, vertices=v, lo=lo, hi=hi)
print("JSON:" + json.dumps(out))
