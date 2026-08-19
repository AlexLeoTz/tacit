from setuptools import setup, find_packages

setup(
    name="project-memory-cortex",
    version="0.1.0",
    description="Persistent, immutable project memory cortex for AI coding agents",
    author="Project Memory Cortex Contributors",
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
            "pmc=src.cli.main:app",
            "project-memory=src.cli.main:app",
        ],
    },
)
