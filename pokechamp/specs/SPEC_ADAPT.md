# 乾坤一擲リザホークの適応選出 500戦（4手読み・両側 deny・ブラインド）仕様書

- 執筆: Opus 5.5（仕様のみ）／実装: Sonnet 5.5／受け入れ確認: Opus 5.5
- 実装先: `pokechamp/tool/roundrobin.py` に `adapt plan|run|report|selftest` を追加（既存のコマンド・関数・結果ファイルは変えない）
- 変更しない: `battle.py`・`refine.py`・`search.py`・`engine.py`・`game_watch.py`、Star Crusade、既存の `logs/refine/rr_*`
- **実装者は本番（`adapt run` の全500戦）を実行しない。** `adapt selftest` までで止める。

## 0. 目的（ユーザー依頼）

メインパーティを **乾坤一擲リザホーク（id `db0baa2843d2bd4b`、以下 L）** にする。L の型は記事の型が真の型（`rr_plan.json` の `teams[L]` そのまま）。
L 対 50構築 × 各10戦 = **500戦** を、4手読み・**両側 deny**・ブラインドで行う。
**選出はお互いに、戦を重ねるごとに相手の過去の選出（3体＋先発）を既知とし、選出の対策に使う（適応選出、左右対称）。**

## 1. 現状（事実、コードで確認済み）

### 1.1 データ
- `tool/data/known_teams.json` 83構築（rating あり73）、`tool/data/new_teams_m6b.json` 6構築（rating なし）。
- `logs/refine/rr_plan.json`（`version`,`sig`,`order`(83),`tiers`{1:25,2:50,3:84},`teams`(84=83＋R11),`sel`(600),…）。
  - `teams[id]` = `rr_team` の正規化構築 ＋ `candidates`（24通り、各要素は先発が先頭の3体の基本名リスト）, `n_cand`, `no_mega`, `article_orders`, `gitems`, `rejected`, `gclass`, `n_mega`, `static`。rating は `rank`/`final`/`peak`。
  - `sel["A|B"]` = `decide_pair(A,B)` の結果 `{'src': 'article'|'guide-cond'|'guide-basic'|'basic', 'order': [...], 'top3', 'sec', 'fallback'}`。第1段階（tier1、25構築）の組だけある。
- L（`teams[L]`）: 「【M-6シングル最終83位】乾坤一擲リザホーク【最終2431】」 rank 83・final 2431、n_mega 2（メガムクホーク／ムクホークナイト、メガリザードンＸ／リザードナイトX）、他: ミミッキュ・イダイトウ・ガブリアス・アシレーヌ。
  - `article_orders` 4通り: ガブ/リザ/アシレ/ムクホ 先発 ＋ ミミッキュ・イダイトウ。`gclass='article'`。`candidates` 24通り（メガ2体の同時選出なし、メガなしは4通りまで）。
  - `sel["L|X"]` は tier1 の24相手について `src='article'`（例: ムクホーク・ミミッキュ・イダイトウ）。
- `logs/refine/rr_deny_games.json`: `deny full`（tier1 総当たり、両側 deny、各組6戦）1800戦。うち L の試合 144戦（24相手×6）、**L 100勝（69.4%）**、判定1。1戦の `sec` 平均25.6秒・中央値20.1秒・最大116.6秒（4並列のワーカー時間）。
- `rr_games.json`（通常）で L は 48戦29勝。
- `plan.sel` の選出計算 `sec` 平均6.3秒・最大15.8秒（プール内では `B._run_games` が子プロセスを作れず直列になる）。

### 1.2 コード
- `roundrobin.rr_apply(team)`: 自分側（`B.TEAM`,`B.MY`）に構築を入れる。`make_pool(procs, teams)` → `_worker_init` で `_TEAMS` と記事形式の `B.KNOWN_TEAMS` を作る（fork）。
- `sort_key(rt) = (rank or 10**6, -max(final or 0, peak or 0), id)`。`plan.order` はこの順（R11 除く83）。
- `decide_pair(A,B)`: 記事の選出 → ガイド条件 → ガイド基本 → `rr_select`（`B.select` を `order_filter` で候補に絞る）。`rr_select` はブラインド化のため `B.match_known`/`_load_select_rules`/`_focus_mons` を無効化し `sets.EXCLUDE={A,B}`、`set_known_context(None)`。
- `B.select(opp6, …)`: 相手の3体を `opp_pick_weights(opp6, MY)`（使用率・相性・pick_rate）の積で上位6組、先発は `lead_rate` で按分。各（自分の並び × 相手の並び）を `search.play(engine_game(...), smart)`（決定的なプレイアウト、`evaluate` 値。勝ち=+100付近、負け=-100付近）で評価、`worst + 0.01*avg` で順位。上位12を smart で再評価。
  - 記事の `picks` があるとそれを「先発固定・重み0.6」で混ぜる仕組み（`kt['picks']`）があるが、`set_known_context` が記事の型も相手推定に流すので**ブラインドが崩れる。今回は使わない**（下の 3.3 は roundrobin.py 内で自前に評価する）。
