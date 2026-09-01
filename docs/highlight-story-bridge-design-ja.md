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

ユーザー承認のもと、実データ（GoPro 49ファイル・68 GiB、実GPX）で本橋渡しを
末端まで実行した。結果は技術的には成功だが、設計上の重要な限界が判明した。

### 実行結果

- `highlight_research`: 797窓解析→strict gate 603→最終品質gate 59→
  4方式×8本=32件が**自動承認32、awaiting 0、rejected 0**（境界事例ログ12件）。
  コード変更なしで完走。
- `app.local_pipeline --highlight-bridge-candidates`: GPS由来event 24件と
  highlight由来候補32件（重複統合前）を合流させたところ、**新規追加された
  eventは0件**だった。32件全てが既存のGPS由来eventの時間窓と重なっていたため
  （本設計書§3の「重なれば新規追加しない、重ならなければ追加する」方針の
  「重ならない」側にどの候補も該当しなかった）。
- 最終的に選ばれた7 chapter・7 matched clipは全てGPS由来eventのみで、
  highlight由来のものは1件も含まれない。

### 分かったこと

strong_turn laneは方位変化・経路効率というGPS由来の信号を使っており、
GPS側の`direction_change`検出と本質的に同種の信号を見ている。そのため
「強い旋回」候補は、GPSが既に検出済みの方向転換eventと高確率で時間的に
重なる。今回の実ライド（約4.2時間・24 event）では、strong_turn・
visual_eventの両laneを合わせた32候補が**すべて**既存eventと重なった。

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
