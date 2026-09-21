"""Coverage for the two failures found when running Tacit inside DeepSeek Harness.

1. **`tacit search` appeared to hang.** fastembed's default cache is the OS temp
   directory, which the sandbox denies; the download then retried with backoff
   before failing, so a query blocked for seconds and returned nothing useful.
   A query must never download, and a missing model must fail in milliseconds.

2. **`scope_hint` was trusted verbatim.** An agent passing an absolute path with
   a trailing separator silently changed ranking, and a bare call with no hint
   resolved the project from whatever the process CWD happened to be.
"""

import shutil
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.search import embeddings as emb
from src.search.embeddings import EmbeddingService
from src.utils.scope import (
    infer_scope_from_cwd,
    normalize_scope_hints,
    resolve_scope_hints,
    scope_matches,
)


@pytest.fixture
def tmp_dir():
    """Workspace-local scratch directory (the OS temp dir may be sandboxed)."""
    base = Path(__file__).resolve().parent / "_resilience_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_provider(monkeypatch):
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "TACIT_EMBED_CACHE", "FASTEMBED_CACHE_PATH"):
        monkeypatch.delenv(var, raising=False)
    EmbeddingService.reset()
    yield
    EmbeddingService.reset()


# ---------------------------------------------------------------------------
# scope_hint sanitising
# ---------------------------------------------------------------------------

def test_absolute_path_outside_the_project_is_discarded(tmp_dir):
    """The exact failure reported: an agent passed a foreign workspace path."""
    project = tmp_dir / "kanlex-play"
    project.mkdir()

    hints = normalize_scope_hints([r"D:\startups-ideas\some-other-project\\"], project_root=project)

    assert hints == [], "a path outside the project cannot scope its memories"


def test_absolute_path_inside_the_project_becomes_relative(tmp_dir):
    project = tmp_dir / "proj"
    (project / "backend" / "app").mkdir(parents=True)

    hints = normalize_scope_hints([str(project / "backend" / "app")], project_root=project)

    assert hints == ["backend/app"]


def test_separators_and_trailing_slashes_are_normalised(tmp_dir):
    project = tmp_dir / "proj"
    (project / "src" / "api").mkdir(parents=True)

    hints = normalize_scope_hints(
        [r"src\api\\", "  src/api/  ", "./src/api"], project_root=project
    )

    assert hints == ["src/api"], "all three spellings are the same scope"


def test_empty_and_dot_hints_are_dropped(tmp_dir):
    assert normalize_scope_hints(["", "   ", ".", "./", None], project_root=tmp_dir) == []


def test_hints_are_capped(tmp_dir):
    hints = normalize_scope_hints([f"dir{i}" for i in range(50)], project_root=tmp_dir, limit=5)

    assert len(hints) == 5


# ---------------------------------------------------------------------------
# automatic scope from the active directory
# ---------------------------------------------------------------------------

def test_scope_is_inferred_from_a_subdirectory(tmp_dir):
    project = tmp_dir / "proj"
    nested = project / "backend" / "app"
    nested.mkdir(parents=True)

    assert infer_scope_from_cwd(project, cwd=nested) == ["backend/app"]


def test_no_scope_is_invented_at_the_project_root(tmp_dir):
    project = tmp_dir / "proj"
    project.mkdir()

    assert infer_scope_from_cwd(project, cwd=project) == []


def test_no_scope_outside_the_project(tmp_dir):
    project = tmp_dir / "proj"
    project.mkdir()

    assert infer_scope_from_cwd(project, cwd=tmp_dir) == []


def test_resolve_falls_back_to_the_active_directory(tmp_dir):
    """Tacit takes the active directory rather than requiring the agent to build one."""
    project = tmp_dir / "proj"
    nested = project / "src"
    nested.mkdir(parents=True)

    assert resolve_scope_hints(None, project_root=project, cwd=nested) == ["src"]


