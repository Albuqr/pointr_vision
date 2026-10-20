---
name: mobile-control
description: Set up automated tests and phone-controllable development. Testkit CI on every push, agent runs triggered from the GitHub mobile app, scheduled runs and notifications. Use when configuring CI/CD, schedules, or remote/mobile workflows.
---

# Mobile control & automatic tests

## Building blocks (pick the fewest that work)
1. **CI on every push.** Use `testkit/ci/github/testkit.yml` (or the GitLab one). Paste the `.env.testkit` content into the `TESTKIT_ENV` secret. Results show up in the GitHub mobile app.
2. **Run an agent from your phone.** Copy [agent-dispatch.yml](agent-dispatch.yml) to `.github/workflows/`. Then in GitHub mobile: Actions → "Agent run" → pick skill, provider and task → Run. The agent opens a PR; it never pushes to `main`.
3. **Scheduled runs.** `suite schedule` prints the OS command (Windows Task Scheduler / cron) for a nightly `run-all.sh` plus a review run. The human installs it. Alternatively, use the vendor schedulers (Claude scheduled tasks, Codex cloud, GitHub `schedule:` cron).
4. **Vendor remote options** (check current availability in the vendors' docs): Claude Code on the web and mobile, Remote Control; Codex cloud tasks; the Gemini CLI GitHub Action.
5. **Notifications.** GitHub mobile push on workflow failure. The ntfy.sh step in [agent-dispatch.yml](agent-dispatch.yml) posts "agent waiting for human" with the run link when a run returns `needs-human`.
6. **Review and approve from the phone.** The agent opens a PR. In GitHub mobile: PR → Files changed → read the diff → Review changes → Approve or Request changes → merge. This is the human sign-off for gate 6; the AI review never replaces it.

## Security
- API keys and test credentials go in Actions secrets only.
- The ntfy topic is a secret (`NTFY_TOPIC`); keep sensitive content out of the message.
- Restrict dispatch to collaborators. Agents work on branches and PRs.
