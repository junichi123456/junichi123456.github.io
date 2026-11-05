# 記事の動き方（プレイブック）をシミュレーションで再現する仕様書

作成: Opus 5.5 ／ 実装: Sonnet 5.5（`model: sonnet`）／ 受け入れ確認: Opus 5.5
作業フォルダ: `pokechamp/tool/`（Linux は `python3`、Windows は `python`）

変更するファイル:
- 新規 `tool/playbook.py`（語彙・検証・発動判定・交代先選択・集計）
- `tool/study.py`（`note` で `play` を検証・保存、`play` / `pending-play` サブコマンド、レポートに表示）
- `tool/refine.py`（`blind_play` に後方互換の引数 `args[12]` を1つ追加）
- `tool/roundrobin.py`（各実行で既定オン、`--no-playbook`、`playbook` サブコマンド＝selftest / ab / report）
- `tool/data/known_teams.json`（乾坤一擲リザホーク `db0baa2843d2bd4b` の `guide.play` を §7.1 の内容で書く。**他の構築・他のキーは変更しない**）

対象外: Star Crusade（ルートの `index.html`・`starcrusade/`）、`game_watch.py`、実戦用 `battle.py` の判断（`guide_lines` は `play` を表示しない＝変更しない）、`search.py`・`policy.py`・`engine.py`（読むだけ）、既存の結果ファイル（`logs/refine/` 以下の既存の全ファイル）。

**実装者は本番（`roundrobin.py run/full/deny/adapt/counter run`、`playbook ab` の全量）を実行しない。** §9 の受け入れ条件の確認だけを行う。バックフィル（§6）も実装者は行わない（Claude の別作業）。

「事実」はコードとデータで確かめた内容。「決定」はこの仕様で決めた内容。

---

## 0. 目的（ユーザー依頼）

「夜間学習において、学習内容の追加を行います。構築記事内に選出基準や運用方法が明記されている場合、可能な限りにおいてシミュレーションでは**記事が想定する動き方を行う**ものとします」

- 選出基準は既存の `guide.picks`（roundrobin の `guide-cond` / `guide-basic`）で反映済み。今回は**運用方法（対戦中の動き方）**を機械可読の規則 `guide.play` として保存し、その構築側として戦うとき、規則が成立する局面で探索の根行動を規則の行動に上書きする。
- **記事に明記されていない動きは書かない**（推測で補わない）。ユーザーが自分の実戦の流れとして明示した動きだけは `origin: "user"` として書いてよい（§1.4）。

---

## 1. 現状（事実）

### 1.1 保存形式（study.py）
- `known_teams.json` = `{"teams": [...]}`。各構築 `{id, title, url, team:[{name, nature, ability, base_ability, item, moves:[和名], ap}], picks, notes, study, counter, guide, rating, regulation}`。2026-11-05 時点で 95 構築すべてに `guide` がある（全員 6 体）。
- `study.py note <id> <json>`（study.py 237–246）: JSON から `GUIDE_KEYS = ('type','core','plan','picks','heavy','notes')` だけを取り、`date` を付けて `guide` を**丸ごと置換**し、`report()` で `logs/study` のレポート（REPORT_P）を作り直す。検証は無い。
- `study.py pending`: `guide` が無く本文 `logs/study/text/<id>.txt` がある構築。
- `save()`（207–226）は再取り込み時に `picks/notes/study/counter/guide` を引き継ぐ（`guide` ごと引き継ぐので `guide.play` も残る）。
- 本文ファイルは `題名\nURL\n\n本文(先頭12000字)`。

### 1.2 実例: 乾坤一擲リザホーク（`db0baa2843d2bd4b`）
- team: メガムクホーク（インファイト/ブレイブバード/ブレイズキック/いのちがけ）、ミミッキュ（じゃれつく/かげうち/トリックルーム/のろい、ゴツゴツメット）、イダイトウ（おはかまいり/アクアジェット/クイックターン/みがわり）、メガリザードンX、ガブリアス、アシレーヌ。
- guide.plan「いのちがけムクホークで不利対面も強引に押し…」、picks「基本: 初手に仕事ができる枠＋ミミッキュ＋イダイトウ」。
- 本文の運用の記述（行番号は text ファイル）:
  - 11「ムクホークに加え、様々な相手に切り返しが可能なゴツメトリルミミッキュ、トリル下で高火力を押し付けられるイダイトウを基軸とした。」
  - 14「初手に出し負けしにくく仕事量が期待できるポケモンを置き、ミミッキュ＠１で切り返す。」
  - 22「不利対面ではいのちがけで特攻していくだけの鳥と見せかけて…」
  - 28「高速物理や積み技、イエッサン絡みにトリルで切り返す枠。」
  - 54「基本的に、初手枠＋ミミッキュ＋後発枠(イダイトウがメイン)」
- 「のろいで退場」「ムクホでまず一番削れる技」「イダイトウで全抜き」は本文に明記が無い（ユーザーの実戦の流れ）。

