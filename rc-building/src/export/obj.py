"""OBJ+MTL 書き出し（Blender・Rhino・SketchUp Pro・3ds Max・MeshLab・Windows 3D ビューア）。

model3d.build_scene が作る Scene（GLB と同じ）をそのまま書く。単位 m・Y 上・-Z 真北・原点 = GLB と同じ。
o 名 = ノード名（グループ|階|材質キー|ID）、usemtl = 材質キー、Kd = sRGB 値。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np

import model3d as M

from .manifest import COORD_WORLD

HEADER = ("# 河沿要（仮称） v4.31  {kind}\n"
          "# 単位: m / 座標: Y 上・-Z が真北・+X が東（GLB と同じ。建物中心まわりに alpha 回転済み）\n"
          "# o 名 = グループ|階|材質キー|ID、usemtl = 材質キー、Kd は sRGB\n")


def mtl_text(table, keys):
    out = ["# 河沿要（仮称） v4.31 材質（Kd は sRGB 0-1）\n"]
    for k in sorted(keys):
        t = table[k]
        r, g, b = (int(t["color"][i:i + 2], 16) / 255 for i in (1, 3, 5))
        a = t.get("alpha", 1.0)
        out.append(f"newmtl {k}\nKd {r:.4f} {g:.4f} {b:.4f}\nKa {r * .2:.4f} {g * .2:.4f} {b * .2:.4f}\n"
                   f"Ks {0.04 + 0.5 * t['metallic']:.3f} {0.04 + 0.5 * t['metallic']:.3f} {0.04 + 0.5 * t['metallic']:.3f}\n"
                   f"Ns {max(1.0, (1 - t['roughness']) * 200):.1f}\nd {a:.3f}\nillum {2 if a >= 1 else 4}\n")
        if t.get("emissive"):
            out.append(f"Ke {r:.4f} {g:.4f} {b:.4f}\n")
        out.append("\n")
    return "".join(out)


def scene_obj(scene, table, kind, mtl_name):
    """(obj 本文, 使った材質キー, 頂点数, 面数, オブジェクト数)。"""
    lines = [HEADER.format(kind=kind), f"mtllib {mtl_name}\n"]
    base = 0
    keys, nv, nf, no = set(), 0, 0, 0
    for name in sorted(scene.graph.nodes_geometry):
        T, gname = scene.graph[name]
        m = scene.geometry[gname]
        v = np.asarray(m.vertices)
        if not np.allclose(T, np.eye(4)):
            v = (np.c_[v, np.ones(len(v))] @ T.T)[:, :3]
        mk = m.visual.material.name
        keys.add(mk)
        lines.append(f"o {name}\nusemtl {mk}\n")
        lines.append("".join(f"v {x:.5f} {y:.5f} {z:.5f}\n" for x, y, z in v))
        lines.append("".join(f"f {a + base + 1} {b + base + 1} {c + base + 1}\n" for a, b, c in np.asarray(m.faces)))
        base += len(v)
        nv += len(v)
        nf += len(m.faces)
        no += 1
    return "".join(lines), keys, nv, nf, no


def write_one(h, outdir, mf, interior):
    scene, table = M.build_scene(h, interior=interior)
    kind = "内装（家具・天井・床仕上げ・内壁・扉・照明器具つき）" if interior else "外観"
    stem = "model_interior" if interior else "model_exterior"
    obj, keys, nv, nf, no = scene_obj(scene, table, kind, f"{stem}.mtl")
    z = Path(outdir) / f"{stem}_obj.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(f"{stem}.obj", obj.encode("utf-8"))
        zf.writestr(f"{stem}.mtl", mtl_text(table, keys).encode("utf-8"))
    mf.add(z, "OBJ+MTL", COORD_WORLD, note=f"{no} objects, {nv} vertices, {nf} faces")
    return z


def write(h, outdir, mf):
    write_one(h, outdir, mf, False)
    write_one(h, outdir, mf, True)
