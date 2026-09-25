"""Unit and integration tests for memory pinning feature across Storage, Bootstrap, MCP, and CLI."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import pytest
from typer.testing import CliRunner

from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage
from src.core.bootstrap import BootstrapEngine
from src.mcp.handlers import MemoryMCPHandlers
from src.mcp.tools import TOOL_DEFINITIONS
from src.cli.main import app
from src.core.agent_rules import AGENT_RULE_CONTENT


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / ".tacit" / "memory.db"
        s = MemoryStorage(db_path)
        yield s


def test_storage_pin_and_unpin(storage):
    node1 = MemoryNode(
        id="node-1",
        content="Important architectural decision 1",
        title="Arch 1",
        type="architecture",
        status="active",
    )
    node2 = MemoryNode(
        id="node-2",
        content="Critical invariant 2",
        title="Invariant 2",
        type="constraint",
        status="active",
    )
    storage.add_memory(node1)
    storage.add_memory(node2)

    # Pin memories
    res = storage.pin_memories(["node-1", "node-2", "non-existent"])
    assert res["count"] == 2
    assert "node-1" in res["pinned"]
    assert "node-2" in res["pinned"]
    assert "non-existent" in res["not_found"]

    assert storage.is_pinned("node-1") is True
    assert storage.is_pinned("node-2") is True
    assert storage.is_pinned("non-existent") is False

    pinned_ids = storage.get_pinned_ids()
    assert pinned_ids == ["node-1", "node-2"]

    pinned_nodes = storage.get_pinned_memories()
    assert len(pinned_nodes) == 2
    assert pinned_nodes[0].id == "node-1"
    assert pinned_nodes[1].id == "node-2"

    # Unpin one memory
    unpin_res = storage.unpin_memories(["node-1"])
    assert unpin_res["count"] == 1
    assert "node-1" in unpin_res["unpinned"]
    assert storage.is_pinned("node-1") is False
    assert storage.is_pinned("node-2") is True
    assert storage.get_pinned_ids() == ["node-2"]

    # Clear pinned memories
    cleared = storage.clear_pinned_memories()
    assert cleared == 1
    assert storage.get_pinned_ids() == []


def test_storage_delete_memory_removes_pin(storage):
    node = MemoryNode(
        id="node-1",
        content="Important architectural decision",
        title="Arch",
        type="architecture",
        status="active",
    )
    storage.add_memory(node)
    storage.pin_memories(["node-1"])
    assert storage.is_pinned("node-1") is True

    storage.delete_memory("node-1")
    assert storage.is_pinned("node-1") is False
    assert storage.get_pinned_ids() == []


def test_bootstrap_renders_pinned_at_end_disregard_of_score(storage):
    # Create multiple memories
    for i in range(5):
        storage.add_memory(
            MemoryNode(
                id=f"regular-{i}",
                content=f"Regular memory content {i}",
                title=f"Regular {i}",
                type="decision",
                status="active",
            )
        )

    # Add a pinned memory
    pinned_node = MemoryNode(
        id="pinned-critical-1",
        content="Never delete production database without 2-person approval.",
        title="Production DB Safety Invariant",
        type="constraint",
        status="active",
    )
    storage.add_memory(pinned_node)
    storage.pin_memories(["pinned-critical-1"])

    briefing = BootstrapEngine.generate_briefing(storage, budget=2000)

    assert "pinned_count" in briefing
    assert briefing["pinned_count"] == 1
    text = briefing["formatted"]

    # Check that "Pinned by DEV" section is present
    assert "Pinned by DEV (important tacit knowledge)" in text
    assert "Production DB Safety Invariant" in text
    assert "Never delete production database without 2-person approval." in text
    assert "★ PINNED" in text

    # Verify that the pinned section appears near the end (after normal tiers)
    dev_pin_idx = text.find("Pinned by DEV")
    assert dev_pin_idx != -1
    # Check that regular entries appear before dev_pin_idx
    if "Regular" in text:
        first_regular_idx = text.find("Regular")
        assert first_regular_idx < dev_pin_idx


def test_mcp_handler_pin_and_unpin(storage):
    handlers = MemoryMCPHandlers(default_storage=storage)

    node1 = MemoryNode(
        id="mcp-node-1",
        content="MCP content",
        title="MCP Title",
        type="decision",
        status="active",
    )
    storage.add_memory(node1)

    # Pin via handler
    res = handlers.handle_memory_pin(ids=["mcp-node-1"])
    assert res["success"] is True
    assert res["count"] == 1
    assert "mcp-node-1" in res["pinned"]
    assert storage.is_pinned("mcp-node-1") is True

    # Unpin via handler
    res_unpin = handlers.handle_memory_pin(ids=["mcp-node-1"], unpin=True)
    assert res_unpin["success"] is True
    assert res_unpin["count"] == 1
    assert "mcp-node-1" in res_unpin["unpinned"]
    assert storage.is_pinned("mcp-node-1") is False


def test_mcp_tool_definition():
    pin_tool = next((t for t in TOOL_DEFINITIONS if t["name"] == "memory_pin"), None)
    assert pin_tool is not None
    assert "ids" in pin_tool["inputSchema"]["properties"]
    assert pin_tool["inputSchema"]["required"] == ["ids"]


def test_cli_pin_command(storage, monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr("src.cli.main.get_storage", lambda project=None: storage)

    node = MemoryNode(
        id="cli-node-1",
        content="CLI test content",
        title="CLI Title",
        type="architecture",
        status="active",
    )
    storage.add_memory(node)

    # Pin via CLI
    result = runner.invoke(app, ["pin", "cli-node-1"])
    assert result.exit_code == 0
    assert "cli-node-1" in result.output
    assert "Pinned successfully" in result.output
    assert storage.is_pinned("cli-node-1") is True

    # List pinned
    list_res = runner.invoke(app, ["pin", "--list"])
    assert list_res.exit_code == 0
    assert "cli-node-1" in list_res.output

    # Unpin
    unpin_res = runner.invoke(app, ["pin", "cli-node-1", "--unpin"])
    assert unpin_res.exit_code == 0
    assert "Unpinned 1 memory" in unpin_res.output
    assert storage.is_pinned("cli-node-1") is False


def test_agent_rules_contain_pinned_guidance():
    assert "Pinned Memories (Pinned by DEV)" in AGENT_RULE_CONTENT
    assert "Pinned by DEV" in AGENT_RULE_CONTENT
    assert "disregard of their score" in AGENT_RULE_CONTENT