### 1.3 シミュレーション（refine.blind_play, refine.py 541–643）
- `args = (party, kid, my_order, opp_order, seed, my_depth, opp_depth, know, rules, trace, excl, deny)`。側0 は呼び出し側が適用済みの構築（roundrobin は `rr_apply(_TEAMS[X])`）、側1 は `kid`。
- 毎ターン: 側0 `a0` = `S.lookahead_action(bst0, 0, my_depth[, mode='deny', info])` または `policy.choose(...)`（rules 指定時、deny とは併用不可）。側1 `a1` = `S.lookahead_action(belief(st,0,t_me,seen[0]), 1, opp_depth[, deny])`。
- `bst0 = st if know else belief(st, 1, t_opp, seen[1])`。`seen[i]` = 側 i の場の各スロットが使った技（相手から見えた技）。
- 実際の進行は `E.step(st, a0, a1, rng=rng, chooser=chooser)`。`chooser(st, side, opts)` は瀕死・とんぼ返り系の後の交代先（既定 `S.chooser`、rules 時は `policy.make_chooser(ctx)`、側0のみ差し替え）。
- 戻り値 `{'res','log','faints','left','fired','rocks_turn','tox','turns','judged'[, 'mv'][, 'deny_stats']}`。
- 30 ターン上限。

### 1.4 根行動の上書きの枠組み（policy.py）
- `Ctx`（ターン数・発動記録 `fired=[(turn, rid, orig, new)]`）、`ALL_RULES`、`ranked_root(bst, depth)` = 側0の全根行動の値付き一覧（[0] が `lookahead_action` と一致、同値は先の手）、`choose()` = 拘束状態（`lockedmove/twoturnmove/mustrecharge/uproar`・行動1つ）では上書きしない → 規則 → 禁止手を除いた次善手、`make_chooser` = 交代先の上書き。**側0専用**（`ranked_root` は i=0 固定）。
- 行動の形: `('m', move_id, mega:bool)` / `('s', slot)`。`E.actions` はメガ可能なら `mega=True` の版だけを返す（engine.py 4093–4108）。メガは `acts[i][2]` が真のときだけ起きる（engine.py 3876）＝ `('m', x, False)` を渡せば「メガしない」も実行できる。
- `E.MOVES[id].ja` が和名。和名→id は逆引きで作れる（例: いのちがけ=`finalgambit`、トリックルーム=`trickroom`、のろい=`curse`、みがわり=`substitute`）。トリックルームは `st.pseudo.get('trickroom')`、ステロは `st.sides[k].cond.get('stealthrock')`。
- `S.best_damage(st, i)` = 側 i の場の最大期待ダメージ（相手の現HP比）、`S.est(st, i, mid)` = 技ごと、`S.faster(st, i)` = 1/0/0.5（トリル込みの行動速度）。`S.evaluate` は決着で ±100、それ以外は数体分程度のスケール。

### 1.5 deny（search.py 747–794）
- `_lookahead_deny(..., info)` は `info['values'] = [(action, value)]`（全根行動、側 i から見た値、`front_bias` は i==0 のみ）を返す。最善は値最大の最初の手。

### 1.6 roundrobin の実行（すべて `R.blind_play` を `args` 12 個まで、`rules=None`）
- full / run: `_job_game`（584）`(None, Y, selX, selY, seed, 4, 4, False, None, False, (X,))`。
- deny: `_job_deny`（1318）同上＋`deny`。
- adapt: `_job_ad`（1978）`_AD_PLAY(... (s0,), (True, True))`、選出は `_AD_SELECT`。
- counter: `_job_ct`（2530）`_CT_PLAY(... (s0,), (True, True))`。
- 選出のガイド利用: `article`（記事の選出）→ `guide-cond`（picks の条件付き）→ `guide-basic` → `basic`（rr_select）（roundrobin.py 509–524）。
- 結果ファイルは `plan_sig` が一致しないと再開を拒否する（622、1342、2058、2562）。プールは `make_pool(procs, teams)` → `_worker_init(teams)`（fork / Windows は spawn）。
- 既存結果: `logs/refine/rr_games.json`、`rr_deny_games.json`（1局 約15秒、例 `full:49174cf5df35f7da|adb3c969ff4e76ee|0` に sel0/sel1/seed/res/turns/left/faints が残る）、`ad_games.json`、`ct_games.json` ほか。

---

## 2. スキーマ `guide.play`（決定）

`guide.play` は規則のリスト（**最大 10 規則**）。`[]` は「記事を読んだが運用の明記が無い」を意味する（未記入＝キーが無い、と区別する）。

```json
{"id": "p1", "who": "メガムクホーク", "phase": "turn",
 "when": {...} | [{...}, {...}],
 "do": {...},
 "until": {...},
 "max": 3,
 "origin": "article",
 "note": "要約（日本語・40字以内）",
 "src": "記事の該当文の短い引用（60字以内）"}
```

