"""マスター .blend の bpy 側の共通部と撮影の実行（v4.33）。bpy の入った python で実行する。

    python shoot_blender.py inspect <job.json>   — マスター（とオーバーレイ）の属性・カメラ一覧を JSON で書く
    python shoot_blender.py shoot   <job.json>   — マスターを 1 回開き、指定カットを順に撮る
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import blend_master as BM  # noqa: E402


def log(*a):
    print("[shoot]", *a, flush=True)


# ===================================================================== 保存側（build）から使う
def keep_materials():
    """どのオブジェクトにも使われない材質（外観用ガラス・点灯面など）も保存する。"""
    for m in bpy.data.materials:
        m.use_fake_user = True


def record_image_means(images):
    """各画像の平均色（リニア）を属性に残す。撮影時に画像が無いとき、同じ平均色の単色に置き換える。"""
    import numpy as np
    for img in images:
        if img.source != "FILE" or not img.filepath:
            continue
        try:
            px = np.empty(len(img.pixels), dtype="float32")
            img.pixels.foreach_get(px)
        except Exception:                                  # noqa: BLE001
            continue
        rgb = px.reshape(-1, 4)[:, :3]
        lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        img["mean_lin"] = json.dumps([float(v) for v in lin.mean(axis=0)])


def gen_signature():
    """オブジェクト名・頂点数・材質名・カメラ定義のハッシュ（手で保存し直したマスターを検出する）。ライブラリ（オーバーレイ）のものは除く。"""
    items = []
    for o in sorted(bpy.data.objects, key=lambda o: o.name):
        if o.library:
            continue
        if o.type == "MESH":
            items.append([o.name, len(o.data.vertices)])
        elif o.type == "CAMERA":
            items.append([o.name, round(o.location.x, 4), round(o.location.y, 4), round(o.location.z, 4), round(o.data.lens, 3), round(o.data.shift_y, 4)])
        else:
            items.append([o.name])
    mats = sorted(m.name for m in bpy.data.materials if not m.library)
    return hashlib.sha1(json.dumps([items, mats], ensure_ascii=False).encode()).hexdigest()


# ===================================================================== 開く・オーバーレイ・検査
def link_overlay(overlay_path):
    """オーバーレイの Overlay コレクションだけをライブラリリンクで入れる。戻り値: 入れたコレクション or None。"""
    if not overlay_path or not Path(overlay_path).exists():
        return None
    with bpy.data.libraries.load(str(overlay_path), link=True) as (src, dst):
        if "Overlay" not in src.collections:
            return None
        dst.collections = ["Overlay"]
    coll = dst.collections[0]
    sc = bpy.context.scene
    ov = bpy.data.collections.get("Overlay")
    if ov is not None and ov.library is None:                # マスターの空の Overlay コレクションに、リンク先のコレクションを子として入れる
        ov.children.link(coll)
    else:
        sc.collection.children.link(coll)
    return coll


def inspect(job):
    bpy.ops.wm.open_mainfile(filepath=str(job["master"]), load_ui=False)
    sc = bpy.context.scene
    props = {k: sc[k] for k in sc.keys() if isinstance(sc[k], (str, int, float))}
    props["gen_signature_now"] = gen_signature()
    props["unit"] = sc.unit_settings.system
    cams = []
    ov_coll = link_overlay(job.get("overlay")) if not job.get("no_overlay") else None
    ov_objs = set(ov_coll.all_objects) if ov_coll else set()
    for o in sorted(bpy.data.objects, key=lambda o: o.name):
        if o.type != "CAMERA":
            continue
        w = o.matrix_world
        fwd = (w.to_quaternion() @ Vector((0, 0, -1)))
        p = {k: (o[k] if isinstance(o[k], (str, int, float)) else str(o[k])) for k in o.keys()}
        cams.append(dict(name=o.name, props=p, loc=list(w.translation), fwd=list(fwd), lens=o.data.lens, shift_x=o.data.shift_x, shift_y=o.data.shift_y,
                         overlay=o in ov_objs, library=bool(o.library)))
    n_obj = len([o for o in bpy.data.objects if not o.library])
    return dict(props=props, cameras=cams, overlay=bool(ov_coll), objects=n_obj, images_packed=len([i for i in bpy.data.images if i.packed_file]))


# ===================================================================== 撮影
class LibShim:
    """CB.Lib の代わり（configure_cut・render_* が使う属性だけ）。"""

    def __init__(self, fallbacks):
        self.mats = {m.name: m for m in bpy.data.materials if not m.library}
        self.fallbacks = fallbacks
        self.lamp_nodes = [n for m in self.mats.values() if m.node_tree for n in m.node_tree.nodes if n.name.startswith("LampStrength")]
        lf = self.mats.get("lamp_face")
        self.int_lamp = None
        if lf is not None:
            P = next(n for n in lf.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bb = next(n for n in lf.node_tree.nodes if n.type == "BLACKBODY")
            self.int_lamp = (P, bb)
        sm = self.mats.get("screen")
        self.int_screen = next(n for n in sm.node_tree.nodes if n.type == "BSDF_PRINCIPLED") if sm is not None else None


def restore_state(CB, CI, cfg, sc, M):
    """prepare() が作った状態（扉・生地・器具・光源のリスト）を、マスターのオブジェクトから復元する。"""
    off = bpy.data.materials.get("lamp_face_off")
    st = dict(doors={}, fabrics=[], fixtures=[], screen_objs=[], lights=[], lamp_off=off, line_objs={}, foot_objs={}, lines=[], foots=[])
    for o in bpy.data.objects:
        if o.library or o.type != "MESH" or "glb_name" not in o:
            continue
        parts = o["glb_name"].split("|")
        grp = parts[0]
        if grp == "扉" and len(parts) > 3:
            st["doors"].setdefault(parts[3], []).append(o)
        elif grp == "外付けスクリーン生地":
            st["fabrics"].append(o)
        elif grp == "照明器具" and parts[2] == "lamp_face":
            st["fixtures"].append((o, parts[1]))
        elif grp == "家具" and parts[2] == "screen":
            st["screen_objs"].append(o)
    wd = cfg["interior"]["line_w_mm"] / 1000.0 - 0.008
    for o in sorted(bpy.data.objects, key=lambda o: o.name):
        if o.library or o.type != "LIGHT" or o.get("kind") != "light":
            continue
        d = json.loads(o["light_def"])
        ch = o["channel"]
        if ch == "D":
            st["lights"].append((o, d))
        else:
            mname = ("line_" if ch == "L" else "foot_") + d["id"]
            mat = bpy.data.materials.get(mname)
            if mat is None:
                mat, sI, tI = CI.cam_only_emission(mname, 1.0, 4000.0)
                sock_s, sock_t = sI, tI
            else:
                em = next(n for n in mat.node_tree.nodes if n.type == "EMISSION")
                bb = next(n for n in mat.node_tree.nodes if n.type == "BLACKBODY")
                sock_s, sock_t = em.inputs["Strength"], bb.inputs["Temperature"]
            if ch == "L":
                st["lines"].append(dict(ob=o, d=d, strength=sock_s, kelvin=sock_t, area=(d["L"] / 1000.0) * wd))
            else:
                st["foots"].append(dict(ob=o, d=d, strength=sock_s, kelvin=sock_t))
    return st


def fix_textures(tex_dir, fallbacks):
    """画像の置き場を張り替え（既定 .cache/cg）、無い画像は同じ平均色の単色に置き換える。"""
    import numpy as np
    tex_dir = Path(tex_dir)
    missing = []
    for img in list(bpy.data.images):
        if img.source != "FILE" or img.library:
            continue
        fp = Path(bpy.path.abspath(img.filepath))
        cand = tex_dir / fp.name
        if cand.exists():
            if str(cand) != str(fp):
                img.filepath = str(cand)
                img.reload()
            continue
        if fp.exists():
            continue
        mean = json.loads(img["mean_lin"]) if "mean_lin" in img else [0.5, 0.5, 0.5]
        enc = [c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055 for c in mean]
        img.source = "GENERATED"
        img.generated_width = img.generated_height = 4
        img.generated_color = (*enc, 1.0)
        missing.append(fp.name)
    if missing:
        fallbacks.extend(n for n in missing if n not in fallbacks)
    return missing


def set_mode(mode, mats):
    """外観（ext）・内装（int）で、見せる物・材質（ガラス・天井・壁の保険マスク）を切り替える。"""
    for o in bpy.data.objects:
        if o.library or o.type == "CAMERA":
            continue
        m = o.get("shoot_modes", "both")
        if m != "both":
            o.hide_render = (m == "int" and mode == "ext") or (m == "ext" and mode == "int")
        key = "mat_ext" if mode == "ext" else "mat_int"
        if key in o and o.type == "MESH":
            mt = mats.get(o[key])
            if mt is not None:
                o.data.materials.clear()
                o.data.materials.append(mt)


def apply_hidden(overlay_coll):
    """オーバーレイの属性 hide_master（GLB 名 or タグの JSON リスト）で、マスターの要素を非表示にする。"""
    if overlay_coll is None:
        return 0
    raw = overlay_coll.get("hide_master")
    if not raw:
        return 0
    names = set(json.loads(raw)) if isinstance(raw, str) else set(raw)
    n = 0
    for o in bpy.data.objects:
        if o.library:
            continue
        if o.get("glb_name") in names or o.get("tag") in names or o.name in names:
            o.hide_render = True
            n += 1
    return n


def shoot(job):
    import cg_blender as CB
    import cg_interior as CI
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=str(job["master"]), load_ui=False)
    bpy.context.preferences.filepaths.save_version = 0
    sc = bpy.context.scene
    sig_now = gen_signature()
    ov = link_overlay(job.get("overlay")) if not job.get("no_overlay") else None
    fallbacks = []
    missing = fix_textures(job["tex_dir"], fallbacks)
    mats = {m.name: m for m in bpy.data.materials if not m.library}
    for o in [o for o in bpy.data.objects if o.name == "Sun" and not o.library]:
        bpy.data.objects.remove(o)                        # 太陽は撮影時に設定する（GUI で開いたときだけ保存時の値が見える）
    hidden = apply_hidden(ov)
    CB.Lib.audit_log.update(json.loads(sc["material_colors"]))
    lib = LibShim(fallbacks)
    state = {}
    results, failed = [], []
    raw_path = Path(job["raw_log"])
    glow_ob = next((o for o in bpy.data.objects if o.get("kind") == "glow" and not o.library), None)
    glow = None
    ext_lights = [o for o in bpy.data.objects if o.get("kind") == "ext_light" and not o.library]
    sc.cycles.seed = int(job.get("seed", 0))
    sc.cycles.use_animated_seed = False
    cur_mode = None
    stI = None
    log("master opened", round(time.time() - t0, 1), "s; overlay:", bool(ov), "hidden:", hidden, "missing textures:", missing)
    for fam in job["cfgs"]:
        cfg = json.loads(Path(fam["cfg"]).read_text(encoding="utf-8"))
        interior = cfg.get("mode") == "interior"
        mode = "int" if interior else "ext"
        M = Matrix.Translation((cfg["pivot"][0], cfg["pivot"][1], 0)) @ Matrix.Rotation(cfg["alpha"], 4, "Z") @ Matrix.Translation((-cfg["pivot"][0], -cfg["pivot"][1], 0))
        if cur_mode != mode:
            set_mode(mode, mats)
            cur_mode = mode
        if interior and stI is None:
            stI = restore_state(CB, CI, cfg, sc, M)
        if not interior and glow_ob is not None:
            P = next(n for n in glow_ob.data.materials[0].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bb = next(n for n in glow_ob.data.materials[0].node_tree.nodes if n.type == "BLACKBODY")
            bb.inputs["Temperature"].default_value = float(cfg["room_light"]["kelvin"])
            glow = (glow_ob, P)
        for cut in cfg["cuts"]:
            if job.get("only") and cut["id"] not in job["only"]:
                continue
            log("render", cut["id"], cut["res"], cut["samples"], "spp, limit", cut["time_limit"], "s")
            try:
                if interior:
                    r = CI.render_interior_cut(CB, sc, cut, cfg, lib, stI, state, M)
                else:
                    sc.view_settings.use_white_balance = False         # 内装カットの設定（ホワイトバランス・間接光のクランプ）を外観に持ち込まない
                    sc.cycles.sample_clamp_indirect = 0.0
                    r = CB.render_cut(sc, cut, cfg, lib, state, glow, ext_lights, False)
                r["texture_fallbacks"] = list(fallbacks)
                r["family"] = fam["family"]
                results.append(r)
            except Exception as e:                       # noqa: BLE001
                import traceback
                traceback.print_exc()
                failed.append(dict(id=cut["id"], error=f"{type(e).__name__}: {e}"))
            raw_path.write_text(json.dumps(dict(setup_seconds=round(time.time() - t0, 1), cuts=results, failed=failed, material_colors=CB.Lib.audit_log,
                                                gen_signature_now=sig_now, texture_missing=missing, overlay=bool(ov)), ensure_ascii=False, indent=1), encoding="utf-8")
    log("all done", round(time.time() - t0, 1), "s")


def main():
    cmd, jp = sys.argv[1], sys.argv[2]
    job = json.loads(Path(jp).read_text(encoding="utf-8"))
    if cmd == "inspect":
        Path(job["result"]).write_text(json.dumps(inspect(job), ensure_ascii=False), encoding="utf-8")
    elif cmd == "shoot":
        shoot(job)


if __name__ == "__main__":
    main()
