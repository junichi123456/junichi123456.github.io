# フォントで描いた文字を補助見本にする 仕様書（glyph_ocr の補助見本）

目的: 実戦の見本（`data/glyph_templates.json`、いま約76〜84文字）に無い文字を、ゲームに近いフォント（ニタラゴルイカ）で描いた文字で**補う**。
いまは実戦の見本が150文字に届かず、見本照合（`glyph_ocr.read_box`）がほとんど使われない。補助見本で穴を埋めて、
実戦の見本が持つ「ミ/三」「ぎ/き」の読み分けを早く効かせる。

前提（変更しない）:
- 観測は OBS WebSocket の映像だけ。Star Crusade は触らない。
- **フォントファイルはリポジトリに入れない**（再配布しない）。フォントから描いた見本ファイルもコミットしない。
- フォントのパスは PC ごとに違う → 環境変数か設定ファイルで渡す。未設定・ファイルが無い・開けないときは**機能オフで従来どおり**。
- Windows（PowerShell）で動くこと。ps1/bat を作る場合は ASCII のみ。
- コミットは `git pull --rebase origin ccr-22f85824-zkfyfy` のあと同じブランチへ push。PR は作らない。

方針（ユーザー承認済み）:
- 実戦の見本を優先。**実戦の見本が無い文字だけ**フォントで補う。
- フォント文字は取り違えが約15%ある → 補助見本で読んだ文字は **Windows OCR と一致したときだけ**採用する。
- まず無料版（`NitalagoRuikaSeikyo-03.TTF` / `-04.TTF`）で作って効果を測る。濁音・小さい仮名が無くて頭打ちなら有料版を検討（判断基準は 7 章）。

---

## 1. フォントの指定

優先順位（上が勝つ）:
1. 環境変数 `POKECHAMP_FONT`（フォントファイルのパス）。`POKECHAMP_FONT_WEIGHT`（整数、任意）、`POKECHAMP_FONT_INDEX`（.ttc の番号、任意）。
2. `tool/data/font_seed.json`:
   ```json
   {"path": "C:/Users/junem/Downloads/NitalagoRuika-KyohkanW/ニタラゴルイカ教漢（Win用）3.0/NitalagoRuikaSeikyo-04.TTF",
    "weight": 1, "index": 0, "enabled": true}
   ```
   - `weight` … 太さ補正。`ImageDraw.text(..., stroke_width=weight, stroke_fill=255)` の値（0〜3、既定 0）。ゲームの文字が太めなので eval で 0/1/2 を比べて決める。
   - `enabled: false` で明示的にオフ。
3. どちらも無い → 機能オフ。

追加するもの:
- `glyph_ocr.font_config() -> dict | None`（`{'path','weight','index'}`。ファイルが存在しない・`ImageFont.truetype` で開けない → `None`）。例外は内部で握りつぶす。
- `tool/data/font_seed.example.json`（上の形の見本。path は `"C:/path/to/NitalagoRuikaSeikyo-04.TTF"` のようなダミー）をコミットする。
- `.gitignore` に `pokechamp/tool/data/font_seed.json` と `pokechamp/tool/data/glyph_seed.json` を追加。`*.ttf` `*.TTF` `*.otf` `*.ttc` も `pokechamp/` 以下で無視する。

## 2. 補助見本の作り方

### 2-1 保存方式: ファイル `tool/data/glyph_seed.json`（キャッシュ）に決める
理由:
- 描画（約400文字×96px＋太さ補正）は1〜2秒かかる。`game_watch` の読み取りスレッドで毎回やると最初のメッセージを取り逃がす。ファイルなら `load()` と同じく mtime を見て読むだけ。
- `eval` と `game_watch` が同じ見本を使える（結果の再現性）。中身を `stats` で確認できる。
- 「実戦の見本がある文字は除く」は**読み込み時**に行う（後述）。build で実戦の見本が増えても作り直し不要。

形式:
```json
{"meta": {"font": "NitalagoRuikaSeikyo-04.TTF", "size": 12345, "mtime": 1790000000.0, "weight": 1, "index": 0,
          "charset": "<文字集合のsha1先頭12桁>", "ver": 1},
 "glyphs": {"あ": "0101...（N*N=576桁）", ...},
 "missing": "がぐげじだでば..."}
```
- `missing` … 文字集合のうちフォントに無い文字（`font_probe._has` が False）。7 章の集計に使う。
- `meta` が現在の設定（ファイル名・サイズ・mtime・weight・index・文字集合・ver）と食い違えば作り直す。