- `_job_deny(a)`: `rr_apply(_TEAMS[X])`; `R.blind_play((None, Y, selX, selY, seed, 4, 4, False, None, False, (X,), deny))`。
- `refine.blind_play(args)`: `args = (party, kid, my_order, opp_order, seed, my_depth, opp_depth, know, rules, trace, excl, deny)`。30ターンで決着しなければ `S.evaluate` の符号で `res`、`judged=True`。返り値 `res, log, faints[(turn, side, 倒れた名, その時の相手の場の名)], left, turns, judged, deny_stats`。
- `safeio.write_json`（atomic 書き込み）、`append_log`、`done_game`、`wilson`、`_sha_all`、`sha_files`、`circle_pairs` 等は再利用する。

## 2. 対戦相手の集合（決定）

### 2.1 規則
1. 母集団 = `rr_plan.json` の `teams`（known_teams＋new_teams_m6b を正規化済み）から **L と R11 を除く**。
2. **rating 無しを除外**: `rank`・`final`・`peak` がすべて None/0 のもの（new_teams_m6b の6構築など）。→ 現状 **72構築**。
3. `sort_key` 順に先頭から **50構築**。現状: 先頭 rank28/2480、50番目 rank723（`8e9ebc27e2db3f56`）、51番目 rank751。全50がメガ持ちで `n_cand=24`。tier1 との重なり **23構築**。
4. 各相手の `candidates`・`article_orders`・`gitems` は `rr_plan.json` の値をそのまま使う（作り直さない）。
5. `adapt plan` は 50構築＋L すべてに `rr_apply` を試し、失敗した構築は飛ばして次の順位を繰り上げる（理由を表示・記録）。

### 2.2 フォールバック（今回は不要・実装不要）
適格が50に満たない場合のみ: 使用率（`sets.usage_rank`）上位50以内のメガ可能種から2体、`usage_sets.json` の上位50種から補完4体を、種族重複なし・持ち物重複なし・メガストーンはちょうど2個で、種 `crc32("adrand{i}")` により作り、`build_candidates(rt, None, w)` で24通りを作る。**今回は72≥50なので不要。** `adapt plan` は適格<50 のとき「フォールバック未実装」で SystemExit するだけでよい。

### 2.3 `logs/refine/ad_plan.json`
```
{ "version": "ad1", "created": ..., "rr_sig": rr_plan.sig, "sig": sha256(rr_sig + L + 対戦相手id列 + "ad1"),
  "main": "db0baa2843d2bd4b", "games_per_pair": 10, "depth": [4,4], "deny": [true,true],
  "opponents": [50個のid, sort_key 順], "skipped": [{"id","why"}],
  "sel1": { "L|X": decide_pair結果, "X|L": ... } }
```
- `sel1` は第1戦の選出。`rr_plan.sel` に同じ鍵があれば**そのままコピー**（deny full と同じ選出＝比較の基準がそろう）。無ければ `decide_pair` をプールで計算して保存（50組×2側のうち tier1 にない 27組×2=54回、各~6秒）。
- `rr_plan.json` には書かない（不変）。sig が違う既存 `ad_plan.json` は `--force` で退避（`rr` の plan と同じ流儀）。

## 3. 適応選出（決定）

両側とも同じ関数 `adapt_select(A, Bid, hist)` を使う（左右対称）。A = 選ぶ側、Bid = 相手。

### 3.1 履歴 `hist`（このペアの第1〜n-1戦、古い順）
各要素: `{'n': 戦番号(1始まり), 'mine': A が使った並び, 'theirs': Bid が使った並び, 'res_for_A': 1|0.5|0}`（判定決着も勝敗に数える）。
- **既知にするのは相手の選出（3体＋先発）だけ**。相手の3体目が場に出なかった試合でも3体とも既知とする（ユーザー指示「選出は既知」）。
- 相手の型・技は既知にしない（「見えた技」は選出の学習にも対戦の推定にも持ち越さない。対戦内の推定は従来の `blind_play` の `seen` のみ）。
- 自分の過去の勝敗（自分の並びごと）は使う（3.4）。

