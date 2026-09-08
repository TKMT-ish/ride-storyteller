# 研究: より良いツーリングビデオ編集とは何か（2026-09-05）

オーナーの指示: 「より良いツーリングビデオ編集とは何か、研究を進めて下さい。ストーリーに沿ったクリップの
選び方、クリップ長、ルート表示の入れ方、タイトル、ビデオ編集に関する知識を蓄えて下さい。」

前回の研究 [`research-touring-video-quality-ja.md`](research-touring-video-quality-ja.md)（10 規則、S1〜S4）を
土台に、指定の 5 点を深掘りした。所要約 2 時間、出典は日英・学術・制作者・コミュニティから 25 件弱。
地名・ファイル名・実素材は書かない。当システムの前提（GPS + 判定済み窓、入力なし、地名なし、単一 POV）への
写像を §7 に置く。

## 0. 結論——編集が守るべき 12 の規則

| # | 規則 | 根拠 |
|---|---|---|
| E1 | **クリップは「並び」で選ぶ**。1本の良し悪しではなく、隣との関係（変化・対比・つながり）で決める。連続する B ロールには「連鎖（sequential）」と「挿絵（illustrative）」の 2 種があり、混ぜて置くと散らかる | ITE-B, Splice, NFS |
| E2 | **テンポは 4 つの要素の合算**: カットの頻度・画面内の動きの速さ・被写体との距離・カメラの動き。POV は距離とカメラ動きがほぼ一定なので、**カット頻度と画面内の動き**しか使えない | ITE-P |
| E3 | **テンポの変化には理由が要る**。速い→遅いは感情の設計（速い=緊張、遅い=余韻）。理由の無い変化は素人の印 | ITE-P |
| E4 | **走行ショットは 4〜8 秒**、モンタージュの山場は 0.5〜2 秒で拍に合わせ、**その後に長い1本で息をつかせる**。現代映画の平均ショット長は 4〜6 秒（古典期は 8〜11 秒） | vidpros, SLT, Wiki-ASL, movieru |
| E5 | **撮影は 10 秒以内、使うのは 1〜2 秒が大半**（日本の制作者の共通見解）。12 秒をそのまま並べるのは長い | rantaka-1, rantaka-2, ABR |
| E6 | **同じ尺・同じ絵を続けない**。緩急（寄り・引き・タイムラプス・B ロール）が「メリハリ」を作る。退屈の原因は「同じカットの連続」と「ストーリーがない」の 2 つ | rantaka-1, Filmora-JP, demogoru |
| E7 | **ルート表示は「全体→区間→全体」**。冒頭に全行程（6〜8 秒）、章の境目に区間（3〜5 秒、到達点で 1〜3 秒止める）、締めに全行程＋統計。**同じ速さで全区間を見せない**（脚ごとに速度とズームを変える） | animaps, pippit, Relive |
| E8 | **地図は統計と写真を伴ってはじめて物語になる**。Relive（3D 地図＋距離・高度・速度＋写真、約 1 分、2,200 万人）は成功、Strava flyover（点が線をなぞるだけ）は失敗。単純な地図でも「指でなぞる」だけで機能した例（Itchy Boots）がある | Relive, A4（前回）, motovlog-map |
| E9 | **テロップは短く・太く・縁取り・簡素な動き**: 6 秒に約 21 字、太いゴシック、背景と分離（縁取りか座布団）、動きは 1.5 秒以内、「全部を 2 回読める長さ」だけ出す（単純な下三分の一は 3〜5 秒、複雑なら 5〜10 秒、出入りは 15〜25 フレーム） | meec-11, frame.io, vimeo-LT, riverside |
| E10 | **題は引き、本文は答え**。冒頭は疑問・感覚語・答えの保留で引き、章題は「今日の課題」（峠・距離・目的地）、終わりは情緒の昇華。テロップに句読点を使わず空白で区切る | A1（前回）, douga-branding |
| E11 | **音は映像より許されない**。走行は自然音（エンジン・風・路面）が現実感、曲を使うなら場面に合わせて（走行 BPM130+、風景はアコースティック/環境音、締めはゆったり）。J/L カット（音を先に/後に）でつなぎを滑らかに | CC, SJCAM, demogoru, Wiki-Lcut |
| E12 | **色と明るさを揃える**。露出・WB・コントラスト・彩度をクリップ間で合わせる。不揃いは絶景でも素人の印。速度を変えたショットにはモーションブラー | insideeditors, Nadir |

