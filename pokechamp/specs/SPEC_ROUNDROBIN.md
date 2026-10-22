# 上位構築の総当たり（4手読み同士のブラインド戦）仕様書

作成: Opus 5.5 ／ 実装: Sonnet 5.5（`model: sonnet`）／ 受け入れ確認: Opus 5.5
作業フォルダ: `pokechamp/tool/`（Linux は `python3`、Windows は `python`）
新規: `tool/roundrobin.py`。既存ファイルの変更は `tool/refine.py` の `blind_play` に後方互換の2点だけ（§9.2）。

「事実」はコードとデータで確かめた内容。「決定」はこの仕様で決めた内容。

対象外: Star Crusade（ルートの `index.html`・`starcrusade/`）、`game_watch.py`、OCR 関連、`team.py`、`data/*.json` と `data/party/*.json`（読むだけ）、既存の結果ファイル（`logs/refine/` の rr_* 以外、`logs/*.md` の ROUNDROBIN.md 以外）。

---

## 0. 目的

これまでに集めた上位構築（`data/known_teams.json`、83構築）と採用パーティ R11（`data/party/ADOPTED.json`）を、**互いに相手の6体だけを見て選出し、両者4手読みで戦わせる**総当たりにかけ、最も強い構築を決める。

- 選出は「ガイド（記事の選出・夜間学習のメモ）があればその通り、無ければ基本の選出」。
- 選出の候補は1構築24通りまで。先発は区別し、後発2体の順序は区別しない。メガストーン持ち2体を同時に出さない。メガなしの選出は24通りのうち4通りまで。
- 時間がかかるので3段階に分け、各段階の結果を足し合わせて順位を出す。

**実装者は本番（`run`）を実行しない。** 受け入れ条件（§10）の確認だけを行う。

---

## 1. 前提（事実）

### 1.1 データ
| 項目 | 値 |
|---|---|
| `known_teams.json` の構築数 | 83（全て `regulation: mc`、全て6体が `calc.POKE` にある。`battle.KNOWN_TEAMS` の現行レギュ絞り込み後も83） |
| `new_teams_m6b.json` | 6構築。**6つとも id が `known_teams.json` に既にある**（`refine.teams()` は重複を足さない）→ 対象は 83 構築＋R11 = **84** |
| `rating` | 73構築にある（`rank` あり68、`final` のみ5）。10構築は無い（`hatena_*` など） |
| メガ持ちの数（§3.2の判定） | 1体: 8構築、2体: 70構築、3体: 5構築、0体: 0構築 |
| 名前がメガでないのにメガストーンを持つ個体 | 18体・9構築（例 `28caf4e8` の「メタグロス@メタグロスナイト」、`815520d5` の「ガブリアス@ガブリアスナイトZ」と「ルカリオ@ルカリオナイトZ」） |
| 記事の選出 `picks`（team 直下） | 9構築（1件:3構築、2件:1構築、4件:5構築）、計25件、全て3体。`mons[0]` が先発（`battle.select` の `fixed` がこの並びをそのまま相手の順として使う）。**2件の中にメガ持ち2体の選出が1件、メガなしが2件** |
| ガイド `guide` | 83構築すべてにキー `type, core, plan, picks, heavy, notes, date`。`guide.picks` は `[{when, pick, note}]` で、77構築に計306件（6構築は空: `d858baf8`, `hatena_r…`, `hatena_g…`, `466e7e1c`, `108328e9`, `598640a0`） |
| `guide.picks[].pick` の長さ | 3体:186、1体:73、2体:45、0体:1、4体:1。中身は自然文混じり（「メガ枠」「@1」「+対面駒2体」「ブリジュラス or ガブリアス」「Hヌメルゴン」「リザードンX」「刺さっているメガ2体」など） |
| `guide.picks[].when` | 「基本」で始まる:64（ちょうど「基本」39）、相手のポケモン名を含む:約160、否定・状況（「〜がいない」「出しにくい」「欲しいとき」「多い」等）:約55、その他（「雨パ」7、「バトン」「受け構築」「対面選出」等）:約27 |
| 持ち物の欠け | 6体が `item: null`。`37993777` は3体が null（`refine.apply_party` の「持ち物重複なし」assert に掛かる） |
| 技の数 | `c0ae6e25` のメタモンは技1つ（`へんしん`）。`apply_party` の「技4つ」assert に掛かる |
| R11 | `ADOPTED.json` と `R11.json` は同一内容。カバルドン・メガセグレイブ@セグレイブナイト・ドヒドイデ・エアームド・マスカーニャ・グレンアルマ（メガ持ち1体）。`ap` のキーは `defn`（`known_teams` は `def`。`calc.Mon` はどちらも受ける） |

試作パーサ（§4 の規則の簡易版）で数えた目安: `guide.picks` 306件のうち、3体とも構築の個体に解決できる「完全」121件、1〜2体と「メガ枠」等の空き枠からなる「部分」131件、使えない54件。構築単位では「完全な基本選出がある」約34、「条件付き・部分だけ使える」約23、「使える記述なし」約26。正確な数は `plan` が出す（§10）。

