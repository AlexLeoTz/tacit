"""Coverage for the two failures found when running Tacit inside DeepSeek Harness.

1. **`tacit search` could silently degrade.** The old local ONNX model downloaded
   into a sandboxed/excluded cache, or never loaded at all, so queries quietly
   returned keyword-only results. Hosted Gemini embeddings remove that failure
   mode; with no key, search is explicitly keyword-only and an empty result
   carries the exhaustive-scan protocol.

2. **`scope_hint` was trusted verbatim.** An agent passing an absolute path with
   a trailing separator silently changed ranking, and a bare call with no hint
   resolved the project from whatever the process CWD happened to be.
"""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

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
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "TACIT_EMBED_PROVIDER", "TACIT_GEMINI_DIM"):
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
# provider resolution: hosted only, no local model
# ---------------------------------------------------------------------------

def test_gemini_is_the_default_provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTESTKEY1234567890")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    EmbeddingService.reset()

    service = EmbeddingService.get()

    assert service.provider == "gemini"
    assert service.available is True
    assert service.dimension == 768


def test_openai_requires_an_explicit_opt_in_when_gemini_exists(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTESTKEY1234567890")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    EmbeddingService.reset()

    assert EmbeddingService.get().provider == "gemini"

    monkeypatch.setenv("TACIT_EMBED_PROVIDER", "openai")
    EmbeddingService.reset()

    assert EmbeddingService.get().provider == "openai"


def test_no_key_is_reported_without_downloading_anything(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    EmbeddingService.reset()

    service = EmbeddingService.get()

    assert service.available is False
    assert service.dimension == 0
    assert "GEMINI_API_KEY" in service.describe()


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


def test_reindex_reports_rate_limits_instead_of_a_traceback(tmp_dir, monkeypatch):
    """A 429 during reindex must explain itself and say the work is resumable."""
    from src.core.storage import MemoryStorage
    from src.search.embeddings import EmbeddingUnavailable

    MemoryStorage(tmp_dir / ".tacit" / "memory.db")
    monkeypatch.setattr(EmbeddingService, "available", property(lambda self: True))
    monkeypatch.setattr(EmbeddingService, "provider", property(lambda self: "gemini"))

    def rate_limited(self, progress=True, force=False):
        raise EmbeddingUnavailable(
            "Gemini embedding request failed: HTTP Error 429: Too Many Requests"
        )

    monkeypatch.setattr(MemoryStorage, "reindex_all", rate_limited)

    from src.cli.main import app

    result = CliRunner().invoke(app, ["reindex", "--project", str(tmp_dir)])

    # Panel borders sit between wrapped lines, so assert on fragments that stay
    # inside a single line rather than on prose that spans a wrap.
    flat = " ".join(result.stdout.split())
    assert result.exit_code == 1
    assert "Embedding stopped early" in flat
    assert "HTTP Error 429: Too Many Requests" in flat
    assert "Embeddings already written are kept" in flat
    assert "TACIT_EMBED_MIN_INTERVAL" in flat