## 1. 方法と限界

- 検索は英語・日本語で計 15 回、本文を読めた出典は 17（一部は 403/404 で要旨のみ）
- バイクツーリング動画に**限った**定量データは依然として無い（ASL・維持率は一般動画の値の転用）
- 成功チャンネル（Itchy Boots 等）の**内部の編集規則は非公開**（有料講座）。視聴者の言葉と公開インタビューから読んだ
- 「評価の高い」の判定は前回と同じ 4 面（制作者の自述・視聴者の共感・学術・自動生成の成否）

## 2. ストーリーに沿ったクリップの選び方

### 2.1 何を根拠に選ぶか

- **B ロールの 2 種**（ITE-B）: **連鎖**（過程・旅・進行を示す一連のショット。各ショットが「次」への環）と
  **挿絵**（気分・場所・文脈を足す単独のショット）。編集者は縦横 2 軸で置く——横軸は物語の進行（時系列に
  連鎖）、縦軸は感情の一致（その瞬間の意味を強める画）。「画をカバーのために置くのではなく、意味に合わせて置く」
- **「何が変わったか」で選ぶ**（前回 E3・E7）: 天候・地形・道の性格・停止・出発・到着・迷い。**POV は物語の
  明瞭さに最も価値が低い**——だから POV しか無い当システムでは、章（変化）が物語を担う
- **旅動画の実務**（Splice, NFS）: まず「何も起きていない」「揺れている」ショットを捨て、各素材の**ハイライトを
  決めてから**時系列か主題で並べる。速い区間は短く、思索的な区間は長く。拍に合わせて切る
- **自動要約の 3 基準**（前回 A5）: 面白さ・代表性・多様性。当システムは面白さ（順位）と代表性（章ごと）を持ち、
  **多様性は Q2（見た目）で初めて入った**

### 2.2 「並び」の設計——当システムに足りないもの

現状の選別は「順位が高い順に、章ごとに、似た絵を避けて」。これは**1 本ずつの評価**で、**隣との関係**を
見ていない。E1〜E3 から、章の中の並びに次の規則を足す:

1. **章の最初の窓は「連鎖の起点」**——章の性格を最も端的に見せる窓（順位より「章の題に合う」を優先。
   例: 「長い下り」章は下っている絵で始める）
2. **章の中は「変化の向き」で並べる**——同じ向き（ずっと平坦な直線）を 3 本続けない。動きの量
   （フレーム差）の大小を交互に
3. **章の最後の窓は長め**（E4 の「息」）
4. **停止の章は挿絵 1 本**（Q0）＋直前の走行の余韻

### 2.3 冒頭の 15 秒（前回 E4 と一致）

cold open は**走行の絵**（停止地点の屋内ではない。S2 追補）で、動きのある 1 本。その上に「今日の見出し」。
続けて出発の章。**冒頭 15 秒に説明カードを置かない**。

## 3. クリップ長

| 出典 | 数字 |
|---|---|
| 現代映画の平均ショット長（Wiki-ASL） | **4〜6 秒**（古典期 8〜11 秒） |
| 旅 Vlog（vidpros） | **4〜8 秒**（YouTube Vlog 一般も 4〜8 秒） |
| ドキュメンタリー（vidpros） | 7〜25 秒 |
| 音楽同期のモンタージュ（vidpros, SLT） | 2〜6 秒、山場は **0.5〜1 秒**で拍に合わせ、**最後に長い 1 本** |
| 日本の制作者（rantaka, movieru） | **撮影 1 カット 10 秒以内・使うのは 1〜2 秒**、Vlog は 5 秒前後で切替 |
| Adventure Bike Rider（前回 E9） | 7 秒未満は使わない、撮るなら 10 秒 |

### 読み方

