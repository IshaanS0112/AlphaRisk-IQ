# Pushing AlphaRisk IQ to GitHub

Target: **https://github.com/IshaanS0112/AlphaRisk-IQ**

**Before you start**, two things are already confirmed:

- The repo exists on GitHub and is **completely empty** — zero branches, no
  initial commit. So the first push cannot be rejected.
- Your local folder has no `.git` yet, so nothing here can overwrite history that
  doesn't exist.

---

## Step 0 — One-time git setup

Skip if `git config --global user.name` already prints your name.

```bash
git config --global user.name "Ishaan Singh"
git config --global user.email "ishu2004.ind@gmail.com"
git config --global init.defaultBranch main
```

The email must be one GitHub knows about, or your commits won't be linked to your
profile and the contribution graph stays empty. Check at
[github.com/settings/emails](https://github.com/settings/emails).

> Want to keep your real email private? Use the noreply address GitHub gives you
> on that page (`12345678+IshaanS0112@users.noreply.github.com`) instead.

---

## Path A — the script (one command)

```bash
cd ~/BASE/02-projects/AlphaRiskIQ
./PUSH_TO_GITHUB.sh
```

It runs the test suite and the frontend build **before** touching git, refuses to
commit if anything ignored somehow got staged, then commits and pushes. No GitHub
CLI needed — the repo already exists. Expected output:

```
==> Backend test suite
156 passed in 9.07s
==> Frontend typecheck and build
✓ built in 921ms
==> Committing
[main (root-commit) a1b2c3d] AlphaRisk IQ: Sharpe/Sortino under both downside...
 102 files changed, ...
==> Pushing to https://github.com/IshaanS0112/AlphaRisk-IQ.git
 * [new branch]      main -> main

Done -> https://github.com/IshaanS0112/AlphaRisk-IQ
```

Skip to **Step 5**.

---

## Path B — Manual, four commands

### Step 1 — Verify before committing

```bash
cd ~/BASE/02-projects/AlphaRiskIQ/backend
source .venv/bin/activate
python -m pytest -q
```

Expect `156 passed`. Then:

```bash
cd ../frontend
npm run typecheck
npm run build
```

Don't push red tests. A recruiter who clones your repo and gets a failure has
learned something about you in ten seconds.

### Step 3 — Commit

```bash
cd ~/BASE/02-projects/AlphaRiskIQ
git init -b main
git add -A
git status --short | head -20
```

Check the list. **102 files, about 1.1 MB.** You should see `backend/app/...`,
`frontend/src/...`, `data/...`, `docs/...`.

You should **not** see any of these — if you do, stop and tell me:

```
backend/.env              ← your API key
backend/alphariskiq.db    ← local database
__pycache__/              ← compiled Python
node_modules/             ← 200 MB of dependencies
.DS_Store                 ← macOS junk
```

All five are covered by `.gitignore`, which I dry-ran against this exact repo.

Now commit:

```bash
git commit -m "AlphaRisk IQ: Sharpe/Sortino under both downside conventions, historical and parametric VaR with expected shortfall, Kupiec-tested VaR backtesting, beta-adjusted stress scenarios derived from cited index levels, LLM narration over frozen structured context"
```

### Step 4 — Push

```bash
git remote add origin https://github.com/IshaanS0112/AlphaRisk-IQ.git
git push -u origin main
```

macOS will pop up a browser or a credential prompt the first time. If it asks for
a **password**, that is not your GitHub password — GitHub removed password auth in
2021. Use a Personal Access Token:

1. [github.com/settings/tokens](https://github.com/settings/tokens) → **Generate
   new token (classic)**
2. Note: `mac-git`, Expiration: 90 days, Scope: tick **`repo`** only
3. Generate, copy it, paste it as the password

Expected:

```
Enumerating objects: 118, done.
Writing objects: 100% (118/118), 285.43 KiB | 5.12 MiB/s, done.
To https://github.com/IshaanS0112/AlphaRisk-IQ.git
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

---

## Step 5 — Check it actually landed

Open **https://github.com/IshaanS0112/AlphaRisk-IQ**.

Four things to check, in order:

**1. The README renders.** GitHub shows it below the file list. The VaR crossover
table should display as a proper table.

**2. CI is running.** Click the **Actions** tab. Four jobs kick off automatically:
`Backend tests`, `Synthetic fixture is reproducible`, `Scenario magnitudes still
match`, `Frontend typecheck and build`. Wait ~2 minutes for four green ticks.

> **This is the single highest-value thing on the page.** A green CI badge on a
> public repo means a stranger's machine ran your test suite and it passed. It is
> the difference between claiming the code works and demonstrating it.

If a job fails, click into it — the log names the failing test. Fix locally,
`git add -A && git commit -m "fix: ..." && git push`, and CI re-runs.

**3. No secrets.** Repo → **Settings** → **Security** → confirm `backend/.env` is
not in the file list. Search the repo for `sk-ant` — should be zero results.

**4. Size is sane.** Settings → General shows repository size. Should be around
**1.1 MB**. If it says hundreds of MB, `node_modules` got in and you need to fix
it before anyone clones it.

---

## Step 6 — Make the repo page do some work for you

Two minutes, and it changes how the repo reads to someone skimming.

**Add topics.** Repo home → the gear icon next to **About** → Topics:

```
risk-management  quantitative-finance  value-at-risk  portfolio-analytics
fastapi  react  typescript  python  postgresql  docker
```

Topics are how GitHub search finds you, and they signal the domain instantly.

**Set the description and website.** Same dialog — paste the description from Step
1. Leave Website blank unless you deploy it.

**Add the CI badge to the README.** Put this directly under the `# AlphaRisk IQ`
heading:

```markdown
[![CI](https://github.com/IshaanS0112/AlphaRisk-IQ/actions/workflows/ci.yml/badge.svg)](https://github.com/IshaanS0112/AlphaRisk-IQ/actions/workflows/ci.yml)
```

Then:

```bash
git add README.md && git commit -m "docs: add CI badge" && git push
```

**Pin it to your profile.** [github.com/IshaanS0112](https://github.com/IshaanS0112)
→ **Customize your pins** → tick `AlphaRisk-IQ`. You get six pins; this is a
finance-track project so it belongs next to your strongest tech ones, not buried.

---

## Everyday git, after the first push

```bash
git add -A
git commit -m "feat: add Christoffersen independence test"
git push
```

Commit message conventions that read well on a public repo:

| Prefix | For |
|---|---|
| `feat:` | new capability |
| `fix:` | a bug |
| `docs:` | README, architecture, comments |
| `test:` | tests only |
| `refactor:` | restructuring, no behaviour change |

One habit worth having: **run `python -m pytest -q` before every push.** Costs
nine seconds, and a repo whose history has no broken commits is worth more than
one with a longer history.

---

## If something goes wrong

| Error | What happened | Fix |
|---|---|---|
| `remote origin already exists` | You ran `git remote add` twice | `git remote set-url origin https://github.com/IshaanS0112/AlphaRisk-IQ.git` |
| `Updates were rejected because the remote contains work` | You ticked "Add a README" when creating the repo | `git pull --rebase origin main` then push again |
| `Support for password authentication was removed` | Using your password | Use a Personal Access Token (Step 4) |
| `src refspec main does not match any` | You never committed | Run `git commit` first |
| `Permission denied (publickey)` | SSH remote without a key | Switch to HTTPS: `git remote set-url origin https://github.com/...` |
| `file is 123.00 MB; exceeds GitHub's limit` | Something large got staged | Do **not** just delete and re-commit — the blob stays in history. Ask me; this is what happened to HPC-Vision. |
| Committed `.env` by accident | The key is now in history | Treat the key as compromised: revoke it at console.anthropic.com **first**, then clean history. |

---

## After it's up

Worth doing in the same sitting, while the project is fresh:

1. **Load real market data** (`docs/RUNBOOK.md` Step 8) and fix the risk-free
   rates in `data/universes/universes.json`. Right now every number in the repo is
   from synthetic data and labelled as such — honest, but weaker than the real
   thing.
2. **Push TradeArenaX**, which has been sitting ready since the July audit.
3. **Fix HPC-Vision's history**, which still cannot be pushed at all because of
   four 225 MB files in its commits. It's the only repo on your profile that's
   actually broken.
