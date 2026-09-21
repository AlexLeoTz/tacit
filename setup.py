import re
from pathlib import Path

from setuptools import find_packages, setup

#: Single source of truth for the version — keep it in ``src/__init__.py`` only,
#: so the update banner (`Config.check_for_updates`) and the installed package
#: can never disagree.
_INIT = Path(__file__).parent / "src" / "__init__.py"
_VERSION = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']', _INIT.read_text(encoding="utf-8"), re.MULTILINE
).group(1)

setup(
    name="tacit",
    version=_VERSION,
    description="Persistent, immutable project memory and tacit knowledge layer for AI coding agents",
    author="Tacit Contributors",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "typer>=0.9.0",
        "rich>=13.0.0",
        "pydantic>=2.0.0",
        "mcp>=0.1.0",
        "websockets>=12.0",
        "markdown>=3.5.0",
        "python-dotenv>=1.0.0",
        "watchdog>=3.0.0",
        "fastembed>=0.4.0",
        "numpy>=1.24.0",
    ],
    entry_points={
        "console_scripts": [
            "tacit=src.cli.main:app",
        ],
    },
)
