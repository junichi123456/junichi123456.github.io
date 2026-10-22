# 相手の勝ち筋を潰す読み（deny モード）とブラインド A/B 仕様書

作成: Opus 5.5 ／ 実装: Sonnet 5.5（`model: sonnet`）／ 受け入れ確認: Opus 5.5
作業フォルダ: `pokechamp/tool/`（Linux は `python3`、Windows は `python`）
変更するファイル: `tool/search.py`（追加のみ）、`tool/refine.py`（`blind_play` に後方互換の引数1つ）、`tool/roundrobin.py`（サブコマンド `deny` 追加）。

「事実」はコードとデータで確かめた内容。「決定」はこの仕様で決めた内容。

対象外: Star Crusade（ルートの `index.html`・`starcrusade/`）、`game_watch.py`、実戦用 `battle.py` の判断、`search.decide`／`Searcher`（実戦の読み）、`policy.py`、`data/*.json`・`data/party/*.json`（読むだけ）、既存の結果ファイル（`logs/refine/rr_*` を含む既存の全ファイル）。

**実装者は本番（`roundrobin.py deny run`）を実行しない。** §8 の受け入れ条件の確認だけを行う。

---

## 0. 目的（ユーザー依頼）

「今後の対戦シミュレーションにおいては、相手の勝ち筋を潰すように動くブラインドテストを行ってください。」

シミュレーション用の読み `search.lookahead_action` に、**相手が勝つ見込みの最も高い展開（勝ち筋）を先に見つけ、それが成立しない手を選ぶ** `deny` モードを加える。既定は従来のまま。ブラインド条件（相手の型は推測＝`refine.belief` のみ）は維持する。

---

## 1. 現状（事実）

### 1.1 `search.lookahead_action(st, i=0, depth=3, k_self=3, k_opp=2)`（search.py 637–668）
- 根: 自分の全合法手 `E.actions(st, i)` × 相手の `prune(st, j, k_opp + 1)`（=3手）。
- 内部 `val(s, d)`: 自分 `prune(s, i, k_self)`（3手）× 相手 `prune(s, j, k_opp)`（2手）。`E.step` は既定 `rng=EXPECTED`（乱数なし、最も起こりやすい結果）。
- 相手応手の混合: `PESS * min(vs) + (1 - PESS) * mean(vs)`、`PESS = 0.6`（search.py 24、658、665）。＝「最善応手60%＋平均40%」。
- 葉: `sign * evaluate(s)`、決着時は `+ 0.3 * sign * winner * d`（早い勝ち優先）。
- 根の値に `front_bias(st, a)` を足すのは **i == 0 のときだけ**（665行）。→ 側0と側1で読みが完全対称ではない（事実）。
- `prune(st, i, k)` は `action_scores` の上位 k。積み技は `0.45`（条件: 上昇あり・HP>0.6・現積み<4・`foe_threat < 0.6`）、それ以外 `0.05`（173行）。攻撃は `est` 割合（確1なら 1.5〜1.9）。**相手の積み技・先制技は上位2手から漏れやすい** → 現行の読みは相手の勝ち筋を「見ない」ことがある。これが deny で直す点。

### 1.2 `search.evaluate(st)`（278–293）
- 決着: `100 * winner + side_value(0) - side_value(1)`（winner: 1 側0勝ち／-1 側1勝ち／0 引分け、engine.py 601–605）。
- 未決着: `side_value` 差 ＋ `0.3 * tanh(1.5 * edge)`、`edge = give - take`（`best_damage` を 1.2 で頭打ち、先に確1を取れる側に ±0.6）。
- `_mon_value`: 生存 1.0 ＋ 1.2×HP割合、場の攻撃ランク +0.09/段、素早さ +0.05/段 ほか。ステロ −0.1×控え数 など（`side_value`）。

