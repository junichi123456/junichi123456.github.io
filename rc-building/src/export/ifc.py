"""IFC4 書き出し（ifcopenshell）。House の箱・壁・室・家具・照明を属性付きの部材として出す。

座標系: 建物ローカル（mm、原点 = X1・Y1 壁芯交点、z=0 = 設計 GL、Z 上）。真北は TrueNorth と IfcMapConversion で与える。
形状は h.boxes の箱を IfcExtrudedAreaSolid の矩形押出しで出す（GLB と体積が一致）。開口は壁厚に広げた箱の IfcOpeningElement。
"""
from __future__ import annotations

import hashlib
import math
import zipfile
from collections import Counter
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.material
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.guid
import numpy as np
import trimesh
from shapely.geometry import LineString, Polygon, box as sbox
from shapely.ops import unary_union

import model3d as M
from geom import Box

from . import common as C
from .manifest import COORD_LOCAL

api = ifcopenshell.api
CAT_PRED = {"wall": "SOLIDWALL", "partition": "PARTITIONING", "parapet": "PARAPET", "insul": "NOTDEFINED"}
MAX_TRI = 5000            # 家具 1 点あたりの三角形上限
SKIP_LABEL = ""           # 空のラベルは「開口」


# ------------------------------------------------------------------ 低レベル（形状）
class Ctx:
    """書き出し中の共有状態。"""

    def __init__(self, h, schema="IFC4"):
        self.h = h
        self.f = ifcopenshell.file(schema=schema)
        self.table = M.material_table(h.spec, interior=True)
        self.table["space"] = dict(color="#DDDDDD", alpha=0.15)
        self.flags = C.Flags(h.root)
        self.styles = {}
        self.mats = {}
        self.psets = Counter()

    # --- 基本部品
    def pt(self, *c):
        return self.f.createIfcCartesianPoint([float(v) for v in c])

    def dr(self, *c):
        return self.f.createIfcDirection([float(v) for v in c])

    def a2p3(self, o=(0, 0, 0), axis=None, ref=None):
        return self.f.createIfcAxis2Placement3D(self.pt(*o), self.dr(*axis) if axis else None, self.dr(*ref) if ref else None)

    def style(self, key):
        if key not in self.styles:
            t = self.table[key]
            r, g, b = C.hex_rgb(t["color"])
            col = self.f.createIfcColourRgb(None, r / 255, g / 255, b / 255)
            tr = 1.0 - t.get("alpha", 1.0)
            rend = self.f.createIfcSurfaceStyleRendering(col, tr if tr > 0 else None, None, None, None, None, None, None, "NOTDEFINED")
            self.styles[key] = self.f.createIfcSurfaceStyle(key, "BOTH", [rend])
        return self.styles[key]

    def material(self, key):
        if key not in self.mats:
            m = api.material.add_material(self.f, name=key, category="concrete" if "concrete" in key else None)
            self.mats[key] = m
        return self.mats[key]

    def styled(self, item, key):
        self.f.createIfcStyledItem(item, [self.style(key)], None)
        return item

    # --- 押出し形状
    def rect_solid(self, q, dz, key):
        x0, y0, z0, x1, y1, z1 = q
        if x1 - x0 <= 0 or y1 - y0 <= 0 or z1 - z0 <= 0:
            return None
        prof = self.f.createIfcRectangleProfileDef("AREA", None, self.f.createIfcAxis2Placement2D(self.pt((x0 + x1) / 2, (y0 + y1) / 2), None),
                                                   float(x1 - x0), float(y1 - y0))
        s = self.f.createIfcExtrudedAreaSolid(prof, self.a2p3((0, 0, z0 - dz)), self.dr(0, 0, 1), float(z1 - z0))
        return self.styled(s, key)

    def poly_profile(self, poly):
        def ring(r):
            pts = [self.pt(x, y) for x, y in list(r.coords)]
            return self.f.createIfcPolyline(pts)
        if poly.interiors:
            return self.f.createIfcArbitraryProfileDefWithVoids("AREA", None, ring(poly.exterior), [ring(i) for i in poly.interiors])
        return self.f.createIfcArbitraryClosedProfileDef("AREA", None, ring(poly.exterior))

    def prism_solid(self, poly, z0, z1, dz, key):
        if poly.is_empty or z1 - z0 <= 0 or not isinstance(poly, Polygon):
            return None
        s = self.f.createIfcExtrudedAreaSolid(self.poly_profile(poly), self.a2p3((0, 0, z0 - dz)), self.dr(0, 0, 1), float(z1 - z0))
        return self.styled(s, key)

    def cyl_solid(self, x, y, r, z0, z1, dz, key):
        prof = self.f.createIfcCircleProfileDef("AREA", None, self.f.createIfcAxis2Placement2D(self.pt(x, y), None), float(r))
        s = self.f.createIfcExtrudedAreaSolid(prof, self.a2p3((0, 0, z0 - dz)), self.dr(0, 0, 1), float(z1 - z0))
        return self.styled(s, key)

    def tilt_solid(self, cx, cy, cz, ex, ey, ez, tilt, dz, key):
        """X 軸まわりに tilt 度傾けた箱（model3d.tbox と同じ向き）。"""
        a = math.radians(tilt)
        zax = (0, -math.sin(a), math.cos(a))
        o = (cx - zax[0] * ez / 2, cy - zax[1] * ez / 2, cz - dz - zax[2] * ez / 2)
        prof = self.f.createIfcRectangleProfileDef("AREA", None, self.f.createIfcAxis2Placement2D(self.pt(0, 0), None), float(ex), float(ey))
        s = self.f.createIfcExtrudedAreaSolid(prof, self.a2p3(o, zax, (1, 0, 0)), self.dr(0, 0, 1), float(ez))
        return self.styled(s, key)

    def mesh_item(self, verts_mm, faces, key):
        pl = self.f.createIfcCartesianPointList3D([[float(a) for a in v] for v in verts_mm])
        fs = self.f.createIfcTriangulatedFaceSet(pl, None, None, [[int(i) + 1 for i in t] for t in faces], None)
        return self.styled(fs, key)

    def body(self, items, rep_type="SweptSolid"):
        items = [i for i in items if i is not None]
        if not items:
            return None
        ctx = self.body_ctx
        rep = self.f.createIfcShapeRepresentation(ctx, "Body", rep_type, items)
        return self.f.createIfcProductDefinitionShape(None, None, [rep])

    # --- 製品
    def product(self, cls, name, container, items, ptype=None, objtype=None, tag=None, rep_type="SweptSolid", desc=None, placement=None):
        e = api.root.create_entity(self.f, ifc_class=cls, name=name, predefined_type=ptype) if ptype else api.root.create_entity(self.f, ifc_class=cls, name=name)
        if objtype:
            e.ObjectType = objtype
        if tag:
            e.Tag = tag
        if desc:
            e.Description = desc
        if container is not None:
            e.ObjectPlacement = placement or self.f.createIfcLocalPlacement(container.ObjectPlacement, self.a2p3())
        rep = self.body(items, rep_type)
        if rep:
            e.Representation = rep
        if container is not None:
            api.spatial.assign_container(self.f, products=[e], relating_structure=container)
        return e

    def pset(self, e, name, props):
        props = {k: v for k, v in props.items() if v is not None and v != ""}
        if not props:
            return
        ps = api.pset.add_pset(self.f, product=e, name=name)
        api.pset.edit_pset(self.f, pset=ps, properties=props)
        self.psets[name] += 1

    def kz(self, e, keys=(), tag="", room="", group="", node="", extra=None):
        """共通 Pset_Kawazanyo。"""
        fl = self.flags.get(tag=tag, room=room, group=group)
        keys = sorted({k for k in keys if k})
        props = dict(Version=C.VERSION, 要確認=bool(fl["confirm"]), 仮置き=bool(fl["provisional"]), 根拠=fl["basis"],
                     色コード="、".join(f"{k}={self.table[k]['color']}" for k in keys if k in self.table),
                     材質キー="、".join(keys), GLBノード名=node or None)
        if extra:
            props.update(extra)
        self.pset(e, "Pset_Kawazanyo", props)
        if keys:
            api.material.assign_material(self.f, products=[e], material=self.material(keys[0]))


