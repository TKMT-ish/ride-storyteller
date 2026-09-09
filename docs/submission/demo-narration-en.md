# デモ動画ナレーション台本（英語・案・2026-09-09）

> [`demo-scenario-v2-ja.md`](demo-scenario-v2-ja.md) の 10 区間・177 秒のタイムラインに
> 声を載せるための台本。シナリオ v2 の「決めていただくこと 5」の推奨は **字幕のみ** で、
> この台本は **オーナーが自分の声で吹き込むと決めた場合** に使う。決めるまで録音は要らない。
> 動画そのものは作らない。字幕（.srt）はこれまでどおり画面上の英文から生成し、
> ここで話す英文は字幕より短い口語で、**画面の英文と矛盾させない**。

守ったこと。

- 数字はすべてシナリオ v2 の表のもの（走行日 day 7 の記録）。台本が新しい数字を足すことはない。
- 話す速さは **約 2.3 語/秒（140 語/分弱）**。会話より少しゆっくり。8 秒の区間は 16 語前後まで、
  40 秒の区間は文の間に何秒も置く。
- オーナーの言い分をそのまま英語にした。一日の録画の大半は単調で、良い場面を人が選ぶのは
  大仕事だから録画は HDD の肥やしになっていた。いまは GPS の軌跡と GoPro の録画から Gemini が
  見栄えのする場面を切り出し、その大仕事は機械時間約 80 分・人の確認 2 回で終わる。
  クラウドのモデルへ行くのはローカルで作った低解像度のコピーだけで、4K はこの機械から出ない。
- 総語数 **301 語**（上限 400）。区間ごとの語数と「目安秒」（語数 ÷ 2.3）を各区間の末尾に置く。
  語数は空白区切り（`forty-three` は 1 語。単独のダッシュ「—」と、`[間 3 秒]` のような角括弧の
  指示は数えない・話さない）。

---

## 区間ごとの台本

区間の番号・開始・秒・種類・画面の英文は v2 のタイムラインの原文どおり。
**話す英文** が録音するもの、**日本語の意味** はオーナーが内容を確かめるためのもの（訳は逐語ではない）。

### 1 · 0:00 · 8 秒 · 成果物（作品の最も良い 8 秒）

**画面の英文（字幕）**
> **Made by Ride Storyteller** from 4 hours 43 minutes of GoPro footage. No one edited this.

**話す英文**
> Ride Storyteller cut this from four hours forty-three of GoPro footage. Nobody edited it.

**日本語の意味**
> Ride Storyteller が、4 時間 43 分の GoPro 映像からこれを切り出しました。人は誰も編集していません。

語数 14 · 目安 6 秒 · 余白 2 秒。絵が出て 0.5 秒ほど置いてから話し始める。

### 2 · 0:08 · 12 秒 · RAW（小さなコピー 12 本のモザイク）

**画面の英文（字幕）**
> One day of riding: **108 GB of video, 4 hours 43 minutes.** Nearly all of it looks like this.

**話す英文**
> One day of riding. A hundred and eight gigabytes of video, four hours forty-three minutes. And nearly all of it looks like this.

**日本語の意味**
> ある一日の走行。108 GB の動画、4 時間 43 分。そのほとんどが、こんな景色です。

語数 23 · 目安 10 秒 · 余白 2 秒。「looks like this」でモザイクを指す気持ちで、少し落として終える。

### 3 · 0:20 · 12 秒 · RAW（1 本を等速で。何も起きない）

**画面の英文（字幕）**
> Finding the good minutes means watching all of it. So the footage sat on a hard drive.

**話す英文**
> Finding the good minutes means watching all of it. Hours of work, by hand. [間 1 秒] So the recordings just sat on a hard drive.

**日本語の意味**
> 良い数分を探すには、全部を見なければならない。何時間もの手作業です。だから録画はハードディスクに眠ったままでした。

語数 23 · 目安 10 秒 · 余白 2 秒。「by hand」の後に一拍。何も起きない絵をわざと 1 秒見せる。

### 4 · 0:32 · 15 秒 · Console（作品の章カード：経路図と区間の強調）

**画面の英文（字幕）**
> The GPS track already knows where the day happened: setting off, each stop, each named road. **Every leg becomes a chapter.**

**話す英文**
> No one has to log where the day went. The GPS track already knows: setting off, each stop, each named road. [間 1 秒] Every leg becomes a chapter.

**日本語の意味**
> その日どこを走ったかを人が記録する必要はありません。GPS の軌跡がもう知っている——出発、それぞれの停止、名前のある道。区間ひとつひとつが章になります。

