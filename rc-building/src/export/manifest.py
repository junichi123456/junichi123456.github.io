"""dist/export/manifest.json（ファイル名・形式・サイズ・sha256・版・座標系）。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .common import VERSION

COORD_LOCAL = "建物ローカル（原点=X1・Y1 壁芯交点、z=0=設計GL、mm、Z上）"
COORD_WORLD = "真北ワールド（建物中心まわりに回転、m、Y上、-Z=真北、+X=東）"
COORD_ENU = "WGS84 経緯度（局所 ENU 近似）"
COORD_NONE = "座標なし（表）"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Manifest:
    def __init__(self, outdir, merge=False):
        """merge=True: 一部の形式だけ作り直すとき、既存の manifest.json の他の形式の項目を残す（--blend-only）。"""
        self.outdir = Path(outdir)
        self.files = []
        self.skipped = []
        self.merge = merge

    def add(self, path, fmt, coord, note=""):
        path = Path(path)
        self.files.append(dict(file=path.relative_to(self.outdir).as_posix(), format=fmt, size=path.stat().st_size,
                               sha256=sha256(path), version=VERSION, coordinates=coord, note=note))

    def skip(self, fmt, reason):
        self.skipped.append(dict(format=fmt, reason=reason))
        print(f"export: {fmt} をスキップ（{reason}）")

    def total_size(self):
        return sum(f["size"] for f in self.files)

    def write(self):
        p = self.outdir / "manifest.json"
        if self.merge and p.exists():
            old = json.loads(p.read_text(encoding="utf-8"))
            new = {f["file"] for f in self.files}
            self.files = [f for f in old.get("files", []) if f["file"] not in new and (self.outdir / f["file"]).exists()] + self.files
        p.write_text(json.dumps(dict(version=VERSION, total_bytes=self.total_size(), files=self.files, skipped=self.skipped),
                                ensure_ascii=False, indent=1), encoding="utf-8")
        return p
