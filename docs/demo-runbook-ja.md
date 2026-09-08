# 実機確認の手順（別日のクリップを1本の作品にする）

作成日: 2026-09-03

新しい日のGPXと動画から作品を作るまでの手順。**人が判断するのは1箇所だけ**
（カメラとGPSの時計のズレ）で、それ以外はすべてシステムが決める。

所要時間の目安（実測、1回のツーリング分）: 素材の棚卸しと候補抽出が最も長く、
5分の作品のレンダーが約5分、音楽付けが約1分。

## 0. 素材を置く

```
private-media/input/<任意の名前>/     ← 動画（.mp4 と .lrv）とGPXをここへ
```

`private-media/` はGit管理外。素材も生成物も外部へ送らない。


## 0.5 画面から行う場合（推奨）

手順1〜3・2.5〜2.7はすべて `/private-journey` から行える。

**いちばん簡単な起動**: Finder で `scripts/open-console.command` をダブルクリックする。
コンソールが動いていなければ起動し（ログは `.autonomy/console.log`）、ブラウザで
`http://127.0.0.1:8765/private-journey` を開く。作品は画面の「作品の構成」で再生でき、
その下にファイルの場所（QuickTime で開くときのパス）と、無音版か音楽版かが表示される。

手で起動する場合:

```bash
RIDE_PRIVATE_JOURNEY_PACKAGE_DIRECTORY=private-media/work/<既存package> \
  .venv/bin/python -m app.web.server
```

ブラウザで `http://localhost:8765/private-journey` を開く。

1. 画面下部「別の日のクリップを取り込む」に、`private-media/input/` からの相対パスで
   GPXと動画フォルダを入力 → 「時計のズレを提案させる」
2. 提案（時間・旅の中の本数・曖昧さの有無）を見て、**提案どおりの数字**で
   「この数字でこの日を取り込む」（提案に無い数字は拒否される）
3. 画面が取り込んだ日へ切り替わる。「次の操作」に従う:
   縮小コピーを作る（無料）→ **表示された金額を入力して**承認して判定させる（課金）
   → 作品を生成する（無料）
4. 上部の「見ている日」で、取り込み済みの別の日へ切り替えられる

パスは `private-media/input` 配下しか読まない。判定は表示された金額を円の小数2桁まで
一致させて入力しないと始まらない。

## 1. 時計のズレを提案させる（**人が確認する唯一の点**）

```bash
.venv/bin/python -m app.clock_offset <ride.gpx> <動画ディレクトリ>
```

出力例（実素材で検証済み）:

```json
{
  "is_unambiguous": true,
  "proposed": {
    "offset_s": -46800, "offset_hours": -13.0,
    "recordings_inside": 14, "recordings_total": 49, "recordings_clipped": 0,
    "covered_ratio": 0.24, "lead_in_s": 581.0, "lead_out_s": 1019.5
  },
  "runners_up": [ ... ]
}
```

**見るべき点**

- `is_unambiguous` が `true` なら、その`offset_s`を採用してよい。
- `false` の場合は候補が拮抗している。`runners_up`と見比べて人が決める。
  （システムは「一番マシな数字」を押し付けない。ここが人の判断が要る唯一の場面。）
- `recordings_inside` が0でエラーになる場合、GPXと動画が**別の日**の可能性が高い。

このコマンドは動画のメタデータとGPXしか読まない。画素は復号せず、ネットワークも使わない。

## 2. packageを作る

```bash
.venv/bin/python -m app.local_pipeline \
  <ride.gpx> <動画ディレクトリ> \
  --output private-media/work/<新しい名前> \
  --clock-offset-s <手順1で確認した数字> \
  --clock-offset-confirmed \
  --target-duration-s 300
```

GPXと動画ディレクトリは**位置引数**（フラグ名は付けない）。`--clock-offset-confirmed`
を付けない限り、時計のズレは未確認として扱われ、先へ進めない。

