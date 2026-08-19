"""Logging configuration for Project Memory Cortex."""

import logging
from rich.console import Console
from rich.logging import RichHandler

console = Console()


def get_logger(name: str = "project_memory") -> logging.Logger:
    """Get a configured logger with rich formatting."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        rich_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
        )
        rich_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(rich_handler)
    return logger
