# 操作可能なデータ形式の開き方（v4.31）

`dist/export/` に、既製ソフトで開いて回転・計測・編集・再利用できる形式で書き出してあります。図面（`dist/dxf/*.dxf`・PDF・PNG）と GLB は従来のままです。
基本計画段階のモデルで、**実施設計の精度はありません**（家具・照明は仮置き、敷地は地図からの推定 ±5%）。再生成は `cd rc-building && python3 src/build.py --export-only [--with-blend]`。

| ファイル | 形式 | 座標系・単位 | 向いている用途 |
|---|---|---|---|
| `kawazanyo_IFC4.ifc`（大きいときは `.ifc.zip`） | IFC4 | 建物ローカル・mm | 設計者への引継ぎ（壁・床・窓・扉・室・階段・家具・照明・外構） |
| `model_exterior_obj.zip` / `model_interior_obj.zip` | OBJ+MTL | 真北ワールド・m・Y 上 | 汎用メッシュ（Blender・Rhino・SketchUp Pro・MeshLab） |
| `kawazanyo_exterior.blend` / `kawazanyo_interior.blend` | Blender | 真北ワールド・m | カメラ（外観 7・内装 36）・太陽・照明つきで撮り直す |
| `model_exterior.fbx` / `model_interior.fbx` / `model_exterior.usdz` | FBX / USDZ | 真北ワールド・m | Unity・Unreal・Maya・3ds Max／Mac・iPhone の AR |
| `schedules.xlsx` と `csv/*.csv` | 表 | mm・m² | 室・建具・仕上・設備・照明・家具・壁量・法規の一覧 |
| `site.geojson` / `site.kml` | GeoJSON / KML | WGS84 経緯度 | 敷地・寄付地・外構を地図上で扱う |
| `model_3d.dxf` | 3D DXF（MESH、R2010） | 建物ローカル・mm | AutoCAD・FreeCAD・BricsCAD で平面 DXF と重ねる |
| `manifest.json` | — | — | ファイル名・形式・サイズ・sha256・版・座標系 |

GLB（`dist/model.glb`・`dist/model_interior.glb`）は Web ビューア・Blender・Windows の 3D ビューアでそのまま開けます。

## 座標と向き（共通の約束）
- **建物ローカル**（IFC・3D DXF）：原点 = 通り芯 X1・Y1 の壁芯交点、z=0 = 設計 GL（TP+109.0m）、+X = X1→X4、+Y = Y1→Y4、単位 mm、Z 上。既存の平面 DXF と同じ原点・向き（平面 DXF は用紙座標の図面があるため、重ねるときは建物の X1・Y1 交点を基点に合わせる）。
- **真北ワールド**（OBJ・FBX・USDZ・.blend・GLB）：建物中心まわりに回転して、真北が −Z（Blender では +Y）、東が +X、単位 m。
- **真北**：建物の南面は真南から西へ約 12.3° 振れています。IFC は `TrueNorth` と `IfcMapConversion`（Eastings/Northings = X1・Y1 交点の局所 ENU、XAxisAbscissa/Ordinate = cosα/sinα、OrthogonalHeight = 109.0、Scale = 0.001）で持ちます。局所 ENU は国土地理院ベクトルタイル由来で、測量後に平面直角座標（IX 系、EPSG:6677）へ置換します。
- **階の標高**：基礎 FDN = −350、1FL = GL+1,500、2FL = GL+4,900、RFL = GL+8,300、パラペット天端 GL+8,900（mm）。
- **名前**：メッシュ系は `グループ|階|材質キー|ID`（GLB と同じ）。IFC は `Name` = 記号・室名、`Tag`、`ObjectType` = 和名。3D DXF のレイヤーは `3D-<階>-<カテゴリ>`（例 `3D-1F-WALL`、`3D-SITE-FENCE`、`3D-SITE-BOUNDARY-OLD`）。
- **要確認・仮置き**：IFC は `Pset_Kawazanyo`（要確認・仮置き・根拠・色コード・材質キー）、表は「要確認」「仮置き」列に ○。登録は `data/export_flags.yaml`。

## 無料ソフト
- **FreeCAD**（IFC・3D DXF）：ファイル → 開く（BIM ワークベンチ）。IFC は単位 mm のまま読み込まれます。3D DXF は DXF のインポート設定で「MESH を読む」。
- **BlenderBIM / Bonsai**（IFC の編集）：Blender に Bonsai を入れて IFC を開く。`Pset_Kawazanyo` で要確認の部材を絞り込めます。
- **BIMvision**（IFC 閲覧・計測・Pset 確認）：IFC をそのまま開く。
- **Blender**（.blend・OBJ・FBX・GLB）：.blend はカメラ一覧（`C01`〜、`Z1-11a`〜）から視点を選ぶ。OBJ・FBX は単位 m で読む（OBJ は「Forward −Z、Up Y」）。.blend の材質は色と手続き生成のみで、写真テクスチャは含みません（CG の画像は `dist/render/`）。
- **Windows の 3D ビューア・Mac のクイックルック**：GLB／OBJ／FBX／USDZ（クイックルックは USDZ。iPhone では AR 表示）。
- **QGIS**：`site.geojson` を追加、CRS は EPSG:4326。**Google Earth**：`site.kml` を開く（GeoJSON は非対応のため KML を併記）。**geojson.io** にも貼れます。
- **Excel 互換**（Excel・Numbers・LibreOffice・Google スプレッドシート）：`schedules.xlsx`。CSV は UTF-8（BOM 付き）。
- **LibreCAD・Jw_cad**：2D の `dist/dxf/*.dxf` のみ。**3D DXF は開けません**（3D 非対応）。
- **SketchUp Free**：制限あり・要確認（OBJ/IFC の可否は版による）。

## 有料ソフト
- **Revit**：IFC は「リンク」を推奨。共有座標は `IfcMapConversion` で合わせます。IFC の単位は mm。
- **ArchiCAD**：IFC 変換設定で「プロジェクト北」を `TrueNorth` に合わせる。
- **AutoCAD**：3D DXF を開く（MESH は 2010 以降）。`INSUNITS` = mm（4）に設定済み。向きを真北に合わせるときは UCS を回転。
- **Rhino・SketchUp Pro**：OBJ（または IFC）。

## 既知の制限
- 家具・照明・足元灯は仮置き／仮定値（v4.16）。ジム機器・蓄電池・機械は簡易ボリューム。
- 内装 CG の旧配色（I04〜I13 等）は形式に関係なくモデル側が正（モデルは最新）。
- IFC の開口は箱で表現（窓・扉は薄い箱。サッシの框・ヒンジの形状は無い）。IfcSpace の面積は室の面積表の値（形状は壁芯の矩形）。敷地内の地形は 2m グリッド、周辺建物・遠景地形は OBJ・FBX・.blend のみ。
- 敷地は地図からの推定（±5%）。寄付地は市へ割譲する提案で、法的扱いは要確認。
- IFC2X3 は出していません（IFC4 の `IfcMapConversion` と `IfcTriangulatedFaceSet` を使うため）。`--ifc-schema IFC2X3` は未実装です。
- 動作確認：ifcopenshell 0.9.0（読み戻し・スキーマ検証）、Blender 5.2（bpy。.blend・FBX・USDZ の読み戻し）、trimesh、openpyxl、shapely、ezdxf。**FreeCAD・BIMvision・Revit・ArchiCAD・AutoCAD・QGIS・Google Earth・SketchUp での目視確認はしていません**（手元に無いため。開けなかった場合は知らせてください）。