def _pieces(ctx, bx, dz):
    """Box → [(押出し形状, 材質キー)]。GLB と同じ classify で材質を分ける。"""
    out = []
    for q, mk in M.classify(ctx.h, bx):
        s = ctx.rect_solid(q, dz, mk)
        if s is not None:
            out.append((s, mk))
    return out


def _bkey(bx):
    return (round(bx.x0, 3), round(bx.y0, 3), round(bx.z0, 3), round(bx.x1, 3), round(bx.y1, 3), round(bx.z1, 3), bx.cat, bx.level, bx.tag)


# ------------------------------------------------------------------ 空間構造
def _dms(v):
    s = 1 if v >= 0 else -1
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    sec = int(((v - d) * 60 - m) * 60)
    micro = int(round((((v - d) * 60 - m) * 60 - sec) * 1e6))
    return [s * d, s * m, s * sec, s * micro]


def build_spatial(ctx):
    h, f = ctx.h, ctx.f
    project = api.root.create_entity(f, ifc_class="IfcProject", name="河沿要（仮称）新築計画")
    project.Description = f"基本計画段階のモデル（{C.VERSION}）。実施設計の精度はない。単位 mm。"
    si = lambda t, n="METRE", p=None: api.unit.add_si_unit(f, unit_type=t, prefix=p)
    api.unit.assign_unit(f, units=[api.unit.add_si_unit(f, unit_type="LENGTHUNIT", prefix="MILLI"), api.unit.add_si_unit(f, unit_type="AREAUNIT"),
                                   api.unit.add_si_unit(f, unit_type="VOLUMEUNIT"), api.unit.add_si_unit(f, unit_type="PLANEANGLEUNIT")])
    model = api.context.add_context(f, context_type="Model")
    ctx.body_ctx = api.context.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
    plan = api.context.add_context(f, context_type="Plan")
    ctx.fp_ctx = api.context.add_context(f, context_type="Plan", context_identifier="FootPrint", target_view="PLAN_VIEW", parent=plan)
    ctx.ann_ctx = api.context.add_context(f, context_type="Plan", context_identifier="Annotation", target_view="PLAN_VIEW", parent=plan)
    nx, ny = C.truenorth_dir(h)
    for c in (model, plan):
        c.TrueNorth = ctx.dr(nx, ny)
    # 地理参照（局所 ENU → 建物ローカル）
    e0, n0 = h.mm2m(0, 0)
    crs = f.createIfcProjectedCRS("Local ENU 35.66773N 139.34047E / TP", "局所 ENU（国土地理院ベクトルタイル由来）。測量後に EPSG:6677 へ置換", None, None, None, None,
                                  api.unit.add_si_unit(f, unit_type="LENGTHUNIT"))
    f.createIfcMapConversion(model, crs, float(e0), float(n0), float(h.gl_tp), math.cos(h.alpha), math.sin(h.alpha), 0.001)

    def place(elev=0.0, rel=None):
        return f.createIfcLocalPlacement(rel, ctx.a2p3((0, 0, elev)))

    site = api.root.create_entity(f, ifc_class="IfcSite", name="敷地（八王子市大和田町7丁目）")
    site.ObjectPlacement = place()
    lat, lon = h.gsi["meta"]["origin_latlon"]
    site.RefLatitude, site.RefLongitude, site.RefElevation = _dms(lat), _dms(lon), float(h.gl_tp * 1000)
    site.LongName = "新敷地境界内（寄付地を除く）。標高 TP+109.0m が z=0"
    ctx.site = site
    bld = api.root.create_entity(f, ifc_class="IfcBuilding", name="河沿要（仮称）")
    bld.ObjectPlacement = place(rel=site.ObjectPlacement)
    ctx.building = bld
    api.aggregate.assign_object(f, products=[site], relating_object=project)
    api.aggregate.assign_object(f, products=[bld], relating_object=site)
    ctx.storey = {}
    for name, z in C.storeys(h):
        s = api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=name)
        s.Elevation = float(z)
        s.LongName = {"FDN": "基礎", "1F": "1階", "2F": "2階", "RF": "屋上"}[name]
        s.ObjectPlacement = place(z, bld.ObjectPlacement)
        api.aggregate.assign_object(f, products=[s], relating_object=bld)
        ctx.storey[name] = s
    ctx.elev = dict(C.storeys(h))
    ctx.project = project
    ctx.pset(project, "Pset_Kawazanyo", dict(Version=C.VERSION, 版=C.VERSION))
    # 敷地境界: 新境界を FootPrint、旧境界・寄付地を IfcAnnotation
    ring = lambda pts: f.createIfcPolyline([ctx.pt(x, y) for x, y in list(pts) + [pts[0]]])
    site.Representation = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(ctx.fp_ctx, "FootPrint", "Curve2D", [ring(h.site_pts)])])
    for nm, pts, grp in (("旧敷地境界（寄付地を含む）", h.gross_edges_pts, "敷地"), ("寄付地（要確認）", list(h.donation_poly.exterior.coords)[:-1], "寄付地")):
        an = api.root.create_entity(f, ifc_class="IfcAnnotation", name=nm)
        an.ObjectPlacement = f.createIfcLocalPlacement(site.ObjectPlacement, ctx.a2p3())
        an.Representation = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(ctx.ann_ctx, "Annotation", "Curve2D", [ring(pts)])])
        api.spatial.assign_container(f, products=[an], relating_structure=site)
        ctx.kz(an, group=grp)
    ctx.kz(site, group="敷地", extra=dict(新敷地面積m2=round(h.site.area / 1e6, 2), 旧敷地面積m2=round(h.site_gross.area / 1e6, 2),
                                           寄付地面積m2=round(h.donation_poly.area / 1e6, 2)))
    ctx.kz(bld)