### 1.2 コード
- `design.targets()`: `(rank または 10**6, -max(final, peak))` の昇順に並べ、先頭 `MAX_TEAMS=20` を返す。`design.team_weight(t)`: rank≤300 か pts≥2300 で 1.0、他 0.7。
- `design._set_to_mon(b, e)`: メガは `Mon(メガ名, …, mega_ability or POKE[mega]['ab'][0], item, moves, label=b)`。
- `refine.teams()`: known＋new を合わせ、`battle.KNOWN_TEAMS` に無い id を足す。
- `refine.apply_party(party)`: `_BASE_SPECIES` 一致・持ち物重複なし・AP（合計66・各32以内）・技4つ重複なし・`B.MOVE` に存在、を assert し、`B.TEAM`・`B.MY`（`B.my_sets()`）・`B._OPP_CACHE` を更新。`B.my_sets()` はメガの元の姿の特性を `POKE[base]['ab'][0]` にする（記事の `base_ability` を使わない）。
- `core_test._init_party(tag)`: `_BASE_SPECIES` を置き換えてから `apply_party`、`B.MY_TYPES` を作り直し、`refine.teams()`。→ 種族の違うパーティも読めるが、上の assert は残る。
- `refine.blind_play(args)`: `(party, kid, my_order, opp_order, seed, my_depth, opp_depth[, know, rules, trace])`。先頭で `_sets.EXCLUDE = {kid}`、`apply_party(party)`。`_ctx(kid)` で相手（side 1）の**真の型**を `B.KNOWN_TEAMS` の id=kid の記事から取り（`B.opp_sets` → `B.known_set`）、`B.engine_game(my_order, opp_order)` で side 0 は `B.MY`（`B.mine`）から作る。読みは `match_known` を無効にし `set_known_context(None)` として、相手の型を `_templates(opp_order, B.opp_sets, 1)`、自分の型（相手から見た推測）を `_templates(my_order, B.opp_sets, 0)` で推測し、毎ターン `belief()` に差し替えて `S.lookahead_action(…, my_depth / opp_depth)`。30ターンで決着しなければ `S.evaluate(st) > 0` で 1、他 -1（`judged: True`）。例外は `{'res': None, 'error': …}`。戻り値: `res, log, faints, left([[名前, HP%]×3]×2), turns, judged, rocks_turn, tox, fired`。
- **非対称な点**: side 0 は `B.TEAM/B.MY`、side 1 は既知の記事。`B.known_set` のメガ判定は「名前がメガ名か」だけ（`is_mega = name != b and name in POKE`）なので、**名前がメガでないメガストーン持ち（上表18体）は side 1 ではメガシンカしない**。
- `B.select(opp6, ignore_stored=True, order_filter=…)`: 自分の60通り（`itertools.combinations` × 先発3）を `order_filter` で絞り（絞った結果が空なら絞らない）、`data/select_rules.json` の `active_select_rules`・`_focus_mons` も掛ける。相手の3体組は `opp_pick_weights(opp6, MY)` の積の上位6、先発は `lead_rate` の比で配分、`_run_games`（自前の Pool。デーモンプロセス内では例外→逐次実行に落ちる）で貪欲に打ち切り評価し、最悪値→平均で並べ、上位12を1手読みで再評価。`refine.blind_select(t, order_filter)` はこれを `EXCLUDE={t['id']}`・`match_known` 無効で呼ぶ。
- `B.opp_pick_weights(opp6, my6)`: 使用率・`matchup`・`pick_rate` からの各個体の出しやすさ。`B.lead_rate(b)`: 自分の対戦記録 `KNOW` からの先発率（記録なしは 1/3）。
- `B.MY_TYPES` は `infer.best_set` が相手の型を推測するときの「自分のタイプ」。
- `sets.EXCLUDE`: この id の記事の型を推測の材料から外す（`article_candidates`）。
- `prep.opp_trips`・`prep.all_orders`: 既存の相手選出・自分の60通り。本仕様では使わない（`refine.trips_fixed` は `logs/refine/trips.json` を書くので**呼ばない**）。
- 並列: `core_test` は `mp.get_context('fork' or 'spawn').Pool(procs)` の `imap_unordered(chunksize=1)` で1戦ごとに `safeio.write_json`（tmp→`os.replace`）。ワーカーは毎回パーティを入れ直す（Windows の spawn 対策）。
- 実測（参考）: 4コアの環境で `refine.blind_select`（R11、相手1構築）が 60通り 3.6秒、24通りに絞って 3.2秒。過去の `blind_play`（5手/3手読み）の1戦あたりワーカー時間は中央値 33〜63秒・平均 45〜79秒（`logs/refine/cores_R9.json`・`item_*.json`・`slot4_*.json` の `sec`）。4手/4手はまだ測っていない（§10 で測る）。

