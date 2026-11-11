"""マスター .blend まわりの共通部（bpy 不要。システムの python3 で動く）。v4.33

マスター .blend（dist/export/kawazanyo_master.blend）は build が自動生成する。手で編集しない。施主の手編集はオーバーレイ
（data/blend/kawazanyo_overlay.blend の Overlay コレクション）に入れる。撮影は src/shoot.py。
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = Path(os.environ.get("KAWAZANYO_MASTER") or ROOT / "dist" / "export" / "kawazanyo_master.blend")
OVERLAY = Path(os.environ.get("KAWAZANYO_OVERLAY") or ROOT / "data" / "blend" / "kawazanyo_overlay.blend")
CACHE = ROOT / ".cache" / "cg"
SHOOT_CACHE = CACHE / "shoot"

# マスターの形状・材質・照明・カット定義に関わるファイル（model_hash の入力）
HASH_SRC = ["house.py", "geom.py", "model3d.py", "furniture.py", "furniture_shapes.py", "interior_shell.py", "interior.py", "lighting.py",
            "cg_blender.py", "cg_interior.py", "master_build.py", "blend_master.py"]
# カット設定を作る関数（render_*.py のうち、マスターの内容に効く関数だけ。ラッパー側の変更ではマスターを古いとしない）
HASH_FUNCS = [("render_cg", ["build_cfg", "sun_position", "lamp_schedule", "Frame", "eye_z"]), ("render_interior", ["interior_cfg", "scenery_cfg", "RC_planters"]),
              ("render_zones", ["cut_defs", "def_hash"])]


def model_hash(root: Path = ROOT) -> str:
    h = hashlib.sha256()
    files = [root / "spec.yaml"] + sorted((root / "data").glob("*.yaml")) + [root / "src" / s for s in HASH_SRC]
    for p in files:
        if p.exists():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    import importlib
    import inspect
    sys.path.insert(0, str(root / "src"))
    for mod, names in HASH_FUNCS:
        m = importlib.import_module(mod)
        for n in names:
            h.update(inspect.getsource(getattr(m, n)).encode())
    return h.hexdigest()


def git_commit(root: Path = ROOT) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:                                    # noqa: BLE001
        return "unknown"


def bpy_python():
    for p in (os.environ.get("BPY_PYTHON"), str(ROOT / ".venv-bpy" / "bin" / "python")):
        if p and Path(p).exists():
            return p
    return None


def tex_dir(override=None) -> Path:
    return Path(override or os.environ.get("KAWAZANYO_TEX") or CACHE)


def cut_hash(s: dict) -> str:
    """render_zones.def_hash と同じ式（カット定義のうち画に効く項目）。"""
    key = json.dumps([s["cam"], s["target"], s["lens"], s.get("exposure", 0.0), s["when"], s.get("open_doors", {}), s.get("also_1f", False),
                      s.get("shift_y", 0.0), s.get("wb", 5000)], sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def cut_families(h, Z):
    """全カット {id: dict(family, kind, floor, spec, title, hash, extra)}。family: C（外観）・I（内装）・Z（ゾーン）。"""
    import render_zones as RZ
    out = {}
    for cid, c in h.spec["cg"]["cuts"].items():
        s = dict(c)
        z = s["cam"][2]
        floor = "-"
        out[cid] = dict(family="C", kind="ext", floor=floor, spec=s, title=s["title"], extra={})
    for cid, c in h.spec["interior_cg"]["cuts"].items():
        s = dict(c)
        out[cid] = dict(family="I", kind="int", floor="2F" if s["cam"][2] > h.fl["2F"] else "1F", spec=s, title=s["title"], extra={})
    for cid, d in RZ.cut_defs(h, Z).items():
        s = dict(d["spec"])
        out[cid] = dict(family="Z", kind="int", floor=d["floor"], spec=s, title=s["title"], extra=dict(theater=d["theater"], room=d["room"], dir=d["dir"], slug=d["slug"], direct=d["direct"]))
    for cid, e in out.items():
        s = dict(e["spec"])
        if s["cam"][2] == "eye":
            s["cam"] = [*s["cam"][:2], 0]
        e["hash"] = cut_hash(s)
    return out


def opening_items(h):
    """openings.csv（export/tables.sheet_openings）と同じ集合: 建具 1 つずつ。"""
    out = []
    for w in h.walls:
        if w.cat == "insul":
            continue
        for op in w.openings:
            if op.operation == "opening":
                continue
            um = (op.u0 + op.u1) / 2
            x, y = (um, w.c) if w.axis == "x" else (w.c, um)
            out.append(dict(label=op.label, kind="window" if op.kind == "window" else "door", floor=op.floor, x=x, y=y, z=(op.z0 + op.z1) / 2,
                            w=op.width, h=op.height, side=op.side, name=op.name))
    return out


def ascii_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.@-]+", "_", s)


def glb_node_names(path):
    """GLB のメッシュ付きノード名（Blender の取り込みは名前を 63 バイトで切るため、完全名は GLB から読む）。"""
    import struct
    b = Path(path).read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n].decode("utf-8"))
    return [nd["name"] for nd in j["nodes"] if "mesh" in nd]


def resolve_name(raw, full_names, taken=()):
    """Blender のオブジェクト名（切れた名前・.001 付き）→ GLB の完全名。"""
    full = full_names if isinstance(full_names, (set, frozenset, dict)) else set(full_names)
    if raw in full and raw not in taken:
        return raw
    r2 = re.sub(r"\.\d+$", "", raw)
    if r2 in full and r2 not in taken:
        return r2
    b = r2.encode("utf-8")
    cut = b.decode("utf-8", "ignore")
    cand = [f for f in sorted(full) if f.startswith(cut[:-1] if len(cut) < len(r2) else cut) and f not in taken]
    if not cand:
        cand = [f for f in sorted(full) if f.startswith(cut[:-1]) and f not in taken]
    return cand[0] if cand else raw


def master_job(h, tmp, with_textures=True):
    """マスター生成の入力（render_cg／render_interior／render_zones と同じ関数で作った設定と、全 57 カメラの定義）。"""
    import yaml
    import furniture as FU
    import lighting as LI
    import render_cg as RC
    import render_interior as RI
    import render_zones as RZ
    from model3d import export_glb  # noqa: F401
    spec = h.spec
    ic = spec["interior_cg"]
    tex_e = dict(spec["cg"]["textures"])
    tex_i = {**tex_e, **ic["textures"]}
    full = RC.fetch_assets({"cg": {"textures": tex_i, "hdri": spec["cg"]["hdri"]}}, CACHE, use_textures=with_textures)
    as_e = dict(textures={k: full["textures"][k] for k in tex_e}, hdri=full["hdri"], source=full["source"])
    ns = types.SimpleNamespace(only=None, preview=False, size=None, samples=None, scene_only=False, no_glb=True)
    out = Path(tmp)
    cfg_e = RC.build_cfg(h, spec, ns, as_e, out)
    Z = RZ.load()
    fam = cut_families(h, Z)
    # 内装: I カット（spec.interior_cg）と Z カット（data/interior_zones.yaml）を 1 つの設定にまとめる
    glb_i = ROOT / "dist" / "model_interior.glb"
    cfg_i, its = RI.interior_cfg(h, spec, ns, full, out, glb_i)
    sp = copy.deepcopy(spec)
    sp["interior_cg"]["cuts"] = {cid: {**e["spec"], "file": cid} for cid, e in fam.items() if e["family"] == "Z"}
    sp["interior_cg"]["resolution"] = list(Z["settings"]["resolution"])
    cfg_z, _ = RI.interior_cfg(h, sp, ns, full, out, glb_i)
    cfg_i["cuts"] = cfg_i["cuts"] + cfg_z["cuts"]
    cfg_e["glb"] = str(ROOT / "dist" / "model.glb")
    cfg_e["raw_log"] = cfg_i["raw_log"] = str(out / "raw.json")
    fr = RC.Frame(h)
    ecut = {c["id"]: c for c in cfg_e["cuts"]}
    icut = {c["id"]: c for c in cfg_i["cuts"]}
    cams = []
    for cid, e in fam.items():
        c = ecut[cid] if e["kind"] == "ext" else icut[cid]
        zmm = c["cam_mm"][2]
        floor = e["floor"]
        d = dict(kind=e["kind"], floor=floor, family=e["family"], title=e["title"], when=c["when"], lens=c["lens"], exposure=c["exposure"],
                 target=json.dumps(e["spec"]["target"]), def_hash=e["hash"], file=e["spec"]["file"], exclude=json.dumps(["Furniture", "Lighting"] if e["kind"] == "ext" else []),
                 cut_spec=json.dumps(e["spec"], ensure_ascii=False))
        if e["kind"] == "int":
            d.update(fl_mm=h.fl[floor], eye_mm=round(zmm - h.fl[floor]), shift_y=c.get("shift_y", 0.0), wb=c["wb"], lamp_k=c["lamp_k"], lamp_pct=c["lamp_pct"],
                     channels=json.dumps(c["ch"]), open_doors=json.dumps(c.get("open_doors", {})), also_1f=bool(e["spec"].get("also_1f")),
                     theater=bool(e["extra"].get("theater")) or cid == "I07", hfov=round(math.degrees(2 * math.atan(18.0 / c["lens"])), 1))
            if c.get("pitch") is not None:
                d["pitch"] = c["pitch"]
        else:
            d.update(eye_mm=round(zmm), hfov=round(math.degrees(2 * math.atan(18.0 / c["lens"])), 1))
        cams.append(dict(id=cid, family=e["family"], kind=e["kind"], props=d, cut=c))
    lns = LI.lines(h, its)
    tags_d = [f"{d['floor']}-{d['code']}-D{i}" for i, d in enumerate(LI.downlights(h, its, lns), 1)]
    rooms = [dict(floor=r.floor, name=r.name, code=LI.room_code(h, r), loc=fr.to_bl((r.rect[0] + r.rect[2]) / 2, (r.rect[1] + r.rect[3]) / 2, h.fl[r.floor] if r.floor in h.fl else 0)) for r in h.rooms]
    ops = [dict(label=o["label"], kind=o["kind"], floor=o["floor"], name=o["name"], w=round(o["w"]), h=round(o["h"]), loc=fr.to_bl(o["x"], o["y"], o["z"])) for o in opening_items(h)]
    st = Z["settings"]
    cg = spec["cg"]
    scene_props = dict(sun_date=st["when"][5:10], sun_time=st["when"][11:16], lat=cg["site"]["lat"], lon=cg["site"]["lon"], tz=cg["site"]["tz"],
                       true_north_deg=round(math.degrees(h.alpha) * -1, 2), hdri_id=cg["hdri"]["day"], hdri_rot_deg=0.0, hdri_strength=1.0,
                       light_schedule=json.dumps(spec["smart"]["lighting_schedule"]), light_channels=json.dumps(spec["lighting"]["channels"]))
    from export.common import VERSION
    meta = dict(version=VERSION, model_hash=model_hash(), generated_at=dt.datetime.now().isoformat(timespec="seconds"), git_commit=git_commit())
    return dict(cfg_int=cfg_i, cfg_ext=cfg_e, glb_ext=cfg_e["glb"], cams=cams, tags=dict(D=tags_d), rooms=rooms, openings=ops, meta=meta, scene_props=scene_props,
                furn_names={it.id: it.name for it in its}, downlight_lm=spec["lighting"]["downlight"]["max_lm"])
