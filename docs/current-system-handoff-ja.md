# Ride Storyteller 現行システム引継ぎ

> 更新日: 2026-09-01
> 用途: IBM Bobがアプリ全体を再設計する際の事実ベースライン
> 注意: この文書は新設計の承認書ではない。現在実装、検証結果、確定制約、
> 未決事項を分離して記録する。

## 1. プロダクトの目的

Ride Storytellerは、オートバイ旅行のGPSと長時間映像から、旅の物語に使える
短い映像候補を探し、人が確認した証拠だけで5〜10分の映像作品を組み立てる
システムである。

中核原則は次のとおり。

- GPSは「どこを確認するか」を提案するが、カメラに映った内容を断定しない。
- 映像解析結果は候補であり、人の確認前に視覚証拠を`confirmed`へしない。
- 欠落素材、時刻不一致、解析失敗、未確認、却下はfail closedで編集を止める。
- 実GPX、座標、実動画、ファイル名、撮影時刻、認証情報を公開Git、Notion、
  合成デモ、外部AIへ送らない。

## 2. 現在の到達点

### 動作確認済み

- GPX解析、ルート正規化、説明可能なGPSイベント抽出と集約。
- ルートとイベントからの決定論的Story Plan作成。
- Story Agentによる映像証拠要求、映像分析結果の採用／却下／人手確認判断。
- `awaiting_video_evidence`、`confirmed`、`rejected`の状態遷移と決定元の記録。
- 未確認映像をFFmpeg計画へ進めない証拠gate。
- 日本語／英語UIと、言語が変わっても不変な内部ID・status contract。
- 合成専用Google ADK AgentとGemini 2.5 Flashのローカル実行。
- 東京リージョンの合成専用Agent Platform Runtime。
- 東京private Cloud Runの合成専用public-demo。commit `6998221`の第5revision、
  Sourceリンク、濫用防御、private IAMを検証済み。未認証公開は未実施。
- JPY建てプロジェクト限定月額1,000円予算と通知閾値を作成・再取得済み。
  予算はhard capではない。
- ローカル実GPXと実動画の時刻照合、720pレビュークリップ生成。
- GoPro chapterを論理録画へまとめ、後続chapter開始時刻を累積durationで補正。
- LRVがない場合のMP4／MOV直接映像メトリクス解析。
- 外部GPX、GoPro GPMF IMU、FFmpeg、端末内Apple Visionを使うハイライト研究。
- 人が全候補を確認済みにした場合だけ動く無音ローカルドラフトrender。

### 2026-08-30 実素材v4a

| 項目 | 結果 |
|---|---:|
| 物理MP4 | 14 |
| 論理録画 | 10 |
| 容量 | 約26.7 GiB |
| 実映像duration | 約85分 |
| 最初から最後までの時間幅 | 約224分 |
| 映像coverage | 約38% |
| 解析した12秒窓 | 2,385 |
| 走行・非直線strict gate | 202 |
| GPMF／Vision完全証拠 | 202 |
| 最終quality gate | 21 |
| 抽出結果 | 4方式×8本＝32本 |
| 内容重複除外後 | 15本 |
| 外部送信 | 0 |
| 自動confirmed | 0 |

技術E2Eは成功した。一方、3時点ストーリーボードの目視では緩い直線寄り候補が
残ったため、候補品質は`PARTIAL`、推奨8本は未承認である。明確な旋回、合流、
交差点、周辺車両変化を持つ8本を手動レビュー用の正解例候補としてローカル生成
したが、ユーザー確認前なので証拠状態は変更していない。

## 3. 現在の主要フロー

### 3.1 合成Agentデモ

```text
固定合成GPS event
  -> Story Agent
  -> mock media search
  -> mock / structured video analysis
  -> updated story decision
  -> bilingual local UI
```

Google ADK／Agent Platformの経路も固定合成eventだけを扱う。実GPX、実動画、
任意ユーザー入力を読むtoolはない。

### 3.2 ローカル実素材準備

