"""General-purpose progressive tool discovery framework.

Provides a multi-source ToolRegistry, BM25 search, per-session
ToolActivationState, and 4 meta-tools:
  search_tools     — BM25 keyword search + auto-activate
  activate_domain  — batch-activate all tools in a domain
  list_domains     — list domains with tool count + activation status
  list_active_tools — list currently activated tool names + descriptions
  create_tool      — Dev-only: create a custom tool with sandboxed code
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Sequence


# ── Role-based domain access (§5.4) ──────────────────────────

ROLE_DOMAIN_ACCESS: Dict[str, List[str]] = {
    "shell":   ["memory_read", "memory_search",
                "native_read", "native_search", "native_git",
                "custom"],
    "core":    ["memory_read", "memory_search",
                "native_read", "native_search",
                "custom"],
    "expert":  ["memory_read", "memory_search",
                "native_read", "native_search", "native_git",
                "custom"],
    "dev":     ["memory_read", "memory_write", "memory_search", "memory_structure",
                "native_read", "native_write", "native_exec",
                "native_search", "native_git", "native_control",
                "custom"],
    "review":  ["memory_read", "memory_write", "memory_search", "memory_structure",
                "native_read", "native_search", "native_git",
                "custom"],
}

# Roles allowed to create custom tools
ROLE_CREATE_TOOL_ACCESS = frozenset({"dev"})


# ── Tool Registry ─────────────────────────────────────────────

@dataclass
class DomainInfo:
    """A registered tool domain."""
    name: str
    description: str
    keywords: List[str]
    tool_names: List[str]
    # Callable that returns full schemas for given tool names
    schema_provider: Any = None  # Callable[[List[str]], List[Dict[str, Any]]]


class ToolRegistry:
    """Multi-source tool catalog.  Register domains, then search/activate."""

    def __init__(self) -> None:
        self._domains: Dict[str, DomainInfo] = {}
        self._tool_to_domain: Dict[str, str] = {}
        # BM25 index (lazy-built)
        self._bm25_corpus: Dict[str, List[str]] = {}
        self._bm25_df: Dict[str, int] = {}
        self._bm25_avg_dl: float = 0.0
        self._bm25_n: int = 0
        self._index_dirty: bool = True

    def register_domain(
        self,
        name: str,
        description: str,
        keywords: List[str],
        tool_names: List[str],
        schema_provider: Any,
    ) -> None:
        """Register a tool domain.  *schema_provider(names) -> [schema]*."""
        self._domains[name] = DomainInfo(
            name=name,
            description=description,
            keywords=keywords,
            tool_names=list(tool_names),
            schema_provider=schema_provider,
        )
        for tn in tool_names:
            self._tool_to_domain[tn] = name
        self._index_dirty = True

    @property
    def domain_names(self) -> List[str]:
        return list(self._domains.keys())

    def domain_info(self, name: str) -> Optional[DomainInfo]:
        return self._domains.get(name)

    def all_tool_names(self) -> List[str]:
        result: List[str] = []
        for d in self._domains.values():
            result.extend(d.tool_names)
        return result

    def get_schemas(self, tool_names: Sequence[str]) -> List[Dict[str, Any]]:
        """Get full schemas for the given tool names via their domain's provider."""
        by_domain: Dict[str, List[str]] = {}
        for tn in tool_names:
            domain_name = self._tool_to_domain.get(tn, "")
            if domain_name:
                by_domain.setdefault(domain_name, []).append(tn)
        schemas: List[Dict[str, Any]] = []
        for domain_name, names in by_domain.items():
            domain = self._domains[domain_name]
            if domain.schema_provider:
                schemas.extend(domain.schema_provider(names))
        return schemas

    # ── BM25 ──

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        import re
        tokens: List[str] = []
        for part in re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", text.lower()):
            part = part.strip()
            if not part:
                continue
            tokens.extend(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", part))
        return tokens

    def _build_index(self) -> None:
        if not self._index_dirty:
            return
        corpus: Dict[str, List[str]] = {}
        for domain in self._domains.values():
            kw_text = " ".join(domain.keywords)
            for tn in domain.tool_names:
                # Build doc from tool name + domain description + keywords
                # Try to get tool-level description from schema
                desc = ""
                if domain.schema_provider:
                    try:
                        schemas = domain.schema_provider([tn])
                        if schemas:
                            desc = schemas[0].get("description", "")
                    except Exception:
                        pass
                text = f"{tn} {desc} {domain.description} {kw_text}"
                corpus[tn] = self._tokenize(text)

        self._bm25_corpus = corpus
        self._bm25_n = len(corpus)
        self._bm25_avg_dl = (
            sum(len(t) for t in corpus.values()) / max(self._bm25_n, 1)
        )
        df: Dict[str, int] = {}
        for tokens in corpus.values():
            seen: set[str] = set()
            for token in tokens:
                if token not in seen:
                    df[token] = df.get(token, 0) + 1
                    seen.add(token)
        self._bm25_df = df
        self._index_dirty = False

    def bm25_search(
        self,
        query: str,
        allowed_tools: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[str]:
        """Return tool names ranked by BM25 relevance."""
        self._build_index()
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        k1, b = 1.5, 0.75
        scores: list[tuple[str, float]] = []
        for tool_name, doc_tokens in self._bm25_corpus.items():
            if allowed_tools is not None and tool_name not in allowed_tools:
                continue
            dl = len(doc_tokens)
            tf_map: Dict[str, int] = {}
            for t in doc_tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
            score = 0.0
            for qt in query_tokens:
                tf = tf_map.get(qt, 0)
                if tf == 0:
                    continue
                df_val = self._bm25_df.get(qt, 0)
                idf = math.log((self._bm25_n - df_val + 0.5) / (df_val + 0.5) + 1.0)
                num = tf * (k1 + 1)
                den = tf + k1 * (1 - b + b * dl / max(self._bm25_avg_dl, 1.0))
                score += idf * num / den
            if score > 0:
                scores.append((tool_name, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scores[:top_k]]


# ── Activation State ──────────────────────────────────────────

@dataclass
class ToolActivationState:
    """Per-session tool activation tracker."""
    active_tools: set[str] = field(default_factory=set)
    role: str = ""
    registry: Optional[ToolRegistry] = field(default=None, repr=False)

    def allowed_domains(self) -> List[str]:
        static = ROLE_DOMAIN_ACCESS.get(
            self.role.strip().lower(),
            self.registry.domain_names if self.registry else [],
        )
        # Dynamically include mcp_* domains (all roles can access MCP tools)
        if self.registry:
            mcp_domains = [d for d in self.registry.domain_names if d.startswith("mcp_")]
            return list(dict.fromkeys(list(static) + mcp_domains))  # deduplicated
        return list(static)

    def allowed_tools(self) -> List[str]:
        if not self.registry:
            return []
        allowed = self.allowed_domains()
        result: List[str] = []
        for domain_name in allowed:
            info = self.registry.domain_info(domain_name)
            if info:
                result.extend(info.tool_names)
        return result

    def activate(self, tool_names: List[str]) -> tuple[List[str], List[str]]:
        allowed = set(self.allowed_tools())
        activated: List[str] = []
        denied: List[str] = []
        for name in tool_names:
            if name in allowed:
                self.active_tools.add(name)
                activated.append(name)
            else:
                denied.append(name)
        return activated, denied

    def get_active_schemas(self) -> List[Dict[str, Any]]:
        if not self.active_tools or not self.registry:
            return []
        return self.registry.get_schemas(list(self.active_tools))


# ── Meta-Tool Definitions ─────────────────────────────────────

_META_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "search_tools",
        "description": "BM25 keyword search over all available tools. Matched tools are auto-activated.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "capability needed, e.g. 'edit file', 'grep search', 'git diff'",
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 35, "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "activate_domain",
        "description": "Batch-activate all tools in a domain.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "domain name to activate",
                },
            },
            "required": ["domain"],
        },
    },
    {
        "name": "list_domains",
        "description": "List available tool domains with tool count and activation status.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_active_tools",
        "description": "List currently activated tools with their descriptions.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "create_tool",
        "description": "Create a custom tool (Dev only). Code must define run(args) → dict. "
                       "Forbidden: import, exec, eval, open, subprocess.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "tool name, lowercase + underscores, 2-31 chars",
                },
                "description": {"type": "string"},
                "code": {
                    "type": "string",
                    "description": "Python source defining run(args) → dict",
                },
                "params_schema": {
                    "type": "object",
                    "description": "JSON Schema for tool parameters",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "search keywords for tool discovery",
                },
            },
            "required": ["name", "description", "code"],
        },
    },
]