def build_spaces(ctx):
    import interior as IN
    h, f = ctx.h, ctx.f
    fin = {}
    for fl, n, c, a, (fl_, sk, wa, ce, note) in IN.finish_schedule(h):
        fin[(fl, n)] = (fl_, sk, wa, ce)
    for r in h.rooms:
        st = ctx.storey[r.floor]
        z0 = h.fl[r.floor]
        x0, y0, x1, y1 = r.rect
        sol = ctx.rect_solid((x0, y0, z0, x1, y1, z0 + (r.ch or h.ch[r.floor])), ctx.elev[r.floor], "space")
        sp = api.root.create_entity(f, ifc_class="IfcSpace", name=r.name)
        sp.LongName = r.name
        sp.PredefinedType = "SPACE"
        sp.ObjectPlacement = f.createIfcLocalPlacement(st.ObjectPlacement, ctx.a2p3())
        sp.Representation = ctx.body([sol])
        api.aggregate.assign_object(f, products=[sp], relating_object=st)
        q = api.pset.add_qto(f, product=sp, name="Qto_SpaceBaseQuantities")
        ch = float(r.ch or h.ch[r.floor])
        api.pset.edit_qto(f, qto=q, properties=dict(NetFloorArea=round(r.area, 4), GrossFloorArea=round(r.area, 4), Height=ch))
        fi = fin.get((r.floor, r.name))
        try:
            col = IN.color_of(h, r.name)["text"]
        except Exception:                      # noqa: BLE001
            col = None
        ctx.pset(sp, "Pset_SpaceCommon", dict(Reference=r.name, IsExternal=False, GrossPlannedArea=round(r.area, 4),
                                              OccupancyType="居室" if r.habitable else None))
        ctx.kz(sp, room=r.name, extra=dict(天井高mm=ch, 床仕上=fi[0] if fi else None, 巾木=fi[1] if fi else None, 壁仕上=fi[2] if fi else None,
                                           天井仕上=fi[3] if fi else None, 配色=col, 居室=bool(r.habitable)))
        ctx.nspace = getattr(ctx, "nspace", 0) + 1


# ------------------------------------------------------------------ 壁・開口・建具
def _fill_box(w, op):
    th, cat, mat = (30, "glass", "glass") if op.kind == "window" else (50, "door", "door")
    if op.glass is True:
        th, mat = 11, "glass"
    hh = th / 2
    if w.axis == "x":
        return Box(op.u0, w.c - hh, op.z0, op.u1, w.c + hh, op.z1, cat, mat, level=w.floor, tag=op.label)
    return Box(w.c - hh, op.u0, op.z0, w.c + hh, op.u1, op.z1, cat, mat, level=w.floor, tag=op.label)


def _open_box(w, op):
    hh = w.t / 2 + 25 + (w.ins_extra if hasattr(w, "ins_extra") else 0)
    if w.axis == "x":
        return (op.u0, w.c - hh, op.z0, op.u1, w.c + hh, op.z1)
    return (w.c - hh, op.u0, op.z0, w.c + hh, op.u1, op.z1)