```text
private GPX + private video folder
  -> ffprobe metadata
  -> clock-confirmed local catalog
  -> timestamp-covered GPS events
  -> Story Plan
  -> resolved candidate intervals
  -> 720p review clips
  -> evidence-review.json
  -> human review gate
  -> silent local draft render
```

この経路は時刻対応を保証するが、映像の面白さを保証しない。

### 3.3 ローカルハイライト研究

```text
external GPX motion
  + FFmpeg visual metrics
  + GoPro GPMF gyro / acceleration
  + local Apple Vision aesthetics / context / Feature Print
  -> strict movement and interest gates
  -> four ranking strategies
  -> diversity and duplicate removal
  -> private review clips and storyboards
  -> human review
```

現状ではこの出力がStory Plan、`CandidateEditPlan`、`evidence-review.json`へ自動接続
されていない。これは全体設計で解消すべき主要な分断である。

## 4. コードの責務

| 領域 | 現在の責務 |
|---|---|
| `app/contracts` | route、event、media、video analysis、evidence decisionの不変contract |
| `app/gps` | GPX parser、event抽出、密集event集約 |
| `app/agents` | Story Agent、Story Planner、英語／日本語story copy |
| `app/video/catalog.py` | candidate intervalと動画時刻の解決 |
| `app/video/local_catalog.py` | ffprobe、時計補正、GoPro chapter論理化 |
| `app/video/highlight_discovery.py` | GPS／FFmpeg窓特徴量と初期10方式比較 |
| `app/video/gpmf_metrics.py` | GoPro IMU／camera metadataのローカル集計 |
| `app/video/apple_vision.py` | macOS Visionのローカル画質／意味／類似度解析 |
| `app/video/highlight_review.py` | 不透明候補ID・固定理由codeだけを用いるprivate人手review contract |
| `app/video/highlight_quality.py` | hard gate、4方式score、MMR多様性、評価 |
| `app/video/highlight_research.py` | 実素材研究E2Eとprivate成果物生成 |
| `app/video/metric_cache.py` | private出力内のFFmpeg／GPMF派生数値cache。source識別子を保存しない |
| `app/edit` | candidate edit、証拠状態、render plan gate |
| `app/local_pipeline.py` | private GPXからreview packageまでの統合 |
| `app/local_render.py` | 全候補confirmed後の無音ローカルrender |
| `app/web/private_evidence_review.py` | opaque IDだけで確認用clipを提示するloopback-only映像証拠確認UI |
| `app/web` | bilingual UI、local／public_demo境界、Cloud Run計画 |
| `app/agent_runtime` | Gemini probe、Google ADK、Agent Platform Runtime |
| `app/submission` | オフライン提出準備の安全検査 |
| `app/mcp` | optional Box設定preflight。現在のMVP／IBM track gateではない |

## 5. 確定済みの設計・運用制約

次の条件は、ユーザーの新しい明示決定なしに緩めない。

1. 実メディアと実GPXはローカルprivateを既定とする。
2. 実素材のクラウド送信は未承認。合成入力のクラウド検証とは分離する。
3. ~~視覚証拠を自動confirmedにしない。~~ **2026-09-01にユーザーが明示的に変更**。
   詳細は本節末尾の「2026-09-01の変更」を参照。
4. 最終作品は音声ナレーションなし。既存の著作権フリー音楽を使う予定。
5. 開発UIは日本語を既定とし、提出時は英語表示／英語字幕へ切り替える。
6. 公開ソースは`AGPL-3.0-only`。私用映像、GPX、音楽、認証情報は対象外。
7. Agentic Cinemaの選択trackはIBM。IBM Bob利用を開発証拠として示す。
8. Boxはoptional素材検索基盤であり、IBM track要件でもMVP gateでもない。
9. Gemini inferenceは`global`、Agent Runtimeとstagingは東京を使う。
10. private Cloud Runと未認証公開は別承認。現在のserviceはprivateのまま。

### 2026-09-01の変更｜視覚証拠confirmedの人手依頼を最小化

ユーザーの明示指示により、制約3を次のとおり変更する。

