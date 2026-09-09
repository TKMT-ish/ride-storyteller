# IBM Bob session record — ScriptExecutor and the Director pipeline (2026-08-30)

The owner kept the text of the IBM Bob thread in which Bob designed and
implemented two slices of the story pipeline on its own task plan: **Step 4**,
`ScriptExecutor` (a `DirectorScript` becomes an FFmpeg render plan, fail-closed),
and **Step 5**, the Director pipeline behind a `director_mode` opt-in with a
Vertex AI Gemini transport. The screenshot taken during that session
(Bob's Todo list, 3/7 done) is the sanitised gallery image
`10-ibm-bob-plan-and-files.png`; the thread below is what the list was
tracking. Nothing here is an account detail, a credential, a path outside the
repository, or private media; Bob's usage figures were not part of the thread.

## What the repository shows today (verified 2026-09-09)

Every file Bob named exists, landed in one commit the next day, and its tests
still pass:

| Bob's item | File | Lines | First commit | Tests today |
|---|---|---|---|---|
| Step 4 `ScriptExecutor` | `app/executor.py` | 161 | `08f7099` 2026-09-01 "Build private story E2E workflow" | `tests/test_executor.py` (508 lines) |
| Step 5 Director pipeline | `app/director_pipeline.py` | 481 | `08f7099` | `tests/test_director_pipeline.py` (1,015 lines) |
| Step 5 Gemini transport | `app/agents/vertex_director.py` | 144 | `08f7099` | `tests/test_vertex_director.py` (added `eb2346b`, 2026-09-08) |
| `director_mode` opt-in | `app/local_pipeline.py` (`director_mode: bool = False`) | — | `08f7099` | covered by the pipeline tests |

The three test files pass together (58 tests) on the current tree. Bob's own
report of the session said 19 executor tests, 476 in the whole suite, Ruff
clean; the suite has since grown past 3,100.

The design Bob describes is the one in the code: the executor flattens
`DirectorScript.scenes → clips` in Director order, looks each `event_id` up
among the resolved clips, refuses a missing clip, a duplicate `event_id`, or a
source/offset mismatch (`ValueError`), and hands the ordered tuple to the
existing `build_ffmpeg_render_plan()` so that no FFmpeg command is generated
outside the render-plan module and the evidence gate is unchanged.

## The thread, as kept by the owner

```text
I have everything I need. The design is clear:

ScriptExecutor.execute() receives a DirectorScript + a lookup dict of ResolvedCandidateClip by event_id + a visual_evidence_confirmed_event_ids allow-list
It flattens DirectorScript.scenes → clips in scene order → builds the ResolvedCandidateClip tuple in that order → passes to existing build_ffmpeg_render_plan()
Fail-closed on: missing resolved clip, duplicate event_id, source mismatch
19/19. Now the full suite and ruff:

Five E501 violations — fix them:

Step 4 完了報告
変更ファイル
ファイル	種別
app/executor.py	新規作成
tests/test_executor.py	新規作成
既存ファイルへの変更はゼロ。build_ffmpeg_render_plan、render_local_review_film、ResolvedCandidateClip、CandidateClip、evidence gate — いずれも無変更。

ScriptExecutorの構造
ScriptExecutor.execute(
    script: DirectorScript,
    resolved_clips: tuple[ResolvedCandidateClip, ...],
    *,
    visual_evidence_confirmed_event_ids: tuple[str, ...] = (),
    output_file_name: str = "ride-storyteller-film.mp4",
) -> FfmpegRenderPlan

内部処理の流れ:

1. resolved_clips を event_id → ResolvedCandidateClip の辞書に変換
2. DirectorScript.scenes を順番に走査
3.   各 Scene.clips を順番に走査
4.     fail-closed checks (下記参照)
5.     通過した ResolvedCandidateClip を ordered リストへ追加（Director順）
6. build_ffmpeg_render_plan(tuple(ordered), visual_evidence_confirmed_event_ids=...) を呼び出す
7. FfmpegRenderPlan をそのまま返す

ScriptExecutor は FFmpeg コマンドを独自生成しない。

DirectorScript → ResolvedCandidateClipの対応方法
SceneClip.event_id をキーとして resolved_by_id 辞書を引く。クリップ順は DirectorScript.scenes → Scene.clips のネスト順をflattenした順序。カタログ側の元の順序・時系列順・chapter_id には依存しない。

fail-closed条件（すべて ValueError）
条件	エラーメッセージの特徴
SceneClip.event_id に対応する ResolvedCandidateClip がない	"no matching ResolvedCandidateClip"
同一 event_id が DirectorScript 内に複数回現れる	"appears more than once"
rc.asset_id != scene_clip.source_asset_id	"does not match"
rc.start_offset_s と scene_clip.source_start_sec の差が 1e-6 を超える	"start_offset_s"
rc.end_offset_s と scene_clip.source_end_sec の差が 1e-6 を超える	"end_offset_s"
evidence allow-listの取得方法
visual_evidence_confirmed_event_ids は呼び出し元（Step 5 の local_pipeline 統合）が confirmed_event_ids(plan) などから取得して渡す。ScriptExecutor 自身は allow-list を生成・判定しない。allow-list はそのまま build_ffmpeg_render_plan へ転送されるだけであり、既存の第2防衛線の動作を変えない。

追加テスト（19件）
Section	内容
1	単一confirmed clip → READY_FOR_FFMPEG / unconfirmed → NEEDS_HUMAN_REVIEW + command=None
2	DirectorのScene順が維持される / Scene内clip順が維持される / カタログ順に影響されない
3	対応するResolvedCandidateClipがない場合のfail-closed（全件ない / 一部ない）
4	同一event_idが複数Sceneに現れた場合のfail-closed
5–7	source_asset_id / start_offset / end_offset の不一致によるfail-closed
8	_OFFSET_TOLERANCE_S（1e-6）以内の浮動小数点誤差は許容
9	evidence allow-list が正しく転送される（全unconfirmed / 部分確認 / 全確認）
10	FFmpegコマンドは build_ffmpeg_render_plan 由来であること（ScriptExecutor独自生成ではない）
11	ResolvedCandidateClip のフィールドが変化しない（frozen dataclass 不変性の明示確認）
12	clip_count が DirectorScript の flatten 数と一致する
13	第1防衛線（Director入口）+ 第2防衛線（evidence gate）の両方が独立して機能することを確認
Step 4関連テスト結果
19 passed in 0.16s

全テスト結果
476 passed, 7 warnings in 8.34s

Ruff結果
All checks passed!

Step 5（app/local_pipeline.py への --director フラグ統合）には進まず停止します。

Let me thoroughly read the existing local pipeline and surrounding infrastructure before writing a single line.

Now let me check the vertex story copy transport to understand the Gemini transport pattern:

Now I have everything I need. The architecture is completely clear. Let me plan and implement:

app/agents/vertex_director.py — VertexAIGeminiDirectorTransport (mirrors VertexAIGeminiStoryCopyTransport pattern)
app/director_pipeline.py — run_director_pipeline() — the new E2E function with director_mode opt-in
Modify app/local_pipeline.py — add director_mode=False parameter, wire to run_director_pipeline when True
tests/test_director_pipeline.py — all E2E tests
Now I realize the run_director_pipeline function has a fundamental design issue: it tries to reconstruct minimal GpsEvent objects, but that's fragile. The real issue is that the existing pipeline already has real GPS events from extract_events. The Director pipeline should receive them. Let me reconsider the interface: run_director_pipeline should receive the real GpsEvent objects (which exist in prepare_local_review_package) rather than reconstructing them. Let me check what's available:

The existing prepare_local_review_package has events (real GpsEvents), resolved_clips, and candidate_plan (with CandidateClips). The director pipeline should receive these directly. Let me rewrite director_pipeline.py with a cleaner interface:

Now add director_mode to prepare_local_review_package in local_pipeline.py:

Now add director_mode and gemini_transport parameters to prepare_local_review_package, and the director_result field to LocalPipelineResult:

Now add director_mode and gemini_transport to prepare_local_review_package and call the Director pipeline when enabled:

Now wire the Director pipeline into the return value. Find the result construction and add the director call:

Now write the test file. First let me check what the to_universal_event requires from CandidateClip — specifically, it validates chapter_id matches between candidate_clip and resolved_clip. I need to make sure my test fixtures are consistent:
```

## How this is used in the submission

- Image gallery: `09` (Bob's review finding) and `10` (this session's task plan
  beside the files it produced).
- Project text: "How We Built It With AI Assistants" names Bob's review and,
  from this record, its implementation of the executor/director slice.
- The earlier review record stays in [`ibm-bob-evidence.md`](ibm-bob-evidence.md)
  and [`ibm-bob-review-sanitized.md`](ibm-bob-review-sanitized.md).
