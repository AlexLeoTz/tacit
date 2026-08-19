"""Command-Line Interface (CLI) for Project Memory Cortex with Multi-Project Support."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import uuid

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
import typer

from ..core.memory_node import MemoryNode
from ..core.storage import MemoryStorage
from ..export.markdown_exporter import MarkdownExporter
from ..export.preview_server import MarkdownPreviewServer
from ..mcp.server import MemoryMCPServer
from ..utils.config import Config

app = typer.Typer(
    name="pmc",
    help="Project Memory Cortex - Persistent institutional memory for AI coding agents.",
    add_completion=False,
)
console = Console()


@app.callback()
def main_callback(ctx: typer.Context):
    """Global callback executed before any CLI command."""
    # Don't show update banner if developer is already running `pmc update` or `pmc mcp`
    if ctx.invoked_subcommand not in ("update", "mcp"):
        try:
            update_info = Config.check_for_updates()
            if update_info and update_info.get("has_update"):
                console.print(
                    Panel.fit(
                        f"[yellow]Update available:[/yellow] [dim]v{update_info['current']}[/dim] -> [bold green]v{update_info['latest']}[/bold green]\n"
                        f"Run [bold cyan]pmc update[/bold cyan] to upgrade globally.",
                        border_style="yellow",
                        padding=(0, 2),
                    )
                )
        except Exception:
            pass



def get_storage(project: Optional[str] = None) -> MemoryStorage:
    """Helper to initialize storage for target or current project root."""
    if project:
        registered = Config.list_registered_projects()
        target_path = registered.get(project, project)
        root = Config.find_project_root(target_path)
    else:
        root = Config.find_project_root()

    Config.ensure_directories(root)
    return MemoryStorage(Config.get_db_path(root))


@app.command()
def init(
    directory: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Custom project directory for memory storage"
    )
):
    """Initialize project memory database and directories for the current (or specified) project."""
    target_root = Config.find_project_root(directory)
    Config.ensure_directories(target_root)
    db_path = Config.get_db_path(target_root)
    storage = MemoryStorage(db_path)
    count = storage.get_count()

    # Automatically generate agent rules for Antigravity, Cursor, and Claude
    rule_content = """# Project Memory Rules

