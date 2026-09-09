# 公開リポジトリ事前検査

## 目的

Devpost提出用リポジトリを公開する前と、公開後の更新前に、秘密情報、実GPX、
実動画、個人用ファイルがGit追跡対象に含まれていないことを確認します。

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

## 2026-08-25｜Sourceリンク公開ゲートの実装

- `RIDE_SOURCE_REPOSITORY_URL`をWeb配備設定へ追加した。
- HTTPSのGitHub／GitLab／Bitbucketのリポジトリroot URLだけを許可し、認証情報、
  query、fragment、subpage、末尾slashを拒否する。
- 設定時は公開UIに日英の`Source code (AGPL-3.0)`リンクを表示する。
- 未設定の`public_demo`は公開準備未完了の警告を表示する。
- Cloud Run計画は、Source URL未設定では`--no-invoker-iam-check`を生成しない。
  private配備・認証付き確認は引き続き可能。
- URL検証、日英表示、欠落時停止、Cloud Run公開ゲートの集中テスト63件が成功。

## 未完了の外部ゲート

- 公開リポジトリは作成済みで、`main`は公開commit `6998221`と一致する。
  URL: <https://github.com/TKMT-ish/ride-storyteller>
- 公開URLはまだDevpostへ登録していない。
- 公開UIの`Source`リンク機能と実URL設定は認証付きprivate Cloud Runで検証済み。
  unauthenticated公開は未承認のため、一般公開URLとしての再検証は未完了。
- IBM Bobのプロジェクト固有・製品識別可能な安全な画面は取得・原寸確認済み。
- 実GPX・実動画の公開またはクラウド送信は引き続き未承認。

## 2026-08-30時点の注意

実素材E2Eとハイライト研究を含む現在の作業ツリーには未commit変更がある。
したがって、公開`main`とローカル開発版は同一ではない。次回push前に、この
文書の再実行コマンド、全回帰テスト、Ruff、差分確認をもう一度実施する。

## 2026-09-07｜公開の前に決める1点: 履歴に残る地名

**作業ツリーは地名を含まない**（同日 commit `cedd104` で、自分のコメント6か所・
テストfixture3ファイル・設計記録1行を実地名なしの書き方に直した）。確認:

```bash
grep -rniE "実地名を列挙したパターン" app tests docs README.md devpost-submission.md
```

**しかし履歴は含む**。公開 `main`（`6998221`、2026-08-25）から現在までの
417 commit の差分には、走行した町の名前が 47 行ある。実素材で作品を作り始めた
のがその後だったため。したがって**そのまま push すると地名が公開される**。

選択肢は2つ。**どちらを選ぶかはオーナーの判断**であり、当層では実行しない。

1. **履歴を持ち込まない（推奨）**: 現在のツリーだけを1 commit として公開する。
   開発の経緯は Devpost の write-up と本リポジトリの設計記録が語る。

   ```bash
   git checkout --orphan public-release
   git add -A
   git commit -m "Ride Storyteller"      # 内容は現在のツリーそのまま
   git log --oneline                      # 1 commit であることを確認
   git push origin public-release:main --force-with-lease   # 承認後にだけ
   git checkout main                      # 元のブランチへ戻る
   ```

   `--force-with-lease` は公開 `main` を置き換える。公開済みの `6998221` を
   残したい場合は先に `git push origin 6998221:refs/heads/archive-2026-08-25`。

2. **履歴ごと公開する**: 審査員に開発の経緯が見える利点があるが、走行した町の
   名前が公開される。これを選ぶ場合は、地名が特定するのが「12日間の観光ルート」
   であって自宅ではないことを確認したうえで決めること。

いずれの場合も公開直前に本文書の再実行コマンド・全回帰テスト・Ruff・
`python -m app.submission` を通すこと。

## 2026-09-09｜実行: 現在のツリーだけを公開 `main` に載せた

オーナーの判断（2026-09-09 03:30 JST）は「**現在のツリーのみ**」。実行した内容:

1. **二度目の地名除去 `cb43326`**。初回 `cedd104` 以後、テスト fixture 8 ファイルと
   handoff 3 行が走行地名（町・郊外・道路・展望地）を拾い直していた。検査は
   手打ちの語ではなく、実素材の地名キャッシュ
   `private-media/work/*/place-names.json`（1,223 語、マクロン有無の両方）で
   HEAD のツリー全体を照合した。公式ツーリングルート名と国道番号は全国の参照
   データなので残し、町・郊外・道路・展望地は同じ形の架空名に替えた。
2. **1 commit `548c2b8`** を `git commit-tree cb43326^{tree} -p origin/main` で作り、
   公開 `main`（`3a27970`、既に公開されていた 49 commit）の上に fast-forward で
   push した。force push はしていない。私有履歴（約 420 commit）は dev ミラー
   だけに残る。以後の更新も同じ方法で 1 commit ずつ載せる。
3. 配布物 `ride-storyteller-day-7.zip`（1,730,095,484 バイト）と `.sha256` を
   **draft release** `day-7-package` に添付した。draft は公開リポジトリでも
   共同作業者にしか見えず、タグは公開時に作られる。
4. **可視性の変更は当層では実行していない**（自動モードの分類器が公開操作を
   止めた）。オーナーが実行する 1 コマンド:

   ```bash
   gh repo edit TKMT-ish/ride-storyteller --visibility public --accept-visibility-change-consequences
   ```

   release の公開も同様に 1 コマンド（`gh release edit day-7-package --draft=false`）。

再検査の手順（公開 push の前に毎回）: HEAD のツリーを上記キャッシュの語で照合し、
`docs/research-touring-video-editing-ja.md` 以外に走行地名が 0 件であることを確認
してから、クリーンな worktree で全テスト・Ruff・`python -m app.submission` を通す。

## 2026-09-09｜remote の名前を整理した

デスクトップアプリが `origin` を基準に差分を数えるため、`origin` を私有ミラー
（`ride-storyteller-dev`）に付け替え、公開リポジトリは **`public`** という remote 名にした
（`dev` は従来どおり私有ミラーの別名として残す）。以後、公開 `main` へ載せるときは
`git push public <squash>:refs/heads/main`。この文書の上のほうにある `git push origin …` は
当時の名前で、いまなら `public` と読み替える。

