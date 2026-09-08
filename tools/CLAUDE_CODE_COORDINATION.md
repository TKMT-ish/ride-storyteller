# Claude Code 協調ランナー

`tools/run_claude_task.sh` は、Ride StorytellerでClaude Codeへ限定タスクを渡すためのローカル運用ツールです。

- 可視の対話Terminalからだけ起動します。
- `.claude-busy/` を原子的に取得するため、先行タスクがある場合は開始しません。
- タスクごとに新しい明示session IDを発行します。前タスクの文脈が必須の場合だけ、確認済みのIDを `--resume` で明示します。
- lockにはPID、開始時刻、mode、session ID、タスク名だけを記録します。秘密情報や実素材の情報は書きません。
- 正常終了、割込み、終了シグナルでlockを解除します。強制終了でlockが残った場合は、所有者を確認してから人手で扱います。自動削除はしません。
- **課金回避:** ソラはClaudeを自動起動しません。起動前に、既に開いている可視TerminalのClaude Codeで `/usage` を実行し、契約内の利用枠が残っていることを人が確認します。その確認後にだけ `--included-plan-capacity-confirmed` を付けます。この指定は確認の記録であり、課金クレジットの利用を許可するものではありません。
- `ANTHROPIC_API_KEY` が設定されたTerminalでは、このランナーは起動を拒否します。APIキーが優先されると従量課金になるためです。
- 無料枠・契約内枠を使い切った場合はClaudeを起動せず、ソラによる実装・検証または安全なローカル作業へ切り替えます。アカウント設定でUsage creditsを無効にすると、さらに強く防止できます。

例（Terminalから実行）：

```zsh
tools/run_claude_task.sh \
  --prompt-file /private/tmp/ride-storyteller-task.txt \
  --included-plan-capacity-confirmed \
  --label private-conflict-review
```

このランナーはClaude Codeの実装を安全に直列化するだけであり、実素材の外部送信、Gemini/Cloud実行、render、push、公開を許可しません。それらは既存の個別承認境界に従います。