META_TOOL_NAMES = frozenset(d["name"] for d in _META_TOOL_DEFINITIONS)


def get_meta_tool_definitions(role: str = "", registry: Optional[ToolRegistry] = None) -> List[Dict[str, Any]]:
    """Return meta-tool schemas. Filters activate_domain enum by role access."""
    defs = deepcopy(_META_TOOL_DEFINITIONS)
    if role and registry:
        allowed = ROLE_DOMAIN_ACCESS.get(role.strip().lower(), registry.domain_names)
        for defn in defs:
            if defn["name"] == "activate_domain":
                defn["parameters"]["properties"]["domain"]["enum"] = allowed
    elif registry:
        for defn in defs:
            if defn["name"] == "activate_domain":
                defn["parameters"]["properties"]["domain"]["enum"] = registry.domain_names
    return defs


# ── Meta-Tool Handler ─────────────────────────────────────────

def handle_meta_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    state: Optional[ToolActivationState] = None,
) -> Dict[str, Any]:
    """Route meta-tool calls. Returns structured result with error codes."""
    _state = state or ToolActivationState()
    registry = _state.registry

    if tool_name == "search_tools":
        query = str(arguments.get("query") or "").strip()
        top_k = int(arguments.get("top_k") or 5)
        if not query:
            return {"status": "error", "code": "E_EMPTY_QUERY"}
        if not registry:
            return {"status": "error", "code": "E_NO_REGISTRY"}
        allowed = _state.allowed_tools()
        matched = registry.bm25_search(query, allowed_tools=allowed, top_k=top_k)
        if not matched:
            return {
                "status": "ok",
                "code": "NO_MATCH",
                "matched_tools": [],
                "count": 0,
                "schemas": [],
            }
        activated, denied = _state.activate(matched)
        schemas = registry.get_schemas(activated)
        result: Dict[str, Any] = {
            "status": "ok",
            "matched_tools": activated,
            "count": len(activated),
            "schemas": schemas,
        }
        if denied:
            result["denied"] = denied
            result["code"] = "E_PARTIAL_DENIED"
        return result

    if tool_name == "activate_domain":
        domain = str(arguments.get("domain") or "").strip().lower()
        if not registry:
            return {"status": "error", "code": "E_NO_REGISTRY"}
        info = registry.domain_info(domain)
        if info is None:
            return {"status": "error", "code": "E_DOMAIN_NOT_FOUND", "domain": domain}
        if domain not in _state.allowed_domains():
            return {"status": "error", "code": "E_DOMAIN_DENIED", "domain": domain,
                    "allowed": _state.allowed_domains()}
        activated, denied = _state.activate(info.tool_names)
        schemas = registry.get_schemas(activated)
        return {
            "status": "ok",
            "domain": domain,
            "activated": activated,
            "count": len(activated),
            "schemas": schemas,
        }

    if tool_name == "list_domains":
        if not registry:
            return {"status": "error", "code": "E_NO_REGISTRY"}
        allowed = _state.allowed_domains()
        domains: List[Dict[str, Any]] = []
        for dname in registry.domain_names:
            info = registry.domain_info(dname)
            if info is None:
                continue
            active_count = len([t for t in info.tool_names if t in _state.active_tools])
            domains.append({
                "domain": dname,
                "description": info.description,
                "total": len(info.tool_names),
                "active": active_count,
                "accessible": dname in allowed,
            })
        return {"status": "ok", "domains": domains}

    if tool_name == "list_active_tools":
        if not registry:
            return {"status": "ok", "active_tools": [], "count": 0}
        active_list: List[Dict[str, str]] = []
        for tool in sorted(_state.active_tools):
            desc = ""
            domain_name = registry._tool_to_domain.get(tool, "")
            info = registry.domain_info(domain_name)
            if info and info.schema_provider:
                try:
                    schemas = info.schema_provider([tool])
                    if schemas:
                        desc = schemas[0].get("description", "")
                except Exception:
                    pass
            active_list.append({"name": tool, "description": desc})
        return {"status": "ok", "active_tools": active_list, "count": len(active_list)}

    if tool_name == "create_tool":
        if not _state.role or _state.role.strip().lower() not in ROLE_CREATE_TOOL_ACCESS:
            return {"status": "error", "code": "E_CREATE_DENIED",
                    "error": f"role '{_state.role}' cannot create tools"}

        tool_name_val = str(arguments.get("name") or "").strip().lower()
        if not tool_name_val or not re.match(r"^[a-z][a-z0-9_]{1,30}$", tool_name_val):
            return {"status": "error", "code": "E_INVALID_NAME",
                    "error": "name must match ^[a-z][a-z0-9_]{1,30}$"}

        description_val = str(arguments.get("description") or "").strip()
        code_val = str(arguments.get("code") or "").strip()
        params_schema = arguments.get("params_schema") or {"type": "object", "properties": {}}
        keywords_val = arguments.get("keywords") or []

        from agents.runtime.custom_tools import (
            validate_tool_code,
            save_custom_tool,
            register_custom_tools_into_registry,
            _LOADED_CUSTOM_TOOLS,
        )

        ok, errors = validate_tool_code(code_val)
        if not ok:
            return {"status": "error", "code": "E_VALIDATION_FAILED", "errors": errors}

        import time as _time
        spec = {
            "name": tool_name_val,
            "description": description_val,
            "version": 1,
            "created_by": _state.role,
            "created_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "params_schema": params_schema,
            "code": code_val,
            "keywords": keywords_val if isinstance(keywords_val, list) else [],
        }

        memory_root = arguments.get("_memory_root")
        saved_path = save_custom_tool(spec, memory_root=memory_root)
        _LOADED_CUSTOM_TOOLS[tool_name_val] = spec

        # Re-register custom domain if registry available
        if registry:
            register_custom_tools_into_registry(registry, memory_root=memory_root)

        # Auto-activate the new tool
        _state.activate([tool_name_val])

        return {
            "status": "ok",
            "tool_name": tool_name_val,
            "saved_to": str(saved_path),
            "schemas": [{"name": tool_name_val, "description": description_val,
                         "parameters": params_schema}],
        }

    return {"status": "error", "code": "E_UNKNOWN_META_TOOL", "tool_name": tool_name}


