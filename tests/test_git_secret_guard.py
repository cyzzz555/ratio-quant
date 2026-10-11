"""Synthetic credentials only; no real provider or account access."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from app.git_secret_guard import placeholder, scan_content, scan_repository, sensitive_path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "backend/app/git_secret_guard.py"
SYNTHETIC = "aB3cD4eF5gH6iJ7k" * 4


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    for args in [
        ("init",),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "commit.gpgsign", "false"),
    ]:
        assert run_git(root, *args).returncode == 0
    return root


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "frontend/.env.local",
        "secrets/key.txt",
        "credentials/data.json",
        "config/BINANCE_credentials.json",
        "copies/api_keys.backup",
        "hosts.yml",
        "key.pem.old",
    ],
)
def test_sensitive_files_are_blocked(path: str) -> None:
    assert sensitive_path(path)
    assert scan_content(path, b"")[0].rule == "credential-file"


@pytest.mark.parametrize(
    "label",
    [
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "OPENAI_API_KEY",
        "apiKey",
        "apiSecret",
        "password",
        "private_key",
        "access_token",
    ],
)
def test_literal_assignments_are_detected(label: str) -> None:
    content = (json.dumps(label) + ": " + json.dumps(SYNTHETIC)).encode()
    assert any(f.rule == "credential-assignment" for f in scan_content("source.json", content))


def test_templates_hashes_and_environment_lookups_are_safe() -> None:
    content = (
        "BINANCE_API_KEY="
        + json.dumps("${BINANCE_API_KEY}")
        + "\n"
        + "BINANCE_API_SECRET="
        + json.dumps("YOUR_BINANCE_API_SECRET")
        + "\n"
        + "api_key = os.environ.get('BINANCE_API_KEY')\n"
        + "sha256="
        + "a09f" * 16
        + "\n"
        + "LIVE_TRADING_ENABLED=false\n"
    ).encode()
    assert not scan_content(".env.example", content)
    assert not sensitive_path("docs/secret_guard.md")
    assert not placeholder(SYNTHETIC)


def test_public_client_sentinel_does_not_exempt_file_or_real_values() -> None:
    safe = (json.dumps("apiKey") + ": " + json.dumps("forbidden")).encode()
    assert not scan_content("tests/test_public_client.py", safe)
    unsafe = (json.dumps("apiKey") + ": " + json.dumps(SYNTHETIC)).encode()
    assert scan_content("tests/test_public_client.py", unsafe)
    assert scan_content("tests/other.py", safe)


def test_provider_tokens_private_keys_and_binary_bytes() -> None:
    content = b"\xff\x00" + ("sk-" + SYNTHETIC).encode()
    assert any(f.rule == "provider-token" for f in scan_content("source.bin", content))
    header = "-----BEGIN " + "PRIVATE KEY-----"
    assert scan_content("source.txt", header.encode())[0].rule == "private-key"
    assert any(
        f.rule == "unlabelled-64-character-token"
        for f in scan_content("source.txt", SYNTHETIC.encode())
    )


def test_connection_password_and_authorization_header() -> None:
    address = "postgresql://alice:" + SYNTHETIC + "@localhost/database"
    assert any(f.rule == "url-password" for f in scan_content("source.txt", address.encode()))
    header = "Authorization: Bearer " + SYNTHETIC
    assert any(
        f.rule == "authorization-header" for f in scan_content("source.txt", header.encode())
    )


def test_staged_content_is_checked_instead_of_clean_working_copy(repo: Path) -> None:
    source = repo / "source.txt"
    source.write_text("BINANCE_API_KEY=" + json.dumps(SYNTHETIC))
    assert run_git(repo, "add", "source.txt").returncode == 0
    source.write_text("safe working copy")
    findings, count = scan_repository(repo, history=False)
    assert count == 1
    assert findings
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--staged"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert SYNTHETIC not in result.stdout + result.stderr
    assert json.loads(result.stdout)["findings"][0]["path"] == "source.txt"


def test_history_retains_deleted_credentials_and_other_branches(repo: Path) -> None:
    source = repo / "source.txt"
    source.write_text("BINANCE_API_SECRET=" + json.dumps(SYNTHETIC))
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "synthetic credential").returncode == 0
    source.write_text("safe current content")
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "clean current content").returncode == 0
    assert not scan_repository(repo, history=False)[0]
    assert scan_repository(repo, history=True)[0]


def test_history_includes_a_secret_on_a_non_current_branch(repo: Path) -> None:
    source = repo / "source.txt"
    source.write_text("safe")
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "safe").returncode == 0
    clean = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert run_git(repo, "checkout", "-b", "synthetic-test-branch").returncode == 0
    source.write_text("BINANCE_API_SECRET=" + json.dumps(SYNTHETIC))
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "synthetic branch credential").returncode == 0
    assert run_git(repo, "checkout", "--detach", clean).returncode == 0
    assert not scan_repository(repo, history=False)[0]
    assert scan_repository(repo, history=True)[0]


def test_large_blob_is_scanned_to_its_end() -> None:
    content = b"a" * 2_000_000 + b"\n"
    content += ("BINANCE_API_KEY=" + json.dumps(SYNTHETIC)).encode()
    assert any(f.line == 2 for f in scan_content("large.txt", content))


def test_unicode_newline_path_and_symlink_do_not_read_target(repo: Path, tmp_path: Path) -> None:
    source = repo / "中文\nsource.txt"
    source.write_text("safe")
    outside = tmp_path / "outside.txt"
    outside.write_text(SYNTHETIC)
    (repo / "reference.txt").symlink_to(outside)
    assert run_git(repo, "add", ".").returncode == 0
    findings, count = scan_repository(repo, history=False)
    assert not findings
    assert count == 2


def test_non_repository_fails_closed(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(tmp_path), "--history"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "error"


def install_hooks(root: Path) -> None:
    target = root / "backend/app/git_secret_guard.py"
    target.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT, target)
    shutil.copytree(ROOT / ".githooks", root / ".githooks")
    for hook in (root / ".githooks").iterdir():
        hook.chmod(0o755)
    # Make hooks use this interpreter; no test dependency on a global Python install.
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    (root / ".gitignore").write_text(".venv/\n")
    assert run_git(root, "config", "core.hooksPath", ".githooks").returncode == 0


def test_real_pre_commit_hook_blocks_credential_file_even_when_force_added(repo: Path) -> None:
    install_hooks(repo)
    (repo / ".env").write_text("local value")
    assert run_git(repo, "add", "-f", ".env").returncode == 0
    result = run_git(repo, "commit", "-m", "must be rejected")
    assert result.returncode != 0
    assert "credential-file" in result.stdout + result.stderr
    assert run_git(repo, "rev-parse", "--verify", "HEAD").returncode != 0


def test_real_pre_push_hook_blocks_dirty_history_before_transmitting(
    repo: Path, tmp_path: Path
) -> None:
    install_hooks(repo)
    source = repo / "source.txt"
    source.write_text("safe current content")
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "safe start").returncode == 0
    # Deliberately bypass only a disposable test repository's commit hook, then verify push.
    source.write_text("BINANCE_API_KEY=" + json.dumps(SYNTHETIC))
    assert run_git(repo, "add", "source.txt").returncode == 0
    assert (
        run_git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-m", "synthetic").returncode == 0
    )
    source.write_text("safe current content")
    assert run_git(repo, "add", "source.txt").returncode == 0
    assert run_git(repo, "commit", "-m", "clean index").returncode == 0
    remote = tmp_path / "remote.git"
    assert (
        subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True).returncode == 0
    )
    assert run_git(repo, "remote", "add", "origin", str(remote)).returncode == 0
    result = run_git(repo, "push", "origin", "HEAD:refs/heads/main")
    assert result.returncode != 0
    assert SYNTHETIC not in result.stdout + result.stderr
    assert run_git(remote, "show-ref").returncode != 0


def test_ignore_patterns_cover_credentials_without_hiding_template(repo: Path) -> None:
    shutil.copyfile(ROOT / ".gitignore", repo / ".gitignore")
    for path in [
        ".env",
        "credentials/account.json",
        "config/binance_credentials.json",
        "backup.pem.old",
        "hosts.yml",
    ]:
        assert run_git(repo, "check-ignore", "--no-index", path).returncode == 0
    assert run_git(repo, "check-ignore", "--no-index", ".env.example").returncode != 0
    assert os.access(ROOT / ".githooks/pre-push", os.X_OK)
