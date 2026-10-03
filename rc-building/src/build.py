"""図面一式・法規チェック・3D モデルを生成するエントリポイント。

    python3 src/build.py            # rc-building/ で実行
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

import legal  # noqa: E402
import sheets  # noqa: E402
from cadlib import render  # noqa: E402
from design import Building  # noqa: E402
from model3d import export_glb  # noqa: E402


def main():
    b = Building(ROOT / "spec.yaml")
    dist = ROOT / "dist"
    for d in ("dxf", "png"):
        (dist / d).mkdir(parents=True, exist_ok=True)

    body = [
        sheets.site_plan(b, "A-01"),
        sheets.floor_plan(b, "1F", "A-02"),
        sheets.floor_plan(b, "2F", "A-03"),
        sheets.floor_plan(b, "3F", "A-04"),
        sheets.floor_plan(b, "RF", "A-05"),
        sheets.elevations_sheet(b, "A-06"),
        sheets.section_sheet(b, "A-07", "A"),
        sheets.section_sheet(b, "A-08", "B"),
        sheets.fittings_sheet(b, "A-09"),
    ]
    lsheets, rows, sm = sheets.legal_sheets(b, 10)
    body += lsheets
    body += [
        sheets.struct_plan(b, "S-01", "FDN"),
        sheets.struct_plan(b, "S-02", "2F"),
        sheets.struct_plan(b, "S-03", "3F"),
        sheets.struct_plan(b, "S-04", "RF"),
        sheets.member_list(b, "S-05"),
    ]
    dl = [(s.number, s.title, s.scale_label) for s in body]
    cover = sheets.cover_sheet(b, [("A-00", "表紙・図面リスト・建築概要", "—")] + dl)
    all_sheets = [cover] + body

    index = []
    with PdfPages(dist / "drawings.pdf") as pdf:
        for s in all_sheets:
            stem = f"{s.number}"
            s.save(dist / "dxf" / f"{stem}.dxf")
            render(s, dist / "png" / f"{stem}.png", pdf)
            index.append(dict(number=s.number, title=s.title, scale=s.scale_label,
                              dxf=f"dist/dxf/{stem}.dxf", png=f"dist/png/{stem}.png"))
            print("sheet", s.number, s.title)

    export_glb(b, dist / "model.glb")
    write_report(b, rows, sm, dist)
    (dist / "index.json").write_text(json.dumps(dict(sheets=index, summary=jsonable(sm),
                                                     checks=rows), ensure_ascii=False, indent=1), encoding="utf-8")
    ng = [r for r in rows if r["result"] == legal.NG]
    print(f"checks: {len(rows)} rows, NG={len(ng)}")
    for r in ng:
        print("  NG:", r["item"], r["planned"])


def jsonable(sm):
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in sm.items()}


def write_report(b, rows, sm, dist):
    lines = ["# 法規チェック結果（自動生成）", "",
             f"- 敷地面積 {sm['site_area']:.2f} m² / 建築面積 {sm['building_area']:.2f} m² / 延べ面積 {sm['total']:.2f} m²",
             f"- 建ぺい率 {sm['coverage'] * 100:.2f}% / 容積率 {sm['far'] * 100:.2f}% / 建築物の高さ {sm['height']:.2f} m", "",
             "| 区分 | 項目 | 根拠 | 規定・要求 | 計画 | 判定 |", "|---|---|---|---|---|---|"]
    for r in rows:
        cells = [r[k].replace("|", "／").replace("\n", " ") for k in ("cat", "item", "basis", "required", "planned", "result")]
        lines.append("| " + " | ".join(cells) + " |")
    (dist / "LEGAL_CHECK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