- 走行 POV の「内部の動き」は少ない（E2）ので、**同じ 8 秒でも景色が変わらなければ長く感じる**。
  尺は順位だけでなく**画面内の変化量**で決めるべき（変化が少ない窓ほど短く）
- 最良の 1 本（cold open・章の締め）は 8〜10 秒、通常は 5〜7 秒、つなぎは 3〜4 秒、**同じ尺を 3 本続けない**
- 12 秒の判定窓から**どの 6 秒を使うか**も選べる（前半/後半で動きの多い側）。これは無料（1fps コピーで測れる）

## 4. ルート表示の入れ方

### 4.1 何が機能し、何が失敗したか

- **Relive**（成功、2,200 万人）: 3D 地図の上を経路が伸び、距離・高度・平均速度と**写真のポップアップ**、
  約 1 分。統計と写真が「地図を物語にする」
- **Strava flyover**（失敗、前回 A4）: 点が線をなぞるだけ、統計も写真も無く、1 分の走行=1 秒で長い
- **Itchy Boots**: 紙の地図に蛍光ペン、指でなぞる。**それだけで登録者が伸びた**（motovlog-map）。
  精巧さより「今どこで、どこへ向かうか」が伝わることが要点
- 日本の実践（Filmora-JP, PowerDirector, Google Earth）: 冒頭に「動く走行ルート」で行程説明、
  ペイントや Ken Burns で線を引く。**冒頭**に置くのが定番

### 4.2 尺と置き方（animaps, pippit, Corel）

- 説明の地図は **3〜8 秒**。短い脚は 3 秒、長い脚は 6〜8 秒。**到達点で 1〜3 秒止める**
- **脚ごとに速さとズームを変える**（同じ速さで全区間を見せると単調）
- 地図の動きは語りに合わせ、**要点の前でカメラを止める**（当システムでは題・本文の前で止める）

### 4.3 当システムへの写像

現状: 章カードに「地図無しの経路線＋その区間の強調」。これは E8 の「統計を伴う」を満たすが、**動かない**。

| 置き場所 | 内容 | 尺 |
|---|---|---|
| 冒頭（cold open の直後） | 全行程の線が**描かれていく**（6〜8 秒）、その上に今日の見出し（距離・時間・登り） | 6〜8 秒 |
| 章の境目 | 全行程を薄く、**その章の区間を太く**、区間の始点→終点へ 3〜5 秒で伸びる。到達点で 1〜2 秒止め、そこで題と本文 | 5〜6 秒 |
| 締め | 全行程が描き切られ、統計（Relive 型） | 6〜8 秒 |
| 走行中の隅の小地図 | **既定では出さない**（POV の上に常時何かを置くと注意が割れる。テロップ規則と同じ） | — |

地図は「地名の無い経路線」で良い。**進行の位置（どこまで来たか）**が没入の一部（前回 A3）。

## 5. タイトル（章題・テロップ・見出し）

### 5.1 テロップの 11 条件（meec-11、要約）

背景と分離（縁取り or 座布団）／大きさにメリハリ／色で強調／適切なエッジ／ベースを使う／**文は短く（6 秒に約 21 字）**／
コンセプトに合う／**太いフォント**／**シンプルなフォント（ゴシック）**／**動きは 1.5 秒以内**／装飾は要点だけ。
テロップに「、。」を使わず空白で区切る（douga-branding）。

### 5.2 下三分の一（lower third）の型（frame.io, vimeo-LT, riverside）

- 単純なもの 3〜5 秒、複雑なもの 5〜10 秒。**「全部を 2 回読める長さ」**
- 出入り 15〜25 フレーム（25fps）、フェード/スライド/95%からのスケール、必ずイージング
- 上位: 大きい（章題）、下位: 小さい（本文）。1 枚に 1 メッセージ
- 高コントラスト、背景の矩形、安全域、被写体の目や口を隠さない

### 5.3 当システムへの写像

現状: 全画面の章カード（題＋本文＋経路図、6 秒、動きなし）。研究の示唆:

- **章題は動く絵の上に**（前回 E7「静止画ではなく動く絵の上にタイトル」）。章カードを「章の最初の窓の上に
  下三分の一で 5 秒」に置き換える案。経路図は右下に小さく 5 秒だけ
