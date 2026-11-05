# SPEC_SCHED3: 各構築3戦・5手読みブラインドテスト（`roundrobin.py sched3`）

作成: Opus 5.5 / 実装: Sonnet 5.5 / 対象: `pokechamp/tool/roundrobin.py` のみ（Star Crusade・game_watch.py は対象外）

## 0. 目的
pokesol 学習後の `known_teams.json`（＋`new_teams_m6b.json`、`raw_teams()` と同じ）の**全構築＋R11** を、各構築ちょうど3戦（例外1構築のみ4戦）の対戦表で戦わせ、平均勝率の順位を出す。
条件: 両側 5手読み `(5,5)`、ケア deny 両側オン `(True,True)`、プレイブック既定オン（`--no-playbook` で切）、ブラインド、選出は既存 `decide_pair`（記事→ガイド条件→ガイド基本→24通り候補から `rr_select`）。
現時点の見込み: 構築 148（全て `rr_team` 化可能を確認済み）＋R11 ＝ N=149（奇数）→ 224 戦。

## 1. コマンド（後方互換。既存サブコマンドの挙動・既存結果ファイルは一切変えない）
```
python3 roundrobin.py sched3 plan   [--procs 4] [--force] [--test-ids a,b,c,d] [--out-dir D]
python3 roundrobin.py sched3 run    [--procs 4] [--max-games N] [--retry-errors] [--no-playbook] [--out-dir D]
python3 roundrobin.py sched3 report [--out-dir D]
python3 roundrobin.py sched3 selftest [--out-dir D(既定は一時フォルダ)]
```
出力（既定 `logs/refine/`）: `s3_plan.json`、`s3_games.json`、`s3_logs.jsonl`、`s3_report.md`。`S3_VERSION='s3v1'`、`S3_DEPTH=(5,5)`。

## 2. plan
1. 構築の組み立ては `cmd_plan` の 752〜763行・783〜795行（`rr_team`→`sort_key`、`r11_team()`、`_job_static`、`build_candidates`＋`GUIDE_OVERRIDES`）と**同じ処理**を使う。共通部分は `build_rr_teams(procs)` のような関数に切り出してよいが、`cmd_plan` の出力（rr_plan.json）は不変であること。
2. 各構築に `rr_apply` を試し、失敗したものは `excluded:[{id, reason}]` に記録して対戦表から外す（受け入れ時は 0件が期待値）。
3. **並べ方（強さに偏らない）**: `ids` を `sha256(("s3"+id).encode()).hexdigest()` の昇順に並べる（rating は使わない）。
4. **対戦グラフ**（位置 i=0..N-1、`m=N//2`）:
   - 環: (i, i+1 mod N) の N本。
   - N 偶数: 対角 (i, i+m) を i=0..m-1 の m本 → 全員次数3、総 3N/2 戦（N≥4）。
   - N 奇数（m=(N-1)/2）: 対角 (i, i+m) を i=0..m-1（ノード N-1 以外が次数3）、加えて (N-1, m-1) の1本 → **位置 m-1 の構築だけ次数4**、総 (3N+1)/2 戦（N≥7）。
   - 重複辺・自己辺が無いことを plan 時に assert。N<4（偶数）/N<7（奇数）はエラー終了。
5. 辺リストは上の順（環→対角→追加）で番号 e を振る。正規形 `(a,b)=pair_ab(x,y)`、左右は e が偶数なら X=a,Y=b、奇数なら X=b,Y=a。鍵 `s3:{a}|{b}`、種 `zlib.crc32(f"s3{a}{b}".encode())`。
6. 必要な選出 (X|Y),(Y|X) を全辺について `_job_decide` で計算（4プロセス、`cmd_select` と同様に1件ごと保存）し `plan['sel']` に保存。
7. `s3_plan.json` = `{version, created, depth:[5,5], deny:[true,true], sig, ids(ハッシュ順), excluded, teams, edges:[{e,a,b,X,Y,seed,key}], degree:{id:n}, extra4:id|null, sel}`。
   `sig = sha256(json.dumps([teams[i] for i in sorted(ids)], ensure_ascii=False, sort_keys=True) + S3_VERSION + "5,5")`。既存 plan と sig が違えば停止、`--force` で日時付きに退避して作り直し（`cmd_plan` と同じ流儀）。同じ sig なら選出済み分を再利用（再開）。