| キー | 必須 | 意味 |
|---|---|---|
| `id` | 必須 | 構築内で一意。`^[a-z0-9_]{1,12}$` |
| `who` | 必須 | `phase:"turn"`: 規則が働く自分の場のポケモン（構築内の名前。メガ名・元の名どちらでも可、`battle._base` で正規化）または `"*"`（誰が場にいても）。`phase:"replace"`: 常に `"*"` |
| `phase` | 任意 | `"turn"`（既定。毎ターンの行動）／`"replace"`（瀕死・交代技の後の交代先選び） |
| `when` | 必須 | 発動条件。dict = 全条件 AND、list = いずれかの dict が成立（OR）。`{}` は常に成立 |
| `do` | 必須 | 行動（§2.2 のどれか1種＋任意の `mega`） |
| `until` | 任意 | 解除条件（`when` と同じ語彙、dict のみ）。一度成立したら、その試合の残りでこの規則は無効 |
| `max` | 任意 | この試合での発動上限（既定: `do.switch` は 2、それ以外は 6） |
| `origin` | 任意 | `"article"`（既定。記事の明記）／`"user"`（ユーザーが明示した流れ。夜間ルーチンは使わない） |
| `note` | 必須 | 規則の要約 |
| `src` | `origin:"article"` なら必須 | 記事本文の該当文の引用（本文に**部分文字列として**含まれること。空白差は無視して照合） |

### 2.1 `when` の語彙（決定。これ以外のキーは拒否）

判定はすべて「その側が見えている情報」（`bst` = その側の belief。相手の型は推測、HP・状態・ランク・場は見える）で行う。`phase:"replace"` の判定は真の状態 `st` の**見える部分**だけ（下表の ※ は replace でも可）。

| キー | 値 | 成立 |
|---|---|---|
| `turn` | int または `[lo, hi]` | 試合のターン番号（1 始まり、`[lo, null]` 可）※ |
| `lead` | bool | 自分の場が初手のポケモンで、まだ一度も交代していない |
| `foe` | [名前] | 相手の場のポケモン（`_base` 比較）がいずれか ※ |
| `foe_type` | [タイプ和名] | 相手の場のポケモンの現在タイプにいずれかを含む（18タイプ和名→英名の表を playbook.py に持つ）※ |
| `foe_shown` | [技和名] | 相手の場のポケモンが既に使った技（`seen[相手]` の当該スロット）にいずれかを含む |
| `foe_boosted` | bool | 相手の場のポケモンの能力ランクのどれかが +1 以上（＝積み技を使った後） ※ |
| `my_hp` | `[lo, hi]` | 自分の場の HP 割合（0–1、両端含む） ※ |
| `foe_hp` | `[lo, hi]` | 相手の場の HP 割合 ※ |
| `my_sub` / `foe_sub` | bool | 自分／相手の場が `substitute` 状態 |
| `trickroom` | bool | トリックルーム中 ※ |
| `rocks_on_foe` / `rocks_on_me` | bool | 相手側／自分側にステルスロック ※ |
| `mega_used` | bool | 自分がメガシンカ済み ※ |
| `foe_faster` | bool | `S.faster(bst, i) == 0.0`（相手が先に動く。トリル込み） |
| `foe_can_ko` | bool | `S.best_damage(bst, 1-i) >= 1.0`（相手の最大打点で自分が倒れる見込み） |
| `can_ko` | bool | `S.best_damage(bst, i) >= 1.0` |
| `bad_matchup` | bool | 不利対面 = `foe_can_ko and not (can_ko and S.faster(bst, i) == 1.0)` |
| `bench_alive` | [名前] | 自分の控えにいずれかが生存（`who` 以外）※ |
| `foe_left` | `[lo, hi]` | 相手の残り生存数（選出3体中）※ |
| `my_left` | `[lo, hi]` | 自分の残り生存数 ※ |
| `after` | [規則 id] | この試合でいずれかが既に1回以上発動した（流れの順序を表す）※ |

### 2.2 `do` の語彙（決定。次のうち**ちょうど1種**＋任意の `mega`）

| キー | 値 | 行動 |
|---|---|---|
| `move` | [技和名]（1個以上） | 並び順に、最初に合法な技を使う（「優先技の並び」もこれで書く）。技は `who` の技構成に限る |
| `best_damage` | `true` | 合法な攻撃技（`cat != 'status'`）のうち `S.est(bst, i, mid)` 最大（同値は技構成の順） |
| `switch` | [名前] | 並び順に、生存している控えへ交代（`phase:"turn"`）／その名前を交代先に選ぶ（`phase:"replace"`） |
| `avoid` | [技和名] | これらの技を根行動の候補から外す（禁止。他の規則・通常の読みと併用される） |
| `preserve` | [名前] | これらへの交代（`phase:"turn"` の交代・`replace` の交代先）を、他に選択肢がある限り選ばない（「最後まで温存」） |
| `mega` | bool（`move` / `best_damage` と併用のみ） | `true`: メガ可能ならメガして使う（既定の挙動と同じ）／`false`: メガせずに使う（`('m', id, False)`） |

- 「みがわり→待つ」は2規則で書く: `when:{"my_sub":false}, do:{"move":["みがわり"]}` と `when:{"my_sub":true}, do:{"move":[...]}`（何を待つ／使うかが記事に書かれている場合だけ）。
- `phase:"replace"` で使える `do` は `switch` と `preserve` のみ。

