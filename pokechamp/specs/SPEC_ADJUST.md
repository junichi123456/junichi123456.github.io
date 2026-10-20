# R9 の 1 匹調整（エンペルト: あくび → れいとうビーム）と検証 仕様書

作成: Opus 5.5 ／ 実装: Sonnet 5.5（`model: sonnet`）／ 受け入れ確認: Opus 5.5
元の構築: `pokechamp/tool/data/party/R9.json` ／ 新しい構築: `pokechamp/tool/data/party/R10.json`（新規）
前提の研究: `specs/SPEC_CORES.md`、結果 `logs/refine/cores_R9.json`・`logs/CORES_R9.md`

この仕様書の「事実」はコードとデータで確認した内容（2026-10-20）。

---

## 0. 目的と全体の流れ

1. R9 で役割が最も薄い 1 匹（エンペルト。§1.1）の技を 1 つだけ変えた R10 を作る（§2）。
2. **再戦 20 組**: 既存の R9 の試合から勝ち 10・負け 10 を選び、同じ選出・同じ種・同じ深さ・同じ規則で R10 で戦い直し、組ごとの勝敗の変化を数える（§3）。
3. **6 手読みのブラインドテスト**: エンペルトが選出に入る構築について、R10 と R9 を自分 6 手・相手 3 手で 5 戦ずつ回す（§4）。
4. 1 戦ごとにチェックポイント保存（`core_test.py` の仕組みを再利用。§5）。
5. 結果を `pokechamp/logs/ADJUST_R10.md` にまとめ、R10 を採用するかを数字の基準で判定する（§6）。

対象外: Star Crusade（ルートの `index.html`・`starcrusade/`）、`game_watch.py`、OCR 関連、`team.py`・`engine.py`・`search.py`・`battle.py`・`policy.py` の変更、`data/*.json`（`data/party/R10.json` の新規作成を除く）の変更、**`logs/refine/cores_R9.json` と `logs/CORES_R9.md` の変更**。

---

## 1. 前提（コードとデータで確認した事実）

### 1.1 調整対象がエンペルトである根拠（cores_R9.json）
- `cores_R9.json` の変種: `on` 100 戦、`on-NONE` 100 戦、`on-no-M2+R1b` 100 戦、`off` 98 戦。`sig` は R9、`policy_version` 1、`depth` [5, 3]。
- エンペルトが自分の選出に入った試合は計 100 戦で勝ち 23（23%）。変種別: on-NONE 7 勝 18 敗、on 2 勝 23 敗、on-no-M2+R1b 2 勝 23 敗、off 12 勝 13 敗。先発時 25%、他の 5 体は 33〜37%。
- エンペルトを選出した構築: on 系（on / on-NONE / on-no-M2+R1b）は 1e1ecbc7・705822f2・96073793・d19098fc・d858baf8 の 5 構築、off は 1e1ecbc7・705822f2・8cfae507・96073793・d858baf8。
- 変種名と規則の対応（`core_test.rules_for`）: `on` = 選出規則あり＋全行動規則（`policy.ALL_RULES`）、`on-NONE` = 選出規則あり＋行動規則なし（`rules=('NONE',)`。`policy.choose` を通るが該当する規則が無いので、探索の 1 位をそのまま打つ）、`off` = 選出規則なし＋`rules=None`（従来の `blind_play`）。選出は `on*` が plan の `on`、`off` が plan の `off`。