8. 終了時に表示: N、総試合数、次数分布、extra4 の構築、時間見積り（§4）。

## 3. run
- `_job_deny` と同じ形の `_job_s3`（depth を引数で受け取り `R.blind_play(... S3_DEPTH[0], S3_DEPTH[1] ..., deny=(True,True)) + _pb_args(X,Y)`）。グローバル `DEPTH` は書き換えない。
- `s3_games.json` = `{version, plan_sig, depth, deny, playbook:_pb_sig(), games:{key: rec}}`。rec は `deny_record` と同じ項目（a,b,side0,side1,sel0,sel1,seed,res,winner,judged,turns,left,faints,sec,error,deny_stats,pb）。plan_sig 不一致・`pb_guard` 不一致で停止。
- 1戦ごとに `safeio.write_json` で atomic 保存、ログは `append_log` で `s3_logs.jsonl`。再実行時は済みの鍵を飛ばす（`--retry-errors` で res=None を再試行）。`--max-games N` で打ち切り。進捗表示は `run_deny_jobs` と同形式。

## 4. 時間見積り（plan と run 開始時に表示）
実測: deny＋4手読み 1戦 平均 25.6秒（rr_deny_games.json 1800戦）。5手読みで約2〜3倍 → 1戦 50〜80秒（ワーカー時間）。
4プロセスで実時間 12〜20秒/戦 × 224戦 ≈ **45〜75分**。選出 448件 × 約7秒 / 4 ≈ 13分、静的スコア数分。**合計 約1〜1.5時間**。
`s3_games.json` に実測 sec があればその平均で再計算して表示。

## 5. report（`s3_report.md` と標準出力）
1. 前提: N、総戦数、深さ/deny/playbook/種の規則、excluded、extra4。
2. 構築ごと: 勝/戦数（引分0.5、res=None は戦数から除外し「例外」欄に数）、平均勝率、**95% Wilson 区間**（既存 `wilson()`）、平均残HP差（`left[自側]` 合計 − `left[相手側]` 合計、`_ct_hp` と同じ計算）、rating。
3. ランキング: 勝率降順 → 平均残HP差降順 → rating 降順（rating 無しと R11 は最後）→ id。
4. **R11 と リザホーク `db0baa2843d2bd4b` の順位**を冒頭に明記（同率の構築数も）。
5. 上位10の対戦内訳: 相手名（短縮）・先後・勝敗・手数・判定かどうか。
6. 判定決着数（`judged` 真）と例外数。
7. 注意書き（必ず）: 「1構築3戦のみで誤差が非常に大きい（3戦全勝でも95%区間は約44〜100%）。上位は偶然の可能性が高く、順位は参考値。確かめるには上位同士の追加対戦が必要」。

## 6. selftest（実装者が実行するのはこれだけ。本番 plan/run は実行しない）
1. グラフ: N=4..40 の全てで 自己辺/重複辺なし、偶数は全員次数3、奇数は1構築だけ4・他は3、辺数 = ⌈3N/2⌉、同じ入力で同じ結果、並びが rating と無関係（ids の順を入れ替えても辺集合同一）。
2. 全構築 apply: `raw_teams()` の全構築＋R11 に `rr_team`→`rr_apply` が例外なく通る（失敗は id を表示して NG）。
3. 小規模実戦: 一時フォルダで `--test-ids`（4構築、偶数）、深さを selftest 専用に (1,1) へ下げてよい。`run --max-games 2` → 再実行で残りだけ実行され、先の2戦の rec が不変（再開）。種＝crc32 規則、左右が偶奇で入れ替わっていること。
4. report が例外なく生成され、R11 行と注意書きを含む。
5. 既存ファイル sha256 不変（`_sha_all()` を前後で比較。`logs/refine/` の既存 rr_*/ad_*/ct_*/pb_* と data/）。

## 7. 受け入れ条件
- `python3 -m py_compile tool/roundrobin.py` が通る。
- `sched3 selftest` が全項目 OK。既存の `selftest --quick`・`deny selftest` の結果が変わらない（時間が許せば実行）。
- 全構築が apply でき excluded=0、次数は全員3（N奇数時は extra4 の1構築のみ4、report に明記）。
- 中断→再実行で再開でき、済み試合は再計算されない。既存結果ファイルの sha256 不変。
- 本番（plan/run の実データ実行）は実装者は行わず、Opus が実行・確認する。
