"""Markdown exporter for writing persistent documentation files from project memories."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Dict, List, Optional

from ..core.memory_node import MemoryNode
from ..core.storage import MemoryStorage
from .templates import MEMORY_MARKDOWN_TEMPLATE, INDEX_MARKDOWN_TEMPLATE


@dataclass
class ExportSummary:
    """Statistics summary of an export run."""
    total_memories: int
    total_files: int
    export_directory: Path
    categories: Dict[str, int]


class MarkdownExporter:
    """Exports SQLite project memories into categorized markdown files with an index."""

    def __init__(self, storage: MemoryStorage):
        self.storage = storage

    def _sanitize_filename(self, text: str) -> str:
        """Create a filesystem-safe filename slug."""
        # Replace non-alphanumeric with hyphens
        slug = re.sub(r"[^\w\s-]", "", text).strip().lower()
        slug = re.sub(r"[-\s]+", "-", slug)
        return slug[:60] if slug else "untitled"

    def format_node_markdown(self, node: MemoryNode) -> str:
        """Render a MemoryNode into a formatted markdown string."""
        date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
        return MEMORY_MARKDOWN_TEMPLATE.format(
            title=node.title or node.summary,
            id=node.id,
            type=node.type,
            date=date_str,
            impact=node.impact,
            status=node.status,
            author=node.author,
            summary=node.summary,
            content=node.content,
            tags=", ".join(node.tags) if node.tags else "None",
            scope=", ".join(node.scope) if node.scope else "Global",
            parents=", ".join(f"`{p}`" for p in node.parents) if node.parents else "None",
            children=", ".join(f"`{c}`" for c in node.children) if node.children else "None",
            related=", ".join(f"`{r}`" for r in node.related) if node.related else "None",
            content_hash=node.content_hash,
            merkle_root=node.merkle_root,
        )

    def export_all(self, output_dir: Path) -> ExportSummary:
        """Export all memories from storage to output_dir grouped by type."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        memories = self.storage.get_all(limit=100000)
        categories_count: Dict[str, int] = {}
        written_files = 0

        # Export individual memory markdown files
        for node in memories:
            cat_dir = output_path / node.type
            cat_dir.mkdir(parents=True, exist_ok=True)

            date_prefix = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d")
            slug = self._sanitize_filename(node.title or node.summary)
            file_name = f"{date_prefix}-{slug}-{node.id[:8]}.md"
            file_path = cat_dir / file_name

            content_md = self.format_node_markdown(node)
            file_path.write_text(content_md, encoding="utf-8")

            categories_count[node.type] = categories_count.get(node.type, 0) + 1
            written_files += 1

        # Generate INDEX.md
        breakdown_lines = []
        for cat, count in sorted(categories_count.items()):
            breakdown_lines.append(f"- **{cat.capitalize()}**: {count} entries (`./{cat}/`)")
        breakdown_str = "\n".join(breakdown_lines) if breakdown_lines else "No memories recorded yet."

        recent_table_lines = [
            "| Date | Type | Title / Summary | File |",
            "|---|---|---|---|",
        ]
        for node in memories[:20]:
            date_prefix = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d")
            slug = self._sanitize_filename(node.title or node.summary)
            rel_file = f"./{node.type}/{date_prefix}-{slug}-{node.id[:8]}.md"
            title_clean = (node.title or node.summary).replace("|", "\\|")[:60]
            recent_table_lines.append(
                f"| {date_prefix} | `{node.type}` | {title_clean} | [View]({rel_file}) |"
            )
        recent_table_str = "\n".join(recent_table_lines)

        index_content = INDEX_MARKDOWN_TEMPLATE.format(
            generated_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            total_count=len(memories),
            breakdown=breakdown_str,
            recent_table=recent_table_str,
        )

        (output_path / "INDEX.md").write_text(index_content, encoding="utf-8")
        written_files += 1

        return ExportSummary(
            total_memories=len(memories),
            total_files=written_files,
            export_directory=output_path,
            categories=categories_count,
        )