def build_walls(ctx):
    """h.walls 1 本 = 1 IfcWall。開口は IfcOpeningElement、窓・扉は IfcWindow/IfcDoor（IfcRelFillsElement）。戻り値: 壁由来の箱キーの Counter。"""
    h, f = ctx.h, ctx.f
    used = Counter()
    fit = {x["label"]: x for x in h.fittings}
    glz = h.spec["glazing"]
    ctx.walls = []
    ctx.nwin = ctx.ndoor = ctx.nopen = 0
    for w in h.walls:
        st = ctx.storey[w.floor]
        dz = ctx.elev[w.floor]
        allb = h._wall_boxes(w)
        solids, keys = [], []
        for bx in allb:
            used[_bkey(bx)] += 1
            if bx.cat in ("glass", "door") and bx.tag != "增し打ち":
                continue
            for s, mk in _pieces(ctx, bx, dz):
                solids.append(s)
                keys.append(mk)
        pred = CAT_PRED.get(w.cat, "NOTDEFINED")
        nm = f"{w.floor}-{'X' if w.axis == 'x' else 'Y'}{round(w.c)}-{round(w.a)}～{round(w.b)}"
        wall = ctx.product("IfcWall", nm, st, solids, ptype=pred, objtype=C.CAT_JP.get(w.cat, w.cat), tag=w.cat)
        ctx.walls.append(wall)
        ext = w.side in ("S", "N", "E", "W") and w.cat in ("wall", "parapet", "insul")
        ctx.pset(wall, "Pset_WallCommon", dict(Reference=nm, IsExternal=bool(ext), LoadBearing=w.cat == "wall", ExtendToStructure=w.cat == "wall",
                                               FireRating="耐火構造" if w.cat in ("wall", "parapet") else None))
        if w.extra:
            tt = "、".join(f"{round(a)}～{round(b)} +{round(te)}mm" for a, b, te, sg in w.extra)
        else:
            tt = None
        ctx.kz(wall, keys, group=C.CAT_JP.get(w.cat), node=f"躯体|{w.floor}|{keys[0] if keys else ''}",
               extra=dict(壁芯座標=round(w.c), 軸="X方向" if w.axis == "x" else "Y方向", 厚mm=w.t, 始点=round(w.a), 終点=round(w.b), 増し打ち=tt))
        # 材料層（断熱は別壁として存在するので、各壁は単層）
        ls = api.material.add_material_set(f, name=f"{C.CAT_JP.get(w.cat, w.cat)} t{round(w.t)}", set_type="IfcMaterialLayerSet")
        lay = api.material.add_layer(f, layer_set=ls, material=ctx.material({"wall": "concrete", "parapet": "concrete", "insul": "insul", "partition": "lgs"}.get(w.cat, "concrete")))
        lay.LayerThickness = float(w.t)
        api.material.assign_material(f, products=[wall], type="IfcMaterialLayerSetUsage", material=ls)
        if w.cat == "insul":
            continue
        for op in w.openings:
            ctx.nopen += 1
            oq = _open_box(w, op)
            o = ctx.product("IfcOpeningElement", f"開口 {op.label or op.name}", st, [ctx.rect_solid(oq, dz, "space")], ptype="OPENING", tag=op.label)
            f.createIfcRelVoidsElement(ifcopenshell.guid.new(), None, None, None, wall, o)
            if op.operation == "opening":
                continue
            fb = _fill_box(w, op)
            pcs = _pieces(ctx, fb, dz)
            win = op.kind == "window"
            el = ctx.product("IfcWindow" if win else "IfcDoor", op.label or op.name, st, [p for p, _ in pcs],
                             ptype="WINDOW" if win else "DOOR", objtype=op.name, tag=op.label)
            el.OverallWidth, el.OverallHeight = float(op.u1 - op.u0), float(op.z1 - op.z0)
            f.createIfcRelFillsElement(ifcopenshell.guid.new(), None, None, None, o, el)
            ft = fit.get(op.label, {})
            ctx.pset(el, "Pset_WindowCommon" if win else "Pset_DoorCommon",
                     dict(Reference=op.label, IsExternal=bool(op.exterior), FireRating="防火設備" if op.fire else None, SmokeStop=bool(op.smoke_seal)))
            g = None
            if win and op.exterior:
                g = glz.get("build_1f" if op.floor == "1F" else "build_2f")
            ctx.kz(el, [k for _, k in pcs], tag=op.label, room="", node=f"建具|{op.floor}|{pcs[0][1] if pcs else ''}",
                   extra=dict(建具名=op.name, 開き方式=op.operation, 吊元=("u0側" if op.hinge == 0 else "u1側") if op.operation == "swing" else None,
                              開き方向=op.swing if op.operation == "swing" else None, 非常用進入口代替=bool(op.alt_entry),
                              ガラス仕様=g, ガラス面積m2=round(op.glass, 3) if isinstance(op.glass, float) else None,
                              ホスト壁=wall.Name, 建具表の個数=ft.get("count")))
            if win:
                ctx.nwin += 1
            else:
                ctx.ndoor += 1
            ctx.fittings_seen = getattr(ctx, "fittings_seen", set()) | {op.label}
    return used


