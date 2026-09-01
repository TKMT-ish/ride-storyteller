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