### 2.3 検証 `playbook.validate(play, team) -> list[str]`（決定。空リスト＝合格）
拒否理由（日本語・規則 id 付き）を全部返す:
- `play` が list でない／11 規則以上／`id` 重複・形式違反。
- 未知のキー（規則・`when`・`do`・`until`）。`do` の種類が 0 または 2 以上（`mega` を除く）。`mega` を `move`/`best_damage` 以外と併用。
- `who`・`foe` 以外の名前（`switch`/`preserve`/`bench_alive`）が構築の6体に無い（`foe` は `B.POKE` 等の既知の種族名であればよい）。
- `move`/`avoid` の技が `who` の技構成（`team[].moves`、和名）に無い（`who:"*"` のときは構築の誰かの技構成）。`foe_shown` の技が `B.MOVE` に無い。
- タイプ和名が18タイプに無い。範囲が `[lo, hi]` でない・lo>hi・HP が 0–1 外。`after` が未定義の id を指す。
- `origin:"article"` で `src` が空、または本文（`logs/study/text/<id>.txt`）に含まれない。`origin` が `article/user` 以外。
- `phase:"replace"` で `do` が `switch`/`preserve` 以外。

---

## 3. シミュレーションでの適用（決定）

### 3.1 新モジュール `playbook.py`
```
VOCAB_WHEN, VOCAB_DO, TYPE_JA                        # 語彙と和名→英名
validate(play, team, text=None) -> [str]
load_all(path=prep.KNOWN_P) -> {team_id: play}       # guide.play がある構築だけ（[] も含めない）
play_sig(plays) -> str                               # sha256(json.dumps(sorted, ensure_ascii=False, sort_keys=True))[:12]
class PB:
    __init__(self, play, side, team_id)
    decide(self, st, bst, side, a0, ranked_fn, seen, turn) -> (action, info)   # 根行動
    chooser(self, base_chooser) -> chooser(st, side, opts)                      # 交代先
    stats(self) -> {'fired': [...], 'rejected': [...], 'uses': {rid: n}}
ranked(bst, i, depth, k_self=3, k_opp=2, extra=()) -> [(v, a)]   # 側 i 版 ranked_root（3.3）
```

### 3.2 `PB.decide` の手順（毎ターン、その側の根行動について）
1. **素通り**: `a0 is None`、合法手 `E.actions(st, side)` が1つ以下、`a0[1] == 'recharge'`、または場が `lockedmove/twoturnmove/mustrecharge/uproar` → `(a0, None)`（policy.choose と同じ）。
2. `until` が成立した規則を無効化（記録 `rejected: (turn, rid, 'until')`）。
3. `phase:"turn"` で、`who` が場のポケモン（または `"*"`）、未無効・`max` 未満、`when` 成立の規則を**リスト順**に集める。無ければ `(a0, None)`（**探索結果を一切変えない**）。
4. 制約の集約: 成立した `avoid` → 禁止技集合、`preserve` → 禁止交代先集合。
5. 行動規則（`move`/`best_damage`/`switch`）を**リスト順**に試す。最初に「合法かつガード通過」した規則を採用:
   - 合法: 行動が `E.actions(st, side)`（**真の状態**の合法手）に含まれる。`mega:false` は `('m', id, True)` が含まれれば `('m', id, False)` を合法とみなす。メガ可能でない時の `mega:true/false` はそのまま `E.actions` の版を使う。禁止集合に入る行動は不合法扱い。
   - ガード（致命的悪手の除外）: `ranked_fn()` で根行動の値一覧（側 i 視点）を得て（**このとき初めて計算**、1ターンに1回だけ）、規則の行動の値 `v_r` と最善 `v_0` を比べ、`v_r <= PB_LOSS (=-50.0) < v_0`（読みの範囲で負けが確定する）または `v_0 - v_r > PB_GAP (=1.5)` なら却下（`rejected: (turn, rid, 'guard', round(v_0 - v_r, 3))`）。
   - 不合法なら `rejected: (turn, rid, 'illegal')`、次の規則へ。
6. 採用した規則があれば `fired: (turn, rid, aname(a0), aname(a))` を記録し、`uses[rid] += 1`、`(a, rid)` を返す。行動が `a0` と同じでも発動として数える（`same=True` を付ける）。
7. 行動規則が全て不採用で、制約（4）が `a0` を禁止している場合: 値一覧の上位から禁止されていない最初の行動（無ければ `a0`）を返し、その制約規則を発動として記録。
8. それ以外は `(a0, None)`。

**規則どうしの衝突**: 行動規則はリスト順が優先（記事の流れ順に書く）。制約（`avoid`/`preserve`）は行動規則にも通常の読みにも常に掛かる。`switch` と `preserve` が矛盾したら `preserve` が勝つ（不合法扱い）。

### 3.3 根行動の値一覧 `ranked_fn`
- 通常の読み: `playbook.ranked(bst, i, depth)` = `S.lookahead_action` の根の計算をそのまま側 i に一般化し全行動の値を返す（`sign`、`theirs = prune(st, j, k_opp+1)`、`PESS` 混合、`front_bias` は i==0 のみ、ソートは `(-v, 元の順)`）。`extra` に `('m', id, False)` を渡すと同じ式で値を付けて含める。**`ranked(...)[0][1] == S.lookahead_action(bst, i, depth)` を selftest で確認**（側 0・1 とも）。
- deny モード: その側の `dinfo[i]['values']`（既に計算済み）を使う（追加の探索なし）。`mega:false` 版は deny には値が無いので、ガードは同じ技の `mega:true` 版の値で代用する。
- `a0` は従来どおりの計算（`S.lookahead_action` / deny）で求め、`ranked_fn` はガードが必要になった時だけ呼ぶ。→ 規則が成立しないターンの計算・乱数消費は従来と同一。

