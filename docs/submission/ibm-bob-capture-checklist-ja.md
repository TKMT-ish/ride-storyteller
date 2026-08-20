# IBM Bob証拠画面の再取得チェックリスト

> 以前のIBM Bobレビュー本文は保持されていますが、元スクリーンショットの
> ローカルファイルは消失しています。IBM trackでBob使用を実証するため、
> プロジェクト固有の新しい画面を1枚以上再取得します。

## 取得前の準備

1. IBM Bob IDEを起動する。
2. `Ride Storyteller`フォルダを開く。
3. `.env`、Google Cloudコンソール、認証ファイル、実GPX、実動画、私用
   カタログは開かない。
4. Bobのチャット領域が見え、IBM Bobの製品名またはロゴを確認できる状態に
   する。

## Bobへ渡す安全な確認プロンプト

以下は公開予定コードだけを対象にした再確認用です。

```text
Review the current Ride Storyteller implementation as IBM Bob. Focus only on
public repository files. Verify whether the earlier findings about Google ADK
wiring, attributed visual-evidence transitions, schema-constrained Gemini video
analysis, and fail-closed boundary tests are now addressed. Cite specific
repository-relative files and tests. Do not inspect or display .env files,
credentials, account details, cloud resource names, private filesystem paths,
GPX data, or video file names. End with one concise remaining-risk statement.
```

Bobの回答に、少なくとも1つの具体的な相対パスと、実装済み／未実装の判断が
表示されるまで待ちます。秘密情報や私用パスが表示された場合、その画面は
保存せず、プロンプトを修正してやり直します。

## スクリーンショットに含めるもの

- IBM Bobの製品名、ロゴ、または製品UI
- `Ride Storyteller`のプロジェクト文脈
- 具体的なBob所見
- 例: `app/agent_runtime/adk_agent.py`、`app/edit/candidate_planner.py`、
  `tests/test_evidence_status.py`

## 含めてはいけないもの

- メールアドレス、氏名、アバター、課金情報
- APIキー、OAuth情報、トークン、`.env`の値
- Google CloudのRuntime名、バケット名、請求先ID
- 実GPXの地名・座標・時刻
- 実動画のファイル名や私用フォルダの絶対パス
- ブラウザのブックマーク、別プロジェクト、無関係なタブ

## 保存と検証

1. 画面全体ではなく、IBM Bob製品UIと所見が分かる範囲に切り抜く。
2. フル解像度で拡大し、禁止情報がないことを目視確認する。
3. 一時的に `docs/submission/private-review/` など公開対象外の場所で確認し、
   Codexの秘密情報検査を通した後だけ公開用assetsへ移す。
4. `docs/submission/ibm-bob-evidence.md`に画像への相対リンクと取得日を追記する。
5. Devpostの説明と3分動画のIBM Bob区間で同じ証拠を使用する。

このチェックリスト自体は証拠ではありません。IBM Bob製品UIに表示された
プロジェクト固有のレビュー画面が必要です。