### 1.2 れいとうビーム（engine / moves データ）
- `engine.MOVES['icebeam']`: 和名 れいとうビーム、こおり・特殊、**威力 90、命中 100**、PP 12、優先度 0、追加効果 10% こおり、接触なし。
- `data/moves.json`（`calc.MOVE['れいとうビーム']`）: id 58、pow 90、acc 100、pp 12。`battle.MOVE` に含まれる（`refine.apply_party` の assert を通る）。
- エンペルト（図鑑 395）の `data/learnsets.json['395']` に技 id 58 がある（覚えられる）。
- 参考（calc.py、R9 エンペルト なまいき C 補正なし 実数値 191-106-130-131-146-72、相手は `battle.opp_sets` の使用率の型、HP 満タン）:

  | 相手 | れいとうビーム | なみのり |
  |---|---|---|
  | ガブリアス（タスキ H2 A32 S32） | 93〜110% | 35〜41% |
  | ボーマンダ（メガ前） | 105〜124% | 19〜23% |
  | メガボーマンダ | 96〜115% | 18〜21% |
  | カイリュー（calc の特性込み） | 46〜54% | 8〜10% |
  | ゴリランダー（H32 A32 D2） | 47〜56% | 17〜21% |

  エンペルト（素早さ 72）はこれらより遅いので、1 対 1 は「1 発受けてから撃つ」形になる。

### 1.3 再利用する仕組み（core_test.py / refine.py）
- `core_test._init_r9()`: `refine.load_party(9)`→`refine._BASE_SPECIES` を R9 の種族に→`refine.apply_party`→`battle.MY_TYPES` 更新→`refine.teams()`。冪等。R10 は種族が同じなので `apply_party` の種族 assert を通る。
- `refine.blind_play(args)`: `args = (party, kid, my_order, opp_order, seed, my_depth, opp_depth, know, rules)`。毎戦の最初に `apply_party(party)` を呼ぶので、**同じワーカーで R9 と R10 の試合を混ぜてもよい**。戻り値 `res, log, faints, left, fired, rocks_turn, tox, turns, judged`。`log` の各要素は `(自分の場の名前, 自分の行動の和名, 相手の場の名前, 相手の行動の和名)`（メガ同時は `M+` が付く）。最大 30 ターン。
- `core_test.cmd_run`: `multiprocessing` の `imap_unordered` で受け取るたびに `safeio.write_json` で全体を原子的に保存。`res` が `None` 以外の戦は飛ばす。`load_data` は `sig`・`policy_version`・`depth` が違えば止まり、`--force` で日時付きに退避。
- `core_test.seed_of(kid, k) = zlib.crc32(f'core{kid}{k}'.encode())`。
- 現状 `core_test.py` は `PARTY_N = 9`・`RESULT_P = logs/refine/cores_R9.json`・`OPP_DEPTH = 3` を固定で持つ。
- `engine.step(st, a0, a1, rng, chooser, log=None)`: `log` に list を渡すと、エンジンが文字列を追記する（`'<名前> uses <技ID>'`、`'<技ID> missed'`、`'<名前> protected'`、`'<名前> immune'`、`'switch <side> <名前>'`、`'faint <名前>'` など）。追記するだけで、乱数・結果は変わらない（A4 で確かめる）。

---

## 2. R10（変更は 1 技だけ）

- `tool/data/party/R10.json` を R9.json のコピーとして作り、**エンペルト（4 番目、添字 3）の `moves[1]` の「あくび」を「れいとうビーム」に置き換える**。技の並び順は変えない（`moves = ["なみのり", "れいとうビーム", "ステルスロック", "クイックターン"]`）。
- 種族・性格（なまいき）・努力値（hp 32 / defn 22 / spd 12）・特性（げきりゅう）・持ち物（シュカのみ）・label（`エエンペルト`）、他の 5 体はすべて R9 と同じ。JSON の書式（`indent=1`、`ensure_ascii=False`）も R9 と揃える。
- 並び順を保つ理由: `E.actions` の順は技の順で、`policy.ranked_root` の同点処理（先の行動が勝つ）に効く。差を 1 技だけにするため。

---

## 3. 再戦 20 組

