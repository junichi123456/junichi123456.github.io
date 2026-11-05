# SPEC_RESOURCE: 取り巻きを「切れるリソース」として扱う読み（resource モード）

作成: Opus 5.5 / 実装: Sonnet 5.5 / 受け入れ確認: Opus 5.5
根拠: SKILL.md「リソース管理の原則」。軸で相手の残り全員に勝てるなら、取り巻きの瀕死は切ってよい。
対象: tool/search.py・tool/refine.py・tool/roundrobin.py と新規 tool/test_resource.py。
対象外: Star Crusade、game_watch.py、battle.py の実戦判断。**実装者は本番500戦を実行しない。**

## 1. 「軸が全相手を倒せる」条件 `axis_cover(st, i, axis)`（search.py に新規）
- **軸**: `RES_AXIS = {'M8_6': ('リザードン', 'ガブリアス')}`（roundrobin.py に置く。照合は `Mon.name`＝元種族名）。M8_6 では軸以外の自分の手持ち（ミミッキュ・イダイトウ・ドドゲザン・シャワーズのうち選出された者）が**取り巻き**。
- **入力の局面**: その側が読みに使う belief 局面（相手の型は `refine.belief` の推測。真の型は見ない＝ブラインド条件を守る）。
- **相手の候補 C**: belief 局面の相手側で、まだ倒れていない全員（見えていない選出も含む。従来の探索と同じ情報量）。
- **1対1判定 `beats(A, c)`**（ロールアウトはしない。damage 推定だけ）:
  - `_swap_view` で A と c を場に出した複製を作り、`est` で各自の最善技の1発の割合（最も出やすい乱数）を出す。安全側に A の与ダメ×0.9、c の与ダメ×1.1。
  - `nA = ceil(c の残りHP割合 / dA)`、`nC = ceil(A の残りHP割合 / dC)`（ダメージ0なら∞）。きあいのタスキ（満タン）・ばけのかわ（未発動）なら `nA += 1`。
  - 勝ち = `nA <= 3` かつ（`nA < nC`、または `nA == nC` で A が素早さで真に先手）。ランクは場に出ている者の現在値のみ、控えは0。積み技・先制技は考えない（保守側）。
  - **メガ**: 軸は2体ともメガ枠でメガは1回だけ。メガ未使用なら「A をメガ・B を通常」と「A を通常・B をメガ」の2通りを評価し、**どちらか一方の割り当てで全候補が覆えれば成立**。メガ済みなら現在の姿で評価。メガ姿は belief と同じ方法（form=mega_form、stats=None、ability=form.ability）で複製に作る。
- **成立条件**: 生きている軸が1体以上 ∧ 生きている取り巻きが1体以上 ∧ 全ての c ∈ C が、生きている軸の**少なくとも1体**に `beats` される。軸が1体だけでも、その1体で全員に勝てれば成立。**一部にしか勝てない場合は不成立**（取り巻きを温存＝従来どおり）。C が空なら不成立（勝負は付いている）。
- **コスト**: 判定は**根（1手の決定）で1回だけ**。結果は `(軸/候補の id, 姿, HP を1/16に丸めた値, 持ち物, busted, mega_used)` をキーにした プロセス内 dict にキャッシュ（上限 20000 件、超えたら clear）。

## 2. 行動への反映（評価の割引＋根の交代ペナルティ）
- `evaluate_resource(st, r, sats, w)`: `evaluate(st)` を呼び、resource 側 r の取り巻き（`sats`=索引の集合）について `adj = (1 - w) * Σ _mon_value(st, r, m, active)` を r の価値から引く（r=0 なら `v - adj`、r=1 なら `v + adj`）。勝敗の ±100 はそのまま。
- **葉での適用条件**: 根で成立 ∧ 葉の局面で「根で生きていた軸が全員まだ生きている」とき（軸が落ちた葉では割り引かない）。葉で axis_cover を再計算しない（コスト対策）。
- **重み `RES_W = 0.4`**（根拠: 満タンの取り巻きの `_mon_value` ≈2.2。0.4 倍で瀕死の損が ≈0.9 となり、相手1体の HP 6〜7割を削る価値（1.2×0.65≈0.8＋対面差）と釣り合う。0 にしないのは、推測型で条件が外れる場合と、取り巻きが死に出し・クッションとして持つ価値を残すため）。
- **根の交代ペナルティ `RES_SW_PEN = 0.10`**: 成立時、場の自分が取り巻きのとき、交代行動の根の値から 0.10 を引く（取り巻きを守るための引きを減らす。居座り・設置・のろい・みがわり・いのちがけ・自爆系は割引により自然に上がる）。
- **不成立時**: `lookahead_action` の従来経路（mode=None または 'deny'）をそのまま呼ぶ＝**従来の読みと完全一致**。
- **deny・プレイブックとの順序**: ① 根で axis_cover を判定 → ② 成立なら deny の有無に応じて「通常／deny の木」を**葉の評価だけ `evaluate_resource` に替えた複製関数**で読む（prune・相手の応手選び・DENY_PESS/PESS・deny_threat は従来と同じ）→ ③ 根に交代ペナルティ → ④ プレイブックはその後（`_rk` が deny の values を使う場合は resource 補正後の values）。M8_6 側はプレイブック対象外なので本番では④は起きない。

