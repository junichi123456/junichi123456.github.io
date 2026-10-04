"""DXF 作図ライブラリ（CAD 製図ルールの共通部）。

- 単位 mm、モデル空間に実寸 (1:1) で作図し、図枠・文字・記号は縮尺倍して配置
- レイヤ・線種・線の太さは JIS A 0150（建築製図通則）の線の使い分けに準拠
- 文字は IPA ゴシック（ipag.ttf）
"""
from __future__ import annotations

import math

import ezdxf
from ezdxf.enums import TextEntityAlignment

FONT = "ipag.ttf"

# レイヤ名: (色 ACI, 線種, 線幅[1/100mm], 説明)
LAYERS = {
    "G-FRAME": (7, "Continuous", 70, "図枠"),
    "G-TITLE": (7, "Continuous", 25, "表題欄"),
    "G-TABLE": (7, "Continuous", 18, "表"),
    "A-GRID": (1, "CENTER", 13, "通り芯（一点鎖線・細線）"),
    "A-GRID-SYMB": (7, "Continuous", 18, "通り芯符号"),
    "A-CUT": (7, "Continuous", 50, "切断面 RC（太線）"),
    "A-CUT-HATCH": (8, "Continuous", 9, "切断面ハッチング"),
    "A-CUT-LGS": (7, "Continuous", 35, "切断面 軽量間仕切（中線）"),
    "A-CUT-INS": (9, "Continuous", 9, "切断面 断熱材ハッチング"),
    "A-FENCE": (7, "Continuous", 35, "RC塀"),
    "A-PAVE": (3, "Continuous", 13, "舗装（透水性 Dotcon+）"),
    "A-DRAIN": (5, "DASHED", 25, "雨水排水・浸透施設"),
    "A-NEIGH": (8, "Continuous", 13, "隣接建物（基盤地図情報）"),
    "A-WATER": (5, "Continuous", 18, "水路"),
    "A-TERRAIN": (30, "Continuous", 25, "地形断面（DEM）"),
    "A-FLOOD": (5, "DASHDOT", 25, "想定浸水深"),
    "A-FLOW": (6, "DASHED", 35, "動線（回遊・家事・搬入）"),
    "A-VIS": (7, "Continuous", 18, "見え掛り（細線）"),
    "A-HIDDEN": (8, "HIDDEN", 13, "隠れ線（破線）"),
    "A-GLAZ": (5, "Continuous", 18, "建具・ガラス"),
    "A-DOOR": (5, "Continuous", 18, "扉・開き勝手"),
    "A-STRS": (7, "Continuous", 18, "階段"),
    "A-ROOM": (7, "Continuous", 18, "室名・面積"),
    "A-DIMS": (7, "Continuous", 13, "寸法"),
    "A-TEXT": (7, "Continuous", 18, "注記"),
    "A-SYMB": (7, "Continuous", 18, "記号（方位・切断・レベル）"),
    "A-SITE": (3, "PHANTOM", 25, "敷地境界線（二点鎖線）"),
    "A-ROAD": (8, "Continuous", 18, "道路"),
    "A-GROUND": (7, "Continuous", 50, "地盤面 GL"),
    "A-LEGAL": (1, "DASHED", 25, "法規制ライン（斜線・延焼ライン）"),
    "A-LEGAL-TEXT": (1, "Continuous", 18, "法規注記"),
    "A-FIRE": (6, "DASHDOT", 25, "延焼のおそれのある部分"),
    "A-ALT": (1, "Continuous", 35, "代替進入口"),
    "S-COLS": (7, "Continuous", 50, "構造 柱"),
    "S-BEAM": (7, "HIDDEN", 25, "構造 梁（伏図・隠れ）"),
    "S-BEAM-V": (7, "Continuous", 35, "構造 梁（見え）"),
    "S-FNDN": (7, "HIDDEN", 25, "構造 基礎"),
    "S-SLAB": (7, "Continuous", 18, "構造 スラブ"),
    "S-REBAR": (1, "Continuous", 35, "鉄筋"),
    "S-TEXT": (7, "Continuous", 18, "構造 注記"),
}


