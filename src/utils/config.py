"""Configuration and Multi-Project Management for Project Memory Cortex."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Centralized configuration and multi-project resolver for Tacit (formerly Memory Cortex)."""

    DEFAULT_MEMORY_DIR_NAME = ".tacit"
    DEFAULT_EXPORT_DIR_NAME = "memory-export"
    REGISTRY_FILE: Path = Path.home() / ".gemini" / "config" / "tacit_projects.json"

    PREVIEW_PORT: int = int(os.getenv("PREVIEW_PORT", "4000"))
    PREVIEW_WS_PORT: int = int(os.getenv("PREVIEW_WS_PORT", "4001"))
    MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "stdio")
    SEARCH_LIMIT: int = int(os.getenv("SEARCH_LIMIT", "50"))
    DUAL_WRITE: bool = os.getenv("TACIT_DUAL_WRITE", os.getenv("PMC_DUAL_WRITE", "true")).lower() in ("true", "1", "yes")

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
        """Discover project root by walking upwards on auto-discovery, or using explicit path when provided."""
        if start_path:
            explicit = Path(start_path).resolve()
            if explicit.is_file():
                explicit = explicit.parent
            return explicit

        current = Path.cwd().resolve()
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
        """Get the memory directory (.tacit or legacy .project-memory) for a specific project."""
        root = cls.find_project_root(project_root)
        env_dir = os.getenv("MEMORY_DIR")
        if env_dir and not project_root:
            return Path(env_dir).resolve()
        
        # Check if legacy .project-memory exists first, to ensure backwards compatibility
        legacy_dir = root / ".project-memory"
        if legacy_dir.exists() and not (root / cls.DEFAULT_MEMORY_DIR_NAME).exists():
            return legacy_dir
            
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
        """Loads projects with fallback to legacy pmc_projects.json"""
        if cls.REGISTRY_FILE.exists():
            try:
                return json.loads(cls.REGISTRY_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        
        legacy_file = cls.REGISTRY_FILE.parent / "pmc_projects.json"
        if legacy_file.exists():
            try:
                data = json.loads(legacy_file.read_text(encoding="utf-8"))
                # Migrate to the new registry file
                cls.REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
                cls.REGISTRY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return data
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
        if not cache_path.exists():
            legacy_cache = cls.REGISTRY_FILE.parent / "pmc_update_cache.json"
            if legacy_cache.exists():
                try:
                    legacy_cache.rename(cache_path)
                except Exception:
                    pass

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
                "https://api.github.com/repos/AlexLeoTz/project-memory-cortext/releases/latest",
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

