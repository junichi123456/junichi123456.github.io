"""河沿要（仮称）図面一式・法規チェック・3D モデルを生成する。

    cd rc-building && python3 src/build.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

import house_legal  # noqa: E402
import house_sheets as hs  # noqa: E402
from cadlib import render  # noqa: E402
from house import House  # noqa: E402
from model3d import export_glb  # noqa: E402
from sheetlib import fittings_sheet, legal_sheets  # noqa: E402


def main():
    h = House(ROOT)
    dist = ROOT / "dist"
    for d in ("dxf", "png"):
        (dist / d).mkdir(parents=True, exist_ok=True)
    rows, sm, wq = house_legal.checks(h)
    wall_rows = [["階", "方向", "耐力壁長さ", "壁量", "判定"]]
    for (f, d), (L, q) in sorted(wq.items()):
        wall_rows.append([f, d, f"{L:.1f} m", f"{q:.1f} cm/m²", "≧12 適合" if q >= 12 else "不足"])
    wall_rows.append(["", "", "壁厚", f"{h.t / 10:.0f} cm", "≧15 適合"])

    body = [
        hs.site_plan(h, "A-01", sm),
        hs.exterior_plan(h, "A-02"),
        hs.gate_detail(h, "A-02D"),
        hs.floor_plan(h, "1F", "A-03"),
        hs.floor_plan(h, "2F", "A-04"),
        hs.roof_plan(h, "A-05"),
        hs.elevations(h, "A-06"),
        hs.building_sections(h, "A-07"),
        hs.site_sections(h, "A-08"),
        fittings_sheet(h, "A-09"),
        hs.openings_smoke_sheet(h, "A-10"),
    ]
    body += legal_sheets(h, 11, rows)
    body += [hs.wall_plan(h, "S-01", wall_rows), hs.details(h, "S-02"), hs.seismic_sheet(h, "S-03"), hs.energy_sheet(h, "M-01"), hs.orientation_sheet(h, "M-02"), hs.glazing_uv_sheet(h, "M-03"), hs.interior_policy_sheet(h, "I-01"), hs.finish_sheet(h, "I-02"), hs.wifi_sheet(h, "E-01"), hs.control_sheet(h, "E-02"), hs.insect_sheet(h, "E-03")]
    dl = [(s.number, s.title, s.scale_label) for s in body]
    cover = hs.cover(h, [("A-00", "表紙・図面リスト・計画概要", "—")] + dl, sm)
    sheets = [cover] + body
    index = []
    with PdfPages(dist / "drawings.pdf") as pdf:
        for s in sheets:
            s.save(dist / "dxf" / f"{s.number}.dxf")
            render(s, dist / "png" / f"{s.number}.png", pdf)
            index.append(dict(number=s.number, title=s.title, scale=s.scale_label,
                              dxf=f"dist/dxf/{s.number}.dxf", png=f"dist/png/{s.number}.png"))
            print("sheet", s.number, s.title)
    export_glb(h, dist / "model.glb")
    write_report(rows, sm, dist)
    (dist / "index.json").write_text(json.dumps(dict(sheets=index, summary={k: round(v, 3) for k, v in sm.items()},
                                                     checks=rows), ensure_ascii=False, indent=1), encoding="utf-8")
    ng = [r for r in rows if r["result"] == house_legal.NG]
    print(f"checks: {len(rows)} rows, NG={len(ng)}, 要確認={sum(r['result'] == house_legal.CHK for r in rows)}")
    for r in ng:
        print("  NG:", r["item"], r["planned"])


def write_report(rows, sm, dist):
    lines = ["# 法規チェック結果（自動生成）", "",
             f"- 敷地面積 {sm['site_area']:,.2f} m²（推定）／建築面積 {sm['building_area']:.2f} m²／延べ面積 {sm['total']:.2f} m²",
             f"- 建ぺい率 {sm['coverage'] * 100:.2f}%／容積率 {sm['far'] * 100:.2f}%／最高高さ {sm['height']:.2f} m", "",
             "| 区分 | 項目 | 根拠 | 規定・要求 | 計画 | 判定 |", "|---|---|---|---|---|---|"]
    for r in rows:
        cells = [str(r[k]).replace("|", "／") for k in ("cat", "item", "basis", "required", "planned", "result")]
        lines.append("| " + " | ".join(cells) + " |")
    (dist / "LEGAL_CHECK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