- **題は 12 字以内、本文は 21 字以内**（1 行）。現状の本文「出発から3時間06分 · 142.0km · 海抜815m → 67m」は
  約 30 字で長い → 2 段（題の下に距離・時間、その下に高低差）か、1 段に絞る
- **題は引き**（A1）: 「峠を越える」より「この先、峠」、「長い下り」より「ここから下る」。疑問・保留の型を
  語彙に足す（「次の町まで」「風が変わる」）

## 6. 編集技法（当システムに関係するもの）

- **J/L カット**（Wiki-Lcut）: 音を画より先に/後に切り替える。当システムでは**隣り合う窓の自然音を 0.5 秒
  クロスフェード**すれば、硬いカットが和らぐ（無料）
- **音**（CC, SJCAM）: 「視聴者は悪い音を許さない」。風切りは撮影側の対策（マイク位置・ウインドジャマー）。
  編集側は**風切りが酷い窓だけ音量を下げる**（前回 E8 の折衷）。エンジン音・路面・バイザーの音が現実感
- **色**（insideeditors, Nadir）: 露出・WB・コントラスト・彩度を揃える。当システムなら ffmpeg の自動レベル
  （窓ごとの輝度正規化）が無料で入る。**速度を変えるならモーションブラー**——変えない方が安全
- **タイムラプス**（rantaka-3, Filmora-JP）: 時間の経過を凝縮して「旅のテンポ」を作る。当システムは
  **1fps の縮小コピーを既に持っている**——章の未撮影区間や長い停止の前後を、コピーからタイムラプスに
  できる（無料の B ロール。前回規則 6「時間の経過を見せる」）。ただし 480p なので**小さく（ピクチャ・イン・
  ピクチャや地図の隣）**使う
- **トランジション**: 基本はカット。ディゾルブは章の境目だけ。派手な効果は不要
- **POV の単調さ**（RideNest, chinmounts）: 角度を変える・バイクを外から撮る——**当システムには無い素材**。
  代替は、章（変化）・タイムラプス・地図の動き・尺の変化で「同じ絵」を切ること

## 7. 当システムへの写像——編集の単位 E-1〜E-7（S1〜S4 の後、または並行）

| 単位 | 内容 | 閉じ方 |
|---|---|---|
| **E-1 章内の並び** | 章の最初の窓は「章の題に合う」窓、章内は動きの多寡を交互に、最後は長め（§2.2） | 2 ride で同じ向きが 3 本続かない。オーナー再視聴 |
| **E-2 尺を変化量で決める** | 窓の尺を順位×画面内の変化量（1fps フレーム差）で 3〜10 秒に。12 秒のどの 6 秒を使うかも動きで選ぶ | 同じ尺が 3 本続かない。平均 5〜7 秒 |
| **E-3 動く経路図** | 冒頭 6〜8 秒の全行程描画、章の境目に区間の伸び（3〜5 秒＋停止 1〜2 秒）、締めの全行程＋統計 | 2 ride で描画。オーナーが「どこまで来たか分かる」と言う |
| **E-4 題を動く絵の上に** | 章カードを「章の最初の窓の上の下三分の一 5 秒」に。題 12 字・本文 21 字以内。題の語彙に「引き」を足す | 章カード全画面が消え、冒頭 15 秒にカードが無い |
| **E-5 音のつなぎ** | 隣り合う窓の音を 0.5 秒クロスフェード、風切りの酷い窓は自動で −6 dB（RMS で判定） | 硬いカットが無い。オーナーが音に触れない |
| **E-6 色を揃える** | 窓ごとの露出・コントラストの自動正規化（ffmpeg）。速度変更はしない | 隣接窓の輝度差が閾値内 |
| **E-7 コピーからのタイムラプス** | 長い停止の前後・未撮影区間を 1fps コピーのタイムラプスで 3〜5 秒（小窓）。時間の経過を見せる | 2 ride で 2〜3 箇所。オーナー再視聴 |

順序の推奨: **E-3 → E-4**（見た目の印象が最も変わる。オーナー指摘「タイトルがストーリーを表せていない」の続き）
→ **E-1 → E-2**（単調さ）→ **E-5 → E-6**（品位）→ **E-7**（余裕があれば）。すべて無料（モデル支出なし）。

