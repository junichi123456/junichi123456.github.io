"""書き出し共通: 座標変換・命名・色・フラグ・階の標高。

建物ローカル（IFC・3D DXF）: mm、原点 = X1・Y1 壁芯交点、z=0 = 設計 GL、Z 上。
真北ワールド（OBJ・FBX・USDZ・.blend・GLB）: m、Y 上、-Z = 真北（model3d.build_scene と同じ）。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import yaml

VERSION = "v4.32"
PROJECT_NAME = "河沿要（仮称）"

# 材質キー・カテゴリ → 和名カテゴリ
CAT_JP = {"wall": "RC耐力壁", "partition": "間仕切壁", "parapet": "パラペット", "insul": "外断熱", "slab": "スラブ",
          "glass": "窓", "door": "扉", "stair": "階段", "footing": "基礎", "column": "柱", "mullion": "方立",
          "blind": "外付けスクリーン", "beam": "梁"}


def truenorth_dir(h):
    """建物ローカルでの北方向の単位ベクトル (x, y)。h.alpha は建物の反時計回り回転角。"""
    return (math.sin(h.alpha), math.cos(h.alpha))


def true_north_deg(h):
    """建物 +Y 軸から真北までの角度（反時計回り正、度）。"""
    return math.degrees(h.alpha)


def storeys(h):
    """[(名称, 標高 mm)]: 基礎 FDN・1F・2F・RF。"""
    return [("FDN", -float(h.base_t)), ("1F", float(h.fl["1F"])), ("2F", float(h.fl["2F"])), ("RF", float(h.fl["RF"]))]


def world_matrix(h):
    """建物ローカル m（Z 上）→ 真北ワールド m（Y 上）の 4x4。model3d.build_scene と同一。"""
    import trimesh
    rz = trimesh.transformations.rotation_matrix(h.alpha, [0, 0, 1], [h.W / 2000, h.D / 2000, 0])
    return trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]) @ rz


def local_to_enu(h, x_mm, y_mm):
    """建物ローカル mm → 局所 ENU m（site_gsi.json と同じ座標）。"""
    return h.mm2m(x_mm, y_mm)


def enu_to_lonlat(h, e, n):
    """局所 ENU m → (経度, 緯度)。origin_latlon 基準の局所近似（敷地 200m 内で誤差 1cm 未満）。"""
    lat0, lon0 = h.gsi["meta"]["origin_latlon"]
    R = 6378137.0
    dlat = n / R
    dlon = e / (R * math.cos(math.radians(lat0)))
    return (lon0 + math.degrees(dlon), lat0 + math.degrees(dlat))


def node_name(grp, lvl, key, nid=None):
    """全形式共通のオブジェクト名 グループ|階|材質キー|ID。"""
    return f"{grp}|{lvl}|{key}" + (f"|{nid}" if nid else "")


def hex_rgb(hx):
    return tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))


def mat_hex(table, key):
    return table[key]["color"]


def box_volume_m3(b):
    return (b.x1 - b.x0) * (b.y1 - b.y0) * (b.z1 - b.z0) / 1e9


def level_of(h, z):
    """絶対高さ z (mm) が属する階名（FDN/1F/2F/RF）。"""
    if z < 0:
        return "FDN"
    if z < h.fl["2F"] - 1:
        return "1F"
    if z < h.fl["RF"] - 1:
        return "2F"
    return "RF"


class Flags:
    """data/export_flags.yaml。get(tag/room/group) → dict(confirm, provisional, basis)。"""

    def __init__(self, root):
        d = yaml.safe_load((Path(root) / "data" / "export_flags.yaml").read_text(encoding="utf-8"))
        self.d = d
        self.default = d["default"]

    def _merge(self, *ents):
        out = dict(self.default)
        basis = []
        for e in ents:
            if not e:
                continue
            for k in ("confirm", "provisional"):
                out[k] = out[k] or bool(e.get(k))
            if e.get("basis"):
                basis.append(e["basis"])
        out["basis"] = "／".join(basis)
        return out

    def get(self, tag="", room="", group=""):
        rooms = [v for k, v in self.d.get("rooms", {}).items() if room and k in room]
        return self._merge(self.d.get("tags", {}).get(tag), *rooms, self.d.get("groups", {}).get(group))
