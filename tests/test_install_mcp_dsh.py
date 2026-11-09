"""`tacit install-mcp --client deepseek-harness` profile resolution.

The installer used to assume the profile was always named ``web``. A machine
that only has a ``desktop`` profile therefore got "No dsh profile found" even
though dsh was installed correctly. These tests pin the resolution order:
``$DSH_PROFILE`` -> ``$DSH_PROFILE_DIR`` -> the only profile on disk -> ``web``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from src.cli.main import app
from src.utils.config import Config

runner = CliRunner()


@pytest.fixture
def dsh_home(tmp_path, monkeypatch):
    """An isolated, empty dsh home with no profile inherited from the shell."""
    home = tmp_path / ".dsh"
    monkeypatch.setenv("DSH_HOME", str(home))
    monkeypatch.delenv("DSH_PROFILE", raising=False)
    monkeypatch.delenv("DSH_PROFILE_DIR", raising=False)
    # The CLI callback probes GitHub for releases; keep tests offline.
    monkeypatch.setattr(Config, "check_for_updates", classmethod(lambda cls: None))
    return home


def make_profile(home: Path, name: str, *, patch: bool = True) -> Path:
    profile_dir = home / "profiles" / name
    profile_dir.mkdir(parents=True)
    (profile_dir / "cordis.yml").write_text("[]\n", encoding="utf-8")
    if patch:
        (profile_dir / "cordis.patch.yml").write_text("", encoding="utf-8")
    return profile_dir


def run_install():
    return runner.invoke(app, ["install-mcp", "--client", "deepseek-harness"])


def load_patch(profile_dir: Path):
    text = (profile_dir / "cordis.patch.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or []


def tacit_rows(entries):
    rows = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("insert"), list):
            rows.extend(
                row
                for row in entry["insert"]
                if isinstance(row, dict) and row.get("id") == "mcp-tacit"
            )
    return rows


def test_single_non_web_profile_is_autodetected(dsh_home):
    profile_dir = make_profile(dsh_home, "desktop")

    result = run_install()

    assert result.exit_code == 0, result.output
    assert "desktop" in result.output
    rows = tacit_rows(load_patch(profile_dir))
    assert len(rows) == 1
    assert rows[0]["name"] == "@deepseek-ai/dsh-mcp-client"
    assert rows[0]["config"] == {
        "serverName": "tacit",
        "transport": "stdio",
        "command": "tacit",
        "args": ["mcp"],
        "failOnStartupError": False,
    }


def test_explicit_profile_wins_over_the_only_profile(dsh_home, monkeypatch):
    make_profile(dsh_home, "desktop")
    work = make_profile(dsh_home, "work")
    monkeypatch.setenv("DSH_PROFILE", "work")

    result = run_install()

    assert result.exit_code == 0, result.output
    assert len(tacit_rows(load_patch(work))) == 1
    desktop_patch = dsh_home / "profiles" / "desktop" / "cordis.patch.yml"
    assert desktop_patch.read_text(encoding="utf-8") == ""


def test_profile_dir_basename_is_used_when_profile_is_unset(dsh_home, monkeypatch):
    desktop = make_profile(dsh_home, "desktop")
    alpha = make_profile(dsh_home, "alpha")
    monkeypatch.setenv("DSH_PROFILE_DIR", str(alpha))

    result = run_install()

    assert result.exit_code == 0, result.output
    assert len(tacit_rows(load_patch(alpha))) == 1
    assert (desktop / "cordis.patch.yml").read_text(encoding="utf-8") == ""


def test_explicit_profile_beats_the_profile_dir(dsh_home, monkeypatch):
    desktop = make_profile(dsh_home, "desktop")
    alpha = make_profile(dsh_home, "alpha")
    monkeypatch.setenv("DSH_PROFILE", "desktop")
    monkeypatch.setenv("DSH_PROFILE_DIR", str(alpha))

    result = run_install()

    assert result.exit_code == 0, result.output
    assert len(tacit_rows(load_patch(desktop))) == 1
    assert (alpha / "cordis.patch.yml").read_text(encoding="utf-8") == ""


def test_ambiguous_profiles_without_a_hint_are_reported(dsh_home):
    make_profile(dsh_home, "desktop")
    make_profile(dsh_home, "work")

    result = run_install()

    assert result.exit_code == 0, result.output
    assert "desktop, work" in result.output
    assert "DSH_PROFILE" in result.output
    assert not (dsh_home / "profiles" / "web").exists()


def test_unknown_explicit_profile_is_reported(dsh_home, monkeypatch):
    make_profile(dsh_home, "desktop")
    monkeypatch.setenv("DSH_PROFILE", "ghost")

    result = run_install()

    assert "No dsh profile found" in result.output
    assert "desktop" in result.output
    assert not (dsh_home / "profiles" / "ghost").exists()


def test_patch_layer_is_created_when_absent(dsh_home):
    profile_dir = make_profile(dsh_home, "desktop", patch=False)
    assert not (profile_dir / "cordis.patch.yml").exists()

    result = run_install()

    assert result.exit_code == 0, result.output
    assert len(tacit_rows(load_patch(profile_dir))) == 1


def test_existing_patch_entries_are_preserved(dsh_home):
    profile_dir = make_profile(dsh_home, "desktop")
    (profile_dir / "cordis.patch.yml").write_text(
        "- id: agent-default-model\n"
        '  name: "@deepseek-ai/dsh-agent-default-model"\n'
        "  config:\n"
        "    provider: deepseek-account\n",
        encoding="utf-8",
    )

    result = run_install()

    assert result.exit_code == 0, result.output
    entries = load_patch(profile_dir)
    assert entries[0]["id"] == "agent-default-model"
    assert entries[0]["config"]["provider"] == "deepseek-account"
    assert len(tacit_rows(entries)) == 1


def test_rerunning_does_not_duplicate_the_entry(dsh_home):
    profile_dir = make_profile(dsh_home, "desktop")

    assert run_install().exit_code == 0
    assert run_install().exit_code == 0

    entries = load_patch(profile_dir)
    assert len(tacit_rows(entries)) == 1
    # Exactly one insert wrapper survives: the one rewritten by the second run.
    inserts = [
        entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("insert"), list)
    ]
    assert len(inserts) == 1
