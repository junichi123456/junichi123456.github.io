# SPEC_TONORAGU2: トノラグ3変種 × 相手選出固定（イエッサン先発）で「最も勝てるプレイング」を抽出する

作成: Opus 5.5 / 実装: Sonnet 5.5 / 前提: `specs/SPEC_TONORAGU.md`（tn1）・`logs/TONORAGU.md`
対象: `tool/roundrobin.py`（`tonorag` に `--focus` 系を追加）、`tool/refine.py`（`blind_play` にオプトインの記録だけ追加）
対象外: Star Crusade、game_watch.py、battle.py の実戦判断、engine.py / search.py / playbook.py、tn1 の既存結果。**実装者は本番（run）を実行しない**（selftest と実測1戦まで）。

## 0. 目的とユーザー要件
- リザホーク（L＝`TN_L`）は6体にイダイトウがいる → 相手は**イエッサンを先発に出す可能性が高い**。この前提で相手選出を固定し、変種A/B/Cごとに「最良選出」と「その選出で最も勝てるプレイング（ターン別の行動）」をログから出す。
- ブラインド・ケアは tn1 と同じ: 相手の型は推測のみ（`know=False`）、両側 deny `(True, True)`、L側プレイブック既定オン（`--no-playbook` で切れるのも同じ）、resource 既定 `loose`。深さ stage1＝(4,4)、stage2＝(5,5)。

## 1. 相手選出（固定）
| 変種 | 先発 | 後発順（2通り） |
|---|---|---|
| A | イエッサン | ニョロトノ→ラグラージ / ラグラージ→ニョロトノ |
| B（イエッサン不在） | バサギリ（記事の基本選出） | 同上 |
| C | イエッサン♀ | 同上 |
- 新定数 `TN2_LEADS = {'A': ['イエッサン'], 'B': ['バサギリ'], 'C': ['イエッサン♀']}`。生成は既存 `tn_opp_sels` と同じ規則（先発∉`TN_BACK`、`TN_BACK` 2体を必ず含む）を `leads` 引数で受ける形にし、tn1 の呼び出し結果は不変。変種ごと2通り、計6通り。
- L側は `T[TN_L]['candidates']` の24通りを全部。

## 2. コマンド（既存 tonorag を壊さない拡張）
- `--focus` を tonorag の全サブコマンド（plan/run/report/selftest）に追加。付けたときだけ tn2 名前空間を使う。付けないときの挙動・出力・sig は tn1 と完全に同じ。
- ファイル（`tn2_paths(out_dir)`）: `logs/refine/tn2_plan.json`、`tn2_games.json`、`tn2_logs.jsonl`、`logs/TONORAGU2.md`（`--out-dir` 指定時はその中に `TONORAGU2.md`）。**tn_* と TONORAGU.md は読みもしない／書かない**（report が tn1 と比較したい場合も読み取りのみ・任意）。
- `tonorag plan --focus [--games 8] [--games2 12] [--top 2] [--resource loose] [--procs 4] [--force]`
  - plan に `games: {'1': N1, '2': N2}`, `top: T`, `leads: TN2_LEADS`, `opp_sels`, `candidates`, `depth`, `deny`, `resource`, `playbook`署名, `estimate` を保存。`sig` は tn1 と同じ材料＋`'tn2'`＋leads（games/top は sig に含めない＝後から増やせる）。
- `tonorag run --focus --stage 1|2 [--games N] [--procs 4] [--max-games] [--retry-errors]`
  - 1ペア（変種×相手選出×L選出）あたり N 戦。stage1 は k＝0..N−1（N 省略時は plan の games['1']）、stage2 は k＝100..100+N−1（省略時 games['2']）。**k の偶奇で左右入れ替え**（既存 `tn_job` と同じ: 偶数 L が side0）。
  - key＝`tn2:{V}|{相手選出}|{L選出}|{k}`、種＝`crc32("tn2"+V+相手選出+L選出+k)`。N を後で増やすと新しい k だけが追加で走る（既存は再実行しない）。
  - stage2 は stage1（plan の N1 分）が全部済んでいる時だけ。初回に変種ごと上位 `top` 選出（stage1 の勝率→平均残HP の順。同率は candidates 順）を決めて plan['stage2_sels'] に保存し、以後固定。
  - 1戦ごとに `safeio.write_json` で atomic 保存、ログは `append_log` で `tn2_logs.jsonl`（中断→再実行で続きから）。レコードは `tn_record` と同じ項目＋`focus: True`。