---

## 2. 対象構築と段階

### 2.1 並べ方（決定）
83構築を `key = (rank or 10**6, -max(final or 0, peak or 0), id)` の昇順に並べる（`design.targets` と同じ規則に id の同順位処理を足し、上限を外したもの）。R11 は全段階に必ず入れる（id `'R11'`）。

| 段階 | 対象 | 構築数 | 組 | 本戦（1組2戦） | 再戦 | 新しく増える戦数 |
|---|---|---|---|---|---|---|
| 1 | 上位24＋R11 | 25 | 300 | 600 | なし | 600 |
| 2 | 上位49＋R11 | 50 | 1,225 | 2,450 | 上位5の各組4戦=40 | 1,850＋40 = 1,890 |
| 3 | 全83＋R11 | 84 | 3,486 | 6,972 | 上位5の各組4戦（済みの組は飛ばす）≤40 | 4,522＋≤40 |

第1段階の上位24は rank 28（`a99ce37e`）〜 239（`adb3c969`）。第2段階の境は 49番目 rank 690 / 50番目 rank 708。rating の無い10構築は第3段階だけに入る。

### 2.2 累積
- 各段階は前の段階の対戦をそのまま含む（対戦の鍵・種・選出は段階に依らない。§5.4・§6）。第2段階では、第1段階の組は再実行しない。
- 選出候補は**最初から84構築全体を相手集団として計算**し、段階で変わらないようにする（§3.4）。

### 2.3 所要時間の見積り（決定: 数字は `plan` が実測値で出し直す）
1戦のワーカー時間を T とすると、4プロセスでの実時間は約 T/4。

| 段階 | 戦数 | T=50秒（過去の5/3手読みの平均相当。実時間12.5秒/戦） | 実時間30秒/戦（依頼者の保守的な見積り） |
|---|---|---|---|
| 1 | 600 | 約2.1時間 | 約5.0時間 |
| 2（増分） | 1,890 | 約6.6時間 | 約15.8時間 |
| 3（増分） | 約4,560 | 約15.8時間 | 約38時間 |
| 合計 | 約7,050 | 約24.5時間 | 約59時間 |

- 選出の計算（§5.3 の基本選出）が別に要る: 順序つきの組（A が B を見て選ぶ）ごとに1回、24通りに絞った `B.select` で、逐次ワーカー1回あたり数秒〜10秒程度。第1段階 最大600回（約0.3〜0.7時間）、第2段階 +1,850回、第3段階 +4,522回。ガイドで選出が固定の組は計算しない。
- **第1段階を5時間以内に収める規則**: `selftest` で測った1戦の実時間（4プロセス）が 30秒を超えたら、`plan --tier 1` は対象を「上位20＋R11」（210組・420戦）に減らすよう警告し、`--tier1-size N` で指定できるようにする（既定24）。
- 「1組1戦」にすると全体は半分（第3段階まで約3,500戦）になるが、左右の偏りを消せないので既定は2戦。`--games-per-pair 1` を第3段階の増分にだけ使えるようにする（レポートに明記）。

---

## 3. 構築の正規化と選出候補24通り

### 3.1 正規化した構築（決定）
各構築を次の「rr 構築」に変換し、`rr_plan.json` に保存する（元データは書き換えない）。

```
{"id": ..., "title": ..., "rank": ..., "final": ..., "peak": ..., "weight": design.team_weight(t),
 "mons": [{"base": 基本名, "species": 戦闘時の名前（メガ持ちはメガ名）, "mega": true/false,
           "nature", "ap"（def/defn は def に統一）, "ability"（メガ持ちはメガ後の特性）,
           "base_ability"（メガ前の特性）, "item"（null は ""）, "moves"}]}
```
- メガ持ちの判定: ①名前が `POKE` のメガ名（`norm(name) != _base(name)`）、または ②持ち物に「ナイト」を含み、基本名が `B.MEGA_OF` にある。②のとき `species` は `B.MEGA_OF[base]` から、持ち物末尾の X/Y/Z と全角Ｘ/Ｙ/Ｚを対応させて1つ選ぶ（例 ガブリアスナイトZ → メガガブリアスＺ）。決まらなければ例外（selftest で0件を確認）。
- `ability`: ①は記事の `ability`、②は `POKE[メガ名]['ab'][0]`。`base_ability`: 記事の `base_ability`（②では記事の `ability` と同じ）。
- R11: `ADOPTED.json` から。`species` がメガ名のものはメガ持ち、`base_ability` は `POKE[base]['ab'][0]`、`rank/final` は無し、`weight` は 1.0。