# ------------------------------------------------------------------ 壁以外の箱
def build_other_boxes(ctx, used):
    h, f = ctx.h, ctx.f
    rest = []
    for bx in h.boxes:
        k = _bkey(bx)
        if used[k] > 0:
            used[k] -= 1
            continue
        rest.append(bx)
    # 階段の分類
    stair_by_tag = {s.name: s for s in h.stairs}
    stair_parts = {s.name: {"lo": [], "up": [], "land": []} for s in h.stairs}
    other = []
    for bx in rest:
        base = bx.tag[:-2] if bx.tag.endswith("踊場") else bx.tag
        if bx.cat == "stair" and base in stair_by_tag:
            s = stair_by_tag[base]
            zl = s.z0 + s.half * s.riser
            key = "land" if bx.tag.endswith("踊場") else ("up" if bx.z1 > zl + 1 else "lo")
            stair_parts[base][key].append(bx)
        else:
            other.append(bx)
    for s in h.stairs:
        st = ctx.storey[s.floor]
        dz = ctx.elev[s.floor]
        parts = stair_parts[s.name]
        stair = ctx.product("IfcStair", s.name, st, [], ptype="HALF_TURN_STAIR", objtype="階段", tag=s.name)
        kids = []
        for nm, bxs in (("下の flight", parts["lo"]), ("上の flight", parts["up"])):
            items, keys = [], []
            for bx in bxs:
                for sol, mk in _pieces(ctx, bx, dz):
                    items.append(sol)
                    keys.append(mk)
            fl = ctx.product("IfcStairFlight", f"{s.name} {nm}", None, items, ptype="STRAIGHT", tag=s.name)
            fl.ObjectPlacement = f.createIfcLocalPlacement(stair.ObjectPlacement, ctx.a2p3())
            fl.NumberOfRisers, fl.NumberOfTreads = int(s.half), int(s.half - 1)
            fl.RiserHeight, fl.TreadLength = float(s.riser), float(s.tread)
            ctx.kz(fl, keys, tag=s.name, group="階段")
            kids.append(fl)
        items, keys = [], []
        for bx in parts["land"]:
            for sol, mk in _pieces(ctx, bx, dz):
                items.append(sol)
                keys.append(mk)
        land = ctx.product("IfcSlab", f"{s.name}踊場", None, items, ptype="LANDING", tag=s.name + "踊場")
        land.ObjectPlacement = f.createIfcLocalPlacement(stair.ObjectPlacement, ctx.a2p3())
        ctx.kz(land, keys, tag=s.name, group="階段")
        kids.append(land)
        api.aggregate.assign_object(f, products=kids, relating_object=stair)
        ctx.pset(stair, "Pset_StairCommon", dict(Reference=s.name, NumberOfRiser=int(s.n), NumberOfTreads=int(s.n - 1),
                                                 RiserHeight=float(s.riser), TreadLength=float(s.tread), RequiredHeadroom=2100.0))
        ctx.kz(stair, tag=s.name, group="階段")
    ctx.nother = Counter()
    ext_steps = [b for b in other if b.cat == "stair" and b.tag == "外部階段"]
    if ext_steps:                                         # 外部階段の各段は 1 つの IfcStair にまとめる
        items, keys = [], []
        for bx in ext_steps:
            for sol, mk in _pieces(ctx, bx, 0.0):
                items.append(sol)
                keys.append(mk)
        e = ctx.product("IfcStair", "外部階段", ctx.site, items, ptype="STRAIGHT_RUN_STAIR", objtype="外部階段", tag="外部階段")
        ctx.pset(e, "Pset_StairCommon", dict(Reference="外部階段", NumberOfRiser=h.ext_stair["n"], RiserHeight=float(h.ext_stair["riser"]), TreadLength=float(h.ext_stair["tread"])))
        ctx.kz(e, keys, tag="外部階段", node="階段|EXT|" + (keys[0] if keys else ""))
        ctx.nother["stair_ext"] += 1
        other = [b for b in other if not (b.cat == "stair" and b.tag == "外部階段")]
    for bx in other:
        if bx.level == "EXT" and bx.tag != "庇" and bx.tag != "庇B":
            cont, dz = ctx.site, 0.0
        else:
            lvl = bx.level if bx.level in ctx.storey else C.level_of(h, bx.z0)
            cont, dz = ctx.storey[lvl], ctx.elev[lvl]
        pcs = _pieces(ctx, bx, dz)
        items = [p for p, _ in pcs]
        keys = [k for _, k in pcs]
        cat, tag = bx.cat, bx.tag
        if cat == "slab":
            pred = "ROOF" if bx.level == "RF" else "FLOOR"
            obj = "庇" if tag in ("庇", "庇B") else None
            e = ctx.product("IfcSlab", tag or "スラブ", cont, items, ptype="USERDEFINED" if obj else pred, objtype=obj or "床", tag=tag)
            kind = "slab"
        elif cat == "footing":
            e = ctx.product("IfcSlab", "基礎スラブ", cont, items, ptype="BASESLAB", objtype="基礎", tag=tag)
            kind = "footing"
        elif cat == "column":
            e = ctx.product("IfcColumn", tag or "柱", cont, items, ptype="COLUMN", objtype="角の鋼柱", tag=tag)
            kind = "column"
        elif cat == "mullion":
            e = ctx.product("IfcMember", tag or "方立", cont, items, ptype="MULLION", objtype="方立", tag=tag)
            kind = "member"
        elif cat == "blind" and tag == "外付けスクリーン":
            e = ctx.product("IfcShadingDevice", tag, cont, items, ptype="SHUTTER", objtype="ZIPスクリーン", tag=tag)
            kind = "blind"
        elif cat == "blind":
            e = ctx.product("IfcBuildingElementProxy", tag or "付属物", cont, items, objtype=tag or "付属物", tag=tag)
            kind = "proxy"
        elif cat == "stair":
            if tag == "玄関ポーチ":
                e = ctx.product("IfcSlab", tag, cont, items, ptype="FLOOR", objtype="ポーチ", tag=tag)
                kind = "porch"
            else:
                e = ctx.product("IfcStair", tag or "外部階段", cont, items, ptype="STRAIGHT_RUN_STAIR", objtype="外部階段", tag=tag)
                kind = "stair_ext"
        elif cat == "partition" and tag in ("手すり壁", "腰壁（転落防止）"):
            e = ctx.product("IfcRailing", tag, cont, items, ptype="GUARDRAIL", objtype="手すり壁", tag=tag)
            kind = "railing"
        elif cat == "wall" and bx.level == "EXT":
            e = ctx.product("IfcWall", tag or "外構壁", cont, items, ptype="SOLIDWALL", objtype="外構壁", tag=tag)
            kind = "wall_ext"
        elif cat == "door":
            e = ctx.product("IfcBuildingElementProxy", tag, cont, items, objtype=tag, tag=tag)
            kind = "proxy"
        else:
            e = ctx.product("IfcBuildingElementProxy", tag or cat, cont, items, objtype=C.CAT_JP.get(cat, cat), tag=tag)
            kind = "proxy"
        ctx.nother[kind] += 1
        ctx.kz(e, keys, tag=tag, group="塀" if kind == "wall_ext" else None, node=f"{C.CAT_JP.get(cat, cat)}|{bx.level}|{keys[0] if keys else ''}")


