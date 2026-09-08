# データの流れ——端末の外へ出るもの、出ないもの

利用者（ライダー）に説明できる形で、Ride Storyteller が**端末の外へ送るデータ**を段ごとに列挙する。
ここに無いものは送っていない。実装が変わったら、この表を同じ commit で直す。

最終更新: 2026-09-07（節の地名の追加時）。

## 1. 一覧

| 段 | 端末の外へ出るもの | 送り先 | 出ないもの | 根拠（コード） |
|---|---|---|---|---|
| 取り込み | なし | — | GPX・動画・ファイル名・時計のズレ | `app/web/private_journey_intake.py`（`private-media/input` 配下の読取りのみ） |
| 計画（plan / preflight） | なし | — | 候補窓の一覧・費用見積は端末内で計算 | `app/analysis_run.py` `plan_analysis_run`（ネットワーク client を開かない） |
| 判定（judge） | **判定窓の縮小コピー**（480p・1 fps・無音・12 秒、1 本 ≈ 0.7 MB）。窓ごとに 1 ファイル | Google Cloud Storage（自分のプロジェクトの私有バケット `ride-storyteller-analysis`、asia-northeast1、公開アクセス防止）→ Vertex AI の Gemini 2.5 Flash が読む | 4K の原動画・GPX・ファイル名・撮影時刻・座標。コピーの名前は候補 ID（窓の時刻から作ったハッシュ） | `app/analysis_run.py` `run_analysis`、`app/video/vertex_transport.py` |
| 比較順位（rank） | 判定で送ったコピーの **URI**（再アップロードなし） | Vertex AI Gemini | 上と同じ | `app/analysis_ranking.py` |
| 物語の計画 | なし | — | 章・尺・題は端末内で決める | `app/private_journey_film.py` `plan_journey_film` |
| **地図背景（E-10）** | **走行範囲の外接矩形の中心座標（小数 5 桁）とズーム倍率、画像サイズ、配色** | Google Maps Platform（Maps Static API）。1 作品あたり 1〜2 リクエスト、結果は package 内にキャッシュ | 経路そのもの（点列）・時刻・ファイル名。経路の線・現在位置は端末内で地図の上に描く | `app/map_background.py` `static_map_url`（`path=`・`markers=` を含まないことをテストで固定） |
| **地名（点 2・節）** | **行程の両端、通過した町の中央、停止地点の座標（小数 4 桁、約 10 m）と言語**。1 点 1 リクエスト、結果は package 内 `place-names.json` にキャッシュ | Google Maps Platform（Geocoding API） | 経路そのもの・時刻・ファイル名。停止した場所の座標は行程の端として送られる（町名を得るため） | `app/place_names.py` `geocoding_url`（`latlng`・`language`・`key` 以外を含まないことをテストで固定） |
| 作品の生成 | なし | — | 作品ファイル・字幕・カードは端末内 | `app/story_film.py`（ffmpeg・Quick Look はローカル） |
| 音楽 | なし | — | 曲は端末内のライブラリ | `app/story_music.py` |
| コンソール（画面） | なし（127.0.0.1 のみで待ち受け） | — | 作品の配信も同じ端末のブラウザへ | `app/web/deployment.py`（既定 host 127.0.0.1） |

## 2. 送る前に必ず通る門

- **費用の門**: 判定は `plan` が示した金額を**そのまま入力**しないと始まらない（CLI `--i-approve-spending`、
  画面は金額の入力）。数字が違えば拒否。
- **鍵**: Google の鍵（ADC、Maps の API キー）は端末の環境設定にだけあり、ログ・commit・Notion に書かない。
- **地図**: 鍵が無い、サービスが拒否した、`RIDE_MAP_STYLE=none` のいずれでも作品は**黒地の経路図で**でき、
  結果 JSON に `map_background: "none"` と出る。地図のために作品が止まることはない。
- **地名**: 鍵が無い、Geocoding API が有効でない、届かない、のいずれでも章題は地形の語に戻り、作品はできる。

## 3. クラウド側に残るもの

- GCS のバケットには判定窓の縮小コピーが残る（再判定・比較順位で再利用するため）。原動画は一切ない。
  削除はバケットの中身を消せばよい（利用者ごとの削除は多利用者化の設計項目、`cloud-architecture-ja.md` §5）。
- Vertex AI は入力を学習に使わない契約（Google Cloud の Vertex AI データ利用条件）。
- Maps Static API のリクエストは Google 側のアクセスログに残る（中心座標とズームのみ）。

## 4. 製品の言葉で

> あなたの動画は、あなたの Mac から出ません。AI に見せるのは 12 秒ごとの小さなコピー（画質を落とし、音を消したもの）
> だけで、それもあなた自身の Google Cloud に置かれます。地図を出すために Google に伝えるのは「その日走った範囲の
> 真ん中がどこか」、章の題に町名を入れるために伝えるのは「各行程の始点と終点がどこか」だけで、走った道筋そのものは送りません。

## 5. 関連

- [`cloud-architecture-ja.md`](cloud-architecture-ja.md)（段の分担と多利用者化）
- [`demo-runbook-ja.md`](demo-runbook-ja.md) §0.5（画面からの手順）
- [`completion-roadmap-ja.md`](completion-roadmap-ja.md) Gate 7（単位経済と品質単位）