### 3.2 自分側に入れる（`rr_apply`、決定）
`refine.apply_party` は §1.1 の2構築で assert に掛かり、メガ前の特性も記事と変わるので使わない。`roundrobin.rr_apply(team)` を新設する:
- 検査: 種族が `POKE` にある、技1〜4個・重複なし・全て `B.MOVE` にある、AP 合計66以下・各32以下、空でない持ち物に重複なし。
- `B.TEAM[:] = [Mon(species, nature, ap, ability, item or None, moves, label=base)]`
- `B.MY = {base: (Mon(base, …, base_ability, …), Monメガ) or (Mon, None)}`
- `B.MY_TYPES = tuple(tuple(m.types) for m in B.TEAM)`、`B._OPP_CACHE.clear()`。
- 冪等。ワーカーは毎ジョブの先頭で呼ぶ。

### 3.3 相手側に入れる（決定）
ワーカーの初期化で `refine.teams()` を呼んだ後、`B.KNOWN_TEAMS` を **rr 構築から作った記事形式**（`name` = `species`（メガ持ちはメガ名）、`ability`, `base_ability`, `item`, `moves`, `nature`, `ap`）で**同じ id のまま置き換える**（メモリ上だけ。R11 は id `'R11'` で追加）。これで side 1 でも名前がメガでないストーン持ちがメガシンカし、R11 も真の型で戦う。以後 `refine.teams()` を呼ばない（呼ぶと置き換えが崩れるため、置き換え後に `teams()` を呼んでいないことを selftest で確認）。

### 3.4 選出候補の生成（決定）
選出は `(先発, {後発2体})`。保存形式は `[先発, 後発1, 後発2]` で、後発2体は**構築の並び順**に並べて一意にする。全体で 6×C(5,2)=60 通り。

**除外**: メガ持ち2体以上を含む選出（3体組にメガ持ちが2体以上）。

**優先順位つきの並び L**（重複は先に出た方を残す）:
1. 記事の選出 `picks`（`mons[0]` が先発）。
2. ガイドの「完全」な選出（§4.2）。`guide.picks` の記載順。条件が読めない項目の選出も候補には入れる。
3. ガイドの「部分」な選出（§4.2）について、条件を満たす選出のうち静的スコア上位3通りずつ（記載順）。
4. 残り全部を静的スコアの降順（同点は文字列順）。

**静的スコア**（相手に依らない基本ルール）:
- 各個体 x の出しやすさ `w(x)` = 84構築のうち自分以外の各構築 F について、`rr_apply(F)` した状態で A の記事を既知の文脈にして（`B._KNOWN_CTX['team'] = Aの記事形式`、`_OPP_CACHE.clear()`）`B.opp_pick_weights(A6, list(B.MY.values()))[x]` を計算し、その平均。
- `S(先発 l, 組 c) = Π_{x∈c} w(x) × lead_rate(l) / Σ_{x∈c} lead_rate(x)`（`B.lead_rate` は `KNOW` から）。
- 対象は常に84構築全体（段階で変わらない）。plan で一度計算して保存。

**枠の配分**: メガ持ちの数 m、メガなしの選出の数 N0、メガ1体の選出の数 N1 とする。

| m | 取りうる選出（2体メガ除外後） | 配分 |
|---|---|---|
| 0 | 60 通り（全てメガなし） | L の先頭24。`no_mega: true` を付けてレポートに出す（現データでは0構築） |
| 1（8構築） | N1=30（10組×3）、N0=30 | メガなし q=4、メガ1体 20 |
| 2（70構築） | N1=36（12組×3）、N0=12（4組×3）、除外12 | q=4、メガ1体 20 |
| 3（5構築） | N1=27（9組×3）、N0=3（1組×3）、除外30 | q=3、メガ1体 21 |

- q = min(4, N0)、メガ1体の枠 = 24 − q（N1 がそれより少なければ N1。現データでは起きない）。それぞれ L の順に取る。
- メガなしの枠には、L の上位（記事・ガイドのメガなし選出が先）から入る。ガイドのメガなし選出が5つ以上あるときは先の4つだけ。
- 24通りに満たない場合（候補が足りない構築）はその数で良い（`n_cand` を記録）。現データでは全構築24。
- 記事・ガイドの選出が除外規則（メガ2体）や枠の上限で入らなかったときは `rejected: [{order, why}]` に記録する。

---

## 4. ガイドの機械的な読み方

### 4.1 名前の解決 `resolve(text, team)`（決定）
構築の6体の基本名のどれか1つに解決できれば成功、できなければ None。順に試す:
1. 全角ＸＹＺ→半角、前後の空白除去。
2. そのまま／先頭「メガ」を除く／末尾の X・Y・Z を除く／先頭「H」→「ヒスイ」／先頭「A」→「アローラ」、のどれかが基本名（`B._base`）と一致。
3. 略称表 `ABBR`（マンダ→ボーマンダ、グロス→メタグロス、ガブ→ガブリアス、リザ→リザードン、ブリ→ブリジュラス、グソク→グソクムシャ、ガルド→ギルガルド、セグ→セグレイブ、アマガ→アーマーガア、イエ→イエッサン、カメ→カメックス、エッテ→フラエッテ、カバ→カバルドン、ニューラ→オオニューラ、ガモス→ウルガモス、ミミ→ミミッキュ、ルカ→ルカリオ、ヒトム→ヒートロトム、ウォッシュ→ウォッシュロトム）。
4. 文字列が構築のどれか1体の基本名の部分文字列（2文字以上・一意）。

