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

INDEX_MARKDOWN_TEMPLATE = """# Tacit Index

Generated on: {generated_at}  
Total Memories: **{total_count}**

## Category Breakdown
{breakdown}

## Recent Memories (Top 20)
{recent_table}

---
*Powered by Tacit*
"""

HTML_PREVIEW_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tacit Preview</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        zinc: {
                            950: '#09090b',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        .modal-overlay {
            transition: opacity 0.2s ease;
        }
        .modal-overlay .modal-card {
            transition: transform 0.2s ease;
            transform: scale(0.95);
        }
        .modal-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }
        .modal-overlay.active .modal-card {
            transform: scale(1);
        }
        
        /* Modern markdown styling classes */
        .markdown-body {
            font-size: 0.95rem;
            line-height: 1.7;
        }
        .markdown-body h1 {
            font-size: 1.75rem;
            font-weight: 700;
            margin-top: 1.5rem;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid rgba(156, 163, 175, 0.2);
        }
        .markdown-body h2 {
            font-size: 1.35rem;
            font-weight: 600;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
            padding-bottom: 0.25rem;
            border-bottom: 1px solid rgba(156, 163, 175, 0.1);
        }
        .markdown-body p {
            margin-bottom: 1rem;
        }
        .markdown-body ul, .markdown-body ol {
            margin-left: 1.5rem;
            margin-bottom: 1rem;
            list-style-type: disc;
        }
        .markdown-body li {
            margin-bottom: 0.35rem;
        }
        .markdown-body code {
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.85em;
            padding: 0.15em 0.4em;
            background-color: rgba(156, 163, 175, 0.15);
            border-radius: 0.25rem;
        }
        .markdown-body pre {
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.9em;
            padding: 1rem;
            overflow-x: auto;
            background-color: rgba(156, 163, 175, 0.08);
            border: 1px solid rgba(156, 163, 175, 0.15);
            border-radius: 0.5rem;
            margin-bottom: 1rem;
        }
        .markdown-body pre code {
            background-color: transparent;
            padding: 0;
            border-radius: 0;
        }
    </style>