語数 26 · 目安 11 秒 · 余白 4 秒。ここが「困っていたこと」から「仕組み」へ切り替わる点。
声を少し明るくする。「Every leg becomes a chapter」は経路図の区間の強調が出るのに合わせる。

### 5 · 0:47 · 18 秒 · Console（「コピーを作る」段階と、できた小さなコピー）

**画面の英文（字幕）**
> Locally, ffmpeg cuts **337 twelve-second windows** and shrinks each to **480p at one frame a second: 245 MB in all.** The 4K never leaves the machine.

**話す英文**
> Locally, ffmpeg cuts three hundred and thirty-seven twelve-second windows, shrunk to 480p at one frame a second: two hundred and forty-five megabytes in all. [間 1 秒] Only those go to the cloud. The 4K never leaves the machine.

**日本語の意味**
> ローカルで ffmpeg が 12 秒の窓を 337 個切り出し、480p・毎秒 1 フレームに縮めます。合計 245 MB。クラウドへ送るのはこれだけ。4K はこの機械から出ません。

語数 36 · 目安 16 秒 · 余白 2 秒。この区間だけ語数が詰まっている。数字を急がず、
その代わり文の間を切り詰める。「The 4K never leaves the machine」は一語ずつはっきり。
読み方: ffmpeg は「エフ・エフ・エム・ペグ」、480p は「four-eighty-p」、4K は「four-K」。

### 6 · 1:05 · 15 秒 · Console（費用の確認欄。数字を打ち返す操作）

**画面の英文（字幕）**
> One page shows the price — **¥49.79** — and waits for a person to type that figure back. Nothing is bought until then.

**話す英文**
> One page shows the price — forty-nine point seven nine yen — and waits for a person to type that figure back. [間 1 秒] Until then, nothing is bought.

**日本語の意味**
> 一つの画面が値段——49.79 円——を示し、人がその数字を打ち返すまで待ちます。それまでは何も買いません。

語数 25 · 目安 11 秒 · 余白 4 秒。「forty-nine point seven nine yen」は画面の数字と同時に。
打ち返す操作の絵が終わってから「Until then, nothing is bought」。

### 7 · 1:20 · 30 秒 · RAW＋判定（小さなコピー 4 本を順に、各 7.5 秒。判定文とスコアを重ねる）

**画面の英文（字幕）**
> **Gemini 2.5 Flash judges every window**: is the rider in frame, is the bike stopped, what is worth looking at. 337 structured judgements. **Only 43 scored 0.7 or more.**

**話す英文**
> Gemini two point five Flash judges every window: is the rider in frame, is the bike stopped, what is worth looking at. [間 3 秒] Three hundred and thirty-seven structured judgements came back. Only forty-three scored point seven or more. [間 3 秒] Most of a riding day is just road. Gemini found the minutes that aren't.

**日本語の意味**
> Gemini 2.5 Flash がすべての窓を判定します。ライダーが写っているか、バイクは止まっているか、見る価値のあるものは何か。337 件の構造化された判定が返ってきました。0.7 以上だったのは 43 窓だけ。走行日の大半はただの道路です。Gemini が、そうではない数分を見つけました。

語数 51（この台本で最長）· 目安 22 秒 · 余白 8 秒。4 本の窓に合わせて三つに割る。

| 窓 | 秒 | 話す部分 |
|---|---|---|
| 1 本目 | 0 – 7.5 | 「Gemini two point five Flash … looking at.」（1 本目に少しはみ出してよい） |
| 2 本目 | 7.5 – 15 | 終わりまで黙る。判定文とスコアを読ませる |
| 3 本目 | 15 – 22.5 | 「Three hundred and thirty-seven … or more.」 |
| 4 本目 | 22.5 – 30 | 「Most of a riding day … that aren't.」 |

「Only forty-three」を区間で一番強く。読み方: 0.7 は「point seven」。

### 8 · 1:50 · 15 秒 · Console（数値カード：337 windows · 245.1 MB · ¥49.79 · 63 beats · 380 s）

**画面の英文（字幕）**
> The story planner keeps **63 beats in the order the day happened**; ffmpeg cuts the film and adds the music. **About 80 minutes of machine time. Two confirmations from a person.**

**話す英文**
> The planner keeps sixty-three beats in the order the day happened; ffmpeg cuts the film, adds the music. [間 1 秒] The whole edit: about eighty minutes of machine time, two confirmations from a person.

