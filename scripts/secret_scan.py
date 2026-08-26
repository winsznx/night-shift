"""Fail the build if anything credential-shaped is tracked by git.

Deliberately noisy about false positives rather than quiet about real ones: a scan that
misses a committed key is worse than one that flags a fixture string.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Google API key", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("private key block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("service account json", re.compile(r'"type"\s*:\s*"service_account"')),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("bearer token literal", re.compile(r"Bearer\s+ya29\.[A-Za-z0-9._\-]{20,}")),
]

# Files whose whole purpose is to describe the shape of a secret without being one.
ALLOWED = {".env.example", "scripts/secret_scan.py", "SECURITY.md", "SETUP.md"}
SKIP_SUFFIXES = {".pub.pem", ".lock", ".png", ".jpg", ".svg", ".ico", ".woff2"}


SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".next",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
}


def tracked_files() -> list[str]:
    """Files to scan.

    Prefers `git ls-files`, which scans exactly what would be published. Falls back to
    walking the tree when there is no git repo — the clean-room reproduction extracts a
    `git archive` tarball, which has no `.git`, and a scanner that crashes there is a
    scanner that silently stops protecting the one place it matters most.
    """
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        return [line for line in out.stdout.splitlines() if line]
    except (subprocess.CalledProcessError, FileNotFoundError):
        root = Path(".")
        return [
            str(p)
            for p in root.rglob("*")
            if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)
        ]


def main() -> int:
    findings: list[str] = []
    for name in tracked_files():
        if name in ALLOWED or any(name.endswith(s) for s in SKIP_SUFFIXES):
            continue
        path = Path(name)
        if not path.exists() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                findings.append(f"{name}:{line}  {label}")

    # A tracked .env is a finding on its own, whatever it contains.
    for name in tracked_files():
        if name == ".env" or name.endswith("/.env"):
            findings.append(f"{name}  a .env file is tracked by git")
        if name.endswith("-key.json") or name.endswith("service-account.json"):
            findings.append(f"{name}  looks like a service account key")

    if findings:
        print("Secret scan FAILED:")
        for f in sorted(set(findings)):
            print(f"  {f}")
        return 1

    print(f"Secret scan clean across {len(tracked_files())} tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
