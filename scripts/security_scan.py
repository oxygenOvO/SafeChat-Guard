from __future__ import annotations

import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 10 * 1024 * 1024
TEXT_SUFFIXES = {
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
EXCLUDED_PARTS = {".git", ".pytest_cache", ".test_tmp", "__pycache__"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "hardcoded_api_key": re.compile(
        r"(?i)\bapi[_-]?key\b\s*[:=]\s*['\"](?!\$|<|your-|replace-)[^'\"]{12,}['\"]"
    ),
}


def main() -> int:
    findings: list[str] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            findings.append(f"large_file:{relative}:{size}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{name}:{relative}:{line_number}")

    forbidden = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file()
        and any(
            part in {"__pycache__", ".pytest_cache", ".test_tmp"}
            for part in path.parts
        )
    ]
    findings.extend(f"temporary_file:{path}" for path in forbidden)

    if findings:
        print("delivery scan failed; values are intentionally not printed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("delivery scan passed: no credential pattern, oversized file, or cache artifact found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
