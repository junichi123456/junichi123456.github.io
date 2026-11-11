"""マスター .blend の生成（bpy 側。v4.33）。export_blender.py master <job.json> <out.blend> <result.json> から呼ぶ。

GLB（内装・外観）を取り込み、材質・照明・太陽・カメラ 57 を与え、コレクション分け・命名・属性（glb_name・tag・channel 等）を付けて保存する。
テクスチャはパックしない（相対パス）。手で編集しない（次の build で上書き）。
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import blend_master as BM  # noqa: E402
import cg_blender as CB  # noqa: E402
import cg_interior as CI  # noqa: E402
import shoot_blender as SB  # noqa: E402


EXT_GROUPS = {"躯体（RC壁）", "外装（外断熱）", "屋上防水", "建具", "基礎", "外付けスクリーン", "外付けスクリーン生地", "カーポート", "ソーラーパーゴラ", "防犯カメラ", "門扉", "その他"}
SITE_GROUPS = {"周辺建物", "道路", "水路", "RC塀", "菜園", "ボラード", "外構照明", "忍び返し"}
INT_GROUPS = {"内装仕上げ", "扉", "間仕切", "階段", "床スラブ"}
INT_ONLY_GROUPS = {"家具", "台所小物", "照明器具", "内装仕上げ", "外付けスクリーン生地"}      # 外観カットでは隠す（内装の GLB にだけある）
GRP_CODE = {"家具": "furn", "台所小物": "kit", "照明器具": "lamp", "扉": "door", "内装仕上げ": "fin", "建具": "fit", "間仕切": "part", "階段": "stair", "床スラブ": "slab"}


def collection_for(grp, lvl):
    if grp in ("家具", "台所小物", "ジム機器"):
        return "Furniture_" + ("2F" if lvl in ("2F", "RF") else "1F")
    if grp == "照明器具":
        return "Lighting"
    if grp in SITE_GROUPS or grp.startswith("外構") or grp.startswith("地形"):
        return "Site"
    if grp in INT_GROUPS:
        return "Interior_" + ("2F" if lvl in ("2F", "RF") else "1F")
    return "Exterior"


def make_collections(sc):
    cols = {}
    for n in ("Exterior", "Interior_1F", "Interior_2F", "Furniture", "Lighting", "Site", "Cameras", "Overlay"):
        c = bpy.data.collections.new(n)
        sc.collection.children.link(c)
        cols[n] = c
    for n, parent in (("Furniture_1F", "Furniture"), ("Furniture_2F", "Furniture"), ("Ext", "Cameras"), ("Int_I", "Cameras"), ("Int_Z", "Cameras"), ("Int_R", "Cameras"), ("Int_T", "Cameras"), ("Section_1F", "Interior_1F"), ("Section_2F", "Interior_2F")):
        c = bpy.data.collections.new(n)
        cols[parent].children.link(c)
        cols[n] = c
    return cols


def put(ob, col):
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    col.objects.link(ob)


def convert_meshes(new_objs, M, Minv):
    """build_scene と同じ後処理（頂点を建物座標 m に戻し、オブジェクトの変換で真北基準に置く）。"""
    meshes = [o for o in new_objs if o.type == "MESH"]
    for o in meshes:
        w = o.matrix_world.copy()
        o.data.transform(w)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
        o.data.transform(Minv)
        o.matrix_world = M
    for o in [o for o in new_objs if o.type != "MESH"]:
        bpy.data.objects.remove(o)
    return meshes


def clean_materials(lib, before=None):
    """glTF 取り込みが作った材質（使われないもの）を消し、lib の材質を材質キーと同じ名前にする（名前の衝突で ".001" が付くため）。"""
    used = set(lib.mats.values())
    for m in list(bpy.data.materials):
        if m not in used and m.users == 0 and (before is None or m not in before):
            bpy.data.materials.remove(m)
    for k, m in lib.mats.items():
        if m.name != k:
            m.name = k


def import_ext_only(job, lib, M, int_names):
    """外観 GLB にだけあるノード（ジム機器・内部建具の一括ノード）を足す。重複するノードは内装 GLB 側に統合（捨てる）。"""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=job["glb_ext"])
    new = [o for o in bpy.data.objects if o not in before]
    Minv = M.inverted()
    meshes = convert_meshes(new, M, Minv)
    full_ext = BM.glb_node_names(job["glb_ext"])
    keep, drop = [], []
    taken = set()
    for o in meshes:
        full = BM.resolve_name(o.name, full_ext, taken)
        taken.add(full)
        (drop if full in int_names else keep).append((o, full))
    for o, _ in drop:
        me = o.data
        bpy.data.objects.remove(o)
        bpy.data.meshes.remove(me)
    mats = job["cfg_int"]["materials"]
    for o, full in keep:
        key = full.split("|")[2]
        if key not in lib.mats:
            lib.make(key, mats[key])
        o.data.materials.clear()
        o.data.materials.append(lib.mats[key])
        o.data.polygons.foreach_set("use_smooth", [False] * len(o.data.polygons))
    return keep


def add_section_caps(job, cols, M):
    """T（天井視点）の断面キャップ。FL+2,400 の水平面が貫く壁・間仕切（濃灰）・外断熱（中濃灰）・造作家具（中灰）の上面。
    カメラにだけ写り（影・間接光に寄与しない）、T のカット以外ではコレクションごと非表示（shoot の configure_cut が切り替える）。"""
    import bmesh
    mats = {}
    # カメラの WB（5,500K）で灰色が青く転ぶのを打ち消す: 5,500K の昼光色（Y=1 に正規化した線形 sRGB）を掛ける
    T = 5500.0
    x = -3.0258469e9 / T ** 3 + 2.1070379e6 / T ** 2 + 0.2226347e3 / T + 0.240390
    y = -3.000 * x * x + 2.870 * x - 0.275
    X, Z = x / y, (1 - x - y) / y
    tint = (3.2406 * X - 1.5372 + -0.4986 * Z, -0.9689 * X + 1.8758 + 0.0415 * Z, 0.0557 * X - 0.2040 + 1.0570 * Z)

    def mat(kind):
        if kind not in mats:
            hexv = {"wall": "#2B2B2B", "insul": "#5C5C5C", "furniture": "#8A8A8A"}[kind]
            lin = [((int(hexv[i:i + 2], 16) / 255.0) / 12.92 if int(hexv[i:i + 2], 16) / 255.0 <= 0.04045 else (((int(hexv[i:i + 2], 16) / 255.0) + 0.055) / 1.055) ** 2.4) for i in (1, 3, 5)]
            m = bpy.data.materials.new("section_" + kind)
            m.use_nodes = True
            nt = m.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs["Color"].default_value = (*[c * t for c, t in zip(lin, tint)], 1.0)
            em.inputs["Strength"].default_value = 1.4          # 露出 −0.5EV で指定の灰色に見える強さ
            nt.links.new(em.outputs[0], out.inputs[0])
            m.use_fake_user = True
            mats[kind] = m
        return mats[kind]
    n = 0
    for fl in ("1F", "2F"):
        items = [b for b in job["section"] if b["floor"] == fl]
        bm = {}
        for b in items:
            x0, y0, x1, y1 = (v / 1000.0 for v in b["rect"])
            z1, z0 = b["z"] / 1000.0 - 0.002, b["z"] / 1000.0 - 0.022
            g = bm.setdefault(b["kind"], bmesh.new())
            vs = [g.verts.new(p) for p in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
            for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                g.faces.new([vs[i] for i in f])
            n += 1
        for kind, g in bm.items():
            me = bpy.data.meshes.new(f"section.{fl}.{kind}")
            g.to_mesh(me)
            g.free()
            me.materials.append(mat(kind))
            ob = bpy.data.objects.new(f"Section.{fl}.{kind}", me)
            ob.matrix_world = M
            ob["kind"], ob["shoot_modes"], ob["section_floor"] = "section_cap", "int", fl
            ob.visible_shadow = ob.visible_diffuse = ob.visible_glossy = ob.visible_transmission = ob.visible_volume_scatter = False
            cols["Section_" + fl].objects.link(ob)
        cols["Section_" + fl].hide_render = True
        cols["Section_" + fl].hide_viewport = True
    return n


def add_cameras_all(sc, job, cols):
    first = None
    for cam in job["cams"]:
        cut = cam["cut"]
        interior = cam["kind"] == "int"
        cd = bpy.data.cameras.new(cam["id"])
        cd.sensor_width = 36.0
        cd.clip_start = 0.05
        cd.clip_end = 2000.0 if interior else 5000.0
        cd.lens = cut["lens"]
        if cut.get("ortho_scale"):                            # T: 正投影・天井面に立って手前 400mm を切る（FL+2,400 の水平断面）
            cd.type = "ORTHO"
            cd.ortho_scale = cut["ortho_scale"]
            cd.clip_start = cut.get("clip_start") or 0.05
        ob = bpy.data.objects.new(cam["id"], cd)
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
        put_new = cols[{"C": "Ext", "I": "Int_I", "Z": "Int_Z", "R": "Int_R", "T": "Int_T"}[cam["family"]]]
        put_new.objects.link(ob)
        for k, v in cam["props"].items():
            ob[k] = v
        first = first or ob
    sc.camera = first


def build_master(job, out):
    t0 = time.time()
    cfg_i, cfg_e = job["cfg_int"], job["cfg_ext"]
    bpy.context.preferences.filepaths.save_version = 0
    sc, lib, meshes, M = CB.build_scene(cfg_i)
    Minv = M.inverted()
    clean_materials(lib)
    int_names = set(BM.glb_node_names(cfg_i["glb"]))
    # 解決した GLB 名（Blender の名前は 63 バイトで切れるので、GLB のノード名一覧に戻す）
    taken = set()
    full_of = {}
    for o in meshes:
        full = BM.resolve_name(o.name, sorted(int_names), taken)
        taken.add(full)
        full_of[o] = full
    # 外観用の材質を残す（prepare が差し替える前の状態）
    ext_mat = {o: o.data.materials[0] for o in meshes}
    ext_copy = {}
    for k in ("base", "partition"):
        if k in lib.mats:
            ext_copy[k] = lib.mats[k].copy()
            ext_copy[k].name = k + ".ext"
    st = CI.prepare(CB, sc, lib, meshes, M, cfg_i)
    CB.add_plants(cfg_i, lib, M)
    plants = [o for o in bpy.data.objects if o.name.startswith("plant")]
    before = set(bpy.data.objects)
    CI.add_scenery(CB, cfg_i, M)
    trees = [o for o in bpy.data.objects if o not in before]
    before_m = set(bpy.data.materials)
    keep = import_ext_only(job, lib, M, int_names)
    clean_materials(lib, before_m)
    glow = CB.add_window_glow(cfg_e, M) if cfg_e["window_lights"] else None
    ext_lights = CB.add_ext_lights(cfg_e)
    default_cut = cfg_i["cuts"][0]
    CI.configure_cut(CB, sc, lib, st, cfg_i, default_cut, M)
    day = next((c for c in cfg_e["cuts"] if c["kind"] == "day"), cfg_e["cuts"][0])
    state = {}
    CB.setup_world(sc, day, cfg_e, state)
    CB.setup_sun(sc, day, state)
    sun = state.get("sun")
    # ---- コレクションと属性
    cols = make_collections(sc)
    used = set()
    furn_names = job["furn_names"]

    def mkname(lvl, grp, parts):
        lvl = "S" if lvl == "-" else lvl
        base = BM.ascii_name(parts[3] if len(parts) > 3 else parts[2])
        for nm in (f"{lvl}.{base}", f"{lvl}.{base}.{BM.ascii_name(parts[2])}", f"{lvl}.{GRP_CODE.get(grp, 'x')}.{base}.{BM.ascii_name(parts[2])}"):
            if nm not in used:
                used.add(nm)
                return nm
        n = 2
        while f"{lvl}.{base}.{n}" in used:
            n += 1
        used.add(f"{lvl}.{base}.{n}")
        return f"{lvl}.{base}.{n}"

    def tag_mesh(o, full, ext_only):
        parts = full.split("|")
        grp, lvl, mk = parts[0], parts[1], parts[2]
        nid = parts[3] if len(parts) > 3 else ""
        o.name = mkname(lvl, grp, parts)
        o["glb_name"] = full
        o["grp"], o["lvl"], o["mk"] = grp, lvl, mk
        if grp == "家具" and nid:
            o["kind"], o["tag"] = "furniture", nid
            o["ifc_name"] = furn_names.get(nid, "")
        elif grp == "扉" and nid:
            o["kind"], o["tag"] = "door_leaf", nid.split("@")[0]
        modes = "ext" if ext_only else ("int" if grp in INT_ONLY_GROUPS else "both")
        o["shoot_modes"] = modes
        if mk == "glass":
            o["glass_role"] = "window"
        if grp == "外付けスクリーン生地" and nid:                        # v4.34: 面（S/N/E/W）と完全遮光生地の別（--screens auto が使う）
            o["side"], o["blackout"] = nid.split("-")[1], mk == "zip_blackout"
        put(o, cols[collection_for(grp, lvl)])
        if ext_only:
            o.hide_render = True
            o.hide_viewport = True

    for o in meshes:
        full = full_of[o]
        cur = o.data.materials[0] if o.data.materials else None
        key = full.split("|")[2]
        em = ext_copy.get(key, ext_mat[o]) if key in ("base", "partition") else ext_mat[o]
        if cur is not None and em is not None and em != cur:
            o["mat_int"], o["mat_ext"] = cur.name, em.name
        tag_mesh(o, full, False)
    for o, full in keep:
        tag_mesh(o, full, True)
    for o in plants:
        o["kind"], o["shoot_modes"] = "plant", "both"
        put(o, cols["Site"])
    for o in trees:
        o["kind"], o["shoot_modes"] = "tree", "int"
        put(o, cols["Site"])
    # 光源
    kel = {k: v for k, v in default_cut["ch"].items()}
    for (ob, d), tag in zip(st["lights"], job["tags"]["D"]):
        ob.name = "D." + BM.ascii_name(tag)
        ob["kind"], ob["channel"], ob["tag"], ob["ifc_name"] = "light", "D", tag, tag
        ob["kelvin"], ob["lm"], ob["room"], ob["floor"] = kel["D"][0], job["downlight_lm"], d.get("room", ""), d["floor"]
        ob["light_def"] = json.dumps(d, ensure_ascii=False)
        ob["shoot_modes"] = "int"
        put(ob, cols["Lighting"])
    for e in st["lines"]:
        d, ob = e["d"], e["ob"]
        ob.name = "L." + BM.ascii_name(d["id"])
        ob["kind"], ob["channel"], ob["tag"], ob["ifc_name"] = "light", "L", d["id"], d["id"]
        ob["kelvin"], ob["lm"], ob["room"], ob["floor"] = kel["L"][0], round(d["lm_per_m"] * d["L"] / 1000), d["room"], d["floor"]
        ob["light_def"] = json.dumps(d, ensure_ascii=False)
        ob["shoot_modes"] = "int"
        put(ob, cols["Lighting"])
        mat = [m for m in bpy.data.materials if m.name == "line_" + d["id"]]
        if mat:
            mat[0].use_fake_user = True
    for e in st["foots"]:
        d, ob = e["d"], e["ob"]
        ob.name = "F." + BM.ascii_name(d["id"])
        ob["kind"], ob["channel"], ob["tag"], ob["ifc_name"] = "light", "F", d["id"], d["id"]
        ob["kelvin"], ob["lm"], ob["room"], ob["floor"] = kel["F"][0], cfg_i["interior"]["foot_lm"], d.get("stair", ""), d["floor"]
        ob["light_def"] = json.dumps(d, ensure_ascii=False)
        ob["shoot_modes"] = "int"
        put(ob, cols["Lighting"])
        mat = [m for m in bpy.data.materials if m.name == "foot_" + d["id"]]
        if mat:
            mat[0].use_fake_user = True
    if sun is not None:
        sun.name = "Sun"
        sun["kind"] = "sun"
        put(sun, cols["Lighting"])
    if glow is not None:
        glow[0].name = "room_light_glow"
        glow[0]["kind"], glow[0]["shoot_modes"] = "glow", "ext"
        glow[0].hide_render = True
        put(glow[0], cols["Lighting"])
    for i, ob in enumerate(ext_lights):
        ob.name = f"ext_light.{i:02d}"
        ob["kind"], ob["shoot_modes"] = "ext_light", "ext"
        ob.hide_render = True
        put(ob, cols["Lighting"])
    # 室・建具の Empty（IFC・CSV と同じ記号で照合できるように。形状は GLB のメッシュ）
    for r in job["rooms"]:
        e = bpy.data.objects.new("Room." + BM.ascii_name(f"{r['floor']}.{r['code']}"), None)
        e.empty_display_type, e.empty_display_size = "PLAIN_AXES", 0.3
        e.location = Vector(r["loc"])
        e["kind"], e["tag"], e["ifc_name"], e["floor"], e["shoot_modes"] = "room", f"{r['floor']}:{r['name']}", r["name"], r["floor"], "both"
        put(e, cols["Interior_" + ("2F" if r["floor"] == "2F" else "1F")])
    cnt = {}
    for o_ in job["openings"]:
        k = (o_["floor"], o_["label"])
        cnt[k] = cnt.get(k, 0) + 1
        e = bpy.data.objects.new(f"Op.{o_['floor']}.{BM.ascii_name(o_['label'])}" + (f".{cnt[k]}" if cnt[k] > 1 else ""), None)
        e.empty_display_type, e.empty_display_size = "CUBE", 0.15
        e.location = Vector(o_["loc"])
        e["kind"], e["tag"], e["ifc_name"], e["floor"], e["shoot_modes"] = "opening", o_["label"], o_["name"], o_["floor"], "both"
        e["opening_type"], e["w_mm"], e["h_mm"] = o_["kind"], o_["w"], o_["h"]
        put(e, cols["Interior_" + ("2F" if o_["floor"] == "2F" else "1F")])
    n_caps = add_section_caps(job, cols, M)
    add_cameras_all(sc, job, cols)
    # ---- Scene のプロパティ
    m = job["meta"]
    for k, v in job["scene_props"].items():
        sc[k] = v
    sc["model_version"], sc["model_hash"], sc["generated_at"], sc["git_commit"], sc["bpy_version"] = m["version"], m["model_hash"], m["generated_at"], m["git_commit"], bpy.app.version_string
    sc["texture_fallbacks"] = json.dumps(sorted(set(lib.fallbacks)))
    sc["material_colors"] = json.dumps(CB.Lib.audit_log, sort_keys=True)
    sc["master_note"] = "自動生成。手で編集しない（次の build で上書き）。手編集は data/blend/kawazanyo_overlay.blend の Overlay コレクションへ。"
    sc.render.engine = "CYCLES"
    sc.render.resolution_x, sc.render.resolution_y = day["res"]
    sc.cycles.samples = day["samples"]
    sc.view_settings.exposure = day["exposure"]
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    SB.keep_materials()
    SB.record_image_means(bpy.data.images)
    sc["gen_signature"] = SB.gen_signature()
    out = Path(out)
    bpy.ops.wm.save_as_mainfile(filepath=str(out), compress=True)
    res = dict(file=out.name, seconds=round(time.time() - t0, 1), meshes=len([o for o in bpy.data.objects if o.type == "MESH"]),
               cameras=len([o for o in bpy.data.objects if o.type == "CAMERA"]), lights=len([o for o in bpy.data.objects if o.type == "LIGHT"]),
               materials=len(bpy.data.materials), objects=len(bpy.data.objects), section_caps=n_caps, fallbacks=sorted(set(lib.fallbacks)))
    return res