class Sheet:
    """A3 横 1 枚分の図面（DXF ドキュメント）。"""

    PAPER = (420.0, 297.0)
    MARGIN = 10.0
    TB = (190.0, 38.0)   # 表題欄 幅・高さ

    def __init__(self, number, title, scale, project, scale_label=None):
        self.number = number
        self.title = title
        self.S = float(scale)
        self.scale_label = scale_label or (f"1:{int(scale)}" if scale != 1 else "—")
        self.project = project
        self.doc = ezdxf.new("R2018", setup=True)
        self.doc.units = ezdxf.units.MM
        self.doc.header["$MEASUREMENT"] = 1
        self.doc.header["$LTSCALE"] = self.S * 0.5
        self.doc.header["$PSLTSCALE"] = 0
        self.doc.styles.add("JP", font=FONT)
        self.doc.styles.get("Standard").dxf.font = FONT
        for name, (color, lt, lw, desc) in LAYERS.items():
            lay = self.doc.layers.add(name, color=color, linetype=lt, lineweight=lw)
            lay.description = desc
        ds = self.doc.dimstyles.new("JIS")
        ds.dxf.dimtxsty = "JP"
        ds.dxf.dimscale = self.S
        ds.dxf.dimtxt = 2.0
        ds.dxf.dimasz = 1.0
        ds.dxf.dimblk = "DOT"
        ds.dxf.dimexo = 1.0
        ds.dxf.dimexe = 1.0
        ds.dxf.dimgap = 0.6
        ds.dxf.dimtad = 1
        ds.dxf.dimtih = 0
        ds.dxf.dimtoh = 0
        ds.dxf.dimdec = 0
        ds.dxf.dimclrd = 7
        ds.dxf.dimclre = 7
        ds.dxf.dimclrt = 7
        ds.dxf.dimlwd = 13
        ds.dxf.dimlwe = 13
        self.msp = self.doc.modelspace()
        self.ox = 0.0   # 図枠左下（モデル座標）
        self.oy = 0.0

    # --------------------------------------------------------- coordinates
    def P(self, px, py):
        """用紙座標 (mm) → モデル座標。"""
        return (self.ox + px * self.S, self.oy + py * self.S)

    def place(self, model_xy, paper_xy):
        """モデル点 model_xy が用紙上 paper_xy に来るよう図枠位置を決める。"""
        self.ox = model_xy[0] - paper_xy[0] * self.S
        self.oy = model_xy[1] - paper_xy[1] * self.S

    # ------------------------------------------------------------ primitives
    def line(self, p, q, layer, **kw):
        return self.msp.add_line(p, q, dxfattribs={"layer": layer, **kw})

    def pline(self, pts, layer, closed=False, **kw):
        return self.msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer, **kw})

    def rect(self, x0, y0, x1, y1, layer, **kw):
        return self.pline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, closed=True, **kw)

    def circle(self, c, r, layer, **kw):
        return self.msp.add_circle(c, r, dxfattribs={"layer": layer, **kw})

    def arc(self, c, r, a0, a1, layer):
        return self.msp.add_arc(c, r, a0, a1, dxfattribs={"layer": layer})

    def text(self, s, p, h=2.5, layer="A-TEXT", align="LEFT", rot=0.0, paper=False, **kw):
        """h は用紙上の文字高さ (mm)。"""
        if paper:
            p = self.P(*p)
        t = self.msp.add_text(str(s), height=h * self.S,
                              dxfattribs={"layer": layer, "style": "JP", "rotation": rot, **kw})
        t.set_placement(p, align=getattr(TextEntityAlignment, align))
        return t

    def mtext(self, s, p, h=2.5, width=None, layer="A-TEXT", paper=False):
        if paper:
            p = self.P(*p)
        m = self.msp.add_mtext(s, dxfattribs={"layer": layer, "style": "JP", "char_height": h * self.S})
        if width:
            m.dxf.width = width * self.S
        m.set_location(p)
        return m

    def hatch_polys(self, polys, layer="A-CUT-HATCH", pattern="ANSI31", spacing=1.0, solid=False, color=None):
        """spacing: 用紙上のハッチ線間隔 (mm)。"""
        h = self.msp.add_hatch(color=color or 256, dxfattribs={"layer": layer})
        if solid:
            h.set_solid_fill(color=color or 8)
        else:
            h.set_pattern_fill(pattern, scale=spacing * self.S / 3.175)
        for poly in polys:
            h.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True,
                                      flags=ezdxf.const.BOUNDARY_PATH_EXTERNAL)
            for r in poly.interiors:
                h.paths.add_polyline_path(list(r.coords)[:-1], is_closed=True)
        return h

    def dim(self, p1, p2, base, angle=0, layer="A-DIMS", text=None):
        """直列寸法。angle=0 水平, 90 垂直。数値は 3 桁区切り。"""
        if angle == 0:
            v = abs(p2[0] - p1[0])
        else:
            v = abs(p2[1] - p1[1])
        d = self.msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="JIS",
                                    text=text or f"{v:,.0f}", dxfattribs={"layer": layer})
        d.render()
        return d

    def dim_chain(self, pts, offset, horizontal=True, layer="A-DIMS"):
        """pts: 軸方向の座標列, offset: 寸法線の位置（もう一方の座標）。"""
        for a, b in zip(pts, pts[1:]):
            if horizontal:
                self.dim((a, offset), (b, offset), (a, offset), 0, layer)
            else:
                self.dim((offset, a), (offset, b), (offset, a), 90, layer)

    # -------------------------------------------------------------- symbols
    def grid_bubble(self, c, label, r=4.0):
        self.circle(c, r * self.S, "A-GRID-SYMB")
        self.text(label, c, 3.0, "A-GRID-SYMB", "MIDDLE_CENTER")

    def level_mark(self, x, z, label, side=1, length=22):
        """立面・断面のレベル記号 ▽ と引出線。"""
        S = self.S
        tri = [(x, z), (x - 1.2 * S, z + 2.0 * S), (x + 1.2 * S, z + 2.0 * S)]
        self.pline(tri, "A-SYMB", closed=True)
        x2 = x + side * length * S
        self.line((x, z), (x2, z), "A-SYMB")
        self.text(label, (x + side * 2.0 * S if side > 0 else x2, z + 0.6 * S), 2.2, "A-SYMB",
                  "LEFT" if side > 0 else "LEFT")

    def north_arrow(self, c, r=8.0, rot=0.0):
        """方位記号。rot: 真北の向き（用紙上方から反時計回り、度）。"""
        S = self.S
        cx, cy = c
        a = math.radians(rot)

        def R(dx, dy):
            return (cx + (dx * math.cos(a) - dy * math.sin(a)) * S, cy + (dx * math.sin(a) + dy * math.cos(a)) * S)
        self.circle(c, r * S, "A-SYMB")
        self.pline([R(0, r), R(-0.35 * r, -0.6 * r), R(0, -0.3 * r), R(0.35 * r, -0.6 * r)], "A-SYMB", closed=True)
        h = self.msp.add_hatch(color=7, dxfattribs={"layer": "A-SYMB"})
        h.paths.add_polyline_path([R(0, r), R(0, -0.3 * r), R(0.35 * r, -0.6 * r)])
        self.text("N", R(0, r + 2.2), 3.5, "A-SYMB", "MIDDLE_CENTER", rot=rot)
        if abs(rot) > 0.1:
            self.text(f"真北 {abs(rot):.1f}°{'西' if rot > 0 else '東'}振れ（建物は南側道路に平行）", (cx, cy - (r + 2.5) * S), 1.6, "A-SYMB", "TOP_CENTER")

    def view_title(self, s, scale_txt, p, paper=True, h=4.0):
        if paper:
            p = self.P(*p)
        t = self.text(s, p, h, "A-TEXT", "BOTTOM_LEFT")
        w = _text_width(s, h) * self.S
        self.line((p[0], p[1] - 1.2 * self.S), (p[0] + w + 3 * self.S, p[1] - 1.2 * self.S), "A-SYMB",
                  lineweight=50)
        self.text(f"S={scale_txt}", (p[0] + w + 4 * self.S, p[1]), 2.8, "A-TEXT", "BOTTOM_LEFT")

    # ------------------------------------------------------------- tables
    def table(self, x, y, cols, rows, row_h=6.0, h=2.2, header=True, layer="G-TABLE"):
        """用紙座標 (x, y)=左上。cols: 列幅リスト。rows: 文字列の 2 次元リスト。
        長い文字列は列幅で折り返し、行高を自動拡張する。戻り値: 下端 y。"""
        cy = y
        total_w = sum(cols)
        self.pline([self.P(x, y), self.P(x + total_w, y)], layer, lineweight=35)
        for ri, row in enumerate(rows):
            wrapped = [_wrap(str(c), w - 2.0, h) for c, w in zip(row, cols)]
            n = max(len(wl) for wl in wrapped)
            rh = max(row_h, n * h * 1.45 + 1.8)
            cx = x
            for wl, w in zip(wrapped, cols):
                for li, line in enumerate(wl):
                    self.text(line, (cx + 1.0, cy - 1.2 - h - li * h * 1.45), h, "A-TEXT", "LEFT", paper=True)
                cx += w
            cy -= rh
            lw = 35 if (header and ri == 0) else 18
            self.pline([self.P(x, cy), self.P(x + total_w, cy)], layer, lineweight=lw)
        cx = x
        for w in [0] + cols:
            cx += w
            self.pline([self.P(cx, y), self.P(cx, cy)], layer)
        return cy

    # ---------------------------------------------------------------- frame
    def frame(self, drawings_list_hint=""):
        W, H = self.PAPER
        m = self.MARGIN
        P = self.P
        self.rect(*P(0, 0), *P(W, H), "G-FRAME", lineweight=0)
        self.rect(*P(m, m), *P(W - m, H - m), "G-FRAME")
        tw, th = self.TB
        x0, y0 = W - m - tw, m
        self.rect(*P(x0, y0), *P(W - m, y0 + th), "G-TITLE", lineweight=50)
        pr = self.project
        # 罫線
        ys = [y0 + th, y0 + th - 10, y0 + th - 21, y0 + th - 29, y0]
        for yy in ys[1:-1]:
            self.line(P(x0, yy), P(W - m, yy), "G-TITLE")
        self.line(P(x0 + 22, y0), P(x0 + 22, y0 + th), "G-TITLE")
        self.text("工事名称", P(x0 + 2, ys[1] + 3.5), 2.2, "G-TITLE")
        self.text(pr["name"], P(x0 + 24, ys[1] + 3.0), 3.4, "G-TITLE")
        self.text("図面名称", P(x0 + 2, ys[2] + 4.0), 2.2, "G-TITLE")
        self.text(self.title, P(x0 + 24, ys[2] + 3.2), 4.4, "G-TITLE")
        # 下段: 縮尺 / 日付 / 設計 / 図番
        self.text("縮尺", P(x0 + 2, ys[3] + 2.6), 2.2, "G-TITLE")
        cells = [(x0 + 22, "A3", f"{self.scale_label}"), (x0 + 62, "日付", pr["date"]),
                 (x0 + 112, "設計", pr["designer"])]
        for cx, lab, val in cells:
            self.line(P(cx, ys[3]), P(cx, ys[2]), "G-TITLE")
            self.text(lab, P(cx + 1.5, ys[3] + 2.6), 2.0, "G-TITLE")
            self.text(val, P(cx + 10, ys[3] + 2.4), 2.6, "G-TITLE")
        self.text("段階", P(x0 + 2, y0 + 3.4), 2.2, "G-TITLE")
        self.text(f"{pr['phase']}　／　本図は建築基準法令に基づく計画段階の検討図であり、確認申請・構造計算・関係機関協議により確定する",
                  P(x0 + 24, y0 + 3.4), 1.9, "G-TITLE")
        # 図番
        bx = W - m - 34
        self.line(P(bx, ys[3]), P(bx, ys[1]), "G-TITLE")
        self.text("図番", P(bx + 1.5, ys[1] - 3.0), 2.0, "G-TITLE")
        self.text(self.number, P(bx + 17, ys[2] + 1.0), 6.0, "G-TITLE", "BOTTOM_CENTER")

    def save(self, path):
        self.doc.saveas(path)