### 3.4 交代先 `PB.chooser(base)`
- `side` がこの PB の側でない、`opts` が空 → `base(st, side, opts)`。
- `phase:"replace"` の規則（`when` は ※ のキーのみ、`st` で判定）をリスト順に: `switch` の名前を並び順に `opts` から探して最初に見つかったものを返す（発動記録 `fired: (turn, rid, '-', 名前)`）。`preserve` は `opts` から除く（全部除かれるなら除かない）。
- 規則で決まらなければ `base(st, side, 除外後の opts)`。
- `E.step` の中（探索木）では使わない。実際の進行の `E.step(..., chooser=...)` だけ。

### 3.5 無限ループ・暴走の防止
- 規則ごとの `max`（既定 `switch` 2、他 6）。
- `do.switch`（turn）は**2ターン連続で発動しない**（前ターンに同じ規則が発動していたら不成立扱い）。
- 同じ規則が3ターン連続で発動し、その間 自分の場・相手の場・両者の HP（%丸め）が全く変わらなければ、その規則を以後無効（`rejected: (turn, rid, 'stuck')`）。
- 30 ターン上限は従来どおり。

### 3.6 `blind_play` の引数追加（refine.py）
- `args[12]` = `(play0, play1)`。各要素は `None` または 規則リスト（検証済み）。省略・`None`・`(None, None)` は従来と**完全に同じ実行**。
- `rules`（args[8]）が `None` でない側0とは併用不可: `play0` と `rules` が両方あれば `ValueError('playbook and rules cannot be combined')`。deny とは併用可（3.3）。
- 側ごとに `PB(play_k, k, team_id_k)`（側0の team id は `excl[0]` があればそれ、無ければ `'side0'`。側1 は `kid`）。
- 毎ターン:
  - 側0: `bst0` を1回だけ作り（`st if know else belief(...)`）、従来の `a0` 計算に渡した後、`play0` があれば `a0, rid = pb0.decide(st, bst0, 0, a0, ranked_fn, seen, tn+1)`。
  - 側1: 同様に `bst1 = belief(st, 0, t_me, seen[0])` を1回だけ作り、`a1` の後に `pb1.decide`。
  - **`play` が無い側は `belief` の呼び方も含めて従来コードのまま**（従来は式の中で直接 belief を呼んでいる。play がある側だけ変数に取り出す）。
- 交代先: `chooser` を `pb1.chooser(pb0.chooser(base))` のように合成（base は従来の chooser）。
- 戻り値に `play` がある時だけ `'pb': {'0': pb0.stats(), '1': pb1.stats()}`（無い側は省く）を追加。`fired`（policy）とは別キー。

### 3.7 roundrobin での既定オン
- `_worker_init(teams, pb_on=True, pb_only=None)`、`make_pool(procs, teams, pb_on=True, pb_only=None)`（spawn でも届くよう initargs で渡す）。ワーカーは起動時に `_PB = playbook.load_all() if pb_on else {}`。
- `_job_game` / `_job_deny` / `_job_ad` / `_job_ct` は blind_play の args の末尾に `(_PB.get(s0), _PB.get(s1))`（`pb_only` 指定時は `pb_only` の構築の側だけ）を足す。`_PB` が空なら**何も足さない**（＝args は従来と同じ長さ）。
- 各サブコマンド（`run`、`deny run/full`、`adapt run`、`counter run`）に `--no-playbook` を追加。既定はオン。
- 結果ファイルのトップに `'playbook': play_sig(_PB)`（オフ時は `None`）を書く。既存ファイルを読むとき、キーが無い＝`None` とみなし、今回の値と違えば `SystemExit('既存の結果は playbook={old}。--no-playbook で続行するか --out-dir で別フォルダに出力してください')`。→ **既存の `logs/refine/*.json` は書き換わらない**（オンで既定フォルダに対して run すると止まる）。
- 各ゲーム記録に `r['pb']` があれば `rec['pb']` として保存。
- 選出（`article` → `guide-cond` → `guide-basic` → `basic`、adapt の `_AD_SELECT`）は**変更しない**。プレイブックは選出後の対戦中だけに効く。`who` が選出に入っていなければその規則は単に成立しない。

### 3.8 発動率の集計 `roundrobin.py playbook report [--out-dir D]`
- `--out-dir`（既定 `logs/refine`）の `rr_games.json` / `rr_deny_games.json` / `ad_games.json` / `ct_games.json` / `pb_ab_games.json` のうち存在するものを読み、`rec['pb']` を持つ記録を構築×規則で集計:
  - 発動回数、発動した試合数、その試合の勝率（その構築側から見た勝ち=1、引分0.5）、発動しなかった試合（同じ構築・同じ選出にその `who` を含む）の勝率、`rejected` の理由別件数（guard/illegal/until/stuck）。
- 出力: `<out-dir>/pb_report.md`（表）と標準出力の要約。既存ファイルは読むだけ。