### 2-2 生成関数 `glyph_ocr.make_seed(cfg=None, out=SEED_P, verbose=True) -> int`
1. `cfg = cfg or font_config()`。`None` なら何もせず 0。
2. フォントを `ImageFont.truetype(path, font_probe.SIZE, index=index)` で開く。
3. 帯 `band = font_probe.band_of(font, stroke=weight)`（REF の文字で行の高さを決める。glyph_ocr.segment が行の帯で正規化するのと同じ考え方）。
4. 文字集合（2-3）の各文字 `ch` について:
   - `font_probe._has(font, ch)` が False → `missing` に入れて作らない。
   - `b = font_probe.render_cell(font, ch, band, stroke=weight)`（中で `glyph_ocr.cell` を使う＝同じ正規化）。`None` か `not glyph_like(b, ch)` なら作らない。
   - **1文字につき1個**（速度のため）。
5. `glyph_seed.json` を書く（一時ファイル→`os.replace` で原子的に）。
- `font_probe.py` の `_ink / band_of / render_cell` に**省略可能な引数 `stroke=0`** を足す（既定値で今の動作と同じ。CLI は変えない。`--weight` オプションを足すのは任意）。
- 実戦の文字は斜体だが、`glyph_ocr.ink` が傾きを戻してから切るので、フォントは**傾けずに**描く（font_probe と同じ）。
- CLI: `python glyph_ocr.py seed [--font PATH] [--weight W] [--index I]`（作り直して文字数と missing を表示）。
- `game_watch.py` 起動時の `_glyph_build` スレッドで、`glyph_ocr.build()` のあとに `glyph_ocr.make_seed()`（meta が同じなら何もしない）を呼ぶ。例外は print して続行。

### 2-3 文字集合 `seed_charset() -> str`
メッセージに出うる文字だけにする（行列を小さく保ち 50ms 以内に収めるため。目安 500 文字以下）:
- ひらがな `ぁ`〜`ゖ`、カタカナ `ァ`〜`ヶ`、`ー`、`PUNCT` の記号。
- `data/pokemon.json` の `ja` と `ab`（特性）、`data/moves.json` の `ja` に出てくる文字。
- `FIXED`・`STAT_JA` の値・`sentence_candidates` で使う定型文（`相手のトレーナーは…を繰り出した！` `戻れ` `倒れた` `上がった` `下がった` `ひるんで技がだせない` `メガシンカ` など）の文字。定型文の文字列はモジュール定数 `SEED_EXTRA` にまとめる。
- 持ち物名の一覧が data にあれば加えてよい（無ければ不要）。
- 並びは sorted、重複なし。数字・英字は入れない。

## 3. 照合での使い方（glyph_ocr）

### 3-1 読み込み
- `load(seed=False)`。`seed=True` のときだけ `glyph_seed.json` を読み、**実戦の見本に1個でもある文字を除いた**グリフを、実戦の見本の行列の後ろに追加する。各行に「補助か」のフラグ配列 `is_seed` を持つ。
- キャッシュはキー（実戦ファイル mtime, seed ファイル mtime, seed 有無）ごとに保持。seed ファイルが無い・壊れている → 補助なし（例外を外に出さない）。
- 既存の `load()`（引数なし）の戻り値・挙動は変えない（font_probe が `tpl['mat'] / ['matd'] / ['chars']` を使う）。

### 3-2 点数
- 定数 `SEED_PEN = 0.05`: 補助見本の点数から引く（同じくらい似ていれば実戦の見本、または実戦の見本の別の文字が勝つ）。
- 定数 `SEED_ACCEPT = 0.60`: 補助見本で読んだ文字の、ペナルティ後の点数がこれ未満なら、その文字は「不確か」。
- 値は eval で調整してよい（調整したら仕様の数字と報告に書く）。
- `match_char` は戻り値の形 `[(score, char), ...]` を保ったまま、補助かどうかを別に返す内部関数 `_match(b, tpl) -> [(score, char, is_seed), ...]` を作って共用する。
- 速度: 今の `match_char` の「文字ごとの最大」を Python の for で回している部分は、文字の番号配列と `np.maximum.at`（または並べ替え済みの `np.maximum.reduceat`）でベクトル化する。1行の全セルをまとめて1回の行列演算にしてもよい。

