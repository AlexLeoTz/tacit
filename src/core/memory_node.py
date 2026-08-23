"""Immutable MemoryNode data structure for Tacit."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json
import uuid

from ..utils.hashing import calculate_content_hash, calculate_merkle_root


@dataclass(frozen=True)
class MemoryNode:
    """Immutable memory node with content addressing and Merkle lineage."""

    # Identity & Time
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )

    # Content
    content: str = ""
    summary: str = ""
    title: str = ""

    # Classification
    type: str = "decision"  # decision, command, hack, architecture, error, context
    tags: List[str] = field(default_factory=list)
    scope: List[str] = field(default_factory=list)
    impact: str = "medium"  # high, medium, low

    # Relationships
    parents: List[str] = field(default_factory=list)  # Causal parents
    children: List[str] = field(default_factory=list)  # Derived children
    related: List[str] = field(default_factory=list)  # Non-causal relations

    # Metadata
    author: str = "ai-agent"
    model_version: str = ""
    status: str = "active"  # active, superseded, deprecated

    # Integrity
    content_hash: str = ""
    merkle_root: str = ""

    # Raw metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Populate default summaries/titles and calculate cryptographic hashes."""
        # Auto-populate summary if omitted
        if not self.summary:
            computed_summary = (
                self.content[:100] + ("..." if len(self.content) > 100 else "")
                if self.content
                else "Untitled Memory"
            )
            object.__setattr__(self, "summary", computed_summary)

        # Auto-populate title if omitted
        if not self.title:
            content_snippet = (
                self.content[:50] + ("..." if len(self.content) > 50 else "")
                if self.content
                else "Memory Node"
            )
            computed_title = f"{self.type.capitalize()}: {content_snippet}"
            object.__setattr__(self, "title", computed_title)

        # Calculate content hash if empty
        if not self.content_hash:
            c_hash = calculate_content_hash(
                content=self.content,
                summary=self.summary,
                title=self.title,
                timestamp=self.timestamp,
            )
            object.__setattr__(self, "content_hash", c_hash)

        # Calculate Merkle root if empty
        if not self.merkle_root:
            m_root = calculate_merkle_root(
                content_hash=self.content_hash,
                timestamp=self.timestamp,
                parents=self.parents,
            )
            object.__setattr__(self, "merkle_root", m_root)
    def _calculate_content_hash(self) -> str:
        """Compute expected SHA-256 hash of content fields."""
        return calculate_content_hash(
            content=self.content,
            summary=self.summary,
            title=self.title,
            timestamp=self.timestamp,
        )

    def _calculate_merkle_root(self) -> str:
        """Compute expected Merkle root from content hash and parents."""
        return calculate_merkle_root(
            content_hash=self.content_hash,
            timestamp=self.timestamp,
            parents=self.parents,
        )

    def verify(self) -> bool:
        """Verify node integrity against recalculated hashes."""
        return (
            self.content_hash == self._calculate_content_hash()
            and self.merkle_root == self._calculate_merkle_root()
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with JSON-encoded relational & list fields for storage."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "content": self.content,
            "summary": self.summary,
            "title": self.title,
            "type": self.type,
            "tags": json.dumps(self.tags),
            "scope": json.dumps(self.scope),
            "impact": self.impact,
            "parents": json.dumps(self.parents),
            "children": json.dumps(self.children),
            "related": json.dumps(self.related),
            "author": self.author,
            "model_version": self.model_version,
            "status": self.status,
            "content_hash": self.content_hash,
            "merkle_root": self.merkle_root,
            "metadata": json.dumps(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryNode":
        """Create a MemoryNode instance from a stored dictionary."""

        def _safe_json_loads(val: Any, default: Any) -> Any:
            if isinstance(val, (list, dict)):
                return val
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    return default
            return default

        return cls(
            id=data["id"],
            timestamp=float(data["timestamp"]),
            content=data["content"],
            summary=data.get("summary", ""),
            title=data.get("title", ""),
            type=data.get("type", "decision"),
            tags=_safe_json_loads(data.get("tags"), []),
            scope=_safe_json_loads(data.get("scope"), []),
            impact=data.get("impact", "medium"),
            parents=_safe_json_loads(data.get("parents"), []),
            children=_safe_json_loads(data.get("children"), []),
            related=_safe_json_loads(data.get("related"), []),
            author=data.get("author", "ai-agent"),
            model_version=data.get("model_version", ""),
            status=data.get("status", "active"),
            content_hash=data.get("content_hash", ""),
            merkle_root=data.get("merkle_root", ""),
            metadata=_safe_json_loads(data.get("metadata"), {}),
        )


def validate_scope_paths(scope: List[str], project_path: Optional[str] = None) -> None:
    """Validate that scope paths exist in the codebase."""
    if not scope:
        return

    from ..utils.config import Config
    from pathlib import Path
    import os

    # Skip validation if disabled via env var (e.g., for test isolation)
    if os.environ.get("TACIT_NO_PATH_VALIDATION") == "true":
        return

    try:
        project_root = Config.find_project_root(project_path)
    except Exception:
        project_root = Path.cwd()

    for path_str in scope:
        # Clean trailing/leading slashes/spaces
        clean_str = path_str.strip().lstrip("/").rstrip("\\").lstrip("\\").rstrip("/")
        target_path = Path(clean_str)
        
        # Resolve relative to project root
        full_path = (project_root / target_path).resolve()
        
        # Also try relative to current working directory or absolute
        if not full_path.exists():
            fallback_path = Path(path_str).resolve()
            if fallback_path.exists():
                full_path = fallback_path

        if not full_path.exists():
            raise ValueError(
                f"Scope path '{path_str}' does not exist as a file or directory in the codebase."
            )