**日本語の意味**
> プランナーが 63 ビートを、その日に起きた順のまま保ちます。ffmpeg が映画を切り、音楽を付けます。編集作業の全部で、機械時間およそ 80 分、人の確認は 2 回。

語数 32 · 目安 14 秒 · 余白 1 秒。「The whole edit」の後で一拍置き、数字を二つ並べて終える。
これがデモの主張の芯（4 時間 43 分の録画を見るだけで 4 時間 43 分、に対する約 80 分）なので、
早口にしない。前半を少し速めて後半に時間を残す。

### 9 · 2:05 · 40 秒 · 成果物（作品の連続 40 秒：章カード → 走行 → 下部テロップ → 立ち寄り）

**画面の英文（字幕）**
> The result: **six minutes**, chapters named by place, a map in the corner, sections for scenic roads and stops.

**話す英文**
> The result. Six minutes of film. [間 4 秒] Chapters, each named by place. [間 4 秒] A map in the corner, following the ride. [間 4 秒] Sections for the scenic roads, and for the stops. [間 5 秒] Every scene here was chosen from the GPS track and Gemini's judgements. Nobody scrubbed through four hours forty-three to find them.

**日本語の意味**
> 結果です。6 分の映画。章にはそれぞれ地名が付きます。隅の地図が走行を追います。景色の良い道と立ち寄りには、それぞれのセクション。ここにあるシーンはすべて、GPS の軌跡と Gemini の判定から選ばれたものです。4 時間 43 分を人が探し回ってはいません。

語数 49 · 目安 21 秒 · 余白 19 秒。この区間は絵が主役。話すのは 40 秒のうち半分だけで、
文と文の間を大きく空ける。目安の時間割（区間の開始からの秒）。

| 秒 | 絵（想定） | 話す部分 |
|---|---|---|
| 0 – 3 | 章カード | 「The result. Six minutes of film.」 |
| 7 – 9 | 章カード → 走行へ | 「Chapters, each named by place.」 |
| 13 – 16 | 走行、隅の地図 | 「A map in the corner, following the ride.」 |
| 20 – 23 | 下部テロップ（景色の良い道） | 「Sections for the scenic roads, and for the stops.」 |
| 28 – 38 | 立ち寄り | 「Every scene here … to find them.」 |
| 38 – 40 | | 黙る。作品の音を聞かせる |

英語版の作品ができて 40 秒の場所が決まったら、この時間割を実際の絵に合わせて直す
（シナリオ v2「決めていただくこと 3」）。文の順は変えない。

### 10 · 2:45 · 12 秒 · Console（締めのカード）

**画面の英文（字幕）**
> **Open source (AGPL-3.0). Runs on your machine. About ¥50 of Gemini per riding day.** Judges: the day-7 package cuts this film on your own computer.

**話す英文**
> Open source. Runs on your machine, about fifty yen of Gemini a riding day. [間 1 秒] The day-seven package cuts this film on yours.

**日本語の意味**
> オープンソース。あなたの機械で動き、Gemini 代は走行一日あたり約 50 円。day 7 のパッケージは、この映画をあなたの機械で切り出します。

語数 22 · 目安 10 秒 · **声は 11 秒までに終える**（絵は 12 秒。声が絵より 1 秒早く終わる。
下の「アセンブラの受け方」）。ライセンス名（AGPL-3.0）は札に任せて話さない。11 秒に
収めるため。「on yours」で止め、余韻は絵に渡す。

---

## 語数のまとめ

| 区間 | 秒 | 語数 | 目安秒（÷2.3） | 余白 |
|---|---|---|---|---|
| 1 | 8 | 14 | 6 | 2 |
| 2 | 12 | 23 | 10 | 2 |
| 3 | 12 | 23 | 10 | 2 |
| 4 | 15 | 26 | 11 | 4 |
| 5 | 18 | 36 | 16 | 2 |
| 6 | 15 | 25 | 11 | 4 |
| 7 | 30 | 51 | 22 | 8 |
| 8 | 15 | 32 | 14 | 1 |
| 9 | 40 | 49 | 21 | 19 |
| 10 | 12（声は 11） | 22 | 10 | 1 |
| **計** | **177** | **301** | **131** | **45** |

区間 5・8 は目安が区間の長さに近い。録ってみて溢れるなら、5 は「in all」、8 は「The whole edit:」
を落とす（意味は変わらない）。他の区間は削らなくてよい。

---

## 録音の注意

### ペースと声

- **約 2.3 語/秒**。ニュースの読みより遅く、友人に説明するくらい。数字（three hundred and
  thirty-seven、forty-nine point seven nine）は特にゆっくり。数字は字幕にも出ているので、
  聞き取れなくても伝わるが、急ぐと安く聞こえる。
