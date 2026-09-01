# ローカルE2E準備パイプライン

## 目的

実GPXと実動画をMac内だけで結び、映像証拠を人が確認できる短いレビュー
クリップまで作る。Google、Gemini、Box、Maps、Cloud Runへ素材を送らない。

```text
GPX解析
  -> GPSイベント抽出・集約
  -> ローカル動画メタデータ取得
  -> 確認済みカメラ時計補正
  -> 映像区間が存在するGPSイベントの選定
  -> Story Plan
  -> GPS時刻と動画区間の最終照合
  -> 720pレビュークリップ
  -> 人手の映像証拠確認で停止
```

これは最終動画の完成処理ではない。未確認の映像を自動採用せず、Geminiへの
実動画送信も行わない。

GPS timestamp coverageだけの候補が直線・停車を含む場合は、先に
`app.video.highlight_research`を実行する。連続速度、中央GPS曲率、GoPro GPMF、
ローカルApple Vision、Feature Print重複除外を通過した8本×4方式を比較し、
その後も人手確認で停止する。FFmpegとGPMFの派生数値は同じprivate出力配下の
`metric-cache/`にだけ再利用するため、変更のないMP4をしきい値調整ごとに再走査しない。
interest gateは明確な旋回だけを通すstrong-turn laneと、scene変化・motion変動だけを
使うtemporal visual-event laneに分かれる。後者は交差点・車両・景観を意味的に認識したと
断定せず、候補理由として人手reviewへ渡すだけである。
詳細は`docs/highlight-selection-experiments.md`を参照。

現状、`app.local_pipeline`のevent起点候補と`app.video.highlight_research`の
映像起点候補は別packageを生成し、自動統合されない。ハイライト研究結果を
Story Plan、candidate edit、`evidence-review.json`へ接続することは、アプリ全体
再設計の主要課題である。

## 2026-08-30 現在の実素材状態

- 14物理MP4を10論理録画としてcatalog化した。
- GoPro後続chapter 4本は、先行chapterのduration累積で開始時刻を補正した。
- 確認済みcamera-to-GPS補正は−46,800秒（−13時間）。
- 実映像は約85分、対象時間幅は約224分、coverageは約38%。映像がない区間を
  推測で補わない。
- LRVはないため、MP4原本を1fps／幅320pxへ早期縮小してローカル解析した。
- 14本すべてからGoPro GPMFのGYRO／ACCLを取得できた。GoPro GPS時刻値は無効で、
  位置・速度の正本には外部GPXだけを使う。
- 技術E2Eは成功したが、候補品質は`PARTIAL`。推奨8本と映像証拠は未承認。

## 前提

- `ffmpeg`と`ffprobe`がMacにインストールされていること。
- Apple Visionを使うハイライト研究はmacOSネイティブ権限で実行すること。
  制限されたprocess sandboxでは正常なJPEGでもpixel buffer作成に失敗する場合がある。
- 12秒clip／12秒の採用候補間隔に対し、研究の既定survey strideは6秒である。全strict候補へ
  Vision品質評価を行うが、Feature Print距離は各方式の上位96候補の和集合（最大384件）だけで
  計算する。全候補の総当たり距離計算は候補数の二乗で増えるため行わない。
- GPXと動画フォルダをCodexまたは実行中のターミナルが読み取れること。
- カメラ時刻に加えるとGPS時刻になる補正秒数を、ローカルで確認済みであること。
- 出力先は公開リポジトリ外、またはリポジトリ内の`private-media/`、
  `data/private/`、`media/private/`配下であること。

## 実行

```bash
python -m app.local_pipeline \
  "/path/to/private.gpx" \
  "/path/to/private-videos" \
  --output "/path/to/private-output" \
  --clock-offset-s 0 \
  --clock-offset-confirmed \
  --target-duration-s 300 \
  --language ja
```

`--clock-offset-confirmed`がなければ、動画を1本もプローブせず停止する。
`--clock-offset-s`には推測値を入れない。既存出力は`--overwrite`を明示した場合
だけ更新する。

イベント選定は映像内容を評価しない。補正後のevent時刻を含む動画区間がある
イベントだけを対象とし、まず利用可能な種類ごとにimportanceが最も高い1件を
選び、目標尺に達するまで残りをimportance順に追加する。出力順は走行時刻順。
該当イベントが0件ならfail closedで停止し、視覚的に適切とは判定しない。

## 私用出力

