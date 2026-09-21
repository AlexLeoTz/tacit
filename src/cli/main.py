"""Command-Line Interface (CLI) for Tacit with Multi-Project Support."""

import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid
import yaml

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
import typer

from .. import __version__
from ..core.agent_rules import AGENT_RULE_CONTENT
from ..core.memory_node import MemoryNode
from ..core.storage import MemoryStorage
from ..export.markdown_exporter import MarkdownExporter
from ..export.preview_server import MarkdownPreviewServer
from ..mcp.server import MemoryMCPServer
from ..utils import updater
from ..utils.config import Config

app = typer.Typer(
    name="tacit",
    help="Tacit - Persistent, immutable institutional memory and tacit knowledge layer for AI coding agents.",
    add_completion=False,
)
console = Console()


def _make_output_encoding_safe() -> None:
    """Stop Rich from crashing on box-drawing characters in a legacy console.

    `tacit briefing` renders a `════` header. On a Windows console using a legacy
    code page (cp1252) that string cannot be encoded, so printing a briefing
    raised UnicodeEncodeError instead of showing it. Replacing unencodable
    characters is strictly better than refusing to print.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def _esc(value: object) -> str:
    """Escape dynamic text for Rich markup.

    Memory types and agent-written titles routinely contain square brackets —
    `[decision]`, `[WinError 32] …` — which Rich otherwise parses as style tags
    and silently deletes from the output.
    """
    return escape(str(value))


_make_output_encoding_safe()


def _version_callback(value: bool) -> None:
    """Handle the eager ``--version`` flag (referenced by `tacit update` and the docs)."""
    if value:
        console.print(f"[bold cyan]tacit[/bold cyan] [green]{__version__}[/green]")
        # Where the code actually came from: an editable install pins the CLI to
        # the directory it was installed from, so this is the fastest way to
        # notice that an unrelated clone is being executed instead.
        console.print(f"[dim]{updater.package_parent_dir()}[/dim]")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the Tacit version and exit.",
    ),
):
    """Global callback executed before any CLI command."""
    # Don't show update banner if developer is already running `tacit update` or `tacit mcp`
    if ctx.invoked_subcommand not in ("update", "mcp"):
        try:
            update_info = Config.check_for_updates()
            if update_info and update_info.get("has_update"):
                console.print(
                    Panel.fit(
                        f"[yellow]Update available:[/yellow] [dim]v{update_info['current']}[/dim] -> [bold green]v{update_info['latest']}[/bold green]\n"
                        f"Run [bold cyan]tacit update[/bold cyan] to upgrade globally.",
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
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force overwrite existing rule files"
    ),
):
    """Initialize project memory database and directories for the current (or specified) project."""
    target_root = Config.find_project_root(directory)
    Config.ensure_directories(target_root)
    db_path = Config.get_db_path(target_root)
    storage = MemoryStorage(db_path)
    count = storage.get_count()

    # Automatically generate agent rules for Antigravity, Cursor, and Claude
    rule_content = AGENT_RULE_CONTENT
    # 1. Antigravity rule
    agy_rule = target_root / ".agents" / "rules" / "tacit.md"
    agy_rule.parent.mkdir(parents=True, exist_ok=True)
    if force or not agy_rule.exists():
        agy_rule.write_text(f"---\ntrigger: always_on\ndescription: Institutional memory guideline using Tacit\n---\n\n{rule_content}", encoding="utf-8")

    # 2. Cursor rules
    cursor_rule = target_root / ".cursorrules"
    if force or not cursor_rule.exists():
        cursor_rule.write_text(rule_content, encoding="utf-8")

    # 3. Check for GEMINI_API_KEY and configure embedding preferences
    gemini_key = os.environ.get("GEMINI_API_KEY")
    env_file = target_root / ".env"
    if not gemini_key and env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("GEMINI_API_KEY="):
                    gemini_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass

    embed_provider_msg = "[cyan]Embedding Engine:[/cyan] [bold]Local CPU ONNX (bge-small-en-v1.5)[/bold]"
    if gemini_key:
        try:
            use_gemini = typer.confirm(
                "\nDetected GEMINI_API_KEY. Would you like Tacit to use Google Gemini for high-precision embeddings? (Selecting 'no' will use local CPU ONNX model)",
                default=True,
            )
            if use_gemini:
                embed_provider_msg = "[cyan]Embedding Engine:[/cyan] [bold green]Google Gemini (gemini-embedding-001)[/bold green]"
            else:
                os.environ.pop("GEMINI_API_KEY", None)
                embed_provider_msg = "[cyan]Embedding Engine:[/cyan] [bold]Local CPU ONNX (bge-small-en-v1.5)[/bold] [dim](Gemini declined)[/dim]"
        except Exception:
            embed_provider_msg = "[cyan]Embedding Engine:[/cyan] [bold green]Google Gemini (gemini-embedding-001)[/bold green]"

    console.print(
        Panel.fit(
            f"[bold green]Tacit Initialized[/bold green]\n"
            f"[dim]Project Root:[/dim] {target_root.resolve()}\n"
            f"[dim]Storage Dir:[/dim]  {Config.get_memory_dir(target_root).resolve()}\n"
            f"[dim]Database:[/dim]     {db_path.resolve()}\n"
            f"[dim]Total Memories:[/dim] {count}\n"
            f"{embed_provider_msg}\n"
            f"[cyan]Auto-created AI agent rules in `.agents/rules/` and `.cursorrules`[/cyan]",
            border_style="green",
        )
    )




@app.command()
def remember(
    content: str = typer.Argument(..., help="Detailed content of the memory entry"),
    type: str = typer.Option(
        Config.DEFAULT_MEMORY_TYPE,
        "--type",
        "-t",
        help=f"Memory category. One of: {', '.join(Config.MEMORY_TYPES)}",
    ),
    summary: str = typer.Option("", "--summary", "-s", help="Concise summary (auto-generated if omitted)"),
    title: str = typer.Option("", "--title", help="Title for the memory node"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags (e.g. 'auth,jwt,security')"),
    scope: str = typer.Option("", "--scope", help="Comma-separated scope paths"),
    impact: str = typer.Option("medium", "--impact", "-i", help="Impact level: high, medium, low"),
    parents: str = typer.Option("", "--parents", "-p", help="Comma-separated parent memory IDs"),
    supersedes: str = typer.Option("", "--supersedes", help="Comma-separated memory IDs superseded by this entry"),
    relation_note: str = typer.Option("", "--relation-note", help="Reason for superseding/deriving"),
    author: str = typer.Option("user", "--author", "-a", help="Author tag"),
    project: Optional[str] = typer.Option(None, "--project", help="Target project name or directory path"),
):
    """Add a new persistent memory entry."""
    storage = get_storage(project)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    scope_list = [s.strip() for s in scope.split(",") if s.strip()]
    parent_list = [p.strip() for p in parents.split(",") if p.strip()]
    supersede_list = [s.strip() for s in supersedes.split(",") if s.strip()]

    # Validate scope paths exist in target project root
    from ..core.memory_node import validate_scope_paths
    validate_scope_paths(scope_list, project)

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

    success = storage.add_memory(
        node,
        supersedes=supersede_list if supersede_list else None,
        relation_reason=relation_note if relation_note else None,
    )
    if success:
        proj_label = f" [cyan]({project})[/cyan]" if project else ""
        sup_label = f" [yellow](Supersedes: {', '.join(supersede_list)})[/yellow]" if supersede_list else ""
        console.print(f"[bold green]Recorded [{node.type.upper()}]:[/bold green]{proj_label}{sup_label} {node.summary}")
        console.print(f"[dim]ID:[/dim] {node.id}")
        console.print(f"[dim]Content Hash:[/dim] {node.content_hash[:16]}...")
    else:
        console.print("[bold red]Failed to store memory: duplicate or database integrity error.[/bold red]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by memory type"),
    mode: str = typer.Option("hybrid", "--mode", "-m", help="Search mode: hybrid or keyword"),
    scope: Optional[str] = typer.Option(None, "--scope", help="Comma-separated scope path hints"),
    all_status: bool = typer.Option(False, "--all-status", "--include-superseded", help="Include superseded memories"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Display BM25/vector rank provenance"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results to display"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Search stored memories using hybrid BM25 / dense vector search with RRF fusion."""
    storage = get_storage(project)
    scope_list = [s.strip() for s in scope.split(",") if s.strip()] if scope else None

    results = storage.search_hybrid(
        query=query,
        limit=limit,
        mode=mode,
        scope_hint=scope_list,
        memory_type=type,
        include_superseded=all_status,
        debug=debug,
    )

    if not results:
        proj_hint = f" in project '{project}'" if project else ""
        console.print(f"[yellow]No memory entries found matching '{query}'{proj_hint}.[/yellow]")
        return

    table = Table(title=f"Search Results for '{query}' ({len(results)} found, mode={mode})", show_header=True, header_style="bold cyan")
    table.add_column("Date", style="dim", width=16)
    table.add_column("Type", style="magenta", width=10)
    table.add_column("Score", style="green", width=7)
    table.add_column("Summary", style="white", min_width=25)
    table.add_column("Tags", style="cyan", width=12)
    table.add_column("ID", style="dim", width=9)

    for item in results:
        node = item["node"]
        score = item.get("score", 0.0)
        date_str = datetime.fromtimestamp(node.timestamp).astimezone().strftime("%Y-%m-%d %H:%M")
        tags_str = ", ".join(node.tags) if node.tags else ""
        status_flag = f" [{node.status.upper()}]" if node.status != "active" else ""
        table.add_row(
            date_str,
            _esc(f"[{node.type}]{status_flag}"),
            f"{score:.3f}",
            _esc(node.title or node.summary),
            _esc(tags_str),
            node.id[:8],
        )

    console.print(table)