### 3.1 組の選び方（決定的に再現できる手順）
入力は `logs/refine/cores_R9.json`（読むだけ）。
1. 変種を **on-NONE → on → off** の順に見る（on-no-M2+R1b は使わない）。
2. 各変種の中で `res` が `None` でない試合のうち、**その変種の選出（on-NONE・on は plan の `on`、off は plan の `off`）の `my_order` にエンペルトが入る試合**を候補にする。
3. 候補を **(k, `EVAL_IDS` での構築の位置)** の昇順に並べる（構築が偏らないよう、試合番号ごとに構築を巡回する）。
4. 順に見て、組のキー **(構築id, 自分の選出順 tuple, 相手の選出順 tuple, 種)** が既に採った組と同じなら飛ばす（結果が違っても同じ 1 組）。そうでなければ、勝ち（`res == 1`）は勝ちが 10 未満のとき、負け（それ以外）は負けが 10 未満のときに採る。
5. 勝ち 10・負け 10 がそろったら終わり。そろわなければエラーで止める。

この手順で得られる 20 組（事前に計算した期待値。`adjust-plan` の出力がこれと一致すること＝A3）:

| 組 | 元の試合キー（構築 8 桁 \| 変種 \| k） | 自分の選出 | 相手の選出 | 種 | 元の結果 |
|---|---|---|---|---|---|
| P01 | 1e1ecbc7\|on-NONE\|0 | エンペルト→ドヒドイデ→マスカーニャ | カメックス→イエッサン→アシレーヌ | 802184701 | 勝 |
| P02 | 705822f2\|on-NONE\|0 | エンペルト→ドヒドイデ→グレンアルマ | カイリュー→エンペルト→ルカリオ | 4100120823 | 勝 |
| P03 | 705822f2\|on-NONE\|1 | エンペルト→ドヒドイデ→グレンアルマ | カイリュー→エンペルト→ルカリオ | 2204487777 | 勝 |
| P04 | 1e1ecbc7\|on-NONE\|2 | エンペルト→ドヒドイデ→マスカーニャ | カメックス→イエッサン→アシレーヌ | 3252567249 | 勝 |
| P05 | 1e1ecbc7\|on-NONE\|3 | エンペルト→ドヒドイデ→マスカーニャ | カメックス→イエッサン→アシレーヌ | 3067677767 | 勝 |
| P06 | 705822f2\|on-NONE\|3 | エンペルト→ドヒドイデ→グレンアルマ | カイリュー→エンペルト→ルカリオ | 1835774285 | 勝 |
| P07 | 1e1ecbc7\|on-NONE\|4 | エンペルト→ドヒドイデ→マスカーニャ | カメックス→イエッサン→アシレーヌ | 683514340 | 勝 |
| P08 | 96073793\|off\|0 | セグレイブ→エンペルト→マスカーニャ | ボーマンダ→カバルドン→グソクムシャ | 3234335868 | 勝 |
| P09 | 96073793\|off\|1 | セグレイブ→エンペルト→マスカーニャ | ボーマンダ→カバルドン→グソクムシャ | 3083812074 | 勝 |
| P10 | 96073793\|off\|2 | セグレイブ→エンペルト→マスカーニャ | ボーマンダ→カバルドン→グソクムシャ | 784756048 | 勝 |
| P11 | 96073793\|on-NONE\|0 | エンペルト→セグレイブ→ドヒドイデ | ボーマンダ→カバルドン→グソクムシャ | 3234335868 | 負 |
| P12 | d19098fc\|on-NONE\|0 | エンペルト→マスカーニャ→グレンアルマ | フラエッテ→ガブリアス→スターミー | 3202030078 | 負 |
| P13 | d858baf8\|on-NONE\|0 | セグレイブ→ドヒドイデ→エンペルト | ドヒドイデ→リザードン→エアームド | 3093535671 | 負 |
| P14 | 96073793\|on-NONE\|1 | エンペルト→セグレイブ→ドヒドイデ | ボーマンダ→カバルドン→グソクムシャ | 3083812074 | 負 |
| P15 | d19098fc\|on-NONE\|1 | エンペルト→マスカーニャ→グレンアルマ | フラエッテ→ガブリアス→スターミー | 3386648936 | 負 |
| P16 | 1e1ecbc7\|on-NONE\|1 | エンペルト→ドヒドイデ→マスカーニャ | カメックス→イエッサン→アシレーヌ | 1490513259 | 負 |
| P17 | d858baf8\|on-NONE\|1 | セグレイブ→ドヒドイデ→エンペルト | ドヒドイデ→リザードン→エアームド | 3479481121 | 負 |
| P18 | 96073793\|on-NONE\|2 | エンペルト→セグレイブ→ドヒドイデ | ボーマンダ→カバルドン→グソクムシャ | 784756048 | 負 |
| P19 | d19098fc\|on-NONE\|2 | エンペルト→マスカーニャ→グレンアルマ | フラエッテ→ガブリアス→スターミー | 1356167378 | 負 |
| P20 | 705822f2\|on-NONE\|2 | エンペルト→ドヒドイデ→グレンアルマ | カイリュー→エンペルト→ルカリオ | 443318747 | 負 |

