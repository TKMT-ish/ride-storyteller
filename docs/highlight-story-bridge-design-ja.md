# Highlight discovery ↔ Story Plan / evidence review 接続設計（Proposed）

> 作成日: 2026-09-01
> 状態: **Proposed**。未実装・未承認。[current-system-handoff-ja.md](current-system-handoff-ja.md)
> §6「優先度高」の1項目「ハイライト研究とStory Plan／candidate edit／evidence reviewが
> 別系統」、および§7の論点3「GPS event起点と映像起点のhighlight discoveryを統合する
> 方法」に対する設計案。実装前にユーザー判断が必要な点を明示する。
> 本書はコードを変更しない。承認された範囲だけを次段階で実装する。

## 1. 現状の分断（事実確認）

現在、確認済みイベントに至る経路が2系統あり、互いに接続されていない。

| | GPS起点（既存） | 映像起点（既存） |
|---|---|---|
| 候補の単位 | `GpsEvent`（`event_id`、location、start/end time） | `QualitySelection`（`asset_id` + `start_offset_s` + `duration_s`、video-relative） |
| 生成元 | `app/gps/extract_events.py` | `app/video/highlight_discovery.py` + `highlight_quality.py` |
| 人手確認contract | `app/video/review.py` の`LocalEvidenceReview`（`event_id`キー、`CONFIRMED/REJECTED/AWAITING`） | `app/video/highlight_review.py` の`HighlightReview`（opaque `candidate_id`キー、`approved/rejected/awaiting`＋固定理由code） |
| Story Planへの接続 | `app.gps.extract_events` → Story Planner → `ResolvedCandidateClip`（`app/video/catalog.py`） | なし |
| Director/Editorへの接続 | `LocalEvidenceReview`の`CONFIRMED`のみ | なし |

`highlight_quality.py:117-131`の`ScoredHighlightWindow`と`QualitySelection`
（`highlight_quality.py:134-149`）は、絶対時刻・GPS座標を保持していない。一方
`highlight_discovery.py:721-791`の`_gps_features`は、各windowの絶対
`start`/`end` datetimeを内部で計算し、その区間のroute pointを既に参照している。
つまり「映像window ↔ 絶対UTC時刻 ↔ GPS座標」の対応は**計算済みだが、
出力contract（`WindowFeatures`／`HighlightWindowEvidence`／`QualitySelection`）
には保持されていない**。これが接続を阻む一次的なギャップである。

## 2. 設計方針

判断の重複を避けるため、次の原則を維持する。

1. **映像内容だけで物語上の出来事を確定しない**という既存原則（handoff §1）は、
   映像起点の候補にも同様に適用する。`HighlightReviewStatus.APPROVED`は
   「この区間は物語に使える視覚的根拠がある」という人手判断であり、
   これを`GpsEvent`の存在証明として転用してよい、というのが本設計の中心判断である
   （§4で明示的なユーザー判断事項とする）。
2. 既存の2つの人手確認contract（`LocalEvidenceReview`、`HighlightReview`）は
   **どちらも変更しない**。統合は新しい橋渡し層（bridge）で行い、既存の
   fail-closed契約・opaque ID方針・スキーマ互換性を壊さない。
3. bridgeはprivate出力のみを読み書きする。source path、ファイル名、座標を
   Story PlanやDirector向けの外部表現（browser summary等）へ持ち出さない制約は
   既存モジュール（`app/web/private_evidence_review.py`等）と同じ基準に従う。

## 3. 提案するデータフロー

```text
既存: private GPX + video
        -> app.gps.extract_events (GpsEvent[])
        -> Story Planner -> StoryPlan
        -> app.video.catalog (ResolvedCandidateClip[], event_id keyed)
        -> LocalEvidenceReview (event_id keyed, human confirm)

追加: 同じ private GPX + video
        -> highlight_discovery / highlight_quality (QualitySelection[])
        -> HighlightReview (candidate_id keyed, human approve/reject + reason)
        -> [新規] highlight_story_bridge
             (a) WindowFeatures/HighlightWindowEvidenceへ絶対start/end時刻と
                 nearest RoutePointを追加保持する拡張
             (b) approved candidateだけを、時刻・位置を持つ
                 "video-originated GpsEvent" へ変換する
             (c) 既存GpsEvent群の時間窓と重なる場合は「補強」、
                 重ならない場合は「新規追加」に分岐する（§3.1/3.2）
        -> Story Planner の入力GpsEvent集合に統合
        -> 以降は既存のStory Plan -> catalog -> LocalEvidenceReviewへ合流
```

### 3.1 既存GpsEventと時間窓が重なる場合（補強）

対応する`event_id`の`ResolvedCandidateClip`区間を、approved highlightの
より狭い・より確度の高い区間で置き換える候補として提示する。ただし
`LocalEvidenceReview`の`CONFIRMED`判断そのものは上書きしない
（handoff §11で修正済みの「再実行時に人手confirmedを消さない」制約と同型）。
つまりbridgeは**候補区間の質を上げるだけ**で、確認状態を自動変更しない。

### 3.2 重ならない場合（新規追加）

`GpsEvent`契約（`app/contracts/models.py:187-207`）を満たす新しいeventを
合成する。

- `event_id`: `f"highlight-event-{candidate_idの先頭16桁}"`のような、
  既存`highlight_review_candidate_id`から導出する安定ID（衝突しない）。
- `event_type`: 既存の`extract_events`語彙（departure/stop/long_ride/
  elevation_change/speed_change/direction_change/arrival）を流用せず、
  `"visual_highlight"`のように新しい種別を追加する。Story Plannerと
  Director双方がこの新種別を未知typeとしてfail closedしないよう、
  許可listへの追加が必要（`app/agents/orchestrator.py`等、
  「未知event typeをfail closedする」既存テスト`tests/test_orchestrator.py`
  に新種別を通す変更を含む）。
- `location`: windowの絶対時刻区間中央に最も近い`RoutePoint`。
- `importance_hint`: `ScoredHighlightWindow`の対応scoreを`[0,1]`へ写像。
- `evidence`: `interest_lanes`の値（`strong_turn`/`visual_event`）と
  `HighlightReviewReason`の値をそのまま文字列として格納する
  （座標・ファイル名は含めないため、既存の「explainable candidate」方針と両立する）。