### 1.3 `refine.blind_play(args)`（refine.py 541–621）
- `args = (party, kid, my_order, opp_order, seed, my_depth, opp_depth, know, rules, trace, excl)`。
- 側0: `a0 = S.lookahead_action(st if know else belief(st, 1, t_opp, seen[1]), 0, my_depth)`（580）。`rules` があれば `policy.choose`（583、今回は触らない）。
- 側1: `a1 = S.lookahead_action(belief(st, 0, t_me, seen[0]), 1, opp_depth)`（584）。
- 両者とも `belief`（推測の型＋見えた技）で読む＝ブラインド。勝敗は `st.winner`、30ターンで未決着なら `S.evaluate(st) > 0` で判定（`judged=True`）。

### 1.4 `roundrobin.py`
- `DEPTH = (4, 4)`、`_job_game((key, X, Y, selX, selY, seed))` → `R.blind_play((None, Y, selX, selY, seed, 4, 4, False, None, False, (X,)))`。X が側0。
- `game_seed(a, b, k) = crc32(f'rr{a}{b}{k}')`、`game_sides(a, b, k)` は k 偶数で (a, b)、奇数で (b, a)＝**鏡合わせで側を入れ替えて対称性を取る**。
- 選出は `rr_plan.json` の `plan['sel'][f'{X}|{Y}']['order']`。
- 既存結果（事実、`logs/refine/rr_games.json`）: 全640戦、平均 29.4 秒/戦（最大 113 秒）。R11 が絡む第1段階48戦（相手24構築×k=0,1）: R11 21勝、判定決着2、平均12.4ターン、平均 27.5 秒/戦。上位2構築 `bab22dcc629688e8` 対 `096193444e19a2f0` は k=0..5 の6戦（bab22dcc 5勝）。

---

## 2. モードと切り替え（決定）

| 場所 | 追加する引数 | 既定 |
|---|---|---|
| `search.lookahead_action(st, i=0, depth=3, k_self=3, k_opp=2, mode=None, info=None)` | `mode`: `None`（従来）または `'deny'`。`info`: dict を渡すと deny の内訳を書き込む（§3.5） | `None` |
| `refine.blind_play(args)` | `args[11]` = `deny`: 長さ2のタプル `(側0がdenyか, 側1がdenyか)`。無い／`None` は `(False, False)` | 従来 |
| `roundrobin.py` | 新サブコマンド `deny`（§5）。既存の `plan/run/report/selftest/show` と `DEPTH` は変更しない | — |

- `mode=None` の経路は**1文字も変えない**（既存の関数本体はそのまま、deny は別関数 `_lookahead_deny` に分けて `mode == 'deny'` のときだけ呼ぶ）。
- 片側だけ deny: `blind_play` 内で `S.lookahead_action(..., 0, my_depth, mode='deny' if deny[0] else None)`、側1も同様。`rules` 経路（policy）は deny を無視する（`deny[0]` かつ `rules` は `ValueError`）。
- deny でも相手の型は `belief` の推測のみ（`know=True` との併用は可能だが A/B では使わない）。

---

## 3. deny のアルゴリズム（決定）

方針: ①相手応手を最悪ケース寄りに評価（maximin 寄りの混合）、②相手の「勝ち筋になる手」を応手候補に必ず入れる（見落としを減らす）、③葉で相手の勝ち筋が残っている局面を減点する。①②③の併用。計算量は現行の 1.33 倍程度（§3.6）。

記号: i＝読む側、j＝1−i、`sign = 1 if i == 0 else -1`、`me = 場の i`、`foe = 場の j`。

