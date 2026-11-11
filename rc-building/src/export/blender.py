"""bpy 系（.blend・FBX・USDZ）の起動役。bpy の入った python（.venv-bpy または環境変数 BPY_PYTHON）があるときだけ実行する。"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

from .manifest import COORD_WORLD

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


def find_python():
    for p in (os.environ.get("BPY_PYTHON"), str(ROOT / ".venv-bpy" / "bin" / "python")):
        if p and Path(p).exists():
            return p
    return None


def make_cfgs(h, tmp):
    """render_cg／render_interior／render_zones と同じ関数で設定を作る（テクスチャ・HDRI なし = 持ち運べる .blend にする）。"""
    import render_cg as RC
    import render_interior as RI
    import render_zones as RZ
    spec = h.spec
    none_tex = {k: dict(asset=v, diff=None, status="skipped") for k, v in spec["cg"]["textures"].items()}
    tex_i = {**none_tex, **{k: dict(asset=v, diff=None, status="skipped") for k, v in spec["interior_cg"]["textures"].items()}}
    hd = {k: dict(asset=v, path=None, status="skipped") for k, v in spec["cg"]["hdri"].items()}
    ns = types.SimpleNamespace(only=None, preview=False, size=None, samples=None, scene_only=False, no_glb=True)
    out = Path(tmp)
    cfg_e = RC.build_cfg(h, spec, ns, dict(textures=none_tex, hdri=hd, source="none"), out)
    Z = RZ.load()
    defs = RZ.cut_defs(h, Z)
    sp = copy.deepcopy(spec)
    ic = sp["interior_cg"]
    ic["cuts"] = {}
    for cid, d in defs.items():
        s = dict(d["spec"])
        s["file"] = cid
        ic["cuts"][cid] = s
    cfg_i, _its = RI.interior_cfg(h, sp, ns, dict(textures=tex_i, hdri=hd, source="none"), out, ROOT / "dist" / "model_interior.glb")
    cfg_e["glb"] = str(ROOT / "dist" / "model.glb")
    cfg_e["raw_log"] = cfg_i["raw_log"] = str(out / "raw.json")
    pe, pi = out / "ext.json", out / "int.json"
    pe.write_text(json.dumps(cfg_e, ensure_ascii=False), encoding="utf-8")
    pi.write_text(json.dumps(cfg_i, ensure_ascii=False), encoding="utf-8")
    return pe, pi, len(cfg_e["cuts"]), len(cfg_i["cuts"])


def write_master(h, outdir, mf, timeout=900):
    """マスター .blend（kawazanyo_master.blend）を作る。失敗・bpy なしのときは旧ファイルを残して manifest に記録（build は止めない）。"""
    outdir = Path(outdir)
    py = find_python()
    if not py:
        mf.skip("master.blend", "bpy の入った python が無い（.venv-bpy または BPY_PYTHON）")
        return None
    dst = outdir / "kawazanyo_master.blend"
    tmpb = outdir / "_master_tmp.blend"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            import blend_master as BM
            job = BM.master_job(h, tmp)
            jp, rp = Path(tmp) / "master_job.json", Path(tmp) / "master_result.json"
            jp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([py, str(ROOT / "src" / "export_blender.py"), "master", str(jp), str(tmpb), str(rp)], capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0 or not tmpb.exists():
                raise RuntimeError(r.stderr[-400:] or r.stdout[-400:])
            res = json.loads(rp.read_text(encoding="utf-8"))
        size = tmpb.stat().st_size
        if size > 15e6:
            raise RuntimeError(f"マスター .blend が {size / 1e6:.1f}MB（15MB 超）")
        if size > 10e6:
            print(f"警告: マスター .blend が {size / 1e6:.1f}MB（目標 10MB 以下）")
        tmpb.replace(dst)
    except Exception as e:                       # noqa: BLE001
        tmpb.unlink(missing_ok=True)
        import traceback; traceback.print_exc()
        mf.skip("master.blend", f"生成に失敗（旧ファイルを残す）: {type(e).__name__}: {str(e)[:300]}")
        if dst.exists():
            mf.add(dst, "Blender master .blend", COORD_WORLD, note="旧ファイル（今回の生成は失敗）")
        return None
    mf.add(dst, "Blender master .blend", COORD_WORLD, note=f"カメラ{res['cameras']}・材質{res['materials']}・オブジェクト{res['objects']}・撮影は src/shoot.py（手で編集しない）")
    return res


def write(h, outdir, mf, only=None, timeout=3600):
    outdir = Path(outdir)
    py = find_python()
    if not py:
        mf.skip("blend/FBX/USDZ", "bpy の入った python が無い（.venv-bpy または BPY_PYTHON）")
        return
    write_master(h, outdir, mf)
    with tempfile.TemporaryDirectory() as tmp:
        pe, pi, ne, ni = make_cfgs(h, tmp)
        cmd = [py, str(ROOT / "src" / "export_blender.py"), str(pe), str(pi), str(outdir)]
        if only:
            cmd += ["--only", ",".join(only)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        mf.skip("blend/FBX/USDZ", f"bpy 工程が失敗: {r.stderr[-300:]}")
        return
    res = json.loads((outdir / "_blender_result.json").read_text(encoding="utf-8"))
    (outdir / "_blender_result.json").unlink()
    notes = {"kawazanyo_exterior.blend": f"カメラ{ne}", "kawazanyo_interior.blend": f"カメラ{ni}"}
    for p in [q for q in sorted(outdir.glob("*.blend")) if q.name != "kawazanyo_master.blend"] + sorted(outdir.glob("*.fbx")) + sorted(outdir.glob("*.usdz")):
        mf.add(p, {".blend": "Blender .blend", ".fbx": "FBX", ".usdz": "USDZ"}[p.suffix], COORD_WORLD, note=notes.get(p.name, ""))
