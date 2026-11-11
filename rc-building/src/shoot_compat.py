"""旧スクリプト（render_cg.py・render_interior.py・render_zones.py）の引数を src/shoot.py の引数に読み替える（v4.33）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))


def regen_master():
    """--regen-glb: GLB とマスター .blend を再生成する（build.py --blend-only）。"""
    r = subprocess.run([sys.executable, str(ROOT / "src" / "build.py"), "--blend-only"])
    return r.returncode


def run(default_cameras, args, extra=None):
    """args: 旧スクリプトの argparse.Namespace（only・preview・samples・size・force・floor・regen_glb を使う）。default_cameras: --only が無いときのカメラ（ワイルドカード）。"""
    import shoot
    if getattr(args, "regen_glb", False):
        rc = regen_master()
        if rc != 0:
            return rc
    only = getattr(args, "only", None)
    cams = ",".join(sorted(only)) if only else default_cameras
    av = ["--camera", cams]
    if getattr(args, "preview", False):
        av.append("--preview")
    if getattr(args, "samples", 0):
        av += ["--samples", str(args.samples)]
    if getattr(args, "size", ""):
        w, h = args.size.lower().split("x")
        av += ["--res", w, h]
    if getattr(args, "force", False):
        av.append("--force")
    if getattr(args, "time_limit", None) is not None:
        av += ["--time-limit", str(args.time_limit)]
    av += list(extra or [])
    print("マスター .blend から撮影します（旧経路は --legacy）: shoot.py", " ".join(av))
    return shoot.main(av)