# --------------------------------------------------------------- text width
def _cw(ch):
    return 0.78 if ord(ch) < 0x2000 else 1.38


def _text_width(s, h):
    return sum(_cw(c) for c in s) * h


def _wrap(s, width, h):
    out = []
    for para in s.split("\n"):
        cur, w = "", 0.0
        for ch in para:
            cw = _cw(ch) * h
            if w + cw > width and cur:
                out.append(cur)
                cur, w = "", 0.0
            cur += ch
            w += cw
        out.append(cur)
    return out or [""]


# ------------------------------------------------------------- rendering
def render(sheet: Sheet, png_path=None, pdf=None, dpi=130):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration, LineweightPolicy
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    W, H = Sheet.PAPER
    fig = plt.figure(figsize=(W / 25.4, H / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    cfg = Configuration(lineweight_policy=LineweightPolicy.ABSOLUTE, lineweight_scaling=1.0,
                        background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                        min_lineweight=0.1)
    ctx = RenderContext(sheet.doc)
    Frontend(ctx, MatplotlibBackend(ax, adjust_figure=False), config=cfg).draw_layout(sheet.msp, finalize=True)
    x0, y0 = sheet.P(0, 0)
    x1, y1 = sheet.P(W, H)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    if png_path:
        fig.savefig(png_path, dpi=dpi, facecolor="white")
    if pdf is not None:
        pdf.savefig(fig, facecolor="white")
    plt.close(fig)
