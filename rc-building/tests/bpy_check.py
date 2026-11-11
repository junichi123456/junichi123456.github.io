"""bpy 側の読み戻し検証（tests/test_export.py から bpy の入った python で呼ぶ）。標準出力に JSON を 1 行出す。

    bpy_check.py blend <file.blend>
    bpy_check.py master <kawazanyo_master.blend>   — v4.33 マスター: コレクション・属性・タグ・光源・パック画像の数
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
if kind == "master":
    import collections
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    obs = [o for o in bpy.data.objects if not o.library]
    tags = collections.defaultdict(list)
    for o in obs:
        if "tag" in o:
            tags[o.get("kind", "")].append(o["tag"])
    out = dict(objects=len(obs), cameras=sum(o.type == "CAMERA" for o in obs), camera_names=sorted(o.name for o in obs if o.type == "CAMERA"),
               materials=len(bpy.data.materials), top_collections=[c.name for c in sc.collection.children],
               props={k: sc[k] for k in sc.keys() if isinstance(sc[k], (str, int, float))}, packed=len([i for i in bpy.data.images if i.packed_file]),
               images=[i.filepath for i in bpy.data.images if i.source == "FILE"], glb_names=sorted(o["glb_name"] for o in obs if "glb_name" in o),
               tags={k: sorted(v) for k, v in tags.items()},
               channels=dict(collections.Counter(o["channel"] for o in obs if o.type == "LIGHT" and "channel" in o)),
               cam_props={o.name: {k: o[k] for k in o.keys() if isinstance(o[k], (str, int, float))} for o in obs if o.type == "CAMERA"},
               unit=sc.unit_settings.system, meshes=sum(o.type == "MESH" for o in obs))
elif kind == "blend":
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
