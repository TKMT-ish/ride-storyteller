# デモ動画シナリオ v2（案・2026-09-09）

> オーナーの指示（2026-09-09 04:00 JST）: 「困っていたこと → この仕組みがどう解いたか」
> が分かる構成に作り直す。編集作業が何分で終わるかを言う。Ride Storyteller の成果物と
> それ以外を見分けられる画面設計にする。クラウド AI の前にローカルで低解像度化する点は
> 訴求してよい。**シナリオのみ。動画はまだ作らない。**

現行の構成（`demo-script-en.md`、9 区間 2 分 57 秒）は「作品の抜粋に説明を重ねる」
形で、**何が問題だったのかを一度も見せていない**。v2 は前半を「問題 → 仕組み」、
後半を「結果」に振り分け、画面の種類ごとに見た目の規則を決める。

## 数字はすべて day 7 の記録から

画面に出す数字は下の表のものだけを使う。出所は `private-media/work/day-7-v1/` の
記録と、Seagate ドライブ上の元ファイルの実測（2026-09-09）。

| 何 | 値 | 出所 |
|---|---|---|
| 走行 | 314.8 km・7 時間 21 分・GPS 点 9,325 | `local-pipeline-summary.json` |
| 元の録画 | GoPro 4K **35 ファイル・108.6 GB・4 時間 43 分** | カタログの asset を drive 上で実測 |
| 窓 | **337 窓 × 12 秒**（60 秒おき）＝ 67 分ぶん | `analysis-settings.json`、`gemini-video-analysis.json` |
| 小さなコピー | **854×480・1 fps**、1 本約 0.6 MB、**合計 245.1 MB** | `analysis-proxies/`、コンソール表示 |
| 判定 | Gemini 2.5 Flash、**337 / 337**、**¥49.79** | コンソール表示 |
| 単調さ | 見どころ（visual interest）0.7 以上は **337 窓中 43** | 判定の集計 |
| 物語 | **63 ビート**（映像 59・空白カード 4）、作品 **6 分 20 秒** | `journey-story-plan.json` |
| 機械の時間 | 取り込み → 判定完了 **66 分**（05:18 → 06:24）、物語 → 作品 **13 分**（00:38 → 00:51）。合計 **約 80 分** | 各記録ファイルの更新時刻 |
| 人の操作 | **確認 2 回**（時計のずれ、費用の数字を打ち返す） | 設計どおり |

「編集作業が xx 分で完了」は **「約 80 分の機械時間、人は確認 2 回」** と言う。
比較対象は「4 時間 43 分の録画を等速で見るだけで 4 時間 43 分」。
形容詞（革命的）より、この対比のほうが審査員には強い。

## 画面の 3 種類と見分け方

| 種類 | 何を映すか | 見た目 |
|---|---|---|
| **RAW** | 元の GoPro 映像（小さなコピーそのまま） | 全画面。左上に小さな札 `RAW GoPro · unedited` |
| **Console** | ローカルのコンソール画面、数値カード、章カード | 全画面。左上に札 `Local console` |
| **Ride Storyteller の成果物** | 完成した作品 | **80 % に縮小（1536×864）して右上へ**（余白 24 px、細い白枠）。枠の上に札 `Ride Storyteller output · day 7 · no one edited this`。**デモの説明文は枠の下の空いた帯（下 192 px）に左寄せ**で置く |

成果物を縮小する副作用が一つ良い方向に働く。作品自身の下部テロップ（章題・地名）
が枠の中にそのまま見え、デモの説明文とぶつからない。現行の「作品の下部テロップの
上にデモの説明を重ねる」構成では両方が下 1/3 に来て読みづらかった。

最後の 10 秒だけ全画面に戻すかは**オーナーの判断**（下の「決めていただくこと」）。
私は札を残したまま最後だけ全画面にするのを勧める。締めの一撃は大きいほうがよい。

## タイムライン（2 分 57 秒・10 区間）

英文がそのまま字幕（.srt）にもなる。現行どおり音声ナレーションは無し（後述）。

