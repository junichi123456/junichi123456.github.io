# SPEC_M7MEGA2: m7 をメガ持ち2体の構築（M8_1〜M8_3）でも回せるようにする

対象: `pokechamp/tool/roundrobin.py` の m7 部分（`party_team`、`m7_paths`、`cmd_m7_plan/run/report/selftest`、argparse の `m7`）。
`build_candidates` / `all_orders` は**原則変更しない**（後述 2 の小変更のみ）。対象外: Star Crusade、`game_watch.py`、他コマンド（adapt/counter/sched3/final20 等）。

## 現状（確認済み）
- `party_team(name, tid)` は「メガ持ち != 1」で `SystemExit`。M8_1/M8_2/M8_3 はすべてメガ2体なので止まる。
  - M8_1: メガリザードンＸ・メガガブリアスＺ ／ M8_2: 同左 ／ M8_3: メガリザードンＸ・メガメタグロス。
- `all_orders` は既に「メガ持ち2体を同時に含む選出」を除外。`build_candidates` は メガなし `min(4, 件数)` ＋ メガ1体 `min(24-q, 件数)` を採るので、メガ2体でも 24 通りになる（下の数え上げ参照）。
- 出力名は `m7_paths` が固定（`m7_plan.json`・`m7_games.json`・`m7_logs.jsonl`、md は既定 `logs/M7RUN.md`）。`--prefix` 引数は定義だけで未使用。チーム ID は定数 `M7_ID='M7'`。
- 既存 M7 結果（不変であること）:
  - `logs/refine/m7_plan.json` 4c9c3222db219745ca44f422db6c9933629af4355b3e5f60ab9bc2330172c903
  - `logs/refine/m7_games.json` 37a669c3b1bd5bb033e5808545614e9d50f639b8a18464814aeec95980263deb
  - `logs/M7RUN.md` 437f7434e68aa043dc573a190d54149929fe8d7ef907a7c723a526002beace52

## 1. party_team の検査とメガ前特性
- 検査を `1 <= メガ持ち数 <= 2` に緩める。0体・3体以上は `SystemExit(f'{name}: メガ持ちが{n}体です（1〜2体のみ）')`。
- 特性の決め方（メガ種族 sp、元種族 base、json の `ability` を e_ab とする）:
  1. e_ab が `POKE[sp]['ab']` に含まれる → `ability = e_ab`、`base_ability = e.get('base_ability') or (e_ab if e_ab in POKE[base]['ab'] else POKE[base]['ab'][0])`（現行どおり。R11 方式の ab[0] 既定）。
  2. e_ab がメガ側に無く `POKE[base]['ab']` に含まれる（例: M8_3 メガメタグロスの「クリアボディ」）→ `ability = POKE[sp]['ab'][0]`（かたいツメ）、`base_ability = e.get('base_ability') or e_ab`。
  3. どちらにも無い → `SystemExit`（特性名の誤り）。
- この規則はメガ2体の両方に個別に適用。M7（メガカイリュー/マルチスケイル）は規則1で現行と同じ値になること（M7 の sig を変えない）。
- 既定の base_ability は ab[0]（リザードン→もうか、ガブリアス→すながくれ）。変えたい場合は party json に `base_ability` を書く運用とし、コードで推測しない。

## 2. 24通りの候補（build_candidates）
メガ持ち2体（A,B）＋他4体の構築での `all_orders`（先発×後発2体の組、後発の順序は区別しない）:
- 全 6×C(5,2)=60、うち A・B 同時 12 を除外 → 48。
- メガ1体入り: 2体 × C(4,2)=6組 × 先発3 = **36**。メガなし: C(4,3)=4組 × 先発3 = **12**。
- 採用: メガなし上位 **4**、メガ入り上位 **20** → 計 **24**（現行ロジックのまま成立）。

追加する優先順位（`n_mega == 2` のときだけ。1体以下の挙動は一切変えない）:
- メガ入り 20 枠は現行の並び（記事→ガイド→score 降順）で採るが、**各メガ持ちが最低 6 通り**入るよう補正する（片方が 6 未満なら、もう片方の最下位から入れ替えて、不足側の次点を入れる）。
- 返り値に `mega_split: {A: 件数, B: 件数}` を追加（`m7_team` に保存され report で表示）。

満たすべき規則（ユーザー当初規則）: メガを含む選出が基本／メガなしは4通りまで／合計24通り以内／後発2体の順序は区別しない（`norm_order` 済み）／メガ持ち2体同時は0件。

## 3. 結果ファイルの分離
- 接頭辞 `pfx = (a.prefix or a.party).lower()`（argparse の `--prefix` 既定を `None` に）。`--party M7` → `m7`（現行と同名）、`M8_1` → `m8_1`。
- `m7_paths(out_dir, pfx)`: `{pfx}_plan.json`・`{pfx}_games.json`・`{pfx}_logs.jsonl`、md は out_dir 指定時 `{out_dir}/{PFX}RUN.md`、未指定時 `logs/{PFX}RUN.md`（PFX は大文字。M7 は `M7RUN.md` で現行と同一）。
- チーム ID は `tid = a.party`（M7 は 'M7' のまま）。`M7_ID` を直接使っている m7 系の箇所（s3 との重複検査、`m7_opponents` の除外、`teams[...]`、job の L、report の見出し）は `plan['team_id']`（plan 作成時に保存）か引数で受ける。games のキー `m7:{X}|{k}` と `m7_seed` は**変えない**（M8 各案を同じ seed で比較できるようにする）。
- 混在防止: 既存 plan の `party` が `a.party` と違えば `SystemExit('この out-dir/接頭辞には {old} の結果があります')`。run/report も plan の `party` と `--party` が違えば止める。複数案（M8_1/2/3）は接頭辞が違うので同じ `logs/refine` に並べてよいが、**同じ接頭辞・同じ out-dir で別案を回さない**。
- 運用例: `python3 roundrobin.py m7 plan --party M8_1` → `logs/refine/m8_1_plan.json`、`m7 report --party M8_1` → `logs/M8_1RUN.md`。

## 4. 受け入れ条件
1. `python3 -m py_compile roundrobin.py` が通る。
2. `party_team('M8_1')`・`('M8_2')`・`('M8_3')` が例外なく返り、各 `rr_apply(rt)` が通る。M8_3 のメガメタグロスは `ability='かたいツメ'`, `base_ability='クリアボディ'`。`party_team('M7')` の返り値が変更前と完全一致（json 比較）。
3. メガ0体・3体の一時 party（`R.PARTY_D` を一時フォルダに差し替え）で `SystemExit`。
4. M8_1/M8_2/M8_3 それぞれで `build_candidates`（静的スコア w は全 1.0 の仮値で可）が: 件数 24／メガ2体同時 0／メガなし ちょうど 4／メガ入り 20／各メガ持ち 6 以上／全候補が `all_orders` に含まれ後発が `norm_order` 済み／重複なし。M7 で `build_candidates` の結果が変更前と一致。
5. `m7_paths(None,'m8_1')` が `m8_1_plan.json` 等と `logs/M8_1RUN.md` を返し、`m7_paths(None,'m7')` が現行と同一パス。
6. `m7 selftest --quick`（一時フォルダ）が全 ○。selftest に `--party`（既定 M7）を通し、上記 2〜5 を項目として追加。`--party M8_1` でも全 ○。
7. 既存 M7 結果3ファイルの sha256 が上記と同じ。既定の場所に `m8_*` ファイルや `M8_*RUN.md` が作られていない。

実装者は本番（`m7 plan/run` を out-dir 指定なしで）を**実行しない**。selftest は一時フォルダでのみ。