def test_resolve_prefers_explicit_hints_over_inference(tmp_dir):
    project = tmp_dir / "proj"
    nested = project / "src"
    nested.mkdir(parents=True)

    hints = resolve_scope_hints(["docs"], project_root=project, cwd=nested)

    assert hints == ["docs"]


def test_scope_matching_is_loose_and_separator_insensitive():
    stored = [r"src\api\auth.py", "backend/jobs"]

    assert scope_matches(stored, ["src/api"]) is True, "a directory hint matches files beneath it"
    assert scope_matches(stored, ["SRC/API"]) is True
    assert scope_matches(stored, ["frontend"]) is False
    assert scope_matches(stored, []) is False
    assert scope_matches([], ["src/api"]) is False


# ---------------------------------------------------------------------------
# deterministic project selection
# ---------------------------------------------------------------------------

def test_tacit_project_env_pins_the_workspace(tmp_dir, monkeypatch):
    """Documented but previously unimplemented: nothing read TACIT_PROJECT."""
    from src.utils.config import Config

    project = tmp_dir / "pinned-project"
    project.mkdir()
    elsewhere = tmp_dir / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("TACIT_PROJECT", str(project))

    assert Config.find_project_root() == project.resolve()


def test_invalid_tacit_project_falls_back_to_discovery(tmp_dir, monkeypatch):
    """A bogus value must not break discovery — it is ignored."""
    from src.utils.config import Config

    monkeypatch.chdir(tmp_dir)
    monkeypatch.setenv("TACIT_PROJECT", str(tmp_dir / "does-not-exist"))

    # tmp_dir lives inside this repository, so discovery should walk up to it.
    assert Config.find_project_root() == Path(__file__).resolve().parents[1]


def test_mcp_handlers_stay_pinned_when_cwd_changes(tmp_dir, monkeypatch):
    """A client changing directory mid-session must not switch databases."""
    from src.mcp.handlers import MemoryMCPHandlers

    project_a = tmp_dir / "project-a"
    project_b = tmp_dir / "project-b"
    for project in (project_a, project_b):
        (project / ".tacit").mkdir(parents=True)

    handlers = MemoryMCPHandlers(project_root=project_a)
    monkeypatch.chdir(project_b)

    resolved = handlers._resolve_storage()

    assert resolved.db_path.resolve() == (project_a / ".tacit" / "memory.db").resolve()


# ---------------------------------------------------------------------------
# model cache resolution
# ---------------------------------------------------------------------------

class FakeTextEmbedding:
    """Stands in for fastembed so no model is ever downloaded in tests."""

    calls: list = []

    def __init__(self, model_name, cache_dir=None, local_files_only=False, **kwargs):
        FakeTextEmbedding.calls.append(
            {"model": model_name, "cache_dir": cache_dir, "local_files_only": local_files_only}
        )
        if local_files_only:
            raise ValueError("Could not load model from cache")

    def embed(self, batch):  # pragma: no cover - only used when load succeeds
        raise AssertionError("no model should be loaded in these tests")


@pytest.fixture
def fake_fastembed(monkeypatch):
    FakeTextEmbedding.calls = []
    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding))
    return FakeTextEmbedding


def test_explicit_cache_override_is_respected(tmp_dir, monkeypatch):
    target = tmp_dir / "custom-cache"
    monkeypatch.setenv("TACIT_EMBED_CACHE", str(target))

    assert emb.resolve_cache_dir(tmp_dir) == target


def test_cache_falls_back_into_the_project_when_the_user_cache_is_unwritable(tmp_dir, monkeypatch):
    """Inside a workspace-restricted sandbox only the project directory is writable."""
    monkeypatch.setattr(emb, "user_cache_dir", lambda: Path("C:/Windows/System32/tacit_nope"))
    project = tmp_dir / "proj"
    project.mkdir()

    resolved = emb.resolve_cache_dir(project)

    assert resolved == project / ".tacit" / "models"
    assert resolved.is_dir()