- クリップ取得から最終生成物に至るまでの人手確認は、**カメラ→GPS時計オフセットの
  確認1点だけ**に限定する。これは既存の`build_local_video_catalog`の
  `clock_offset_confirmed`（[local_catalog.py:100](local_catalog.py)）が既に
  担っている、素材ごとではなく一度だけの確認である。
- それ以外（個々のclipが本当にその出来事を写しているか、物語に使うに値する
  品質か）は、既存の決定論的gate・scoreだけでシステムが自動判定する。
  `LocalEvidenceReview`（`app/video/review.py`）のevent単位confirm/rejectと、
  `HighlightReview`（`app/video/highlight_review.py`）のcandidate単位
  approved/rejectedは、**人手承認待ちのブロッキングUIではなく自動判定**へ
  移行する。
- 既知の誤検出リスク（実14 MP4評価で「緩い直線寄り候補が候補として残った」、
  第2節参照）は許容する。ただし閾値付近の境界事例は、処理を止めずに
  private非ブロッキングログへ記録し、後から人手が任意に見直せるようにする。
  ログはopaque candidate ID・score・gate名・reason codeのみを持ち、source
  path・ファイル名・座標・時刻は含めない（既存の`HighlightReview`と同じ
  非識別方針）。
- 映像が全く無い／timestampが一致しないeventは、レンダー全体を止める理由には
  しない。その出来事は物語から外れる（GPSは提案するだけで断定しないという
  §1原則どおり）。
- 詳細設計は[`highlight-story-bridge-design-ja.md`](highlight-story-bridge-design-ja.md)
  に反映済み。未実装（Proposed）であり、この文書時点ではコード変更を伴わない。

## 6. 既知の問題と技術負債

### 優先度高

- ハイライト研究とStory Plan／candidate edit／evidence reviewが別系統。
- 最終E2Eのsource video directoryは`private-media/work/`配下を拒否する。研究用proxyを
  元映像として再利用し、候補品質や物語の根拠を取り違えないためである。
- 緩い道路曲率が「非直線」を通り、普通の道路映像が候補へ残る。
- strong-turnとtemporal visual-eventの候補laneは分離済みだが、visual-eventは
  scene／motionの非意味的proxyであり、合流・交差点・車両などを認識したとは扱わない。
  実14 MP4での候補品質と本数は未評価である。
- private highlight-review UIはloopback-only local serverに実装済み。明示設定した研究出力だけを
  読み、opaque IDと固定理由codeだけを表示・保存する。1候補の保存は他カードを再描画しないため、
  未保存の選択と再生位置をリセットしない。保存は原子的で、途中失敗時にも既存の判断履歴を保持する。
  review labelをStory Planへ接続する処理は未実装。
- private evidence-review UIはlocal pipelineの確認用clipだけを読み、human visual evidenceを
  `confirmed`、`rejected`、`awaiting`として保存する。品質reviewの採用／却下とは自動接続しない。
  画面は判断状態に基づく次のlocal gateを表示するが、全件confirmedでもDirectorやrenderを
  自動開始せず、local pipelineの再検証を要求する。
  未設定時はpathや設定値を露出せず、必要なローカル設定名と再起動だけを案内する。
- DirectorScriptのbrowser-safe summaryは、確認済みeventに出発と到着の両方があるか、片方だけか、
  旅の途中だけかを表示する。未確認の旅程端点を補う表現は使用しない。
- private metric cacheは実装済みだが、26.7 GiBのv4aでcache hit時の実測短縮時間は未計測。
- ハイライト候補の採用／却下＋固定理由codeのprivate contractは実装済み。2026-09-01に
  `auto_decide_highlight_review`／`find_highlight_review_borderline_candidates`を追加し、
  人手承認待ちのブロッキングUIを自動判定＋非ブロッキング境界事例ログへ置き換えた
  （[highlight-story-bridge-design-ja.md](highlight-story-bridge-design-ja.md) §7-0）。
  loopback-only review UI（`app/web/private_evidence_review.py`）とStory Planへの接続は
  未実装のまま。2026-09-01に`LocalEvidenceReview`側（`app/video/review.py`、
  `app/edit/candidate_planner.py`、`app/local_pipeline.py`のfail-closed gate3箇所）
  も同型の自動判定へ移行済み（同設計書§7-1）。highlight由来eventとGpsEventの橋渡し
  本体（同設計書§3）はまだ未着手。
