"""Configuration and Multi-Project Management for Project Memory Cortex."""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Centralized configuration and multi-project resolver for Memory Cortex."""

    DEFAULT_MEMORY_DIR_NAME = ".project-memory"
    DEFAULT_EXPORT_DIR_NAME = "memory-export"
    REGISTRY_FILE: Path = Path.home() / ".gemini" / "config" / "pmc_projects.json"

    PREVIEW_PORT: int = int(os.getenv("PREVIEW_PORT", "8080"))
    MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "stdio")
    SEARCH_LIMIT: int = int(os.getenv("SEARCH_LIMIT", "50"))

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
        """Get the .project-memory directory for a specific project."""
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
    def register_project(cls, project_path: Path) -> None:
        """Register a project root in the global registry for easy multi-project tracking."""
        try:
            cls.REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            projects: Dict[str, str] = {}
            if cls.REGISTRY_FILE.exists():
                try:
                    projects = json.loads(cls.REGISTRY_FILE.read_text(encoding="utf-8"))
                except Exception:
                    projects = {}

            proj_str = str(project_path.resolve())
            projects[project_path.name] = proj_str
            cls.REGISTRY_FILE.write_text(json.dumps(projects, indent=2), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def list_registered_projects(cls) -> Dict[str, str]:
        """Return all registered projects {name: path}."""
        if not cls.REGISTRY_FILE.exists():
            return {}
        try:
            return json.loads(cls.REGISTRY_FILE.read_text(encoding="utf-8"))
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