| # | 開始 | 秒 | 種類 | 画面 | 画面上の英文（字幕） |
|---|---|---|---|---|---|
| 1 | 0:00 | 8 | 成果物 | 作品の最も良い 8 秒（海沿いの走行を想定） | **Made by Ride Storyteller** from 4 hours 43 minutes of GoPro footage. No one edited this. |
| 2 | 0:08 | 12 | RAW | 小さなコピー 12 本を 4×3 のモザイクで同時再生。ほぼ全部が灰色の道路 | One day of riding: **108 GB of video, 4 hours 43 minutes.** Nearly all of it looks like this. |
| 3 | 0:20 | 12 | RAW | 1 本を等速で。何も起きない | Finding the good minutes means watching all of it. So the footage sat on a hard drive. |
| 4 | 0:32 | 15 | Console | 作品の章カード（経路図と区間の強調） | The GPS track already knows where the day happened: setting off, each stop, each named road. **Every leg becomes a chapter.** |
| 5 | 0:47 | 18 | Console | コンソールの「コピーを作る」段階と、できた小さなコピーが並ぶ様子 | Locally, ffmpeg cuts **337 twelve-second windows** and shrinks each to **480p at one frame a second: 245 MB in all.** The 4K never leaves the machine. |
| 6 | 1:05 | 15 | Console | 費用の確認欄。数字を打ち返す操作 | One page shows the price — **¥49.79** — and waits for a person to type that figure back. Nothing is bought until then. |
| 7 | 1:20 | 30 | RAW＋判定 | 小さなコピー 4 本を順に（各 7.5 秒）。それぞれに Gemini の判定文とスコアを重ねる（例: 「rural highway · vista · interest 0.9」「car park · stationary · 0.2」） | **Gemini 2.5 Flash judges every window**: is the rider in frame, is the bike stopped, what is worth looking at. 337 structured judgements. **Only 43 scored 0.7 or more.** |
| 8 | 1:50 | 15 | Console | 数値カード（現行の `console` 区間を流用）: 337 windows · 245.1 MB · ¥49.79 · 63 beats · 380 s | The story planner keeps **63 beats in the order the day happened**; ffmpeg cuts the film and adds the music. **About 80 minutes of machine time. Two confirmations from a person.** |
| 9 | 2:05 | 40 | 成果物 | 作品の連続 40 秒。章カード → 走行 → 下部テロップ（地名・区間）→ 立ち寄り | The result: **six minutes**, chapters named by place, a map in the corner, sections for scenic roads and stops. |
| 10 | 2:45 | 12 | Console（カード） | 締めのカード | **Open source (AGPL-3.0). Runs on your machine. About ¥50 of Gemini per riding day.** Judges: the day-7 package cuts this film on your own computer. Music: Wandering by Numall Fix · CC BY 3.0 · royalty free music by www.free-stock-music.com |

合計 177 秒（8+12+12+15+18+15+30+15+40+12）。3 分の上限に 3 秒残すのは現行と同じ理由
（エンコードで数十ミリ秒はみ出ても 3:00 を超えないため）。

オーナーの例文（「大量の録画のほとんどは退屈で単調 … HDD の肥やし … Gemini で GPS と
録画から見栄えの良いシーンを切り出せるようになった」）は、区間 2・3・7 がそのまま
英語で担う。

## この案に含めた私の考え

1. **冒頭 8 秒は結果を先に見せる。** 問題から始めると最初の 20 秒が灰色の道路になる。
   結果を一瞬見せてから「でも元はこれ」と落とすほうが、審査員が最初の 10 秒で離れない。
2. **単調さは形容詞でなく Gemini 自身の数字で言う。** 「337 窓中 43 だけが 0.7 以上」は、
   この仕組みが選別している証拠にもなる。
3. **区間 7 が "Agentic Cinema" の核。** 小さなコピーの上に判定文をそのまま重ねると、
   「モデルが何を見て何と言ったか」が見え、同時にオーナーの訴求点（ローカルで低解像度に
   してから送る）を二度目に、今度は絵で示せる。
4. **時間の主張は正直に。** 判定を買い直さない配布物の「5 分半で作品」は別の話で、
   デモで言うのは取り込みから作品までの約 80 分。これでも「4 時間 43 分を見るだけで
   4 時間 43 分」との対比で十分に強い。
5. **作品は英語で切り直す。** いまの day 7 の作品は章カードも下部テロップも日本語
   （`local-pipeline-inputs.json` の `output_language: ja`）。デモの枠の中に日本語が
   出ると審査員は読めない。`output_language` を `en` にして物語計画と作品だけ作り直す。
   判定は買い直さないので ¥0、機械時間は約 15 分。配布物の作品も同じ判断が要る。
6. **ナレーション音声は入れない。** 字幕付きの英文で要件を満たす。macOS の合成音声は
   可能だが品質が作品の印象を下げる。オーナーが英語で吹き込むなら別。