@app.command()
def reindex(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Rebuild every vector, required after switching embedding provider",
    ),
):
    """Backfill missing dense vector embeddings across all memories in the project database."""
    from ..search.embeddings import EmbeddingService

    storage = get_storage(project)
    embed_svc = EmbeddingService.get()
    console.print(f"[dim]Embedding provider:[/dim] {embed_svc.describe()}")

    if not embed_svc.available:
        console.print(Panel.fit(
            "[bold red]No embedding provider available[/bold red]\n\n"
            "Semantic search is disabled; queries fall back to keyword matching only.\n\n"
            "Set [bold cyan]OPENAI_API_KEY[/bold cyan] or [bold cyan]GEMINI_API_KEY[/bold cyan], "
            "or install the offline model with [bold]pip install fastembed[/bold].",
            border_style="red",
        ))
        raise typer.Exit(code=1)

    stale = storage.count_stale_embeddings()
    if stale and not force:
        console.print(Panel.fit(
            f"[yellow]{stale} memories were embedded with a different model.[/yellow]\n"
            "Their vectors cannot be compared with the current provider, so they are\n"
            "skipped by semantic search. Rebuild them with:\n\n"
            "[bold cyan]tacit reindex --force[/bold cyan]",
            border_style="yellow",
        ))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Embedding memory entries via {embed_svc.provider}...", total=None)
        done, total = storage.reindex_all(progress=False, force=force)
        progress.advance(task)

    if total == 0:
        console.print("[green]All memory entries are already indexed with dense vector embeddings.[/green]")
    else:
        console.print(f"[bold green]Successfully embedded {done}/{total} memories into vector storage.[/bold green]")


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
            _esc(f"[{node.type}]"),
            _esc(node.title or node.summary),
            node.id[:8],
        )

    console.print(table)