# ------------------------------------------------------------------ 外構（塀・舗装・パーゴラ・カーポート・地形）
def build_site(ctx):
    h, f = ctx.h, ctx.f
    fgl = h.fgl
    site = ctx.site
    ctx.nfence = 0
    # 塀（区間ごとに 2m 単位の角柱。1 本の LineString = 1 IfcWall）
    for li, ln in enumerate(h.fence_lines):
        L = ln.length
        items, keys = [], []
        d, pi = 0.0, 0
        while d < L - 1:
            d2 = min(L, d + 2000)
            seg = LineString([ln.interpolate(d).coords[0], ln.interpolate(d2).coords[0]])
            c = seg.interpolate(0.5, normalized=True)
            top = h.fence_top(c.x, c.y)
            base = min(h.fgl, h.ground(c.x, c.y)) - 100
            off = seg.parallel_offset(h.fence_t / 2, "left")
            if not h.fence_poly.contains(off.interpolate(0.5, normalized=True)):
                off = seg.parallel_offset(h.fence_t / 2, "right")
            poly = off.buffer(h.fence_t / 2, cap_style=2)
            k = int(hashlib.sha1(f"{li}-{pi}".encode()).hexdigest(), 16) % 5 + 1
            s = ctx.prism_solid(poly, base, top, 0.0, f"fence_{k}")
            if s is not None:
                items.append(s)
                keys.append(f"fence_{k}")
            d, pi = d2, pi + 1
        w = ctx.product("IfcWall", f"塀 {li + 1}", site, items, ptype="SOLIDWALL", objtype="塀", tag="塀")
        ctx.pset(w, "Pset_WallCommon", dict(Reference=f"塀 {li + 1}", IsExternal=True, LoadBearing=False))
        ctx.kz(w, keys, tag="塀", group="塀", extra=dict(高さmm=h.fence_h, 厚mm=h.fence_t, 長さmm=round(L)))
        ctx.nfence += 1
    # 門扉・門柱
    for name, x0, x1, yg, hh in h.gate_leaves:
        yc = yg + 75
        its = [ctx.rect_solid((x0, yc - 30, fgl + 30, x1, yc + 30, fgl + hh), 0, "gate_panel"), ctx.rect_solid((x0, yc - 40, fgl + 30, x1, yc + 40, fgl + 80), 0, "steel_frame")]
        e = ctx.product("IfcBuildingElementProxy", name, site, its, objtype="門扉", tag=name)
        ctx.kz(e, ["gate_panel", "steel_frame"], group="塀")
    for i, (x0, y0, x1, y1) in enumerate(h.gate_piers, 1):
        e = ctx.product("IfcBuildingElementProxy", f"門柱 {i}", site, [ctx.rect_solid((x0, y0, fgl - 150, x1, y1, fgl + 2050), 0, "concrete")], objtype="門柱")
        ctx.kz(e, ["concrete"], group="塀")
    # 舗装（IFC4 に舗装クラスが無いため IfcSlab USERDEFINED「透水舗装」）
    site_in = h.fence_poly.buffer(-h.fence_t)
    dot = list(M.polys_of(h.dotcon))
    dot += list(M.polys_of(h.approach.intersection(site_in)))
    dot += [h.dotcon_farm] + list(M.polys_of(h.dotcon_garden))
    items = [ctx.prism_solid(p, fgl - 150, fgl + 20, 0.0, "dotcon") for p in dot if isinstance(p, Polygon)]
    e = ctx.product("IfcSlab", "Dotcon+ 舗装", site, items, ptype="USERDEFINED", objtype="透水舗装")
    ctx.kz(e, ["dotcon"], group="外構", extra=dict(面積m2=round(sum(p.area for p in dot) / 1e6, 1)))
    items = [ctx.prism_solid(p, fgl - 100, fgl + 20, 0.0, "porous_concrete") for p in M.polys_of(h.forecourt)]
    e = ctx.product("IfcSlab", "門前の広場（透水性コンクリート）", site, items, ptype="USERDEFINED", objtype="透水舗装")
    ctx.kz(e, ["porous_concrete"], group="外構")
    # ソーラーパーゴラ
    spec = h.spec
    pg = spec["exterior"]["solar_pergola"]
    x0, y0, x1, y1 = h.pergola
    ph = h.pergola_h
    zb = max(h.ground((x0 + x1) / 2, (y0 + y1) / 2), fgl)
    tn = math.tan(math.radians(pg["tilt"]))
    head = lambda y: zb + ph + (y - y0) * tn
    xs = [x0 + i * (x1 - x0) / 4 for i in range(5)]
    frame, pvs = [], []
    for x in xs:
        for y in (y0, y1):
            frame.append(ctx.rect_solid((x - 75, y - 75, zb, x + 75, y + 75, head(y)), 0, "steel_frame"))
            frame.append(ctx.rect_solid((x - 200, y - 200, zb - 100, x + 200, y + 200, zb + 150), 0, "concrete"))
        Lb = (y1 - y0) / math.cos(math.radians(pg["tilt"]))
        frame.append(ctx.tilt_solid(x, (y0 + y1) / 2, (head(y0) + head(y1)) / 2 - 75, 100, Lb, 150, pg["tilt"], 0, "steel_frame"))
    rows, nmod = 7, 16
    pitch = (y1 - y0) / rows
    pw = pitch * pg["coverage"]
    mw = (x1 - x0) / nmod
    for r in range(rows):
        yc = y0 + (r + 0.5) * pitch
        zc = head(yc) + 80
        for i in range(nmod):
            xc = x0 + (i + 0.5) * mw
            pvs.append(ctx.tilt_solid(xc, yc, zc + 1.5, mw - 20 - 50, pw - 50, 40, pg["tilt"], 0, "pv"))
    e = ctx.product("IfcBuildingElementProxy", "ソーラーパーゴラ（架台）", site, frame, objtype="パーゴラ")
    ctx.kz(e, ["steel_frame", "concrete"], group="外構")
    e = ctx.product("IfcSolarDevice", "ソーラーパーゴラ（PV 112枚）", site, pvs, ptype="SOLARPANEL", objtype="太陽光パネル")
    ctx.kz(e, ["pv"], group="外構", extra=dict(枚数=len(pvs), 傾斜度=pg["tilt"]))
    # カーポート
    cp = h.carport
    cph = spec["exterior"]["carport"]["h"]
    frame, pvs = [], []
    for (x, y) in [(cp[0], cp[1]), (cp[2] - 200, cp[1]), (cp[0], cp[3] - 200), (cp[2] - 200, cp[3] - 200)]:
        frame.append(ctx.rect_solid((x, y, fgl, x + 200, y + 200, fgl + cph), 0, "steel_frame"))
        frame.append(ctx.rect_solid((x - 100, y - 100, fgl - 100, x + 300, y + 300, fgl + 150), 0, "concrete"))
    frame.append(ctx.rect_solid((cp[0], cp[1], fgl + cph, cp[2], cp[3], fgl + cph + 80), 0, "steel_frame"))
    nx, ny = 8, 4
    mw, md = (cp[2] - cp[0]) / nx, (cp[3] - cp[1]) / ny
    for i in range(nx):
        for j in range(ny):
            xc, yc = cp[0] + (i + 0.5) * mw, cp[1] + (j + 0.5) * md
            pvs.append(ctx.rect_solid((xc - mw / 2 + 35, yc - md / 2 + 35, fgl + cph + 80, xc + mw / 2 - 35, yc + md / 2 - 35, fgl + cph + 122), 0, "pv"))
    e = ctx.product("IfcBuildingElementProxy", "ソーラーカーポート（架台）", site, frame, objtype="カーポート")
    ctx.kz(e, ["steel_frame", "concrete"], group="外構")
    e = ctx.product("IfcSolarDevice", "ソーラーカーポート（PV 32枚）", site, pvs, ptype="SOLARPANEL", objtype="太陽光パネル")
    ctx.kz(e, ["pv"], group="外構", extra=dict(枚数=len(pvs)))
    # ボラード・プランター
    vs = spec["vehicle_security"]["bollards"]
    for i, (x, y) in enumerate(h.bollards, 1):
        e = ctx.product("IfcBuildingElementProxy", f"昇降ボラード {i}", site,
                        [ctx.cyl_solid(x, y, vs["d"] / 2, fgl, fgl + vs["h"], 0, "bollard"), ctx.rect_solid((x - 300, y - 300, fgl - 150, x + 300, y + 300, fgl + 20), 0, "concrete")],
                        objtype="昇降ボラード")
        ctx.kz(e, ["bollard", "concrete"], group="外構")
    fm = spec["farm"]
    for nm, beds, zbase in (("菜園プランター", h.garden_beds, zb), ("プランター", h.planters, fgl + 20)):
        for i, b in enumerate(beds, 1):
            px0, py0, px1, py1 = b
            z0 = zbase + fm["leg"]
            z1 = z0 + fm["planter_h"]
            its = [ctx.rect_solid((px0, py0, z0, px1, py1, z1), 0, "planter")]
            e = ctx.product("IfcBuildingElementProxy", f"{nm} {i}", site, its, objtype=nm)
            ctx.kz(e, ["planter"], group="外構")
    # 外構照明
    for i, (name, (x, y)) in enumerate(h.ext_lights, 1):
        e = ctx.product("IfcLightFixture", f"{name} {i}", site, [ctx.cyl_solid(x, y, 75, fgl + 20, fgl + 560, 0, "fixture")], ptype="POINTSOURCE", objtype=name)
        ctx.pset(e, "Pset_LightFixtureTypeCommon", dict(Reference=name, NumberOfSources=1, ColourTemperature=2200.0 if hasattr(h, "ext_lights") else None))
        ctx.kz(e, ["fixture"], group="照明", extra=dict(色温度K=2200))
    # 地形（敷地内を 2m グリッドで間引く）
    from shapely.geometry import Point
    minx, miny, maxx, maxy = h.site.bounds
    step = 2000.0
    nxs, nys = int((maxx - minx) // step) + 2, int((maxy - miny) // step) + 2
    idx, verts, tris = {}, [], []
    def vid(i, j):
        if (i, j) not in idx:
            x, y = minx + i * step, miny + j * step
            idx[(i, j)] = len(verts)
            verts.append((x, y, h.ground(x, y)))
        return idx[(i, j)]
    for i in range(nxs):
        for j in range(nys):
            cx, cy = minx + (i + .5) * step, miny + (j + .5) * step
            if h.site.contains(Point(cx, cy)):
                a, b, c, d = vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)
                tris += [(a, b, c), (a, c, d)]
    if tris:
        t = ctx.product("IfcGeographicElement", "敷地内の地形（2m グリッド）", site, [ctx.mesh_item(verts, tris, "ground_wild")], ptype="TERRAIN", objtype="地形", rep_type="Tessellation")
        ctx.kz(t, ["ground_wild"], group="敷地", extra=dict(格子間隔mm=step, 出典="国土地理院 DEM5A"))