- on-NONE の勝ちは 7 戦しかないので、残り 3 勝は on → off の順で補う。on の勝ち 2 戦（96073793|on|1、1e1ecbc7|on|1）は、on-NONE の P14・P16 と組のキーが同じなので重複として飛ばされ、off の 3 勝（P08〜P10）が入る。
- P08〜P10 と P11・P14・P18 は種が同じだが選出が違うので別の組（キーが違う）。

### 3.2 再戦の条件（元の試合と厳密に同じ）
- `refine.blind_play((party, kid, my_order, opp_order, seed, 5, 3, False, rules, True))`
  - `my_order`・`opp_order`: 元の試合の plan の値（cores_R9.json からそのまま。再計算しない）。
  - `seed`: 元の試合に保存された `seed`（`seed_of` で作り直さず、保存値を使う）。
  - 深さ: 自分 5 手・相手 3 手（cores_R9.json の `depth` [5, 3]）。`know=False`（ブラインド）。
  - `rules`: 元の変種で決める。on-NONE → `('NONE',)`、on → `policy.ALL_RULES`、off → `None`。plan の組に `rules`（list または null）として保存し、実行時に tuple に戻す。
  - 最後の `True` は §5.4 の `trace`（技の記録。結果は変えない）。
- 実行するもの:
  - **R10 再戦** 20 戦（`party` = R10）。
  - **R9 対照** 20 戦（`party` = R9、同じ引数）。保存済みの元の結果が今のコードで再現するかを確かめる。再現しない組があれば、その組の比較の基準は「R9 対照の結果」にし、レポートで印を付ける（§6）。
- 比較: 組ごとに **負→勝**、**勝→負**、変化なし を数える（基準は元の結果。R9 対照と元が違う組は R9 対照を基準にして別に数える）。

---

## 4. 6 手読みのブラインドテスト

### 4.1 対象構築
- 評価 20 構築（`core_test.EVAL_IDS`）のうち、次のどちらかを満たす構築:
  - (a) **R10 で再計算した on の選出**（下の 4.2）にエンペルトが入る。
  - (b) **R9 の on の選出**（cores_R9.json の plan の `on`）にエンペルトが入る（1e1ecbc7・705822f2・96073793・d19098fc・d858baf8 の 5 構築）。
- (a)(b) の和集合にする（技を変えたことで選出からエンペルトが外れた構築・入った構築の両方を見るため）。どちらに当たったかを plan に `why: ['R10','R9']` のように記録する。

### 4.2 選出
- **R10**: R10 を `apply_party` した状態で、`make_plan` の on と同じ処理（`refine.blind_select(t, order_filter=policy.select_filter(opp6))`、満たす選出が無いときは `policy.relaxed_filter` で緩和）。**行動規則なし**（`rules=('NONE',)`、変種 on-NONE と同じ）。
- **R9**: cores_R9.json の plan の `on`（`my_order`）をそのまま使う（再計算しない）。行動規則なし（`('NONE',)`）。
- **相手の選出**: 両方とも cores_R9.json の plan の `opp_order` をそのまま使う（`opp_selection` は自分の 6 体との相性を使うので、再計算すると R10 で変わりうる。条件を揃えるため固定）。
- 注意: `blind_select` は `sets.EXCLUDE` と `B._OPP_CACHE` を変える。R10 の選出計算の前に必ず R10 を `apply_party` し、計算後は次の処理の前に必要なパーティを `apply_party` し直す（`blind_play` は自分で `apply_party` するので対戦には影響しない）。