### 4.2 `pick` の要素と分類（決定）
| 要素の形 | 扱い |
|---|---|
| `resolve` できる名前 | 指名（その個体を入れる） |
| 「A or B」「AまたはB」「AかB」で、各々 resolve できる | 選択指名（どちらか1体） |
| 「メガ」「メガ枠」（resolve できないもの） | メガ枠（メガ持ちのどれか1体） |
| 「@1」「@」で始まる・「+」で始まる・「枠」「駒」「1体」を含む（上の2つ以外） | 自由枠 |
| 「刺さっているメガ2体」など、メガ2体を求めるもの | 項目ごと使えない（メガ2体は出さない） |
| それ以外 | 項目ごと使えない |

- **完全**: 指名3体（選択指名なし）。先発は、`note` に「X先発」があり X が3体のどれかに resolve できればそれ、無ければ `pick[0]`。
- **部分**: 枠が合計3以下で、指名・選択指名・メガ枠が1つ以上。先発は「X先発」があればそれに固定、無ければ `pick[0]` が指名ならその個体、他は未指定。部分の条件を満たす選出 = 指名を全て含み、選択指名のどちらかを含み、メガ枠があればメガ持ちを1体含み、先発指定があれば先発が一致する選出。
- 4体以上の指名は使えない。メガ持ち2体を含む完全な選出は使えない（`rejected`）。

### 4.3 `when` の分類（決定）
1. 「基本」で始まる、または「最多」→ **基本項目**。
2. 否定・状況の語（`ない|以外|にくい|づらい|危険|止め|欲しい|たい|多い|っぽい|そう|その他|無理|保証|必要`）を含む → **読めない**。
3. それ以外: `・／/、`で OR のまとまりに分け、各まとまりを `＋+` で AND の項に分ける。各項から、`POKE` の名前（3文字以上、長い順に照合、メガ名は基本名に直す）と `ABBR` を拾う（1つの項に2体以上あれば AND）。名前を1つも拾えない項を含むまとまりは捨てる。残るまとまりが1つ以上 → **条件項目**（どれかのまとまりの全ての名前が相手の6体の基本名にあれば成立）。0 → **読めない**。
   - 例: 「ジュペッタ＋パーモット＋イダイトウ」= 3体全部、「マスカーニャ・ミミロップがいる」= どちらか、「イエッサンカメックス」= 両方、「雨パ」= 読めない。

### 4.4 構築ごとのガイド区分（`plan` が出す）
- `article`: 記事の `picks` があり、候補に1つ以上残る。
- `guide-fixed`: 使える基本項目が完全な選出。
- `guide-cond`: 条件項目が1つ以上使える（基本項目の有無は問わない）。
- `guide-partial`: 使えるのが部分の選出だけ。
- `none`: 使えるものが無い → 基本の選出。
- 各構築について、読めなかった `when`・使えなかった `pick` を `unreadable: [{when, pick, why}]` として保存し、レポートに「ガイド判定不能一覧」として出す。
- 上書き用ファイル `data/rr_guide_overrides.json`（任意、初期は作らない）: `{id: [{"when_any": [[種族…]], "order": [先発, 後発, 後発]}] | {"order": […]}}`。あれば §4.2〜4.3 の結果より優先する。実装はファイルが無くても動くこと。

---

## 5. 選出の決め方

### 5.1 1組の選出（A が B の6体だけを見て決める。決定）
上から最初に決まったものを使う。記録の `src` にその段の名前を入れる。
1. **article**: A の記事の `picks`（候補に残ったもの）が1つならそれ。2つ以上なら、それらだけに絞った基本の選出（§5.3）。
2. **guide-cond**: 条件項目のうち、B の6体で成立するもの（記載順の最初）。完全ならその選出、部分なら部分の条件を満たす候補だけに絞った基本の選出。絞った結果が空なら次へ。
3. **guide-basic**: 基本項目（記載順の最初の使えるもの）。完全／部分の扱いは 2 と同じ。
4. **basic**: 24通り全体での基本の選出。

- 選出したものが候補24通りにあることを必ず確かめる（無ければ次の段へ。`fallback_reason` を記録）。
- ガイドのある構築は「相手の6体で条件が成立するか」で切り替わる。完全な基本項目しか無い構築は相手に依らず固定（先発も固定）。部分の選出は、残りを相手を見て基本の選出で埋める。
- 優先順位は依頼の「記事の選出 → ガイドの記述 → 基本ルール」に従う（記事の `picks` がある9構築ではガイドの条件項目より記事を優先）。