ここでカタログ化、イベント検出、候補の時刻照合、確認用クリップの抽出までが走る。

## 2.5 Geminiに何を尋ねるかを決める（**送信なし・無料**）

この製品の核心は、**Geminiが実素材を見て、どの区間を使うかを決めること**。
その前に、何を送りいくら掛かるかを自分の目で見る。

```bash
.venv/bin/python -m app.analysis_cli plan <package>
```

実素材での出力（1回のツーリング分）:

```json
{
  "candidate_count": 173,
  "watched_count": 173,
  "upload_megabytes": 95.1,
  "cost": { "total_jpy": 25.56, "budget_jpy": 500.0, "within_budget": true }
}
```

**見るべき点**

- `candidate_count` は映像から数えた窓の数。GPSイベントの数ではない
  （実rideではGPSイベント基準だと7本しか無く、撮った映像の大半が捨てられていた）。
- `watched_count` が `candidate_count` より少なければ、**予算が効いて絞られている**。
  絞る場合はride全体に等間隔で散らすので、旅の前半だけになることはない。
- `upload_megabytes` は縮小コピーの合計。**元の4K素材（実測68.1 GiB）は送らない。**
- 予算は `--budget-jpy` で下げられる。既定は¥500。

このコマンドは動画を開かず、ネットワークも使わない。

## 2.6 送るものを実際に作って測る（**送信なし・無料**）

```bash
.venv/bin/python -m app.analysis_cli preflight <package>
```

全候補の縮小コピーをローカルで作る。**課金の前に、素材側で詰まらないことを確かめる。**

実素材での結果: 173本中173本成功・失敗0・実測95.0 MB・所要14分。

```json
"preflight": { "prepared_count": 173, "measured_megabytes": 95.0,
               "measured_share_of_estimate": 0.999, "ready": true, "failures": {} }
```

`ready` が `false` なら `failures` に理由コードが出る
（`source_missing` / `copy_failed` / `copy_empty` / `unknown_asset`）。
**1本目で止まらず全部試すので、どれだけ壊れているかが一度で分かる。**

作ったコピーは `<package>/analysis-proxies/` に残り、次の手順がそれを使う。

## 2.7 Geminiに判定させる（**課金する。承認が要る**）

```bash
.venv/bin/python -m app.analysis_cli judge <package> \
  --bucket <GCSバケット> --i-approve-spending
```

`--i-approve-spending` を付けない限り、**アップロードは始まらない**。
手順2.5の金額に納得してから付ける。

判定結果は `<package>/gemini-video-analysis.json` に保存され、
**2回目以降は読み直すだけで買い直さない**（`--overwrite` で再購入）。

**途中で失敗しても、買った分は失われない。** 173本の判定は173回の課金呼び出しで、
150本目で通信が切れれば149本分を捨てることになる——それを避けるため、判定は
1本ごとに `gemini-video-analysis.partial.json` へ書かれる。同じコマンドを
もう一度実行すれば、**持っていない分だけを尋ねる**。

出力の `carried_from_earlier_attempt` が買い直さずに済んだ本数、
`newly_bought` が今回新しく買った本数。完全な記録が書かれた時点で
partialファイルは消える。

## 3. 作品を作る

```bash
.venv/bin/python -m app.private_journey_film <package> --music rising-tide
```

Gate 1の健全性検証 → 物語計画 → 章カード描画 → 連結レンダー → 字幕 → 音楽、まで一気に走る。

**手順2.7を済ませていれば、Geminiの判定が採用区間を決める。** 済ませていなければ、
確認済みclipから組む従来の経路になる（判定があるpackageは candidate export を開かない）。

**時間がかかるので、途中で止めないこと。** 止めても壊れた作品は残らない
（出力は完成後に原子的に置き換えられる）が、レンダーは最初からやり直しになる。

### 曲を変えたいとき

絵は変わらないので、**5分の再エンコードは不要**。

```bash
.venv/bin/python -m app.private_journey_film <package> \
  --music <track_id> --music-only --overwrite
```

