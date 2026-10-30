"""内装CG 段階2（Blender）: cg_blender.py から cfg["mode"] == "interior" のときに呼ばれる。

GLB（dist/model_interior.glb）の各ノードは「グループ|階|材質キー|ID」。材質は spec.yaml の interior_palette（リニアに直して scene.json で受け取る）。
テクスチャは「色の変化を残し、平均色を仕様色に合わせる」（チャンネルごとに 仕様色/テクスチャ平均 を掛ける）。
"""
from __future__ import annotations

import math
import re
from collections import defaultdict

import bpy
from mathutils import Matrix, Vector


def log(*a):
    print("[cg-int]", *a, flush=True)


def lin4(rgb, k=1.0):
    return (rgb[0] * k, rgb[1] * k, rgb[2] * k, 1.0)


# ===================================================================== 材質
def _tex_image(CB, lib, cfg, name):
    """テクスチャ名 → (image, 平均リニア RGB)。取得できていなければ None（手続き生成に切り替える）。"""
    t = cfg["textures"].get(name)
    if not t or not t.get("diff"):
        if name not in lib.fallbacks:
            lib.fallbacks.append(name)
        return None
    cache = lib.__dict__.setdefault("_int_img", {})
    if name not in cache:
        import numpy as np
        img = bpy.data.images.load(t["diff"])
        img.colorspace_settings.name = "sRGB"
        px = np.empty(len(img.pixels), dtype="float32")
        img.pixels.foreach_get(px)
        rgb = px.reshape(-1, 4)[:, :3]
        lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)      # Image.pixels は sRGB 符号化値なのでリニアに直して平均する
        cache[name] = (img, [float(v) for v in lin.mean(axis=0)])
    return cache[name]


def make_material(CB, lib, key, cfg):
    pal = cfg["interior"]["palette"][key]
    mat = bpy.data.materials.new(key)
    b = CB.NT(mat)
    P = b.bsdf
    rgb = pal["rgb"]
    P.inputs["Roughness"].default_value = pal.get("roughness", 0.8)
    P.inputs["Metallic"].default_value = pal.get("metallic", 0.0)
    if pal.get("coat"):
        P.inputs["Coat Weight"].default_value = pal["coat"]
        P.inputs["Coat Roughness"].default_value = 0.1
    if pal.get("sheen"):
        P.inputs["Sheen Weight"].default_value = pal["sheen"]
    if pal.get("sss"):
        P.inputs["Subsurface Weight"].default_value = pal["sss"]
    P.inputs["Base Color"].default_value = lin4(rgb)
    CB.Lib.audit_log[key] = [round(v, 4) for v in rgb]
    fn = globals().get("p_" + key)
    if fn is not None:
        fn(CB, lib, b, pal, cfg)
    elif pal.get("tex"):
        tex_matched(CB, lib, b, pal, cfg)
    lib.mats[key] = mat
    return mat


def tex_matched(CB, lib, b, pal, cfg):
    name = pal["tex"]
    im = _tex_image(CB, lib, cfg, name)
    rgb = pal["rgb"]
    if im is None:
        if name == "osb":
            osb_procedural(b, pal)
        return None
    img, mean = im
    ratio = tuple(float(rgb[i] / max(mean[i], 1e-4)) for i in range(3))
    co = b.tc().outputs["Object"]
    mp = b.node("ShaderNodeMapping", vector_type="POINT")
    b.nt.links.new(co, mp.inputs["Vector"])
    mp.inputs["Scale"].default_value = (1 / pal["tile_m"],) * 3
    n = b.node("ShaderNodeTexImage", projection="BOX", projection_blend=0.2, image=img)
    b.nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
    matched = b.vmath("MULTIPLY", n.outputs["Color"], ratio)
    var = pal.get("var")
    if var:                                   # 変化を弱める（床シート ±3%、ゴム ±6%）
        matched = b.mixc(lin4(rgb), matched, min(1.0, var / 0.3))
    b.set(b.bsdf.inputs["Base Color"], matched)
    lum = b.node("ShaderNodeRGBToBW")
    b.nt.links.new(n.outputs["Color"], lum.inputs["Color"])
    if pal.get("bump"):
        b.set(b.bsdf.inputs["Normal"], b.bump(lum.outputs["Val"], pal["bump"], 0.001))
    return lum.outputs["Val"]