### 5.2 相手の型の扱い
選出を決めるときも対戦中も、相手の記事の型は使わない（`sets.EXCLUDE = {A, B}`、`match_known` 無効）。自分の型は自分の真の型。

### 5.3 基本の選出 `rr_select(A, B, allowed)`（決定）
ワーカーで:
1. `rr_apply(A)`、`B.KNOWN_TEAMS` は §3.3 の置き換え済み。
2. `sets.EXCLUDE = {A.id, B.id}`、`B._OPP_CACHE.clear()`、`B.match_known = lambda *a, **k: None`、`B._load_select_rules = lambda: []`、`B._focus_mons = lambda opp6: {}`（R11 用の手作り規則を全構築で無効にして条件をそろえる）。`B.set_known_context(None)`。
3. `best, top, _ = B.select(B6の基本名, ignore_stored=True, order_filter=lambda o: 正規化(o) in allowed)`。正規化は §3.4 の並べ方。
4. finally で差し替えたものを元に戻す。
5. `B.select` の内部の `_run_games` はデーモンのワーカー内では Pool を作れず逐次に落ちる（それで良い。Windows でも同じ結果になる）。
6. 結果 `{order, top3, sec}` を `rr_plan.json` の `sel["A|B"]` に保存（1件ごとに atomic）。以後は再計算しない。

### 5.4 選出の保存と再利用
`sel` の鍵は順序つき `"A|B"`（A が選ぶ側）。段階が進んでも既存の `sel` はそのまま使う。再戦（§6.3）も同じ選出を使う（違いは乱数の種だけ）。

---

## 6. 対戦の形式

### 6.1 1戦（決定）
- side 0 = X、side 1 = Y。X の選出 = `sel["X|Y"]`、Y の選出 = `sel["Y|X"]`。
- ワーカー: `rr_apply(X)` → `refine.blind_play((None, Y.id, selX, selY, seed, 4, 4, False, None, False, (X.id,)))`（§9.2 の拡張: `party=None` は「適用済み」、11番目は追加の除外 id）。
  - side 1 の真の型 = Y の rr 構築（§3.3）、side 0 の真の型 = X の rr 構築（`B.MY`）。
  - 互いの型の推測は使用率・他の記事（X・Y の記事は除外）・見えた技から。両者4手読み。
- 30ターンで決着しないと `judged: true`（評価値の符号で判定）。判定決着は勝敗に含めつつ別にも数える。評価値がちょうど0のとき `blind_play` は side 1 勝ちにする（既知の偏り。左右入れ替えで相殺される。件数をレポートに出す）。
- 例外（`res: None`）は記録し、`run` は既定では再実行しない（`--retry-errors` で再実行）。

### 6.2 1組あたりの戦数と種（決定）
- 組 {A, B} は id の文字列順で `a < b` とする（段階・並びに依らない）。
- 本戦 k=0: side 0 = a、k=1: side 0 = b（左右の入れ替え）。
- 種 = `zlib.crc32(f"rr{a}{b}{k}".encode())`。対戦の鍵 = `f"{a}|{b}|{k}"`。

### 6.3 再戦（第2段階以降）
- その段階の本戦が全て終わった時点の順位（§7）で上位5構築を決め、`rr_plan.json` の `rematch[tier]` に保存して固定する。
- 上位5の各組（10組）に k=2,3,4,5 の4戦を追加（k が偶数なら side 0 = a）。既にある鍵は飛ばす。
- 再戦は勝率の主表には入れず、「再戦表」と「直接対決」に入れる（主表は全構築が同じ数だけ戦った結果にするため）。

### 6.4 鏡合わせ（selftest 用）
A 対 A: `sel["A|A"]` を両者が使い、kid = A。種 `crc32(f"rrmirror{A}{k}")`。結果は `rr_games.json` に入れず、selftest の出力にだけ出す。

---

## 7. 集計とレポート

### 7.1 構築ごとの値
- 本戦の戦数 G、勝ち W、勝率 W/G、Wilson 95%区間、判定決着の数と判定での勝ち、決着のみの勝率、平均残HP（自分の3体の残りHP%の平均。負けは0として含める）、`weight=1.0` の相手への勝率（参考）。
- 選出の分布: `src` ごとの回数（article / guide-cond / guide-basic / basic）と割合、よく使った選出の上位3（回数）、メガを含む選出の割合。

### 7.2 順位（決定）
1. 勝率（本戦のみ）の降順。
2. 勝率が同じ構築どうしは、その構築どうしの直接対決（再戦を含む）の勝率。
3. 平均残HP。
4. id。

