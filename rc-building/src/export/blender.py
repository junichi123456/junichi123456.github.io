"""bpy 系（.blend・FBX・USDZ）の起動役。bpy の入った python（.venv-bpy または環境変数 BPY_PYTHON）があるときだけ実行する。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .manifest import COORD_WORLD, sha256

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


def find_python():
    for p in (os.environ.get("BPY_PYTHON"), str(ROOT / ".venv-bpy" / "bin" / "python")):
        if p and Path(p).exists():
            return p
    return None


def write_master(h, outdir, mf, timeout=900, force=False):
    """マスター .blend（kawazanyo_master.blend）を作る。失敗・bpy なしのときは旧ファイルを残して manifest に記録（build は止めない）。"""
    outdir = Path(outdir)
    py = find_python()
    if not py:
        mf.skip("master.blend", "bpy の入った python が無い（.venv-bpy または BPY_PYTHON）")
        return None
    dst = outdir / "kawazanyo_master.blend"
    tmpb = outdir / "_master_tmp.blend"
    import blend_master as BM
    cur = BM.model_hash()
    mp = outdir / "manifest.json"
    if dst.exists() and not force and mp.exists():                # 入力（model_hash）が同じなら作り直さない（--blend-only で強制）
        old = next((f for f in json.loads(mp.read_text(encoding="utf-8")).get("files", []) if f["file"] == dst.name), None)
        if old and f"model_hash={cur}" in old.get("note", ""):
            mf.add(dst, "Blender master .blend", COORD_WORLD, note=old["note"])
            print("export: master .blend は最新（model_hash 一致）のため再生成しない（--blend-only で強制）")
            return dict(reused=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
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
    mf.add(dst, "Blender master .blend", COORD_WORLD, note=f"カメラ{res['cameras']}・材質{res['materials']}・オブジェクト{res['objects']}・撮影は src/shoot.py（手で編集しない）・model_hash={cur}")
    return res


def write(h, outdir, mf, only=None, timeout=3600, force=False):
    """マスター .blend（kawazanyo_master.blend）と、GLB から FBX・USDZ を書く。bpy の入った python が無ければ skip を記録して終わる。"""
    outdir = Path(outdir)
    py = find_python()
    if not py:
        mf.skip("blend/FBX/USDZ", "bpy の入った python が無い（.venv-bpy または BPY_PYTHON）")
        return
    write_master(h, outdir, mf, force=force)
    for old in ("kawazanyo_exterior.blend", "kawazanyo_interior.blend"):        # v4.33: マスター 1 本に置き換えた
        (outdir / old).unlink(missing_ok=True)
    # FBX・USDZ は GLB から作る。書き出しは時刻を含みバイト列が一定でないため、元の GLB（sha256）が前回と同じなら作り直さない（--blend-only で強制）
    srcs = {"model_exterior.fbx": "model.glb", "model_interior.fbx": "model_interior.glb", "model_exterior.usdz": "model.glb"}
    mp = outdir / "manifest.json"
    old = {f["file"]: f.get("note", "") for f in json.loads(mp.read_text(encoding="utf-8")).get("files", [])} if mp.exists() else {}
    sha = {g: sha256(ROOT / "dist" / g) for g in set(srcs.values())}
    fresh = all((outdir / f).exists() and f"glb_sha256={sha[g]}" in old.get(f, "") for f, g in srcs.items())
    if force or only or not fresh:
        cmd = [py, str(ROOT / "src" / "export_blender.py"), "conv", str(outdir)]
        if only:
            cmd += ["--only", ",".join(only)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            mf.skip("FBX/USDZ", f"bpy 工程が失敗: {r.stderr[-300:]}")
            return
        (outdir / "_blender_result.json").unlink(missing_ok=True)
    for f, g in srcs.items():
        if (outdir / f).exists():
            mf.add(outdir / f, {".fbx": "FBX", ".usdz": "USDZ"}[Path(f).suffix], COORD_WORLD, note=f"glb_sha256={sha[g]}")
