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
  も同型の自動判定へ移行済み（同設計書§7-1）。同日、highlight由来eventとGpsEventの
  橋渡し中核（`app/video/highlight_story_bridge.py`、同設計書§7-2）も実装した。
  2026-09-02、橋渡しが実際に必要とする狭いレコード`HighlightBridgeCandidate`の
  永続化（`highlight-bridge-candidates.json`）を実装し、`QualitySelection`本体を
  保存しない設計でVision分類ラベル・asset_id非公開方針を維持したまま解決した
  （同設計書§7-3）。同日、`app.local_pipeline.prepare_local_review_package`に
  `highlight_bridge_candidates_path`引数を追加して配線し、CLI引数
  `--highlight-bridge-candidates`も追加した（同設計書§7-4）。実データで
  末端まで実行し、`highlight_research`は選定候補が全件自動承認・
  awaiting/rejected 0件で完走したが、`app.local_pipeline`との合流では
  **新規追加eventが0件**だった（候補が全て既存GPS由来eventと時間的に重複）。
  橋渡しが実際に価値を持つのは「既存eventの区間補強」側だと実データで
  判明した（同設計書§7-5）。なお実データ検証の過程でGoPro LRVプロキシの時間長
  不一致バグ（`_recording_key`の紐付け誤り）を発見・修正済み
  （`app/video/highlight_discovery.py`）。2026-09-02、その区間補強経路
  `reinforce_resolved_clips_with_highlights`を合成fixtureのみで実装・配線した
  （同設計書§7-6）。同日、既存の実private入力・catalog・既存の
  highlight-bridge-candidates.jsonだけを使ってローカル検証したところ
  （新規highlight research実行なし）、highlight候補と重なるmatched clipは
  ごく一部で、重なった1件は候補が複数あって曖昧なためfail-closedで意図通り
  変更しなかった（区間が狭まったclipは0件）。既存コードに問題は見つからず、
  コード変更なし（同設計書§7-7）。同日、`_select_unambiguous_candidate`を追加し、
  重なる候補が全て同一`QualitySelectionMethod`でrankが一意に最小の場合だけ
  補強するよう緩和した（method間はscore・rankとも比較しない、同率や
  method混在は従来どおり変更しない）。合成fixtureのみで検証済み
  （同設計書§7-8）。`--resume-output`との統合は未実施のまま。同日、
  method混在・rank同率でも人手が明示的に選ぶための`HighlightReinforcementSelection`
  契約（private-only、UI未接続）を追加し（同設計書§7-9）、続けてどのclipに
  その選択が必要かを安全に一覧化する`find_highlight_reinforcement_conflicts`を
  追加した（同設計書§7-10）。いずれも合成fixtureのみで検証済み。同日、
  既存のloopback-only private review UI群と同じ方式で、この一覧・選択契約を
  画面化した`app/web/private_highlight_reinforcement_review.py`を追加し
  （同設計書§7-11）、コミット済み。ブラウザへはevent_id・candidate_idを
  一切渡さず、session内だけで意味を持つopaque review tokenだけを使う。
  続けて`app.local_pipeline.prepare_local_review_package`に新引数
  `highlight_reinforcement_review_directory`とCLI引数
  `--highlight-reinforcement-review-directory`を追加し、web UIが保存する
  selectionを新規/再準備packageへ接続した（同設計書§7-12）。効果的な
  candidatesとselectionはpackage内へsnapshotされ、`--resume-output`は
  常にそのsnapshotだけを再現する。review directory側でselectionが後から
  変わっても、既存packageのresumeは影響を受けない。合成fixtureのみで
  検証済み。Codex reviewで、snapshotの片方だけが存在するpackageと、snapshotを
  明示的入力なしで`overwrite=True`再準備しようとする呼出しを、いずれもprobe前に
  拒否するfail-closed境界を追加した。選択済み補強からoffline Director、silent renderまでの
  合成private Story E2E回帰も追加した。この増分は未commit。Director・render・evidence判定・
  auto-confirmation方針は変更していない。
- 2026-09-02、`app/submission/readiness.py`の`media_gates`定型文をv4a以前の
  「実ファイル入手後にinventory作成」等からv4a実績に合わせて更新した。ただし
  提出準備statusと実素材開発statusを同一の正本として扱わない方針は変わらない。

### 優先度中

- Apple VisionはmacOSネイティブ権限が必要。過去のtool sandbox内では
  `CVPixelBufferPool`を作れず失敗していたが、2026-09-02に別環境（Claude Code
  bash実行）から`tools/apple_vision_probe.m`をコンパイル・実行したところ、実際の
  GoProフレームに対して正常に分類結果が得られた。サンドボックスの権限構成に依存する
  問題であり、恒久的に解消したとは断定しない。
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
（本文書では非公開のため伏字）とBobの予算／使用量数値が写っており、
`submission/ibm-bob-evidence.md`
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
  一方でaccount email（本文書では非公開のため伏字）とBobの予算・使用量数値が写っており、
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

## 20. 2026-09-02｜Gate 1 実施記録｜実素材packageの健全性確認

ロードマップ（[`completion-roadmap-ja.md`](completion-roadmap-ja.md)）Gate 1の検証を、
再現可能な機能として`app/private_package_health.py`に実装した。

- 検証内容: private input manifestの読み取り、catalogとmanifestの時計補正値の一致確認、
  evidence reviewのawaiting／confirmed／rejected集計、resolved candidateのmatched／
  unmatched集計、confirmed済みかつmatchedなclipの合計尺と目標尺の比較。
- 出力サマリーは件数・尺・真偽値・固定reason codeだけを持ち、event ID、asset ID、
  ファイル名、path、座標、時刻を一切含まない。
- 読み取りはpackage自身が既に書き出したJSONのみ。source video、GPX、ネットワークには
  一切アクセスしない。
- 判定をブロックする条件は4つ: 時計補正の不一致、未判断（awaiting）の残存、confirmed 0件、
  confirmed合計尺の不足。
- unmatched clipとrejected eventは報告するがブロックしない（2026-09-01の決定により、
  該当eventは物語から外れるだけのため。第5節参照）。
- CLI: `python -m app.private_package_health <package>`。
- 合成fixtureのみで10件のテストを追加した（正常系、awaiting残存、confirmed 0件、
  時計補正不一致、尺不足、unmatched／rejected非ブロック、package欠損、必須export欠損、
  symlink拒否、サマリーの非識別性）。

**結果**: 既存の実素材package群へ適用したところ、時計補正一致・awaiting 0・confirmed 1件以上は
満たしたが、**confirmed合計尺が目標尺に届かず未達**だった（reason code
`insufficient_confirmed_duration`）。したがってGate 1は現時点で未通過であり、renderへ進まない。
次の課題は、confirmed区間の合計尺を目標尺まで増やすことであり、Gate 2の物語構成と併せて扱う。

## 21. 2026-09-02｜Gate 1追跡調査｜confirmed尺不足の原因

第20節の`insufficient_confirmed_duration`について、原因をローカルだけで切り分けた。

- 目標尺を引き上げても、選定されるeventと合計尺は一切変わらない。つまり不足は
  「目標尺による打ち切り」ではなく、**映像で裏付けられるGPS eventの総数そのものが上限**
  であることを確認した。抽出されたGPS eventのうち、映像coverageを持つのは約3割にとどまる。
- さらに、映像で裏付けられるeventの種別は速度変化と方向転換に限られ、**出発（departure）と
  到着（arrival_candidate）の映像が存在しない**。現状のconfirmed集合だけでは、旅の始点と
  終点を映像で示せない（DirectorScriptの`JourneyCoverage`でいう
  `middle_of_journey_only`に相当する）。
- したがって「confirmed尺を増やす」方向の実装（候補追加、閾値緩和、目標尺の引き上げ）は
  この素材では効果がない。残る選択肢は次の3つであり、いずれも製品判断を伴う。
  1. 目標尺を実際のconfirmed尺に合わせて短くする（中間のみの短編になる）。
  2. 不足分を映像以外の表現（章テキスト、地図上の移動、時間経過）で埋める。これは
     ロードマップGate 2・Gate 3が既に方針として掲げている方向であり、
     「存在しない映像で補わない」原則とも整合する。
  3. 追加の実素材を用意する（撮影済み素材の追加投入）。
- 実素材はローカル読取りのみで、外部送信・render・公開は行っていない。

## 22. 2026-09-02｜Gate 2着手｜欠落区間の非映像contract

第21節の3択について、ユーザーが「不足分を章テキスト・地図表現で埋める」を選択した。
これを受け、欠落区間をGPS証拠だけから記述するcontractを`app/journey_gaps.py`に実装した。

- `JourneyGapSegment`は、確認済み映像が無い区間について、**GPS trackが証明する事実だけ**を
  持つ: 継続時間、走行距離、獲得標高、喪失標高。カメラが何を写したかは一切主張しない
  （撮影していないため）。「存在しない映像で補わない」原則をcontractレベルで保証する。
- 区間種別は`before_first_clip`（映像より前）、`between_clips`、`after_last_clip`（映像より後）。
  出発・到着に映像が無い今回の素材では、始点と終点がこの非映像区間として表現される。
- `build_journey_gap_plan`は、確認済み映像の絶対時刻窓を先にmergeしてから間隙を取る。
  重複・順不同の窓でも架空の間隙を作らない。既定60秒未満の間隙、およびtrackが2点未満しか
  記述しない区間は、推測せず除外する。
- `to_dict()`は集計値のみ（時間・距離・標高差）。座標、撮影時刻、event ID、asset ID、
  path、ファイル名を含まない。
- DirectorScriptのcontractは変更していない。欠落区間は並行する独立contractとし、
  Gate 3のrendererが両者を合成する設計とする。
- 合成fixtureのみで15件のテストを追加。全734件成功、Ruff成功。
- 既存の実素材packageへ適用したところ、確認済み映像の前後と間に複数の欠落区間が検出され、
  その中に出発側・到着側の区間が含まれることを確認した。これにより、出発から到着までを
  一本の物語として構成する材料が揃った。実素材はローカル読取りのみで外部送信していない。

## 23. 2026-09-02｜Gate 2｜欠落区間とconfirmed映像を一本の物語順へ

第22節の欠落区間を、確認済み映像と同じ1本の時系列へ並べるcontractを
`app/story_timeline.py`に実装した。

- 背骨は時系列とした。欠落区間の意味は「どの2つの撮影済み場面の間に位置するか」で
  決まるため、章カードが意味を持つのは走行順に置かれたときだけである。Hook /
  Build-up / Climax / Resolutionの役割は`app/director.py`のcontractに残し、
  ここでは二重定義しない。
- `StoryBeat`は`footage`（撮影済み場面）か`gap_card`（その間の移動）のいずれかで、
  走行時刻の窓と画面上の尺を持つ。footageはevent IDを持ちgapを持たない、gap cardは
  gapを持ちevent IDを持たない、をcontractで強制する。
- **画面上の尺は走行時間ではない**。長時間の移動区間をそのまま長い章カードにすると
  作品が止まるため、走行時間に比例させたうえで下限3秒・上限8秒でclampする決定論的な
  写像とした（既定は走行240秒あたり画面1秒）。単独の区間が作品を占有することも、
  読めないほど短いカードが出ることもない。
- 重なり合うfootage、footageと重なる欠落区間、同一eventの二重使用はfail closedで
  拒否する。旅を誤って表現したtimelineを黙って作らない。
- `to_dict()`はkind、画面尺、走行時間、および欠落区間の集計値のみ。event ID、asset ID、
  絶対撮影時刻、座標、path、ファイル名を含まない。footage beat自体はcut用のevent IDを
  保持するが、これは他のprivate artifactと同じ扱いで、serialize時には出さない。
- 合成fixtureのみで12件のテストを追加。全746件成功、Ruff成功。

### 実素材での検証結果（ローカル読取りのみ、外部送信なし）

既存の実素材package（`local-pipeline-inputs.json`のtarget 300秒）へ適用した結果。

| 指標 | 値 |
|---|---|
| confirmed footage beat | 7 |
| gap card beat | 8 |
| footage 画面尺 | 210.0秒 |
| gap card 画面尺 | 44.2秒 |
| **作品全体の画面尺** | **254.2秒** |
| 欠落区間の走行時間合計 | 14,792秒 |
| beat並び | `g F g F g F g F g F g F g F g` |

出発側の章カードで始まり、到着側の章カードで終わる完全な交互構造となり、出発から到着
までを一本の旅として構成できることを実素材で確認した。第20節で未通過となった
`insufficient_confirmed_duration`（confirmed尺210秒 < 目標300秒）は、欠落区間を
画面へ載せることで254.2秒まで縮まった。残り45.8秒は素材不足ではなく、カード尺・章テキストの
配分というGate 3の調整問題である。

### 実装上の注意（実素材検証で発見）

footage beatの走行時刻窓には、**GPS eventの窓ではなく実際に切り出すクリップの窓**を
渡す必要がある。両者は大きく異なり、旋回eventは数秒だがその周囲のクリップは30秒である。
event窓を渡すと作品尺を過小評価し（検証中に210秒が12秒と算出された）、さらにカメラが
回っていた区間を欠落区間として二重に扱ってしまう。`app/journey_gaps.py`へ渡す
`covered_windows`も同じクリップ窓から作ること。この注意は`TimelineFootage`の
docstringにも記載した。

## 24. 2026-09-02｜Gate 2｜章テキストと尺配分でGate 1の尺不足が解消

第23節の残り45.8秒について、欠落区間の章テキストと画面尺の配分規則を
`app/gap_chapters.py`に実装した。

### 章カードの文言

- カード上の言葉は**すべてGPS trackが証明する事実だけ**から作る。継続時間、走行距離、
  獲得標高、喪失標高。地名も天候も、ライダーが何を見たかの推測も載せない。カメラは
  回っていなかったのだから、旅そのものが証明することしか書かない。
- 区間の性格は`GapCharacter`で分類する: `departure` / `arrival` / `climb` / `descent` /
  `long_haul` / `link`。最初と最後の区間は、地形よりも「旅のどこに位置するか」の方が
  重要な事実であるため、標高や距離より`departure` / `arrival`を優先する。それ以外は地形が決める。
- 獲得標高と喪失標高が相殺する起伏地形は、`climb`ではなく`link`とする（純標高で判定）。
- 本文は`1時間52分 · 74.3km · 登り620m / 下り410m`の形式。標高差が10m未満の区間では
  標高句を省く。日英で同一構造を保つ。
- 文言は画面表示を前提とするため、座標、絶対撮影時刻、event ID、asset ID、path、
  ファイル名を一切含まない。

### 尺配分規則

- 目標尺に届かない分は、**既に必要だったカードを長く保持する**ことだけで埋める。映像を
  引き伸ばさず、存在しない素材で埋めない。
- 配分は**走行時間に比例**させる。基準尺（第23節）が走行時間に比例している以上、追加分も
  同じ原則に従わなければ、作品の緩急の論理が二つに割れてしまう。上限12秒に達したカードは
  そこで止まり、使えなかった分は上限未満のカードへ回る（water-filling）。決定論的。
- 全カードを上限まで保持しても届かない場合は、`residual_shortfall_s`として報告する。
  目標を満たしたかのように黙って扱わない。
- 合成fixtureのみで15件のテストを追加。全761件成功、Ruff成功。

### 実素材での検証結果（ローカル読取りのみ、外部送信なし）

| 指標 | 値 |
|---|---|
| 目標尺 | 300.0秒 |
| footage 画面尺 | 210.0秒 |
| gap card 画面尺（配分後） | 90.0秒 |
| **作品全体の画面尺** | **300.0秒** |
| `residual_shortfall_s` | **0.0** |
| `meets_target` | **True** |

8枚中6枚が上限12秒、残り2枚が7.7秒・10.3秒となり、目標尺ちょうどに一致した。
日英どちらの言語でも同一の尺配分・同一の区間分類となることを確認した。

**第20節でGate 1未通過の理由とした`insufficient_confirmed_duration`は、これで解消した。**
不足は素材の不足ではなく、旅の欠落区間を画面に載せていなかったことに起因していた。
Gate 1の再判定には、`app/private_package_health.py`の尺判定をこの章計画後の作品尺に
基づかせる変更が必要であり、次の作業単位とする。

## 25. 2026-09-02｜Gate 1 通過｜package自身が作品の姿を持つ

### 課題

Gate 1の尺判定は、第24節で作品尺300.0秒を確認した後も`insufficient_confirmed_duration`を
出し続ける状態だった。`app/private_package_health.py`は設計上**packageが自分で書いた
JSON出力しか読まない**（GPXもsource videoもネットワークも触らない）ため、章カードを含む
作品の姿がpackage内に存在しない限り、確認済み映像210秒しか見えなかったからである。

### 解決：`app/story_package.py`

`JourneyGapPlan`・`StoryTimeline`・`GapChapterPlan`の答えを1つの順序付き計画に統合し、
package内に`journey-story-plan.json`として書き出すcontractを実装した。

- **footage beatはevent IDだけを名指し、切り出し位置は持たない**。実際のcutは
  `ride-storyteller-candidates.json`に残す。フレームの所在を1箇所にしか書かないことで、
  2つの記述がずれる余地を無くす。
- gap beatは章カード（種別・性格・タイトル・本文・確定尺）を持つ。
- event IDを含むためprivate artifactであり、git管理外のpackageにのみ置く。公開export、
  browser payload、handoff noteには載せない。
- 書き込みはmkstemp＋`os.replace`でatomic、symlinkは拒否。既定はoverwrite（派生データ
  であり、新しい出力の隣に古い作品の姿を残さないため）。読み込みはschema version、
  型、必須キー、event重複をfail closedで検証する。
- Gate 1は、計画があればその作品尺で、無ければ従来どおり確認済み映像尺で尺判定する。
  どちらを使ったかは`duration.includes_chapter_cards`で明示する。**計画が壊れている
  場合は映像尺へ黙って戻らず、fail closedで停止する**。
- 合成fixtureのみで18件のテストを追加（`story_package` 14件、Gate 1統合 4件）。
  全779件成功、Ruff成功。

### Gate 1 再判定結果（実素材、ローカル読取りのみ、外部送信なし）

```
is_ready: true          blocking_reasons: []
clock_offset_confirmed: true
matched 7 / unmatched 0 / confirmed 7 / awaiting 0 / rejected 0
duration: confirmed 210.0s → film 300.0s / target 300.0s / missing 0.0s
          coverage_ratio 1.0, includes_chapter_cards true
```

**Gate 1は通過した。** 第20節で未通過とした`insufficient_confirmed_duration`は解消し、
最終E2Eの入力が固定された。beat数15（footage 7、章カード8）。

次はGate 3（chapter card、地図・移動表示、字幕、音楽、決定論的render）。

## 26. 2026-09-02｜Gate 3着手｜章カードの描画と地図

### 発見：使えるffmpegに文字描画機能が無い

Gate 3の章カード・字幕に着手した時点で、導入済みのffmpeg 9.0.1（Homebrew）が
`drawtext`・`subtitles`・`ass`のいずれのフィルタも持たないことが判明した。
`--enable-libfreetype`・`--enable-libass`を付けずにビルドされているためで、Homebrew現行の
ffmpeg formulaは依存11件のみでfreetype/libassを含まない。**再インストールでは解決しない**。

代替手段の調査結果:

| 手段 | 可否 |
|---|---|
| ffmpeg `drawtext` / `subtitles` | 不可（ビルドに機能なし） |
| Pillow等の画像ライブラリ | 不可（本プロジェクトは実行時依存0件を維持する方針） |
| ImageMagick | 未導入 |
| PyObjC（Quartz/AppKit） | 未導入 |
| **macOS内蔵 Quick Look（`qlmanage -t`）でHTMLをPNG化** | **可** |

### 採用：HTML → Quick Look → PNG → ffmpeg

章カードをHTMLページとして組み、macOS内蔵のQuick Lookでラスタライズする方式を採用した。
**新規依存ゼロで、日本語も地図SVGも同じ経路で描ける。**実測0.3秒/枚。

- **Quick LookはHTMLを常に正方形へ描画する**（`-s 1280`→1280×1280。`-s 1280x720`を
  渡しても正方形になる）。したがってページは正方形として組み、作品の16:9フレームは
  その中央から切り出す。
- **寸法はvw/vh基準にする**。`width:1280px`のような固定指定はQuick Lookのビューポートと
  ずれ、内容が中央から外れる（実測で右下へ大きくずれた）。ビューポートに依らず中央へ
  来るよう相対単位で組む。
- ページは外部参照を一切持たない（script、stylesheet、画像、フォントファイル）。
  ラスタライズがネットワークへ到達できず、同じ入力が常に同じカードを描く。

### 地図表現（Gate 3の要件）

`route_map_svg`で、旅全体を淡い線、そのカードが表す区間を強調色で重ねて描く。
視聴者は「時間が経過した」だけでなく「旅のどこを通ったか」を見られる。

- 経度は**ルート平均緯度の余弦で補正**してから描く（補正しないと東西に伸びて実際の
  ルート形状と違う図になる）。
- 描画枠は**正方形が既定**。旅は任意の方向へ延びるため、南北に細長いルートを横長枠へ
  収めると読めない大きさになる（実測で確認し、320×320へ変更した）。
- 図はview box内へ正規化される。**ルートの形は残り、地球上の位置は残らない**。
  緯度経度の値も`latitude`等の語もmarkupに現れない。
- 長いtrackは決定論的に間引く（上限400点、両端は必ず残す）。実素材7,098点で確認。
- ただし形状自体は土地勘のある者には識別可能であるため、**この地図はprivate作品内に
  限る**。公開demo・提出物・外部送信には用いない。

### 検証

- 合成fixtureのみで15件のテストを追加。全794件成功、Ruff成功。
- 実素材（route 7,098点、章カード8枚）でHTML生成→Quick Look→ffmpeg crop→フレーム
  取り出しまで通し、日本語タイトル・本文・実ルート形状・強調区間が正しく描画される
  ことを目視確認した。実素材はローカル読取りのみで外部送信していない。

次は、このカードと確認済み映像を`journey-story-plan.json`の順に連結する決定論的
レンダーを実装する。

## 27. 2026-09-02｜Gate 3｜計画通りの作品を実際に切り出した

`journey-story-plan.json`が示すbeat順に、確認済み映像と章カードを1本のmp4へ連結する
`app/story_film.py`を実装した。

### 設計上の2つの規律

- **映像証拠gateを迂回できない**。人が確認していないeventを指すbeat、またはclipが存在しない
  beatがあれば、そのbeatを黙って落とさずrenderを停止する。落とせば「完成しているように
  見える短い作品」ができてしまい、証拠gateの意味が消えるため。
- **連結前に全segmentを同一のフレーム（1280×720 / 30fps / yuv420p / SAR 1）へ正規化する**。
  FFmpegのconcat filterは仕様の異なるstreamを繋がない。カードは正方形で描かれ映像は
  16:9で撮られているため、カードだけ中央帯をcropしてから揃える。不一致はencode途中では
  なくcommand構築時に検出する。

映像側の音声は落とす（エンジン音・風切り音であり、Gate 3は選択した著作権フリー音楽を
用いる方針。ナレーションは加えない）。commandは純関数として構築するため、FFmpeg・
Quick Look・実素材なしにrender全体の形をテストできる。

### 実素材での実行結果（ローカルのみ、外部送信なし）

```
Gate 1: ready
confirmed clips available: 7
cards drawn: 8
segment_count 15 / footage 7 / card 8
duration_s 300.0    audio_included false    external_data_sent false
```

出力: 1280×720 / h264 / 30fps / 8,999フレーム / 300.03秒 / 249.5MB。
t=296秒のフレームで、最終カードが「帰り着くまで」であり、地図の強調区間がルート末端に
位置することを目視確認した。**出発から到着までを一本の旅として語る作品が、実素材から
生成できる状態になった。**

- 合成fixtureのみで23件のテストを追加。全817件成功、Ruff成功。
- 生成物（mp4、`story-cards/`のHTML・PNG）はgit管理外の`private-media/`配下にのみ置く。

Gate 3の残りは字幕と音楽（曲名・作者・ライセンスは提出用に分離記録する）。

## 28. 2026-09-02｜字幕と、クラウド（Linux）での章カード描画

### 字幕はサイドカー（焼き込まない）

`app/story_subtitles.py`で、作品と同じ`journey-story-plan.json`からSRT/WebVTTを生成する。

- 作品にナレーションは無いため、字幕は発話の書き起こしではなく**画面上の章テキストを
  トラックとして提供するもの**。プレイヤーの字幕機能で読め、絵を作り直さずに提出用
  字幕ファイルが得られる。
- **映像beatにはcueを付けない**。そこでは何も語られておらず、作品は「そこで撮影された」
  以上の主張をしない。沈黙を埋めるために作ったcueは、本プロジェクトが拒否してきた
  種類の主張そのものになる。
- 字幕は作品の言語に従う（日本語の作品は日本語のカードと日本語のcue）。画面の言葉と
  トラックの言葉が食い違わない。**タイミングは言語に依らず同一**（テストで保証）。
- 焼き込まない理由は2つ。(1) Quick Lookは透明背景のページを**白で合成する**ため
  オーバーレイ素材を作れない（実測確認）。(2) より本質的に、焼き込むと言語がencodeの
  属性になり、言語切替のたびに全再エンコードが必要になる。

### クラウド（Linux）での章カード描画

**ユーザー指摘「本番はGoogleクラウド」への対応。** Quick LookはmacOS専用であり、
Cloud Runには存在しない。カード描画を差し替え可能にした。

| 実行環境 | rasteriser | 備考 |
|---|---|---|
| 開発機（macOS） | `QUICK_LOOK`（`qlmanage`） | 追加インストール不要。ログインセッションが必要 |
| Linux container / Cloud Run | `HEADLESS_CHROMIUM`（`chromium --headless=new`） | 同じHTMLを描画 |

**カードのHTMLが唯一のcontractであり、変わるのはrasteriserだけ。**両者に同じ正方形
（1280×1280）を要求するため、16:9フレームを取り出すcropは同一で、どちらで描いても
カードの見た目は変わらない。

### 現状の事実（誤解を避けるため明記）

- 配備中のCloud Run containerは`python:3.12-slim`ベースで**ffmpegを含まず**、
  `RIDE_WEB_MODE=public_demo`で動作する。**現在クラウドでは作品を生成していない。**
- 上記の対応は「クラウドで描画できる**道を用意した**」であり、「クラウドで動いている」
  ではない。クラウドで実際にrenderするには、containerへffmpegとchromiumの追加、
  および実素材をクラウドへ送るか否かの**方針判断**が別途必要になる。

合成fixtureのみで14件のテストを追加。全831件成功、Ruff成功。

## 29. 2026-09-02｜1コマンドで作品が完成する状態になった

`app/private_journey_film.py`を実装し、reviewed packageから作品・字幕までを1回の呼び出しで
生成できるようにした。

```
.venv/bin/python -m app.private_journey_film <package>
```

これまで物語計画の構築だけがコード化されておらず（検証用スクリプトにしか無かった）、
系として繋がっていなかった。この実装で、Gate 1検証 → 物語計画の生成と書き出し →
章カード描画 → 連結render → 字幕出力までが1本になった。

### 実行中に発見・修正した3つの実バグ

1. **Gate 1の尺判定と物語計画の鶏と卵**。Gate 1の尺判定には計画が必要だが、計画は
   render実行時に作られる。そのため計画の無いpackageは尺不足で永久にブロックされ、
   作品を一度も作れなかった。修正: **Gate 1を2回問う**。「証拠が確定しているか」
   （awaiting無し・confirmed有り・時計補正一致）はpackage単体の事実なので先に問い、
   これに失敗すれば計画もrenderもしない。「作品が目標尺に届くか」は作品の姿が
   決まるまで**事実ですらない**ので、計画を書いてから改めてgate全体を問う。
2. **計画が自分のserializeを往復しない**。丸め前の値でtotalを合計していたため、
   書き出して読み直すと別の値になった。放置すると「Gate 1が測る作品」と
   「rendererが切る作品」が食い違う。修正: 書き出す桁数（小数3桁）で各beatを
   丸め、totalはその丸めた値から合計する。
3. **1フレーム未満の誤差で完成した作品が却下される**。丸め残差（0.001秒程度）で
   `insufficient_confirmed_duration`が誤発火した。さらに計画側の`meets_target`と
   Gate 1側で厳しさが違い、**同じ作品を2箇所が別々に判定**していた。修正:
   許容値`DURATION_TOLERANCE_S`（1フレーム＝1/30秒）を`app/story_package.py`に
   1箇所だけ置き、双方がこれを使う。

### 実素材での実行結果（ローカルのみ、外部送信なし）

```
health: is_ready true / blocking_reasons []
        confirmed 210.0s → film 300.0s / target 300.0s / coverage 1.0
film:   segment 15 (footage 7 + card 8) / 300.0s / audio false
subtitles: ride-storyteller-story-film.srt, .vtt
plan:   beat 15 / meets_target true
local_only true / external_data_sent false
```

字幕は8枚のカードに対応する8cue。冒頭`00:00:00,000 --> 00:00:12,000 旅の始まり`、
末尾`00:04:48,000 --> 00:05:00,000 帰り着くまで`。**作品が出発で始まり到着で終わる
ことが、字幕のタイムコードからも確認できる。**

合成fixtureのみで13件のテストを追加。全843件成功、Ruff成功。

## 30. 2026-09-03｜音楽と、クラウド構成の設計

### 音楽（Gate 3の最後の1件）

ユーザー承認のもと、著作権フリー曲5曲を選定・取得した。全てKevin MacLeod作、
**Creative Commons: By Attribution 4.0**（商用可、帰属表示のみ）。

| track ID | 曲 | 尺 |
|---|---|---|
| `wholesome` | Wholesome | 363.8秒 |
| `enchanted-valley` | Enchanted Valley | 190.3秒 |
| `windswept` | Windswept | 208.3秒 |
| `rising-tide` | Rising Tide | 277.4秒 |
| `lightless-dawn` | Lightless Dawn | 379.8秒 |

`app/story_music.py`の設計判断:

- **ライセンスは成果物の一部**として扱う。作品は無音で切り出され（走行音は落とし、
  ナレーションも入れない）、音楽が唯一の音になる。各曲は題名・作者・出典・ライセンス・
  **そのライセンスが要求する帰属文言そのもの**を持ち、`docs/music-credits.md`へ分離記録する。
- **曲の尺は作品の尺と一致しない**（190〜380秒 対 300秒）。短ければループ、長ければ
  トリムし、いずれも**音は絵と同時に終わる**。唐突に止まる音楽は無音より悪いので、
  フェードイン・フェードアウトを掛ける。
- **映像ストリームは再エンコードせずコピーする**。絵は既に決まっており、音を付けるために
  249.5MBをlibx264へ通し直すのは、時間と画質の無駄でしかない。
- **プレビュー**を実装した。人が音楽を選ぶなら、名前の一覧からではなく**自分の作品に
  乗った音を聴いて**選ぶべきである。映像がコピーなので短い試聴の生成は安価。
  実素材で5本（各40秒、映像h264コピー＋音声aac）を生成し、音声が入ることを確認した。

合成fixtureのみで23件のテストを追加。全866件成功、Ruff成功。
**曲の最終選択はユーザー待ち。**

### クラウド構成の設計（[`cloud-architecture-ja.md`](cloud-architecture-ja.md)）

ユーザーの回答「本番＝他ユーザーの走行をクラウドで処理する製品」を受け、構成を設計した。
本書は設計判断であるため、ローカルLLMへは委譲せず自分で書いた。

実測で得た決定的な数字:

| 段階 | 実測 |
|---|---|
| 元動画（MP4全解像度） | **68.1 GiB** |
| LRVプロキシ | 1.9 GiB（元の約36分の1） |
| GPX | 2.56 MiB |
| **採用クリップ（作品に映る全映像）** | **219 MiB** |
| 完成作品 | 249.5 MiB |

**68.1 GiBのうち作品に映るのは219 MiB（0.31%）。転送量は318分の1になる。**

そして既存パイプラインは、意図せずこの分割に適した順序を既に持っている。
「どの30秒を使うか」の判断はGPXとメタデータだけで完結し、画素が必要になるのは
区間確定後の切り出しと、LRVプロキシで足りるハイライト検出だけである。

したがって構成は**エッジで絞り、クラウドで組む**。元動画68.1 GiBは端末から出ない。

移植の障害は調査時点で**1つだけ**（macOS専用のQuick Look）で、これは既に差し替え可能に
してLinux用実装を検証済み。全contractはJSON上の純関数、外部プロセスは全て注入式。

見落とすと危険な項目として、**コンテナのCJKフォント**を明記した。無い場合でも
レイアウトは正しく描画され日本語だけが豆腐になる。エラーにならず目視でしか気づけない。

提出時点の範囲は「ローカル完結の実装＋合成クラウドデモ＋本設計書」とし、**実素材を
クラウドへ送る経路は作らない**。走行映像には第三者の顔・ナンバープレートが写るため、
同意・保持ポリシーが未定のまま外部へ送ることは、この製品が主張している性質と矛盾する。

## 31. 2026-09-03｜実機確認の準備と、ハッカソン要件の再確認

### Gate 3 完了

曲は`rising-tide`（Rising Tide / Kevin MacLeod / CC BY 4.0）を採用した。曲自体が
出発から高まって落ち着く弧を描き、作品の「旅の始まり → 登りが続く → 帰り着くまで」と
重なるため。実素材で音楽入りの作品を生成し、mean −25.1 dB / max −3.3 dBで音が
入っていることを確認した（300.03秒、h264＋aac、257MB）。

### 実行中に発見・修正した2つの実バグ

1. **中断すると壊れた作品が残る**。10分の上限がffmpegを途中で殺し、**240MBの
   再生できないmp4**（moov atom無し）が残った。「完成しているように見えるが違う」——
   本プロジェクトが他の全箇所で防いできた失敗そのもの。修正: レンダーと音楽ミックスの
   両方を、隣に書いてから成功時のみ原子的に置き換える方式にした。中断は「壊れた作品」
   ではなく「作品が無い」で終わり、失敗した再レンダーは前の作品を壊さない。
2. **音楽ディレクトリのパスを推測していた**。packageのパスから導出しており1階層ずれ、
   5分のレンダーが成功した後に「catalogue unavailable」で失敗した。音楽ライブラリは
   個々の走行ではなく導入環境に属するので、導出できるものが無い。**推測をやめ、
   指定を必須にした**。あわせて`--music-only`を追加し、曲の差し替えに5分の再エンコードが
   要らないようにした（絵は変わらず、ミックスは映像をコピーするため）。

### 明日の実機確認の準備

**`app/clock_offset.py`**: 人が判断する唯一の点（カメラとGPSの時計のズレ）を、
推測させずに提案する。

- 両方の時計を読み、どのシフトなら映像が旅の中に**丸ごと**収まるかを評価し、根拠
  （丸ごと収まる録画数・旅のカバー率・両端からの距離）と共に人へ提示する。
- 試すのは**全時間・半時間単位**のみ。カメラの時計は分単位ではなく時間帯単位で狂う。
- **決定はしない。** 候補が拮抗する場合は`is_unambiguous: false`として報告し、
  「一番マシな数字」を押し付けない。曖昧な場合こそ人の判断が要る場面である。
- 設計上の要点: 単に**重なる**録画ではなく**丸ごと収まる**録画で評価する。重なりだけで
  数えると同点が出る（合成4時間rideで2時間ずらしても全録画が重なったままで同点になった）。
  旅の端をはみ出す録画は、そのシフトがカメラをライダーの居ない場所へ置いた証拠である。
- **実素材で検証**: 49本の録画から既知の答え **−46,800秒（−13時間）を曖昧さなく再現**。

**[`demo-runbook-ja.md`](demo-runbook-ja.md)**: 新しい日のGPXと動画から作品までの手順。
記憶からではなく**実際にコマンドを叩いて書いた**。初稿では手順2のフラグが間違っており
（`--video-to-gps-offset-s`は存在せず、正しくは`--clock-offset-s`、GPXと動画は位置引数）、
明日の最初の10分を失うところだった。

予行で見つけたメッセージも直した。イベントと録画が1件も一致しないとき、従来は事実だけを
述べて止まり、「カメラが回っていなかった旅」と「時計のズレで映像が旅の別の場所に置かれた」
を区別できなかった。両者は対処が正反対なので、**両側の件数を示し、まず時計ツールを見るよう
促す**メッセージにした。

### ハッカソン要件の再確認（2026-09-03、ライブ取得）

締切は変更なし: **2026-09-09 14:00 PT = 2026-09-10 06:00 JST**。

確認できた要件と、現状との差:

| 要件 | 現状 |
|---|---|
| 締切 | 変更なし。残り約6日 |
| トラック（IBM / Grafana / Parallel / Clickhouse / Replit） | IBMを選択済み。Bob利用証跡あり。Confluentは推奨であり必須ではない |
| デモ動画3分以内・YouTube/Vimeo・英語または英語字幕 | **未作成** |
| 公開ソースリポジトリ | 公開済み |
| **ホスト済みプロジェクトURL** | **Cloud Runはprivateのまま。公開には別途承認が必要** |
| **Gemini と Google Cloud Agent Builder による agent** | **現状はAgent Platform / AdkApp。Agent Builderではない** |

**要確認の2点**（いずれもユーザー判断が要る）:

1. **Agent Builder要件**。公式文言は「powered by Gemini and Google Cloud Agent Builder」。
   現行実装はAgent Platform（AdkApp / Agent Engine）であり、名称が一致しない。
   審査基準1が「Google Cloudの効果的な利用」であるため、無視できない差である。
2. **公開URLとデモ動画**。どちらも外向きの行為であり、実素材（第三者の顔・ナンバー
   プレートが写る走行映像）を公開するか否かの判断を含む。合成デモで作るか実素材で
   作るかは、ユーザーが決めることである。

## 32. 2026-09-03｜Gate 4着手｜旅の状態を1枚で見る画面

`app/web/private_journey_status.py` と `/private-journey-status` を実装した。
packageの状態を「入力の確認 → 物語の計画 → 作品の生成 → 音楽の追加」の4段で表示し、
作品に出る章テキストと、次に取るべき操作を示す。

### 設計判断

- **読むだけで、何も開始しない。** レンダーは時間と計算資源を使い、やり直しが利かない。
  ページを開いた副作用で始まってよい種類の処理ではないので、GET以外は405で拒否する。
- **次の操作は「名前」で返し、コマンド文字列を返さない。** コマンドにはpackageのpathが
  必要になり、pathこそブラウザへ出してはいけないものである。固定語彙
  （`make_the_film`等）を返し、ページ側が文言へ変換する。
- ブラウザへ出すのは集計値と、**すでに作品の画面に出ている言葉**だけ。event ID、
  asset ID、元動画のファイル名、path、座標、撮影時刻は出さない。章タイトルと本文が
  例外に見えるが、これらはGPSが証明する事実だけから作られ、作品を観る人には見えている。
- **信用できない計画は「問題なし」として表示しない。** 計画が壊れている場合は
  「計画が信用できない」と、packageが読めない場合は「読めない」と、区別して報告する。
  前者は計画を作り直せばよく、後者はそうではないため、読み手にとって対処が違う。
- public demoでは`/private-journey-status`と`/api/private-journey-status`を403で拒否する
  （他のprivate画面と同じ扱い）。

合成fixtureのみで16件のテストを追加（status 13件、web route 3件）。全897件成功、Ruff成功。

### 実素材での確認

```
inputs_checked   done
story_planned    done
film_cut         done
film_scored      done
next_action: watch_the_film        chapters: 8
  旅の始まり     | 15分 · 1.4km · 登り28m / 下り31m      | 12.0 s
  走り続ける     | 1時間1分 · 87.5km · 登り1010m / 下り958m | 12.0 s
```

payloadにprivate識別子が含まれないことを実素材で確認した。

### 使い方（明日の実機確認）

```bash
export RIDE_PRIVATE_JOURNEY_PACKAGE_DIRECTORY="$(pwd)/private-media/work/<package>"
.venv/bin/python -m app.web.server        # ローカル起動
# ブラウザで http://127.0.0.1:8080/private-journey-status
```

## 33. 2026-09-03｜訂正: Agent Builder要件は既に満たしている

### 昨日の報告は誤りだった

第31節で「公式文言は *powered by Gemini and Google Cloud Agent Builder* だが、現行実装は
Agent Platform（AdkApp / Agent Engine）であり名称が一致しない」と、要件との差として
報告した。**これは誤りである。**

Googleの公式ドキュメントを確認したところ、**Agent Development Kit も Agent Engine も
`/agent-builder/` 配下で公開されており、いずれもAgent Builderの構成要素である**。
Agent Builderは「本番でAIエージェントを構築・拡張・統治するための製品スイート」と
説明されている。

したがって本プロジェクトは、要件を**既に満たしている**。

| Agent Builderの構成要素 | 本プロジェクトでの使用箇所 |
|---|---|
| Agent Development Kit（ADK） | `app/agent_runtime/adk_agent.py`（`google.adk.agents.Agent` / `google.adk.models.Gemini`） |
| Agent Engine | `app/agent_runtime/agent_platform.py`（`vertexai.agent_engines.AdkApp`） |
| Gemini | Gemini 2.5 Flash |

**実装を変える必要はない。** 変える必要があったのは文書の側である。

### 実際の問題は用語だった

コードと提出用write-upはSDKの呼称に従って "Agent Platform" と書いており、要件語である
"Agent Builder" が一度も現れなかった。要件を満たしているのに、**審査員が要件語を探しても
見つからない**状態だった。実装の欠陥ではなく文書の欠陥である。

対応として`docs/submission/agent-builder-conformance.md`を追加した。

- 使っている構成要素と、**使っていない構成要素**（Agent Studio、検索・データストア製品）を
  両方明示する。実態より広い主張と読まれないため。
- 各主張の**検証方法**を表で示す（読むファイル、走らせるテスト）。審査員が推測せずに済む。
- 配備済みAgent Engine runtimeが**合成データ専用**であること（2026-08-17に東京で1回検証、
  GPX・動画・座標・撮影時刻を一度も送っていない）を、意図した製品特性として記す。
  走行映像には第三者が写るため、物語を裏付ける素材は端末から出ない設計にしてある。
  その代償は実測でゼロ（68.1 GiBのうち画面に出るのは219 MiB、選定はGPX 2.56 MiBと
  メタデータだけで決まる）。

`project-writeup-en.md`も、ADKとAgent Engineを**Agent Builderの構成要素として**記述する
表現へ更新した。文書に書いた検証コマンドは実際に走らせ、29件成功を確認した。

### 残る提出上の未達（変更なし）

1. **デモ動画3分以内**（未作成）— 実素材を使うか合成デモにするかはユーザー判断。
2. **ホスト済みプロジェクトURL** — Cloud Runはprivateのまま。公開は明示承認が必要。

## 34. 2026-09-03｜デモ台本の書き直し（事実でない主張を含んでいた）

提出前検査（`python -m app.submission`）はローカル項目6件すべて通過。残るのは外部ゲート
（登録・公開・ホスティング・デモ動画）のみで、いずれも承認を要する。

その中で、**単独で進められて最も危険だった項目**がデモ台本だった。

### 発見: 台本が事実でない主張を含んでいた

`demo-script-en.md`は2026-08-24に書かれ、Gate 2〜4の実装より前のものだった。単に
古いだけでなく、**審査提出物として虚偽になる記述**を含んでいた。

| 台本の記述 | 実際 |
|---|---|
| 「Geminiがクリップを評価し、人が映像証拠を確認する」 | **実映像のGemini解析は未承認・未実行**。クリップ単位の証拠確認は2026-09-01決定で時刻照合からの自動判定になっており、人の確認は時計のズレ1点のみ |
| 「Story Agentが映像証拠を要求すると判断する」 | 同上。自動判定に置き換わっている |
| 「Google Cloud Agent Platform」 | 要件語はAgent Builder（第33節） |
| 欠落区間・章カード・地図・字幕・音楽・完成作品 | **台本に一切登場しない**。過去2日で作った製品の中身がまるごと欠けていた |

提出前検査のmedia_gatesも同じ点を警告していた。

### 書き直した台本

実測値だけで構成した（68.1 GiB → 219 MiB、GPX 2.56 MiB、作品300.0秒、
時計のズレ−46,800秒を49本から曖昧さなく再現）。構成は次の通り。

問題の提示 → 証拠は「どこを見るか」しか言わない → 人が答える唯一の問い（時計）→
撮っていない区間を捏造しない（章カードと地図）→ 1コマンドで組み上がる →
Gemini と Agent Builder → IBM Bob 証跡 → 完成作品 → 締め。

台本末尾に「**この台本が決して主張してはならないこと**」を明記した（実映像のGemini解析、
クリップ単位の人手確認、ホスト済みagentが実走行を処理したこと、公開デモに実素材が
あること）。過去の版が実際にそのうち2つを主張していたため。

**[FOOTAGE CHOICE]** として、2:40の区間だけをユーザー判断待ちとして残した。完成作品には
第三者の顔・ナンバープレートが写るため、実素材で撮るかラベル付き合成で代替するかは
ユーザーが決めることである。他の全区間は今すぐ収録できる。

### 字幕の修正

- **3分48秒に伸びていた**。デモ動画の上限は3分ちょうどであり規則違反だった。台本の
  区切りに合わせて26 cue・180.0秒ちょうどへ詰め直した。
- em dashを含んでおりASCII制約に反していた。一部プレイヤーで文字化けするため通常の
  ハイフンへ置換した。

### テストの前提が失効していた

`test_submission_subtitles_keep_unverified_real_media_explicitly_gated`は、字幕に
「REAL MEDIA GATE」「not available in this draft」を**含むこと**を要求していた。これは
「実素材の成果物がまだ無い」という前提の但し書きである。**実素材の作品が存在する今、
この但し書きを残すことは審査員に虚偽を見せることになる**。

テストの本来の意図（未検証の能力を主張しない）は正しいので、**現在も未検証な事柄**に
対する検査へ書き直した: 実映像のGemini解析、クリップ単位の人手確認、実素材のクラウド
送信——これらを字幕が主張していないことを検査する。情報漏洩とASCII制約の検査は別テスト
として残した。

全898件成功、Ruff成功。

## 35. 2026-09-03｜提出用write-upの書き直し（同じ虚偽が入っていた）

第34節でデモ台本の虚偽を見つけたため、**審査員が最も読む文書**である
`docs/submission/project-writeup-en.md`を同じ観点で監査した。同じ虚偽が入っていた。

### 削除した事実でない記述

| 旧記述 | 実際 |
|---|---|
| 「Story Agentが映像証拠を要求し、**Geminiがその区間を解析**し、受入/却下/エスカレーションする」 | 実映像のGemini解析は未承認・未実行 |
| 「選定クリップの**映像証拠が明示的に確認される**まで編集はブロックされる」 | 2026-09-01決定で時刻照合からの自動判定。人の確認は時計のズレ1点のみ |
| 実績欄「明示的なconfirmed/rejected映像証拠遷移」 | 同上。実績として書けない |
| highlight research「人手レビューで止まる」 | 同上 |
| 残課題「利用者の映像確認を完了し、承認済みhighlightをStory Planと編集へ接続する」 | 既に完了または方針変更で消滅 |

### 欠けていた内容（製品の中身がほぼ全部）

旧版は欠落区間、章カード、地図、字幕、音楽、1コマンド化、時計のズレ提案、状態画面、
そして**完成した300.0秒の作品そのもの**に一切触れていなかった。実測値（68.1 GiB →
219 MiB、GPX 2.56 MiB）も無かった。過去2日で作ったものが提出文書に存在しなかった。

### 書き直しの方針

- 冒頭に「**ここに書かれた計測値はすべて1回の実走行から得たもので、リポジトリから
  再現できる。実行していない能力は一切記述しない**」と明記した。
- 「What it does」を、実際の動作順（GPS→時計の1点確認→欠落区間の章カード化→
  1コマンドで作品）で書き直した。
- 「Challenges」に、実際に踏んだ設計上の困難を書いた: 作品は映像だけではないこと
  （尺判定が測る対象を間違えていた）、1つのgateが性質の違う2つの問いを同時に
  していたこと、カメラの時計は分単位ではなく時間帯単位で狂うこと。
- 「What we learned」を追加した。**興味深い失敗のほとんどは、システムが静かに
  「間違ったことに成功していた」形を取った**——映像を測っていた尺判定、indexの無い
  240MBの「完成して見える」mp4、自分のserializeを往復しない計画、実行していない
  解析を語るデモ台本。fail-closed gateは騒がしい失敗を捕まえるが、静かな失敗は
  「測っている対象は本当に重要な対象か」を繰り返し問うことでしか捕まらない。

監査後、除去すべき5つの記述が残っていないことと、記載した6つの実測値が実データと
一致することを機械的に確認した。全898件成功、提出前検査のローカル6項目すべて通過。

## 36. 2026-09-03｜審査基準対応表とアーキテクチャ図の書き直し

第35節で予告した2件を監査・書き直した。いずれも2026-09-01付でGate 2〜4より前のもの。

### `judging-alignment.md`（審査4基準への対応表＝採点に直結）

削除した失効記述:

- 「明示的なawaiting / confirmed / rejected映像証拠遷移」— 2026-09-01決定で自動判定
- 「外部転送も**自動確認**もなく4組のレビューセットを生成」— 現在は自動確認である
- 「あらゆる映像上の主張はタイムスタンプ解決と**明示的な証拠**でgateされる」— 同上
- 「**計画中の**作品」— 作品は存在する

**解消済みなのに「Still required」に残っていた4件**を削除した。実素材の
source-to-confirmed-edit証跡（作品が存在する）、Agent Builder表記（第33節で解決）、
音楽の帰属記録（`music-credits.md`）、ワークフロー統合（1コマンド化済み）。
**未達でないものを未達として提出する状態だった。**

追加した根拠は、1コマンドでの作品生成（300.0秒・15 beat・字幕8cue）、時計のズレ提案
（49本から−46,800秒を曖昧さなく再現）、章カードのOS描画とmacOS/Linux一致検証、
中断しても壊れた作品を残さないrender、898件のテスト、実測値（68.1 GiB → 219 MiB、
判断はGPX 2.56 MiBのみで完結）。

「時間短縮率は計測するまで公表しない」という旧版の抑制は正しいので残した。文書末尾に
「**この文書が主張してはならないこと**」を追記した（過去版が2件主張していたため）。

### `architecture.md`（提出用アーキテクチャ図）

図が現状と違っていた。「人手の映像証拠確認」「未統合のmanual handoff」「無音ドラフト
render」が残り、欠落区間・章カード・物語計画・字幕・音楽・時計提案・状態画面が無かった。

**図自体のバグも修正した**: ノードID `Plan` が「Inspectable FFmpeg plan」と
「Credential-free Cloud Run plan」という別物2つに使われていた。

描き直した図では、**人の入力が1本の太線だけ**であることが視覚的に分かるようにした。
また「What the diagram is claiming / is not claiming」を明文化し、点線のクラウド経路が
uploaderではないこと、ホスト済みruntimeが合成専用であることを、図の読み手が推測せずに
済むようにした。

ノードID重複なし・subgraph均衡を機械的に検証。全898件成功、提出前検査ローカル6項目通過。

## 37. 2026-09-03｜README（公開リポジトリの表紙）の訂正

提出文書5件の監査後、**審査員がソースリンクから最初に見る**README.mdにも同じ陳腐化が
残っていたため訂正した。テストはREADMEの存在のみを要求しており内容には依存しない。

### 直接的な虚偽だった記述

> 「映像証拠は人が明示的に確認または却下するまで`awaiting_video_evidence`のまま。
> ローカルの候補生成がクリップを自動確認することはない。」

2026-09-01決定により、クリップ単位の証拠は時刻照合から自動で決まる。**公開リポジトリの
表紙に、現在の動作と正反対の説明が載っていた。**現在の記述に直し、旧設計の待ち行列が
消滅したことも明記した。

`/private-evidence-review`画面の記述は残した。この画面は今も存在し、**自動判定を人が
上書きする経路**として機能するため。ただし「通常の経路ではなく上書きである」ことを
明示した。

### その他の訂正

- 冒頭の要約とフロー図が旧ループ（Story Agentが証拠を要求→media search→analyser）の
  ままだった。現在の流れ（GPS event → 時刻照合 → 欠落区間 → 物語 → 章テキスト →
  カード・連結・字幕・音楽）へ描き直し、**人の確認が1点だけである**ことを明記した。
- 「Agent Builder互換性を確立するものではない」→ 第33節で解決済みのため、
  conformance文書への参照へ差し替え。「Agent Platform」表記もAgent Engineへ。
- highlight選定の「最終的な採否は人手レビュー」→ 選定は**時刻照合で既に解決済みの
  クリップを絞る**だけであり、照合されていない映像を追加できない、という正確な記述へ。
- 「Current real-media status」が2026-08-30の研究run止まりだった。**完成作品が存在する
  事実**（300.0秒・confirmed 7・章カード8・Gate 1通過・coverage 1.0）と実測値
  （68.1 GiB → 219 MiB、判断はGPX 2.56 MiBのみ）を先頭に置いた。

### 最大の欠落: 作り方が書いていなかった

READMEに**作品を生成する実際のコマンドが1つも載っていなかった**。規則が求めるのは
「judging and testingのための公開リポジトリ」であり、審査員がcloneして何を実行すれば
よいか分からない状態だった。3コマンド（時計の提案 → package生成 → 作品生成）と、
曲の差し替え（再エンコード不要）、状態画面の起動方法を追加した。

**記載した4モジュールと7フラグが実在することを機械的に検証した。**
全898件成功、Ruff成功、提出前検査ローカル6項目通過。

## 38. 2026-09-03｜作品を元素材（4K）から切り出すよう変更

### 発見: 完成作品がレビュー用プロキシから作られていた

元素材は **3840×2160 / 60 Mbps**、作品は **1280×720**。**画素数で9分の1**を出力していた。
原因は、作品の映像segmentを`review-clips/`（人がブラウザで候補を確認するために作った
720pプロキシ）から取っていたこと。

かつては「人が観て確認したものがそのまま出る」という理屈が成り立った。しかし
**2026-09-01決定でクリップ単位の証拠は時刻照合から自動で決まる**ようになり、
誰もプロキシを観ないため、この理屈は既に失効していた。プロキシは単なる低画質の複製に
なっていた。

### 変更

- `FootageSource`（録画ファイルと、その中のどこから切り出すか）を導入し、
  `StoryFilmSegment`に`source_start_s`を追加した。
- footage segmentは `-ss <開始> -i <録画>` の順で指定する。**入力の前にseekする**ことで、
  1時間先の窓でもデコードせずに跳べる。
- `_confirmed_footage_sources`が、candidate exportのasset_id＋offsetとcatalogの
  file_nameから、`video_root`配下の実録画を解決する。カタログ名がpathの形をしていれば
  拒否する（ディレクトリ脱出の防止）。録画が移動していれば「no longer where it was」で
  fail closedする。
- **作品を1080pへ、カードのラスタライズを1920正方形へ**引き上げた。カードは16:9を
  中央から切り出すため、正方形の一辺は作品の横幅と一致していなければならない
  （小さく描いて拡大すると文字が甘くなる）。

クリップの同一性はevent IDと窓が担保しており、プロキシではない。したがって元素材へ
戻しても、人手の却下・再オープン（`/private-evidence-review`）の結果は保たれる。

合成fixtureのみで5件のテストを追加（元素材から切り出すこと、プロキシを使わないこと、
録画が移動した場合、カタログ名がpathの場合、負のオフセット）。全903件成功、Ruff成功。

## 39. 2026-09-03｜ユーザー決定: デモ動画は実素材を使う

`[FOOTAGE CHOICE]`として空けていた台本2:40の判断が確定した。**実素材を使う。**

台本に記録し、あわせて実務上の注意を明記した。

- 公開されるのは**選んだ15秒の抜粋のみ**であり、作品全体ではない。
- その抜粋に判読可能なナンバープレート・識別可能な顔が含まれていないか、公開前に確認する。
  可能なら開けた道の区間を選ぶ。
- 章カードにはルートの形が描かれる。これも公開対象に含まれる。

**混同を避けるための区別を明記した**: 「公開デモに実素材は無い」は**ホスト済みアプリ**の
話であり、**デモ動画**とは別物である。アプリは合成データのみを扱い続ける。

締めの文言も調整した。旧「without ever leaving your machine」は、実素材の抜粋を公開する
今回の判断と並べると誤解を招く。**処理がローカルで完結すること**と、**所有者が抜粋を
公開するという別個の意図的行為**を分けて述べる表現へ変更した。

### 実素材での再生成結果（1080p）

```
film        1920×1080 / 30fps / 300.13秒 / 749.0MB
scored      1920×1080 / 300.07秒 / 756.4MB / 音楽 mean −25.2 dB
plan        beat 15 / meets_target true
subtitles   .srt / .vtt
local_only true / external_data_sent false
```

t=296秒の章カードフレームを1920×1080で取り出し、日本語タイトル・本文・ルート地図が
いずれも鮮明に描画されることを目視確認した。旧720p版は削除した。

ファイルサイズは249.5MB（720p）から756.4MB（1080p）へ増えた。ローカルのprivate成果物
であり、公開するのはデモ動画の15秒抜粋のみであるため、この増加は許容する。

## 40. 2026-09-03｜字幕と映像の一致を実素材で検証し、不変条件として固定

### 検証していなかったこと

字幕は物語計画のbeat尺から生成し、映像も同じ計画から切り出す。**しかし両者が一致する
ことを確かめたことが無かった。** ずれていれば、公開するデモ動画の字幕が別のカードを
説明することになる。

### 実素材での確認

1080p版の作品に対し、8つのcueそれぞれの開始0.5秒後のフレームを抽出した。

- 全8フレームが90〜110KB（映像フレームは約1.9MB）＝**すべてカード上に着地**
- cue 6（`204.0-216.0s 登りが続く / 1時間17分 · 91.8km · 登り1348m / 下り1067m`）の
  フレームを目視し、**まさにその内容のカードが表示されていること**を確認
- cue境界の直後・直前（12.5s / 41.5s / 133.9s）は1.9〜2.1MB＝**映像に戻っている**

**ずれは無かった。**

### 不変条件として固定

一致は偶然ではないが、**保証しているものが何も無かった**。字幕と映像は同じ計画から
**別の経路**で作られる（`app.story_film`はbeatをFFmpeg入力として並べ、
`app.story_subtitles`はcue時刻として並べる）。片方だけ変更すれば静かにずれ、
完成作品を観るまで気づけない。これは本プロジェクトが繰り返し踏んできた
「静かに間違ったことに成功する」失敗そのものである。

`tests/test_film_and_subtitles_agree.py`で7件の不変条件を固定した。

- 全cueが、映像segmentから歩いて求めたカード位置と一致する（footage 1/3/6本で検証）
- cueの文言が、そのカードの文言と一致する
- 作品と字幕が同時に終わる
- **cueが映像区間へはみ出さない**（映像上では何も語られていないため）
- 言語を変えてもcueが1つも動かない（絵を作り直さずに言語を変えられる）

### テストが実際にずれを捕まえることの確認

**変異テストを行った。** 字幕側の歩進をカードbeatだけ進むように壊すと、7件中5件が失敗し、
元に戻すと全て通った。捕まえないテストは飾りであるため、この確認を行った。

全910件成功、Ruff成功。

## 41. 2026-09-03｜設計の是正（1）目標尺への水増しを廃止

### 前提が撤回された

ユーザーの回答により、次が確定した。

1. **採用区間は増やせるし、増やす方が良い**
4. **尺は伸縮可能。5分くらいになれば良い**

これで、目標尺に届かせるための機構が根拠を失った。その機構は本来、
**ローカルのゲートが厳しすぎて採用区間が7本しか残らなかったこと**への対処であり、
症状に薬を塗っていたに過ぎない。

### 削除したもの

- `gap_chapters._allocate_shortfall`（不足尺をカードへ配分する water-filling）
- `DEFAULT_EXTENDED_CARD_S`（不足時にカードを12秒まで伸ばす上限）
- `GapChapterPlan.residual_shortfall_s` / `meets_target`
- `JourneyStoryPlan.target_duration_s` / `residual_shortfall_s` / `meets_target`
- `PrivatePackageHealth.target_duration_s` / `missing_duration_s` / `coverage_ratio`
- `REASON_INSUFFICIENT_CONFIRMED_DURATION`（Gate 1 のブロッキング理由から）
- `private_journey_film`の**2段階gate**——これは「作品が目標尺に届くか」が計画前には
  事実ですらなかったために必要だった構造で、問い自体が消えたため1段へ戻した

計画schemaは`journey-story-plan-v2`へ上げた。

### 残したもの

カードの尺は`story_timeline`が与える値（走行時間に比例、下限3秒・上限8秒）のまま。
これは目標とは無関係に成立する緩急の規則である。

### 実素材での結果

```
beats 15（footage 7・カード8）
footage 210.0秒 → 作品 254.2秒（従来は300.0秒へ水増し）
Gate 1 ready: True / blocking: []
```

**作品は素材どおりの長さになった。** 短ければそれは「選定が厳しすぎる」という情報であり、
renderを拒む理由ではない。採用区間を増やせば作品は自然に伸びる。

全901件成功、Ruff成功。

## 42. 2026-09-03｜追加要件：プロキシ動画に依存しない

ユーザー指示: **「プロキシ動画はなくても動作するようにする必要があります。ローカルで、
低解像度映像を作成するのは、良いアイディアです。」**

私の設計案ではGoProのLRVプロキシ（1.9 GiB）をローカル解析の入力に想定していたが、
**LRVは常に存在するとは限らない**。他機種、設定、撮影方法で欠ける。他ユーザーの走行を
処理する製品では前提にできない。

したがって: **元素材からローカルのffmpegで低解像度の解析用プロキシを生成する。**
LRVがあれば使ってよいが、無くても同じ経路が成立しなければならない。これは
Gemini へ渡す前段（段2のアップロード用素材の生成）と同じ仕組みで賄える。

## 43. 2026-09-03｜費用の見積もりと、段を増やして削る仕組み

ユーザー決定: **画質は2段**（判定用の低解像度→採用分だけ最終画質）、**費用上限 ¥500**、
厳しければ3段4段で削る方法を作る。

### まず価格を確認した（推測しない）

第三者ブログには「動画は**1秒あたり $0.15**」とあった。これだと候補200本×12秒で
約¥54,000となり予算の100倍になる。**この数字は誤り**で、公式のメディア・トークン化に
当たり直した。

| | トークン |
|---|---|
| 低解像度フレーム | 66 |
| 高解像度フレーム | 258 |
| 動画（低解像度） | 約100 / 秒 |
| 動画（高解像度） | 約300 / 秒 |

Gemini 2.5 Flash: 入力 $0.30/1M、出力 $2.50/1M。

### 実測見積もり（候補202本）

```
local-metrics (free)          202 -> 202   $0.0000
gemini-stills (screening)     202 ->  71   $0.0181
gemini-video (full)            71 ->  21   $0.0699
                                    合計   ¥13.2   （上限 ¥500）
```

**¥500 は全く厳しくない。** 一段で全202本を動画解析しても ¥29.8 で収まる。

### 段を増やすと高くなる、という発見

素直に段を足したところ、**カスケードの方が高くなった**（¥31.2 対 ¥29.8）。原因を
辿ると、**出力トークンが支配的**だった。

| | 1候補あたり |
|---|---|
| 動画12秒の入力（1,200 tok） | $0.000360 |
| 本解析の出力（250 tok） | **$0.000625** |

出力は入力の約8倍の単価である。したがって**選別段が本解析と同じ出力を返すと、入力を
削っても出力で損をする**。選別する候補の分だけ、支配的な費用を余計に払うことになる。

対処: **選別段は「スコアと採否」だけを返す**（12トークン）。これで

```
カスケード ¥13.2 ／ 一段のみ ¥29.8 ／ 削減 56%
```

`stills_stage(..., screening=True)` を既定とし、`screening=False` との比較を
テストで固定した（**素直な段追加は費用が増えることを、テストが示す**）。

### 予算は支出前に強制する

`app/analysis_budget.py` は、**請求書を見て気づくのではなく、送る前に見積もる**。

- 見積もりが上限を超えたら、カスケードを**締める**（通す候補を減らす）
- 締める対象は高い段の**手前**の段である。**段自身の keep_ratio を絞ってもその段の費用は
  下がらない**（下がるのは後続だけ）。ある段の請求額を決めるのは、そこへ到達する候補数、
  すなわち手前の段である。無料のローカル段が最良の絞り先になる。
- 最終段の keep_ratio は触らない。後続が無いので、絞っても結果を失うだけで1円も浮かない。
- 最も締めても収まらない場合は**実行しない**。誰も使わない答えに予算の一部を使うのは、
  何も使わないより悪い。
- 価格と為替は**定数ではなく引数**。古い数字が黙って見積もりを狂わせることを防ぐ。

合成fixtureのみで21件のテストを追加。全922件成功、Ruff成功。

## 44. 2026-09-03｜プロキシ動画が無い素材で解析できなかった不具合

ユーザー要件「**プロキシ動画はなくても動作するようにする必要があります**」に対し、
現状を調べたところ**実際に動かない状態だった**。

### 症状

窓解析`analyze_local_highlight_windows`は、対応するLRVプロキシが見つからない録画に対して
**元のMP4へフォールバックする**よう既に実装されていた。しかし入口の
`discover_and_extract_highlights`の既定解析器が`analyze_lrv_metrics`——**LRV以外を
拒否する版**——であり、それが内側へそのまま渡っていた。

したがって、フォールバックが正しくMP4を選んでも、解析器がそれを受け取らず
`analysis input must be an existing non-symlink LRV file`で停止する。
**フォールバックは存在したが、既定の配線がそれを無効化していた。**

LRVは機種・設定・撮影方法で欠ける。他ユーザーの走行を処理する製品では前提にできない。

### 修正

既定を`None`にし、内側の安全な既定（`analyze_video_metrics`、LRV/MP4/MOVを受け付け
320pxへ縮小して解析）が効くようにした。モジュールのdocstringも、
「LRVプロキシを解析する」から「各録画を解析する。対応するプロキシがあればそれを優先し、
無ければ元ファイルへ落とす」へ改めた。

### テストが実際に不具合を捕まえることの確認

新テストは、入口の既定解析器を取り出し、プロキシの無い`.mp4`に対して呼ぶ。
**修正を戻すと落ち、戻すと通る**ことを確認した（`ValueError` at line 333 → 12 passed）。

全923件成功、Ruff成功。

## 45. 2026-09-03｜アップロード用の低解像度素材をローカルで作る

`app/analysis_proxy.py`。Gemini へ渡すために、候補区間を送れる大きさへ落とす。
**プロキシ動画を前提にしない**——カメラが書いた元ファイルから作る。

### 小さくするのに効いた3点（いずれも判定を損なわない）

- **フレームレート**。Geminiは動画を毎秒1枚程度で標本化する。**同じ1 fpsで符号化すれば
  解析は一切損なわれず、バイト数だけが激減する**。30 fpsで送れば30倍のデータを送って
  捨てられることになる。
- **解像度**。低メディア解像度ではフレームは大きさに関わらず一律66トークンなので、
  道と景色が読める以上の画素は何も買わない。短辺480pxとした。
- **音声**。落とす。エンジン音と風切り音であり、毎秒32トークンを課金され、判定は聴かない。

stills（選別段用）は同じ窓から等間隔で抜く。**先頭数秒ではなく等間隔**にするのは、
候補の最初の一瞬がその候補を代表しないため。

### 実測（実素材、4K 3840×2160 / h264 / 60 Mbps）

| | |
|---|---|
| 12秒のプロキシ動画 | **516.9 KB**（2.2秒） |
| stills 3枚 | **184.9 KB**（3.0秒） |

カスケードに当てはめると:

```
stills を202本分   37.3 MB
clips を71本分     36.7 MB
送信合計           74.0 MB
元素材             69,734 MB
                   942分の1
```

**68.1 GiB を 74 MB にして送る。** 家庭用回線の上りでも数十秒である。

### 書き込みの規律

プロキシは隣に書いて完成後に原子的に置き換える。stillsは一時ディレクトリへ全部書いてから
まとめて移す——**半端な枚数が残ると、選別段がそれを完全な組と取り違える**ため。
元ファイルのsymlinkは拒否する。

合成fixtureのみで14件のテストを追加。全937件成功、Ruff成功。

### 未解決の観測

最初の実行が10分を超えて中断した。同じ処理が再実行では5秒で完了し、**再現しなかった**。
素材は内蔵ボリューム上にあり外部ドライブではない。原因を特定できていないため、
**実測値（2.2秒／3.0秒）は再現後のものである**ことを明記しておく。明日の実機確認で
初回アクセスが遅い場合は、この観測を思い出すこと。

## 46. 2026-09-03｜Geminiの判定を採否へ繋ぐcontract

`app/gemini_selection.py`。**これが製品に欠けていた接合部**である。GPSが候補を安く絞り、
`analysis_proxy`が送れる大きさへ落としても、**判定を読み返して行動する部分が無ければ、
モデルは誰も聞いていない映像を見ていることになる**。

### 2つのスコアは別の問いに答えている

- `visual_interest_score`: その瞬間は観る価値があるか
- `story_relevance_score`: この旅の物語に居場所があるか

**駐車場の見事な映像は前者が高く後者が低い。** 前者だけで作った作品は、旅ではなく
リールになる。既定は物語側を重くした（0.6対0.4）が、**重みは埋め込まず引数**にした。

### confidenceは平均に混ぜない

**確信のある中程度の判定は、確信のない絶賛より価値がある。** したがって低confidenceは
スコアに溶かさず、候補を除外する。曖昧な判定は「静かな否定」ではなく「判定が無い」
として扱う。

### 間隔

スコア順に貪欲に採るが、**既に採った区間に近すぎる候補は落とす**。良い1分から5本採れば、
その1分についての作品になってしまう。旅は続いていた。間隔は開始時刻ではなく**窓と窓の
間**で測る（長いクリップは開始が離れていても路上では隣接しうるため）。

### 尺は目標であって割り当てではない

十分な映像が集まれば選定を止めるが、**足りなければ短い作品になるだけで、水増ししない**
（第41節の方針と同じ）。

### 説明可能性

全候補に固定reason codeの判定理由が付く: `selected` / `not_analysed` /
`confidence_below_floor` / `score_below_floor` / `too_close_to_a_stronger_clip` /
`film_already_long_enough`。

`to_dict()`は**モデルの文章を一切引用しない**。event ID、asset ID、`visual_description`、
`scenery_tags`、`road_type`のいずれも出さない。モデルが「赤い車、ナンバー XYZ 123」と
書いても、報告に現れるのは採否・理由・スコアだけである。テストで固定した。

合成fixtureのみで17件のテストを追加。全954件成功、Ruff成功。

### 未接続

この contract はまだパイプラインへ配線していない。`VideoAnalysis`を実際に得るには
アップロードと課金呼び出しの承認が要る。**承認前に実行できる部分をここまで作った。**

## 47. 2026-09-03｜判定を保存し、作品へ配線した

### 判定を書き留める（`app/analysis_record.py`）

解析はこの系で**唯一お金がかかる工程**である。記憶の中だけに置けば、作品を切り直すたびに
買い直すことになる。したがって判定は、元になったexportの隣に書き出し、再実行はそれを読む。

書き留めることは**検証可能性**でもある。選定に異議を唱えられるのは、その根拠となった判定を
読み返せる場合だけなので、記録には判定結果だけでなく**モデル自身の記述とスコア**を残す。

event IDとasset IDを含むためprivate artifactであり、git管理外のpackageにのみ置く。

### 作品への配線（`app/private_journey_film.py`）

**判定があれば、それが「どのconfirmedクリップを実際に使うか」を決める。** これが判定を
買う目的そのものである。

- **記録が無ければ従来どおり**全confirmedクリップを使う。解析を実行していない、あるいは
  実行できなかった場合でも、作品は作れる。
- **記録が読めない場合はfail closedで停止する。** 黙って従来動作へ落ちると、
  「判定に金を払った作品」とは別の作品が切られ、**それが起きたことに誰も気づかない**。
- 判定が全クリップを却下した場合も停止する（何も映らない作品を黙って作らない）。

### テスト

- 記録が無い → 全confirmedクリップが使われる
- 記録がある → 低スコアのクリップが落ちる
- confidenceが低い → 除外される（曖昧な判定は否定ではなく判定の不在）
- 記録が壊れている → 停止する

合成fixtureのみで20件のテストを追加。全967件成功、Ruff成功。

### 承認待ちで残っているもの

**アップロードと初回の課金Gemini呼び出しだけ**である。それ以外——ローカルの低解像度素材生成、
費用見積もりと予算強制、判定の保存、判定から採否への変換、作品への配線——はすべて実装済みで、
合成fixtureで検証済み。**判定が手に入った瞬間に作品が変わる状態になった。**

## 48. 2026-09-03｜送信と判定の実行部（承認の材料を含む）

`app/analysis_run.py`。**機外へ出る工程**なので、2つに分けた。

- `plan_analysis_run`: packageを読み、**何を送りいくらかかるか**を報告する。副作用ゼロ。
  **支出の承認を求める相手へ出すのはこれである。**
- `run_analysis`: 実際に行う。**アップローダと解析器を引数で渡さないと動かない**
  （既定値なし）。Googleへ到達しうるimportはこのモジュールに無い。
  黙って支出を始められる形は、この判断の手前に置くモジュールとして誤りである。

失敗した候補は飛ばさない。**判定の欠けた記録は「モデルが何も言うことがなかった」記録と
区別がつかず**、選定は黙って別の作品を切ってしまう。

### 実素材のdry runで設計の誤りが出た

最初の実行結果:

```
candidate 7 → gemini-stills 7→2 → gemini-video 2→1     費用 ¥0.55
```

**7本の候補が1本まで絞られた。1本の作品は作品ではない。** keep ratioは候補約200本を
想定した値であり、小さな素材では枯れる。

原因は私の設計上の混同である。**カスケードは予算に収めるための機構であって、クリップを
選ぶ機構ではない。** 選ぶのは判定が揃った後の`gemini_selection`の仕事である。
¥0.55対¥500で予算は制約になっていないのに、費用のための絞り込みが品質の選定を
横取りしていた。

既定のkeep ratioを1.0（全部通す）に変え、**予算が制約になったときだけ
`plan_cascade_within_budget`が締める**ようにした。

```
candidate 7 → 7 → 7     費用 ¥1.7 / 送信 10.3 MB
```

テストで両方向を固定した（小さな素材は枯れない／予算が効くときは締まる）。

合成fixtureのみで16件のテストを追加。全983件成功、Ruff成功。

### 承認の材料（実素材、現在のpackage）

| | |
|---|---|
| 判定する候補 | **7本**（時刻照合で解決済みの全クリップ） |
| 送信するもの | 候補の低解像度stillsと短いプロキシのみ **10.3 MB** |
| 送らないもの | 元の4K素材 68.1 GiB |
| 費用見積もり | **¥1.7**（上限¥500） |

なお候補が7本しかないのは、ローカルのゲートが厳しすぎるためである（実績では
2,385窓→202候補→21本→confirmed 7本）。**「採用区間を増やす」作業は未着手**で、
これを行えば候補は約200本になり、費用は¥13程度になる見込み。

## 49. 2026-09-03｜候補が少ない本当の理由（測って分かった）

「採用区間を増やす」ため、まず**目標尺の上限が効いていると想定して**
`select_video_backed_events`を緩めようとした。**測ったら外れていた。**

```
GPS events total      : 24
selected at target 300: 7
selected with no cap  : 7    ← 上限を外しても同じ
```

上限は制約になっていない。**24個のGPSイベントのうち、映像があるのが7個しかない**のが原因。
ゲートを緩めても1本も増えない。

### さらに測ると、映像は大量にあった

```
ride duration : 4.2 h
camera ran for: 2.3 h  (走行の55%)
GPS events    : 24  → うち映像内にあるのは 7
```

**カメラは2.3時間回っていたのに、システムが候補にしていたのは7×30秒＝3.5分だけ。**
GPSがイベントを立てた場所しか見ていないためである。

### GPSイベントと手持ちの映像は、ほとんど別物である

GPSイベントは「**旅のどこで何かが起きたか**」に答え、録画は「**どこでカメラが回っていたか**」に
答える。この2つは設計が想定していたよりはるかに重ならない。GPSイベントは「見る理由」としては
妥当だが、**唯一の理由として扱うと、何も判定しないうちに映像の大半を捨てる**ことになる。

### 対処: 候補を映像そのものから引く（`app/footage_candidates.py`）

録画のうち走行時間内に収まる窓を、一定間隔で列挙する。窓は**自分自身の時間範囲から
識別子を導く**ので、2回実行しても同じ候補になり、別経路で見つかった同じ窓は1つに畳まれる。
出発前・到着後の映像、録画の末尾をはみ出す窓は除く。カタログのメタデータとGPXしか読まず、
**動画は開かない**。

判定はしない。ローカル指標での絞り込みは呼び出し側の選択であり、**寛大に列挙する目的は、
判定にカメラが実際に見たものを見せること**である（ローカル＝再現率、Gemini＝適合率）。

### 実素材での結果

| | |
|---|---|
| 従来の候補 | **7**（GPSイベント∩映像） |
| 映像から引いた候補 | **173** |
| 判定費用 | **¥27.9**（上限¥500） |
| 送信量 | 121 MB（元の4K 68.1 GiBは送らない） |

**24倍の候補を、予算の6%で判定できる。**

合成fixtureのみで12件のテストを追加。全995件成功、Ruff成功。

### 未接続

この列挙はまだ`plan_analysis_run`へ繋いでいない。繋ぐとcandidate exportではなく映像窓が
判定対象になり、`plan_journey_film`側も窓由来のclipを扱えるようにする必要がある
（既存のhighlight bridgeと同じ形になる）。次の作業単位とする。

## 50. 2026-09-03｜映像由来の候補を、判定と作品へ配線した

第49節で作った列挙を、両端へ繋いだ。

### 判定側（`plan_analysis_run`）

candidate exportではなく**映像の窓**を判定対象にした。実素材で **7 → 173候補**、
費用¥27.9、送信121.3 MB。予算による締め付けは発生しない。

### 作品側（`plan_journey_film`）

判定は「GPSイベントが偶然入っていたクリップ」より**広い集合**についてのものなので、
判定がある場合はその集合を**絞り込むのではなく置き換える**。

- 判定あり: 採用された窓から映像を組む。窓の絶対時刻はカタログの録画開始＋時計補正＋
  オフセットで求まるので、candidate exportは要らない。
- 判定なし: 従来どおりconfirmed済みclipを使う。
- 判定が読めない: 停止する（第47節と同じ理由）。

レンダー側の`_confirmed_footage_sources`も同じ規則にした。**判定済みpackageの作品は
判定された窓から切られるので、素材の解決も同じ出所から行う**——古いcandidate exportを
読むと、計画がもう名指していないクリップを探しにいくことになる。

### 実素材での結果

```
candidates : 173   (GPSイベント由来では7)
upload     : 121.3 MB
cost       : ¥27.88   (上限¥500、締め付けなし)
```

合成fixtureのみでテストを更新し、全996件成功、Ruff成功。

### これで承認待ちの1点だけが残った

**送信と課金**以外は繋がった。承認が得られれば、173本の窓をGeminiが判定し、その判定が
作品の中身を決める——**製品の核心が動く状態**である。

## 51. 2026-09-03｜経路全体を通し、配線のバグを発見・修正

各部品には単体テストがあったが、**列挙 → 判定 → 計画 → 作品を一度も通していなかった**。
金を使う前に、そして明日の実機確認の前に通した（Geminiの位置にはstubを置く。
stubが代わりを務めるのは**唯一お金がかかる工程**で、その前後はすべて本物を動かす）。

### 見つかったバグ

`plan_journey_film`が、判定がある場合でも`ride-storyteller-candidates.json`を
**無条件に読んでいた**。判定済みpackageはその export を必要としない——作品の中身は
どれ一つそこから来ない——のに、無ければ`FileNotFoundError`で落ちる。

**単体テストは常に完全なpackageを用意していたため、この依存は見えなかった。**
これは製品として重要で、**映像の窓だけから組み立てたpackage（クラウド経路がまさにそれ）
には candidate export が存在しない**。

修正: 確認済みclipから組む経路を`_confirmed_clip_footage`へ分離し、**判定がある場合は
呼ばない**ようにした。判定済みpackageは candidate export を一度も開かない。

`_confirmed_footage_sources`側は既に早期returnしており同じ欠陥は無かった（統合テストで確認）。

### 通した内容

- 60候補の列挙（2本の録画、30秒間隔）
- stubによる判定（一部を高評価、残りを低評価）
- 計画が**高評価の窓だけ**を使うこと、出発と到着が章カードで挟まれること
- 作品のsegmentが**元の録画から、判定された窓のオフセットで**切られること
- 判定が何も採らなければ計画前に停止すること
- **2回目は判定を読み直し、解析器を呼ばないこと**（解析は唯一お金がかかる工程）

全1000件成功、Ruff成功。

---

## 52. 送るものを作る工程と、送る工程が繋がっていなかった（`analysis_run`）

前節の統合テストはstubの`upload`を渡していたため、**渡すファイルが無いこと自体**を
見逃していた。`app.analysis_proxy`は縮小コピーを作り、`run_analysis`はアップロードする
——が、**両者を繋ぐコードがどこにも無かった**。`upload`が受け取るのは候補のメタデータ
（asset_id とオフセット）だけで、送るべき実体が渡らない。

これは承認後に効く欠陥だった。承認をもらってGCSアダプタを書き始めた時点で、
アップローダ側が「どの窓をどう縮小するか」を**もう一度決め直す**羽目になる。
それはこの層が既に決めたことで、二箇所に置けば必ずずれる。

### 変更

`run_analysis`が候補ごとに縮小コピーを作り、**そのファイル**をアップローダへ渡す。

```python
upload: Callable[[Path, AnalysisCandidate], str]  # ファイルを受け取りURIを返す
analyse: Callable[[str, AnalysisCandidate], VideoAnalysis]
make_proxy: Callable[[AnalysisWindow, Path], Path] = write_proxy_clip
```

`make_proxy`だけ既定を持つ。**縮小はローカルで完結し無料**だから。`upload`と`analyse`は
機外へ出て、片方は課金するので既定を持たない——呼ぶだけで金が動く形にはしない。

`upload`の契約が「ファイルを受け取ってURIを返す」だけになったのが要点。
アップローダは何も判断しない。

コピーは`analysis-proxies/`にpackage内保存。判定を買い直す羽目になったときに、
送るものまで作り直す理由は無い。

### privacy

`_source_recording`は catalog のファイル名を**ride自身のvideo_root配下でだけ**探し、
名前にパス区切りが含まれるものとsymlinkを拒む。

テストで固定した不変条件:

- **アップローダに渡るのは常に縮小コピーで、原本ではない**（原本は68.1 GiB）
- 各コピーは自分の窓のオフセットから作られる
- コピーはpackage内に残る
- 録画が移動していれば判定を買う前に停止する
- `make_proxy`の既定は本物の`write_proxy_clip`

全1005件成功、Ruff成功。

---

## 53. 承認後に書くはずだった2つのアダプタ（`analysis_adapters`）

`run_analysis`はアップローダと解析器を必須引数で受け取り、どちらにも既定を持たない。
その**中身**が未実装だった。書くこと自体は実行ではないので、承認前に書ける。

### ここに静かに間違った映像を切る罠がある

候補のオフセットは**原本の録画の中の**位置（例: 1830s→1842s）で、作品はそこを切る。
だがアップロードされたのは**0秒から始まる12秒の独立クリップ**である。
12秒のクリップに対して「1830秒から1842秒を見て」と頼めば、**何も見ていない**。

なのでこの2つの役割を分けた。

- モデルには**プロキシ全体**（0 → duration）を尋ねる
- 返ってきた判定に**候補自身のオフセット**を刻み直す

混同しても例外は出ない。**間違った映像の判定、あるいは何も映っていない判定**が返り、
作品はそれを元に切られる。テストで両方向を固定した。

### バケットの一覧に何が載ってよいか

オブジェクト名は**窓のハッシュだけ**から作る（`footage-<sha256[:16]>.mp4`）。
録画のファイル名や撮影時刻からは決して作らない。それらは人と場所を特定するうえ、
オブジェクト名はアップロードの中で唯一**人が読み、ログに残り、クリップを消した後も
バケットの一覧に残り続ける**部分だから。安全でない識別子は拒む。

### 機外に出る境界

Googleのimportは工場関数の**内側**にある。このモジュールはクラウドライブラリも
認証情報も無い機械でimportでき、ロジックをテストできる（ASTで検査し固定）。
`upload_to_bucket(...)`を組み立てても接続しない。**呼んで初めて**接続する。

アップローダは何も判断しない。どの窓を、どれだけ小さくして送るかは既に決まっている。
ここで決め直せば同じ判断が二箇所に置かれ、必ずずれる。

全1020件成功、Ruff成功。

---

## 54. 承認前に、送るものを全部作って測る（`analysis_preflight`）

承認をお願いしている数字——**121.3 MB / ¥27.9**——は、どちらも**算術**だった。
実測した定数に候補数を掛けただけで、**実際のrideの窓を全部縮小したことは一度も無い**。

カタログが信じているより録画が早く終わっている窓、FFmpegがseekできないファイル、
移動した素材——どれも**試すまで見えない**。そして最初に試すものが、
**課金しながら走っている実行であってはいけない**。

`run_preflight(package, plan)`が実行のローカル側を全部やる。全プロキシを ride 自身の
ファイルから作り、**何もアップロードせず、何も判定しない**。返るのは
「実行が実際に送る量」を、見積りではなく**数えたバイト**で。

### fail-open と fail-closed が逆である理由

`run_analysis`は1本でも失敗したら止まる。判定の欠けた記録は「モデルが何も言わなかった」
記録と**区別がつかず**、静かに別の作品が切られるから。

preflightは逆に**全部試して失敗を報告する**。目的が「どれだけ壊れているか知ること」
なのに最初の1件で止まれば、**誰も聞いていない質問に答えたことになる**。

この非対称は意図的で、両方をテストで固定した。

### 渡す先が無い

`run_preflight`には**uploaderもanalyserも引数に無い**（署名で検査）。
Googleのimportも無い（ASTで検査）。**承認前にできる半分**なので、
走らせて金が動く余地を構造的に消してある。

失敗は固定の非識別 reason code で数える:
`unknown_asset` / `source_missing` / `copy_failed` / `copy_empty`。
報告にpath・ファイル名・識別子は載らない。

作ったコピーは実行が探す場所に残るので、preflightは無駄仕事にならない。
既にあるコピーは測るだけで作り直さない（`rebuild=True`で再作成）。

`_source_recording`は`source_recording`として公開した。preflightと実行が
同じファイルを解決して同じコピーを作る以上、探し方が二通りあってはいけない。

全1038件成功、Ruff成功。

---

## 55. 実素材でpreflightを走らせ、自分の誤読を見つけた

`bridge-e2e-v1` packageで実行（**ローカル生成のみ・送信なし**）。

```
candidate_count : 173
prepared_count  : 173      失敗 0
measured        : 95.0 MB
largest         : 0.93 MB
所要            : 14分17秒
```

プロキシをffprobeで検品: **854×480 / 1 fps / 12フレーム / きっかり12.000秒**。設計通り。

### モジュールの欠陥（自分で書いて、自分で誤読した）

preflightは**プロキシしか作らない**のに、比較相手を`plan.upload_megabytes`——
**stills 32 MBを含む合計121.3 MB**——にしていた。95.0 / 121.3 = 0.783 と出るので
「見積りより22%小さい」と読める。**そう報告した。**

同種で比べれば **95.0 vs 89.3 MB = 6.4%超過**。**節約ではなく超過だった。**

原因は`MEASURED_PROXY_KILOBYTES_PER_SECOND = 43.0`が**12秒クリップ1本**からの
外挿だったこと。173本の実測は **45.8 KB/s**。

### 直したこと

- 定数を **43.0 → 45.8**（1本の外挿ではなく173本の実測）
- `AnalysisRunPlan`が見積りを`stills_megabytes` / `video_megabytes`に分けて持つ。
  合計は導出プロパティ。**送る主体が違うものを1つの数字に畳むと、片方の実測を
  合計で割るという誤りが自然に起きる**から。
- `PreflightResult.estimated_megabytes`は**clips分**を指す。合計は
  `estimated_total_megabytes`として別に持つ。
- 誤った比較を固定していたテストを削除し、**超過が節約に見えないこと**を検査する
  テストを追加した。

### 承認材料の訂正

| | 旧 | 新 |
|---|---|---|
| 候補 | 173本 | 173本 |
| clips | 89.3 MB（見積り） | **95.0 MB（実測）** |
| stills | 32.0 MB | 32.0 MB（見積りのまま） |
| 合計送信 | 121.3 MB | **127.1 MB** |
| 費用 | ¥27.9 | ¥27.9（変わらず） |

費用はトークン数で決まり送信バイト数では決まらないので、**¥27.9は動かない**。

**preflightは全173本が実際に作れることを証明した。承認後に素材側で詰まる要素は無い。**

全1039件成功、Ruff成功。

---

## 56. 何も落とさない審査段は、費用と送信量だけを増やしていた

前節で承認材料を実測に直したとき、もう一つ見えたことがある。
**計画は2段（stills審査 → 動画）で見積もるのに、`run_analysis`は1段しか実行しない。**
stillsは作られも送られもしない。承認材料が実際の動作と違っていた。

原因は`screen_keep_ratio`の既定が1.0だったこと。**全部通す審査は、何も審査していない。**
自分の費用と自分の送信量を足して、候補を1本も減らさない。
実rideでは **32 MBと見積り費用の約1/3**がそれだった。

### 直したこと

審査段は**その価値を稼ぐときだけ**計画する。

```
cascade = fit((matched, watching))          # まず直接
if cascade.tightened:                       # 収まらない時だけ
    cascade = fit((matched, screening, watching))
```

審査段の存在意義は「高くて無理な仕事を可能にする」こと——全候補を安く一瞥し、
生き残りだけを見る。予算が効かないなら、その一瞥は買う理由が無い。
予算が効くときは逆に、**候補を減らして帳尻を合わせるより一瞥を買う方が良い**。

段の参照を index から名前引きに変えた（段数が可変になったため）。

### 実rideでの効果

| | 前 | 後 |
|---|---|---|
| 段 | matched / stills / video | **matched / video** |
| stills | 32.0 MB | **0 MB** |
| clips | 95.1 MB | 95.1 MB（実測95.0） |
| 合計送信 | 127.1 MB | **95.1 MB** |
| 費用 | ¥27.88 | **¥25.56** |

**計画が実行と一致した。** 予測95.1 MBに対し実測95.0 MB。

予算¥20に絞ると審査段が現れ、173本全部をstillsで見て動画は86本に絞る（¥15.03）。
段が要るときだけ現れる。

### 既知の未実装（正直に記録する）

cascadeのtighteningは**価格には反映されるが、`run_analysis`は絞りを実行しない**。
実行はplanの全候補を判定する。実rideでは予算が効かないので承認材料には影響しないが、
予算が効く経路を使うなら、生き残りの選別を実装する必要がある。

全1044件成功、Ruff成功。

---

## 57. 承認額を超える請求になっていた（tighteningが価格だけで実行されていなかった）

前節で「既知の未実装」として記録した項目は、実際には**支出の安全性のバグ**だった。

実rideで確認:

```
承認     : ¥20.0
計画     : ¥15.03（173本中86本を判定）
実行     : 173本すべてを判定 → ¥25.56
```

**承認額の1.28倍**。予算は価格計算にだけ効いて、実行を絞っていなかった。

### 直したこと

`AnalysisRunPlan.watched_candidates` が「この計画が支払う候補」を返す。
`run_analysis`も`run_preflight`も`plan.candidates`ではなくこれを回す。

予算が効かなければ全部。効くときだけ絞る。

### どれを残すかは恣意的ではない

候補は**ride順**に並んでいる。**先頭から86本取れば、旅の前半だけを買って後半を
一本も買わない**ことになる。

なので**等間隔に散らす**。173本→86本で、位置は 0, 2, 4, ... 170。
間隔は一定、末尾の余りは間隔以下。**旅全体を、密度を下げて見る**。
「一部しか見ない」のではなく「粗く全部見る」。

テストで固定した不変条件:

- 絞られた計画は`watched_count`本ちょうどを判定する
- 最初の候補を含み、末尾の余りは間隔以下（前半だけにならない）
- 間隔のばらつきは1以内
- 予算が効かなければ`watched_candidates == candidates`
- preflightも送る分だけを作る（作らないファイルにFFmpegの時間を使わない）

全1049件成功、Ruff成功。

### 承認材料（変化なし）

上限¥500では予算が効かないため、**173本 / 95.1 MB / ¥25.6のまま**。
このバグは予算を絞ったときにだけ現れる。

---

## 58. 手順書に、打てないコマンドが書いてあった（`analysis_cli`）

`docs/demo-runbook-ja.md`を読み直して分かったこと。

**手順書はGemini判定を経ない旧経路を案内していた。** 手順2でpackageを作り、手順3で
いきなり作品を作る。**製品の核心（Geminiが実素材を判定する）が手順書に無い。**

理由は単純で、計画・preflight・判定に**コマンドが存在しなかった**——ライブラリ関数
だけだった。手順書に書けない。

### `python -m app.analysis_cli <plan|preflight|judge>`

3つに分けたこと自体が設計:

| 副コマンド | 送信 | 課金 | 何をするか |
|---|---|---|---|
| `plan` | なし | なし | 何を送りいくら掛かるかを言う。動画を開かない |
| `preflight` | なし | なし | 送るものを全部作って実測する |
| `judge` | **する** | **する** | アップロードしてGeminiに判定させる |

`judge`は`--i-approve-spending`と`--bucket`が無ければ**始まる前に拒否する**。
承認は決定であって既定値ではない。

**承認フラグの検査は、Googleに届き得るimportより前にある。**
打ち間違いがアップロードを始めることはない。ASTで文の順序を検査して固定した
（拒否のifが、`app.analysis_adapters`のimportより前の位置にあること）。

`plan`と`preflight`はクラウドライブラリの無い機械で動く。

### 実素材で確認した

```
plan      : 173候補 / 95.1 MB / ¥25.56 / within_budget true
preflight : 173本中173本 / 実測95.0 MB / 見積り比 0.999 / failures なし
judge     : 承認フラグ無しで拒否（exit 1）
```

### 手順書の更新

手順2.5（計画）・2.6（preflight）・2.7（判定）を追加。手順3に
「2.7を済ませていればGeminiの判定が採用区間を決め、済ませていなければ従来経路」
と明記。トラブル表に新しい4つのメッセージを追加。

「検証済みの範囲」に、**2.7は未実行・承認待ち**であることを明記した。

全1062件成功、Ruff成功。

---

## 59. 判定経路を実素材で通した（stub判定）。作品は出る

承認して¥25.6を払ったとき**本当に5分の作品が出るのか**は、誰も確かめていなかった。
統合テストは合成fixtureだけ。実rideの173本を通したことがない。

`bridge-e2e-v1`のJSONだけを`judged-dry-run-v1`へ複製し（実映像はvideo_root経由で
読取りのみ）、Geminiの位置にstub判定を置いて通した。

```
candidates judged : 173
beats             : 41   (footage 20, cards 21)
total duration    : 323.6s   目標 300.0s
footage seconds   : 240.0s
opens / closes    : gap_card / gap_card
```

**作品は出る。** 出発と到着の章カードで挟まれ、目標尺の付近に着地する。
選別の閾値（最小信頼度0.4・最小間隔120秒）が173本に対して厳しすぎることもない。

### そこで見つけた危険

**stubの判定から作った作品が、買った判定から作った作品と区別できない。**

記録は同じファイル名・同じ形で書かれ、`analysis_provider`は保存されるのに
**下流の誰も見ていなかった**。作品は「モデルが何を見たか」の証拠として人に見せる
ものなので、でっち上げのスコアから切った作品はそれではない。

しかも私はこの危険を、たった今**自分で作った**（dry-run packageに偽の判定を置いた）。

### 直したこと

`plan_journey_film`は、`analysis_provider`が`BOUGHT_ANALYSIS_PROVIDERS`
（現在は`gemini`のみ）でない判定からは**作品を作らない**。

```
this judgement was not bought from a model, so a film from it would show
invented scores as evidence; pass allow_unbought_judgement to build one anyway
```

dry runは`allow_unbought_judgement=True`と**明示的に言う**。既定で継承しない。
`judged-dry-run-v1`が実際に拒否されることを確認した。

全1064件成功、Ruff成功。

### 承認を受領（2026-09-03）

ユーザーから「承認します。実行しましょう」を受領。ただし**実行はまだできない**。

- Google Cloudの認証情報が期限切れ（ADCの再認証が必要）
- **再認証は対話が必要で、私が代行してはならない**（ユーザー自身が実行する）
- アップロード先のGCSバケット名も未確定

準備は完了している。認証後は1コマンドで走る。

---

## 60. 途中で失敗したとき、買った判定を捨てていた

承認済みの実行が目前なので、**その実行で最も高くつく失敗**を先に潰した。

173本の判定は**173回の課金呼び出しを順に行う**。`run_analysis`は1本でも失敗すると
例外を投げ、**何も書かずに終わっていた**。150本目で通信が切れれば、
**149本分の支払いが消え、次の試行で全部買い直す。**

「失敗した候補を飛ばさない」という原則は正しい——判定の欠けた記録は
「モデルが何も言わなかった」記録と区別できず、静かに別の作品を切る。
だがそれは**払ったものを捨てる理由にはならない**。両立する。

### 直したこと

判定は**届いた1本ごとに** `gemini-video-analysis.partial.json` へ書く。
再実行は**持っていない分だけを尋ねる**。完全な記録は今までどおり
**完全になったときだけ**書かれ、その時点でpartialは消える。

`overwrite`はpartialに触らない。「買い直す」ためのフラグでpartialを捨てれば、
中断したoverwrite実行を再開できず、**まさに直そうとしている損失が再発する**。
partialは試行に属し、フラグには属さない。

読めないpartialは**エラー**にした。黙って最初からやり直せば、
何も言わずに全rideを二度買うことになる。

CLIは `carried_from_earlier_attempt` と `newly_bought` を報告する。
障害が**金の損失で済むか時間の損失で済むか**の差がそこに出る。

テストで固定した不変条件:

- 5本目で失敗しても、4本分がpartialに残る
- 再実行は残り（`watched_count - 4`）だけを尋ね、失敗した1本も含む
- 完成した記録は繰り越し分を含めて全部を持ち、planの順序と一致する
- 完全な記録が書かれたらpartialは消える
- 読めないpartialは黙って買い直さない

`judgements_already_bought`は公開名にした（CLIが繰越本数を報告するため）。

全1069件成功、Ruff成功。

### 認証は依然ブロック中

ADCの再認証が必要。**対話が必要な操作で、私が代行してはならない。**

---

## 61. 初回の課金実行を開始した（2026-09-03）

ユーザーが承認し、再認証を自身で実行（`gcloud auth application-default login`）。

**バケット**: `ride-storyteller-analysis` を asia-northeast1 に作成。
`public_access_prevention = enforced`、uniform bucket-level access。非公開。

**コマンド**:
```
python -m app.analysis_cli judge private-media/work/bridge-e2e-v1 \
  --bucket ride-storyteller-analysis --prefix bridge-e2e-v1 --i-approve-spending
```

173候補 / 送信95.1 MB / ¥25.6。原本4K 68.1 GiBは送っていない。

### 最初の判定

`analysis_provider = gemini`。Geminiが実素材を見て書いた記述:

> The video shows a street scene from the perspective of a motorcycle,
> with a rearview mirror prominently in the…

**製品の核心が初めて動いた。**

### 速度

1本あたり約35秒。アップロード（約500 KB）は一瞬で、時間のほぼ全てがGeminiの
動画処理。173本で約100分。逐次呼び出しなので並列化すれば短縮できるが、
走っている実行には手を触れない。中断しても買った分は `partial` に残る（§60）。

結果は完走後に追記する。

---

## 62. 初回の課金実行が完走。Geminiの判定が初めて作品の中身を決めた

```
judged     : 173 / 173     carried 0 / newly_bought 173
providers  : {gemini}
record     : gemini-video-analysis.json（196 KB）
所要       : 約100分（1本あたり約35秒、ほぼ全てGeminiの動画処理）
費用       : ¥25.6（計画どおり。請求の実額はBillingの反映後に確認）
```

### Geminiが見たもの

```
interest : mean 0.57  min 0.20  max 0.70
story    : mean 0.48  min 0.10  max 0.90
conf     : mean 0.94  min 0.90
road     : Asphalt highway / suburban street, roundabout / rural two-lane /
           multi-lane arterial / parking lot / intersection …
weather  : sunny / partly cloudy / overcast / cloudy（表記ゆれ多数）
```

記述は実素材に即している（「rearview mirror」「rider's arm and jacket」
「roundabout」「motel-like building」「dedicated bike lane」）。

### 作品構成（判定済みpackageから）

```
beats            : 41  (footage 20, cards 21)
total duration   : 320.7s   目標 300.0s
footage seconds  : 240.0s
opens / closes   : gap_card / gap_card
```

**Geminiの判定が採用区間を決めた初めての作品構成。** `journey-story-plan.json`
に書かれた。stub dry-run（§59）の41 beat / 323.6sとほぼ同じ形で着地。

### 気づき（次の改善候補、今は手を付けない）

**スコアが圧縮されている。** 173本の interest はほぼ 0.60 か 0.70、story は
ほぼ 0.70。差がつかず、選別は最小間隔120秒でほぼ等間隔に近い選び方になっている。
選ばれた20本はほとんど「highway」。判定の記述は豊かなのにスコアが平坦なのは、
プロンプトが「0〜1で採点」としか言っておらず、**何を基準に差をつけるか**を
与えていないため。次段で改善する価値がある（相対評価・基準の明示・記述からの
再採点など）。作品としては成立しているので、今回はこのまま進める。

`weather_visible` の表記ゆれ（40種）は、下流が使っていないので今は無害。

---

## 63. 同点のとき、モデルが決めなかったことを選別が決める（`gemini_selection`）

初回実行の判定はスコアが平坦だった: **30本が0.66ちょうど、33本が0.54ちょうど**。
選別は`(-score, start_time)`で並べていたので、同点は**早い時刻順**——
旅の前半のhighwayから埋まり、選ばれた20本のうち10本がラベル「highway」そのもの。

### 直したこと

同点（`tie_epsilon = 0.02`以内）の中では、

1. **まだ作品に出ていない種類の道**を優先する（`road_family`で粗く分類）
2. 次に、**既に採った区間から最も遠い**窓
3. 最後に時刻順

モデルの順位は触らない。**モデルが決めなかったことだけを決める。**
明確な差がある窓は今までどおり先に採られる（テストで固定）。

`road_family`はGeminiの自由記述ラベルを highway / street / rural / junction /
parking に粗く畳む。先に一致した語が勝つので具体的な語を先に置く。
**スコアには一切触れない**——同点の順序付けにしか使わない。

### 実素材での効果（同じ判定・無料）

| | 前 | 後 |
|---|---|---|
| 採用20本の種類 | highway系16 + 他4 | **highway 15 + rural/junction/street/parking/gas station** |
| 平均スコア | — | 0.673（下がっていない） |
| 時間分布 | first 0.04 / median 0.78 / last 0.99 | 同じ（分離ルールが支配） |

173本中137本がhighwayなので15/20は比例配分として妥当。**残り5本が5種類に散った**。

`_verdict_reason`は床の判定（`_floor_reason`）と、採る/近すぎる/足りたの判定に
分割した。後者は貪欲ループの中で決まるため。

全1091件成功、Ruff成功。

### 注記

このレンダー（§62の構成）は**変更前の選別**で走っている。改善後の構成で
作り直すのは、初回の作品をユーザーが見たあとに判断する。

---

## 64. 初めての作品が完成した（Geminiの判定で採用区間を決めた5分の映像）

ユーザーの「進めて」でレンダーを実行（ローカル・無料）。

```
ride-storyteller-story-film-scored.mp4   774 MB   1920x1080 h264 + aac
duration   320.8s（構成 320.693s と一致）
beats      41   字幕 41 cue（SRT / VTT）
music      Rising Tide（CC BY 4.0、attribution記録済み）
local_only true   external_data_sent false
moov       正常（途中停止による破損なし）
```

**「Geminiが実素材を判定して5分の映像を作る」が端から端まで通った。**

判定→選別→構成→章カード→レンダー→字幕→音楽。人が決めたのは時計のズレと承認だけ。

### 作品をユーザーへ渡す方法

774 MBの実素材なので**ファイル送信はしない**（端末から出さない原則）。パスで渡す:
`private-media/work/bridge-e2e-v1/ride-storyteller-story-film-scored.mp4`

### この作品は変更前の選別で作られている

§63の同点処理は、このレンダー開始後に入った。改善後の構成で作り直すかは
ユーザーが初回作品を見てから決める（レンダーは無料・約5分）。

---

## 65. UI 第1層: 判定経路を含む操作卓（読み取り専用）`/private-journey`

ユーザー指示「そろそろUIも作って下さい」。既存の状態画面（`/private-journey-status`）は
判定経路を知らず、入力確認→物語→作品→音楽の4段しか出さない。

`app/web/private_journey_console.py`が判定経路の3段を**先頭に**置き、既存の段が続く:

| 段 | 出すもの |
|---|---|
| `footage_planned` | 候補数・判定対象数・送信MB・**費用¥**・上限¥・予算内か |
| `copies_prepared` | 作成済み / 必要 コピー数、実測MB（pending / in_progress / done） |
| `footage_judged` | 判定済み / 必要 本数（partial があれば in_progress） |

実素材packageでの表示: 「173 候補 · 95.1 MB 送信 · **¥25.56** 費用 (上限 ¥500)」→
「173 / 173 コピー作成 (95 MB)」→「173 / 173 判定済み」→ 以降すべて完了 →
次の操作「作品を再生してください」。ブラウザで確認済み。

### 設計

- **読むだけ**。計画は動画を開かず、コピーも判定も報告するだけで作らない・買わない
- payloadは件数・容量・金額・固定reason codeのみ。path・ファイル名・窓ID・モデルの文章は出ない（テストで固定）
- `in_progress`（判定購入中）の間は5秒ごとに再読込。**判定が届くのを画面で見られる**
- 買っていない判定（stub）は`judgement_not_bought_from_a_model`でblocked
- GETのみ、未設定なら503、public demoでは配信しない
- 操作（preflight・承認つき判定・レンダー）は**次段**。承認は表示された金額に結びつける

### 見つかった欠陥（未修正、次の作業）

`PrivateJourneyStatus`と**`private_journey_film`コマンド本体**が
`check_private_package_health`を通り、それが**候補exportを必須**にしている。
映像だけから判定したpackage（クラウド形）にはexportが無いので、
**判定はできても作品コマンドで落ちる**。今回の実素材は古いexportが残っていたため通った。
consoleはfilm状態が読めなくても判定経路を出すよう作ったが、コマンド側は直す必要がある。

全1112件成功、Ruff成功。

---

## 66. Gate 1 が「判定済みのpackage」を理解するようになった（作品コマンドの gate 修正）

§65で見つけた欠陥。`check_private_package_health`は候補export
（`ride-storyteller-candidates.json`）と evidence review を**必須**にしていた。
映像だけから判定したpackage——クラウド経路が作る形——にはどちらも無いので、
**判定はできても作品コマンド（`private_journey_film`）で落ちる**。
今回の実素材は古いexportが残っていたため通っただけだった。

### 設計

packageには2つの形がある。

| 形 | 持つもの | Gate 1が問うこと |
|---|---|---|
| 旧 | 候補export + evidence review | 証拠は確定したか（awaiting / rejected / unmatched） |
| 新 | **買った判定** | 時計は一致するか、判定は本当に買ったものか、判定は空でないか |

**判定があればそれが問いを決める。** exportの問いは「誰も使わないclip」についての
問いになるので、判定済みpackageには尋ねない。両方無ければ読めない（従来どおり）。

`check_private_package_health`の内側で分岐するので、**呼び出し側は一切変えていない**。
作品コマンド・状態画面・consoleの3箇所が一度に直った。

新しいblocking reason: `judgement_not_bought_from_a_model` / `no_judged_footage`。
`BOUGHT_ANALYSIS_PROVIDERS`は循環importを避けて`analysis_record`へ移し、
`private_journey_film`は再exportする。

### 実素材での確認

```
judged-dry-run-v1（stub判定・exportなし）: is_ready False  reasons ('judgement_not_bought_from_a_model',)
bridge-e2e-v1   （買った判定 + 旧export）: is_ready True   judged 173  film_s 320.7
```

dry-runは**落ちずに正しい理由で止まり**、本物は判定の本数（173）を報告する
（旧exportの7ではなく——作品の中身と一致）。

全1121件成功、Ruff成功。

---

## 67. UI 第2層: 操作（preflight・承認つき判定・レンダー）`app/web/private_journey_actions.py`

`/private-journey`が読むだけでなく**動かせる**ようになった。次の操作に応じてボタンが出る:

| next_action | 出るもの | 費用 |
|---|---|---|
| `prepare_the_copies` | 「縮小コピーを作る」 | 無料・ローカル |
| `approve_and_judge` | **金額入力** + バケット入力 + 「承認して判定させる」（赤） | **課金** |
| `make_the_film` / `choose_music` | 曲の選択 + 「作品を生成する」 | 無料・ローカル |

### 承認の門

判定だけが金を使う。その承認は**チェックボックスではない**。リクエストは
**画面に表示された金額を円の小数2桁まで一致させて**持ってこなければならず、
アップロード先バケットも要る。一致しなければ`approval_does_not_match_the_figure`で
**job が作られる前に**拒否——Googleに届き得るimportより前。古い画面や打ち間違いが
アップロードを始めることはない。**承認する数字は、見せられた数字である。**

### job runner

プロセスに1つ、**同時に1件だけ**（2件目は409 `another_job_is_running`）。
背景スレッドで実行し、consoleの`job`をpollingで追う（実行中は5秒ごと）。
状態は kind / state / 固定reason / 経過秒 / 件数だけ。**失敗のメッセージは出さない**
——メッセージにはpathが載る。`job_failed` / `package_refused_the_request` /
`judgement_already_bought` のいずれか。

曲は`MUSIC_TRACK_IDS`（5曲）に限定。任意文字列はファイル名として届かない。

### server

- `POST /api/private-journey/{preflight|judge|film}`、JSON本文は4 KBまで
- GET は405、未設定は503、不正本文は400、実行中は409、受理は202
- public demoでは3つとも配信しない
- `GET /api/private-journey`の payload に`job`が乗る

テストは runner を「保持するだけ」に差し替え、FFmpeg も Google も動かさない。
門の形だけを固定した（26件）。

全1147件成功、Ruff成功。ブラウザで実素材packageの画面を確認（次項）。

---

## 68. UIをブラウザで通した。細部3点を修正

実素材の複製package（`console-demo-v1`: inputs + catalog + proxies）で確認。

- **承認フォーム**: 「承認する金額を、表示どおりに入力 ¥25.56」の入力欄、バケット欄、
  赤い「承認して判定させる（課金）」。意図どおり。
- **作品生成フォーム**（判定記録を加えた状態）: 曲の選択 + 「作品を生成する（無料・ローカル）」。
- **ボタンを押した**: 3秒後に「物語の計画 完了 41 beat, 5m 20s」が現れ、レンダーへ進んだ。
  候補export無しのpackageで作品コマンドが走った——§66のGate 1修正が実地で効いた。

修正:
1. 冒頭文が「読み取り専用…処理を開始しません」のまま→**嘘になっていた**。
   「コピー作成と作品生成はローカルで無料。判定の購入は表示された金額を入力して
   承認したときだけ始まる」に書き換え。
2. 判定前の「作品の状態」が `blocked / film_status_unavailable`→判定前は単に
   「未実施」。判定があるのに読めないときだけ blocked。
3. 曲の既定値が先頭の `wholesome`→`rising-tide`。

気づき（未対応）: 判定済み・計画前の「入力の確認」が判定映像の合計（34m36s）を
「尺」として出す。健全性チェックが計画無しのとき素材合計を返す仕様どおりだが、
ラベルは誤解を招く。UIの文言で吸収するか、計画前は出さないか、次で判断。

---

## 69. UIのボタンから2本目の作品ができた。取り込み層を追加

### 2本目（`console-demo-v1`、UIの「作品を生成する」から）

```
job      : film / done / 185.0s
film     : 320.5s   762 MB   scored（rising-tide）
next     : watch_the_film
```

候補export無しのpackageで、ブラウザのボタン一つから作品まで通った。
§66のGate 1修正と§67のjob runnerが実地で動いた。

### 選別の前後比較（同じ判定・同じ173本）

| | highway | その他 |
|---|---|---|
| 1本目（同点は時刻順） | 15 | rural 2 / gas station / street / parking |
| 2本目（同点は種類→距離） | 15 | rural / **junction** / gas station / street / parking |

**差は小さい。** 173本中137本がhighwayで、分離ルール（120秒）が支配的なため、
同点処理が効く余地が少ない。rural 1本が junction 1本に置き換わっただけ。
改善は本物だが、このrideでは目に見える差にならない。誇張しない。

### 取り込み層 `app/web/private_journey_intake.py`

手順書の1・2（時計オフセットの提案、packageの作成）をconsoleから行えるようにする層。
2つの門:

- **パス**: ブラウザから来る。`private-media/input`（`RIDE_PRIVATE_INTAKE_ROOT`）配下に
  限定し、resolveして、途中にsymlinkがあれば拒む。ブラウザがこのプロセスに任意の
  ファイルを読ませることはできない。packageは`private-media/work/<plain word>`にだけ書く。
- **時計オフセット**: 人が下す唯一の判断。確定は金額の門と同じで、**提案された数字
  （bestかrunners_up）を返さなければ確定にならない**。作成時に提案を**再計算**して
  照合するので、画面が覚えていた数字ではなく今の証拠に対して確認する。

`extract_reviews=False`で作る。判定経路にreview clipは要らず、候補ごとのFFmpegは
誰も見ないファイルに分を使うだけ。

テスト18件（symlink脱出、相対パス、名前の制限、既存packageの保護、提案外の数字の拒否、
再計算照合、target尺の範囲）。server配線は次項。

---

## 70. 取り込みを server と画面に配線した。package の切替も

`/private-journey` に「別の日のクリップを取り込む」節が付いた。

```
POST /api/private-journey/intake/propose   {gpx, video_root}            → 提案（数字と本数だけ）
POST /api/private-journey/intake/create    {gpx, video_root, name, offset_s, target_duration_s} → job(intake)
POST /api/private-journey/select           {name}                       → consoleの対象を切替
GET  /api/private-journey                  … "package": <名前>, "packages": [<名前>…]
```

- 提案の返り値は `offset_hours / offset_s / recordings_inside / recordings_total /
  is_unambiguous / runners_up`。**pathは返さない。**
- 作成は job（`intake`）。安い拒否（パス・名前・既存）は job の前、オフセットの照合は
  job の中で提案を**再計算して**行う。提案外の数字は `offset_was_not_the_one_proposed`。
- 作成が完了すると console はその package へ**切り替わる**（`_CURRENT_PACKAGE`）。
  環境変数の package は出発点にすぎない。
- 画面上部に package のプルダウンと「切替」。work root 直下の plain-word 名だけを列挙。

### 修正した自分のミス

`from_environment()` を `_console()` に一括置換した際、`_console()` 自身の中まで
置き換わって無限再帰（RecursionError、12件失敗）。置換は範囲を絞る。
また前項で `pytest | tail` のパイプが終了コードを隠し、**失敗したまま commit した**。
以後 `set -o pipefail` を付ける。

全1172件成功、Ruff成功。

---

## 71. 別の日のクリップは既に置かれていた。UIの取り込みで package を作った

`private-media/input/gps/` に GPX が2つあった。既知の日と、もう一つ。動画49本のうち
既知の日に入るのは14本だけだったので、残りはもう一つの日の可能性が高い。

時計オフセットの提案（ローカル・メタデータのみ）:

```
is_unambiguous : True
proposed       : -46800 s = -13.0 h   inside 29 / 49   covered 0.34
runner-up      : -48600 s (28)  -50400 s (25)  -45000 s (25)
```

同じ −13時間、同じカメラ。**曖昧さなし。**

### UIの取り込み API で package を作った

```
POST /api/private-journey/intake/create  {gpx, video_root, name: day-two-v1, offset_s: -46800}
job intake / done / 5.8s
→ console が day-two-v1 へ切替
```

計画（送信なし・無料）:

```
candidate_count 92   upload 50.6 MB   cost ¥13.59   within_budget True
next_action: prepare_the_copies
```

preflight（92本の縮小コピー、ローカル・無料）を UI の API から開始。
**判定（¥13.59）は新しい支出なので、承認を待つ。**

（GPXのファイル名には地名が含まれるため、docs/Notion/commit には書かない。）

---

## 72. 2つ目の日の preflight 完了。承認待ち

```
job preflight / done / 162.8s
prepared 92 / 92   measured 48.2 MB（見積り 50.6 MB、比 0.95）  ready true  failures なし
next_action: approve_and_judge
```

UI の API から開始し、UI の polling で完了を確認した。判定（¥13.59）は承認待ち。

---

## 73. 採点基準（rubric）をプロンプトに入れた（未検証・次の課金実行で確かめる）

初回の判定は平坦だった: **30本が0.66ちょうど、33本が0.54ちょうど**。プロンプトは
「0〜1で採点」としか言っておらず、**0.3と0.8が道の上で何を意味するか**を与えていない。
基準無しに採点を求められたモデルは、全部を「まあまあ」にする。

`SCORING_RUBRIC`（`app/video/gemini_client.py`）:

| | 0.2 | 0.5 | 0.8 | 1.0 |
|---|---|---|---|---|
| interest | 景色が変わらない（停車・駐車場・渋滞・何もない直線） | 普通の道を淡々と | 景色が明らかに見せる価値（山・峡谷・海岸・川・谷・空）か道そのもの（連続カーブ・登り・下り・バンク） | その日の一枚 |
| story | どこでもあり得る | 道と風景の種類が分かる | ランドマーク・分岐・峠・地形や天候の変化・出発や到着 | 旅がそれを軸に語られる瞬間 |

「全範囲を使え。長い旅の大半の窓は普通。0.7超は明らかに際立つ窓に取っておけ。
各窓をそれ自体で採点し、全部が中間だと決めてかかるな。」

抽象語ではなく**道の上の具体**（駐車場・渋滞・峡谷・カーブ・峠・到着）で書いた。
モデルは「quality」には反応できないが「a gorge」には反応できる。

「見えるものだけを記述する」の制約は残す。

**未検証。** 実素材での効果は次の課金実行（2つ目の日、¥13.59）で確かめる。
悪化していれば同額で判定し直せば済む。

全1177件成功、Ruff成功。

---

## 74. 提出文書を判定経路と操作卓に合わせて再監査した

提出文書は**「Geminiは実素材を解析していない。一度も。」**と明記していた。
2026-09-03 以降それは虚偽で、審査員が読む文書だった。

直したもの:

| 文書 | 変更 |
|---|---|
| `project-writeup-en.md` | 「What it does」に判定経路（173窓・95 MB・¥25.6・全件返答）、支出の門、操作卓を追加。Accomplishments と Remains を更新。テスト数 898→1,177 |
| `judging-alignment.md` | 証拠の箇条を実数へ。「主張してはならないこと」を**「モデルの判断が人の判断と照合されたとは言わない」**へ書き換え（過去の記述が2026-09-03まで真だったことも残す） |
| `demo-script-en.md` | `/private-journey-status` → `/private-journey`（支出の門を見せる）。禁止事項を更新。**字幕SRTは台本変更に未追従**（録画時に合わせる） |
| `architecture.md` | 図に「映像の窓→縮小コピー→支出の門→GCS→Gemini判定→選別→StoryPlan」を追加。クラウド境界は「一度越えた・毎回門がある」。散文を更新 |
| `README.md` | パイプライン図・実素材の状態・consoleの案内を更新 |
| `app/submission` | ハードコードされた media gate「未承認・未実行」を「承認・実行済み（1回）」へ |

主張の線引き: **「Geminiが実素材を判定し、作品はその判定から切られた」は言う。
「その判断が人の判断と照合された」は言わない。「hosted agent が実rideを処理した」は言わない。**

---

## 75. 2つ目の日の判定を開始（承認済み）。支出は ¥500 まで一任

ユーザー: 「承認します。五百円まではあなたに一任します。」（2026-09-03）

以後、Gemini判定 / GCSアップロードの支出は**累計 ¥500 まで**私の判断で行う。
各実行の金額と累計を必ず報告する。4K原本は送らない。新しい種類の外部コスト
（デプロイ・公開ホスティング）は別途承認。

### 実行

画面と同じ API を通した（支出の門を通る）:

```
POST /api/private-journey/judge  {approve_jpy: "13.59", bucket: "ride-storyteller-analysis"}
→ job judge / running
60秒後: 2 / 92 判定済み、provider gemini、interest 0.4 story 0.6
```

最初の2本が **0.4 / 0.6**——初回の平坦な 0.6 / 0.7 帯から既に外れている。
rubric の効果は完走後に分布で見る。

### 支出の累計

| 日 | 候補 | 費用 |
|---|---|---|
| 1つ目 | 173本 | ¥25.56 |
| 2つ目 | 92本 | ¥13.59 |
| **累計** | | **¥39.15**（上限 ¥500） |

---

## 76. 3分デモをローカルで組み立てた（`app/submission/demo_assembly.py`）

ユーザー指示「あなたができることは全て実施して下さい。承認が必要ならモバイルへ」。
録画は人が要るが、**組み立ては部品から機械的にできる**。

台本の時間割どおり、カード（HTML→Quick Look PNG、章カードと同じ契約）と、
完成作品からの抜粋1本を ffmpeg で繋ぐ。console の数字は画面と同じ payload から書く
（スクリーンショットではない）。

```
0:00 問題 20s → 0:20 証拠 25s → 0:45 時計 20s → 1:05 章カード×2 30s
→ 1:35 console 25s → 2:00 Gemini 25s → 2:25 IBM Bob 15s → 2:40 実素材抜粋 15s → 2:55 締め 5s
```

- 各セグメントを同一パラメータ（1920×1080・30fps・h264・aac 48k）で個別に作り、
  concat demuxer で `-c copy` 結合。無音区間は `anullsrc`
- カード文言は件数・容量・金額・作品の言葉だけ。**path・ファイル名・座標・時刻は禁止**
  （`/\S` を path と見なして拒否、`173 / 173` は比として許可）
- 字幕は焼き込めない（この ffmpeg に文字描画が無い）ので SRT を隣に置く
- 途中で失敗すれば demo も scratch も残らない（完成時のみ `os.replace`）

実行結果: `private-media/work/bridge-e2e-v1/demo/demo-en.mp4`
**180.02秒・1920×1080・video+audio・37.1 MB**、`demo-subtitles-en.srt` 同梱。

### 公開前に人が見るもの

- 2:40–2:55 の実素材抜粋（作品の 20.4–35.4秒）に**判読可能なナンバープレート・
  識別可能な顔が無いか**。自動検出は無いので目視
- 章カードの経路図は地図無しの線だが、形から場所が推測され得る。台本は許容済み
- 台本の 2:00–2:25 と 1:35–2:00、締めの文言を判定経路に合わせて更新済み。
  **SRT は旧文言のまま**——録画（ナレーション）の有無で扱いが変わるため未更新

公開（YouTube）は別途承認。

全1188件成功、Ruff成功。


---

## 77. 字幕 SRT を台本に追従、クラウド構成文書を実態に同期

- `demo-subtitles-en.srt` の 1:35–2:25 と締めの cue を、更新済み台本（判定経路・支出の門・
  95 MB・¥26）に合わせた。タイミングは不変、26 cue、3:00。demo フォルダにも再コピー
- `cloud-architecture-ja.md`: 実測表に判定用コピー 95 MB を追加（元の約720分の1）、
  §4 の分担を実装済みの形（エッジ=console、クラウド=GCS+Gemini、hosted=合成のみ）へ、
  §7 を「実素材の判定は承認のもとで一度実施」へ

---

## 78. 判定を並列化した（既定4本同時）

初回は1本あたり約35秒の逐次呼び出しで、173本に100分かかった。時間のほぼ全てが
ネットワーク待ち（アップロード＋モデル応答）なので、4本同時なら約4分の1になる。
モデルの既定クォータの範囲内。

`run_analysis(..., concurrency=DEFAULT_CONCURRENCY)`（既定4、1で従来の逐次）。

- 結果は候補IDで受け、記録は**計画の順序**で書く（ネットワークの返る順ではなく）
- partial は**届くたびにロックの下で**計画順に書き直す。買った分を捨てない性質は不変
- 最初の失敗で**新しい仕事は出さない**。飛行中のものは完了させて記録する
  （どのみち払っている）。`FIRST_EXCEPTION` で待ち、残りはキャンセル
- 再実行は持っていない分だけ尋ねる（並列でも二重購入しないことをテストで固定）
- 同数の正確さを数える再開テストは `concurrency=1` で走らせる（並列では非決定）

console と CLI はそのまま既定4を使う。走行中の job（2つ目の日）は旧コードのまま逐次。
次の判定から効く。

全1193件成功、Ruff成功。

---

## 79. 2つ目の日の判定が完走。rubric の効果は「あるが控えめ」

```
job judge / done / 2518s（42分、旧コードの逐次）
newly_bought 92   carried 0   next_action: make_the_film
```

### スコア分布の比較（1つ目=rubric無し、2つ目=rubric有り）

| | 1つ目（173本） | 2つ目（92本） |
|---|---|---|
| interest 平均 / sd | 0.57 / 0.11 | 0.60 / 0.10 |
| interest 最頻値 0.6 の割合 | **60%**（104/173） | **46%**（42/92） |
| interest > 0.7 | **0本** | **5本**（0.8） |
| interest 値の種類 | 7 | 9 |
| story > 0.7 | 5本（3%） | 11本（12%） |
| story 平均 / sd | 0.48 / 0.16 | 0.59 / 0.16 |

**読み方（誇張しない）**: 上端が使われるようになり（0.8 が出た、story>0.7 が4倍）、
最頻値への集中が減った。だが**分散（sd）は変わっていない**。rubric は効いているが、
「平坦さの解消」と呼ぶには足りない。別の日なので統制比較でもない。

次段の候補: (a) 相対評価（同じrideの複数窓を1回の呼び出しで比較させる）、
(b) 記述→採点の二段（記述は豊かなので、記述から採点し直す）。

### 支出の累計

¥25.56 + ¥13.59 = **¥39.15**（上限 ¥500）

---

## 80. 2つ目の日の作品が完成（画面のボタンから、192秒）

```
job film / done / 192.5s
story   41 beat（footage 20 / cards 21）  317.7s
film    1026 MB → scored 1034 MB（1080p、Rising Tide）  実尺 317.8s
next    watch_the_film
```

`private-media/work/day-two-v1/ride-storyteller-story-film-scored.mp4`

### 採用20本の種類（rubric 有り・同点処理有り）

rural 8 / highway 3 / paved road 3 / parking 2 / asphalt road 2 / unknown 1 / roadworks 1。
採用の平均 interest 0.65 / story 0.75（全92本の平均 0.60 / 0.59 より高い——選別が上を採っている）。

1つ目の日（highway 15/20）と対照的に、この日は田舎道が中心。**判定が走行の性格を反映している。**

### 端から端まで、画面から

取り込み（5.8秒）→ 縮小コピー（163秒）→ 承認つき判定（42分・¥13.59）→ 作品（192秒）。
**別の日のクリップが、ターミナルを開かずに作品になった。**

支出累計 ¥39.15 / 上限 ¥500。

---

## 81. 相対評価: 同点の窓をモデル自身に比較させる（`analysis_ranking`）

1本ずつの採点は「比べる相手のない数字」で、2つの実rideで束になった（大半が0.6）。
rubricは少し広げた。**0.6と0.6を分けるのは、両方を見せて「どちらが作品に入るべきか」
を訊くこと**である。

### 仕組み

- 判定済みの窓のうち、最高点から `band=0.15` 以内のものを、スコア順に**12本ずつ**の
  グループにする
- 各グループを**1回の呼び出し**で送る（既に判定で上げたコピーをそのまま。Window A, B, C…
  とラベル付け）。問い: 「5分の作品に最も値する順に、全ラベルを1回ずつ並べよ」
- 返ってきた順序を `gemini-window-ranking.json` に書く。**順位は全体で通し**
  （上の帯のグループが 1..n、次が n+1..）——下の帯は既に上の帯より下と判定済みだから
- **selection は順位を同点の第1キー**にする。道の種類・距離の heuristics は
  「訊かなかった窓」だけを並べる。**モデル自身の比較が推測に勝つ——訊いた範囲でだけ**

### 境界

- transport はラベル（A..Z）で答えさせ、呼び手が識別子へ戻す。モデルが識別子を
  復唱するのを当てにしない。欠け・重複は `incomplete ranking` で拒否
- 買っていない判定は順位付けしない。買っていない順位は作品に使わない
- コピーが無ければ買う前に止まる。比較器が窓を落とせば書かない
- CLI `rank` は `--i-approve-spending` 必須（判定と同じ門）
- 費用: 12本×12秒×100 tok ≈ 14k 入力 + 数十 出力 ≈ **1グループ1円未満**

全1208件成功、Ruff成功。実rideでの検証は次項。

---

## 82. 相対評価を2つ目の日で購入。順序は変わったが、採用は変わらなかった

実行で見つけた2点を先に直した（`928ef32`）: Vertex AI は**1リクエストに動画10本まで**
（12本目で 400）、モデルは「Window C」と答えるので**最後の文字**をラベルとして読む。

```
rank: 17 窓 / 2 グループ / 約 ¥0.96（＋失敗2回分 ≈ ¥1）  provider gemini
rank 1: score 0.74（案内看板のある駐車場）  rank 2: 0.76  rank 3-5: 0.82 ...
```

モデルの順序は点数順と**違う**（0.74 の窓を 0.82 の3本より上に置いた——看板＝ランドマーク
という rubric どおりの判断）。しかし**採用20本は同じ**（入れ替え 0）。理由: band 0.15 に
入った17本は全て既に採用枠（20）に入っており、順位は「どれを採るか」ではなく
「同点の中の順番」しか変えないため。分離ルール（120秒）が支配的なのも同じ。

効くはずの場面は**同点の窓が枠より多い ride**——1つ目の日（0.66 が30本、枠20）。
そちらで検証する（≈¥2、一任範囲内）。

支出累計: ¥39.15 + ≈¥1 = **≈¥40.1** / 上限 ¥500

## 83. 自律ループをスケジュールタスクにした

ユーザー指示「自律ループをスケジュールタスクを設定して、開発が止まらないようにして下さい」。

デスクトップアプリのスケジュールタスク `ride-storyteller-autonomous-loop` を **30分毎**で作成
（`~/.claude/scheduled-tasks/ride-storyteller-autonomous-loop/SKILL.md`）。プロンプトは自己完結:
読むもの（handoff 末尾・roadmap・memory）、役割、優先順、制約（実素材の境界・支出一任 ¥500・
承認は PushNotification 1通・同時実行の回避）、素材の場所、各ループで更新する文書と Notion ID、報告形式。

注意: **アプリが開いている間だけ動く**（閉じていた分は次回起動時に1回走る）。
初回は「Run now」でツール承認を先に済ませると以後のループが止まらない。

---

## 84. 相対評価の帯を「最高点から」ではなく「採用枠の境界から」取る（`5aac30c`）

1つ目の日で最初の帯（最高点 −0.15）を買ったら、対象は**6窓**だけで採用は1本しか
動かなかった。決定は20位の境界で下されていて、そこに 0.66 が30本並んでいるのに、
帯はその上で切れていた。**決定が下される場所を順位付けしなければ意味がない。**

- `windows_worth_ranking(band=0.05, slots=20, max_windows=40)`: 20位の点数から
  0.05 下までを対象にし、上限40窓（4グループ、≈¥2.25）
- fixture が枠より少ないテストは `slots=` を明示する（枠より候補が少なければ cut は最下位）
- 1つ目の日で再購入中（背景）。結果は次項

### 自律ループの実行主体

デスクトップアプリのスケジュールタスク `ride-storyteller-autonomous-loop`（30分毎）。
アプリが開いている間だけ動く。支出累計 ≈ ¥41（判定 ¥39.15 + 順位付け ≈ ¥2）。

---

## 85. 境界で順位付けしたら、1つ目の日の採用が20本中8本入れ替わった

```
rank: 40 窓 / 4 グループ / ≈¥2.25   所要 約9分
chosen before/after: 20 / 20   swapped: 8
families: 不変（highway 15 ほか）   mean score: 0.673 → 0.675
```

入れ替わったのは全て 0.64〜0.66 の同点帯——点数では区別できなかった窓を、
モデルが**両方見て**入れ替えた。種類の分布も平均点も変わらないのは当然で、
これは「どの highway を見せるか」をモデルの比較で決めた結果である。

**設計は実地で検証された**: 順位付けは「決定が下される場所」で買えば作品を変える。
最高点付近で買っても変えない（§82）。

再レンダー（1つ目の日、順位付け反映）を実行。demo の抜粋（20.4–35.4秒）は
既に組み立て済みファイルなので影響しない。

支出累計: ≈¥41 + ¥2.25 = **≈¥43** / 上限 ¥500

次の候補（ループへ）: console に `rank` job と「順位付け 40 / 40」の段を出す。
判定→順位付け→作品を画面から一本で。

---

## 86. 1つ目の日を順位付け反映で再レンダーした

```
film   321.1s   797 MB   41 beat（footage 20 / cards 21）  external_data_sent false
採用の種類: highway 15 / gas station / rural / junction / street / parking（不変）
```

`private-media/work/bridge-e2e-v1/ride-storyteller-story-film-scored.mp4` は
**モデルの比較で8本が入れ替わった版**に置き換わった。旧版の抜粋から組んだ
`demo/demo-en.mp4` はそのまま（再組み立てすれば新版から切られる）。

---

## 87. 方針: ビジネス展開（月 ¥100〜300）まで開発を続ける

ユーザー（2026-09-04）: 「このシステムをビジネスとして展開できるレベルになるまで開発を
継続して下さい。月々100〜300円のサービスを目指しています。」 保留2件は今晩判断。

roadmap に **Gate 7** を追加。門は単位経済: 現状 ≈¥27.9/走行 は ¥300 帯でも赤字。
**順位付けだけ + stride 60秒で ≈¥5.5/走行**（¥100 帯の上限 ¥7.5 に収まる）。
単位 7.1〜7.9 を順に、各単位を実素材2 ride で実測して閉じる。

session 衝突回避の規約（roadmap 末尾）: 着手時に handoff へ「着手中: …」を追記して commit。

### 7.1 完了: 費用モデルをコードに（`app/unit_economics.py`）

実測定数（判定 ¥0.148/窓、順位付け ¥0.056/窓、保管 ¥0.4/走行）から1走行の支出を出し、
価格帯（¥100: 上限 ¥7.5/走行、¥300: ¥22.5、いずれも4走行/月・粗利70%）に収まるかを返す。
`plan_analysis_run().to_dict()["unit_economics"]` と console の計画段（`per_ride_jpy`,
`fits_tier_100`, `fits_tier_300`）に載る。

実素材2 ride:

| ride | 現行（判定+順位付け40） | 順位付けだけ |
|---|---|---|
| 1つ目（173窓） | ¥28.24 — ¥300帯も×  | ¥11.54 — ¥300帯○ |
| 2つ目（92窓） | ¥16.26 — ¥300帯○ | **¥6.34 — ¥100帯○** |

**次（7.2）: 順位付けだけの経路。** 短い ride は既に ¥100 帯に入り、長い ride は
stride 60秒（7.3）で入る見込み。

---

## 88. 1つ目の日で相対評価が効いた——採用20本のうち8本が入れ替わった

第82節の続き。帯を「点数の上から」ではなく「**決着がつく場所から**」取るよう直した
（`5aac30c`）うえで、1つ目の日（173窓）を順位付けした。

```
rank: 40 窓 / 4 グループ / 約 ¥2.25   provider gemini
film: 41 beat（footage 20 / cards 21）  画面尺 321.0s
```

### 何が変わったか（同じ判定・同じ規則で、順位の有無だけを入れ替えて計測）

| | 順位あり | 順位なし |
|---|---|---|
| 採用 | 20本 / 240.0s | 20本 / 240.0s |
| 入れ替わり | **8本**（40%） | — |
| 採用の平均 interest / story | 0.62 / 0.71 | 0.63 / 0.70 |
| 道の種類（road_family） | highway 15・他5 | highway 15・他5 |

**読み方（誇張しない）**: 順位は作品の**5本に2本**を入れ替えたが、
採用の平均点も道の種類の構成も動いていない。つまりこれは
**「より高い点の窓を採る」変化ではなく、「点が同じ窓のどれを採るか」の変化**である。
第82節（2つ目の日・入れ替え0）との差は帯の位置だけで、決着の場所を訊けば動く。

### 訊いた甲斐があったと言える根拠

- 判定が **ちょうど 0.66** を付けた窓が、順位を訊いた40本のうち **30本**。
  モデルはそれを **2位〜40位** に散らした。作品はそのうち14本を採った。
  点数だけでは決められなかった30本の並びを、比較が決めている
- 上位グループ（点数最上位の10本）の (順位, 点数):
  `(1, 0.72) (2, 0.66) (3, 0.66) (4, 0.68) (5, 0.76) (6, 0.76) (7, 0.66) (8, 0.71) (9, 0.66) (10, 0.82)`
  ——**その日の最高点 0.82 を最下位に、0.72 を1位に**置いた。
  順位は点数の焼き直しではない
- 採用20本の順位は 1..37（40本中）。帯の下端まで使われている

**言わないこと**: この順序が人の判断と一致するとは言わない（照合していない）。
言えるのは「モデル自身の比較が、点数の同点を決めている」ことだけである。

### 支出の累計

| 実行 | 費用 |
|---|---|
| 1つ目の日・判定 173本 | ¥25.56 |
| 2つ目の日・判定 92本 | ¥13.59 |
| 2つ目の日・順位付け 17窓（＋失敗2回） | ≈¥1 |
| 1つ目の日・順位付け 6窓（帯を直す前） | ≈¥0.4 |
| 1つ目の日・順位付け 40窓 | ¥2.25 |
| **累計** | **≈¥42.8**（上限 ¥500） |

---

## 89. 認証切れが「ただの失敗」に見えていた。理由をひとつ足した

2つ目の日を**新しい帯で**順位付けし直そうとして（≈¥2.25、一任の範囲）、止まった。
Google がこの端末のサインインを受け付けなかった（ADC の再認証が要る）。
**何も送っておらず、何も課金されていない**（最初のアップロードで落ちた）。

問題は落ち方だった。ターミナルには他人のフレームのスタックが出て、
**操作卓には `job_failed` としか出ない**。ride が悪いのか、package が悪いのか、
金を使ったのかが読めず、やるべきこと（再サインイン）はどこにも書かれていない。

- `app.analysis_cli`: `CloudSignInExpired`（`AnalysisCommandError` の下位）を足し、
  judge と rank の**課金経路だけ**を包んだ。Google の例外は**名前で見分ける**
  ——ここで import すればこのモジュールの前提（import しただけでは Google に届かない）が
  壊れるため。原因の連鎖（`__cause__` / `__context__`）も辿る
- 文言に、やることと、金の話を入れた:
  「`gcloud auth application-default login` を実行して再試行。
  既に買った分は保持され、二重には買わない」
- 操作卓の理由コードに `cloud_sign_in_expired` を足した（`package_refused_the_request` とは別物）。
  例外の**メッセージは出さない**設計は不変（path を含み得るため）

全1222件成功、Ruff成功。

**ユーザーへ**: `gcloud auth application-default login` を実行するまで、
判定・順位付け（＝Gemini と GCS を使う経路）は動かせない。それ以外は影響なし。

---

## 90. 7.4 ローカルの無料スクリーニングは、測って否定した

Gate 7 は「無料のローカル判定で窓を半分に落とす → ¥2.8/走行」を見込んでいた。
実素材2 ride の**全窓**（173 + 92）に2つの無料信号を当てて測った。**その節約は無い。**

### 測ったこと

| 規則 | 1つ目（173窓） | 2つ目（92窓） | 作品の採用窓を落とした数 |
|---|---|---|---|
| フレーム差分（1fps proxy の隣接フレーム差の中央値） | 3本（1.7%） | 1本（1.1%） | 0 / 0 |
| GPS速度（窓内の最高速 ≤ 1.0 m/s = 停止） | 13本（7.5%） | 10本（10.9%） | **2 / 3** |
| 停車ごとに先頭1本だけ買う | 5本（2.9%） | 3本（3.3%） | **0 / 1** |

- フレーム差分は**ほとんど何も分けない**。カメラが乗り手に付いているので、
  信号待ちでも画面全体が動く。採用された最も静かな窓を割らない閾値では2%未満
- GPS速度は「止まっていた」を正しく読むが、**どの閾値でも作品が採った窓を落とす**。
  落とした窓の最高点は **0.80**——2つ目の日の**その日の最高点**だった
- 両方の作品が停車中の窓を使っている（給油・分岐・到着）。
  **止まっている＝映すものが無い、ではない**

**作品を傷つけない最大の節約は約2%＝¥0.5/走行**（¥28 の請求に対して）。
Gate 7 は仕事の量（判定をやめて順位付けだけ・stride を伸ばす）で払うしかない。

### 何を置いたか（`app/analysis_screening.py`、CLI `screen`）

**測って報告するだけで、何も落とさない。** 支払い経路からは誰も呼ばない
（`drops_nothing: true` を payload に書いて、読む人が信用に頼らなくて済むようにした）。
GPS トラックだけを読み、**動画を1本も開かず、何も送らない**——無料。
渋滞に1時間座る ride では答えが変わり得るので、測定は再現可能なまま残す。

```
python -m app.analysis_cli screen <package>   # 無料・送信なし
1つ目: 173窓 / 停止13 / 停車8 / 未知1 → 全部落として ¥1.92、停車ごとなら ¥0.74
2つ目:  92窓 / 停止10 / 停車7 / 未知5 → 全部落として ¥1.48、停車ごとなら ¥0.44
```

報告は**件数と金額だけ**（窓の識別子・時刻・場所・パスを持たない。テストで固定）。
GPS が何も言わない窓は**決して停止と呼ばない**——「知らない」と「止まっている」は別で、
見ない理由になるのは片方だけ。

全1231件成功、Ruff成功。支出 **¥0**（累計 ≈¥43 のまま）。

### ついでに直したこと

節番号 84・85 が重複していた（並行 session が既出の番号で追記した）。
末尾の2節を **88・89** に振り直し、roadmap の参照2箇所も合わせた。

### この測定が Q2 に渡すもの

同じ作業中に別 session がオーナーの視聴記録を入れた（`user-feedback-2026-09-04-ja.md`、
`b370eb6`）。**Q2「見た目の多様性」が欲しがっている無料信号は、ここで落ちた信号と同じもの**
——1fps proxy のフレーム差である。落とす基準としては使えなかったが、
**隣り合う採用窓が似ているかを測る**なら向きが違う: 閾値を跨ぐ判断ではなく、
窓どうしの比較になる。実測値の分布（1つ目の日: 中央値 3〜63、採用窓は 13〜63）は
`app/analysis_screening.py` の測り方をそのまま使い回せる。

### 残っていること

**品質の単位 Q1〜Q5 が 7.2 以降より先**（オーナーの視聴フィードバック、同 commit）。
7.4 を否定したことで費用側の手段は「順位付けだけ + stride 60（≈¥5.5）」に絞られたが、
それは品質が片付いてからでよい。

**認証は切れたまま**（第89節）。`gcloud auth application-default login` を実行するまで、
判定・順位付け（Gemini / GCS）は動かせない。このため **7.2（順位付けだけの経路）と
7.3（stride 60秒）は実測で閉じられない**——どちらも実際にモデルを呼ばないと
「採用がどう変わるか」を測れない。7.4 を先に片付けたのはそのため。

---

## 91. 本当の2日目を取り込み、判定・順位付け・レンダーまで通した（`day-2-v1`）

ユーザー（2026-09-04 夜）: 「2日目のクリップが全く見当違い。day2 フォルダに入っているので、やり直して」。

**原因**: これまでの `day-two-v1` は **1日目と同じ42本の映像に別の GPX を当てたもの**だった
（`local-video-catalog.json` の中身が `bridge-e2e-v1` と同一）。第82節以降の「2日目」の
数字（92窓・¥13.59・採用の分布）は、実は1日目の映像を別の軌跡で切ったものである。
**`day-two-v1` は捨てる**（比較の基準にしない）。

### 新しい package `day-2-v1`（`private-media/input/videos/day2` + 同フォルダの GPX）

| 段 | 結果 |
|---|---|
| 時計のズレ（`app.clock_offset`） | **−46,800 秒、曖昧さなし**。38本すべて ride 内、次点 37本と明確な差。同じカメラの既知の値 |
| ride | 412 km・8.5 時間・GPS 13,718 点・イベント 49・章 10。映像は 8,392 秒（ride の 27%） |
| 候補（12秒窓・30秒刻み） | **690 窓**（これまでの4倍） |
| preflight | 690/690 成功・失敗 0・**502 MB**（見積 379 MB の 1.32 倍） |
| 判定（Gemini 2.5 Flash） | 690 窓・**¥101.95**。1回目は 433 本目で通信リセットに落ち（432 本は partial に保存）、同じコマンドで残り 258 本だけ買い足した（`carried 432 / newly_bought 258`） |
| 順位付け | 40 窓・4 グループ・**¥2.25** |
| 作品（無音） | 342 秒・footage 20 / カード 20・レンダー 4分28秒。`ride-storyteller-story-film.mp4` |

### 判定の分布（690 窓）

- 総合点 平均 0.55・SD 0.11・最高 **0.80（3本）**・0.75 が 18 本・0.70 以上 40 本
- 採用枠の境界（20位）は **0.75**、境界 ±0.05 に **ちょうど 40 本**——帯（max 40）に全部入った
- 道の種類の上位: 曲がりくねった舗装路 77・田舎の舗装路 72・2車線 47・田舎道 31・2車線ハイウェイ 28。
  1日目（ハイウェイ中心）とは**素材の性格が違う**
- 順位付けは点数の順をなぞった（1〜3位 = 0.80、4〜10位 = 0.75）。1日目の「最高点を最下位に」は
  起きていない。今回の仕事は **同点 18 本（0.75）と 15 本（0.70）の並びを決めた**こと
- 採用 20 本: 平均 0.73・最低 0.70、**全部が順位付け済み**、使った順位 1〜35。道の種類は
  「該当なし」3・曲がりくねった舗装路 2・海沿いの曲がり道 1・…と散っている（同点処理の効果）

### 見つけて直した欠陥（2件、commit 済み）

1. **通信リセット 1 回で 45 分の走行が止まる**（`0682e37`）。`vertex_transport` に
   一過性の失敗（httpx/httpcore の接続系・`ConnectionError`/`TimeoutError`・429/5xx）だけを
   3 回まで間隔を置いて再試行する層を入れた。モデルが答えた失敗は再試行しない
   （拒否を2度払うことになる）。名前で見分けるので HTTP ライブラリを import しない。
   pause は注入可能でテストは待たない。判定・順位付けの両方に効く
2. **proxy の見積が 32% 軽い**（`204b616`）。`MEASURED_PROXY_KILOBYTES_PER_SECOND` を
   1日目の 45.8 から 2日目の実測 **60.6** へ（見積は請求に負けない側の数字にする）

### 7.4 の3つ目の ride

`screen`: 690 窓 / 停止 30（4.3%）/ 停車 10 / 未知 26 → 全部落としても ¥4.44、停車ごとなら ¥2.96。
結論は変わらない（採用 20 本のうち「該当なし」3 本は停車中の絵）。

### 支出

| 実行 | 費用 |
|---|---|
| 第88節までの累計 | ≈¥42.8 |
| 2日目（真）・判定 690 窓 | ¥101.95 |
| 2日目（真）・順位付け 40 窓 | ¥2.25 |
| **累計** | **≈¥147**（上限 ¥500） |

### 単位経済への含み

690 窓の ride は現行経路で **¥104.8/走行**——¥300 帯の上限 ¥22.5 の **4.7 倍**。
1日目（173窓）の ¥28 で「¥300 帯でも赤字」と言っていたが、**長い日は桁が違う**。
順位付けだけ + stride 60 の見込み（≈¥5.5）は 173 窓の線形外挿で、690 窓なら ≈¥22。
**Gate 7 は「窓の数を ride の長さに比例させない」設計（上限つきの候補数、
GPS の瞬間を優先して間引く＝Q1 と同じ機構）が要る。**

### オーナーへ

- 観るもの: `private-media/work/day-2-v1/ride-storyteller-story-film.mp4`（無音。曲は
  `--music <id> --music-only --overwrite` で後から）
- Q1 の判定材料: 「1.5分付近の大きな右カーブ」が今度の作品に入っているか

---

## 92. オーナー視聴（2日目・真）: 博物館が多すぎる → 「一つの場所は1本」（`b184a3f`）

オーナー: 「途中で立ち寄った博物館の映像が多すぎます」。続けて「走行映像の選択は悪くありません。
旅のストーリーを作成するロジックは、まだまだ改善の必要があります」。

### 何が起きていたか

採用 20 本のうち **5 本（画面 1.6〜2.5 分の 1 分間連続）が博物館の屋内**。
判定は博物館の窓に **その日の最高の story 点（0.80〜0.90）**を付け（ランドマーク・停止）、
順位付けは **1・2・5・7・19 位**に置いた。690 窓のうち屋内は 33 本、順位付けした 40 本のうち **16 本**。
選別の間隔規則（120 秒）は「同じ道の区間」を弾くためのもので、20 分の滞在は各窓が 2 分以上離れて
いるため素通りした。**一つの場所に長く居たことが、その場所の窓を増やしていた。**

### 直し方（買い直し ¥0）

- `app/analysis_screening.py` に `halts()`: GPS で**歩く速さ（3 m/s）以下か、軌跡が途切れた**窓の
  連続を「一つの停止」とし、**実測で遅い読みが 1 本以上ある連続だけ**を場所と数える
  （開けた道での GPS 断は場所ではない）。屋内では GPS が消えるので、博物館は「未知」の連続 +
  実測 2.0 m/s が 1 本、として捕まった
- `app/gemini_selection.py`: `JudgedCandidate.halt`、`DEFAULT_MAX_WINDOWS_PER_HALT = 1`、
  理由コード `same_halt_already_shown`。点数には触らない。動いている窓は従来どおり
- `app/private_journey_film.py` が package の GPS から halt を読んで渡す

### 再レンダーの前後（同じ判定・同じ順位、規則だけ追加）

| | 前 | 後 |
|---|---|---|
| 採用 | 20 本 | 20 本（**4 本入れ替え**） |
| 博物館 | **5 本** | **1 本** |
| 採用の平均点 / 最低 | 0.73 / 0.70 | 0.72 / 0.65 |
| 入った窓 | — | 曲がりくねった舗装路 2・山道 1・橋のある市街路 1 |
| 画面尺 | 342 秒 | 345 秒（footage 20 / カード 21） |

1 日目はこの規則で変わらない（採用の停車窓 2 本は別々の場所）。再レンダー不要。

### 「物語ロジック」への指摘（未着手、次の中心）

2日目のカード 21 枚の内訳: **「道はつづく」11**（うち 3 秒の繋ぎ 9）・「登りが続く」4・「下りへ」4・
始まり/終わり各 1。本文は「36分 · 39.3km · 登り528m / 下り166m」型の数字だけ。
つまり今の物語は **地形の断片 × 21** で、その日に何が起きたか（出発 → 海沿い → 峠 → 博物館で 1 時間 →
到着）を一度も語らない。提案: 章を 4〜6 に減らして境界を「性格が変わる場所」に置く／題を GPS の事実
（時刻・峠・海沿い・停止の長さ）と隣接窓の記述から付ける／停止を物語の拍にする。
**地名の扱い（A: GPS の事実だけ／B: オーナーが 1 行の行程を入力）をオーナーに確認中。**

全 1242 件成功、Ruff 成功。支出 ¥0（累計 ≈¥147）。

---

## 93. 研究: 評価の高いバイクツーリング動画（入力を求めない方針の確定）

オーナー（2026-09-04 深夜）: 「ユーザーの入力や選択を求めるのは採用しない。バイクツーリング動画で
評価の高いものはどのようなものか、12 時間を上限に研究せよ」。第92節の A/B は **A（GPS の事実だけ）で確定**、
B の入力欄も作らない。

結果は [`docs/research-touring-video-quality-ja.md`](research-touring-video-quality-ja.md)（約 1.5 時間、
出典が収束したので打ち切り）。要点は 10 規則（§0）と、当システムへの写像 **S1〜S4**（§3）:

1. 一日は「出発→移動→目的地→余韻→締め」の 5 段（三幕と同型）
2. 最初の 15 秒で掴む（cold open: その日いちばんの絵から）
3. 同じ絵を続けない（退屈の第一原因）。POV はつなぎ
4. 物語は「変化」でできている——GPS はその大半を知っている
5. 停止・休憩は物語の拍（ただし一つの場所は 1 本）
6. 時間の経過を見せる（時刻・距離・地図。Relive は成功、Strava flyover は失敗の例）
7. 題は引き、本文は答え、終わりは余韻
8. 一貫性と面白さは別の軸（今のカードは一貫性だけ）
9. 音楽は視聴者を割る。既定は自然音
10. 自動要約の 3 基準（面白さ・代表性・多様性）のうち、多様性と物語が無い

**次の単位は S1（章の骨格）**。roadmap の Q3' を S1〜S4 に置き換えた。支出 ¥0（累計 ≈¥147）。

---

## 94. S1 章の骨格: 21 枚の「道はつづく」を 4〜6 章にした（`89f5cc5`）

研究（第93節）の規則 1・4・7・8 を実装した。`app/ride_chapters.py`。

### 何をするか

- **軌跡を先に切る**（4〜6 章）。境界は GPS が証明する「性格の変化」だけ:
  **長い停止**（≥15 分。速度ではなく**距離**で読む——300 m + 歩く速さ×経過 の範囲に留まっていれば
  同じ場所。GPS が屋内でジッターしても、途切れても、歩いて回っても 1 つの場所。走り出した点で切り詰める）と
  **峠**（前後に 300 m 以上の登り/下り、近傍で最高）。足りなければ最長の章を半分に、多ければ最短の走行章を
  隣に畳む（停止は畳まない。枠が無ければ最も短い停止から吸収）。走行章は一日の 1/3 を超えない
- **章の性格**は証拠から: 停止／出発／到着／峠へ登る（峠で終わり正味登り）／登り／下り／水辺（判定の記述に
  coast・lake 等）／町（town・urban 等）／低地／曲がりくねり（方位変化 ≥40°/km）／速い直線（≥22 m/s）／その他
- **題は 1 作品に 1 度**（性格ごとに 2〜3 種の語彙、尽きたら「先へ」系）。**本文は証拠だけ**:
  「出発から2時間05分 · 71.9km · 海抜93m → 295m」、停止は「ここで72分」
- 判定済みの film では **章カード（6 秒）→ その章の窓（時系列）** の順。繋ぎカードは無くなった。
  判定の無い package は従来の空白カード経路のまま
- `passes()` は O(n)（最初の版は 2 日目 13,718 点で 63 秒 → 0.1 秒）

### 実素材 2 ride（再レンダー ¥0、採用 20 本は不変）

| | 1 日目 | 2 日目 |
|---|---|---|
| カード | **21 → 4** | **21 → 6** |
| 題 | 出発／水辺を走る／登りが続く／到着へ | 出発／ここで休む（72 分）／長い下り（815→67 m）／もう一度止まる（22 分）／町を抜ける／到着へ |
| 画面尺 | 321 → 264 秒 | 345 → 276 秒 |
| 章ごとの窓 | 1 / 9 / 3 / 7 | 5 / 1 / 7 / 0 / 1 / 6 |

2 日目は **博物館が「ここで72分」という章になった**（走行映像 1 本 + カード）。1 日目は停止も峠も無く、
時間で 4 等分——題は判定の記述（水辺）と地形（登り）から付いた。

### 見えたこと（次の単位へ）

- **章ごとの窓の数が偏る**（1/9/3/7、5/1/7/0/1/6）。採用は全体で 20 本を選んでから章に配っているため。
  章ごとの配分（S3 で窓の尺と一緒に）
- 窓の無い章がある（2 日目の 22 分停止）。カードだけで通る。停止の章に窓が無いのは自然だが、走行章なら要検討
- 画面尺が 60 秒ほど短くなった（3 秒カード ×9 が消えた分）。S3 で窓の尺 6〜10 秒可変にするとき再配分
- 時間帯（夜明け・夕暮れ）は使っていない——GPX は UTC で現地時刻が証明できない。カメラの時計は
  現地時刻の可能性が高いが、それを根拠にするのは別の単位

全 1257 件成功、Ruff 成功。支出 ¥0（累計 ≈¥147）。

**観るもの**: 両 package の `ride-storyteller-story-film.mp4`（無音）。1 日目の `-scored.mp4`（曲入り）は
旧版のまま。


---

## 95. UI: 作品の構成と再生（`c688632`）——オーナーが「どの窓か」を指せるように

console の payload は意図して裸（件数・容量・金額・固定 reason code）。この画面はその逆で、
**オーナーが自分の作品を見る**ための私用ビュー: 全 beat を画面順に、章の下に採用窓を並べ、
各窓に**モデルの記述・点数・順位**を添える。「2分目が単調」が窓の一覧を指す言葉になる。

- `GET /api/private-journey/story`（`app/web/private_journey_story.py`）: 章（題・本文・性格・
  開始秒）→ 窓（開始秒・尺・順位・interest/story・道・記述）。cold open は別枠。path・
  asset id・ファイル名は出ない（テスト）
- `GET /private-journey/film`: 完成作品（scored → silent の順）を **byte range で**ストリーム。
  丸ごと読まない（1 MiB ずつ）、リクエストの path は一切使わない、public demo では配信しない。
  200 / 206 / 416 / 404 をテストで固定
- 画面: 作品の `<video>` プレーヤーと、章ごとの窓一覧

2日目（`day-2-v1`、ループが S1〜S3 + Q2 で再構成した版）で確認: 8章・37窓・306秒、作品 1186 MB（無音版）。

### 見つかったこと（ループへ: S2 の追補）

**cold open（順位1位）が博物館の屋内展示**（「薄暗い屋内の展示…」）。Q0 で停止地点は1本に
絞ったが、cold open は順位1位をそのまま採る。研究の規則2「その日いちばんの絵」は走行の絵の
はず。**cold open は halt 内の窓を除いて選ぶ**（moving window のみ）。

全 1295 件成功、Ruff 成功。

---

## 95. S2〜S4: 冒頭と締め・窓の尺と章ごとの配分・見た目の差・無音既定（`d1a4bcc` `55627e6` `e799e13` `23d2353`）

研究（第93節）の残りの規則を実装し、両 ride を再レンダーした（¥0）。

### S2 冒頭と締め（`app/story_opening.py`）

- **cold open**: 順位 1 位の窓（無ければ点数最高）を章から抜いて **最初に 10 秒**、続けて**その日の見出し**カード
  （「413kmの一日 · 8時間31分 · 登り5398m / 下り5764m」）、それから「出発」章
- **締め**: 「今日はここまで · 412.5km · 8時間31分」のカード → 最終章に窓が 2 本以上あれば**最後の 1 本を画で締める**
- タイムラインは時系列が契約なので、計画（plan）の段で組み替える。窓は 1 度しか映さない

### S3 窓の尺と章ごとの配分（`app/story_pacing.py`）と見た目の差（`app/analysis_look.py`）

- **尺**: 順位 1〜5 位は 10 秒、順位付き 8 秒、順位なし 6 秒。同じ尺が 3 本続けば真ん中を変える。
  選別の目標（240 秒）は**画面尺**で数えるので、同じ長さの作品により多くの窓が入る
- **章ごとの配分**: 章の候補数の割合で目標を分け、窓のある章には最低 1 本、停止は 1 本。
  全体で 20 本を選んでから章に配る（1/9/3/7、5/1/7/0/1/6）のをやめた
- **見た目**: 1 fps proxy に `signalstats` を当て、輝度・色 2 軸・フレーム差の 4 数を 1 度だけ測って
  package に保存（`analysis-look.json`。690 窓で 1 分弱）。**前後に映る窓と見た目が同じ（距離 < 0.05）なら
  理由 `looks_like_the_window_before_it` で外す**。強いほうが残る。コピーが読めない package は従来どおり
- 乾式実行: 隣り合う採用窓の「同じ絵」ペアが **4 → 0（1 日目）、10 → 0（2 日目）**。入れ替わり 10 本 / 12 本

### S4 無音既定（操作卓）

`none` を選択肢の先頭・既定にし、無音の作品を「完成」と数える（曲待ちにしない）。状態に `scored` を持つ。
CLI は元から無音既定。

### 実素材 2 ride（最終形）

| | 1 日目 | 2 日目 |
|---|---|---|
| 窓 | 20 → **28**（10 秒 7・8 秒 11・6 秒 10） | 20 → **37**（10 秒 1・8 秒 16・6 秒 20） |
| カード | 21 → **6**（見出し + 4 章 + 締め） | 21 → **8**（見出し + 6 章 + 締め） |
| 冒頭 | 順位 1 位の窓 10 秒 → 「269kmの一日」 | 順位 1 位の窓 10 秒 → 「413kmの一日」 |
| 締め | 「今日はここまで · 269.5km · 4時間10分」→ 最後の 1 本 | 同 · 412.5km · 8時間31分 → 最後の 1 本 |
| 画面尺 | 321 → 254 秒（footage 218） | 345 → 306 秒（footage 258） |
| 音 | 無音 | 無音 |

### 見えたこと

- 2 日目は 10 秒の窓が 1 本だけ。順位 1〜5 位のうち章ごとの選別で残ったのが冒頭の 1 本だけだった
  （他は見た目が同じで外れたか、同じ停止）。尺の段階付けは順位でなく**採用内の順位**で付けるほうが素直
- 見出しの「登り 5398 m」は GPX の高度ノイズを全部足した値。章の本文も同じ。**高度は平滑化してから足す**べき
  （既存の gap カードも同じ癖）。次の小単位
- 1 日目の画面尺が 254 秒に縮んだ（3 秒カード ×9 と 12 秒窓が消えた分）。目標 240 秒 footage に対し 218。
  停止の章や見た目の規則で目標に届かない章が出る。配分の余りを他章に回す改善は S3 の続き

### session の衝突（記録）

同時刻に手動 session が「UI 作品の構成と再生」に着手（`cef0827`、`server.py` に 150 行の未 commit 変更）。
S4 の `server.py` 2 行は **HEAD + 自分の変更だけをインデックスに置いて** commit した（作業ツリーの相手の
変更には触れていない）。`git add app tests` の一括は、相手の未追跡ファイルを巻き込むので使わなかった。

全 1282 件成功（相手の新規テストは除外して実行）、Ruff 成功（同）。支出 ¥0（累計 ≈¥147）。

**観るもの**: 両 package の `ride-storyteller-story-film.mp4`（無音、最終形）。

---

## 96. 高度の平滑化・尺の段階・冒頭は走行窓から（`006146f` `fe0d99c`）

第95節の「見えたこと」と、手動 session の指摘（cold open が博物館の屋内展示）を直した。

- **高度**（`app/gps/elevation.py`）: ヒステリシス 10 m で登り/下りを足す。ジッターは 1 度も数えず、本当の登りは
  全部数える。見出し・章の本文が使う。1 日目 登り 3550 → **1600 m**、2 日目 5399 → **3215 m**
  （GPX パーサの summary と従来の空白カードは生の合計のまま——別経路なので今回は触っていない）
- **尺の段階**: 「モデルの順位 1〜5 位」ではなく**採用した窓の中の上位 1/5** に 10 秒。2 日目の 10 秒が 1 本 → 8 本
- **冒頭**: 停止（halt）に属する窓は候補の最後尾へ。2 日目の冒頭は順位 1 位の博物館展示から、
  **順位 11 位の 2 車線ハイウェイの走行窓**に変わった。博物館は作品に 1 本（章「ここで休む」）だけ

| 最終形 | 1 日目 | 2 日目 |
|---|---|---|
| 窓 / カード / 画面尺 | 28 / 6 / 256 秒 | 37 / 8 / 320 秒 |
| 尺 | 10 秒 8・8 秒 10・6 秒 10 | 10 秒 8・8 秒 9・6 秒 20 |
| 見出し | 269kmの一日 · 4時間10分 · 登り1600m / 下り1234m | 413kmの一日 · 8時間31分 · 登り3215m / 下り3579m |
| 冒頭の窓 | ハイウェイの走行 | 2 車線ハイウェイの走行（順位 11 位） |

両 ride 再レンダー済み（¥0）。全 1307 件成功（手動 session の story view のテストを含む）、Ruff 成功。
支出累計 ≈¥147。

**残り（小）**: 配分の余り（1 日目 footage 220/240 秒）を他章に回す。**次（大）**: Q1（GPS の瞬間を候補に）か、
Gate 7 の費用側（7.2 順位付けだけの経路、候補数の上限）。オーナー再視聴の結果で決める。

---

## 97. 自律ループの第3層: private ミラーとクラウド routine（push は承認、公開はまだ）

オーナー（2026-09-05）: 「pushを承認する。公開はまだ。プライベートのまま開発継続。まだ満足のいくものになっていない。」

- private ミラー `TKMT-ish/ride-storyteller-dev` を作成し、remote `dev` として main を push。
  `main` の upstream は `dev/main` に設定した——**素の `git push` は private へ行き、公開 origin には行かない**
- 公開 origin への push・デモ公開・Cloud Run 公開 IAM・Devpost 提出は、オーナーが作品に満足するまで行わない
- 第3層 = クラウド routine（2時間毎、private ミラー上、コード・テスト・文書の単位のみ、`cloud/<日時>` branch へ push）。
  実素材・Gemini・GCS・資格情報には触れない。ローカルの層が `cloud/*` を検証して main へ取り込む

研究「より良いツーリングビデオ編集」（前節）と合わせ、Notion に「07｜研究」ページを新設。

---

## 98. 第3層が稼働: クラウド routine `ride-storyteller-cloud-loop`

- routine id `trig_01QRkyS49cGeqyif7yzNiMB5`、**2時間毎**（cron `35 */2 * * *` UTC）、モデル claude-sonnet-5、
  対象は private ミラー `TKMT-ish/ride-storyteller-dev` の main。初回を手動起動（session `cse_014kYHxWymNxvxG573KpXVt7`）
- 担当は**コード・テスト・文書の単位だけ**（実素材・Gemini・GCS・資格情報に触れない。ネットワーク呼び出しを
  テストに入れない）。成果は `cloud/<日時>` branch へ push、main へは直接 push しない。公開 origin には触れない
- 自動で付いた MCP 接続（Notion / Drive / Calendar）は**外した**——クラウド層に要らない権限は持たせない
- ローカルの層が `git fetch dev` して `cloud/*` をテスト緑なら main に取り込み、branch を消す（デスクトップの
  タスクのプロンプトに規約を追加済み）

三層の役割分担:

| 層 | 実体 | 担当 | 動く条件 |
|---|---|---|---|
| 1 | デスクトップ scheduled task（30分毎） | 全単位（実素材・支出を含む） | アプリが開いている |
| 2 | launchd watchdog（heartbeat 45分途絶で起動） | 同上（同じプロンプト） | Mac が起きている |
| 3 | クラウド routine（2時間毎） | コード・テスト・文書のみ | 常時（Mac が落ちていても） |
## 99. クラウド層: E-4 の題12字・本文21字の整形関数（`0fd8772`）

自律ループ第3層（クラウド routine）による初回の実行。実素材の実測が要らない単位として、
研究（第93節・第94節の編集研究、`docs/research-touring-video-editing-ja.md` §5）が挙げた
E-4「題を動く絵の上に」のうち、**下三分の一へ移す映像合成そのものではなく、文字を
題12字・本文21字に収める整形関数だけ**を選んだ（動く絵への合成は実素材での見た目確認が
要る大きい単位なので次に残す）。

`app/lower_third_text.py`: `fit_title`（12字既定、超えたら末尾を省略記号1字に置き換えて
切る）、`fit_body`（本文の各部分を「重要な順」に渡し、収まるまで末尾から間引く。最初の
一部分は落とさない契約。それすら単体で超える場合は `fit_title` と同じやり方で切る）、
`fit_lower_third_text`（両方を1度に）、`LowerThirdText`（構築時に両方の上限とタイトル・
本文が空でないことを検証する frozen dataclass）。既存の `app.ride_chapters` の題・本文の
語彙はそのまま使い、ここでは長さだけを整える——語を言い換えない。

テスト `tests/test_lower_third_text.py`: 24件、合成 fixture のみ（実素材なし）。境界
（ちょうど上限、上限+1）、間引きの優先順位（最初の部分は残る）、間引いても収まらない
場合の切り詰め、空・空白のみの部分の無視、カスタム区切り文字・カスタム上限、
`LowerThirdText` の各不変条件（題/本文が空、上限超過）を確認。

環境: `pip install -e '.[dev]'` で `google`/`vertexai`/`agentplatform` の import は解消。
`ffmpeg` が無い環境のため `tests/test_judged_film_end_to_end.py`（6件）のみ `--ignore` で外した
（レンダーパイプラインの end-to-end で、コード側の問題ではない）。全 1325 件成功
（新規24件を含む）、Ruff check/format 成功。支出 ¥0（実素材・Gemini・GCS には触れていない）。

**次に推奨**: E-4 の残り（下三分の一への実際の合成、章カードの置き換え）はオーナー再視聴を
要する大きい単位なので、ローカル層向け。クラウド層の次単位は E-2「フレーム差から尺を決める」
関数（1fps proxy のフレーム差という数値入力から尺を決める部分のみ、合成 fixture で完結）、
または S3 の「配分の余りを他章に回す」の続き。

## 100. E-3 動く経路図: 章の区間が伸びて止まる（`9c2bd74` `e7e46a2`、手動 session）

**やったこと**: 章カードを1枚の静止画から「最初の数秒で区間の強調線が伸び、止まる」連番フレームに
した。研究 §4.2（区間は3〜5秒で描き、到達点で止める）に沿う。

- **見出しカード**（`GapCharacter.HEADLINE`）は 6 秒で**全行程**を描く。**締め**は描き切った状態の
  静止画。**章カード**は 3.5 秒でその章の区間が伸びる（12 fps、章 42 フレーム、見出し 72 フレーム）。
- 章は**章カード同士で**経路を分け合う（見出し・締めを除く）。見出しや締めがあっても
  最初の章は出発点から始まり、最後の章は到着点で終わる。
- フレームは普通のカードと同じ HTML（`card-NNN-fXXX.html`、完成図は `card-NNN.html` のまま）。
  **全カードの全フレームを Quick Look 1回の呼び出し**で描く（`QuickLookRasteriser.batch=True`、
  Chromium は 1 ページ 1 呼び出しのまま）。
- ffmpeg 側は `-framerate 12 -start_number 1 -i card-NNN-f%03d.html.png` の image2 連番に
  `tpad=stop_mode=clone:stop_duration=D,trim=duration=D,setpts=PTS-STARTPTS` を前置し、最後の
  フレームを beat の残り時間だけ保持する。連番を許すのは GAP_CARD のみ（他は ValueError）。
- `write_chapter_cards(...) -> tuple[CardRaster, ...]`（`CardRaster(still, pattern, frame_rate)`）。
  `build_story_film_segments` は `Path | CardRaster` のどちらも受ける（旧呼び出しは無変更で動く）。
  経路が無い／`animate=False` なら従来どおり静止画。
- 既存テストの偽ラスタライザは「命令の最後の1ページだけ描く」前提だったので、
  「命令中の全 `.html` に PNG」へ直した（`test_story_film.py`、`test_private_journey_film.py`）。

**テスト**: 新規 `tests/test_story_film_moving_route.py` 10 件（フレーム数、単調増加、見出しの全行程、
締めの静止、章同士の分け合い、Quick Look 1回、Chromium はページ毎、静止画フォールバック、
命令の形、区分の不変条件）。**全 1341 件成功、Ruff 成功**。

**実測（両 ride 再レンダー、`--overwrite`、`story-cards` は削除してから）**:

| package | カード | PNG（内フレーム） | レンダー | 作品尺 | ファイル |
|---|---|---|---|---|---|
| 2日目 | 8 | 320（312） | 258 s | 320.6 s | 1.31 GB |
| 1日目 | 6 | 234（228） | 223 s | 256.4 s | 720 MB |

Quick Look は 25 枚@1920² を 0.72 秒で描くので、フレーム化のコストはレンダー全体の中では
無視できる（レンダー時間はほぼ footage の再エンコード）。**作品ファイルが 1 秒あたり 3〜4 MB**
（≈32 Mbps）なのは今回の変更ではなく従前からの出力設定で、配信する製品としては高すぎる。
出力ビットレートの単位（8〜12 Mbps、1080p）を roadmap に追加すべき。支出 ¥0。

**見て分かった追補**（roadmap E-3 に記載、ループへ）:
1. 見出しカードの地図が小さい（19vw）。全行程を描く 6 秒の主役なので 30vw 程度に。
2. 停止の章（「ここで休む」）まで**区間**が強調される。停止は**点**で示すべき。
3. 区間は位置比（章 i / 章数）で割っている。章カードに ride 時刻を持たせ、**章の実時刻**で
   区間を切る契約変更が必要（`GapChapterCard` に `starts_at`/`ends_at` を足す）。

**オーナー再視聴**: 見た目が変わる単位なので PushNotification 1通で両作品の再視聴を依頼した。
## 101. E-3 追補: 章の実時刻で区間・停止は点・見出しの地図を大きく（`4dc0641` `45bb129` `adc6181`、手動 session）

§100 の絵を見て分かった三点を直し、両 ride を再レンダーした。

- **章カードが ride の時計を持つ**: `GapChapterCard.since_departure_s` / `duration_s`（出発からの秒数と
  長さ。時刻そのものは持たない。`is_on_the_clock`）。`ride_chapters.chapter_cards` が `RideChapter` から
  埋め、`story_package._beat_from_dict` は無ければ `None`（古い plan も読める）。片方だけは ValueError。
- **区間は章の実時刻で切る**: `story_film._card_spans` が全章カードに時計があれば track の timestamp を
  `bisect` して first/last を決める（無ければ従来の位置比 `_stretch_indices` にフォールバック）。
- **停止（HALT）は点**: `route_map_svg(..., mark_index=)` が `<circle class="mark">` を描く（停止の
  真ん中の時刻で track が居た点。位置比フォールバックでは自分の区間の中央）。停止カードは伸びる動きなし
  （静止画 1 枚）。
- **見出し・締めの地図は 30vw**（`wide=True` → `class="map map-wide"`。章カードは 19vw のまま）。
- **前回の描画の残骸を消す**: `write_chapter_cards` は描く前に `card-*` を削除。停止が「動く→静止」に
  変わった今回、古い連番が残ると ffmpeg が読み続けるところだった。

**テスト**: 11 件追加（時計で切った区間の点数、停止の点の位置、位置比フォールバック、1 章だけ時計が
無い plan、見出し・締めの wide、SVG の mark・wide、章カードが章の時計を持つ、plan の往復、半分の時計の拒否、
残骸の削除）。**全 1353 件成功、Ruff 成功**。

**実測（再レンダー、`--overwrite`）**:

| package | カード | PNG（内フレーム） | レンダー | 作品尺 | ファイル |
|---|---|---|---|---|---|
| 2日目 | 8（停止 2） | 236（228） | 261 s | 320.6 s | 1.31 GB |
| 1日目 | 6 | 234（228） | 644 s（前回 223 s。同時に別 session の pytest が走っていた） | 256.4 s | 720 MB |

2日目の停止 2 枚が静止画になり、フレームは 312 → 228。作品尺・ファイルサイズは不変（≈32 Mbps、
**E-8 配信できる出力** として roadmap に追加。既に `libx264 -preset -crf` で出力しているので CRF/上限
ビットレートの見直しで済むはず）。支出 ¥0。

**整形のみの commit**: venv の ruff が 0.16.2 になり、`ruff format` が 49 ファイルを整形した。全ファイルの
構文木が HEAD と同一であることを `ast.dump` で確認して `adc6181` に分けた（dev extra は `ruff>=0.6`。
クラウド層は fresh install なので同じ整形になる）。

**オーナー再視聴**: §100 の依頼の後で絵が変わったので、差し替えた旨を PushNotification で 1 通。
## 103. E-8 配信できる出力: CRF 23・上限 12 Mbps（`88121ef`、手動 session）

**やったこと**: `build_story_film_command` の H.264 出力を CRF 20・上限なし → **CRF 23、`-maxrate 12000k
-bufsize 24000k`** に（`STORY_FILM_CRF` / `STORY_FILM_MAX_BITRATE_KBPS` / `STORY_FILM_BUFFER_KBITS`）。
`-preset medium`、`format=yuv420p`（フィルタ側）、`+faststart` は従来どおり。音楽の合成
（`story_music.py`）は `-c:v copy` なので映像ビットレートはここだけで決まる。

**実測（2日目、320.6 秒、同じ cut）**:

| | CRF 20（前） | CRF 23 + 12 Mbps（今） |
|---|---|---|
| ファイル | 1.31 GB | **414 MB** |
| 平均ビットレート | 32.7 Mbps | **10.3 Mbps** |
| 前版との類似（冒頭 60 秒） | — | SSIM 0.955（Y 0.938）/ PSNR 34.4 dB |

3.2 倍小さく、スマホの回線で見られる帯域。SSIM/PSNR は「CRF 20 の版とどれだけ違うか」であって
原素材への忠実度ではない（原素材との比較は cut が同じ時間軸に無いので不能）。目で見て判断するのは
オーナー再視聴に含める。レンダー 695 秒は同時刻に macOS の `mediaanalysisd`（新しい動画ファイルの索引）
が CPU 85% で走り load average 27 だったため。この設定の所為ではない（静かな時に測り直す）。

**テスト**: 新規 `tests/test_story_film_delivery.py` 3 件（品質目標と上限が命令にある、上限が配信帯域
6〜12 Mbps・VBV ≥ 1 秒・CRF 21〜26、ヘッダー先頭と無音）。**全 1374 件成功、Ruff 成功**（クラウド層の
`cloud/20260905-0036`、E-2 の `app/story_hold.py` を取り込んだ後の数）。支出 ¥0。

**次**: E-4 題を動く絵の上に（クラウド層の `app/lower_third_text.py` の整形関数を使う）。

## 102. クラウド層: E-2 の尺を変化量で決める関数（`ded120e`）

自律ループ第3層（クラウド routine）による2回目の実行。§99 の推奨どおり、E-2「尺を変化量で決める」
（研究 §3: 順位だけでなく画面内の変化量で尺を決めるべき、変化が少ない窓ほど短く）のうち、
**実際の合成・選定への組み込みではなく、尺を決める関数そのものだけ**を選んだ（`footage_for` への
配線は全レンダー済みクリップの尺を変える見た目側の判断で、オーナー再視聴を要する大きい単位として
次に残す）。§101 と同時進行の E-8（09:35 JST 着手、レンダー出力設定）とは別モジュールで競合なし。

`app/story_hold.py`: `app.story_pacing` の固定尺 10/8/6 秒を、研究が挙げる範囲（最良級 8〜10秒・
通常 5〜7秒・つなぎ 3〜4秒）に広げた。`hold_range_for`（順位→範囲、`hold_for` と同じ閾値）、
`hold_from_motion`（1窓の尺を、`app.analysis_look.WindowLook.motion`（1fps proxy のフレーム差の
平均）と、その窓が入る集合内の下限・上限から範囲内の位置として決める。下限で範囲の下端、上限で
上端、下限=上限なら中点にクランプ）、`hold_all_from_motion`（集合全体を1度に決め、`footage_for` と
同じやり方で3本連続同尺の真ん中を寄せる）。`app.story_pacing.hold_for`/`paced`/`footage_for` は
無変更——尺の決め方を実際に切り替えるのは見た目に効くコード外の判断とし、ここでは触れない。

**テスト** `tests/test_story_hold.py`: 18件、合成 fixture のみ（実素材なし）。順位による範囲の
振り分け、下限・上限・中点での位置、範囲外の値のクランプ（外挿しない）、下限=上限での中点、
負の変化量・逆転した範囲の拒否、単独窓の中点、集合内での相対位置による範囲いっぱいの分布、
3本連続同尺の真ん中寄せ（最初・最後は対象にならないことを含む）、集合内の不正な値の拒否。

環境: `pip install -e '.[dev]'` で `google`/`vertexai`/`agentplatform` の import は解消。`ffmpeg` が
無い環境のため `tests/test_judged_film_end_to_end.py`（6件）のみ `--ignore` で外した（レンダー
パイプラインの end-to-end で、コード側の問題ではない）。全 1365 件成功（新規18件を含む）、
Ruff check/format 成功。支出 ¥0（実素材・Gemini・GCS には触れていない）。

**次に推奨**: `hold_all_from_motion` を `footage_for` に配線し両 ride を再レンダーしてオーナー再視聴
（見た目が変わる大きい単位、ローカル層向け）。クラウド層の次単位は E-1「章内の並び」のうち計算だけの
部分（章内の窓を動きの多寡で交互に並べる関数）、または研究 §3 のもう一方「12秒のどの6秒を使うか」
（1fps のフレーム差の系列から前半・後半どちらを使うか選ぶ関数、同じく合成 fixture で完結）。
## 104. E-4 題を動く絵の上に（`f23773a` `6c0e2b6`、手動 session）

**やったこと**: 章カードで 6 秒止まる代わりに、章の題が**章の最初の窓の下三分の一に 5 秒だけ**重なる
（研究 §5.2〜5.3、E-4）。見出し（S2）と締めは全画面のまま。

- **plan の契約**（`story_package.py`）: footage の beat が `card` を持てる（`is_titled_footage`）。題の
  `screen_duration_s` は窓を超えられない。`beats_with_cards`（描く順）と `card_beats`（全画面のみ）を分けた。
  古い plan（footage に card 無し）はそのまま読める。
- **`app/story_titles.py` `title_over_footage(plan)`**: 「章カード → 直後の窓」を 1 つの題付き窓に。題は
  `min(5, 窓 − 1)` 秒、3 秒未満になる窓（4 秒未満）はカードのまま。後に窓が無い章（撮っていない章）も
  カードのまま。`plan_journey_film` の判定経路で `frame_the_film` の後に適用。冪等。
- **描画**（`chapter_card.build_lower_third_html`）: 黒地の正方形ページの 16:9 帯の最下 2/9（1080 中 240 px）に
  題 3.6vw 太字・本文 1.9vw、右端に経路図 10.4vw。題 12 字・本文 21 字に整形（クラウド層の
  `fit_lower_third_text`、本文は末尾の要素から落とす）。本文の要素が題と同じなら落とす（「出発 · 112.3km」→
  「112.3km」）。経路の区間が伸びる動き（E-3）はそのまま 3.5 秒。線は帯用に太く明るく。
- **合成**（`story_film._lower_third_chains`）: 帯を `crop`（帯→最下 2/9）→ `format=rgba` →
  `colorchannelmixer=aa=0:ar=.299:ag=.587:ab=.114`（**明度をアルファに**。Quick Look は透過 PNG を出さない
  ので、黒地に描いて明度で抜く）。その下に `color=black@0.55` の半透明バンド。両方 0.4 秒でフェードイン／
  アウト、`overlay=eof_action=pass:repeatlast=0` で帯が終われば footage が素通り。入力は題付き窓ごとに 1 本増。
- **コンソール**（story view）: 題付き窓を章の始まりとして並べ、`over_footage: true` を付けた。

**テスト**: 21 件追加（`test_story_titles.py` 5、`test_story_film_lower_third.py` 11、chapter_card 3、
story_package 2、story view 1）。e2e は `card_beats` → `beats_with_cards`。**全 1395 件成功、Ruff 成功**。

**実測（両 ride 再レンダー）**:

| package | 全画面カード | 題付き窓 | 作品尺 | ファイル | 平均 |
|---|---|---|---|---|---|
| 2日目 | 2（見出し・締め） | 6 | 320.6 → **284.6 s** | 406 MB | 11.4 Mbps |
| 1日目 | 2 | 4 | 256.4 → **232.4 s** | 330 MB | 11.4 Mbps |

絵の確認（2日目 18.5 s／76.5 s／21.5 s のフレーム）: 題と本文はバンドの上で読める、5 秒後は素の映像。
帯の経路図は最初の版で細すぎた（→ 線を太く明るく `6c0e2b6`）。支出 ¥0。

**判断の記録**: 研究の閉じ方「冒頭 15 秒にカードが無い」は見出しカードと衝突する。オーナーは経路図＋短い題を
評価しているので**見出しは残し**、E-4 の閉じ方は「章カード全画面が消える」のみとした。

**残り（roadmap E-4 に記載）**: 題の語彙に「引き」（「この先、峠」）／帯の経路図の存在感（帯からはみ出す
小さな地図パネルにするか）。

**オーナー再視聴**: 見た目が変わる単位なので PushNotification 1 通。
## 105. Q1 GPS の瞬間を候補に戻す（`42f517b`、手動 session）

**問題**: 候補窓は footage を 30 秒おきに 12 秒切るので録画の 6 割は一度も判定されず、窓と窓の間のカーブは
選ばれようがなかった（オーナー指摘「大きく右に曲がるシーンが含まれていない」）。

**やったこと**:
- **`app/gps/turns.py` `sharp_turns(points)`**: 走行速度（≥ 4 m/s）で 10 秒以内に進行方向が 90° 以上振れる
  区間を 1 つのカーブとして検出（符号付き、右が正。`SharpTurn.to_dict` は集計のみ）。既存の per-sample
  方向イベント（60°）は停車中の GPS ノイズで 2日目に 426 件出るので使わない。2日目の実測（ローカル読取り）:
  90°/10 s で 83 カーブ、うち 47 が既存の窓の外。110° なら 40／25。
- **`footage_candidates.turn_candidates`**: 録画内で窓に入っていないカーブごとに、カーブの中央を中心にした
  12 秒窓を追加（鋭い順に最大 24 本、録画と ride の内側にクランプ、時計オフセット込み、ID は窓自身から
  作るので既存窓と一致すれば同じ候補）。`plan_analysis_run` が stride の窓に足す。
- **`run_analysis`**: 完成済みの判定記録も「買い済み」として扱う。`--overwrite` の再実行で追加窓だけを買う。
- **選抜**（`select_judged_candidates(moments=)`、`select_by_chapter`、`plan_journey_film`）: 点数が同じ
  （±0.02）窓の中では、track が証明するカーブを持つ窓を**先に**取り、その後にモデルの順位。
  `gemini_selection.window_moments` がカーブの中央を含む窓を対応付ける。

**支出**: 2日目の追加 24 窓を判定 **¥3.55**（154 秒、記録 690 → 714）。**累計 ≈¥151**（上限 ¥500）。

**結果（2日目再レンダー）**: 判定済み 714 窓のうちカーブを含む窓 65、採用 37 窓のうち **15 がカーブを含む**。
追加した 24 窓の平均点は 0.477（全体 0.551）で、採用は 1 本のみ。鋭いカーブ（163°、144°）は町中の交差点
らしく、モデルは高く見ない。**候補には戻し、同点なら優先する**が、最終判断はモデルの点数のまま——
これは意図どおり（GPS の事実が候補を保証し、良し悪しはモデルが決める）。作品尺 288.6 秒。
オーナーの言う「右カーブ」がどれかは特定できない（別の日の作品での指摘）ので、閉じ方は「カーブ窓が候補に
入り、採用されている」で読み替えた。

**テスト**: 16 件追加（`test_gps_turns.py` 8、footage_candidates 6、analysis_run 1、gemini_selection 1）。
**全 1411 件成功、Ruff 成功**。

**1日目**: 同じ処置に ≈¥3.5 かかる。次のループで plan → 判定 → 再レンダー。

## 106. クラウド層: E-2 のもう一方「12秒のどの6秒を使うか」を決める関数（`83d8401`）

自律ループ第3層（クラウド routine）による3回目の実行。§102 の完了時に残した二択
（E-1「章内の並び」／E-2 の残り「12秒の判定窓からどの6秒を使うか、動きで前半・後半を選ぶ」）
のうち後者を選んだ。手動 session が同時刻に Q1（`app/gps/turns.py` 等）に着手中（10:44 JST、
2時間以内）だったため、Q1 が触れているファイル（`analysis_run.py` `footage_candidates.py`
`gemini_selection.py` `gps/turns.py` `private_journey_film.py` `story_pacing.py`）とは無関係な
新規モジュールを選んだ。

`app/story_clip_half.py`: `choose_window_half(frame_to_frame_motion, *, window_seconds,
half_seconds)`。`app.analysis_look.measure_look` が `WindowLook.motion`（平均）に潰す前の
1fps フレーム差の系列（1秒境界ごとに1値、窓が `window_seconds` 秒なら `window_seconds - 1` 個）
を受け取り、窓の中央付近（前半・後半それぞれが自分の端から `half_seconds - 1` 個を取った残り）
を両方の平均から除いた上で、平均動き量の大きい方の半分（`front`/`back`）と、その半分の開始秒
（`front` なら 0、`back` なら `window_seconds - half_seconds`）を返す。同点は `front` を残す
（視聴者は前半を先に見るので、同点が後半を選ぶ根拠にはならない）。`app.story_hold` と同じく
実際の trim・`app.story_pacing` への配線はしない（判定済み12秒の半分を捨てて使う、という
見た目に効く判断はオーナーが見てから切り替えるべきもの）。

**テスト** `tests/test_story_clip_half.py`: 12件、合成 fixture のみ（実素材なし）。前半・後半
それぞれが勝つ場合、同点で前半が残る場合、中央の除外区間（そこだけに極端な値を置いても結果が
振れないことで確認）、偶数・奇数の窓/半分の組み合わせでの開始秒、系列の長さ不一致・半分が窓に
収まらない・半分が0以下・半分が2秒未満・動き量が負・非有限（inf）の拒否。

環境: `pip install -e '.[dev]'` で `google`/`vertexai`/`agentplatform` の import は解消。`ffmpeg` が
無い環境のため `tests/test_judged_film_end_to_end.py`（6件）のみ `--ignore` で外した（レンダー
パイプラインの end-to-end で、コード側の問題ではない。§102 と同じ理由）。全 1417 件成功
（新規12件を含む）、Ruff check/format 成功（format 1ファイル整形——新規ファイルの1行が
100桁ぎりぎりだった）。支出 ¥0（実素材・Gemini・GCS には触れていない）。

**次に推奨**: E-1「章内の並び」（章の最初の窓は題に合う窓を優先・章の中は動きの多寡を交互・
最後は長め）のうち計算だけの部分（窓の動き量の系列から交互の並び順を返す関数）。Q1 の
着手中が外れていれば Q1 の続き（`turns.py` の corner window を選抜で実際に優先する側、または
オーナー実測）も候補。E-2 の両関数（`hold_all_from_motion` と `choose_window_half`）を
`footage_for`／実際の trim に配線して両 ride を再レンダーするのは見た目が変わる大きい単位
としてローカル層向けに残る。

## 107. クラウド層: E-1 章内の並びを決める関数（`6197b44`）

自律ループ第3層（クラウド routine）による3回目の実行。§102 の推奨どおり、E-1「章内の並び」
（研究 §2.2: 章の最初の窓は「章の題に合う」窓、章内は動きの多寡を交互に、最後は長め）のうち、
**並び順を決める関数そのものだけ**を選んだ（実際の footage・beat への配線は次単位として残す）。
Q5（着手中: 2026-09-05 11:58 JST、手動 session）とは別モジュールで競合なし。

`app/chapter_order.py`: `ChapterWindow(window_id, motion, opens_chapter=False)` と
`order_chapter_windows(windows) -> tuple[str, ...]`。オープナー（`opens_chapter=True` の窓、
高々1本）を先頭に固定し、残りは `app.analysis_look.WindowLook.motion` で降順に並べた列の
両端から交互に取り出す（大→小→大→小…）ことで、動きの多寡が3本連続で同じ側に偏らない列を作る。
「章の最後は長め」は尺の決定（`app.story_hold` が既に持つ）であって並び順ではないため、ここでは
触れない。path・アセットID・章題の文言は一切読まない。

**テスト** `tests/test_chapter_order.py`: 12件、合成 fixture のみ（実素材なし）。単独窓、オープナー
優先（動きが最小でも先頭）、オープナー無しでの全体ジグザグ、2本のみでの高→低、9本での「3本連続
同じ側」不在の検証、動きが同点のときの `window_id` によるタイブレークで並びが決定的であること、
空の章・重複ID・オープナー2本・負の動き・非有限の動き・空IDの拒否。

環境: `pip install -e '.[dev]'` で `google`/`vertexai`/`agentplatform` の import は解消。`ffmpeg` が
無い環境のため `tests/test_judged_film_end_to_end.py`（6件）のみ `--ignore` で外した（レンダー
パイプラインの end-to-end で、コード側の問題ではない）。全 1417 件成功（新規12件を含む）、
Ruff check/format 成功。支出 ¥0（実素材・Gemini・GCS には触れていない）。

**次に推奨**: 研究 §3 のもう一方「12秒のどの6秒を使うか」（1fps のフレーム差の系列から前半・後半
どちらの動きが多いか選ぶ純計算関数、合成 fixture で完結）。または S3 に残る「配分の余りを他章に
回す」の続き。`order_chapter_windows` を実際の章 beat へ配線するのは見た目に効く判断のため
ローカル層向け。Q5（映像中心のデモ）は手動 session が着手中のため触れていない。

## 108. クラウド層: E-2 のもう半分・12秒のどの6秒を使うか（`d3598d0`、`app.story_clip_half` と重複）

自律ループ第3層（クラウド routine）による3回目の実行。§102 末尾の推奨どおり、E-2「尺を変化量で
決める」（研究 §3）のうち前回残した**もう一方**——「12秒の判定窓のどちらの6秒を使うか、動きで選ぶ」
——の、選ぶ関数そのものだけを実装した（実際の cut 位置への配線は見た目が変わる判断として次に残す）。

`app/story_hold.py` に追加（E-2 の尺決定と同じ module。別モジュールに分けるほど独立していない）:

- `WindowHalf`（`FIRST`/`SECOND`）と `DEFAULT_HALF_DURATION_S`（6.0秒）。
- `motion_by_half(motion_series)`: 1fps のフレーム差系列（`app.analysis_look.measure_look` が
  内部で計算し平均へ潰している YDIF そのもの）を中点で前半・後半に割り、それぞれの平均を返す。
  奇数個は後半へ寄せる（前半が常に得をしないため)。
- `choose_half_by_motion(motion_series)`: 後半の平均が前半より大きければ `SECOND`、それ以外
  （同点・全く動かない窓を含む）は `FIRST`——今日すでに窓の先頭から切っている挙動と一致させ、
  後半が明確に勝るときだけ cut の開始点を動かす。
- `trim_bounds_for_half(window_duration_s, half, half_duration_s=6.0)`: 選んだ半分を
  「窓自身の先頭からの (start, end) 秒」に変換。窓が半分の尺以下なら両者とも窓全体にクランプする
  （無い秒数を要求しない）。

`app.story_pacing` の「窓は先頭から切る」規則へは配線していない——毎クリップの in point が変わる
見た目に効く判断であり、オーナーが後半始まりの窓を見る前にコードだけで切り替えるべきではない
（§102 の尺関数と同じ理由）。

**テスト** `tests/test_story_hold.py` に10件追加（偶数・奇数系列の分割、単独/空系列の拒否、
系列内の負値の拒否、同点と無動作窓が前半を保つこと、`trim_bounds_for_half` の既定・カスタム尺、
窓が半分の尺以下または丁度等しい場合のクランプ、非正の窓尺・半分尺の拒否）。合成 fixture のみ。

環境: 前回と同じく `pip install -e '.[dev]'` で `google`/`vertexai`/`agentplatform` の import は解消。
`ffmpeg` が無い環境のため `tests/test_judged_film_end_to_end.py`（6件）のみ `--ignore` で外した
（レンダー end-to-end で、コード側の問題ではない。前回と同一理由）。**全 1421 件成功
（新規10件を含む）、Ruff check/format 成功**。支出 ¥0（実素材・Gemini・GCS には触れていない）。

**重複の記録**: §106 の `app.story_clip_half.choose_window_half` と本節の `app.story_hold.
choose_half_by_motion`/`trim_bounds_for_half` は同じ問い（判定済み12秒窓のどちらの6秒を使うか）
に別モジュールで別々に答えた——クラウド層の2つの routine 実行が互いの成果を知らず並走したため。
どちらもテストは通り config はしていない（見た目に効く配線はまだ無い）ので両方を残すが、
実際に `footage_for`／trim へ配線する単位ではどちらか一方を選び、もう一方を削るべき（次の
ローカル層セッション向け）。

**次に推奨**: (a) 上の重複を解消してから、選んだ方を実際の cut 位置へ配線し両 ride を
再レンダーしてオーナー再視聴（見た目が変わる大きい単位）。(b) クラウド層の次単位は S3 に残る
「配分の余りを他章に回す」、または研究に残る他の計算だけの単位。

## 109. Q5 デモを映像中心に（`2b59f61`、デスクトップ・スケジュールタスク）

ロック取得時、`app/submission/demo_assembly.py` に未コミットの変更が残っていた（`CaptionedExcerpt`
と `caption_html` は定義済みだが `demo_timeline`／`assemble_demo` のどちらからも呼ばれておらず、
未使用 import も残っていた——手前のセッションが打ち切られた形跡）。handoff に該当する「着手中」
行は無く heartbeat も古かったため、他層と衝突していないと判断し、この Q5 の実装として仕上げた。

**問題**（`user-feedback-2026-09-04-ja.md` Q5）: 3分のデモが「カードで始まりカードで進み、最後の
15秒だけ映像」という構成で、動画製品のデモというよりスライドショーに見える。

**やったこと**: 6枚あったカードのうち5枚（problem・evidence・clock・gemini・close）を、作品映像の
一部＋下三分の一のテロップ（`app.chapter_card`／`app.story_film` の章見出しの帯と同じ寸法・同じ
「明度をアルファに変換して白文字だけ残す」合成）に置き換えた。残る1枚（コンソールの数字を出す
`console` カード）だけが全画面のまま——テロップには表を置けないため。5本の映像は作品内の1箇所
（`--excerpt-start-s`）から連続で切り出す（5箇所バラバラだと確認の手間が5倍になる）。テロップは
既定で該当ストレッチの尺いっぱい表示するが、締めの1本だけ `caption_hold_s=8.0` で早めに消え、
残り12秒は映像だけが流れる（`CaptionedExcerpt.hold_s` が既に持っていた仕組み）。合計は従来どおり
ちょうど3分。

`assemble_demo` の `excerpt: Excerpt` 引数は `excerpt_start_s: float`（5本の起点）に変更、CLI の
`--excerpt-duration-s` は削除（各ストレッチが固定尺を持つため不要）。

**実機 ffmpeg で確認**（合成テストパターン映像、実素材は不使用）: テロップ表示中はフレームに
帯とテキストが読める形で載り、`caption_hold_s` 経過後のフレームでは帯・テキストとも完全に消えて
素の映像のみになることを実際にレンダーして目視確認した（`eof_action=pass` の狙いどおり）。

**テスト**: `tests/test_demo_assembly.py` に11件追加・数件更新（`CaptionedExcerpt` の妥当性検証、
`caption_html` のエスケープ、5本が連続で切り出されること、新しいコマンドのフェード秒数と
`eof_action=pass`、フルアセンブリテストのセグメント種別ごとの呼び出し回数）。**全1450件成功**
（`test_judged_film_end_to_end.py` は既存の慣例どおり ffmpeg 依存で除外——今回は実機に ffmpeg が
あるため個別に実 ffmpeg 検証は別途実施した）。**Ruff check/format 成功**。支出 ¥0。

**次に推奨**: 実際のパッケージで一度 `python -m app.submission.demo_assembly` を走らせて
5ストレッチの実写を目視確認（顔・ナンバー含め）。E-1（章内の並び、`app.chapter_order` あり）を
`footage_for` へ配線、または E-2 の重複解消（§108 参照）。

## 110. クラウド層: S3 の残り「配分の余りを他章に回す」を決める関数（`app/story_pacing.py`）

自律ループ第3層（クラウド routine）による4回目の実行。§96「見えたこと」・roadmap 7章に残っていた
S3 の続き（1日目の footage が目標 240 秒に対し 218〜220 秒にしか届かない——停止の章や見た目の
規則（隣接窓が同じ絵）で目標に届かない章が出るのに、余った秒数がどこにも行かず捨てられている）
のうち、**配分を決める計算そのものだけ**を実装した（`select_by_chapter` への配線・実際の再レンダー
は見た目に効く判断として次に残す）。

`app/story_pacing.py` に追加（新しい関心ではなく、章ごとの配分を既に持つこのモジュールに足す）:

- `ChapterAllocation(chapter_id, weight, capacity_s)`: 章の取り分の重み（`select_by_chapter` が
  今使っている「候補数の割合」）と、その章が実際に使い切れる上限秒数（停止なら1本分、見た目の
  重複除去で候補が薄い章ならその分だけ、という**理由を問わない**上限）。
- `reallocate_footage_targets(allocations, footage_target_s, *, floor_s=SHORT_HOLD_S)`: まず
  重みに比例した目標を配り（`select_by_chapter` と同じ比例配分＋下限）、`capacity_s` を超える分
  だけを、まだ余地のある章へ重み比例で（全章の重みが0なら均等に）手渡す。手渡した先がそれ自身の
  上限を超えることがあるので、超えなくなるまで繰り返す（章の数だけで必ず止まる——上限を超えた
  章は次のラウンドから除かれる一方）。全章が上限に達してもなお余りがあれば、それは今までどおり
  使われない（要求しすぎない）。

**テスト** `tests/test_story_pacing.py` に11件追加、合成 fixture のみ（実素材なし）: 上限内で
比例配分のみで済む場合、1章が上限で余りをもう1章へ全量手渡す場合、2章へ重み比例で分ける場合、
手渡された先がさらに自分の上限を超えて2段階目の連鎖が起きる場合、全章が上限に達して目標を
使い切れない場合（要求超過が起きないこと）、全章の重みが0のときの均等配分（上限到達時の均等な
連鎖も含む）、重みが極端に薄い章でも下限は上限の範囲内で確保されること、章が1つだけの場合、
どの組み合わせでも各章の最終値が自分の上限を超えないこと、目標秒数・下限秒数が0以下・章が空・
`chapter_id` の重複／空文字・重み／上限が負の拒否。

環境: 前回までと同じく `pip install -e '.[dev]'` で `google`/`vertexai`/`agentplatform` の import は
解消。`ffmpeg` が無い環境のため `tests/test_judged_film_end_to_end.py`（6件）のみ `--ignore` で
外した（レンダー end-to-end で、コード側の問題ではない。前回までと同一理由）。**全 1456 件成功
（新規11件を含む）、Ruff check/format 成功**。支出 ¥0（実素材・Gemini・GCS には触れていない）。

**次に推奨**: `reallocate_footage_targets` を `select_by_chapter` の章ごとの `target` 計算へ実際に
配線し（各章の `capacity_s` は、その章の候補が現行規則で使い切れる秒数——停止なら
`SHORT_HOLD_S`、それ以外は候補本数×`LONG_HOLD_S` などの上限——から出す）、両 ride を再レンダーして
footage が目標に近づくかオーナー再視聴（見た目が変わる単位、ローカル層向け）。または §108 の
重複解消（`app.story_clip_half` と `app.story_hold` のどちらかを選び削る）。あるいは研究に残る
他の計算だけの単位（E-6 色を揃える・E-7 コピーからのタイムラプスのうち純計算部分）。
## 111. E-2 の配線: 動きで尺を決め、動く方の 6 秒を切る（`a8d39ec` ＋ 目標の数え方、手動 session）

クラウド層が用意した関数（`app/story_hold.py`）を実際の cut に配線し、両 ride を再レンダーした。

**やったこと**:
- **尺**（`story_pacing.footage_for(..., looks=, openers=)`）: 採用窓すべての look があれば、rank の段
  （上位 1/5 → 長、順位あり → 中、無し → 短）は**範囲**になり（8〜10／5〜7／3〜4 秒）、その窓の動き
  （`WindowLook.motion`、採用窓同士の最小〜最大に対する位置）が範囲内の点を決める
  （`hold_all_from_motion`、3 本同じ尺の中央を崩す規則込み）。look が無ければ従来の固定尺。
- **どの 6 秒か**: look が 1 秒ごとの動き系列（`WindowLook.motion_series`、新設。`measure_look` の
  YDIF をそのまま保持）を持てば `choose_half_by_motion` で動きの多い半分を選び、`trim_bounds_for_half`
  の開始秒を **`source_offset_s`** として `TimelineFootage` → `StoryBeat` → `StoryPlanBeat`（plan JSON に
  0 より大きいときだけ書く）→ `build_story_film_segments`（`-ss` に加算）へ通した。ride 時刻も offset 分
  ずれる（実際に映る区間の時刻）。
- **章の最初の窓は 6 秒以上**（`OPENER_MIN_HOLD_S`、`chapter_openers`）: E-4 の題 5 秒＋空き 1 秒を担うため。
- **目標の数え方**: `select_by_chapter` は `paced()` で目標尺を数えるが固定尺のままだと採用窓が少なすぎた
  （2日目 289 → 218 秒に落ちた）。look があるときは各段の範囲の中央（3.5／6／9 秒）で数える
  （`paced(motion_aware=)`）→ 同じ目標でより多くの窓を採る。
- **系列の計測**: `looks_for(..., need_series=True)` は系列の無い既存の look を測り直す。`plan_journey_film`
  は採用窓だけに系列を要求する（714 窓を測り直さない）。
- **重複の解消**: `app/story_clip_half.py`（クラウド層のもう一方）とそのテストを削除。`story_hold` 側を採用。

**E-1（章内の並び）の判断**: `StoryTimeline` は「beat は ride 時刻順・重ならない」を契約にしており
（`story_timeline.py`）、章内でジグザグに並べ替えると契約を壊す。ツーリングの一日の物語として時刻順は
守る価値があると判断し、**並べ替えはしない**。`app/chapter_order.py` は未配線のまま残す（研究 §2.2 の
「動きの多寡を交互に」は尺の変化（本節）と look-alike 規則で代替）。オーナーの再視聴で単調さが残れば再考。

**実測（両 ride 再レンダー、load 平常）**:

| package | 採用窓 | 尺 min/平均/max | 尺の種類 | 後半始まり | 作品尺 | レンダー |
|---|---|---|---|---|---|---|
| 2日目 | 37 → **59** | 3.0 / 4.84 / 9.5 s | 52 | 30 | 288.6 → **304.7 s**（430 MB） | 223 s |
| 1日目 | 31 → 28 | 3.1 / 5.48 / 10.0 s | 26 | 15 | 232.4 → **166.0 s**（230 MB） | 139 s |

2日目は同じ尺でほぼ 1.6 倍の窓数（研究の「平均 4〜6 秒、同じ尺を 3 本続けない」に到達）。1日目は判定済み
175 窓の中で閾値と間隔を通る窓が尽きるため、尺が短くなった分だけ作品も短くなった（166 秒）。
**追補（roadmap へ）**: 素材が少ない日は、目標に届かないときに採用窓の尺を範囲の上側へ寄せる
（配分の余りを尺に回す）。S3「配分の余りを他章に回す」と同じ場所。

**テスト**: 12 件追加（pacing 6、look 2、package 1、titles 1、film 1、目標の数え方 1）、12 件削除
（story_clip_half）。**全 1466 件成功、Ruff 成功**。支出 ¥0。

**オーナー再視聴**: 見た目（リズム・切り出し位置）が変わる単位。PushNotification 1 通。
## 112. E-2 追補: 素材が少ない日は尺を範囲の上側へ（`d418c57`、手動 session）

§111 で 1日目が 166 秒に縮んだ対策。`footage_for(..., footage_target_s=)`: 動きで置いた尺の合計が目標
（`DEFAULT_FOOTAGE_TARGET_S` 240 秒）に届かないとき、不足分を各窓の**自分の範囲の上端までの余地**に
比例して配る（`_raised_toward_target`）。範囲は超えない、動きによる順序は保つ、目標に届いていれば何も
しない。`plan_journey_film` が目標を渡す。

**実測（1日目再レンダー、122 秒）**: 28 窓、尺 4.0〜10.0 秒（平均 6.5）、footage 182 秒、作品 **194.3 秒**
（166.0 → 194.3、272 MB）。全窓が範囲の上端に達しても 240 秒には届かない——判定済み 175 窓の中で
閾値と間隔を通る窓が 28 本しかないため。これ以上伸ばすなら（a）1日目の判定窓を増やす（stride 30 → 15 秒、
≈¥26）か、（b）範囲自体を素材の少なさで広げるか、のどちらかで、いずれも設計判断として roadmap に残す。
2日目は目標を超えているので不変（304.7 秒）。

**テスト**: 3 件追加（上端まで上げる・目標達成時は不変・不足分の比例配分）。**全 1469 件成功、Ruff 成功**。
支出 ¥0。
## 113. UI の一手: ダブルクリックでコンソール、作品の場所を画面に（`f695e41`、手動 session）

オーナーの質問「どうやってそのファイルを見るの？ コンソールとはなんのこと？」への直接の答え。
これまで作品を見るには「サーバーを起動して URL を開く」手順が要り、その説明自体が伝わらなかった。

- **`scripts/open-console.command`**（実行権付き）: Finder でダブルクリック → `.venv` の有無を確認 →
  8765 番で応答が無ければ `python -m app.web.server` を nohup で起動（ログ `.autonomy/console.log`）→
  応答を待って `open http://127.0.0.1:8765/private-journey`。既に動いていればブラウザを開くだけ。
- **作品の場所**: story payload に `package`（フォルダ名）と `film.file_name` を足し、ページの
  プレイヤー下に `private-media/work/<package>/<ファイル名>` と、無音版なら「無音版（音楽は別工程）」を
  出す（LABEL `film_file` / `film_silent`、日英）。**絶対パスは payload に入れない**——既存テスト
  `test_the_film_is_reported_without_a_path` の意図（`str(package) not in json.dumps(payload)`）を維持。
- runbook §0.5 に「いちばん簡単な起動」を追記。

**テスト**: `tests/test_console_launcher.py` 3 件（存在と実行権、`bash -n`、モジュール・URL・127.0.0.1 の参照）、
story view の film テストを更新。**全 1472 件成功、Ruff 成功**。支出 ¥0。

**気付き**: オーナーには「コンソール」「package」「レンダー」という語が通じていない。画面の語彙を
「作品」「取り込み」「判定」「生成」に寄せる小単位（UI 語彙の見直し）を roadmap の UI 項に足す。
## 114. UI 語彙の見直し: 画面の日本語からコードの語を消す（`583996d`、手動 session）

`/private-journey` の日本語ラベルは `package`・`beat`・`preflight`・`バケット` といったコードの語を
そのまま出していて、オーナーには通じていなかった（§113 の質問）。置き換え:

| 前 | 後 |
|---|---|
| package（切替のラベル） | 見ている日 |
| package名（英数字・-・_） | この日の名前（英数字・-・_） |
| この数字でpackageを作る | この数字でこの日を取り込む |
| 提案された数字でだけpackageを作れます | 提案された数字でだけ、その日を取り込めます |
| この端末では私用packageが設定されていません | この端末にはまだ取り込んだ日がありません。下の「別の日のクリップを取り込む」から始めてください |
| このpackageから作品を生成してください | この日の作品を生成してください |
| beat | 場面 |
| アップロード先バケット | 送り先（クラウドの保管場所の名前） |
| …（ローカル・無料）: preflight | …（この端末内・無料）。 |

英語ラベルは開発者向けとして据え置き。旧ページ（私用ハイライト確認・director preview）の
「確認パッケージ」は対象外（オーナーが使う画面ではない）。動いていたコンソール（18 時間前の旧コードで
稼働していた）を最新コードで再起動し、新しい語が出ることを確認した。

**テスト**: 既存のページ構文テスト（node）と全 1472 件成功、Ruff 成功。支出 ¥0。
## 115. オーナー二度目の視聴 → E-9 左上の現在位置マップ（`a26343a`）、E-10 地図背景の下地（`194f49c`）

**オーナー（2026-09-05 夜、再視聴後）**: 「とても良くなりました。章と章の間に経路図が出ますが、クリップの例えば
左上にも小さく経路図を載せ、現在位置がわかるとより良いです。また、せっかくGoogleのサービスを使っているので、
黒バックではなく地図を背景にしてはどうでしょうか？」→ `user-feedback-2026-09-04-ja.md` に追記、roadmap に E-9／E-10。

**E-9 やったこと**:
- `chapter_card.build_position_map_html(svg)`: ページ全体が小窓（暗い正方形＋細い枠、経路は太線、
  現在地は白い点 `POSITION_MARK_RADIUS=16`）。`route_map_svg(..., mark_radius=)` を追加。
- `story_film.write_position_maps(plan, package, route_points=, ride_times=)`: footage beat ごとに 1 枚
  `pos-NNN.html` → PNG（Quick Look 1 回）。点の位置は「窓の ride 開始時刻 ＋ `source_offset_s` ＋ 尺/2」の
  track 点。走行済み区間は出発〜その点。ride 時刻が不明な beat は地図なし（誤った地図を出さない）。
- `StoryFilmSegment.corner_map`（footage のみ）、`build_story_film_segments(..., position_maps=)`、
  `_corner_map_chains`: `-loop 1 -t 尺` の入力を高さ 18% の正方形に `scale` し左上（余白 3%）に全尺
  `overlay`。題の帯（E-4）は小窓の**上**に重なる（`_lower_third_chains(base=)`）。
- `private_journey_film._ride_times(package)`: 判定記録の窓開始 ＋ 録画開始 ＋ 時計オフセット。
- 前回描画の掃除は `card-*` に加えて `pos-*` も。

**実測（両 ride 再レンダー）**: 2日目 59 枚・304.7 秒・430 MB（213 秒）／1日目 28 枚・194.3 秒・272 MB
（150 秒）。フレーム確認（18.5 s、150 s）: 左上に小窓、題の帯と両立、点は読める。

**E-10 下地**（`app/map_background.py`、未配線）: `frame_for(points)`（外接矩形が 84% に収まる最大ズーム、
正方形 640×640 scale 2）、`MapFrame.project(lat, lon)`（Web Mercator → 画像ピクセル）、`static_map_url`
（中心・ズーム・寸法・style・key。**経路は送らない**）、`map_background(package, points, style=, fetch=)`
（`package/map-background/map-<hash>.png` にキャッシュ、PNG 以外は拒否）。配色 `DARK_STYLE`（POI・交通・
道路名なし、町名あり）と `UNLABELLED_STYLE`。実 API を 1 回叩いたところ **403「This API is not activated」**
——Static Maps API の有効化はオーナー操作として依頼（PushNotification）。有効化後の残り: `route_map_svg` の
投影を `MapFrame` に切り替え、背景画像を data URI で埋め込む版（カード・見出し・締め・小窓）を作り、
両 ride をレンダーして「地名あり／なし」をオーナーが選ぶ。

**テスト**: 15 件追加（corner map 7、map_background 8）。**全 1487 件成功、Ruff 成功**。支出 ¥0。
## 116. E-10 地図を背景に: 描画側は完成、取得はオーナーのキー設定待ち（`b33d6ea`）

- `map_background.MapBackground(frame, data_uri)`（PNG を base64 の data URI で持つ。ページは外部参照なしのまま）、
  `style_named` / `chosen_style_name`（`RIDE_MAP_STYLE`: `labels`（既定、町名あり）／`plain`（文字なし）／`none`）、
  `background_or_none(package, points, style_name=, fetch=)`（鍵なし・サービス拒否・`none` は None → 従来の黒地）。
- `chapter_card.route_map_svg(..., background=)`: 背景があれば `_svg_over_map`——viewBox は地図画像のピクセル
  （1280²）、経路点は `MapFrame.project` で置き、`<image href="data:...">` を下に敷き、線は
  `vector-effect="non-scaling-stroke"` で表示幅を保つ。点の半径は箱の大きさに比例。
- `story_film.write_chapter_cards(..., background=)`／`write_position_maps(..., background=)`／`_card_map(...)`。
- `private_journey_film.run_private_journey_film(..., map_style=, map_fetch=)`、結果に `map_background`
  （style 名または `none`）、CLI `--map-style labels|plain|none`。
- **取得の状態**: オーナーが Maps Static API を有効化 → 403 の文言が「API not activated」から
  「**This API key is not authorized to use this service**」に変わった＝**キー側の API 制限**に Maps Static API が
  無い。認証情報でキーの制限に Maps Static API を追加してもらうよう依頼（チャットで手順を提示）。
- 反映後の手順: `--map-style labels` と `--map-style plain` で 2日目を別名（`--output-file-name`）に 2 本出し、
  フレームを見て既定を決め、両 ride を再レンダー、オーナー再視聴。

**テスト**: 5 件追加（背景の data URI、地図の投影で置かれた経路、style 名と none、拒否時の黒地、カードと小窓が
`<image>` を持つ）。**全 1492 件成功、Ruff 成功**。支出 ¥0（403 は無課金）。
## 117. E-10 地図を背景に: 両 ride をレンダー、オーナーの配色選択待ち（`d077198` `8a1b725` `4c7475c`）

**取得**: オーナーが Maps Static API を有効化し、キー `…_260817` の API 制限に Maps Static API を追加、
アプリケーションの制限を「なし」に。反映は約 5 分揺れた（200 と 403 が交互）ので、`background_or_none` の
フォールバックが効いていることも実地で確認できた。両 ride × 2 配色 = **4 リクエスト**、以後は
`<package>/map-background/` のキャッシュ。zoom 7（2日目 413 km）。支出: Maps は無料枠内（¥0 と記録）。

**最初のレンダーで見えた 2 点と修正**:
1. 左上小窓の線が 1 px——小窓ページは 1920 px で描き 1/10 に縮むので、`vector-effect="non-scaling-stroke"`
   の線幅（ページ px）が消える。svg に `on-map` クラスを付け、小窓の style で地図上の線を太く
   （最初 70/100 は塊になり、26/38 に落とした）。カードは 6/9 px。
2. 小窓の地名は読めずノイズ → 小窓は常に文字なしの地図（`corner_background`、style `plain`）。カードは選んだ配色。

**結果**（両 ride、`--map-style labels` を既定ファイルに、2日目のみ `plain` を別名に）:

| ファイル | 配色 | 尺 | 容量 |
|---|---|---|---|
| 2日目 `ride-storyteller-story-film.mp4` | 町名あり | 304.7 s | 430 MB |
| 2日目 `ride-storyteller-story-film-plain.mp4` | 文字なし | 304.7 s | 430 MB |
| 1日目 `ride-storyteller-story-film.mp4` | 町名あり | 194.3 s | 272 MB |

フレーム確認: 見出しカードは暗い地図の上に全行程が青く伸びる（町名は日英併記、道路名・POI なし）。
小窓は地図＋白い走行済み線＋青い点で読める。題の帯の右端の小地図は暗くて地図がほぼ見えない（帯の下で
半透明バンドがかかるため）——帯の地図は黒地のままでよいか、後で判断。

**残り**: オーナーが「町名あり／文字なし」を選ぶ → 既定に固定（`RIDE_MAP_STYLE` または既定値）。
陸と海のコントラスト（`DARK_STYLE` の geometry 色）、コンソールでの配色切替。
テスト全 1492 件成功、Ruff 成功。
## 118. 小窓の追補: 線を細く、現在地は小さな単色の丸（`2d07253`）

**オーナー（2026-09-05 22:25、小窓のスクリーンショット付き）**: 「水色の軌跡線が太すぎます。現在地マーク円も大きい
です。もう少しすっきりとして下さい。現在地マーク円は、縁取りにするより、単一カラーの方が好き。」

- 地図上の小窓の線: 26/38 → **14/20**（ページ px。作品では約 1.4/2.0 px）。黒地版も 9/12 → 6/8。
- 現在地: `POSITION_MARK_RADIUS` 16 → **8**（作品で半径約 4 px）、白の単色（`stroke:none`）。
- 作品サイズ（194 px）のプレビューを先に見てから両 ride を再レンダー（2日目 labels 220 s／plain 273 s、
  1日目 170 s。尺・容量は不変）。フレーム確認: 線は細く、点は小さく読める。

テスト全 1492 件成功。支出 ¥0（地図はキャッシュ）。**オーナーの配色選択（町名あり／文字なし）は未回答**。
## 119. オーナーの決定: 小窓は少し大きく、地図は町名あり。今日の区切り（`2d0a860`）

**オーナー（2026-09-05 23:10）**: 「小窓を、もう少し大きくしたい。章の説明画面の地図は、町名ありが良いです。
ここまでできたら、一旦区切りをつけましょう。」

- `CORNER_MAP_HEIGHT_SHARE` 0.18 → **0.23**（高さ 194 → 248 px）。拡大に合わせて地図上の線 14/20 → 11/16、
  現在地の半径 8 → 6 にして、作品上の太さ（約 1.4/2.1 px、半径約 4 px）は §118 で承認された大きさを保つ。
- **既定の配色は `labels`（町名あり）に固定**（`DEFAULT_MAP_STYLE`、決定の経緯をコメントに）。小窓は常に文字なし。
- 2日目の比較用 `ride-storyteller-story-film-plain.mp4` は削除（決定済みのため）。
- 両 ride を既定で再レンダー（下の表）。

| package | 作品 | 配色 |
|---|---|---|
| 2日目 | 304.7 s・430 MB | 町名あり、小窓 23% |
| 1日目 | 194.3 s・272 MB | 同 |

**今日（2026-09-05）の到達点**: E-3・E-8・E-4・Q1・Q5（watchdog 層）・E-2 配線＋追補・E-1 判断・UI 入口と語彙・
E-9・E-10。オーナー評価「とても良くなりました」。支出累計 ≈¥151／¥500（Gemini・GCS）、Maps は無料枠内。
テスト全 1492 件成功、Ruff 成功。

**区切りの後（自律層向け）**: E-10 追補（`DARK_STYLE` の陸と海のコントラスト、コンソールの配色切替）、
題の帯の右端の小地図（地図の上では暗くて見えない——黒地に戻すか、帯の上に小窓と同じ地図を置くか）、
E-5 音、E-6 色、7.2 単位経済の実測。見た目が変わる単位はオーナー再視聴を要する。

## 120. オーナーからの条件: 予算 ¥1000、GPX は day1〜day12、タイムスタンプの注意（2026-09-05 23:45）

- **予算**: 「合計 1000 円まで使用可」。累計 ≈¥151（Gemini・GCS）。上限は合計であり日ごとではない。
- **GPX**: `private-media/input/videos/day1`〜`day12` に 1 本ずつ（一覧で確認。day3 以降のフォルダにクリップは無く、
  クリップは外付け `/Volumes/Seagte 2/…/NZ縦断/` に 375 本・1.1 TB が 1 フォルダで）。
- **注意**: 「ファイルのタイムスタンプが NZ 時刻になっているものがある」——録画によって UTC と NZ 時刻が混在し得る。
  現在の時計オフセットは package（日）につき 1 つ。提案の曖昧さ（`runners_up`）が出たら、**録画ごとのオフセット**
  （UTC 系と NZ 系の 2 群に分ける）を設計する単位が必要。
- day3 以降の**着手はオーナーの合図待ち**（§119）。着手時の費用計画: 全窓判定は 1 日 ≈¥100 なので残り ≈¥849 では
  10 日分に足りない → stride 60 秒（≈¥50/日）または順位だけの経路（≈¥6/日）を提案する。

## 121. 全行程の処理を開始: day3〜day12（`57d4b6f`、2026-09-06 00:00）

**オーナー決定**: 「この後、実施して下さい」「B とします」「（タイムスタンプの）混在はしていません」「コピーせずに進めて下さい」。
予算は合計 ¥1000（累計 ≈¥151 から）。

**仕組み**:
- `analysis_run.write_analysis_settings(package, stride_s=)` / `analysis_stride_s(package)`: package に窓の間隔を固定
  （`analysis-settings.json`）。`plan_analysis_run(stride_s=None)` はそれを読むので plan・preflight・judge・rank・
  コンソールが同じ窓を見る。CLI `plan --stride-s 60`。
- `scripts/trip/process-day.sh N`: GPX は `private-media/input/videos/dayN`、footage は `RIDE_TRIP_VIDEO_ROOT`
  （外付け。読取りのみ）。時計オフセット提案 → package（`--skip-review-clips`）→ plan（stride 60）→ preflight →
  judge（`--i-approve-spending`、prefix `day-N-v1`）→ rank → film。各段は冪等（既にあれば飛ばす）。
  ログ `.autonomy/trip/day-N.log`、各段の JSON も同じ場所。`process-days.sh 3 12` で連続実行、止まった日で停止。
- **曖昧なオフセットの規則**: 長い ride では複数のシフトが同じ録画集合を ride 内に置くため同点になる。同点の中に
  NZ の時差そのもの（13 h、無ければ 12 h）の whole-hour シフトがあればそれを選んでログに残す。無ければ停止して相談。

**day3 の実測**: オフセット提案は曖昧（11.5／12／12.5／13 h が同点、38 録画が ride 内、375 本の走査 35 秒）→
規則で 13 h を採用。plan: **370 窓 ≈¥54.67**（stride 60）。preflight 実行中。
day1 の確定値は −13 h、day3 は +13 h と符号が逆——day3 の GPX が NZ 現地時刻を Z 表記で持っている可能性。
作品には影響しない（映像と GPS の相対関係だけを使う）が、地図の日照などを将来使うなら要確認。

**見込み**: 1 日 ≈35〜45 分、10 日で 6〜7 時間。費用 ≈¥55/日 × 10 ＋ 順位 ≈¥2.5/日 → 累計 ≈¥725 以内。

**day3 の停止（2026-09-06 00:20）**: preflight は 370 窓を 18 分で完了、judge の開始時に `CloudSignInExpired`
（ADC の期限切れ）。**購入 0**。オーナーに `gcloud auth application-default login` を依頼（PushNotification）。
サインインが戻ったら `scripts/trip/process-day.sh 3` を再実行するだけで judge から続く（各段は冪等）。
その後 `process-days.sh 4 12`。

**day3 完了・day4 で停止（2026-09-06 01:28）**: day3 は judge 370 窓（¥54.67、累計 ≈¥206）→ rank → film 258.5 秒・
360 MB（採用 45 窓、題付き 6、カード 2、地図あり）。フレーム確認: 走行映像と、停止章の屋内展示 1 窓。
**day4**: オフセット提案 8.0 h（26 録画）、同点 8.5、次点 9.5／10.0——NZ の時差（12／13 h）が無く規則で選べず停止。
8 h 前後は時差では説明できない＝カメラの時計が別の値（電池交換でのリセット等）と見る。
→ GoPro の `gpmd` ストリーム（GPMF: GPSU=UTC 時刻、GPS5=位置）を読めば録画ごとの真の UTC が取れる。
ffprobe で `gpmd` の存在を確認済み。次: GPMF パーサで録画ごとのオフセットを直接求め、曖昧な日を解く。

**訂正（2026-09-06 01:35）: day3 のオフセットは誤り、¥54.67 は無駄になった**。GoPro の metadata track（GPMF）から
GPS 時刻を読むと、day3・day4 のカメラは **−13.00 h**（NZ 現地時刻、録画間の差 3 秒以内）。day3 で採用した
+13 h は符号が逆で、全日分が 1 フォルダにあるため「+13 h にずらすと *別の日*（day2）の録画 38 本が走行の中に入る」
偶然を containment 法が「最多」と評価していた。判定した 370 窓は day2 の録画（day-2-v1 で既に判定済みの窓と同内容）。
**教訓**: 複数日を 1 フォルダで扱うとき containment 法は使えない。GPS 時刻（`app/gopro_gps.py`）を第一手段にし、
時差規則は削除、containment は GPS の無いカメラ向けの最後の手段で、曖昧なら止める。day3 は package を捨てて作り直す。
支出累計 ≈¥206（うち ¥54.67 は失敗分として計上）。

**day3 完了（GPS 時計、2026-09-06 02:24）**: オフセット −46,808 s（GPS 14 録画、差 2.9 s）。plan 168 窓 ≈¥24.82
（stride 60）→ preflight 8 分 → judge 21 分（168 購入）→ rank → film **226.4 s・289 MB**（採用 33 窓、題付き 5、
章: 出発／休む／水辺／休む／海沿い／到着）。累計 ≈¥231（失敗分 ¥54.67 込み）。day4 へ自動継続。
`app.gopro_gps.recordings_in` はカタログ経由に修正（チャプター分割の開始時刻補正。生の creation_time では
後続チャプターが 35 分ずれて「時計が不一致」と誤判定した）`8a269c8`。

**day4 完了（2026-09-06 03:02）**: オフセット −46,813 s（GPS 21 録画、差 2.0 s）。189 窓 ≈¥27.92 → film **269.3 s・367 MB**
（採用 51 窓、題付き 6、章: 出発／町／休む／水辺／休む／到着、見出し 365 km）。累計 ≈¥259。day5 へ。

**day5 完了（2026-09-06 04:01）**: 326 窓 ≈¥48.17 → film **294.4 s・399 MB**（採用 54 窓、題付き 5）。累計 ≈¥307。day6 へ。

## 122. クラウド層: E-6 露出を揃える計算（`42b33ad`、`dev/cloud/20260905-1036` を main へ統合）

自律ループ第3層（クラウド routine）による5回目の実行。研究 §6・roadmap E-6「窓ごとの露出・
コントラストの自動正規化」のうち、**露出（明るさ）だけ**を、`app.analysis_look.WindowLook.luma`
（既に測定済みの平均輝度）から計算する部分だけ実装した（コントラスト・WBは対応する測定値が
無いため見送り、`eq` フィルタへの実際の配線・再レンダーは見た目が変わる判断として次に残す）。

`app/story_color.py`:

- `luma_target(lumas)`: 窓群が揃うべき明るさを**中央値**で返す（平均だと1本のひどい露出不良が
  目標自体を引きずるため）。
- `brightness_correction(luma, target, *, max_correction=0.12)`: FFmpeg `eq=brightness=` の値
  （-1〜1）で、`luma`（0〜255）を`target`へ寄せる補正量を返す。差分を255で正規化し、
  `max_correction`（既定 0.12）でクランプする——ギャップを一度に全部埋めると露出不良の理由
  （トンネル・逆光）ごと均してしまう平坦化になるため。
- `brightness_corrections(lumas, *, target=None, max_correction=...)`: 窓群全体に対する補正の列
  （順序保持）。`target` 省略時は `luma_target` 自身を使う。

path・アセットID・窓の中身は一切読まない。数値（輝度の平均）だけを扱う。

**テスト** `tests/test_story_color.py`: 19件、合成 fixture のみ（実素材なし）。単独窓での中央値、
奇数・偶数個での中央値（平均との違い）、目標地点で補正0、暗い窓を明るく・明るい窓を暗く、
非常に暗い/明るい窓でのクランプ、カスタム上限、非正の上限・負値・非有限値の拒否、既定target
（自群の中央値）、全窓同一輝度で補正すべて0、入力順の保持、明示targetでの上書き、空リストの拒否。

環境: 前回までと同じく `pip install -e '.[dev]'` で `google`/`vertexai`/`agentplatform` の import は
解消。`ffmpeg` が無い環境のため `tests/test_judged_film_end_to_end.py`（6件）のみ `--ignore` で
外した（レンダー end-to-end で、コード側の問題ではない。前回までと同一理由）。**全 1485 件成功
（新規19件を含む）、Ruff check/format 成功**。支出 ¥0（実素材・Gemini・GCS には触れていない）。

**次に推奨**: E-5「音のつなぎ」のうち計算だけの部分（窓間の RMS 値から風切り減衰の要否・
`-6 dB` の適用を決める関数、クロスフェード秒数の定数化）、合成 fixture で完結。または UI 語彙の
見直し（§113 の気付き、`app/web/` の表示文言）。`brightness_corrections` を実際の render へ配線
するのはローカル層向け（見た目が変わる判断）。

## 123. クラウド層: `app.contracts.models` の境界・失敗経路のテストを追補（`be7c2ca`、`dev/cloud/20260905-1836` を main へ統合）

day3〜day12 の全行程処理（§121）はローカル層の実素材作業のため触れず、実素材の実測を要らない単位を選んだ。

`app.contracts.models`（`RoutePoint`・`RouteSummary`・`StoryChapter`・`StoryPlan`・`Location`・`VideoQuery`・
`GpsEvent`・`MediaAsset`・`VideoAnalysis`・`StoryDecision`）は Day 1 の全パイプラインが通る検証済みデータ
契約だが、既存の `tests/test_contracts.py` は `GpsEvent` の2経路しか見ていなかった。各 dataclass の
`__post_init__` の拒否経路（timezone のない timestamp、順序が逆の時刻、範囲外のスコア、必須文字列の欠落）と
`to_dict()` のシリアライズ（Zulu 表記の timestamp、`DecisionStatus` の文字列値）が未検証だった。

`tests/test_contracts_models.py` を新設: 69 件。各 dataclass の拒否経路に加え、自身の境界値
（スコア 0.0/1.0 ちょうど、緯度 90 ちょうど、`StoryPlan.target_duration_s` の 300/600 秒ちょうど）が
受理されることも確認。ネットワーク・I/O なし、純粋な dataclass 検証のみ。

**環境**: `pip install -e '.[dev]'` は成功（google/vertexai/agentplatform 一式が入り、全 1502 件が収集できた）。
`ffmpeg` と `qlmanage` は未導入のため `tests/test_judged_film_end_to_end.py`（6 件、実際に ffmpeg を呼ぶ結合テスト）
を `--ignore` で外した。node は導入済みで `tests/test_web_page_scripts_parse.py` は実行できた。

**テスト**: 新設 69 件。**全 1565 件成功（1496 既存 + 69 新規、ffmpeg 依存の 6 件を除く）、Ruff check・format 成功**。
支出 ¥0（実素材・Gemini・GCS には一切触れていない）。

**次に推奨**: 同じ手法で `app/video/local_catalog.py`・`app/scout.py` など未テストの純粋ロジックの境界を
補うか、`chapter_order.py`（E-1、時刻順を守る判断は済みだが配線されていない）のような配線待ちの純粋関数の
テスト強化。day3〜day12 の処理はローカル層の続きを待つ。

## 124. クラウド層の取り込み: 6 branch を確認、2 統合・1 既済・3 重複で見送り

day3〜day12 の処理（day6 進行中）を横目に、`dev` の `cloud/*` を手順どおり確認した。

- `cloud/20260905-0036`: 中身は既に main の祖先（空 diff）。統合済みとして branch のみ削除。
- `cloud/20260905-1036`（E-6 露出計算、`app/story_color.py`）: pytest・Ruff 緑 → 統合（§122）。
- `cloud/20260905-1836`（contracts 境界テスト）: pytest・Ruff 緑 → 統合（本節の直前、§123）。
- `cloud/20260905-1235`（E-4、`app/story_lower_third.py`）: **見送り**。E-4 はローカル層が同日中に
  `app/lower_third_text.py` を実装済み・`app/chapter_card.py` に配線済み（§119 の到達点）。同じ
  題材（題12字・本文21字の予算）への独立な二つ目の実装で、こちらは未配線・未使用のまま残る。
  マージすれば緑にはなるが死んだ重複コードを増やすだけなので、branch を削除し統合しない。
- `cloud/20260905-1435`（E-6、`app/story_color.py` 別実装）・`cloud/20260905-1635`（E-6、
  `app/exposure_match.py`）: 同じ E-6 の題材を、`cloud/20260905-1036` と知らずに独立に二度実装した
  もの（クラウド層は互いの branch を見ずに進むため）。前者はファイル名まで衝突（`app/story_color.py`）
  し、後者は別名だが同じ「隣接窓の輝度を揃える」計算を別のアルゴリズム（中央値ターゲット vs
  前後2パスのクランプ平均）で行う。§122 で先に統合した実装を正とし、両方 branch を削除。

**教訓**: クラウド層は同時に複数走ると同じ研究項目（特に E-6）に重複着手しやすい。次に選ぶ単位の
候補から「今 main にある/統合待ちの branch で扱っている題材」を外すような一覧を渡せると重複が減る
——ここでは対症療法（統合時に重複を見つけて捨てる）で足りたが、恒久対応は別単位。

テスト・Ruff は §122・§123 の統合時点でそれぞれ確認済み（緑）。本節自体はコード変更なし。支出 ¥0。

**day6 完了（2026-09-06 05:17）**: 376 窓 ≈¥55.55 → rank は「Vertex AI Gemini returned an incomplete ranking」で失敗
（スクリプトは順位なしで続行）→ film **338.6 s・471 MB**（採用 69 窓、題付き 6）。累計 ≈¥363。day7 へ。
**課題**: `rank_windows` は 1 グループの応答が不完全だと全体を捨てる。再試行（同じグループを 1 回やり直す）と、
不完全なグループだけ落として残りを書く寛容さが要る（roadmap へ）。

**バッチ後にやること**: day6 の rank を買い直し（`analysis_cli rank … --overwrite` 不要、未作成）→ `private_journey_film` で作品更新。
順位づけの寛容さは `4798f7b`（1 回聞き直し、失敗グループだけ順位なし）。

**day7 完了（2026-09-06 06:28）**: 297 窓 ≈¥43.88 → rank 成功 → film **259.7 s・376 MB**
（採用 46 窓、題付き 6）。累計 ≈¥407。day8 へ。

**day8 完了（2026-09-06 07:12）**: 149 窓 ≈¥22.01 → rank 成功 → film **246.3 s・332 MB**（採用 36 窓、題付き 4）。累計 ≈¥429。day9 へ。

## 125. クラウド層: E-5 音のつなぎの計算だけの部分（`e2688ff`、branch `cloud/20260905-2036`）

自律ループ第3層（クラウド routine）による6回目の実行。day3〜day12 の全行程処理はローカル層の
実素材作業のため触れず、§123 の推奨どおり研究 §5・roadmap E-5「音のつなぎ」の計算だけの部分を
実装した（§122 の `app/story_color.py`（E-6 露出）と同じ形）。

`app/story_audio.py`:

- `CROSSFADE_SECONDS`: 研究の値（0.5 秒）を定数として名付けただけ。
- `rms_baseline(rms_values)`: 窓群が比較の基準にすべき静かさを**中央値**で返す（風切りの酷い
  1 本が基準自体を引き上げて自分の超過を隠すのを防ぐ。`luma_target` と同じ理由）。
- `wind_attenuation_db(rms, baseline, *, threshold_db=6.0, attenuation_db=-6.0)`: `rms` が
  `baseline` より `threshold_db` 以上高ければ研究の値どおり `-6dB` を、そうでなければ `0.0` を返す。
  静かな窓（信号待ち・惰性走行）を持ち上げることはしない。閾値超えは段階的でなく一律 `-6dB`
  （「酷い」かどうかの二値判断であり、比例補正ではない）。
- `wind_attenuations(rms_values, *, baseline=None, ...)`: 窓群全体への適用列（順序保持）。

RMS の実測はこの codebase にまだ存在せず、`app.story_film` は現状すべての窓の音声を丸ごと捨てている
（本文冒頭のコメントどおり）。したがってクロスフェード・減衰を実際の render に配線するかどうかは、
「録画の音をそもそも使うか」という `app.story_color` の露出補正より大きい、レンダー側の判断として
残した——数値さえ揃えば計算できる状態にしただけ。

**テスト** `tests/test_story_audio.py`: 22 件、合成 fixture のみ（実素材なし）。定数値、基準の中央値
（奇数・偶数個）、基準ちょうど・基準より静かな窓・閾値未満で補正0、閾値ちょうど・大幅超過で同じ
一律 `-6dB`（比例でないことの確認）、カスタム閾値・減衰量、dBFS の検証（正値・非有限の拒否）、
閾値・減衰量の符号検証、既定基準（自群の中央値）、全窓同一で補正すべて0、入力順の保持、明示
baseline での上書き、空リストの拒否。

**環境**: `pip install -e '.[dev]'` 成功、`google`/`vertexai`/`agentplatform` の import 解消。`ffmpeg`・
`qlmanage` 未導入のため `tests/test_judged_film_end_to_end.py`（6 件）のみ `--ignore` で外した（前回まで
と同一理由）。node は導入済みで `tests/test_web_page_scripts_parse.py` は実行できた。**全 1609 件成功
（1587 既存 + 22 新規）、Ruff check・format 成功**。支出 ¥0（実素材・Gemini・GCS には一切触れていない）。

**次に推奨**: E-1「章内の並び」の判断（時刻順を守る）を実装した `chapter_order.py` は配線待ちのまま
（§122 時点から変わらず）——配線は見た目が変わる判断でローカル層向けだが、その手前で
`chapter_order.py` 自身の境界テストが薄ければ補強の余地がある。または `app/scout.py`・
`app/video/local_catalog.py` など未テストの純粋ロジックの境界補強（§123 の推奨の続き）。
day3〜day12 の処理はローカル層の続きを待つ。

## 126. クラウド層: `app.video.local_catalog` の境界・失敗経路のテストを追補（`7700af4`）

day3〜day12 の全行程処理はローカル層の実素材作業のため触れず、§123 の推奨（`local_catalog.py`・
`scout.py` など未テストの純粋ロジックの境界を補う）に沿って単位を選んだ。origin の `cloud/*` を
確認し、`cloud/20260905-2036`（E-5 音のつなぎ、未統合）と題材が重複しないことを確認済み。

`tests/test_local_video_catalog.py` は既存 8 件が主要経路（LRV 除外、GoPro チャプター連結、
欠落・probe失敗の issue 化、非有限オフセットの拒否、上書き保護）を確認していたが、以下の境界・
失敗経路が未検証だった:

- GoPro チャプターの記録開始時刻の許容差（`_GOPRO_CREATION_TIME_TOLERANCE_S` = 2.0 秒）の
  境界ちょうど（受理）と直後（拒否）。
- チャプター群内で1本だけ probe に失敗した場合、probe に成功した残りのチャプターも
  「不完全な群」として `INVALID_GOPRO_CHAPTER_SEQUENCE` になること（未検証だった副作用）。
- 同一チャプター番号が群内で重複する場合（`_gopro_chapter_identity` をモンキーパッチして
  意図的に衝突させる合成ケース）の拒否。
- GoPro ファイル名の大文字・小文字非依存の認識。
- 独立クリップとチャプター群のエントリが混在するときの、記録開始時刻による全体ソート順。
- `LocalVideoCatalogBuild.__post_init__` の4つの不変条件（負のカウント、
  source+skipped ≠ inventory、entries+issues ≠ source、logical/adjusted が entries を超える）を
  dataclass を直接構築して個別に確認。
- `LocalCatalogIssue.to_dict()` が asset_id（ハッシュ）とコード文字列のみを含み、パスを含まないこと。

path・実ファイル名・座標・時刻は合成 fixture のみ（`tmp_path` の空ファイルと fake probe 関数）で、
実素材・GCS・Gemini には一切触れていない。

**テスト**: 新設 14 件（8 → 22、`tests/test_local_video_catalog.py`）。**全 1599 件成功**
（`pip install -e '.[dev]'` 成功で google/vertexai/agentplatform 一式込み。`ffmpeg` 未導入のため
`tests/test_judged_film_end_to_end.py`（6 件、実際に ffmpeg を呼ぶ結合テスト）のみ `--ignore` で
外した——前回までと同一理由。node は導入済みで `tests/test_web_page_scripts_parse.py` も実行できた）。
Ruff check・format 成功。支出 ¥0。

**次に推奨**: 同じ手法で `app/scout.py`（未テスト、§123 の推奨に残っていた）の境界・失敗経路。
または `app/gopro_gps.py`（day3〜day4 のオフセット規則刷新の元、§121 の教訓）の純粋関数部分の
境界テスト補強。day3〜day12 の処理と `cloud/20260905-2036`（E-5）の取り込みはローカル層/次回の
統合待ち。

**day9 完了（2026-09-06 08:57）**: 403 窓 ≈¥59.54 → rank 成功 → film **303.1 s・436 MB**（採用 54 窓、題付き 6）。累計 ≈¥489。day10 へ。

**オーナーの問い（2026-09-06 09:00）「GoPro の縮小版（LRV）は利用できなかったか」** → 送るコピーの元として使うのが正解
（roadmap に単位追加）。理由: Gemini の動画料金は秒数×1 fps 相当で決まり、こちらの fps や解像度を上げても得はない一方、
LRV を 12 秒切ってそのまま送ると 1 窓 ≈12 MB（今の 0.7 MB の 17 倍）。だが**復号の元**を LRV にすれば 4K HEVC の
復号が消え、preflight（1 日 18〜25 分）が数分になる。作品本体は 4K 原本から。バッチ終了後に `make_proxy` の入力を
`sidecar_for()` 経由にする（`app/gopro_gps.py` に既にある）。

**day10 完了（2026-09-06 10:10）**: 265 窓 ≈¥39.15 → rank 成功 → film **287.0 s・390 MB**（採用 51 窓、題付き 5）。累計 ≈¥528。day11 へ。

**day11 完了（2026-09-06 11:22）**: 356 窓 ≈¥52.60 → rank 成功 → film **284.2 s・406 MB**（採用 57 窓、題付き 6）。累計 ≈¥581。day12 へ（preflight は LRV 元で初回）。

---

## 127. 2日前の文脈で目を覚まして、走っているバッチの横で古い package を触った（2026-09-06 11:16〜11:32）

オーナーの「ログイン完了」（§121 で依頼した ADC 再サインイン）に応えた session が、
**2026-09-04 の文脈のまま**動いた。当時の未了作業（「2つ目の日を新しい帯で順位付けし直す」）を
そのまま実行してしまい、その間に **day12 の judge が走っていた**。

### 実際にしたこと

- **廃れた package** を新しい帯で順位付け: **40窓 / 4グループ / ¥2.25**（購入成立）。
  触ったのは 2026-09-04 に使っていた古い作業 package で、**その日の現行 package は別にある**
  （全行程バッチが作り直したもの）。現行の成果物は一切上書きしていない
- 同じ古い package の作品を再レンダー（`--overwrite`）: 155.0 s、23 beat（footage 21 / card 2）。
  上書きしたのは 2026-09-04 の古い作品だけ

### 分かったこと（¥2.25 で買えた知見）

今日の選別（`select_by_chapter`、章ごとに配分）で順位の有無を入れ替えると（古い package の
92 窓・stride 30 での測定なので、現行の日ごとの package の数字ではない）:

| | 順位あり | 順位なし |
|---|---|---|
| 採用 | 21窓 | 22窓 |
| 入れ替わり | 2 in / 3 out | — |
| 採用の平均 interest / story | 0.61 / 0.70 | 0.60 / 0.67 |

順位は今の選別でも効いている（採用の 1 割前後が入れ替わり、平均もわずかに上がる）。
第84節（旧選別・1つ目の日で 8/20）と桁は違うが、章ごとに枠を配る今の選別では
同点の塊が章単位に割れるため、順位が動かせる余地はもともと小さい。

### 反省（同じことを繰り返さないために）

1. **長く空いた session は、まず handoff の末尾を読んでから動く。** 今回は §83 の続きのつもりで
   §126 まで進んだ木を触った。ロードマップと handoff の末尾を読む手順はループの規約にあり、
   それを飛ばしたのは「会話の続き」に見えたためである
2. **同時実行の確認先が足りない。** 規約は web console の `job.state` だけを見よと書いていたが、
   全行程バッチ（`scripts/trip/process-days.sh`）は console を通らない。
   **`.autonomy/trip/batch.log` の末尾**（と `day-N-*.json` の mtime）を見れば走行中と分かる。
   ループの規約（`ride-storyteller-autonomous-loop`）にこの確認を足した
3. **古い作業 package が同じ日の名前で残っている。** 同じ日について古い package と現行 package が
   並んでおり、古い方を触っても止める仕組みが無い。判定・順位付けの前に、その package が
   handoff 末尾の現行系列（全行程バッチが作ったもの）かを確かめる
4. 古い package（stride 30・92窓）を今のコードで切ると 155 秒にしかならない。
   day3〜day12 の 280〜300 秒と比べないこと——窓の数も stride も違う

### 支出

¥2.25（廃れた package の順位付け＝実質は上の測定代）。**累計 ≈¥583 / 上限 ¥1000**（§120 のオーナー決定）。
day12 の judge（≈¥35.31）は別途、バッチ側で進行中。

## 128. 全行程バッチ完了: day3〜day12 の作品 10 本（2026-09-06 12:00）

| day | 窓 | 判定 ¥ | 作品 | 採用窓 |
|---|---|---|---|---|
| 3 | 168 | 24.82 | 226 s | 33 |
| 4 | 189 | 27.92 | 269 s | 51 |
| 5 | 326 | 48.17 | 294 s | 54 |
| 6 | 376 | 55.55 | 338 s | 69（順位なし版。買い直し中） |
| 7 | 297 | 43.88 | 259 s | 46 |
| 8 | 149 | 22.01 | 246 s | 36 |
| 9 | 403 | 59.54 | 302 s | 54 |
| 10 | 265 | 39.15 | 286 s | 51 |
| 11 | 356 | 52.60 | 283 s | 57 |
| 12 | 239 | 35.31 | 268 s | 46 |

判定合計 ¥408.95（stride 60）、順位づけ ≈¥2.25/日 × 9 ≈ ¥20、day3 の失敗分 ¥54.67。**累計 ≈¥635／¥1000**。
時計は全日 GPS 時計で −13.00 h（差 3 秒以内、カメラは NZ 現地時刻）。所要: 1 日 30〜60 分（preflight が大半）。
**day12 は LRV 元の preflight で 239 窓が約 1 分**（従来 13〜25 分）。順位づけは day6 のみ失敗（寛容版で買い直し）。
サインイン期限切れ 1 回（購入 0 で停止 → オーナー再ログイン）。

**残り**: day6 の順位買い直し＋作品更新（実行中）。オーナーの全日視聴と感想。次の設計: 12 日分の
「旅全体」の 1 本（各日のハイライトを 10〜15 秒ずつ）は研究の続きとして roadmap へ。

**day6 更新（2026-09-06 12:26）**: 寛容版の順位づけ成功（559 s、≈¥2.25、40 窓 4 グループ）→ 作品 **305.9 s・422 MB**
（338.6 s から。順位が同点の並びと尺を変えた）。累計 ≈¥637。全行程バッチはこれで完了、ロック解放。

## 129. クラウド層: `app.analysis_look` の境界・失敗経路のテストを追補（`96988aa`）

自律ループ第3層（クラウド routine）による7回目の実行。day3〜day12 の全行程処理（§121）はローカル層の
実素材作業のため触れず、origin の `cloud/*` を確認（未統合の branch なし）してから §123・§126 と同じ手法で
単位を選んだ。

`app/analysis_look.py`（窓の見た目を輝度・色2軸・動きの4値で測り、判定プロキシと同じ package に
`analysis-look.json` として保管するモジュール）の既存 `tests/test_analysis_look.py` は8件で主要経路
（複数フレームの平均・先頭差分の除外、距離計算、一度測ったら再測しない保管、値の検証、系列付き
再測定）を確認していたが、以下の境界・失敗経路が未検証だった:

- `measure_look`: フレームが1枚だけの窓では「先頭の差分は捨てる」規則が空系列を残してしまうため、
  自身の差分をそのまま動きの値に使う fallback（未検証だった分岐）。シンボリックリンクされたプロキシは
  実体があっても「欠落」として扱われること（`is_symlink()` の判定は `is_file()` の前）。
- `looks_for`: 保管ファイル自体がシンボリックリンクの場合は「unsafe」で拒否。未対応の
  `schema_version` は拒否。窓を1本も要求しない呼び出しは測定も書き込みも行わず空を返す。
  書き込み失敗時（`json.dump` を模擬的に失敗させる）に一時ファイルが残らないこと（atomic write の
  例外経路）。
- `WindowLook.to_dict()`: 系列が無いときは `motion_series` キー自体を含まないこと。
  `distance()` が対称であること。

path・実ファイル名・座標・時刻は一切扱わない（このモジュール自体が窓の内容を読まず、輝度・色・動きの
数値だけを扱う）。新設テストも合成 fixture（fake ffmpeg 出力を注入する runner、`tmp_path` 上のダミー
ファイル）のみ。

**テスト**: 新設7件（8 → 15、`tests/test_analysis_look.py`）。`pip install -e '.[dev]'` 成功で
google/vertexai/agentplatform 一式込みの全収集ができた。`ffmpeg` は未導入のため
`tests/test_judged_film_end_to_end.py`（6件、実際に ffmpeg を呼ぶ結合テスト）のみ `--ignore` で
外した——前回までと同一理由。node は導入済みで `tests/test_web_page_scripts_parse.py` も実行できた。
**全1629件成功（1622既存 + 7新規）、Ruff check・format 成功**。支出 ¥0（実素材・Gemini・GCS には
一切触れていない）。

**次に推奨**: 同じ手法で `app/story_hold.py`・`app/video/highlight_quality.py` など、テスト済みだが
分量に対して件数が薄いモジュールの境界補強。または roadmap 7.9「運用」（失敗の可視化・再開・コスト監視・
上限で止まる設計）のうち計算だけの部分。day3〜day12 の処理はローカル層の続きを待つ。

## 130. クラウド層: `app.gopro_gps` の境界・失敗経路のテストを追補（`d44092c`）

自律ループ第3層（クラウド routine）による7回目の実行。day3〜day12 の全行程処理・その後の反省（§127）は
ローカル層の実素材作業のため触れず、§126 の推奨（`app/gopro_gps.py` の純粋関数部分の境界テスト補強）に
沿って単位を選んだ。origin に未統合の `cloud/*` branch は無く、重複の心配はなかった。

`app.gopro_gps` は day3〜day4 の停止（§121）を経て containment 法から GPS 時計を第一手段に格上げした
モジュールで、既存の `tests/test_gopro_gps.py` は主要経路（1秒1fix・中央値によるクロック測定・日ごとの
合意判定・LRV サイドカー読取り・CLI の JSON 出力）を8件でカバーしていたが、以下の境界・失敗経路が
未検証だった:

- `GpsFix.is_trusted` の閾値ちょうど（`GOOD_FIX`・`GOOD_PRECISION`、受理）と一歩外れた値（拒否）。
- `recording_clock` の `MIN_FIXES` ちょうど（測定できる）と一歩足りない（できない）、信頼できない fix を
  いくら足しても不足を埋められないこと。
- `RecordingClock.to_dict()` / `DayClock.to_dict()` の丸めと、**file_name を一切含まない**という
  privacy 不変条件（`RecordingClock.to_dict()` は意図的に file_name を落とし、`DayClock` はそもそも
  録画名を保持しない）。
- `day_clock` の `AGREEMENT_S` 境界（ちょうどは合意あり、一歩超えると合意なし）。
- `day_clock` が、reader が `GoProGpsError` を送出する録画（gpmd トラックが無い等）を「GPS無し」として
  数え、日全体の測定を落とさないこと（従来は「trusted fix 不足」経由の同じカウンタしか通っていなかった
  未検証の分岐）。
- `sidecar_for` の接頭辞・stem長の境界（短すぎる stem、GoPro以外の接頭辞、大小文字を区別する設計、
  stem長ちょうど4の境界）。
- `parse_gps_fixes` が、パースできないタイムスタンプや GPS5 欠落のパケットを（例外を出さず）読み飛ばすこと、
  空入力で何も返さないこと。

合成 fixture のみ（既存ヘルパーが作る GPMF バイト列、または `GpsFix` を直接構築）。実素材・実ファイル名・
座標・GCS・Gemini には一切触れていない。

**テスト**: 新設18件（`tests/test_gopro_gps.py`、8 → 26）。**全 1641 件成功（1623 既存 + 18 新規、
`tests/test_judged_film_end_to_end.py` の6件を除く）、Ruff check・format 成功**。環境は前回までと同じく
`pip install -e '.[dev]'` で `google`/`vertexai`/`agentplatform` の import は解消。`ffmpeg` が無い環境
のため `tests/test_judged_film_end_to_end.py`（6件、実際に ffmpeg を呼ぶ結合テスト）のみ `--ignore` で
外した（前回までと同一理由）。node は導入済みで `tests/test_web_page_scripts_parse.py` も実行できた。
支出 ¥0。

**次に推奨**: `app/clock_offset.py`（GPS の無いカメラ向けの containment 法、フォールバックとして残る
純粋関数）の境界テスト補強。または `app/analysis_screening.py`（7.4 で「測って報告するだけ」と位置づけ
られた無料スクリーニング、閾値ロジックの境界）。day3〜day12 の処理・§127 の反省を踏まえたループ規約の
改善はローカル層/次回の統合待ち。

## 131. クラウド層: `app.ride_chapters` の未検証だった経路にテストを追補（`4a1c308`、branch `cloud/20260906-0435`）

全行程バッチ（day3〜day12）はロールに沿ってローカル層に残し、`app/*.py` 対 `tests/test_*.py`
の行数比を洗い直して単位を選んだ。`app/ride_chapters.py`（653行）は `tests/test_ride_chapters.py`
（252行、比 0.38）で app/ 内最低の比率——チャプター分割・命名・タイムライン組み立てという
純粋ロジックのみのモジュールで、実素材を使わず境界を補える。

追補した経路（すべて合成の GPS 点列 fixture）:

- `RideChapter.__post_init__` の2つの不変条件（非正の尺、負の集計値）をデータクラスを
  直接構築して確認。`to_dict()` が集計値6項目のみを返すこと（座標・時刻は入力にも
  含めていないが、キー集合を直接検証）。
- `describe_chapter` の分岐: 始点・終点の海抜が両方あるときの表現、無いときの
  登り/下りへのフォールバック、変化が小さいとき何も言わない、1000m でのkm切替、
  「出発から」の分の繰り上がり（59分→1時間00分）。
- `chapter_cards` の見出し枯渇: 同じ性格の章が自前の見出し数を超えたら共有の
  LINK 予備へ、それも尽きたら番号付き予備（「その先 4」）へ——重複なしのまま。
- `day_account`（`private_journey_film.py` から呼ばれているのに直接のテストが
  一件も無かった）の通常経路と「2点未満」の失敗経路。
- `build_chapter_timeline` の2つの失敗経路: 章が0件、そして2つの窓が章境界を
  1秒未満の間隔で挟んでカードの置き場が無くなるケース。
- `long_halts`・`passes` の最小点数未満での早期return。

path・ファイル名・座標・時刻は `_track()` が合成する GPS 点列のみで、実素材・GCS・
Gemini・課金には一切触れていない。

**テスト**: 新設17件（`tests/test_ride_chapters.py` 252→432行）。**全1640件成功**
（`pip install -e '.[dev]'` 成功で google/vertexai/agentplatform 込み。`ffmpeg` 未導入のため
`tests/test_judged_film_end_to_end.py`（6件、実際に ffmpeg を呼ぶ結合テスト）のみ除外——
従来と同一理由。node は導入済みで `tests/test_web_page_scripts_parse.py` も実行できた）。
Ruff check・format 成功。支出 ¥0。

**次に推奨**: 同じ手法で `app/story_film.py`（1043行・比0.46）または `app/gopro_gps.py`
（382行・比0.50）の境界テスト補強。もしくは `app/scout.py`・`app/demo.py`・`app/story_copy_probe.py`
（テストファイル無し）に最初の一本を書く。全行程バッチの視聴フィードバックが出たら
それを単位の優先に。

## 132. 運転手が大きく映る窓を外す（`d6369e1`、手動 session）＋ 物語構成の作り直しに着手中

オーナーの 3 回目の視聴（2026-09-06）: クリップの選択は良い、単調な窓は無い。物語の枠を
「どこからどこへ」に変えたいとして 8 点の要望。決定 3 点: 地名は Google Geocoding、章は
「休止から休止までの行程」、シーニックルートは公式指定の経路（OpenStreetMap の route relation、
`network=NZ:Touring:*` と SH の alt_name）を端末内の参照ファイルに置いて照合する（参照ファイルは
`private-media/reference/` 配下、git に入れない）。

**この節で入ったもの（点 6）**: `VideoAnalysis.rider_visible`（none/small/large、旧記録は unknown）、
判定の schema と rubric に同項目、`app/rider_in_frame.py`（モデルの答えが無い旧記録は描写文の語で判定）、
選抜の床に `rider_fills_the_frame`。12 日分の記録では 3,657 窓中 49 窓、ほぼ全て停止中（鏡の映り込み）。
再判定は不要。

**着手中: 手動 session（2026-09-06 20:00 JST〜）** — 点 1・7（定点と行程の章）、続いて 2（地名）、
8（節）、3・4・5。触るモジュール: `app/ride_chapters.py`、`app/story_pacing.py`、`app/gemini_selection.py`、
`app/footage_candidates.py`、`app/analysis_run.py`、`app/private_journey_film.py`、`app/gps/`、
`app/chapter_card.py`、`app/story_titles.py`。自律層はこれらを避けて別の単位を選ぶこと
（`story_ambient` の未 commit 作業は別層のもの、触っていない）。

## 133. 行程の章・定点・地名（`bc8b067`、`981b819`、手動 session）

§132 の続き。オーナーの決定（地名は Google Geocoding、章は休止から休止、シーニックルートは公式指定）を受けて
S-1/S-7 と S-2 を入れた。

- **定点**（`app/gps/moments.py`、`app/fixed_shots.py`）: 出発＝動き出す直前の静止点（その後 60 秒で 100 m
  以上進む）、到着＝最後の動きの終点、休止の両端＝`long_halts` の両端。窓は事象時刻に合わせて置く
  （出発・再出発は動く 3 秒前から、到着・停車は止まった 3 秒後まで）。`plan_analysis_run` が転換点の窓の後に
  足し、既に判定済みの日は不足分だけ買う（`windows_at`）。選抜は定点を最初に採る
  （理由 `moment_the_track_proves`、点数の床は免除、運転手の規則は適用）。保持は窓頭から 8 秒。
- **行程＝章**（`segment_ride`）: 長い停止の終わりで切る。行程の末尾に `halt_s`。2 時間超は峠で、無ければ等分。
  6 章を超えたら最短を隣に畳む。停止の章は無くなった。地形の性格が「出発」「到着へ」より先。
- **地名**（`app/place_names.py`）: 行程の両端の座標（小数 4 桁）を 1 点 1 リクエスト、`place-names.json` に
  キャッシュ。章題「A → B」、見出しカードも「A → B · 距離」。`RIDE_PLACE_NAMES=none` で無効化。
  下部テロップの字数は全角換算（`display_width`）。`tests/conftest.py` が鍵を空にして誤送信を防ぐ。
- **12 日分の乾式確認**（ローカル、¥0）: 各日 2〜5 の休止、定点の窓は合計 56（≈¥8）。購入は ADC の期限切れで
  止まっている（`gcloud auth application-default login` をオーナーに依頼）。Geocoding API はまだ鍵の制限に無い。
- **公式シーニックルート**: OpenStreetMap の route relation（`network=NZ:Touring:*` 9 本＋SH43/SH73/SH45 の
  alt_name＋Inland Scenic Route 72、計 15 本、経路点 13 万）を Overpass から取得し
  `private-media/reference/touring-routes/nz.json`（3 MB、git 外）に保存。軌跡との照合は 150 m 以内の点の割合。
- **テスト**: 1,745 件成功。Ruff 緑。別層の `story_ambient` の未 commit 作業はそのまま（触っていない）。

**次**: オーナーの再ログインと API 有効化 → 定点の購入と地名の取得 → 12 日を再カット。並行して S-8（節）。

## 134. クラウド層取り込み: E-4 下ごしらえの重複実装（`app/story_caption.py`、`e8b82b5`統合）

クラウド routine の初回実行（branch `cloud/20260906-0636`、番号は自分の履歴で「§98」）が、
E-4 の題12字・本文21字を整形する関数を独自に実装していた（`app/story_caption.py`
`fit_title`/`fit_body`/`build_lower_third_caption`）。**E-4 本体は既に §99〜§101・§103 で
`app/lower_third_text.py` を使って実装・配線・再レンダー済み**——このクラウド branch は
分岐が古く、その後の進捗を知らないまま同じ目的の別モジュールを書いていた。

以下、そのブランチが残した記録（当時の視点のまま）:

## 98. クラウド層: E-4 の下ごしらえ——題12字・本文21字の整形関数（`33d87c4`）

第3層（クラウド routine）の初回実行。実素材・Gemini・GCS には触れていない。

roadmap の E-4（章題を動く絵の上に、下三分の一 5 秒）のうち、**純粋な文字数の整形だけ**を
`app/story_caption.py` に切り出した。`fit_title`（題を12字以内へ、超えたら省略記号で切る）、
`fit_body`（`describe_chapter` が返す「· 」区切りの本文を21字×最大2行へ、部品は割らずに詰め、
入りきらない部品が残れば最後の行を省略記号で示す）、両方を1度に適用する
`build_lower_third_caption`（幅については例外を出さない——出さないのは題が空でない場合のみ）。

**E-4 本体（下三分の一への置き換え・全画面カードの廃止・冒頭15秒の見え方）はここでは実装していない。**
実素材でオーナーが見て確認する単位なので、レイアウト・レンダリングへの配線は次のローカル層/オーナー確認の
単位に残した。今回はその手前の、境界値だけで閉じるテキスト整形を先に済ませた。

テスト27件を新規追加（合成テキストのみ。実ライドの題・本文は使っていない）。全1334件成功
（`test_judged_film_end_to_end.py` の6件は `ffmpeg` バイナリがこのクラウド環境に無いため実行不可——
コード起因ではなく環境要因、他は変更していない）。Ruff（check・format）成功。支出 ¥0（累計 ≈¥147）。

**次に推奨する単位**: E-4 本体（このモジュールを `chapter_card.py`/描画経路に配線し、実素材2 rideで
オーナー確認）。もしくは roadmap 「残: 配分の余りの回し」（第96節末尾）。どちらも実素材の再レンダーが
要るため、ローカル層向け。

**取り込みの判断**: `app/story_caption.py` とそのテストはコード上無害（既存モジュールに触れず、
テスト・Ruff とも緑）なので取り込む。実際の配線には使わない——`lower_third_text.py` が現行。
死んだコードとして残るのは望ましくないが、削除も別の判断が要るため、次にこのモジュールに
触れる者への注記としてここに残す。

## 135. クラウド層取り込み: `app.scout` の境界・失敗経路のテストを新設（branch `cloud/20260906-0835`、`c12f274`統合）

クラウド routine の2回目の実行が残した記録（そちらの履歴では「§129」、以下は当時の視点のまま）:

day3〜day12 の処理・視聴・次の設計（旅全体の1本）はローカル層/オーナー側の続きのため触れず、
§126 の推奨（未テストの純粋ロジックの境界補強）に沿って単位を選んだ。origin の他 `cloud/*` を
確認し、重複なし。

`app/scout.py`（GPS/映像解析と Director を橋渡しする `to_universal_event`・`UniversalEvent`）は
テストが1件も無かった。モジュールの docstring に書かれた契約——二重の video-evidence gate、
source 3項目の all-or-nothing、生の緯度経度・ファイル名を `UniversalEvent` に一切載せない
プライバシー不変条件——を守る境界・失敗経路を新設 `tests/test_scout.py` で検証:

- `candidate_clip`/`resolved_clip`/`gps_event` 間の `event_id` 不一致、`candidate_clip` と
  `resolved_clip` の `chapter_id` 不一致（いずれも `ValueError`）。
- `NOT_FOUND` の `resolved_clip` は理由に関わらず source として拒否されること
  （呼び出し側は未解決なら `resolved_clip` 自体を渡さない設計であることの確認）。
- `scored_window` の前提条件（`candidate_clip`・`resolved_clip` 必須）、asset_id 不一致、
  区間がはみ出す場合の拒否、**ちょうど境界**（許容誤差ぎりぎりでなく完全一致）は受理されること。
- `evidence_confirmed` は `CONFIRMED`＋`MATCHED` の両方が揃う場合のみ真になること、
  `REJECTED` でも video evidence 自体は真になること（confirmed とは独立）。
- `UniversalEvent.__post_init__` の各不変条件を直接構築して個別に確認
  （intensity・score の範囲、source 3項目の all-or-nothing、evidence_confirmed と
  video evidence／resolved source の依存関係）。
- プライバシー不変条件: `UniversalEvent` およびネストする `UniversalEventEvidence`・
  `UniversalEventLocationContext` の dataclass フィールドを列挙し、`latitude`・`longitude`・
  `file_name`・`source_uri` 等が存在しないことを確認。

path・実ファイル名・座標・時刻は合成 fixture のみ（`app.video.highlight_quality` 系の既存テスト
（`test_highlight_story_bridge.py`）と同じ手法で `WindowFeatures`・`HighlightWindowEvidence`・
`ScoredHighlightWindow` を組み立てた）で、実素材・GCS・Gemini には一切触れていない。

**テスト**: 新設 42 件（`tests/test_scout.py`）。**全 1665 件成功**（`pip install -e '.[dev]'` 成功で
google/vertexai/agentplatform 一式込み。`ffmpeg` 未導入のため `tests/test_judged_film_end_to_end.py`
（6 件、実際に ffmpeg を呼ぶ結合テスト）のみ `--ignore` で外した——前回までと同一理由。node は
導入済みで `tests/test_web_page_scripts_parse.py` も実行できた）。Ruff check・format 成功
（format は新設ファイルに1回自動整形をかけた）。支出 ¥0。

**次に推奨**: 同じ手法で `app/gopro_gps.py` の純粋関数部分の境界テスト補強（§126 で挙げたまま
未着手）、または `app/chapter_order.py`（E-1 章内の並び、配線待ちのままローカル層向けだが
自身の境界テストは補強の余地がある）。day3〜day12 の視聴・感想、旅全体の1本の設計は
オーナー/ローカル層の続きを待つ。

**取り込みの判断**: 既存 `tests/test_universal_event.py`（60件）と重なる契約もあるが、内容は
競合せず追加のみ。テスト・Ruff とも緑なので取り込む。

## 136. クラウド層取り込み: `app.gopro_gps` の境界・失敗経路のテストを追補（branch `cloud/20260906-1035`、`ef17139`統合）

クラウド routine の3回目の実行が残した記録（そちらの履歴では「§129」、以下は当時の視点のまま。
`tests/test_gopro_gps.py` は §130 で既に別の境界テストが追補されていたため、同じファイルの
別セクションとして両方残した——テスト関数名はすべて異なり重複なし）:

day3〜day12 の全行程処理（§121・§128）はローカル層の実素材作業のため触れず、§126 の推奨
（「`app/gopro_gps.py`（day3〜day4 のオフセット規則刷新の元、§121 の教訓）の純粋関数部分の境界
テスト補強」）に沿って単位を選んだ。origin の未統合 `cloud/*` を確認し、`cloud/20260906-0835`
（`app.scout` の境界テスト、§126 の推奨の別枝）と重複しないことを確認済み。`cloud/20260906-0636`
は main よりかなり古い時点を祖先とし、`app/gopro_gps.py` を含む多数のモジュールを削除する差分
だった（壊れた/古い branch と判断し、参照も統合もしていない）。

`app.gopro_gps`（day3〜day4 でタイムゾーン規則・containment 法を捨てて GPS 時計を第一手段に
した、その実装本体）の既存 `tests/test_gopro_gps.py`（6 件）は一続きの正常系（フルの秒単位
トラック、日単位の一致判定、LRV サイドカー）しか見ておらず、以下の境界・失敗経路が未検証
だった:

- `GpsFix.is_trusted` の `GOOD_FIX`／`GOOD_PRECISION` ちょうどの境界と、その一つ外側。
- `parse_gps_fixes` が壊れた/部分的な GPMF を渡されたときに例外を出さず「フィックス無し」に
  倒れること: STRM を持たない DEVC、GPS5 の無い STRM、GPSU の無い STRM、時刻としてパースでき
  ない GPSU 値。
- `recording_clock` の `MIN_FIXES` ちょうど（測定される）とその一つ下（`None`）。
- `sidecar_for` の GX/GH 接頭辞チェックより短い stem、GoPro 命名でないファイル名。
- `day_clock` に録画が1本も無い場合のエラー経路。
- `RecordingClock.to_dict()`／`DayClock.to_dict()` の丸めと形（曖昧・負のオフセットの枝も含む）。
- `gpmd_stream_index`・`extract_gpmf` の subprocess 失敗経路（probe 失敗・gpmd 無し・ffmpeg 失敗）を
  `subprocess.run` の monkeypatch で確認。

新設テストはすべて合成 GPMF バイト列をその場で組み立てるか `subprocess.run` を monkeypatch する
のみで、実素材・実 GPS・GCS・Gemini には一切触れていない。

**テスト**: 新設 22 件（6 → 28、`tests/test_gopro_gps.py`）。**全 1643 件成功**（`pip install -e '.[dev]'`
成功で google/vertexai/agentplatform 一式込み、1629 件収集）。`ffmpeg`・`qlmanage` は未導入のため
`tests/test_judged_film_end_to_end.py`（6 件、実際に ffmpeg を呼ぶ結合テスト）のみ `--ignore` で
外した——前回までと同一理由。node は導入済みで `tests/test_web_page_scripts_parse.py` も実行できた。
Ruff check・format 成功。支出 ¥0（実素材・Gemini・GCS には一切触れていない）。

**次に推奨**: `cloud/20260906-0835`（`app.scout` の境界テスト）を確認・統合する（本節と同じ手法・
未統合のまま）。または `app/journey_gaps.py`・`app/gap_chapters.py` など未確認の純粋ロジックの境界
補強。`cloud/20260906-0636` は壊れた/古い branch として扱い、統合しない（削除は次にこの branch 群を
整理する回に譲る）。day3〜day12 のローカル層作業は完了済み（§128）で、次はオーナーの全日視聴と
感想待ち。

**取り込みの判断**: `tests/test_gopro_gps.py` の import 文（`AGREEMENT_S`・`GpsFix` の有無）だけが
テキスト衝突し、テスト本体は無衝突で両方残した。テスト・Ruff とも緑なので取り込む。この節が
「壊れた/古い branch」と述べた `cloud/20260906-0636` は、実際には main へ無事統合済み（§134）——
祖先が古かっただけで、削除差分ではなかった。

## 137. 自律ループ（デスクトップ層）: `app.clock_offset` の境界・失敗経路のテストを追補

§132 の「着手中: 手動 session」（`ride_chapters.py`・`story_pacing.py`・`gemini_selection.py`・
`footage_candidates.py`・`analysis_run.py`・`private_journey_film.py`・`app/gps/`・`chapter_card.py`・
`story_titles.py`）を避け、§130 が推奨していた `app/clock_offset.py`（GPS の無いカメラ向け
containment 法、GPS 時計が使えないときのフォールバックとして残る純粋関数）の境界テストを追補。
作業開始時、`app/private_journey_film.py`・`app/story_film.py` に別層（手動 session）の未 commit
差分、`app/story_ambient.py`・`tests/test_story_ambient.py` に別層の未 commit 新規ファイルがあった
——いずれも触れていない。

`app/clock_offset.py` の既存 `tests/test_clock_offset.py`（10件）は主要経路（カメラのオフセット
復元、根拠の提示、正しい時計、半時間ゾーン、明確な答え、曖昧な答え、別日の映像の拒否）を見ていたが、
以下の境界・失敗経路が未検証だった:

- `propose_clock_offset`: track が1点だけで尺ゼロの GPX → 「the ride's own track covers no time」。
- `_recordings`: 動画ディレクトリ自体がシンボリックリンク（実体は正しいディレクトリでも拒否）、
  ファイル自体がシンボリックリンク（無視）、対象外の拡張子（probe を一切呼ばない——呼べば
  辞書 lookup で `KeyError` になる fixture で確認）、拡張子の大小文字を区別しないこと、
  `recorded_start_time` が無い録画・尺ゼロの録画（後者は `LocalVideoMetadata.__post_init__` 自身が
  尺>0を強制するため、属性だけ揃えた `SimpleNamespace` で境界を再現）。
- `_score`: 重なる2本の録画区間が `covered_ride_s` で二重計上されず、マージされた区間として
  数えられること。
- タイブレークの規則: 同着の候補群の中で `abs(offset_s)` が最小のものが選ばれること
  （固定値ではなく、候補群を実際に走査して検証）。
- `candidate_offsets_s`（探索範囲を絞る）・`keep_runners_up`（0件にすると常に「明確」と
  報告されること——保持しなかった同着は報告のしようがない、という副作用も含めて）の呼び出し
  引数としての振る舞い。
- `ClockOffsetCandidate.inside_ratio`/`covered_ratio` を合計0件で直接構築し、0除算せず0を返すこと。

合成 GPX・合成 `LocalVideoMetadata`（一部は `SimpleNamespace` で属性だけ揃えた模造品）のみ。
実素材・実ファイル名・座標・GCS・Gemini には一切触れていない。

**テスト**: 新設14件（`tests/test_clock_offset.py` 10→24）。**全1846件成功**（クラウド層3branch
（`cloud/20260906-0636`・`0835`・`1035`）を先に取り込んだ後の数、内訳は各節を参照）。Ruff
check・format 成功。支出 ¥0。

**次に推奨**: `app/analysis_screening.py`（7.4「測って報告するだけ」の閾値ロジック）の境界補強。
または `app/story_ambient.py`（別層が未 commit のまま置いているモジュール、いずれそちらの層が
commit するはず）。§132 の手動 session が触れているモジュール群は引き続き避けること。

## 134. 定点の購入・地名の取得・12 日の再カット（`7b58b00`、`a6b7907`、手動 session）

- **定点の窓**: オーナーの再ログイン後、day2〜12 で `judge --overwrite` を 1 日ずつ実行。完成記録は引き継がれ
  不足分だけ買う（56 窓、¥8.3、Gemini 累計 ≈¥645）。CLI の報告は完成記録からの引き継ぎを数えていなかったので
  `carried_from_finished_record` を足し、`newly_bought` を「計画にあって手元に無かった窓」に直した（`7b58b00`）。
- **地名**: Geocoding API 有効化後、行程の両端を取得（77 リクエスト、package の `place-names.json`）。
  日本語で問うと有名な町だけカタカナ、他はラテン文字になり一つの題に混ざるため、
  `RIDE_PLACE_LANGUAGE`（既定は作品の言語）を足し、この旅は `en` で取り直した。同じ町で始まり終わる行程は
  町名だけの題になる（周回や短い行程）。
- **再カット**: `RIDE_PLACE_LANGUAGE=en` で 12 日を再カット。見出しは「始点 → 終点 · 距離」、章題は「A → B」、
  本文は「性格の語 · 出発から · 距離 · 海抜 · ここで N 分」。
- **HEAD の破損と修復**（`a6b7907`）: 別層の未 commit 作業（ambient）が同じファイルにあり、自分の hunk だけを
  分けて stage した 2 つの commit（`981b819`・`7b58b00`）の同ファイルが構文エラーだった（作業木は正常、テストは
  作業木で通っていた）。作業木の版から ambient の追加分だけを取り除いた版で HEAD を直し、`git stash` して
  HEAD 自体で 1,830 件のテストを通した。**教訓**: 他者の WIP を含むファイルの部分 stage はしない。
  記憶ファイル `shared-worktree-partial-staging` に残した。

## 135. 行程をまたぐ窓の間隔（`a0af7d8`、手動 session）

day6 の再カットが `build_chapter_timeline` の「two windows leave no room for a chapter card」で止まった。
再出発の定点（動き出す 3 秒前から）は行程の境目をまたぎ、次の行程は独立に選抜していたので数秒後に始まる
stride の窓を採り、二つの窓が走行時刻で重なって章カードの置き場が無くなった。行程ごとの独立選抜は以前からで、
境目に定点を置いたことで稀→頻発になった。

直し: `select_judged_candidates(avoid=…)`——別の行程で既に採った窓と定点を「間隔」の判定にだけ数える
（尺には数えない）。`select_by_chapter` は一日の定点を先に留め、各行程に他の定点と前の行程の採用窓を渡す。
これで作品中のどの二つの窓も 120 秒より近づかない。day6 再カット 5分39秒。他の 11 日も同じ規則で再カット中
（境目付近の 1〜2 窓が入れ替わる程度）。

## 136. S-5 シーニックルートの照合（`d116c0a`、手動 session。配線はまだ）

`app/scenic_routes.py`: 参照ファイル（`touring-routes-v1`、`private-media/reference/touring-routes/*.json`、
環境変数 `RIDE_TOURING_ROUTES` で 1 ファイルを指定可）を読み、経路点を約 1 km の格子に入れて、軌跡の各点が
150 m 以内にあるかを見る。連続する区間（3 分までの離脱は許す）が 15 分以上なら `ScenicStretch`。同じ道を
共有する 2 経路はその日長く走った方が勝つ。`segment_ride(scenic=…)` はその区間を一章にし（両端が停止や
一日の端から 20 分以内ならそこに寄せる）、長さでの分割も畳み込みも免除、`RideChapter.route_name` を持ち、
カードの性格の語は経路名になる（題は S-2 の「A → B」のまま）。**`scenic` を渡さなければ従来どおり**——
再カットのバッチが走っている間に挙動を変えないため、`plan_journey_film` への配線はバッチ後に行う。

## 137. S-3 都市部通過・4回目視聴の9点・S-8 節（章内テロップ）: 配線まで完了（`2e6dcb5`、`1f64d70`、`5f7b0e0`、手動 session）

自律ループが前回引き継いだ時点では §136 まで（S-5 は照合のみで配線は保留）だったが、その後の
手動 session が同じ晩のうちに3つの commit で残りの物語構成（S-3・S-8）を実装し、S-5 の配線も
含めて `plan_journey_film` に一括で通した。この節はその追いつき（本来は commit ごとに書くはず
だった）。

**S-3（`2e6dcb5`）**: `app/town_passages.py`。オーナーの三つ目の規則——走行そのものと都市部通過は
別物。軌跡（3分以上・時速43km未満・停止2回以上、halt は除く）と、モデルの記述の語彙（street・
urban・roundabout 等）の**両方**が言う区間だけを都市部と判定する。地名を付けるのは配線時（後段）
の place service の役目、と当時の commit は書いていたが、実際には同じ晩のうちに配線された。

**4回目視聴の9点のうち未着手だった5点（`1f64d70`）**: オーナーの第4回視聴の指摘（2026-09-06夜）。
- 出発・到着の判定を走行の速さ（1分300m、旧100m）で読む。カメラが止まった7分後に宿へ徒歩で着いた
  ケースが誤って「到着」に含まれていた
- カメラが日の出発・到着を1時間未満だけ外して撮り逃したときは、切り捨てず撮れている最初/最後の
  瞬間に寄せる（休止の外れた端は単に映さない）。計画と作品が読む録画は同じにする
- モデルが車庫・駐車場・私道の窓を選んだら除外（`parked_in_a_car_park`）。ただし**その日自身の
  出発・到着**は例外として作品が使ってよい
- 締めカードは作品の最後（到着が最後の絵）に固定し、本文は行程が通った地名を順に重複なく列挙、
  距離・時間はその下
- 停止の少ない日は `TARGET_CHAPTERS`（目安5章）で長い行程の中間あたりを通過点に割って分割。
  シーニックな行程はこの分割の対象にしない

**S-8（`5f7b0e0`）**: `app/story_sections.py`。オーナーの8番目の規則——章は行程の始点と終点を
言うが、節は移動中の絵に重ねて「今どこにいて、物語がどう転がったか」を言う。`SectionEvent`
（`SectionKind`: 都市部・休止・立ち寄り・シーニックルートへの出入り・幹線道路からの離脱）を
軌跡と各参照ファイルから作り、`attach_sections` が瞬間に最も近い窓（窓の始まりが瞬間の30秒前〜
10分後）の下三分の一に1行だけ4秒重ねる。章題を持つ窓には重ねない。同じ行は30分以内なら言い
直さない。`app/private_journey_film.py` の `_section_events` がこれを組み立て、`segment_ride`
は `scenic=stretches` を受け取るようになった——**§136 が「配線はまだ」と書いた S-5 の配線は
この commit で完了した**。S-3 の都市部判定もここで `SectionKind.TOWN` として配線済み。

**気づいたこと（コードの欠陥ではなかった）**: 統合直後に全体テストを流すと
`tests/test_private_journey_film.py::test_a_judgement_decides_which_clips_the_film_uses` が
`NameError: name 'replace' is not defined`（`app/private_journey_film.py` の `_highway_runs`）で
落ちた。`from dataclasses import dataclass, replace` は実際には存在しており、`__pycache__` を
削除して再実行すると通った——古いバイトコードキャッシュが原因で、commit された行の欠陥ではない。

**取り込みの判断**: この節はドキュメントの追いつきのみで、コード変更は無い。

**テスト**: 新設ファイル `tests/test_town_passages.py`（5件）・`tests/test_fixed_shots.py`（11件）・
`tests/test_story_sections.py`（13件）・`tests/test_story_film_section.py`（2件）、既存の
`tests/test_ride_chapters.py`・`test_gemini_selection.py`・`test_gemini_selection_ties.py`・
`test_story_opening.py` にも追補。**全1865件成功**（`__pycache__` 削除後、ffmpeg 結合テスト
（6件）と別層未 commit の `tests/test_story_ambient.py` を除く——後者は `app/story_ambient.py`
とともに未 commit のまま置かれており、いずれそちらの層が仕上げるはず。触れていない）。Ruff
check 成功（`app`・`tests` 全体、未 commit の ambient 系ファイルも含めて）。支出 ¥0。

**次に推奨**: 物語構成の作り直しで残る唯一の単位は **S-4 転換点（主要国道からの分岐）**——まず
GPS だけで「道の性格が変わった点」、次に候補点の逆ジオコーディングで路線名の変化を見る
（`PlaceName.road` は取得済み）。閉じたら12日分の再カット・オーナー再視聴が必要。あるいは
E-1・E-5・E-6・E-7（音・色・タイムラプス）へ進む。`app/story_ambient.py` は別層が仕上げる想定
なので触れないこと。

## 137. 4 回目の視聴の 9 点を反映（2026-09-07、手動 session）

再カット（行程の章・定点・地名）を見たオーナーから 9 点。全て入れて 12 日を再カット中。

- **出発・到着の抜け（2・3）**: `set_off`/`come_to_rest` を走行ペース（1 分 300 m）で読む。day2 の到着は宿での
  徒歩に引きずられ撮影終了の 7 分後になっていた。カメラが出発より遅れて/到着より早く切れた日は、1 時間以内なら
  最初/最後の撮影時点を定点にする（`filmed_moments`、計画と作品で同じ撮影区間を読む）。
- **駐車場（9）**: `parked_in_a_car_park`（road_type と描写文）で選抜の床に。一日の出発・到着の定点は例外。
- **終了カード（6・7）**: 到着の窓が最後の映像、終了カードがその後で作品の最後。本文に行程の全地点を順に
  （重複は 1 回）、その下に距離と時間。休止の少ない日は約 5 章（`TARGET_CHAPTERS`、峠があればそこで）。
- **節（1・4・5・8）**: `app/story_sections.py`。`StoryPlanBeat.section`、`build_section_html`（1/9 の細い帯）、
  `write_section_strips`、`_section_chains`。事象: シーニックルートの出入り（`scenic_events`）、主要道路からの
  離脱（`highway_exits`、参照は OSM の `NZ:SH` 140 relation を `private-media/reference/highways/nz.json` に）、
  町の通過（`town_passages`、町名は中央点の逆ジオコーディング）、長い停止の到着窓に「X で休憩 · N 分」、
  5〜15 分の停止に「X に立ち寄る」。窓への割り当ては最も近い窓（30 秒前〜20 分後）、冒頭窓と章題つき窓は避け、
  同じ文は 30 分に 1 回。行程の始点・終点の町は「通る」と言わない。一日の両端付近の立ち寄り・離脱は言わない。
- **誤検出への備え（1）**: 経路の離脱は 10 分まで許し、停止をまたいで走行 5 km 未満なら同じ区間。主要道路の
  離脱も「10 分以上かつ 5 km 以上走って戻らない」。
- **day6 での確認**: 章 6、節 9（シーニックルートに入る/離れる、SH1 を離れて町へ、海辺に
  立ち寄る 5 分、休憩 53 分…）。テスト 1,871 件緑。

**残**: 12 日の再カット（バックグラウンド）→ オーナー確認。字幕（srt/vtt）とコンソールへの節の反映は未着手。

**§137 の結果（2026-09-07 01:12）**: 12 本を再カット。合計 57 分 47 秒（day1 3:22、day2 5:06、day3 4:44、
day4 4:45、day5 4:56、day6 5:35、day7 4:23、day8 4:24、day9 5:21、day10 5:09、day11 5:32、day12 4:29）。
各日 5〜6 章、節は 3〜9 本。別層の ambient の未 commit 作業は作業木に戻した（import の衝突は解消済み、未 stage）。
費用: Gemini ¥8.3（累計 ≈¥645）、Geocoding は行程の両端に加えて節の地点で 1 日数件。

## 138. クラウド層 `cloud/20260906-1235` の取り込み（`09b760f`、デスクトップ層）

`git fetch dev` で見つけた branch。祖先は §134 直後（`4e5713f`）で、main はその後 S-3・S-4・S-5・S-8
一式が入って大きく先に進んでいた。branch 自身の実質的な差分（祖先からの2 commit）は3点だけ:
`app/private_journey_film.py` の構文修正（`frame_the_film` への `from_to=` 引数と `_leg_names_or_none`
関数の位置ずれ）と `app/place_names.py` の境界テスト28件（`tests/test_place_names.py`）、handoff の
追記。**構文修正は main では既に正しい位置に収まっており（後続の commit で書き直されたか、初めから
無事だった）**、`app/private_journey_film.py` の衝突は HEAD 側をそのまま採用（変更なし）。
`tests/test_place_names.py` は無衝突で追加、テスト・Ruff とも緑なので取り込む。
`git push dev --delete cloud/20260906-1235` で branch を消した。

## 139. クラウド層: `app.unit_economics` の境界・失敗経路のテストを追補（`ab16317`）

`docs/completion-roadmap-ja.md` 7.1（完了済み・安定モジュール）に境界・失敗経路の抜けがあった。
実素材の再カットが day1〜12 で進行中の物語構成まわり（`ride_chapters`・`story_pacing`・
`story_sections`・`town_passages`・`scenic_routes`・`place_names` 等）は当層から見て「直近で
頻繁に変わっている」ため触れず、金額計算のみで完結し地名・座標・ファイル名を一切持たない
`app/unit_economics.py` を選んだ。

追加した境界・失敗経路:
- `PriceTier`: `rides_per_month` が 0 以下、`gross_margin` が負（上限 1.0 だけでなく下限 0.0 も
  境界であることの確認）、`gross_margin=0.0`（許容される下端そのもの）。
- `RideCost`: `ranked_windows` が負のときも拒否されること、判定・順位付けとも 0 本でも保管費用
  だけで `total_jpy` が成立すること。
- `RideCost.fits`: 閾値がちょうど一致する境界（`<=` なので一致は適合、1 円超過は不適合）を
  固定値ではなく `PriceTier.ceiling_jpy_per_ride` から実際に計算して確認。
- `cheapest_fitting_tier`: `TIERS` の宣言順ではなく金額順で選ぶことを、`monkeypatch` で
  `TIERS` を意図的に逆順にしたタプルに差し替えてから検証（宣言順に依存していないことの確認）。
- `current_pipeline`/`ranking_only_pipeline`: 候補数が既定の順位付け本数（40）を下回るときの
  切り詰め、明示的な `ranked_windows` 引数の尊重、1.15 倍の丸め処理を実測。

合成 `PriceTier`/`RideCost` のみ。実 ride・GPX・Gemini 呼び出し・GCS には一切触れていない。

**テスト**: 新設11件（`tests/test_unit_economics.py` 5→16件相当、実ファイルは5関数→16関数）。
**全1882件収集・1876件成功**（ffmpeg 結合テスト6件を deselect。環境に ffmpeg が無いため
——弱めてはいない、既存の環境要因と同じ扱い）。Ruff check・format 成功。支出 ¥0。

**次に推奨**: 物語構成まわりの再カットが一段落したら `app/place_names.py`・`app/town_passages.py`・
`app/scenic_routes.py`・`app/map_background.py`（テスト行数比が低い）の境界補強。あるいは
E-7「コピーからのタイムラプス」（研究 `docs/research-touring-video-editing-ja.md` §7）の
判定ロジック（どの停止・未撮影区間が対象か、3〜5秒のどちらに丸めるか）を `app.story_audio`・
`app.story_color` と同じ「決めるだけで配線しない」形で新設する単位。いずれも次のセッションが
その時点の「着手中」を確認してから選ぶこと。

## 140. クラウド層 `cloud/20260906-1635` の取り込み ＋ E-7 判定ロジック新設（`b414c17`、デスクトップ層）

**取り込み**: `git fetch dev` で見つけた branch（祖先は §139 直後）。実質差分は
`tests/test_unit_economics.py` の境界テスト11件のみ（handoff の追記は §139 として既存の
§138 と番号が競合したため、この commit で §139 に採番し直した）。無衝突でテスト・Ruff
とも緑なので取り込み、`git push dev --delete cloud/20260906-1635` で branch を消した。

**E-7（`app/story_timelapse.py`、新設）**: §137/§139 が推奨した通り、`app.story_audio`・
`app.story_color` と同じ「決めるだけで配線しない」形。長い停止（`MINIMUM_HALT_S`=15分、
`app.ride_chapters.LONG_HALT_S` と同じ値を独自定数として持つ——決定専用モジュールを他の
物語構成モジュールから疎結合に保つため、import はしない）と、未撮影区間で既にカード1枚を
稼ぐ長さ（`MINIMUM_GAP_S`=60秒、`app.journey_gaps.DEFAULT_MINIMUM_GAP_S` と同じ値）を
それぞれ別の閾値で候補に。表示秒数は3〜5秒（研究の指定どおり）で、元の停止・空白が長いほど
上限に近づく線形補間（1時間以上で頭打ち）。`decide_timelapse`（1件）・`decide_timelapses`
（複数件、`None` は「カードのまま」を示す）の2つの入口。1fps縮小コピー（判定用に既存）を
そのまま時間経過の絵として使う想定で、コピーのパス・座標・FFmpeg 処理には一切触れない。

合成の `(kind, duration_s)` のみ。実 ride・GPX・ファイル名には一切触れていない。

**テスト**: 新設 `tests/test_story_timelapse.py`（22件）。**全1927件成功**（1905→1927、
クラウド層のテスト11件を含む）。Ruff check 成功。支出 ¥0。

**次に推奨**: E-7 の配線（小さな picture-in-picture として `app.story_film` に組み込み、
両 ride で 2〜3 箇所レンダーしてオーナー再視聴）。ただし `app/story_ambient.py`（別層の
未 commit の音声レイヤー、`app/story_film.py` の `audio_included` フィールドも同じ WIP の
一部）が同じ `app.story_film` に触れる可能性があるため、そちらの commit を待ってから着手する
方が衝突を避けやすい。先に着手するなら `app/scenic_routes.py`・`app/map_background.py` の
境界補強、または UI（`/private-journey`）側の単位。

## 141. `app/town_passages.py` の境界補強＋語の誤検出の修正（デスクトップ層）

§140 の推奨に従い、書き込み中の音声レイヤー（`app/story_ambient.py`・未 commit の
`app/story_film.py` の `audio_included`）を避け、地名・座標・ファイル名を持たない
`app/town_passages.py` を選んだ。

**見つけた欠陥（修正した）**: `says_town` の語彙が単語境界なしの部分文字列一致だった
——`"city"` が `"electricity"` に、`"town"` が `"hometown"`／`"uptown"` に紛れ込んで
誤って都市部と判定していた。`\b...\b` で単語境界を付け、複数形（`towns`・`cities`・
`streets`・`roundabouts` 等）は明示的に許可して既存の一致を壊さないようにした。

**追加した境界・失敗経路**:
- `says_town`: 部分文字列の誤検出が起きないこと（`electricity`・`hometown`・`uptown`）、
  単語単体・複数形は引き続き一致すること。
- `slow_stretches`: 各閾値（`window_s`・`town_mean_mps`・`stop_mps`・`min_stops`・
  `minimum_s`・`max_gap_s`）がそれぞれの非正の境界で拒否されること、逆に境界そのもの
  （`min_stops=1`・`stop_mps=0.0`・`max_gap_s=0.0`）は受理されること。
- 点が2点未満（0点・1点）は常に空。
- 通過の長さが `minimum_s` にちょうど一致する境界は含まれ、1ステップ超えると除外。
- 二つの町の間隔が `max_gap_s` の境界をまたぐと合流/分離が切り替わること（式で見積もらず、
  実際に `max_gap_s` を掃引して切り替わる値を見つけてから境界の1ステップ両側を確認——
  窓平滑化が町の縁でちらつくため、式による見積りは実測とずれた）。
- `town_passages`: ヒントの時刻が通過の始端・終端ちょうどに乗る境界（含まれる）と、
  1ステップ外側（含まれない）。

合成トラックのみ。実 ride・GPX・ファイル名には一切触れていない。

**テスト**: `tests/test_town_passages.py` 6→17件。**全1939件成功**（この環境には ffmpeg が
入っており結合テストも実行された）。Ruff check 成功。支出 ¥0。

**次に推奨**: 同じ形で `app/scenic_routes.py`・`app/map_background.py` の境界補強。あるいは
`app/story_ambient.py`（別層）の commit を待って E-7 の配線、または UI 側の単位。

## 142. クラウド層: `app.scenic_routes` の境界・失敗経路のテストを追補

§141 の推奨に従い、地名・座標を扱うが実素材には触れない `app/scenic_routes.py`
（テスト行数比が低い方）を選んだ。`app/story_ambient.py` はこの時点でもまだ未 commit
（`app/story_film.py` に存在せず）だったため触れていない。

追加した境界・失敗経路:
- `scenic_stretches` の閾値検査: `on_route_m`・`minimum_s` の非正の境界での拒否
  （従来は `on_route_m=0.0` のみ）、`max_gap_s` は負を拒否しつつ `max_gap_s=0.0`
  （許容される下端そのもの、`< 0` 判定であって `<= 0` ではないこと）を確認。
- `TouringRoute`・`ScenicStretch` の `__post_init__` を直接呼び出し、空白名・
  0本の線・空の線だけの route・終端が始端以下の stretch を拒否することを確認
  （従来は `load_touring_routes` 経由でしか通っていなかった）。
- `load_touring_routes` の壊れた入力: payload が dict でない、route が dict でない、
  `name` が文字列でない、`lines` がリストでない、点が数値の組でない、の5経路。
- `stretch_at`/`stretches_within` の半開区間の境界: 終端の瞬間はその stretch に
  含まれず次のものに属すること、1マイクロ秒だけ内側/外側での切り替わり。
- `_RouteIndex.near` の `<=` 境界（`_distance_m` で実測した距離ちょうどでは真、
  そこから僅かに引くと偽になること）と `_cell` の切り捨て（四捨五入ではない）。
- `MERGE_UNDER_M`（5,000m）の厳密な `<` 境界: 一旦道を外れて閉じた2つの run の間に
  進んだ距離がちょうど閾値なら合流せず2本のまま、1m 下回ると1本に合流すること
  （閉区間を作るための合成 track を新設: 道沿い→大きく外れて`max_gap_s`超え→
  道沿いに戻る、の3区間）。
- 同じ長さの stretch が重なったときに開始が早い方が残ることの確認
  （従来は片方が明確に長い場合のみ検証されていた）。

合成 track・route のみ。実 ride・GPX・参照ファイルには一切触れていない。

**テスト**: `tests/test_scenic_routes.py` 10→20件。**全1949件収集・1943件成功**
（`tests/test_judged_film_end_to_end.py` の6件を deselect。この環境に ffmpeg が
無いため——弱めてはいない、既存の環境要因と同じ扱い）。Ruff check・format 成功。
支出 ¥0。

**次に推奨**: 同じ形で `app/map_background.py` の境界補強。あるいは
`app/story_ambient.py`（別層）の commit を待って E-7 の配線、または UI 側の単位。
いずれも次のセッションがその時点の「着手中」を確認してから選ぶこと。

## 143. `app/map_background.py` の境界補強（デスクトップ層）

§142 の推奨どおり `app/map_background.py` を選んだ。`app/story_film.py` に別層の
未commit差分（`audio_included` フィールド、`app/story_ambient.py` はまだ存在しない）が
あるのは確認したが、触っていない変更として一切さわらず残した。

**追加した境界・失敗経路**（`tests/test_map_background.py` 12→21件）:
- `MapFrame`: 緯度 `±85.0`・経度 `±180.0`・ズーム `0`〜`MAX_ZOOM`（18）が境界そのもの
  では受理され、1e-9 外側で拒否されること。`size_px` は 0・負が拒否、`scale` は 1・2 のみ
  受理（0・3 は拒否）。
- `frame_for` のズーム選択（`max(width, height) <= size_px * ROUTE_FIT_SHARE` が `<=` で
  受理されること）: ズーム8でちょうど閾値ピクセル幅になる経度差を計算して合成した2点で
  ズーム8が選ばれ、そこへ経度を 1e-6° だけ足すとズーム7に落ちることを実測（式の見積もりで
  済ませず、実際に `frame_for` を呼んで確認——`town_passages` の境界補強で得た教訓と同じ
  形）。
- キャッシュ: 0バイトのファイル（クラッシュしたフェッチの残骸）はキャッシュ命中として
  扱われず再フェッチされること。キャッシュディレクトリがシンボリックリンクだと
  `MapBackgroundError`（既存の安全チェックの動作確認）。
- `MapFrame.key`: 同じフレーム・スタイルは同じ鍵、スタイル・ズーム・`size_px`・`scale`
  のいずれかが変わると鍵も変わること。
- `static_map_url`: 既定言語 `ja` と明示的な `language=` の上書き。
- `chosen_style_name`: プロセス環境変数 → `.env` → 既定値の優先順位。環境変数が
  **空文字列で設定されている**場合は「未設定」とは扱われず（`os.environ.get` の仕様上
  `.env` にはフォールバックしない）既定値に落ちることを実測（コードを読んだだけでは
  気づきにくい分岐なので、動作として固定した）。

合成 `RoutePoint`・`MapFrame` と偽のフェッチ関数のみ。実 ride・GPX・実際の Google Maps
キー・ネットワークには一切触れていない。

**テスト**: `tests/test_map_background.py` 12→21件。**全1958件成功**（1949→1958）。
Ruff check 成功。支出 ¥0。

**次に推奨**: 境界補強の対象は一巡した（`unit_economics`・`town_passages`・
`scenic_routes`・`map_background`）。次はいずれかを選ぶ:
(1) `app/story_ambient.py`（別層）の commit を待って E-5・E-7 の配線、
(2) UI（`/private-journey`）側の単位、
(3) 7.2 順位付けだけの経路（単位経済の門、Gate 7.0 を¥100帯へ近づける）。
いずれも次のセッションがその時点の「着手中」を確認してから選ぶこと。

## 144. 7.2 順位付けだけの経路: `app/analysis_tournament.py` 新設（デスクトップ層）

§143 が挙げた3択のうち、`app/story_film.py` の別層 WIP（`audio_included`、`story_ambient.py`
未commit）にまだ触れず、UI の残りは字句の置換のみで小さいことから、単位経済の門を¥100帯へ
近づける **7.2** を選んだ。

**実装**: `app.analysis_run`＋`app.analysis_ranking` の代替として、窓ごとの採点（Gemini 呼び出し
1回・¥0.148/窓）を一切買わず、比較（¥0.056/窓）だけで全窓の順位を決める。10本以内の組を
比較 → 各組の1位（勝者）を代表として次の小さな組へ進め、決着する組まで再帰。最終的な全体順は
「勝者の順」で組を並べ、各組内は組自身の順を保つ——組を跨いだ比較は勝者同士だけなので近似
（弱い組の1位に、強い組の2位以下が実は勝るケースは拾えない。ドキュストリングと専用テストで
この近似の代償を明示）。比較できなかった組（穴のある答えが2回続く）はスコアへ逃げ場がないため
`app.analysis_ranking` と違い「順位なし」にはできず、渡された順（多くは行程順）をそのまま残す。

**コストの再現**: `plan_tournament_cost`（`_tournament_shape` の再帰）で roadmap 7.0 の
「173窓・10本組・決勝込みで≈¥11」を実測ではなく式で再現（193窓分の送信・21回の比較で¥10.89）。
`app.analysis_ranking.plan_ranking_cost` と同じ1秒100トークン換算。

**CLI**: `python -m app.analysis_cli tournament <package> --bucket ... --i-approve-spending`
（`judge`・`rank` と同じ支出の門、Google import は承認確認の後）。`rank_with` の比較器・
`upload_to_bucket` をそのまま再利用。

**残した設計課題（次の単位へ）**: `app.gemini_selection` は `VideoAnalysis`（運転手が画面を
占める・車を停めた場所・道の種別）で選抜のフィルタと同点処理をしている。順位付けだけの経路には
その `VideoAnalysis` が一切無い——比較しか買っていないので、モデルに窓を「見て何か言わせる」
呼び出し自体が無い。順位を選抜へ配線する前に、これらのフィルタを順位専用の経路でどう扱うか
（例: 停止ごとの運転手可視判定だけ安価に別途買う／諦めて7.2は「フィルタ無しの粗い版」と割り切る
／等）を決める必要がある。`app.story_audio`・`app.story_timelapse` と同じ「決めるだけで配線
しない」形にとどめ、決め切らずに次へ渡す。

**テスト**: 新設 `tests/test_analysis_tournament.py`（31件、純粋な再帰の形・近似の代償・
穴のある答えへの耐性・持続化・費用式を実測抜きで検証）、`tests/test_analysis_cli.py` に
`tournament` コマンドの3件を追加。**全1992件成功**（1958→1992）。Ruff check・format 成功。
支出 ¥0（累計変わらず ≈¥645／¥1000）。

**次に推奨**: 上記の設計課題を決めてから選抜（`app.gemini_selection`）への配線、実素材2 ride
（`bridge-e2e-v1`・`day-2-v1`）で「判定+順位付け」版との費用・採用結果を比較して7.2を閉じる。
あるいは (1) `app/story_ambient.py`（別層）の commit 待ち、(2) UI 側の単位。

## 138. day1 の 10 点を反映し day1 のみ再作成（2026-09-07 朝、手動 session。`d096032`・`e934917`）

オーナーは節つきの再カットを day1 だけ確認し 10 点を挙げた（記憶 `owner-day1-feedback-2026-09-07`）。加えて
「具体的な指摘を Gemini へのプロンプトにどう反映するかが重要」。反映の分担:

- **Gemini に聞き直す**: 判定の schema に `stationary`（車両が窓の間ずっと止まっているか）と `road_event`
  （joining_highway / leaving_highway / entering_town / leaving_town / setting_off / pulling_in / none）を追加、
  `rider_visible` の基準に「鏡に映る運転手は large」を明記。旧記録は unknown。`stationary=yes` の窓は通常選抜から外す
  （一日の両端の定点は例外）。`rider_visible=small` でも描写文が運転手を語れば除外（day1 の鏡の窓は large/yes と
  再判定された）。
- **GPS・参照で決める**: 章は 5 分以上の停止で切る（`STOP_MIN_S`。停止が無い日だけ約 5 分割。長さでの分割は廃止）。
  出発・到着は「動き出し」（`ROLLING_MPS`）に置き、出発前・到着後の窓は選抜から外す（`_within_the_ride`）。
  ハイウェイの出入りは定点（`MomentKind.HIGHWAY_ON/OFF`、`app/route_references.py` を計画と作品で共有）＋節の文。
  シーニックルートの端が主要道路の走行区間の途中にあれば参照データの端とみなし、章も文も作らない（`real_scenic`、
  day1 のツーリングルート誤検出）。モデルの語からの「町（街へ）」の性格づけは廃止。
- **構成**: 冒頭は上位 4 窓を 3 秒ずつ（`highlight`、後で本編にも出る）、次に第 1 章の全画面カード。見出しカードは
  廃止、章題は全画面カードに戻す（E-4 の下部テロップ化は章題には使わない）。終了カードは最後、経路の連鎖と一日の
  集計。複数日の旅は全カードに「Day N」（`app/trip_days.py`: 隣の package の GPX 日付が連続していれば旅、
  その中の順番）。節の文は全て現地時刻つき（カメラの時計ずれから推定、`RIDE_LOCAL_UTC_OFFSET` で上書き）。
  出発・到着の窓にも文。
- **day1 の結果**: 3分27秒。4 クリップ → Day 1 の全画面カード（出発地 → 1つ目の休憩地）→「13:51 出発地を出発」
  （動き出しの窓）→「13:54 州道に入る」→ … →「15:23 1つ目の休憩地で休憩 · 10分」→ 章カード →
  → … →「17:15 州道を離れ、到着地へ」（モデルも leaving_highway）→「17:22 到着地に到着」→ 終了カード。
  **章は 3**（オーナーの想定は 2）: 2つ目の 10 分停止も規則上の区切り。1つ目の休憩地からの再出発の定点は
  カメラが撮っておらず入らない。費用: day1 の窓 3 個 ¥0.4。
  （地名は 2026-09-07 に伏せた。実地名は git に置かない規則のため。）
- **他層との同居**: 利用制限の中断中に自律層が commit を重ねていた（town_passages/scenic_routes の境界テスト、
  Gate 7.2 tournament、E-7 timelapse）。ambient の未 commit 作業は他層が stash に退避済み。`story_film.py` の
  6 行（`audio_included`）は作業木に未 stage のまま。
- **テスト**: 1,998 件緑。他の 11 日はまだ再カットしていない（オーナーの確認後）。

## 145. クラウド層: `app.analysis_budget` の境界・失敗経路のテストを追補（`02ba39b`）

（§143 時点でクラウド層が選んだ単位。§144 の 7.2 実装と並行して進んでいたため
番号が前後する——本節はクラウド層のマージ時点でのマージにより 145 番を振った。）

§143 の推奨(1)(2)(3)はいずれも他層の未commit差分待ちか判断を要する単位だったため、
Gate 7 の費用見積もりを担う `app/analysis_budget.py`（金額計算のみで地名・座標・
ファイル名を持たない、テスト行数比 0.77）を選んだ。`app/story_ambient.py` は
この時点でもまだ未commit。narrative構成まわり（`ride_chapters`・`story_pacing`・
`story_sections`・`town_passages`・`scenic_routes`・`place_names`）は直近2日で
頻繁に変わっているため触れず、当層の対象からも除外した。

追加した境界・失敗経路（実行前に手元で挙動を確認してから固定した）:
- `estimate_cascade`: 候補数 `0`（負ではない境界）は全段が候補0・費用0で通ること。
- 生存数の丸め: `round()` が四捨五入ではなく銀行丸め（偶数への丸め）であること
  ——2.5→2、3.5→4——を実測して固定（将来の丸め規則変更を無自覚な副作用にしない）。
- `keep_ratio` がどれだけ小さくても、候補が1件以上残っていれば生存数が0にならない
  こと（`max(1, round(...))` の下限）。
- `AnalysisStage.keep_ratio`: 上端 `1.0` そのものは受理され、1e-9 超過は拒否される
  境界（下端 `1e-9` は従来どおり受理）。
- `output_tokens_per_candidate` が負のときの拒否（従来は入力側のみ検査）。
- `is_free`: 入力・出力の**片方だけ**が0のときは `False`（両方0のときのみ`True`)。
- `video_stage`/`stills_stage`: `0` だけでなく負の秒数・フレーム数も拒否されること。
- `plan_cascade_within_budget` の `minimum_keep_ratio` 自体の境界検査（`0.0`・`1.5`
  はいずれも拒否）——従来は budget・為替レートの境界のみ検査されていた。
- `minimum_keep_ratio=1.0`（それ自体は正当な値）は締め代の余地を残さないため、
  締めが必要な cascade を常に拒否させること。
- 単一段の cascade は「最後の段の keep_ratio は締めない」規則により、予算超過なら
  `minimum_keep_ratio` をどれだけ緩めても絶対に締められず拒否されること
  （締め処理の対象がそもそも存在しない境界）。
- 締め処理が `minimum_keep_ratio` に**ちょうど**クランプされ、そこで停止すること
  （半減後の値が下限を下回る場面を数値で作り、実際に境界へ張り付くことを確認
  ——`map_background`の教訓と同じく式の見積もりで済ませず実行して確認）。
- `CascadePlan` を `estimate_cascade` を経由せず直接 `stages=()` で組んだときも
  `final_candidate_count`・`to_dict()` が例外を出さず0を報告すること。

合成 `AnalysisStage`・`CascadePlan` のみ。実 ride・GPX・Gemini 呼び出しには
一切触れていない。

**テスト**: `tests/test_analysis_budget.py` 21→33件。**全1970件収集・1964件成功**
（`tests/test_judged_film_end_to_end.py` の6件をこの環境に ffmpeg が無いため除外
——弱めてはいない、既存の環境要因と同じ扱い）。Ruff check・format 成功。支出 ¥0。

**次に推奨**: 同じ形の境界補強はここで一巡した4件に続き5件目が閉じた。次はいずれかを選ぶ:
(1) `app/story_ambient.py`（別層）の commit を待って E-5・E-7 の配線、
(2) UI（`/private-journey`）側の単位、
(3) 7.2 順位付けだけの経路の実装（`app/analysis_budget.py` は費用見積もりのみで
実行部を持たないため、`app/analysis_tournament.py` のような新設が必要）——この
(3) は本節と並行してデスクトップ層が §144 で先に着手・実装済み（マージ時点で判明）。
いずれも次のセッションがその時点の「着手中」を確認してから選ぶこと。

## 139. オーナーの回答を受けた実装と、シーン選択の調査（2026-09-07 午前、手動 session。`614ae0d`・`b6bdeec`）

回答: (1) 定点は鏡の運転手・停車中でも可、動く候補を優先。(2) 章は 15 分以上の停止で切り、区切りが少ない日は
5 分停止を格上げ。(3) 上位 40 窓を判定し直す。(4) 予算内で進める。オーナーは約 8 時間不在。

- **定点の候補買い**: 各定点に 10 秒間隔で 3 窓（出発・ハイウェイ出入りは後ろへ、到着は前へ）。
  `choose_shots` がモデルの答え（`road_event` の一致 → `stationary=no` → 近さ）で 1 窓を選ぶ。選抜では
  `required` が運転手・駐車場・停車の床を免除。
- **停止地点の絵**: 5 分以上の各停止に、停止内で最も点の高い窓を 1 本（`_place_shots`）。
- **章**: `segment_ride(stop_minimum_s=15 分, short_stop_s=5 分, minimum_legs=3)`。長い停止での区切りが 3 章未満なら
  短い停止を長い順に格上げ。
- **ハイライト**: `app/highlights.py`。判定に `photogenic_score`（写真として残したいか）と `highlight_subject`
  （vista/mountains/water/cityscape/landmark/winding_road/sky/rest_stop）を追加（`614ae0d`）。無い旧記録は関心度と
  景色の語で代用。被写体を重ねず、20 分以上離し、走行順に 4 本 × 1 秒。運転手・駐車場は除外、`rest_stop` は可。
- **再判定**: `judge --overwrite --refresh-top 40` で各日の上位 40 窓（点数順）を買い直す（新しい質問に答えさせる）。
  day1: 40 再判定 + 新規 47 窓。1 日 8〜10 分かかる（原本からの縮小コピー＋送信）。day2 以降はバックグラウンドで順次。
- **調査**: research §11。GoPro Quik は GPMF の変化点、研究は「物語・重要度・多様性」の同時最適化と「写真らしさ」。
  次に試す順: 画質の門（Gemini に `image_quality`）→ 本編の被写体多様性 → センサー変化点の候補窓 → 章の中の並び。
- テスト 2,026 件緑。

**§139 の続き（2026-09-07 10:00）**: 全 12 日の買い足し完了——各日 40 窓の再判定＋定点の候補窓、合計 806 窓 ≈¥119
（Gemini 累計 ≈¥764）。再カット中に見つけて直したもの: (a) 定点同士が走行時刻で重なるとタイムラインが組めない
（停止の絵が到着の窓の中で始まる、ハイウェイ合流と再出発が 5 秒差）→ `required` 同士も重なりを許さない（`83747b0`）、
さらに pacing で定点をその保持長 8 秒で数える（`dcdea36`）ことで重なりを選抜の段階で防ぐ。(b) 定点が多い日
（day6 は停止 6 か所で定点 24 本）は作品が 7 分に伸びた → 定点の時間を目標尺から先に引き、通常の窓はその残りで
選ぶ。目標尺は 240 秒 → 300 秒（定点込み）。結果の見込み: 停止の多い日 ≈6 分、少ない日 ≈5 分。
(c) ハイライトは作品に出る窓の中から選ぶ（選ばれなかった窓は冒頭に出せない）。写真らしい窓が 4 本に足りない日は
上位の窓で埋める。(d) 一日の出発の候補窓は 5 本（GPS が「動いた」と言ってから 30 秒近く停車していた day1）。

## 146. `app/analysis_cli.py` の境界・失敗経路テスト補強（デスクトップ層、`32741ae`）

§143・§145 と同じ形の境界補強。開始時点で他層の作業（story_film.py の未commit差分
`audio_included`、story_ambient.py 未commit、day-2/10/11-v1 の再レンダー ffmpeg
プロセス 3 本が実行中——`private_journey_film` を day-7〜10 に順次かける手動/headless
session と並走していた）を確認し、レンダー中の package・narrative構成（`ride_chapters`・
`story_pacing`・`story_sections`・`town_passages`・`scenic_routes`・`place_names`・
`fixed_shots`）・story_film.py には触れず、レンダー経路から独立した `app/analysis_cli.py`
（テスト行数比 0.65、CLI ディスパッチのみで narrative を持たない）を選んだ。

追加した境界・失敗経路（`tests/test_analysis_cli.py` 16→34件）:
- `command_rank`: 承認なし・bucket なしの拒否（`judge`・`tournament` には既にあったが
  `rank` には無かった）、`build_parser` の `rank` 引数の往復。
- `command_screen`: 初のテスト（成功経路・`speed_mps` が負の拒否）。
- `main()` のディスパッチ: `plan`・`judge` にしか無かったのを `preflight`・`screen`・
  `rank`・`tournament` にも拡張。
- `command_rank`／`command_tournament` の upload クロージャ（比較器が返した event_id を
  アップロード済みクリップへ戻す部分）を、計画に無い event_id で実際に呼び、
  「a ranked window is not in this package's plan」を実測（`rank_windows`・
  `run_tournament` を偽関数に差し替えて呼ばせる形——Google 到達なし）。`rank` 側は
  `plan_ranking_cost` が既存の判定記録を読むため、判定済み package を作る補助
  （`_judged_package`）を新設。
- `_is_sign_in_failure` の `__cause__`/`__context__` 連鎖を自己参照サイクルで叩き、
  無限ループしないことを確認（`_tournament_order` 系の境界補強で得た「実行して確かめる」
  教訓と同じ形）。

合成 package・GPX・偽の判定記録のみ。Google・実 ride には一切触れていない。

**テスト**: `tests/test_analysis_cli.py` 16→34件。**全2041件成功**（1970→2041、この間に
day1 再カット等の他層 commit を含む）。Ruff check 成功。支出 ¥0（累計変わらず ≈¥764）。

**他層との同居**: day-2/10/11-v1 の再レンダーが実行中だったため、レンダー結果の確認・
判定・順位付けはこの単位では行っていない。次のセッションは `.autonomy/trip/batch.log`
や `ps` で進行中の作業がないか確かめてから選ぶこと。

**次に推奨**: (1) 12日再カットの完了後、オーナー再視聴の依頼（§139 の続き）。
(2) `app/story_ambient.py`（別層）の commit を待って E-5・E-7 の配線。
(3) Gate 7.2 を実素材2 rideで閉じる（`requires_analysis=False` 経路と `judge`+`rank` の
採用・費用差を比較——ただし bridge-e2e-v1・day-2-v1 が他層の作業対象でない時に行うこと）。
(4) UI 側の単位。いずれも次のセッションがその時点の「着手中」を確認してから選ぶこと。

## 147. クラウド層: `app.story_timeline` の境界・失敗経路のテストを追補（`ea27e04`）

（本節はマージ時点で §145 と番号が重複していたクラウド層の単位に 147 番を振り直した
もの。§146 のデスクトップ層の単位と並行して進んでいた。）

境界補強は §139/§141/§142/§143 で `unit_economics`・`town_passages`・`scenic_routes`・
`map_background` を一巡していた。物語構成まわり（`ride_chapters`・`chapter_card`・
`private_journey_film`・`trip_days`・`gap_chapters`）は day1 再作成（§138）を含む再カットが
進行中のため触れず、`app/story_film.py` も別層の未commit差分（`audio_included`）が触れる
可能性があるため避けた。Gate 2 の土台で地名・座標・ファイル名を一切持たず、テスト行数比が
近隣モジュールより低かった `app/story_timeline.py`（171/234）を選んだ。

追加した境界・失敗経路（`tests/test_story_timeline.py` 15→32件）:
- `TimelineFootage`: 開始・終了がちょうど一致する境界（`<=` 判定であって単なる逆転だけでは
  ないことの確認）、`source_offset_s` の負値の拒否と `0.0`（許容される下端そのもの）の受理、
  タイムゾーン無しの `datetime`（開始・終了の両方）の拒否、`duration_s` プロパティ。
- `StoryBeat` を直接構築: `screen_duration_s` が 0 以下、`ride_end_time <= ride_start_time`
  の境界、`FOOTAGE` の種別整合性（event_id 無し、または footage に gap も付いている）の2経路、
  `GAP_CARD` の種別整合性（gap 無し、または gap card に event_id も付いている）の2経路、
  `ride_duration_s` プロパティ。
- `StoryTimeline` を直接構築: 空の beats タプル、時系列が逆順、beat がちょうど接する境界
  （重なり判定が厳密な `<` なので受理される）と1ミリ秒未満だけ重なるケース（拒否される）、
  `build_story_timeline` を経由しない直接構築での event_id 再利用。
- `gap_card_screen_duration_s`: `minimum_s`・`ratio` の負値の拒否、`maximum_s == minimum_s`
  （`<` 判定であって `<=` ではないので、等しい境界そのものは許容される下限であることの確認）、
  線形補間が下限・上限にちょうど乗る滞在時間の値と、その1秒内側/外側での動作。
- `build_story_timeline`: gap との重なりだけでなく footage 同士が重なるケースの拒否、
  `minimum_gap_card_s`・`maximum_gap_card_s`・`gap_card_ratio` を末端まで通した動作確認。

合成 `TimelineFootage`・`JourneyGapSegment`・`JourneyGapPlan` のみ。実 ride・GPX・
Gemini 呼び出しには一切触れていない。

**テスト**: `tests/test_story_timeline.py` 15→32件。**全1943件収集・1934件成功**
（google-adk 等の重量級依存が無いため `test_adk_agent.py`・`test_adk_handoff.py`・
`test_agent_platform.py`・`test_deployable_agent.py`・`test_gemini_probe.py`・
`test_vertex_story_copy.py`・`test_vertex_video_transport.py`・`test_web_server.py` の
収集を `--ignore`——`.[dev]` は重いので試していない、本質はコード欠陥ではなく環境。
ffmpeg が無いため `test_analysis_ranking.py` の3件・`test_judged_film_end_to_end.py` の6件を
deselect——弱めてはいない、既存の環境要因と同じ扱い）。Ruff check・format 成功（自分が
変更した `tests/test_story_timeline.py` のみ format 実行、他の未整形ファイルは触れていない）。
支出 ¥0。

**次に推奨**: 境界補強の対象を広げるなら `app/analysis_budget.py`（171/234相当の低い比率、
2026-09-05 以降変更なし、金額計算のみ）・`app/analysis_cli.py`（テスト行数比0.71、CLI 引数
検証が中心）。物語構成の再カットが一段落したら `app/gap_chapters.py`・`app/trip_days.py`・
`app/chapter_card.py`・`app/private_journey_film.py`（比率が低いが直近で頻繁に変わっている
ため今回は避けた）。`app/story_ambient.py`（別層）の commit を待って E-5・E-7 の配線、
または UI 側の単位も選択肢。いずれも次のセッションがその時点の「着手中」を確認してから
選ぶこと。
## 146. クラウド層: `app.route_references` の境界・失敗経路のテストを新設（`db4794d`）

`app/route_references.py`（`5f7b0e0`・`d096032` で新設・拡張、シーニックルートと
ハイウェイ参照を計画と作品で共有する要）にテストが1件も無かった。直近2日で
narrative構成まわり（`ride_chapters`・`story_pacing`・`story_sections`・
`town_passages`・`scenic_routes`・`place_names`・`highlights`・`fixed_shots`・
`gap_chapters`・`chapter_card`・`footage_candidates`・`rider_in_frame`）は頻繁に
変わっているため§145が触れずにいた領域だが、`route_references.py` 自体は
新設後の後続5 commitで一度も変更されておらず、依存先（`scenic_routes`・
`story_sections`）の関数シグネチャも安定している。純粋関数（合成
`RoutePoint`・`ScenicStretch`・`Moment` のみ、実ファイルは `tmp_path` に書いて
`monkeypatch` で差し替え）でテストが閉じられると判断し、この単位を選んだ。

追加したテスト（実行して固定した境界・失敗経路）:
- `scenic_or_none`/`highway_runs`: 参照が無ければ空、1ファイルが読めなくても
  他のファイルは効くこと、複数ファイルの結果が `reference_files` の返す順に
  関係なく開始時刻順にソートされること。
- `highway_runs`: `plain_route_name` で方角の接尾辞が落ちること
  （"State Highway 1 South" → "State Highway 1"）、`scenic_stretches` の
  モジュール既定（15分）ではなく `highway_runs` 自身が渡す10分の下限が
  効いていること（5分の重なりは捨てられる）。
- `road_moments`: 点が無ければ空、1本のハイウェイ区間は入り1・出1の
  `Moment` になること、離れた2区間はそれぞれ入り・出を持ち、全体が
  時刻順にソートされること。
- `real_scenic`: 区間の両端が全ての参照区間の外にあれば無変化、片端だけ・
  両端が参照区間の内側にあれば除外、`edge_s` の境界ちょうど（保持）と
  1秒超過（除外）、参照区間自体が短すぎて内側が存在しない場合は何も除外
  されないこと、複数の参照区間のうち後方の1つだけに掛かる場合も判定
  されること（先頭だけを見ていないこと）。

実素材・GPX・Gemini・GCS には一切触れていない。

**テスト**: 新設 `tests/test_route_references.py`（0→16件）。環境:
`.venv/bin/pip install -e '.[dev]'` を実施（`google`/`vertexai`/`agentplatform`
の import エラー解消）。**全2,043件収集・2,037件成功**
（`tests/test_judged_film_end_to_end.py` の6件をこの環境に ffmpeg が無いため
`--ignore` で除外——弱めてはいない、既存の環境要因と同じ扱い）。
Ruff check・format 成功（自分が変更したファイルのみ）。支出 ¥0。

**次に推奨**: `app.route_references` のうち `HIGHWAYS_DIRECTORY` 定数と実際の
`private-media/reference/highways` ディレクトリの配線確認は実素材が要るため
対象外のまま。次のクラウド層単位としては、(1) `app/story_ambient.py`
（他層の未commit待ち、状況を再確認）、(2) narrative構成クラスタが直近数時間
落ち着いていれば `app/gap_chapters.py`（テスト行数比が低め）の境界補強、
(3) UI（`app/web/`）側のロジック単位、のいずれか。次のセッションはその時点の
「着手中」を確認してから選ぶこと。

**§139 の結果（2026-09-07 11:52）**: 12 本を最終規則で再カット。合計 68 分 23 秒（day1 3:02、day2 6:26、day3 5:32、
day4 5:44、day5 6:02、day6 6:20、day7 5:54、day8 4:40、day9 6:22、day10 6:03、day11 6:28、day12 5:50）。
各日ハイライト 4 本 × 1 秒、章 3〜6、節 4〜17。day7・8 で出た「窓の重なり」は `_without_overlaps`（`a032a24`）で
切り出しの段でも解消。他層が途中放置していた `dev/cloud/20260907-0036` のマージ（handoff の衝突）を解消して
commit（`3f307f4`）。`app/story_film.py` の 6 行（`audio_included`、他層）は作業木に未 stage のまま。
費用: 今回 806 窓 ≈¥119、Gemini 累計 ≈¥764 / ¥1000。**次**: オーナーの視聴 → research §11 の順（画質の門 →
本編の被写体多様性 → センサー変化点 → 章内の並び）。字幕・コンソールへの節の反映は未着手。

## 148. クラウド層: `app.chapter_order`（E-1、未配線）の境界・失敗経路のテストを追補（`71eb083`）

`docs/current-system-handoff-ja.md` 末尾の「着手中:」を確認したところ生きているものは無し
（直近のものは §132 内で既に解消済み）。実素材の実測が要らない単位として、直近の narrative
構成の頻繁な変更（`ride_chapters`・`story_pacing`・`story_sections`・`town_passages`・
`scenic_routes`・`place_names`・`fixed_shots`・`highlights`・`gps/moments`・`trip_days` 等、
いずれも直近数時間以内に触られている）を避け、E-1（roadmap: 「`chapter_order.py` は未配線」）
の `app/chapter_order.py` を選んだ——1日以上前に実装されたきり動いておらず、他モジュールから
一切 import されていない（未配線のまま、決めるだけで配線しない既存パターンと同じ）純粋な
並べ替え計算のみのモジュール。

追加した境界・失敗経路（実行して確認してから固定。式の見積もりで済ませていない）:

- `motion` の非負境界: `0.0` と `-0.0`（`-0.0 < 0` は Python では `False` なので拒否されない
  こと）がいずれも受理されること。
- `motion` の有限性検査: 既存は `nan` のみ検査していたため、`+inf`・`-inf` も拒否されることを
  個別に追加。
- opener を兼ねる一本だけの chapter（`ChapterWindow(..., opens_chapter=True)` が1本のみ）が
  そのまま自分自身の順序になること。
- opener 無しのジグザグが偶数本（2本・4本）でも、既存の奇数本（5本・9本）のテストと同じ規則
  で端まで振れること。
- 3本が同点のときの実際の順序を実測して固定: `by_motion` は同点なら `window_id` の昇順で
  並び、ジグザグは低い端から取り始めるため、入力順 `b, a, c` は `a, c, b` になること（既存
  テストは「決定的である」ことだけを見ており、実際の値は見ていなかった）。
- id重複とopener複数の両方の欠陥が同時にある入力で、どちらの `ChapterOrderError` が先に
  出るか（コード上は id重複の検査が opener数の検査より先に走るため、"unique" のメッセージが
  出ること）を実測して固定。

合成 `ChapterWindow` のみ。実 ride・GPX・Gemini 呼び出しには一切触れていない。

**テスト**: `tests/test_chapter_order.py` 13→21件。**全2031件成功**（2023→2031、環境要因の
`tests/test_judged_film_end_to_end.py` の6件はこの環境に ffmpeg が無いため除外——弱めては
いない、既存の環境要因と同じ扱い）。Ruff check 成功。Ruff format は変更したファイル
（`tests/test_chapter_order.py`）では成功——`app/story_timelapse.py`・
`tests/test_story_timelapse.py` に既存の未整形（本層が変更していないファイル、他層の
直近コミットに起因、main の時点で既に不整形と確認済み）があるが、当層の対象外として
手を付けていない。支出 ¥0。

**次に推奨**: 同じ形の境界補強を続けるなら、まだ触れていない純粋計算モジュール
（`app/story_hold.py`・`app/lower_third_text.py` 等、ただし直近の narrative 変更との
近さを次のセッションが着手前に確認すること）。あるいは既存の未整形2ファイルを別単位
として ruff format のみ当てる（振る舞いは変えない、リファクタ枠）。いずれも次の
セッションがその時点の「着手中」を確認してから選ぶこと。

## 149. クラウド層の取り込み（`0426fb6`）＋ §139 完了を受けたオーナー再視聴の依頼（デスクトップ層）

開始時にロック取得、`git status` で `app/story_film.py` の未commit差分（`audio_included`、
別層の作業）を確認して触れず、`.autonomy/trip/batch.log` の最終行が5分以内だったため
判定・順位付け・レンダー系の単位は避けた。手動 session の「着手中」も2時間以内には無し。

**取り込み**: `git fetch dev` で `dev/cloud/20260907-0036`（既に main 祖先、`db4794d` の
route_references テストと同一）と `dev/cloud/20260907-0236`（E-1 `chapter_order` の境界・
失敗経路テスト、`71eb083`）を検出。前者は取り込み済みのためスキップ、後者を
`git merge --no-ff` したところ handoff の末尾追記どうしが衝突（両側が §146 を名乗って
いた）。§139 側の系列（12日再カット・§146〜148 の一連）を head に残し、取り込み側の
節を §148 として付け直して両方を保持。pytest 2081件成功（6件 ffmpeg 環境要因で
deselect、既存と同じ扱い）・Ruff check 成功で確定し、`git push dev --delete
cloud/20260907-0236` で branch を消した。

**オーナー再視聴の依頼**: §139 の12日再カット完了（11:52 JST）以降、依頼が未送信のまま
「次に推奨」に残っていたため、見た目が変わる大きい単位として PushNotification を1通
送信（デスクトップ通知、Remote Control 未接続のためモバイル送信は無し）。地名・
ファイル名は含めていない。

**テスト**: 新規追加なし（クラウド層の21件を含めて2081件成功、上と同じ）。Ruff check
成功。支出 ¥0（累計 ≈¥764 / ¥1000 のまま）。

**次に推奨**: オーナーの回答を待って research §11 の順（画質の門 → 本編の被写体多様性 →
センサー変化点 → 章内の並び）に着手。回答が無い間は `app/story_film.py` の
`audio_included`（別層）の commit を待つか、`app/story_hold.py`・`app/lower_third_text.py`
等の境界補強、または UI 側の単位。次のセッションはその時点の「着手中」と
`.autonomy/trip/batch.log`・`ps` の進行中作業を確認してから選ぶこと。

## 150. UI 残作業: コンソールの英語表記を「オーナーの言葉」化に合わせる（デスクトップ層）

開始時にロック取得、`.autonomy/trip/batch.log` の最終行が前日（2026-09-06 12:00）で
5分規則に掛からないことを確認、`git status` で `app/story_film.py` の未commit差分
（`audio_included`、別層の音声レイヤー作業）を確認して触れず。`dev` の `cloud/*` branch は
`dev/cloud/20260907-0036` のみで既に main の祖先——`git push dev --delete` で削除して
片付けた（§149 が取り込み済みと確認しつつ削除を見送っていたもの）。「着手中」は無し。

優先順の S2 追補〜E-7 はすべて完了か他層待ち（E-5・E-7 は `app/story_ambient.py` 未着手
——`ls` で存在しないことを確認、待ちは継続）。次点の **UI** から、roadmap 551行目
「UI の入口」の残り「旧ページの語彙、英語版」を選んだ。第94節 `583996d`
（"Say it in the owner's words"）がコンソール（`_private_journey_console_page`・
`_private_journey_status_page`）の**日本語**だけを package／beat／preflight／bucket の
コード語彙からオーナーの言葉に置き換えており、英語側は手つかずのまま残っていた
（diff を実測して確認: 変更は全て `else` 側の日本語文字列のみ）。

置き換えた8箇所（`app/web/server.py`、辞書のキー名・JS/CSS の内部識別子は変更せず、
表示英文のみ）:
- `unavailable`（両page）: "No private ride package is configured..." →
  "No day has been brought in on this machine yet. Start with \"Bring in a new day\" below."
  （日本語の「別の日のクリップを取り込む」への誘導と対応）
- `beats`: "beats" → "scenes"（日本語「場面」と対応、既存の「chapters」と衝突しない語を選択）
- `bucket_label`: "Bucket to upload to" → "Where to send it (cloud storage location name)"
- `package`（ラベル）: "Package" → "Day being viewed"
- `intake_help`: "...the package is built..." → "...the day is brought in..."
- `name`: "Package name (letters, digits, - _)" → "Name for this day (letters, digits, - _)"
- `create`: "Build the package with this offset" → "Bring in this day with this offset"
- `prepare_the_copies`: "...(local, free): preflight." → "...(on this machine, free)."
  （英語だけに残っていた `preflight` のコード語も落とした）
- `make_the_film`（両page）: "Make the film from this package." → "Make the film for this day."

`_private_journey_status_page` の `unavailable` は「下の『別の日のクリップを取り込む』から」と
言うが、この page 自体には intake への導線が無い（read-only の状態画面）——583996d が
console page からそのまま複写した際の日本語側の既存の不整合で、今回は英語を日本語に
**忠実に対応**させることが目的のため、この不整合自体の是非は次点の課題として残す
（触れると「英語版を揃える」の外の判断が要る）。`_private_highlight_review_page` 等の
開発者向けレビュー page（package・review 等の語が日英とも残る）はオーナー向けコンソールと
別物のため対象外のまま。

実素材・GPX・Gemini 呼び出しには一切触れていない。見た目のテキストのみで構造は
変えていないため、両 ride の再レンダー依頼は不要と判断。

**テスト**: 新規追加なし（既存のコンソール系テストは表示文言を固定していないため、
差し替えても全て通過することを実測で確認）。**全2,046件成功**（環境要因の7ファイルのみ
`--ignore`——`test_web_server.py` は実行してみると重量級 import なしで34件通過したため、
従来の除外対象から外した。ffmpeg はこの環境に実在し `test_judged_film_end_to_end.py` も
deselect せず通過）。Ruff check・format 成功（`app/web/server.py` のみ format 適用、
他の未整形ファイルは触れていない）。`git diff --check` 問題なし。支出 ¥0（累計
≈¥764 / ¥1000 のまま）。

**次に推奨**: `_private_journey_status_page` の `unavailable` 文言の不整合（intake 導線が
無い page が intake を指す）を直すなら別単位で。他は `app/story_ambient.py`（別層）の
commit を待って E-5・E-7 の配線、または `app/story_hold.py`・`app/lower_third_text.py` 等の
境界補強、または 7.2 の残り（`VideoAnalysis` を順位専用経路がどう扱うか決めて2 rideで
比較）。次のセッションはその時点の「着手中」を確認してから選ぶこと。

## 151. クラウド層: `app.video.gpmf_metrics` の境界・失敗経路のテストを追補（`1399a39`）

main を `origin/main`（`748e6c6`、§150 まで）に同期して開始。`git status` は clean、
`app/story_film.py` 等の他層未commit差分は無し。「着手中」を末尾まで確認したが生きて
いるものは無し（§132 のものは既に解消済み）。実素材の実測が要らない単位として、直近の
narrative 構成クラスタ（`ride_chapters`・`story_pacing`・`chapter_card`・`trip_days`・
`gap_chapters`・`private_journey_film` 等、いずれも本日 06:53〜08:43 に触られている）を
避け、GoPro の GPMF（カメラ内蔵IMU・シーン確率メタデータ）を読む純粋関数群
`app/video/gpmf_metrics.py`（2026-09-06 から無変更、テスト行数比0.33で既存5件のみ）を
選んだ。GPS キーを意図的に無視する設計（docstring に明記）で、Gate 2 のプライバシー
不変条件と直接関わる。

追加した境界・失敗経路（実行して確認してから固定。合成 KLV バイト列とスタブ
`runner` のみ、実 GPMF・実動画・GPS には一切触れていない）:

- `parse_gpmf_nodes`: 空/短すぎる入力、null key・非ASCII keyでの打ち切り、
  `structure_size==0`での打ち切り、有効な兄弟ノードの後に来る打ち切られたノードでも
  手前の兄弟は保持されること、コンテナ型（`type_code==0`）のノードだけが子ノードへ
  再帰すること（leaf 型は `children == ()`）。
- `parse_ffprobe_packet_data`: 空文字列、パターンに合わない行の無視、4桁に満たない
  末尾のhex片が例外を出さず黙って捨てられること（実測して固定した既存の挙動）。
- `summarize_gpmf_packet`: 認識できるノードが無ければ `None`、ACCLのみ存在し
  GYRO・SCENが無い場合は`None`になる既存の癖（判断の是非は問わず固定）、負の
  `duration_s`が0にクランプされること、`SCAL`が無い場合は生の復号値がそのまま
  使われること、シーンデータが無い場合`scene_confidence`等が0になること、
  `HUES`からの`hue_weight_mean`計算。
- `summarize_gpmf_window`: 空のsamples、`duration_s==0`の拒否、窓の端にちょうど
  接するだけのサンプルが厳密不等号により除外されること、重複サンプルで
  `coverage_ratio`が1.0にクランプされること、中心サンプル選択が同点のとき
  入力順の先頭を採ること（実測して固定）。
- `analyze_gpmf_metrics`: 存在しない/拡張子不正/symlinkのpath拒否、ffprobe不在・
  タイムアウト・非0終了・不正JSON・非objectペイロードの各異常系、`gpmd`streamが
  無い場合、packetからサンプルが1件も取れない場合、スタブrunnerを2回（streams・
  packets）呼び分けて成功する経路を1件。`tmp_path`にダミーファイルを書き、
  `runner`をmonkeypatchする形（`route_references`の§146と同じ手法）。
- プライバシー不変条件: `GpmfMetricSample`・`GpmfWindowSummary`・`GpmfNode`の
  全フィールド名に位置情報・ファイルパス関連の語が含まれないことを
  `dataclasses.fields`で機械的に検査する1件を追加。

合成バイト列とスタブ `subprocess.run` 差し替えのみ。実 ride・GPX・Gemini・GCS には
一切触れていない。

**テスト**: `tests/test_gpmf_metrics.py` 5→36件。環境: `pytest`・`ruff`のみ
install（`.[dev]`は試していない——`google`/`vertexai`/`agentplatform`のimportエラーが
出る8ファイルを`--ignore`——本質はコード欠陥ではなく環境）。この環境には`ffmpeg`が
無いため`tests/test_analysis_cli.py`の2件・`tests/test_analysis_ranking.py`の3件・
`tests/test_judged_film_end_to_end.py`の6件を`--deselect`（弱めてはいない、既存の
環境要因と同じ扱い。§146以前のこの環境には`ffmpeg`があったと記録されているが、今回の
環境には無かった——環境ごとに変わりうる）。**全2032件成功**。Ruff check 成功。
Ruff format は変更したファイル（`tests/test_gpmf_metrics.py`）で成功——
`app/story_timelapse.py`・`tests/test_analysis_cli.py`・`tests/test_story_timelapse.py`に
既存の未整形（当層が変更していないファイル、§148で確認済みの2ファイルに加え
`test_analysis_cli.py`も今回未整形と判明）があるが、当層の対象外として手を付けて
いない。`git diff --check`問題なし。支出 ¥0。

**次に推奨**: 同じ形の境界補強を続けるなら`app/video/highlight_research.py`
（テスト行数比0.13、ただしファイルパス・ffmpegコマンド構築が多く実素材寄りの
配慮が要る）、`app/story_hold.py`・`app/lower_third_text.py`。既存の3ファイルの
未整形（`app/story_timelapse.py`・`tests/test_analysis_cli.py`・
`tests/test_story_timelapse.py`）をまとめて`ruff format`のみ当てる単位も選択肢
（振る舞いは変えない、リファクタ枠）。または`app/story_ambient.py`（別層）の
commit を待って E-5・E-7 の配線。次のセッションはその時点の「着手中」を
確認してから選ぶこと。

## 152. クラウド層の取り込み（`app.video.gpmf_metrics`）＋ `app.story_hold` の NaN/inf 素通り欠陥を修正（デスクトップ層）

開始時にロック取得、heartbeat、`.autonomy/trip/batch.log`の最終行が前日
（2026-09-06 12:00）で5分規則に掛からないことを確認。`git status`で
`app/story_film.py`の未commit差分（`audio_included`、別層の音声レイヤー作業、
§149〜151から引き続き未stage）を確認して触れず。「着手中」は無し。

**取り込み**: `git fetch dev`で`dev/cloud/20260907-0435`（§151の
`app.video.gpmf_metrics`境界・失敗経路テスト、`1399a39`）を検出。main（§150まで
反映済み）からの差分はhandoffの追記322行のテスト新設のみで衝突なし、
`git merge --no-ff`で取り込み。pytest 2118件成功（2112 +
`test_judged_film_end_to_end.py`の6件——この環境には`ffmpeg`が実在し全件通過、
除外していない）、Ruff check成功で確定し、`git push dev --delete
cloud/20260907-0435`でbranchを消した。

**自分の単位**: 優先順のS2追補〜E-7は完了か他層待ち（`app/story_ambient.py`は
`ls`で未存在を確認、E-5・E-7は引き続き待ち）。直近3時間に触られた
`app/story_pacing.py`・`app/web/server.py`は避け、§148・§150が次点に挙げていた
`app/story_hold.py`（最終変更2026-09-05、narrative構成クラスタから十分離れている）
を選んだ。

既存21件のテストを読み、`hold_from_motion`のガード節を実測して発見した欠陥:
`motion`・`motion_floor`・`motion_ceiling`のいずれも非負しか検査しておらず
（`math.isfinite`を呼んでいない）、Pythonの比較演算はNaN相手だと常に`False`を
返すため`motion < 0`がNaNを弾かない。実測（`.venv/bin/python -c`）で確認:
`hold_from_motion(1, math.nan, motion_floor=0.0, motion_ceiling=8.0)`は例外を
投げず`8.0`（長尺タイアの下端）を静かに返す、`math.inf`は`10.0`（上端）を返す、
`motion_ceiling=math.inf`も例外なく`8.0`を返す——いずれも「値がおかしいと
気付けないまま尺が決まる」経路。同じファイル内の`motion_by_half`は既に
`math.isfinite`でNaN・infを拒否しており、`app.chapter_order`（§148で境界を固定
したE-1のmotionフィールド）も同じ検査を持つ——`hold_from_motion`だけがこの
規約から外れていた非対称。

`hold_from_motion`の3引数すべてに`math.isfinite`検査を追加（`motion`条件は
このモジュールの他の検査と同じ例外文言のまま）。この関数・
`hold_all_from_motion`は`app.story_pacing`からは定数（`LONG_HOLD_RANKS`等）
のみ import されており、モジュール docstring の通り `hold_for`・`footage_for`
へは未配線——今回の修正は実際にレンダリングされている尺には一切影響しない
（配線後に初めて効いてくる安全な先取り修正）。

追加したテスト（`tests/test_story_hold.py`、21→28件のうち7件が新規、
`hold_all_from_motion`に1件追加で計8件）:
- `-0.0`の motion／floor が拒否されずタイアの下端に置かれること（`app.chapter_order`
  と同じ非トラップ）。
- NaN・`+inf`のmotionが`StoryHoldError`で拒否されること（修正前は素通りしていた
  ことを実測してから固定）。
- NaN・`-inf`のfloor、NaN・`+inf`のceilingが同様に拒否されること。
- `hold_all_from_motion`の集合内にNaNが混じっても拒否されること。
- `motion_by_half`の系列内にNaN・infが混じっても拒否されること（既存の検査は
  負値のみテストされていたため追補）。

合成データのみ。実 ride・GPX・Gemini 呼び出しには一切触れていない。見た目が
変わる単位ではないため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_story_hold.py` 21→41件。**全2125件成功**（2118 + 7、
`test_judged_film_end_to_end.py`含む）。Ruff check・format成功（変更した
`app/story_hold.py`・`tests/test_story_hold.py`のみ）。`git diff --check`
問題なし。支出¥0（累計変わらず）。

**次に推奨**: 同じ形の境界補強を続けるなら`app/lower_third_text.py`
（直近変更2026-09-06 20:06、narrative構成クラスタから離れているか次の
セッションが着手前に確認）、または`app/video/highlight_research.py`。
`app/story_hold.py`の`hold_from_motion`/`hold_all_from_motion`自体は
`app.story_pacing`への配線がまだ無い（オーナーが尺の変化を見てから決める枠、
モジュール docstring 通り）——配線するかどうかは別単位の判断。または
`app/story_ambient.py`（別層）のcommitを待ってE-5・E-7。次のセッションは
その時点の「着手中」を確認してから選ぶこと。

## 153. デスクトップ層: `app.video.highlight_research` の境界テストを追補

ロック取得・heartbeat・`.autonomy/trip/batch.log`の最終行（前日 2026-09-06 12:00）を
確認して5分規則に掛からないことを確認。`git status`で`app/story_film.py`の
`audio_included`差分（別層の未commit、§149〜152から引き続き）を確認して触れず。
`git fetch dev`は`cloud/*` branch無し。「着手中」も無し。

§152の推奨2案（`app/lower_third_text.py`・`app/video/highlight_research.py`）から
後者を選択（テスト行数比0.13、2026-09-02から無変更でnarrative構成クラスタから
最も離れている）。§151が指摘した「実素材寄りの配慮」は、ファイルパス・ffmpeg
コマンドを**組み立てるだけ**の純粋関数（`build_frame_extraction_command`・
`build_contact_sheet_command`・`_validate_private_output_directory`・
`_remap_vision_distance`・`_build_diversity_pool`）に絞ることで避けた——実行
（`command_runner`）・実GPMF・実Vision解析には触れていない。

追加した境界・失敗経路（実測して確認してから固定）:

- `build_frame_extraction_command`: `time_s=0.0`（負ではない境界）を許すこと、
  6桁への丸め（`1.23456789`→`"1.234568"`）、`overwrite`が`-y`/`-n`のどちらか
  一方だけを選ぶこと（従来は`overwrite=False`の`-n`側が未検証だった）。
- `build_contact_sheet_command`: `thumbnail_count`が0・負で`ValueError`
  （既存コードにあるが未検証だった防御）、グリッド計算の境界
  （1枚→`1x1`、ちょうど5枚→`5x1`、6枚で次の行→`5x2`）、`overwrite`の
  `-y`/`-n`分岐。
- `_remap_vision_distance`: 重複した`feature_index`を渡すと`ValueError`
  （既存コードの防御だが未検証だった）。
- `_build_diversity_pool`: `per_method`が負のときも`ValueError`
  （0のみ検証済みだった）。
- `_validate_private_output_directory`: リポジトリ外のパスは
  `ValueError`（「ignored private directory」ではなく「must stay inside the
  repository」という別メッセージの分岐、未検証だった）、`private-media`・
  `data/private`・`media/private`の3つの許可ルート全てを受理すること、
  出力先が許可ルートそのもの（サブディレクトリなし）でも受理すること、
  `private-media-decoy`のような紛らわしい名前のディレクトリは拒否すること
  （文字列前方一致ではなくパス部品の完全一致であることの確認）。

合成パス・合成距離関数のみ。実ride・GPX・Gemini・GCS・実ffmpeg実行には
一切触れていない。見た目が変わる単位ではないため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_highlight_research.py` 5→18件。**全2137件成功**
（この環境には`ffmpeg`が実在し、`.[dev]`のimportも全て通ったため`--ignore`・
`--deselect`は不要——§151が記録した環境要因はこの環境には無かった）。
Ruff check・format成功（変更した`app/video/highlight_research.py`は不変更、
`tests/test_highlight_research.py`のみ変更）。`git diff --check`問題なし。
支出¥0（累計変わらず）。

**次に推奨**: 同じ形の境界補強を続けるなら`app/lower_third_text.py`
（直近変更2026-09-06 20:06、narrative構成クラスタとの距離は次のセッションが
着手前に確認）。`app/video/highlight_research.py`自体は`_build_complete_evidence`・
`_extract_research_clips`等、実ffmpeg実行とファイルI/Oを伴う経路が残っており、
境界テストの対象を広げるなら実素材を使わない合成fixture（stub `command_runner`、
`tmp_path`）の設計から要検討。または`app/story_ambient.py`（別層）のcommitを
待ってE-5・E-7の配線。次のセッションはその時点の「着手中」を確認してから選ぶこと。

## 154. クラウド層: `app.lower_third_text`（E-4）の境界・失敗経路のテストを追補

main を `origin/main`（`90eb381`、§153まで）に同期して開始——ローカルの`main`
参照が126コミット遅れていたため`git fetch`で追いつかせてから branch を切った。
`git status`はclean、他層の未commit差分は無し。末尾の「着手中:」を確認したが
生きているものは無し。

§153の推奨（`app/lower_third_text.py`、直近変更2026-09-06 20:06）を選んだ。
その後の3時間の commit（`748e6c6`〜`90eb381`）はnarrative構成クラスタ
（`chapter_order`・`story_hold`・`highlight_research`）にのみ触れており、
このファイル自体は無変更と確認。E-4「題12字・本文21字」の純粋な整形関数で、
実素材の実測が要らない単位。

既存21件のテストを読み、実測して発見した境界（実行して確認してから固定。
合成文字列のみ、実ride・GPX・Gemini・GCSには一切触れていない）:

- `fit_title`: 空白のみの文字列は`strip`後の幅が0のため**例外を投げず`""`を
  返す**——「題には何か言葉が要る」という不変条件は`fit_title`自身ではなく
  `LowerThirdText.__post_init__`側にあることが実測でわかった（既存テストは
  この関数単体の空白入力を検証していなかった）。分数の`max_chars`
  （例: 1.5）でも`_ELLIPSIS_WIDTH`を常に1.0として予約する保守的な計算により
  実際の幅が上限を超えないこと。
- `fit_body`: `max_chars`が0または負のときの拒否——`fit_body`自身に検査は
  無く、1件まで削っても収まらず`fit_title`へ委譲した先でその関数の
  「max_chars must be positive」検査が代わりに効くという、2関数間の
  配線に依存した経路（実測して固定）。1件だけの本文がちょうど上限幅に
  収まる場合は切り詰められないこと。リストに文字列としての`None`
  （既存テスト名`test_body_ignores_blank_and_none_parts`は実は空文字列
  しか渡しておらず、名前が約束する`None`自体は未検証だった）を渡しても
  空白と同様に無視されること。
- `fit_lower_third_text`: 本文の全パートが空白のときは`fit_body`側の
  エラーが`LowerThirdText`に届く前に出ること、題が空白のときは
  `fit_title`側では素通り（`""`を返す）した後に`LowerThirdText`側の
  検査で初めて拒否されること——2つの異なる経路で同じ`LowerThirdTextError`
  に行き着くことを実測して区別。
- `LowerThirdText`: 空文字列の本文だけでなく空白のみの本文も拒否される
  こと（既存は題側の空白のみテスト済みで本文側は空文字列のみだった、
  対称性の穴）。
- `display_width`: 空文字列が0.0、半角カタカナ（`east_asian_width`が
  `H`を返す、既存テストが使う全角カタカナとは別のUnicodeブロック）が
  半角として数えられること。

合成文字列のみ。実ride・GPX・Gemini・GCSには一切触れていない。見た目が
変わる単位ではないため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_lower_third_text.py` 21→33件。**全2062件成功**
（`pytest`・`ruff`のみinstall、`.[dev]`は試していない——`google`/
`vertexai`/`agentplatform`のimportエラーが出る8ファイルを`--ignore`。
この環境には`ffmpeg`が無いため`tests/test_analysis_cli.py`の2件・
`tests/test_analysis_ranking.py`の3件・`tests/test_judged_film_end_to_end.py`
の6件を`--deselect`——弱めてはいない、既存の環境要因と同じ扱い）。
Ruff check成功。Ruff formatは変更したファイル（`tests/test_lower_third_text.py`）
で成功——`app/story_timelapse.py`・`tests/test_analysis_cli.py`・
`tests/test_story_timelapse.py`に既存の未整形（§148・§151で既に記録済み、
当層は変更していないため対象外）が引き続き残っている。`git diff --check`
問題なし。支出¥0。

**次に推奨**: 既存の3ファイルの未整形（`app/story_timelapse.py`・
`tests/test_analysis_cli.py`・`tests/test_story_timelapse.py`）をまとめて
`ruff format`のみ当てる単位（振る舞いは変えない、リファクタ枠、複数節に
渡って推奨され続けている）。同じ形の境界補強を続けるなら
`app/video/highlight_research.py`の残り（`_build_complete_evidence`・
`_extract_research_clips`等、実ffmpeg実行を伴う経路——§153が指摘した
通り合成fixtureの設計から要検討）。または`app/story_ambient.py`
（別層）のcommitを待ってE-5・E-7の配線。次のセッションはその時点の
「着手中」を確認してから選ぶこと。

## 155. デスクトップ層: クラウド層の取り込み（lower_third_text 境界テスト）＋ 3ファイルの ruff format 適用

開始時にロック取得、heartbeat。`.autonomy/trip/batch.log` の最終行は前回の全行程
バッチの最終行（`day12 done` / `batch exit=0`）で、現在時刻から5分規則に掛からない
ことを確認。`git status` で `app/story_film.py` の `audio_included` 差分（別層の
未commit、§149〜154から引き続き）を確認して触れず。末尾の「着手中:」を確認したが
生きているものは無し。

**取り込み**: `git fetch dev` で `dev/cloud/20260907-0636`（§154 の
`app.lower_third_text` 境界・失敗経路テスト、E-4「題12字・本文21字」の純粋な
整形関数、`2401b2a`）を検出。main（§153 まで反映済み）からの差分は
`tests/test_lower_third_text.py`（21→33件）と handoff の追記のみでコード側の
変更は無く衝突なし、`git merge --no-ff` で取り込み。pytest **2148件成功**
（この環境には `ffmpeg` が実在し `.[dev]` の import も全て通ったため
`--ignore`・`--deselect` は不要）、Ruff check 成功で確定し、
`git push dev main` → `git push dev --delete cloud/20260907-0636` で
branch を片付けた。

**自分の単位**: §154 が挙げた次点のうち、「§148・§151で既に記録済みの
未整形3ファイル（`app/story_timelapse.py`・`tests/test_analysis_cli.py`・
`tests/test_story_timelapse.py`）をまとめて `ruff format` のみ当てる単位
（振る舞いは変えない、リファクタ枠）」を選んだ——複数節に渡って推奨され
続けており、他層が触っていないファイルで衝突が無く、実素材の実測が
不要なため。

`ruff format --check` で3ファイルとも整形要と確認してから
`ruff format app/story_timelapse.py tests/test_analysis_cli.py
tests/test_story_timelapse.py` を適用。差分は3ファイルとも改行位置の
折り畳みのみ（`+4/-8`、`git diff --stat` で確認）——`TimelapseDecisionError`
の1行化、`monkeypatch.setattr` の不要な括弧除去、`TimelapseDecision(...)`の
1行化のみで、文字列・値・ロジックの変更は無い。

実素材・GPX・Gemini 呼び出しには一切触れていない。見た目が変わる単位では
ないため両rideの再レンダー依頼は不要。

**テスト**: 新規追加なし（整形のみ）。**全2148件成功**（取り込み後と同数、
変化なし——ロジック不変を裏付ける）。Ruff check・format 成功。
`git diff --check` 問題なし。支出¥0（累計変わらず ≈¥764 / ¥1000）。

**次に推奨**: 未整形ファイルの在庫は解消。同じ形の境界補強を続けるなら
`app/video/highlight_research.py` の残り（`_build_complete_evidence`・
`_extract_research_clips` 等、実ffmpeg実行を伴う経路——§153が指摘した通り
合成fixtureの設計から要検討）。または `app/story_ambient.py`（別層、`ls` で
未存在を確認済み）のcommitを待って E-5・E-7 の配線。次のセッションはその
時点の「着手中」と `.autonomy/trip/batch.log` を確認してから選ぶこと。

## 156. デスクトップ層: `/private-journey-status` の「未取り込み」通知が指す導線の不整合を修正（UI）

開始時にロック取得、heartbeat。`.autonomy/trip/batch.log` の最終行は前回の全行程
バッチ（`day12 done`、2026-09-06 12:00）で5分規則に掛からない。`git fetch dev`は
`main`と`dev/main`が既に一致（`8aa34a3`）で取り込む`cloud/*` branchは無し。
`git status`で`app/story_film.py`の`audio_included`差分（別層の未commit、
§149〜155から引き続き、`app/story_ambient.py`という未committedな音声レイヤーを
指すコメントが追加されていた）を確認して触れず。末尾の「着手中:」を確認したが
生きているものは無し。

roadmapのGate 7単位（S2追補〜E-7）は軒並み完了・配線待ち・別層待ちで、プロンプトの
優先順に沿うと次は「UI」。roadmap 552行目に残っていた既知の不整合
（`_private_journey_status_page`の`unavailable`文言が指す intake 導線がその
pageに無い）を選んだ——実素材・GPX・Gemini に一切触れない自己完結した欠陥修正で、
他層のWIPと衝突しない。

**発見**: `/private-journey-status`（読み取り専用の進行状況ページ）は
`api/private-journey-status`のfetchが失敗したとき「下の『別の日のクリップを
取り込む』から始めてください」と表示するが、そのintake操作（GPX・動画フォルダの
入力欄と提案ボタン）は別ページ`/private-journey`（`_private_journey_console_page`）
にしかない。`_private_journey_status_page`自体にはintakeのHTMLが存在せず、
「下の」という案内は実在しない要素を指していた。

**修正**: 文言を`/private-journey?lang=<言語>`への実リンクに置き換え（`_page`等
既存コードにある`private_director_preview_link`と同じ形の导線）。このLABEL文字列
は元は`textContent`で描画されていたためHTMLリンクを解釈できず、`innerHTML`に
変更。JSONにダンプするLABEL全体に`<`が混入し得るようになったため、
`_private_director_preview_page`が既に使っている`.replace("<", "\\u003c")`を
同様に適用（`</script>`早期終端を避ける防御。バックスラッシュエスケープは
f-string式`{}`の中では使えないため、ダンプ結果を`label_json`という別変数に
先出しして参照）。

実素材・GPX・Gemini呼び出しには一切触れていない。見た目が変わる単位ではあるが
コンソールUIのみ（作品の描画には関わらない）ため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_web_server.py`に
`test_private_journey_status_unavailable_notice_links_to_the_intake_console`を
追加（日英両方でエスケープ済みリンクが埋め込まれること、旧文言「下の」/
「below」が残っていないことを検証）。**全2149件成功**。Ruff check・format成功。
`git diff --check`問題なし。支出¥0（累計変わらず ≈¥764 / ¥1000）。

**次に推奨**: 同じ形の境界補強を続けるなら`app/video/highlight_research.py`の
残り（`_build_complete_evidence`・`_extract_research_clips`、合成fixtureの設計
から要検討）。または`app/story_ambient.py`（別層、依然未commit）のcommitを
待ってE-5・E-7の配線。次のセッションはその時点の「着手中」と
`.autonomy/trip/batch.log`を確認してから選ぶこと。

## 157. クラウド層: `app.gps.parser`（GPXパーサ）の境界・失敗経路のテストを追補

`git fetch origin main`でmainが最新（`9ac0632`、§156まで）と確認してから
branchを切った（フェッチ前のローカル参照は126コミット遅れていたため一度
追いつかせている）。`git status`はclean、他層の未commit差分は無し。末尾の
「着手中:」を確認したが生きているものは無し。`app/story_ambient.py`は
`ls`で未存在を確認済み。

§153・§156の推奨（`app/video/highlight_research.py`の残り、実ffmpeg実行を
伴う経路）は合成fixture設計の検討が要るため今回は見送り、モジュール規模比の
テスト薄い候補を`app/`・`app/video/`・`app/gps/`全体で機械的に洗い出した。
`app/gps/parser.py`（125行）に対し`tests/test_gps_parser.py`が3件・32行しか
無く、GPXタイムスタンプ・緯度経度・標高の境界がほぼ未検証と判明——実素材の
実測が要らない純粋パーサで、直近の変更行程（narrative構成クラスタ・
lower_third_text・highlight_researchの一連）とは無関係なファイルのため
衝突なしと判断。

追加した境界・失敗経路（実際にモジュールへ合成GPX文字列を投げて実測して
から固定。すべて`tests/fixtures/sample_route.xml`と同じ「synthetic route」
系統の合成データ、実ride・GPX・Gemini・GCSには一切触れていない）:

- タイムゾーン無しのタイムスタンプが`ValueError`（"must include a
  timezone"）で拒否されること、`Z`終端は`UTC`として、`+09:00`等の
  オフセットは`UTC`へ正規化されて格納されること。
- `<time>`要素を持たない`trkpt`が`ValueError`（"every GPX track point
  must include time"）で拒否されること（既存テストは空文字列の
  トラック全体の欠落のみ検証済みで、1点だけ`time`が無いケースは未検証
  だった）。
- 連続する2点のタイムスタンプが同一、または逆順のとき、どちらも
  `ValueError`（"strictly increasing"）で拒否されること（`elapsed_s <= 0`
  の等号側・負側の両方を実測して区別）。
- 緯度・経度が範囲外（95°・181°）のとき、`_parse_root`自身ではなく
  `RoutePoint.__post_init__`が委譲する`Location`の検査で拒否されること
  （2モジュールをまたぐ配線に依存した経路であることを実測して固定）。
- 標高の加算は前後2点**双方**に`<ele>`がある区間だけで行われること
  ——中間点にだけ`<ele>`が無い3点構成で、両端の標高差があっても
  gain/lossが0のままであることを確認（既存テストは全点に`<ele>`が
  ある構成のみだった）。
- `xmlns`宣言の無いGPX（名前空間なし）でも`{*}`のワイルドカード要素
  検索で同様に解析できること（既存テストは全て名前空間ありの構成
  だった）。
- 移動量ゼロ（同一座標での2点）が速度0・距離0として素通りし、例外に
  ならないこと。
- 先頭点の`distance_from_start_m`が0.0・`speed_mps`が`None`であること
  （直接の境界としては未検証だった）。
- 非公開ヘルパー`_parse_timestamp`・`_child_text`・`_distance_m`を直接
  呼んで単体検証: naiveな値の拒否、`<ele>`欠落時に`None`を返すこと、
  赤道上の経度1度の大圏距離が既知値（≈111,194.9 m）と一致すること、
  同一点の距離が0.0であること。

合成文字列のみ。実ride・GPX・Gemini・GCSには一切触れていない。見た目が
変わる単位ではないため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_gps_parser.py` 3→19件。**全2159件成功**（`.[dev]`の
installを試したところ`google`/`vertexai`/`agentplatform`のimportも含めて
全て通ったため`--ignore`は不要だった。この環境には`ffmpeg`が無いため
`tests/test_judged_film_end_to_end.py`の6件のみ`--ignore`——既存の環境要因
と同じ扱いで、弱めてはいない）。Ruff check・format成功（`ruff format`で
1回のみ整形適用、文字列クォート統一と長い文字列リテラルの折り畳み、ロジック
変更なし）。`git diff --check`問題なし。支出¥0（累計変わらず）。

**次に推奨**: 同じ形の境界補強を続けるなら`app/gps/turns.py`
（139行、`tests/test_gps_turns.py`120行で比率は`parser.py`ほど薄くないが
未確認）、または`app/video/highlight_research.py`の残り
（`_build_complete_evidence`・`_extract_research_clips`、合成fixtureの設計
から要検討）。または`app/story_ambient.py`（別層、依然未commit）のcommitを
待ってE-5・E-7の配線。次のセッションはその時点の「着手中」と
`.autonomy/trip/batch.log`を確認してから選ぶこと。

## 158. デスクトップ層: クラウド層の取り込み（gps.parser 境界テスト）＋ `app.gps.turns`（Q1）の境界・失敗経路のテストを追補

開始時にロック取得、heartbeat。`.autonomy/trip/batch.log`の最終行は前回の
全行程バッチの最終行（`day12 done`、2026-09-06 12:00）で現在時刻から5分規則に
掛からない。`git status`で`app/story_film.py`の`audio_included`差分（別層の
未commit、§149〜157から引き続き）を確認して触れず。末尾の「着手中:」を
確認したが生きているものは無し。

**取り込み**: `git fetch dev`で`dev/cloud/20260907-0836`（§157の
`app.gps.parser`境界・失敗経路テスト、`tests/test_gps_parser.py` 3→19件、
`ff6893c`）を検出。コード側の変更は無く衝突なし、`git merge --no-ff`で取り込み。
pytest **2165件成功**、Ruff check成功で確定し、`git push dev main` →
`git push dev --delete cloud/20260907-0836`でbranchを片付けた。

**自分の単位**: §157の次点のうち`app/gps/turns.py`（Q1、139行）を選んだ——
`app/video/highlight_research.py`の残りは合成fixture設計の検討が要ること、
`app/story_ambient.py`は依然未存在（`ls`で確認）でE-5・E-7の配線がまだ
できないことから見送り、直近のnarrative構成クラスタとは無関係で他層のWIP
（`story_film.py`）とも衝突しないこのファイルを選んだ。既存8件のテストは
主要な振る舞い（右左折・緩い曲がり・停車中の旋回・停止中のジッター・
2連続の角・題材の再開・しきい値の拒否・集計のみの出力）を押さえていたが、
実際にモジュールへ合成GPX点列を投げて実測し、次の境界・失敗経路が
未検証と判明（すべて合成座標・合成タイムスタンプのみ、実ride・GPX・
Gemini・GCSには一切触れていない）:

- `sharp_turns`の拒否条件`min_degrees <= 0 or span_s <= 0 or min_speed_mps < 0`
  は`min_degrees=0`側しか既存テストが通っておらず、`span_s`・`min_speed_mps`
  側は別条件として未検証だった（3つとも実測して`SharpTurnError`を確認）。
  対称に、`min_speed_mps=0`は拒否**されない**境界（`< 0`のみが拒否）である
  ことも実測して固定。
- 点列が0・1・2点のとき（走査条件`index < count - 2`が一度も真にならない）、
  例外にならず空`tuple`を返すこと。
- `speed_mps=None`の点は`(speed_mps or 0.0)`により0として扱われ、明示的に
  低速な点と同じく走査を止めること（`RoutePoint.speed_mps`はOptionalだが
  この経路は未検証だった）。
- `_bearing`を東西南北4方位で個別に実測（既存テストは角のジオメトリ経由の
  間接検証のみだった）。
- `_turned`のゼロ度またぎ（350→10が+20、10→350が−20）と、**厳密に180度の
  旋回は常に−180.0に落ち、+180.0は決して現れない**こと——`_turned`の
  docstringは「(-180, 180]」と書いていたが実測すると実際の値域は
  **[-180, 180)**で、180度ちょうどの旋回（左右どちらの回転かは360を法として
  区別できない）は−180側に決まる。179.999999からの漸近（179.999999のまま
  変わらず+180には到達しない）で範囲の閉じ方を確認してから、docstringを
  実測値に合わせて修正（ロジック自体は無変更）。
- `SharpTurn.to_dict`の丸め（`duration_s`は小数3桁・`degrees`は小数1桁、
  ちょうど1.5秒・123.456度で実測して固定）と`middle`が範囲内チェックだけ
  でなく厳密な中点（7秒スパンの中点が3.5秒後）であることを直接検証。

合成座標・合成タイムスタンプのみ。実ride・GPX・Gemini・GCSには一切触れて
いない。見た目が変わる単位ではないため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_gps_turns.py` 8→17件。**全2174件成功**（この環境には
`ffmpeg`が実在し`.[dev]`のimportも全て通ったため`--ignore`・`--deselect`は
不要）。Ruff check・format成功（`app/gps/turns.py`のdocstring1箇所と
`tests/test_gps_turns.py`のみ変更）。`git diff --check`問題なし。支出¥0
（累計変わらず ≈¥764 / ¥1000）。

**次に推奨**: 同じ形の境界補強を続けるなら`app/video/highlight_research.py`
の残り（`_build_complete_evidence`・`_extract_research_clips`、合成fixtureの
設計から要検討）。または`app/story_ambient.py`（別層、依然未commit）の
commitを待ってE-5・E-7の配線。次のセッションはその時点の「着手中」と
`.autonomy/trip/batch.log`を確認してから選ぶこと。

## 159. クラウド層: `app.gps.moments`（S-1/S-7 の定点検出）の境界・失敗経路のテストを追補

`git checkout main && git pull origin main`でmainが最新（`75fcd55`、§158まで）
と確認してからbranch `cloud/20260907-1036`を切った。`git status`はclean、
他層の未commit差分は無し。末尾の「着手中:」を確認したが生きているものは
無し。`app/story_ambient.py`は`ls`で依然未存在と確認済み。

§157・§158と同じ形で続けるため`app/gps/`配下を見た。`app/video/
highlight_research.py`の残りは合成fixture設計の検討が要ることから見送りは
変わらず、`app/gps/moments.py`（146行）に対し`tests/test_gps_moments.py`が
6件・105行で、S-1/S-7（定点検出）の主要な振る舞い（出発・帰着・1停止での
4モーメント・停止範囲外の除外・`Moment`の整合性検査）は押さえていたが、
実際にモジュールへ合成`RoutePoint`列を投げて実測し、次の境界・失敗経路が
未検証と判明（すべて合成座標・合成タイムスタンプのみ、実ride・GPX・
Gemini・GCSには一切触れていない）:

- 非公開ヘルパー`_moved`・`_pace`を直接呼んで単体検証: 同一タイムスタンプ
  （`elapsed=0`）でも例外にならず、距離が進んでいれば移動あり・進んで
  いなければ移動なしと判定されること。タイムスタンプが逆順（`elapsed`が
  負）でも`max(elapsed, 0.0)`により0扱いとなり、正の距離差があれば移動
  ありと判定されること（`_pace`はどちらも0.0を返す）。
- `_moved`の徒歩速度しきい値（`WALKING_MPS=1.5 m/s`）はちょうど境界
  （10秒で15m）では移動と判定**されず**、わずかに超えると判定される
  こと（厳格な`>`であることを実測して固定）。
- `set_off`・`come_to_rest`は0点・1点の軌跡で例外にならず`None`を返す
  こと（走査条件が一度も真にならない経路）。
- `SUSTAINED_M`（300m）／`SUSTAINED_S`（60秒）の持続判定境界が**含む**
  （`>=`）側であること——ちょうど60秒で300m進む構成では検出され、
  299mでは（後続に進行が無い限り）`None`のまま検出されないことを
  `set_off`・`come_to_rest`双方で実測。
- 徒歩しきい値は超えるが`SUSTAINED_M`に届かない「偽の出発」（停滞に
  戻る）があっても、走査が次の候補へ進み、後続の本当に持続する出発を
  正しく検出すること（`if`節に`continue`が無くとも forループが自然に
  次の`moved`地点へ進む経路）。
- `set_off`内の「ロールオフ精緻化」ループ（`ROLLING_MPS=2.5 m/s`未満の
  忍び足を読み飛ばす）が、ちょうど`ROLLING_MPS`と等しい歩調の地点で
  停止すること（`<`の厳格性により、超えない忍び足だけを読み飛ばし、
  ちょうどの地点はそこで確定する）。
- `day_moments`が停止（halt）を渡された順序ではなく、実際の時刻順で
  番号付けすること（後の停止を先に渡しても`halt=0`は時刻の早い方に
  付くことを実測）。
- `day_moments`の停止除外条件`start <= began or end >= ended`が、
  停止が完全に範囲外である必要はなく、出発・到着どちらか片方の境界に
  「またがる」だけで十分に除外されること（出発直前〜直後、到着直前〜
  直後の両ケースを別々に実測）。
- `Moment.__post_init__`のタイムゾーン検査が、halt整合性検査とは独立
  した経路であることをメッセージ（"timezone-aware"）付きで単独確認。

合成座標・合成タイムスタンプのみ。実ride・GPX・Gemini・GCSには一切触れて
いない。見た目が変わる単位ではないため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_gps_moments.py` 6→17件。**全2179件成功**（この
環境には`google`/`vertexai`/`agentplatform`のimportに要る`.[dev]`が問題
なく入り`--ignore`は不要だった。`ffmpeg`が無いため
`tests/test_judged_film_end_to_end.py`の6件のみ`--ignore`——既存の環境要因
と同じ扱いで、弱めてはいない）。Ruff check・format成功（`tests/
test_gps_moments.py`のみ変更、`ruff format`の整形適用は無し）。
`git diff --check`問題なし。支出¥0（累計変わらず）。

**次に推奨**: 同じ形の境界補強を続けるなら`app/highlights.py`（153行・
`tests/test_highlights.py`120行）または`app/trip_days.py`（119行・
`tests/test_trip_days.py`93行）——比率が薄い側で未確認。または
`app/video/highlight_research.py`の残り（合成fixture設計から要検討）。
または`app/story_ambient.py`（別層、依然未commit）のcommitを待って
E-5・E-7の配線。次のセッションはその時点の「着手中」と
`.autonomy/trip/batch.log`を確認してから選ぶこと。

## 160. デスクトップ層: クラウド層の取り込み（gps.moments 境界テスト）＋ `app.trip_days`（日番号・現地時刻）の境界・失敗経路のテストを追補

開始時にロック取得、heartbeat。`.autonomy/trip/batch.log`の最終行は前回の
全行程バッチの最終行（`day12 done`、2026-09-06 12:00）で現在時刻から5分規則に
掛からない。`git status`で`app/story_film.py`の`audio_included`差分（別層の
未commit、§149〜159から引き続き）を確認して触れず。末尾の「着手中:」を
確認したが生きているものは無し。

**取り込み**: `git fetch dev`で`dev/cloud/20260907-1036`（§159の
`app.gps.moments`境界・失敗経路テスト、`tests/test_gps_moments.py` 6→17件、
`9daf612`）を検出。コード側の変更は無く衝突なし、`git merge --no-ff`で取り込み。
pytest **2185件成功**、Ruff check成功で確定し、`git push dev main` →
`git push dev --delete cloud/20260907-1036`でbranchを片付けた。

**自分の単位**: §159の次点のうち`app/trip_days.py`（119行、`tests/
test_trip_days.py`93行）を選んだ——`app/highlights.py`と行数・テスト行数の
比率はほぼ同じだったため、内容を読んで判断: `trip_days.py`はファイル
システム境界（存在しないファイル・壊れたJSON・欠けたキー）としきい値
（ゾーン判定の30分・14時間、正規表現の1桁時・符号）の両方を持ち、実測して
固定する境界が`highlights.py`より具体的に多いと判断した。日番号・現地時刻は
オーナーのday1指摘（2026-09-07）で配線されたばかりの経路でもある。
`app/video/highlight_research.py`の残りは合成fixture設計の検討が要ることから
見送りは変わらず、`app/story_ambient.py`は依然未存在（`ls`で確認）で
E-5・E-7の配線がまだできない。

既存4件のテストは主要な振る舞い（カメラ時計からのオフセット・UTC付近は
ゾーンでない・連続する日付でのtrip_day番号付け・GPXなしの日帰り）を
押さえていたが、実際にモジュールへ合成パッケージ（GPX・JSON）を投げて
実測し、次の境界・失敗経路が未検証と判明（すべて合成ファイル・合成
タイムスタンプのみ、実ride・GPX・Gemini・GCSには一切触れていない）:

- ゾーン判定のしきい値`_ZONE_MIN_S`（30分）・`_ZONE_MAX_S`（14時間）が
  **含む**（`<=`）側であること——ちょうど30分・ちょうど14時間はゾーンと
  認められ、1秒でも外れると`None`になることを両端で実測。
- `RIDE_LOCAL_UTC_OFFSET`の正規表現が1桁の時（`-9:00`）・負符号・コロン
  省略（`+1300`）のいずれも同じ値にパースされること、符号なし（`1300`）は
  マッチせず`ValueError`になることを実測して区別。
- カタログファイルが存在しない・JSONが壊れている・`video_to_gps_offset_s`
  キーが欠けている、いずれも例外にならず`local_offset_s`が`None`を返す
  こと（`(OSError, ValueError, KeyError, TypeError)`の握り潰しが実際に
  効いている3経路を個別に確認）。
- 非公開ヘルパー`_first_time`を直接呼んで単体検証: 存在しないファイル・
  `<time>`要素の無いGPX・パース不能な時刻文字列がいずれも`None`を返す
  こと、タイムゾーン無しの時刻は拒否されず`UTC`を補って返すこと。
- `package_date`が`local-pipeline-inputs.json`の欠落・壊れたJSON・
  `gpx_path`キーの欠落のいずれでも`None`を返すこと（`_first_time`とは
  別の握り潰し経路であることを実測して区別）。
- `trip_day`の連続日判定: 4日離れた（連続しない）2パッケージはどちらも
  日帰り（`None`）のままで、互いの存在が誤って走を作らないこと。
- symlinkで繋がる兄弟パッケージは`sibling.is_symlink()`により走の判定から
  除外されること——symlinkの先だけに連続日のパッケージを置き、直接の
  兄弟としては存在しない構成で実測し、除外されている（`None`のまま）
  ことを確認。
- `local-pipeline-inputs.json`を持たない、ただのディレクトリが兄弟に
  あっても例外にならず走査が読み飛ばすこと。

合成ファイル・合成タイムスタンプのみ。実ride・GPX・Gemini・GCSには一切
触れていない。見た目が変わる単位ではないため両rideの再レンダー依頼は
不要。

**テスト**: `tests/test_trip_days.py` 4→12件。**全2193件成功**（この
環境には`ffmpeg`が実在し`.[dev]`のimportも全て通ったため`--ignore`・
`--deselect`は不要）。Ruff check・format成功（`tests/test_trip_days.py`
のみ変更）。`git diff --check`問題なし。支出¥0（累計変わらず ≈¥764 /
¥1000）。

**次に推奨**: 同じ形の境界補強を続けるなら`app/highlights.py`（153行・
`tests/test_highlights.py`120行、未確認のまま残っている）。または
`app/video/highlight_research.py`の残り（合成fixture設計から要検討）。
または`app/story_ambient.py`（別層、依然未commit）のcommitを待って
E-5・E-7の配線。次のセッションはその時点の「着手中」と
`.autonomy/trip/batch.log`を確認してから選ぶこと。

## 161. デスクトップ層: `app.highlights`（冒頭ハイライト選定）の境界・失敗経路のテストを追補

開始時にロック取得、heartbeat。`.autonomy/trip/batch.log`の最終行は前回の
全行程バッチの最終行（`day12 done`、2026-09-06 12:00）で現在時刻から5分規則に
掛からない。`git status`で`app/story_film.py`の差分（別層の未commit、
§149〜160から引き続き）を確認して触れず。末尾の「着手中:」を確認したが
生きているものは無し。`git fetch dev`で`cloud/*` branchは無しと確認。

§160の次点`app/highlights.py`（153行、`tests/test_highlights.py`120行）を
選んだ。既存5件のテストは主要な振る舞い（モデルの`photogenic_score`優先・
語彙からの推定・4枚の被写体重複なし・スプレッド・第2パスでの補充・
運転手/駐車場/退屈な絵の除外）を押さえていたが、実際に合成`JudgedCandidate`
を投げて実測し、次の境界・失敗経路が未検証と判明（すべて合成記述文・
合成スコアのみ、実ride・GPX・Gemini・GCSには一切触れていない）:

- `photogenic`・`subject_of`とも`candidate.analysis is None`の窓は
  `None`・`"none"`を返し例外にならないこと。
- `photogenic_score=0.0`という「本物の0点」の答えが、`is not None`判定
  により語彙由来の推定（この文なら大きなボーナスが付く）へフォール
  スルーせず、そのまま使われること。
- `photogenic`のclamp: 高い`visual_interest_score`＋複数の絶景語で
  `0.75*1.0+0.3=1.05`となる構成が`1.0`に、退屈語＋`visual_interest_score=0`
  で`-0.15`となる構成が`0.0`に、それぞれ実際に収まること。
- `highlight_subject`は`app.contracts.models.HIGHLIGHT_SUBJECT_VALUES`の
  閉じた列挙（`subject_of`自身の語彙と同じ集合）なので、モデルが答えた
  値は矛盾する記述文があっても常にその値が勝つこと（"landmark"の答え＋
  「山の眺め」という記述文で"landmark"が返ることを実測）。
- 語彙推定は複数語が同時に一致する文で、タプルの並び順どおり最初に
  一致した被写体を返すこと（"coastal"と"mountain"が両方ある文で
  "mountains"が勝つ）。
- 一致する語が無い記述文は"none"に落ちること。
- `pick_highlights`: `count=0`は例外にならず空タプルを返すこと
  （`len(chosen) >= count`が0対0で常に真になる経路）。
- `ride_start`・`ride_end`の範囲判定が**含む**（`<=`）側であること——
  ちょうど境界の時刻の窓が実測で採用されること。
- `spread_s=0.0`では近接除外が効かないこと（`abs(diff) < 0`が常に偽）
  ——同時刻の2窓がどちらも採用されることを実測。
- スプレッド判定が厳格な`<`であること——既定の`spread_s`ちょうど離れた
  2窓は「近すぎる」扱いにならず両方採用されることを実測。
- `minimum`（既定0.55）の閾値も同様に**含む**側であること——`score`が
  ちょうど閾値と等しい窓が第1・第2パスで（第3パス待たずに）採用される
  ことを、`scores`引数でタイブレークを0に固定して実測。
- `scores`引数が同点の`photogenic_score`を持つ2窓の順位を実際に入れ替え
  られること。

合成記述文・合成スコアのみ。実ride・GPX・Gemini・GCSには一切触れていない。
見た目が変わる単位ではないため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_highlights.py` 5→17件。**全2205件成功**（この
環境には`ffmpeg`が実在し`.[dev]`のimportも全て通ったため`--ignore`・
`--deselect`は不要）。Ruff check・format成功（`tests/test_highlights.py`
のみ変更）。`git diff --check`問題なし。支出¥0（累計変わらず ≈¥764 /
¥1000）。`cloud/*` branchは無し（取り込みなし）。

**次に推奨**: 同じ形の境界補強を続けるなら`app/video/highlight_research.py`
の残り（合成fixture設計から要検討、§157〜160から見送りが続いている）。
または`app/story_ambient.py`（別層、依然未commit）のcommitを待って
E-5・E-7の配線。他の候補として、境界テストが薄い層（`app/story_sections.py`
・`app/town_passages.py`・`app/highway_exits.py`等、S-8/S-3/S-4を実装した
モジュール群）はまだ実測していない。次のセッションはその時点の
「着手中」と`.autonomy/trip/batch.log`を確認してから選ぶこと。

## 163. デスクトップ層: `dev/cloud/20260907-1235`取り込み＋`app.rider_in_frame`の`parked_in_a_car_park`境界テスト

開始時にロック取得、heartbeat。`.autonomy/trip/batch.log`の最終行は
前回の全行程バッチのまま（現在時刻から5分規則に掛からない）。末尾の
「着手中」は生きているものなし。

**共有ワークツリーの状態**: 開始直後の`git status`は`app/analysis_record.py`
・`app/contracts/models.py`・`app/fixed_shots.py`・`app/gap_chapters.py`・
`app/gemini_selection.py`・`app/gps/moments.py`・`app/highlights.py`・
`app/place_names.py`・`app/ride_chapters.py`・`app/route_references.py`・
`app/story_film.py`・`app/story_sections.py`・`app/video/gemini_client.py`・
`app/video/vertex_transport.py`・`tests/test_gemini_selection.py`（すべて
未commit差分）と未追跡`app/ferries.py`・`app/places.py`・
`app/reference_fetch.py`・`app/stop_kinds.py`を確認。作業中に
`app/route_references.py`が新たに差分を持ち、`app/place_shots.py`が
新たに出現し、さらに後で`app/private_journey_film.py`・
`app/story_pacing.py`にも差分が生じるのを確認した——**別層（手動session
と思われる、`.autonomy`のlockを介さない）がこのworktreeで今まさに
ferry/place/stop-kind関連の大きな機能を書いている最中**。いずれの
ファイルも触れず、`git add`もしていない。加えて`git stash list`に
自分が作っていない`wip: other layer ambient (not mine) - pre cloud merge`
が1件残っている（§149〜161から引き継がれた形跡）ことを確認したが、
自分のものではないため触れていない。

**取り込み**: `git fetch dev`で`dev/cloud/20260907-1235`（クラウド層の
`app.gps.events`境界・失敗経路テスト、`tests/test_events.py`のみ変更、
`7b5055a`+handoff）を検出。`git merge --no-ff`はこの共有worktreeの
未commit差分と無関係なファイルのみを触るため衝突なくmerge成功。
検証は[[shared-worktree-partial-staging]]の手順どおり——`git stash
push -u`で他層の未commit差分を丸ごと退避しHEAD単体で
`pytest`・`ruff check`を実測（**2228件成功**・Ruff成功）してから
`git stash pop`で他層のWIPを寸分違わず復元。`git push dev main`→
`git push dev --delete cloud/20260907-1235`で片付けた。

**自分の単位**: 上記の理由でロードマップ優先順（S2/Q1/E-3/E-4/Q5/E-1/
E-2/E-5/E-6は完了、E-7は`app/story_ambient.py`の別層commit待ちで着手
不可、7.2の残り決定は`app/gemini_selection.py`自体が編集中で着手不可）
の主要単位はすべて今動いているファイル群に触れる必要があり選べなかった。
§159〜161と同じ形の境界テスト補強に戻り、まだ触れられていないモジュール
から`app/rider_in_frame.py`（S-6実装、82行）を選定。既存4テストは
`rider_fills_the_frame`（モデル回答優先・語彙フォールバック・不正な
`rider_visible`値の拒否）を押さえていたが、**同モジュールの
`parked_in_a_car_park`（S-9系「駐車場の窓を除く」判定、オーナー
2026-09-06指摘9番）にテストが1件も無い**ことを実測で発見。

追補したのは（すべて合成`VideoAnalysis`のみ、実ride・GPX・Gemini・GCS
には一切触れていない）:
- オーナー規則が名指す語句すべて（`car park`／`carpark`／大文字小文字
  無視／`parking lot`・`area`・`garage`・`space`・`bay`／`forecourt`／
  `driveway`／ハイフン付き`parking-lot`）が実際に一致すること。
- 関数名とは裏腹に**「駐車されている（parked）」という状態語自体は
  正規表現に含まれておらず**、"The motorcycle is parked on the side of
  the road"のような文は一致しないこと（駐車場という**場所**の描写だけを
  拾う設計であることを実測で区別）。
- 「national park」「amusement park」のような`park`を含む無関係な語や、
  区切りの無い`parkinglot`は一致しないこと（`parking-lot`はハイフン
  ありのみ拾う分岐が別に要ることを実測）。
- `road_type`フィールド単独でも一致すること（`f"{road_type}
  {visual_description}"`の連結探索を実測で確認）。

**テスト**: `tests/test_rider_in_frame.py` 4→11件（parametrize込みで
30ケース）。他層WIPを`git stash`で退避した状態で**全2245件成功**、
Ruff check・format成功（`tests/test_rider_in_frame.py`のみ変更）。
`git diff --check`問題なし。見た目が変わる単位ではないため両rideの
再レンダー依頼は不要。

**commit**:
- `a0932ca` `dev/cloud/20260907-1235`のmerge
- `7d2e868` `app.rider_in_frame`の`parked_in_a_car_park`境界テスト
- `git push dev main`（private ミラー）完了。公開originには触れていません。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし。別層が編集中の19ファイル（上記）と`stash@{0}`の
`wip: other layer ambient`は今回も未着手のまま残しています。

**次に推奨**: 別層の大きなWIP（ferries/places/stop_kinds/reference_fetch
と既存モジュールへの配線）がcommitされ次第、ロードマップ優先順
（E-7の配線、7.2の`VideoAnalysis`扱いの決定）に戻るのが筋。それまでは
境界テストの薄いモジュール（`app/town_passages.py`・`app/story_opening.py`
・`app/story_titles.py`等）を1つずつ拾うのが安全。次のセッションは
その時点の「着手中」と`.autonomy/trip/batch.log`、および共有worktreeの
`git status`（新たに動いているファイルが増えていないか）を確認してから
選ぶこと。

## 162. クラウド層: `app.gps.events`（GPSイベント抽出・統合）の境界・失敗経路のテストを追補

`git checkout main && git pull origin main`でmainが最新（`2a6e66c`、§161まで）
と確認してからbranch `cloud/20260907-1235`を切った。`git status`はclean、
他層の未commit差分は無し。末尾の「着手中:」を確認したが生きているものは
無し。`git fetch`で他の`cloud/*`branchは無しと確認。

§157〜161と同じ形で続けるため、テスト行数比率が薄い側（`ratio`計算）を
一通り見た上で`app/gps/events.py`（239行、`tests/test_events.py`
既存93行・6件）を選んだ——`app/gps/parser.py`・`turns.py`・`moments.py`と
同じ`app/gps/`配下の残り最後のモジュールで、実素材の実測が要らない純粋な
GPS計算のみ。既存6件のテストは主要な振る舞い（departure/arrival/
elevation_changeの抽出・stop/long_rideしきい値の設定可能性・近接する
volatile eventの統合・単独eventの保持・window境界での新クラスタ化・
volatile種別間の非統合）を押さえていたが、実際にモジュールへ合成
`RoutePoint`・`GpsEvent`を投げて実測し、次の境界・失敗経路が未検証と
判明（すべて合成座標・合成タイムスタンプのみ、実ride・GPX・Gemini・GCSには
一切触れていない）:

- `stop_speed_mps`（既定1.0、`<=`）・`stop_min_duration_s`（既定60.0、
  `>=`）の両しきい値が**含む**側であること——ちょうど速度1.0・経過60秒の
  構成でstopが検出され、速度がわずかに超える、または経過がわずかに
  足りないと検出されないことをそれぞれ実測。
- `elevation_change_m`（既定25.0、`>=`）の境界がちょうど25mの上昇・下降
  どちらでも検出され、24.999mでは検出されないこと。前後どちらかの
  `elevation_m`が`None`の窓は例外にならずelevation_changeを生成しない
  ことを両方向（前がNone・後がNone）で実測。
- `speed_change_mps`（既定5.0、`>=`）の境界がちょうど5.0 m/sの差で検出
  され、4.999では検出されないこと。`previous.speed_mps`が`None`のとき
  `speed_delta`が強制的に0.0になり、`current.speed_mps`がどれだけ大きく
  てもspeed_changeが発生しないことを実測して固定。
- `direction_change`が`index >= 2`を要求するため、2点だけの経路では
  どれだけ急な仮想的な方向転換でも一度もbearing差が計算されないこと。
  実際の約90度の転回（北進→東進）では検出され、直線（3点が同一方位）
  では検出されないことを実測。
- 非公開ヘルパー`_direction_delta`を直接呼んで単体検証: ちょうど60度
  でしきい値に達し、59.999度では届かないこと。0/360度の継ぎ目を跨ぐ
  bearing差（10→350度、0→300度、0→180度）が最短方向で正しく計算される
  こと。
- `long_ride_min_duration_s`（既定900.0、`>=`）の境界がちょうど900秒で
  検出され、899.999秒では検出されないこと。
- 1点だけの経路で`extract_events`を呼んでも、`range(1, 1)`が一度も回らず
  例外にならないこと——生成されるのはdeparture・arrival_candidateの
  2件のみであることを実測。
- `consolidate_events(())`が空tupleをそのまま返し例外にならないこと。
- `EventConsolidationPolicy.__post_init__`が`volatile_event_window_s`の
  0・負の両方を`ValueError`で拒否し、ごく小さい正の値（0.001）は受理
  すること。
- 非公開ヘルパー`_representative`の最終タイブレーク: `importance_hint`・
  `start_time`が完全に同点の2件で、`event_id`の辞書順が小さい方が
  代表として選ばれること。
- `stable`（`volatile_event_types`に含まれない）event種別、例として
  "stop"は、時刻的に隣接していても`consolidate_events`で統合されない
  こと——volatile種別との非対称性を明示的に確認。

合成座標・合成タイムスタンプのみ。実ride・GPX・Gemini・GCSには一切触れて
いない。見た目が変わる単位ではないため両rideの再レンダー依頼は不要。

**テスト**: `tests/test_events.py` 6→29件。**全2222件成功**（この
環境には`google`/`vertexai`/`agentplatform`のimportに要る`.[dev]`が
問題なく入り`--ignore`は不要だった。`ffmpeg`が無いため
`tests/test_judged_film_end_to_end.py`の6件のみ`--ignore`——既存の
環境要因と同じ扱いで、弱めてはいない）。Ruff check・format成功
（`tests/test_events.py`のみ変更）。`git diff --check`問題なし。

**次に推奨**: これで`app/gps/`配下（parser・turns・moments・events）の
境界テスト補強は一巡した。続けるなら`app/video/highlight_research.py`の
残り（合成fixture設計から要検討、§157から見送りが続いている）。または
`app/story_ambient.py`（別層、依然未commit）のcommitを待ってE-5・E-7の
配線。他の候補として、比率が薄い側にある`app/video/highlight_discovery.py`
（964行・test 337行、比率0.35——ただしGemini/Vertex呼び出しを含む可能性が
高く合成fixture設計の検討が要る）や`app/chapter_card.py`（424行・test 233行、
比率0.55）はまだ実測していない。次のセッションはその時点の「着手中」と
`.autonomy/trip/batch.log`を確認してから選ぶこと。

## 164. デスクトップ層: `app.chapter_card`の境界・失敗経路のテストを追補

lock取得後、`git status`で別層（§163が記述した手動session、`.autonomy`の
lockを介さない）の大きなWIPを確認したところ、途中で`3a243c0`
（"Read the map and the picture: places, roads, passes, ferries, stop
kinds"）としてcommitされたのを確認した——別層は今も稼働中で、
`app/story_film.py`の差分と`tests/test_ferries.py`・`tests/test_place_shots.py`・
`tests/test_places.py`・`tests/test_reference_fetch.py`・`tests/test_stop_kinds.py`
の未追跡ファイルが新たに現れている。末尾の「着手中:」は生きているものが
無く、`.autonomy/trip/batch.log`の最終行は前日（9/6 12:00）で5分以内では
ない。`git fetch dev`に`cloud/*`branchは無し。

ロードマップ優先順の主要単位はいずれも別層が今動かしているファイル群に
触れる必要があり選べなかったため、§163が候補に挙げていた
`app/chapter_card.py`（424行、境界テスト前は`tests/test_chapter_card.py`
233行・比率0.55、別層の差分に一切含まれない）を選定。実測で次が未検証と
判明（すべて合成`RoutePoint`・合成`GapChapterCard`のみ、実ride・GPX・
Gemini・GCSには一切触れていない）:

- ラベル無しの`GapChapterCard`（既定`label=None`）を渡すと`<div
  class="label">`が一切出力されないこと。
- `build_lower_third_html`もタイトル・本文どちらか欠けると
  `build_chapter_card_html`と同じ`ChapterCardError`で拒否されること
  （既存テストは`build_chapter_card_html`側のみを押さえていた）。
- `route_map_svg`を渡さない`build_lower_third_html`には`<svg`が一切
  含まれないこと。
- 間引きのしきい値`_MAX_MAP_POINTS`（400）がちょうど400点では間引かれず
  そのまま描かれ、401点で間引きが発動すること。
- 5000点まで間引かれた経路でも`mark_index`（末尾点）が間引き後の配列の
  末尾点と同じ座標に落ちること——`_placed_index`の比例写像が間引き後も
  正しいことを実測。
- `mark_radius`を既定の9以外（25）に指定すると、描かれる`<circle>`の
  `r`属性がその値になること。
- `highlight_from_index == highlight_to_index`（1点だけの強調）でも
  最低2点の線として描かれること（`end - start < 1`のとき`end`を1つ
  広げる分岐を実測）。

**テスト**: `tests/test_chapter_card.py` 22→30件。別層のWIP
（`app/story_film.py`の差分と`tests/test_ferries.py`等5ファイル）を
[[shared-worktree-partial-staging]]の手順どおり`git stash push -u`で
対象ファイルのみ退避しHEAD単体で実測——**全2248件成功**（144秒、
`tests/test_judged_film_end_to_end.py`はffmpeg不在の既存事由で
`--ignore`）。Ruff check・format成功（`tests/test_chapter_card.py`・
`app/chapter_card.py`のみ対象）。`git stash pop`で他層のWIPを寸分違わず
復元してから`tests/test_chapter_card.py`のみを`git add`。`git diff
--check`問題なし。見た目が変わる単位ではないため両rideの再レンダー依頼は
不要。

**commit**: `app.chapter_card`の境界テスト追補（このhandoff更新を含む）。
`git push dev main`予定（private ミラー）。公開originには触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし。別層が編集中の`app/story_film.py`と未追跡5ファイルは
今回も未着手のまま残している。

**次に推奨**: 別層のWIP（ferries/places/stop_kinds/reference_fetchの
配線が`app/story_film.py`にまだ及んでいる）がcommitされ次第、ロードマップ
優先順（E-7の配線、7.2の`VideoAnalysis`扱いの決定）に戻るのが筋。それまでは
`app/video/highlight_discovery.py`・`app/video/highlight_research.py`
（比率0.35・0.32だが合成fixture設計の検討が要る）や、まだ実測していない
`app/video/apple_vision.py`（比率0.55）を拾うのが次の候補。次のセッションは
その時点の「着手中」・`.autonomy/trip/batch.log`・共有worktreeの
`git status`を確認してから選ぶこと。

## 165. オーナー第6回視聴（14点）— 地図・立ち寄り地・フェリーを読む＋提出準備

開始時に hub ロック取得、`.autonomy/lock` 取得、heartbeat。共有worktreeには
別層の `app/story_film.py`（ambient、§149〜160から継続）が未commitで残って
おり触れていない。作業中に別層が一度 `git stash push -u` で当層の差分を退避
したが、直後に pop され全て戻った（[[shared-worktree-partial-staging]] の
教訓どおり、hunk分割はしていないので破損なし）。

**指摘14点の要旨**: day1の最後をホテルのレセプションに / day2の有名道路名を
下部テロップに / day2の博物館は館内でなくバイクの絵が良かった / day2の
シーニックルート（幹線から分岐する側道）を認識できていない / day2の給油かつ
主要都市入りに下部テロップが無い / 駐車場排除の指示を「個人宅を特定できる
駐車場の排除」に訂正（ホテル発着映像を入れたい） / day3の立ち寄り地テロップ
が市名では広すぎる / day3の博物館に下部テロップが無い / day3のフェリー乗船は
重要イベントなので下部テロップを / day3のフェリー下船シーンが無い /
day4の休憩地の絵が駐車場排除で消えた / day5冒頭のデッキ静止画は選ぶべきで
ない、直後の川の絵が良い / day5の運転手が大きい絵 / day7の久しぶりの街の名前
/ day10の主要都市名が出ない / 昼食・観光の立ち寄りは給油・トイレの小休止と
分けて扱う。

**設計判断**: これらはほぼ全て「作品が世界を知らない」ことが原因だった。
トラックと映像は読めるが、そこが町なのか、峠なのか、フェリーなのか、そして
停止が何のための停止だったのかを知らない。そこで次を足した。

- `app/reference_fetch.py`（新）: OpenStreetMap から Overpass 経由で国単位に
  参照ファイルを1度だけ取得する。送るのは国コードと種別だけ。町（city/town/
  village 636件）・峠（88件）・フェリー航路（85件）・名前付き道路（9件）。
  形式は `places-v1`・`landmarks-v1`・`touring-routes-v1`。git には入れない。
- `app/places.py`（新）: 町は「走行が遅くなったか」ではなく「その町の半径内を
  通ったか」で判定する（city 3.5km / town 1.5km / village 700m）。環状道路で
  通過する市は減速しないし、村は一本道なので、旧来の判定は両方とも取り
  こぼしていた。峠は300m以内の最接近時刻。
- `app/ferries.py`（新）: 航路線・トラックの速度中央値と距離・**カメラの証言**の
  三点が揃ったときだけ渡船とする。入江沿いの道が航路線を1時間半なぞる例と、
  「Ferry Terminal」の標識がある町の目抜き通りの例が実際にあり、地図と
  トラックだけでは分離できなかった。船上ではGPSが空を失い100m/sの値を返すので
  速度は中央値で見る。乗船待ちの停止は渡船の一部として章に含め、そこまでの
  道路は含めない。渡船中の距離は当日の走行距離から差し引く。
- `app/stop_kinds.py`（新）: 停止が何だったかをモデルの答え（新設の
  `place_kind`・`place_name`）と、それ以前の判定では記述文の語から読む。
  給油・食事（昼の時間帯なら昼食）・展望・見学・買い物・宿・フェリー・個人宅。
  「屋内か」「個人宅を特定しうるか」も同じ読み方なのでここに置いた。
- `app/place_shots.py`（新）: 各停止の「場所の絵」を選ぶ。屋外＞屋内、その
  停止の種類に合う絵＞合わない絵、モデルが「運転手なし」と答えた窓＞聞かれて
  いない窓、停車/進入中＞前方の道。フェリーだけは例外で、乗船の瞬間を採る。
  一日の両端では宿の絵（レセプション等）を採る。
- `app/route_references.py`: 名前付き道路の走行区間を、地図が持つ場合は地図
  から、持たない場合は Geocoding の道路名を3分ごとに標本して読む。実際に
  有名な道路の一つは OSM に way 名として無く、Geocoding からしか取れなかった。
  フェリー下船の定点（`MomentKind.FERRY_OFF`）もここ。
- `app/ride_chapters.py`: 渡船は独立した章（`GapCharacter.FERRY`）。同じ市内で
  始まり終わる区間の題は、より細かい名前（suburb / spot）を使う。
- `app/story_sections.py`: 節の種類を追加（町へ入る・道路名・峠・乗船・下船・
  場所名）。停止の文は種類ごとに変わる。町の文は5分以内の窓にしか載せない
  （8分後の窓に「〜を通る」と出すと別の場所で言うことになる）。
- `app/highlights.py`: 動いている絵を先に採り、静止画は最後の一巡でだけ、
  かつ眺め・山・水・街・立ち寄り地の絵に限る。屋内と個人宅は除外。
- `app/gemini_selection.py`: 駐車場の門を**個人宅の門**に置き換えた。定点でも
  個人宅は通さない。
- `app/contracts/models.py`・判定プロンプト: `place_kind`・`place_name` を追加。

**実測（12日分の計画のみ、レンダー前）**: day2で有名道路と側道のシーニック
ルートの両方を検出、主要都市入りと給油の2文が出た。day3で渡船が1章になり、
乗船・下船の文と絵が入り、立ち寄り地は市名でなく細かい名前になった。day1の
最後に宿のレセプションの絵が入った。day7・day10の町名が出た。誤検出だった
2日分の渡船（入江沿いの道・町の目抜き通り）はカメラの証言を必須にして消えた。

**テスト**: 2,328件成功（新規73件＋既存4件を訂正後の規則に書き換え）。Ruff
check・format 成功。`git diff --check` 問題なし。支出¥0（Gemini累計 ≈¥764 /
¥1000 のまま。Geocoding は Maps 無料枠内、キャッシュ済みで再実行は0件）。

**提出準備（同じセッション）**: `docs/submission/project-writeup-en.md`・
`README.md`・`devpost-submission.md`・`docs/submission/judging-alignment.md`・
`docs/submission/technical-evidence.md`・`docs/submission/demo-script-en.md`
を現状（12本・4,039窓・≈¥764・2,328テスト）に書き直した。デモ動画の字幕は
`app.submission.demo_assembly` のタイムラインから生成するようにしたので、
字幕とキャプションがずれない。`.autonomy/day2-crf20.mp4`（1.3GB、別セッション
の試写）を `private-media/scratch-renders/` へ移し、`python -m app.submission`
のローカル6項目が全て通るようになった。

**次に必要（オーナーの操作が要るもの）**: 公開リポジトリの作成と可視化、
デモ動画の顔・ナンバープレート確認と公開、ホスト版の公開、Devpost への送信。
これらは明示承認が要るため当層では行わない。

## 166. クラウド層 `cloud/20260907-1435` 取り込み: E-2 の計算部分——順位と動きの量から尺を決める（`2681623`）

デスクトップ層が `git fetch dev` で見つけ取り込んだ。番号がローカルの§98と衝突していた
（クラウド層は分岐した古い base から数えて独自に「98」を付けていた）ため、ここで
現行の続き番号に付け直す。branch の内容そのものは純計算のみで、他ファイルには一切
触れていない。

自律ループ第3層による実行。roadmap の E-2「窓の尺を順位×画面内の変化量（1fps フレーム差）で
3〜10 秒に。12 秒のどの 6 秒を使うかも動きで選ぶ」のうち、**実素材の実測が要らない計算部分だけ**を実装した。

- `app/story_motion_pacing.py`: `duration_from_motion(motion, rank=...)` は順位のスコア（1位=1.0〜
  下限0.2、`worst_rank_considered` 以降は下限で頭打ち）と動きのスコア（`WindowLook.motion` と同じ基準値
  64 で正規化、0〜1）を**均等に**混ぜて 3〜10 秒に写す。`best_span(motion_by_second, span_s)` は
  秒ごとの動きの系列から、指定の長さでいちばん動きが多い連続区間を返す（同点は最も早い区間、
  系列より長い指定は全体を返す）
- 動きの**測定**（proxy から秒ごとの frame difference を取る部分。`analysis_look.py` は今は窓 1 本に
  つき平均 1 個しか持たない）には触れていない。selection・`story_pacing.hold_for` への配線もしていない——
  今回は roadmap の単位が言う「計算」だけを、合成 fixture のテストで固定した
- 全 20 件のテストは合成の順位・動きの数値のみ（座標・時刻・ファイル名は無い）

取り込み時にデスクトップ層でテスト・Ruffを再実行して確認（下の節を参照）。

**次に推奨する単位**: `analysis_look.py` に秒ごとの motion 系列を測る経路を足して
`duration_from_motion`/`best_span` を配線する（実素材での検証が要るので、この単位はローカル層向け）。

## 167. 取り込み中の衝突: 共有worktreeで別プロセスがマージの途中経過をcommitした

デスクトップ層。開始時lock取得、heartbeat。`git status`は`app/story_film.py`の
未commit差分のみ（別層のambient WIP、§165から継続、既知）で他の未追跡ファイルは
無し。`.autonomy/trip/batch.log`の最終行は9/6で5分以内ではない。末尾の
「着手中:」も生きているものが無かったため、`git fetch dev`で見つけた
`cloud/20260907-1435`（前節166、`app/story_motion_pacing.py`のみを純追加する
2commit）の取り込みに着手した。

**起きたこと**: 別層のambient WIPを`git stash push -u`で退避してから`git merge
--no-ff`したところ、`docs/current-system-handoff-ja.md`の同じ節番号「98」を
両側が使っていたための衝突のみが起きた（cloud側のbaseがmainの248 commit
手前で分岐していたため、追加された他のファイルは一切触れておらず衝突しなかった）。
衝突マーカーを解決している最中に、**同じ共有worktreeで別プロセスがcommitを
実行し**、まだ2つ目の編集を当てる前の中間状態（衝突マーカーの後半`=======`・
`>>>>>>> dev/cloud/20260907-1435`がファイルに残ったまま）のindexをそのまま
拾って`1b60c59`（"Say that some windows were bought twice"、author
`TKMT-ish`、devpost-submission.md等の無関係な差分も同居）としてcommitして
しまった——`MERGE_HEAD`はこのcommitで消費され、マージ自体はここで完了扱いに
なった。オーナー本人が同じ端末で並行して手作業をしていたとみられる（同種の
「別層WIPを退避してからマージする」手順を示すstash（`stash@{1}`、"wip: other
layer ambient (not mine) - pre cloud merge"、`app/private_journey_film.py`の
ambient配線）が残っており、このセッションが作ったものではない）。

**対応**: 破壊的なgit操作（reset・force push）はせず前進で直した。作業ツリー上の
編集は既に両方とも終わっていたので、`1b60c59`との差分を取ると「§98衝突マーカーの
残り」だけがきれいに残っており、それを`f03eeda`として通常commitした。マージの
親2つ（`4327a29`・`425291f`）は`1b60c59`に記録済みなのでやり直し不要。テストと
Ruffは`1b60c59`直後の状態と`f03eeda`の両方で実行——**2,345件成功**
（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由）、
Ruff check成功、`git diff --check`問題なし。取り込んだ別層のambient WIP
（`app/story_film.py`）は`git stash pop`で寸分違わず復元し、このセッションが
作った方のstashだけを消した（[[shared-worktree-partial-staging]]どおり、
関わっていない`stash@{1}`には触れていない）。

**commit**: `f03eeda`（マージ自体は`1b60c59`が既に完了）。`git push dev main`
・`git push dev --delete cloud/20260907-1435`済み。公開originには触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし。ただし**オーナーへの一言**: 直前のご自身のcommit
`1b60c59`が、このループのマージ解決の中間状態を巻き込んで衝突マーカーの
残骸ごと記録されていた（`f03eeda`で修正済み、内容は正しい状態になっている）。
同じworktreeでの並行手作業とデスクトップ層のマージ作業が重なるとこの種の
競合が起きるので、大きな手作業（`git add -A`・`git commit -a`等ファイル
指定なしの操作）をする前は`.autonomy/lock`の有無を見ていただけると安全。

**次に推奨**: 別層のambient WIP（`app/story_film.py`、`stash@{1}`の
`app/private_journey_film.py`ambient配線）がcommitされ次第、ロードマップ
優先順に戻る。それまでは§164が挙げた`app.video.highlight_discovery`・
`app.video.highlight_research`・`app.video.apple_vision`が次の候補。

## 168. デスクトップ層: ロードマップ優先順の確認（E-2は配線済みと判明）＋ `app.video.apple_vision` の境界・失敗経路のテストを追補

lock取得後heartbeat。`git status`は`app/story_film.py`の未commit差分のみ（§165以降
継続する別層のambient WIP、既知）、`.autonomy/trip/batch.log`の最終行は9/6で
5分以内ではない。末尾の「着手中:」は生きているものが無い。`git fetch dev`に
`cloud/*` branchは無し。

ロードマップ優先順（S2追補→Q1→E-3→E-4→Q5→E-1→E-2→E-5→E-6→E-7）を上から
確認したところ、**E-2はすでに配線済み**と判明した: `app/story_hold.py`
（rank別tierの範囲＋動きで尺を決める`hold_all_from_motion`、窓内のどちらの
半分を切るかの`choose_half_by_motion`）が`app/story_pacing.py`の
`footage_for`・`select_by_chapter`（`motion_aware`引数）に配線済みで、
`app/private_journey_film.py`（実製品の描画経路）が`looks_for(...,
need_series=True)`で秒ごとのmotion系列を取得して渡している。ロードマップの
該当節（Gate 7・E-2）はこの配線完了を書き落としていたので追記した。

一方、cloud層が§166で追加した`app/story_motion_pacing.py`
（`duration_from_motion`・`best_span`）はどこからも呼ばれておらず、上記の
既存配線と同じ問題（rank×motionで尺を決める）を独立に再実装したものだと
分かった。動く実装ではなく計算だけの重複なので害はないが、次に触る人は
`story_hold.py`が正である方だと分かるようにしておく。

E-1は「時刻順を守り並べ替えない」という判断で完了扱い、E-5（音のつなぎ・
風切り音の減衰）は`app/story_audio.py`と`app/story_film.py`の音声レンダー
経路に触れる必要があり、別層が今まさに音声（ambient）を配線中の
`app/story_film.py`と重なるため今回は避けた。E-6・E-7（配線待ち）も同様に
`app/story_film.py`待ち。UI・7.2以降も大きな変更は同じ理由で避け、§164の
推奨どおり`app.video.apple_vision`（227行・既存テスト124行・比率0.55だが
`build_apple_vision_probe`・`analyze_images_with_apple_vision`本体・
`_validate_private_or_temporary_path`が丸ごと未検証だった）を選んだ。

追補した境界・失敗経路（すべて合成fixture、実素材・実行ファイルなし。
`runner`はテスト内のモック関数）:

- `parse_apple_vision_output`: 不正なJSON・未対応schema・件数不一致・
  distanceの添字が昇順でない・distanceが負、の5つの拒否経路。
- `build_apple_vision_probe`: ソースが`.m`でない／存在しない、出力先が
  private-media等でも`/tmp`系でもない場合の拒否、コンパイル成功
  （`runner`が出力ファイルを書く）の受理、コンパイラの非0終了・出力
  ファイル未生成・`FileNotFoundError`・`TimeoutExpired`の4つの失敗経路。
- `analyze_images_with_apple_vision`: 画像0件・probeが存在しない／symlink・
  画像が非対応拡張子／symlink、の拒否、`runner`の非0終了・
  `FileNotFoundError`の失敗経路。
- `analyze_images_with_apple_vision_in_batches`: `batch_size<=0`の拒否。

**テスト**: `tests/test_apple_vision.py` 6→27件。追補分のみを`git stash push
--keep-index -- app/story_film.py`で別層WIPを退避して実測——**2,366件成功**
（121秒、`--ignore=tests/test_judged_film_end_to_end.py`はffmpeg不在の
既存事由）。Ruff check成功（`app`・`tests/test_apple_vision.py`）。`git
stash pop`で別層WIPを寸分違わず復元（[[shared-worktree-partial-staging]]
どおり、関わっていない`stash@{1}`には触れていない）。`git diff --check`
問題なし。見た目が変わる単位ではないため両rideの再レンダー依頼は不要。

**commit**: `app.video.apple_vision`の境界テスト追補（このhandoff更新を
含む）。`git push dev main`（private ミラー）。公開originには触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし。

**次に推奨**: 別層のambient WIP（`app/story_film.py`、`stash@{1}`の
`app/private_journey_film.py`ambient配線）がcommitされ次第、E-5・E-6配線・
E-7配線に戻るのが筋。それまでは§164が挙げた`app.video.highlight_discovery`・
`app.video.highlight_research`（比率0.35・0.32、合成fixture設計の検討が
要る）が次の候補。次のセッションはその時点の「着手中」・
`.autonomy/trip/batch.log`・共有worktreeの`git status`を確認してから選ぶこと。

### §165 の結果（2026-09-08 01:42、全 12 本を再カット＋採譜まで完了）

`a73b87f` のコードで 12 本を一本ずつ切り、同じ実行で音楽まで付けた（`--music rising-tide`）。
合計 **71 分 19 秒**（3分16秒〜6分38秒）、各日 章 3〜6 / 節 9〜22 / 冒頭ハイライト 4。

| 日 | 尺 | 章 / 節 |
|---|---|---|
| day1 | 3分16秒 | 3 / 9 |
| day2 | 6分58秒 | 6 / 20 |
| day3 | 5分37秒 | 6 / 9 |
| day4 | 6分04秒 | 4 / 14 |
| day5 | 6分26秒 | 6 / 22 |
| day6 | 6分28秒 | 6 / 20 |
| day7 | 6分20秒 | 3 / 13 |
| day8 | 4分46秒 | 3 / 10 |
| day9 | 6分33秒 | 4 / 13 |
| day10 | 6分10秒 | 4 / 14 |
| day11 | 6分38秒 | 5 / 19 |
| day12 | 5分57秒 | 3 / 13 |

前回（68分23秒）より 3 分ほど長い。停止の絵・宿の絵・ハイライトが固定枠に加わったぶん。

**確認した点（オーナーの 14 点に対して）**: 名前付き道路の節が出る / 主要都市に入る節が出る /
博物館は館内でなくバイクの絵 / 渡船が 1 章になり乗船・下船の節と絵が入る / 立ち寄り地は市名でなく
細かい名前 / 一日の最後に宿のレセプションの絵 / 峠に標高つきの節 / 給油と昼食が別の文になる。
**残った粗**: 低い峠が続く日は峠の節が 3 本並ぶ（day10）。看板から拾う名前に稀に店名の断片が混じる。

**デモ動画**: `private-media/work/day-4-v1/demo/demo-en.mp4`（177.02 秒、`--excerpt-start-s 30`）。
冒頭が開けた田園と海沿いの登りで、抽出したフレームには判読できるナンバープレートも顔も無い。
**公開前に 5 本の映像を通しで見ること**（抽出は確認ではない）。字幕は同じタイムラインから生成。

**バッチが一度落ちた**: 23:00 に始めた最初の一括は day3 の後で消えていた（原因は特定できていない。
`pkill -f` を別用途で 2 回使っており、それが巻き込んだ可能性がある）。以後 `pkill -f` は使わず、
一括は `nohup` で流し直した。**教訓**: 長時間の一括の最中に `pkill -f` を使わない。

## 169. クラウド層: `app.video.highlight_discovery` の純計算ヘルパーに境界・失敗経路のテストを追補

自律開発ループ第3層による実行。新規セッションのため`.autonomy/trip/batch.log`・
共有worktreeの状態は当層の対象外（実素材に触れないためロックの対象外）。
末尾の「着手中:」を確認したが生きているものは無かった。

§168が次の候補として挙げた`app.video.highlight_discovery`・
`app.video.highlight_research`のうち、後者は`run_local_highlight_research`の
本体がGPMF・Apple Vision・ffmpegサブプロセスを何段も跨ぐ大きな合成fixtureを
要求するため、前者の**純計算ヘルパー**に絞った。`analyze_local_highlight_windows`
が内部で使う次のprivate関数は、既存テスト（12件）のどこからも直接検証されて
いなかった: `_normalize`・`_blend`・`_exposure_quality`・`_recording_key`・
`_std`・`_distance_m`・`_bearing_degrees`・`_direction_delta`・`_percentile`・
`_passes_common_interest_gate`・`_validate_private_output_directory`・
`_gps_features`。

追補した境界・失敗経路（すべて合成の座標・距離・角度の数値。実素材・実ファイル
なし）:

- `_gps_features`: 選択点2未満／有効速度サンプル2未満で`None`を返す2つの拒否
  経路、標高サンプルが2未満のときの既定値0.0（1つ以上あっても2未満なら計算し
  ない）、真北→真東への90度転回を与えたときの`heading_change_degrees`の一致。
- `_distance_m`・`_bearing_degrees`・`_direction_delta`: 赤道での緯度1度の
  既知距離（≈111,195m）、同一点で距離0、真北・真東の方位、コンパスの0/360度
  をまたぐ差分（350°→10°は20°、350°と10°の順序を入れ替えても対称）。
- `_validate_private_output_directory`（`highlight_discovery`側の実装。
  `highlight_research`側の同名関数とは非対称——こちらはリポジトリ外のパスを
  素通りさせ、リポジトリ内でのみprivate root以外を拒否する）: 3つの経路
  （素通り・拒否・許容）を直接検証。
- `_normalize`・`_blend`・`_exposure_quality`・`_percentile`・`_recording_key`・
  `_std`・`_passes_common_interest_gate`: 空入力・全同値・不正な重み（長さ不一致・
  総和が非正）・fraction範囲外・GoProの2文字接頭辞の有無・大文字小文字・境界値
  それぞれ1本ずつ。

**テスト**: `tests/test_highlight_discovery.py` 12→51件。**環境**:
`.venv/bin/pip install -q -e '.[dev]'`（`google-adk`・`google-cloud-aiplatform`・
`google-genai`）が今回は成功したため、収集エラーは出なかった。**全2,405件成功**
（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由。この
コンテナにはffmpegが入っていない）。Ruff check・format済み。`git diff --check`
問題なし。見た目が変わる単位ではないため再レンダー依頼は不要。

**commit**: `e74be40`（`tests/test_highlight_discovery.py`のみ）。
`git push -u origin HEAD`（branch `cloud/20260907-1635`、private ミラー）。
main へは直接push していない。公開origin・実素材・Gemini・GCSには一切触れて
いない。

**支出**: ¥0（変わらず）。

**承認待ち**: なし。

**次に推奨**: `app.video.highlight_research`本体の合成fixture設計（GPMF・
Apple Vision・ffmpegの各段をモックした`run_local_highlight_research`の
成功/失敗経路）。次点は`_build_complete_evidence`・`_extract_research_clips`・
`_build_contact_sheet`など、まだ直接検証されていない同ファイルの内部関数。

## 170. デスクトップ層: `cloud/20260907-1635` の取り込み（`app.video.highlight_discovery` 境界テスト）＋ `app.video.highlight_research` の残り純計算・書き出しヘルパーにテストを追補

lock取得後heartbeat。`git status`は`app/story_film.py`の未commit差分のみ（別層のambient
WIP、既知・継続中）で他の未追跡ファイルは無し。`.autonomy/trip/batch.log`の最終行は9/6で
5分以内ではない。末尾の「着手中:」も生きているものが無かった。

`git fetch dev`で`cloud/20260907-1635`（§169、`app.video.highlight_discovery`の純計算
ヘルパーへの境界テスト追補、2commit）を見つけ取り込みに着手した。`docs/current-system-handoff-ja.md`
の同じ節番号を両側が使っていたための衝突のみが発生（cloud側が追加した`tests/test_highlight_discovery.py`
自体には衝突なし）。§165の結果ノートの直後にcloud側の§169をそのまま続けて置く形で解決。
**全2,405件成功**（`--ignore=tests/test_judged_film_end_to_end.py`）・Ruff check成功・
`git diff --check`問題なしを確認してから`6486e49`としてマージ commit、`git push dev main`・
`git push dev --delete cloud/20260907-1635`済み。

続けて、§169が次点に挙げた`app.video.highlight_research`（比率0.32）を見た。本体
`run_local_highlight_research`・`_build_complete_evidence`・`_extract_research_clips`は
GPMF・Apple Vision・ffmpegサブプロセスを何段も跨ぐ大きな合成fixtureが要るため見送り、
それ以外でまだ直接検証されていなかった3つに絞った:

- `_build_diversity_pool`の**選択ロジック本体**（既存テストは`per_method<=0`の拒否のみで、
  実際に「各手法ごとに上位を取り、feature_indexで重複排除・昇順に返す」動作は未検証だった）:
  4手法それぞれで別の窓が1位になるfixtureで`per_method=1`が4件を昇順で返すこと、
  1つの窓が全手法で1位を独占するfixtureで重複排除により1件になることの2本。
- `_write_private_research_state`（JSON書き出し。純粋関数だが未検証だった）:
  schema_version・privacy・counts（可変長kwargs）・method別のevaluation/selectionsの
  ネスト構造をJSON往復で確認する1本。
- `_build_contact_sheet`（`command_runner`をモックした合成fixture。実ffmpeg・実素材なし）:
  空thumbnailsの拒否、runnerが出力ファイルを書く場合の受理、runnerの非0終了、
  runnerが0を返したのに出力ファイルが無い場合の拒否、の4本。

fixtureは`tests/test_highlight_quality.py`の`_window`/`_gpmf`/`_evidence`と同じ形を
`tests/test_highlight_research.py`側にも複製し（`ScoredHighlightWindow`を直接組み立てる
`_scored`を追加）、スコア計算そのもの（`score_highlight_evidence`）は経由していない。

**テスト**: `tests/test_highlight_research.py` 12→25件。`.venv/bin/python -m ruff format`
で1ファイルを整形（88桁超の関数定義・呼び出し2箇所）。**全2,412件成功**
（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由）。Ruff check
成功。`git diff --check`問題なし。見た目が変わる単位ではないため両rideの再レンダー依頼は
不要。別層のambient WIP（`app/story_film.py`）には触れていない。

**commit**: `app.video.highlight_research`の境界テスト追補（このhandoff更新を含む）。
`git push dev main`（private ミラー）。公開originには触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし。

**次に推奨**: 別層のambient WIP（`app/story_film.py`）がcommitされ次第、E-5・E-6配線・
E-7配線に戻るのが筋。それまでは`app.video.highlight_research`の`_build_complete_evidence`・
`_extract_research_clips`（合成fixture設計が要る、GPMF・Apple Vision・ffmpegの各段を
モック）が次の候補。次のセッションはその時点の「着手中」・`.autonomy/trip/batch.log`・
共有worktreeの`git status`を確認してから選ぶこと。

## 171. デスクトップ層: Gate 7.2 の実測は ADC 再認証待ちでブロック → `app.video.highlight_research` の残り2関数にテスト追補

lock取得後heartbeat。`.autonomy/trip/batch.log`の最終行は9/6のままで5分規則に掛からない。
末尾の「着手中」も生きているものなし。`git status`は`app/story_film.py`の未commit差分
（別層のambient WIP、既知・継続中）のみ、`git stash list`の`wip: other layer ambient`も
継続して残存——いずれも触れていない。

**Gate 7.2の残り**（実素材2 rideで`tournament`と既存judge+rank結果を費用・選抜で比較して
閉じる）に着手した。`plan_tournament_cost`で両packageの見積りを確認
（bridge-e2e-v1 187窓・22比較・¥11.73、day-2-v1 753窓・85比較・¥47.11、合計¥58.84。
累計¥764/1000に対し余裕あり、新種の外部コストでもないため実行して良いと判断）。
`gcloud auth list`・`gcloud config get-value project`は生きているが、
`python -m app.analysis_cli tournament ...`は**「Google will not accept this
machine's sign-in; run `gcloud auth application-default login`」で拒否**——
Application Default Credentialsの再認証が要る対話操作で、過去のhandoff（第61節
「認証は依然ブロック中」）と同じ理由で**代行してはならない**。実行はゼロ回、
支出は発生していない。着手中の印を外し、Gate 7.2は次にADCが再認証された
session まで引き続き保留とする。

代わりに、優先単位（S/Q/E は完了または`app/story_ambient.py`待ちでブロック、
UIは次の単位なし、7.2はADC待ち）がどれも動かせないため、前2節（§169・§170）から
続く境界テスト追補に戻った。§170が次点に挙げていた`app.video.highlight_research`の
`_build_complete_evidence`・`_extract_research_clips`（本体、GPMF・Apple Vision・
ffmpegの各段をモックした合成fixtureが要る）に着手。

設計した合成fixture（すべて偽の座標・バイト列。実ride・GPX・Gemini・GCSには
一切触れていない）:

- `_build_complete_evidence`: `PrivateMetricCache`に**先に**偽の`analyze_gpmf_metrics`
  結果を書き込んでおくことで、本体が呼ぶ本物の`analyze_gpmf_metrics`を一度も
  呼ばせずキャッシュ命中させる（`load_or_analyze_gpmf_metrics`はcache miss時のみ
  analyzerを呼ぶ設計を利用）。`command_runner`は`command[0]`で3種の呼び出し
  （`ffmpeg`のフレーム抽出／`xcrun`のVisionプローブ・コンパイル／プローブ自身の
  パスでのVision解析、JSON出力`ride-apple-vision-v1`スキーマを返す）を判別する
  1つの偽関数にまとめた。
- 追補した経路: 2資産・2窓の正常系（`feature_index`が窓ごとに連番、中心フレーム
  パスが`(asset_id, start_offset_s)`で引ける）、GPMF証跡が1つも無い拒否、
  `coverage_ratio`が0.75未満で除外される拒否（12秒窓に1秒分のGPMFのみ）、
  proxyが無い拒否、フレーム抽出コマンドが失敗する拒否、Visionプローブの
  コンパイルが失敗し`AppleVisionError`が`HighlightResearchError`へ包まれる拒否。
- `_extract_research_clips`: 正常系（1本抽出・サムネイル1枚）、**同じ窓が2つの
  手法から選ばれたときハードリンクで済ませ2回目のエンコードをしないこと**
  （`command_runner`の呼び出し回数を数えて確認——inode一致でも検証）、
  ソース欠落・エンコード失敗・中心フレーム欠落の3つの拒否。

**テスト**: `tests/test_highlight_research.py` 25→36件。**全2,423件成功**
（`--ignore=tests/test_judged_film_end_to_end.py`）。Ruff check・format成功
（fixtureのdict内包表記1箇所をformatが整形）。`git diff --check`問題なし。
見た目が変わる単位ではないため両rideの再レンダー依頼は不要。別層のambient WIP
（`app/story_film.py`・stash）には触れていない。

**commit**: このhandoff更新と`tests/test_highlight_research.py`のみ。
`git push dev main`（private ミラー）。公開originには触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: **オーナーのADC再認証**（`gcloud auth application-default login`、
対話操作）。これが済めばGate 7.2の実測（bridge-e2e-v1・day-2-v1で`tournament`
実行、既存judge+rank結果との費用・選抜比較）にすぐ戻れる。日常の進捗のため
PushNotificationは送っていない。

**次に推奨**: ADC再認証後はGate 7.2の実測を最優先で。それまでは
`app.video.highlight_research`の`_build_diversity_pool`・`run_local_highlight_research`
本体（複数関数を跨ぐ統合fixtureが要る、優先度は低）、または境界テストの薄い
他モジュール（`app/story_opening.py`・`app/story_titles.py`等）が次点。別層の
ambient WIPがcommitされ次第、E-5・E-6配線・E-7配線に戻るのが筋。次のセッションは
その時点の「着手中」・`.autonomy/trip/batch.log`・共有worktreeの`git status`を
確認してから選ぶこと。

## 172. クラウド層: `app.config.load_local_environment`（13モジュール共有の`.env`パーサ本体）に直接テストを追補

新規セッション。`git status`は前回commit以降クリーン（別層のambient WIPは今回のcontainerには
存在せず、共有worktreeの状態はローカル層が持つものと別）。`.venv/bin/pip install -q -e '.[dev]'`
成功（`google-adk`・`google-cloud-aiplatform`・`google-genai`等）、収集エラーなし、既存
**2,423件全成功**（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由。
このcontainerにもffmpegは入っていない）を確認してから着手。

前回（§171）の次点候補（`_build_diversity_pool`・`run_local_highlight_research`本体の統合
fixture、`app/story_opening.py`・`app/story_titles.py`）を見たが、後者2つは実際には
テスト行数が本体と同等以上（1.0〜1.6倍）で薄くはなかった。代わりに「モジュール行数 対
`tests/test_<同名>.py`行数」の比を repo 全体で機械的に洗い出し（`app/`配下の全`.py`と
対応する `tests/test_*.py` を突き合わせ）、ファイル名が対応しない誤検出（実際は別名の
テストファイルで厚くカバーされている——`app.contracts.models`は`tests/test_contracts_models.py`
489行で既に厚い、等）を1つずつ潰した結果、`app/config.py`の`load_local_environment`
（`.env`のKEY=VALUE読み取り、13モジュールが共有——`agent_runtime`・`mcp`・`web`各所の
ローカル設定読み込み）に**直接のテストが1本も無い**ことを見つけた。既存の呼び出し側
テスト（`test_place_names.py`・`test_map_background.py`・`test_private_journey_status.py`
等）はいずれも`load_local_environment`自体を`monkeypatch`で潰しており、パーサ本体
（コメント・空行・不正な行のスキップ、クォート除去、最初の`=`だけで分割、後勝ち、
`os.environ`を一切変更しない）は素通りだった。

追補したテスト（すべて合成`.env`内容・`tmp_path`。実の`.env`・資格情報・トークンは
一切使っていない）: ファイル欠落・空ファイル・パスがディレクトリの3つの「設定なし」経路、
コメント行・空行・`=`の無い行・名前が空の行のスキップ、行全体・キー・値の前後空白除去、
最初の`=`のみで分割（値に`=`が含まれるURL等）、二重引用符・単一引用符の除去、
`""`だけの値が空文字列になる境界、引用符内のアポストロフィが誤って剥がれないこと、
同名キーの後勝ち、複数キーの読み取り、非ASCII値のUTF-8読み取り、デフォルト引数
（カレントディレクトリの`.env`）、そして`os.environ`を一切変更しないこと。

**テスト**: `tests/test_config.py`（新設）19件。**全2,442件成功**
（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由。それ以外に
環境要因で外したテストは無い）。Ruff check成功。Ruff format差分1件（長い行の折返しと
文字列クォートの正規化）を`ruff format`で解消。`git diff --check`問題なし。見た目が
変わる単位ではないため両rideの再レンダー依頼は不要。

**commit**: `74a6a39`（`tests/test_config.py`のみ）。`git push -u origin HEAD`
（branch `cloud/20260907-2036`、private ミラー）。main へは直接push していない。
公開origin・実素材・Gemini・GCS・資格情報・課金には一切触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし（§171のADC再認証待ちは継続、このセッションでは触れていない）。

**次に推奨**: `app.video.highlight_research`の`_build_diversity_pool`統合部分・
`run_local_highlight_research`本体（複数関数を跨ぐ統合fixtureが要る、優先度は低。
§170・§171で周辺の純計算・書き出しヘルパーは既に埋めた）。次点は同じ「行数比」洗い出しで
見つかった他の未検証モジュール（`app/gps/`配下・`app/video/probe.py`等、いずれも
テスト自体は別名ファイルで存在するため要再確認——今回`app.contracts.models`で
誤検出したのと同じ罠がある。機械的な行数比だけで判断せず、実際に該当モジュールを
importしているテストファイルを`grep`で洗ってから「未検証」と結論すること）。
ADC再認証が済めばGate 7.2の実測（bridge-e2e-v1・day-2-v1）に戻るのが最優先。
別層のambient WIP（`app/story_film.py`・`app/story_ambient.py`）がcommitされ次第、
E-5・E-6配線・E-7配線に戻るのが筋。

## 173. デスクトップ層: クラウド2branch（`cloud/20260907-1835`・`cloud/20260907-2036`）の取り込み

lock取得後heartbeat。`git status`は`app/story_film.py`の未commit差分（別層のambient WIP、
既知・継続中、§169以降と同じ）のみで他の未追跡ファイルは無し。`.autonomy/trip/batch.log`の
最終行は9/6のままで5分規則に掛からない。末尾の「着手中」も生きているものなし。

`git fetch dev`で2つのcloud branchを見つけた。

- **`cloud/20260907-2036`**（§172、`app.config.load_local_environment`への直接テスト19件）:
  `tests/test_config.py`は新設ファイルで衝突なし、`--no-ff`でそのまま`merge made by 'ort'`。
- **`cloud/20260907-1835`**（§171クラウド側、`_extract_research_clips`への境界テスト追補）は
  `--no-ff`を試みたところ`tests/test_highlight_research.py`で広範囲の衝突。原因を調べると、
  同じセッション帯でデスクトップ層（本ファイル§171、`79faf9c`）とクラウド層が**同じ関数
  `_extract_research_clips`に対して独立にテストを書いていた**——ヘルパー名も別
  （`_quality_selection`/`_all_method_selections` 対 `_selection`/`_selections`/`_analysis`）
  で、機械マージでは解決できない形。両者の被覆内容を比較し、クラウド側33件・デスクトップ側
  36件（デスクトップ側は`_build_complete_evidence`も含む上位互換）だが、クラウド側にのみ
  **2本の未複製な経路**があった: `_extract_research_clips`の重複排除（同じ窓を2手法が選ぶ場合の
  hardlink）が、出力済みの古いファイルと衝突したときの挙動——`overwrite=True`なら差し替え、
  `overwrite=False`なら`FileExistsError`がそのまま伝播する（既存挙動の記録、バグではない）。

  `git merge --abort`でこのbranchのマージ自体は取り止め、上記2本をデスクトップ側の既存
  ヘルパー（`_write_file`・`_all_method_selections`・`_quality_selection`・
  `_clip_command_runner`）を使う形に書き直して`tests/test_highlight_research.py`へ直接
  追加した（`test_extract_research_clips_dedup_replaces_a_stale_output_when_overwrite_true`・
  `test_extract_research_clips_dedup_raises_on_a_stale_output_without_overwrite`）。これで
  クラウド側の被覆はデスクトップ側に完全に包含されたため、branch自体はもう不要と判断。

**テスト**: `tests/test_highlight_research.py` 36→38件、`tests/test_config.py`
（§172由来）19件。**全2,444件成功**（`--ignore=tests/test_judged_film_end_to_end.py`、
ffmpeg不在の既存事由）。Ruff check・format済み。`git diff --check`問題なし。見た目が
変わる単位ではないため両rideの再レンダー依頼は不要。別層のambient WIP
（`app/story_film.py`）には触れていない。

**commit**: マージ commit（`cloud/20260907-2036`取り込み）＋
`tests/test_highlight_research.py`への2本追加とこのhandoff更新。`git push dev main`
（private ミラー）、`git push dev --delete cloud/20260907-2036`。
`cloud/20260907-1835`も内容が完全に上位互換へ吸収されたため
`git push dev --delete cloud/20260907-1835`。公開originには触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: **オーナーのADC再認証**（`gcloud auth application-default login`、対話操作。
§171から継続）。これが済めばGate 7.2の実測に戻れる。

**次に推奨**: ADC再認証後はGate 7.2の実測を最優先で。それまでは§172が挙げた
「モジュール行数対テスト行数」の機械的洗い出し（`app/gps/`配下・`app/video/probe.py`等、
実際にimportしているテストを`grep`で確認してから「未検証」と結論すること）、または
`_build_diversity_pool`統合部分・`run_local_highlight_research`本体（優先度は低）。
別層のambient WIP（`app/story_film.py`）がcommitされ次第、E-5・E-6配線・E-7配線に
戻るのが筋。次のセッションはその時点の「着手中」・`.autonomy/trip/batch.log`・
共有worktreeの`git status`を確認してから選ぶこと。

## 174. デスクトップ層: S1の残り「配分の余りを他章に回す」を`select_by_chapter`へ配線

lock取得後heartbeat。`git status`は`app/story_film.py`の未commit差分（別層のambient WIP、
§169以降と同じ、既知・継続中）のみ。`.autonomy/trip/batch.log`の最終行は9/6のままで
5分規則に掛からない。末尾の「着手中」も生きているものなし。

roadmap優先順（S2追補→Q1→E-3→E-4→Q5→E-1→E-2→…）は全て完了済みで、E-5・E-7の残りは
ambient WIP未commitのため引き続き見送り。次点のS1「配分の余りの回し」（第110節、クラウド層が
`reallocate_footage_targets`・`ChapterAllocation`を`app/story_pacing.py`に用意済みで、
`select_by_chapter`への配線と再レンダーだけが残っていた）に着手した。

**やったこと**: `select_by_chapter`の章ごとのtarget計算を、これまでの「HALTは常に
`SHORT_HOLD_S`固定・それ以外は`allowance × share`」という一発計算から、`ChapterAllocation`
（`weight=len(inside)`、`capacity_s`はHALTなら`SHORT_HOLD_S`・それ以外はその章のheld候補が
現行規則で使い切れる秒数の合計）を組んで`reallocate_footage_targets`に渡す形に置き換えた。
容量を超えた章の超過分は、まだ余地のある章へ重みに比例して回る（HALTが1本しか使えなくても、
以前はその章の本来の取り分がそのまま捨てられていた）。`pinned_here`（その章のrequired windows
の秒数）は従来どおり配分後に加算。未使用になった`total`変数を削除。

**テスト**: `tests/test_story_pacing.py`に新規1件
（`test_a_halts_unspent_share_reaches_the_next_chapter`——HALTと隣のLINK章が候補数
同数でも、単純な五分五分の按分ならLINK章がtarget不足で6/10windowsしか採れないところ、
HALTの余りが回ることで10/10全て採れることを確認）。既存36件は変更なしで通過（動作の後方
互換を実測で確認——HALT章は今までどおり必ず1本、通常章の按分結果もあらゆる既存caseで
一致）。**全2445件成功**（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の
既存事由はこのcontainerには該当せず、単に従来から外している既知のend-to-endテストのみ）。
Ruff check・format済み。`git diff --check`問題なし。

**実測（両ride再レンダー、`app/story_film.py`のambient WIPには触れず、自分の変更だけ
`git stash`で分離してbefore/afterを取った）**:

| package | 配線前 footage windows / card / 尺 | 配線後 |
|---|---|---|
| bridge-e2e-v1 | 34 / 4 / 196.0s | 34 / 4 / 196.0s（無変化） |
| day-2-v1 | 61 / 7 / 418.0s | 61 / 7 / 418.0s（無変化） |

両packageとも配線前後で採用windows数・尺ともまったく同じだった——どの章も自分の容量上限に
かからず、按分だけで目標を使い切れていたため。roadmapが挙げた実例（1日目 footage 220/240秒、
第96節時点の観測）はday1固有の話で、bridge-e2e-v1・day-2-v1では再現しない。**見た目が変わらない
実測結果は妥当**（この2 packageの容量に余りが無かっただけで、今回追加したテストが実際に
再配分が起きるcaseを閉じている）。見た目が変わらないため、両ride再レンダーの依頼・
オーナー再視聴PushNotificationは不要と判断（§172と同じ扱い）。

**commit**: `<pending>`（`app/story_pacing.py`・`tests/test_story_pacing.py`・roadmap・
このhandoffのみ。`app/story_film.py`の別層WIPには一切触れていない）。`git push dev main`
（private ミラー）。公開origin・実素材・Gemini・GCS・資格情報・課金には一切触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし（オーナーのADC再認証待ちは§171から継続、このセッションでは触れていない）。

**次に推奨**: roadmap優先リストは実質すべて完了（残るE-5・E-7配線は別層のambient WIPが
commitされるまで見送り）。ADC再認証が済めばGate 7.2の実測（bridge-e2e-v1・day-2-v1）が
最優先。それまではE-4残り（題の語彙に「引き」／帯の経路図の存在感）、E-10残り（地図の
陸海コントラスト、コンソールの配色切替、題の帯の小地図の扱い——閉じ方は両ride地図背景版を
レンダーしオーナーが地名あり/無しを選ぶ）、またはday6の順位買い直し（バッチ終了後、≈¥2）、
または§172が挙げた「モジュール行数対テスト行数」の機械的洗い出しの続き。

着手中: Gate 7.2の実測（bridge-e2e-v1・day-2-v1、ADC再認証を確認できたため着手）（2026-09-08 09:59、デスクトップ層）

## 175. クラウド層: `app.agent_runtime.google_config.GoogleCloudRuntimeSettings`（Vertex AI設定契約）に直接テストを追補

新規セッション。`origin/main`は前回のfetch時点で74 commit進んでいた（S1配線・§172〜174を含む
デスクトップ層の取り込み済み）ので、まず`git checkout main && git merge --ff-only origin/main`で
追従してから着手した。`.venv/bin/pip install -q -e '.[dev]'`成功、収集エラーなし、既存
**2,445件全成功**（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由。
このcontainerにもffmpeg・qlmanageは無く、nodeはある）を確認してから着手。

§172・§173が挙げた「モジュール行数対テスト行数」の機械的洗い出しを引き継ぎ、`app/`配下の
全`.py`と対応する`tests/test_*.py`を突き合わせた。ファイル名が対応しない誤検出
（`app/contracts/models.py`は`tests/test_contracts_models.py`で既に厚い、
`app/submission/readiness.py`は`tests/test_submission_readiness.py`で既に厚い、等——
§172が踏んだのと同じ罠）を、実際にimportしているテストファイルを`grep`で洗って1つずつ
除外した結果、`app/agent_runtime/google_config.py`の`GoogleCloudRuntimeSettings`
（`GOOGLE_CLOUD_PROJECT`・`GOOGLE_CLOUD_LOCATION`・`GEMINI_MODEL`・
`GOOGLE_GENAI_USE_VERTEXAI`を読む、Vertex AI設定の有無だけを表す非ネットワーク契約——
`app/web/server.py`・`app/agent_runtime/agent_platform.py`・ADKエージェント各所が使う）に
**直接のテストが1本も無い**ことを見つけた。既存の呼び出し側テスト（`tests/test_agent_platform.py`
等）はいずれも`GoogleCloudRuntimeSettings`をリテラル値で直接組み立てるか`from_environment`を
monkeypatchで潰しており、`from_environment`自体（プロセス環境と`.env`の優先順位、空白除去、
`use_vertex_ai`の大文字小文字正規化）・`missing_configuration`・`status`・`to_dict`の
組み立てロジックは素通りだった。`app.config.load_local_environment`本体（§172）と対になる、
その1段上の契約。

追補したテスト（すべて合成のプロジェクト名・場所名・モデル名。実の資格情報・GCPプロジェクトIDは
一切使っていない）: `.env`からの読み取り、`.env`が無いときの全項目空、**プロセス環境が`.env`より
優先されること**、プロセス環境の値が空文字列でも`.env`へフォールバックしないこと
（`os.environ.get(key, default)`はキーが存在するだけで`default`を素通りさせる境界）、
全項目の前後空白除去、`use_vertex_ai`の大文字小文字正規化（`"True"` → `"true"`）、
`missing_configuration`が欠けている項目だけを列挙すること（全欠落・全充足・一部欠落・
フラグが`"true"`と完全一致しない4通り——`"false"`・`"1"`・`"yes"`・空文字列——のパラメータ化)、
`status`の2値、そして**`to_dict()`がプロジェクト名・場所名・モデル名の実値を一切含まず、
真偽値と欠落項目名だけを返すこと**（payloadを文字列化して実値が含まれないことを確認する
privacy不変条件のテスト）。

**テスト**: `tests/test_google_config.py`（新設)17件。**全2,462件成功**
（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由。それ以外に
環境要因で外したテストは無い）。Ruff check成功。Ruff format差分1件（1関数シグネチャの
折返し）を`ruff format`で解消。`git diff --check`問題なし。見た目が変わる単位ではないため
両rideの再レンダー依頼は不要。

**commit**: `tests/test_google_config.py`とこのhandoff更新のみ。`git push -u origin HEAD`
（branch `cloud/20260907-2236`、private ミラー）。main へは直接push していない。
公開origin・実素材・Gemini・GCS・資格情報・課金には一切触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし（§171由来のオーナーADC再認証待ちは継続、このセッションでは触れていない）。

**次に推奨**: ADC再認証が済めばGate 7.2の実測（bridge-e2e-v1・day-2-v1）が最優先。それまでは
同じ「行数比＋grep確認」の洗い出しの続き（`app/agents/vertex_director.py`・
`app/video/vertex_transport.py`等は直接のテストファイルが無いが呼び出し側でVertex AI
クライアントをmonkeypatchしており、`from_environment`類の純計算部分だけを切り出せるか要確認）、
またはE-4残り・E-10残り（オーナーの実視聴判断が要る単位、次点）。次のセッションはその時点の
「着手中」・共有worktreeの`git status`を確認してから選ぶこと。
## 176. クラウド層: `app/story_motion_pacing.py`（未配線の重複計算）を削除

環境: `python3` 3.11.15。venvへ`pytest`・`ruff`を導入後、`google`/`vertexai`/`agentplatform`の
importエラーが8ファイルで出たため`pip install -e '.[dev]'`を実行（成功、追加のタイムアウト無し）。
以後は全2,451件が収集可能。`ffmpeg`が本containerに無いため`tests/test_judged_film_end_to_end.py`の
6件のみ従来どおり除外（`node`は利用可能、`qlmanage`は未使用）。

§166でクラウド層が作った`app/story_motion_pacing.py`（`duration_from_motion`・`best_span`、
順位＋動き量からholdの尺と12秒窓のどちらの半分を使うかを決める計算）が、§168の確認時点で
「`app/story_hold.py`の`hold_all_from_motion`・`choose_half_by_motion`が同じ問題を先に解決し
`app/story_pacing.py`へ配線済みで、`story_motion_pacing.py`はどこからも呼ばれていない独立
重複」と記録されたまま残っていた。`grep`で確認すると、`app`配下のどこからもimportされておらず、
唯一の参照は自分自身のテストファイル（`tests/test_story_motion_pacing.py`、129行）のみだった。
振る舞いを変えずに重複を減らす単位として、両ファイルを削除し、roadmapの当該注記を「削除済み」
へ書き換えた（実装が消えたのに注記だけ「重複が残っている」と読める食い違いを解消）。

**テスト**: 2,445→2,425件（削除した129行のテストファイル1本の分減、既存の他テストは無変更）。
**全2,425件成功**（`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由）。
Ruff check・format済み。`git diff --check`問題なし。見た目が変わる単位ではないため両ride
再レンダー・オーナー再視聴PushNotificationは不要。

**commit**: `4be25fb`（`app/story_motion_pacing.py`・`tests/test_story_motion_pacing.py`の削除、
`docs/completion-roadmap-ja.md`の注記更新）。`git push origin`は新規branch
`cloud/20260908-0035`へ（このprivateミラーのmainには直接pushしない）。公開origin・実素材・
Gemini・GCS・資格情報・課金には一切触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし（オーナーのADC再認証待ちは§171から継続、このセッションでは触れていない）。

**次に推奨**: roadmap優先リストは実質すべて完了（残るE-5・E-7配線は別層のambient WIPが
commitされるまで見送り）。ADC再認証が済めばGate 7.2の実測が最優先。それまでは§172の
「モジュール行数対テスト行数」の機械的洗い出しの続き（今回`story_motion_pacing.py`のような
死んだ重複が見つかる可能性がある）、またはE-4残り・E-10残り（いずれもオーナーの選択が必要）。

## 177. クラウド層: §172の「モジュール行数対テスト行数」洗い出しを完走、`app.agents.vertex_director`に境界テストを追補

新規セッション。`git fetch origin main`で分かったこと: このcontainer起動時のローカル`main`は
74commit遅れていた（`origin/main`は既に`8111a53`＝§174まで反映済み）。`git merge --ff-only`で
追随してから着手（別containerの状態不整合で、実際の紛失は無かった）。`.venv/bin/pip install -q -e
'.[dev]'`成功、収集エラーなし。着手前に**全2455件成功**を確認（後述の新規10件を含む数、
`--ignore=tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由。このcontainerにも
ffmpegは入っていない）。末尾の「着手中:」は生きているものなし。

§172が機械的発見と言いつつ手作業で止めていた「`app/`配下の全`.py`と対応する
`tests/test_*.py`の行数比」を、AST解析で最後まで自動化した:
`ast.parse`でtestファイルのimport文を集め、`from app.X import name`が`app.X`パッケージの
`__init__.py`内で`from .submodule import (…, name, …)`として再輸出されている場合は
`app.X.submodule`へ帰属させる（`app.contracts.models`・`app.submission.readiness`・
`app.agent_runtime.adk_agent`等、パッケージの`__init__.py`が複数submoduleを束ねて
再輸出する構成で、素朴な文字列一致だと軒並み「未検証」に誤判定される——§172が名指しした
罠そのもの）。この帰属を通したのち、`app/`137ファイル中、本当にテスト参照ゼロだったのは
9件: `app.submission.__main__`（3行、`main()`を呼ぶだけ）・`app.agents.video_agent`
（7行、docstringのみで実体コード無し）・`app.video.clips`（同、docstringのみ）・
`app.mcp.preflight`（16行、CLIエントリ）・`app.gemini_probe`（17行、CLIエントリ）・
`app.adk_synthetic_demo`（18行、CLIエントリ）・`app.agent_runtime.deploy_synthetic`
（44行、Agent Platformへの実デプロイを行うCLI）・`app.story_copy_probe`（58行、実Gemini
呼び出しの薄いCLIラッパー）・`app.agents.vertex_director`（144行）。

前者8つはCLIの薄い配線（`main()`が環境から設定を読み実クラウド呼び出しへ委譲するだけ）か
docstringのみのプレースホルダで、テストする実体（分岐・境界・失敗経路）が無いか、
実クラウド操作（Agent Platformへのデプロイ・実Gemini呼び出し）そのものが本体のため、
モックで固めても「配線が変わっていないことの確認」以上の値が薄いと判断し見送った。

`app.agents.vertex_director`だけが質的に異なった: 同じ`_GenaiClient`Protocolパターンを
使う兄弟クラス`app.agents.vertex_story_copy.VertexAIGeminiStoryCopyTransport`
（`tests/test_vertex_story_copy.py`で厚くテスト済み）・`app.video.vertex_transport`
（`tests/test_analysis_ranking.py`経由でテスト済み）と全く同じ構造
（`__init__`のモデル名検証、`from_environment`の設定不足時`ValueError`、
`compose_script`の空prompt/payload検証、クライアント例外を`GeminiDirectorError`へ
変換、`_response_mapping`が`response.parsed`優先・`response.text`のJSONへの
フォールバック・不正JSON/構造なしで`GeminiDirectorError`）を持つ純粋な
Protocol実装でありながら、テストが1本も無かった。実Gemini呼び出しは一切せず、
`test_vertex_story_copy.py`と同じ「`SimpleNamespace(models=RecordingModels(...))`を
`client`として渡す」手法でネットワークに触れずに閉じられる単位。

**やったこと**: `tests/test_vertex_director.py`を新設。兄弟テストと同じ構造で、
`VertexAIGeminiDirectorTransport`の(1)空白のみのmodel名を拒否、(2)scenesスキーマ
（`additionalProperties: false`・`scene_type`のenum4種）を守ったrequestを組む、
(3)`response.parsed`が無ければ`response.text`のJSONへフォールバック、(4)不正JSON
テキストで`invalid JSON director script`、(5)prompt/payloadが空なら
クライアントを一切呼ばずに`non-empty`で`GeminiDirectorError`、(6)クライアントの
例外を`request failed`の`GeminiDirectorError`に変換し元の例外文言を漏らさない、
(7)`parsed`も`text`も無ければ`no structured director script`、(8)`parsed`が
Mapping以外（list等）でも`text`へ正しくフォールバックする、(9)`from_environment`が
環境変数未設定時に`Google Cloud configuration is incomplete`で失敗する、の10件。
実クラウド資格情報・ネットワーク呼び出しは一切使っていない（`.env`もこのcontainerに
存在しない）。

**テスト**: 新規10件。**全2455件成功**（`--ignore=tests/test_judged_film_end_to_end.py`、
ffmpeg不在の既存事由、それ以外に環境要因で外したテストは無い）。Ruff check・format済み
（277ファイル整形済み確認、差分なし）。`git diff --check`問題なし。見た目が変わる単位
ではないため両rideの再レンダー・オーナー視聴は不要。実素材・Gemini・GCS・資格情報・
課金には一切触れていない。

**commit**: `eb2346b`（`tests/test_vertex_director.py`のみ）。`git push -u origin HEAD`
（branch `cloud/20260908-0236`、private ミラー）。main へは直接push していない。
公開origin・実素材・Gemini・GCS・資格情報・課金には一切触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし（§171由来のADC再認証待ちは他層の話としてこのセッションでは触れていない）。

**次に推奨**: §172の行数比洗い出しは本節で完走したので、次点は別の切り口。
ADC再認証が済めばGate 7.2の実測（bridge-e2e-v1・day-2-v1）が最優先。それまでは
E-4残り（題の語彙に「引き」／帯の経路図の存在感）、E-10残り（地図の陸海コントラスト、
コンソールの配色切替、題の帯の小地図の扱い）、day6の順位買い直し、または
`app.gps.turns`・`app.video.probe`等テスト行数比が高い（=既に厚い）モジュール群の
逆側——本節で見送った8つのCLIエントリのうち、もし後日ロジックが増えるなら
そのとき改めてテストを検討すること。次のセッションはその時点の「着手中」・
`.autonomy/trip/batch.log`・共有worktreeの`git status`を確認してから選ぶこと。

## 166. 公開できる素材にする — ナンバーのぼかし、顔の除外、そして持ち出せる package

オーナーの指示（2026-09-08）: 他人の車は写っていてよい。**ナンバーはぼかす**。
**個人を特定できる人の写り込みは除外する**。そのうえで、審査員が手元で実際に作品を
作れるようにする。公開リポジトリは一時的に非公開へ（実施済み。走行地名は公開履歴に
1件も無いことを確認したうえで）。

### 端末内で見る（`tools/apple_vision_boxes.m`・`app/video/vision_boxes.py`）

Apple Vision に文字と顔を1回で聞く小さな Objective-C ツール。既存の probe と同じ形で
`clang` で組み、外へは何も出さない。実測: 文字＋顔で **1フレーム 52ミリ秒**。

### ナンバーの絞り込み（`app/plate_blur.py`）

ここが全部だった。実測では1本の作品に**文字が1,031か所、うちナンバーは17か所**。
全部ぼかせば道路標識が消える。最初の規則（英字2＋数字2が短い文字列のどこかに）は
看板の誤読（`3ta3`・`Esk StI`・`1VINANN`）まで拾い、しかもエンコードごとに誤読が
変わるので収束しなかった。**英字の並びと数字の並びが隣接**し、**小文字を含まない**、
に締めたところ、実走行から読めた実物（QHF65・FUH958・ANT-09・NNT685・DWE65・FWN527・
QU6499）は全て通り、誤読は1つも通らなくなった。

ぼかしは crop → boxblur → overlay を時間で切り替える。boxblur 単体では画面全体が
ぼける。半径は領域の1/4未満に抑える（4:2:0 の彩度面の制約。12 を渡すと落ちる）。

### 収束の問題（これが一番の学び）

**再エンコードすると読める文字が変わる**。あるエンコードで読めなかったナンバーが、
次のエンコードでは読める。したがって「一度ぼかして終わり」にはならない。

- `blur_until_clean`: 各周回で見つけた領域を**累積して原本に一度だけ**当てる。
  ぼかした版をさらにぼかすと周回ごとに劣化するため。
- `--harden`: package の全クリップを見て、顔があれば**クリップごと削除**、
  ナンバーがあれば再ぼかし、地図と判定記録をそれに合わせて狭める。
- `--harden-from-film`: **完成した作品を読み、領域を plan 経由でクリップへ戻す**。
  クリップ単体では読めず作品では読めるナンバーは、これでしか捕まらなかった。

### 持ち出せる package（`app/portable_package.py`）

day7 の元動画は **56.6 GiB**。配れない。作品が使う窓だけを 1080p（CRF 26、作品自体の
ビットレートに合わせた）で切り出し、ナンバーをぼかし、`film-sources.json` で対応づける。
この地図は**許可リストでもある**: それ以外の窓は選抜に出てこない。GPX と音楽1曲
（CC BY 4.0）も同梱し、`--install` で manifest を置き場所に合わせる。

**実測（day7）**: 判定済み337窓 → 作品が使う55窓 → **顔で2本除外 → 53本**、
合計 **約1.4 GB**。審査員は clone して2コマンドで **6分の作品**が手元に出来る。
カードの描画器は macOS なら Quick Look、それ以外は headless Chromium を自動で選ぶ
（`--cards` で上書き）。Maps の鍵が無ければ地図なしで同じ作品になる。

### 公開するデモ動画

day7 の作品からブラー済みで組み立て、**全フレーム走査でナンバー0・顔0**を確認。
顔は作品中の98〜110秒の1か所だけだったので、抜き出しはその後（240秒〜）から取った。

### 収束したときの数字（2026-09-08 13:20）

| | |
|---|---|
| 配布 package | `private-media/distribution/ride-storyteller-day-7.zip` |
| 大きさ | 1,730,095,484 バイト（1.61 GiB。GitHub Release の 2 GB 制限内） |
| SHA-256 | `d6dedf409fe7c1ea307ba051e8004b5ee6019b9216236f2a45d2e4cde5dc5e1d` |
| クリップ | 53本（顔で2本除外） |
| そこから作られる作品 | 6分08秒、61 beat、字幕と音楽つき |
| 全フレーム走査 | 作品でナンバー0・顔0 |
| デモ動画 | `day-7-v1/demo/demo-en-published.mp4`、177.03秒、全フレームでナンバー0・顔0 |
| 音楽 | Wandering / Numall Fix、126 BPM、5分54秒、CC BY 3.0（オーナー選定 2026-09-08） |

**収束に3周かかった**。クリップを全フレームで綺麗にしても、作品に切ると読める
ナンバーが出る。`--harden-from-film` で作品側の検出をクリップへ戻し、3周目で0。
最後に残った1件は1フレームだけの誤読で再現しなかったため、**検査は同じ読みが2回
出ることを求める**ようにした（ぼかしは1回で当てる。読めたナンバーは1回でもナンバー）。

**残り（オーナーの操作）**: 公開リポジトリを再公開するか判断、デモ動画の目視確認と
公開、package の配布先（GitHub Release か公開バケット）、ホスト URL、Devpost 送信。

## 178. Cloud Run の公開デモに審査員限定の認証（未コミットの引き継ぎを完走）

新規セッション。着手時に共有 worktree の `git status` を見たところ、`app/web/cloud_run.py`・
`app/web/deployment.py`・`app/web/server.py`・対応する3つのtestファイル・`.env.example`が
未commitで変更されていた（別レイヤーの途中終了。末尾に「着手中」行は無く、lockも空いていた）。
`shared-worktree-partial-staging`の教訓（hunkを分割して混ぜるとHEADを壊す）に従い、
まず差分の中身を読み、対象testを実行して緑であることを確認してから「自分の単位として
引き継いで完成させる」と判断した。

**内容**: `RIDE_PUBLIC_DEMO_BASIC_AUTH_USER`/`RIDE_PUBLIC_DEMO_BASIC_AUTH_PASSWORD`の
両方を設定したときだけ、`public_demo`モードの`/health`以外の全リクエストにHTTP Basic
認証を要求する。両方空なら従来通り無認証（ローカル試験用）。local モードは公開bindしない
ため常に無視。ヘッダ欠落・不正形式・誤ったuser/passwordは全て同一の401 JSONを返す
（`hmac.compare_digest`でタイミング差も揃え、どこが違うかを漏らさない）。
`CloudRunPublicDemoPlan.gcloud_deploy_arguments`は`public_access_approved=True`のとき
`basic_auth_configured=True`も無いと`PermissionError`（ソースrepo URLの既存チェックと同型）。
plan/environmentには実credentialは一切入らず、設定済みかの確認flagのみ運ぶ。

これは**公開操作そのものではない**——公開IAMの承認は引き続き別の明示承認が必要
（roadmap Gate 6「ホスト済みプロジェクトURL」）。将来それが承認されたときに、
無制限公開ではなく審査員限定にできる手段を先に用意しただけ。

**テスト**: 対象3ファイル88件 + 全体2538件成功（`--ignore=tests/test_judged_film_end_to_end.py`、
ffmpeg不在の既存事由）。Ruff check済み、`git diff --check`問題なし。見た目が変わる単位
ではないため両rideの再レンダー・オーナー視聴は不要。実素材・Gemini・GCS・資格情報・
課金には一切触れていない。

**commit**: `be433c2`。`git push dev main`予定（このセッション内で実施）。公開origin
へは押していない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし（公開IAM自体は引き続き未承認・未実行）。

**次に推奨**: 優先順どおりS2追補以降の品質単位は既に完了しているため、次点は
E-4残り（題の語彙に「引き」／帯の経路図の存在感）かE-10残り、または§177が示した
`.autonomy/trip/batch.log`・共有worktreeの`git status`確認後の次の単位。

## 179. クラウド層: `tests/test_web_page_scripts_parse.py` の対象を console/status の2 page から5 page 追補

新規セッション。`git checkout main && git fetch origin main`で確認: ローカル`main`は
`origin/main`（`be02fcc`＝§177・§166を含む）と一致しており遅れなし。detached HEADから
`main`へ切替えた際に出た「81 commits behind」警告は、切替前のdetached commitがすでに
`main`の先端`be02fcc`そのものだったための偽警告（`git merge-base --is-ancestor`で確認）
で、実際の紛失は無かった。`.venv/bin/pip install -q -e '.[dev]'`成功、収集エラーなし。
着手前に**全2,528件収集・2,522件成功**（`tests/test_judged_film_end_to_end.py`の6件のみ
`ffmpeg`不在で失敗、既知の環境要因。`node`は利用可能、`qlmanage`は未使用）を確認した。
末尾の「着手中:」（§174、Gate 7.2実測・デスクトップ層）は実素材・ADC実測の話で
クラウド層の対象外、かつ`git status`は清潔（別層のambient WIPはこのcontainerに存在せず）。

§172・§177が完走した「モジュール行数対テスト行数」の洗い出しに続く形で、今回は
`app/web/server.py`の中でも**JavaScriptが構文として正しいことだけを見る**
`tests/test_web_page_scripts_parse.py`（コメントに経緯があるとおり、f-string内の
Pythonエスケープがそのままブラウザへ漏れてconsole pageの全関数がundefinedになった
実障害の再発防止用。Pythonのテストは何もJavaScriptを実行しないため気付けなかった）
の対象範囲を洗った。`PAGES`タプルは`_private_journey_console_page`・
`_private_journey_status_page`の2つだけで、`app/web/server.py`内の他の`_..._page`
関数を`grep`で全て洗うと、同じ「f-string中に`<script>`でJSONを埋め込む」構造を持つ
page がさらに5つ見つかった: `_private_highlight_review_page`・
`_private_highlight_reinforcement_review_page`・`_private_evidence_review_page`・
`_private_director_preview_page`・`_media_inventory_page`（残る2つの`*_setup_page`は
`<script>`を含まないため対象外と確認済み）。いずれも引数は`language: UiLanguage`のみで
ファイル・ネットワーク・環境変数に触れず、既存のharness（`getattr(server, page)(language)`
→ `node --check`）にそのまま乗る。追補前に両言語で実際にレンダーしスクリプトを含むことを
確認してから配線した。

**やったこと**: `PAGES`タプルへ上記5つを追加しただけ（本体コードは無変更）。

**テスト**: `test_the_pages_inline_script_parses`が5件（page）×2件（言語）=10件増、
既存5件（2 page×2言語+home page smoke 1件）と合わせて15件。**全2,532件成功**
（`--deselect`で`tests/test_judged_film_end_to_end.py`の6件のみ除外、ffmpeg不在の既存事由。
それ以外に環境要因で外したテストは無い）。Ruff check・format済み（282ファイル整形済み確認、
差分なし）。`git diff --check`問題なし。見た目が変わる単位ではないため両ride再レンダー・
オーナー再視聴PushNotificationは不要。実素材・Gemini・GCS・資格情報・課金には一切触れていない。

**commit**: `a757edf`（`tests/test_web_page_scripts_parse.py`のみ）。`git push -u origin HEAD`
（branch `cloud/20260908-0435`、private ミラー）。main へは直接push していない。
公開origin・実素材・Gemini・GCS・資格情報・課金には一切触れていない。

**支出**: ¥0（累計変わらず ≈¥764 / ¥1000）。

**承認待ち**: なし（§171由来のADC再認証待ちは他層の話としてこのセッションでは触れていない）。

**次に推奨**: 同じ切り口（`app/web/server.py`の他のpage関数、または他モジュールの
「テストはあるが境界・失敗経路が薄い」箇所）の続き。ADC再認証が済めばGate 7.2の実測
（bridge-e2e-v1・day-2-v1）が最優先だが、これは実素材が要るためデスクトップ層のみ着手可能。
それ以外はE-4残り・E-10残り（いずれもオーナーの視覚判断が必要、クラウド層は着手不可）、
day6の順位買い直し（課金が要るためクラウド層は着手不可）。次のセッションはその時点の
「着手中」・`.autonomy/trip/batch.log`・共有worktreeの`git status`を確認してから選ぶこと。

## 180. デスクトップ層: ADC復旧を確認、進行中のGate 7.2実測を発見（横取りせず記録のみ）

lock取得・heartbeat。`git fetch dev`で3つの`cloud/*` branchを確認したが、いずれも
`git merge-base --is-ancestor`で**main に既に取り込み済み**（§177〜179で merge 済みの
残骸）と判明したため、コード変更なしで`git push dev --delete`し3件とも削除した。

`.autonomy/trip/batch.log`は9/6で止まっており5分規則に掛からず、末尾に生きている
「着手中」も無かったため、優先順位どおりGate 7.2の実測（§171が**ADC再認証待ち**で
保留にしていた単位）に着手しようとしたところ、**ADCは既に復旧していた**
（`gcloud auth application-default print-access-token`成功、
`google.auth.default()`も`ride-storyteller`projectを返す）。オーナーが
`gcloud auth application-default login`を済ませたとみられる（このセッションでは
対話操作は一切行っていない）。

実測に入る前に`private-media/work/`を確認したところ、**既に別プロセスが着手済み**
だった: `private-media/work/bridge-e2e-v1/gemini-tournament-ranking.json`
（187窓分すべて揃っている、更新時刻 11:03、`plan_tournament_cost`の見積り¥11.73と
符合）と、`.autonomy/gate72/day-2-v1-tournament.log`（12:13作成）。`ps`で確認すると
`python -m app.analysis_cli tournament private-media/work/day-2-v1 --bucket
ride-storyteller-analysis --prefix day-2-v1 --i-approve-spending`が**PID 39426、
親プロセスID 1（孤立）、経過2時間47分、現在も実行中**（Google宛のTCP接続が1本
ESTABLISHED、CLOSE_WAIT多数——大きな動画window群を10本ずつ送る比較を複数ラウンド
続けているとみられる挙動で、ハングの確証は無い）。ADC再認証が済んだ直後、この
デスクトップ上の別セッション（おそらく直前のスケジュール実行かwatchdog）が
Gate 7.2の実測に着手し、bridge-e2e-v1は買い切ったが、day-2-v1（753窓・85比較・
見積り¥47.11、bridge比4倍のボリューム）の途中で今に至るまで実行し続けている状態。

**shared-worktree-partial-staging**と同じ理由で、実行中のプロセスにもGCS/Geminiへの
実課金にも触れていない: 二重に`tournament`を走らせれば二重に課金するため、
`private-media/work/day-2-v1`と当該プロセスは一切触らず、状況の記録だけに留めた
（handoff末尾に「着手中」行が無かったのはこの単位を開始したセッションが完走前に
終了したため——次に見る層はこの節を「着手中」相当として扱うこと）。

**支出**: このセッションでの新規支出は¥0。ただし**確認できた実際の支出**として
bridge-e2e-v1のtournamentが完了済み（¥11.73、ファイルが揃っているため実行され課金
された事実は確か）。累計 **≈¥764 → ≈¥776 / ¥1000**（§179時点の¥764に確認済みの
¥11.73を加算）。day-2-v1分の¥47.11は**プロセスが完走し次第確定**（完走すれば累計
≈¥823/1000）。

**承認待ち**: なし（ADC再認証は既に他所で完了済み、これはユーザーの対話操作でこの
セッションの範囲外）。

**次に推奨**: 次のセッションはまず`ps aux | grep analysis_cli`でこのtournament
プロセスの生死を確認すること。完走していれば
`private-media/work/day-2-v1/gemini-tournament-ranking.json`が生まれているはずで、
そうなれば**Gate 7.2本来の残り作業**（`select_judged_candidates(requires_analysis=
False)`経由でbridge-e2e-v1・day-2-v1それぞれ「判定+順位付け」版とtournament版の
採用窓・費用を比較し、閉じる）に進める。まだ実行中なら、2時間47分から大きく
超えて進捗が無い（TCP接続数・ログファイルサイズが変化しない）ようならハングを
疑ってプロセスの状態を再確認し、必要なら安全に再実行する判断をすること
（このセッションでは実行時間内で判断材料が不足していたため保留した）。
それ以外はE-4残り・E-10残り（オーナーの視覚判断が必要）に進むこと。

## 181. クラウド層: `app/edit/candidate_planner.py` に境界・失敗経路のテストを追補

新規セッション。`git checkout main && git pull origin main`で追従（74 commit分の
S1配線・§172〜180を含む取り込み済み）してから`cloud/20260908-0636`branchを切って着手。
`.venv/bin/pip install -q -e '.[dev]'`成功、収集エラーなし。着手前に全2,548件収集・
2,542件成功（`tests/test_judged_film_end_to_end.py`の6件のみ`ffmpeg`不在で失敗、
既知の環境要因。`node`は利用可能、`qlmanage`は未使用）を確認した。末尾の「着手中:」
（§180、Gate 7.2実測・day-2-v1 tournament・デスクトップ層）は実素材・課金の話で
クラウド層の対象外、`git status`は清潔（別層のambient WIPはこのcontainerに存在せず）。

§172・§175・§177・§179が続けてきた「モジュール行数対テスト行数」の機械的洗い出しに
`grep`ベースの誤検出除去（ファイル名不一致のため`test_${basename}.py`探索だと偽陽性・
偽陰性の両方が出る）を加えてapp/配下全体を再走査し、実際にどのテストファイルからも
importされていないモジュールを2つ特定した: `app/adk_synthetic_demo.py`と
`app/story_copy_probe.py`。いずれもVertex AI/ADKへ実際にネットワーク接続するCLIの
エントリポイントで、意味のあるテストを書くには実課金かモックの多重化が要り、
このセッションの制約（外部サービス呼び出しをテストに入れない）に合わない。

代わりに、importはされているが境界・失敗経路が薄いモジュールとして
`app/edit/candidate_planner.py`（93行、既存テストは`tests/test_candidate_planner.py`
の2件・29行のみ）を選んだ。この契約は`app/director_pipeline.py`・`app/local_pipeline.py`・
`app/scout.py`・`app/web/server.py`など複数箇所からGPSイベント→編集候補クリップの
橋渡しに使われており、GPSイベント由来のevent_id/chapter_id/asset_name_hintのみを
扱う純粋計算（ファイル・ネットワーク・実座標・実時刻には触れない）。

**やったこと**: `tests/test_candidate_planner.py`に27件追加（既存2件と合わせ29件）。
内訳: `CandidateClip.__post_init__`の状態別バリデーション（`awaiting`で
`evidence_source`が設定済みだと拒否、`confirmed`/`rejected`で`None`・空文字・
空白のみの文字列を拒否）／`confirm_clip_evidence`の遷移（confirmed・rejectedへの
遷移、他フィールド不変の確認、空白sourceの拒否、既決定クリップへの再決定拒否）／
`review_candidate_edit_plan`の分岐（尺充足かつ未決定なしで ready、尺不足のみの
reason、pending優先のブロック、**rejectedクリップはdocstring通り「透明性のため
報告されるが単体では readiness をブロックしない」ことを明示的に確認**、confirmed
クリップが1本も無ければ尺・pendingが満たされても not ready）／`confirmed_event_ids`
の順序保持と空集合／`to_dict()`各種（enum が文字列値になる、`json.dumps`が通る、
tuple がlistに変換される）／`build_candidate_edit_plan`の初期状態（全クリップが
`awaiting_video_evidence`・`evidence_source=None`）。本体コード（`app/edit/`配下）は
無変更。

**テスト**: `tests/test_candidate_planner.py`のみ変更、29件全成功。全体
**2,575件成功**（`--deselect`で`tests/test_judged_film_end_to_end.py`の6件のみ除外、
ffmpeg不在の既知事由。それ以外に環境要因で外したテストは無い）。
`.venv/bin/python -m ruff check app tests`は初回E501（行長）15件を検出、
`ruff format`で自動整形して解消・再チェック通過。`ruff format --check`は282ファイル
フォーマット済み確認、差分なし。`git diff --check`問題なし。見た目が変わる単位では
ないため両ride再レンダー・オーナー再視聴PushNotificationは不要。実素材・Gemini・
GCS・資格情報・課金には一切触れていない。

**commit**: `0542b39`（`tests/test_candidate_planner.py`のみ）＋このhandoff追記
（別commit）。`git push -u origin HEAD`（branch `cloud/20260908-0636`、
private ミラー）。main へは直接push していない。

**支出**: ¥0（このセッションでは変更なし。§180が記録した確認済み累計 ≈¥776/1000
に対してこのセッションからの追加支出は無い）。

**承認待ち**: なし（§180由来のGate 7.2 day-2-v1 tournamentの生死確認は他層の話として
このセッションでは触れていない）。

**次に推奨**: 同じ切り口（importされているが境界・失敗経路が薄いモジュール）の続き。
候補は`app/web/i18n.py`（442行、テスト110行、ratio .24——翻訳辞書の欠落キー・言語
フォールバックの境界）、`app/places.py`（343行、テスト191行、ratio .55——地名の
プライバシー不変条件を絡めた境界）、`app/stop_kinds.py`（321行、テスト187行、
ratio .58）。ADC再認証・Gate 7.2実測（bridge-e2e-v1完了済み、day-2-v1は§180時点で
実行中——次のセッションはまず`ps aux | grep analysis_cli`で生死確認）は実素材・課金が
要るためクラウド層は着手不可、デスクトップ層のみ。E-4残り・E-10残り（オーナーの
視覚判断が必要）も同様にクラウド層は着手不可。E-5（音のつなぎ）・E-7配線は別層が
音声（ambient）レイヤーを配線中のため引き続き見送り。


## 182. デスクトップ層: `cloud/20260908-0636`取り込み、`app/story_caption.py`重複コードを削除

lock取得・heartbeat。`git fetch dev`で`cloud/20260908-0636`（§181の`candidate_planner`境界・
失敗経路テスト追補）を発見、`git merge --no-ff`→全2,575件成功・Ruff緑を確認して`main`に
残し、`git push dev main`後に`git push dev --delete cloud/20260908-0636`。

続けてGate 7.2実測（§180が発見した`day-2-v1`のtournamentプロセス、PID 39426）の生死を
確認したところ、**まだ実行中**（12:13PM開始、確認時16:06で約4時間、CPU時間はごく僅かで
ネットワーク待ちの挙動と一致）。§180と同じ理由で触れず、次の判断材料にはまだ早いと
見送った。

優先順位（S2追補→Q1→E-3→E-4→…）に沿って`docs/completion-roadmap-ja.md`のE-4の項を
読み直したところ、「残り: 題の語彙に「引き」／帯の経路図の存在感」の2点はいずれも
実素材のレンダーをオーナーが見て判断する性質のもの（地図の線の太さは`6c0e2b6`で
既に一度強めてあり、その上でなお「残り」と書かれているのは見た目の確認待ちという
ことだった）で、コードだけでは閉じられないと判断した。

代わりに、E-4の同じ節が指す**未処理の副作用**を片付けた: `docs/current-system-handoff-ja.md`
第134節が記録していた`app/story_caption.py`（`fit_title`/`fit_body`/`build_lower_third_caption`）は、
クラウド層が分岐の古い状態からE-4の文字整形を独自に再実装したもので、実際に配線されたのは
別モジュール`app/lower_third_text.py`（`chapter_card.py`が現に import している方）。
第134節は「死んだコードとして残るのは望ましくないが、削除も別の判断が要る」と明記して
判断を先送りしていた。`grep`で`app/story_caption.py`の呼び出し元が自分のテスト
（`tests/test_story_caption.py`）以外に無いこと（本体コードからのimportゼロ）を確認し、
`app/story_motion_pacing.py`削除（クラウド層§175、同じ「独立に再実装された重複」の前例）に
倣って両ファイルを削除した。

**テスト**: 削除前2,575件→削除後**2,542件成功**（33件はstory_caption専用テストの消失、
それ以外の減少なし。`--deselect tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由）。
Ruff check緑。`git diff --check`問題なし。見た目が変わる単位ではない（配線されていない
コードの削除）ため両ride再レンダー・オーナー再視聴PushNotificationは不要。実素材・Gemini・
GCS・資格情報・課金には一切触れていない。

**commit**: このセッションの一連（着手中マーカー→cloud取り込みmerge→削除→本節）。
`git push dev main`予定。公開origin へは押していない。

**支出**: ¥0（累計変わらず ≈¥776 / ¥1000。day-2-v1分¥47.11はtournamentプロセス完走待ち）。

**承認待ち**: なし。

**次に推奨**: 次のセッションはまず`ps aux | grep analysis_cli`でtournamentプロセス
（PID 39426）の生死を確認すること。§180から数えて長時間（4時間超）進捗が無いようなら
ハングを疑い状態を再確認・必要なら安全な再実行を判断する。完走していれば
`private-media/work/day-2-v1/gemini-tournament-ranking.json`が生まれ、Gate 7.2本来の
残り作業（`select_judged_candidates(requires_analysis=False)`経由で採用窓・費用の比較）に
進める。それ以外はE-4残り・E-10残り（いずれもオーナーの視覚判断が必要、次にオーナーへ
両rideをまとめて見せる機会に合わせるのが効率的）。

## 183. デスクトップ層: Gate 7.2残り「判定+順位付け版とtournament版の採用窓・費用比較」を実装・実測して閉じる

lock取得・heartbeat。§182の「着手中」マーカーの続き。作業ツリーに前セッション由来の
未commit差分（`app/analysis_cli.py`の変更、`app/analysis_compare.py`・
`tests/test_analysis_compare.py`の未追跡新規ファイル）が残っており、内容を読んで
この単位そのものの実装だと確認した（`compare_selection_paths`が
`_judged_candidates`＋`select_judged_candidates`を2回——判定つきと、
`replace(candidate, analysis=None)`で判定を剥いだ`requires_analysis=False`版——
呼んで採用窓数・再生秒数・見積り費用を並べる設計。tournament実行中プロセスへの
参照は無く、既に書かれたrankingファイルを読むだけ）。他層が触った形跡（`ps aux`に
`analysis_cli`プロセス無し、`.autonomy/trip/batch.log`は9/6付で無関係）が無いこと、
`git status`の変更が全てこの単位の範囲内であることを確認し、実装の続きとして扱った。

E501（`command_compare`のdocstringが101桁）を1件修正した以外はロジックの変更なし。
全**2,546件成功**（削除前2,542件から新規4件——`test_analysis_compare.py`。
`--deselect tests/test_judged_film_end_to_end.py`、ffmpeg不在の既存事由）。Ruff check緑、
`ruff format --check`も対象3ファイルとも整形済み確認。`git diff --check`問題なし。

**実測（両ride、`app.analysis_cli compare <package>`、Gemini・GCSに一切送らない——
既に買ってある判定・順位付け・tournamentランキングを読むだけ）**:

- bridge-e2e-v1（候補187窓）: 判定+順位付け版は25窓採用・¥29.88、tournament版は
  25窓採用・¥11.73（**約61%減**）。だが**両者が共通して選んだのは25窓中5窓のみ**
- day-2-v1（候補751窓）: 判定+順位付け版は25窓採用・¥113.51、tournament版は
  25窓採用・¥47.11（**約58%減**）。**共通は25窓中2窓のみ**

費用面はroadmap 7.2の想定（≈¥11幅、tournament版が判定+順位付けの半分程度）通りだが、
**採用窓の重なりが極めて小さい**（2〜5/25＝8〜20%）ことが新しい情報。tournament版は
`VideoAnalysis`（運転手可視・駐車判定・道の種別の床、道種の同点判定）を持たないため、
判定+順位付け版が床で落とす窓を拾い、逆に判定+順位付け版が拾う窓を拾わない構造的な
違いが数値に出ている——費用だけを見てtournament版に切り替えると、作品の中身が
別物になる可能性が高いということ。**7.2の残り作業（比較の実装・実測）はこれで閉じる**
が、tournament版を実運用に採用するかどうかは別の判断（作品の質を両者で見比べる、
または`VideoAnalysis`をtournament経路にも安く持たせる案を検討する）として残る。
`docs/completion-roadmap-ja.md`のGate 7.2にこの数値を追記した。

見た目が変わる単位ではない（新しいCLIサブコマンドの追加、レンダーへの配線なし）ため
両ride再レンダー・オーナー再視聴PushNotificationは不要。実素材のGPX・動画ファイル名・
撮影時刻・座標・地名はどこにも出していない（上の数値は候補数・採用数・秒数・円のみ）。

**commit**: このセッションの一連（前セッションのWIP実装＋E501修正＋本節）。
`git push dev main`予定。公開origin へは押していない。

**支出**: ¥0（累計変わらず ≈¥776 / ¥1000。今回の`compare`はGemini/GCSに一切送らない）。

**承認待ち**: なし。

**次に推奨**: 優先順位（S2追補→Q1→E-3→…）に戻ると、次はQ1。E-4残り・E-10残りは
引き続きオーナーの視覚判断待ち。tournament版採用の是非（上記の重なりの薄さ）は
コードだけでは決められないため、次にオーナーへ相談する材料としてメモに残す。


## 184. クラウド層: `app/web/i18n.py` に境界・失敗経路のテストを追補

新規セッション。`git checkout main && git pull origin main`で追従（`main`は§182の
`app/story_caption.py`削除を含む`104074a`で追いつき済み）してから`cloud/20260908-0836`
branchを切って着手。`.venv/bin/pip install -q -e '.[dev]'`成功、収集エラーなし。
末尾（§182）は完走済みの記録で「着手中」マーカーは無く、`git status`も清潔
（別層のambient WIPはこのcontainerに存在せず）。

§181が推奨した「importはされているが境界・失敗経路が薄いモジュール」候補のうち
最有力（行数比 .24）だった`app/web/i18n.py`（442行、既存テスト`tests/test_i18n.py`は
110行・9件で、正常系の言語切替とページ配線は厚いがヘルパー関数
`_parse_language`/`configured_default_language`の境界・失敗経路は薄かった）に着手した。
GPSイベント・座標・ファイル名には一切触れない、UI文言辞書と言語解決だけの純粋な
モジュール。

**やったこと**: `tests/test_i18n.py`に9件追加（既存9件と合わせ18関数・162テストケース、
一部parametrize）。内訳: `resolve_language`の大小文字・地域サフィックス・空白の正規化
（`EN`・`en-GB`・`en_US`・前後空白・末尾ダッシュのみの`en-`）／`None`・空文字・空白・
未対応言語コード・`-en`のような不正な形の入力が例外を投げず設定済みdefaultへ
fail-safeすること／`configured_default_language`が不正・空白のみの環境変数値を
無視してdefaultへ戻ること（例外を投げないこと）／ローカル`.env`ファイルから
`RIDE_UI_DEFAULT_LANGUAGE`を読む経路と、プロセス環境変数がある場合はそちらが
優先されること／`copy_for`が返す`MappingProxyType`が実際に書き込み不可であること
（`TypeError`を確認）／`translation_keys()`が両言語のキー集合と一致すること／
両言語の値に含まれる`{count}`等のformatプレースホルダが全キーで一致すること
（一方だけプレースホルダを消す変更があれば実行時`str.format`が壊れる境界を
テストで捕捉できるようにした）。本体コード（`app/web/i18n.py`）は無変更。

**テスト**: `tests/test_i18n.py`のみ変更、162件全成功。全体**2,698件成功**
（`--deselect tests/test_judged_film_end_to_end.py`の6件のみ除外、`ffmpeg`不在の
既知事由を`which ffmpeg`で確認済み。`node`は利用可能、`qlmanage`は未使用。
それ以外に環境要因で外したテストは無い）。`.venv/bin/python -m ruff check app tests`
緑（1回で通過、追加修正なし）。`ruff format --check`は280ファイルフォーマット済み確認、
差分なし。`git diff --check`問題なし。見た目が変わる単位ではないため両ride再レンダー・
オーナー再視聴PushNotificationは不要。実素材・Gemini・GCS・資格情報・課金には
一切触れていない。

**commit**: `f10944c`（`tests/test_i18n.py`のみ）＋このhandoff追記（別commit）。
`git push -u origin HEAD`（branch `cloud/20260908-0836`、private ミラー）。main へは
直接push していない。公開origin・実素材・Gemini・GCS・資格情報・課金には
一切触れていない。

**支出**: ¥0（累計変わらず ≈¥776 / ¥1000。§180が記録したday-2-v1分¥47.11は
tournamentプロセス完走待ちで、このセッションでは確認していない）。

**承認待ち**: なし（§180由来のGate 7.2 day-2-v1 tournamentの生死確認は他層の話として
このセッションでは触れていない）。

**次に推奨**: §181が挙げた同じ切り口の残り候補、`app/places.py`（343行、テスト191行、
ratio .55——地名のプライバシー不変条件を絡めた境界）または`app/stop_kinds.py`
（321行、テスト187行、ratio .58）。あるいは他モジュールで同種の「ヘルパー関数の
境界・失敗経路が薄い」箇所を`grep`で再走査すること。Gate 7.2実測・day-2-v1 tournament
の生死確認は実素材・課金が要るためクラウド層は着手不可、デスクトップ層のみ
（次のセッションはまず`ps aux | grep analysis_cli`で確認）。E-4残り・E-10残り
（オーナーの視覚判断が必要）も同様にクラウド層は着手不可。E-5（音のつなぎ）・E-7配線は
別層が音声（ambient）レイヤーを配線中のため引き続き見送り。


## 185. クラウド層: `app/places.py` に境界・失敗経路のテストを追補

新規セッション。`git fetch origin main`で追従（origin/mainは§184の`app/web/i18n.py`
テスト追補を含む`9709bc7`まで進んでいたが、ローカルの`main`ブランチ参照は古い
`45c2eb8`のままだった——`fetch`でリモート追跡参照を更新してから`cloud/20260908-1036`
branchを`origin/main`相当のHEADから切って着手）。`.venv/bin/pip install -q -e '.[dev]'`
成功、収集エラーなし（2,708件収集）。`git status`は清潔（別層のambient WIPはこの
containerに存在せず）。末尾（§184）は完走済みの記録で「着手中」マーカーは無し。

§181・§184が挙げてきた「importされているが境界・失敗経路が薄いモジュール」候補の
うち`app/places.py`（343行、既存テスト`tests/test_places.py`は191行・12件、ratio .55）
に着手した。GPSイベント座標を受け取り基準ファイル（`places-v1`/`landmarks-v1`、
OpenStreetMap由来）と突き合わせるだけの純粋計算モジュールで、実素材のファイル・
座標・時刻には一切触れない（テストは全て合成fixture）。

**やったこと**: `tests/test_places.py`に32件追加（既存12件と合わせ44件）。内訳:
`_read`/`load_places`/`load_landmarks`の失敗経路（存在しないファイル、symlink拒否、
壊れたJSON、非object payload、辞書でない要素、必須キー欠落、型が合わない座標）／
`_files`の失敗経路（存在しないdirectory、symlinkされたdirectory拒否、非JSONファイル
無視、1件の壊れたファイルが他の正常なファイルを隠さないこと）／`PlaceMark`・
`Landmark`の空白名バリデーション／`PlacePassage`の終了<開始拒否と`middle`
プロパティ／`place_passages`の負のmerge_gap拒否・非正の半径拒否・重なる地点
（市の中の郊外）が両方報告されること・地点を離れてmerge_gapを超えて戻ると
2passageに分かれること対merge_gap内なら1passageのままなこと／`passage_at`が
該当時刻に何も無ければNoneを返すこと・同種の地点は人口の多い方が勝つタイブレーク／
`landmark_crossings`の非正のreach拒否・複数の圏内点から最も近い1点を選ぶこと／
これまでテストが皆無だった`within()`（スラック境界の等号側、空トラック、トラック
範囲の前後の点を使うこと）。本体コード（`app/places.py`）は無変更。

**テスト**: `tests/test_places.py`のみ変更、44件全成功。全体**2,734件成功**
（`--deselect tests/test_judged_film_end_to_end.py`の6件のみ除外、`ffmpeg`不在の
既知事由。`node`は利用可能、`qlmanage`は未使用。それ以外に環境要因で外したテストは
無い）。`.venv/bin/python -m ruff check app tests`緑（1回で通過）。`ruff format --check`
は282ファイルフォーマット済み確認、差分なし。`git diff --check`問題なし。見た目が
変わる単位ではないため両ride再レンダー・オーナー再視聴PushNotificationは不要。
実素材・Gemini・GCS・資格情報・課金には一切触れていない。

**commit**: `33a08f8`（`tests/test_places.py`のみ）＋このhandoff追記（別commit）。
`git push -u origin HEAD`（branch `cloud/20260908-1036`、private ミラー）。main へは
直接push していない。

**支出**: ¥0（このセッションでは変更なし。累計 ≈¥776/1000 のまま——このセッションは
実測を確認していない）。

**承認待ち**: なし。

**次に推奨**: 同じ切り口の残り候補、`app/stop_kinds.py`（321行、テスト187行、
ratio .58——場所の種類判定・屋内/私有地判定の正規表現境界）。または他モジュールで
同種の「ヘルパー関数の境界・失敗経路が薄い」箇所を`grep`ベースの行数比で再走査する
こと。Gate 7.2実測・day-2-v1 tournamentの生死確認は実素材・課金が要るためクラウド層は
着手不可、デスクトップ層のみ（次のセッションはまず`ps aux | grep analysis_cli`で
確認）。E-4残り・E-10残り（オーナーの視覚判断が必要）も同様にクラウド層は着手不可。
E-5（音のつなぎ）・E-7配線は別層が音声（ambient）レイヤーを配線中のため引き続き
見送り。


## 186. デスクトップ層: `cloud/20260908-1036`取り込み、Gate 7.3「stride 60秒」を実測して閉じる

lock取得・heartbeat。`git fetch dev`で`cloud/20260908-1036`（§185の`app/places.py`境界・
失敗経路テスト追補）を発見、`git merge --no-ff`→全2,734件成功・Ruff緑を確認して`main`に
残し、`git push dev main`後に`git push dev --delete cloud/20260908-1036`。`ps aux`に
`analysis_cli`プロセス無し、`.autonomy/trip/batch.log`は9/6付で無関係を確認。

優先順位（S2追補→Q1→…）の単位はS2追補・Q1・E-3・Q5・E-1・E-2・E-6・E-7が完了、
E-4残り・E-5・UIの残りはオーナーの視覚判断待ちか別層が音声レイヤーを配線中で
着手不可のため、次点のGate 7.2〜7.9に進み、**7.3（stride 60秒を既定に、候補数半減・
作品の質が落ちないことを2 rideで確認）**に着手した。

**設計**: `app.footage_candidates.enumerate_footage_candidates`は各recordingの
オフセットを0からstrideずつ刻むだけなので、stride 60の候補集合はstride 30で
既に買った候補集合の**厳密な部分集合**（60=30×2なので、オフセットが60の倍数の
窓だけが残る）。Q1のカーブ窓・S-1/S-7の定点窓（`turn_candidates`・`windows_at`）は
strideに依存せず独立に配置されるため、stride 60でも全て買われる。つまり
**新たにGeminiに1円も送らずに**、既に判定・順位付け済みの2 rideのデータを
オフセットでフィルタするだけでstride 60の選抜を再現できる——7.2の`analysis_compare`
と同じ「既に買ったものを読むだけ」の形。

**実装**: `app/analysis_stride_preview.py`新設。`stride_filtered_candidates`が
`JudgedCandidate.analysis.start_offset_s`を見て、基準stride（30秒）の格子に乗って
いない窓（カーブ・定点＝常に残す）と、格子に乗っていて新しいstride（60秒）にも
乗る窓だけを残す（`stride_s`をbase未満に狭める呼び出しは拒否）。`preview_stride_selection`
が`_judged_candidates`＋`select_judged_candidates`を、全候補版とフィルタ後版の
2回呼んで採用窓数・尺・重なりを比較する（`app.analysis_compare`と同型）。CLIに
`analysis_cli stride-preview <package> [--stride-s 60]`を追加（`app/analysis_cli.py`、
importのRuff並び替えを`ruff check --fix`で1件自動修正）。

**テスト**: `tests/test_analysis_stride_preview.py`新設11件（純粋関数`stride_filtered_
candidates`の格子判定・非格子窓の常時保持・基準strideでの恒等・analysis無し窓の除外・
非正/縮小strideの拒否、`preview_stride_selection`の未判定package拒否・候補ゼロ生存の
拒否（monkeypatch）・候補数減少と尺目標維持の統合テスト）。全体**2,745件成功**
（`--deselect tests/test_judged_film_end_to_end.py`の6件のみ除外、既知事由）。Ruff
check緑、`ruff format`差分なし、`git diff --check`問題なし。

**実測（両ride、`app.analysis_cli stride-preview <package> --stride-s 60`、Gemini・GCSに
一切送らない）**:

- bridge-e2e-v1: 候補187→103窓（**45%減**）。採用は両stride とも**25窓・300秒**
  （尺目標に届かないことはない）。base の25窓中20窓がstride 60でも候補として残り、
  実際に**19/25（76%）が同じ窓のまま選ばれた**（残りは近傍の代替へ）
- day-2-v1: 候補751→412窓（**45%減**）。採用は両stride とも**25窓・300秒**。baseの
  25窓中19窓が候補として残り、その**19窓全てがそのまま選ばれた**（19/19=100%）

候補数はroadmap想定通りほぼ半減（都市部の多いday-2-v1・bridge-e2e-v1どちらも
カーブ・定点窓の分だけ50%より少し甘い45%減）、**尺目標はどちらのrideも一切
削れず**、採用窓の大部分（76〜100%）が同一という結果——**7.3の「作品の質が
落ちないことを2 rideで確認」を満たした**。`docs/completion-roadmap-ja.md`の7.3に
この数値を追記し、完了とマークした。stride 60をpackageの既定にする配線
（`analysis_cli plan --stride-s 60`を毎回明示する運用から、`DEFAULT_STRIDE_S`
自体を変える判断）は、実運用に採用するかの最終判断としてオーナー確認後に
別単位で回す（tournament版採用の是非と合わせて相談する材料）。

見た目が変わる単位ではない（新しいCLIサブコマンドの追加、レンダーへの配線なし）ため
両ride再レンダー・オーナー再視聴PushNotificationは不要。実素材のGPX・動画ファイル名・
撮影時刻・座標・地名はどこにも出していない（上の数値は候補数・採用数・秒数のみ）。

**commit**: `app/analysis_stride_preview.py`・`app/analysis_cli.py`・
`tests/test_analysis_stride_preview.py`＋このhandoff追記。`git push dev main`予定。
公開origin へは押していない。

**支出**: ¥0（累計変わらず ≈¥776 / ¥1000。今回のstride previewはGemini/GCSに
一切送らない）。

**承認待ち**: なし。

**次に推奨**: stride 60を`DEFAULT_STRIDE_S`の既定にする配線判断（オーナー確認後）。
または7.5（Flash-Liteの試験、順位付け品質がFlashと一致するか）。E-4残り・E-10残り・
tournament版採用の是非はオーナーの視覚判断・相談待ち。E-5・E-7配線は別層が音声
レイヤーを配線中のため引き続き見送り。

## 187. デスクトップ層: Gate 7.6 多利用者化の第一片——利用者ごとの prefix と越境参照の禁止

lock取得・heartbeat。開始時に別層（headless の `claude -p`）が §186（Gate 7.3）を
完走して lock を解放し作業ツリーが清潔になった直後だったため、その続きとして
**Gate 7.6「多利用者化」の最初の一片**に着手した。7.5（Flash-Lite の試験）は
Gemini を呼ぶ＝支出が要るのに対し、7.6 のこの部分は**外部に1円も送らずに閉じられる**。

**なぜここから**: 判定・順位付けの経路は「1人・1台」の前提で書かれている。
バケットの prefix は自由入力の CLI フラグで既定は空——**全 ride の全窓が同じ平面に並ぶ**。
利用者が1人なら安全で、2人になった瞬間に安全でなくなる。アップロードされるのは
公道に向けたカメラが撮った proxy であり、他人の顔・ナンバー・住居が入っている。

### 置いた規則（`app/tenancy.py` 新設）

2つだけ、意図的に退屈な規則にした。

1. **利用者の物は利用者自身の prefix の下にある**。prefix は**利用者から導出**する
   （`u/<sha256の先頭32桁>`）——利用者が選べない以上、名前で他人の空間へ入り込めない。
   利用者そのものではなく digest にしたのは、オブジェクト名が
   **人に読まれ・ログに残り・clip が消えた後もバケット一覧に残る**唯一の部分だから
   （窓を録画ファイル名でなく自分のハッシュで名付けている
   `app.analysis_adapters.object_name_for` と同じ理由）。バケット一覧から読めるのは
   「利用者が何人いるか」だけで、それが誰かは読めない
2. **その prefix の外は決して読まない・送らない**。保存された URI は所有権の証拠にならない。
   出口で確かめるのは只で、package が複製されても・backup から戻されても・
   誰かが編集しても生き残る唯一の検査である

比較は**パスの区切り単位**で行う（生の文字列前方一致だと `u/abcd` が `u/abcdef/...` を
名乗れてしまい、それは別人である）。`..`・空segment・`\` は**解決せず拒否**する
——登ろうとする名前は、その時点で何のための名前かを自分で言っている。
**拒否のメッセージは拒否した対象を復唱しない**（「この URI は」と書けば、
規則が封じ込めるはずのパスをログや操作卓へ運び出してしまう）。

### 配線（既定の単独利用者経路は一切変えない）

`account_id` を渡さなければ**今まで通り**——既存の全経路・全テストは無傷。渡したときだけ:

- `upload_to_bucket(..., account_id=)`: 呼び手の `--prefix` を利用者の prefix の
  **横ではなく下**に置く（`scoped_prefix`）。run を run と見分ける用途は残り、
  利用者の空間から出る用途だけが消える
- `judge_with(analyzer, account_id=)`: **送る前に**オブジェクトが利用者のものか確かめる。
  判定は金を使う場所であり、他人のオブジェクトはこの利用者の予算で他人の ride を見ることになる
- `rank_with(transport, prompt=, account_id=)`: 順位付けは一度に複数の窓を送るので、
  **群のうち1本でも他人のものなら群ごと拒否**する
- CLI: `judge` / `rank` / `tournament` に `--account`

### テスト

`tests/test_tenancy.py` 新設15件（導出の安定性・利用者が prefix に現れないこと・
空白の正規化・`gs://` と裸名の同一視・区切り単位の比較・`u/abcd` vs `u/abcdef`・
prefix 自身はオブジェクトでない・`..`/`.`/空/`\` の拒否・拒否文が対象を復唱しないこと・
run prefix が下に付くこと・run prefix が外へ出られないこと）。
`tests/test_analysis_adapters.py` に7件、`tests/test_analysis_cli.py` に3件追補
（`--account` が uploader と comparator の**両端**に届くこと、無指定なら `None` のままであること）。

全**2,770件成功**（`--deselect tests/test_judged_film_end_to_end.py` の6件のみ除外、既知事由）。
Ruff check 緑、`ruff format --check` 286ファイル差分なし、`git diff --check` 問題なし。

### 実測（実素材2 ride、オフライン。Gemini・GCS には一切送らない）

両 ride の**実際の候補集合**に対して、利用者を2人立てて名付けと所有判定を回した。

| ride | 窓 | 自分の物と判定 | **他人から届く** | 現在の（prefix 無しの）名前が受理される数 |
|---|---|---|---|---|
| bridge-e2e-v1 | 187 | 187 | **0** | **0** |
| day-2-v1 | 753 | 753 | **0** | **0** |

実素材940窓で越境は0。付く階層は2段（`u/<digest>/…`）。
**最後の列が本題**である: 今バケットにある名前は prefix を持たないので、
**どの利用者からも受理されない**——多利用者化した時点で既存オブジェクトは
移設か再アップロードが要る、という事実が測定として出た（今は単独利用者なので実害なし）。

見た目が変わる単位ではない（レンダーへの配線なし）ため両 ride 再レンダー・
オーナー再視聴の依頼は不要。実素材の GPX・動画ファイル名・撮影時刻・座標・地名は
どこにも出していない（上の数値は窓数と件数のみ）。

**支出**: ¥0（累計変わらず ≈¥776 / ¥1000。この単位は外部に何も送らない）。

**承認待ち**: なし。

**7.6 の残り**（この片では**やっていない**こと）: 認証そのもの（利用者をどう名乗らせるか）、
署名付き URL、同意・保持期間・削除。prefix の分離はそれらの土台であって代わりではない。

**次に推奨**: 7.6 の続き（保持期間と削除——`u/<digest>` 配下を丸ごと消せる形になったので、
削除は「prefix を消す」1操作で書ける）。または stride 60 を `DEFAULT_STRIDE_S` の
既定にする配線判断（オーナー確認後）。7.5（Flash-Lite）は支出が要る。

## 188. デスクトップ層: Gate 7.6 の続き——保持期間と削除

lock取得・heartbeat。`git fetch dev` の `cloud/*` branch は無し（取り込むものなし）。
着手中の単位は無かったため、§187 が「次に推奨」と書いた **7.6 の続き——保持期間と削除**を
取った。品質の単位（E-5）は別層の音声レイヤーが commit されなかった（`app/story_ambient.py`
は存在しない）ため技術的には空いたが、E-5 の実際の障害は「作品は素材の音を捨てる」という
**製品判断**の方であり、無音既定（S4）を勝手に覆すことはしない。この単位は外部に1円も
送らず、削除も実バケットには一切行っていない。

### なぜ「保持」ではなく「削除」から書いたか

送っている縮小コピーは**公道を撮った映像**であり、そこに写っている人は何にも同意していない。
同意したのは乗り手だけである。この非対称が保持期間の問題の全てで、正直な答えは
**声に出して言える程度に小さい数字**しかない（`docs/cloud-architecture-ja.md` §5）。

同時に、縮小コピーはこのパイプラインで**最も価値の低いもの**でもある。金で買っているのは
判定（数百バイトの文章）であり、作品はそこから切られる。判定が書かれた時点で、
読み元のコピーには用が無い。持ち続けるのは慎重さではなく、誰も対価を払っていない負債である。

### 置いた規則（`app/retention.py` 新設）

3つ、また意図的に退屈な規則にした。

1. **削除は prefix を単位に行い、名前の一覧では行わない**。一覧は package から来るが、
   package は編集され・欠け・backup から戻され・単に失われる。そして
   **どの package も覚えていないオブジェクトこそ、残してはいけないもの**である。
   完全性が「手元にあるかもしれないファイル」に依存しない唯一の範囲が、利用者の prefix である。
   このモジュールは package を一切読まない
2. **一覧から返ってきた名前は、削除する前にもう一度確かめる**。こちらが訊いたのは1つの
   prefix だが、答えは自分が書いたのではない client からネットワーク越しに届く。
   **訊いたことは証拠ではない**。検査は只で、規則は `app.tenancy` が既に持っている
   ——削除はこの codebase がバケットに対して行う最も破壊的な操作なので、
   送信と同じ門を通す（緩い方ではなく）
3. **prefix の外を答えた一覧は sweep を止める**。読み飛ばすのでも濾すのでもなく、止める。
   1人の空間を訊いて別の物が返ってきたなら、相手はこちらが思っているものではない
   ——それは削除を始める瞬間ではない

拒否文と要約は**オブジェクト名を復唱しない**（`app.tenancy` と同じ規則）。
`SweepPlan.summary()` が返すのは件数だけで、`due` に入る名前は削除の実行にしか渡らない
——計画は自然に印刷される物であり、印刷が言ってよいのは「何件か」であって「どれか」ではない。

**`forget_account` は「保持期間0の sweep」ではない**。それだと各オブジェクトに
「期限は過ぎたか」を訊いてしまい、**未来の時刻が打たれたオブジェクト**（書いた機械の時計が
ずれていた、という誰も気づかない類のもの）が「いいえ」と答えて、全消去の要求を生き延びる。
黙って残す削除は失敗する削除より悪いので、間違え得る問いを一切しない別の経路にした。

### 配線

- CLI `analysis_cli retention`: `--bucket` `--account` `--prefix` `--retention-days`（既定30）
  `--forget` `--i-approve-deletion`。**package 引数を取らない**（消すべきはバケットにある物で、
  package は「上げるつもりだった物」の記録に過ぎない）。承認が無ければ**一覧して判断して止まる**
  ——`judge` が支出の前に置いている壁と同じ形。既定の保持期間は30日、上限は365日
  （それを超える期間は方針ではなく方針の不在である）
- 期間は**日単位の整数のみ**、時刻は**タイムゾーン必須**（素の時刻を機械間で比べると、
  早く消すか長く残すかを黙って間違える）。期限ちょうどは「遅い」側に倒す

### テスト

`tests/test_retention.py` 新設31件（期限の算術・境界の向き・タイムゾーン違いの同一時刻・
素の時刻の拒否・期間の上下限と bool 混入・要約が名前を持たないこと・他人の1件で計画ごと
止まること・拒否文が対象を復唱しないこと・`run-1` と `run-10` の区別・prefix 自身は
オブジェクトでないこと・未来時刻でも forget は消すこと・承認なしでは1件も消えないこと・
他人の名前が1つ混じれば**1件も消さない**こと・`..` を解決せず拒否すること・
**prefix を無視する client が sweep を止めること**・どの package も覚えていない
orphan が sweep で消えること）。`tests/test_analysis_cli.py` に7件追補
（承認の既定 off・payload が名前を持たないこと・`--forget` が aged sweep を通らないこと・
package 引数を取らないこと・拒否が traceback にならないこと）。

全**2,808件成功**（`--deselect tests/test_judged_film_end_to_end.py` の6件のみ除外、既知事由）。
Ruff check 緑、`ruff format --check` 288ファイル差分なし、`git diff --check` 問題なし。

### 実測（実素材2 ride、完全オフライン。GCS には接続せず、実バケットからは1件も消していない）

両 ride の**実際の候補集合**に対し、アップロードと同じ規則でオブジェクト名を組み立て、
半数を保持期間より古く・半数を内側に置いて sweep を回した。

| ride | 窓 | 30日で期限切れ | 保持 | forget が届く | **他の利用者が届く** | **現在の（prefix 無しの）名前に届く** |
|---|---|---|---|---|---|---|
| bridge-e2e-v1 | 187 | 94 | 93 | 187 | **0** | **0** |
| day-2-v1 | 751 | 376 | 375 | 751 | **0** | **0** |

実素材938窓。「消して欲しい」に対して **forget は利用者の物に100%届き、他人の物には0%届く**。

**最後の列が本題である**。§187 は「今バケットにある prefix 無しの名前は、多利用者化した
時点でどの利用者からも**読めない**」と測った。同じ名前は**消せない**ことが今回出た
——**届かない保持期間の約束は約束ではない**。既存オブジェクトの移設は、多利用者化の
「あった方がよい後片付け」ではなく、保持ポリシーを名乗るための前提条件である。
（現在は単独利用者・実害なし。移設が要るという事実を測定として残す）

見た目が変わる単位ではない（レンダーへの配線なし）ため両 ride 再レンダー・
オーナー再視聴の依頼は不要。実素材の GPX・動画ファイル名・撮影時刻・座標・地名は
どこにも出していない（上の数値は窓数と件数のみ）。

**支出**: ¥0（累計変わらず ≈¥776 / ¥1000。この単位は外部に何も送らない）。

**承認待ち**: なし。

**7.6 の残り**（この片では**やっていない**こと）: 認証そのもの、署名付き URL、
同意（何を預かり何をしないかの表示）、既存オブジェクトの移設、
バケット側のライフサイクル規則との二重化（この sweep は端末から回す形しかない）。

**次に推奨**: 7.6 の続き（署名付き URL、または同意表示）。
または stride 60 を `DEFAULT_STRIDE_S` の既定にする配線判断（オーナー確認後）。
7.5（Flash-Lite）は支出が要る。E-5 は「素材の音を使うか」の製品判断がオーナー待ち。

### 音楽（2026-09-08 夜）

Q4「既定は無音」は済んでいたが、残りは未着手のままだった。今回オーナーが選び直した。
オーケストラ系は「幻想的でダメ」、ロックも「合わない」、最終的にオーナー自身が
free-stock-music の直リンクで **Wandering / Numall Fix**（126 BPM、5分54秒、CC BY 3.0）
を指した。速く、明るく、押していく曲。作品の尺（6分08秒）に近くループがほぼ出ない。

- 直リンクは hotlink 防止で HTML を返す。Referer を付けると取れる。
- この配布元は**ライセンスが求める以上の1行**（配布元の明記）を求めるので、カタログに
  `also_credit` を足して、作品が印字するクレジットが求められたとおりになるようにした。
- デモは**絵を再エンコードせず**音だけ差し替えた（`mix_music_into_film` は `-c:v copy`）。
  全フレーム検査の結果がそのまま生きる。

## 189. クラウド層: `app/demo.py`（合成専用デモ）に単独のテストファイルを新設

`app/demo.py` は300行あるが、単独の `tests/test_demo.py` を持たず、他の複数のテスト
ファイル（`test_director.py`・`test_video_catalog.py`・`test_story_agent_localization.py`
等）から間接的に使われているだけだった。この module は完全に合成データのみ
（固定の GPS event・固定の座標・固定の映像 asset 名）で、実素材・Gemini・GCS への
参照は一切無いため、この単位の対象として選んだ。

`tests/test_demo.py`（新規20件）で、間接利用では踏まれていなかった境界・失敗経路を
固定した:

- `run_demo` が未知の scenario / 未知の言語文字列を `ValueError` で拒否すること
- `run_demo` が enum だけでなく素の文字列（web 層のクエリパラメータを想定）の言語も
  受け付けること
- `missing_asset`（対応する素材が無い）と `gemini_unavailable`（`ConnectionError` を
  投げる合成 transport）が、どちらも**沈黙で受理／拒否せず** `needs_human_review` に
  倒れて安全側に失敗すること
- `build_synthetic_director_events` の4件が時系列順・非重複であること、座標を一切
  持たないこと、intensity が climax へ向けて上がり到着で下がる弧を描くこと
  （docstring が約束する「合成の旅の弧」を実際に検査）
- `build_demo_candidate_edit_plan` が docstring どおり**意図的に不完全**であること
  （`CandidatePlanStatus.NEEDS_MORE_EVIDENCE`・`is_ready_for_edit is False`・
  少なくとも1clipが証拠待ちのまま）を具体的に固定し、将来の変更が偶然これを
  「完備」にして web/CLI の「未完了」経路のテストを踏まなくなる事故を検出できるように
  した
- 却下理由の文言が event_id を復唱しないこと（`app.tenancy`・`app.retention` と同じ
  「要約は対象を復唱しない」規則をこの module にも適用して確認）

**テスト**: 全**2,829件成功**（`--deselect tests/test_judged_film_end_to_end.py` の6件のみ
除外。この container に `ffmpeg` が入っておらず、既知の環境要因）。Ruff check 緑、
`ruff format --check` 289ファイル差分なし、`git diff --check` 問題なし。

実素材・GPX・Gemini・GCS には一切触れていない。支出¥0。承認待ちなし。

**次に推奨**: `app/agents/story_agent.py`・`app/deployable_agent.py`・
`app/agent_runtime/adk_agent.py` はテスト比率が低いが ADK/Vertex の import に触れる
ため、まず「合成 fixture だけで境界を足せるか」を切り分けてから着手すること。
または roadmap Gate 7 の E-1〜E-7 のうち計算だけの部分（`app/chapter_order.py` は
実装済みだが未配線——配線判断はオーナー決定待ちなので、配線ではなくモジュール単体の
境界テスト追補が対象）。

## 190. `app/agents/story_agent.py`・`app/deployable_agent.py`・
`app/agent_runtime/adk_agent.py` の境界・失敗経路テストを追補

第189節が挙げた3件のうち、まず「合成 fixture だけで境界を足せるか」を切り分けた。
3件とも ADK/Vertex を import はするが、いずれも**モジュール読み込みとオブジェクト構築が
ネットワークに触れない**（既存テストが既にオフラインで通っている）ため、全て対象にした。

- **`app/agents/story_agent.py`（`RuleBasedStoryAgent`、ADK 非依存の決定論的コア）**:
  既存テストは `PrototypeOrchestrator` 経由の低重要度1本と、`app.demo` のシナリオ4本
  （固定値のみ）だけで、この module の3つの決定関数を直接・境界値で踏んでいなかった。
  `decide_from_event` の重要度閾値0.60ちょうど・僅かに下・条件を満たす3種の
  `event_type` すべて、`update_with_video` の関連度閾値0.60ちょうど・僅かに下、
  `needs_human_review` が生の文字列を受け付けること（`StoryEvidenceFailure(failure)`
  の cast）と未知の文字列を拒否すること、既定言語が日本語であることを追補（新規11件）
- **`app/deployable_agent.py`**: 渡した model 文字列がそのまま `Agent.model` に届くこと、
  instruction が実素材を要求しない旨を含むこと、そして**この module が
  `app.agent_runtime.adk_agent` と独立に持つ固定 event が、意図せず乖離していないこと**
  （2つの `get_synthetic_*_event` が同じ辞書を返す）を追補（新規3件）。最後の1件は
  「意図的な重複」（deploy 経路が `app.agent_runtime` 全体を import せずに済むため）を
  実際に固定する回帰検査で、docstring の主張をテストにした
- **`app/agent_runtime/adk_agent.py`**: `run_synthetic_adk_demo`（非同期、events の
  `tool_called`／`final_response_received` を読み取り、どちらか欠ければ安全側に失敗する
  経路）が**丸ごと未テスト**だった。`google.adk.runners.InMemoryRunner` を偽の
  クラス（`monkeypatch.setattr(adk_agent_module, "InMemoryRunner", ...)`）に差し替え、
  Gemini や Vertex に一切触れずに: 成功経路（tool 呼び出し＋テキストの両方）・
  tool 呼び出しとテキストが別 event に分かれる場合の集計・tool 未呼び出しでの拒否・
  テキスト無しでの拒否・空白のみのテキストでの拒否・runner 例外が `AdkSyntheticRunError`
  に chain されること（`__cause__` を確認）・設定不備が `InMemoryRunner` 構築より前に
  拒否されること（実物の `InMemoryRunner` を差し替えないまま確認）、`AdkSyntheticRun.
  to_dict()` の中身、を固定した（新規9件）。`pytest-asyncio` は入っていないため、
  同期テストの中で `asyncio.run(...)` を使う形にした（プラグイン追加なし）

**テスト**: 全**2,857件成功**（`--deselect tests/test_judged_film_end_to_end.py` の6件
のみ除外、既知事由。新規23件）。Ruff check 緑、`ruff format --check` 291ファイル
差分なし、`git diff --check` 問題なし。

実素材・GPX・Gemini・GCS には一切触れていない。支出¥0。承認待ちなし。

**触れなかったもの**: `app/web/private_journey_console.py`・`app/web/server.py`
（未commitの変更あり）、`app/data_handling_disclosure.py`・
`tests/test_data_handling_disclosure.py`（未追跡、7.6「同意表示」らしき別層の作業と
見られる）——このループの開始時点で既に作業ツリーにあり、自分が変更したものではないため
規約どおり触っていない。

**次に推奨**: roadmap Gate 7 の E-1〜E-7 のうち計算だけの部分
（`app/chapter_order.py` は実装済みだが未配線・既存21件のテストで境界は概ね埋まっている
ため優先度は下がる）。または `app/agent_runtime/agent_platform.py`
（`run_hosted_synthetic_agent_runtime` 等、adk_agent.py と同型の event 解析ロジックを
持つ可能性があり、同じ手法で境界テストを追補できるか未確認）。

## 191. クラウド層: `app/agents/story_agent.py` を直接叩く境界テストを新設（並行作業）

第189節の推奨どおり `app/agent_runtime/adk_agent.py`・`app/deployable_agent.py` を見たが、
どちらも `google.adk` を最上位 import で持つため、この container では `pip install
-e '.[dev]'`（重い依存だが今回は成功した）なしには収集できない。切り分けの結果、
`app/agents/story_agent.py`（`RuleBasedStoryAgent`）は `app.contracts` と
`.story_planner` の enum しか import せず、完全に合成 fixture だけで境界を足せる
候補と判断してこちらを選んだ。

**merge時の注記**: この単位はデスクトップ層の第190節と同じ対象（`RuleBasedStoryAgent`の
0.60閾値境界）を並行して選んでいた。ファイルは競合しなかった（デスクトップ層は
既存の`tests/test_story_agent.py`に追補、こちらは新規`tests/test_story_agent_unit.py`）
ため、両方をそのままmainへ残した。カバレッジは一部重複するが、それぞれ異なる観点
（デスクトップ層は`event_type`3種の網羅と既定言語、こちらは`asset_name_hint`・
`event_id`の引き継ぎと「要約が対象を復唱しない」規則の全経路確認）を持つため、
統合整理は次の単位で判断すること。`app/deployable_agent.py`・
`app/agent_runtime/adk_agent.py`の境界テストは第190節で先に閉じている。

既存の `tests/test_story_agent.py`・`tests/test_story_agent_localization.py` は、
この agent を `PrototypeOrchestrator` や `app.demo.run_demo` 経由でしか叩いておらず、
agent 自身の3つの公開メソッドを直接呼ぶテストが無かった。`tests/test_story_agent_unit.py`
（新規28件）で、間接利用では踏まれていなかった境界を固定した:

- `decide_from_event` の `importance_hint >= 0.60` の境界（ちょうど0.60は証拠待ちへ、
  0.599999は却下）と、`event_type` が証拠対象の3種のどれでもない場合は
  importance_hint がどれだけ高くても却下されること（両方の条件が要ることの確認）
- `update_with_video` の `story_relevance_score >= 0.60` の境界（同じ形）と、
  却下後も `needs_video_evidence` は `True` のまま（証拠は使われたが確証しなかった、
  という意味であることを固定——将来の「整理」で偶然反転しないように）
- `asset_name_hint`・`event_id` が `decide_from_event` → `update_with_video` を
  通して引き継がれること
- `needs_human_review` の2つの失敗理由を両言語で固定し、`app.demo` が使う「素の
  文字列」も enum と同じ結果になること、未知の理由文字列は `ValueError` で拒否
  されること
- `app.tenancy`・`app.retention`・`app.demo` と同じ「要約は対象を復唱しない」
  規則をこの module にも適用し、全ての決定経路・両言語で reason 文が event_id を
  含まないことを確認

**テスト**: 全**2,857件成功**（`--deselect tests/test_judged_film_end_to_end.py` の6件
のみ除外。この container に `ffmpeg` が無く、既知の環境要因）。今回の切り分けのため
`.venv/bin/pip install -q -e '.[dev]'` を実行し成功した（`google-adk`・`vertexai`
等を含む収集エラー10件が解消、2,835件収集）。Ruff check 緑、`ruff format --check`
290ファイル差分なし、`git diff --check` 問題なし。

実素材・GPX・Gemini・GCS には一切触れていない。支出¥0。承認待ちなし。

**次に推奨**（第190節で`app/deployable_agent.py`・`app/agent_runtime/adk_agent.py`は
閉じたため更新）: roadmap Gate 7 の E-5（音のつなぎ）は他層が音声を配線中のため避け、
E-7（`app/story_timelapse.py`）の計算だけの部分に既存テストの境界追補の余地が無いか
確認すること。または`tests/test_story_agent.py`・`tests/test_story_agent_localization.py`・
`tests/test_story_agent_unit.py`の3ファイルに広がった`RuleBasedStoryAgent`のテストを
整理する（重複の解消は正しさに影響しないため優先度は低い）。

## 192. `app/story_timelapse.py`（E-7 判定ロジック）に境界テストを5件追補

第191節の推奨どおり、E-7（`app/story_timelapse.py`、タイムラプス判定だけを持ち配線は
`app/story_ambient.py`のcommit待ち）に既存テストの境界追補の余地が無いか確認した。
既存20件は主要な境界（`MINIMUM_HALT_S`・`MINIMUM_GAP_S`ちょうど／僅かに下、表示尺の
飽和・線形補間、`ValueError`系の入力検証）を広く覆っていたが、以下5点が抜けていた:

- `decide_timelapse`の`UNFILMED_GAP`分岐は`decide_timelapses`経由で「Noneでない」ことしか
  確認されておらず、`LONG_HALT`分岐にある完全一致（`TimelapseDecision`の中身）の検査を
  持っていなかった
- `TimelapseDecision.__post_init__`は`source_duration_s`・`display_s`とも`nan`・負数は
  検査していたが、`math.inf`（`isfinite`が拾うはずの経路）は未検査だった
- `decide_timelapses`は「一部None・一部Noneでない」（既存）と「空リストを拒否」（既存）
  はあったが、「全件が閾値未満でNone」と、「1件でも不正な値（負数）があれば全体を
  `TimelapseDecisionError`で落とす」（1日分の計画を黙って一部だけ計画しない、という
  安全側の失敗）が固定されていなかった

`tests/test_story_timelapse.py`に5件追加（20→25件）。実素材・GPX・Gemini・GCSには
一切触れていない。支出¥0。

**テスト**: 全**2,888件成功**（`--deselect tests/test_judged_film_end_to_end.py`の6件のみ
除外、既知事由）。Ruff check緑、`ruff format --check`292ファイル差分なし、
`git diff --check`（自分の変更ファイルのみ）問題なし。

**触れなかったもの**: `app/web/private_journey_console.py`・`app/web/server.py`
（未commitの変更あり）、`app/data_handling_disclosure.py`・
`tests/test_data_handling_disclosure.py`（未追跡、7.6「同意表示」の別層作業と
見られる）——この節の開始時点で既に作業ツリーにあり、自分が変更したものではないため
規約どおり触っていない（前節から継続、依然未commitのまま）。`dev`の`cloud/*` branchは
無かった（`git fetch dev`で確認）。

**次に推奨**: E-7自体の判定ロジックはこれで境界を広く固めたため、`tests/test_story_agent.py`・
`tests/test_story_agent_localization.py`・`tests/test_story_agent_unit.py`の3ファイルに
広がった`RuleBasedStoryAgent`のテスト整理（優先度は低い）。または他に決定だけ持ち
配線待ちのmodule（`app/story_color.py`・`app/story_audio.py`等）で同様の境界確認が
できないか。7.5（Flash-Liteの試験）は実素材の判定支出を伴うため、次の実素材ループで
検討すること。

## 193. クラウド層: `app/story_copy_probe.py`の直接境界テストを新設

第192節の推奨どおり`app/story_color.py`・`app/story_audio.py`を確認したが、両方とも
既存テスト（19件・22件）が既に閾値ちょうど／僅かに下、中央値の頑健性、空リスト・
非有限値・不正符号の拒否、既定target/baselineの導出、入力順の保持、を広く覆っており、
抜けている境界を見つけられなかった。代わりに`app/*.py`のテスト対比表を作り、行数に対して
テストが薄いか皆無のmoduleを洗い出したところ、`app/story_copy_probe.py`（58行）が
**単独のテストファイルを持たない**ことが分かった。

この module の中核（`GeminiStoryCopyGenerator`）は`tests/test_story_copy.py`が広く
覆っているが、`run_synthetic_story_copy_probe()`自身の配線——設定済み transport の
model 名が結果に届くこと、常に英語出力を要求すること、`synthetic_input`／
`private_data_used`フラグの値、失敗が安全側の`GeminiStoryCopyError`に化けて
provider の生エラー文が漏れないこと——は一度も直接テストされていなかった。
`VertexAIGeminiStoryCopyTransport.from_environment`をモンキーパッチした偽 transport
（`tests/test_gemini_probe.py`と同じ形。ネットワークなし）で、`tests/test_story_copy_probe.py`
（新規7件）を作り、以下を固定した:

- 設定済み transport の`model`文字列がそのまま結果の`model`に届くこと
- 常に日本語の demo story plan から英語出力を要求すること（prompt に"in English"が
  含まれることも確認）
- `synthetic_input`が常に`True`、`private_data_used`が常に`False`であること
- 正常応答での`chapter_count`・`response_received`の値
- transport が例外を投げた場合、`GeminiStoryCopyError`に安全に化けて provider の
  生エラー文（"sensitive provider response"）が漏れないこと
- 応答の構造が変えられている場合（demo plan の3つの chapter_id と不一致・必須
  フィールド欠落）も同じ安全側の失敗になること
- `SyntheticStoryCopyProbe.to_dict()`が6つの安全なフィールドだけを持ち、それ以上
  でも以下でもないこと

**テスト**: 全**2,889件成功**（`test_judged_film_end_to_end.py`の6件のみ除外。この
container に`ffmpeg`が無く、既知の環境要因。新規7件）。Ruff check緑、
`ruff format --check`291ファイル差分なし、`git diff --check`（自分の変更ファイルの
み）問題なし。

実素材・GPX・Gemini・GCSには一切触れていない。支出¥0。承認待ちなし。作業開始時点で
作業ツリーは他層の未commit差分なくクリーンだった。

**次に推奨**: `tests/test_story_agent.py`・`tests/test_story_agent_localization.py`・
`tests/test_story_agent_unit.py`の3ファイルに広がった`RuleBasedStoryAgent`のテスト
整理（優先度は低い、継続）。または`app/rider_in_frame.py`（82行・既存7件）・
`app/analysis_compare.py`（112行・既存4件）のように行数に対してテストが薄いmodule
を同様に切り分ける（ただし`analysis_*`系はFFmpeg proxyの実測を前提にしている可能性が
高く、まず「合成fixtureだけで境界を足せるか」を切り分けてから着手すること）。

## 194. クラウド層の取り込み＋`app/story_color.py`・`app/story_audio.py`に境界テストを追補

**クラウド層の取り込み**: 単位の前に`git fetch dev`したところ`cloud/20260908-1635`
（`app/story_copy_probe.py`の直接境界テスト7件新設）を発見。`git merge --no-ff`で
取り込み、全2895件成功・Ruff緑を確認して`main`に残し、`dev`のbranchを削除
（§193として記録済みの内容と同じ、節番号のみここで統合）。

**次に選んだ単位**: 第192節の推奨（決定だけ持つ他moduleの境界確認）に沿って
`app/story_color.py`（E-6、露出補正の計算、実際のE-6配線はFFmpeg `normalize`
フィルタの方で別実装——このmoduleは使われていない並行の決定ロジック）と
`app/story_audio.py`（E-5、クロスフェード長・風切り減衰の計算、配線待ち）を確認した。
既存テスト（18件・20件）は境界を広く覆っていたが、`math.isfinite(x) or x <=/>= 0`
という形の検査で、`or`の「符号」半分だけがテストされ「有限性」半分（`nan`・`inf`が
符号条件をすり抜けるケース）が未検査だった点が、第192節で`TimelapseDecision`に
見つけたのと同じ形で残っていた:

- `story_color.brightness_correction`: `max_correction=math.nan`・`math.inf`
  （正の値なので`<= 0`はすり抜けるが`isfinite`で拒否されるべき）、`luma`・`target`の
  `math.inf`、`target`の負値（既存は`luma`の負値と`target`の`nan`のみ検査していた）
- `story_audio.wind_attenuation_db`: `threshold_db`・`attenuation_db`の`math.nan`・
  符号条件をすり抜ける側の`math.inf`／`-math.inf`、`rms`・`baseline`の`-math.inf`
  （既存は`math.inf`側のみ）

`tests/test_story_color.py`に4件、`tests/test_story_audio.py`に4件追加
（計8件、18→22件・20→24件）。実素材・GPX・Gemini・GCSには一切触れていない。支出¥0。

**テスト**: 全**2898件成功**（`--deselect tests/test_judged_film_end_to_end.py`の6件のみ
既知事由で除外）。Ruff check緑、`ruff format --check`両ファイル差分なし、`git diff --check`
（自分の変更ファイルのみ）問題なし。

**触れなかったもの**: `app/web/private_journey_console.py`・`app/web/server.py`
（未commitの変更あり）、`app/data_handling_disclosure.py`・
`tests/test_data_handling_disclosure.py`（未追跡、7.6「同意表示」の別層作業と
見られる）——この節の開始時点で既に作業ツリーにあり、自分が変更したものではないため
規約どおり触っていない（前節から継続、依然未commitのまま）。

**次に推奨**: 同じ`isfinite`半分の検査漏れパターンが他の決定だけのmodule
（`app/story_hold.py`・`app/story_pacing.py`等の数値境界を持つ関数）にも
残っていないか確認する。または`tests/test_story_agent.py`系3ファイルの整理
（優先度は低い、第192節から持ち越し）。

## 195. 7.6 既存オブジェクトの移設——`app/tenant_migration.py`

第187節（利用者ごとの prefix）と第188節（保持期間と削除）は、どちらも同じ壁で終わって
いた。バケットに既にある object は `<窓のhash>.mp4` で前に何も付いておらず、**どの利用者の
ものでもない**。だから sweep も `forget_account` も届かず、`require_own_object` はどこへも
送らない。届かない保持期間の約束は約束ではないので、これは片付け仕事ではなく多利用者化の
前提条件である（両節がそう書いていた）。

`app/tenant_migration.py` を新設。規則は4つ、前の2 module と同じく意図的に鈍い:

- **行き先は導出であって選択ではない**。今ある名前の前に利用者の prefix を置くだけ。
  だから二つの object が一つの名前に落ちることが原理的になく、呼び手が言い換えで
  他人の空間を狙うこともできない。`gs://` でも素の名前でも同じ答えになる。
- **複製 → 確認 → 削除の順**。複製の後で落ちれば重複が残り、逆順なら、他人の顔が
  取り戻せた場所に穴が残る。**重複は請求書で、穴は誰かの ride** ——どちらなら説明
  できるかで順序が決まる。行き先が既にある場合は複製を飛ばして削除だけ進む
  （名前は元の名前から決まる純関数で、この codebase の object 名は窓の hash なので、
  同じ名前は同じ中身。中断した移設がそのまま再開できる）。
- **既に利用者空間にある object はその場に置く**。移設の途中のバケットは再開時の
  正常な状態なので、数えて素通りする（停止しない）。他人の prefix のものも同じ。
- **停止するのは、tenant root の下にいてどの利用者のものでもない object**
  （`u/a.mp4`、digest が欠けた `u/abc/...`）。この codebase が作れない状態であり、
  どの利用者のつもりだったかを当てることは、唯一取り返しのつかない誤りだから。
  `..`・空segment・`\` を含む名前は解決せず拒否（`app.tenancy` と同じ規則）。

`move_objects` は削除と同じ壁（`approved=True`）を持ち、**1バイトも複製する前に**全ての
行き先を利用者に照らして検査する（途中で検査すると、半分だけ移った prefix が完了した
ものと見分けられなくなる）。計画も拒否文も件数だけを持ち、object 名は決して持たない。
CLI は `python -m app.analysis_cli migrate --bucket … --account …`。
`--i-approve-migration` が無ければ**一覧して判断して止まる**。package 引数も `--prefix`
も取らない——移設が要るのは、どの run もどの package も覚えていない object だから。

**実測（実素材2 ride、940窓、外部送信なし・支出¥0）**:

| | bridge-e2e-v1（187窓） | day-2-v1（753窓） |
|---|---|---|
| 移設前に利用者から届く数 | 0 / 187 | 0 / 753 |
| 移設後に利用者が所有する数 | 187 / 187 | 753 / 753 |
| 移設後に他人から届く数 | 0 | 0 |
| バケットの object 数（前→後） | 187 → 187 | 753 → 753 |
| 2度目の実行が動かす数 | 0（冪等） | 0（冪等） |

第188節が測った壁がそのまま埋まった: **`forget_account` と期限 sweep の到達は
移設前 0/940、移設後 940/940**。object 数が増えないことは、複製が残っていない
（削除まで完走した）ことの確認でもある。

**テスト**: 全**2,942件成功**（`--deselect tests/test_judged_film_end_to_end.py` の6件のみ
既知事由で除外。新規43件——`tests/test_tenant_migration.py` 38件、
`tests/test_analysis_cli.py` に5件）。Ruff check 緑、`ruff format` 済み、
`git diff --check`（自分の変更ファイルのみ）問題なし。

**触れなかったもの**: `app/web/private_journey_console.py`・`app/web/server.py`
（未commitの変更あり）、`app/data_handling_disclosure.py`・
`tests/test_data_handling_disclosure.py`（未追跡、7.6「同意表示」の別層作業と
見られる）——この節の開始時点で既に作業ツリーにあり、自分が変更したものではないため
規約どおり触っていない（第192節・第194節から継続、依然未commitのまま）。`dev` の
`cloud/*` branch は無かった（`git fetch dev` で確認）。

**次に推奨**: 7.6 の残りは「認証そのもの」「署名付きURL」「同意表示（別層が着手中）」
「バケット側ライフサイクル規則との二重化」。このうち**署名付きURL**が、既に閉じた
`app.tenancy`・`app.retention`・`app.tenant_migration` の上に素直に載る次の一片
（`require_own_object` を通してから署名する、有効期限は保持期間より短い、署名の
失敗は対象を復唱しない）。バケット側ライフサイクル規則との二重化も、
`app.retention` の定数から規則を**生成して読み比べるだけ**の形なら外部送信なしで
閉じられる。認証そのものは範囲が大きく、オーナー判断（どの身元提供者か）が要る。

着手中: 7.6 署名付きURL（`app/signed_links.py`）（2026-09-09 03:45 JST、デスクトップ層）
