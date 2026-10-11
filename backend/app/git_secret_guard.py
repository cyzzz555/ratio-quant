"""Offline Git credential checks. Read Git blobs, never print matched values."""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

SENSITIVE_NAMES = (
    ".env",
    ".env.*",
    ".netrc",
    "hosts.yml",
    "hosts.yaml",
    "id_rsa*",
    "id_ed25519*",
    "*.pem",
    "*.pem.*",
    "*.key",
    "*.key.*",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "credentials.json",
    "credentials.yaml",
    "credentials.yml",
    "credentials.*",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.*",
    "*api_keys*",
    "*api_secrets*",
    "*binance_keys*",
    "*binance_secrets*",
    "*binance_credentials*",
)
SENSITIVE_DIRS = {"secrets", ".secrets", "credentials", ".credentials", ".aws", ".ssh", ".gnupg"}
FIELD = (
    r"(?<![\w-])[\"']?(?:[a-z0-9]+[_-])*"
    r"(?:api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|password|passwd|private[_-]?key|binance[_-]?(?:key|secret)|"
    r"access[_-]?key[_-]?id)"
    r"[\"']?(?![\w-])\s*[:=]\s*"
    r"(?:(?P<quote>[\"'])(?P<quoted>[^\"'\r\n]*)(?P=quote)|"
    r"(?P<bare>[a-z0-9_./+@=-]{16,})(?=$|[\s,#}]))"
)
ASSIGNMENT = re.compile(FIELD, re.IGNORECASE | re.MULTILINE)
TOKEN = re.compile(
    r"(?<![\w-])(?:gh[pousr]_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{30,}|"
    r"sk-(?:proj-|svcacct-)?[a-zA-Z0-9_-]{20,}|AKIA[A-Z0-9]{16})(?![\w-])"
)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")
BINANCE_SHAPE = re.compile(r"(?<![\w/-])[a-zA-Z0-9]{64}(?![\w/-])")
AUTH_HEADER = re.compile(r"(?i)\b(?:Bearer|Basic)\s+([a-zA-Z0-9_./+=-]{20,})")
URL_PASSWORD = re.compile(
    r"(?<![\w+.-])[a-zA-Z][a-zA-Z0-9+.-]{0,255}://[^\s/:]+:([^\s/@]+)@"
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str


class GuardError(Exception):
    """Check could not complete; fail closed without exposing Git stderr."""


def placeholder(value: str) -> bool:
    value = value.strip()
    if not value or value.upper() in {"REDACTED", "REPLACE_ME", "CHANGEME", "PLACEHOLDER"}:
        return True
    if value.startswith(("YOUR_", "your_")):
        return True
    if re.fullmatch(r"[<].+[>]|\$\{[^}]+\}|\{[a-zA-Z_]\w*\}|[*xX]+", value):
        return True
    return False


def sensitive_path(path: str) -> bool:
    parts = PurePosixPath(path.lower()).parts
    if not parts:
        return False
    if set(parts[:-1]) & SENSITIVE_DIRS:
        return True
    name = parts[-1]
    # A template is still scanned for actual embedded credentials.
    if name == ".env.example":
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in SENSITIVE_NAMES)


def entropy(value: str) -> float:
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in Counter(value).values())


def scan_content(path: str, content: bytes) -> list[Finding]:
    findings: list[Finding] = []
    if sensitive_path(path):
        findings.append(Finding(path, 0, "credential-file"))
    # Latin-1 preserves ASCII credentials even in a binary or invalid UTF-8 blob.
    for number, line in enumerate(content.decode("latin-1").splitlines(), 1):
        rules: set[str] = set()
        if PRIVATE_KEY.search(line):
            rules.add("private-key")
        if TOKEN.search(line):
            rules.add("provider-token")
        for match in ASSIGNMENT.finditer(line):
            value = match.group("quoted") if match.group("quote") else match.group("bare")
            # Existing public-client rejection test uses this exact noncredential sentinel.
            # Do not skip the test file: every other value and rule is still checked.
            if path == "tests/test_public_client.py" and value == "forbidden":
                continue
            if not placeholder(value):
                rules.add("credential-assignment")
        for match in URL_PASSWORD.finditer(line):
            if not placeholder(match.group(1)):
                rules.add("url-password")
        for match in AUTH_HEADER.finditer(line):
            if not placeholder(match.group(1)):
                rules.add("authorization-header")
        for match in BINANCE_SHAPE.finditer(line):
            value = match.group()
            # Content hashes are ordinary research evidence, not credential patterns.
            if not re.fullmatch(r"[a-fA-F0-9]{64}", value) and entropy(value) >= 4.0:
                rules.add("unlabelled-64-character-token")
        findings.extend(Finding(path, number, rule) for rule in sorted(rules))
    return findings


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=False
    )
    if result.returncode:
        raise GuardError("Git read failed; credential check did not complete")
    return result.stdout


def staged_blobs(root: Path) -> set[tuple[str, str]]:
    blobs: set[tuple[str, str]] = set()
    for row in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not row:
            continue
        header, path = row.split(b"\t", 1)
        mode, object_id, stage = header.split()
        if stage != b"0":
            raise GuardError("Unmerged index; credential check did not complete")
        if mode != b"160000":
            blobs.add((object_id.decode("ascii"), path.decode("utf-8", "surrogateescape")))
    return blobs


def history_blobs(root: Path) -> set[tuple[str, str]]:
    blobs: set[tuple[str, str]] = set()
    # Include every local/remote ref so non-main branch pushes are protected too.
    for commit in git(root, "rev-list", "--all").splitlines():
        for row in git(root, "ls-tree", "-r", "-z", commit.decode("ascii")).split(b"\0"):
            if not row:
                continue
            header, path = row.split(b"\t", 1)
            _, kind, object_id = header.split()
            if kind == b"blob":
                blobs.add((object_id.decode("ascii"), path.decode("utf-8", "surrogateescape")))
    return blobs


def scan_repository(root: Path, *, history: bool) -> tuple[list[Finding], int]:
    refs = history_blobs(root) if history else staged_blobs(root)
    object_ids = sorted({object_id for object_id, _ in refs})
    if not object_ids:
        return [], 0
    raw = git(root, "cat-file", "--batch", data=("\n".join(object_ids) + "\n").encode())
    contents: dict[str, bytes] = {}
    offset = 0
    for object_id in object_ids:
        newline = raw.find(b"\n", offset)
        if newline < 0:
            raise GuardError("Incomplete Git blob response")
        header = raw[offset:newline].split()
        if len(header) != 3 or header[0].decode() != object_id or header[1] != b"blob":
            raise GuardError("Invalid Git blob response")
        size = int(header[2])
        start = newline + 1
        if start + size >= len(raw) or raw[start + size : start + size + 1] != b"\n":
            raise GuardError("Truncated Git blob response")
        contents[object_id] = raw[start : start + size]
        offset = start + size + 1
    findings = {
        finding for object_id, path in refs for finding in scan_content(path, contents[object_id])
    }
    return sorted(findings, key=lambda f: (f.path, f.line, f.rule)), len(refs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--history", action="store_true")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        findings, count = scan_repository(args.repo, history=args.history)
    except (GuardError, OSError, ValueError) as error:
        # Do not print exception text: filenames or subprocess data may be sensitive.
        print(json.dumps({"status": "error", "error_type": type(error).__name__}))
        return 2
    print(
        json.dumps(
            {
                "status": "blocked" if findings else "passed",
                "blobs_checked": count,
                "findings": [asdict(finding) for finding in findings],
            },
            ensure_ascii=True,
        )
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