- `python -m app.submission`の安全検査自体は成功するが、表示される`media_gates`の
  一部に「実ファイル入手後にinventory作成」等のv4a以前の定型文が残る。提出準備
  statusと実素材開発statusを同一の正本として扱わない。

### 優先度中

- Apple VisionはmacOSネイティブ権限が必要。ツールのサンドボックス内では
  `CVPixelBufferPool`を作れない。
- strict候補すべてのFeature Printを総当たりにしない。全候補は距離なしのbounded Vision batchで
  品質評価し、各方式の上位96候補の和集合（最大384件）だけを距離・MMR選定の母集団とする。
- 実映像coverageは約38%で、GPS全旅程を映像化できない。欠落区間の表現方法が未設計。
- 現在のrenderは確認用クリップの無音連結で、編集リズム、transition、地図、字幕、
  音楽mixを実装していない。
- 実動画のGemini解析は未承認・未実施。Vertex transportは承認済み`gs://` objectだけを
  受け取り、ローカル動画をuploadしない。
- 公開UIは合成デモ中心で、private実素材ワークフローのproduct UIではない。

## 7. 今後の設計・実装論点

IBM Bobの追加利用は終了した。以後はソラが、現在コードへの小修正ではなく、次を
一貫したアプリ設計として扱う。

1. ユーザーが素材を登録してから完成映像を得るまでの画面遷移。
2. import、catalog、同期、候補生成、レビュー、Story Plan、編集、exportの状態機械。
3. GPS event起点と映像起点のhighlight discoveryを統合する方法。
4. strong-turnとtemporal visual-eventの実素材評価を行い、景観、意味的な視覚イベント、
   物語上の役割を別々に扱うcandidate modelへ発展させる。
5. 人手レビューの採用／却下／差替え／理由を保存するデータcontract。
6. ローカル処理、任意クラウド処理、公開デモのsecurity／privacy境界。
7. Agent、決定論的処理、Apple Vision、Gemini、人手の責務分担。
8. private metric cacheを使った再現可能なexperiment／evaluation設計。
9. 38% coverageでも旅の始点・展開・終点を成立させるstory／edit戦略。
10. 既存コードから新設計へ段階移行するbuild planとtest strategy。

## 8. 設計・実装で必ず区別する状態

- **Implemented**：現在コードに存在する。
- **Verified**：テストまたは実行証拠がある。
- **Proposed**：未実装の設計案。
- **Requires user decision**：費用、外部送信、公開、音楽、作品内容などの判断。
- **Blocked**：実素材不足、権限、未承認external actionで進めない。

実素材v4aの技術E2E成功を、完成アプリ、良好クリップの自動選定成功、実動画Gemini
解析、公開service、Devpost提出完了の証明として扱ってはならない。

## 9. 検証状態

2026-09-01時点で、repository testは562件成功、Ruff成功、`git diff --check`成功。
外部Google SDK由来の非致命的な非推奨warningが7件ある。現在workspaceには未コミットの
ローカルスクリーンショット1枚（`docs/スクリーンショット 2026-08-30 23.58.48.png`）があり、
ユーザーの申告によりIBM Bob利用証跡である（第10節参照）。account email
（`bonz2000@gmail.com`）とBobの予算／使用量数値が写っており、`submission/ibm-bob-evidence.md`
が定めるpublic-safe基準（email非表示、費用・使用量非表示）を満たさないため、sanitize前は
public評価用assetへ加えない。private story
E2E基準線、private映像証拠確認UI、その保存防御はローカルcommit `08f7099`、`8a5287c`、
`bc7e995`、`82f736e`、`ba96633`、`bbe331e`に保存済みで、公開GitHubの`main`がこの文書と
同一状態とは限らない。

