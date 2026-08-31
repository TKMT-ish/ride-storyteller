# 4日間の物語E2E自律開発計画

更新日: 2026-09-01

## 到達目標

1回のツーリングを、確認済みの映像証拠だけから、`Hook → Build-up → Climax → Resolution`
の一貫した`DirectorScript`へ構成し、既存の決定論的Editorが安全に受け取れる状態にする。

これは映像の見栄えを競う機能ではなく、旅全体を一本の物語として再構成するためのMVPである。
未確認素材・位置座標・ファイル名・絶対パスを、物語の根拠や外部サービスへ流用しない。

## 固定する責務

```text
Scout     : 確認済みの出来事と利用可能な根拠を観測する
Director  : 根拠のある出来事を、物語上の順番と役割へ構成する
Editor    : DirectorScriptを忠実に実行し、映像証拠gateを再検査する
```

Directorは出来事・場所・映像を捏造しない。Blogger Modeで中盤の確認済み出来事を
Hookとして先に置くことは許容するが、同じ映像を重複させない。

## 4日間の実施順序

### Day 1 — 物語契約の固定

- RuleBasedDirectorの物語役割、出発・到着の扱い、重複禁止をテストで固定する。
- DirectorScriptの安全な表示用ビューを定義する。表示ビューにはsource asset ID、区間、
  ファイル名、座標を含めない。
- 既存のScout入力とEditor入力の間で、確認済み映像証拠だけが通過することを回帰テストする。

### Day 2 — 合成入力によるGemini Director経路

- 固定の完全合成UniversalEventだけで、Web経路のGemini DirectorとRuleBased fallbackを
  検証する。
- 実素材由来のイベントを外部Geminiへ送る経路は、明示的な`allow_external_director`なしでは
  停止することを維持する。
- この期間中にGeminiを自動実行しない。ボタン操作または別途明示された承認だけを実行契機とする。

### Day 3 — ローカル物語プレビュー

- private出力だけに保存できるDirectorScript artifactと、その安全な要約を検証する。
- 人手の`evidence-review.json`からconfirmedになったイベントだけをDirectorへ渡す。
- ハイライト品質reviewの「採用」は映像証拠confirmationとは別であり、自動接続しない。

### Day 4 — 決定論的Editorまでの接続と回帰

- ScriptExecutorがDirector順序を保持し、未確認・却下・時刻不一致ならFFmpeg commandを
  作らないことを検証する。
- 実動画の描画は、全候補の人手証拠確認後だけに限定する。音楽、公開、クラウド送信は範囲外。
- 全テスト、Ruff、差分検査を実行し、設計・履歴・テスト結果をNotionへ記録する。

## クレジット・外部利用の運用

- Codexの利用可能クレジット残高は、開発環境からプログラムで取得できない。そのため残高を
  推測せず、外部APIを使わない作業を常に優先する。
- LocalgenのDevstral/Gemma 4は、実素材を含まないテスト雛形、定型実装、文面の下書きに限定する。
  下書きは採用前に人間の設計判断とテストで検証し、利用後はmodelを常駐させずメモリを解放する。
- Gemini、Cloud Run、Artifact Registry、GitHub、Devpost、Box、実素材の外部送信は、4日間の
  自律実行対象に含めない。

## 継続中の自律チェック

1. 有意味な作業区切りごとに、正本の仕様・作業ツリー・既存テストを確認する。
2. 完了待ちの時間を置かず、次の最小の安全な実装またはテストを進める。
3. `pytest`、Ruff、差分検査を実行する。
4. 必要なNotionの02/06/07（設計変更時は01/04/05も）を更新し、再取得で確認する。
5. 外部利用・課金・公開が必要になった場合は実行せず、ローカル作業へ切り替える。

## 完了判定

- 4つの物語役割を持つDirectorScriptが、確認済みイベントのみから決定論的に生成される。
- Directorの出力が既存ScriptExecutorへ渡り、確認allow-listがない場合はfail closedになる。
- 合成経路ではGemini不在・失敗時にRuleBasedDirectorへ安全にfallbackする。
- 実データ、秘密情報、座標、パスが外部・公開物・非private artifactへ漏れない。
