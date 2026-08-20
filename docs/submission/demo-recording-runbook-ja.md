# 3分デモ撮影ランブック（日本語）

> 公開・録画前の操作順です。実メディア区間は、実動画アクセス、クラウド送信、
> 人による映像確認がすべて完了するまで撮影済みと扱いません。

## 撮影前チェック

- UI言語は英語。
- `public_demo`モードを使う。
- `.env`、Google Cloudコンソール、Box、実GPX、実動画、実ファイル名は開かない。
- ブラウザのブックマーク、プロフィール、メールアドレス、別タブを隠す。
- 画面解像度と文字サイズを固定し、通知を停止する。
- `docs/submission/demo-script-en.md`と
  `docs/submission/demo-subtitles-en.srt`を手元で確認する。

## 安全なローカル起動

プロジェクトフォルダで次を実行する。

```bash
RIDE_WEB_MODE=public_demo RIDE_UI_DEFAULT_LANGUAGE=en \
  python -m app.web.server
```

ブラウザで `http://127.0.0.1:8765/?lang=en` を開く。次を目視確認してから録画する。

- `Synthetic data`または同等の表示がある。
- public-safe-modeの説明がある。
- GPX、Google Maps、ローカルメディア、クラウド実行コントロールを使用できない。
- ページ内にメール、キー、Runtime名、バケット名、私用パスがない。

## 画面収録順

### 0:00–0:20

ホーム画面、問題、パイプライン概要を表示する。

### 0:20–0:50

Synthetic Story Planを実行し、GPSが候補を示すだけで映像内容を断定しないことを
説明する。

### 0:50–1:25

`accepted`シナリオを実行し、Story Agentの判断、ツール呼び出し、映像分析、
更新判断の順を表示する。続けて`missing asset`を短く表示し、人の確認へ安全に
止まることを示す。

### 1:25–1:50

Candidate Planを表示する。未確認映像があるためFFmpeg準備完了にならないことを
示す。

### 1:50–2:15

最終公開環境で承認済みの場合だけ、合成専用Agent Runtimeの結果を表示する。
モデル本文は表示せず、tool-call、final-response、`private_data_used=false`など
安全な完了メタデータだけを使う。public_demoモード自体からクラウド呼び出しは
行わない。

### 2:15–2:35

再取得したIBM Bob画面と`ibm-bob-evidence.md`の対応表を表示する。Bob画面は
`ibm-bob-capture-checklist-ja.md`の禁止情報検査を通す。

### 2:35–2:55

**REAL MEDIA GATE**。承認済みの実動画E2Eが存在する場合だけ収録する。存在しない
場合は、未完成の合成プレースホルダーを実出力と誤認させず、この区間を後日
差し替える。

### 2:55–3:00

英語の一文で終了する。

## 推奨ファイル名

- `01-home-en-public-safe.jpg`（取得済み・ローカル合成）
- `02-agent-accepted-en.jpg`（取得済み・ローカル合成）
- `03-agent-missing-asset-en.jpg`（取得済み・ローカル合成）
- `04-candidate-evidence-blocked-en.jpg`（取得済み・ローカル合成）
- `05-story-plan-synthetic-en.jpg`（取得済み・ローカル合成）
- `06-hosted-synthetic-metadata-en.jpg`
- `07-ibm-bob-sanitized.jpg`
- `08-real-media-confirmed-en.jpg`
- `ride-storyteller-demo-en.mp4`

## 撮影後チェック

1. 動画全体が3分以内である。
2. 音声がある場合は英語、ない場合も表示テキストと字幕が英語である。
3. 英語字幕の時刻を最終映像へ合わせる。
4. 秘密情報、私用パス、実GPX位置、未承認の動画名が1フレームもない。
5. アプリが動画で示したとおり動くことを公開URLで再検証する。
6. YouTubeまたはVimeoで公開表示にした後、未ログイン状態からURLを確認する。

このランブックは録画を実施した証拠ではありません。最終動画URLと未ログインでの
再生確認が別途必要です。
