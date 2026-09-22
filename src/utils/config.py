"""Configuration and Multi-Project Management for Tacit."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


class ProjectRootError(RuntimeError):
    """Raised when Tacit cannot identify a real project to store memories for.

    The failure mode this exists to prevent: a long-lived process (an MCP server,
    a daemon, a shell started in the home directory) resolves "the project" to a
    *container* directory — ``C:\\Users\\<name>``, a drive root, ``System32`` or a
    temp folder — and silently creates ``.tacit`` there. Every later session
    underneath it then reads and writes that one shared store, so a briefing
    mixes memories from unrelated repositories.
    """


class Config:
    """Centralized configuration and multi-project resolver for Tacit."""

    #: Files/directories whose presence marks a directory as a project root.
    PROJECT_MARKERS = (".tacit", ".git", "pyproject.toml", "package.json")

    DEFAULT_MEMORY_DIR_NAME = ".tacit"

    #: Pointer inside the marker directory naming the real store after `tacit move`.
    MEMORY_LOCATION_FILE = "location"
    DEFAULT_EXPORT_DIR_NAME = "memory-export"
    REGISTRY_FILE: Path = Path.home() / ".gemini" / "config" / "tacit_projects.json"

    PREVIEW_PORT: int = int(os.getenv("PREVIEW_PORT", "4000"))
    PREVIEW_WS_PORT: int = int(os.getenv("PREVIEW_WS_PORT", "4001"))
    MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "stdio")
    SEARCH_LIMIT: int = int(os.getenv("SEARCH_LIMIT", "50"))
    TOKEN_BUDGET: int = int(os.getenv("TACIT_TOKEN_BUDGET", "2000"))
    DUAL_WRITE: bool = os.getenv("TACIT_DUAL_WRITE", "true").lower() in ("true", "1", "yes")

    #: The closed Tacit taxonomy. Single source of truth: the MCP tool schemas,
    #: the dashboard filters, the CLI help and the generated agent rules all
    #: derive from this list, so adding a category here updates every surface.
    #:
    #: The set is deliberately finite. Each entry must answer a different
    #: question and drive a different level of required detail, otherwise
    #: entries fragment across near-synonyms and the briefing/dashboard
    #: grouping degrades. Do not extend it casually.
    MEMORY_TYPES = [
        # --- core (in use since the first release) ---
        "decision",      # a choice between alternatives, and why the others lost
        "command",       # an operational invocation needed to reproduce work
        "hack",          # a deliberate workaround for an external limitation
        "architecture",  # system structure: components, boundaries, data flow
        "error",         # a diagnosed failure, its root cause, and the fix
        "context",       # descriptive environment, domain, or business background
        # --- extended (distinct required detail, not covered above) ---
        "constraint",    # a binding limit: quota, licence, compliance, platform
        "convention",    # a normative rule for how code must be written here
        "security",      # authn/authz model, threat mitigations, secret handling
        "performance",   # measured baseline, bottleneck, and the delta achieved
        "integration",   # an external service/API/dependency contract and its quirks
        "migration",     # a schema/data/version migration with rollout and rollback
    ]

    #: Default category applied when a caller does not specify one.
    DEFAULT_MEMORY_TYPE = "decision"

    @classmethod
    def find_project_root(cls, start_path: Optional[str | Path] = None) -> Path:
        """Discover project root by walking upwards on auto-discovery, or using explicit path/name when provided."""
        current = Path.cwd().resolve()

        if not start_path:
            # TACIT_PROJECT pins the workspace deterministically, which matters for
            # long-lived MCP servers whose client may change the process CWD.
            pinned = os.environ.get("TACIT_PROJECT", "").strip()
            if pinned:
                candidate = Path(pinned).expanduser()
                if candidate.exists():
                    return candidate.parent if candidate.is_file() else candidate.resolve()
                # A bad value must not break discovery; fall through instead.

        if start_path:
            # If start_path is a Path object or already an existing filesystem directory/file
            p = Path(start_path)
            if p.is_absolute() and p.exists():
                return p.parent if p.is_file() else p.resolve()

            start_str = str(start_path).strip()

            # Check if start_str matches current project name or any parent directory in hierarchy
            if current.name.lower() == start_str.lower() or current.name.lower().startswith(start_str.lower()):
                return current

            for parent in current.parents:
                if parent.name.lower() == start_str.lower():
                    # If current workspace is a subfolder of that project (e.g. sokosupa.com inside Sokosupa)
                    # and current workspace has its own .tacit or .git, keep current workspace root
                    if (current / cls.DEFAULT_MEMORY_DIR_NAME).exists() or (current / ".git").exists():
                        return current
                    return parent.resolve()

            # Check if start_path matches registered projects (exact or case-insensitive)
            registered = cls.list_registered_projects()
            if start_str in registered:
                target_p = Path(registered[start_str])
                if target_p.exists():
                    return target_p.resolve()

            for reg_name, reg_path in registered.items():
                if reg_name.lower() == start_str.lower():
                    target_p = Path(reg_path)
                    if target_p.exists():
                        return target_p.resolve()

            # Check if path relative to cwd exists
            rel = (current / p).resolve()
            if rel.exists() and (rel / cls.DEFAULT_MEMORY_DIR_NAME).exists():
                return rel

            # If explicit path was provided and exists
            if p.exists():
                return p.parent if p.is_file() else p.resolve()

            # Fallback to current if start_str is just a generic project name that wasn't found as a distinct folder
            if not ("/" in start_str or "\\" in start_str):
                return current

            return rel

        probe = current
        while True:
            if (probe / cls.DEFAULT_MEMORY_DIR_NAME).exists():
                return probe
            if (probe / ".git").exists():
                return probe
            if (probe / "pyproject.toml").exists() or (probe / "package.json").exists():
                return probe
            if probe.parent == probe:
                break
            probe = probe.parent

        return current

    # ------------------------------------------------------------------
    # Project identity guards
    # ------------------------------------------------------------------

    @classmethod
    def has_project_marker(cls, path: Optional[str | Path] = None) -> bool:
        """True when ``path`` looks like a project root (marker file/dir present)."""
        try:
            candidate = Path(path).expanduser() if path else Path.cwd()
        except (OSError, TypeError):
            return False
        return any((candidate / marker).exists() for marker in cls.PROJECT_MARKERS)

    @classmethod
    def is_container_dir(cls, path: Optional[str | Path] = None) -> bool:
        """True for directories that *contain* projects rather than being one.

        Home directories, filesystem roots, Windows/Program Files/AppData trees
        and temp folders. A store created in one of these is shared by every
        unrelated workspace underneath it, which is exactly how memories from
        different repositories ended up in a single briefing.
        """
        try:
            candidate = Path(path).expanduser() if path else Path.cwd()
            resolved = candidate.resolve()
        except (OSError, RuntimeError, TypeError):
            return False

        # Filesystem/drive root, e.g. C:\ or /
        if resolved.parent == resolved:
            return True

        guarded: List[Path] = []
        for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)",
                    "ProgramData"):
            raw = os.environ.get(var)
            if not raw:
                continue
            try:
                guarded.append(Path(raw).resolve())
            except (OSError, RuntimeError):
                continue
        try:
            guarded.append(Path(tempfile.gettempdir()).resolve())
        except (OSError, RuntimeError):
            pass

        for base in guarded:
            if resolved == base or base in resolved.parents:
                return True

        # The home directory itself, but not the projects under it: a checkout in
        # ~/Desktop or ~/code is a perfectly good project root.
        try:
            if resolved == Path.home().resolve():
                return True
        except (OSError, RuntimeError):
            pass

        # A directory that already contains a *registered* project is a container
        # for projects, even though nothing static says so: `D:\work` holding
        # several repos must not become a store just because an agent started
        # there. The registry is read raw to avoid recursing back into this check.
        try:
            known = cls._load_projects_registry()
        except Exception:
            known = {}
        for path_str in known.values():
            try:
                other = Path(path_str).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if other != resolved and resolved in other.parents:
                return True
        return False

    @classmethod
    def require_project_root(
        cls,
        project_root: Optional[str | Path] = None,
        explicit: Optional[bool] = None,
        allow_unmarked: bool = False,
    ) -> Path:
        """Resolve a project root that is safe to *create a store in*.

        ``explicit`` means the caller named this project itself (``--project``,
        ``TACIT_PROJECT``, ``tacit init --dir``); an explicit choice is always
        honoured. Otherwise two things are refused:

        * a **container** directory — home, drive root, system or temp folder, or
          any directory that already holds a registered project — because a store
          there is shared by every workspace underneath it, and
        * a **marker-less** directory — one with no ``.tacit``/``.git``/
          ``pyproject.toml``/``package.json`` — because a store invented there
          becomes an ancestor marker for whatever is later created below it.
          ``allow_unmarked`` exists for the one caller that legitimately creates
          a project: ``tacit init``.
        """
        root = cls.find_project_root(project_root)
        if explicit is None:
            explicit = bool(project_root) or bool(os.environ.get("TACIT_PROJECT", "").strip())
        if explicit:
            return root
        if cls.is_container_dir(root):
            raise ProjectRootError(
                f"'{root}' is not a project: it is a container directory "
                "(home, drive root, system or temp folder).\n"
                "Tacit will not create a memory store there, because every project "
                "below it would then share one store and mix memories.\n"
                "Fix: run `tacit init` inside the repository you are working in, or "
                "point Tacit at it explicitly with `--project <path>` / the "
                "TACIT_PROJECT environment variable."
            )
        if not allow_unmarked and not cls.has_project_marker(root):
            raise ProjectRootError(
                f"'{root}' is not a project: no .tacit, .git, pyproject.toml or "
                "package.json was found here.\n"
                "Tacit will not create a memory store in an unidentified directory, "
                "because it would then be discovered by everything created below it.\n"
                "Fix: cd into the repository, run `tacit init` here if this directory "
                "really is the project, or name one with `--project <path>` / the "
                "TACIT_PROJECT environment variable."
            )
        return root

    @classmethod
    def is_usable_project(cls, path: Optional[str | Path]) -> bool:
        """True when ``path`` exists and may host a store (registry hygiene)."""
        if not path:
            return False
        try:
            candidate = Path(path).expanduser()
        except (OSError, TypeError):
            return False
        if not candidate.exists():
            return False
        if cls.is_container_dir(candidate):
            return False
        return cls.has_project_marker(candidate)

    @classmethod
    def get_memory_dir(cls, project_root: Optional[str | Path] = None) -> Path:
        """Get the memory directory (.tacit) for a specific project.

        The store can be relocated with ``tacit move``; a pointer file left in
        ``<root>/.tacit/location`` records where it went, so the marker directory
        stays in place and project discovery is unaffected.
        """
        root = cls.find_project_root(project_root)
        env_dir = os.getenv("MEMORY_DIR")
        if env_dir and not project_root:
            return Path(env_dir).resolve()
        relocated = cls.read_memory_location(root)
        if relocated is not None:
            return relocated
        return root / cls.DEFAULT_MEMORY_DIR_NAME

    @classmethod
    def read_memory_location(cls, project_root: str | Path) -> Optional[Path]:
        """Resolve the relocation pointer, or ``None`` when the store is default."""
        marker = Path(project_root) / cls.DEFAULT_MEMORY_DIR_NAME
        pointer = marker / cls.MEMORY_LOCATION_FILE
        try:
            raw = pointer.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw or raw.startswith("#"):
            return None
        target = Path(raw).expanduser()
        if not target.is_absolute():
            target = Path(project_root) / target
        try:
            return target.resolve()
        except OSError:
            return target

    @classmethod
    def write_memory_location(cls, project_root: str | Path, memory_dir: str | Path) -> Path:
        """Record where the store now lives, relative to the project root when possible."""
        root = Path(project_root)
        marker = root / cls.DEFAULT_MEMORY_DIR_NAME
        marker.mkdir(parents=True, exist_ok=True)
        pointer = marker / cls.MEMORY_LOCATION_FILE
        target = Path(memory_dir)
        try:
            relative = target.resolve().relative_to(root.resolve())
            text = str(relative).replace("\\", "/")
        except (OSError, ValueError):
            text = str(target.resolve())
        pointer.write_text(text + "\n", encoding="utf-8")
        return pointer

    @classmethod
    def clear_memory_location(cls, project_root: str | Path) -> None:
        """Drop the pointer, returning the project to the default location."""
        pointer = (
            Path(project_root) / cls.DEFAULT_MEMORY_DIR_NAME / cls.MEMORY_LOCATION_FILE
        )
        try:
            pointer.unlink()
        except OSError:
            pass

    @classmethod
    def get_db_path(cls, project_root: Optional[str | Path] = None) -> Path:
        """Get the memory.db path for a specific project."""
        return cls.get_memory_dir(project_root) / "memory.db"

    @classmethod
    def project_root_for_db(cls, db_path: str | Path) -> Path:
        """Infer the project root that owns a database file.

        Needed by readers that only receive a ``MemoryStorage`` (the briefing and
        search engines) and must still know the project's name to recognise
        project-wide scopes. Handles both the default ``<root>/.tacit`` layout and
        a store relocated by ``tacit move``, whose marker directory keeps a
        ``location`` pointer back to it.
        """
        try:
            store_dir = Path(db_path).resolve().parent
        except (OSError, RuntimeError):
            return Path.cwd()
        if store_dir.name == cls.DEFAULT_MEMORY_DIR_NAME:
            return store_dir.parent
        # Relocated store: find the marker directory pointing at it.
        probe = store_dir.parent
        while True:
            marker = probe / cls.DEFAULT_MEMORY_DIR_NAME
            pointer = marker / cls.MEMORY_LOCATION_FILE
            if pointer.exists():
                relocated = cls.read_memory_location(probe)
                if relocated is not None and relocated == store_dir:
                    return probe
            if probe.parent == probe:
                break
            probe = probe.parent
        return store_dir

    @classmethod
    def get_export_dir(cls, project_root: Optional[str | Path] = None) -> Path:
        """Get the memory-export directory for a specific project."""
        root = cls.find_project_root(project_root)
        env_dir = os.getenv("EXPORT_DIR")
        if env_dir and not project_root:
            return Path(env_dir).resolve()
        return root / cls.DEFAULT_EXPORT_DIR_NAME

    @classmethod
    def ensure_directories(
        cls,
        project_root: Optional[str | Path] = None,
        allow_unmarked: bool = False,
    ) -> Path:
        """Create necessary data directories for a given project and register in global index.

        Refuses to invent a store in a container directory (home, drive root,
        system or temp folder) or in an unidentified directory unless the caller
        named that project explicitly: see :class:`ProjectRootError`.
        """
        root = cls.require_project_root(project_root, allow_unmarked=allow_unmarked)
        memory_dir = cls.get_memory_dir(root)
        export_dir = cls.get_export_dir(root)

        memory_dir.mkdir(parents=True, exist_ok=True)
        export_dir.mkdir(parents=True, exist_ok=True)

        for subdir in cls.MEMORY_TYPES:
            (memory_dir / subdir).mkdir(parents=True, exist_ok=True)

        cls.register_project(root)
        return root

    @classmethod
    def _load_projects_registry(cls) -> Dict[str, str]:
        """Loads projects from registry file."""
        if cls.REGISTRY_FILE.exists():
            try:
                return json.loads(cls.REGISTRY_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    @classmethod
    def register_project(cls, project_path: Path) -> None:
        """Register a project root in the global registry for easy multi-project tracking.

        Container directories are never registered: entries like the home
        directory or ``System32`` are pure noise that also make
        ``--project <name>`` lookups resolve to a shared store.
        """
        try:
            resolved = Path(project_path).resolve()
            if not resolved.exists() or cls.is_container_dir(resolved):
                return
            cls.REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            projects = cls._load_projects_registry()

            projects[resolved.name] = str(resolved)
            cls.REGISTRY_FILE.write_text(json.dumps(projects, indent=2), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def list_registered_projects(cls) -> Dict[str, str]:
        """Return all registered projects {name: path}, minus unusable entries.

        Registrations that point at a container directory, a missing path or a
        directory with no project marker are filtered out so stale junk cannot
        be resolved back into a store.
        """
        try:
            raw = cls._load_projects_registry()
        except Exception:
            return {}
        return {
            name: path
            for name, path in raw.items()
            if cls.is_usable_project(path)
        }

    # Backward compatibility properties
    @property
    def MEMORY_DIR(self) -> Path:
        return self.get_memory_dir()

    @property
    def DB_PATH(self) -> Path:
        return self.get_db_path()

    @property
    def EXPORT_DIR(self) -> Path:
        return self.get_export_dir()

    @classmethod
    def check_for_updates(cls) -> Optional[Dict[str, Any]]:
        """Check GitHub releases API (cached for 24h) and return update info if available."""
        import time
        import urllib.request
        from .. import __version__

        cache_path = cls.REGISTRY_FILE.parent / "tacit_update_cache.json"
        now = time.time()

        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if now - data.get("last_checked", 0) < 86400:  # 24 hours
                    latest = data.get("latest_version")
                    if latest and cls._is_newer_version(__version__, latest):
                        return {"current": __version__, "latest": latest, "has_update": True}
                    return {"current": __version__, "latest": latest or __version__, "has_update": False}
            except Exception:
                pass

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(
                "https://api.github.com/repos/AlexLeoTz/tacit/releases/latest",
                headers={"User-Agent": "Tacit-Update-Checker", "Accept": "application/vnd.github.v3+json"},
            )
            with urllib.request.urlopen(req, timeout=1.5) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    latest_tag = payload.get("tag_name", "").lstrip("v")
                    if latest_tag:
                        cache_path.write_text(
                            json.dumps({"last_checked": now, "latest_version": latest_tag}),
                            encoding="utf-8",
                        )
                        has_up = cls._is_newer_version(__version__, latest_tag)
                        return {"current": __version__, "latest": latest_tag, "has_update": has_up}
        except Exception:
            pass

        return {"current": __version__, "latest": __version__, "has_update": False}

    @classmethod
    def _is_newer_version(cls, current: str, latest: str) -> bool:
        """Compare semver strings safely."""
        try:
            cur_parts = [int(p) for p in current.split(".") if p.isdigit()]
            lat_parts = [int(p) for p in latest.split(".") if p.isdigit()]
            return lat_parts > cur_parts
        except Exception:
            return False

