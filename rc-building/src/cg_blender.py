"""外観CG 段階2: Blender（bpy）で GLB を取り込み、材質・照明を与えて Cycles で描画する。

render_cg.py が書いた scene.json を読む。システムの python3 ではなく bpy の入った python で実行する:
    .venv-bpy/bin/python src/cg_blender.py dist/render/scene.json [--only C03,C04]
座標は scene.json の通り、Blender のワールド（X=東, Y=真北, Z=上, 設計GL基準 m）。
GLB の各メッシュは、頂点を建物座標（m）に戻し、オブジェクトの変換で真北基準に置く。
こうするとテクスチャ座標（Object）が建物の軸に揃い、壁の目地やタイルが水平・垂直になる。
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

import bpy
import mathutils
from mathutils import Matrix, Vector

SOCK = bpy.types.NodeSocket


def log(*a):
    print("[cg]", *a, flush=True)


# ===================================================================== ノード作成の補助
class NT:
    def __init__(self, mat):
        mat.use_nodes = True
        self.mat = mat
        self.nt = mat.node_tree
        for n in list(self.nt.nodes):
            if n.type not in ("OUTPUT_MATERIAL",):
                self.nt.nodes.remove(n)
        self.out = next(n for n in self.nt.nodes if n.type == "OUTPUT_MATERIAL")
        self.bsdf = self.nt.nodes.new("ShaderNodeBsdfPrincipled")
        self.nt.links.new(self.bsdf.outputs["BSDF"], self.out.inputs["Surface"])
        self._tc = None
        self._plane = None

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def set(self, sock, v):
        if isinstance(v, SOCK):
            self.nt.links.new(v, sock)
        else:
            try:
                sock.default_value = v
            except TypeError:
                sock.default_value = tuple(v) if hasattr(v, "__len__") else v

    def tc(self):
        if self._tc is None:
            self._tc = self.node("ShaderNodeTexCoord")
        return self._tc

    def math(self, op, a, b=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        return n.outputs[0]

    def vmath(self, op, a, b=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        return n.outputs[0]

    def mixf(self, a, b, fac):
        n = self.node("ShaderNodeMix", data_type="FLOAT")
        self.set(n.inputs[0], fac)
        self.set(n.inputs[2], a)
        self.set(n.inputs[3], b)
        return n.outputs[0]

    def mixc(self, a, b, fac, blend="MIX"):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        self.set(n.inputs[0], fac)
        self.set(n.inputs[6], a)
        self.set(n.inputs[7], b)
        return n.outputs[2]

    def sep(self, vec):
        n = self.node("ShaderNodeSeparateXYZ")
        self.nt.links.new(vec, n.inputs[0])
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def comb(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        self.set(n.inputs[0], x)
        self.set(n.inputs[1], y)
        self.set(n.inputs[2], z)
        return n.outputs[0]

    def maprange(self, v, a0, a1, b0, b1, clamp=True):
        n = self.node("ShaderNodeMapRange", clamp=clamp)
        self.set(n.inputs["Value"], v)
        n.inputs["From Min"].default_value = a0
        n.inputs["From Max"].default_value = a1
        n.inputs["To Min"].default_value = b0
        n.inputs["To Max"].default_value = b1
        return n.outputs["Result"]

    def scalev(self, vec, sx, sy=None, sz=None):
        n = self.node("ShaderNodeMapping", vector_type="POINT")
        self.nt.links.new(vec, n.inputs["Vector"])
        n.inputs["Scale"].default_value = (sx, sy if sy is not None else sx, sz if sz is not None else sx)
        return n.outputs["Vector"]

    def plane(self):
        """壁なら (面内の水平座標, 高さ, 0)、水平面なら (x, y, 0)。Object 座標＝建物の軸に揃った m。"""
        if self._plane is not None:
            return self._plane
        co = self.tc().outputs["Object"]
        nm = self.tc().outputs["Normal"]
        x, y, z = self.sep(co)
        nx, ny, nz = self.sep(nm)
        ax, ay, az = (self.math("ABSOLUTE", v) for v in (nx, ny, nz))
        is_top = self.math("GREATER_THAN", az, 0.7)
        x_wall = self.math("GREATER_THAN", ax, ay)          # 法線が X 向き → 壁面は YZ 面 → 水平座標は y
        u = self.mixf(x, y, x_wall)
        a = self.mixf(u, x, is_top)
        b = self.mixf(z, y, is_top)
        self._plane = self.comb(a, b, 0.0)
        return self._plane

    def bump(self, height, strength, distance, invert=False, normal=None):
        n = self.node("ShaderNodeBump", invert=invert)
        n.inputs["Strength"].default_value = strength
        n.inputs["Distance"].default_value = distance
        self.set(n.inputs["Height"], height)
        if normal is not None:
            self.nt.links.new(normal, n.inputs["Normal"])
        return n.outputs["Normal"]

    def brick(self, vec, w, hgt, mortar, c1, c2, cm, offset=0.5, smooth=0.0):
        n = self.node("ShaderNodeTexBrick", offset=offset, offset_frequency=2, squash=1.0, squash_frequency=2)
        self.nt.links.new(vec, n.inputs["Vector"])
        n.inputs["Scale"].default_value = 1.0
        n.inputs["Mortar Size"].default_value = mortar
        n.inputs["Mortar Smooth"].default_value = smooth
        n.inputs["Bias"].default_value = 0.0
        n.inputs["Brick Width"].default_value = w
        n.inputs["Row Height"].default_value = hgt
        n.inputs["Color1"].default_value = c1
        n.inputs["Color2"].default_value = c2
        n.inputs["Mortar"].default_value = cm
        return n.outputs["Color"], n.outputs["Fac"]


def lin4(rgb, k=1.0):
    return (rgb[0] * k, rgb[1] * k, rgb[2] * k, 1.0)


# ===================================================================== 材質
class Lib:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mats = {}
        self.tex = cfg["textures"]           # 名前 → {"diff": path or None}
        self.imgcache = {}
        self.fallbacks = []
        self.lamp_nodes = []
        self.top_z = 2.7

    def image(self, name):
        t = self.tex.get(name)
        if not t or not t.get("diff"):
            if name not in self.fallbacks:
                self.fallbacks.append(name)
            return None
        if name not in self.imgcache:
            img = bpy.data.images.load(t["diff"])
            img.colorspace_settings.name = "sRGB"
            import numpy as np
            px = np.empty(len(img.pixels), dtype="float32")
            img.pixels.foreach_get(px)
            px = px.reshape(-1, 4)
            lum = 0.2126 * px[:, 0] + 0.7152 * px[:, 1] + 0.0722 * px[:, 2]
            self.imgcache[name] = (img, float(lum.mean()))
        return self.imgcache[name]

    def variation(self, b: NT, texname, tile_m, var, bump_strength=0.0, bump_dist=0.002, noise_scale=300.0):
        """明暗の変化（平均 1.0、±var）と、バンプ用の高さを返す。"""
        co = b.tc().outputs["Object"]
        im = self.image(texname)
        if im is not None:
            img, mean = im
            mp = b.scalev(co, 1.0 / tile_m)
            n = b.node("ShaderNodeTexImage", projection="BOX", projection_blend=0.2, interpolation="Linear", image=img)
            b.nt.links.new(mp, n.inputs["Vector"])
            lum = b.node("ShaderNodeRGBToBW")
            b.nt.links.new(n.outputs["Color"], lum.inputs["Color"])
            rel = b.math("DIVIDE", lum.outputs["Val"], max(mean, 1e-3))
            v = b.maprange(rel, 1 - 2.2 * var / 0.4 * 0.4, 1 + 2.2 * var / 0.4 * 0.4, 1 - var, 1 + var)
            h = lum.outputs["Val"]
        else:
            nz = b.node("ShaderNodeTexNoise", noise_dimensions="3D")
            b.nt.links.new(co, nz.inputs["Vector"])
            nz.inputs["Scale"].default_value = noise_scale / max(tile_m, 0.3) * 0.5
            nz.inputs["Detail"].default_value = 6.0
            nz.inputs["Roughness"].default_value = 0.6
            v = b.maprange(nz.outputs["Fac"], 0.3, 0.7, 1 - var, 1 + var)
            h = nz.outputs["Fac"]
        nrm = b.bump(h, bump_strength, bump_dist) if bump_strength > 0 else None
        return v, h, nrm

    def tinted(self, b: NT, rgb, v):
        s = b.comb(v, v, v)
        return b.vmath("MULTIPLY", lin4(rgb)[:3], s)

    # ------------------------------------------------------------------ 個別の材質
    def make(self, key, md):
        mat = bpy.data.materials.new(key)
        b = NT(mat)
        P = b.bsdf
        rgb = md["rgb"]
        P.inputs["Roughness"].default_value = md.get("roughness", 0.8)
        P.inputs["Metallic"].default_value = md.get("metallic", 0.0)
        if md.get("coat"):
            P.inputs["Coat Weight"].default_value = md["coat"]
            P.inputs["Coat Roughness"].default_value = 0.1
        self.audit(key, rgb)
        fn = getattr(self, "m_" + key, None)
        if fn is None:
            for pre in ("fence_",):
                if key.startswith(pre):
                    fn = self.m_paint
        if fn is None:
            P.inputs["Base Color"].default_value = lin4(rgb)
        else:
            fn(b, md, rgb)
        self.mats[key] = mat
        return mat

    audit_log = {}

    def audit(self, key, rgb):
        Lib.audit_log[key] = [round(v, 4) for v in rgb]

    # 外壁塗装（砂骨の塗り肌）
    def m_paint(self, b, md, rgb):
        v, h, nrm = self.variation(b, "stucco", md.get("tile_m", 2.0), 0.04, 0.15, 0.002, 400.0)
        b.set(b.bsdf.inputs["Base Color"], self.tinted(b, rgb, v))
        b.bsdf.inputs["Specular IOR Level"].default_value = 0.4
        if nrm is not None:
            b.set(b.bsdf.inputs["Normal"], nrm)

    m_base = m_assort = m_accent = m_paint

    def m_tile(self, b, md, rgb):
        c1, c2 = lin4(rgb, 0.94), lin4(rgb, 1.06)
        col, fac = b.brick(b.plane(), 0.235, 0.068, 0.008, c1, c2, lin4(self.cfg["colors_lin"]["tile_joint"]))
        v, _, _ = self.variation(b, "stucco", 2.0, 0.03, 0, 0)
        b.set(b.bsdf.inputs["Base Color"], b.vmath("MULTIPLY", col, b.comb(v, v, v)))
        b.set(b.bsdf.inputs["Roughness"], b.mixf(0.35, 0.9, fac))
        b.set(b.bsdf.inputs["Normal"], b.bump(fac, 0.3, 0.001, invert=True))

    def m_concrete(self, b, md, rgb, broom=False):
        v, h, nrm = self.variation(b, "concrete", md.get("tile_m", 2.0), 0.08, 0.25, 0.002, 200.0)
        pv = b.plane()
        # 型枠の目地 0.9×1.8m
        _, fj = b.brick(pv, 0.9, 1.8, 0.003, (1, 1, 1, 1), (1, 1, 1, 1), (0, 0, 0, 1), offset=0.0)
        n1 = b.bump(fj, 0.6, 0.001, invert=True, normal=nrm)
        # セパ穴: 450×600 ピッチ
        vc = b.node("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
        sv = b.scalev(pv, 1 / 0.45, 1 / 0.6, 1.0)
        b.nt.links.new(sv, vc.inputs["Vector"])
        vc.inputs["Scale"].default_value = 1.0
        vc.inputs["Randomness"].default_value = 0.0
        hole = b.maprange(vc.outputs["Distance"], 0.045, 0.03, 0.0, 1.0)
        n2 = b.bump(hole, 0.8, 0.005, invert=True, normal=n1)
        # 雨だれ
        _, _, z = b.sep(b.tc().outputs["Object"])
        nz = b.node("ShaderNodeTexNoise", noise_dimensions="3D")
        b.nt.links.new(b.vmath("MULTIPLY", b.tc().outputs["Object"], (8.0, 8.0, 0.4)), nz.inputs["Vector"])
        nz.inputs["Scale"].default_value = 1.0
        nz.inputs["Detail"].default_value = 4.0
        top = b.maprange(z, self.top_z - 1.8, self.top_z, 0.4, 1.0)
        streak = b.math("MULTIPLY", b.maprange(nz.outputs["Fac"], 0.35, 0.65, 0.0, 1.0), top)
        dark = b.maprange(streak, 0.0, 1.0, 1.0, 0.94)
        hole_dark = b.maprange(hole, 0.0, 1.0, 1.0, 0.85)
        k = b.math("MULTIPLY", b.math("MULTIPLY", v, dark), hole_dark)
        b.set(b.bsdf.inputs["Base Color"], self.tinted(b, rgb, k))
        b.set(b.bsdf.inputs["Normal"], n2)

    def m_concrete_broom(self, b, md, rgb):
        self.m_concrete(b, md, rgb)

    def m_porous_concrete(self, b, md, rgb):
        v, h, nrm = self.variation(b, "porous", 1.0, 0.07, 0.4, 0.002, 250.0)
        vc = b.node("ShaderNodeTexVoronoi", voronoi_dimensions="3D")
        b.nt.links.new(b.scalev(b.tc().outputs["Object"], 250.0), vc.inputs["Vector"])
        vc.inputs["Scale"].default_value = 1.0
        grain = vc.outputs["Distance"]
        g = b.maprange(grain, 0.0, 0.8, 0.88, 1.08)
        _, jf = b.brick(b.plane(), 3.0, 3.0, 0.005, (1, 1, 1, 1), (1, 1, 1, 1), (0, 0, 0, 1), offset=0.0)
        n2 = b.bump(jf, 0.8, 0.002, invert=True, normal=nrm)
        n3 = b.bump(grain, 0.3, 0.001, normal=n2)
        b.set(b.bsdf.inputs["Base Color"], self.tinted(b, rgb, b.math("MULTIPLY", v, g)))
        b.set(b.bsdf.inputs["Normal"], n3)

    def m_dotcon(self, b, md, rgb):
        c1, c2 = lin4(rgb, 0.96), lin4(rgb, 1.04)
        col, fac = b.brick(b.plane(), 0.61, 0.61, 0.010, c1, c2, lin4(self.cfg["colors_lin"].get("dotcon_joint", (0.27, 0.235, 0.165))), offset=0.0)
        vc = b.node("ShaderNodeTexVoronoi", voronoi_dimensions="3D")
        b.nt.links.new(b.scalev(b.tc().outputs["Object"], 400.0), vc.inputs["Vector"])
        vc.inputs["Scale"].default_value = 1.0
        g = b.maprange(vc.outputs["Distance"], 0.0, 0.8, 0.90, 1.06)
        v, _, _ = self.variation(b, "dotcon", 0.6, 0.04, 0, 0, 200.0)
        n1 = b.bump(fac, 1.0, 0.015, invert=True)
        n2 = b.bump(vc.outputs["Distance"], 0.5, 0.002, normal=n1)
        base = b.vmath("MULTIPLY", col, b.comb(b.math("MULTIPLY", v, g), b.math("MULTIPLY", v, g), b.math("MULTIPLY", v, g)))
        b.set(b.bsdf.inputs["Base Color"], base)
        b.set(b.bsdf.inputs["Roughness"], b.mixf(0.92, 0.95, fac))
        b.set(b.bsdf.inputs["Normal"], n2)

    def m_gravel(self, b, md, rgb):
        v, h, nrm = self.variation(b, "gravel", 1.0, 0.18, 0.8, 0.01, 400.0)
        b.set(b.bsdf.inputs["Base Color"], self.tinted(b, rgb, v))
        b.set(b.bsdf.inputs["Normal"], nrm)

    def m_asphalt(self, b, md, rgb):
        v, h, nrm = self.variation(b, "asphalt", 3.0, 0.14, 0.5, 0.004, 300.0)
        b.set(b.bsdf.inputs["Base Color"], self.tinted(b, rgb, v))
        b.set(b.bsdf.inputs["Normal"], nrm)

    def m_ground_wild(self, b, md, rgb):
        v, h, nrm = self.variation(b, "grass", 4.0, 0.22, 0.4, 0.01, 60.0)
        b.set(b.bsdf.inputs["Base Color"], self.tinted(b, rgb, v))
        b.set(b.bsdf.inputs["Normal"], nrm)

    def m_soil(self, b, md, rgb):
        v, h, nrm = self.variation(b, "soil", 1.0, 0.2, 0.6, 0.01, 300.0)
        b.set(b.bsdf.inputs["Base Color"], self.tinted(b, rgb, v))
        b.set(b.bsdf.inputs["Normal"], nrm)

    def m_glass(self, b, md, rgb):
        P = b.bsdf
        P.inputs["Base Color"].default_value = lin4(rgb)
        P.inputs["Transmission Weight"].default_value = 1.0
        P.inputs["IOR"].default_value = 1.52
        P.inputs["Roughness"].default_value = 0.02
        for k, val in (("Thin Film Thickness", 90.0), ("Thin Film IOR", 1.9)):
            if k in P.inputs:
                P.inputs[k].default_value = val

    def m_roof_sheet(self, b, md, rgb):
        _, fac = b.brick(b.plane(), 8.0, 1.0, 0.004, (1, 1, 1, 1), (1, 1, 1, 1), (0, 0, 0, 1), offset=0.0)
        b.set(b.bsdf.inputs["Base Color"], lin4(rgb))
        b.set(b.bsdf.inputs["Normal"], b.bump(fac, 0.5, 0.001))

    def m_gate_panel(self, b, md, rgb):
        _, fac = b.brick(b.plane(), 20.0, 0.1, 0.003, (1, 1, 1, 1), (1, 1, 1, 1), (0, 0, 0, 1), offset=0.0)
        b.set(b.bsdf.inputs["Base Color"], b.vmath("MULTIPLY", lin4(rgb)[:3], b.comb(b.maprange(fac, 0, 1, 1.0, 0.55), b.maprange(fac, 0, 1, 1.0, 0.55), b.maprange(fac, 0, 1, 1.0, 0.55))))
        b.set(b.bsdf.inputs["Normal"], b.bump(fac, 0.6, 0.002, invert=True))

    def m_pv(self, b, md, rgb):
        P = b.bsdf
        col, fac = b.brick(b.plane(), 0.182, 0.182, 0.002, lin4(rgb), lin4(rgb, 1.15), lin4(self.cfg["colors_lin"]["pv_joint"]), offset=0.0)
        b.set(P.inputs["Base Color"], col)
        P.inputs["Coat Weight"].default_value = 1.0
        P.inputs["Coat Roughness"].default_value = 0.02
        P.inputs["Roughness"].default_value = 0.08

    def m_neighbor(self, b, md, rgb):
        oi = b.node("ShaderNodeObjectInfo")
        k = b.maprange(oi.outputs["Random"], 0.0, 1.0, 0.94, 1.0)
        b.set(b.bsdf.inputs["Base Color"], self.tinted(b, rgb, k))

    def m_water(self, b, md, rgb):
        P = b.bsdf
        P.inputs["Base Color"].default_value = lin4(rgb)
        P.inputs["Roughness"].default_value = 0.05
        P.inputs["Transmission Weight"].default_value = 0.3
        P.inputs["IOR"].default_value = 1.33
        nz = b.node("ShaderNodeTexNoise", noise_dimensions="3D")
        b.nt.links.new(b.tc().outputs["Object"], nz.inputs["Vector"])
        nz.inputs["Scale"].default_value = 3.0
        b.set(P.inputs["Normal"], b.bump(nz.outputs["Fac"], 0.05, 0.1))

    def m_stainless(self, b, md, rgb):
        b.bsdf.inputs["Base Color"].default_value = lin4(rgb)
        b.bsdf.inputs["Anisotropic"].default_value = 0.5

    def m_lamp_2200k(self, b, md, rgb):
        P = b.bsdf
        P.inputs["Base Color"].default_value = lin4(rgb, 0.2)
        bb = b.node("ShaderNodeBlackbody")
        bb.inputs["Temperature"].default_value = 2200.0
        val = b.node("ShaderNodeValue")
        val.outputs[0].default_value = 0.0
        val.label = "LampStrength"
        val.name = "LampStrength"
        P.inputs["Emission Color"].default_value = (1, 1, 1, 1)
        b.nt.links.new(bb.outputs["Color"], P.inputs["Emission Color"])
        b.nt.links.new(val.outputs[0], P.inputs["Emission Strength"])
        self.lamp_nodes.append(val)


# ===================================================================== シーンの構築
def build_scene(cfg):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    bpy.ops.import_scene.gltf(filepath=cfg["glb"])
    alpha = cfg["alpha"]
    pv = cfg["pivot"]
    T = Matrix.Translation((pv[0], pv[1], 0))
    M = T @ Matrix.Rotation(alpha, 4, "Z") @ T.inverted()
    Minv = M.inverted()
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for o in meshes:
        w = o.matrix_world.copy()
        o.data.transform(w)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
        o.data.transform(Minv)
        o.matrix_world = M
    for o in [o for o in bpy.data.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o)
    lib = Lib(cfg)
    mats = cfg["materials"]
    for o in meshes:
        key = re.sub(r"\.\d+$", "", o.name).split("|")[2]
        if key.startswith("neighbor"):
            key = "neighbor"
        elif key.startswith("water"):
            key = "water"
        elif key.startswith("rev"):
            key = "concrete"
        if key not in lib.mats:
            if key not in mats and key in cfg.get("interior", {}).get("palette", {}):
                import cg_interior                    # 内装CG: 内装パレットの材質
                cg_interior.make_material(sys.modules[__name__], lib, key, cfg)
            else:
                lib.make(key, mats[key])
        o.data.materials.clear()
        o.data.materials.append(lib.mats[key])
        o.data.polygons.foreach_set("use_smooth", [False] * len(o.data.polygons))
        if re.sub(r"\.\d+$", "", o.name).split("|")[0] == "道路" and False:
            pass
    return sc, lib, meshes, M


def add_plants(cfg, lib, M):
    """プランターの植物: 土の上に低い起伏のメッシュ（固定シード）。"""
    import bmesh
    mn = mathutils.noise
    mat = bpy.data.materials.new("plant")
    b = NT(mat)
    nz = b.node("ShaderNodeTexNoise", noise_dimensions="3D")
    b.nt.links.new(b.tc().outputs["Object"], nz.inputs["Vector"])
    nz.inputs["Scale"].default_value = 9.0
    c1, c2 = cfg["colors_lin"]["plant_a"], cfg["colors_lin"]["plant_b"]
    col = b.mixc(lin4(c1), lin4(c2), nz.outputs["Fac"])
    b.set(b.bsdf.inputs["Base Color"], col)
    b.bsdf.inputs["Roughness"].default_value = 0.7
    b.bsdf.inputs["Subsurface Weight"].default_value = 0.1
    b.set(b.bsdf.inputs["Normal"], b.bump(nz.outputs["Fac"], 0.4, 0.02))
    n = 0
    for pl in cfg["planters"]:
        x0, y0, x1, y1 = pl["rect"]
        x0, y0, x1, y1 = x0 + 0.04, y0 + 0.04, x1 - 0.04, y1 - 0.04
        z0 = pl["soil_z"]
        hmax = pl["height"]
        step = 0.045
        nx, ny = max(2, int((x1 - x0) / step)), max(2, int((y1 - y0) / step))
        bm = bmesh.new()
        verts = []
        seed = 7 + n
        for j in range(ny + 1):
            row = []
            for i in range(nx + 1):
                x, y = x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny
                big = mn.fractal(Vector((x * 1.6 + seed, y * 1.6, 0.3)), 0.6, 2.0, 4)
                small = mn.noise(Vector((x * 14 + seed, y * 14, 1.7)))
                row_wave = 0.5 + 0.5 * math.sin((y - y0) / (y1 - y0) * math.pi)       # 縁に向かって低く
                hh = 0.04 + hmax * max(0.0, 0.55 + 0.7 * big) * (0.75 + 0.25 * small) * (0.35 + 0.65 * row_wave)
                row.append(bm.verts.new((x, y, z0 + hh)))
            verts.append(row)
        for j in range(ny):
            for i in range(nx):
                bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
        me = bpy.data.meshes.new("plant")
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new("plant", me)
        bpy.context.scene.collection.objects.link(ob)
        ob.data.materials.append(mat)
        ob.matrix_world = M
        for p in me.polygons:
            p.use_smooth = True
        n += 1


def add_window_glow(cfg, M):
    """夕景: 窓の 0.8m 内側に発光面（室内の灯り）。"""
    mat = bpy.data.materials.new("room_light")
    b = NT(mat)
    P = b.bsdf
    P.inputs["Base Color"].default_value = (0, 0, 0, 1)
    bb = b.node("ShaderNodeBlackbody")
    bb.inputs["Temperature"].default_value = cfg["room_light"]["kelvin"]
    b.nt.links.new(bb.outputs["Color"], P.inputs["Emission Color"])
    P.inputs["Emission Strength"].default_value = 0.0
    glow = []
    import bmesh
    bm = bmesh.new()
    for w in cfg["window_lights"]:
        c = Vector(w["center"])
        u = Vector(w["u"]) * 0.5
        v = Vector(w["v"]) * 0.5
        vs = [bm.verts.new(c + a * u + bb_ * v) for a, bb_ in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        bm.faces.new(vs)
    me = bpy.data.meshes.new("room_light")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("room_light", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(mat)
    ob.visible_shadow = False
    return ob, P


def add_ext_lights(cfg):
    out = []
    for L in cfg["ext_lights"]:
        d = bpy.data.lights.new("ext", "SPOT")
        d.color = cfg["lamp_color"]
        d.energy = L["watts"]
        d.spot_size = math.radians(L["cone"])
        d.spot_blend = 0.5
        d.shadow_soft_size = 0.05
        ob = bpy.data.objects.new("ext", d)
        ob.location = L["pos"]
        ob.rotation_euler = (0, 0, 0)          # 真下（-Z）を向く
        bpy.context.scene.collection.objects.link(ob)
        out.append(ob)
    return out


# ===================================================================== World・カメラ・描画
def hdri_sun_azimuth(path):
    """HDRI の最も明るい点の方位（ワールド XY 平面の角度 atan2(y,x)）。Blender の正距円筒の対応に従う。"""
    import numpy as np
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.empty(len(img.pixels), dtype="float32")
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    lum = px[:, :, 0] + px[:, :, 1] + px[:, :, 2]
    j, i = np.unravel_index(int(np.argmax(lum)), lum.shape)
    u, v = (i + 0.5) / w, (j + 0.5) / h
    phi = (u - 0.5) * 2 * math.pi
    theta = (v - 0.5) * math.pi
    dx, dy, dz = -math.cos(phi) * math.cos(theta), math.sin(phi) * math.cos(theta), math.sin(theta)
    bpy.data.images.remove(img)
    return math.atan2(dy, dx), math.degrees(theta)


def setup_world(sc, cut, cfg, state):
    w = bpy.data.worlds.new("w_" + cut["id"])
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    nt.links.new(bg.outputs[0], out.inputs[0])
    path = cfg["hdri"].get(cut["kind"])
    sun = cut.get("sun")
    bg.inputs["Strength"].default_value = cut.get("sky_strength", 1.0)
    if path:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(path)
        tcn = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        nt.links.new(tcn.outputs["Generated"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
        rot = 0.0
        if sun:
            ah, eh = hdri_sun_azimuth(path)
            ss = math.atan2(math.cos(math.radians(sun["az"])), math.sin(math.radians(sun["az"])))   # 北基準→数学角
            rot = ah - ss
            state["hdri_sun"] = (round(math.degrees(ah), 1), round(eh, 1), round(math.degrees(ss), 1))
        mp.inputs["Rotation"].default_value = (0, 0, rot)
        if cut["kind"] == "day":
            # 空の太陽（極端に明るい点）は太陽ランプに任せる。カメラに見える空はそのまま
            lp = nt.nodes.new("ShaderNodeLightPath")
            clamp = nt.nodes.new("ShaderNodeVectorMath")
            clamp.operation = "MINIMUM"
            nt.links.new(env.outputs["Color"], clamp.inputs[0])
            clamp.inputs[1].default_value = (cfg["sky_clamp"],) * 3
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
            nt.links.new(clamp.outputs[0], mix.inputs[6])
            nt.links.new(env.outputs["Color"], mix.inputs[7])
            nt.links.new(mix.outputs[2], bg.inputs["Color"])
        else:
            nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    else:
        sky = nt.nodes.new("ShaderNodeTexSky")
        types = [e.identifier for e in sky.bl_rna.properties["sky_type"].enum_items]
        sky.sky_type = "MULTIPLE_SCATTERING" if "MULTIPLE_SCATTERING" in types else "NISHITA"
        if sun:
            sky.sun_elevation = math.radians(sun["el"])
            sky.sun_rotation = math.radians(sun["az"])
        else:
            sky.sun_elevation = math.radians(-3)
        sky.sun_disc = False
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        state["sky_fallback"] = True


def setup_sun(sc, cut, state):
    if state.get("sun") is not None:
        bpy.data.objects.remove(state["sun"])
        state["sun"] = None
    sun = cut.get("sun")
    if cut["kind"] != "day" or not sun:
        return
    d = bpy.data.lights.new("sun", "SUN")
    d.energy = cut.get("sun_strength", 3.0)
    d.angle = math.radians(0.53)
    ob = bpy.data.objects.new("sun", d)
    sc.collection.objects.link(ob)
    el, az = math.radians(sun["el"]), math.radians(sun["az"])
    to_sun = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    ob.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()
    state["sun"] = ob


def render_cut(sc, cut, cfg, lib, state, glow, ext_lights, preview):
    t0 = time.time()
    setup_world(sc, cut, cfg, state)
    setup_sun(sc, cut, state)
    dusk = cut["kind"] == "dusk"
    for v in lib.lamp_nodes:
        v.outputs[0].default_value = cfg["lamp_strength"] if dusk else 0.0
    if glow is not None:
        ob, P = glow
        ob.hide_render = not dusk
        P.inputs["Emission Strength"].default_value = cfg["room_light"]["strength"] if dusk else 0.0
    for ob in ext_lights:
        ob.hide_render = not dusk
    if state.get("cam") is None:
        cd = bpy.data.cameras.new("cam")
        cd.sensor_width = 36.0
        cd.clip_start = 0.05
        cd.clip_end = 5000.0
        state["cam"] = bpy.data.objects.new("cam", cd)
        sc.collection.objects.link(state["cam"])
    cam = state["cam"]
    cam.data.lens = cut["lens"]
    cam.location = Vector(cut["cam"])
    cam.rotation_euler = (Vector(cut["target"]) - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    sc.render.engine = "CYCLES"
    c = sc.cycles
    c.device = "CPU"
    c.samples = cut["samples"]
    c.use_adaptive_sampling = True
    c.adaptive_threshold = cfg["adaptive_threshold"]
    c.time_limit = cut["time_limit"]
    c.use_denoising = True
    c.denoiser = "OPENIMAGEDENOISE"
    c.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    c.max_bounces = cfg["max_bounces"]
    c.diffuse_bounces, c.glossy_bounces, c.transmission_bounces = 3, 3, 6
    c.caustics_reflective = c.caustics_refractive = False
    c.use_light_tree = True
    c.texture_limit_render = "2048"
    sc.render.resolution_x, sc.render.resolution_y = cut["res"]
    sc.render.resolution_percentage = 100
    sc.render.threads_mode = "AUTO"
    sc.view_settings.view_transform = cfg.get("view_transform", "AgX")
    sc.view_settings.look = cfg.get("look", "None")
    sc.view_settings.exposure = cut["exposure"]
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "8"
    sc.render.use_stamp = False
    for k in dir(sc.render):
        if k.startswith("use_stamp"):
            try:
                setattr(sc.render, k, False)
            except Exception:
                pass
    sc.render.filepath = cut["out"]
    Path(cut["out"]).parent.mkdir(parents=True, exist_ok=True)
    t1 = time.time()
    bpy.ops.render.render(write_still=True)
    return dict(id=cut["id"], file=cut["out"], seconds=round(time.time() - t0, 1), render_seconds=round(time.time() - t1, 1),
                samples=cut["samples"], res=cut["res"], exposure=cut["exposure"], hdri_sun=state.get("hdri_sun"),
                sky_fallback=state.get("sky_fallback", False))


def main_interior(cfg, only):
    """内装CG（cfg["mode"] == "interior"）: GLB の内装・家具に材質を与え、カットごとに照明・扉・スクリーンを切り替えて描画する。"""
    import cg_interior
    me = sys.modules[__name__]
    t0 = time.time()
    sc, lib, meshes, M = build_scene(cfg)
    st = cg_interior.prepare(me, sc, lib, meshes, M, cfg)
    log("scene built", round(time.time() - t0, 1), "s;", len(meshes), "objects;", len(lib.mats), "materials; fallbacks:", lib.fallbacks)
    log("MATERIAL_COLORS " + json.dumps(Lib.audit_log, sort_keys=True))
    state, results = {}, []
    for cut in cfg["cuts"]:
        if only and cut["id"] not in only:
            continue
        log("render", cut["id"], cut["res"], cut["samples"], "spp, limit", cut["time_limit"], "s")
        r = cg_interior.render_interior_cut(me, sc, cut, cfg, lib, st, state, M)
        r["texture_fallbacks"] = lib.fallbacks
        results.append(r)
        log("done", r)
        Path(cfg["raw_log"]).write_text(json.dumps(dict(setup_seconds=round(time.time() - t0, 1), cuts=results, material_colors=Lib.audit_log),
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    log("all done", round(time.time() - t0, 1), "s")


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    if cfg.get("mode") == "interior":
        return main_interior(cfg, only)
    t0 = time.time()
    sc, lib, meshes, M = build_scene(cfg)
    add_plants(cfg, lib, M)
    glow = add_window_glow(cfg, M) if cfg["window_lights"] else None
    ext_lights = add_ext_lights(cfg)
    log("scene built", round(time.time() - t0, 1), "s;", len(meshes), "objects;", len(lib.mats), "materials; fallbacks:", lib.fallbacks)
    # 各材質の色（リニア）を出力する（段階1が仕様値と照合する）
    log("MATERIAL_COLORS " + json.dumps(Lib.audit_log, sort_keys=True))
    state = {}
    results = []
    for cut in cfg["cuts"]:
        if only and cut["id"] not in only:
            continue
        log("render", cut["id"], cut["res"], cut["samples"], "spp, limit", cut["time_limit"], "s")
        r = render_cut(sc, cut, cfg, lib, state, glow, ext_lights, cfg["preview"])
        r["texture_fallbacks"] = lib.fallbacks
        results.append(r)
        log("done", r)
        Path(cfg["raw_log"]).write_text(json.dumps(dict(setup_seconds=round(t0 and (time.time() - t0), 1), cuts=results), ensure_ascii=False, indent=1), encoding="utf-8")
    log("all done", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
