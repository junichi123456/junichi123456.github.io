# SPEC_COUNTER: 苦手構築への対策選出（ベストレスポンス探索）

作成: Opus 5.5 / 実装: Sonnet 5.5 / 対象: `pokechamp/tool/roundrobin.py` のみ（Star Crusade・game_watch.py は触らない）

## 1. 目的
メイン構築 L=`db0baa2843d2bd4b`（乾坤一擲リザホーク）が適応10戦（`logs/refine/ad_games.json`）で負け越した相手 X について、
X の選出を固定したうえで L の候補24通りを総当たりし、「この相手にはこの選出」「出してはいけない個体」を決める。

## 2. 対象の相手（既定8構築）
勝率は ad_games.json の L 視点（勝1・分0.5・負0、res None は除外）。

| id | 名前 | 適応10戦 |
|---|---|---|
| e74e068449bec8e6 | 付け焼刃サイクル（120位） | 2/10 |
| bab22dcc629688e8 | ジュペパモイダイ（154位） | 2/10 |
| yakkun_n8943 | ルカリザ検定対面 | 2/10 |
| 047f48a2b51a88d1 | 復刻カバドリマンダ（229位） | 3/10 |
| 856f9d20f6a9b5a9 | 鬼がかり対面（438位） | 3/10 |
| 1813f454535e22eb | 主人公はフラエッテ（546位） | 4/10 |
| 45330f7ff4d912c7 | 最終661位(2248) | 4/10 |
| 598640a00e16d952 | 最終676位 | 4/10 |

- 機械的な抽出規則: 勝率昇順、同率は `ad_plan.json` の `opponents` 順。30%以下の5構築は規則どおり。40%は10構築が同率のため、上の3つは依頼者の指定で採用（243位/264位/459位/561位は今回対象外）。
- 既定リストは定数 `CT_DEFAULT_OPPS` として持つ。`--opps id,id,...` で上書きできる。各 id は ad_plan の opponents に含まれ、ad_games に10戦の結果があることを確認する（なければ停止）。

## 3. 相手の選出の固定
- X の固定選出 = ad_games.json の X の10戦で X 側が使った並び（先発込みの tuple）の最頻値。同数なら最初に出た方（k の小さい方）。
- 現データでの期待値: e74e→セグレイブ/ギャラドス/キラフロル、bab2→ブリジュラス/イダイトウ/ドドゲザン、yakkun→ミミッキュ/リザードン/カバルドン、047f→ボーマンダ/カバルドン/ブリジュラス、856f→イダイトウ/リザードン/ミミッキュ。
- X 側の並びは L の選出に関係なく常にこれ（選出計算はしない）。

## 4. L の候補
- `rr_plan.json` の `teams[L]['candidates']`（24通り、並び＝先発込み）をそのまま使う。メガ制約は生成時の規則のまま（メガ候補が2体の構築なのでメガ持ち2体を同時に入れない＝メガ個体の重なり≤1）。新たな候補は作らない。

## 5. 対戦の条件
- 1戦の呼び出しは `_job_adapt` と同じ: `rr_apply(_TEAMS[s0])` の後 `R.blind_play((None, s1, o0, o1, seed, DEPTH[0], DEPTH[1], False, None, False, (s0,), (True, True)))`。4手読み・両側 deny・ブラインド。
- 左右: k 偶数は L が side0、奇数は X が side0。
- 種: `zlib.crc32(f'ct{X}{"/".join(sel)}{k}'.encode())`（sel は L の並び）。
- 第1段: 8構築×24通り×k=0..3（4戦）＝768戦。
- 第2段（確認）: 第1段の上位3選出に k=4..15（12戦）＝288戦。上位の順位は「勝率 → L 残りHP合計−相手残りHP合計の平均 → 候補の順番」。第1段がその X で全部終わってから決める。
- 選出の評価は第2段の12戦（Wilson 95%区間）。同率は16戦合計で比べる。

