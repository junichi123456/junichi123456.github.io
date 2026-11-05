# SPEC_FINAL20: sched3 の3戦3勝20構築による総当たり（final20）

作成: Opus 5.5 / 実装: Sonnet 5.5 / 対象: `pokechamp/tool/roundrobin.py` のみ（Star Crusade・game_watch.py は対象外）

## 0. 現状（2026-11-05 時点の確認値）
- `pokechamp/logs/refine/s3_plan.json`（151構築）・`s3_games.json`（227戦、例外0）。3/3勝の構築はちょうど **20**（リザホーク `db0baa2843d2bd4b` を含む）。
- 3/3 同士は sched3 で対戦していないため、`s3_plan.json` の `sel` に再利用できる組は現状 **0件**（再利用処理は実装するが、実際には380件の選出を新規計算する前提）。

## 1. コマンド
`python roundrobin.py final20 plan|run|report|selftest [--out-dir D] [--procs 4] [--force] [--max-games N] [--retry-errors] [--no-playbook]`
- sched3 と同じ parser 共通引数（`run/deny/adapt/counter/sched3` に付けているもの）を `final20` にも付ける。既存サブコマンドの挙動・既存ファイルは一切変えない。
- 出力: `logs/refine/f20_plan.json` / `f20_games.json` / `f20_logs.jsonl` / `f20_report.md`（`f20_paths(out_dir)`、`s3_paths` と同形）。
- 定数: `F20_VERSION='f20v1'`、深さ・deny は `S3_DEPTH`/`S3_DENY` を流用、`F20_N=20`。

## 2. plan
1. `s3_paths` の plan/games を読み（無ければ停止）、`s3_games.plan_sig == s3_plan.sig` を確認。`s3_stats` で各構築の (勝, 戦数, 残HP差) を得る。
2. 対象 = 勝==戦数==3 の構築。**20個ちょうどでないとき**: 全構築を (勝率↓, 残HP差合計↓, id↑) で並べ、多ければ3/3の中で上位20に切り詰め、少なければ次点から足して20にする。採否理由（`'3/3'` / `'補充'`）と s3 成績を `plan['s3']` に保存。
3. 構築本体は `s3_build()` → `s3_apply_all`。対象に apply 失敗があれば停止（受け入れ条件: 全20 apply 成功）。`plan['teams'][i]` は `s3_plan['teams'][i]` をそのままコピー（静的スコア再計算しない）。
4. ペア: 対象 id を昇順に並べ i<j の190組、`a,b = pair_ab(x,y)`、k=0,1。キー `f20:{a}|{b}|{k}`、種 `zlib.crc32(f"f20{a}{b}{k}".encode())`、**k 偶数で side0=a、奇数で side0=b**。
5. 選出: 必要な順序付き組 `X|Y`（380件）について、`s3_plan['sel']` に同キーがあればコピー（`plan['sel_src'][key]='s3'`）、無ければ `cmd_select(P, plan, 0, procs, pairs)`（= `_job_decide`/`decide_pair`、ガイド/基本・24通り候補）で計算。1件ごとの保存・再開は cmd_select の既存挙動に従う。
6. `sig = sha256(json(sorted ids の rr_team) + F20_VERSION + depth + s3_plan.sig)`。既存 plan と sig 不一致なら停止、`--force` で日時付き退避して作り直し（s3 と同じ）。
7. 終了時に「N=20、190組×2=380戦、再利用選出 x件、新規 y件」と時間見積もりを表示。

## 3. run
- `_job_s3` と `s3_record` をそのまま再利用（キーの解析は `f20:` 用に `rsplit` 等で a,b,k を取る別関数 `f20_record` にしてよい。記録項目は s3_record と同じ＋`k`）。
- 開始時に `pb_guard(games)`（playbook 既定オン、`--no-playbook` で切替）。`games.plan_sig` 不一致なら停止。
- 1戦ごとに `safeio.write_json` で atomic 保存、ログは `f20_logs.jsonl` に追記。`done_game` で済みを飛ばす（中断→再実行で続きから）。`--max-games`、`--retry-errors` は s3 と同じ。4並列既定。
- 30手で決着しない場合の判定（judged）は blind_play の既存動作のまま。

## 4. report（`f20_report.md`）
1. 冒頭: リザホーク（あれば）・R11（あれば）の順位、完了戦数/380、判定決着数、例外数。
2. ランキング表: 順位・id・タイトル・勝/38（引分0.5）・勝率・Wilson 95%（既存 `wilson()`）・平均残HP差・s3成績（3-0 等、補充なら印）。
   並び: 勝率↓ → **直接対決**（同率グループ内の相互対戦だけでの得点↓。3者以上も同様のミニリーグ）→ 平均残HP差↓ → id↑。
3. 勝敗行列 20×20（行=自分、セル=対その相手の得点 0/0.5/1/1.5/2、未実施は `-`、対角 `・`）。列見出しは順位番号、行に順位＋id 先頭8桁。
4. 上位5構築それぞれの「強い相手」（2-0 した相手）と「弱い相手」（0-2 した相手、無ければ 0.5〜1 の相手）。
5. sched3 との比較: 全員 s3 は 3-0 のため、「s3 での相手の s3 勝率平均（相手の強さ）」と final20 勝率の並置、Spearman 順位相関（s3 残HP差順 vs final20 順位）。
6. 注意: 38戦の Wilson 区間幅は約±15pt。区間が重なる構築は区別できない。選出は固定（ガイド/基本）でブラインド、5手読みAI同士の結果であり実戦の強さそのものではない。

## 5. selftest（本番ファイルに触れない）
一時 `--out-dir` に s3 の plan/games をコピーして実行。確認項目:
1. 対象が20個・全員 apply 成功・3/3 判定が s3_stats と一致。2. 3/3 が20以外の合成データ（3/3 を21個・19個）で切り詰め/補充が規則どおり。
3. ジョブ380件・重複なし・種=crc32("f20{a}{b}{k}")・k の偶奇で左右入れ替え。4. s3 sel にある組はコピーされる（合成で1件入れて確認）。
5. `--max-games 2` で2戦→再実行で残りに進む（再開）、games に2件、各戦後にファイルが妥当な JSON。
6. report が勝敗行列・Wilson・直接対決のタイブレーク（合成3者同率）を出す。7. 前後で `s3_*.json`・`logs/refine` 既存全ファイルの sha256 不変。
selftest 中の実戦は深さを小さくしてよい（`--max-games` 分のみ）。

## 6. 時間見積もり
- 対戦: 380戦 × 約65秒 ÷ 4並列 ≈ **約103分**（50〜80秒想定で 80〜127分）。
- 選出: 380件 × 約7秒 ÷ 4 ≈ **約11分**（plan 時）。合計 約2時間。`s3_estimate` 相当の表示を f20 でも出す。

## 7. 受け入れ条件（Opus が確認）
1. `python3 -m py_compile tool/roundrobin.py` 成功。2. `final20 selftest` 全項目 OK。
3. `final20 plan` で20構築すべて apply 成功・対象 id が s3 の 3/3 と一致（リザホーク含む）。
4. 中断→再実行で済みの戦を再計算しない（selftest 5）。
5. `logs/refine/s3_*`・`rr_*` など既存結果ファイルの sha256 が実装前後で不変。既存 `sched3 selftest` も OK。
6. **実装者は `final20 run` の本番（380戦）を実行しない。** plan の選出計算も本番フォルダでは実行せず、selftest の一時フォルダのみ。