### 3-3 戻り値（互換を壊さない）
- `read_line(mask_img, seed=False, detail=False)` / `read_box(mask_img, seed=False, detail=False)`。
- `detail=False`（既定）: 今と同じ `(text, min_score)` または `None`。`seed=False` なら結果も今と完全に同じ。
- `detail=True`: dict を返す（読めなければ `None`）:
  ```python
  {'text': 'ミミッキュの攻撃が…', 'low': 0.61,            # low = 全文字の最小点（補助はペナルティ後）
   'chars': [{'ch': 'ミ', 'score': 0.83, 'seed': False}, ...],   # read_box は行をまたいで連結。行の区切りの ' ' は chars に入れない
   'n': 18, 'seed_n': 3, 'confidence': 'high' | 'seed'}       # 補助を1文字でも使えば 'seed'
  ```
- 補助見本で読んだ文字は `seed: True`、`confidence` は `'seed'`（低い扱い）。

### 3-4 150文字ゲート（MIN_CHARS）との関係
- **`MIN_CHARS` は実戦の見本の文字数だけで数える（補助は数えない）**。`seed=False` の判定は今のまま。
- `seed=True` のときのゲート: 実戦の見本が `SEED_MIN_REAL = 60` 文字以上、かつ 実戦＋補助で `MIN_CHARS` 以上。
  理由: 補助で読んだ文字は必ず Windows OCR と照合して採否を決める（4 章）ので、ゲートを下げても誤読は OCR 以上に増えない。実戦の見本が60文字未満では実戦の見本の比率が低すぎ、照合の意味が薄い。
- `stats` は「実戦 X 文字 / 補助 Y 文字（うち実戦と重なるので使わない Z）/ フォントに無い W 文字」を表示する。

## 4. 採用条件（game_watch.MsgWatch.read_box）

流れ（上から順に、例外はすべて握りつぶして次へ）:
1. 今と同じ: `r = glyph_ocr.read_box(mask)`（補助なし）。`r and r[1] >= ACCEPT` なら `r[0]` を返す（変更なし）。
2. `text = ocr.read(mask)`（Windows OCR）。今と同じく `is_message(text)` なら `save_crop(mask, text, …)`（crop に残すのは **OCR の文字列**のまま）。
3. 補助が使えるとき（`MsgWatch.SEED` が True かつ seed ファイルあり）: `d = glyph_ocr.read_box(mask, seed=True, detail=True)`。
   `adopt_seed(d, text)`（glyph_ocr に置く純関数。eval からも使う）が真なら `d['text']` を返し、偽なら `text` を返す。

`adopt_seed(d, ocr_text) -> bool` のルール（すべて満たすと採用）:
- (a) `d` が `None` でない。`msgparse.is_message(ocr_text)` が真。
- (b) 実戦の見本で読んだ文字はすべて `score >= ACCEPT`、補助で読んだ文字はすべて（ペナルティ後）`score >= SEED_ACCEPT`。
- (c) 補助で読んだ文字が全体の **30% 以下**（`seed_n <= 0.3 * n`）。
- (d) 両者を比較用に正規化: `k(x) = msgparse.apply_fixes(msgparse.norm(x))` から空白と `/` を除く。`difflib.SequenceMatcher(None, k(glyph), k(ocr))` の `ratio() >= 0.6`（同じ文を読んでいる）。
- (e) **補助で読んだ文字は、OCR の同じ位置の文字と一致していること**: glyph 文字列の各位置について、`get_opcodes()` の `equal` 区間に入っている位置だけを「一致」とし、`seed: True` の文字が1つでも `equal` 区間外なら不採用。正規化で文字数が変わる場合に備え、比較は `chars` 単位の glyph 文字列（空白なし）と `k(ocr)` で行い、glyph 側にも同じ `apply_fixes(norm())` をかけたうえで位置が対応しない文字は「不一致」と扱う（安全側）。
- 実戦の見本で読んだ文字は OCR と食い違ってよい（ここが「ミ/三」を直す効果）。
- 食い違い・条件不足は**従来どおり Windows OCR の結果**を返す。

記録（PC で効果を確かめるため）:
- 3 を通ったときだけ `logs/live/glyph_seed.jsonl` に1行追記: `{"t", "ocr", "glyph", "n", "seed_n", "low", "adopted": bool, "why": "<落ちた条件 a〜e または ok>"}`。1万行を超えたら古い半分を捨てる。書き込み失敗は無視。
- 起動オプション `--no-seed`（補助だけ切る）を追加。`--no-glyph` のときは補助も使わない。

## 5. 評価（受け入れ条件の測り方）: `python glyph_ocr.py eval`

