# 画面認識の改善 仕様書

目的: `tool/game_watch.py` の読み違い（相手6体の誤特定・場のポケモンが `?`・交代画面の読み落とし・自分の技や能力上昇の読み落とし）を減らす。
2つの改善を並行して行う。

| | 内容 | 実装する場所 | 費用 |
|---|---|---|---|
| A | 要所だけ画像を読めるAIに渡して判定させる | **PCのPowerShellで起動しているClaude** | 少額（1戦で数回） |
| B | ゲームの字体に合わせた文字読み取り（見本照合） | クラウド側（Sonnet 5.5）で実装・push | 無料 |

共通の前提（変更しない）:
- 観測は OBS の映像だけ。入力は OBS WebSocket の映像だけ（PCBL は使わない）。Star Crusade は触らない。
- `game_watch.py` が今の手法で出す結果が**基準**。A・B はどちらも「うまくいけば上書き、失敗・遅延したら今の結果のまま」とする（A・B が壊れても今より悪くならない）。
- 画面座標は 16:9 の割合で書く（`game_watch.py` 冒頭の `MSG_BOX` `OPP_PANEL` `MY_PANEL` `PNAME` と同じ流儀）。
- OBS のパスワード・個人情報をコミットに入れない。
- コミットは `git pull --rebase origin ccr-22f85824-zkfyfy` してから同ブランチへ push。PR は作らない。

---

## A. 要所だけ画像を読めるAIに渡す

### A-1 どこで使うか（3つの場面だけ）

| kind | いつ | 渡す画像 | 何を答えさせるか |
|---|---|---|---|
| `preview` | 選出画面を検出し、右の相手6枠が安定したとき（現状の `sprites.match` / `identify.py` の直前） | 選出画面の1フレーム（`game_<seq>_preview*.png` の最後の1枚） | 相手の6体の名前（上から順）と各タイプ |
| `replace` | 交代選択画面（自分のポケモンが瀕死・とんぼがえり等）を検出したとき | その画面の1フレーム | 自分の手持ち（名前・残HP・瀕死か）と、いま場にいる相手の名前 |
| `field` | 判断が `（場のポケモンが分からない）` になる、または場の名前が `?` のとき | コマンド選択画面の1フレーム | 場の自分/相手のポケモン名とHP |

毎フレーム送らない。上の3つ以外では呼ばない。

### A-2 受け渡しの方式（ファイル経由）

`game_watch.py` は依頼ファイルを書き、回答ファイルを待つ（最大待ち時間は種類ごと）。AI側は別プロセスで依頼を監視して回答を書く。

```
logs/live/vision_request.json   game_watch.py が書く（1件だけ・上書き）
logs/live/vision_answer.json    AI側が書く（requestのidをそのまま入れる）
```

`vision_request.json`:
```json
{"id": 221, "kind": "preview", "image": "logs/live/game_0221_preview_022.png", "time": 1792238000.0,
 "known": {"my_party": ["イダイトウ","ガブリアス","アシレーヌ","ヒートロトム","ミミッキュ","メタグロス"]}}
```
- `image` は `pokechamp/` からの相対パス。`known.my_party` は自分の6体（`team.py` の TEAM）。答えの名前の候補を絞るために渡す。

`vision_answer.json`（AI側が書く。`id` が依頼と一致しなければ無視）:
```json
{"id": 221, "kind": "preview", "ok": true,
 "opp_six": ["ガブリアス","メタグロス","ウォッシュロトム","グソクムシャ","サーフゴー","アシレーヌ"],
 "opp_types": [["ドラゴン","じめん"],["はがね","エスパー"],["でんき","みず"],["むし","みず"],["はがね","ゴースト"],["みず","フェアリー"]],
 "confidence": "high"}
```
- `replace`: `{"id", "kind":"replace", "ok":true, "my_party":[{"name":"イダイトウ","hp":173,"max":197,"fainted":false}, ...], "opp_active":"ガブリアス"}`
- `field`: `{"id", "kind":"field", "ok":true, "me":"アシレーヌ","opp":"メタグロス","me_hp":[187,187],"opp_hp_pct":74}`
- 読めない項目は `null`。全体が読めなければ `"ok": false`。**推測で名前を埋めない**（読めなければ null）。