関連文書:

- [`local-e2e-pipeline.md`](local-e2e-pipeline.md)
- [`highlight-selection-experiments.md`](highlight-selection-experiments.md)
- [`highlight-story-bridge-design-ja.md`](highlight-story-bridge-design-ja.md)（Proposed、§6優先度高の接続設計）
- [`local-media-inventory.md`](local-media-inventory.md)
- [`submission/architecture.md`](submission/architecture.md)
- [`submission/technical-evidence.md`](submission/technical-evidence.md)
- [`submission/test-evidence.md`](submission/test-evidence.md)

## 10. IBM Bob 利用実績と利用終了記録

- IBM Bobは、コードベースの構造レビュー、GPSからrenderまでのフロー確認、
  fail-closed映像証拠gateの指摘、アプリ全体を再設計するための引継ぎ資料作成に
  使用した。公開可能な利用証跡は
  [`submission/ibm-bob-evidence.md`](submission/ibm-bob-evidence.md)と
  [`submission/ibm-bob-review-sanitized.md`](submission/ibm-bob-review-sanitized.md)に残す。
- 2026-08-31に、ユーザーからIBM Bobの利用クレジットが尽きたとの報告を受けた。
  以後はBobへの追加依頼を前提にせず、既存の利用証跡と人間によるレビューを継続する。
- 正確な消費クレジット数、費用、アカウント情報は取得しておらず、ここにも記録しない。
- Bobに起因する各作業の正確な実装範囲・当時のtest数は、保存済みの提出証跡で裏付け
  られる範囲だけを表現する。後続の未確認変更までBobがreviewしたとは扱わない。
- 2026-09-01、ユーザーの申告により、未コミットの
  `docs/スクリーンショット 2026-08-30 23.58.48.png`（撮影日時からBob作業当時のもの）を
  IBM Bob利用証跡として記録した。画面にはBobのTodoリストがあり、
  `app/agents/vertex_director.py`、`app/director_pipeline.py`、
  `tests/test_director_pipeline.py`等の作成項目が写る。既存の
  `ibm-bob-evidence.md`記載内容（review／findingマッピング中心）に加えて、
  Bobがdirector／executor関連ファイルの作成作業自体にも関与したことを示す証跡である。
  一方でaccount email（`bonz2000@gmail.com`）とBobの予算・使用量数値が写っており、
  同文書が定めるpublic-safe基準（email・費用非表示）を満たさない。sanitize（トリミング
  または黒塗り）とユーザーの明示的な承認前は、public submission assetへ追加しない。

## 11. 2026-08-31｜Director映像証拠bridgeの引継ぎ修正

- `overwrite=true`の再実行が既存`evidence-review.json`を初期化し、人手のconfirmed
  decisionを失う統合回帰を検出して修正した。
- 再実行ではcatalogやreview proxyなどの派生出力を更新しても、人手reviewは保存する。
  current candidate setと一致しないstale reviewは初期化せず`ValueError`で停止する。
- reviewのconfirmed／rejected decisionをfresh `CandidateClip`へ明示的に反映してから
  Scout／Directorへ渡す。映像を自動confirmedにせず、confirmed 0件ではDirectorを起動
  しない。
- Director pipelineは`RuleBasedDirector`を既定とする。Gemini transportが渡されても
  `allow_external_director=True`がなければ外部呼出し前に停止する。実素材の外部送信未承認を
  実行時にも維持するためのgateである。Director artifactはsource identityを含むため、repo内では
  ignoredなprivate出力directory以外へ書き出せない。
- 実GPX・実動画・座標・資格情報への読取り・外部送信、クラウド操作、commit／pushは
  行っていない。localgenには非機密の限定した設計下書きを依頼したが、起動待ち時間内に
  応答せず、生成出力は採用していない。

## 12. 2026-08-31｜private metric cache実装

- `app.video.metric_cache`を追加し、highlight researchのFFmpeg video metricsとGPMF
  metricsをprivate出力内の`metric-cache/`へ別々に保存するよう接続した。