### 3.1 定数（search.py の先頭付近に追加）
```
DENY_PESS = 0.85      # 相手応手の混合: 0.85*最悪 + 0.15*平均（従来 0.6）
DENY_ROOT_THREATS = 2 # 根で追加する「勝ち筋の手」の最大数
DENY_W_SWEEP = 0.12   # 積み全抜きの減点 / 実効ランク1段
DENY_W_PRIO = 0.25    # 先制技圏内の減点
DENY_SWEEP_CAP = 4    # 実効ランクの上限
```
根拠: 純粋 maximin（1.0）は「最悪の1手」に過剰反応して交代・守り連打で受け身になる（evaluate の 0.3·tanh 項が小さいため差が付かず、交代のテンポ損だけが残る）。0.85 は最悪ケースを主にしつつ、同点に近い手を平均で仕分ける。減点の大きさは `_mon_value` の目安（1体 ≒ 1.0＋1.2×HP、攻撃ランク 0.09/段）に合わせ、「+2 積んだ相手を止められない」＝0.24〜0.48（ほぼ1体の半分〜HP満タン分の差）とした。

### 3.2 勝ち筋の手 `threat_replies(s, j, n)`（相手 j の手から、勝ち筋になるものを選ぶ）
`E.actions(s, j)` のうち次に当たる手に「脅威点」を付け、点の高い順（同点は `action_scores` 順）に最大 n 手:

| 種類 | 条件 | 点 |
|---|---|---|
| 先制技で倒す（先制技圏内） | 技 `md.pri > 0`、`md.cat != 'status'`、`est(s, j, mid) >= 1`（me を倒す） | 3 |
| 積み技（積み→全抜き） | `md.boosts and md.target == 'self' or md.self_boost` で攻撃・特攻・素早さのいずれかが正、`not boosts_ignored(foe, me)`、foe の該当ランク < 6 | 2 |
| 交代読み | j の交代のうち `switch_score(s, j, k)` 最大のもの（me の最大打点を半減以下にする受けがいれば） ※`_swap_view` で `best_damage(s, i, target=受け) < 0.5` | 1.5 |
| 設置技（ステロ＋特性潰し） | `md.side in _HAZ and md.target == 'foeSide'` で i 側にまだ無い（まきびし・どくびしは2未満） | 1 |

- `est` は既存のキャッシュ付き関数を使う（計算量を増やさない）。`switch_score` も既存。
- foe が倒れている（交代の選択だけの局面）では空リスト。

### 3.3 相手の応手集合（勝ち筋を必ず入れる）
- 根: `theirs = dedupe(prune(st, j, k_opp) + threat_replies(st, j, DENY_ROOT_THREATS))`（最大 4 手、従来は `prune(st, j, k_opp+1)` = 3手）。
- 内部ノード: `h = prune(s, j, k_opp)`、`t = threat_replies(s, j, 1)`。`t` があり `t[0] not in h` なら `theirs = [h[0], t[0]]`、無ければ `theirs = h`（**幅は2のまま**、2番目の手を勝ち筋の手に置き換える）。
- 自分の手の幅は従来どおり（根は全合法手、内部は `prune(s, i, k_self)`）。

