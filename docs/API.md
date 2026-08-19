# Project Memory Cortex - Python API Reference

The `project-memory-cortex` Python library provides direct programmatic access to the immutable memory core, DAG graph engine, SQLite storage, and search index.

---

## Core Modules

### `MemoryNode` (`src.core.memory_node`)
Represents an immutable, content-addressed memory unit.

```python
from src.core import MemoryNode

node = MemoryNode(
    content="Switched backend from Flask to FastAPI for async performance.",
    type="decision",
    summary="Migrated Flask to FastAPI",
    title="Decision: Migrate to FastAPI",
    tags=["backend", "api", "async"],
    impact="high",
    author="lead-engineer",
)

# Properties
print(node.id)           # UUID string
print(node.content_hash) # SHA-256 hash of title, summary, content, timestamp
print(node.merkle_root)  # Combined cryptographic Merkle root with parent nodes
print(node.verify())     # True (confirms integrity has not been tampered with)
```

---

### `MemoryDAG` (`src.core.memory_dag`)
Maintains an acyclic dependency graph across memories with causality and lineage analysis.

```python
from src.core import MemoryDAG, MemoryNode

dag = MemoryDAG()

parent = MemoryNode(content="Initial Database schema with PostgreSQL", type="architecture")
child = MemoryNode(
    content="Added index on user email",
    type="decision",
    parents=[parent.id]
)

dag.add_node(parent)
dag.add_node(child)

# Lineage queries
ancestors = dag.get_ancestors(child.id)    # {parent.id}
descendants = dag.get_descendants(parent.id) # {child.id}
dag.verify_integrity()                     # True
```

---

### `MemoryStorage` (`src.core.storage`)
Thread-safe SQLite storage with FTS5 indexing.

```python
from pathlib import Path
from src.core import MemoryStorage, MemoryNode

storage = MemoryStorage(Path(".project-memory/memory.db"))

# Insert
storage.add_memory(node)

# Fetch
retrieved = storage.get_memory(node.id)

# Full text search
results = storage.search_full_text("FastAPI migration", limit=5)
```

---

### `MarkdownExporter` (`src.export.markdown_exporter`)
Export database memories to organized Markdown directory structure with `INDEX.md`.

```python
from pathlib import Path
from src.export import MarkdownExporter

exporter = MarkdownExporter(storage)
summary = exporter.export_all(Path("./memory-export"))
print(f"Exported {summary.total_files} files.")
```