## 8. 研究で決着しなかったこと

- 隅の小地図（常時表示）を視聴者が好むかは出典が割れる（テレメトリ系は「情報が多い」派、Vlog 系は
  「注意が割れる」派）。当システムは**既定オフ**で、E-3 の後にオーナーの好みで判断
- 章題の「引き」の語彙が日本語の旅動画でどこまで自然かは、オーナーの再視聴で決める
- BGM の合致（景色×曲）は前回と同じく未決。既定は無音のまま

## 10. 冒頭ハイライト（1 秒 × 4）の選び方——調査（2026-09-07）

オーナーの要望: 冒頭は各 1 秒のハイライト 4 本、「見栄えのする絵」（都市景観、郊外の景色、休憩地で撮った映像）。
調べた範囲での結論と、当システムへの写像。

### 10.1 出典が言うこと

- **最初の 3〜5 秒が勝負**。視聴者は数秒で見続けるか決めるので、その日で最も刺激のある絵（俯瞰、賑わい、劇的な
  風景）から入り、話は後から戻す（Teleprompter、Insta360、Clipchamp の旅動画ガイド）。
- **B ロールは短くてよい**。人は情報を一瞬で受け取るので 1 秒前後のカットで足りる。長いパンは冒頭ではなく
  終わりに置く（Adventure Bike Rider、Itchy Boots の指南）。
- **確立 → 寄り → 引きの終わり**という順（Adventure Bike Rider）。冒頭モンタージュは音楽の拍に切る。
- **「絵になる」＝写真として残したいか**。研究では、動きの大きさではなく**写真の美的基準**（構図・対称性・
  色の鮮やかさ）で egocentric 旅動画のフレームを順位づけ、GPS で場所の重要度を重みづけると人の選択に近づく
  （arXiv 1601.04406 "Discovering Picturesque Highlights from Egocentric Vacation Videos"）。
  Videogenic（CHI 2024）は**プロの写真を事前分布**にして「写真らしい瞬間」を探し、利用者はそれをハイライトと
  認めた。
- **多様性**。同じ被写体・同じ構図を続けない。ハイライト検出の研究も冗長性の除去を前提にする。

### 10.2 当システムへの写像

1. **判定に「写真として残したいか」を聞く**: `photogenic_score`（0〜1、構図・光・主題・色。動きは問わない）と
   `highlight_subject`（vista / mountains / water / cityscape / landmark / winding_road / sky / rest_stop / none）。
   これは走行の良さ（`visual_interest_score`）とは別の軸。停車中の絵（休憩地の眺め）も対象になる。
2. **選び方**: その日の窓から、`photogenic_score` 高い順に、**被写体の種類が重ならない**よう、**20 分以上離して**、
   一日の前半・中盤・後半に散るよう 4 本。運転手が大きく映る窓と駐車場だけの窓は除く（`rest_stop` で写真的な
   ものは許す）。旧記録（`photogenic_score` 無し）は `visual_interest_score` と `scenery_tags` の語で代用。
3. **切り方**: 各 1 秒。窓の中で動きが中程度の位置（E-2 の半分選びと同じ系列）から 1 秒。走行順に並べる。
4. **その後**: 第 1 章の全画面カード。ハイライトは本編でも改めて出る（別の長さで）。

### 10.3 決まっていないこと

- 旧記録に `photogenic_score` を付け直す範囲（各日の上位 40 窓 ≈ 480 窓 ≈ ¥71、全窓なら ≈ ¥550）。
- 1 秒 × 4 が短すぎないか、音楽の拍に合わせるか（現状は無音）。

出典（10 節）: Teleprompter「10 Essential Travel Vlogging Tips」、Insta360「How to Make a Travel Video」、
Clipchamp「How to make a travel highlight video」、Adventure Bike Rider「How to film a motorcycle travel
documentary」「Video editing tips」、Itchy Boots「Motorcycle Vlogging 101」、arXiv 1601.04406、
Videogenic (ACM DIS 2024, doi 10.1145/3635636.3656186)。