- 感情は入れすぎない。区間 2・3（困っていたこと）は淡々と、区間 4 で少し明るく、区間 8 の
  数字と区間 10 の締めをはっきり。形容詞で盛らない（v2 の方針: 「革命的」より対比の数字）。
- 台本の英文は口語なので、読みにくい語は自分の言い方に直してよい。ただし **数字と、字幕と
  食い違う言い換え** はしない（例: 「nothing leaves the machine」とは言わない。出るのは
  小さなコピーで、出ないのは 4K）。

### 息を置く場所（絵に呼吸させる）

- 区間 3 の後半（何も起きない絵をわざと見せる）
- 区間 7 の 2 本目の窓（判定文とスコアを読ませる。ここで黙るのが「モデルが何を見て何と
  言ったか」を見せる一番の場面）と 4 本目の後
- 区間 9 の文と文の間（4〜5 秒ずつ。上の時間割）
- 区間 10 の最後の 1 秒（声が終わってから絵が終わる）

### 一続きか、区間ごとか

**区間ごとに 10 本、を勧める。** アセンブラは各区間の開始位置に音声を置くので、一続きの
1 本を後で切るより最初から区間ごとに録ったほうが、位置が狂わず、言い直しも 1 区間だけで済む。
一続きで録ってしまった場合は、区間の頭で切って下のファイル名で保存する（区間の間の無音は
ファイルに含めない）。

各ファイルは頭と尻の無音を **0.2 秒以内** に切りそろえる。アセンブラは無音を詰めないので、
先頭に長い無音があると、その分だけ声が遅れて出る。区間の中での「間」（[間 3 秒]）は
ファイルの中に無音として残す。それが絵と合う位置になる。

### 形式とファイル名

- **48 kHz・モノラル・PCM WAV**（16 bit。24 bit でもよい）。圧縮形式（m4a、mp3）にしない。
- ピークは −3 dBFS を超えない。ラウドネスは −16〜−18 LUFS くらい（アセンブラが音楽を下げて
  声を通すので、無理に大きく録らない）。
- 静かな部屋、同じマイク、同じ距離で 10 本を続けて録る。1 本だけ別の日に録り直すと音が
  変わって分かる。録り直すなら前後の区間も一緒に。
- ファイル名は **`narration-01.wav` … `narration-10.wav`**（区間番号を 2 桁で）。
- 置き場所はパッケージのデモ用ディレクトリの下、たとえば
  `private-media/work/<package>/demo/narration/`。`private-media/` は git 管理外なので
  声がリポジトリに入ることはない。リポジトリには入れない。

### アセンブラの受け方（将来の `--narration`、未実装）

`app/submission/demo_assembly.py` にはまだ音声の入口がない。作るときの仕様をここに置く。
台本のほうが先に決まっていれば、実装はこれに合わせるだけでよい。

- `python -m app.submission.demo_assembly <package> --narration <dir>` で、`<dir>` の
  `narration-NN.wav` を **区間 N の開始位置** に置く。ないファイルの区間は字幕のみ（今と同じ）。
- 音声は **伸縮しない**。ファイルが区間より長ければ、そのファイル名と超過秒数を挙げて **拒否**
  する（黙って切らない）。区間 10 は特別で、**11.0 秒より長ければ拒否**。締めのカードは
  12 秒だが、声が絵より 1 秒早く終わり、最後の 1 秒はカードだけが残る。
- 声が鳴っている間は作品の音楽を下げる（ダッキング）。声の前後 0.3 秒ほどで滑らかに戻す。
  区間 9 は声の合間に音楽が戻るので、間の長さがそのまま音楽の聞こえる長さになる。
- 出力は 48 kHz に統一（今の scored film の音声と揃える）。
- 字幕（.srt）は変えない。字幕は画面の英文、声はこの台本、の二重で要件を満たす。
- 検査: 10 本の合計が 131 秒前後（目安）から大きく外れていれば、ペースが違うので録り直しを
  勧める表示を出す。強制はしない。

### 録る前に決めておくこと

シナリオ v2 の「決めていただくこと」のうち、この台本に関わるもの。

1. **ナレーションを入れるか**（v2 の 5）。入れないなら、この台本は使わない。
2. **区間 9 の 40 秒の場所**（v2 の 3）。決まってから区間 9 の時間割を直し、その後で録る。
3. **最後の 10 秒を全画面にするか**（v2 の 2）。台本は変わらない。