## 3. 戦数と時間（4並列で2時間以内）
- stage1: 3変種×相手選出2×24選出×N1=8 ＝ **1152戦**（4手）。stage2: 3×2×上位2選出×N2=12 ＝ **144戦**（5手）。
- 見積り（`tn_estimate` を流用、s4=12秒、s5=57秒、procs=4）: stage1 57.6分＋stage2 34.2分＝**約92分**、余裕係数1.3でも約119分。参考: tn1 実測（tn_games.json の sec 平均）は 4手 9.2秒／5手 30.4秒 → 実測ベース約62分。
- plan は見積りが120分（rf=1.3 込み）を超える `--games/--top` を指定されたら警告を出す（止めない）。report §1 に見積りと実所要（sec 合計/procs）を並べる。

## 4. ログの追加項目（tn_logs.jsonl に無いもの）
現状の log 行は `[side0の場, side0の行動, side1の場, side1の行動]`（行動前の場、`M+`＝メガ、`→X`＝交代、`-`/`反動`）と `faints`=[ターン, 側, 名前, 倒した側の場]、`left`（最終HP%）だけで、**天候・残りターン・フィールド・HP・ばけのかわ・ほろび/アンコールのカウント・だっしゅつボタン発動**が無い。
- `refine.py` にモジュール変数 `SNAP = False` を追加。`blind_play` は `SNAP` が True の時だけ、`log.append(...)` の直前（行動決定後・`E.step` 前の st）に1要素を `snap` に積み、戻り値に `'snap': snap` を足す（`len(snap) == len(log)`）。E.step の後に同じターンの結果として `post` を足す。**RNG・st を一切変更しない（読むだけ）**。False の時は戻り値・挙動とも従来と同一。
- `snap[t]`（行動前）キー: `w`=`st.weather`、`wt`=`st.wturns`、`tr`=`st.terrain`、`tt`=`st.tturns`、`room`=`st.pseudo.get('trickroom', 0)`、`hp`=[各側の場の `round(100*hp/maxhp)`]、`mega`=[各側 `mega_used`]、`bk`=[各側の場が disguise 持ちなら `busted`（False/True/'done'）、他は None]、`vol`=[各側の場の `{'perish': vol.get('perishsong'), 'encore': vol.get('encore'), 'curse': 'curse' in vol}`]、`item`=[各側の場の item]、`alive`=[各側の生存数]。
- `post[t]`（E.step 後）キー: `hp`、`act`=[各側の場の名前]、`ej`=[その側の場が行動前に ejectbutton を持ち、step 後に item が空で場が変わったら True]。
- roundrobin 側: `_job_tn2` の中でだけ `R.SNAP = True`（終了時に元へ戻す）。`append_log` には `{'key', 'log', 'snap', 'post'}` を書く（tn2 のみ。tn1 の `append_log` 形式は変えない）。