Whenever you make key architectural decisions, discover bugs, fix tricky errors, or execute critical deploy/setup commands in this project:
1. **Record key decisions**: Call `memory_add` with type `decision`, `architecture`, `hack`, `command`, or `error`.
2. **Context on session start**: Call `memory_context` to recall institutional memory and past design decisions.
"""
    # 1. Antigravity rule
    agy_rule = target_root / ".agents" / "rules" / "project_memory.md"
    agy_rule.parent.mkdir(parents=True, exist_ok=True)
    if not agy_rule.exists():
        agy_rule.write_text(f"---\ntrigger: always_on\ndescription: Institutional memory guideline using Project Memory Cortex\n---\n\n{rule_content}", encoding="utf-8")

    # 2. Cursor rules
    cursor_rule = target_root / ".cursorrules"
    if not cursor_rule.exists():
        cursor_rule.write_text(rule_content, encoding="utf-8")

    console.print(
        Panel.fit(
            f"[bold green]Project Memory Cortex Initialized[/bold green]\n"
            f"[dim]Project Root:[/dim] {target_root.resolve()}\n"
            f"[dim]Storage Dir:[/dim]  {Config.get_memory_dir(target_root).resolve()}\n"
            f"[dim]Database:[/dim]     {db_path.resolve()}\n"
            f"[dim]Total Memories:[/dim] {count}\n"
            f"[cyan]Auto-created AI agent rules in `.agents/rules/` and `.cursorrules`[/cyan]",
            border_style="green",
        )
    )



@app.command()
def remember(
    content: str = typer.Argument(..., help="Detailed content of the memory entry"),
    type: str = typer.Option("decision", "--type", "-t", help="Memory type (decision, command, hack, architecture, error, context)"),
    summary: str = typer.Option("", "--summary", "-s", help="Concise summary (auto-generated if omitted)"),
    title: str = typer.Option("", "--title", help="Title for the memory node"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags (e.g. 'auth,jwt,security')"),
    scope: str = typer.Option("", "--scope", help="Comma-separated scope paths"),
    impact: str = typer.Option("medium", "--impact", "-i", help="Impact level: high, medium, low"),
    parents: str = typer.Option("", "--parents", "-p", help="Comma-separated parent memory IDs"),
    author: str = typer.Option("user", "--author", "-a", help="Author tag"),
    project: Optional[str] = typer.Option(None, "--project", help="Target project name or directory path"),
):
    """Add a new persistent memory entry."""
    storage = get_storage(project)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    scope_list = [s.strip() for s in scope.split(",") if s.strip()]
    parent_list = [p.strip() for p in parents.split(",") if p.strip()]

    node = MemoryNode(
        id=str(uuid.uuid4()),
        timestamp=datetime.now().astimezone().timestamp(),
        content=content,
        summary=summary,
        title=title,
        type=type.lower(),
        tags=tag_list,
        scope=scope_list,
        impact=impact.lower(),
        parents=parent_list,
        author=author,
    )

    success = storage.add_memory(node)
    if success:
        proj_label = f" [cyan]({project})[/cyan]" if project else ""
        console.print(f"[bold green]Recorded [{node.type.upper()}]:[/bold green]{proj_label} {node.summary}")
        console.print(f"[dim]ID:[/dim] {node.id}")
        console.print(f"[dim]Content Hash:[/dim] {node.content_hash[:16]}...")
    else:
        console.print("[bold red]Failed to store memory: duplicate or database integrity error.[/bold red]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by memory type"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results to display"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Search stored memories using full-text search."""
    storage = get_storage(project)
    results = storage.search_full_text(query=query, limit=limit, memory_type=type)

    if not results:
        proj_hint = f" in project '{project}'" if project else ""
        console.print(f"[yellow]No memory entries found matching '{query}'{proj_hint}.[/yellow]")
        return

    table = Table(title=f"Search Results for '{query}' ({len(results)} found)", show_header=True, header_style="bold cyan")
    table.add_column("Date", style="dim", width=18)
    table.add_column("Type", style="magenta", width=12)
    table.add_column("Summary", style="white")
    table.add_column("Tags", style="cyan")
    table.add_column("ID", style="dim", width=10)

    for node in results:
        date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M")
        tags_str = ", ".join(node.tags) if node.tags else ""
        table.add_row(
            date_str,
            f"[{node.type}]",
            node.summary,
            tags_str,
            node.id[:8],
        )

    console.print(table)


