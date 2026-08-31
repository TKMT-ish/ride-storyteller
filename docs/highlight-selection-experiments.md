# 良好クリップ選定の比較実験

## 問題

GPS eventと動画時刻が一致しても、映像が面白いとは限らない。初回の実素材候補は、
直線走行や停車を多く含んだ。したがってtimestamp matchは入力gateとして残し、
「映像候補の品質」を別の比較可能な選定段階として扱う。

## 共通gate

すべての方式で、12秒窓を6秒間隔で評価する。次を満たさない窓はランキング前に
除外する。

- GPS平均速度5m/s以上。
- 走行速度2.5m/s以上のpointが85%以上。
- 12秒区間の前半と後半の進行方向差が8度以上。
- FFmpeg VMAF motion平均が5以上。

LRVがあれば1fps・横320px相当で解析し、なければMP4／MOVを同じ条件へ早期縮小
して解析する。選ばれた区間だけを元MP4から720pへ抽出する。外部serviceは
使用せず、映像証拠を自動confirmedにしない。

## 10種類の方法

1. **GPSカーブ**：進行方向差が大きい区間を優先する。
2. **走行速度ダイナミクス**：停車を除き、速度標準偏差と速度幅が大きい区間を優先する。
3. **高低差ダイナミクス**：短時間の標高差と標高幅が大きい区間を優先する。
4. **映像motion**：VMAF motionの平均と変動が大きい区間を優先する。
5. **場面変化**：フレーム輝度差と変化peak率が高い区間を優先する。
6. **鮮明さ**：motion gate通過後、blurが低くentropyが高い区間を優先する。
7. **露出品質**：平均輝度が中間域に近く、階調幅が広い区間を優先する。
8. **色彩**：平均彩度が高く、情報量もある区間を優先する。
9. **視覚情報量**：正規化entropyと階調幅が高い区間を優先する。
10. **シネマティック総合**：カーブ、速度、高低差、motion、場面変化、鮮明さ、
    露出、色彩、entropyを重み付き統合する。

各方式は上位3本を選び、同一方式内では30秒未満の近接候補を重複採用しない。

## 実素材結果（2026-08-28）

- 35本のLRV／MP4 pairを解析。
- 12秒窓626件。
- v1はGPS小揺れを方位変化として累積したため91件がgateを通過し、停車候補が1件残った。
- v2は区間前半／後半の方位差とvisual motion下限へ修正し、通過41件。
- v2から10方式×3本＝30本、すべて1280×720、合計約361秒を抽出。
- 30/30でffprobe成功。external transfer 0。

## 現時点の結論

方式4、5、10は動きや場面変化のあるカーブを比較的上位に置く。一方、方式2、3、
7、8、9は条件を厳しくしても緩いカーブや直線に見える映像を残すことがある。
単一の低水準指標だけでは「旅として面白い」「景色が良い」「珍しい対象がある」を
完全には判定できない。

次の品質改善は、人手の採用／却下ラベルを保存して重みを校正すること。その後、
必要ならローカルsemantic model、または送信対象を限定して明示承認したvision model
による景観・道路・対象物の意味評価を別gateで比較する。

## v3 ローカル品質研究（2026-08-28）

ユーザー確認でv2の候補が「直線走行と停車が多く、つまらない」と判定されたため、
単一指標のランキングを主方式から外した。v3は次の一次資料と実ファイル検証を基に、
候補生成を4段階へ再設計した。