---

## 4. `study.py` の変更（決定）

- `GUIDE_KEYS` に `'play'` を追加。
- `note(tid, path)`: JSON に `play` があれば `playbook.validate(play, t['team'], 本文)` を実行。エラーがあれば各理由を表示し、**何も保存せず** `sys.exit(2)`。JSON に `play` が無く既存 `guide` に `play` があれば既存の `play` を引き継ぐ。`play` を保存したら `guide['play_date']` を付ける。
- 新サブコマンド:
  - `python study.py play <id> <json-file>`: JSON は `{"play": [...]}` または規則リスト。検証して `guide.play` と `play_date` **だけ**を書き換える（他の guide キー・`date` は不変）。エラー時は `note` と同じく保存しない・exit 2。
  - `python study.py pending-play [--n 15]`: `guide` があり `'play' not in guide` で本文がある構築を、レート順（`report()` と同じ並び）に最大 n 件、`id 題名 本文パス` で表示。最後に `残り N 件`。
  - `python study.py check-play`: 全構築の `guide.play` を検証し、不合格の id と理由を表示（exit 1）。
- `report()`: `play` が空でなければ `- 動き方: ` に続けて各規則の `note`（`origin:"user"` は末尾に「（ユーザー実戦）」）を1行ずつ。
- 先頭の docstring に新サブコマンドを追記。

---

## 5. 夜間ルーチンの手順（差し替え用の完成文）

現行ルーチンのプロンプトのうち、guide を書く手順（手順3）を下の「手順3」「手順4」に置き換える（取り込み・コミット等の他の手順は現行のまま。番号は必要に応じて詰める）。

```
手順3（新着構築のガイドと動き方）
cd pokechamp/tool で `python3 study.py pending` を実行し、表示された各構築について本文ファイル（logs/study/text/<id>.txt）を読む。
各構築ごとに次の JSON をファイル（例: /tmp/guide_<id>.json）に書き、`python3 study.py note <id> /tmp/guide_<id>.json` で保存する。
{
 "type": "構築の型（短く）",
 "core": ["軸のポケモン", ...],
 "plan": "運用の要点（記事の要約、1〜2文）",
 "picks": [{"when": "選出の条件（記事の言葉）", "pick": ["ポケモン", ...], "note": "補足"}],
 "heavy": ["重い相手", ...],
 "notes": "注意点",
 "play": [ 動き方の規則 ... ]
}
play（動き方）の書き方:
- 記事に「この局面ではこう動く」と明記された運用だけを規則にする。明記が無い動き・一般論・自分の推測は書かない。明記が無ければ "play": [] とする。
- 規則の形: {"id":"p1","who":"技を使う自分のポケモン（構築の6体の名前）","when":{条件},"do":{行動},"note":"要約","src":"記事の該当文をそのまま短く引用（60字以内、本文の文字列と一致させる）"}
  任意: "until":{解除条件}、"max":発動上限、"phase":"replace"（倒された後・交代技の後に出す先を決める規則。このとき who は "*"、do は switch か preserve）。
- when に使えるキー（これ以外は書かない。dict は全部成立、[{..},{..}] はどれか成立）:
  turn（ターン番号 or [下限,上限]。初手は 1）、lead（初手のポケモンのまま）、foe（相手の場のポケモン名の一覧）、foe_type（相手のタイプ和名の一覧）、
  foe_shown（相手が使った技の和名の一覧）、foe_boosted（相手が積み技でランク上昇済み）、my_hp / foe_hp（HP割合 [下限,上限]、0〜1）、
  my_sub / foe_sub（みがわり中）、trickroom（トリックルーム中）、rocks_on_foe / rocks_on_me（ステロの有無）、mega_used（メガ済み）、
  foe_faster（相手が先に動く）、foe_can_ko（相手の攻撃で倒される）、can_ko（こちらが倒せる）、bad_matchup（不利対面）、
  bench_alive（控えに生きているポケモン名の一覧）、foe_left / my_left（残り数 [下限,上限]）、after（先に発動しているべき規則 id の一覧）
- do に使えるキー（ちょうど1つ。mega は move/best_damage に添えてよい）:
  move（使う技の和名を優先順に並べた一覧。その who の技構成の技だけ）、best_damage（true: 一番削れる攻撃技）、switch（交代先の名前を優先順に）、
  avoid（使わない技の一覧）、preserve（温存して最後まで出さないポケモンの一覧）、mega（true: メガして使う / false: メガせずに使う）
- 例（記事「不利対面ではいのちがけで特攻していく」の場合）:
  {"id":"p2","who":"メガムクホーク","when":{"bad_matchup":true},"do":{"move":["いのちがけ"]},"note":"不利対面はいのちがけ","src":"不利対面ではいのちがけで特攻していく"}
- `study.py note` が語彙外・技構成に無い技・本文に無い引用などを拒否したら、表示された理由に従って JSON を直して再実行する（3回直しても通らなければ play を [] にして保存し、拒否理由を作業報告に書く）。

手順4（既存構築の動き方のバックフィル）
`python3 study.py pending-play --n 15` を実行し、表示された構築（最大15件）について本文ファイルと既存の guide（data/known_teams.json）を読み、手順3と同じ規則で play だけを書く。
JSON は {"play": [...]} とし、`python3 study.py play <id> /tmp/play_<id>.json` で保存する（guide の他のキーは変わらない）。明記が無ければ {"play": []} を保存する。
最後に `python3 study.py check-play` を実行し、不合格が無いことを確認する。作業報告に「play を書いた件数／[] の件数／残り件数（pending-play の表示）」を書く。
```