@app.command()
def get(
    node_id: str = typer.Argument(..., help="Memory node ID (or prefix)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Get full details of a specific memory entry."""
    storage = get_storage(project)

    node = storage.get_memory(node_id)
    if not node:
        # Search by prefix if exact match not found
        all_memories = storage.get_all(limit=1000)
        matches = [m for m in all_memories if m.id.startswith(node_id)]
        if len(matches) == 1:
            node = matches[0]
        elif len(matches) > 1:
            console.print(f"[yellow]Multiple matches found for prefix '{node_id}'. Please specify full UUID.[/yellow]")
            return

    if not node:
        console.print(f"[red]Memory entry '{node_id}' not found.[/red]")
        return

    exporter = MarkdownExporter(storage)
    md_content = exporter.format_node_markdown(node)
    console.print(Panel(md_content, title=f"Memory Node: {node.id}", border_style="cyan"))


@app.command()
def recent(
    days: int = typer.Option(7, "--days", "-d", help="Number of past days to query"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results to return"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by memory type"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """List recent memories for the current or specified project."""
    storage = get_storage(project)
    cutoff = datetime.now().astimezone().timestamp() - (days * 86400)
    memories = storage.get_since(cutoff)
    if type:
        memories = [m for m in memories if m.type == type]
    memories = sorted(memories, key=lambda m: m.timestamp, reverse=True)[:limit]

    if not memories:
        console.print(f"[yellow]No memories found in the last {days} days.[/yellow]")
        return

    table = Table(title=f"Recent Memories (Last {days} Days)", show_header=True, header_style="bold blue")
    table.add_column("Date", style="dim", width=18)
    table.add_column("Type", style="magenta", width=12)
    table.add_column("Title / Summary", style="white")
    table.add_column("ID", style="dim", width=10)

    for node in memories:
        date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M")
        table.add_row(
            date_str,
            f"[{node.type}]",
            node.title or node.summary,
            node.id[:8],
        )

    console.print(table)


@app.command()
def export(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output directory for markdown files"),
    preview: bool = typer.Option(False, "--preview", help="Launch live preview server after exporting"),
    port: int = typer.Option(4000, "--port", help="Port for preview HTTP server if --preview is set"),
    ws_port: Optional[int] = typer.Option(None, "--ws-port", help="Port for preview WebSocket server (defaults to 4001 or next available)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Export stored memories to categorized Markdown files and generate INDEX.md."""
    storage = get_storage(project)
    exporter = MarkdownExporter(storage)

    if output:
        out_dir = Path(output)
    else:
        root = Config.find_project_root(project)
        out_dir = Config.get_export_dir(root)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Exporting memories to markdown...", total=None)
        summary = exporter.export_all(out_dir)
        progress.update(task, completed=True)

    console.print(
        Panel.fit(
            f"[bold green]Export Complete[/bold green]\n"
            f"[dim]Output Directory:[/dim] {summary.export_directory.resolve()}\n"
            f"[dim]Total Memories:[/dim]   {summary.total_memories}\n"
            f"[dim]Files Created:[/dim]    {summary.total_files}",
            border_style="green",
        )
    )

    if preview:
        server = MarkdownPreviewServer(storage, out_dir, port=port, ws_port=ws_port)
        server.start(block=True)



@app.command()
def serve(
    port: int = typer.Option(4000, "--port", help="Port for preview HTTP server"),
    ws_port: Optional[int] = typer.Option(None, "--ws-port", help="Port for preview WebSocket server (defaults to 4001 or next available)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Directory for exported documentation"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Start real-time Markdown preview server with WebSocket live-reload."""
    storage = get_storage(project)
    root = Config.find_project_root(project)
    out_dir = Path(output) if output else Config.get_export_dir(root)
    server = MarkdownPreviewServer(storage, out_dir, port=port, ws_port=ws_port)
    server.start(block=True)


@app.command(name="dashboard")
def dashboard(
    port: int = typer.Option(4000, "--port", help="Port for preview and dashboard server"),
    ws_port: Optional[int] = typer.Option(None, "--ws-port", help="Port for preview WebSocket server (defaults to 4001 or next available)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Directory for exported documentation"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
    open_browser: bool = typer.Option(False, "--open", help="Automatically open dashboard in default browser"),
):
    """Start visual Project Memory Dashboard web interface with multi-project support and live-reload."""
    storage = get_storage(project)
    root = Config.find_project_root(project)
    out_dir = Path(output) if output else Config.get_export_dir(root)

    server = MarkdownPreviewServer(storage, out_dir, port=port, ws_port=ws_port)
    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    server.start(block=True)


@app.command()
def projects():
    """List all registered and discovered projects on this machine."""
    registered = Config.list_registered_projects()
    current_root = Config.find_project_root()
    registered[current_root.name] = str(current_root.resolve())

    table = Table(title="Registered Projects (Project Memory Cortex)", show_header=True, header_style="bold green")
    table.add_column("Project", style="cyan", width=24)
    table.add_column("Path", style="dim")
    table.add_column("Memories", style="magenta", justify="right", width=10)
    table.add_column("Status", style="green", width=10)

    for name, path_str in sorted(registered.items()):
        root = Path(path_str)
        db_path = Config.get_db_path(root)
        count = 0
        if db_path.exists():
            try:
                s = MemoryStorage(db_path)
                count = s.get_count()
            except Exception:
                count = 0
        is_active = (root == current_root)
        table.add_row(
            name,
            path_str,
            str(count),
            "[bold green]Active[/bold green]" if is_active else "[dim]Saved[/dim]",
        )

    console.print(table)


@app.command()
def delete(
    node_id: str = typer.Argument(..., help="Memory node ID to delete"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Delete a specific project memory node with confirmation."""
    storage = get_storage(project)
    node = storage.get_memory(node_id)

    if not node:
        # Search by prefix
        all_memories = storage.get_all(limit=1000)
        matches = [m for m in all_memories if m.id.startswith(node_id)]
        if len(matches) == 1:
            node = matches[0]
            node_id = node.id
        elif len(matches) > 1:
            console.print(f"[yellow]Multiple memories matched prefix '{node_id}'. Please specify full UUID.[/yellow]")
            return
        else:
            console.print(f"[red]Memory entry '{node_id}' not found.[/red]")
            return

    console.print(f"[yellow]Target Memory:[/yellow] [{node.type}] {node.summary} ([dim]{node.id}[/dim])")

    if not yes:
        confirm = typer.confirm("Are you sure you want to permanently delete this memory node?")
        if not confirm:
            console.print("[dim]Operation canceled.[/dim]")
            return

    deleted = storage.delete_memory(node_id)
    if deleted:
        console.print(f"[bold green]Successfully deleted memory node {node_id}.[/bold green]")
    else:
        console.print(f"[bold red]Failed to delete memory node {node_id}.[/bold red]")


@app.command()
def clear(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Clear all memories from a project database with confirmation."""
    root = Config.find_project_root(project)
    storage = get_storage(project)
    count = storage.get_count()

    if count == 0:
        console.print(f"[yellow]No memories stored in project '{root.name}'.[/yellow]")
        return

    console.print(f"[bold red]WARNING:[/bold red] This will delete all [bold]{count}[/bold] memories from project '[cyan]{root.name}[/cyan]' ({root.resolve()}).")

    if not yes:
        confirm = typer.confirm("Are you ABSOLUTELY sure you want to delete all project memories?")
        if not confirm:
            console.print("[dim]Operation canceled.[/dim]")
            return

    cleared = storage.clear_all_memories()
    console.print(f"[bold green]Cleared {cleared} memories from project storage.[/bold green]")


@app.command()
def mcp(
    transport: str = typer.Option("stdio", "--transport", "-t", help="MCP transport mode (stdio)"),
):
    """Run Model Context Protocol (MCP) server for AI coding agents."""
    server = MemoryMCPServer()
    server.run(transport=transport)


@app.command(name="install-mcp")
def install_mcp(
    client: str = typer.Option("claude", "--client", "-c", help="Target client: claude, cursor, or print"),
):
    """Automatically configure Claude Desktop, Cursor, or print the MCP config snippet for global usage."""
    import os
    import sys

    config_entry = {
        "command": "pmc",
        "args": ["mcp"]
    }

    if client.lower() == "print":
        console.print(Panel(
            json.dumps({"mcpServers": {"project-memory": config_entry}}, indent=2),
            title="MCP Configuration Snippet",
            border_style="cyan"
        ))
        return

    if client.lower() in ("antigravity", "agy", "gemini"):
        config_path = Path.home() / ".gemini" / "config" / "mcp_config.json"
    elif client.lower() == "claude":
        if sys.platform == "win32":
            config_path = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
        elif sys.platform == "darwin":
            config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        else:
            config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    elif client.lower() == "cursor":
        if sys.platform == "win32":
            config_path = Path(os.environ.get("APPDATA", "")) / "Cursor" / "User" / "globalStorage" / "cursor_desktop_config.json"
        elif sys.platform == "darwin":
            config_path = Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "cursor_desktop_config.json"
        else:
            config_path = Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "cursor_desktop_config.json"
    else:
        console.print(f"[red]Unknown client '{client}'. Supported options: antigravity, agy, claude, cursor, print.[/red]")
        return

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        existing_data = {}
        if config_path.exists():
            try:
                existing_data = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                existing_data = {}

        if "mcpServers" not in existing_data:
            existing_data["mcpServers"] = {}

        existing_data["mcpServers"]["project-memory"] = config_entry
        config_path.write_text(json.dumps(existing_data, indent=2), encoding="utf-8")

        console.print(Panel.fit(
            f"[bold green]MCP Server Configured Successfully[/bold green]\n"
            f"[dim]Client:[/dim]  {client.capitalize()}\n"
            f"[dim]Config:[/dim]  {config_path.resolve()}\n\n"
            f"[cyan]The 'pmc mcp' server is now globally registered for all projects.[/cyan]",
            border_style="green",
        ))
    except Exception as e:
        console.print(f"[red]Failed to write config automatically: {e}[/red]")
        console.print("[yellow]You can manually add this to your MCP configuration:[/yellow]")
        console.print(json.dumps({"mcpServers": {"project-memory": config_entry}}, indent=2))


@app.command()
def update(
    git_url: str = typer.Option("https://github.com/AlexLeoTz/project-memory-cortext.git", "--url", help="Git repository URL to update from"),
):
    """Update PMC globally to the latest version from GitHub and refresh project rules in the current directory."""
    import subprocess
    import sys

    console.print("[cyan]Updating Project Memory Cortex (PMC) globally...[/cyan]")
    pip_target = f"git+{git_url}"

    try:
        # 1. Update the global python package via pip with force-reinstall
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-deps", pip_target]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            # Fallback if in local git repo directory
            current_root = Config.find_project_root()
            if (current_root / "setup.py").exists():
                console.print("[yellow]Remote pip install returned error, upgrading via local editable mode...[/yellow]")
                subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=current_root, check=False)
            else:
                console.print(f"[red]Update failed: {result.stderr}[/red]")
                return

        # 2. Refresh rules in current workspace
        current_root = Config.find_project_root()
        rule_content = """# Project Memory Rules

Whenever you make key architectural decisions, discover bugs, fix tricky errors, or execute critical deploy/setup commands in this project:
1. **Record key decisions**: Call `memory_add` with type `decision`, `architecture`, `hack`, `command`, or `error`.
2. **Context on session start**: Call `memory_context` to recall institutional memory and past design decisions.
"""
        agy_rule = current_root / ".agents" / "rules" / "project_memory.md"
        if agy_rule.exists() or (current_root / ".agents").exists():
            agy_rule.parent.mkdir(parents=True, exist_ok=True)
            agy_rule.write_text(f"---\ntrigger: always_on\ndescription: Institutional memory guideline using Project Memory Cortex\n---\n\n{rule_content}", encoding="utf-8")

        cursor_rule = current_root / ".cursorrules"
        if cursor_rule.exists():
            cursor_rule.write_text(rule_content, encoding="utf-8")

        console.print(Panel.fit(
            f"[bold green]Project Memory Cortex Successfully Updated![/bold green]\n"
            f"[dim]Version Source:[/dim] {git_url}\n"
            f"[dim]Active Project:[/dim] {current_root.resolve()}\n\n"
            f"[cyan]Global 'pmc' CLI and local workspace rules are up to date.[/cyan]",
            border_style="green",
        ))

    except Exception as e:
        console.print(f"[bold red]Failed to update PMC: {e}[/bold red]")


if __name__ == "__main__":
    app()



