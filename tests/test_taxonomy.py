"""Guards for the closed Tacit taxonomy.

``Config.MEMORY_TYPES`` is the classification vocabulary for the whole product:
it drives the MCP tool schemas, the CLI help, the dashboard filters and badge
colours, and the detail templates in the generated agent rules. These tests fail
if any of those surfaces drifts back to a hand-maintained copy of the list.
"""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.main import app
from src.core.agent_rules import AGENT_RULE_CONTENT
from src.export.templates import CATEGORY_COLORS, HTML_PREVIEW_TEMPLATE
from src.mcp.tools import TOOL_DEFINITIONS
from src.utils.config import Config

CORE_TYPES = ["decision", "command", "hack", "architecture", "error", "context"]


@pytest.fixture
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    import shutil

    base = Path(__file__).resolve().parent / "_taxonomy_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# The taxonomy itself
# ---------------------------------------------------------------------------

def test_taxonomy_is_unique_lowercase_slugs():
    types = Config.MEMORY_TYPES
    assert len(types) == len(set(types))
    for name in types:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name


def test_default_category_belongs_to_the_taxonomy():
    assert Config.DEFAULT_MEMORY_TYPE in Config.MEMORY_TYPES


def test_original_core_categories_remain_valid():
    """Existing databases, docs and saved briefings reference these by name."""
    for legacy in CORE_TYPES:
        assert legacy in Config.MEMORY_TYPES


def test_taxonomy_stays_within_the_practical_ceiling():
    """A taxonomy only works while agents can reliably pick one category.

    Past roughly a dozen choices, classification accuracy collapses and entries
    start fragmenting across near-synonyms.
    """
    assert 6 <= len(Config.MEMORY_TYPES) <= 12


# ---------------------------------------------------------------------------
# Surfaces derived from it
# ---------------------------------------------------------------------------

def _collect_type_enums(node, found):
    """Recursively collect every JSON-Schema enum that lists memory categories."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "enum" and isinstance(value, list) and "decision" in value:
                found.append(value)
            else:
                _collect_type_enums(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_type_enums(item, found)


def test_mcp_tool_schemas_are_derived_from_the_taxonomy():
    found = []
    for tool in TOOL_DEFINITIONS:
        _collect_type_enums(tool["inputSchema"], found)

    assert len(found) >= 3, "expected memory_add, memory_add_batch and memory_search enums"
    for enum in found:
        assert enum == list(Config.MEMORY_TYPES)


def test_mcp_server_description_advertises_every_category():
    from src.mcp.server import _ADD_MEMORY_DESCRIPTION

    for name in Config.MEMORY_TYPES:
        assert name in _ADD_MEMORY_DESCRIPTION


def test_dashboard_lists_every_category_in_both_dropdowns():
    for name in Config.MEMORY_TYPES:
        assert HTML_PREVIEW_TEMPLATE.count(f'<option value="{name}">') == 2


def test_dashboard_colours_every_category_and_keeps_a_fallback():
    for name in Config.MEMORY_TYPES:
        assert name in CATEGORY_COLORS, f"{name} has no badge colour"
        if name != "context":
            assert f"case '{name}'" in HTML_PREVIEW_TEMPLATE
    # Unknown or legacy categories must still render rather than break the badge.
    assert "default:" in HTML_PREVIEW_TEMPLATE


def test_no_taxonomy_placeholders_leak_into_the_rendered_dashboard():
    assert "TACIT_CATEGORY" not in HTML_PREVIEW_TEMPLATE


# ---------------------------------------------------------------------------
# Agent rules
# ---------------------------------------------------------------------------

def test_agent_rules_document_every_category():
    for name in Config.MEMORY_TYPES:
        assert f"`{name}`" in AGENT_RULE_CONTENT, f"{name} missing from the agent rules"


def test_agent_rules_declare_the_taxonomy_closed():
    lowered = AGENT_RULE_CONTENT.lower()
    assert "closed set" in lowered
    assert "never invent a new category" in lowered


def test_agent_rules_mandate_a_descriptive_title():
    """Only title/tags/summary are embedded, so a vague title breaks retrieval."""
    lowered = AGENT_RULE_CONTENT.lower()
    assert "writing titles" in lowered
    assert "must have a `title`" in lowered
    assert "embedded into the vector index" in lowered
    # The rules must state the failure mode, not just the requirement.
    assert "unfindable" in lowered


def test_agent_rules_map_every_category_to_a_content_archetype():
    """Each category must be reachable from one of the five archetype headings."""
    archetypes = re.findall(r"### Archetype [A-E] — [^\n]+", AGENT_RULE_CONTENT)
    assert len(archetypes) == 5

    covered = set()
    for heading in archetypes:
        for name in Config.MEMORY_TYPES:
            if f"`{name}`" in heading:
                covered.add(name)
    assert covered == set(Config.MEMORY_TYPES)


def test_init_writes_the_taxonomy_into_workspace_rules(tmp_dir, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    target = tmp_dir / "project"

    result = CliRunner().invoke(app, ["init", "--dir", str(target)])

    assert result.exit_code == 0
    written = (target / ".cursorrules").read_text(encoding="utf-8")
    for name in Config.MEMORY_TYPES:
        assert f"`{name}`" in written