### 3.2 第1戦（n=1）
従来どおり `ad_plan.sel1["A|Bid"]['order']`（記事 → ガイド条件 → ガイド基本 → 24通りから `rr_select`）。`src` もそのまま記録。

### 3.3 第2戦以降（n≥2）: 相手の選出分布 q と評価
1. **相手の並びの分布 q**（先発込みの並び c について）:
   - 履歴の重み: `h(c) = Σ_{i: theirs_i = c} 0.7^(n-1-i)`（直近を重く。λ=0.7）。`H = h / Σh`。
   - 未知の選出が出る確率: `π_new = 1 / (1 + m)`（m = 履歴の試合数、α=1 のディリクレ過程。m=1 で0.5、m=9 で0.1）。既に見た選出が再度出る確率 = 1-π_new。
   - 事前分布 Prior: A 側を `rr_apply` した状態で `w = B.opp_pick_weights(B6, list(B.MY.values()))`、3体組の積で**上位4組**、各組の先発を `lead_rate` で按分（`B.select` と同じ式）。履歴に出た並びは Prior から除いて正規化。
   - `q = (1-π_new)·H + π_new·Prior`。q の上位から累積0.95 まで、最大10並びを評価対象 C とし再正規化。
2. **評価**（`rr_select` と同じブラインドの退避・復元の枠内で行う。`kid=None`、`sets.EXCLUDE={A,Bid}`、`match_known`/`_load_select_rules`/`_focus_mons` 無効、`set_known_context(None)`、`history_bonus` は使わない）:
   - 第1段: A の24候補 × C の各並び c を `search.play(B.engine_game(o, c), smart=False)`（`B._game_job((o, c, False, None))` を**直列**で呼ぶ。プール内なので `_run_games` は使わない）。最大 24×10=240局。
   - 勝率化: `p(v) = 1 / (1 + exp(-v/20))`（v=+100→≈1、0→0.5）。
   - `E(o) = Σ_c q(c)·p(v(o,c))`、`W(o) = min_{c∈C, q(c)≥0.05} p(v(o,c))`。
   - 第2段: `E` 上位8候補について、q 上位5並びを `smart=True` で再評価し、その c の値を置き換えて E・W を計算し直す（最大40局）。
   - **選んだ根拠（計算時間）**: 既存の `B.select` は直列で 24×18 局（貪欲）＋12×15 局（smart）を平均6.3秒・最大15.8秒で終えている。本案は最大240＋40局で同等以下に収まり、1回あたり**十数秒以内**の目安を満たす。engine の4手読みロールアウトは1局数十秒かかるので不採用、過去の戦績だけでは24通りのほとんどが未使用で評価できないので補助（3.4）にとどめる。
3. **総合点**:
   - `S(o) = (1-π_new)·E(o) + π_new·W(o)`（履歴が少ないうちは最悪ケースを重く、増えると期待値を重く）。
   - 実戦の戦績: このペアで A が並び o を使った試合の `r̂(o) = (勝ち+0.5·引分+1) / (試合数+2)`、未使用は0.5。`S'(o) = S(o) + 0.15·(r̂(o) - 0.5)`（勝った選出を優先、負けた選出を避ける）。
   - ガイドの小さな加点: o が A の `article_orders` またはガイド基本（`gitems` の kind='basic' かつ usable の orders）に含まれれば +0.01（同点近くで記事の運用に寄せる。L ではメガムクホーク軸・ミミッキュ・イダイトウ）。

### 3.4 過剰適応の抑え（決定）
1. **同じ並び（3体＋先発）を3戦連続で使わない**: 直前2戦で A が同じ並び o を使っていたら o を候補から外す（同じ3体で先発違いは別の並びなので可）。
2. 実戦の戦績項（3.3-3）で「最後に勝てた選出」を残しやすく、負けた選出を外れやすくする。
3. 乱数は使わない（同じ履歴なら同じ選出。再開しても結果が変わらない）。同点は A の `candidates` の並び順が先のものを選ぶ。

### 3.5 選出の制約（決定）
- n≥2 で選べるのは A の `candidates`（24通り）だけ。24通りの制約は従来どおり（メガなしは4通りまで、メガストーン2体の同時選出なし。生成は `build_candidates`、変更しない）。L はメガムクホークとメガリザX の両方を持つが同時選出は候補に入っていない。
- 相手も自分の24候補から同じ規則で選ぶ。

