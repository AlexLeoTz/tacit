# Usage Examples & Workflows

## 1. CLI Workflows

### Initialize Project Memory
```bash
python -m src.cli.main init
```

### Record Key Decisions, Architecture & Hacks
```bash
# Record an architectural decision
python -m src.cli.main remember "Adopted SQLite FTS5 for local search instead of heavyweight Elasticsearch" \
  --type architecture \
  --title "Local FTS5 Engine Decision" \
  --tags "database,search,sqlite" \
  --impact high

# Record a quick build workaround / hack
python -m src.cli.main remember "Pinned numpy<2.0.0 due to legacy C-API extension compatibility in audio worker" \
  --type hack \
  --title "Pin NumPy < 2.0.0" \
  --tags "python,dependencies,build" \
  --impact medium

# Record a critical operational command
python -m src.cli.main remember "docker run --gpus all -v /data:/data -p 8000:8000 vllm/vllm-openai:latest" \
  --type command \
  --title "Production vLLM Container Start Command" \
  --tags "docker,gpu,vllm,deploy"
```

### Search Memories
```bash
python -m src.cli.main search "numpy"
python -m src.cli.main search "sqlite" --type architecture
```

### Export to Markdown and Launch Live Preview
```bash
python -m src.cli.main export --preview --port 8080
```

---

## 2. MCP Client Integration

### Claude Desktop Configuration
Add the server definition to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "project-memory": {
      "command": "python",
      "args": ["-m", "src.cli.main", "mcp"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

### Prompting AI Agents
When starting a session with Claude or Antigravity:
> *"Check `memory_context` to recall our architecture rules and past decisions before making changes to authentication."*