### 3.3 evidence状態の初期値（2026-09-01 決定済み）

ユーザーが2026-09-01に明示決定した（[current-system-handoff-ja.md](current-system-handoff-ja.md)
§5「2026-09-01の変更」参照）。

- 人手確認はカメラ→GPS時計オフセットの確認1点のみ（既存の
  `clock_offset_confirmed`）。これ以外は自動判定に一本化する。
- したがって案A・案Bはどちらも採用しない。`HighlightReview`の
  approved/rejectedという人手承認ステップ自体を、候補ごとのブロッキングUIとして
  維持しない。代わりに、既存の決定論的hard gate・4方式scoreが閾値を満たす候補を
  自動的に「採用」として`GpsEvent`合成・`LocalEvidenceReview`の`CONFIRMED`まで
  進める。閾値未達は自動的に対象外とする。
- 既知の誤検出リスク（実14 MP4評価での直線道路誤判定、handoff §2）は許容する。
  ただし閾値付近の境界事例（後述4.1）はprivateな非ブロッキングログへ記録し、
  処理は止めずに後から人手が任意に見直せるようにする。
- 映像が無い／timestamp不一致のeventは、レンダー全体を止めず、その出来事を
  物語から外す（§1原則「GPSは提案するだけで断定しない」を維持）。

### 3.4 境界事例ログ（新規、非ブロッキング）

`HighlightReview`の固定理由code・opaque IDという既存の非識別方針を維持したまま、
承認ステップをログへ置き換える。

- ログ対象: 4方式scoreが採用閾値から一定範囲内（初期値として上位/下位
  それぞれ10パーセンタイル、実装時に調整可能なパラメータとする）に入る候補、
  および`passes_complete_evidence_gate`をぎりぎり通過/不通過した候補。
- ログ内容: opaque candidate ID、method、rank、score、通過/不通過したgate名。
  source path、ファイル名、座標、frameは含めない（`highlight_review.py`と
  同じ制約）。
- ログの用途: 後から人手が任意に`HighlightReview`相当のstatusを個別に
  上書きできる「訂正用の入り口」として残す。存在しなくても自動パイプラインは
  完結する（=blockingではない）。

## 4. 実装前にユーザー判断が必要な点

1. ~~§3.3の初期状態（案A/案B）~~ → 2026-09-01決定済み（§3.3参照）。
2. **新event_type `"visual_highlight"` を、Story Plan・Director・
   `DirectorScript`のnarrative role割当てロジックにどう位置づけるか。**
   （Hook/Build-up/Climax/Resolutionのどれに置きうるか、既存のGPS由来eventと
   同列に扱ってよいか）
3. **§3.1の「補強」を自動候補提示に留めるか、既存`ResolvedCandidateClip`区間を
   置き換える具体的なCLI/UIをどの段階で作るか。**
4. **実14 MP4データでの試験対象範囲**。まず`tests/`の合成fixtureだけで
   contractを検証し、実素材への適用は別途明示指示を受けてから行う、
   という既存の進め方（handoff §12, §13, §15と同型）でよいか。
5. **`LocalEvidenceReview`の既存per-event人手確認（`app/web/private_evidence_review.py`
   のUI、`app/private_story_e2e.py`が要求する「全件confirmed」チェック）を、
   自動判定へ置き換える具体的な移行手順。** 既に実装・テスト済みの経路であり、
   fail-closed契約の意味が変わるため、影響するtestの洗い出しを伴う別作業として
   扱うことを提案する（§7）。

## 5. 実装ステップ案（承認後）

1. `WindowFeatures`（または`HighlightWindowEvidence`）に絶対`start`/`end`時刻と
   nearest `RoutePoint`を追加する拡張。既存のvideo-relative fieldは変更しない
   （後方互換）。synthetic contract testを先に追加する。
2. `app/video/highlight_story_bridge.py`（新規）に、approved selectionから
   `GpsEvent`を合成する純関数と、既存GpsEvent集合との重なり判定を実装する。
   source path・座標をログや例外メッセージに出さない。
3. `extract_events`または Story Planner呼び出し側で、GPS由来eventと
   highlight由来eventを結合する差し込み点を追加する。
4. `LocalEvidenceReview`の初期化ロジックを、§3.3で決定した自動判定
   （hard gate通過→`CONFIRMED`、閾値付近→§3.4の境界事例ログへ記録しつつ
   処理は継続、gate不通過→対象外）で実装する。
5. 合成fixtureで、重複event拒否・fail closed（clock未確認・素材欠損時のみ）・
   opaque性・schema互換・自動判定の閾値境界を検証する。
6. 実14 MP4データへの適用は、上記が全て緑になり、かつ§4の残り判断
   （2, 3, 4, 5）が確定してから別ステップとして行う。

## 6. 意図的にやらないこと

- 既存2契約（`LocalEvidenceReview`、`HighlightReview`）のスキーマ変更。
- Vision/Gemini等、新しい外部推論の追加。
- カメラ→GPS時計オフセット確認（`clock_offset_confirmed`）の省略。これは
  2026-09-01時点で唯一残る必須の人手確認であり、自動化の対象外。
- 素材が完全に欠損している場合や、時刻整合そのものが取れない場合にまで
  fail closedを外すこと。自動化の対象は「個々の候補の質・関連性の判断」に
  限り、「構造的な前提が満たされているか」の確認は維持する（§3.3）。

## 7-0. 実装済み｜HighlightReview側の自動判定＋境界事例ログ（2026-09-01）

§7の1番目を実装した。

- `app/video/highlight_review.py`に`auto_decide_highlight_review`（interest laneから
  approval reasonを導出し全候補APPROVED）、`find_highlight_review_borderline_candidates`
  （method内score下位分位点＋GPMF/road-context gate margin僅差の2条件、非blocking）、
  `load_or_autodecide_highlight_review`（既存の人手修正があれば保持、無ければ自動判定して
  新規作成）を追加した。
- `app/video/highlight_research.py`を新関数へ配線し、`highlight-review-borderline.json`
  を毎回再生成するよう接続した（人手編集対象ではないため`overwrite=True`固定）。