- GoPro公式の[GPMF parser](https://github.com/gopro/gpmf-parser)とGPMF定義を確認し、
  実MP4に`GYRO`、`ACCL`、`SCEN`、`YAVG`、`UNIF`等が存在することをローカルで
  検証した。GPSキーはこの品質解析では意図的にdecodeしない。
- Apple Visionの
  [`VNCalculateImageAestheticsScoresRequest`](https://developer.apple.com/documentation/vision/vncalculateimageaestheticsscoresrequest)
  とFeature PrintをMac上だけで使用する。画像pathや画像内容を外部へ送信しない。
- [TVSum](https://openaccess.thecvf.com/content_cvpr_2015/html/Song_TVSum_Summarizing_Web_2015_CVPR_paper.html)
  の文脈依存importanceと、
  [Diversity-Representativeness reward](https://arxiv.org/abs/1801.00054)
  の考え方を、MMR型の多様性・代表性選抜として限定的に取り入れた。

### 評価した10の信号

1. 平均速度ではなく、最低速度・10 percentile速度・中央速度・走行比率を使う連続走行。
2. 区間方位差、累積方位差、経路効率を組み合わせたGPS曲率。
3. クリップ中央4秒だけのGPS方位変化。
4. FFmpegのmotion、scene差、blur、entropy、露出、彩度。
5. GoPro GPMFの区間平均ジャイロ旋回量。
6. GoPro GPMFの中央1秒ジャイロ旋回量とIMU jitter。
7. GPMF `SCEN`の自然／人工scene確率。
8. Apple Visionの3時点aesthetic scoreとutility判定。
9. Apple Visionの道路文脈とFeature Print完全／近似重複判定。
10. 品質・走行動作・景観のscoreと、MMR多様性・route分散の統合。

### v3のfail-closed gate

- 12秒窓を2秒間隔で解析する。
- 平均速度5.0m/s、最低速度2.5m/s、10 percentile速度4.0m/s、中央速度4.0m/s以上。
- 走行比率95%以上、visual motion 5.0以上。
- 強い区間曲率に加え、中央GPS方位変化6度以上。
- GPMF coverage 75%以上、区間平均ジャイロ0.025rad/s以上、中央ジャイロ
  0.08rad/s以上。
- 3フレーム中2フレーム以上と中央フレームが道路文脈。utility比率は3分の1以下。
- 同一asset／offsetは1回だけ。Apple Feature Print距離0.04未満は重複として除外。
- 12秒未満の時間差は除外し、クリップ同士を重ねない。
- 条件下で必要本数を作れなければ、自動でしきい値を緩めず失敗終了する。

### 反復結果

| pass | 主な変更 | 結果と判断 |
|---|---|---|
| v3a | 連続速度、緩い曲率、GPMF、Vision、MMR | 60候補。駐車場文脈と直線に見える区間が残り不採用。 |
| v3b | 強いGPS曲率、3時点の道路文脈 | 32候補。駐車場は除外できたが、中央が直線に見える例が残った。 |
| v3c | 区間平均ジャイロ0.04rad/s | 14候補。30秒分離では10本を作れずfail closed。12秒分離なら作成できたがroute分散が狭い。 |
| v3d | 2秒stride、中央ジャイロ0.04rad/s | 1,858窓、証拠gate 37件。中央への寄せ方は改善したが緩い旋回が残った。 |
| v3e | 中央ジャイロ0.10rad/s | 非重複10本を作れずfail closed。 |
| v3f | 中央ジャイロ0.08rad/s | 証拠gate 25件、各方式10本。直線残存をさらに減らす余地あり。 |
| v3g | 中央GPS方位変化8度 | 非重複10本を作れずfail closed。 |
| v3h | 中央GPS方位変化6度、各方式8本 | 証拠gate 15件、4方式×8本を作成。連続素材v4前の比較baseline。 |

4方式は`quality-first`、`ride-dynamics`、`scenic-context`、
`balanced-diverse`。v3hの各方式は8/8が固有、hard-gate違反0、utility frame 0。
当時の比較上位だった`balanced-diverse`は8本すべて道路文脈で、Feature Print完全重複0組、
最小pair距離0.371、平均pair距離0.516だった。

### v2との同一尺度比較

| 指標 | v2全30候補 | v3h balanced 8候補 |
|---|---:|---:|
| asset／offset固有率 | 17/30（56.7%） | 8/8（100%） |
| Apple Feature Print距離0.04未満のpair | 21 | 0 |
| 中央画像の道路文脈率 | 96.7% | 100% |
| Apple utility率 | 0% | 0% |
| Apple aesthetic平均 | 0.478 | 0.417 |
| 最小Feature Print距離 | 0.000 | 0.371 |

v3hは一般的なaesthetic平均ではv2より低い。直線の青空道路が高い美的scoreを得る
一方、今回のユーザー要件は「直線と停車を避け、旋回動作を含むこと」だからである。
したがってApple aestheticを目的関数にはせず、ユーザー指定の連続走行・中央旋回を
hard gateにした。v3hはproxy指標上の比較baselineであり、「良好」とは確定しない。

## v4a 連続撮影素材での実素材E2E（2026-08-30）

### 素材と実装変更

- 今回用意された全14 MP4、約26.7 GiBを入力とした。LRVは存在しない。
- GoPro chapterを10論理録画へまとめ、同一開始時刻だった後続chapter 4本を
  先行duration累積で補正した。
- MP4原本を1fps、幅320pxへ早期縮小し、LRVと同じFFmpeg metric chainへ渡した。
- 位置・速度・方位は外部GPXを正本とし、GoPro GPMFのGYRO／ACCLを品質証拠へ
  使用した。GoPro GPS時刻値は無効だったため使用していない。
- Apple VisionはMac内だけで使用した。制限process sandboxではpixel bufferを
  作れなかったが、同一フレームをmacOSネイティブ権限で解析すると成功した。

### E2E結果

| 指標 | 結果 |
|---|---:|
| 解析source | 14 |
| 12秒窓 | 2,385 |
| strict interest gate | 202 |
| GPMF／Vision complete evidence | 202 |
| final quality gate | 21 |
| 方式 | 4 |
| 抽出clip | 32（各方式8） |
| 内容hash固有clip | 15 |
| external transfer | 0 |
| visual evidence auto-confirm | 0 |

保存済み606フレームに対し、Apple Visionは183,315組のFeature Print距離を
端末内で約4.48秒で計算した。全体時間の主なボトルネックは、26.7 GiBのHEVC
原本を再decodeするFFmpeg metric処理だった。

### 方式比較

| 方式 | aesthetic平均 | 平均pair距離 | 最小pair距離 | route bucket | hard gate違反 |
|---|---:|---:|---:|---:|---:|
| quality-first | 0.545 | 0.480 | 0.340 | 1 | 0 |
| ride-dynamics | 0.480 | 0.550 | 0.434 | 2 | 0 |
| scenic-context | 0.546 | 0.479 | 0.340 | 1 | 0 |
| balanced-diverse | 0.520 | 0.554 | 0.415 | 2 | 0 |

`balanced-diverse`は数値上の最有力だった。しかし、各clipの2秒、6秒、10秒を
並べたstoryboardでは、緩い直線寄りの道路が複数残った。したがってv4aの判定は
次のとおり。

- 技術E2E: **PASS**
- 自動候補品質: **PARTIAL**
- 推奨8本の人手承認: **NOT YET**
- 映像証拠`confirmed`: **0**

### 根本原因と次の仮説

現行の12秒区間方位変化8〜12度条件は、緩い高速道路カーブも「非直線」として
通す。一方、単純に閾値を上げると、合流、交差点、追越車両など、GPS曲率だけでは
表現できない意味のある場面まで失う。

次のv4bではinterest gateを少なくとも二系統に分ける。

1. **strong-turn gate**：区間方位、中央方位、累積方位、経路効率、gyroで明確な
   旋回を判定する。
2. **visual-event gate**：合流、交差点、周辺車両変化、珍しい対象など、旋回以外の
   時間方向イベントを判定する。

どちらにも該当しない緩い直線寄り窓を除外する。加えて、v4aの全動画再走査を
繰り返さないprivate metric cacheを先に実装し、人手採用／却下理由のcontract、review UIを
続けて実装する。

重複除外した15本を3時点ずつ目視し、明確な旋回、合流、交差点、周辺車両変化を
持つ8本を手動レビュー用の正解例候補としてローカルにまとめた。この8本もユーザー
未確認であり、自動選定成功や映像証拠確認の証明にはしない。

### v4b準備｜private metric cache（2026-08-31）

- `app.video.highlight_research`はprivate出力直下の`metric-cache/`へ、FFmpegの
  1fps縮小メトリクスとMP4／MOVのGPMF集計を別entryとして保存する。
- cache keyはファイルsize、更新時刻、先頭／末尾各32KiBのハッシュだけから作る。
  元のpath、ファイル名、撮影時刻、座標、frameはcache JSONに保存しない。
- 同一sourceの再実行はcacheを再利用し、source内容または更新状態が変わった場合だけ
  そのsourceを再解析する。schema不一致または破損cacheはfail-openでなく、捨てて
  ローカル再解析する。
- Apple Visionのframe抽出／意味評価、clip抽出、人手確認をcacheで省略しない。
  visual evidenceの状態も変えない。
- 実14 MP4に対するcache hit時の所要時間は未計測である。v4bの新gateを用いる
  実素材再実行も未実施である。

### v4b準備｜interest laneの分離（2026-08-31）

- strict interest gateを、連続走行を共通条件とする2系統へ分離した。
  - **strong-turn**：区間方位差18度以上、中央方位差8度以上、累積方位差30度以上、
    経路効率0.985以下をすべて要求する。以前の緩い道路曲率を強旋回として通さないための
    fail-closedな候補条件である。
  - **temporal visual-event**：scene変化平均12.0以上、scene change peak率0.20以上、
    motion標準偏差1.5以上を要求する。これは時間方向の画像変化のproxyであり、交差点、
    合流、車両、景観などを意味的に認識・断定するものではない。
- 完全evidence gateはどちらかのlaneを満たした候補だけを通す。選定manifestには各候補の
  laneを記録する。この追加fieldとgate意味の変更を区別するため、manifest schemaは
  `local-highlight-research-v2`へ上げた。いずれも映像証拠を自動confirmedにしない。
- 上記しきい値はsynthetic contract testでのみ検証済みである。実14 MP4での候補数、品質、
  cache hit時の所要時間をまだ測定しておらず、v4b成功とは扱わない。

### v4b準備｜人手ハイライトreview contract（2026-08-31）

- researchの候補集合ごとに`highlight-review.json`をprivate出力へ作る。各decisionは
  opaqueなcandidate ID、方式、rank、`awaiting`／`approved`／`rejected`、固定理由codeだけを
  保存する。source path、ファイル名、撮影時刻、座標、frame、自由記述は保存しない。
- `approved`には`clear_turn`、`temporal_event`、`scenic_context`、`story_useful`、
  `rejected`には`too_straight`、`stopped_or_slow`、`low_visual_change`、
  `poor_road_context`、`duplicate`、`other`を要求する。未判断の`awaiting`に理由は付けない。
- 再実行時は既存reviewを初期化しない。selectionのopaque ID、方式、rankが変わった場合は、
  古いdecisionを黙って流用せず停止する。loopback-only review UIは実装済みで、reasonを使う
  再選定とStory Planへの接続は未実装である。

### v4b実行性修正｜bounded Vision diversity（2026-08-31）

- 実走行素材でstrict候補が多い場合、全フレーム間のApple Feature Print距離を総当たりで
  計算すると、候補数の二乗に比例して距離行列が増え、現実的な実行時間・メモリ量を超える。
- 品質・道路文脈・utility判定は全strict候補の3フレームに対し、距離なしのbounded batchで
  実行する。これにより、品質gateの対象を先に狭めない。
- 重複除外とMMRのFeature Print距離は、quality／dynamics／scenic／balancedの各score上位96件の
  和集合（最大384候補）のcenter frameだけに計算する。選定・評価の母集団もこのpoolに固定する。
- 既定strideは2秒から6秒へ変更した。12秒clipと12秒separationに対して冗長な近接窓を減らすためで、
  候補の意味的判定を緩める変更ではない。
- macOS Visionはrestricted process sandboxでは正常フレームでもpixel bufferを確保できない場合が
  ある。実行はnative macOS権限で行い、外部送信はしない。

### v4b実素材E2E｜bounded Vision diversityの確認（2026-08-31）

| 指標 | 結果 |
|---|---:|
| 解析source | 14 |
| 6秒survey窓 | 797 |
| strict interest gate | 602 |
| GPMF／Vision complete evidence | 602 |
| final quality gate | 59 |
| 選定方式 | 4 |
| 抽出clip | 32（各方式8） |
| review decision | awaiting 32、approved 0、rejected 0 |
| external transfer | 0 |
| visual evidence auto-confirm | 0 |

- Apple Visionの品質判定はnative macOSで完走した。restricted sandboxでは同一JPEGに対して
  `CVPixelBufferPool`作成失敗となることを、native実行で環境差として切り分けた。
- 32候補で記録されたinterest laneはtemporal `visual_event`が31、`strong_turn`が2である。
  これは映像内容の意味的断定ではなく、候補化に使った局所変化／旋回の理由である。
- `highlight-review.json`は全32 decisionを`awaiting`で作成した。人の承認・却下がない限り、
  evidence confirmedやrender許可には進まない。

## 私用出力

- `private-media/work/highlight-methods-v1/`：初回比較。
- `private-media/work/highlight-methods-v2/`：方位差・motion gate修正版。
- `private-media/work/highlight-research-v3h/`：連続素材v4前の比較baseline。
- `private-media/work/highlight-research-v4a/`：14 MP4の4方式×8本と評価記録。
- v4aの`unique-review/`：内容hash重複を除いた15本と3枚のstoryboard。
- v4aの`manual-curated-review-v1/`：次期ロジック評価用の手動候補8本。未承認。
- 各方式folderの`clip-01.mp4`〜`clip-03.mp4`：比較用clip。
- `highlight-comparison-manifest.json`：座標、絶対path、撮影日時を含まない選定記録。
- `highlight-contact-sheet.jpg`：10行×3列。行が方式1〜10、列がrank 1〜3。
- v3hの`highlight-research-contact-sheet.jpg`：4方式の中央frame比較。