### 3.4 値の計算
```
def leaf(s, d):                       # 従来の葉 + 勝ち筋の減点
    v = sign*evaluate(s) (+ 0.3*sign*winner*d  決着時)
    if s.winner is None: v -= deny_threat(s, i)
    return v

def deny_threat(s, i):                # 葉の局面に残る相手の勝ち筋
    me, foe = 場の i, 場の j；どちらか倒れていれば 0
    T = 0
    # 積み→全抜き
    if not boosts_ignored(foe, me):
        off = foe の攻撃ランク（foe.stat('atk') >= foe.stat('spa') なら atk、違えば spa）
        eff = min(max(off, 0) + 0.5 * max(foe.boosts['spe'], 0), DENY_SWEEP_CAP)
        if eff >= 1:
            stop = best_damage(s, i) >= 1 and faster(s, i) >= 1      # 自分が先に倒せる＝止まる
            T += DENY_W_SWEEP * eff * (0.3 if stop else 1.0)
    # 先制技圏内（自分が上を取っていても先制技で落ちる）
    if faster(s, i) >= 1 and any(md.pri > 0 and md.cat != 'status' and est(s, j, x) >= 1 for x in foe.moves):
        T += DENY_W_PRIO
    return T

val(s, d): 従来と同じ形。ただし
  葉は leaf(s, d)、相手応手は §3.3、混合は DENY_PESS * min(vs) + (1 - DENY_PESS) * mean(vs)
根: v(a) = DENY_PESS*min(vs) + (1-DENY_PESS)*mean(vs) + (front_bias(st, a) if i == 0 else 0)
   最大の a を返す（同点は E.actions の順で先のもの＝従来と同じ規則）
```
- 「勝ち筋の特定」: 根の各手 a について、最小値を与えた相手応手 `b*(a)`（＝その手に対する相手の勝ち筋）を求める。選ぶ手は `min` 側の値が高い手＝相手の勝ち筋の成立を最も遅らせ／崩す手。
- 閾値: 「負け筋」と見なすのは `vs` の最小値 < −1.0（ほぼ1体分の損）の応手。`info` に記録するだけで選択には使わない（選択は上式のみ。閾値で分岐させると不連続になり A/B の解釈が難しくなるため）。
- ステロ・特性潰し（襷・マルスケ）は `side_value` のステロ減点と `_mon_value` の襷 +0.05 で既に評価に入っている。§3.2 で設置技を応手に入れることで「読む対象」に加える。詰ませ（交代しても全員抜かれる）は積み減点と応手集合の組み合わせで近似する（控え全員への打点は計算量のため見ない）。

### 3.5 `info`（任意、テストと記録用。選択に影響しない）
`info` に dict が渡されたら次を書く: `{'mode': 'deny', 'values': [(a, v)...], 'worst': {a: b*(a)}, 'threats_root': [(kind, b)...], 'lose_lines': [(a, b, vmin) ... vmin < -1.0]}`。`blind_play` は deny の側について、根で `threats_root` が空でなかったターン数と種類の Counter を結果 `'deny_stats': {0: {...}, 1: {...}}` に入れる（勝敗に影響しない）。

### 3.6 計算量（決定と見積り）
- 1根手あたりの葉数（depth=4）: 従来 3（根応手）×(3×2)^3 = 648。deny: 最大 4 ×(3×2)^3 = 864 → **1.33 倍**＋`threat_replies`／`deny_threat` の評価（`est` はキャッシュ、`action_scores` 1回分程度）。
- 上限: deny 側の1手の時間は従来の **2.0 倍以内**（§8-5 で測る）。超えたら `DENY_ROOT_THREATS` を 1 に下げる（それ以外の調整はしない）。

---

## 4. `refine.blind_play` の変更（決定）
- `deny = args[11] if len(args) > 11 and args[11] else (False, False)`。
- 580行: `S.lookahead_action(..., 0, my_depth, mode='deny' if deny[0] else None, info=...)`、584行: 側1も `deny[1]` で同様。`info` は deny の側だけ dict を渡し、`deny_stats` を集計。
- deny が両方 False のとき、戻り値は従来と**完全一致**（`deny_stats` キーも付けない）。

---

## 5. `roundrobin.py deny`（A/B の実行、決定）

```
python3 roundrobin.py deny run    [--part r11|top2|all] [--procs 4] [--retry-errors] [--max-games N] [--out-dir D]
python3 roundrobin.py deny selftest [--out-dir 一時フォルダ]   # §7・§8 の確認用
python3 roundrobin.py deny report [--out-dir D]
```
- 入力は既存の `rr_plan.json`（読むだけ）。`rr_games.json` も読むだけ（基準値の再利用）。
- 出力（新規のみ）: `logs/refine/rr_deny_games.json`、`rr_deny_logs.jsonl`、`rr_deny_report.md`。既存の `rr_*` は書かない。保存は1戦ごとに `safeio.write_json`（中断・再開可。済みの鍵は飛ばす）。
- ジョブ: `_job_game` を拡張せず新関数 `_job_deny((key, X, Y, selX, selY, seed, deny))` → `R.blind_play((None, Y, selX, selY, seed, DEPTH[0], DEPTH[1], False, None, False, (X,), deny))`。`deny = (X == D, Y == D)`、D は deny を使う構築 id。

