# Devpost登録回答ワークシート（日本語）

> 2026-08-17にDevpostのライブ登録フォームから取得した項目を整理した
> ローカル作業用メモです。2026-08-24に登録を完了し、ライブ再取得で確認しました。
> 登録時の個人回答と登録IDは、この公開候補文書には保存していません。

## 現在の登録状態

- 登録済み: はい（2026-08-24ライブ確認）
- 登録フォームの再送信: 不可（登録済みのため）
- 登録送信: 完了
- プロジェクト提出: 未実施

## 必須回答

以下は登録前に使用した質問一覧です。回答内容そのものは記録しません。

1. **チーム方針** — 1つ選択
   - `Working solo`
   - `Looking for teammates`
   - `Already have a team`
2. **Company Name** — 自由入力。勤務先を回答しない場合はフォーム指示どおり
   `NA`
3. **Job Title** — 1つ選択
   - `AI Engineer`
   - `CEO`
   - `CTO`
   - `Data Scientist`
   - `Developer`
   - `Founder`
   - `Senior Software Engineer`
   - `Software Developer`
   - `Software Engineer`
   - `Student`
   - `Other`
4. **AIを使ったプロジェクト開発経験** — `None` / `Low` / `Medium` / `High`
5. **Google Cloud Agent Builderの経験** — `None` / `Low` / `Medium` / `High`
6. **主な参加目的** — 1つ以上選択
   - `Learning`
   - `Networking`
   - `Career Growth`
   - `Competition`
   - `Solving a problem`
7. **任意の参加経路アンケート** — 回答しなくてもよい。Codexは空欄を勝手に
   補完しない。

`Looking for teammates`を選んだ場合だけ、他の参加者に表示する255文字以内の
短い自己紹介が任意で必要です。

## 必須同意

登録フォームは以下の両方への明示同意を要求します。

- 参加資格: 居住国・地域で成人年齢を超えていること、除外国・地域や制裁対象、
  雇用・利益相反など公式ルールの条件を満たすこと
- [Agentic Cinema公式ルール](https://agentic-cinema.devpost.com/rules)および
  [Devpost利用規約](https://info.devpost.com/terms)

ローカル状態を同意済みに変更するには、公式ルールを読んだユーザー本人が
チャットで正確に `yes` と回答する必要があります。`承認します`、`続けて`、
`確認しました`などの曖昧な表現を、規約同意の代用にしてはいけません。

## 一括回答テンプレート

```text
rules agreement: yes
team preference: Working solo / Looking for teammates / Already have a team
company name: （回答。該当なしはNA）
job title: （英語選択肢から1つ）
AI experience: None / Low / Medium / High
Agent Builder experience: None / Low / Medium / High
primary goals: （英語選択肢から1つ以上）
survey: skip または回答
```

登録後の提出フォームには、これとは別に居住国、政府職員該当、個人／チーム／
組織、チーム人数、IBM track、IBM初回利用、公開リポジトリ、公開アプリ、
Google Cloud製品、その他製品などの回答が必要です。これらは
`devpost-submission.md`の `TODO Official Form Fields` で管理します。