```
python glyph_ocr.py eval [--crops DIR] [--font PATH] [--weight W] [--index I] [--folds 2]
                         [--templates PATH] [--simulate-free] [--json OUT]
```
- `--crops` 既定 `logs/sessions/msgcrops/`（237枚、`NNNN.png` + `{"ocr": ...}`）。PC では `logs/live/msgcrops/` も指定できる。
- 正解: `build` と同じ手順（`sentence_candidates` → 切り出し文字数が合い、OCR との類似 ≥ 0.45 の最上位）で決まった crop だけを使う。決まらない crop・`tail_learn` だけで決まる crop は除外し、件数を表示。**この正解づくりの部分は build と共通の関数 `_truth(png, ocr) -> (lines, counts, sentence) | None` に切り出し、build もそれを使う**（build の結果は変えない）。
- 見本: 既定は **k 分割（`--folds 2`、並べ替えた crop の番号 % k）**。学習側の crop から `learn_line(..., stage)` → `write_stage` で**一時ファイル**（`tempfile`）に実戦の見本を作り、テスト側で読む。`glyph_ocr.TPL_P` を一時的に差し替え、終わったら必ず戻す（`try/finally`）。**`data/glyph_templates.json` を書き換えない**。`--templates PATH` を指定したときは分割せずその見本で全 crop を読む（PC の実データ確認用。学習に使った crop と重なる場合は「参考値」と表示）。
- 補助見本: `--font` 指定時はそのフォントで一時の seed を作る（`make_seed(cfg, out=<tempfile>)`）。無ければ `font_config()`。どちらも無ければ補助ありの列は「フォントなし」と出して補助なしだけ評価。
- `--simulate-free`: フォントにある文字でも、濁音・半濁音（`unicodedata.normalize('NFD', ch)` に U+3099/U+309A を含む）、小さい仮名（`ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ`）、`戻` `繰` を「フォントに無い」扱いにする（クラウドの IPA ゴシック等で無料版の欠けを再現する）。
- 評価中は MIN_CHARS / SEED_MIN_REAL のゲートを無視して全行を読む（ゲートの効果は下の「方式」列で再現する）。

出す数字（テスト側の正解文字すべてについて。文字一致は `SequenceMatcher` の一致文字数 / 正解の文字数）:

| 方式 | 内容 |
|---|---|
| OCR | crop の `ocr` を `apply_fixes(norm())` したもの |
| 今の方式 | 実戦の見本だけ。ゲート（実戦 ≥ MIN_CHARS）と `low >= ACCEPT` を満たせば見本の読み、だめなら OCR（今の game_watch と同じ） |
| 実戦のみ（素） | ゲートなしで実戦の見本だけの読み（参考） |
| 補助あり（素） | ゲートなしで実戦＋補助の読み（参考） |
| 補助あり＋採用条件 | 4 章の流れ（1→3、`adopt_seed`）を再現した最終結果。ゲートは SEED_MIN_REAL を適用 |

各方式について: 文字一致率、行（crop）の完全一致率。加えて:
- 補助見本で読んだ文字の数と**誤読率**（補助あり（素）での、`seed: True` 文字のうち正解と違う割合）。採用された crop に限った誤読率も出す。
- 採用率（3 を通った crop のうち `adopt_seed` が真の割合）と、不採用の理由（a〜e）の件数。
- **フォントに無くて読めなかった文字**: 正解文字のうち「実戦の見本に無い かつ フォントに無い（`missing`）」文字の一覧（多い順、文字と回数）と、
  - 割合 A = それらの文字数 / 補助あり（素）で誤った文字数（読み取り失敗のうちフォントの欠けが原因の割合）、
  - 割合 B = それらの文字を含むために補助ありで読み切れない（その文字が誤る）crop の数 / 正解のある crop 数。
- 処理時間: 補助ありの `read_box(seed=True, detail=True)` 1回あたりの平均と最大（ms）。
- `--json OUT` で上をすべて JSON に保存。

## 6. 失敗時の安全
- フォント未設定・無い・壊れている・seed ファイルが無い/壊れている → 補助なしで今と同じ動作。`game_watch` は落ちない。
- `make_seed` / `load(seed=True)` / `adopt_seed` / ログ書き込みの例外は外へ出さない（`game_watch` 側でも try で囲む）。
- 処理時間: メッセージ欄1回（1〜2行）あたり **50ms 以下**（補助ありの読み取り＋OCR 比較。Windows OCR 自体の時間は含めない）。超える場合は 3-2 のベクトル化、文字集合の縮小の順で対処する。
- `seed=False` の呼び出し（今の `read_box(mask)`、`font_probe`、`build`、`learn`、`purge`）は結果も速度も変えない。