7. **プライバシーの検査は増える。** RAW のモザイク（区間 2・3・7）は小さなコピーを
   そのまま出すので、判定文に人・車が書かれていない窓から選び、組んだ後で
   `app.plate_blur` の全フレーム検査を通す。成果物の枠は 80 % なのでナンバーは小さく
   なるが、それを理由に検査を省かない。

## 実装に要るもの（作るときの見積もり）

`app/submission/demo_assembly.py` に区間の種類を 3 つ足す。既存の Card / Still /
Excerpt / CaptionedExcerpt はそのまま使える。

| 追加 | 何をする | 目安 |
|---|---|---|
| `FramedExcerpt` | 作品を 80 % に縮めて右上に置き、札と下の帯の説明文を重ねる（ffmpeg `scale`+`pad`+`overlay`、札と説明文は既存の rasteriser で PNG に） | 2 時間 |
| `Mosaic` | 小さなコピー N 本を格子で同時再生（`xstack`）、札付き | 2 時間 |
| `JudgedWindow` | 小さなコピー 1 本に判定文とスコアの PNG を重ねる。文は `gemini-video-analysis.json` から、地名・ファイル名・座標を出さない検査を既存テストに足す | 2 時間 |
| 英語の作品 | `output_language: en` で物語計画と作品を再生成、ナンバーぼかし、全フレーム検査 | 機械 30 分 |
| 字幕 | 現行どおりタイムラインから生成（変更なし） | — |

テストと文書更新を含めて **半日**。動画の生成はオーナーの合図を待つ。

## 決めていただくこと

1. **作品の言語**: デモ用に英語で切り直してよいか（推奨: はい）。配布物の作品も英語にするか。
2. **最後の 10 秒**: 80 % の枠のままか、札を残して全画面に戻すか（推奨: 全画面）。
3. **区間 9 の 40 秒**: 英語版ができてから私が候補 2 か所を出す。海沿い＋章カード＋
   下部テロップが揃う場所を優先する。
4. **コンソールの映し方**: 実画面の録画（本物の day 7 の数字が動く）か、いまの静止カードか。
   録画のほうが「本当に動く」証拠になるが、収録と検査に 1 時間増える。
5. **ナレーション**: 字幕のみ（推奨）か、音声を入れるか。

## 実装記録（2026-09-09）

オーナーの回答: 英語で作る、最後の 10 秒は全画面、ナレーションは今回なし（原稿は
[`demo-narration-en.md`](demo-narration-en.md) に用意）。それ以外は本案どおり。

- **組み立て器**: `app/submission/demo_scenario_v2.py`（`python -m app.submission.demo_scenario_v2`）。
  区間の種類は FramedExcerpt・FullScreenExcerpt・Mosaic・SingleRaw・JudgedWindow・ConsoleStill と
  v1 の Card。合計 177.0 秒をテストが固定し、数字は inputs と package の判定記録を照合してから使う。
- **英語の作品**: `private-media/work/day-7-en-v1`（`output_language: en` で物語計画と作品だけ再生成、
  判定は買い直していない）。380.07 秒、章カード・下部テロップは英語。
- **区間 1 の 8 秒**: 作品 163 秒から（Bluff の展望台から海沿いを下る）。**区間 9 の 40 秒**: 303 秒から
  （Clyde の展望台での停止 → 章カード「Clyde → Cromwell」→ 走行 → 湖沿い。最後の 10 秒は湖の道を全画面）。
  顔が写る 98〜103 秒からは十分に離れている。
- **区間 5・6 の実画面**: `/workflow` ページに、判定記録だけを抜いた day 7 の写しを読ませ、
  「承認待ち」の状態（337 clips · 245.1 MB · ¥49.79、Before you approve、金額の入力欄）を撮った。
- **元映像の窓**: 337 の判定から機械的に選び（単調さは見どころスコアで）、17 本すべてを
  顔・ナンバー検査にかけた。2 本を落とし、代替で埋めた。
- **図の 8**: コンソールの「計画」は今日のコードで再計算されるため 326 窓になっていた。
  買った判定は 337 なので、カードも照合も**買った記録**に合わせる（`check_figures_against_console`）。
- **ぼかし**: 元映像の窓は判定用コピーそのまま、作品は未ぼかしの版を使い、**組んだデモに**
  `app.plate_blur --fps 30 --passes 4` をかけて全フレームを検査する。