- 既存の`build_highlight_review_template`（awaiting）、`update_highlight_review_decision`、
  `load_or_create_highlight_review`は削除せず、任意の手動訂正経路として残した。
- 既存2契約のJSON schema（`HIGHLIGHT_REVIEW_SCHEMA_VERSION`）は変更していない。
  境界ログは新しい別ファイル・別schema版（`local-highlight-review-borderline-v1`）。
- synthetic fixtureで、lane→reason導出、複数lane時の理由結合、method不一致拒否、
  score下位境界の検出、gate僅差境界の検出、パラメータ検証、手動訂正の保持、
  非識別性（opaque ID・source path等を含まない）、overwrite挙動を検証した。
  592件成功、Ruff成功。
- 実14 MP4データへは未適用。§7の2番目（`LocalEvidenceReview`側の同様の移行）は未着手。

## 7-1. 実装済み｜LocalEvidenceReview側の自動判定＋fail-closed意味変更（2026-09-01）

§7の2番目を実装した。HighlightReview側より影響範囲が広く、3つの既存gateを
連動して変更した。

- `app/video/review.py`に`auto_decide_local_evidence_review`（`VideoMatchStatus.MATCHED`
  なら`CONFIRMED`、`NOT_FOUND`なら`REJECTED`。どちらも固定の非識別source文字列
  `AUTO_DECIDED_MATCHED_SOURCE`/`AUTO_DECIDED_UNMATCHED_SOURCE`を使う）と
  `load_or_autodecide_local_evidence_review`（既存ファイルがあれば人手訂正含め保持、
  無ければ自動判定）を追加した。
- `evaluate_local_evidence_review`の`ready_for_render`を、「reasonsが空」から
  「awaitingが無く、かつconfirmedが1件以上ある」へ変更した。rejected／unmatchedは
  `reasons`に情報として残るが、単独ではrenderを止めなくなった。
- `app/edit/candidate_planner.py`の`review_candidate_edit_plan`も同型に変更した。
  `is_ready_for_edit`は「不足尺が無く、awaitingが無く、confirmedが1件以上ある」で
  判定し、rejected由来のreasonは表示のみで単独ではブロックしない。
- `app/local_pipeline.py`の`rerun_local_director_from_package`の事前check（旧:
  「全件confirmed」必須）を、「awaitingが無く、confirmedが1件以上」へ緩和した。
  `_next_local_pipeline_gate`は`is_ready_for_edit`を最初に判定するよう順序を
  入れ替え、readyならrejectedが残っていてもrenderへ進む。
- `LocalPipelineResult`のprivacy summaryにある`visual_evidence_auto_confirmed`は
  `False`固定から`True`固定へ変更した（実態を正しく反映するため）。
- `app/video/__init__.py`に新関数をexportした。
- 影響した既存test（`test_local_pipeline.py`、`test_director_pipeline.py`、
  `test_private_story_e2e.py`）のうち、「初期状態は全件awaiting」という前提が
  崩れたものは、人手が既存決定を手動でawaiting／rejectedへ戻す状況を明示的に
  再現する形へ書き換えた。新規に、rejectedとconfirmedが混在してもrenderが
  進む場合・nothingがconfirmedなら進まない場合の positive testを追加した。
- 598件成功、Ruff成功。実14 MP4データへは未適用。

### 未解決（この増分の対象外）

- `app/web/private_evidence_review.py`（人手のUI）はそのまま残しており、
  `_next_evidence_gate`のメッセージは変更していない。既存の任意手動訂正用途は
  引き続き機能する。
- highlight由来eventとGpsEventの橋渡し本体（本設計書§3）はまだ未着手。

## 7-2. 実装済み｜highlight→GpsEvent橋渡しの中核機構（2026-09-01）

本設計書§3・§5の中核部分を実装した。ただし実装過程で、当初の想定より
現実的な統合範囲が狭いことが判明したため、§4項目2は解消、項目3・4は
未確定のまま、統合面の制約を1つ新たに記録する。

### 実装内容

- `app/video/highlight_discovery.py`の`WindowFeatures`に`latitude`／
  `longitude`（両方optional、デフォルト`None`、既存呼び出し元・testと
  後方互換）を追加した。`_gps_features`のmidpoint route pointから設定する。
  調査の結果、`timeline_s`は既にvideo-relativeではなく**絶対GPS-clock
  Unixタイムスタンプ**であることが判明したため、絶対時刻用の新規fieldは
  不要だった（設計書§1の記述を訂正）。
- 新規`app/video/highlight_story_bridge.py`に、`build_highlight_gps_event`
  （approved 1候補→`GpsEvent`）、`overlaps_existing_event`（既存GpsEventとの
  時間重なり判定）、`build_highlight_gps_events`（複数method分をapproved
  candidate_idでfilterし、重なるものを除外し、同一window由来の重複を
  event_id基準で除去し、時系列順に返す）を実装した。event_idはwindowの
  asset_id・offset・durationのみから導出し、method・rankを含めない
  （同じ物理windowが複数methodで選ばれても1 eventに収束する）。
  event_type文字列は新規`visual_highlight`。
- synthetic contract testを追加（承認済み候補からのevent合成、位置情報欠如時の
  拒否、重なり判定、approved／rejected混在時のfilter、method間重複除去、
  時系列順ソート）。605件成功、Ruff成功。

### §4項目2は調査により解消（新event_typeのDirector配置）

`app/agents/story_planner.py`の`roles`/`priority`辞書は`event.event_type`が
未知でもfallback表示・優先度0で安全に扱う。`app/director.py`の役割判定
（`_is_departure`／`_is_arrival`による判定＋`_rank_key`による汎用ranking）も
event_type文字列を特別扱いしておらず、未知typeはBuild-upへ落ちるか、
scoreが高ければClimax／Hookにもなり得る。**コード変更は不要**と確認できた。

### 判明した制約は2026-09-02に解消（§7-3参照）

`highlight_quality.QualitySelection`には永続化手段が無いという制約自体は、
`QualitySelection`をそのまま保存するのではなく、橋渡しが実際に必要とする
情報だけを持つ狭いレコード`HighlightBridgeCandidate`を新設することで解消した。
詳細は§7-3。

## 7-3. 実装済み｜HighlightBridgeCandidateの永続化（2026-09-02）

