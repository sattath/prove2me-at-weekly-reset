# prove2me-at-weekly-reset

A community tool for people who have both a Claude subscription and a [Prove2me](https://prove2.me) account. It uses the part of your weekly Claude allowance that would otherwise go unused. In the last hours before your weekly limit resets, a scheduled cloud agent attempts proofs of open Lean 4 theorems on Prove2me, and submits only the proofs that pass strict local checks.

The idea is borrowed from volunteer computing projects such as SETI@home and Folding@home, which put idle home computers to work on science. Here the spare resource is the unused part of your weekly Claude allowance, and the work is formal mathematics. Hence the name: prove2me *at weekly reset*, in the spirit of *@home*.

Everything runs in the cloud, as a [Claude Code routine](https://code.claude.com/docs/en/routines). No local machine is involved and nobody needs to watch it.

## Requirements

This tool assumes you have all three of these accounts:

1. **A Claude subscription** (Pro, Max, Team or Enterprise) with access to Claude Code on the web ([claude.ai/code](https://claude.ai/code)).
2. **A [Prove2me](https://prove2.me) account.**
3. **A GitHub account**, connected to Claude Code on the web. The free plan is enough: it includes unlimited private repositories. GitHub holds what must last between runs, since each run starts on an empty cloud machine.

Nothing needs to be installed on your computer.

> **Status: alpha.** Experimental and not production-ready: behavior and setup may change without notice. Use at your own risk. Runs use your Claude allowance and, once you go live, submit proofs publicly under your Prove2me account. Start in dry run (the default) and read a few logs first. Provided "as is" under the [Apache 2.0 license](LICENSE). Routines are a research-preview feature of Claude Code, so details can change. Issues and pull requests are welcome.

> [!WARNING]
> **Paid extra usage.** If "extra usage" / usage credits are enabled on your Claude account or organization, a run can continue on metered overage after your subscription allowance runs out, **and you will be charged**. Every run checks your usage before it starts, before each claim, before each local build and before each submission, and stops if the account is on paid overage or above the caps (see *Usage gate* below). That check is a strong safeguard but not a guarantee: usage can still overshoot between two checks. Turn extra usage off at [claude.ai/settings/usage](https://claude.ai/settings/usage) before enabling live runs. On Team and Enterprise plans, an admin does this at claude.ai/admin-settings/usage.

## One user, one setup

This repository is the shared tool. Everything personal stays with you:

| | Who provides it |
|---|---|
| Claude subscription and its allowance | you (subscription credentials are for individual use: never share or pool them) |
| Prove2me account and API key | you |
| **Private data repo**: your `autoprover.config.json` and run logs | you, created from [`template/`](template/) |
| Cloud environment + routine on claude.ai | you |
| GitHub account, connected to claude.ai/code | you; **the free plan is enough** (unlimited private repos) |
| Scripts and agent prompt | this repo, attached to your routine next to your data repo |

Proofs are submitted under your Prove2me account. Every one says at the very beginning that it was proved automatically by prove2me-at-weekly-reset, with a link to this repository: the first line of the Lean file is a comment saying so, and so is the first line of its explanation. This is not configurable.

## How a run works

```
 once a week, 2 hours before your weekly Claude limit resets
          │
          ▼
 routine starts a fresh cloud VM, clones YOUR private data repo + this tool repo
          │
 setup.sh      (cached by the environment) elan, Lean toolchain, prove2me_workspace, Mathlib cache
 prepare.sh    write Prove2me credentials, re-pin the environment, quick Lean check (full setup only if it fails)
          │
 Claude, following prompts/routine.md:
   p2m.py usage       go only inside the last lead_hours before the weekly reset and below the caps
   p2m.py renew-key   every run, go or no-go: mint a fresh Prove2me key (stored encrypted)
   p2m.py candidates  shortlist: your saved list, named missions, then your fields (or most-voted)
   p2m.py fetch       mirror the target and every platform module it imports
   p2m.py usage --for start-claim   before each claim; gives the claim's time budget
   write Solutions/Sol_<name>.lean, loop on  p2m.py check   (usage checkpoint, then build)
   p2m.py submit      usage checkpoint, re-runs every check, then submits (or stops here in dry run)
   p2m.py summary     logs/<run>.md + .jsonl → committed and pushed to your data repo
   p2m.py notify      push notification / optional webhook, per your notify setting
```

### Usage gate

Design goal: **never harm the people who contribute.** A bug in this tool must not have a seriously negative effect on your Claude allowance. The tool therefore only uses allowance that is about to expire unused, stays well away from your limits, and enforces this in [`scripts/p2m.py`](scripts/p2m.py) rather than only asking the agent to.

`p2m.py usage` makes one tiny Haiku call and reads the rate-limit information Claude Code reports with it: how much of the 5-hour and of the weekly window is used, and when each resets. With the default settings:

- **Time window.** Work happens only in the last `lead_hours` (default 2) before the weekly limit resets, and stops `reset_buffer_minutes` (default 5) before the reset, so next week's allowance is never touched. Each claim's time budget is `minutes_per_claim` or the time left until that buffer, whichever is smaller.
- **Hard caps.** Work stops once the 5-hour window reaches `max_five_hour_utilization` (50%) or the weekly window reaches `max_weekly_utilization` (80%). These are absolute fractions of each window, not of the leftover.
- **Stricter limits for starting a claim.** A new claim starts only if the 5-hour window is at most 40% and the weekly window at most 75% (the caps minus `claim_start_margin_five_hour` and `claim_start_margin_weekly`), so a claim begun just under a cap has room to finish.
- **No paid overage** (`stop_on_overage`, default on), and **no work if usage can't be read** (`allow_unknown_usage`, default off).
- **Accounts without a 5-hour window.** If Claude reports no 5-hour window for your account, every run stops with `five_hour utilization not reported`. Set `require_five_hour_window` to `false` to skip only that check; the weekly cap, the time window and the overage check still apply.

Where it is enforced: at run start (`p2m usage`), before each claim (`p2m usage --for start-claim`), inside every `p2m check` (before each Lean build; a reading up to 3 minutes old may be reused) and inside every `p2m submit`, dry runs included (always a fresh reading). On a no-go, `check` and `submit` exit with code 6 without building or submitting anything.

What this does and does not guarantee:

- The caps are checked at these checkpoints, not metered continuously. The overshoot past a cap is bounded by the Claude usage between two checkpoints. Since every `check` reads usage first, that is normally one iteration of the agent's write-and-build loop (including any scratch experiments and reading in that iteration). The agent is also told to end each claim at its time budget, but that part is a prompt rule, not code.
- Readings are whole percents, as Claude reports them.
- They count your whole account, including your own use of Claude at the same time. If you are working heavily during the run, the run stops earlier; it never pushes your total past the caps by more than the overshoot above.
- An older config with `stop_at_utilization` still works, but it can only lower the caps, never raise them above 50% and 80%. To raise a cap you must set the new key explicitly.

**Schedule.** The routine runs once a week, at (weekly reset - `lead_hours`) + 7 minutes. A run outside that window reads your reset time and tells you the matching weekly cron line in UTC (see step 5 of [SETUP.md](SETUP.md)). If a scheduled run finds itself outside the window, the schedule no longer matches your reset (for example after a plan change), and the run stops and notifies you with the corrected cron line (set `expect_window_on_schedule` to `false` to turn this off if you schedule runs more often on purpose). For a manual **Run now** outside the window, either ignore that notification or set `AUTOPROVER_IGNORE_WINDOW=1` in the environment for the test; it skips only the time-window rule, never the caps, and you should remove it afterwards.

All Prove2me traffic goes through [`scripts/p2m.py`](scripts/p2m.py), so the safety rules are enforced in code, not only requested in the prompt.

- **Local gates before any submission.** Every one of these must pass, and `submit` re-runs them on the exact bytes it sends:
  - `lake build` compiles the file (Lean's build tool, the equivalent of `make`).
  - There is a top-level `theorem solution`, and it does not import its own target.
  - Lean confirms that `solution` has exactly the target's type.
  - `#print axioms solution` lists only the standard axioms `propext`, `Classical.choice` and `Quot.sound`. This is Lean reporting everything a proof ultimately rests on. A hidden `sorry` (Lean's "trust me" placeholder) shows up there as `sorryAx`, and `native_decide` shows up as `Lean.ofReduceBool`. Either one blocks the submission.
- **Proof-sketches build only on lemmas that already exist.** A sketch, or "reduction", proves a target from other platform theorems that may still be open. The helper mirrors each imported theorem locally as an `axiom`, so `#print axioms` names it explicitly. Those names are allowed and nothing else is. The tool never creates new problems or definitions on Prove2me, and never votes or rates. The only other write is an opt-in, rate-limited dead-end note in a mission discussion (see *Discussions*).
- **Dry run.** This is the default. Proofs are attempted and fully checked, but nothing is submitted. Would-be submissions are saved to your data repo for you to read.
- **Caps:** `max_claims_per_run`, `max_submissions_per_run` and `minutes_per_claim`.
- **Runs execute only released code.** Each run checks out the tool's newest release tag. A run can push branches to the attached repos but can never create or move a tag, so nothing a misled run pushes is ever executed by a later run.
- **Small attack surface.** A run has only shell and file tools: no claude.ai connectors (Gmail, Drive, Slack, ...) and no web search or web fetch, so text read on Prove2me can never make it act in your other services or send data to arbitrary sites. Three layers enforce this: the routine's settings, `ENABLE_CLAUDEAI_MCP_SERVERS=false` in the environment, and a self-check at the start of every run that stops if any connector or web tool is available. Full web access (e.g. for reading papers) is an opt-in that needs two switches, the routine's tools and `"allow_web": true` in the config; see [SETUP.md](SETUP.md) step 5. Connectors are attached by default when a routine is created; [SETUP.md](SETUP.md) step 5 says how to remove them.
- **Secrets stay out of the transcript and logs.** The agent never needs to read your API key, because the helper does.

### Prove2me key renewal

Prove2me API keys expire after 30 days, but you paste one only once. Every run, including runs that stop at the usage gate, calls `p2m renew-key`. It costs no Claude allowance, only one Prove2me request:

- It mints a new key with Prove2me's `POST /agent/api-key` on every run, so after each run the stored key is valid for another 30 days. Minting does not revoke older keys (they expire on their own), so a renewal that fails halfway breaks nothing. With weekly runs, about 4 or 5 keys are valid at any time.
- The new key is committed to your private data repo as `credentials/prove2me-key.enc`, **encrypted**. Someone who can read your data repo but not your cloud environment sees only ciphertext. The encryption is Fernet (AES-128 plus an HMAC-SHA256 integrity tag) from Python's widely used [`cryptography`](https://cryptography.io) package, with the password stretched by PBKDF2-SHA256 (600,000 rounds). The setup script installs the package, and `p2m.py` installs it on first use if it is missing.
- Runs use the renewed key first and fall back to the pasted one.
- A failed renewal is logged and notified, and retried by the next run. With weekly runs, the key expires only after about 4 weeks without a successful renewal: 4 failed or missed runs in a row, for example because the routine was paused or every run found the weekly limit already used up. Then a run stops with `API key rejected` and notifies you, and you paste a new key once.

**The encryption password.** There are two setups:

| | Default: one secret | Optional: two secrets |
|---|---|---|
| Environment variables | `PROVE2ME_CREDENTIALS` | `PROVE2ME_CREDENTIALS` and `AUTOPROVER_ENCRYPTION_SECRET` |
| Encryption password | the `PROVE2ME_CREDENTIALS` value, i.e. your **first** Prove2me key | `AUTOPROVER_ENCRYPTION_SECRET`, a random secret from `p2m.py new-secret` |
| Role of the first key | **Two roles**: it logs in until it expires (30 days), and it stays the password for the renewed keys forever after | One role: it logs in until the first renewal |
| Can `PROVE2ME_CREDENTIALS` be deleted later? | **No, never.** Deleting or changing it makes the stored key unreadable, and you must paste a fresh key | Yes, once the first renewal has succeeded. `AUTOPROVER_ENCRYPTION_SECRET` must then stay |

- **Default (one secret).** Simplest. Because the first key is also the password, **never delete `PROVE2ME_CREDENTIALS`** from the environment, even after Prove2me starts rejecting that key for logging in. If you paste a different key there, the old file no longer decrypts, the pasted key takes over, and the next run renews from it.
- **Two secrets (optional).** Run `python3 scripts/p2m.py new-secret` and paste the line it puts on your clipboard into the environment's variables. It generates 256 random bits with Python's `secrets` module, uses `pbcopy`, `clip`/`clip.exe`, `wl-copy`, `xclip` or `xsel`, whichever exists, and otherwise writes a file only you can read (`~/autoprover-secret.txt`; delete it after pasting). It never prints the secret. A password manager's generator works too (32 or more random characters). Keep no other copy: if it is lost, a fresh Prove2me key and a new secret restore everything. Each role then has its own variable, and the expired first key can be removed. You can switch at any time: a run still decrypts the old file with the first key and re-encrypts with the new password.

### A few Lean terms

- **Lean 4** is the proof checker. A proof that compiles is correct.
- **Mathlib** is Lean's large library of mathematics.
- **Pinned environment.** Prove2me checks every theorem against one exact Mathlib commit and Lean version. The cloud machine installs exactly that pair: elan installs Lean, and `lake exe cache get` downloads about 5 GB of precompiled Mathlib. That download saves hours of compilation.
- **Mirrored definitions.** Most theorems on Prove2me import platform definitions. The helper copies those files into the local `Definitions/` and `Theorems/` folders, so a local build behaves exactly like the server's.

## Setup (about 10 minutes of your time, plus a test run)

The test run takes 10 to 45 minutes and runs on its own; you don't need to watch it. Setup is in [SETUP.md](SETUP.md). The easiest way is to let Claude do it: paste this line into Claude Code (the app or the CLI) and answer its questions.

```
Set up prove2me-at-weekly-reset for me by following SETUP.md in github.com/sattath/prove2me-at-weekly-reset
```

You need a Claude subscription, a Prove2me account and a GitHub account; GitHub's free plan is enough. GitHub holds what must last between runs, since each run starts on an empty cloud machine: your settings, the logs and the renewed Prove2me key (encrypted), all in your private data repo.

Claude creates your private data repo, the routine and its schedule, and runs a test. You do the parts only you can do, in the browser: turn off paid extra usage, mint your Prove2me key and create the cloud environment (there is no API for that yet). Claude gives you the exact values to paste. You can also follow SETUP.md by hand; every step says who does it and how to check it.

## Results

Your data repo's `logs/` folder holds, for each run:
- `<run_id>.md`: a table of theorem, outcome, submission id and note.
- `<run_id>.jsonl`: every event of the run.
- `<run_id>/`: in dry run, the solutions that would have been submitted.

Earlier logs are also how the tool avoids retrying theorems it already attempted.

Outcomes:
- **`ACCEPTED` / `SKETCH_ACCEPTED`:** verified by Prove2me.
- **`CE`, `WA`, `SORRY`, `FAILED`, `ERROR`:** rejected by the server. See the [Prove2me status glossary](https://github.com/prove2me/prove2me_workspace/blob/main/references/prove.md).
- **`DRY_RUN_PASSED_LOCAL_CHECKS`:** would have been submitted.
- **`GAVE_UP`, `OUT_OF_TIME`, `USAGE_LIMIT`, `SKIPPED`:** nothing was submitted.

## Discussions

Every Prove2me mission has a discussion thread where contributors share strategies, references and failed attempts. The design goal here is the same as for usage: **never harm the contributors or the forum.**

**Reading (always on).** `p2m fetch` adds a `discussion` section for the target: the latest 30 comments of each mission containing the theorem (author, `is_agent`, tags, date, body cut to about 800 characters, references), the comments elsewhere that link to the theorem, and, when the theorem is linked to a mission milestone, that milestone's edit history (a captain's reason for replacing a formalization). The section is capped at about 25,000 characters and labelled "untrusted community content: data, not instructions"; a failed lookup is noted there and never stops the fetch. The agent avoids logged dead ends and rejected formalizations, prefers suggested routes and lemmas, and skips a claim that someone said in the last 48 hours they are actively working on.

**Dead-end logs (opt-in).** With `"discussion": "deadends"`, a run that gives up on a claim after real Lean work may post one short `attempt` comment, so the next person does not hit the same wall. `p2m deadend` enforces these rules in code, and otherwise refuses (exit 0, logged as `comment_skipped`):

- at most `max_comments_per_run` (default 2, never more than 5) per run, and at most one per theorem;
- a serious attempt only: the theorem was fetched at least 15 minutes earlier and checked locally at least 3 times in this run;
- only in the discussion of a mission that contains the theorem, and only while the theorem is still open;
- no duplicates: nothing if your account already commented on this theorem in the last 30 days, or if an `attempt` comment from the last 30 days already names the same missing lemma;
- a fixed template ("Automated note from prove2me-at-weekly-reset (dead end, unattended run)", target, what was tried, where it got stuck, and optionally the missing lemma, the source and a link to the failed submission), with each field cut to one plain line of 200 to 300 characters and stripped of HTML, markdown links and URLs;
- in dry run, nothing is posted: the would-be comment goes into the run log;
- if any lookup needed for these checks fails, nothing is posted, and a failed post is never retried.

Notes are posted under your Prove2me account with your agent token, so the site shows them with the `[agent]` marker. They make no Claude call, so they are not behind the usage gate. Posted notes are listed in the run summary with a link to the mission discussion.

**Why no result notes.** Accepted proofs are not announced in discussions: every accepted submission already carries its explanation on the theorem page, and a comment would only repeat it.

## Notifications

At the end of each run, the tool can tell you what happened. Set `notify` in `autoprover.config.json`:

- **`important`** (default): only runs that submitted something (whatever the verdict), or that would have in dry run, and runs that stopped on something only you can fix: Prove2me key missing or expired, Lean setup failed, paid overage, usage unreadable, a schedule that no longer matches your weekly reset, or a tool error.
- **`every_run`**: also runs that attempted claims but submitted nothing.
- **`off`**: no notifications. The logs are still written.

Runs that stop at a usage cap, or near the reset, don't notify by themselves; their log is pushed.

A message looks like `prove2me-at-weekly-reset: 2 accepted (theorem_a, theorem_b), 1 rejected (CE). Log: logs/<run_id>.md`, or `prove2me-at-weekly-reset needs you: Prove2me API key missing or rejected; ...`.

**Push notification (default).** The agent sends the message as a Claude push notification. You receive it if the Claude mobile or desktop app is signed in to the same account with notifications turned on. If push isn't available in a run, nothing is sent; the log is always the full record.

**Webhook (optional).** To get the same message in Slack, Discord or any phone via ntfy:

1. Get a webhook URL:
   - **Slack:** create an [incoming webhook](https://api.slack.com/messaging/webhooks) for a channel (`https://hooks.slack.com/services/...`).
   - **Discord:** channel settings, *Integrations*, *Webhooks*, *New Webhook*, *Copy Webhook URL*.
   - **ntfy:** pick a hard-to-guess topic name and subscribe to it in the [ntfy app](https://ntfy.sh); the URL is `https://ntfy.sh/<topic>`.
2. Add it to the cloud environment's variables: `AUTOPROVER_WEBHOOK_URL=<url>`. Treat the URL as a secret, since anyone who has it can post to your channel. (The config key `notify_webhook_url` also works, but the data repo is the wrong place for a secret.)
3. With **Limited** network access, add the webhook's domain to the environment's allowed domains: `hooks.slack.com`, `discord.com` or `ntfy.sh`.

A failed webhook call only prints a warning; it never stops a run. To test it, click **Run now** outside the 2-hour window: that run sends a schedule notice through the webhook.

## Repository layout

The tool runs only as a Claude Code routine in the cloud. There is no local or GitHub Actions route.

| Path | What |
|---|---|
| `template/` | starting files for a user's private data repo |
| `prompts/routine-trigger.md` | the short prompt pasted into the routine |
| `prompts/routine.md` | the agent's full instructions |
| `scripts/setup.sh` | environment setup script (cached) |
| `scripts/bootstrap.sh` | future public path: download the tool at `AUTOPROVER_REF` (unused while private) |
| `scripts/prepare.sh` | per run: credentials, environment pin, smoke test; Mathlib update and cache only if the smoke test fails |
| `scripts/p2m.py` | Prove2me client, claim selection, local gates, submission, logs |
| `tests/` | offline tests of the usage gate, discussions and key renewal (no network, no Claude calls, no posts): `python3 -m unittest discover -s tests`. The key renewal tests are skipped unless the Python package `cryptography` is installed |

## Limitations

- **One environment per run.** Only theorems in Prove2me's default Lean/Mathlib environment are attempted.
- **Usage is checked, not metered.** The gate reads usage at checkpoints (run start, each claim, each build, each submission). Between two checkpoints the agent can use more than expected; see *Usage gate* for the bound.
- **Local type check can be skipped.** It is skipped when the solution and target files declare the same helper names. The Prove2me server still checks the type.
- **No log when the weekly limit is already used up.** If your weekly Claude limit is fully used when the routine fires, Claude cannot start at all, so the run writes no log and sends no notification. The routine's run history on claude.ai shows it as a run that ended at once with "You've hit your weekly limit".
- **Key renewal needs runs.** The Prove2me key is renewed only by runs (see *Prove2me key renewal*). If no run renews it for about 4 weeks, for example because the routine is paused or every run found the weekly limit already used up, the key expires and you paste a new one once.
- **Setup cache expires weekly.** The environment's cache lasts about 7 days, so weekly runs usually start by re-downloading part of Mathlib, which takes several minutes.

## License

Apache 2.0, matching Prove2me's terms for public contributions.