選べる曲は `private-media/music/music-catalogue.json`。全曲CC BY 4.0。
`wholesome` / `enchanted-valley` / `windswept` / `rising-tide` / `lightless-dawn`。

## 4. できるもの

`<package>/` の中に:

| ファイル | 中身 |
|---|---|
| `ride-storyteller-story-film.mp4` | **作品（無音版）**。音楽を付けていなければこれを観る |
| `ride-storyteller-story-film-scored.mp4` | 音楽入りの版（`--music` を付けたときだけ作られる） |
| `ride-storyteller-story-film.srt` / `.vtt` | 字幕 |
| `journey-story-plan.json` | 作品の構成（beat順・尺・章テキスト） |
| `story-cards/` | 章カードのHTMLとPNG |

## 5. 見て確認したいこと

- **出発の章カードで始まり、到着の章カードで終わっているか。**
  映像のない区間が、存在しない映像で埋められず章テキストと地図で表現されているか。
- 章カードの数字（時間・距離・標高差）が、その区間の実際と合っているか。
- 地図の強調区間が、旅の中で妥当な位置にあるか。
- 音楽が作品の終わりでフェードアウトして終わるか。

## 6. うまくいかないとき

| 症状 | 原因と対処 |
|---|---|
| `no whole- or half-hour shift places any recording wholly inside this ride` | GPXと動画が別の日。組み合わせを確認する |
| `the package is not ready to render: evidence_awaiting_present` | 証拠判定が未確定。`evidence-review.json` を確認 |
| `insufficient_confirmed_duration` | 章カードを足しても目標尺に届かない。素材が少ないか目標尺が長すぎる |
| `no GPS events have local timestamp-matched video coverage: N events and M recordings, none overlapping` | 手順1の数字が違うか、GPXと動画が別の日。まず`app.clock_offset`を再実行する |
| `no confirmed clip is available for the film` | 時刻照合で1本も一致しなかった。手順1の数字を疑う |
| `this package has no footage inside the ride to judge` | 手順1の数字が違う。撮影が旅の外に落ちている |
| `judging uploads footage and bills for it` | 手順2.7で`--i-approve-spending`を付けていない（想定どおりの拒否） |
| `this package already carries a judgement` | 判定済み。買い直すなら`--overwrite` |
| 章カードの日本語が □ になる | Linux環境でCJKフォント未導入（macOSでは起きない） |

## 7. 検証済みの範囲

- 手順1は**実素材で検証済み**。既知の答え（−46,800秒）を49本の録画から曖昧さなく再現した。
- 手順3・4は**実素材で検証済み**。300.03秒・15 beat・字幕8cue・音楽入りの作品を生成した。
- 手順2はこれまでの実素材packageの生成に使われている経路そのもの。合成素材での予行では、
  引数解釈が正しいことと、一致0件のときのメッセージが原因を示すことを確認した。
- 手順2.5・2.6は**実素材で検証済み**。173候補・95.1 MB・¥25.56を出し、
  preflightは173本すべてを作って実測95.0 MB（見積りとの比 0.999）。失敗0。
- 手順2.7は**未実行**。承認待ち。承認なしでは拒否されることを確認済み。

## 8. この手順が守っていること

- **実素材は端末から出ない。** 外部送信・クラウド送信・公開はしない。
- **人の確認は時計のズレ1点のみ。** それ以外は証拠に基づいて自動で決まる。
- **証拠のない映像は使わない。** 未確認のeventを指すbeatがあればレンダーは止まる。
  「完成しているように見える短い作品」を黙って作らない。
- **存在しない映像で穴を埋めない。** 撮影していない区間は、GPSが証明する事実
  （時間・距離・標高差）だけを書いた章カードになる。

## 9. 3分デモを部品から組み立てる（録画の代わり）

完成作品のある package から、台本どおりのカード・章カード・IBM Bob 画像・実素材の抜粋を
繋いだ `demo/demo-en.mp4`（180秒・1080p）と字幕 SRT を作る。**公開はしない。**