- cache JSONには派生数値だけを保存する。source path、ファイル名、撮影時刻、座標、
  frameは保存しない。cache keyはsize、更新時刻、先頭／末尾各32KiBのハッシュから作る。
- 同じsourceは再利用し、source変更、schema不一致、破損cacheだけを再解析する。
  Apple Vision、clip抽出、人手evidence decisionは再利用対象にせず、状態も変更しない。
- 合成fixtureでcache hit、source変更時のinvalidating、GPMF cache、破損時再解析、
  payload非識別子、highlight discovery経路への接続を検証した。実14 MP4への再実行と
  cache hit時の時間短縮測定は未実施である。

## 13. 2026-08-31｜v4b interest laneの最小実装

- strict interest gateを強旋回とtemporal visual-eventの2 laneへ分離した。強旋回は
  方位差18度、中央方位差8度、累積方位差30度、経路効率0.985以下をすべて要求する。
- visual-eventはscene変化、peak率、motion変動の数値proxyだけを使う。合流、交差点、
  車両、景観を意味的に認識したとは主張せず、候補理由を人手reviewへ残すためのlaneである。
- manifest schemaをv2へ上げ、候補のinterest_lanesと使用gateを記録する。実素材の
  evidence statusは変更しない。
- synthetic contract testでlane分離、完全evidence gateの両lane受理、manifest記録を
  検証した。実14 MP4でのbounded実行結果は第15節に記録する。

## 14. 2026-08-31｜人手ハイライトreview contract

- `app.video.highlight_review`を追加した。候補ごとにopaque candidate ID、方式、rank、
  approved／rejected／awaitingと固定理由codeをprivate JSONへ保存する。自由記述、
  source path、ファイル名、撮影時刻、座標、frameは保存しない。
- approvedとrejectedはそれぞれ許可された理由codeを1件以上必要とする。awaitingは理由を
  持てない。candidate集合が変わった古いreviewは流用せず、評価前に`ValueError`で停止する。
- highlight researchの新規出力はtemplateを作成し、再実行では同一集合の既存reviewだけを
  保存する。loopback-only review UIは実装済みで、理由を用いる実素材の閾値評価とStory Plan接続は
  未実装である。
- synthetic contract testでtemplate、reason整合性、approval／rejection集計、stale拒否、
  round-trip、payloadの非識別子を確認した。全522テストが成功している。

## 15. 2026-08-31｜v4b bounded Visionの実素材E2E

- privateの14 sourceを6秒strideで解析し、797窓、strict interest 602、GPMF／Vision
  complete evidence 602、final quality gate 59を得た。4方式で各8本、計32本の確認用clipを
  private出力へ抽出した。外部送信は0である。
- Vision品質評価は全strict候補の3フレームをbounded batchで処理した。Feature Print距離は
  各方式上位96候補の和集合だけに限定し、全候補の総当たり距離行列を作らない。
- restricted sandboxでは正常JPEGにも`CVPixelBufferPool`作成失敗が出るが、同じprivate
  フレームをnative macOS権限で処理して完走した。素材破損ではなく実行環境差である。
- review contractはawaiting 32、approved 0、rejected 0で生成された。映像証拠の自動confirmed、
  Director入力、render許可は発生していない。review UIは実装済みで、理由を使う再選定とDirector接続が
  次の実装課題である。

## 16. 2026-08-31｜MVPの中心を「旅の物語E2E」へ再固定

Ride Storytellerは、良い映像を自動抽出するだけの製品ではない。一回のツーリングを、
確認済みの根拠に基づく一本の物語として再構成する製品である。以後、映像解析の
精度改善より次のE2Eを優先する。

```text
実素材
  → Scout / UniversalEvent
  → Director
  → DirectorScript
  → deterministic Editor
  → evidence-gated Final Video
```

- **Scout** は何が起きたかと、その根拠を供給する。GPS・地理context・映像由来featureを
  統合するが、物語の順序を決めない。
