"""
Tool Contract 统一字段模型

实现 NGA-WS10-001: 统一 Tool Contract 字段模型
为 native_call 和 mcp_call 提供统一的请求/回执字段定义。

参考文档:
- doc/09-tool-execution-specification.md
- doc/00-omni-operator-architecture.md §6.2
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from system.artifact_store import ContentType, get_artifact_store
from system.gc_evidence_extractor import GCEvidence, build_gc_fetch_hints, extract_gc_evidence

class RiskLevel(str, Enum):
    """工具调用风险等级"""
    READ_ONLY = "read_only"          # 只读查询
    WRITE_REPO = "write_repo"        # 修改仓库文件或 Git 状态
    DEPLOY = "deploy"                # 部署、发布、环境变更
    SECRETS = "secrets"              # 密钥、凭据、敏感配置
    SELF_MODIFY = "self_modify"      # 自我进化（修改自身代码/配置）


class ExecutionScope(str, Enum):
    """执行范围"""
    LOCAL = "local"    # 文件级变更
    GLOBAL = "global"  # 环境级变更（需全局互斥锁）


@dataclass
class ToolCallEnvelope:
    """
    统一工具调用契约封装

    所有工具调用（native/mcp）必须携带的治理字段。
    """

    # === 调用标识 ===
    tool_name: str
    call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    trace_id: str = field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:16]}")
    workflow_id: Optional[str] = None
    session_id: Optional[str] = None

    # === 安全治理 ===
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    fencing_epoch: Optional[int] = None  # 防双主写入
    idempotency_key: Optional[str] = None
    caller_role: str = "user"  # user/system/agent

    # === 执行参数 ===
    validated_args: Dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 120_000  # 默认 2 分钟
    input_schema_version: str = "1.0"
    execution_scope: ExecutionScope = ExecutionScope.LOCAL
    requires_global_mutex: bool = False  # global 动作必须为 True

    # === 文件乐观锁（用于并发冲突检测）===
    original_file_hash: Optional[str] = None  # 写文件时必填

    # === 串行队列（全局动作排队）===
    queue_ticket: Optional[str] = None

    # === 预算控制 ===
    estimated_token_cost: int = 0
    budget_remaining: Optional[int] = None

    # === I/O 结果策略 ===
    io_result_policy: Optional[IOResultPolicy] = None

    # === 元数据 ===
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "tool_name": self.tool_name,
            "call_id": self.call_id,
            "trace_id": self.trace_id,
            "workflow_id": self.workflow_id,
            "session_id": self.session_id,
            "risk_level": self.risk_level.value,
            "fencing_epoch": self.fencing_epoch,
            "idempotency_key": self.idempotency_key,
            "caller_role": self.caller_role,
            "validated_args": self.validated_args,
            "timeout_ms": self.timeout_ms,
            "input_schema_version": self.input_schema_version,
            "execution_scope": self.execution_scope.value,
            "requires_global_mutex": self.requires_global_mutex,
            "original_file_hash": self.original_file_hash,
            "queue_ticket": self.queue_ticket,
            "estimated_token_cost": self.estimated_token_cost,
            "budget_remaining": self.budget_remaining,
            "io_result_policy": self.io_result_policy.to_dict() if self.io_result_policy else None,
            "created_at": self.created_at,
        }

    @classmethod
    def from_legacy_call(
        cls,
        call: Dict[str, Any],
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> ToolCallEnvelope:
        """从旧格式工具调用转换为统一契约"""
        tool_name = str(call.get("tool_name", call.get("name", "unknown")))
        call_id = str(call.get("_tool_call_id", call.get("id", f"call_{uuid.uuid4().hex[:12]}")))

        # 提取参数
        args = call.get("arguments", {})
        if isinstance(args, str):
            import json
            try:
                args = json.loads(args)
            except Exception:
                args = {}

        # 推断风险等级（基于工具名）
        risk_level = cls._infer_risk_level(tool_name, args)

        # 推断执行范围
        execution_scope = cls._infer_execution_scope(tool_name, args)

        return cls(
            tool_name=tool_name,
            call_id=call_id,
            trace_id=trace_id or f"trace_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            validated_args=args,
            risk_level=risk_level,
            execution_scope=execution_scope,
            requires_global_mutex=(execution_scope == ExecutionScope.GLOBAL),
        )

    @staticmethod
    def _infer_risk_level(tool_name: str, args: Dict[str, Any]) -> RiskLevel:
        """根据工具名推断风险等级"""
        tool_lower = tool_name.lower()

        # 密钥工具（优先级最高，避免被 read/get 规则抢先命中）
        if any(kw in tool_lower for kw in ["secret", "key", "token", "password", "credential"]):
            return RiskLevel.SECRETS

        # 只读工具
        if any(kw in tool_lower for kw in ["read", "list", "get", "search", "query", "view"]):
            return RiskLevel.READ_ONLY

        # 写入工具
        if any(kw in tool_lower for kw in ["write", "edit", "create", "delete", "modify", "update"]):
            return RiskLevel.WRITE_REPO

        # 部署工具
        if any(kw in tool_lower for kw in ["deploy", "restart", "start", "stop", "install"]):
            return RiskLevel.DEPLOY

        # 默认只读
        return RiskLevel.READ_ONLY

    @staticmethod
    def _infer_execution_scope(tool_name: str, args: Dict[str, Any]) -> ExecutionScope:
        """根据工具名推断执行范围"""
        tool_lower = tool_name.lower()

        # 全局动作
        global_keywords = [
            "install", "npm", "pip", "apt", "yum", "brew",
            "git_branch", "git_checkout", "git_merge",
            "systemctl", "service", "docker", "kubectl",
            "restart", "reboot", "shutdown",
        ]

        if any(kw in tool_lower for kw in global_keywords):
            return ExecutionScope.GLOBAL

        # 对通用命令工具增加参数级判断（例如 run_cmd + npm install）。
        cmd_fields = ["command", "cmd", "script", "task"]
        cmd_text = ""
        for cmd_field in cmd_fields:
            value = args.get(cmd_field)
            if isinstance(value, str) and value.strip():
                cmd_text = value.lower()
                break
        if cmd_text:
            global_cmd_markers = [
                "npm install",
                "npm i ",
                "pip install",
                "uv sync",
                "apt install",
                "apt-get install",
                "yum install",
                "brew install",
                "docker run",
                "docker compose up",
                "kubectl apply",
                "kubectl rollout",
                "git checkout",
                "git merge",
                "git rebase",
                "git reset",
                "systemctl ",
                "service ",
            ]
            if any(marker in cmd_text for marker in global_cmd_markers):
                return ExecutionScope.GLOBAL

        return ExecutionScope.LOCAL


@dataclass
class IOResultPolicy:
    """I/O 结果处理策略"""
    preview_max_chars: int = 8000  # 预览最大字符数
    structured_passthrough: bool = True  # JSON/XML/CSV 不做字符级截断
    artifact_on_overflow: bool = True  # 超阈值落盘并返回 raw_result_ref

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preview_max_chars": self.preview_max_chars,
            "structured_passthrough": self.structured_passthrough,
            "artifact_on_overflow": self.artifact_on_overflow,
        }


@dataclass
class ToolResultEnvelope:
    """
    统一工具执行结果封装
    """

    # === 调用标识（回溯）===
    call_id: str
    trace_id: str
    tool_name: str

    # === 执行状态 ===
    status: str  # "ok" | "error" | "timeout" | "blocked"
    exit_code: Optional[int] = None

    # === 结果数据 ===
    display_preview: str = ""  # 前端展示预览（兼容字段）
    raw_result_ref: Optional[str] = None  # 大对象引用（artifact ID，兼容字段）
    narrative_summary: Optional[str] = None  # 叙事摘要（与证据引用解耦）
    forensic_artifact_ref: Optional[str] = None  # 证据 artifact 引用（独立可回读）
    fetch_hints: Optional[list[str]] = None  # 二次读取提示（jsonpath/line_range）
    critical_evidence: Optional[Dict[str, list[str]]] = None  # 关键证据快照（trace/error/path）

    # === 元数据 ===
    truncated: bool = False
    total_chars: int = 0
    total_lines: int = 0
    content_type: str = "text/plain"  # text/plain | application/json | text/csv | application/xml

    # === 执行统计 ===
    duration_ms: float = 0.0
    token_cost: int = 0

    # === 审计与后续 ===
    risk_assessment: Optional[str] = None  # 执行后风险评估
    next_steps: Optional[list[str]] = None  # 建议后续动作

    # === 时间戳 ===
    completed_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """
        向后兼容映射：
        - narrative_summary <-> display_preview
        - forensic_artifact_ref <-> raw_result_ref
        """
        if self.narrative_summary is None:
            self.narrative_summary = self.display_preview
        elif not self.display_preview:
            self.display_preview = self.narrative_summary

        if self.forensic_artifact_ref is None:
            self.forensic_artifact_ref = self.raw_result_ref
        elif self.raw_result_ref is None:
            self.raw_result_ref = self.forensic_artifact_ref

        if self.critical_evidence is not None:
            self.critical_evidence = _normalize_critical_evidence(self.critical_evidence)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "call_id": self.call_id,
            "trace_id": self.trace_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "exit_code": self.exit_code,
            "display_preview": self.display_preview,
            "raw_result_ref": self.raw_result_ref,
            "narrative_summary": self.narrative_summary,
            "forensic_artifact_ref": self.forensic_artifact_ref,
            "fetch_hints": self.fetch_hints,
            "critical_evidence": self.critical_evidence,
            "truncated": self.truncated,
            "total_chars": self.total_chars,
            "total_lines": self.total_lines,
            "content_type": self.content_type,
            "duration_ms": self.duration_ms,
            "token_cost": self.token_cost,
            "risk_assessment": self.risk_assessment,
            "next_steps": self.next_steps,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_legacy_result(
        cls,
        call_id: str,
        trace_id: str,
        tool_name: str,
        result: Any,
        status: str = "ok",
        duration_ms: float = 0.0,
    ) -> ToolResultEnvelope:
        """从旧格式结果转换为统一契约"""
        result_text = str(result)
        total_chars = len(result_text)
        total_lines = result_text.count("\n") + 1

        # 判断是否需要截断
        preview_limit = 8000
        truncated = total_chars > preview_limit
        display_preview = result_text[:preview_limit] + "\n...[TRUNCATED]" if truncated else result_text

        return cls(
            call_id=call_id,
            trace_id=trace_id,
            tool_name=tool_name,
            status=status,
            display_preview=display_preview,
            narrative_summary=display_preview,
            truncated=truncated,
            total_chars=total_chars,
            total_lines=total_lines,
            duration_ms=duration_ms,
        )


def build_tool_result_with_artifact(
    call_id: str,
    trace_id: str,
    tool_name: str,
    raw_output: str,
    content_type: str = "text/plain",
    duration_ms: float = 0.0,
    *,
    priority: str = "normal",
) -> ToolResultEnvelope:
    """
    构建带 artifact 支持的工具结果

    根据输出大小和类型决定是否落盘为 artifact。
    """
    total_chars = len(raw_output)
    total_lines = raw_output.count("\n") + 1

    # 判断是否为结构化数据
    is_structured = content_type in ["application/json", "text/csv", "application/xml"]

    # 阈值判断
    preview_limit = 8000
    needs_artifact = total_chars > preview_limit
    evidence = extract_gc_evidence(raw_output, content_type=content_type)
    critical_evidence = _build_critical_evidence_snapshot(evidence)
    fetch_hints = _generate_fetch_hints(content_type, raw_output, evidence=evidence)

    if needs_artifact and is_structured:
        # 结构化数据：落盘 artifact，返回摘要
        artifact_id = _persist_artifact(
            raw_output,
            content_type,
            source_tool=tool_name,
            source_call_id=call_id,
            source_trace_id=trace_id,
            priority=priority,
        )
        narrative_summary = _summarize_structured(
            raw_output,
            content_type,
            critical_evidence=critical_evidence,
        )

        if not artifact_id:
            # 兜底：落盘失败时仍返回结构化摘要，但不给不可读 ref
            return ToolResultEnvelope(
                call_id=call_id,
                trace_id=trace_id,
                tool_name=tool_name,
                status="ok",
                display_preview=narrative_summary + "\n[artifact_persist_failed=true]",
                narrative_summary=narrative_summary + "\n[artifact_persist_failed=true]",
                truncated=True,
                total_chars=total_chars,
                total_lines=total_lines,
                content_type=content_type,
                duration_ms=duration_ms,
                fetch_hints=fetch_hints or None,
                critical_evidence=critical_evidence or None,
            )

        return ToolResultEnvelope(
            call_id=call_id,
            trace_id=trace_id,
            tool_name=tool_name,
            status="ok",
            display_preview=narrative_summary,
            raw_result_ref=artifact_id,
            narrative_summary=narrative_summary,
            forensic_artifact_ref=artifact_id,
            fetch_hints=fetch_hints or None,
            critical_evidence=critical_evidence or None,
            truncated=True,
            total_chars=total_chars,
            total_lines=total_lines,
            content_type=content_type,
            duration_ms=duration_ms,
        )
    elif needs_artifact:
        # 纯文本：截断预览
        preview = raw_output[:preview_limit] + "\n...[TRUNCATED]"
        preview_with_evidence = _append_critical_evidence_summary(preview, critical_evidence)
        return ToolResultEnvelope(
            call_id=call_id,
            trace_id=trace_id,
            tool_name=tool_name,
            status="ok",
            display_preview=preview_with_evidence,
            narrative_summary=preview_with_evidence,
            fetch_hints=fetch_hints or None,
            critical_evidence=critical_evidence or None,
            truncated=True,
            total_chars=total_chars,
            total_lines=total_lines,
            content_type=content_type,
            duration_ms=duration_ms,
        )
    else:
        # 小数据：直接返回
        return ToolResultEnvelope(
            call_id=call_id,
            trace_id=trace_id,
            tool_name=tool_name,
            status="ok",
            display_preview=raw_output,
            narrative_summary=raw_output,
            truncated=False,
            total_chars=total_chars,
            total_lines=total_lines,
            content_type=content_type,
            duration_ms=duration_ms,
        )


def _to_content_type(content_type: str) -> ContentType:
    normalized = (content_type or "").strip().lower()
    mapping = {
        "text/plain": ContentType.TEXT_PLAIN,
        "application/json": ContentType.APPLICATION_JSON,
        "text/csv": ContentType.TEXT_CSV,
        "application/xml": ContentType.APPLICATION_XML,
        "text/html": ContentType.TEXT_HTML,
        "application/octet-stream": ContentType.APPLICATION_OCTET_STREAM,
    }
    return mapping.get(normalized, ContentType.TEXT_PLAIN)


def _persist_artifact(
    content: str,
    content_type: str,
    *,
    source_tool: str,
    source_call_id: str,
    source_trace_id: str,
    priority: str = "normal",
) -> Optional[str]:
    """持久化 artifact，并返回 artifact_id；失败时返回 None。"""
    store = get_artifact_store()
    ok, _, metadata = store.store(
        content=content,
        content_type=_to_content_type(content_type),
        source_tool=source_tool,
        source_call_id=source_call_id,
        source_trace_id=source_trace_id,
        priority=priority,
    )
    if not ok or metadata is None:
        return None
    return metadata.artifact_id


def _normalize_critical_evidence(value: Any) -> Dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, list[str]] = {}
    for key in ("trace_ids", "error_codes", "paths"):
        raw_bucket = value.get(key)
        if isinstance(raw_bucket, list):
            bucket = [str(item).strip() for item in raw_bucket if str(item).strip()]
        else:
            bucket = [str(raw_bucket).strip()] if str(raw_bucket or "").strip() else []
        if bucket:
            deduped: list[str] = []
            seen: set[str] = set()
            for item in bucket:
                lowered = item.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                deduped.append(item)
            if deduped:
                normalized[key] = deduped[:3]
    return normalized


def _build_critical_evidence_snapshot(evidence: GCEvidence) -> Dict[str, list[str]]:
    return _normalize_critical_evidence(
        {
            "trace_ids": list(evidence.trace_ids[:3]),
            "error_codes": list(evidence.error_codes[:3]),
            "paths": list(evidence.paths[:3]),
        }
    )


def _append_critical_evidence_summary(summary: str, critical_evidence: Dict[str, list[str]]) -> str:
    normalized = _normalize_critical_evidence(critical_evidence)
    if not normalized:
        return summary

    segments: list[str] = []
    trace_ids = normalized.get("trace_ids", [])
    error_codes = normalized.get("error_codes", [])
    paths = normalized.get("paths", [])
    if trace_ids:
        segments.append(f"trace_id={','.join(trace_ids[:2])}")
    if error_codes:
        segments.append(f"error_code={','.join(error_codes[:2])}")
    if paths:
        segments.append(f"path={','.join(paths[:2])}")

    if not segments:
        return summary
    suffix = "Critical evidence: " + " | ".join(segments)
    return f"{summary}\n{suffix}"


def _summarize_structured(
    content: str,
    content_type: str,
    *,
    critical_evidence: Optional[Dict[str, list[str]]] = None,
) -> str:
    """生成结构化数据摘要（schema/keys/sample 级别）。"""
    artifact_hint = "[Use artifact_reader to access full content]"
    base_summary = f"Structured data ({content_type})\n{artifact_hint}"
    if content_type == "application/json":
        try:
            import json

            data = json.loads(content)
            if isinstance(data, dict):
                keys = list(data.keys())[:10]
                sample_types = [f"{k}:{type(data.get(k)).__name__}" for k in keys[:3]]
                sample_text = f"; sample_types={sample_types}" if sample_types else ""
                base_summary = (
                    f"JSON object with keys: {keys} (total={len(data)}){sample_text}\n{artifact_hint}"
                )
                return _append_critical_evidence_summary(base_summary, critical_evidence or {})
            if isinstance(data, list):
                sample_suffix = ""
                if data:
                    first_item = data[0]
                    if isinstance(first_item, dict):
                        sample_suffix = f"; sample_item_keys={list(first_item.keys())[:8]}"
                    else:
                        sample_suffix = f"; sample_item_type={type(first_item).__name__}"
                base_summary = f"JSON array with {len(data)} items{sample_suffix}\n{artifact_hint}"
                return _append_critical_evidence_summary(base_summary, critical_evidence or {})
            base_summary = f"JSON scalar ({type(data).__name__})\n{artifact_hint}"
            return _append_critical_evidence_summary(base_summary, critical_evidence or {})
        except Exception:
            pass

    if content_type in {"text/csv", "text/tsv"}:
        delimiter = "," if content_type == "text/csv" else "\t"
        lines = [line for line in content.splitlines() if line.strip()]
        if lines:
            header = [item.strip() for item in lines[0].split(delimiter)]
            row_count = max(len(lines) - 1, 0)
            sample_row = ""
            if row_count > 0:
                sample_cells = [item.strip() for item in lines[1].split(delimiter)[: min(len(header), 6)]]
                sample_row = f"; sample_row={sample_cells}"
            base_summary = f"{content_type} with {row_count} rows and columns={header[:10]}{sample_row}\n{artifact_hint}"

    return _append_critical_evidence_summary(base_summary, critical_evidence or {})


def _generate_fetch_hints(
    content_type: str,
    raw_output: str = "",
    *,
    evidence: Optional[GCEvidence] = None,
) -> list[str]:
    """生成二次读取提示（包含关键证据线索）。"""
    effective_evidence = evidence if evidence is not None else extract_gc_evidence(raw_output, content_type=content_type)
    return build_gc_fetch_hints(effective_evidence, content_type=content_type)