def osb_procedural(b, pal):
    """OSB の手続き生成（取得できないときの代替）。細長い削片（Voronoi を x 方向に 1、y 方向に 3.5 倍に伸ばす）＋細かい明暗。"""
    rgb = pal["rgb"]
    co = b.tc().outputs["Object"]
    sv = b.scalev(co, 18.0, 63.0, 18.0)
    vc = b.node("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
    b.nt.links.new(sv, vc.inputs["Vector"])
    vc.inputs["Scale"].default_value = 1.0
    sep = b.node("ShaderNodeSeparateColor")
    b.nt.links.new(vc.outputs["Color"], sep.inputs["Color"])
    bright = b.maprange(sep.outputs[0], 0.0, 1.0, 0.82, 1.12)
    edge = b.maprange(vc.outputs["Distance"], 0.0, 0.15, 0.94, 1.0)
    nz = b.node("ShaderNodeTexNoise", noise_dimensions="3D")
    b.nt.links.new(b.scalev(co, 120.0), nz.inputs["Vector"])
    fine = b.maprange(nz.outputs["Fac"], 0.3, 0.7, 0.96, 1.04)
    k = b.math("MULTIPLY", b.math("MULTIPLY", bright, edge), fine)
    b.set(b.bsdf.inputs["Base Color"], b.vmath("MULTIPLY", lin4(rgb)[:3], b.comb(k, k, k)))
    b.set(b.bsdf.inputs["Normal"], b.bump(vc.outputs["Distance"], 0.15, 0.001))
    print("[cg-int] procedural fallback: oriented_strand_board", flush=True)


def _brick_tiles(CB, b, pal, w, h, mortar, mortar_rgb, var, bump=0.3):
    rgb = pal["rgb"]
    col, fac = b.brick(b.plane(), w, h, mortar, lin4(rgb, 1 - var), lin4(rgb, 1 + var), lin4(mortar_rgb), offset=0.0)
    b.set(b.bsdf.inputs["Base Color"], col)
    b.set(b.bsdf.inputs["Roughness"], b.mixf(pal.get("roughness", 0.8), 0.95, fac))
    b.set(b.bsdf.inputs["Normal"], b.bump(fac, bump, 0.001, invert=True))
    return fac


def p_floor_tile_genkan(CB, lib, b, pal, cfg):
    _brick_tiles(CB, b, pal, 0.6, 0.6, 0.002, _lin("#8E8A7E"), 0.04)


def p_floor_carpet(CB, lib, b, pal, cfg):
    fac = _brick_tiles(CB, b, pal, 0.5, 0.5, 0.001, [v * 0.8 for v in pal["rgb"]], 0.02, 0.2)
    nz = b.node("ShaderNodeTexNoise", noise_dimensions="3D")
    b.nt.links.new(b.scalev(b.tc().outputs["Object"], 600.0), nz.inputs["Vector"])
    nz.inputs["Detail"].default_value = 3.0
    b.set(b.bsdf.inputs["Normal"], b.bump(nz.outputs["Fac"], 0.25, 0.0008))


def p_wall_theater(CB, lib, b, pal, cfg):
    _brick_tiles(CB, b, pal, 0.6, 1.2, 0.002, [v * 0.7 for v in pal["rgb"]], 0.015, 0.2)


def _lin(hx):
    out = []
    for i in (1, 3, 5):
        c = int(hx[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def p_zip_fabric(CB, lib, b, pal, cfg):
    """開口率 5% の生地: 透過を少し混ぜる（外の景色がわずかに透ける）。"""
    tr = b.node("ShaderNodeBsdfTransparent")
    mix = b.node("ShaderNodeMixShader")
    mix.inputs[0].default_value = pal.get("open_ratio", 0.05)
    b.nt.links.new(b.bsdf.outputs["BSDF"], mix.inputs[1])
    b.nt.links.new(tr.outputs[0], mix.inputs[2])
    b.nt.links.new(mix.outputs[0], b.out.inputs["Surface"])


def p_lamp_face(CB, lib, b, pal, cfg):
    P = b.bsdf
    P.inputs["Base Color"].default_value = (1, 1, 1, 1)
    bb = b.node("ShaderNodeBlackbody")
    bb.inputs["Temperature"].default_value = 4000.0
    b.nt.links.new(bb.outputs["Color"], P.inputs["Emission Color"])
    P.inputs["Emission Strength"].default_value = 0.0
    lib.int_lamp = (P, bb)


def _glass(b, ior, rough):
    P = b.bsdf
    P.inputs["Transmission Weight"].default_value = 1.0
    P.inputs["IOR"].default_value = ior
    P.inputs["Roughness"].default_value = rough
    P.inputs["Metallic"].default_value = 0.0


def p_glass_door(CB, lib, b, pal, cfg):
    """合わせ強化ガラス（厚 10.8 の箱）。試験で、薄板の Transparent＋Glossy は斜めから見ると黒い破綻が出たため Principled 透過を採る。"""
    _glass(b, 1.52, 0.0)


def p_glass_clear(CB, lib, b, pal, cfg):
    _glass(b, 1.5, 0.02)


def window_glass_material(CB, tv_ns, tv_ew):
    """窓ガラス（内装CG用）。Transparent と Glossy（GGX・白）の混合で、屈折は使わない。
    反射は室内側の 1 面だけ: 係数 = Fresnel(IOR 1.52) × (1 − Backfacing) × 0.6。透過色は 1 面あたり √tv（2 面を通るため）。
    面の向きは Object の Normal で判定: |nx| > |ny| なら東西（shield 型）、それ以外は南北（gain 型）。"""
    mat = bpy.data.materials.new("window_glass")
    b = CB.NT(mat)
    nt = b.nt
    nt.nodes.remove(b.bsdf)
    tr = b.node("ShaderNodeBsdfTransparent")
    gl = b.node("ShaderNodeBsdfGlossy")
    gl.distribution = "GGX"
    gl.inputs["Roughness"].default_value = 0.01
    gl.inputs["Color"].default_value = (1, 1, 1, 1)
    fr = b.node("ShaderNodeFresnel")
    fr.inputs["IOR"].default_value = 1.52
    lp = b.node("ShaderNodeNewGeometry")
    bf = b.node("ShaderNodeMath", operation="SUBTRACT")
    bf.inputs[0].default_value = 1.0
    nt.links.new(lp.outputs["Backfacing"], bf.inputs[1])
    m1 = b.node("ShaderNodeMath", operation="MULTIPLY")
    nt.links.new(fr.outputs["Fac"], m1.inputs[0])
    nt.links.new(bf.outputs[0], m1.inputs[1])
    m2 = b.node("ShaderNodeMath", operation="MULTIPLY")
    nt.links.new(m1.outputs[0], m2.inputs[0])
    m2.inputs[1].default_value = 0.6
    mix = b.node("ShaderNodeMixShader")
    nt.links.new(m2.outputs[0], mix.inputs[0])
    nt.links.new(tr.outputs["BSDF"], mix.inputs[1])
    nt.links.new(gl.outputs["BSDF"], mix.inputs[2])
    # 透過色: 向きで切り替え
    tc = b.tc()
    sep = b.node("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Normal"], sep.inputs[0])
    ax = b.node("ShaderNodeMath", operation="ABSOLUTE")
    nt.links.new(sep.outputs["X"], ax.inputs[0])
    ay = b.node("ShaderNodeMath", operation="ABSOLUTE")
    nt.links.new(sep.outputs["Y"], ay.inputs[0])
    gt = b.node("ShaderNodeMath", operation="GREATER_THAN")
    nt.links.new(ax.outputs[0], gt.inputs[0])
    nt.links.new(ay.outputs[0], gt.inputs[1])
    cm = b.node("ShaderNodeMix", data_type="RGBA")
    nt.links.new(gt.outputs[0], cm.inputs["Factor"])

    def col(tv):
        v = math.sqrt(tv)
        return (v * 0.99, v, v, 1.0)
    cm.inputs["A"].default_value = col(tv_ns)
    cm.inputs["B"].default_value = col(tv_ew)
    nt.links.new(cm.outputs["Result"], tr.inputs["Color"])
    nt.links.new(mix.outputs["Shader"], b.out.inputs["Surface"])
    return mat


def add_scenery(CB, cfg, M):
    """窓の外の遠景の木の帯。4 種の低ポリゴンの木（幹＋icosphere 細分 2 の葉 3〜5 個）を作り、リンク複製（メッシュ共有）で並べる。"""
    import random
    sc_cfg = cfg.get("scenery") or {}
    trees = sc_cfg.get("trees") or []
    if not trees:
        return
    import bmesh
    leaf = bpy.data.materials.new("tree_leaf")
    b = CB.NT(leaf)
    nz = b.node("ShaderNodeTexNoise", noise_dimensions="3D")
    b.nt.links.new(b.tc().outputs["Object"], nz.inputs["Vector"])
    nz.inputs["Scale"].default_value = 1.2
    c1, c2 = cfg["colors_lin"]["plant_a"], cfg["colors_lin"]["plant_b"]
    b.set(b.bsdf.inputs["Base Color"], b.mixc(lin4(c1), lin4(c2), nz.outputs["Fac"]))
    b.bsdf.inputs["Roughness"].default_value = 0.8
    trunk = bpy.data.materials.new("tree_trunk")
    bt = CB.NT(trunk)
    bt.bsdf.inputs["Base Color"].default_value = lin4(sc_cfg["trunk"])
    bt.bsdf.inputs["Roughness"].default_value = 0.9
    variants = []
    for v in range(4):
        rnd = random.Random(100 + v)
        bm = bmesh.new()
        # 幹（単位の高さ 1.0 の八角柱）
        bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.022, radius2=0.012, depth=0.42, matrix=Matrix.Translation((0, 0, 0.21)))
        for f in bm.faces:
            f.material_index = 1
        n = rnd.randint(3, 5)
        for i in range(n):
            r = rnd.uniform(0.20, 0.30)
            ang = rnd.uniform(0, 2 * math.pi)
            d = 0.0 if i == 0 else rnd.uniform(0.10, 0.20)
            cz = 0.62 + (rnd.uniform(-0.10, 0.20) if i else 0.12)
            before = set(bm.faces)
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r, matrix=Matrix.Translation((d * math.cos(ang), d * math.sin(ang), cz)))
            for f in bm.faces:
                if f not in before:
                    f.material_index = 0
        me = bpy.data.meshes.new("tree_v%d" % v)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(leaf)
        me.materials.append(trunk)
        variants.append(me)
    for i, t in enumerate(trees):
        rnd = random.Random(t["seed"])
        ob = bpy.data.objects.new("tree", variants[i % 4])          # メッシュを共有（リンク複製）
        sc_h = t["h"]
        ob.scale = (sc_h * rnd.uniform(0.85, 1.15), sc_h * rnd.uniform(0.85, 1.15), sc_h)
        ob.rotation_euler = (0, 0, rnd.uniform(0, 2 * math.pi))
        ob.location = (t["p"][0], t["p"][1], t["p"][2] - 0.2)
        bpy.context.scene.collection.objects.link(ob)
        ob.matrix_world = M @ (Matrix.Translation(ob.location) @ ob.rotation_euler.to_matrix().to_4x4() @ Matrix.Diagonal((*ob.scale, 1.0)))
    log("scenery trees", len(trees), "variants", len(variants))