- **Director** はconfirmed eventだけを使い、Hook / Build-up / Climax / Resolutionを
  構成する。Hookは中盤の確認済み出来事を前置できるが、未確認映像・場所・出来事は
  作らない。RuleBasedDirectorは現在の決定論的fallback、Gemini Directorは同じscript
  contractを満たすGoogle Cloud上の本番候補である。
- **Editor** はDirectorScriptを忠実に実行し、既存の映像証拠gateを再確認する。意味付けや
  evidence confirmationを補完しない。
- `visual_score`は撮影映像の見栄え、`scenic_score`は地理的/景観的な文脈を示す別信号である。
  一方から他方を推測しない。

Gemini Directorの最初のWeb E2Eは、固定合成Universal Eventだけで行う。実GPS、実動画、
座標、素材識別子、source intervalを外部へ送る機能は、この方針だけでは承認されない。

この合成E2Eの入口として、local mode専用の
`POST /api/gemini-director-synthetic-demo`を実装した。HTTP本文を拒否し、
`app.demo.build_synthetic_director_events()`の固定fixtureだけをVertex AI Gemini Directorへ
渡す。応答はcomposer、fallbackの有無、scene role、scene数だけであり、source identity、
event ID、座標、pathは返さない。public_demo modeでは403で無効化する。呼出し自体はGoogle
Cloudの外部通信・費用を伴い得るため、今回の実装では実行していない。

## 17. 2026-08-31｜Gemini Directorの物語順序をfail closedで検証

- GeminiのJSON schemaが正しくても、同じ物語役割を繰り返したり、Hook / Build-up /
  Climax / Resolutionの表示順を逆転したりすると、旅の構成として採用できない。
- `app.director`は、同一scene roleの再使用と、定義済みの物語順序に従わない応答を
  `GeminiDirectorError`として拒否する。`FallbackDirector`を利用する呼出し側は、
  その場合に決定論的なRuleBasedDirectorへ戻る。
- eventの重複、未知event、未確認event、source identityの生成・変更も、従来どおり
  拒否する。実素材・座標・path・資格情報の外部送信はこの変更でも発生しない。
- Web UI用には、役割、clip数、transition、overlay textだけを返す専用summaryを使用する。
  event ID、asset ID、ファイル名、source interval、座標、pathはprivateなEditor artifactに
  留め、browser responseには含めない。

## 18. 2026-09-01｜私用Story E2E再開入力を固定

- `app.local_pipeline`は初回準備時に`local-pipeline-inputs.json`をprivate outputだけへ保存する。
  記録するのはGPX、元動画directory、時計補正、目標尺、言語であり、絶対pathを含むためsummary、
  browser、Notion、公開artifactには出さない。
- 既存packageを別のGPXや動画directoryで`--overwrite`しようとすると、動画probe前に停止する。
  人手の`evidence-review.json`を別の旅や派生proxyへ黙って結び付けないためである。
- `python -m app.local_pipeline --resume-output <private package>`は、その入力記録だけを読んで
  offline RuleBased Directorを再実行する。manifestが欠損、破損、symlink、参照先消失ならfail
  closedで停止する。Gemini、Google、Boxその他の外部通信は行わない。

## 19. 2026-09-01｜confirmed packageの一続きStory E2E

- `app.private_story_e2e`を追加した。引数はprivate packageだけであり、manifest検証、全人手
  evidenceのconfirmed確認、offline Director再検証、DirectorScript順のsilent FFmpeg renderを
  一続きに実行する。
- 入力GPXや動画directoryを別引数で受け取らないため、レビュー済み旅を別素材へ置換できない。
  DirectorScript生成後も既存Editorがsource identityとconfirmed allow-listを再確認する。
- 合成contractで、confirmed packageがDirector順にrenderされること、awaiting packageが動画probe前に
  停止することを確認した。Gemini、Google、Box、外部通信は行わない。
- `app.private_story_e2e`の集計出力は、出力動画名を含めない。source asset ID、区間、素材名、pathも
  同様に含めず、private実行の結果は件数・尺・無音・story order適用の事実だけを返す。