# ------------------------------------------------------------------ 家具・機器・照明
def _decimate(meshes):
    """三角形が MAX_TRI を超える家具は、小部品（glide・joint）を落とし、それでも超えるなら外形箱にする。"""
    n = sum(len(m.faces) for m in meshes.values())
    if n <= MAX_TRI:
        return meshes, False
    kept = {k: m for k, m in meshes.items() if k not in ("glide", "joint")}
    if sum(len(m.faces) for m in kept.values()) <= MAX_TRI:
        return kept, True
    out = {}
    for k, m in kept.items():
        out[k] = trimesh.creation.box(bounds=m.bounds) if len(m.faces) > MAX_TRI // 4 else m
    if sum(len(m.faces) for m in out.values()) > MAX_TRI:
        allm = trimesh.util.concatenate(list(meshes.values()))
        return {next(iter(meshes)): trimesh.creation.box(bounds=allm.bounds)}, True
    return out, True


def build_furniture(ctx):
    import furniture as FU
    import lighting as LI
    h, f = ctx.h, ctx.f
    its = FU.items(h)
    ctx.nfurn = 0
    ctx.ndecim = 0
    for it in its:
        meshes, dec = _decimate(FU.build_item(h, it).meshes())
        ctx.ndecim += int(dec)
        st = ctx.storey[it.floor]
        dz = ctx.elev[it.floor]
        items, keys = [], []
        for k, m in meshes.items():
            if k not in ctx.table or len(m.faces) == 0:
                continue
            v = np.array(m.vertices) * 1000.0
            v[:, 2] -= dz
            items.append(ctx.mesh_item(v, m.faces, k))
            keys.append(k)
        e = ctx.product("IfcFurniture", it.id, st, items, ptype="NOTDEFINED", objtype=it.kind, rep_type="Tessellation", desc=it.name)
        pr = h.spec["furniture"]["products"].get(it.product, {}).get("name") if it.product else None
        ctx.pset(e, "Pset_FurnitureTypeCommon", dict(Reference=it.id, Style=it.kind))
        ctx.kz(e, keys, room=it.room, group="家具", extra=dict(名称=it.name, 製品名=pr, 幅mm=round(it.w), 奥行mm=round(it.d), 高さmm=round(it.h),
                                                              数量=it.qty, 室=it.room, 備考=it.note or None))
        ctx.nfurn += 1
    # ジム機器（簡易ボリューム）。蓄電池・機械もここに含まれる
    ctx.nequip = 0
    for name, r, hh, kg in getattr(h, "equipment_cg", h.equipment):
        z0 = h.fl["1F"]
        e = ctx.product("IfcBuildingElementProxy", name, ctx.storey["1F"], [ctx.rect_solid((r[0], r[1], z0, r[2], r[3], z0 + hh), ctx.elev["1F"], "equipment")], objtype="ジム機器")
        ctx.kz(e, ["equipment"], group="ジム機器", extra=dict(質量kg=kg, 幅mm=round(r[2] - r[0]), 奥行mm=round(r[3] - r[1]), 高さmm=hh))
        ctx.nequip += 1
    # 照明
    lcfg = h.spec["lighting"]
    lns = LI.lines(h, its)
    ctx.nlight = 0

    def light(name, floor, items, ptype, props, group="照明"):
        e = ctx.product("IfcLightFixture", name, ctx.storey[floor], items, ptype=ptype, objtype=group)
        ctx.pset(e, "Pset_LightFixtureTypeCommon", props)
        ctx.kz(e, ["fixture"], group="照明" if group != "足元灯" else "足元灯", extra=dict(種別=group, **{k: v for k, v in props.items() if k in ("光束lm", "色温度K")}))
        ctx.nlight += 1

    for l in lns:
        dz = ctx.elev[l["floor"]]
        (x0, y0, z), (x1, y1, _z) = l["p0"], l["p1"]
        q = (min(x0, x1) - (25 if l["axis"] == "y" else 0), min(y0, y1) - (25 if l["axis"] == "x" else 0), z - 60, max(x0, x1) + (25 if l["axis"] == "y" else 0), max(y0, y1) + (25 if l["axis"] == "x" else 0), z)
        flux = round(l["lm_per_m"] * l["L"] / 1000.0)
        light(l["id"], l["floor"], [ctx.rect_solid(q, dz, "fixture")], "DIRECTIONSOURCE", dict(Reference=l["id"], 光束lm=float(flux), 色温度K=2200.0, NumberOfSources=1), "ライン照明")
    for i, d in enumerate(LI.downlights(h, its, lns), 1):
        x, y, z = d["p"]
        light(f"{d['floor']}-{d['code']}-D{i}", d["floor"], [ctx.cyl_solid(x, y, 50, z - 40, z, ctx.elev[d["floor"]], "fixture")], "POINTSOURCE",
              dict(Reference=f"D{i}", 光束lm=float(lcfg["downlight"]["max_lm"]), NumberOfSources=1), "ダウンライト")
    for d in LI.footlights(h):
        x, y, z = d["p"]
        light(d["id"], d["floor"], [ctx.rect_solid((x - 60, y - 60, z - 60, x + 60, y + 60, z + 60), ctx.elev[d["floor"]], "fixture")], "POINTSOURCE",
              dict(Reference=d["id"], 光束lm=float(lcfg["foot"]["lm"]), 色温度K=float(lcfg["foot"]["kelvin"]), NumberOfSources=1), "足元灯")
    pcs, _mk = LI.footlines(h, its)
    for d in pcs:
        (x0, y0, z), (x1, y1, _z) = d["p0"], d["p1"]
        q = (min(x0, x1) - 15, min(y0, y1) - 15, z - 15, max(x0, x1) + 15, max(y0, y1) + 15, z + 15)
        light(d["id"], d["floor"], [ctx.rect_solid(q, ctx.elev[d["floor"]], "fixture")], "DIRECTIONSOURCE",
              dict(Reference=d["id"], 光束lm=float(d["lm_per_m"] * d["L"] / 1000.0), NumberOfSources=1), "足元灯")