---

## 6. 既存構築のバックフィル（手順・決定）

- 対象: `guide` があり `play` キーが無い構築（現時点 95 件）。`python3 study.py pending-play --n 15` で 15 件ずつ。
- 実施者: Claude（夜間ルーチンの手順4で毎晩15件、または手動のバッチ）。1回 15 件。読み物は本文ファイルと既存 `guide`（`plan`・`picks`・`notes` は手掛かりだが、**規則の根拠（`src`）は必ず本文**から引用する）。
- 保存は `study.py play` のみ（`guide` の他キーを壊さない）。1件ずつ保存（途中で止まっても保存済みは残る）。
- 乾坤一擲リザホーク（`db0baa2843d2bd4b`）は実装者が §7.1 の内容で先に書く（`origin:"user"` を含むので夜間ルーチンは上書きしない＝`pending-play` に出ない）。
- 完了の目安: `pending-play` が `残り 0 件`、`check-play` が合格。

---

## 7. 検証

### 7.1 乾坤一擲リザホークのプレイブック（手書きの例。実装者がこのまま `study.py play` で保存）

ユーザーの実戦の流れ「ムクホで一番削れる技 → いのちがけで1匹持っていく → ミミッキュでトリル → のろいで退場 → イダイトウで全抜き」を、記事の明記（article）とユーザー明示（user）に分けて書く。

```json
{"play": [
 {"id": "p1", "who": "メガムクホーク", "when": {"bad_matchup": true, "foe_hp": [0.0, 1.0]},
  "do": {"move": ["いのちがけ"]}, "origin": "article",
  "note": "不利対面はいのちがけで1匹持っていく", "src": "不利対面ではいのちがけで特攻していく"},
 {"id": "p2", "who": "メガムクホーク", "when": {"bad_matchup": false},
  "do": {"best_damage": true}, "origin": "user",
  "note": "まず一番削れる技", "src": ""},
 {"id": "p3", "who": "ミミッキュ", "when": [{"trickroom": false, "foe_boosted": true}, {"trickroom": false, "foe_faster": true}],
  "do": {"move": ["トリックルーム"]}, "max": 2, "origin": "article",
  "note": "高速物理・積み技にトリルで切り返す", "src": "高速物理や積み技、イエッサン絡みにトリルで切り返す枠"},
 {"id": "p4", "who": "ミミッキュ", "when": {"trickroom": true, "my_hp": [0.0, 0.5], "bench_alive": ["イダイトウ"], "after": ["p3"]},
  "do": {"move": ["のろい"]}, "max": 1, "origin": "user",
  "note": "トリル後はのろいで退場してイダイトウへ", "src": ""},
 {"id": "r1", "who": "*", "phase": "replace", "when": {"trickroom": true},
  "do": {"switch": ["イダイトウ"]}, "origin": "article",
  "note": "トリル下はイダイトウを出す", "src": "トリル下で高火力を押し付けられるイダイトウ"},
 {"id": "p5", "who": "イダイトウ", "when": {"trickroom": true},
  "do": {"best_damage": true}, "origin": "user",
  "note": "トリル下で全抜きを狙う", "src": ""}
]}
```
- p1 の `src` は本文 22 行「不利対面ではいのちがけで特攻していくだけの鳥と見せかけて」の部分文字列。p3 は 28 行、r1 は 11 行。
- p1 が p2 より前（不利対面ならいのちがけ優先）。`foe_hp` は語彙確認用の冗長条件（常に成立）として残してよい。

### 7.2 単体テスト `python3 roundrobin.py playbook selftest`（数分以内・本番なし）
局面は `rr_apply(リザホーク)` → `B.engine_game([...], [...])` で作り、HP・ランク・`pseudo['trickroom']` 等を直接書き換える。相手は既知構築の上位から適当に固定（例: 相手の場がメタグロス等）。`decide` には必要に応じて**作り物の `ranked_fn`**（値を指定）を渡し、探索なしで規則選択を確かめる。