ユーザー指示によりQualitySelectionの永続化を設計・実装した。ただし
`QualitySelection`本体（Vision frame・GPMF summary・window特徴量を含む）を
丸ごと保存する設計は採らなかった。理由は次のとおり。

- `highlight_quality.export_quality_research_manifest`は
  `coordinates_in_manifest: False`、`vision_labels_in_manifest: False`等を
  明記し、privateな成果物であってもVision分類ラベル・座標・asset_idを含めない
  方針を既に確立している。`metric_cache.PrivateMetricCache`も同様にVision出力を
  キャッシュ対象から除外している（handoff §12）。`QualitySelection`をそのまま
  永続化すると、この既存方針に反する。
- 橋渡しが`GpsEvent`を合成するために実際に必要な情報は、opaque candidate ID、
  method、rank、絶対時刻窓、位置、interest lane、importance_hint用scoreの
  8項目だけであり、asset_id・生のFFmpeg/GPMF数値・Vision分類ラベルは不要と
  判明した（同一物理windowは絶対時刻窓が一致するため、event識別・重複排除にも
  asset_idは不要）。

### 実装内容

- `app/video/highlight_story_bridge.py`に`HighlightBridgeCandidate`
  （上記8項目のみを持つ狭いview）、`highlight_bridge_candidate_from_selection`
  （`QualitySelection`からの射影。位置情報が無ければ`HighlightStoryBridgeError`）、
  `export_highlight_bridge_candidates`（review-approvedかつ位置情報のある候補
  だけを集める。位置情報欠如は個別skipで全体を失敗させない）、
  `write_highlight_bridge_candidates`／`load_highlight_bridge_candidates`
  （新schema`local-highlight-bridge-candidates-v1`、atomic write）を追加した。
- `build_highlight_gps_event`／`overlaps_existing_event`／
  `build_highlight_gps_events`は`QualitySelection`ではなく
  `HighlightBridgeCandidate`を受け取るよう変更した（既存API変更、
  呼び出し元は前日実装のtestのみだったため影響なし）。
- `app/video/highlight_research.py`を配線し、`highlight-bridge-candidates.json`
  を毎回再生成する（人手編集対象ではないため`overwrite=True`固定、他の派生
  出力と同じ扱い）。`HighlightResearchResult`に`bridge_candidates_path`を追加。
- synthetic contract testを追加（射影、位置欠如時の個別skip、payloadの
  非識別性——asset_id・Vision分類ラベル・生GPMF値を含まないことを直接検証、
  round-trip、schema検証、overwrite挙動）。612件成功、Ruff成功。

### まだ未実施

`app.private_story_e2e`・`--resume-output`経路への接続は未実施。CLI引数化は
`python -m app.local_pipeline --highlight-bridge-candidates <path>`として
2026-09-02に追加済み（`--resume-output`側には未追加、意図的）。

## 7-4. 実装済み｜app.local_pipelineへの配線（2026-09-02）

`prepare_local_review_package`に`highlight_bridge_candidates_path: Path | None`
を追加した。指定すると`highlight-bridge-candidates.json`を読み込み、GPS由来
event集合とのovlerap判定を経て`build_highlight_gps_events`で合流させてから
`select_video_backed_events`／Story Plannerへ渡す。

- 新規eventは既存のcatalog解決・auto-decide evidence・candidate exportの
  経路をそのまま通る。実装を追加した部分は無く、eventの合流点1箇所のみ。
- 意図的にscopeを絞った点: `local-pipeline-inputs.json`（`--resume-output`が
  読む再実行用manifest）にはこのpathを記録しない。毎回明示的に渡す
  per-invocation入力として扱う。CLI引数（`argparse`）へは未接続。
- 統合testを追加: 実際に候補を合流させ、catalogとtimestampが一致すれば
  `matched`、evidence-reviewが自動`confirmed`になることまで確認した
  （合成fixtureのみ、実14 MP4は未適用）。613件成功、Ruff成功。

これで橋渡し機構は、同一プロセス内であれば「highlight研究の出力」から
「Director/Editorが実際に使えるconfirmed event」まで一気通貫でつながった。
残る主な論点は§4の3（既存GPS eventとの重なり時に区間を補強するUI）・4
（実素材適用のタイミング）と、CLI引数化・`--resume-output`との統合である。

## 7-5. 実素材検証｜「重なれば新規追加しない」設計が実データでは価値ゼロ（2026-09-02）

ユーザー承認のもと、実データ（実GoPro動画一式・実GPX）で本橋渡しを末端まで
実行した。結果は技術的には成功だが、設計上の重要な限界が判明した。実素材由来の
具体的な数量・識別子はこの節でも記録しない。

### 実行結果

- `highlight_research`: 解析対象窓がstrict gate・最終品質gateを経て絞り込まれ、
  選定された候補は**全件自動承認、awaiting／rejectedともに0件**（境界事例ログ
  にも記録あり）。コード変更なしで完走。
- `app.local_pipeline --highlight-bridge-candidates`: GPS由来eventとhighlight
  由来候補を合流させたところ、**新規追加されたeventは0件**だった。候補が
  全て既存のGPS由来eventの時間窓と重なっていたため（本設計書§3の「重なれば
  新規追加しない、重ならなければ追加する」方針の「重ならない」側にどの候補も
  該当しなかった）。
- 最終的に選ばれたchapter・matched clipは全てGPS由来eventのみで、highlight
  由来のものは1件も含まれない。

### 分かったこと

strong_turn laneは方位変化・経路効率というGPS由来の信号を使っており、
GPS側の`direction_change`検出と本質的に同種の信号を見ている。そのため
「強い旋回」候補は、GPSが既に検出済みの方向転換eventと高確率で時間的に
重なる。今回の実ライドでは、strong_turn・visual_eventの両laneの候補が
**すべて**既存eventと重なった。

つまり現在実装済みの「重ならなければ新規追加」機構（§3.2、§7-2〜7-4）は、
この実データでは**実質的に何も追加しない**。橋渡しが実際に価値を持つのは、
未実装の§3.1「既存eventとの重なり時に、より精度の高いhighlight区間で
候補clip intervalを補強する」側だったことが、実データでようやく判明した。
これは事前の設計時点では分からなかった、実素材適用によって初めて得られた
知見である。