</head>
<body class="bg-white text-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 flex h-screen overflow-hidden font-sans transition-colors duration-150">
    <div class="w-80 md:w-96 bg-zinc-50 dark:bg-zinc-900 border-r border-zinc-200 dark:border-zinc-800 flex flex-col h-full shrink-0">
        <div class="p-4 border-b border-zinc-200 dark:border-zinc-800 flex flex-col gap-3">
            <div class="flex items-center justify-between">
                <div class="text-base font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-1.5">
                    <span>Tacit</span>
                </div>
                <div class="flex bg-zinc-200 dark:bg-zinc-800 rounded-md p-0.5 gap-0.5 border border-zinc-300 dark:border-zinc-700">
                    <button class="theme-btn px-2 py-0.5 rounded text-[10px] font-semibold transition-all" data-theme="light" title="Light Theme" onclick="setTheme('light')">Light</button>
                    <button class="theme-btn px-2 py-0.5 rounded text-[10px] font-semibold transition-all" data-theme="dark" title="Dark Theme" onclick="setTheme('dark')">Dark</button>
                    <button class="theme-btn px-2 py-0.5 rounded text-[10px] font-semibold transition-all active" data-theme="system" title="System Theme" onclick="setTheme('system')">Auto</button>
                </div>
            </div>
            
            <div>
                <select class="w-full px-2.5 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-900 dark:text-white rounded-md text-xs font-semibold outline-none focus:ring-1 focus:ring-cyan-500 cursor-pointer" id="project-select" onchange="onProjectChange(this.value)">
                    <option value="current">Current Workspace</option>
                    <option value="all">All Projects</option>
                </select>
            </div>
            
            <div class="relative">
                <input type="text" class="w-full pl-8 pr-3 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-950 dark:text-zinc-50 rounded-md text-xs outline-none focus:ring-1 focus:ring-cyan-500 placeholder-zinc-400" placeholder="Search memory nodes..." id="search">
                <div class="absolute left-2.5 top-2.5">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5 text-zinc-400">
                      <path stroke-linecap="round" stroke-linejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
                    </svg>
                </div>
            </div>
            
            <div class="flex gap-2">
                <button class="flex-1 py-1.5 px-3 bg-cyan-600 hover:bg-cyan-700 text-white rounded-md text-xs font-semibold flex items-center justify-center gap-1 transition-all" onclick="openAddMemoryModal()">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                    <span>Add Memory</span>
                </button>
                <button class="py-1.5 px-3 bg-zinc-200 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 rounded-md text-xs font-semibold flex items-center justify-center gap-1 transition-all" onclick="openCliModal()">
                    <span>CLI Reference</span>
                </button>
            </div>

            <div>
                <select id="filter-select" onchange="currentFilter = this.value; renderList();" class="w-full px-2.5 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-900 dark:text-white rounded-md text-xs outline-none focus:ring-1 focus:ring-cyan-500 cursor-pointer">
                    <option value="all">All Categories</option>
                    <option value="decision">Decision</option>
                    <option value="architecture">Architecture</option>
                    <option value="hack">Hack</option>
                    <option value="command">Command</option>
                    <option value="error">Error</option>
                    <option value="context">Context</option>
                </select>
            </div>
        </div>
        
        <div class="flex-1 overflow-y-auto p-3 flex flex-col gap-2" id="memory-list"></div>
        
        <div class="p-3 border-t border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
            <span class="text-xs text-zinc-500" id="mem-count">0 entries</span>
            <button class="text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20 border border-red-200 dark:border-red-900/40 rounded-md px-2 py-1 text-xs font-semibold flex items-center gap-1 transition-all" onclick="openClearAllModal()">
                <span>Clear All</span>
            </button>
        </div>
    </div>
    
    <div class="flex-1 flex flex-col h-full overflow-hidden bg-white dark:bg-zinc-950">
        <div class="p-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-end bg-zinc-50 dark:bg-zinc-900/40 gap-3 min-h-[53px]">
            <div id="action-bar" style="display: none;">
                <button class="bg-red-600 hover:bg-red-700 text-white rounded-lg px-3 py-1.5 text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm" onclick="openDeleteModal()">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                    </svg>
                    <span>Delete Memory</span>
                </button>
            </div>
        </div>
        <div class="flex-1 overflow-y-auto p-6 md:p-10">
            <div class="max-w-3xl mx-auto markdown-body dark:prose-invert" id="rendered-content">
                <h1 class="text-2xl font-bold mb-4 border-b border-zinc-200 dark:border-zinc-800 pb-3">Select a memory to view details</h1>
                <p class="text-zinc-500">Live preview connected to Tacit local server.</p>
            </div>
        </div>
    </div>

    <!-- Single Memory Delete Modal -->
    <div class="modal-overlay fixed inset-0 bg-black/60 backdrop-blur-sm opacity-0 pointer-events-none z-50 flex items-center justify-center p-4" id="delete-modal">
        <div class="modal-card bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-2xl max-w-md w-full">
            <div class="text-lg font-bold text-red-600 dark:text-red-400 mb-3 flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                </svg>
                <span>Confirm Memory Deletion</span>
            </div>
            <div class="text-sm text-zinc-600 dark:text-zinc-400 mb-5" id="modal-memory-desc">
                Are you sure you want to permanently delete this project memory node? This action cannot be undone.
            </div>
            <div class="flex justify-end gap-2.5">
                <button class="px-3.5 py-1.5 bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 rounded-md text-xs font-semibold transition-all" onclick="closeDeleteModal()">Cancel</button>
                <button class="px-3.5 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-md text-xs font-semibold transition-all" onclick="confirmDeleteMemory()">Delete Node</button>
            </div>
        </div>
    </div>

    <!-- Clear All Memories Modal -->
    <div class="modal-overlay fixed inset-0 bg-black/60 backdrop-blur-sm opacity-0 pointer-events-none z-50 flex items-center justify-center p-4" id="clear-all-modal">
        <div class="modal-card bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-2xl max-w-md w-full">
            <div class="text-lg font-bold text-red-600 dark:text-red-400 mb-3 flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                </svg>
                <span>Clear All Workspace Memories</span>
            </div>
            <div class="text-sm text-zinc-600 dark:text-zinc-400 mb-5">
                Are you <strong>ABSOLUTELY SURE</strong> you want to permanently delete memories for this project selection?
                <br><br>
                <span class="text-red-500 font-semibold">This action cannot be undone.</span>
            </div>
            <div class="flex justify-end gap-2.5">
                <button class="px-3.5 py-1.5 bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 rounded-md text-xs font-semibold transition-all" onclick="closeClearAllModal()">Cancel</button>
                <button class="px-3.5 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-md text-xs font-semibold transition-all" onclick="confirmClearAllMemories()">Clear Everything</button>
            </div>
        </div>
    </div>

    <!-- Add Memory Modal -->
    <div class="modal-overlay fixed inset-0 bg-black/60 backdrop-blur-sm opacity-0 pointer-events-none z-50 flex items-center justify-center p-4" id="add-memory-modal">
        <div class="modal-card bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-2xl max-w-xl w-full">
            <div class="flex items-center justify-between mb-3">
                <div class="text-lg font-bold text-zinc-900 dark:text-white">
                    <span>Record New Tacit Knowledge</span>
                </div>
                <button onclick="closeAddMemoryModal()" class="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
            <div class="text-xs text-zinc-500 dark:text-zinc-400 mb-4 leading-relaxed">
                Tacit stores <strong>Tacit Knowledge</strong> (architectural decisions, hacks, operational commands, and error caveats). Do not store transient code or chat logs.
            </div>
            <form id="add-memory-form" onsubmit="submitNewMemory(event)" class="space-y-4 text-xs">
                <div class="grid grid-cols-3 gap-3">
                    <div class="col-span-2">
                        <label class="block font-semibold text-zinc-700 dark:text-zinc-300 mb-1">Title</label>
                        <input type="text" id="add-title" required class="w-full px-3 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-950 dark:text-zinc-50 rounded-md outline-none focus:ring-1 focus:ring-cyan-500" placeholder="e.g. Resolved database connection pool exhaustion">
                    </div>
                    <div>
                        <label class="block font-semibold text-zinc-700 dark:text-zinc-300 mb-1">Type</label>
                        <select id="add-type" class="w-full px-3 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-900 dark:text-white rounded-md outline-none cursor-pointer focus:ring-1 focus:ring-cyan-500">
                            <option value="decision">Decision</option>
                            <option value="architecture">Architecture</option>
                            <option value="hack">Hack</option>
                            <option value="command">Command</option>
                            <option value="error">Error</option>
                            <option value="context">Context</option>
                        </select>
                    </div>
                </div>
                
                <div>
                    <label class="block font-semibold text-zinc-700 dark:text-zinc-300 mb-1">Summary (Short 1-sentence description)</label>
                    <input type="text" id="add-summary" class="w-full px-3 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-950 dark:text-zinc-50 rounded-md outline-none focus:ring-1 focus:ring-cyan-500" placeholder="Brief summary of the decision/hack">
                </div>

                <div>
                    <label class="block font-semibold text-zinc-700 dark:text-zinc-300 mb-1">Detailed Content / Rationale</label>
                    <textarea id="add-content" required class="w-full h-24 px-3 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-950 dark:text-zinc-50 rounded-md outline-none resize-y focus:ring-1 focus:ring-cyan-500 leading-normal" placeholder="Provide the details, reasons, and workarounds."></textarea>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block font-semibold text-zinc-700 dark:text-zinc-300 mb-1">Tags (Comma separated)</label>
                        <input type="text" id="add-tags" class="w-full px-3 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-950 dark:text-zinc-50 rounded-md outline-none focus:ring-1 focus:ring-cyan-500" placeholder="e.g. database, performance, auth">
                    </div>
                    <div>
                        <label class="block font-semibold text-zinc-700 dark:text-zinc-300 mb-1">Scope (File paths, comma separated)</label>
                        <input type="text" id="add-scope" class="w-full px-3 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-950 dark:text-zinc-50 rounded-md outline-none focus:ring-1 focus:ring-cyan-500" placeholder="e.g. /src/db.js, /src/server.js">
                    </div>
                </div>

                <div class="grid grid-cols-3 gap-3">
                    <div class="col-span-2">
                        <label class="block font-semibold text-zinc-700 dark:text-zinc-300 mb-1">Parent Node IDs (Select multiple holding Ctrl/Cmd)</label>
                        <select id="add-parents-select" multiple class="w-full px-2.5 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-900 dark:text-white rounded-md outline-none h-16">
                            <!-- Dynamic options loaded on open -->
                        </select>
                    </div>
                    <div>
                        <label class="block font-semibold text-zinc-700 dark:text-zinc-300 mb-1">Impact</label>
                        <select id="add-impact" class="w-full px-3 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-900 dark:text-white rounded-md outline-none cursor-pointer focus:ring-1 focus:ring-cyan-500">
                            <option value="high">High</option>
                            <option value="medium" selected>Medium</option>
                            <option value="low">Low</option>
                        </select>
                    </div>
                </div>

                <div class="flex justify-end gap-2.5 pt-2">
                    <button type="button" class="px-3.5 py-1.5 bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 rounded-md text-xs font-semibold transition-all" onclick="closeAddMemoryModal()">Cancel</button>
                    <button type="submit" class="px-3.5 py-1.5 bg-cyan-600 hover:bg-cyan-700 text-white rounded-md text-xs font-semibold transition-all">Record Memory</button>
                </div>
            </form>
        </div>
    </div>

    <!-- CLI Reference Modal -->
    <div class="modal-overlay fixed inset-0 bg-black/60 backdrop-blur-sm opacity-0 pointer-events-none z-50 flex items-center justify-center p-4" id="cli-modal">
        <div class="modal-card bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-5 shadow-2xl max-w-lg w-full">
            <div class="flex items-center justify-between mb-3">
                <div class="text-base font-bold text-zinc-900 dark:text-white">
                    <span>Tacit CLI Quick Reference</span>
                </div>
                <button onclick="closeCliModal()" class="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
            <div class="modal-body max-h-[380px] overflow-y-auto text-xs space-y-3" style="margin-bottom: 12px;">
                <p class="text-zinc-500 dark:text-zinc-400 leading-relaxed">
                    Use the global <code>tacit</code> binary in any project terminal to record or query decision graphs.
                </p>
                <div class="space-y-3">
                    <div>
                        <strong class="text-cyan-600 dark:text-cyan-400 font-semibold block mb-0.5">1. Initialize Tacit Database</strong>
                        <pre class="bg-zinc-100 dark:bg-zinc-950 p-2 border border-zinc-200 dark:border-zinc-800 rounded text-[10px]">tacit init</pre>
                    </div>
                    <div>
                        <strong class="text-cyan-600 dark:text-cyan-400 font-semibold block mb-0.5">2. Record Tacit Knowledge (With Parent Linkage)</strong>
                        <pre class="bg-zinc-100 dark:bg-zinc-950 p-2 border border-zinc-200 dark:border-zinc-800 rounded text-[10px] overflow-x-auto">tacit remember "Resolved db connection exhaustion by raising pool to 30" \
  --type decision \
  --tags "db,performance" \
  --parents 54bd72c1,a6a9dc1e</pre>
                    </div>
                    <div>
                        <strong class="text-cyan-600 dark:text-cyan-400 font-semibold block mb-0.5">3. Visualize Causal DAG Tree</strong>
                        <pre class="bg-zinc-100 dark:bg-zinc-950 p-2 border border-zinc-200 dark:border-zinc-800 rounded text-[10px]">tacit tree</pre>
                    </div>
                    <div>
                        <strong class="text-cyan-600 dark:text-cyan-400 font-semibold block mb-0.5">4. Trace Local Lineage (Ancestors & Descendants)</strong>
                        <pre class="bg-zinc-100 dark:bg-zinc-950 p-2 border border-zinc-200 dark:border-zinc-800 rounded text-[10px]">tacit lineage &lt;node_id_or_prefix&gt;</pre>
                    </div>
                    <div>
                        <strong class="text-cyan-600 dark:text-cyan-400 font-semibold block mb-0.5">5. View Full Memory Details</strong>
                        <pre class="bg-zinc-100 dark:bg-zinc-950 p-2 border border-zinc-200 dark:border-zinc-800 rounded text-[10px]">tacit get &lt;node_id_or_prefix&gt;</pre>
                    </div>
                    <div>
                        <strong class="text-cyan-600 dark:text-cyan-400 font-semibold block mb-0.5">6. Delete a Specific Memory Node</strong>
                        <pre class="bg-zinc-100 dark:bg-zinc-950 p-2 border border-zinc-200 dark:border-zinc-800 rounded text-[10px]">tacit delete &lt;node_id_or_prefix&gt;</pre>
                    </div>
                    <div>
                        <strong class="text-cyan-600 dark:text-cyan-400 font-semibold block mb-0.5">7. Global Update & Rule Refresh</strong>
                        <pre class="bg-zinc-100 dark:bg-zinc-950 p-2 border border-zinc-200 dark:border-zinc-800 rounded text-[10px]">tacit update</pre>
                    </div>
                </div>
            </div>
            <div class="flex justify-end pt-2 border-t border-zinc-100 dark:border-zinc-800">
                <button class="px-3.5 py-1.5 bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 rounded-md text-xs font-semibold transition-all" onclick="closeCliModal()">Close</button>
            </div>
        </div>
    </div>

    <div class="connection-status fixed bottom-4 right-4 px-3 py-1.5 rounded-full bg-green-600 dark:bg-green-700 text-white text-[10px] font-bold shadow-lg flex items-center gap-1.5 transition-all z-40 [&.disconnected]:bg-red-600 [&.disconnected]:dark:bg-red-700" id="status">● Connected</div>

    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
        let ws;
        let memories = [];
        let projects = [];
        let currentProjectName = "";
        let selectedProject = localStorage.getItem('tacit_selected_project') || "current";
        let currentMemoryId = null;
        let currentFilter = "all";

        // Theme management (light, dark, system)
        function initTheme() {
            const savedTheme = localStorage.getItem('tacit_theme') || 'system';
            setTheme(savedTheme, false);
        }

        function setTheme(theme, save = true) {
            let actualTheme = theme;
            if (theme === 'system') {
                actualTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            }
            if (actualTheme === 'dark') {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark');
            }
            document.documentElement.setAttribute('data-theme', theme);
            document.querySelectorAll('.theme-btn').forEach(btn => {
                if (btn.getAttribute('data-theme') === theme) {
                    btn.className = "theme-btn px-2 py-0.5 rounded text-[10px] bg-cyan-600 text-white font-semibold transition-all";
                } else {
                    btn.className = "theme-btn px-2 py-0.5 rounded text-[10px] text-zinc-500 dark:text-zinc-400 hover:bg-zinc-300/40 dark:hover:bg-zinc-700/60 transition-all cursor-pointer font-semibold";
                }
            });
            if (save) {
                localStorage.setItem('tacit_theme', theme);
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
            localStorage.setItem('tacit_selected_project', selectedProject);
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
            const wsPort = "__WS_PORT__" !== "__" + "WS_PORT__" ? "__WS_PORT__" : (parseInt(window.location.port) + 1);
            const wsUrl = `ws://${window.location.hostname}:${wsPort}`;
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
                <p>Use your AI assistant (Antigravity, Cursor, Claude) or run <code>tacit remember "..."</code> to record institutional memories.</p>
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

        function openAddMemoryModal() {
            const selectEl = document.getElementById('add-parents-select');
            selectEl.innerHTML = '';
            
            // Populate select dropdown with existing memories
            memories.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = `${m.title || m.summary || m.content.substring(0, 30)} [${m.id.substring(0, 8)}]`;
                selectEl.appendChild(opt);
            });

            document.getElementById('add-memory-modal').classList.add('active');
        }

        function closeAddMemoryModal() {
            document.getElementById('add-memory-modal').classList.remove('active');
            document.getElementById('add-memory-form').reset();
        }

        function openCliModal() {
            document.getElementById('cli-modal').classList.add('active');
        }

        function closeCliModal() {
            document.getElementById('cli-modal').classList.remove('active');
        }

        function submitNewMemory(event) {
            event.preventDefault();
            const title = document.getElementById('add-title').value;
            const memType = document.getElementById('add-type').value;
            const summary = document.getElementById('add-summary').value;
            const content = document.getElementById('add-content').value;
            
            const tags = document.getElementById('add-tags').value.split(',').map(s => s.trim()).filter(s => s.length > 0);
            const scope = document.getElementById('add-scope').value.split(',').map(s => s.trim()).filter(s => s.length > 0);
            
            const selectEl = document.getElementById('add-parents-select');
            const parents = Array.from(selectEl.selectedOptions).map(opt => opt.value);
            
            const impact = document.getElementById('add-impact').value;

            const payload = {
                title: title,
                type: memType,
                summary: summary,
                content: content,
                tags: tags,
                scope: scope,
                parents: parents,
                impact: impact,
                author: "human-developer"
            };

            const proj = selectedProject === 'all' ? 'current' : selectedProject;

            fetch(`/api/memories?project=${encodeURIComponent(proj)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    closeAddMemoryModal();
                    onProjectChange(selectedProject);
                } else {
                    alert(`Failed to add memory: ${data.message || 'unknown error'}`);
                }
            })
            .catch(err => {
                alert(`Error recording memory: ${err.message}`);
            });
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

        // Initialize Theme, Projects & WebSocket
        initTheme();
        connectWS();
    </script>
</body>
</html>
"""
