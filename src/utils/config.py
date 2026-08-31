"""Configuration and Multi-Project Management for Tacit."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Centralized configuration and multi-project resolver for Tacit."""

    DEFAULT_MEMORY_DIR_NAME = ".tacit"
    DEFAULT_EXPORT_DIR_NAME = "memory-export"
    REGISTRY_FILE: Path = Path.home() / ".gemini" / "config" / "tacit_projects.json"

    PREVIEW_PORT: int = int(os.getenv("PREVIEW_PORT", "4000"))
    PREVIEW_WS_PORT: int = int(os.getenv("PREVIEW_WS_PORT", "4001"))
    MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "stdio")
    SEARCH_LIMIT: int = int(os.getenv("SEARCH_LIMIT", "50"))
    TOKEN_BUDGET: int = int(os.getenv("TACIT_TOKEN_BUDGET", "2000"))
    DUAL_WRITE: bool = os.getenv("TACIT_DUAL_WRITE", "true").lower() in ("true", "1", "yes")

    MEMORY_TYPES = [
        "decision",
        "command",
        "hack",
        "architecture",
        "error",
        "context",
    ]

    @classmethod
    def find_project_root(cls, start_path: Optional[str | Path] = None) -> Path:
        """Discover project root by walking upwards on auto-discovery, or using explicit path/name when provided."""
        current = Path.cwd().resolve()

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

    @classmethod
    def get_memory_dir(cls, project_root: Optional[str | Path] = None) -> Path:
        """Get the memory directory (.tacit) for a specific project."""
        root = cls.find_project_root(project_root)
        env_dir = os.getenv("MEMORY_DIR")
        if env_dir and not project_root:
            return Path(env_dir).resolve()
        return root / cls.DEFAULT_MEMORY_DIR_NAME

    @classmethod
    def get_db_path(cls, project_root: Optional[str | Path] = None) -> Path:
        """Get the memory.db path for a specific project."""
        return cls.get_memory_dir(project_root) / "memory.db"

    @classmethod
    def get_export_dir(cls, project_root: Optional[str | Path] = None) -> Path:
        """Get the memory-export directory for a specific project."""
        root = cls.find_project_root(project_root)
        env_dir = os.getenv("EXPORT_DIR")
        if env_dir and not project_root:
            return Path(env_dir).resolve()
        return root / cls.DEFAULT_EXPORT_DIR_NAME

    @classmethod
    def ensure_directories(cls, project_root: Optional[str | Path] = None) -> Path:
        """Create necessary data directories for a given project and register in global index."""
        memory_dir = cls.get_memory_dir(project_root)
        export_dir = cls.get_export_dir(project_root)

        memory_dir.mkdir(parents=True, exist_ok=True)
        export_dir.mkdir(parents=True, exist_ok=True)

        for subdir in cls.MEMORY_TYPES:
            (memory_dir / subdir).mkdir(parents=True, exist_ok=True)

        root = memory_dir.parent
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
        """Register a project root in the global registry for easy multi-project tracking."""
        try:
            cls.REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            projects = cls._load_projects_registry()

            proj_str = str(project_path.resolve())
            projects[project_path.name] = proj_str
            cls.REGISTRY_FILE.write_text(json.dumps(projects, indent=2), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def list_registered_projects(cls) -> Dict[str, str]:
        """Return all registered projects {name: path}."""
        try:
            return cls._load_projects_registry()
        except Exception:
            return {}

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