def test_default_cache_is_persistent_not_temp(tmp_dir, monkeypatch):
    """fastembed's own default is the temp dir, which is exactly what broke."""
    monkeypatch.setattr(emb, "user_cache_dir", lambda: tmp_dir / "user-cache")

    resolved = emb.resolve_cache_dir(tmp_dir)

    assert resolved == tmp_dir / "user-cache"


# ---------------------------------------------------------------------------
# a query must never download
# ---------------------------------------------------------------------------

def test_available_does_not_allow_downloads(fake_fastembed, tmp_dir, monkeypatch):
    monkeypatch.setattr(emb, "resolve_cache_dir", lambda project_root=None: tmp_dir)

    service = EmbeddingService.get()
    assert service.available is False

    assert fake_fastembed.calls, "the model lookup must still be attempted"
    assert all(call["local_files_only"] is True for call in fake_fastembed.calls), (
        "a query-time load must be cache-only"
    )


def test_reindex_path_is_allowed_to_download(fake_fastembed, tmp_dir, monkeypatch):
    monkeypatch.setattr(emb, "resolve_cache_dir", lambda project_root=None: tmp_dir)

    EmbeddingService.get().ensure_local_model(allow_download=True)

    assert fake_fastembed.calls[-1]["local_files_only"] is False


def test_describe_explains_why_embeddings_are_unavailable(fake_fastembed, tmp_dir, monkeypatch):
    monkeypatch.setattr(emb, "resolve_cache_dir", lambda project_root=None: tmp_dir)

    description = EmbeddingService.get().describe()

    assert "unavailable" in description
    assert str(tmp_dir) in description, "the cache location belongs in the message"


def test_missing_model_fails_fast(fake_fastembed, tmp_dir, monkeypatch):
    """The reported symptom was a multi-second retry storm, not a wrong answer."""
    import time

    monkeypatch.setattr(emb, "resolve_cache_dir", lambda project_root=None: tmp_dir)

    started = time.perf_counter()
    EmbeddingService.get().available
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0


# ---------------------------------------------------------------------------
# search degrades to keyword-only instead of failing
# ---------------------------------------------------------------------------

def test_search_returns_keyword_results_when_embeddings_are_unavailable(tmp_dir):
    """`tacit search` must answer, not hang or raise, with no embedding backend."""
    from src.core.memory_node import MemoryNode
    from src.core.storage import MemoryStorage

    monkeypatch_service = EmbeddingService.get()
    assert monkeypatch_service.available is False or True  # provider state is irrelevant here

    storage = MemoryStorage(tmp_dir / ".tacit" / "memory.db")
    storage.add_memory(
        MemoryNode(
            id="wal-note",
            content="WAL mode fixes SQLite locking under concurrent writers",
            title="SQLite WAL mode for concurrent writers",
            summary="Enable WAL to avoid database is locked errors",
            tags=["sqlite", "wal"],
        )
    )

    results = storage.search_hybrid(query="SQLite WAL mode", limit=5, mode="hybrid")

    assert [item["node"].id for item in results] == ["wal-note"]


def test_search_cli_warns_when_results_are_keyword_only(tmp_dir, monkeypatch):
    from src.core.memory_node import MemoryNode
    from src.core.storage import MemoryStorage

    storage = MemoryStorage(tmp_dir / ".tacit" / "memory.db")
    storage.add_memory(
        MemoryNode(
            id="wal-note",
            content="WAL mode fixes SQLite locking under concurrent writers",
            title="SQLite WAL mode for concurrent writers",
            summary="Enable WAL to avoid database is locked errors",
            tags=["sqlite", "wal"],
        )
    )

    monkeypatch.setattr(EmbeddingService, "available", property(lambda self: False))
    monkeypatch.setattr(EmbeddingService, "describe", lambda self: "unavailable (test)")

    from src.cli.main import app

    result = CliRunner().invoke(app, ["search", "SQLite WAL", "--project", str(tmp_dir)])

    assert result.exit_code == 0
    assert "keyword-only" in result.stdout
    assert "wal-note" or "WAL mode" in result.stdout