### 4.3 条件
- 1 構築あたり **5 戦（k = 0..4）**、種は `seed_of(kid, k)`（cores_R9 と同じ種）。**自分 6 手・相手 3 手**、`know=False`、最大 30 ターン。
- R10 と R9 で同じ構築・同じ k・同じ種。`refine.blind_play((party, kid, my_order, opp_order, seed_of(kid,k), 6, 3, False, ('NONE',), True))`。
- 実行順: `for k in 0..4: for kid in 対象: (R10, R9)` の順で job を並べる（途中で止まっても R10 と R9 が同じ数ずつ進むように）。
- 時間の見込み（推定）: 5 手読みは約 6 秒/ターン（SPEC_CORES §1.3 の実測）。6 手は枝分かれで約 4〜6 倍と見て 25〜35 秒/ターン、1 戦 5〜15 分。対象 5〜7 構築 × 5 戦 × 2 パーティ = 50〜70 戦で、4 並列 2〜4 時間。**本番の前に `deep --max-games 1 --procs 1` で 1 戦の秒数を測り、見込みをレポートの条件欄に書く。**

---

## 5. 実装（core_test.py の拡張と refine.blind_play の記録追加）

### 5.1 パーティの一般化（既存の R9 の動作は変えない）
- `_init_party(tag='R9')` を追加: `party = refine.load_tag(tag)`、あとは `_init_r9` と同じ処理（`_BASE_SPECIES`・`apply_party`・`MY_TYPES`・`teams()`）。`_init_r9()` は `return _init_party('R9')` にする（既存コマンドの動作は同じ）。
- `PARTY_N`・`RESULT_P`・`REPORT_P` と既存のサブコマンド（`cores / plan / check-select / selftest / one / run / report`）は**変更しない**（R9 固定のまま）。
- 新しい定数:
  ```python
  ADJ_P = lambda tag: os.path.join(HERE, '..', 'logs', 'refine', f'adjust_{tag}.json')   # adjust_R10.json
  ADJ_REPORT = lambda tag: os.path.join(HERE, '..', 'logs', f'ADJUST_{tag}.md')          # ADJUST_R10.md
  ADJ_VERSION = 1
  ```

### 5.2 新しいサブコマンド（作業フォルダ `pokechamp/tool/`）
すべて `--party`（既定 `R10`）と `--base`（既定 `R9`）を受け取る。
```
python3 core_test.py check-diff   [--party R10 --base R9]   R10 と R9 の差分を表示（1 技だけなら終了コード 0、それ以外は 1）
python3 core_test.py adjust-plan  [--party R10 --base R9] [--force]
                                   再戦 20 組（§3.1）と 6 手読みの対象・選出（§4.1〜4.2）を計算して adjust_R10.json に保存
python3 core_test.py replay       [--party R10 --base R9] [--procs N] [--max-games N] [--no-control]
                                   再戦: R10 20 戦 + R9 対照 20 戦（--no-control で対照を省く）
python3 core_test.py deep         [--party R10 --base R9] [--depth 6] [--games 5] [--procs N] [--max-games N]
                                   6 手読み: 対象構築 × games 戦 × (R10, R9)
python3 core_test.py adjust-report [--party R10 --base R9] [--out path]   logs/ADJUST_R10.md を作る（途中の結果からでも）
python3 core_test.py adjust-selftest                          §5.4 の技の記録の局面テスト
```
- `replay`・`deep` は `adjust-plan` が無ければ先に自動で行う（`cmd_run` の `ensure_plan` と同じ考え方）。
- 長時間の実行は `nohup python3 core_test.py deep > ../logs/refine/adjust_R10.log 2>&1 &`。1 戦ごとに `[済み/全体] キー 勝/負 ターン 秒 経過分` を 1 行出す（`cmd_run` と同じ形）。