- `local-video-catalog.json`：開始時刻・尺・asset IDと時計補正。
- `ride-storyteller-candidates.json`／`.csv`：GPS時刻に対応する候補区間。
- `review-clips/review-NNN.mp4`：FFmpegで作る720p確認用プロキシ。
- `review-clip-manifest.json`：event ID、asset ID、確認用ファイル名の対応。
- `evidence-review.json`：各候補の人手確認状態。初期値はすべて証拠待ち。
- `local-pipeline-summary.json`：座標・絶対パスを含まない集計と次のgate。`--director-mode`
  でDirectorが実行された場合も、ここにはcomposer、fallback有無、scene role、clip件数、
  transition、overlayだけの安全な`director.director_script`要約を含める。event ID、asset ID、
  ファイル名、映像区間、座標は含めない。完全な`local-director-script.json`は私用出力内だけに
  保存され、private DirectorScript previewが読む。
- `metric-cache/`：FFmpeg／GPMFの派生数値cache。source path、ファイル名、撮影時刻、
  座標、frameは保存しない。source fingerprintが変わったentry、schema不一致、破損entryは
  ローカル再解析する。
- `highlight-review.json`：ハイライト研究候補の採用／却下判断用template。opaque candidate ID、
  方式、rank、固定理由codeだけを保存する。実ファイル識別子や自由記述は保存しない。

MP4とMOVをソース候補とする。LRVは棚卸し件数には残すが、GoProの同一撮影
プロキシを別素材として二重登録しないため時刻カタログから除外する。GoPro
chapterは同一directory／camera family／recording IDで論理録画化し、完全な
連番だけを累積durationで補正する。欠番・時刻不一致・開始時刻取得不能・probe
失敗は、絶対pathを含まないissue codeとして残す。

## 映像証拠確認とローカル描画

レビュークリップの生成後は`human_visual_evidence_review`で停止する。
`evidence-review.json`で、確認した候補だけを`confirmed`、不適切な候補を
`rejected`とし、決定済み項目には`human_review`等の空でない
`evidence_source`を記録する。未照合クリップを`confirmed`にはできない。

`--overwrite`を付けてpipelineを再実行しても、既存の`evidence-review.json`は初期化
しない。catalogやreview proxyは再生成できるが、人手のdecisionは別の安全gateである。
再生成後の候補event集合とreviewの集合が一致しない場合は、古いdecisionを黙って流用・
破棄せず`ValueError`で停止する。reviewのdecisionはfresh `CandidateClip`へ明示的に
反映され、`confirmed`だけが任意のDirector pipeline入力になれる。

`RIDE_PRIVATE_EVIDENCE_REVIEW_DIRECTORY`へprivate output directoryを明示設定すると、
loopback serverの`/private-evidence-review`で確認用クリップを見ながら、1件ずつ
`confirmed`、`rejected`、`awaiting_video_evidence`を保存できる。ブラウザにはopaque review IDと
server-owned media URLだけを返し、event ID、asset ID、ファイル名、区間、座標、pathは返さない。
決定元は固定の`human_local_review`であり、ハイライト品質reviewのapproved/rejectedとは別の
映像証拠判断として保持する。public demo modeでは画面・API・media配信をすべて拒否する。
`evidence-review.json`の保存は同一directory内の一時ファイルから置換する。保存途中の失敗では
既存の人手判断を残し、一時ファイルを除去する。
画面にはdecision状態から導く次のローカルgateも表示する。`rejected`が1件でもあれば差し替え、
未判断があれば映像証拠確認を続ける。全件confirmedでも、Directorやrenderを自動開始せず、
既存のlocal pipelineで候補・時刻対応を再検証してから進める。

`local-pipeline-summary.json`の`next_gate`は、常にrender可能とは示さない。未確認なら
`human_visual_evidence_review`、却下済みなら`replace_rejected_candidate_clips`、候補尺不足なら
`add_timestamp_matched_candidates`、全候補確認後でDirector未実行なら`run_offline_director`、
DirectorScript作成済みかつedit-readyなら`render_director_script`となる。

Director pipelineは既定でローカルの`RuleBasedDirector`を使う。Gemini transportを
渡しただけでは実行せず、`allow_external_director=True`を明示しない限り停止する。
これは実素材由来のevent情報を外部Geminiへ送らないためのgateであり、明示許可があっても
座標、source asset ID、ファイル名、path、source intervalはpayloadから除外する。

Director pipelineがGPS event、resolved clip、candidate clipを結合する前に、各入力集合の
`event_id`一意性を確認する。同じIDが一つの集合に複数ある場合は、後の値でevidenceや
source identityを上書きせず、Director・artifact作成・FFmpeg計画の前に停止する。
Director script artifactはsource identityを含むため、repository内へ書く場合はignoredな
private出力directoryだけを許可する。