### 5.1 パート r11（R11 が deny、48戦）
- 対象: `tier_ids(plan, 1)` の R11 以外24構築 × k=0,1。鍵・種・側・選出は本戦と同一: `a, b = pair_ab('R11', o)`、`X, Y = game_sides(a, b, k)`、`seed = game_seed(a, b, k)`、`sel = plan['sel'][f'{X}|{Y}']['order']`。
- 条件: deny = R11 の側のみ True。鍵 `deny:R11|{a}|{b}|{k}`。
- 基準（通常モード）: `rr_games.json` の同じ鍵 `f'{a}|{b}|{k}'` を再利用（新たに回さない）。

### 5.2 パート top2（上位2構築の片側 deny、20戦＋基準4戦）
- A = `bab22dcc629688e8`、B = `096193444e19a2f0`、`a, b = pair_ab(A, B)`、k = 0..9、側・種は `game_sides`・`game_seed`（k が偶奇で側が入れ替わる＝鏡合わせ、front_bias の非対称を打ち消す）。
- 条件 DA（A のみ deny）10戦、DB（B のみ deny）10戦＝**20戦**。鍵 `deny:{A}|{a}|{b}|{k}` 等。
- 基準 N（両者通常）: k=0..5 は `rr_games.json` を再利用、k=6..9 の4戦だけ新たに回す（鍵 `base:{a}|{b}|{k}`）。

### 5.3 report（`rr_deny_report.md`）
- r11: 通常 vs deny の勝ち数（/48、Wilson 95%区間＝既存 `wilson`）、判定決着数、平均ターン数、平均秒、勝敗が入れ替わった対戦の一覧（相手名・k・通常/deny の結果）、相手構築ごとの 0/1/2 勝の変化、`deny_stats` の種類別件数。
- top2: N／DA／DB の A 側勝ち数（各/10）、判定決着数、平均ターン。DA−N が「A が deny を使った効果」、N−DB が「B が deny を使った効果」。
- 符号検定（McNemar、入れ替わった対戦の向きの数）を併記。48戦での有意差は期待しにくいことを明記（判断材料は勝ち数と入れ替わりの中身）。

### 5.4 所要時間の見積り（4並列）
- r11: 48戦 × 27.5秒 × 1.33 ≒ 37秒/戦 → 約 **7.5 分**（上限 2倍で 11 分）。
- top2: 24戦 × 約 20秒 × 1.33（基準4戦は 1.0）≒ 25秒/戦 → 約 **2.5 分**。
- 合計 約 10 分（上限 15 分）。1戦は 20〜50 秒、最長 2〜3 分程度を見込む。

---

## 6. 変更しないもの（決定）
`search.decide`・`Searcher`・`PESS`・`prune`・`action_scores`・`evaluate`・`front_bias` の本体、`lookahead_action` の従来経路、`roundrobin.DEPTH`・既存サブコマンド、`refine.blind_play` の従来の戻り値、`battle.py`、`policy.py`。

---

## 7. テスト用の局面（実装者が用意、`roundrobin.py deny selftest` に入れる）
既存の構築（`ADOPTED.json`／`rr_plan.json` の構築）から `B.engine_game` で局面を作り、必要ならランク・HP を直接書き換える。各テストで `lookahead_action(..., mode=None)` と `mode='deny'` の手と `info` を表示する。
1. **積み技持ちが場に出た直後**: 相手場に積み技（りゅうのまい・つるぎのまい・わるだくみ・からをやぶる・ちょうのまい 等）を持つポケモン、自分は確1を取れず `foe_threat < 0.6`（相手の積み技が従来 `prune` 上位2に入らない局面）。期待: deny の `threats_root` に積み技が入り、選ぶ手が従来と違う（攻撃・挑発・吹き飛ばし・てんねん交代等）。
2. **相手が既に +2**（boosts を書き換え）: 従来は自分の積み・設置を選ぶが、deny は最大打点か止められる交代を選ぶ局面。
3. **先制技圏内**: 自分が上を取るが相手の先制技（でんこうせっか・しんそく・アクアジェット・かげうち 等）で落ちる HP に書き換え。期待: `deny_threat` の先制項が効き、手が変わるか、少なくとも値の差が `DENY_W_PRIO` 分出る。
4. **対照（脅威なし）**: 相手に積み技・先制技が無い局面で、deny と従来の手が同じ。
- 1〜3 のうち**2つ以上で手が異なる**こと。見つからない場合は R11 対 積み技持ち構築の基準戦ログを走査し、各ターンで両モードの手を比べて「相手場に積み技持ち／ランク上昇あり、かつ手が異なる」局面を2つ以上報告してもよい（局面の再構成手順も残す）。