### 7.3 `logs/ROUNDROBIN.md` の中身
1. 条件（4手/4手、ブラインド、選出規則、種の式、対象と段階、進捗: 段階ごとの済み/全体、実測の1戦の時間）。
2. 順位表（全構築。順位・構築名・rank/R・勝率・95%区間・判定（勝/数）・平均残HP・強い相手への勝率・選出の出どころ）。
3. **R11 の順位**と、得意な相手（2戦2勝の構築）・苦手な相手（2戦0勝）の一覧、R11 の選出の分布。
4. 勝敗行列: 第1段階の25構築は md に表で（各セルは a 視点の勝数/戦数）。全体は `logs/refine/rr_matrix.csv`。
5. 選出の分布（構築ごと。ガイド通り/基本の割合、よく使った選出）。
6. 再戦表（上位5の10組、本戦2戦＋再戦4戦）。
7. 判定決着の一覧、例外の一覧、評価値0の件数。
8. ガイド判定不能一覧（§4.4）と、候補から外れた記事・ガイドの選出（`rejected`）。
9. 誤差の注意: 第1段階は1構築48戦で95%区間の幅が約±14ポイント、第3段階は166戦で約±7.6ポイント。区間が重なる順位差は確かでない、と明記。選出は組ごとに固定なので、結果は「その選出どうしの相性＋乱数」であること、型の推測は使用率データに依ること、ガイドの読み取りは機械的で誤りうることも書く。

---

## 8. ファイル

| パス | 中身 | 書き方 |
|---|---|---|
| `logs/refine/rr_plan.json` | `version, created, depth:[4,4], sig, order(並び), tiers:{1:[ids],2:[...],3:[...]}, teams:{id: rr構築＋candidates＋static＋guide区分＋unreadable＋rejected}, sel:{"A|B": …}, rematch:{tier:[[a,b],…]}, timing` | `safeio.write_json`（選出1件ごと） |
| `logs/refine/rr_games.json` | `version, plan_sig, depth, games:{key: {a,b,k,side0,side1,sel0,sel1,src0,src1,seed,res,winner,judged,turns,left,faints,sec,error,rematch}}` | 1戦ごとに `safeio.write_json`。`log` は入れない（軽くする） |
| `logs/refine/rr_logs.jsonl` | `{key, log}` を1行ずつ | 追記＋flush。読むとき壊れた最終行は捨てる |
| `logs/refine/rr_matrix.csv` | 全構築の勝敗行列 | report が書く |
| `logs/refine/rr_timing.json` | selftest の実測 | selftest が書く |
| `logs/ROUNDROBIN.md` | §7.3 | report が書く |

- `sig` = rr 構築（全84）の JSON と `RR_VERSION` の sha256。`plan` で sig が違えば止まり、`--force` で既存を日時付きの名前に退避して作り直す（`core_test.load_data` と同じ）。
- `--out-dir DIR` で上の出力先をまとめて変えられる（selftest は一時ディレクトリを使う）。

---

## 9. 実装

### 9.1 `tool/roundrobin.py`（新規）
```
python3 roundrobin.py plan --tier 1|2|3 [--tier1-size 24] [--no-select] [--procs 4] [--force] [--out-dir D]
python3 roundrobin.py run  [--max-games N] [--procs 4] [--retry-errors] [--games-per-pair 2] [--out-dir D]
python3 roundrobin.py report [--out-dir D]
python3 roundrobin.py selftest [--quick] [--out-dir D]
python3 roundrobin.py show <id>        # その構築の候補24通り・ガイド区分・読めなかった記述を表示
```
- `plan --tier n`: 対象（§2.1）・rr 構築・静的スコア・候補24通り・ガイド区分を作り（全84構築ぶん。数分）、段階 n の対象の順序つき全組について選出を計算して保存（`--no-select` なら飛ばす）。段階 n までの本戦の鍵の一覧と、戦数・所要時間の見積り（`rr_timing.json` があればその値で）を表示。何度呼んでも、済んだ選出は再計算しない。
- `run`: `rr_plan.json` の最も高い段階までの本戦のうち未実行のもの（`res` が無いもの）を実行。順番は段階の若い順、段階内は「全構築の戦数がそろって増える」ように（円環法の回戦順、k=0 を全て → k=1 を全て）。選出が未計算の組があれば先に計算する。段階の本戦が全て終わると、第2段階以降は再戦の上位5を決めて再戦を続ける。`--max-games` で打ち切り可。中断しても次の `run` で続きから（コンテナ再起動に備え、1戦ごとに保存）。並列は `core_test` と同じ（fork/spawn の Pool、`imap_unordered(chunksize=1)`、ワーカー先頭で初期化）。進捗表示: `[済/全] key 勝敗 手数T 秒 経過分`。
- `report`: §7.3 を書く。途中でも書ける（済んだ分だけで集計し、進捗を出す）。
- ワーカー初期化 `_rr_init()`（冪等）: `refine.teams()` を1度呼ぶ → `B.KNOWN_TEAMS` を §3.3 で置き換え → 以後 `rr_apply`。

### 9.2 `tool/refine.py` の変更（後方互換、この2点だけ）
`blind_play` で:
1. `excl = args[10] if len(args) > 10 and args[10] else ()` を読み、`_sets.EXCLUDE = {kid} | set(excl)`。
2. `if party is not None: apply_party(party)`（None なら呼び出し側が適用済み）。

