"""Markdown and HTML templates for export and live preview with Theme and Clear All support."""

MEMORY_MARKDOWN_TEMPLATE = """# {title}

**ID**: `{id}`  
**Type**: `{type}`  
**Date**: {date}  
**Impact**: `{impact}`  
**Status**: `{status}`  
**Author**: `{author}`  

## Summary
{summary}

## Content
{content}

## Taxonomy & Relations
- **Tags**: {tags}
- **Scope**: {scope}
- **Parents**: {parents}
- **Children**: {children}
- **Related**: {related}

---
*Content Hash*: `{content_hash}`  
*Merkle Root*: `{merkle_root}`
"""

INDEX_MARKDOWN_TEMPLATE = """# Project Memory Cortex Index

Generated on: {generated_at}  
Total Memories: **{total_count}**

## Category Breakdown
{breakdown}

## Recent Memories (Top 20)
{recent_table}

---
*Powered by Project Memory Cortex*
"""

HTML_PREVIEW_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="system">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Memory Cortex Preview</title>
    <style>
        /* Base / Dark Theme (Default) */
        :root {
            --bg: #121316;
            --sidebar-bg: #18191e;
            --card-bg: #202229;
            --card-hover: #272a33;
            --card-active: #2f3440;
            --fg: #e2e4ea;
            --fg-muted: #9499a8;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --border: #2e323e;
            --badge-bg: #303442;
            --code-bg: #252834;
            --pre-bg: #1a1c23;
            --success: #10b981;
            --error: #ef4444;
            --danger-bg: #7f1d1d;
            --danger-hover: #991b1b;
            --danger-text: #fca5a5;
        }

        /* Light Theme */
        [data-theme="light"] {
            --bg: #f8fafc;
            --sidebar-bg: #f1f5f9;
            --card-bg: #ffffff;
            --card-hover: #f8fafc;
            --card-active: #e2e8f0;
            --fg: #0f172a;
            --fg-muted: #64748b;
            --accent: #2563eb;
            --accent-hover: #1d4ed8;
            --border: #cbd5e1;
            --badge-bg: #e2e8f0;
            --code-bg: #e2e8f0;
            --pre-bg: #f1f5f9;
            --danger-bg: #fee2e2;
            --danger-hover: #fecaca;
            --danger-text: #dc2626;
        }

        /* Explicit Dark Theme */
        [data-theme="dark"] {
            --bg: #121316;
            --sidebar-bg: #18191e;
            --card-bg: #202229;
            --card-hover: #272a33;
            --card-active: #2f3440;
            --fg: #e2e4ea;
            --fg-muted: #9499a8;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --border: #2e323e;
            --badge-bg: #303442;
            --code-bg: #252834;
            --pre-bg: #1a1c23;
            --danger-bg: #7f1d1d;
            --danger-hover: #991b1b;
            --danger-text: #fca5a5;
        }

        @media (prefers-color-scheme: light) {
            [data-theme="system"] {
                --bg: #f8fafc;
                --sidebar-bg: #f1f5f9;
                --card-bg: #ffffff;
                --card-hover: #f8fafc;
                --card-active: #e2e8f0;
                --fg: #0f172a;
                --fg-muted: #64748b;
                --accent: #2563eb;
                --accent-hover: #1d4ed8;
                --border: #cbd5e1;
                --badge-bg: #e2e8f0;
                --code-bg: #e2e8f0;
                --pre-bg: #f1f5f9;
                --danger-bg: #fee2e2;
                --danger-hover: #fecaca;
                --danger-text: #dc2626;
            }
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--fg);
            display: flex;
            height: 100vh;
            overflow: hidden;
            transition: background 0.15s ease, color 0.15s ease;
        }

        /* Sidebar */
        .sidebar {
            width: 380px;
            background: var(--sidebar-bg);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            height: 100%;
        }

        .sidebar-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
        }

        .header-top-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .app-title {
            font-size: 15px;
            font-weight: 700;
            letter-spacing: -0.02em;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Theme Switcher */
        .theme-switcher {
            display: flex;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 2px;
            gap: 2px;
        }
        .theme-btn {
            background: transparent;
            border: none;
            color: var(--fg-muted);
            padding: 4px 6px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            line-height: 1;
            display: flex;
            align-items: center;
            transition: all 0.15s ease;
        }
        .theme-btn.active {
            background: var(--accent);
            color: #ffffff;
        }

        /* Project Selector */
        .project-bar {
            margin-bottom: 10px;
        }
        .project-dropdown {
            width: 100%;
            padding: 7px 10px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            color: var(--fg);
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            outline: none;
            cursor: pointer;
            transition: border-color 0.15s ease;
        }
        .project-dropdown:focus {
            border-color: var(--accent);
        }

        .search-box {
            width: 100%;
            padding: 8px 12px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            color: var(--fg);
            border-radius: 6px;
            font-size: 13px;
            outline: none;
            transition: border-color 0.15s ease;
        }
        .search-box:focus {
            border-color: var(--accent);
        }

        .filter-chips {
            display: flex;
            gap: 6px;
            margin-top: 10px;
            overflow-x: auto;
            padding-bottom: 4px;
        }
        .filter-chip {
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 12px;
            background: var(--badge-bg);
            color: var(--fg-muted);
            cursor: pointer;
            border: 1px solid transparent;
            white-space: nowrap;
            user-select: none;
        }
        .filter-chip.active {
            background: var(--accent);
            color: #ffffff;
        }

        .memory-list {
            flex: 1;
            overflow-y: auto;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .memory-item {
            padding: 12px;
            border-radius: 8px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .memory-item:hover {
            background: var(--card-hover);
        }
        .memory-item.active {
            background: var(--card-active);
            border-color: var(--accent);
        }

        .item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }

        .type-badge {
            display: inline-block;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .badge-decision { background: #1e3a8a; color: #93c5fd; }
        .badge-command { background: #374151; color: #d1d5db; }
        .badge-hack { background: #713f12; color: #fde047; }
        .badge-architecture { background: #14532d; color: #86efac; }
        .badge-error { background: #7f1d1d; color: #fca5a5; }
        .badge-context { background: #4c1d95; color: #d8b4fe; }

        .proj-badge {
            display: inline-block;
            padding: 1px 6px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            background: var(--badge-bg);
            color: var(--accent);
            border: 1px solid var(--border);
            margin-left: 6px;
        }

        .item-date {
            font-size: 11px;
            color: var(--fg-muted);
        }

        .item-title {
            font-size: 13px;
            font-weight: 600;
            color: var(--fg);
            margin-bottom: 4px;
            line-height: 1.4;
        }

        .item-summary {
            font-size: 12px;
            color: var(--fg-muted);
            line-height: 1.4;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        /* Sidebar Footer */
        .sidebar-footer {
            padding: 12px 16px;
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .btn-clear-all {
            background: transparent;
            color: var(--danger-text);
            border: 1px solid var(--border);
            padding: 5px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 5px;
            transition: all 0.15s ease;
        }
        .btn-clear-all:hover {
            background: var(--danger-bg);
        }

        .mem-count-badge {
            font-size: 11px;
            color: var(--fg-muted);
        }

        /* Main Content View */
        .content-wrapper {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
        }

        .action-bar {
            padding: 12px 60px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: flex-end;
            align-items: center;
            background: var(--sidebar-bg);
            gap: 12px;
        }

        .btn-delete {
            background: var(--danger-bg);
            color: var(--danger-text);
            border: 1px solid var(--border);
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.15s ease;
        }
        .btn-delete:hover {
            background: var(--danger-hover);
            color: #ffffff;
        }

        .content {
            flex: 1;
            overflow-y: auto;
            padding: 40px 60px;
            background: var(--bg);
        }

        .markdown-body {
            max-width: 820px;
            margin: 0 auto;
            line-height: 1.65;
            font-size: 15px;
        }

        .markdown-body h1 {
            font-size: 26px;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
        }
        .markdown-body h2 {
            font-size: 19px;
            margin-top: 28px;
            margin-bottom: 12px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 6px;
        }
        .markdown-body p { margin-bottom: 14px; }
        .markdown-body ul, .markdown-body ol { margin-left: 20px; margin-bottom: 14px; }
        .markdown-body li { margin-bottom: 6px; }
        .markdown-body hr { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
        .markdown-body code {
            background: var(--code-bg);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 13px;
        }
        .markdown-body pre {
            background: var(--pre-bg);
            border: 1px solid var(--border);
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
            margin-bottom: 16px;
        }
        .markdown-body pre code {
            background: transparent;
            padding: 0;
        }

        /* Empty State */
        .empty-box {
            padding: 30px 20px;
            text-align: center;
            color: var(--fg-muted);
            font-size: 13px;
            line-height: 1.6;
        }
        .empty-box strong { color: var(--fg); }
        .empty-proj-btn {
            display: inline-block;
            margin-top: 8px;
            margin-right: 6px;
            padding: 4px 10px;
            border-radius: 6px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            color: var(--accent);
            cursor: pointer;
            font-size: 11px;
            font-weight: 600;
        }
        .empty-proj-btn:hover {
            background: var(--card-hover);
        }

        /* Modal Dialog */
        .modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 9999;
        }
        .modal-overlay.active {
            display: flex;
        }

        .modal-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 24px;
            max-width: 460px;
            width: 90%;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        .modal-title {
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 8px;
            color: #ef4444;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .modal-body {
            font-size: 13px;
            color: var(--fg-muted);
            line-height: 1.5;
            margin-bottom: 20px;
        }
        .modal-actions {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
        }
        .btn-cancel {
            background: var(--card-hover);
            color: var(--fg);
            border: 1px solid var(--border);
            padding: 7px 14px;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
        }
        .btn-confirm-delete {
            background: #ef4444;
            color: white;
            border: none;
            padding: 7px 14px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-confirm-delete:hover {
            background: #dc2626;
        }

        /* Status Indicator */
        .connection-status {
            position: fixed;
            bottom: 18px;
            right: 18px;
            padding: 6px 12px;
            border-radius: 20px;
            background: var(--success);
            color: white;
            font-size: 11px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .connection-status.disconnected {
            background: var(--error);
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <div class="header-top-row">
                <div class="app-title">
                    <span>Memory Cortex</span>
                </div>
                <div class="theme-switcher">
                    <button class="theme-btn" data-theme="light" title="Light Theme" onclick="setTheme('light')">Light</button>
                    <button class="theme-btn" data-theme="dark" title="Dark Theme" onclick="setTheme('dark')">Dark</button>
                    <button class="theme-btn active" data-theme="system" title="System Theme" onclick="setTheme('system')">Auto</button>
                </div>
            </div>
            <div class="project-bar">
                <select class="project-dropdown" id="project-select" onchange="onProjectChange(this.value)">
                    <option value="current">Current Workspace</option>
                    <option value="all">All Projects</option>
                </select>
            </div>
            <input type="text" class="search-box" placeholder="Search memory nodes..." id="search">
            <div class="filter-chips" id="filter-chips">
                <div class="filter-chip active" data-type="all">All</div>
                <div class="filter-chip" data-type="decision">Decision</div>
                <div class="filter-chip" data-type="architecture">Architecture</div>
                <div class="filter-chip" data-type="hack">Hack</div>
                <div class="filter-chip" data-type="command">Command</div>
                <div class="filter-chip" data-type="error">Error</div>
                <div class="filter-chip" data-type="context">Context</div>
            </div>
        </div>
        <div class="memory-list" id="memory-list"></div>
        <div class="sidebar-footer">
            <span class="mem-count-badge" id="mem-count">0 entries</span>
            <button class="btn-clear-all" onclick="openClearAllModal()">
                <span>Clear All</span>
            </button>
        </div>
    </div>
    
    <div class="content-wrapper">
        <div class="action-bar" id="action-bar" style="display: none;">
            <button class="btn-delete" onclick="openDeleteModal()">
                <span>Delete Memory</span>
            </button>
        </div>
        <div class="content" id="content">
            <div class="markdown-body" id="rendered-content">
                <h1>Select a memory to view details</h1>
                <p>Live preview connected to Project Memory Cortex local server.</p>
            </div>
        </div>
    </div>

    <!-- Single Memory Delete Modal -->
    <div class="modal-overlay" id="delete-modal">
        <div class="modal-card">
            <div class="modal-title">
                <span>Confirm Memory Deletion</span>
            </div>
            <div class="modal-body" id="modal-memory-desc">
                Are you sure you want to permanently delete this project memory node? This action cannot be undone.
            </div>
            <div class="modal-actions">
                <button class="btn-cancel" onclick="closeDeleteModal()">Cancel</button>
                <button class="btn-confirm-delete" onclick="confirmDeleteMemory()">Delete Permanently</button>
            </div>
        </div>
    </div>

    <!-- Clear All Memories Modal -->
    <div class="modal-overlay" id="clear-all-modal">
        <div class="modal-card">
            <div class="modal-title">
                <span>Clear Project Memories</span>
            </div>
            <div class="modal-body">
                Are you <strong>ABSOLUTELY SURE</strong> you want to permanently delete memories for this project selection?
                <br><br>
                <span style="color: #ef4444;">This action cannot be undone.</span>
            </div>
            <div class="modal-actions">
                <button class="btn-cancel" onclick="closeClearAllModal()">Cancel</button>
                <button class="btn-confirm-delete" onclick="confirmClearAllMemories()">Clear Everything</button>
            </div>
        </div>
    </div>

    <div class="connection-status" id="status">● Connected</div>

    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
        let ws;
        let memories = [];
        let projects = [];
        let currentProjectName = "";
        let selectedProject = localStorage.getItem('pmc_selected_project') || "current";
        let currentMemoryId = null;
        let currentFilter = "all";

        // Theme management (light, dark, system)
        function initTheme() {
            const savedTheme = localStorage.getItem('pmc_theme') || 'system';
            setTheme(savedTheme, false);
        }

        function setTheme(theme, save = true) {
            document.documentElement.setAttribute('data-theme', theme);
            document.querySelectorAll('.theme-btn').forEach(btn => {
                btn.classList.toggle('active', btn.getAttribute('data-theme') === theme);
            });
            if (save) {
                localStorage.setItem('pmc_theme', theme);
            }
        }

        function updateProjectDropdown() {
            const selectEl = document.getElementById('project-select');
            if (!selectEl) return;

            let totalMemories = 0;
            projects.forEach(p => { totalMemories += (p.count || 0); });

            let html = `<option value="current" ${selectedProject === 'current' ? 'selected' : ''}>Active Workspace (${currentProjectName || 'Current'})</option>`;
            html += `<option value="all" ${selectedProject === 'all' ? 'selected' : ''}>All Projects (${totalMemories} total)</option>`;

            projects.forEach(p => {
                const label = `${p.name} (${p.count} ${p.count === 1 ? 'memory' : 'memories'})`;
                const isSel = (selectedProject === p.name);
                html += `<option value="${p.name}" ${isSel ? 'selected' : ''}>${label}</option>`;
            });

            selectEl.innerHTML = html;
        }

        function onProjectChange(newProject) {
            selectedProject = newProject;
            localStorage.setItem('pmc_selected_project', selectedProject);
            currentMemoryId = null;

            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: "switch_project", project: selectedProject }));
            } else {
                fetch(`/api/memories?project=${encodeURIComponent(selectedProject)}`)
                    .then(res => res.json())
                    .then(data => {
                        memories = data || [];
                        updateCountBadge();
                        renderList();
                        if (memories.length > 0) loadMemory(memories[0].id);
                    });
            }
        }

        function switchProjectDirectly(projName) {
            const selectEl = document.getElementById('project-select');
            if (selectEl) selectEl.value = projName;
            onProjectChange(projName);
        }

        function connectWS() {
            const wsUrl = `ws://${window.location.hostname}:${parseInt(window.location.port) + 1}`;
            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                const status = document.getElementById('status');
                status.textContent = '● Connected';
                status.className = 'connection-status';
                // Request current selected project data
                if (selectedProject !== "current") {
                    ws.send(JSON.stringify({ action: "switch_project", project: selectedProject }));
                }
            };

            ws.onclose = () => {
                const status = document.getElementById('status');
                status.textContent = '● Disconnected (Reconnecting...)';
                status.className = 'connection-status disconnected';
                setTimeout(connectWS, 2000);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'memories' || data.type === 'update') {
                        if (data.projects) {
                            projects = data.projects;
                        }
                        if (data.current_project) {
                            currentProjectName = data.current_project;
                        }
                        if (data.selected_project) {
                            selectedProject = data.selected_project;
                        }
                        updateProjectDropdown();

                        memories = data.memories || [];
                        updateCountBadge();
                        renderList();
                        if (currentMemoryId && memories.some(m => m.id === currentMemoryId)) {
                            loadMemory(currentMemoryId);
                        } else if (memories.length > 0) {
                            loadMemory(memories[0].id);
                        } else {
                            currentMemoryId = null;
                            document.getElementById('action-bar').style.display = 'none';
                            renderEmptyState();
                        }
                    }
                } catch (err) {
                    console.error("WS message parse error:", err);
                }
            };
        }

        function updateCountBadge() {
            const badge = document.getElementById('mem-count');
            if (badge) {
                badge.textContent = `${memories.length} ${memories.length === 1 ? 'entry' : 'entries'}`;
            }
        }

        function getBadgeClass(type) {
            return `badge-${type.toLowerCase()}`;
        }

        function renderEmptyState() {
            const contentEl = document.getElementById('rendered-content');
            const otherProjsWithMem = projects.filter(p => p.count > 0 && p.name !== selectedProject);
            
            let extraHelp = "";
            if (otherProjsWithMem.length > 0) {
                extraHelp = `<br><br><div style="font-size:13px; color: var(--fg-muted);">Memories were found in other project workspaces on your machine:</div><div style="margin-top:8px;">` +
                    otherProjsWithMem.map(p => `<button class="empty-proj-btn" onclick="switchProjectDirectly('${p.name}')">${p.name} (${p.count})</button>`).join('') +
                    `<button class="empty-proj-btn" onclick="switchProjectDirectly('all')">View All Projects</button></div>`;
            }

            contentEl.innerHTML = `
                <h1>No memories found in selected workspace</h1>
                <p>Use your AI assistant (Antigravity, Cursor, Claude) or run <code>pmc remember "..."</code> to record institutional memories.</p>
                ${extraHelp}
            `;
        }

        function renderList() {
            const listEl = document.getElementById('memory-list');
            const searchVal = document.getElementById('search').value.toLowerCase().trim();

            const filtered = memories.filter(m => {
                const matchesType = (currentFilter === "all" || m.type.toLowerCase() === currentFilter.toLowerCase());
                if (!matchesType) return false;
                if (!searchVal) return true;
                return (
                    (m.title && m.title.toLowerCase().includes(searchVal)) ||
                    (m.summary && m.summary.toLowerCase().includes(searchVal)) ||
                    (m.type && m.type.toLowerCase().includes(searchVal)) ||
                    (m.project && m.project.toLowerCase().includes(searchVal)) ||
                    (m.tags && m.tags.some(t => t.toLowerCase().includes(searchVal)))
                );
            });

            if (filtered.length === 0) {
                const otherProjsWithMem = projects.filter(p => p.count > 0 && p.name !== selectedProject);
                let switchHint = "";
                if (otherProjsWithMem.length > 0 && memories.length === 0) {
                    switchHint = `<div style="margin-top:10px;">Found memories in:<br>` +
                        otherProjsWithMem.map(p => `<button class="empty-proj-btn" onclick="switchProjectDirectly('${p.name}')">${p.name} (${p.count})</button>`).join('') +
                        `</div>`;
                }
                listEl.innerHTML = `<div class="empty-box">No matching memories found.${switchHint}</div>`;
                return;
            }

            listEl.innerHTML = filtered.map(m => {
                const dateStr = new Date(m.timestamp * 1000).toLocaleDateString(undefined, {
                    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                });
                const projLabel = (selectedProject === 'all' && m.project) ? `<span class="proj-badge">${m.project}</span>` : '';
                return `
                    <div class="memory-item ${currentMemoryId === m.id ? 'active' : ''}" onclick="loadMemory('${m.id}')">
                        <div class="item-header">
                            <div>
                                <span class="type-badge ${getBadgeClass(m.type)}">${m.type}</span>
                                ${projLabel}
                            </div>
                            <span class="item-date">${dateStr}</span>
                        </div>
                        <div class="item-title">${m.title || m.summary}</div>
                        <div class="item-summary">${m.summary}</div>
                    </div>
                `;
            }).join('');
        }

        function loadMemory(id) {
            currentMemoryId = id;
            renderList();

            const mem = memories.find(m => m.id === id);
            if (!mem) return;

            document.getElementById('action-bar').style.display = 'flex';
            const contentEl = document.getElementById('rendered-content');
            contentEl.innerHTML = marked.parse(mem.markdown || mem.content);
        }

        function openDeleteModal() {
            if (!currentMemoryId) return;
            const mem = memories.find(m => m.id === currentMemoryId);
            const title = mem ? (mem.title || mem.summary) : currentMemoryId;
            document.getElementById('modal-memory-desc').innerHTML = `Are you sure you want to permanently delete memory: <br><strong>"${title}"</strong> (<code>${currentMemoryId}</code>)?`;
            document.getElementById('delete-modal').classList.add('active');
        }

        function closeDeleteModal() {
            document.getElementById('delete-modal').classList.remove('active');
        }

        function confirmDeleteMemory() {
            if (!currentMemoryId) return;
            const targetId = currentMemoryId;
            const mem = memories.find(m => m.id === targetId);
            const targetProj = mem?.project || selectedProject;
            closeDeleteModal();

            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: "delete", node_id: targetId, project: targetProj }));
            } else {
                fetch(`/api/memories/${targetId}?project=${encodeURIComponent(targetProj)}`, { method: 'DELETE' })
                    .then(res => res.json())
                    .then(() => {
                        memories = memories.filter(m => m.id !== targetId);
                        updateCountBadge();
                        renderList();
                        if (memories.length > 0) loadMemory(memories[0].id);
                    });
            }
        }

        function openClearAllModal() {
            document.getElementById('clear-all-modal').classList.add('active');
        }

        function closeClearAllModal() {
            document.getElementById('clear-all-modal').classList.remove('active');
        }

        function confirmClearAllMemories() {
            closeClearAllModal();
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: "clear", project: selectedProject }));
            } else {
                fetch(`/api/memories?project=${encodeURIComponent(selectedProject)}`, { method: 'DELETE' })
                    .then(res => res.json())
                    .then(() => {
                        memories = [];
                        updateCountBadge();
                        renderList();
                        document.getElementById('action-bar').style.display = 'none';
                        renderEmptyState();
                    });
            }
        }

        // Search event listener
        document.getElementById('search').addEventListener('input', renderList);

        // Filter chips listeners
        document.getElementById('filter-chips').addEventListener('click', (e) => {
            const chip = e.target.closest('.filter-chip');
            if (!chip) return;
            document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentFilter = chip.getAttribute('data-type');
            renderList();
        });

        // Initialize Theme, Projects & WebSocket
        initTheme();
        connectWS();
    </script>
</body>
</html>
"""