## 3. 実装箇所
- **search.py**: `RES_W`, `RES_SW_PEN`, `axis_cover`, `evaluate_resource`, `_lookahead_res(st, i, depth, k_self, k_opp, info, deny, axis)` を追加。入口は `lookahead_action(..., mode=None, info=None, res=None)`。`res` が None なら従来と1文字も同じ経路。`res` が軸名タプルなら `_lookahead_res` へ（不成立なら中で従来関数に委譲）。info に `{'res_on': bool, 'res_sats': [...]}` を入れる。既存関数（evaluate, _lookahead_deny, lookahead_action の従来部分, prune, action_scores）は**変更しない**。
- **refine.blind_play**: `args[13] = (res0, res1)`（各 None か軸名タプル。省略・偽なら従来）。`args[12]` が無いときは呼び出し側が None で埋める。`deny[i]` と併用可（`mode='deny'` と `res=...` を同時に渡す）。rules（args[8]）・ctx 経路との併用は ValueError。戻り値に、resource を使った側だけ `res_stats: {side: {'turns': 決定数, 'on': 成立した決定数, 'first': 最初に成立したターン, 'sw_sat_on': 成立時に取り巻きから交代した回数, 'sat_faint_on': 成立時の決定の直後のターンに倒れた取り巻き数}}` を足す（resource 無しの戻り値は従来と同一キー）。
- **roundrobin.py m7**: `--resource` フラグ（`--party` が RES_AXIS に無ければ SystemExit）。
  - 接頭辞: `--resource` 時の既定 prefix は `{party.lower()}r` → `m8_6r_plan.json`, `m8_6r_games.json`, `m8_6r_logs.jsonl`（logs/refine/）、md は **`logs/M8_6rRUN.md`**（`m7_paths` に md 名の上書き引数を足す。従来呼び出しの結果は不変）。
  - plan: `m8_6_plan.json` があり s3_sig が一致すれば、その内容（相手50・sel1・sig）を複製して `resource: {'axis': [...]}` を足して保存（相手と選出の前提を同一にする）。無ければ従来の plan 計算。
  - run: job に res を足し（`_job_adapt` の a[9]、省略時 None）、M8_6 の座っている側だけ軸タプル、相手側は None（相手は従来の deny＋プレイブック）。深さ (5,5)・seed=`m7_seed(X,k)`・適応選出・deny 両側は既存と同じ。games ヘッダに `resource` を記録し、違う設定の games への追記は SystemExit。`ad_record` は `res_stats` があるときだけ記録（従来レコードは不変）。
  - report: 従来の表に加えて「既存 M8_6 との比較」節（§4②）。

## 4. 検証
- **① 単体（tool/test_resource.py、数秒〜数分）**: M8_6 と既存の蓄積構築から局面を作る。
  - (a) 軸が全候補に勝つ局面（例: メガリザX＋ガブ 生存・相手残り2体が低HP/炎弱点）で `axis_cover` が True、相手に軸の受けを1体足すと False。
  - (b) 軸が1体だけ残り全員に勝つ → True／メガ済みでもう一方の軸の非メガでは勝てない → 割り当て評価が正しい。
  - (c) 成立局面で場の取り巻きが不利対面のとき、従来は交代・resource は居座り/攻撃に**手が変わる**例を1つ以上示す。不成立局面では `lookahead_action(res=axis)` と従来の手・info が一致。
  - (d) blind_play を同じ seed で args[13] 無し／(None,None) で2戦ずつ回し、res・turns・log・faints が既存コードと完全一致。
- **② 本番（Opus/ユーザーが実行）**: `python3 roundrobin.py m7 plan --party M8_6 --resource` → `m7 run --party M8_6 --resource --procs N` → `m7 report --party M8_6 --resource`。M8_6rRUN.md に:
  - 全体勝率と95%区間 vs 既存 62.4%（312/500）。500戦の標準誤差 ±2.2%、**±4% 以内の差は誤差扱い**（同じ seed の対応比較で符号検定/McNemar も併記）。
  - 相手ごと10戦の勝数差（既存 vs resource）、同じ (相手,k) で 勝→負・負→勝 の件数。
  - 取り巻きの瀕死数/試合（`faints` の main_side 側で軸以外）と、resource 発動あり/なし別の勝率・試合数。
  - 発動率（on≥1 の試合の割合）、成立した決定の割合、取り巻きを切った回数（sat_faint_on 合計）、成立時の取り巻きからの交代回数。
  - 平均秒/試合の比（既存 57.6 秒）。
  - **同条件の注意**: seed・深さ・相手・plan は同じだが、適応選出は同じ run 内の過去の勝敗を使うので、結果が1つ変わるとその相手の以降の選出が変わり得る。選出（sel0/sel1）が既存と一致した試合数を出し、一致試合だけの比較も載せる。乱数は seed 固定でも分岐が変わればその後は別系列になる。

## 5. 受け入れ条件
1. `python3 -m py_compile search.py refine.py roundrobin.py test_resource.py` が通る。
2. `python3 test_resource.py` が全項目 OK（§4① a〜d）。(d) で従来モードの結果が完全一致。
3. 既存の `python3 roundrobin.py m7 selftest --quick` が従来どおり通る。
4. 既存結果ファイルの sha256 が実装前後で不変: `logs/refine/m8_6_*.json(l)`, `logs/M8_6RUN.md`, 他の `logs/refine/*.json*`, `logs/*RUN.md`（実装前に一覧を保存して比較）。新規 `m8_6r_*` / `M8_6rRUN.md` は作られていない（本番未実行）。
5. 時間比: M8_6 の同じ seed 2戦（深さ5）で resource 有り/無しの所要時間比 ≤ 1.3（test_resource.py に任意項目 `--timing` として置く）。
6. SKILL.md の「シミュレーションへの反映（未実装）」の文を「`m7 --resource` で実装（SPEC_RESOURCE.md）」に更新。
