# SPEC_M7RUN: 新構築 M7 × 蓄積構築50 × 10戦（5手読み・適応選出）

作成: Opus 5.5 / 実装: Sonnet 5.5 / 対象: `tool/roundrobin.py` のみ（Star Crusade・`game_watch.py` は対象外）。**実装者は本番（plan/run の全量）を実行しない。**

## 0. 目的
`tool/data/party/M7.json`（メガカイリュー・スターミー・フラエッテ(えいえんのはな)・ブリジュラス・ヒートロトム・エンブオー、設計 `logs/PARTY_M7_DESIGN.md`）を、蓄積構築の rating 上位50と各10戦（計500戦）させ勝率を測る。条件: 深さ (5,5)、ブラインド、deny 両側、プレイブックは相手側のみ（既定オン、`--no-playbook` で全オフ）、適応選出あり。

## 1. 追加するもの（既存 adapt は挙動・出力とも変えない）
新サブコマンド `python3 roundrobin.py m7 {plan|run|report|selftest} [--party M7] [--prefix m7] [--procs 4] [--force] [--max-games N] [--retry-errors] [--quick] [--keep] [--out-dir D] [--no-playbook]`。
既存関数は「既定値で従来と同じ」キーワード引数の追加だけ許す（例 `ad_hist(..., kp='ad')`、`ad_record(..., seed_fn=ad_seed)`、`_job_adapt` は job 末尾に省略可能な `depth`、無ければ `DEPTH`）。`DEPTH`・`AD_*`・`r11_team()`・`adapt` の sig/seed/キーは変更禁止。

- 定数: `M7_VERSION='m7a'`, `M7_DEPTH=(5,5)`, `M7_ID='M7'`。ファイル: `logs/refine/m7_plan.json` / `m7_games.json` / `m7_logs.jsonl`、レポート `logs/M7RUN.md`（`--out-dir` 指定時はその中の `M7RUN.md`）。
- **party_team(name, tid)**: `data/party/{name}.json` → rr_team 形式（`r11_team` と同じ形、id=`M7`、title=`M7（新構築案）`、rank/final/peak=None、weight=1.0）。`species in B.BASE_OF` ならメガ: base=`B.BASE_OF[species]`、`mega=True`、`ability`=JSON の値（メガ後）、`base_ability`=JSON に `base_ability` があればそれ、無ければ JSON の ability が `POKE[base]['ab']` に含まれればそれ、それも無ければ `POKE[base]['ab'][0]`。→ カイリュー（メガ前）は **マルチスケイル**（r11 方式の ab[0]=せいしんりょく にしない）。item はそのまま（カイリュナイト）、`stone=False`、`label` は無視。**メガ持ちが1体でなければ SystemExit。**
- **チーム集合**: `s3_plan.json`（151構築、R11含む）の `teams` をそのまま使い、M7 を追加した dict を pool に渡す（`make_pool(procs, teams)`）。M7 の `static` は pool で `_job_static('M7')`、候補は `build_candidates(rt, None, ws['M7'], ov)`。他構築の teams は再計算しない。
- **相手集合（adapt と同じ規則）**: s3 の ids から R11 と M7 を除き `sort_key` で並べ、rank/final/peak のいずれかを持つものの先頭50。リザホーク `db0baa2843d2bd4b` は除外しない（確認済み: 適格140中8番目なので50に入る）。`rr_apply` 失敗は skipped に記録して次で埋める。
- **plan**: sig = sha256(s3 sig + json(M7 rt, sort_keys) + ','.join(opps) + M7_VERSION + '5,5')。既存 m7_plan の sig 違いは `--force` 無しで停止、ありで日時付き退避（adapt と同じ）。`sel1` に `M7|X` と `X|M7` の100件を `_job_decide`（decide_pair）で4並列計算: M7 はガイド無し→基本選出（rr_select over candidates）、相手はガイド→基本。plan に `candidates`（M7の24通り）、`excluded_no_mega`（外れたメガなし並び）を保存。
- **run**: `cmd_adapt_run` と同じ駆動（相手ごとに1本ずつ、ペア内10戦は順番、同時最大 `--procs`=4）。k 偶数=M7 が side0、奇数=相手が side0。キー `m7:{X}|{k}`、種 `zlib.crc32(f"m7{X}{k}".encode())`、深さ `M7_DEPTH`、deny `(True,True)`、`_pb_args(s0,s1)`（`_PB` に M7 は無いので相手側だけになる。`'M7' in _PB` なら起動時に停止）。選出は `adapt_select`（第1戦=sel1、第2戦以降=履歴で適応、2連続同一選出の禁止含む）を `_AD['sel1']=plan['sel1']` で使う。1戦ごとに `safeio.write_json` で m7_games.json（sel0/sel1/why0/why1/faints/left/judged/turns/sec/sec_sel/seed/n/main_side）を保存し、ログを m7_logs.jsonl に追記。`pb_guard`・`plan_sig` 照合あり。再開は未完のキーから。