### 今後への示唆

§4項目3（補強UI・ロジック）の優先度を、本橋渡し内で最も高いものへ引き上げる
べきである。「新規追加」経路（§3.2）は無価値ではない（GPS eventが疎な区間や
より短いGPXの旅では新規追加が起きる可能性がある）が、少なくともこの実データ
セットでは検証できていない。次の実装候補は、既存`ResolvedCandidateClip`の
区間を、重なるhighlight候補のより狭く精度の高い区間で置き換える（人手確認は
引き続き自動判定に委ねる）処理である。

## 7-6. 実装済み｜既存event区間補強（reinforcement）経路（2026-09-02）

§4項目3・§7-5「今後への示唆」を実装した。合成fixtureのみで検証し、実素材の
再処理は行っていない。

### 実装内容

- `app/video/highlight_story_bridge.py`に`reinforce_resolved_clips_with_highlights`
  （公開API）と`_reinforce_one_clip`（内部）を追加した。既存型
  （`ResolvedCandidateClip`、`VideoCatalog`、`HighlightBridgeCandidate`）だけを
  使い、新しい永続化・新しいcontractは追加していない。
- 判定順序: ①`status`が`MATCHED`でなければ何もしない（`NOT_FOUND`など未対応は
  元のまま） ②候補のcatalog上の絶対時刻区間と、解決済み区間の絶対時刻区間が
  重なる候補をすべて集め、ちょうど1件でなければ（0件または複数件は曖昧）元の
  ままにする ③その1件の絶対時刻区間が、解決済み区間と同じcatalog entry
  （＝同一asset）の記録区間に完全に収まっていなければ（asset identity不一致）
  元のままにする ④候補区間と解決済み区間の交差（intersection）を計算し、
  区間が不正（幅0以下）なら元のままにする ⑤交差が元の区間より狭くなければ
  （＝補強にならない）元のままにする ⑥それ以外の場合だけ、`start_offset_s`／
  `end_offset_s`をその交差区間へ狭め、`reason`を補強理由の定型文へ更新する。
  `asset_id`、`status`、`chapter_id`、`event_id`、`file_name`は一切変更しない。
- `app/local_pipeline.py`の`prepare_local_review_package`に配線した。
  `highlight_bridge_candidates_path`が渡されたときだけ、`resolve_candidate_clips`
  の直後に適用する。新規event合流（既存の`build_highlight_gps_events`）と同じ
  candidate集合を再利用し、追加のファイル読込・実素材再処理は発生しない。
  自動confirmed方針（evidence自動判定）と時計補正の人手確認
  （`clock_offset_confirmed`）はどちらも変更していない。
- synthetic contract testを追加: 補強成功、`NOT_FOUND`clipの不変、重複無し、
  複数候補の曖昧さ、asset境界外候補の拒否、非狭小候補の不採用、catalogに
  asset不在時の不変、複数clip中の対象外clip不変、を単体testで検証。
  `app.local_pipeline`経由の統合testを1件追加し、実際に`prepare_local_review_package`
  を通してresolved intervalが狭まること、狭まった場合は新規highlight eventが
  重複して増えないことを確認した。
- 627件成功、Ruff成功、`git diff --check`成功。実GPX・実動画・座標・
  ファイル名・absolute path・資格情報は、コード・test・本追記のいずれにも
  含めていない。実素材は一切読み書きしていない。

### 未対応境界（意図的にfail closedのまま）

- 1つの解決済みclipに対して複数のhighlight候補が重なる場合は補強しない
  （最有力候補を選ぶロジックは未実装）。
- 候補区間が解決済み区間と部分的にしか重ならない場合、重なった部分だけを
  使う（交差を取る）。候補区間全体を採用する拡張的な補強はしない。
- `--resume-output`経路（`rerun_local_director_from_package`）には配線して
  いない。既存の`local-pipeline-inputs.json`に`highlight_bridge_candidates_path`
  を記録しない設計（§7-4）と整合させたまま。
- 実素材適用・効果測定は次回以降の別作業とする。

## 7-7. 実素材検証｜補強経路のfail-closed動作を確認（2026-09-02）

commit `ad91139`（既存event区間補強）を、既存のprivate入力manifest
（`local-pipeline-inputs.json`）・既存catalog相当のGPX／video directory・
既存の`highlight-bridge-candidates.json`（§7-5で生成済みのもの）だけを使い、
新しいwork用private output（Git管理外）2つ（補強なし／補強ありの比較用）へ
ローカル検証した。新しいhighlight researchは実行していない。video directory
は入力manifestの値を`app.local_pipeline.load_local_pipeline_inputs`で読み込み、
`private-media/input/`配下（元の取り込み場所）であり`private-media/work/`配下
（派生proxy置き場）でないことをコードで確認してから使用した。

### 安全な集計結果

| 項目 | 補強なし | 補強あり |
|---|---:|---:|
| event数 | 24 | 24 |
| matched clip数 | 7 | 7 |
| matched clip合計尺 | 210.0秒 | 210.0秒 |
| evidence confirmed数 | 7 | 7 |
| next_gate | 変化なし（同一） |  |

**区間が狭まったclipは0件だった。** 内訳：7件のmatched clipのうち、
highlight候補と絶対時刻で重なるものは1件だけ。その1件には重なる候補が
2件存在し、fail-closedの「複数候補は曖昧」ルールにより意図的に変更しなかった
（2件とも同一assetの範囲内にあり、単独なら狭められる候補だったことも確認
済み）。残り6件は重なる候補が0件だった。

### 結論

**既存コードに問題は見つからなかった。** 今回0件だった理由は、実装済みの
fail-closed境界（複数候補の曖昧さ）が実データで実際に働いたためであり、
バグではない。コード変更は行っていない。

### 未実施のまま残る境界（§7-8で一部解消）

- 複数candidateが同一clipに重なる場合の優先順位付け（本検証で実際に1件発生
  したことを確認したため、優先度は上がったが未実装のまま）。→ §7-8で実装。
- `--resume-output`との統合。
- 本検証で使った実素材由来の数値・識別子はこの文書にも記録していない
  （§7-7表の集計値はcount／秒数のみで、event_id・asset_id・座標・ファイル名・
  絶対pathは含まない）。