@app.command(name="tree")
def tree(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Visualize the full causal decision tree (DAG) for the project."""
    from rich.tree import Tree
    from ..core.memory_dag import MemoryDAG

    storage = get_storage(project)
    nodes = storage.get_all(limit=500)
    if not nodes:
        console.print("[yellow]No memories recorded in this project yet.[/yellow]")
        return

    # Build DAG
    dag = MemoryDAG()
    for n in sorted(nodes, key=lambda x: x.timestamp):
        try:
            dag.add_node(n)
        except Exception:
            pass

    # Root nodes are nodes with no parents
    root_nodes = [n for n in nodes if not n.parents]
    if not root_nodes:
        root_nodes = nodes[:1]

    root_tree = Tree(f"[bold cyan]Project Memory DAG[/bold cyan] ({len(nodes)} total nodes)")

    def add_children(tree_branch, node_id, visited=None):
        if visited is None:
            visited = set()
        if node_id in visited:
            return
        visited.add(node_id)
        children_ids = dag.edges.get(node_id, set())
        for cid in sorted(children_ids):
            child_node = dag.get_node(cid)
            if child_node:
                branch = tree_branch.add(
                    f"[{child_node.type.lower()}][bold]{child_node.type.upper()}[/bold][/{child_node.type.lower()}] "
                    f"[white]{child_node.title or child_node.summary}[/white] [dim]({child_node.id[:8]})[/dim]"
                )
                add_children(branch, cid, visited.copy())

    for rnode in root_nodes:
        branch = root_tree.add(
            f"[{rnode.type.lower()}][bold]{rnode.type.upper()}[/bold][/{rnode.type.lower()}] "
            f"[white]{rnode.title or rnode.summary}[/white] [dim]({rnode.id[:8]})[/dim]"
        )
        add_children(branch, rnode.id)

    console.print(root_tree)


@app.command(name="lineage")
def lineage(
    node_id: str = typer.Argument(..., help="Memory node UUID or prefix to inspect ancestry"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Trace and print the full causal ancestor and descendant tree of a specific memory."""
    from ..core.memory_dag import MemoryDAG

    storage = get_storage(project)
    nodes = storage.get_all(limit=1000)
    target_node = None
    for n in nodes:
        if n.id == node_id or n.id.startswith(node_id):
            target_node = n
            break

    if not target_node:
        console.print(f"[red]Memory entry '{node_id}' not found.[/red]")
        return

    dag = MemoryDAG()
    for n in sorted(nodes, key=lambda x: x.timestamp):
        try:
            dag.add_node(n)
        except Exception:
            pass

    ancestors = [dag.get_node(aid) for aid in dag.get_ancestors(target_node.id) if dag.get_node(aid)]
    descendants = [dag.get_node(did) for did in dag.get_descendants(target_node.id) if dag.get_node(did)]

    lines = [f"[bold cyan]Causal Lineage for:[/bold cyan] {_esc(target_node.title or target_node.summary)} [dim]({target_node.id[:8]})[/dim]\n"]

    if ancestors:
        lines.append("[bold yellow]Ancestors (Causal Foundations):[/bold yellow]")
        for a in sorted(ancestors, key=lambda x: x.timestamp):
            lines.append(f"  └── {_esc(f'[{a.type}]')} {_esc(a.title or a.summary)} [dim]({a.id[:8]})[/dim]")
    else:
        lines.append("[dim]No ancestor nodes (Root Decision)[/dim]")

    lines.append(f"\n[bold green]► Target Node:[/bold green] {_esc(f'[{target_node.type}]')} {_esc(target_node.title or target_node.summary)} [dim]({target_node.id})[/dim]")

    if descendants:
        lines.append("\n[bold magenta]Descendants (Derived Decisions/Hacks):[/bold magenta]")
        for d in sorted(descendants, key=lambda x: x.timestamp):
            lines.append(f"  └── {_esc(f'[{d.type}]')} {_esc(d.title or d.summary)} [dim]({d.id[:8]})[/dim]")
    else:
        lines.append("[dim]No downstream descendants yet[/dim]")

    console.print(Panel("\n".join(lines), title="Memory Causal Lineage", border_style="cyan"))



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
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Automatically open preview in default browser"),
):
    """Start real-time Markdown preview server with WebSocket live-reload."""
    if MarkdownPreviewServer.is_tacit_server_running(port):
        console = Console()
        console.print(f"[bold yellow]Notice:[/bold yellow] A Tacit server instance is already running at [bold cyan]http://localhost:{port}[/bold cyan].")
        if open_browser:
            import webbrowser
            webbrowser.open(f"http://localhost:{port}")
        raise typer.Exit(code=0)

    storage = get_storage(project)
    root = Config.find_project_root(project)
    out_dir = Path(output) if output else Config.get_export_dir(root)
    server = MarkdownPreviewServer(storage, out_dir, port=port, ws_port=ws_port)
    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    server.start(block=True)