## 11. シーン選択に改善の余地はあるか——調査（2026-09-07、オーナー依頼）

「このシステムの肝」であるシーン選択について、ウェブ上の実務（GoPro・Insta360）と研究（自己視点動画の要約）を
調べ、当システムの現状と照らした。

### 11.1 実務が使っている信号

- **GoPro Quik の Auto HiLights** は GPMF（GPS の経路・速度・標高・G・シーン変化・カメラ温度・表情）の変化点を
  ハイライト候補にし、音楽の拍に合わせる。「センサーが変わった瞬間＝見どころ」という前提。
- **Insta360 の AI Highlights** は場面ごとの「盛り上がり」でクリップ長を可変にする（詳細は非公開）。
- **自動編集サービス**（Antix、aidvid 等）は鮮鋭さ・露出・視覚的関心で採点し、ブレ・暗所・何も起きない区間を
  無言で捨てる。

### 11.2 研究が言うこと

- **Story-Driven Summarization**（Lu & Grauman, CVPR 2013、テキサス大）: 要約は **物語（前の場面が次を「導く」）
  ・重要度・多様性** の三つを同時に最適化する。頻出する被写体より、物語の流れに影響する被写体を残す。34 人の
  盲検で 65% 以上が既存手法より好んだ。
- **Picturesque Highlights**（arXiv 1601.04406）: 動きではなく**写真の美的基準**（構図・対称・色）で順位づけ、
  GPS で場所の重要度を重みづける。
- **Videogenic**（DIS 2024）: プロの写真を事前分布に「写真らしい瞬間」を探すと、人はそれをハイライトと認める。
- **要約研究一般**: 代表性だけでは肝心の場面が落ちる。**興味深さ（interestingness）**が要る。

### 11.3 当システムの現状との差分と、改善の候補

| 観点 | 現状 | 差分・候補 |
|---|---|---|
| 物語（導き） | 章＝行程、節＝転換点（GPS・参照データ） | 研究の「影響」に相当するものは持っている。**章の中の並び**（E-2 の変化の向き）は未実装 |
| 重要度 | Gemini の視覚的関心・物語関連度 | **写真らしさ**（`photogenic_score`）を追加済み。**転換点の窓**（道路上の出来事）を判定に追加済み |
| 多様性 | 似た絵の抑制（look-alike）、道の種類の交互 | 被写体（`highlight_subject`）の多様性は冒頭のみ。**本編にも**被写体の重複抑制を入れられる |
| センサー変化点 | 鋭い曲がり（Q1）、停止、ハイウェイ出入り | GoPro 流の**速度・標高・G の変化点**を候補窓に足すのは安価（判定 1 窓 ¥0.15）。峠の頂上、
  長い直線からの急減速、標高差の大きい区間の端 |
| 画質の門 | なし（縮小コピーの輝度・動きのみ） | **ブレ・暗所・逆光**の窓を判定で落とす。Gemini に「画質の問題（blur / dark / glare / rain on
  lens / none）」を聞くのが最も安い |
| 拍 | 無音 | 音楽を入れるなら、冒頭ハイライトの 1 秒カットを拍に合わせる（E-5 と一体で） |

### 11.4 次に試す順（費用と効果）

1. **画質の門**（Gemini に `image_quality` を追加、旧記録は語で代用）——安く、はずれが減る。
2. **本編の被写体多様性**（同じ `highlight_subject` を 3 本続けない）——判定不要。
3. **センサー変化点の候補窓**（峠の頂上、急減速の直前、標高差の端）——1 日数窓の追加購入。
4. **章の中の並び**（E-2 の「変化の向き」）——判定不要。

出典（11 節）: GoPro「Updates to Quik App Bring Smarter Auto HiLights + More Precise Editing Tools」、
GoPro Community「Quik: Auto Highlight Videos」、Insta360 Online Manual「AI Highlights Assistant」、
PetaPixel「Antix Automatically Creates Highlight Reels」、Lu & Grauman「Story-Driven Summarization for
Egocentric Video」(CVPR 2013)、arXiv 1601.04406、Videogenic (DIS 2024)、Sharghi et al.「Diversity-aware
Multi-Video Summarization」(arXiv 1706.03123)。