## 7-8. 実装済み｜複数候補時の優先順位付け（2026-09-02）

§7-7で判明した「1つの解決済みclipに複数candidateが重なるとfail-closedで
常に変更しない」という制約を、意味的に比較可能で一意な優先順位がある場合
だけ緩和した。合成fixtureのみで検証し、実素材の再処理は行っていない。

### 判断契約

- `HighlightBridgeCandidate.score`は`QualitySelectionMethod`ごとに意味が
  異なるため、異なるmethod間ではscoreもrankも比較しない。
- 重なる候補（asset identity検証済みのもの）が全て同一methodで、かつ
  rankが一意に最小のものだけを選べる場合に限り、その候補で既存の
  strict narrowing（交差計算・狭小判定）を行う。
- 最小rankが同率、候補のmethodが複数種類混在、有効な候補が0件の場合は
  既存のfail-closedのまま（元の`ResolvedCandidateClip`を完全に維持）。
- asset identity不一致の候補は、優先順位付けの対象から個別に除外するだけで、
  それ自体が曖昧さの理由にはしない（無効な候補が紛れていても、残りの
  有効候補群で一意に決まるなら補強する）。
- 候補が1件だけの場合の既存挙動（そのまま補強判定へ進む）は変更していない。

### 実装内容

- `app/video/highlight_story_bridge.py`に`_select_unambiguous_candidate`
  （内部helper）を追加した。入力は候補のtuple、出力は選ばれた1候補または
  `None`（曖昧）。
- `_reinforce_one_clip`の候補選択順序を変更した: ①絶対時刻で重なる候補を
  集める ②asset identityを満たす候補だけを残す（`valid`） ③`valid`が空なら
  変更しない ④`_select_unambiguous_candidate(valid)`が`None`を返せば変更
  しない ⑤選ばれた1候補で従来どおり交差・狭小判定を行う。asset identity・
  match status・evidence状態・clock-offset確認・manifestの不変性は変更して
  いない。candidate_id・path・ファイル名は理由文にもログにも出力しない
  （既存のまま）。
- 新規synthetic testを追加: 同一method・rank一意で補強、同一method・rank
  同率でno-op、method混在でno-op（rank数値が小さくても比較しない）、
  asset不一致candidateが混在しても残りの有効な1件で補強、を検証した。
  既存の「複数候補は常に変更しない」testは、rank同率という具体的な
  fail-closedケースとして名称・内容を明確化した。
- 630件成功、Ruff成功、`git diff --check`成功。実GPX・実動画・座標・
  ファイル名・絶対path・識別子・資格情報は、コード・test・本追記の
  いずれにも含めていない。実素材は一切読み書きしていない。

### 未対応境界（意図的にfail closedのまま）

- 同一method・rank同率の複数候補からの選定は、自動判定としては依然
  未実装・fail-closedのまま。ただし§7-9の明示選択で人手が個別に解決できる。
- method間でscoreを正規化して比較する仕組み（意図的に見送り。契約上
  「異なるmethod間で比較しない」ことが安全側の要件のため）。

## 7-9. 実装済み｜private-only明示選択契約（2026-09-02）

§7-8の「未対応境界」（同一method・rank同率、method混在で自動判定できない
複数候補）を、将来のprivate UIが人手の選択を安全に保存・適用できるようにする
土台として、明示選択の契約を追加した。**public webやrenderへの接続、UI自体は
今回行っていない**（別タスク）。

### 契約

- `HighlightReinforcementSelection`：`(event_id, candidate_id)`のペアだけを
  持つ。どちらもprivate artifact内だけで使う既存の識別子
  （`GpsEvent.event_id`、`highlight_review_candidate_id`のhash）であり、自由文・座標・path・
  ファイル名・映像本文・資格情報は一切持たない。
- `HighlightReinforcementSelectionSet`：1 event_idにつき選択は最大1件、
  1 candidate_idにつき選択も最大1件。重複event_idまたはcandidate_idは
  構築時に`ValueError`で拒否する（同じ候補を複数clipへ重複配置しない
  fail-closed）。
- `load_highlight_reinforcement_selections`／`write_highlight_reinforcement_selections`：
  呼び出し側が明示するprivate pathへのみ読み書きする。schema不一致、
  トップレベル／要素レベルの未知field、非文字列の識別子、symlink先、
  壊れたJSONを全て拒否する。書き込みは既定で上書きしない（人手の選択を
  再実行で黙って消さないため）、atomic write（一時ファイル→rename）。

### `reinforce_resolved_clips_with_highlights`との統合

- 新しいkeyword-only引数`selections: HighlightReinforcementSelectionSet | None = None`
  を追加した。省略時（既定）は、この契約が存在しなかった場合と完全に同じ
  挙動になる（既存の自動優先順位付けのみ）。
- ある clip の event に選択が記録されている場合、その candidate_id を
  **既存のasset identity・絶対時刻交差・strict narrowingの全チェックに
  独立に通した上でのみ**優先採用する。自動判定が曖昧かどうかに関わらず
  優先する。
- 選択が不正・古い・別clip由来・asset不一致・非狭小のいずれかの場合、
  自動判定へフォールバックしない。元の`ResolvedCandidateClip`をそのまま
  維持する（曖昧な自動判定と同じfail-closedの扱い）。
- 選択が無いeventは、これまでどおり自動優先順位付け
  （`_select_unambiguous_candidate`）にフォールバックする。

### 実装内容

- `app/video/highlight_story_bridge.py`に上記契約一式と、`_select_candidate`
  （明示選択を優先しつつ独立検証する内部helper）を追加した。
  `_reinforce_one_clip`は`_select_unambiguous_candidate`の直接呼び出しから
  `_select_candidate`経由に変更した。
- 合成fixtureのみでテストした: 明示選択によるmethod混在・rank同率の解決
  （正常適用）、選択なし時の完全な既存互換、選択が不明candidate／
  asset不一致／非狭小／unmatched clip向けの場合はfail-closedで元clipを維持、
  同一event_idの重複選択を契約レベルで拒否、persistenceのround trip・
  atomic write・symlink拒否・schema検証一式。