### 3.6 記録（各戦の各側）
`{'src': 'article'|'guide-*'|'basic'|'adapt', 'order', 'q_top': [[q, c]...最大5], 'pi_new', 'score_top': [[S', E, W, r̂, o]...上位3], 'banned_streak': o or null, 'sec'}`

## 4. 対戦の実行（決定）

### 4.1 1戦
- ペア (L, X)、k=0..9（戦番号 n=k+1）。**k 偶数で L が side0**（X は side1）、奇数で入れ替え。
- 種 `seed = zlib.crc32(f"ad{X}{k}".encode())`。
- 鍵 `ad:{X}|{k}`。
- ワーカー関数 `_job_adapt(a)`: `a = (key, X, k, side0, side1, hist0, hist1)`。
  1. side0 の選出 = `adapt_select(side0, side1, hist0)`（k=0 は sel1）、side1 も同様。
  2. `rr_apply(_TEAMS[side0])`; `R.blind_play((None, side1, sel0, sel1, seed, 4, 4, False, None, False, (side0,), (True, True)))`（`_job_deny` と同じ呼び方）。
  3. 返り値に両側の選出記録・`sec_sel`・`sec` を付ける。例外は `res=None, error=...`。

### 4.2 並列と順序
- 並列は**ペア単位**: 同時に進めるペアは最大 `procs`（既定4）。ペア内の10戦は**必ず順番**（第 k 戦は第0..k-1戦がすべて `res` 非 None で記録済みのときだけ投入）。
- メインプロセスが `make_pool(procs, plan['teams'])` と `apply_async` で、1戦終わるたびに記録 → 同じペアの次の戦を投入、ペアが10戦終われば `opponents` 順で次の未完ペアを開始。
- 履歴 hist はメインが `ad_games.json` の記録から組み立てて渡す（ワーカーは状態を持たない）。

### 4.3 保存と再開
- `logs/refine/ad_games.json`（`safeio.write_json` で1戦ごとに atomic）:
  `{'version': 'ad1', 'plan_sig', 'main', 'depth', 'deny', 'games': {key: rec}}`、
  rec = `deny_record` の項目（`side0, side1, sel0, sel1, seed, res, winner, judged, turns, left, faints, sec, error, deny, deny_stats`）＋ `opp: X, k, n, main_side, why0, why1, sec_sel`。
- 対戦ログは `logs/refine/ad_logs.jsonl` に `append_log`。
- plan_sig 不一致なら SystemExit。再開時は各ペアの次の k を「k=0 から連続して記録済みの次」とする。途中に `res=None` があればそのペアは止める（`--retry-errors` で再実行）。`--max-games N` で今回の戦数を制限。
- コンテナ再起動で長時間ジョブが消えるため、本番は `nohup … &` ＋ 再実行で継ぎ足す運用（同じコマンドで続きから）。

### 4.4 所要時間の見積り（4並列）
- 1戦 約40秒（deny full 実測平均25.6秒より保守的に）＋ 選出2回（n≥2 で各~8秒、n=1 はほぼ0）≈ 56秒/戦。
- 500戦 × 56秒 / 4 ≈ **約2.0時間**（最悪 1戦120秒級が混じっても3時間程度）。`adapt plan` の sel1 計算 54回 × 6秒 / 4 ≈ 1.5分。
- `adapt run` は進捗行に経過・残り見積りを出す（`run_deny_jobs` と同じ形式）。

## 5. レポート `logs/ADAPT.md`（`adapt report`、決定）
`--out-dir D` のときは `D/ADAPT.md`。
1. **全体**: L の勝敗（500戦、勝率と Wilson 95%区間）、判定決着数（判定のみの勝率も別記）、エラー数、平均ターン。
2. **戦を重ねるごとの推移**: 第1-3戦／第4-6戦／第7-10戦ごとの L 勝率（区間付き）。L が side0 の試合・side1 の試合別の勝率も一行。
3. **相手構築ごと**（opponents 順の表）: 構築名（title 先頭24字）・rank・10戦の並び（例 `○●○○…`、判定は `△勝`/`△負` ではなく小文字 `o`/`x`）・勝数・1-3/4-6/7-10 の勝数。
4. **適応による選出の変化**: 相手ごとに L の並びの列（第1戦→…→第10戦、種類数）と相手の並びの列、第1戦と異なる並びにした戦数、`src='adapt'` で選んだ並びの勝率 vs 第1戦の並びの勝率。L が最も多く使った並びトップ3と、その時の q 上位（相手の予測）。
5. **勝てない相手トップ10**（L の勝率が低い順、同率は rank 順）と原因: L 側で最初に倒れたポケモン（`faints` の最初の L 側）の頻度、相手の主力（L のポケモンを倒した相手の名前の頻度）、相手がよく使った並び。
6. **L の選出別勝率**: 並び（先発込み）別と3体組別（試合数・勝率）。
7. **比較**: `rr_deny_games.json`（非適応・両側 deny）の L の結果と比較。共通の相手（tier1 ∩ 50 = 23構築）について「非適応 6戦の勝率」と「適応 10戦の勝率」「適応の第1戦のみ（＝非適応と同じ選出）」を相手ごとに並べ、合計も出す。参考として非適応全体 100/144（69.4%）。
8. 末尾に設定（depth・deny・λ・α・係数・seed 規則）と ad_plan の sig。