### A-3 AI側の実装（PowerShell で起動している Claude が作る）

1. `tool/vision_agent.py`（新規）を作る。`vision_request.json` を0.3秒おきに監視し、新しい `id` が来たら次を実行する。
   - `claude -p --model claude-sonnet-5-5 --allowedTools Read --output-format text "<プロンプト>"` を呼ぶ。プロンプトには画像パス（Read で開かせる）と、kind ごとの質問・JSON形式・「名前は次の候補から選ぶ」を書く。
   - 相手6体の候補は `data/pokemon.json` の使用率上位＋`data/known_teams.json` に出てくる名前（`data/regulation.json` の現行レギュレーションのもの）。プロンプトに渡すのは名前の一覧だけ。
   - 出力から JSON を取り出して `vision_answer.json` に原子的に書く（`safeio.write_json` を使う）。
   - 失敗・タイムアウト（15秒）なら `"ok": false` を書く。
2. `game_watch.py` に取り込み側を追加する（`vision.py` のような小さなモジュールにまとめてよい）。
   - 依頼を書く関数 `ask(kind, image, seq, known=None, wait=...)` と、回答を待つ処理。待つのは別スレッドにし、メインの検出ループを止めない。
   - 待ち時間の目安: `preview` 最大 12秒（選出画面は時間に余裕がある）、`replace` 最大 6秒、`field` 最大 5秒。
   - **回答の使い方**:
     - `preview`: 回答が来たら `current.json` の `opp_team` を更新し、`battle.py select` を回答の6体で呼び直す（今は `sprites.confident` が全部揃ったときだけ自動選出している。ここを「AIの回答があればそれを使う」に変える）。`opp_types` は `identify.py` の結果と食い違うとき、AIの回答を優先して `type_glyphs_game.json` へ学習（`identify.learn`）する（食い違いは記録に残す）。
     - `replace`: 回答の `my_party` を `decide_async` の `party` として渡す（`party_read(text)` が2体未満のときの代わり。いまの `party_from_tracker` より優先）。`opp_active` は `tracker.s['active']['opp']` を更新する。
     - `field`: `act['me'] / act['opp']` が空のときだけ埋める（画面から読めた値を上書きしない）。
   - 回答が来る前でも今の処理で先に答えを出してよい。AIの回答が違う内容なら、**判断を更新して再表示**する（`publish(..., update=True)` を使う）。
3. 呼び出しの上限と安全:
   - 同じ `kind` の同じ画面（フレームの `_sig` がほぼ同じ）には再依頼しない。
   - 1戦あたり `preview` 1回、`replace` は交代が起きた回数、`field` は最大3回まで。
   - 画像に含まれるのは対戦画面だけ。OBSのパスワードやキャプチャ設定は渡さない。
4. 起動: `game_watch.py` が `vision_agent.py` を子プロセスとして起動する（`--no-vision` で無効化）。`claude` コマンドが見つからなければ「画像AIなし」と1行出して、今の処理だけで動く。

### A-4 受け入れ条件
- 今回の誤りの再現画像で正しく答える: `logs/sessions/shots_221/game_0221_preview_022.png` → 相手6体が ガブリアス / メタグロス / ウォッシュロトム / グソクムシャ / サーフゴー / アシレーヌ（上から順）。
- `game_0233_replace.png` → 自分の手持ちが ガブリアス(0/185,fainted) / アシレーヌ(0/187,fainted) / イダイトウ(173/197)、相手の場は ガブリアス。
- `claude` が使えない・15秒かかる・不正なJSONでも、`game_watch.py` は止まらず従来どおり判断を出す。
- 判断表示までの遅れが、`preview` 以外で今より増えない（待つのは別スレッド）。

---

## B. ゲームの字体に合わせた文字読み取り（見本照合）

### B-1 狙い
Windows の文字認識は、このゲームの斜体の文字で「ミ→三」「ぎ→き」「が→か」「ク→ワ」のような誤読を繰り返す。字体は固定なので、**文字の画像の見本**と照合して読む。

