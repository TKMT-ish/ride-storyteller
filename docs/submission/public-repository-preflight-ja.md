# 公開リポジトリ事前検査

## 目的

Devpost提出用リポジトリを公開する前に、秘密情報、実GPX、実動画、個人用
ファイルがGit追跡対象に含まれていないことを確認します。この検査は公開の
許可や公開済みであることを意味しません。

## 2026-08-24の検査結果

- Git追跡対象の実GPX、FIT、TCX、動画、音声ファイル: 0件
- Git追跡対象の提出用画像: 合成・公開安全モードのJPEG 5件、
  サニタイズ済みIBM Bob証拠PNG 1件
- `.env`: `.gitignore`で除外
- `.devpost-hackathon-state.json`: `.gitignore`で除外
- `.devpost-submission-answers.json`: `.gitignore`で除外
- 秘密情報テストと提出準備テスト: 16件すべて成功
- 全回帰テスト: 229件すべて成功（第三者SDKの非致命的な非推奨警告7件）
- `git diff --check`: 成功
- ルートライセンス: `AGPL-3.0-only`へ変更。完全な公式本文を配置し、
  提出前検査で`AGPL-3.0`として識別する。

`.env.example`と秘密情報検査コードはGit追跡対象ですが、実値を含めるための
ファイルではありません。公開直前には同じ検査を再実行します。

## 再実行コマンド

```bash
.venv/bin/python -m pytest tests/test_no_secrets.py tests/test_submission_readiness.py -q
git check-ignore -v .env .devpost-hackathon-state.json .devpost-submission-answers.json
git diff --check
```

## 未完了の外部ゲート

- リポジトリはまだ公開していない。
- 公開URLはまだDevpostへ登録していない。
- 公開UIから対応する公開ソースへの明示的な`Source`リンクは、公開URL確定後に
  設定・検証する。
- IBM Bobのプロジェクト固有・製品識別可能な安全な画面は取得・原寸確認済み。
- 実GPX・実動画の公開またはクラウド送信は引き続き未承認。