- 653件成功、Ruff成功、`git diff --check`成功。実GPX・実動画・座標・
  ファイル名・絶対path・識別子・資格情報は、コード・test・本追記のいずれ
  にも含めていない。実素材は一切読み書きしていない。外部通信、Gemini／
  Google／Box、render、pushは行っていない。

### まだ無いもの

- private UI本体（選択を作成・保存する画面）は次の独立タスク。
- `app.local_pipeline`側で`selections`を受け取るCLI引数・入力経路は未接続
  （現状は関数を直接呼ぶ場合のみ利用可能）。

## 7-10. 実装済み｜自動選択できない競合の一覧化（2026-09-02）

§7-9の明示選択契約は「人手がどう選ぶか」を扱うが、「どのclipに選択が
必要か」を安全に一覧化する手段が無かった。この土台として、純粋な
一覧化契約を追加した。**public web、render、CLI接続は今回も行っていない**
（引き続き別タスク）。

### 契約

- `HighlightReinforcementConflict`：`event_id`、`candidate_id`、`method`、
  `rank`だけを持つ。座標・path・素材名・映像本文・絶対時刻・offset・score・
  資格情報・自由文は一切含めない。
- `HighlightReinforcementConflictSet`：同一`(event_id, candidate_id)`の
  重複と、同一candidate_idが複数eventにまたがることの両方を構築時に
  `ValueError`で拒否する。
- `find_highlight_reinforcement_conflicts(clips, candidates, catalog)`：
  `HighlightReinforcementSelectionSet`を一切受け取らない、独立した
  問い合わせ関数。「どのclipに人手判断が要るか」だけに答え、選択の記録は
  既存の別契約（§7-9）に委ねる。
  - 各clipについて、`reinforce_resolved_clips_with_highlights`と同じ
    asset identity・absolute-time overlap・strict narrowingの3条件を
    **候補ごとに個別に**適用する（既存関数は最終的に選ばれた1候補にしか
    narrowing判定をしないが、一覧化では全候補に適用する必要があるため、
    既存の`_reinforce_one_clip`とは独立した内部helper
    `_valid_narrowing_candidates`を新設した。既存関数の挙動は変更していない）。
  - 有効な候補が0件、または1件で`_select_unambiguous_candidate`が一意に
    決まる場合は一覧に含めない（人手判断が不要なため）。
  - method混在、または同一methodで最小rankが同率の場合だけ、有効な候補
    全件を競合項目として返す。
- `load_highlight_reinforcement_conflicts`／`write_highlight_reinforcement_conflicts`：
  strict schema（未知field・非文字列識別子・未知method値・rank非正数を拒否）、
  symlink拒否、atomic write、既定で上書きしない（§7-9の選択persistenceと
  同じ方針）。呼び出し側が明示するprivate pathへのみ読み書きする。

### 実装内容

- `app/video/highlight_story_bridge.py`に上記契約と`_valid_narrowing_candidates`
  を追加した。既存の`reinforce_resolved_clips_with_highlights`・
  `_reinforce_one_clip`・`_select_unambiguous_candidate`・
  `_select_candidate`は変更していない。
- 合成fixtureのみでテストした: method混在の一覧化、同一method・rank同率の
  一覧化、自動選択済み（一意な最小rank、候補1件）の除外、asset不一致・
  非狭小候補が紛れていても残りが1件なら除外、unmatched clip・catalog不一致
  clipの除外、複数clipにまたがる出力の決定的な順序、同一event/candidate
  重複と同一candidateの複数event帰属の拒否、persistenceのround trip・
  atomic write・symlink拒否・schema検証一式。
- 680件成功、Ruff成功、`git diff --check`成功。実GPX・実動画・座標・
  ファイル名・絶対path・識別子・資格情報は、コード・test・本追記のいずれ
  にも含めていない。実素材は一切読み書きしていない。外部通信、Gemini／
  Google／Box、render、pushは行っていない。

### まだ無いもの

- private UI本体（一覧を表示し、選択を作成する画面）は次の独立タスク。
- `app.local_pipeline`・CLIからの呼び出し経路は未接続。

## 7-11. 実装済み｜loopback-only private補強競合reviewUI（2026-09-02）

§7-10の一覧化契約と§7-9の明示選択契約を、既存のprivate review UI群
（`app/web/private_highlight_review.py`、`app/web/private_evidence_review.py`）
と同じloopback-onlyパターンで画面化した。**Director・render・CLI・
local_pipelineへの接続は行っていない**（引き続き別タスク）。

### 設計上の要点

- 新規`app/web/private_highlight_reinforcement_review.py`。設定先は既存の
  `RIDE_PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY`とは別の環境変数
  （`RIDE_PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY`）。設定した1つの
  directory配下だけを読み書きし、親directoryの走査や別packageへのfallbackは
  行わない。
- ブラウザへ渡す内容は`local_only`、`external_data_sent`、schema付きの集計
  view、**session内だけで意味を持つopaque review token**、`method`、`rank`、
  server側で組み立てたthumbnail/media URLだけに限定した。event_id・
  candidate_id・asset_id・offset・時刻・source path・ファイル名・座標・
  score・資格情報は一切含めない。既存の`private_highlight_review.py`が
  candidate_idをそのまま公開していたのとは異なり、今回はより厳格な
  session-scoped tokenだけを公開する。
- tokenは設定package内の競合一覧（§7-10の出力）における位置だけを表す
  文字列で、保存要求のたびに一覧を読み直して再検証する。生のevent_id・
  candidate_idをtokenとして受理することはない。
- 保存は明示選択契約（§7-9）へそのまま書き込む。同じeventへの2回目の選択は
  そのeventの選択だけを置き換え、他のeventの既存選択は保持する。
- 未知token、壊れた／余分なfield、cross-origin request、public demo mode、
  asset欠損はすべてfail closedで拒否する。未設定時の画面はpath・設定値・
  内部エラー文言を一切表示せず、設定すべき環境変数名だけを案内する。

### 実装内容

- `app/web/server.py`に4経路（GET `/private-highlight-reinforcement-review`、
  GET/POST `/api/private-highlight-reinforcement-review`、GET
  `/api/private-highlight-reinforcement-review/asset`）を追加し、
  `_PUBLIC_DEMO_DISABLED_PATHS`へ全て登録した。既存のloopback-origin検証
  helperをそのまま再利用した。