```bash
.venv/bin/python -m app.submission.demo_assembly private-media/work/<package> \
  --excerpt-start-s 20.4 --overwrite
```

（2026-09-05 Q5 以降、デモは作品の 5 区間にテロップを重ねる構成で、`--excerpt-duration-s` は無い。
`--excerpt-start-s` は 5 区間の起点。）

- カードは章カードと同じ HTML→PNG 経路。文言は件数・容量・金額・作品の言葉だけ
- 抜粋は作品の指定秒から。**公開前に判読可能なナンバープレート・識別可能な顔が無いか目視する**
- 字幕は焼き込めないので SRT を隣に置く（YouTube は別ファイルで受け付ける）

## 10. 地図背景の切替（E-10）

経路図（章カード・見出し・締め・左上の現在位置）の背景は 3 通り。既定は `labels`（オーナー決定 2026-09-05）。左上の小窓は配色に関係なく文字なしの地図。

```bash
.venv/bin/python -m app.private_journey_film private-media/work/<package> --overwrite --map-style labels
.venv/bin/python -m app.private_journey_film private-media/work/<package> --overwrite --map-style plain \
  --output-file-name ride-storyteller-story-film-plain.mp4
.venv/bin/python -m app.private_journey_film private-media/work/<package> --overwrite --map-style none
```

- `labels`: 暗い配色の地図、町の名前あり（道路名・POI は非表示）
- `plain`: 同じ配色で文字なし
- `none`: 従来の黒地
- 環境変数 `RIDE_MAP_STYLE` でも指定できる。鍵が無い／API が拒否したときは自動で `none` になり、
  結果 JSON の `map_background` に出る。Google へ送るのは走行範囲の中心座標とズームだけ
  （[`data-flows-ja.md`](data-flows-ja.md)）。地図画像は `<package>/map-background/` にキャッシュされ、
  同じ範囲・配色なら再取得しない。
- **章題の地名**（2026-09-06〜）: 行程の両端を Google の Geocoding API に問い、章題を「A → B」にする。
  同じ鍵の「API の制限」に **Geocoding API** を加えておく。送るのは端点の座標（小数 4 桁）だけ。
  結果は `<package>/place-names.json` にキャッシュ。`RIDE_PLACE_NAMES=none` で問わない（地形の語の題に戻る）。
  `RIDE_PLACE_LANGUAGE` で答えの言語を選ぶ（既定は作品の言語。海外の旅は `en` にしないと有名な町だけ
  カタカナになって混ざる。`scripts/trip/process-day.sh` は `en` を既定にしている）。
- **参照ファイル（2026-09-07〜）**: `private-media/reference/touring-routes/*.json`（公式シーニックルート）と
  `private-media/reference/highways/*.json`（主要道路網）。形式は `touring-routes-v1`（`routes[].name`、`lines[][lat,lon]`）。
  OpenStreetMap の route relation から Overpass で取得して保存する（git には入れない）。無ければ作品は
  その節と章を持たないだけで止まらない。`RIDE_TOURING_ROUTES=<file>` で 1 ファイルを指定できる。
- **判定の買い直し（2026-09-07〜）**: `python -m app.analysis_cli judge <pkg> --overwrite --refresh-top 40 ...` は
  完成記録を引き継ぎつつ、点数上位 40 窓だけを買い直す（モデルに増えた質問——写真らしさ・停車・道路上の出来事——に
  答えさせる）。定点の候補窓（各定点 3〜5 窓）も同じ実行で不足分だけ買う。
- **現地時刻と日数（2026-09-07〜）**: 節の文の頭に現地時刻。カメラの時計が現地時間ならその時計ずれから
  推定し、`RIDE_LOCAL_UTC_OFFSET=+13:00` で上書きできる。同じ `work/` に GPX の日付が連続する package があれば
  複数日の旅とみなし、全画面カードに「Day N」を出す（単日なら出ない）。