## 6. CLI（決定）
```
python roundrobin.py adapt plan   [--main db0baa2843d2bd4b] [--n-opp 50] [--games 10] [--procs 4] [--force] [--out-dir D]
python roundrobin.py adapt run    [--procs 4] [--max-games N] [--retry-errors] [--out-dir D]
python roundrobin.py adapt report [--out-dir D]
python roundrobin.py adapt selftest [--quick] [--keep]
```
- `main()` に `adapt` サブコマンドを追加（`what` を位置引数、`deny` と同じ形）。既存のサブコマンドの引数・動作は変えない。
- `rr_plan.json` は読むだけ。`--out-dir` 指定時は ad_* と ADAPT.md をそこに書く（rr_plan は既定の場所から読む）。
- selftest の差し替え用に、対戦関数をモジュール変数 `_AD_PLAY = R.blind_play` として呼ぶ（fork 前に差し替えればワーカーにも効く）。

## 7. 受け入れ条件（`adapt selftest` で自動確認、`--out-dir` は一時ディレクトリ）
1. `python3 -m py_compile tool/roundrobin.py` が通る。
2. **相手集合**: 50構築、L と R11 を含まない、rating 無しを含まない、`sort_key` 順、`order` 中の適格72の先頭50と一致。L＋50構築すべてに `rr_apply` が通る。
3. **24通りの制約**: L と50構築の `candidates` が24通り、すべて `all_orders` に含まれる、メガ2体同時選出なし、メガなしは4通り以下。`adapt_select` の結果が常に A の `candidates` に入る。
4. **適応が履歴に依存して変わる**: L 対 tier1 の先頭数構築で、履歴 H1（相手が並び a を3戦）と H2（相手が並び b を3戦、a と3体が異なる）で L の選出が異なる組が少なくとも1つある。同じ履歴で2回呼ぶと同じ結果（決定性）。
5. **q の性質**: 同じ並びを3戦観測したとき q(その並び) ≥ 0.6、履歴 [a,a,b] と [b,a,a] で q(b) は前者が大きい（直近重視）、m=0 では Prior と一致。
6. **連続3回禁止**: 直前2戦で同じ並び o を使った履歴（評価を差し替えて o が最高点になるようにする）で o が選ばれない。
7. **順序・再開**（`_AD_PLAY` を即時の偽関数に差し替え、3相手×10戦）: `--max-games 7` で止めて再実行すると、各ペアの k が0から連続、重複なし、合計30戦。第 k 戦の記録 `why*` に入った履歴長が k。途中に `res=None` を入れるとそのペアは止まり、`--retry-errors` で続く。偶数 k で L が side0、seed が `crc32("ad{X}{k}")`。
8. **既存結果の不変**: `_sha_all()` が selftest 前後で一致。既定の場所に `ad_plan.json`/`ad_games.json`/`ad_logs.jsonl`/`logs/ADAPT.md` が作られていない。
9. **所要時間**（`--quick` では省略）: 実際の評価で n≥2 の `adapt_select` を3回（L側2回・相手側1回）測り、中央値15秒以下・最大30秒以下。実際の1戦（両側 deny、4手読み）を1回行い、秒数を表示（120秒以下を目安、超えたら警告のみ）。
10. **report**: 偽の結果から ADAPT.md を作り、5章の各見出し（全体・推移・相手ごと・選出の変化・勝てない相手・選出別・比較）が入っている。
11. 既存の `selftest --quick` と `deny selftest`（時間のかからない項目）が引き続き通る（回帰）。

## 8. 本番の実行（Opus／ユーザーが行う、実装者は行わない）
```
cd pokechamp/tool
python3 roundrobin.py adapt plan
nohup python3 roundrobin.py adapt run --procs 4 > ../logs/refine/ad_run.out 2>&1 &   # 落ちたら同じコマンドで続き
python3 roundrobin.py adapt report
```
