"""3D モデル出力（glTF バイナリ .glb）。図面と同じ Box 群から生成する。"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import trimesh

# カテゴリ → (表示グループ, RGBA)
STYLE = {
    "column": ("構造躯体", (0.72, 0.72, 0.70, 1.0)),
    "beam": ("構造躯体", (0.70, 0.70, 0.68, 1.0)),
    "slab": ("床スラブ", (0.80, 0.79, 0.76, 1.0)),
    "wall": ("外壁・RC壁", (0.86, 0.85, 0.82, 1.0)),
    "parapet": ("外壁・RC壁", (0.86, 0.85, 0.82, 1.0)),
    "partition": ("間仕切", (0.93, 0.92, 0.88, 1.0)),
    "glasswall": ("建具", (0.42, 0.62, 0.82, 0.55)),
    "glass": ("建具", (0.42, 0.62, 0.82, 0.55)),
    "door": ("建具", (0.42, 0.47, 0.55, 1.0)),
    "stair": ("階段", (0.66, 0.64, 0.60, 1.0)),
    "fg": ("基礎", (0.55, 0.53, 0.50, 1.0)),
    "footing": ("基礎", (0.50, 0.48, 0.45, 1.0)),
}


def export_glb(b, path):
    parts = defaultdict(list)
    for bx in b.boxes:
        grp, rgba = STYLE.get(bx.cat, ("その他", (0.8, 0.8, 0.8, 1.0)))
        if bx.mat == "glass":
            grp, rgba = STYLE["glass"]
        lvl = bx.level or "-"
        ext = np.array([bx.x1 - bx.x0, bx.y1 - bx.y0, bx.z1 - bx.z0]) / 1000.0
        if (ext <= 0).any():
            continue
        m = trimesh.creation.box(extents=ext)
        c = np.array([(bx.x0 + bx.x1) / 2, (bx.y0 + bx.y1) / 2, (bx.z0 + bx.z1) / 2]) / 1000.0
        m.apply_translation(c)
        parts[(grp, lvl, rgba)].append(m)
    scene = trimesh.Scene()
    # Z-up(mm) → Y-up(m)
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
    for (grp, lvl, rgba), ms in sorted(parts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        mesh = trimesh.util.concatenate(ms)
        mesh.apply_transform(rot)
        mat = trimesh.visual.material.PBRMaterial(
            baseColorFactor=[int(v * 255) for v in rgba], metallicFactor=0.0, roughnessFactor=0.9,
            alphaMode="BLEND" if rgba[3] < 1 else "OPAQUE", doubleSided=rgba[3] < 1)
        mesh.visual = trimesh.visual.TextureVisuals(material=mat)
        scene.add_geometry(mesh, node_name=f"{grp}|{lvl}", geom_name=f"{grp}|{lvl}")
    # 敷地・道路
    x0, y0, x1, y1 = b.site_rect()
    rx0, ry0, rx1, ry1 = b.road_rect()
    for name, (a0, b0, a1, b1, z, col) in {
        "敷地|-": (x0, y0, x1, y1, -20, (0.80, 0.84, 0.74, 1.0)),
        "道路|-": (rx0, ry0, rx1, ry1, -40, (0.45, 0.46, 0.48, 1.0)),
    }.items():
        m = trimesh.creation.box(extents=[(a1 - a0) / 1000, (b1 - b0) / 1000, 0.02])
        m.apply_translation([(a0 + a1) / 2000, (b0 + b1) / 2000, z / 1000])
        m.apply_transform(rot)
        m.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[int(v * 255) for v in col], metallicFactor=0.0, roughnessFactor=1.0))
        scene.add_geometry(m, node_name=name, geom_name=name)
    scene.export(path)
    return scene