DirectorScriptのbrowser-safe summaryには、確認済みevidenceに出発と到着が両方あるか、片方だけか、
旅の途中だけかを示す`journey_coverage`を含める。これはevent typeからの事実ラベルであり、
未確認の出発・到着を物語上の事実として補わない。古いprivate artifactにこのfieldがない場合も、
安全側に「旅の途中だけ」として扱う。

人手確認後のローカルE2Eで、外部通信なしに物語構成を作る場合は、同じ私用出力directoryへ
`--overwrite --director-mode`を付けて再実行する。`--director-mode`はconfirmed eventだけを
RuleBasedDirectorへ渡し、Geminiを設定・呼出ししない。confirmed eventが0件ならDirectorは
起動せず、既存のevidence-review gateのまま停止する。

Gemini Directorの応答は、未知event、未確認event、同一eventの重複だけでなく、同一の
物語役割を複数回使う構成、または`Hook → Build-up → Climax → Resolution`の表示順を
逆転する構成も拒否する。不正応答時は外部結果を採用せず、呼出し側が
`RuleBasedDirector` fallbackを使う。

Web UI用のDirectorScript要約は、役割、scene内のclip数、transition、overlay textだけを
返す専用viewで生成する。event ID、asset ID、ファイル名、source interval、座標、pathは
Editorだけがprivate artifactから扱い、browser responseには含めない。

ローカルDirector pipelineがprivateな`local-director-script.json`を生成した後は、
`RIDE_PRIVATE_DIRECTOR_SCRIPT_PATH`へそのファイルだけを明示設定し、loopback serverの
`/private-director-preview`で物語構成を確認できる。これは読み取り専用で、role、clip数、
transition、overlay text以外を返さない。public demo modeでは画面・APIとも403になる。

すべての候補が時刻照合済みかつ確認済みになった後だけ、無音のローカル
ドラフト動画を作成できる。

```bash
python -m app.local_render "/path/to/private-output"
```

DirectorScriptの物語順でrenderするには、private artifactのpathを明示して渡す。artifactは
schema・scene順・source identityを検証し、既存のevidence allow-listをScriptExecutorで再検査する。
異常なartifact、未確認証拠、source不一致ではFFmpeg実行前に停止する。
artifactは同じprivate package directory内の`local-director-script.json`だけを受け付け、別packageの
古いscriptを流用しない。

現時点のDirectorScript contractとdeterministic local renderは`cut`だけを扱う。Gemini response、
private artifact、previewのいずれでも`fade`など未実装transitionを拒否し、FFmpegを起動しない。
transitionの追加は、物語順と証拠gateを保ったまま別工程で行う。

```bash
python -m app.local_render "/path/to/private-output" \
  --director-script "/path/to/private-output/local-director-script.json"
```

未確認、却下、時刻不一致、レビュークリップ不足、既存出力がある場合は
FFmpeg実行前に停止する。現在の出力は720p確認素材を結合した無音ドラフトで、
著作権フリー音楽の選定・帰属・音量調整は次工程とする。

## ハイライトreview UI

`RIDE_PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY`に、`highlight-review.json`、
`review-thumbnails/`、各方式の`clip-NN.mp4`を含むprivate研究出力directoryを明示設定する。
loopback-only local serverの`/private-highlight-review`で、候補ごとのthumbnail／動画を確認し、
fixed reason code付きで採用・却下・未判断へ戻すことができる。ブラウザへ返すのはopaque candidate
ID、方式、rank、固定status／reason、server-owned media URLだけである。source path、ファイル名、
時間、座標、frame、自由記述は返さない。public demo modeでは画面・API・media配信がすべて403になる。
`判断を保存`は選択した1候補だけを保存し、他候補のカードを再描画しない。したがって、他カードで
まだ保存していない選択や再生位置は保持される。選択を永続化するには、候補ごとに`判断を保存`を押す。
保存時は同じprivate directory内の一時ファイルを置換して原子的に更新する。途中で保存に失敗した場合は
既存の`highlight-review.json`を保持し、部分的なJSONで判断履歴を壊さない。

## 現在未実装の接続

- confirmed eventから、Hook / Build-up / Climax / Resolutionを持つDirectorScriptを
  Web UIで確認し、ScriptExecutorへ渡すproduct workflow。これは今後の最優先である。
- Gemini Directorを固定合成Universal EventだけでWeb経路から確認するE2E。実素材由来の
  Director入力を外部へ送るには、別の明示承認と最小化されたpayload契約が必要である。
- ハイライト研究候補からStory Plan chapterを作る統合orchestrator。private highlight reviewの
  approvedは品質labelであり、映像証拠confirmedではないため、Directorへ自動接続しない。
- 人手review labelを使うthreshold／ranking評価とStory Planへの接続。
- 地図、字幕、transition、編集リズム、著作権フリー音楽を含む最終render。
