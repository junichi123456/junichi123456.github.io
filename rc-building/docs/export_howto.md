# 操作可能なデータ形式の開き方（v4.31）

`dist/export/` に、既製ソフトで開いて回転・計測・編集・再利用できる形式で書き出してあります。図面（`dist/dxf/*.dxf`・PDF・PNG）と GLB は従来のままです。
基本計画段階のモデルで、**実施設計の精度はありません**（家具・照明は仮置き、敷地は地図からの推定 ±5%）。再生成は `cd rc-building && python3 src/build.py --export-only`（マスター .blend だけなら `--blend-only`、省くなら `--no-blend`。.blend・FBX・USDZ は bpy が必要）。

| ファイル | 形式 | 座標系・単位 | 向いている用途 |
|---|---|---|---|
| `kawazanyo_IFC4.ifc`（大きいときは `.ifc.zip`） | IFC4 | 建物ローカル・mm | 設計者への引継ぎ（壁・床・窓・扉・室・階段・家具・照明・外構） |
| `model_exterior_obj.zip` / `model_interior_obj.zip` | OBJ+MTL | 真北ワールド・m・Y 上 | 汎用メッシュ（Blender・Rhino・SketchUp Pro・MeshLab） |
| `kawazanyo_master.blend`（v4.33） | Blender | 真北ワールド・m | **CG の撮影用マスター**（カメラ 57・材質・照明・太陽つき。`src/shoot.py` で撮る。手で編集しない） |
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
- **Blender**（.blend・OBJ・FBX・GLB）：マスター .blend はカメラ一覧（`C01`〜、`I01`〜、`Z1-11a`〜）から視点を選ぶ（下の「マスター .blend」）。OBJ・FBX は単位 m で読む（OBJ は「Forward −Z、Up Y」）。
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

## マスター .blend から CG を撮る（v4.33）
**運用の約束**：①形状・色・家具・照明の変更は Python（`house.py`・`spec.yaml`・`data/*.yaml`）→ `python3 src/build.py`（マスター自動再生成）→ `shoot.py` で撮影。②Blender で手を入れるのは**オーバーレイだけ**。③オーバーレイの手編集は Python に戻らない（図面・GLB・IFC・数量には反映されない。設計の変更は `data/blend_overlay_requests.yaml` に **要確認** として記録し、Python 側で反映してから再生成）。④古いマスターでは撮らない（`model_hash` が合わないと終了コード 3。`--allow-stale` のときだけ警告つきで続行）。

撮影コマンド（`bpy` の入った python は `BPY_PYTHON`、既定 `.venv-bpy`）：
```
python3 src/shoot.py --camera Z1-11a --time 15:30 --date 03-21 --eye 1600 --out dist/render/interior/zones/
python3 src/shoot.py --camera I01,I03 --preview            # 480×270・16spp（外観は 960×540）を .cache/cg/shoot/preview/ へ
python3 src/shoot.py --all [--kind int|ext] [--floor 1F]   # 全カメラ（撮影済みで定義・引数が同じカットは飛ばす。--force で撮り直し）
```
`--camera` はカンマ区切り・ワイルドカード（`Z1-*`）・範囲（`I04-I13`）。ほかに `--res W H`・`--samples`・`--time-limit`・`--exposure`／`--exposure-add`・`--channels L,D`・`--dim 40`・`--no-overlay`・`--allow-stale`・`--tex-dir`・`--seed`（既定 0）・`--background`（nohup で実行し、進捗を `.cache/cg/shoot/progress.json` に書く。中断後は同じコマンドで未撮影から再開）・`--list`（カメラ一覧）・`--dry-run`。失敗したカットは `.cache/cg/shoot/failed.log` に記録して次へ進み、1 つでも失敗すれば終了コード 1。旧コマンド（`render_cg.py`・`render_cg.py --interior`・`render_zones.py`）は引数互換のラッパーで、内部で `shoot.py` を呼ぶ（`--legacy` で旧経路。v4.33 の 1 版だけ残す）。

