"""Unit tests for MarkdownExporter and ExportSummary generation."""

import tempfile
from pathlib import Path
import pytest

from src.core.memory_node import MemoryNode
from src.core.storage import MemoryStorage
from src.export.markdown_exporter import MarkdownExporter


def test_markdown_exporter_creates_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "export_test.db"
        export_out = Path(tmpdir) / "output"

        storage = MemoryStorage(db_path)
        node_decision = MemoryNode(
            content="Chose Pytest for test runner due to simple fixture ecosystem.",
            type="decision",
            title="Adopt Pytest",
            tags=["testing", "python"],
        )
        node_arch = MemoryNode(
            content="Designed layered hexagonal architecture for core memory services.",
            type="architecture",
            title="Hexagonal Architecture",
            tags=["architecture"],
        )

        storage.add_memory(node_decision)
        storage.add_memory(node_arch)

        exporter = MarkdownExporter(storage)
        summary = exporter.export_all(export_out)

        assert summary.total_memories == 2
        assert summary.total_files == 3  # 2 memory files + 1 INDEX.md
        assert (export_out / "INDEX.md").exists()
        assert (export_out / "decision").exists()
        assert (export_out / "architecture").exists()

        index_text = (export_out / "INDEX.md").read_text(encoding="utf-8")
        assert "Adopt Pytest" in index_text
        assert "Hexagonal Architecture" in index_text
