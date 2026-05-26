---
name: ai-code-review
description: Run a two-model (scanner + validator) AI security code review on staged changes via Azure OpenAI, or install it as a git pre-commit hook in a target repo. Use when the user wants an AI pre-commit security review, to scan staged code for vulnerabilities, or to set up the ai-sast pre-commit gate.
allowed-tools: Bash, AskUserQuestion, Read, Write, Edit
---

Two-model AI security code review built on a Lockton fork of [rivian/ai-sast](https://github.com/rivian/ai-sast), wired to **Azure OpenAI**.

**The two models** (ai-sast's core design):
1. **Scanner** (`AZURE_OPENAI_SCAN_DEPLOYMENT`, e.g. `gpt-4o`) reads each file and reports findings (severity, location, risk, fix).
2. **Validator** (`AZURE_OPENAI_VALIDATOR_DEPLOYMENT`, e.g. `gpt-4o-mini`) re-checks each finding and answers TRUE/FALSE, dropping false positives. Only TRUE findings remain.

The commit is blocked only when a **validated** finding at/above `AI_SAST_GATE_SEVERITY` (default `critical,high`) exists.

## Key locations

- **Engine** (Azure-enabled ai-sast): `~/source/repos/Projects/ai-sast` — this is `AI_SAST_HOME`.
  - Entry point: `python -m src.main.precommit_scan <files>` (run from a repo root, with `AI_SAST_HOME` on `PYTHONPATH`).
- **Hook template**: `<this-skill>/pre-commit`
- **Config template**: `<this-skill>/ai-sast.env.example`

The skill directory is wherever this SKILL.md lives (in the org `.github` repo under `.claude/skills/ai-code-review/`).

## First, ask what the user wants

Use AskUserQuestion to pick the mode:
- **Install hook** — set up the pre-commit gate in a target repo.
- **Run review now** — scan the current staged changes once, without installing anything.

---

## Mode A — Install the pre-commit hook

### 1. Verify the engine and dependencies

```bash
AI_SAST_HOME="$HOME/source/repos/Projects/ai-sast"   # adjust if cloned elsewhere
test -f "$AI_SAST_HOME/src/main/precommit_scan.py" && echo "engine OK" || echo "MISSING: clone ai-sast first"
python -c "import openai, azure.identity; print('deps OK')" || echo "Run: pip install -r \"$AI_SAST_HOME/requirements.txt\""
```

If the engine is missing, offer to clone the Azure-enabled fork:
`git clone https://github.com/larryjoelane/ai-sast.git "$AI_SAST_HOME"`, then `pip install -r "$AI_SAST_HOME/requirements.txt"`.

### 2. Identify the target repo

Confirm the repo to protect (default: current directory). Get its root:
```bash
git -C <target> rev-parse --show-toplevel
```

### 3. Collect config with AskUserQuestion

Ask for: Azure endpoint, auth method (API key vs Entra ID), scan deployment (default `gpt-4o`), validator deployment (default `gpt-4o-mini`), and gate severity (default `critical,high`). For API-key auth, instruct the user to paste the key directly into `.ai-sast.env` rather than telling it to you.

### 4. Write `<repo-root>/.ai-sast.env`

Read `ai-sast.env.example` from this skill dir, fill in the collected values (set `AI_SAST_HOME` to the absolute engine path), and write it to the target repo root. Then ensure it is git-ignored:
```bash
grep -qxF '.ai-sast.env' <repo-root>/.gitignore 2>/dev/null || echo '.ai-sast.env' >> <repo-root>/.gitignore
```

### 5. Install the hook

Copy the template into the repo's hooks dir and make it executable:
```bash
HOOKS_DIR="$(git -C <repo-root> rev-parse --git-path hooks)"
cp "<this-skill>/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"
```
If a `pre-commit` hook already exists, show it and ask before overwriting.

### 6. Smoke-test

```bash
cd <repo-root>
PYTHONIOENCODING=utf-8 PYTHONPATH="$AI_SAST_HOME" python -m src.main.precommit_scan --no-gate $(git diff --cached --name-only --diff-filter=ACM)
```
`--no-gate` reports findings without failing, so the test never blocks. Report the outcome and remind the user that real commits will block on `critical,high` findings (bypass: `git commit --no-verify`).

---

## Mode B — Run review now (no install)

Scan the currently staged files once. Load the target repo's `.ai-sast.env` if present; otherwise require the Azure env vars to be set (`AZURE_OPENAI_ENDPOINT`, a deployment, and `AZURE_OPENAI_API_KEY` or Entra ID login).

```bash
cd <repo-root>
set -a; [ -f .ai-sast.env ] && . ./.ai-sast.env; set +a
export PYTHONIOENCODING=utf-8 AI_SAST_LLM=azure AI_SAST_VALIDATOR_LLM=azure
PYTHONPATH="$AI_SAST_HOME" python -m src.main.precommit_scan --no-gate $(git diff --cached --name-only --diff-filter=ACM)
```

To review specific files instead of the staged set, pass paths after the module name. Summarize the findings (severity, file, issue, fix, validator note) back to the user.

## Notes & gotchas

- **Windows**: git runs hooks via Git Bash, so the `#!/bin/sh` hook works. `PYTHONIOENCODING=utf-8` is required (the engine prints emoji; the cp1252 console crashes without it) — both the hook and the commands above set it.
- **Two distinct deployments** give the best false-positive reduction (scan with a strong model, validate with a fast one), but you may point both at the same deployment.
- **Disable the validator** by setting `AI_SAST_VALIDATOR_LLM=` (empty) — then all scanner findings are used as-is.
- **Cost/latency**: each staged source file is one scan call plus one validator call per finding. Keep commits focused; the hook only scans staged source files (binary/`text` extensions are skipped).
- The engine ships scanner output, not SARIF/JSON — `precommit_scan` parses findings in-process for the gate.