@app.command(name="dashboard")
def dashboard(
    port: int = typer.Option(4000, "--port", help="Port for preview and dashboard server"),
    ws_port: Optional[int] = typer.Option(None, "--ws-port", help="Port for preview WebSocket server (defaults to 4001 or next available)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Directory for exported documentation"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Automatically open dashboard in default browser"),
):
    """Start visual Project Memory Dashboard web interface with multi-project support and live-reload."""
    if MarkdownPreviewServer.is_tacit_server_running(port):
        console = Console()
        console.print(f"[bold yellow]Notice:[/bold yellow] A Tacit dashboard instance is already running at [bold cyan]http://localhost:{port}[/bold cyan].")
        if open_browser:
            import webbrowser
            webbrowser.open(f"http://localhost:{port}")
        raise typer.Exit(code=0)

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

    table = Table(title="Registered Projects (Tacit)", show_header=True, header_style="bold green")
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

    console.print(f"[yellow]Target Memory:[/yellow] {_esc(f'[{node.type}]')} {_esc(node.summary)} ([dim]{node.id}[/dim])")

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


@app.command(name="briefing")
def briefing_cmd(
    budget: int = typer.Option(Config.TOKEN_BUDGET, "--budget", "-b", help="Token budget cap for briefing"),
    timeframe: str = typer.Option(
        "all",
        "--timeframe",
        "-t",
        help="Only brief on memories from this window: all, week, 30d, 6h, year, or an ISO date",
    ),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Generate intelligent relevance-ranked project briefing for agent bootstrapping."""
    from ..core.bootstrap import BootstrapEngine
    storage = get_storage(project)
    res = BootstrapEngine.generate_briefing(storage=storage, budget=budget, timeframe=timeframe)
    # The briefing is pre-rendered plain text: markup=False keeps bracketed titles
    # like "[WinError 32] ..." from being parsed as Rich style tags.
    console.print(res.get("formatted", ""), markup=False)


@app.command(name="context")
def context_cmd(
    budget: int = typer.Option(Config.TOKEN_BUDGET, "--budget", "-b", help="Token budget cap for briefing"),
    timeframe: str = typer.Option(
        "all",
        "--timeframe",
        "-t",
        help="Only brief on memories from this window: all, week, 30d, 6h, year, or an ISO date",
    ),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Alias for 'briefing' — generate relevance-ranked project briefing for agent bootstrapping."""
    briefing_cmd(budget=budget, timeframe=timeframe, project=project)


@app.command()
def supersede(
    target_id: str = typer.Argument(..., help="ID of the memory node to supersede"),
    by: str = typer.Option(..., "--by", help="ID of the newer successor memory node"),
    reason: str = typer.Option("", "--reason", "-r", help="Reason for superseding"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Explicitly mark a memory node as superseded by a newer memory."""
    storage = get_storage(project)
    success = storage.supersede_memory(target_id=target_id, by_id=by, reason=reason, actor="human")
    if success:
        console.print(f"[bold green]Successfully marked memory {target_id[:8]} as superseded by {by[:8]}.[/bold green]")
    else:
        console.print(f"[bold red]Failed to supersede memory {target_id}. Memory not found.[/bold red]")


@app.command()
def retract(
    node_id: str = typer.Argument(..., help="ID of the memory node to retract"),
    reason: str = typer.Option("", "--reason", "-r", help="Reason for retraction"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Mark an erroneously recorded memory as retracted."""
    storage = get_storage(project)
    success = storage.retract_memory(node_id=node_id, reason=reason, actor="human")
    if success:
        console.print(f"[bold green]Successfully retracted memory node {node_id[:8]}.[/bold green]")
    else:
        console.print(f"[bold red]Failed to retract memory {node_id}. Memory not found.[/bold red]")


@app.command()
def verify(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Target project name or directory"),
):
    """Verify cryptographic hash integrity and causal Merkle roots across all project memories."""
    storage = get_storage(project)
    all_nodes = storage.get_all(limit=50000)
    if not all_nodes:
        console.print("[yellow]No memories stored in this project to verify.[/yellow]")
        return

    corrupted = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Verifying {len(all_nodes)} memory nodes...", total=len(all_nodes))
        for node in all_nodes:
            if not node.verify():
                corrupted += 1
                console.print(f"[bold red]INTEGRITY MISMATCH:[/bold red] Node `{node.id}` fails content/Merkle verification.")
            progress.advance(task)

    if corrupted == 0:
        console.print(Panel.fit(
            f"[bold green]Verification Passed[/bold green]\n"
            f"[dim]Total Verified:[/dim] {len(all_nodes)} nodes\n"
            f"[dim]Cryptographic Proof:[/dim] All content hashes and causal roots match.",
            border_style="green",
        ))
    else:
        console.print(Panel.fit(
            f"[bold red]Verification Failed[/bold red]\n"
            f"[red]{corrupted} corrupted nodes detected![/red]",
            border_style="red",
        ))


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
        "command": "tacit",
        "args": ["mcp"]
    }

    if client.lower() == "print":
        console.print(Panel(
            json.dumps({"mcpServers": {"tacit": config_entry}}, indent=2),
            title="MCP Configuration Snippet",
            border_style="cyan"
        ))
        return

    sys_os = platform.system().lower()
    if client.lower() in ("antigravity", "agy", "gemini"):
        config_path = Path.home() / ".gemini" / "config" / "mcp_config.json"
    elif client.lower() == "claude":
        if sys_os == "windows":
            config_path = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
        elif sys_os == "darwin":
            config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        else:
            config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    elif client.lower() in ("claude-code", "claude_code"):
        config_path = Path.home() / ".claude.json"
    elif client.lower() == "cursor":
        if sys_os == "windows":
            config_path = Path(os.environ.get("APPDATA", "")) / "Cursor" / "User" / "globalStorage" / "cursor_desktop_config.json"
        elif sys_os == "darwin":
            config_path = Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "cursor_desktop_config.json"
        else:
            config_path = Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "cursor_desktop_config.json"

    elif client.lower() in ("deepseek", "dsh", "deepseek-harness"):
        config_path = Path.home() / ".config" / "deepseek-harness" / "profiles" / "default.yaml"
        dsh_plugin_entry = {
            "id": "mcp-tacit",
            "name": "@deepseek-ai/dsh-mcp-client",
            "config": {
                "serverName": "tacit",
                "transport": "stdio",
                "command": "tacit",
                "args": ["mcp"],
                "failOnStartupError": False
            }
        }

        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if config_path.exists():
                try:
                    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    data = {}

            if "plugins" not in data or not isinstance(data["plugins"], list):
                data["plugins"] = []

            # Remove existing tacit plugin entry if present
            data["plugins"] = [
                p for p in data["plugins"]
                if not (isinstance(p, dict) and p.get("id") == "mcp-tacit")
            ]
            
            # Append updated entry
            data["plugins"].append(dsh_plugin_entry)

            config_path.write_text(yaml.dump(data, sort_keys=False, default_flow_style=False), encoding="utf-8")

            console.print(Panel.fit(
                f"[bold green]MCP Server Configured Successfully[/bold green]\n"
                f"[dim]Client:[/dim]  DeepSeek Harness\n"
                f"[dim]Config:[/dim]  {config_path.resolve()}\n\n"
                f"[cyan]The 'tacit mcp' plugin is now registered in your default DeepSeek profile.[/cyan]",
                border_style="green",
            ))
        except Exception as e:
            console.print(f"[red]Failed to write DeepSeek Harness config: {e}[/red]")
            console.print("[yellow]You can manually add this plugin block to your dsh YAML profile:[/yellow]")
            console.print(yaml.dump({"plugins": [dsh_plugin_entry]}, sort_keys=False))
        return
    else:
        console.print(f"[red]Unknown client '{client}'. Supported options: antigravity, agy, claude, claude-code, cursor, print.[/red]")
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

        # Remove any legacy aliases
        existing_data["mcpServers"].pop("project-memory", None)
        existing_data["mcpServers"].pop("pmc", None)

        existing_data["mcpServers"]["tacit"] = config_entry
        config_path.write_text(json.dumps(existing_data, indent=2), encoding="utf-8")

        console.print(Panel.fit(
            f"[bold green]MCP Server Configured Successfully[/bold green]\n"
            f"[dim]Client:[/dim]  {client.capitalize()}\n"
            f"[dim]Config:[/dim]  {config_path.resolve()}\n\n"
            f"[cyan]The 'tacit mcp' server is now globally registered for all projects.[/cyan]",
            border_style="green",
        ))
    except Exception as e:
        console.print(f"[red]Failed to write config automatically: {e}[/red]")
        console.print("[yellow]You can manually add this to your MCP configuration:[/yellow]")
        console.print(json.dumps({"mcpServers": {"tacit": config_entry}}, indent=2))


def _is_editable_install() -> bool:
    """True when Tacit was installed with ``pip install -e`` (a development clone)."""
    import sysconfig

    try:
        from importlib.metadata import distribution

        raw = distribution("tacit").read_text("direct_url.json")
        if raw:
            return bool(json.loads(raw).get("dir_info", {}).get("editable"))
    except Exception:
        pass
    try:
        site = Path(sysconfig.get_path("purelib") or "")
        if site.is_dir():
            if any(site.glob("__editable__*tacit*.pth")) or (site / "tacit.egg-link").exists():
                return True
    except Exception:
        pass
    return False


def _local_source_root() -> Optional[Path]:
    """Locate the source checkout backing this installation, when there is one."""
    candidate = updater.package_parent_dir()
    if (candidate / "setup.py").exists() or (candidate / "pyproject.toml").exists():
        return candidate
    try:
        root = Config.find_project_root()
        if (root / "setup.py").exists() and (root / ".git").exists():
            return root
    except Exception:
        pass
    return None


def _resolve_update_mode(force_source: bool) -> tuple[bool, Optional[Path]]:
    """Decide between reinstalling from the Git URL and updating the local checkout.

    Reinstalling from Git over an editable install is what produced the
    ``~acit-0.1.0.dist-info`` debris in site-packages, so an editable install is
    always updated in place instead.
    """
    dev_env = os.environ.get("TACIT_DEV_MODE", "").strip().lower() in ("1", "true", "yes", "on")
    source_root = _local_source_root()
    editable = bool(source_root) and (force_source or dev_env or _is_editable_install())
    return editable, (source_root if editable else None)


@app.command()
def update(
    git_url: str = typer.Option(
        updater.DEFAULT_GIT_URL, "--url", help="Git repository URL to update from"
    ),
    source: bool = typer.Option(
        False,
        "--source",
        help="Update the local source checkout (git pull + editable install) instead of the Git URL",
    ),
    reinit: bool = typer.Option(
        True,
        "--reinit/--no-reinit",
        help="Refresh workspace agent rules once the update finishes",
    ),
):
    """Update Tacit to the latest version and refresh project rules in the current directory."""
    import platform

    console.print("[cyan]Updating Tacit...[/cyan]")

    # The update runs detached on Windows, so a failure there is otherwise silent.
    previous = updater.read_status()
    if previous and previous.get("ok") is False:
        console.print(
            Panel.fit(
                "[yellow]The previous update did not finish cleanly.[/yellow]\n"
                f"[dim]Log:[/dim] {updater.update_log_path()}\n"
                f"[dim]Target:[/dim] {previous.get('target')}\n"
                f"[dim]Reason:[/dim] {str(previous.get('error') or 'see log')[:400]}",
                border_style="yellow",
            )
        )

    foreign_checkout = updater.find_foreign_checkout(Path.cwd())
    if foreign_checkout:
        console.print(
            Panel.fit(
                "[yellow]This is not the checkout the installed command runs.[/yellow]\n\n"
                f"[dim]Running from:[/dim] {updater.package_parent_dir()}\n"
                f"[dim]This directory:[/dim] {foreign_checkout}\n\n"
                "An editable install stays pinned to the directory it was installed from, so\n"
                "the checkout above is the one being updated. To switch to this one, run\n"
                "[bold cyan]pip install -e .[/bold cyan] from it first.",
                border_style="yellow",
            )
        )

    editable, source_root = _resolve_update_mode(source)
    target = str(source_root) if editable else f"git+{git_url}"
    spec = {
        "python": updater.real_python_executable(),
        "package_parent": str(updater.package_parent_dir()),
        "parent_pid": os.getpid(),
        "cwd": str(Path.cwd()),
        "git_url": git_url,
        "target": target,
        "editable": editable,
        "source_root": str(source_root) if source_root else None,
        "reinit": reinit,
        "log": str(updater.update_log_path()),
        "status": str(updater.update_status_path()),
        "attempts": 3,
    }

    if editable:
        console.print(f"[dim]Source checkout detected:[/dim] {source_root}")
        console.print("[dim]Updating in editable mode (git pull + pip install -e).[/dim]")

    # ------------------------------------------------------------------
    # Windows: a running tacit.exe cannot be replaced in place, so the work
    # is handed to a detached updater that outlives this process.
    # ------------------------------------------------------------------
    if platform.system().lower() == "windows":
        try:
            updater.launch_detached_windows_updater(spec)
        except Exception as exc:
            console.print(f"[bold red]Failed to launch the background updater: {exc}[/bold red]")
            console.print("[yellow]Manual fix:[/yellow]")
            console.print("  1. Close every editor running the Tacit MCP server")
            console.print(
                "  2. Run: pip install --upgrade --force-reinstall --no-cache-dir --no-deps "
                + target
            )
            raise typer.Exit(code=1)

        console.print(
            Panel.fit(
                "[bold green]Tacit update started in the background.[/bold green]\n"
                "[dim]It waits for this process to exit, stops leftover Tacit daemons,[/dim]\n"
                "[dim]then reinstalls and refreshes your workspace rules.[/dim]\n\n"
                f"[dim]Log:[/dim] {updater.update_log_path()}\n"
                "[dim]Verify with:[/dim] [bold cyan]tacit --version[/bold cyan]",
                border_style="green",
            )
        )
        raise typer.Exit(code=0)

    # ------------------------------------------------------------------
    # Unix / macOS: safe to run pip in the current process.
    # ------------------------------------------------------------------
    killed = updater.terminate_unix_daemons(exclude_pids={os.getpid()})
    if killed:
        console.print(f"[dim]Stopped background Tacit daemons: {killed}[/dim]")
    updater.clean_tacit_debris()

    result = updater.perform_update(
        spec, log=lambda message: console.print(f"[dim]{message}[/dim]")
    )

    updater.write_status({**result, "target": target})

    if result.get("ok"):
        console.print(
            Panel.fit(
                "[bold green]Tacit successfully updated.[/bold green]\n"
                f"[dim]Version:[/dim] {result.get('version') or __version__}\n"
                f"[dim]Source:[/dim] {target}",
                border_style="green",
            )
        )
        return

    console.print(
        Panel.fit(
            "[bold red]Update failed.[/bold red]\n"
            f"[dim]Source:[/dim] {target}\n\n"
            f"{str(result.get('error') or 'see output above')[:600]}",
            border_style="red",
        )
    )
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()