- 合成fixtureのみでテストした: payloadの非識別性（生ID不在の直接検証）、
  tokenを生IDとして再利用できないこと、有効tokenでの保存、同一eventへの
  2回目の選択が他eventの選択を保持したまま置き換わること、未知／
  cross-origin／public demo／asset欠損のfail-closed、asset取得に
  path traversalが無いこと、未設定時に画面がpath・設定値を出さないこと。
- 696件成功、Ruff成功、`git diff --check`成功。実GPX・実動画・座標・
  ファイル名・絶対path・識別子・資格情報は、コード・test・本追記のいずれ
  にも含めていない。実素材は一切読み書きしていない。外部通信、Gemini／
  Google／Box、render、push、公開は行っていない。commitもしていない
  （指示によりこの回はローカル変更のみ）。

## 7-12. 実装済み｜private補強review directoryとlocal_pipelineの接続（2026-09-02）

§7-11のweb UIが保存するselectionを、`app.local_pipeline`の新規/再準備package
へ接続し、`--resume-output`が明示的な選択の有無に関わらず決定論的に
再現できるようにした。**Director判断・render・evidence判定・
auto-confirmation方針は変更していない**。

### 設計上の要点

- `prepare_local_review_package`に新引数`highlight_reinforcement_review_directory`
  を追加した。既存の`highlight_bridge_candidates_path`（単一ファイル、
  selectionなし）とは独立した、別の入力経路として共存する。両方を同時に
  指定した場合はGPX／動画のprobe前に拒否する。
- 新引数のdirectoryは、指定された1つのpathだけを読む。親・兄弟directoryの
  走査や推測は行わない。directory自体・`highlight-bridge-candidates.json`
  （必須）・`highlight-reinforcement-selections.json`（任意。無ければ
  空のselection setとして扱う）のsymlink・破損・欠落は、いずれもGPX／動画
  probe前にfail closedで拒否する。
- 読み込んだcandidatesとselectionは、既存の`reinforce_resolved_clips_with_highlights`
  （§7-9で追加済みの`selections`引数）へそのまま渡す。selectionが無い場合の
  既存挙動（自動優先順位付けのみ）は完全に変わらない。
- 新引数を使った回だけ、読み込んだ内容をそのまま`output_directory`内へ
  `highlight-bridge-candidates.json`／`highlight-reinforcement-selections.json`
  としてsnapshotする（既存の書き込み契約をそのまま再利用）。
- `rerun_local_director_from_package`／`--resume-output`は、
  **package自身のoutput directory**を`highlight_reinforcement_review_directory`
  として再利用する。これにより、rerunは常にpackage内のsnapshotだけを読み、
  元のreview directoryへは二度とアクセスしない。review directory側で
  selectionが後から変わっても、既に準備済みのpackageのresumeには影響しない。
  snapshotが無いpackage（この機能を使わなかったもの）は、従来どおり
  reinforcementなしでrerunする。snapshotがsymlink・破損・片方だけの不完全な
  状態の場合はprobe前に拒否する。
- 既存packageを`overwrite=True`で再準備する際、review directoryを明示せずに
  古いsnapshotだけを残すことは許可しない。元の選択を再現したい場合は
  `--resume-output`、新しい選択へ置き換える場合はreview directoryの明示、
  どちらでもない場合は新しいoutput directoryを使う。これにより、旧選択を
  意図せず再利用する経路を閉じる。

### 実装内容

- `app/local_pipeline.py`: `_resolve_highlight_reinforcement_inputs`
  （2つの入力経路を検証・読み込む内部helper。probe前に呼び出す）、
  snapshot書き込み処理、CLI引数
  `--highlight-reinforcement-review-directory`（`--highlight-bridge-candidates`
  と併用不可、`--resume-output`とも併用不可）を追加した。
- 合成fixtureのみでテストした: method混在で自動選択できない候補を明示選択が
  解決すること、新旧2つの入力を同時に指定した場合のprobe前拒否、不正な
  review directory（symlink・破損JSON）のprobe前拒否、selection sidecar
  欠落時の空set扱い、snapshotのround trip、review directory側の内容が
  後から変わってもresumeが最初のsnapshotのまま再現すること、package内に
  symlinkされた不正snapshotまたは片方だけのsnapshotが混入した場合のresume時probe前拒否、
  snapshotを明示的に置換しない`overwrite=True`再準備のprobe前拒否、
  出力summary・candidate exportにreview directoryのpathが含まれないこと。
- 708件成功、Ruff成功、`git diff --check`成功。実GPX・実動画・座標・
  ファイル名・絶対path・識別子・資格情報は、コード・test・本追記のいずれ
  にも含めていない。実素材は一切読み書きしていない。外部通信、Gemini／
  Google／Box、render、push、公開は行っていない。commitもしていない。

### まだ無いもの

- `app.private_story_e2e`専用の追加APIは持たない。既存の`--resume-output`
  経由でpackage snapshotを再現する最小構成であり、2026-09-02に選択済み
  reinforcementからoffline Director、silent local renderまでの合成E2E回帰で
  接続を検証した。
- この機能に特化したCLIドキュメントの英訳・ヘルプ文言以上の追加説明はまだ無い。

## 7. 移行の進め方（提案）

§4で未確定の項目（2, 3, 4, 5）はそれぞれ独立に着手できるため、次の順で
段階的に進めることを提案する。一括での大改修は、583件のtestのうち
`LocalEvidenceReview`／`app.private_story_e2e`／`app.web.private_evidence_review`
に関わるものへ影響するため避ける。

1. まず`HighlightReview`側（Director/Editorへ未接続、影響範囲が閉じている）で
   自動判定＋境界事例ログの契約を合成fixtureで実装・検証する。
2. 次に`LocalEvidenceReview`側（既存の`app.private_story_e2e`が依存する
   「全件confirmed」チェックを持つ）を自動判定へ移行する。影響する既存test
   （`tests/test_review.py`相当、`tests/test_private_story_e2e.py`等）を
   洗い出し、fail-closedの意味変更（§6参照）に沿って更新する。
3. 上記2つが緑になった後に、本設計書§3の橋渡し（highlight由来eventの
   Story Planへの合流）を実装する。
4. 実14 MP4データへの適用は最後。