---

## 8. 受け入れ条件
1. `python3 -m py_compile search.py refine.py roundrobin.py` が通る。
2. **従来モードの完全一致**: 変更前の `rr_games.json` から R11 戦2つ、top2 戦1つ（計3戦）を `_job_game` で再実行し、`res`・`turns`・`judged`・`left`・`faints` と `rr_logs.jsonl` の `log` が完全一致。さらに `blind_play` に `args[11] = None` と `(False, False)` を渡した場合も同一。
3. **deny の動作**: §7 のテストで 2つ以上手が異なり、対照（テスト4）は一致。`info['threats_root']` に該当する種類が出ている。
4. **片側 deny**: `(True, False)` と `(False, True)` がそれぞれ片側だけに効く（もう片側の `lookahead_action` が mode=None で呼ばれることを、呼び出し記録か `deny_stats` で確認）。
5. **時間**: §7 の局面＋基準戦ログから取った 30 局面以上で、`lookahead_action(depth=4)` の deny/従来の時間比の中央値 ≤ 1.5、最大 ≤ 2.0（i=0、i=1 の両方）。加えて r11 から1戦だけ deny で実行し、同じ鍵の従来 `sec` の 2 倍以内（この1戦の結果は `--out-dir` の一時フォルダに置き、本番ファイルに書かない）。
6. **既存結果の sha256 不変**: 作業の前後で `logs/refine/` の全既存ファイル（`rr_plan.json`・`rr_games.json`・`rr_logs.jsonl`・`rr_matrix.csv` を含む）、`logs/*.md`、`data/*.json`、`data/party/*.json` の sha256 が一致（`roundrobin.sha_files` の対象＋ `rr_*`）。
7. `deny run` の再開: 一時フォルダで `--part top2` を2戦で止め（テスト用 `--max-games`）、再実行で残りから始まる。※本番の全件実行はしない。
8. 報告: 変更点の差分要約、上記1〜7の結果（テスト局面ごとの従来手／deny手／threats_root、時間比）。

## 9. 本番の実行（Opus／ユーザーが行う）
```
cd pokechamp/tool
python3 roundrobin.py deny run --part all --procs 4
python3 roundrobin.py deny report
```

---

## 10. 追補: 両側 deny の第1段階総当たり（本番の第一優先）

ユーザーの最終依頼: 「第1段階の25構築を同じ条件（4手読み・rr_plan.json の選出・種規則）で、**両側とも deny モード**、**左右それぞれ3戦（1ペア6戦、計300ペア×6＝1,800戦）**回す。変える点は相手の勝ち筋のケアだけ」。§5 の A/B（r11・top2）は第2優先として残す。

### 10.1 事実
- `tier_ids(plan, 1)` は R11 を含む25構築で、ペアは C(25,2)＝300。
- `rr_games.json` の本戦（`rematch=False`）は600戦（300ペア×k=0,1）。平均 29.7 秒/戦、判定決着は27戦、平均12.8ターン。