| # | 局面 | 期待 |
|---|---|---|
| T1 | 初手ムクホーク、相手の打点で倒れない（`bad_matchup` 偽） | p2 発動、行動 = `S.est` 最大の攻撃技（手計算で一致） |
| T2 | ムクホーク HP 20%、相手が先に倒せる | p1 発動、`('m','finalgambit', …)` |
| T3 | ミミッキュ、トリルなし、相手 atk +2 | p3 発動、`trickroom` |
| T4 | ミミッキュ、トリル中、HP 40%、控えイダイトウ生存、p3 発動済み | p4 発動、`curse` |
| T5 | トリル中、交代先 opts にイダイトウとガブリアス | chooser がイダイトウ（r1） |
| T6 | T2 の局面で作り物 ranked: いのちがけ = -100、最善 = +0.5 | 却下 `guard`、`a0` を返す |
| T7 | いのちがけが不合法（`vol['disable']` 等で legal_moves から外す） | 却下 `illegal`、次の規則 or `a0` |
| T8 | `switch` 規則を毎ターン成立させる | 連続発動しない・合計 2 回まで |
| T9 | `until` 成立後 | 以後発動しない |
| T10 | stuck（3ターン同じ局面で同じ規則） | 以後無効 |
| T11 | `playbook.ranked(bst, i, d)[0][1] == S.lookahead_action(bst, i, d)`（i=0,1、深さ2、3局面） | 一致 |
| T12 | validate: 未知キー、技構成に無い技（ムクホークに「のろい」）、6体に無い名前、タイプ誤記、`src` が本文に無い、`do` 2種 | それぞれ理由付きで拒否。§7.1 は合格 |
| T13 | `study.py play` を一時コピーの known_teams で実行（`prep.KNOWN_P` を一時パスに差し替え） | 他の guide キー・`date` 不変、語彙外は exit 2 で無変更 |

### 7.3 A/B `python3 roundrobin.py playbook ab --team db0baa2843d2bd4b [--opps top5] [--games 4] [--procs 4] [--out-dir D]`
- 相手: 既定は `rating.rank` 上位 5 構築（リザホーク自身を除く、`--opps id,id,...` で指定可）。
- 各相手と `--games` 局（側の入れ替えあり、`game_sides`）× {プレイブックあり（`pb_only=リザホーク`）, なし}。両条件で**同じ seed・同じ選出**（選出は従来の roundrobin の選出関数で1回決めて共有）。deny は `(True, True)`（adapt/counter と同じ）。
- 出力 `<out-dir>/pb_ab_games.json`（`plan_sig` 相当に `team, opps, games, playbook sig` を持ち、違えば再開拒否）と `pb_ab_report.md`: 相手別・全体の勝率（あり／なし）、差、規則ごとの発動回数・発動試合の勝率、rejected 理由別件数。
- 既定の出力先は `logs/refine/pb_ab/`（既存ファイルと別）。**実装者は `--opps 1件 --games 1 --procs 1` の動作確認だけ**（全量は Opus/ユーザーが実行）。

---

## 8. 実装メモ（決定）

- `playbook.py` は `battle`・`engine`・`search` を import するだけで、それらを変更しない。和名→技 id は `E.MOVES` の `ja` から逆引き（重複和名があれば `B.MOVE` 側の id を優先）。
- `aname` は policy.aname と同じ形式（側 i 版を playbook.py に持つ）。
- `PB` の内部状態はその試合限り（blind_play ごとに新規作成）。
- 数値定数: `PB_LOSS = -50.0`、`PB_GAP = 1.5`、`PB_MAX_SWITCH = 2`、`PB_MAX_DEFAULT = 6`、`PB_STUCK = 3`、`PB_MAX_RULES = 10`。
- `playbook.PLAYBOOK_VERSION = 1` を `pb` 統計と結果ファイルに記録。

---

## 9. 受け入れ条件（Opus が確認）

1. `python3 -m py_compile playbook.py study.py refine.py roundrobin.py` が通る。
2. **従来結果の再現**:
   a. `blind_play` を args 12 個（従来）と、args[12] = `(None, None)` で、seed 2 種・深さ (2,2) で実行し、戻り値の dict が完全一致。
   b. `logs/refine/rr_deny_games.json` の既存記録 2 件（例 `full:49174cf5df35f7da|adb3c969ff4e76ee|0` ともう1件）を、記録の `side0/side1/sel0/sel1/seed/deny` で `_job_deny` 相当（`--no-playbook` 相当＝`_PB={}`）に再実行し、`res, turns, left, faints` が記録と一致（1件 約15秒）。
   c. 各サブコマンドの `--no-playbook` 時、ジョブが blind_play に渡す args が従来と同じ長さ・同じ内容（selftest で job 生成関数の出力を比較）。
3. `roundrobin.py playbook selftest` の T1–T13 が全て合格（実行時間を表示）。
4. 語彙外の拒否: `study.py note` / `study.py play` に T12 の不正 JSON を与えると、理由を表示し exit 2、`known_teams.json` の sha256 が不変。
5. `known_teams.json` の差分は `db0baa2843d2bd4b` の `guide.play`・`guide.play_date` の追加だけ（`json` で読み比べて他は完全一致）。
6. 既存結果ファイル不変: 作業前後で `sha256sum logs/refine/*.json logs/refine/*.jsonl logs/refine/*.md logs/refine/*.csv` が一致（selftest・A/B 動作確認は一時フォルダか `logs/refine/pb_ab/` に出す）。また既定フォルダに対し playbook オンで `run` を始めると、記録の無い `playbook` キーとの不一致で止まる（データを書かずに SystemExit）ことを、一時コピーで確認。
7. `playbook ab --opps <1件> --games 1 --procs 1 --out-dir <一時>` が完走し、`pb_ab_report.md` に あり/なし の勝率と規則別の発動回数が出る。
8. `battle.py`・`game_watch.py`・`search.py`・`policy.py`・`engine.py`・Star Crusade に差分が無い（`git diff --stat`）。
