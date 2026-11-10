"""GeoJSON（RFC 7946、WGS84）と KML の書き出し（QGIS・geojson.io・Google Earth）。

建物ローカル mm → 局所 ENU m（House.mm2m）→ 経緯度（origin_latlon 基準の局所近似。敷地 200m 内で誤差 1cm 未満）。
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from shapely.geometry import LineString, MultiPolygon, Polygon, box as sbox

import model3d as M

from . import common as C
from .manifest import COORD_ENU


def _ring(h, coords):
    return [[round(v, 9) for v in C.enu_to_lonlat(h, *h.mm2m(x, y))] for x, y in coords]


def _poly_coords(h, p):
    """GeoJSON の Polygon 座標（外周は反時計回り、穴は時計回り = RFC 7946）。"""
    p = Polygon(p.exterior, p.interiors)
    from shapely.geometry.polygon import orient
    p = orient(p, 1.0)
    return [_ring(h, p.exterior.coords)] + [_ring(h, i.coords) for i in p.interiors]


def features(h):
    """[(区分, 名称, shapely 図形 (建物 mm), props, KML 色 'rrggbb')]。"""
    F = C.Flags(h.root)
    gl = h.gl_tp
    out = []

    def add(kind, name, geom, color, grp=None, area=True, **extra):
        fl = F.get(group=grp or kind)
        props = dict(区分=kind, 名称=name, 要確認=bool(fl["confirm"]), 仮置き=bool(fl["provisional"]), 根拠=fl["basis"], **extra)
        if area and geom.geom_type in ("Polygon", "MultiPolygon"):
            props["面積m2"] = round(geom.area / 1e6, 2)
        if geom.geom_type == "LineString":
            props["長さm"] = round(geom.length / 1000, 2)
        out.append((kind, name, geom, props, color))

    add("敷地", "新敷地境界（塀の外面）", h.site, "2f5b4f", 標高TP_m=gl, 備考="新境界 2,426.42 m2（地図からの推定 ±5%）")
    add("敷地", "旧敷地境界（寄付地を含む）", h.site_gross, "c0392b", 標高TP_m=gl)
    add("寄付地", "寄付地（塀外の帯・要確認）", h.donation_poly, "e67e22", grp="寄付地", 標高TP_m=gl, 備考="市へ割譲する提案。法的扱いは要確認")
    x0, y0, x1, y1 = h.outer_dims()
    add("建物", "建物外形（外断熱の外面）", sbox(x0, y0, x1, y1), "4f5b2a", grp="建物", 標高TP_m=gl, 軒高TP_m=round(gl + h.fl["RF"] / 1000, 2),
        パラペット天端TP_m=round(gl + h.parapet_top / 1000, 2), 階数=2, 建築面積m2=round(h.building_area(), 2))
    for i, ln in enumerate(h.fence_lines, 1):
        add("塀", f"塀 {i}（中心線）", ln, "8d8d8d", area=False, 高さm=h.fence_h / 1000, 厚mm=h.fence_t)
    dot = [p for p in M.polys_of(h.dotcon)] + [h.dotcon_farm] + [p for p in M.polys_of(h.dotcon_garden)]
    for i, p in enumerate(dot, 1):
        if isinstance(p, Polygon) and not p.is_empty:
            add("Dotcon+", f"Dotcon+ 舗装 {i}", p, "d8c9a8", grp="外構", 標高TP_m=gl)
    add("外構", "ソーラーパーゴラ", sbox(*h.pergola), "b8892d", PV枚数=112, 容量kWp=27.1)
    add("外構", "ソーラーカーポート", sbox(*h.carport), "b8892d", PV枚数=32)
    add("外構", "雨水貯留槽", h.tank_poly(), "4a90a4", 備考="位置は spec.rainwater")
    add("外構", "がけ 2H 範囲", h.cliff_zone, "a67c52", 備考="がけの高さ 3.2〜3.3m の 2H 範囲")
    for i, b in enumerate(h.existing, 1):
        add("既存建物", f"既存建物 {i}（解体予定）", Polygon(b), "999999", grp="敷地")
    return out


def geojson(h):
    feats = []
    for kind, name, g, props, color in features(h):
        if g.geom_type == "Polygon":
            geo = dict(type="Polygon", coordinates=_poly_coords(h, g))
        elif g.geom_type == "MultiPolygon":
            geo = dict(type="MultiPolygon", coordinates=[_poly_coords(h, p) for p in g.geoms])
        else:
            geo = dict(type="LineString", coordinates=_ring(h, g.coords))
        feats.append(dict(type="Feature", properties=props, geometry=geo))
    lat, lon = h.gsi["meta"]["origin_latlon"]
    return dict(type="FeatureCollection", name="kawazanyo_site",
                properties=dict(版=C.VERSION, 座標系="WGS84 経緯度（局所 ENU の近似。基準 %.5fN %.5fE）" % (lat, lon),
                                建物Y軸の真北からの角度_deg=round(C.true_north_deg(h), 3), 注記="測量前の推定。測量後に EPSG:6677 へ置換"),
                features=feats)


def kml(h):
    ns = "http://www.opengis.net/kml/2.2"
    ET.register_namespace("", ns)
    q = lambda t: f"{{{ns}}}{t}"
    root = ET.Element(q("kml"))
    doc = ET.SubElement(root, q("Document"))
    ET.SubElement(doc, q("name")).text = f"河沿要（仮称） 敷地 {C.VERSION}"
    feats = features(h)
    kinds = []
    for kind, *_ in feats:
        if kind not in kinds:
            kinds.append(kind)
    for k, (kind, name, g, props, color) in enumerate(feats):
        sid = f"s{k}"
        st = ET.SubElement(doc, q("Style"), id=sid)
        ls = ET.SubElement(st, q("LineStyle"))
        ET.SubElement(ls, q("color")).text = "ff" + color[4:6] + color[2:4] + color[0:2]
        ET.SubElement(ls, q("width")).text = "2"
        ps = ET.SubElement(st, q("PolyStyle"))
        ET.SubElement(ps, q("color")).text = "55" + color[4:6] + color[2:4] + color[0:2]
    folders = {kd: ET.SubElement(doc, q("Folder")) for kd in kinds}
    for kd, fo in folders.items():
        ET.SubElement(fo, q("name")).text = kd
    for k, (kind, name, g, props, color) in enumerate(feats):
        pm = ET.SubElement(folders[kind], q("Placemark"))
        ET.SubElement(pm, q("name")).text = name
        ET.SubElement(pm, q("styleUrl")).text = f"#s{k}"
        ET.SubElement(pm, q("description")).text = "\n".join(f"{a}: {b}" for a, b in props.items() if a not in ("区分", "名称"))
        ed = ET.SubElement(pm, q("ExtendedData"))
        for a, b in props.items():
            ET.SubElement(ed, q("Data"), name=a).append(_val(q, b))

        def poly_el(parent, p):
            pe = ET.SubElement(parent, q("Polygon"))
            ET.SubElement(pe, q("tessellate")).text = "1"
            rings = _poly_coords(h, p)
            ob = ET.SubElement(ET.SubElement(pe, q("outerBoundaryIs")), q("LinearRing"))
            ET.SubElement(ob, q("coordinates")).text = " ".join(f"{a},{b},0" for a, b in rings[0])
            for r in rings[1:]:
                ib = ET.SubElement(ET.SubElement(pe, q("innerBoundaryIs")), q("LinearRing"))
                ET.SubElement(ib, q("coordinates")).text = " ".join(f"{a},{b},0" for a, b in r)
        if g.geom_type == "Polygon":
            poly_el(pm, g)
        elif g.geom_type == "MultiPolygon":
            mg = ET.SubElement(pm, q("MultiGeometry"))
            for p in g.geoms:
                poly_el(mg, p)
        else:
            le = ET.SubElement(pm, q("LineString"))
            ET.SubElement(le, q("tessellate")).text = "1"
            ET.SubElement(le, q("coordinates")).text = " ".join(f"{a},{b},0" for a, b in _ring(h, g.coords))
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _val(q, b):
    e = ET.Element(q("value"))
    e.text = str(b)
    return e


def write(h, outdir, mf):
    outdir = Path(outdir)
    gj = geojson(h)
    p = outdir / "site.geojson"
    p.write_text(json.dumps(gj, ensure_ascii=False, indent=1), encoding="utf-8")
    mf.add(p, "GeoJSON", COORD_ENU, note=f"{len(gj['features'])} 地物")
    p = outdir / "site.kml"
    p.write_bytes(kml(h))
    mf.add(p, "KML", COORD_ENU, note=f"{len(gj['features'])} 地物")