## 2. 24通り制約（M7 版）— **当初規則をそのまま適用する**
並び＝先発＋後発2体（構築の並び順）。M7 はメガ1体なので全60並びがメガ2体除外に触れない。内訳: メガ入りの3体組 C(5,2)=10 組×先発3=**30並び**、メガなし C(5,3)=10 組×3=**30並び**。
規則「メガ入りが基本、メガなしは24中4まで、計24以内」は M7 でも満たせる（メガ入り30 ≥ 20）ので緩めない。候補＝既存 `build_candidates` の結果そのまま（メガなし上位4＋メガ入り上位20、順位は static 重み×先発率）。理由: (a) ユーザーの当初規則に一致、(b) リザホーク等と同じ枠で比較可能、(c) 設計書ではメガなし組も強い（最低1.170）が、それは report の「選出別勝率」と「外れたメガなし並び」で検証し、緩和は次段で判断する。M7 側の選出は必ず candidates 内（adapt_select の仕様どおり）。

## 3. report（`logs/M7RUN.md`）
1. 全体勝率（分=0.5、Wilson 95%）、完了数/500、例外数、判定決着数（judged=True）と平均手数。
2. 相手構築ごとの10戦（構築名・id8・rank・M7 視点の ○×△ 列・勝率）、勝率昇順。
3. 推移: 第n戦（n=1..10）ごとの全相手合計勝率、前半(1-5)/後半(6-10)。
4. M7 の選出別勝率（並び単位と3体組単位、回数≥1 全部、メガ入り/なし別の小計）、選出元（sel1 basic / adapt）別。
5. 最も負けた相手トップ10（勝率昇順、同率は負け数）と原因: 最初に倒れた M7 個体（faints の最初の M7 側）、M7 を倒した相手個体（killer 上位3＝相手の主力）、相手の並び上位2。
6. リザホーク比較: ADAPT.md の 58.0%（290/500、深さ4）を併記し、共通相手（M7 相手集合 ∩ ad_plan.opponents）だけの両者勝率も出す。M7 対リザホークの10戦は別行。深さ差（4 vs 5）を注記。
7. M7 の個体ごとの出番（選出回数・先発回数）と出た試合の勝率、倒した数・倒された数。メガカイリューはメガした試合数も。
8. 設定（深さ・deny・プレイブック署名・種式・plan sig・candidates 24 と外れたメガなし並び）。

## 4. 受け入れ条件（Opus が確認）
1. `python3 -m py_compile tool/roundrobin.py` が通る。
2. `m7 selftest`（`--quick` 可、出力は一時ディレクトリ、既定場所に m7_* / M7RUN.md を作らない）で全項目 OK:
   a. `party_team('M7')` が `rr_apply` できる。メガ1体、`B.MY['カイリュー']` が (メガ前 Mon 特性マルチスケイル, メガカイリュー Mon) で、対戦状態で M7 側 `can_mega` が真。
   b. 相手集合が50、R11・M7 を含まず db0baa28 を含み、上記規則の先頭50と一致。
   c. M7 candidates が24、メガ2体を含む並び0、メガなし≤4、全て all_orders 内。
   d. `adapt_select('M7', X, hist)` が candidates 内を返す（hist 空＝sel1、hist 2件同一＝その並びを禁止）。
   e. 種が crc32("m7{X}{k}")、k 偶奇で左右、job の深さが (5,5)、M7 側にプレイブック引数が渡らない。
   f. 再開: 2戦実行→中断→再実行で既存キーを再計算せず続きから（モックの play/select 可）。
   g. 1戦と選出決定の所要時間を実測し表示（実盤面1戦：目安 10〜20秒、選出 中央値≤15秒・最大≤30秒）。
3. 既存結果ファイルの sha256 が実装前後・selftest 前後で不変: `logs/refine/` の rr_*、ad_*、s3_*、f20_*、ct_* と `logs/ADAPT.md`、`tool/data/party/M7.json`。
4. 既存 `adapt selftest --quick` が従来どおり通る。

## 5. 時間見積もり
1戦 約10〜20秒（深さ5）＋選出 両側合計 約5〜20秒（第2戦以降）。500戦÷4並列 ≈ 40〜90分。plan: M7 static 数十秒＋sel1 100件 約2〜5分。
