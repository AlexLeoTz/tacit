from setuptools import setup, find_packages

setup(
    name="tacit",
    version="0.1.0",
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
    ],
    entry_points={
        "console_scripts": [
            "tacit=src.cli.main:app",
            "pmc=src.cli.main:app",
            "project-memory=src.cli.main:app",
        ],
    },
)