# ── Registry Builder ──────────────────────────────────────────

def build_default_registry() -> ToolRegistry:
    """Build and return a ToolRegistry pre-populated with memory + native tools."""
    registry = ToolRegistry()

    # Register memory tools
    try:
        from agents.memory.memory_tools import get_memory_tool_definitions
        registry.register_domain(
            "memory_read", "read and list memory files",
            ["读", "read", "查看", "列出", "list", "view", "内容", "content"],
            ["memory_read", "memory_list"],
            get_memory_tool_definitions,
        )
        registry.register_domain(
            "memory_write", "create and edit memory files",
            ["写", "write", "编辑", "修改", "patch", "替换", "insert", "append",
             "replace", "创建", "create", "edit", "update", "更新"],
            ["memory_write", "memory_patch", "memory_insert",
             "memory_append", "memory_replace"],
            get_memory_tool_definitions,
        )
        registry.register_domain(
            "memory_search", "search and index memory content",
            ["搜索", "search", "grep", "查找", "find", "匹配", "pattern",
             "索引", "index", "定位", "locate"],
            ["memory_grep", "memory_search", "memory_index"],
            get_memory_tool_definitions,
        )
        registry.register_domain(
            "memory_structure", "tag, link and manage memory lifecycle",
            ["标签", "tag", "link", "关联", "废弃", "deprecate", "删除",
             "delete", "归档", "archive", "标记", "mark", "lifecycle"],
            ["memory_deprecate", "memory_tag", "memory_link", "memory_delete"],
            get_memory_tool_definitions,
        )
    except ImportError:
        pass

    # Register native tools
    try:
        from agents.runtime.native_tools import get_native_tool_definitions
        registry.register_domain(
            "native_read", "read files and inspect project structure",
            ["read", "file", "list", "cwd", "ast", "skeleton", "artifact",
             "读取", "文件", "目录"],
            ["read_file", "list_files", "get_cwd",
             "file_ast_skeleton", "file_ast_chunk_read", "artifact_reader"],
            get_native_tool_definitions,
        )
        registry.register_domain(
            "native_write", "write files and apply workspace transactions",
            ["write", "file", "txn", "apply", "overwrite", "append",
             "写入", "保存"],
            ["write_file", "workspace_txn_apply"],
            get_native_tool_definitions,
        )
        registry.register_domain(
            "native_exec", "execute commands and run code",
            ["run", "cmd", "bash", "shell", "python", "repl", "execute",
             "命令", "执行", "运行"],
            ["run_cmd", "os_bash", "python_repl"],
            get_native_tool_definitions,
        )
        registry.register_domain(
            "native_search", "search code and query documentation",
            ["search", "keyword", "query", "docs", "查找", "关键字"],
            ["search_keyword", "query_docs"],
            get_native_tool_definitions,
        )
        registry.register_domain(
            "native_git", "git operations: status, diff, log, blame, grep",
            ["git", "status", "diff", "log", "show", "blame", "grep",
             "changed", "checkout", "版本"],
            ["git_status", "git_diff", "git_log", "git_show", "git_blame",
             "git_grep", "git_changed_files", "git_checkout_file"],
            get_native_tool_definitions,
        )
        registry.register_domain(
            "native_control", "process control and safety mechanisms",
            ["sleep", "watch", "killswitch", "plan", "control", "安全"],
            ["sleep_and_watch", "killswitch_plan"],
            get_native_tool_definitions,
        )
    except ImportError:
        pass

    # Register custom (agent-created) tools
    try:
        from agents.runtime.custom_tools import register_custom_tools_into_registry
        register_custom_tools_into_registry(registry)
    except ImportError:
        pass

    # Register MCP servers (standard protocol)
    try:
        from agents.runtime.mcp_client import get_mcp_pool, register_mcp_into_registry
        pool = get_mcp_pool()
        if pool:
            register_mcp_into_registry(registry, pool)
    except ImportError:
        pass

    return registry


__all__ = [
    "META_TOOL_NAMES",
    "ROLE_CREATE_TOOL_ACCESS",
    "ROLE_DOMAIN_ACCESS",
    "ToolActivationState",
    "ToolRegistry",
    "build_default_registry",
    "get_meta_tool_definitions",
    "handle_meta_tool",
]