### 5.3 結果ファイル `logs/refine/adjust_R10.json`
```json
{"version": 1, "party": "R10", "base": "R9",
 "sig": {"R10": "<refine.sig(R10)>", "R9": "<refine.sig(R9)>"},
 "policy_version": 1, "opp_depth": 3,
 "source": {"file": "logs/refine/cores_R9.json", "sig": "<cores_R9.json の sig>"},
 "pairs": [{"id": "P01", "src": "1e1ecbc7b6d2bad7|on-NONE|0", "kid": "...", "variant": "on-NONE",
            "rules": ["NONE"], "my_order": [...], "opp_order": [...], "seed": 802184701,
            "orig_res": 1, "orig_turns": 11, "orig_log": [...]}],
 "deep": {"depth": [6, 3], "games": 5,
          "plan": {"<kid>": {"title": "...", "why": ["R10", "R9"], "opp_order": [...],
                             "R10": {"my_order": [...], "my_top": [...], "relaxed": []},
                             "R9": {"my_order": [...]}}}},
 "games": {"replay|R10|P01": {...}, "replay|R9|P01": {...},
           "deep|R10|<kid>|0": {...}, "deep|R9|<kid>|0": {...}}}
```
- 各 game は `blind_play` の戻り値＋`seed`・`sec`・`party`・`depth`（`[my, opp]`）・`mv`（§5.4）。
- 起動時の検査: `sig` の R10・R9 のどちらか、`policy_version`、`source.sig`（cores_R9.json の sig）、`deep.depth` が今と違えば止まる。`--force`（`adjust-plan` のみ）で `adjust_R10.<日時>.json` に退避して新しく始める。`deep --depth 7` のように深さを変えたいときも同じ扱い（深さは結果キーではなくファイル単位で固定）。
- 保存: `cmd_run` と同じく、メインプロセスが 1 戦ごとに `safeio.write_json` で全体を原子的に保存。ワーカーは書かない。再開時は `res` が `None` 以外の戦を飛ばし、例外の戦は再実行。
- ワーカー: `_work_adj(job)`、`job = (key, tag, party, kid, my_order, opp_order, seed, my_depth, rules)`。先頭で `_init_party(tag)` を呼び（spawn でも動くように。fork なら冪等）、`refine.blind_play((party, kid, my_order, opp_order, seed, my_depth, OPP_DEPTH, False, rules, True))`。`rules` は tuple か `None`。
- cores_R9.json は**読むだけ**（`json.load` のみ。`save()`・`load_data()` を通さない）。

### 5.4 技の記録（refine.blind_play の 10 番目の引数 `trace`）
- `trace = len(args) > 9 and args[9]`。**`False`（既定、既存の呼び出し）のときは今とまったく同じ動き・同じ戻り値**。
- `True` のとき: 各ターン `elog = []` を作って `E.step(st, a0, a1, rng=rng, chooser=chooser, log=elog)` に渡し、そのターンの自分の技について 1 件 `[ターン, 自分の場の名前, 技の和名, 対象の名前, 結果]` を戻り値の `mv` に追加する（自分の行動が交代・反動・None のターンは記録しない）。
  - 自分の場の名前 = 行動前の `st.active(0).name`、技 = `a0[1]`。
  - 対象: 行動前の `st.active(1).name` から始め、`elog` の中で自分の `'<名前> uses <技ID>'` の行より前にある `'switch 1 <名前>'` の行で更新する（相手の交代・とんぼがえり等で入れ替わった相手）。
  - 自分の uses 行: `'<自分の名前> uses <技ID>'` の行。相手の場も同じ名前で同じ技を使ったターン（例: 705822f2 の相手エンペルト）は区別できないので、結果を `'unknown'` にする。
  - 結果: uses 行から次の `' uses '` を含む行（または末尾）までに、`'<技ID> missed'` で始まる行 → `'miss'`、`' protected'` か `' guarded'` で終わる行 → `'protect'`、`' immune'` で終わる行 → `'immune'`、どれも無ければ `'hit'`。uses 行が無い（ひるみ・ねむり・まひ・先に倒れた）→ `'none'`。
  - 行の書式は実装時に `engine.py` の `self.L(...)` を読んで確かめ、違っていればこの規則を同じ意味になるよう合わせる（変更点は仕様の受け入れ確認時に報告）。
