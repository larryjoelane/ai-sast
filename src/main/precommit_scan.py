#!/usr/bin/env python3
"""
Pre-commit security scan entry point (two-model: scanner + validator).

Designed for use as a git pre-commit hook. Unlike full_scan/pr_scan, this:
  * scans only the files passed on the command line (or, if none, the staged
    files reported by `git diff --cached`),
  * scans each file individually via SecurityScanner.scan_file (no reliance on
    the Unix `find` used by scan_directory, so it works on Windows),
  * runs the second model (validator) to drop false positives, and
  * exits non-zero when a *validated* finding at/above the gate severity exists,
    so the commit is blocked.

Configuration (environment variables):
  AI_SAST_LLM=azure                 initial scan model (model 1)
  AI_SAST_VALIDATOR_LLM=azure       validator model (model 2); empty disables validation
  AI_SAST_GATE_SEVERITY=critical,high   severities that block the commit (default)
  Azure: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY (or Entra ID),
         AZURE_OPENAI_SCAN_DEPLOYMENT, AZURE_OPENAI_VALIDATOR_DEPLOYMENT

Exit codes:
  0  no blocking findings (commit allowed)
  1  one or more validated blocking findings (commit blocked)
  2  configuration / runtime error
"""

import argparse
import os
import subprocess
import sys

# Add the ai-sast project root to the path so `src.*` imports resolve when run
# directly (matches the `python -m src.main.*` convention used in CI).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.scanner import SecurityScanner  # noqa: E402
from src.core.report import HTMLReportGenerator  # noqa: E402
from src.core import validator as validator_mod  # noqa: E402


SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]


def _staged_files():
    """Return staged, added/changed files (ACM) from git, as a list of paths."""
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Could not list staged files: {e}", file=sys.stderr)
        return []
    return [p for p in out.stdout.splitlines() if p.strip()]


def _scannable(scanner, path):
    """True if the file exists and maps to a known source language."""
    return os.path.isfile(path) and scanner._detect_language(path) != "text"


def _gate_severities():
    raw = os.environ.get("AI_SAST_GATE_SEVERITY", "critical,high")
    wanted = {s.strip().lower() for s in raw.split(",") if s.strip()}
    return [s for s in SEVERITY_ORDER if s.lower() in wanted]


def main():
    parser = argparse.ArgumentParser(description="Two-model pre-commit security scan")
    parser.add_argument("files", nargs="*", help="Files to scan (default: staged files)")
    parser.add_argument(
        "--no-gate", action="store_true",
        help="Report findings but always exit 0 (do not block the commit).",
    )
    args = parser.parse_args()

    candidates = args.files or _staged_files()
    if not candidates:
        print("✅ ai-sast: no files to scan.")
        return 0

    try:
        scanner = SecurityScanner()
    except Exception as e:
        print(f"❌ ai-sast: failed to initialize scanner: {e}", file=sys.stderr)
        return 2

    targets = [p for p in candidates if _scannable(scanner, p)]
    if not targets:
        print("✅ ai-sast: no scannable source files staged.")
        return 0

    print(f"🔍 ai-sast: scanning {len(targets)} file(s) with the two-model pipeline...")
    results = [scanner.scan_file(p) for p in targets]

    # Group raw scanner output by severity (model 1 findings).
    grouper = HTMLReportGenerator()
    by_severity = grouper._process_results_by_severity(results)
    total_raw = sum(len(v) for v in by_severity.values())
    if total_raw == 0:
        print("✅ ai-sast: no vulnerabilities reported by the scanner.")
        return 0

    # Model 2: validate findings (drop false positives). None => validation off.
    validated_ids = None
    reasoning_by_id = {}
    repo_url = os.environ.get("GITHUB_REPOSITORY", "") or os.environ.get("CI_PROJECT_URL", "")
    try:
        validation = validator_mod.validate_findings(by_severity, repo_url=repo_url or None)
    except Exception as e:
        print(f"⚠️ ai-sast: validator error ({e}); using unvalidated findings.")
        validation = None
    if validation is not None:
        validated_ids, reasoning_by_id, _all_results, _label = validation

    def is_kept(vuln):
        """A finding is kept if validation is off, or it was a true positive."""
        if validated_ids is None:
            return True
        vid = validator_mod._vuln_id(
            vuln.get("file_path", ""), vuln.get("issue", ""), vuln.get("location", "")
        )
        return vid in validated_ids

    gate = _gate_severities()
    blocking = []
    print("\n--- ai-sast findings ---")
    for severity in SEVERITY_ORDER:
        for vuln in by_severity.get(severity, []):
            if not is_kept(vuln):
                continue
            vid = validator_mod._vuln_id(
                vuln.get("file_path", ""), vuln.get("issue", ""), vuln.get("location", "")
            )
            proof = reasoning_by_id.get(vid, "")
            marker = "⛔" if severity in gate else "•"
            print(f"{marker} [{severity}] {vuln.get('file_path')}: {vuln.get('issue')}")
            if vuln.get("location"):
                print(f"     Location: {vuln.get('location')}")
            if vuln.get("fix"):
                print(f"     Fix: {vuln.get('fix')}")
            if proof:
                print(f"     Validator: {proof}")
            if severity in gate:
                blocking.append(vuln)
    print("------------------------\n")

    if not blocking:
        print("✅ ai-sast: no blocking findings. Commit allowed.")
        return 0

    if args.no_gate:
        print(f"⚠️ ai-sast: {len(blocking)} blocking finding(s) found, but --no-gate set. Commit allowed.")
        return 0

    print(
        f"⛔ ai-sast: {len(blocking)} validated finding(s) at/above gate severity "
        f"({', '.join(gate)}). Commit blocked.\n"
        "   Fix the issue(s), or bypass with: git commit --no-verify"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