## 7. 有料版を買う判断基準（eval の数字で決める）
PC で、ニタラゴルイカ無料版を `font_seed.json` に設定し、`logs/live/msgcrops/` と `logs/sessions/msgcrops/` で eval を回して判断する:
- **買う**: 割合 A ≥ 40%（読み取り失敗の4割以上が「フォントに無い文字」） **かつ** 割合 B ≥ 20%（正解のある crop の2割以上がその欠けで読み切れない）。さらに一覧の上位に濁音・小さい仮名が並んでいること。
- **買わない**: 補助あり＋採用条件の文字一致率が今の方式より 1 ポイント未満しか上がらない（フォント自体が効いていない）、または補助見本の誤読率（素）が 25% を超える（字形が合っていない）。
- それ以外は実戦の見本が増えるのを待ち、1〜2週間後に同じ eval を回して再判断。
- 判断に使った eval の出力（JSON）を `logs/` に保存して push する（フォントや seed ファイルは含めない）。

## 8. ドキュメント更新
- `.claude/skills/pokechamp-battle/SKILL.md` の glyph_ocr の段落に追記: フォントの補助見本（`POKECHAMP_FONT` または `tool/data/font_seed.json`）、`python glyph_ocr.py seed` / `eval`、`--no-seed`、補助で読んだ文字は OCR と一致したときだけ使うこと、フォントは配布しないこと。3〜5行。
- `pokechamp/specs/SPEC_VISION.md` の B に「B-6 フォントの補助見本」を追加: 本仕様へのリンクと要点（実戦優先・実戦に無い文字だけ・OCR 一致で採用・ゲートは実戦の文字数で数える）。
- `glyph_ocr.py` 冒頭の docstring に `seed` / `eval` コマンド、`glyph_seed.json`、`read_line/read_box` の `seed` / `detail` 引数を追記。

## 9. 対象外・実装者への注意
対象外:
- パネルの名前（`PNAME` / `panel_name`）への適用。有料版の購入。フォントの自動ダウンロード。
- 実戦の見本の作り方（build の正解づくり・write_stage の食い違い検査・purge・tail_learn）の変更。`_truth` への切り出しは**結果が同じになる**ことを確かめること（前後で `build` を一時 TPL_P に対して実行し、出力 JSON が同一）。

注意:
- `build` / `write_stage` / `purge` / `tail_learn` / `learn_line` / `save_crop` の挙動を変えない。補助見本を `glyph_templates.json` に**絶対に混ぜない**（実戦の見本の食い違い検査が狂う）。
- 確認（クラウド）:
  1. `python3 -m py_compile pokechamp/tool/glyph_ocr.py pokechamp/tool/font_probe.py pokechamp/tool/game_watch.py`
  2. `/tmp` の合成テスト: IPA ゴシック（`/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf`）または `wqy-zenhei.ttc` で文字列を描いて `text_mask` 相当の白黒画像を作り、(i) フォント未設定で `read_box(mask)` が従来と同じ、(ii) `POKECHAMP_FONT` に存在しないパス → 機能オフで例外なし、(iii) `make_seed` → `load(seed=True)` で実戦にある文字が補助から除かれる、(iv) `adopt_seed` が a〜e の各条件で正しく True/False になる（補助文字が OCR と違う例、補助が30%超の例、別の文の例）、(v) 2行の箱で 50ms 以下。
  3. `cd pokechamp/tool && python3 glyph_ocr.py eval --font /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf --simulate-free` が最後まで動き、全項目を表示する。**受け入れ: 「補助あり＋採用条件」の文字一致率が「今の方式」以上**（下回ったら SEED_PEN / SEED_ACCEPT / 30% の値を見直し、変えた値を報告）。`wqy-zenhei.ttc`（`--index 0`）でも落ちない。
  4. `font_probe.py` を引数なしの今の使い方で実行して挙動が変わらない（見本が無ければ従来のメッセージ）。
- PC でしか確認できない項目（報告に「未確認・PC で確認が必要」と明記）: ニタラゴルイカ（03/04）の読み込みと `weight` の最適値、Windows でのパス（日本語フォルダ名）の扱い、`game_watch.py` 実行中の採用率と `glyph_seed.jsonl`、実機での処理時間、7 章の判断用 eval。
- 報告には eval の数字（各方式の文字一致率・補助の誤読率・割合 A/B・処理時間）を表で載せる。