### B-2 読む場所（まず2か所）
1. **戦闘メッセージ欄** `MSG_BOX = (0.13, 0.72, 0.87, 0.87)`: 「相手のピクシーのムーンフォース！」「ミミッキュの攻撃がぐーんと上がった！」など。1〜2行。
2. **手持ち・パネルの名前**（`PNAME`）は今の `MsgWatch.panel_name` のまま。見本照合が安定してから置き換える（今回は対象外）。

### B-3 方式
- 新規 `tool/glyph_ocr.py`:
  - `build_templates(frames_dir)`: 学習用の画像から文字の見本を作る（下記 B-4）。見本は `data/glyph_templates.json`（文字 → 複数の 24×24 程度の2値画像をビット列で保存）。
  - `read_line(mask_img) -> (text, per_char_score)`: `text_mask`（`game_watch.py`）が作る白黒画像を、文字ごとに切り分けて見本と照合し文字列にする。
    - 切り分け: 縦方向の投影（黒画素の列ヒストグラム）で文字の間の空白を探す。斜体なので、読む前に今の `panel_name` と同じ傾きの補正（`k=0.2`）をかける。
    - 照合: 見本との IoU（`identify.match_type` と同じやり方）。上位候補と点数を返す。
    - 低い点数の文字は `?` ではなく**第2候補を併記**して返し、後段の既存の補正（`msgparse._fuzzy` が現在の12体の名前と技名に寄せる）に任せる。
  - 速度目標: メッセージ欄1枚（1〜2行）を **50ms以下**（numpy のビット演算でよい）。
- `game_watch.py` の `MsgWatch` でメッセージ欄を読む箇所（`ocr.read(text_mask(...))`）に、**まず `glyph_ocr.read_line` を試し、見本が足りない・点数が低いときだけ今の `WinOCR`** を使うフォールバックを入れる。両方の結果が食い違い、`glyph_ocr` の点数が高いときは `glyph_ocr` を採用。
- `--no-glyph` で無効にできる。見本ファイルが無ければ従来どおり動く。

### B-4 見本の集め方
- 学習用データ: `logs/live/game_*.png` と `logs/sessions/*/` にある実戦のスクリーンショット、`logs/live/battle_messages.jsonl` / `messages.jsonl`（その時の OCR 結果）。
- 正解の文字列は、**現在の12体の名前・技名（`data/moves.json`）・定型文**（「〜の攻撃がぐーんと上がった」「〜は倒れた」「〜を繰り出した」「効果はばつぐんだ」など）から作る。実戦画像のメッセージ欄を切り出して文字に分け、OCRの結果（`msgparse` の補正後）が定型文や名前に一致した行だけ、その文字画像を見本として採用する（誤読行は採用しない）。
- 追加の見本: 同じ字体の文字を OBS 映像から**手動で追加するコマンド**を用意する: `python glyph_ocr.py learn <画像> "<その行の正しい文字列>"`。
- 文字ごとに見本は最大8個。重複（IoU 0.95以上）は捨てる。

### B-5 受け入れ条件
- `logs/sessions/20261017_2100/` の実戦画像で、次の行を正しく読める:
  - 「ミミッキュのつるぎのまい」「ミミッキュの攻撃がぐーんと上がった」「相手のピクシーのムーンフォース」。
- 既存の `battle_messages.jsonl` の行を再解析したとき、技・能力変化・交代として読み取れる件数が、今（`msgparse.parse_turn` で moves 84 / boosts 10 / switch 37）より減らない。
- 処理時間がメッセージ欄1回あたり 50ms 以下。
- 見本ファイルが空でも `game_watch.py` が動く。

---

## 作業の分担と順序

1. **B（Sonnet 5.5・クラウド）**: `glyph_ocr.py` と `game_watch.py` への組み込み、見本の自動生成、`SKILL.md`・`tool/README.md` への追記。push する。
2. **A（PowerShell の Claude）**: この仕様書の A を読んで `vision_agent.py` と取り込み側を実装する。実装前に `git pull --rebase origin ccr-22f85824-zkfyfy` し、B が入った後の `game_watch.py` の上に作る。
3. 両方入ったあと、次の実戦の `logs/live` を `python pack_logs.py` で push し、読み違いが減ったか確認する。