### マスターの中身
- コレクション：`Exterior`／`Interior_1F`・`Interior_2F`／`Furniture`（階ごとの子）／`Lighting`／`Site`／`Cameras`（`Ext`・`Int_I`・`Int_Z`）／`Overlay`。
- 名前：オブジェクト名は `<階>.<ID>`（Blender の名前は 63 バイトまで）。GLB のノード名 `グループ|階|材質キー|ID` はカスタムプロパティ `glb_name`、IFC・CSV の記号は `tag`・`ifc_name`（家具 `L-T1`、建具 `SD-1`、照明 `1F-LDK-L1`、室は `階:室名`）。室・建具は形のない Empty（記号の照合用。形状は GLB 由来のメッシュ）。
- カメラ（57＝外観 C 7・内装 I 14・区画 Z 36）：`kind`・`floor`・`fl_mm`・`eye_mm`・`target`・`hfov`・`shift_y`・`pitch`・`exposure`・`wb`・`when`・`lamp_k`・`lamp_pct`・`channels`・`open_doors`・`also_1f`・`theater`・`exclude`・`def_hash`・`title`。
- 光源：`channel`（`L` ライン・`D` ダウンライト・`F` 階段足元灯）・`kelvin`・`lm`・`room`・`tag`。時刻ごとの点灯・調光は Scene の `light_schedule`。太陽・HDRI は Scene の `sun_date`・`sun_time`・`lat`・`lon`・`tz`・`true_north_deg`・`hdri_id`。**ドライバは使わない**ので、GUI で開くと保存時の値（既定 3/21 15:30）のまま見える。撮影時に `shoot.py` が日付・時刻から設定する。
- バージョン：Scene の `model_version`・`model_hash`（house.py・spec.yaml・data/*.yaml・形状に関わる src の sha256）・`generated_at`・`git_commit`・`bpy_version`・`gen_signature`。マスターを手で保存し直すと `gen_signature` が合わなくなり、`shoot.py` が警告して render_log に `master_hand_edited` を記録する（次の build で上書きされる）。
- 外観 GLB（`model.glb`）と内装 GLB（`model_interior.glb`）の統合：内装 GLB は外観 GLB のほぼ上位集合なので、同名のノードは内装側の 1 つにまとめ、外観にだけあるノード（`ジム機器|1F|equipment`・`建具|1F|interior_door`・`建具|2F|interior_door`）を足してある。`建具|1F|glass` は内装 GLB のほうが扉（GD-1・GD-2）のガラスを別ノード（`扉|…`）で持つため頂点数が違う（外観 64・内装 48）。外観カットでは `shoot_modes = int` のもの（家具・台所小物・照明器具・内装仕上げ・外付けスクリーン生地・遠景の木）を隠し、内装カットでは `ext` のもの（上の外観専用ノード・窓の発光面・外構照明）を隠す。窓ガラス・天井・階段・壁の保険マスクは外観用・内装用の 2 種の材質を持ち（`glass_role`・`mat_ext`・`mat_int`）、撮影モードで切り替える。

### オーバーレイ（手編集）
1. `python3 src/shoot.py --init-overlay` で `data/blend/kawazanyo_overlay.blend`（空の `Overlay` コレクションだけ）を作る。または Blender で新規ファイルを作り、`File > Link` でマスターを参照用に読み込んでもよい（`_ref_master` コレクション。撮影時には使わない）。
2. `Overlay` コレクションに、追加オブジェクト（小物・人物・植栽）・追加カメラ・演出用ライトを入れて保存。追加カメラ（名前は自由、`Cameras` ではなく `Overlay` の中）は `--camera <名前>` で撮れる。属性 `when`・`exposure`・`wb` を付けると既定を変えられる。
3. マスターの要素の**非表示**は、`Overlay` コレクションの属性 `hide_master` に GLB 名・タグ・オブジェクト名の JSON リスト（例 `["L-C3", "1F.L-T1"]`）を入れる。
4. 撮影時、`shoot.py` はオーバーレイの `Overlay` コレクションだけを `link=True` で入れる（マスターを再生成しても手編集は消えない）。`--no-overlay` で外す。
5. **やってはいけない**：マスターの要素の移動・寸法・材質の変更（ライブラリオーバーライド）。設計の変更は `data/blend_overlay_requests.yaml` に要確認として記録し、Python 側で反映する。

### テクスチャとピンク表示
写真テクスチャ（Poly Haven、CC0）は .blend に**パックしない**（リポジトリに入れない）。置き場は既定 `.cache/cg/`（環境変数 `KAWAZANYO_TEX` または `--tex-dir` で変更）。`shoot.py` は撮影前に取得する。.blend 内の画像は相対パス `//../../.cache/cg/<file>` なので、Blender の GUI で開いてテクスチャが無いと**ピンク（マゼンタ）に見える**。その場合は `File > External Data > Find Missing Files` でテクスチャの置き場を指すか、`shoot.py` で撮る（無い画像は同じ平均色の単色に置き換えて撮り、render_log の `texture_fallbacks` に記録する）。

### 所要時間・容量
マスターの生成は約 8 秒（描画なし。GLB 取込と材質構築のみ、実測）。タイムアウト 15 分。容量は約 2.4MB（目標 10MB 以下、15MB を超えたら生成失敗として旧ファイルを残す）。旧 `kawazanyo_exterior.blend`・`kawazanyo_interior.blend` はマスターに置き換えて削除した。`build.py` は入力（`model_hash`）が前回と同じならマスター・FBX・USDZ を作り直さない（`--blend-only` で強制）。

### 旧カット I04〜I13 の撮り直し（今回はしない）
`python3 src/build.py` → `python3 src/shoot.py --camera I04-I13 --force` → 1 枚目を縮小して確認 → 帯の版表記が v4.29 配色になっていることを確認 → コミット。