# ------------------------------------------------------------------ 入口
def build_ifc(h, schema="IFC4"):
    """IFC モデルを組み立てて (ifcopenshell.file, 統計 dict) を返す。"""
    if schema != "IFC4":
        raise NotImplementedError("IFC2X3 は未実装（IFC4 で出力。要望時に対応）")
    ctx = Ctx(h, schema)
    build_spatial(ctx)
    build_spaces(ctx)
    used = build_walls(ctx)
    build_other_boxes(ctx, used)
    build_site(ctx)
    build_furniture(ctx)
    stats = dict(walls=len(h.walls), fence=ctx.nfence, windows=ctx.nwin, doors=ctx.ndoor, openings=ctx.nopen, spaces=len(h.rooms),
                 furniture=ctx.nfurn, decimated=ctx.ndecim, lights=ctx.nlight, other=dict(ctx.nother))
    return ctx.f, stats


def write(h, outdir, mf, ifc_schema="IFC4"):
    outdir = Path(outdir)
    model, stats = build_ifc(h, ifc_schema)
    p = outdir / f"kawazanyo_{ifc_schema}.ifc"
    model.write(str(p))
    if p.stat().st_size > 10_000_000:                      # 10MB 超は zip（deflate）
        z = p.with_suffix(".ifc.zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.write(p, p.name)
        p.unlink()
        p = z
    mf.add(p, ifc_schema, COORD_LOCAL + "。真北は TrueNorth と IfcMapConversion", note=f"壁{stats['walls']}・窓{stats['windows']}・扉{stats['doors']}・室{stats['spaces']}・家具{stats['furniture']}・照明{stats['lights']}")
    return p