- `log=elog` を渡しても乱数の消費・結果は変わらない（A4 で確かめる）。
- `adjust-selftest`（`core_test._game` などの既存の局面作りを使う）:
  1. エンペルト（R10 の型）vs ガブリアスで `('m','icebeam',…)`、相手は攻撃技 → 記録が `[1,'エンペルト','れいとうビーム','ガブリアス','hit']`。
  2. 相手が まもる → `'protect'`。
  3. 相手が交代（`('s', j)`）→ 対象が交代先の名前。
  4. `trace=False` と `True` で、同じ引数の 1 戦（3 手読み）の `res`・`log` が一致。

---

## 6. 結果レポート `logs/ADJUST_R10.md`

1. **条件**: R9 と R10 の差分（1 行: エンペルト あくび → れいとうビーム、威力 90・命中 100）、再戦の深さ 5/3、6 手読みの深さ 6/3、最大 30 ターン、種の作り方、実行日時、合計時間（のべ）、6 手読み 1 戦の実測秒数、戦数。**5 戦単位（構築別）では勝率の誤差が ±20% 程度、6 手読みの合計（25〜35 戦）でも ±10% 程度、再戦 20 組の差（負→勝 − 勝→負）は ±3 程度が偶然で起きる**ことを明記する。
2. **再戦 20 組の勝敗変化表**: 組 / 構築 / 変種 / 自分の選出 / 相手の選出 / 種 / 元の結果 / R9 対照（一致なら「再現」、違えば結果と印）/ R10 の結果 / 変化（負→勝・勝→負・同じ）/ R10 のターン数 / R10 でエンペルトが撃ったれいとうビームの回数。下に合計: 負→勝 a、勝→負 b、純増 a − b、R9 対照の再現数（/20）。
3. **6 手読みの構築別勝率**: 構築 / 題名 / 対象の理由（R10・R9）/ 相手の選出 / R9 の選出 / R10 の選出 / R9 の 5 戦（○×）/ R10 の 5 戦（○×）/ 勝ち数の差 / 判定決着数（R9/R10）。最後に合計行（R9 勝率、R10 勝率、差）。エンペルトを選出した試合に限った勝率（R9 / R10）も 1 行出す。
4. **エンペルトの技の使用回数**: 再戦 R10・再戦 R9 対照・6 手 R10・6 手 R9 の 4 列で、エンペルトの 4 技それぞれの使用回数と、エンペルトが場に出たターン数。れいとうビームは結果別（hit / miss / protect / immune / none / unknown）の回数と、**当てた（hit）相手の内訳**（相手の種族ごとの回数、そのうち倒した回数＝同じターンに対象が倒れた回数）。R9 側はあくびの回数と、あくびの後に相手が眠った回数（任意）。
5. **判定**（下の基準を上から順に当てはめ、最初に当たったものにする。根拠の数字を併記）:
   - **判断不能（再現性）**: R9 対照の再現が 20 組中 18 未満。
   - **判断不能（技が使われていない）**: R10 の全試合（再戦＋6 手）のうち、エンペルトが場に出た試合で れいとうビームを 1 回以上撃った試合が 20% 未満。
   - **不採用**: 次のどちらか。(i) 再戦の純増 a − b ≤ 0 かつ 6 手読みの R10 の勝ち数 ≤ R9 の勝ち数。(ii) 6 手読みの R10 の勝ち数が R9 より 3 以上少ない。
   - **採用**: 再戦の純増 a − b ≥ +3 かつ 6 手読みの R10 の勝ち数 ≥ R9 の勝ち数。
   - **判断不能（差が小さい）**: 上のどれにも当たらない（例: 純増 +1〜+2、または再戦と 6 手読みで向きが逆）。このときは「追加で回すなら何を何戦」を 1 行書く（例: 6 手読みを 1 構築 10 戦に増やす）。
   - 補足: 採用でも統計的に有意とは言えない（20 組の符号検定で純増 +3 は片側 p ≈ 0.2 前後）。「この実験で悪化の兆候が無く、改善の方向」という意味で使う。