## 5. レポート `logs/TONORAGU2.md`（核心）
集計の単位は「L視点」（`main_side` で左右を揃える。`M+` は除去して技名を揃え、メガの時期は別に数える）。n<5 の数字には「（参考）」を付ける。勝率は `_tn_ci`（Wilson 区間）。
1. **条件**: 深さ・N1/N2/top・deny・resource・playbook 署名・種の式・相手選出表（§1）・見積りと実所要・B/C の近似一覧（tn1 と同じ書式、近似＝仮説）。
2. **選出表**: 変種×相手選出（後発順2通り）ごとに L 24選出の stage1 勝率（上位8行＋最下位3行）、後発順の差（5pt 以上で「差あり」）。
3. **変種ごとの最良選出**: stage2 勝率（5手）で順位、同率は stage1。各候補に stage1・stage2・合算の勝率と区間。3変種共通（最悪ケース最大、stage1 基準）も1行。
4. **最も勝てるプレイング**（変種ごと、最良選出の stage1+stage2 全試合。深さ別の内訳も1行）:
   - 4.1 **ターン別行動（T1〜T6）**: 各ターンについて、L の（場, 行動）上位3と相手の（場, 行動）上位3を、勝ち試合での出現数・全体の出現数・その行動を取った時の勝率で表にする。T1 は先発の組（L先発×相手先発）も。
   - 4.2 **分岐点**: そのターンまで続いた試合のうち、L が行動 a を取った／取らなかったで勝率差 Δ を出し、|Δ|≥15pt かつ両側 n≥4 のものを Δ の大きい順に最大8件（「T3 リザードン:げきりん 取った 82%(11) / 取らない 40%(10) Δ+42」の形）。T1→T2 の行動の組の上位5と勝率も。
   - 4.3 **個別論点**（すべて log/snap/post/faints から機械集計）:
     - ミミッキュ: トリックルームを `bk` 未破壊で使った回数/破壊後、各勝率。トリル中（`room`>0）の L 行動上位。のろい使用ターン→次ターン以内にミミッキュ瀕死（退場）の割合と、その後に出た L 個体・勝率。
     - リザードンX: メガのターン（`M+` 初出、または `mega` が False→True）ごとの勝率。げきりんの連続ターン数分布、げきりん中に相手が交代した回数、雨下（`w`='raindance'）での げきりん/フレアドライブ の選択数と勝率。
     - イダイトウ: おはかまいりを使った時の L 瀕死数（6体−`alive`… 選出3体基準で数える）別の回数・勝率。アクアジェットを `tr`='psychicterrain' かつ相手場が接地（ふうせん持ち除く）で選んだ回数＝封じられた回数、それ以外の回数。
     - ほろびのうた: L の場が `perish` を持ってからの交代までのカウント（3/2/1/交代せず退場）別の回数と勝率。
     - アンコール: 縛られた技・`dur`・次ターンに交代したか居座ったか、別の勝率。
     - 雨: ラグラージ登場時の `wt`、雨が切れたターン（`w` が raindance→他に変わった最初のターン）での L の行動上位と勝率、ニョロトノ再登場で `wt` が戻った回数。
     - だっしゅつボタン: `post.ej` が立った試合で、発動ターン・誰の攻撃で発動したか・入れ替わりで出た相手・L の次ターン行動（上位3）と勝率。
   - 4.4 **推奨手順（機械生成・仮説）**: 最良選出について、T1〜T4 で勝率が全体以上かつ n≥5 の最頻行動を並べ、4.3 で Δ≥15pt の条件付きルール（例「雨が切れたターンは○○」）を最大5行。「シミュレーション（ブラインド・deny・4/5手読み）由来」と明記。
5. **負け筋**: 最良選出の負け試合の先頭瀕死と倒した相手、瀕死順上位3。
6. **結論**: 変種ごとに「選出・勝率区間・推奨手順の要約1行」。

## 6. 受け入れ条件（`python3 roundrobin.py tonorag selftest --focus` で全部 OK）
1. `python3 -m py_compile tool/roundrobin.py tool/refine.py` が通る。`tonorag selftest`（--focus なし＝tn1）も従来どおり全部 OK。
2. 相手選出: 6通り、A の先発は全て イエッサン、B は全て バサギリ、C は全て イエッサン♀。ニョロトノ・ラグラージは先発に一度も来ず、全選出に両方含む。後発順が2通りとも存在。L 選出は24通り。
3. ジョブ: stage1 の件数＝24×6×N1、k の偶奇で side0/side1 が入れ替わる、key・種が仕様どおり、重複なし。stage2 は stage1 未完で拒否、上位 top 選出が plan に保存され再計算されない。
4. 再開: スタブ（`_TN_PLAY` 差し替え）で一部実行→再実行で残りだけ実行、`--games` を増やすと新しい k だけ追加、`--retry-errors` で error のみ再実行。
5. snap: 実 `blind_play` を浅い深さ（1,1）で同じ種・SNAP オン/オフで1戦ずつ → `res/log/faints/left/turns` が一致し、オン側だけ `snap`/`post` があり `len(snap)==len(log)`、各キーが §4 どおり。
6. report: スタブの games/logs（snap 付き）から TONORAGU2.md（一時 out-dir）が §1〜§6 の見出しを全部持ち、4.3 の7項目がすべて出る（該当0件は「該当なし」）。
7. 既存結果不変: selftest の前後で `logs/refine/tn_plan.json`、`tn_games.json`、`tn_logs.jsonl`、`logs/TONORAGU.md` の sha256 が一致（selftest は一時 out-dir だけに書く）。
8. 時間: plan の estimate（N1=8, N2=12, top=2, 4並列）が rf=1.3 込みで 120分以下であることを表示・確認。実 d4 1戦を測り秒数を表示（本番 run はしない）。