## 9. 出典

- ITE-P: Inside the Edit「Master Pacing in Video Editing」 https://www.insidetheedit.com/blog/pacing-in-video-editing
- ITE-B: Inside the Edit「How to Structure B-Roll」 https://www.insidetheedit.com/blog/b-roll-editing-structure
- Splice: 「Mastering Travel Day B-Roll Storytelling」 https://spliceapp.com/blog/mastering-travel-day-b-roll-storytelling-4/
- NFS: No Film School「5 Editing Techniques… Better Travel Videos」 https://nofilmschool.com/editing-techniques-better-travel-videos
- vidpros: 「Video Clip Length: Ultimate Guide」 https://vidpros.com/video-clip-length/
- SLT: Spend Life Traveling「Cutting a Video: 5 Cuts Explained」 https://www.spendlifetraveling.com/how-to-cut-together-a-travel-video/
- Wiki-ASL: Wikipedia「External rhythm」（平均ショット長） https://en.wikipedia.org/wiki/External_rhythm
- Wiki-Lcut: Wikipedia「L cut」 https://en.wikipedia.org/wiki/L_cut
- rantaka-1: 快適アウトドア計画「撮り方・編集方法 完全ロードマップ」 https://rantaka.com/moto-filming/
- rantaka-2: 同「物語を作る撮影設計テンプレート」 https://rantaka.com/shooting-timing-template/
- rantaka-3: 同「タイムラプス活用法」 https://rantaka.com/touring-timelapse/
- Filmora-JP: 「ツーリング動画撮影コツと編集方法」 https://filmora.wondershare.jp/video-editing/touring-video-shooting-tips-edit-methods.html
- demogoru: でもごるブログ「バイク Vlog の撮り方完全ガイド」 https://demogoru-blog.com/bike-vlog-guide/
- movieru: むびるプラス「Vlog 編集のコツ」 https://movieru.jp/plus/vlog-hensyu-kotsu/
- meec-11: ナカドウガ「見やすいテロップの作り方 11 の条件」 https://note.com/meec/n/n292b1a7cc6b3
- douga-branding: 「動画テロップ講座」 https://www.douga-branding.com/blog/111/
- frame.io: 「Create Lower Thirds Titles That Don't Suck」 https://blog.frame.io/2017/12/04/create-lower-thirds-titles-that-dont-suck/
- vimeo-LT: 「Guide to Lower Thirds Design」 https://vimeo.com/blog/post/what-is-lower-thirds
- riverside: 「Lower Thirds Full Guide」 https://riverside.com/blog/lower-thirds
- Relive: Esri「Relive Outdoor Adventures」 https://www.esri.com/about/newsroom/arcwatch/relive-outdoor-adventures-with-a-new-app-and-esri-maps
- motovlog-map: Motovlog「Creating Route/Map Animations」 https://motovlog.com/threads/creating-route-map-animations.20538/
- animaps: 「Animated Map for YouTube Videos」 https://animaps.ai/guide/animated-map-for-youtube
- pippit: 「Travel Map Animation」 https://www.pippit.ai/resource/travel-map-animation
- CC: CanyonChasers「How to Film Better Motorcycle Videos」 https://www.canyonchasers.net/2025/11/how-to-film-better-motorcycle-videos-with-less-gear-stress/
- SJCAM: 「How to Eliminate Wind Noise」 https://www.sjcam.com/blogs/how-to-eliminate-wind-noise-the-ultimate-motorcycle-action-cam-audio-guide/
- RideNest: 「Motovlogging Camera Angles and Techniques」 https://ridenest.com/how-to-film-like-a-pro-motovlogging-camera-angles-and-techniques/
- insideeditors: 「Travel Video Editing Tips」 https://insideeditors.com/travel-video-editing-tips/
- Nadir: 「10 Simple Rules to Make Cinematic Videos」 https://nadironthego.medium.com/10-simple-rules-to-make-cinematic-videos-988f2baf9e7d
- Itchy Boots（視聴者の言葉）: https://bobistheoilguy.com/forums/threads/anyone-watching-itchy-boots-adventures-on-youtube.359073/