既存の呼び出し（7〜10要素、party あり）の動作は変わらない。

### 9.3 しないこと
- `known_teams.json`・`new_teams_m6b.json`・`data/party/*`・`select_rules.json`・`article_sets.json` を書き換えない。
- `refine.trips_fixed`・`prep.prep_team*` を呼ばない（既存ファイルを書くため）。
- `learn.py` の記録を書かない。

---

## 10. 受け入れ条件（selftest が全て ○ を出すこと。実装者は本番の `run` を実行しない）

1. `python3 -m py_compile roundrobin.py refine.py` が通る。
2. **全84構築が適用できる**: 各構築で `rr_apply` が通り、候補の先頭の選出どうしで `B.engine_game` が例外なく作れる（`c0ae6e25` のメタモン、`37993777` の持ち物なしを含む）。名前がメガでないストーン持ち18体が、side 0・side 1 の両方で `can_mega` になる。
3. **候補の制約**: 全84構築で、候補数 ≤24（現データでは全て24）、重複なし（先発＋後発の組で一意）、全て構築の6体から、メガ持ち2体を含む選出が0、メガなしの選出 ≤4（メガ3体の構築は ≤3）、メガ持ちが1体以上いる構築ではメガ1体の選出 ≥20。記事・ガイドの使える完全な選出（メガ2体のものを除く）が、メガなし枠の上限で外れたもの以外、全て候補に入っている。
4. **ガイド通りの選出が使われる**: (a) 区分 `guide-fixed` の構築を全て、条件項目が成立しない相手（区分 `none` の構築から選ぶ）に対して選ばせ、`sel` が基本項目の選出と一致し `src = guide-basic`。(b) 区分 `guide-cond` の構築を最大5つ、条件の種族を含む相手（条件を満たす構築を対象から探す。無ければ飛ばしてそう表示）に対して選ばせ、その項目の選出（部分なら条件を満たす選出）になり `src = guide-cond`。(c) 区分 `article` の構築で記事の選出が使われる。(d) 区分 `none` の構築は `src = basic`。
5. **ガイド区分の表**を表示する: 区分ごとの構築数、読めなかった `when`/`pick` の数（§1.1 の目安と大きくずれていれば理由を表示）。
6. **鏡合わせ**: 第1段階の上位3構築について A 対 A を各8戦（計24戦、4手/4手）。side 0 の勝率が 25〜75%、例外0。
7. **再開**: 一時ディレクトリで `plan --tier 1`（対象を3構築に絞るテスト用の内部引数で可）→ `run --max-games 2` → `run --max-games 2` で、2回目は1回目の鍵を再実行せず新しい2戦だけを行う。`rr_games.json.tmp` が残っていても読み込みが壊れない。`rr_logs.jsonl` の壊れた最終行を無視できる。
8. **再現性**: 同じ鍵の1戦を2回実行して `res`・`turns`・`left` が一致する。種が `crc32(f"rr{a}{b}{k}")` であること。
9. **既存結果ファイルの sha256 不変**: selftest の前後で `data/known_teams.json`、`data/new_teams_m6b.json`、`data/party/*.json`、`data/select_rules.json`、`data/article_sets.json`、`logs/refine/` の rr_* 以外の全 `.json`、`logs/*.md`（ROUNDROBIN.md 以外）の sha256 が一致する。
10. **後方互換**: `refine.blind_play` を従来の7要素（party あり）で1戦呼べ、`sets.EXCLUDE == {kid}` になる。
11. **1戦の所要時間を実測**: 4プロセスで8戦（第1段階の組から）を実行し、1戦のワーカー時間（中央値・平均）と実時間/戦を `rr_timing.json` に保存して表示。あわせて基本の選出1回のワーカー時間を3回測る。これを使って §2.3 の表（段階ごとの戦数・時間）を出し直して表示し、第1段階が5時間を超える見込みなら §2.3 の縮小案を表示する。

`selftest --quick` は 6・11 を2戦ずつに減らす（開発中の確認用）。受け入れは `--quick` なしで行う。

---

## 11. 実装者への注意
- 実行して良いもの: `py_compile`、`selftest`、`show`、`plan --tier 1 --no-select`、`--out-dir` を一時ディレクトリにした `plan`/`run`（selftest の範囲）。本番の `logs/refine/rr_*` に対する `run` は実行しない。
- `B.select`・`B.opp_pick_weights` などモジュールの関数を差し替えるときは必ず try/finally で戻す。
- `B.KNOWN_TEAMS` の置き換え後に `refine.teams()` を呼ばない（§3.3）。
- Windows（spawn）でも同じ結果になるよう、ワーカー関数の先頭で `_rr_init()` と `rr_apply()` を毎回呼ぶ。
- 報告には、selftest の出力（全項目の ○/×）、ガイド区分の表、候補生成で外れた記事・ガイドの選出の一覧、実測時間と段階ごとの見積りを含める。