## 6. ファイルと再開
- `logs/refine/ct_plan.json`: version、sig、main、ad_plan sig、opps、X ごとの固定選出、L の候補24、確認段の上位3（決まり次第追記）。sig = sha256(ad_plan sig + L + opps + 固定選出 + CT_VERSION)。sig が違えば停止（`--force` で旧ファイルを日付付きに退避）。
- `logs/refine/ct_games.json`: `{'version','plan_sig','games':{key:rec}}`。key は `ct:{X}|{sel}|{k}`。rec は ad_record と同じ項目（side0/side1/sel0/sel1/seed/res/winner/judged/turns/left/faints/sec/error/deny_stats）＋ `opp, sel(L側), k, stage(1|2), main_side`。
- 1戦終わるごとに `safeio.write_json` で atomic 保存。run は既存キーを飛ばす（`--retry-errors` で res None のみやり直し）。`--max-games N`、`--procs`（既定4）。進捗表示は adapt run と同じ形式。
- 既存ファイル（rr_plan/rr_games/ad_plan/ad_games/ad_logs/ADAPT.md ほか logs 配下）は書き換えない。

## 7. コマンド（後方互換、既存サブコマンドの挙動は不変）
`python roundrobin.py counter plan|run|report|selftest [--opps ...] [--out-dir D] [--procs 4] [--max-games N] [--force] [--retry-errors]`
- plan: 対象と固定選出を確定し ct_plan.json を書く（対戦はしない）。
- run: 第1段→（X ごとに第1段が終われば）第2段。
- report: `logs/COUNTER.md`（`--out-dir` 指定時はその中）を書く。

## 8. レポート `logs/COUNTER.md`
相手ごとに:
1. 相手の固定選出、適応10戦の L の実績（勝率、L が使った選出の上位）。
2. 最良選出: 確認12戦の勝率と Wilson 区間、16戦合計。適応10戦の勝率との差。
3. 上位3と悪い選出トップ3（第1段の勝率、同率は残りHP差の平均）。
4. 24通りの表（選出・第1段勝率・確認勝率）。
5. 倒され方（最良選出と全体の両方）: L 側で最初に倒れた個体の回数、L を倒した相手個体の回数（`faints` の [ターン, 側, 倒れた個体, 倒した個体] から）。相手の主力＝L を倒した回数の多い個体。
6. 結論: 「この相手にはこの選出」、出してはいけない個体（その個体を含む選出の第1段勝率が含まない選出より15ポイント以上低い個体）。
冒頭に全体まとめ（8構築の最良選出一覧と、適応10戦からの改善幅）、末尾に条件（種の式、深さ、deny、plan sig）。

## 9. 受け入れ条件（selftest、一時フォルダで実行）
1. `python -m py_compile roundrobin.py` が通る。
2. 候補: L の候補が24通り・重複なし・全て `teams[L]['candidates']` に含まれ、メガ個体の重なりが各1以下。
3. 選出固定: 固定選出が最頻値規則どおり（上の5構築の期待値と一致）。スタブ `_CT_PLAY` で記録した呼び出し引数で、X 側の並びが常に固定選出・L 側が指定候補・左右が k で交互・種が式どおりであること。
4. 再開: スタブで `--max-games 5` を2回実行し、重複なく10件・同じキーの結果が同一。第1段が終わった X だけ第2段が始まる。
5. sha256: selftest 前後で rr_plan.json、rr_games.json、ad_plan.json、ad_games.json、ADAPT.md の sha256 が不変。既定の場所に ct_* と COUNTER.md が作られない。
6. 1戦の時間: 実エンジンで1戦だけ回し 30秒以内（目安10秒）であることを表示。
7. report がスタブ結果から全セクションを出力し、Wilson 区間が既存 `wilson()` と一致。
- 実装者は本番の run（768＋288戦）を実行しない。selftest 結果と変更点を報告すること。