def cam_only_emission(name, strength, kelvin):
    """カメラ光線にだけ見える発光面（照明は別の面光源・Spot が行う。二重に数えない）。戻り値: (材質, 強さの入力, 色温度の入力)。"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    bb = nt.nodes.new("ShaderNodeBlackbody")
    bb.inputs["Temperature"].default_value = kelvin
    nt.links.new(bb.outputs[0], em.inputs["Color"])
    em.inputs["Strength"].default_value = strength
    df = nt.nodes.new("ShaderNodeBsdfDiffuse")
    df.inputs["Color"].default_value = (0.9, 0.9, 0.9, 1)
    lp = nt.nodes.new("ShaderNodeLightPath")
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mx.inputs[0])
    nt.links.new(df.outputs[0], mx.inputs[1])
    nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs[0])
    return m, em.inputs["Strength"], bb.inputs["Temperature"]


def p_screen(CB, lib, b, pal, cfg):
    """スクリーン: 白い板。I07 では 16:9 の手続き画像（夕景の空と地平線のグラデーション。人物・ロゴなし）を Emission で映す。"""
    P = b.bsdf
    co = b.tc().outputs["Object"]
    x, y, z = b.sep(co)
    ux = b.maprange(x, cfg["interior"]["screen_rect"][0], cfg["interior"]["screen_rect"][2], 0.0, 1.0)
    vz = b.maprange(z, cfg["interior"]["screen_rect"][1], cfg["interior"]["screen_rect"][3], 0.0, 1.0)
    ramp = b.node("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].position = 0.0
    cr.elements[0].color = (0.020, 0.016, 0.014, 1)
    cr.elements[1].position = 1.0
    cr.elements[1].color = (0.22, 0.14, 0.17, 1)
    for pos, col in [(0.30, (0.030, 0.022, 0.018, 1)), (0.44, (0.80, 0.30, 0.07, 1)), (0.52, (0.95, 0.50, 0.20, 1)), (0.72, (0.45, 0.22, 0.22, 1))]:
        cr.elements.new(pos).color = col
    # 横方向に少しだけ明るさを振る（一様な光にしない）
    k = b.maprange(ux, 0.0, 1.0, 0.85, 1.1)
    b.nt.links.new(vz, ramp.inputs["Fac"])
    col = b.vmath("MULTIPLY", ramp.outputs["Color"], b.comb(k, k, k))
    b.set(P.inputs["Emission Color"], col)
    P.inputs["Emission Strength"].default_value = 0.0
    lib.int_screen = P


# ===================================================================== 建物の材質の内側マスク（ライニングで覆いきれない所の保険）
def interior_mask_material(CB, lib, old_key, int_key, cfg):
    m = lib.mats.get(old_key)
    if m is None:
        return
    nt = m.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    src = out.inputs["Surface"].links[0].from_socket
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])

    def cmp(sock, op, v):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        nt.links.new(sock, n.inputs[0])
        n.inputs[1].default_value = v
        return n.outputs[0]

    def mul(a, b_):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = "MULTIPLY"
        nt.links.new(a, n.inputs[0])
        nt.links.new(b_, n.inputs[1])
        return n.outputs[0]

    x, y, z = sep.outputs
    W, D, zt = cfg["interior"]["inside_m"]
    k = mul(mul(cmp(x, "GREATER_THAN", 0.001), cmp(x, "LESS_THAN", W - 0.001)), mul(cmp(y, "GREATER_THAN", 0.001), cmp(y, "LESS_THAN", D - 0.001)))
    k = mul(k, cmp(z, "LESS_THAN", zt))
    pb = nt.nodes.new("ShaderNodeBsdfPrincipled")
    pal = cfg["interior"]["palette"][int_key]
    pb.inputs["Base Color"].default_value = lin4(pal["rgb"])
    pb.inputs["Roughness"].default_value = pal.get("roughness", 0.9)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(k, mix.inputs[0])
    nt.links.new(src, mix.inputs[1])
    nt.links.new(pb.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


def prepare(CB, sc, lib, meshes, M, cfg):
    """build_scene の後: 建物の材質の差し替え、扉・スクリーン・照明器具・ダウンライトの用意。戻り値は描画用の状態。"""
    pal = cfg["interior"]["palette"]
    for key in ("base", "partition"):
        interior_mask_material(CB, lib, key, "wall_paint", cfg)
    # 床スラブ・天井・階段は内装の材質へ
    for o in meshes:
        key = re.sub(r"\.\d+$", "", o.name).split("|")[2]
        if key == "slab" and "ceiling_paint" in lib.mats:
            o.data.materials.clear()
            o.data.materials.append(lib.mats["ceiling_paint"])
        elif key == "stair" and "floor_oak" in lib.mats:
            o.data.materials.clear()
            o.data.materials.append(lib.mats["floor_oak"])
    # 窓ガラスは透過のみの材質に差し替える（外観の m_glass は変えない）
    gt = cfg["interior"].get("glass_tv", {"gain": 0.62, "shield": 0.50})
    wg = window_glass_material(CB, gt["gain"], gt["shield"])
    n_glass = 0
    for o in meshes:
        if re.sub(r"\.\d+$", "", o.name).split("|")[2] == "glass":
            o.data.materials.clear()
            o.data.materials.append(wg)
            n_glass += 1
    log("window glass", n_glass, "meshes", gt)
    # 照明器具の発光面は階ごとに点灯／消灯できるよう、消灯用の材質を作る
    off = bpy.data.materials.new("lamp_face_off")
    bo = CB.NT(off)
    bo.bsdf.inputs["Base Color"].default_value = (0.9, 0.9, 0.9, 1)
    bo.bsdf.inputs["Roughness"].default_value = 0.4
    st = dict(doors=defaultdict(list), fabrics=[], fixtures=[], screen_objs=[], lights=[], lamp_off=off, line_objs={}, foot_objs={}, lines=[], foots=[])
    for o in meshes:
        parts = re.sub(r"\.\d+$", "", o.name).split("|")
        grp = parts[0]
        if grp == "扉" and len(parts) > 3:
            st["doors"][parts[3]].append(o)
        elif grp == "外付けスクリーン生地":
            st["fabrics"].append(o)
        elif grp == "照明器具" and parts[2] == "lamp_face":
            st["fixtures"].append((o, parts[1]))
        elif grp == "照明器具" and parts[2] == "line_face" and len(parts) > 3:
            st["line_objs"][parts[3]] = o
        elif grp == "照明器具" and parts[2] == "foot_face" and len(parts) > 3:
            st["foot_objs"][parts[3]] = o
        elif grp == "家具" and parts[2] == "screen":
            st["screen_objs"].append(o)
    # ダウンライト（Spot、真下向き）
    for d in cfg["interior"]["downlights"]:
        L = bpy.data.lights.new("dl", "SPOT")
        L.spot_size = math.radians(110)
        L.spot_blend = 0.6
        L.shadow_soft_size = 0.04
        ob = bpy.data.objects.new("dl", L)
        ob.location = M @ (Vector(d["p"]) / 1000.0 - Vector((0, 0, 0.006)))
        ob.rotation_euler = (0, 0, 0)
        sc.collection.objects.link(ob)
        st["lights"].append((ob, d))
    # ライン照明（面光源 AREA。発光面は同じ換算の cam-only 発光）と階段の足元灯（Spot、壁から 12mm 前・45° 下向き）
    for l in cfg["interior"].get("lines", []):
        wd = cfg["interior"]["line_w_mm"] / 1000.0 - 0.008
        L = bpy.data.lights.new("ln", "AREA")
        L.shape = "RECTANGLE"
        L.size = l["L"] / 1000.0
        L.size_y = wd
        ob = bpy.data.objects.new("ln", L)
        ang = 0.0 if l["axis"] == "x" else math.pi / 2
        cx, cy = (l["p0"][0] + l["p1"][0]) / 2000.0, (l["p0"][1] + l["p1"][1]) / 2000.0
        zz = (l["p0"][2] - cfg["interior"]["line_h_mm"]) / 1000.0 - 0.002
        if l["room"] == "ジム":                       # 直天井は器具本体が 2mm 下がる（interior_shell と同じ）。面光源が発光面の箱に埋もれないように合わせる
            zz -= 0.002
        ob.matrix_world = M @ Matrix.Translation((cx, cy, zz)) @ Matrix.Rotation(ang, 4, "Z")
        sc.collection.objects.link(ob)
        mat, sI, tI = cam_only_emission("line_" + l["id"], 1.0, 4000.0)
        fo = st["line_objs"].get(l["id"])
        if fo is not None:
            fo.data.materials.clear()
            fo.data.materials.append(mat)
        st["lines"].append(dict(ob=ob, d=l, strength=sI, kelvin=tI, area=(l["L"] / 1000.0) * wd))
    for f in cfg["interior"].get("foots", []):
        x, y, z = (v / 1000.0 for v in f["p"])
        nx = f["n"][0]
        Lg = bpy.data.lights.new("ft", "SPOT")
        Lg.spot_size = math.radians(120)
        Lg.spot_blend = 0.5
        Lg.shadow_soft_size = 0.02
        ob = bpy.data.objects.new("ft", Lg)
        ob.matrix_world = M @ Matrix.Translation((x + nx * 0.012, y, z)) @ Matrix.Rotation(math.radians(-45 * nx), 4, "Y")
        sc.collection.objects.link(ob)
        mat, sI, tI = cam_only_emission("foot_" + f["id"], 1.0, 2200.0)
        fo = st["foot_objs"].get(f["id"])
        if fo is not None:
            fo.data.materials.clear()
            fo.data.materials.append(mat)
        st["foots"].append(dict(ob=ob, d=f, strength=sI, kelvin=tI))
    log("lights", len(st["lights"]), "lines", len(st["lines"]), "foots", len(st["foots"]), "doors", len(st["doors"]), "fabrics", len(st["fabrics"]), "fixtures", len(st["fixtures"]))
    return st


# ===================================================================== カットごとの設定
def set_doors(st, cfg, cut, M):
    """扉を既定の閉じた状態に戻してから、カットで指定された扉を開ける。"""
    info = cfg["interior"]["doors"]
    for did, objs in st["doors"].items():
        d = info.get(did)
        ratio = 0.0
        suffix = did.split("@")[-1]
        for t, r in cut.get("open_doors", {}).items():
            if suffix == t or suffix.rstrip("ab") == t:
                ratio = float(r)
        for o in objs:
            if d is None or ratio == 0.0:
                o.matrix_world = M
                continue
            if d["type"] == "swing":
                px, py = d["pivot"]
                piv = Vector((px / 1000.0, py / 1000.0, 0.0))
                R = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(90.0 * d["sign"] * ratio), 4, "Z") @ Matrix.Translation(-piv)
                o.matrix_world = M @ R
            else:
                trav = (d["width"] + 60) / 1000.0 * ratio * d["dir"]
                v = Vector((trav, 0, 0)) if d["axis"] == "x" else Vector((0, trav, 0))
                o.matrix_world = M @ Matrix.Translation(v)


def configure_cut(CB, sc, lib, st, cfg, cut, M):
    lit = set(cut["floors_lit"])
    ch = cut["ch"]                                      # {"L": [K, %], "D": [K, %], "F": [K, %]}
    ic = cfg["interior"]
    # D: 埋込ダウンライト（弱い補助灯。既存の Spot の 30%）
    (kd, pd) = ch["D"]
    w = cut["lamp_w"] * (pd / 100.0) * ic["downlight_ratio"]
    for ob, d in st["lights"]:
        ob.hide_render = d["floor"] not in lit or pd <= 0
        ob.data.energy = w * d.get("w", 1.0)
        ob.data.use_temperature = True
        ob.data.temperature = kd
        ob.data.color = (1, 1, 1)
    P, bb = lib.int_lamp
    bb.inputs["Temperature"].default_value = float(kd)
    P.inputs["Emission Strength"].default_value = pd / 100.0 * 20.0 * ic["downlight_ratio"]
    for o, lvl in st["fixtures"]:
        o.data.materials.clear()
        o.data.materials.append(lib.mats["lamp_face"] if lvl in lit else st["lamp_off"])
    # L: 直付ライン（面光源。強さ = lm × 0.008 W/lm × 明るさ%、発光面は同じ換算 = W ÷ 面積）
    (kl, pl) = ch["L"]
    for e in st["lines"]:
        d = e["d"]
        lm = d["lm_per_m"] * d["L"] / 1000.0 * pl / 100.0
        e["ob"].hide_render = d["floor"] not in lit or pl <= 0
        e["ob"].data.energy = lm * ic["k_area_w_per_lm"]
        e["ob"].data.use_temperature = True
        e["ob"].data.temperature = kl
        e["strength"].default_value = ic["k_area_w_per_lm"] * lm / e["area"] if pl > 0 else 0.0
        e["kelvin"].default_value = float(kl)
    # F: 階段の足元灯（Spot。40lm × 0.0375 W/lm × 明るさ%）
    (kf, pf) = ch["F"]
    for e in st["foots"]:
        e["ob"].hide_render = e["d"]["floor"] not in lit or pf <= 0
        e["ob"].data.energy = ic["foot_lm"] * ic["k_spot_w_per_lm"] * pf / 100.0
        e["ob"].data.use_temperature = True
        e["ob"].data.temperature = kf
        e["strength"].default_value = ic["k_area_w_per_lm"] * ic["foot_lm"] / (0.1 * 0.03) * pf / 100.0 if pf > 0 else 0.0
        e["kelvin"].default_value = float(kf)
    down = cut["screens"] == "down"
    for o in st["fabrics"]:
        o.hide_render = not down
    set_doors(st, cfg, cut, M)
    Pscr = lib.int_screen
    Pscr.inputs["Emission Strength"].default_value = 0.35 if cut.get("screen_video") else 0.0
    # 色・ホワイトバランス・露出
    sc.view_settings.view_transform = cfg.get("view_transform", "AgX")
    sc.view_settings.exposure = cut["exposure"]
    sc.view_settings.use_white_balance = True
    sc.view_settings.white_balance_temperature = cut["wb"]


def place_camera(sc, state, cut):
    import bpy as _b
    if state.get("cam") is None:
        cd = _b.data.cameras.new("cam")
        cd.sensor_width = 36.0
        cd.clip_start = 0.05
        cd.clip_end = 2000
        state["cam"] = _b.data.objects.new("cam", cd)
        sc.collection.objects.link(state["cam"])
    cam = state["cam"]
    cam.data.lens = cut["lens"]
    cam.location = Vector(cut["cam"])
    d = Vector(cut["target"]) - cam.location
    yaw = math.atan2(d.y, d.x)
    pitch = math.atan2(d.z, math.hypot(d.x, d.y)) if cut.get("pitch") is None else math.radians(cut["pitch"])
    cam.rotation_euler = (math.pi / 2 + pitch, 0, yaw - math.pi / 2)        # 水平を保つ（ヨーのみ注視点から）
    cam.data.shift_y = cut.get("shift_y", 0.0)
    cam.data.shift_x = cut.get("shift_x", 0.0)
    sc.camera = cam


def render_interior_cut(CB, sc, cut, cfg, lib, st, state, M):
    import time
    from pathlib import Path
    t0 = time.time()
    CB.setup_world(sc, cut, cfg, state)
    CB.setup_sun(sc, cut, state)
    configure_cut(CB, sc, lib, st, cfg, cut, M)
    place_camera(sc, state, cut)
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
    c.max_bounces = 8
    c.diffuse_bounces, c.glossy_bounces, c.transmission_bounces = 4, 3, 8
    c.transparent_max_bounces = 8
    c.caustics_reflective = c.caustics_refractive = False
    c.use_light_tree = True
    c.sample_clamp_indirect = 10.0
    c.texture_limit_render = "2048"
    sc.render.resolution_x, sc.render.resolution_y = cut["res"]
    sc.render.resolution_percentage = 100
    sc.render.threads_mode = "AUTO"
    sc.view_settings.look = "None"
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
                samples=cut["samples"], time_limit=cut["time_limit"], res=cut["res"], exposure=cut["exposure"], wb=cut["wb"],
                lamp_k=cut["lamp_k"], lamp_pct=cut["lamp_pct"], channels=cut.get("ch"), hdri_sun=state.get("hdri_sun"))
