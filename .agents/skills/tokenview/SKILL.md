---
name: tokenview
description: Report AI subscription usage (Claude Code, Codex, Gemini CLI) read from the CLIs' own local session logs, with 5-hour/weekly windows where available, plus suite runner runs per stage. Recommends re-routing when a provider nears its limit. Use when asked about usage, limits, quota or costs across agents.
---

# Tokenview

## Procedure
1. Run `suite usage`, or `suite usage --json` if you need machine-readable output.
2. Read each row:
   - **Claude Code**: tokens in the last 5 h and 7 d, from `~/.claude/projects/**/*.jsonl`. A plan-limit % appears only if the status-line snapshot captured `rate_limits` [UNVERIFIED field].
   - **Codex**: tokens plus the official `used_percent` for the 5 h and weekly windows, taken from the `rate_limits` inside `~/.codex/sessions/**/*.jsonl`.
   - **Gemini CLI**: tokens from `~/.gemini/tmp/*/chats/*.json` (best effort; the format is undocumented).
3. Any window above `switchAt` (80%) → `suite run` already skips that provider and rotates across the others; `suite route` shows the queue.
4. For a visual view: `suite dashboard` (browser), or the tray icon (`tray/`).

All of this is read locally from files the CLIs already write. No credentials are read and nothing leaves the machine.