### 10.2 `roundrobin.py deny full [--max-games N] [--procs 4] [--retry-errors] [--out-dir D]`
- ペアは `circle_pairs(tier_ids(plan, 1))` の順で、k＝0..5 を回す。順序は k=0 を全ペア → k=1 を全ペア → … とし、途中で止めても全ペアが均等に進むようにする。
- `a, b = pair_ab(x, y)`、`X, Y = game_sides(a, b, k)`（k が偶数なら a が側0、奇数なら b が側0 → 左右それぞれ3戦）。`seed = game_seed(a, b, k) = crc32(f'rr{a}{b}{k}')` で、既存の規則を k=0..5 に広げる。
- 選出は `plan['sel'][f'{X}|{Y}']['order']` を使う（読むだけ。足りなければ止める。`cmd_select` は呼ばない＝rr_plan.json を書かない）。
- deny は `(True, True)` で、`_job_deny` を使う（§5）。深さは `DEPTH=(4,4)` のまま。
- 鍵は `full:{a}|{b}|{k}` とする。保存先は `rr_deny_games.json`（`{'version', 'plan_sig', 'depth', 'mode': 'deny', 'games': {...}}`、1戦ごとに `safeio.write_json`）と `rr_deny_logs.jsonl`。レコードの形は `game_record` と同じ。
- **既存との関係**: k=0,1 の種は `rr_games.json` の同じ鍵と同じ値になるが、それで正しい（同じ乱数で通常と deny を比べられる）。鍵の接頭辞 `full:` と別ファイルによって、既存の結果とは衝突しない。`rr_games.json` は読むだけ。
- 再開: 済みの鍵は飛ばす。`--retry-errors` を付けると `res is None` の戦だけやり直す。`--max-games` は今回の実行で回す上限。
- 進み具合は `run` と同じ形式で表示する（済み/全体、経過、残りの見込み）。

### 10.3 `deny report` に足す「通常 対 deny」順位比較表
- 通常側は `rr_games.json` の `rematch=False` の600戦、deny 側は `full:` の1,800戦。どちらも既存の `ranking(plan, games, ids)` と `team_stats` で集計する（deny 側は `{'games': full のレコード}` を渡す）。
- 表の列: 構築（タイトル16字＋id6桁）、通常の勝率（勝/戦）と順位、deny の勝率と順位、順位差（＋が上昇）、deny の Wilson 95%、判定決着数（通常/deny）、平均ターン（通常/deny）。並びは deny の順位順。
- 本文には次を書く: R11 の順位（通常→deny）、全体の判定決着数と平均ターン（通常 vs deny）、順位が5以上動いた構築の一覧、k=0,1 だけで比べた勝率（同じ種どうしの比較）、`deny_stats` の種類別件数の合計。
- 注記: 通常は1ペア2戦、deny は6戦で、戦数が違う。順位差は区間の幅を見て読むこと。

### 10.4 所要時間の見積り（4並列）
- 1戦は 29.7 秒 × 1.33 ≒ 40 秒。1,800戦 × 40 秒 ÷ 4 ≒ **5.0 時間**。上限の2倍（59 秒/戦）なら約 **7.4 時間**。
- 中断・再開を前提とする。`--max-games 600` ずつ3回に分けて回せる（1回 約1.7時間）。

### 10.5 受け入れ条件（§8 に追加）
9. 一時フォルダで `deny full --max-games 3` を実行し、鍵が `full:` で k=0 から始まること、`(True, True)` で呼ばれること（`deny_stats` に 0 と 1 の両方があること）、再実行で続きから始まることを確かめる。本番ファイルには書かない。
10. `deny report` が、一時フォルダのテスト用 deny 結果と既存の `rr_games.json` から比較表を出せる（表の列と R11 の順位行がある）。`rr_games.json` と `rr_plan.json` の sha256 は変わらない。

### 10.6 本番の実行（Opus／ユーザー）
```
python3 roundrobin.py deny full --procs 4      # 第一優先（約5時間、再開可）
python3 roundrobin.py deny report
python3 roundrobin.py deny run --part all      # 第二優先（§5 の A/B）
```