6. **所見**（数行）: 負→勝になった組でれいとうビームが誰に当たったか、勝→負になった組で何が起きたか（あくびが無くなったことで失ったもの等、`log` から）。

---

## 7. 受け入れ条件

- **A1** `python3 -m py_compile core_test.py refine.py policy.py battle.py` が通る。
- **A2** `core_test.py check-diff`: R10 と R9 の差が「エンペルト（添字 3）`moves[1]`: あくび → れいとうビーム」の 1 件だけで、終了コード 0。他の項目（6 体の species・nature・ap・ability・item・label、他の技と並び順）は完全一致。`refine.apply_party(R10)` が assert を通り、`calc.learnset('エンペルト')` にれいとうビームが含まれる。
- **A3** `core_test.py adjust-plan`: 再戦の組が 20、勝ち 10・負け 10、組のキーに重複なし、§3.1 の表と組・順番・選出・相手の選出・種・元の結果がすべて一致。各組の `my_order`・`opp_order`・`seed` が cores_R9.json の元の試合（plan と game の `seed`）と一致し、`rules` は §3.2 の対応どおり。6 手読みの対象に (b) の 5 構築がすべて入り、R9 の選出が cores_R9.json の plan の `on` と一致、`opp_order` も一致。
- **A4** 再現性と記録の無害さ: `replay` の R9 対照 20 戦の `res`・`log` が元の試合と一致（目標 20/20、18 未満なら本番の判定は「判断不能」になるので、その時点で Opus に報告して止める）。`adjust-selftest` の 4 項目が合格（特に `trace` の有無で `res`・`log` が一致）。
- **A5** チェックポイント: `replay --max-games 2` → 2 戦が保存される。もう一度 `replay --max-games 2` → 最初の 2 戦を飛ばして次の 2 戦。`deep` でも同じ。実行中に kill しても `adjust_R10.json` が `json.load` できる。コマンドをやり直すと続きから回る。
- **A6** R9 の既存結果が不変: 作業の前後で `logs/refine/cores_R9.json` の sha256 が `c57de93080a9ed6797ff9832e4649386ded2baf1d15f8f12e42b501b7a51734d`、`logs/CORES_R9.md` が `ed3938404fea891421b6ce733dd3dba87a9d68905b1d6ace4785773f18050f6d` のまま。`core_test.py report --out <scratch>/c.md` の出力が `logs/CORES_R9.md` と「作成」行以外で一致。`core_test.py cores` が「全体: 一致」。
- **A7** `adjust-report` が途中の結果（例: 再戦 2 戦だけ）からでも §6 の形でレポートを作れる（無い項目は「-」）。
- **A8** 本番: 再戦 R10 20 戦・R9 対照 20 戦・6 手読み（対象構築 × 5 戦 × R10/R9）がすべて `res` ありで保存され、`logs/ADJUST_R10.md` に §6 の項目がそろう。
- **A9** 変更・追加したファイルは `tool/core_test.py`（拡張）、`tool/refine.py`（`blind_play` の `trace` 引数だけ）、`tool/data/party/R10.json`（新規）、結果の `logs/refine/adjust_R10.json`・`logs/refine/adjust_R10.log`・`logs/ADJUST_R10.md` だけ。

Opus は A1〜A7 を確認してから本番（A8）を始めさせ、A8 の後にレポートと判定を確認して報告する。
