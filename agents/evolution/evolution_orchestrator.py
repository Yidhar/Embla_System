"""Evolution Orchestrator — closed-loop self-improvement pipeline.

Lifecycle per cycle:
  1. Perceive  — PatternDetector found failure clusters (done by EvolutionTrigger)
  2. Attribute — LLM reads failure episodes + current prompt → root cause
  3. Propose   — LLM drafts improved prompt content
  4. Execute   — prompt_mutator writes with safety gates (ACL, injection, backup, audit)
  5. Verify    — next cycle checks if same failures recur; auto-rollback if worse

All LLM calls use litellm.completion (sync) so the orchestrator can run
inside Chronos APScheduler threads without touching the FastAPI event loop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Mutation history persistence ──────────────────────────────
_DEFAULT_MUTATIONS_PATH = Path("scratch/runtime/evolution_mutations.jsonl")
_DEFAULT_PROPOSALS_PATH = Path("scratch/runtime/evolution_proposals.jsonl")


# ── Data classes ──────────────────────────────────────────────

@dataclass
class Attribution:
    """LLM-produced root cause analysis for a failure cluster."""
    root_cause: str
    category: str  # prompt_gap | tool_missing | config_issue | upstream_dependency | not_actionable
    target_file: str
    confidence: float
    reasoning: str = ""


@dataclass
class Proposal:
    """LLM-produced prompt improvement."""
    target_path: str
    new_content: str
    diff_description: str
    reason: str
    attribution: Attribution


@dataclass
class MutationRecord:
    """Persisted record of an applied mutation for verification."""
    change_id: str
    target_path: str
    cluster_key: str
    applied_at: str
    before_hash: str
    after_hash: str
    rollback_path: str
    failure_count_at_apply: int
    verified: bool = False
    verification_result: str = ""  # improved | no_change | regressed | rolled_back


@dataclass
class CycleResult:
    """Summary of one evolution cycle."""
    acted: bool = False
    attributions: List[Attribution] = field(default_factory=list)
    proposals: List[Proposal] = field(default_factory=list)
    applied_count: int = 0
    skipped_count: int = 0
    queued_count: int = 0
    errors: List[str] = field(default_factory=list)


# ── Orchestrator ──────────────────────────────────────────────

class EvolutionOrchestrator:
    """Central coordinator for the self-improvement loop."""

    # Categories that justify prompt mutation
    _ACTIONABLE_CATEGORIES = frozenset({"prompt_gap", "tool_missing", "config_issue"})

    def __init__(
        self,
        *,
        episodic_dir: Path = Path("memory/episodic"),
        prompts_root: Optional[Path] = None,
        project_root: Path = Path("."),
        config: Optional[Dict[str, Any]] = None,
        event_emitter: Any = None,
    ):
        self._episodic_dir = Path(episodic_dir)
        if prompts_root is not None:
            self._prompts_root = Path(prompts_root)
        else:
            from agents.prompt_engine import get_system_prompts_root
            self._prompts_root = Path(get_system_prompts_root())
        self._project_root = Path(project_root)
        self._event_emitter = event_emitter

        cfg = config or {}
        self._auto_approve = bool(cfg.get("auto_approve", False))
        self._allowed_scopes = list(cfg.get("allowed_scopes", ["roles", "skills", "styles", "rules"]))
        self._cooldown_minutes = int(cfg.get("cooldown_minutes", 30))
        self._mutations_path = _DEFAULT_MUTATIONS_PATH
        self._proposals_path = _DEFAULT_PROPOSALS_PATH

    # ── Public API ────────────────────────────────────────────

    def run_cycle(self, signals: list) -> CycleResult:
        """Run one full evolution cycle: attribute → propose → execute/queue."""
        from agents.evolution.pattern_detector import EvolutionTriggerSignal

        result = CycleResult()

        # Verify previous mutations first
        try:
            self._verify_previous_mutations()
        except Exception as exc:
            logger.debug("Verification of previous mutations failed: %s", exc)

        for signal in signals:
            if not isinstance(signal, EvolutionTriggerSignal):
                continue

            # Skip if recently mutated (cooldown)
            if self._is_in_cooldown(signal.task_type):
                result.skipped_count += 1
                logger.debug("Skipping signal %s — in cooldown", signal.task_type)
                continue

            try:
                # Step 1: Read failure episodes
                episodes = self._read_failure_episodes(signal.sample_files)
                if not episodes:
                    result.skipped_count += 1
                    continue

                # Step 2: Attribute — LLM root cause analysis
                attribution = self._attribute(signal, episodes)
                result.attributions.append(attribution)

                if attribution.category not in self._ACTIONABLE_CATEGORIES:
                    logger.info(
                        "进化归因: %s → %s (不可操作, 跳过)",
                        signal.task_type, attribution.category,
                    )
                    result.skipped_count += 1
                    continue

                if attribution.confidence < 0.4:
                    logger.info("进化归因置信度过低 (%.2f), 跳过", attribution.confidence)
                    result.skipped_count += 1
                    continue

                # Check scope
                if not self._is_allowed_scope(attribution.target_file):
                    logger.info("Target %s not in allowed scopes %s", attribution.target_file, self._allowed_scopes)
                    result.skipped_count += 1
                    continue

                # Step 3: Read current prompt
                current_content = self._read_prompt(attribution.target_file)
                if current_content is None:
                    result.errors.append(f"Cannot read prompt: {attribution.target_file}")
                    continue

                # Step 4: Propose — LLM draft improvement
                proposal = self._propose(attribution, current_content, episodes)
                result.proposals.append(proposal)

                # Step 5: Execute or queue
                if self._auto_approve:
                    ok = self._execute(proposal, signal)
                    if ok:
                        result.applied_count += 1
                        result.acted = True
                    else:
                        result.errors.append(f"Mutation failed for {proposal.target_path}")
                else:
                    self._queue_proposal(proposal, signal)
                    result.queued_count += 1

            except Exception as exc:
                logger.warning("Evolution cycle error for signal %s: %s", signal.task_type, exc)
                result.errors.append(f"{signal.task_type}: {exc}")

        # Emit summary event
        self._emit_cycle_event(result)
        return result

    # ── Step 2: Attribution (LLM) ─────────────────────────────

    def _attribute(self, signal, episodes: List[Dict[str, str]]) -> Attribution:
        """LLM analyzes failure episodes to find root cause."""
        episodes_text = "\n\n---\n\n".join(
            f"File: {ep['filename']}\n{ep['content'][:1500]}" for ep in episodes[:5]
        )

        # Read the suggested target prompt for context
        target_path = signal.suggested_targets[0] if signal.suggested_targets else "roles/backend_expert.md"
        target_content = self._read_prompt(target_path)
        target_preview = (target_content[:2000] + "...") if target_content and len(target_content) > 2000 else (target_content or "(file not found)")

        system_prompt = (
            "你是 Embla System 的进化分析引擎。分析以下失败经验记录，找出根因。\n\n"
            "分类必须是以下之一:\n"
            "- prompt_gap: Agent 的 prompt 缺少关键指导（如缺少错误处理策略、缺少领域知识）\n"
            "- tool_missing: Agent 缺少完成任务所需的工具\n"
            "- config_issue: 配置参数不合理（超时、重试次数等）\n"
            "- upstream_dependency: 外部依赖问题（API 不稳定、网络波动）— 系统无法改善\n"
            "- not_actionable: 一次性问题或无法归因\n\n"
            "回复 JSON 格式:\n"
            '{"root_cause": "简短描述", "category": "分类", "target_file": "建议修改的prompt文件路径", '
            '"confidence": 0.0-1.0, "reasoning": "分析推理过程"}'
        )

        user_prompt = (
            f"## 失败模式\n"
            f"聚类: {signal.task_type}\n"
            f"失败次数: {signal.failure_count}\n"
            f"建议目标: {', '.join(signal.suggested_targets)}\n\n"
            f"## 失败经验记录\n{episodes_text}\n\n"
            f"## 当前 Prompt 内容 ({target_path})\n{target_preview}"
        )

        response = self._llm_call(system_prompt, user_prompt)
        return self._parse_attribution(response, fallback_target=target_path)

    # ── Step 4: Proposal (LLM) ────────────────────────────────

    def _propose(self, attribution: Attribution, current_content: str, episodes: List[Dict[str, str]]) -> Proposal:
        """LLM drafts improved prompt content based on attribution."""
        failure_summaries = "\n".join(
            f"- {ep.get('filename', '?')}: {ep.get('content', '')[:200]}" for ep in episodes[:3]
        )

        system_prompt = (
            "你是 Embla System 的 Prompt 优化引擎。根据失败归因结果，改进 prompt 内容。\n\n"
            "要求:\n"
            "1. 保留原始 prompt 的核心职责和结构\n"
            "2. 只添加/修改与失败原因直接相关的部分\n"
            "3. 改动要具体可执行，不要添加空洞的指导\n"
            "4. 输出完整的修改后 prompt（不是 diff）\n"
            "5. 不要添加 '忽略之前的指令' 等注入内容\n\n"
            "回复 JSON 格式:\n"
            '{"new_content": "完整的修改后prompt内容", "diff_description": "改了什么的一行描述"}'
        )

        user_prompt = (
            f"## 归因结果\n"
            f"根因: {attribution.root_cause}\n"
            f"分类: {attribution.category}\n"
            f"目标文件: {attribution.target_file}\n"
            f"置信度: {attribution.confidence}\n\n"
            f"## 失败案例摘要\n{failure_summaries}\n\n"
            f"## 当前 Prompt 内容\n```\n{current_content}\n```"
        )

        response = self._llm_call(system_prompt, user_prompt)
        parsed = self._parse_json_response(response)

        new_content = str(parsed.get("new_content") or "").strip()
        if not new_content:
            # Fallback: append a guidance section to existing content
            new_content = current_content + (
                f"\n\n## 自动改进 ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n"
                f"根据 {attribution.root_cause} 的分析，建议关注以下方面:\n"
                f"- {attribution.reasoning[:200]}\n"
            )

        return Proposal(
            target_path=attribution.target_file,
            new_content=new_content,
            diff_description=str(parsed.get("diff_description") or attribution.root_cause),
            reason=f"[auto-evolution] {attribution.root_cause}",
            attribution=attribution,
        )

    # ── Step 5: Execute ───────────────────────────────────────

    def _execute(self, proposal: Proposal, signal) -> bool:
        """Apply mutation via prompt_mutator with full safety pipeline."""
        from agents.evolution.prompt_mutator import update_my_prompt

        result = update_my_prompt(
            prompt_path=proposal.target_path,
            new_content=proposal.new_content,
            reason=proposal.reason,
            project_root=self._project_root,
            prompts_root=self._prompts_root,
        )

        if result.success:
            logger.info(
                "进化变更已应用: %s (change_id=%s, reason=%s)",
                proposal.target_path, result.change_id, proposal.diff_description,
            )
            self._record_mutation(MutationRecord(
                change_id=result.change_id,
                target_path=proposal.target_path,
                cluster_key=signal.task_type,
                applied_at=datetime.now(timezone.utc).isoformat(),
                before_hash=result.before_hash,
                after_hash=result.after_hash,
                rollback_path=result.rollback_path,
                failure_count_at_apply=signal.failure_count,
            ))
        else:
            logger.warning("进化变更被拒绝: %s — %s", proposal.target_path, result.reason)

        return result.success

    # ── Proposal queue (for auto_approve=false) ───────────────

    def _queue_proposal(self, proposal: Proposal, signal) -> None:
        """Write proposal to pending queue for human review."""
        self._proposals_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "target_path": proposal.target_path,
            "diff_description": proposal.diff_description,
            "reason": proposal.reason,
            "cluster_key": signal.task_type,
            "failure_count": signal.failure_count,
            "attribution": {
                "root_cause": proposal.attribution.root_cause,
                "category": proposal.attribution.category,
                "confidence": proposal.attribution.confidence,
                "reasoning": proposal.attribution.reasoning,
            },
            "new_content_sha256": hashlib.sha256(proposal.new_content.encode()).hexdigest(),
            "new_content_preview": proposal.new_content[:500],
            "new_content": proposal.new_content,
            "status": "pending",
        }
        with open(self._proposals_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("进化提案已排队等待审批: %s → %s", signal.task_type, proposal.target_path)

    def approve_proposal(self, proposal_index: int) -> bool:
        """Approve and execute a pending proposal by its line index."""
        proposals = self._load_proposals()
        if proposal_index < 0 or proposal_index >= len(proposals):
            return False
        entry = proposals[proposal_index]
        if entry.get("status") != "pending":
            return False

        from agents.evolution.prompt_mutator import update_my_prompt
        result = update_my_prompt(
            prompt_path=entry["target_path"],
            new_content=entry["new_content"],
            reason=entry["reason"],
            project_root=self._project_root,
            prompts_root=self._prompts_root,
        )
        entry["status"] = "approved" if result.success else "rejected"
        entry["executed_at"] = datetime.now(timezone.utc).isoformat()
        entry["change_id"] = result.change_id
        if result.success:
            self._record_mutation(MutationRecord(
                change_id=result.change_id,
                target_path=entry["target_path"],
                cluster_key=entry["cluster_key"],
                applied_at=entry["executed_at"],
                before_hash=result.before_hash,
                after_hash=result.after_hash,
                rollback_path=result.rollback_path,
                failure_count_at_apply=entry.get("failure_count", 0),
            ))
        self._save_proposals(proposals)
        return result.success

    def list_pending_proposals(self) -> List[Dict[str, Any]]:
        """Return all pending proposals for dashboard display."""
        return [p for p in self._load_proposals() if p.get("status") == "pending"]

    # ── Verification (called at start of each cycle) ──────────

    def _verify_previous_mutations(self) -> None:
        """Check if previous mutations improved outcomes. Auto-rollback if worse."""
        from agents.evolution.pattern_detector import PatternDetector

        mutations = self._load_mutations()
        unverified = [m for m in mutations if not m.get("verified")]
        if not unverified:
            return

        detector = PatternDetector(episodic_dir=self._episodic_dir, trigger_threshold=1)

        for mutation in unverified:
            cluster_key = mutation.get("cluster_key", "")
            old_count = int(mutation.get("failure_count_at_apply", 0))

            # Count current failures for the same cluster
            signals = detector.check_recent(limit=50)
            current_count = 0
            for sig in signals:
                if sig.task_type == cluster_key:
                    current_count = sig.failure_count
                    break

            if current_count > old_count:
                # Regression — auto-rollback
                rollback_path = mutation.get("rollback_path", "")
                if rollback_path and Path(rollback_path).exists():
                    target_full = self._prompts_root / mutation["target_path"]
                    import shutil
                    shutil.copy2(rollback_path, str(target_full))
                    mutation["verified"] = True
                    mutation["verification_result"] = "rolled_back"
                    logger.warning(
                        "进化回滚: %s (failures %d→%d, rolled back)",
                        mutation["target_path"], old_count, current_count,
                    )
                    self._emit_event("EvolutionRolledBack", {
                        "change_id": mutation.get("change_id"),
                        "target_path": mutation.get("target_path"),
                        "reason": f"regression: {old_count}→{current_count} failures",
                    })
                else:
                    mutation["verified"] = True
                    mutation["verification_result"] = "regressed"
                    logger.warning("进化回归但无法回滚: %s", mutation["target_path"])
            elif current_count < old_count:
                mutation["verified"] = True
                mutation["verification_result"] = "improved"
                logger.info(
                    "进化验证通过: %s (failures %d→%d)",
                    mutation["target_path"], old_count, current_count,
                )
                self._emit_event("EvolutionVerified", {
                    "change_id": mutation.get("change_id"),
                    "target_path": mutation.get("target_path"),
                    "improvement": f"{old_count}→{current_count} failures",
                })
            else:
                # No change — check if enough time has passed (2 evaluation cycles = 2 hours)
                applied_at = mutation.get("applied_at", "")
                try:
                    applied_time = datetime.fromisoformat(applied_at)
                    elapsed_hours = (datetime.now(timezone.utc) - applied_time).total_seconds() / 3600
                    if elapsed_hours >= 2.0:
                        mutation["verified"] = True
                        mutation["verification_result"] = "no_change"
                        logger.info("进化无变化: %s (2h elapsed, marking verified)", mutation["target_path"])
                except Exception:
                    pass

        self._save_mutations(mutations)

    # ── LLM call (sync, via litellm) ──────────────────────────

    def _llm_call(self, system_prompt: str, user_prompt: str) -> str:
        """Sync LLM call using litellm.completion — runs in Chronos thread."""
        try:
            from system.config import get_config
            cfg = get_config()
            api_key = cfg.api.api_key
            api_base = cfg.api.base_url
            model = cfg.api.model
        except Exception:
            logger.warning("Cannot read LLM config for evolution, using defaults")
            return ""

        # Normalize model name for litellm
        model_name = str(model or "").strip()
        if model_name and "/" not in model_name:
            model_name = f"openai/{model_name}"

        try:
            import litellm
            response = litellm.completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
                api_key=api_key,
                api_base=api_base,
                timeout=60,
                num_retries=2,
            )
            return str(response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.warning("Evolution LLM call failed: %s", exc)
            return ""

    # ── Helpers ────────────────────────────────────────────────

    def _read_failure_episodes(self, filenames: List[str]) -> List[Dict[str, str]]:
        """Read episodic memory files by filename."""
        episodes = []
        for fn in filenames:
            fp = self._episodic_dir / fn
            if fp.exists():
                try:
                    episodes.append({"filename": fn, "content": fp.read_text(encoding="utf-8")})
                except Exception:
                    pass
        return episodes

    def _read_prompt(self, prompt_path: str) -> Optional[str]:
        """Read a prompt file from the prompts root."""
        normalized = prompt_path.replace("\\", "/").strip("/")
        full_path = self._prompts_root / normalized
        if not full_path.exists():
            return None
        try:
            return full_path.read_text(encoding="utf-8")
        except Exception:
            return None

    def _is_allowed_scope(self, target_path: str) -> bool:
        """Check if target path falls within allowed evolution scopes."""
        normalized = target_path.replace("\\", "/").strip("/").lower()
        return any(normalized.startswith(scope) for scope in self._allowed_scopes)

    def _is_in_cooldown(self, cluster_key: str) -> bool:
        """Check if a cluster was recently mutated and is in cooldown."""
        mutations = self._load_mutations()
        now = datetime.now(timezone.utc)
        for m in reversed(mutations):
            if m.get("cluster_key") != cluster_key:
                continue
            try:
                applied = datetime.fromisoformat(m["applied_at"])
                elapsed_min = (now - applied).total_seconds() / 60
                if elapsed_min < self._cooldown_minutes:
                    return True
            except Exception:
                pass
        return False

    def _parse_attribution(self, response: str, fallback_target: str) -> Attribution:
        """Parse LLM attribution response."""
        parsed = self._parse_json_response(response)
        return Attribution(
            root_cause=str(parsed.get("root_cause") or "unknown"),
            category=str(parsed.get("category") or "not_actionable"),
            target_file=str(parsed.get("target_file") or fallback_target),
            confidence=min(1.0, max(0.0, float(parsed.get("confidence") or 0.0))),
            reasoning=str(parsed.get("reasoning") or ""),
        )

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Extract JSON from LLM response (handles markdown code blocks)."""
        text = response.strip()
        # Strip markdown code fences
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                if cleaned.startswith("{"):
                    text = cleaned
                    break
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in text
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return {}

    # ── Persistence ───────────────────────────────────────────

    def _record_mutation(self, record: MutationRecord) -> None:
        self._mutations_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "change_id": record.change_id,
            "target_path": record.target_path,
            "cluster_key": record.cluster_key,
            "applied_at": record.applied_at,
            "before_hash": record.before_hash,
            "after_hash": record.after_hash,
            "rollback_path": record.rollback_path,
            "failure_count_at_apply": record.failure_count_at_apply,
            "verified": record.verified,
            "verification_result": record.verification_result,
        }
        with open(self._mutations_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load_mutations(self) -> List[Dict[str, Any]]:
        if not self._mutations_path.exists():
            return []
        entries = []
        for line in self._mutations_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries

    def _save_mutations(self, mutations: List[Dict[str, Any]]) -> None:
        self._mutations_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._mutations_path, "w", encoding="utf-8") as f:
            for m in mutations:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def _load_proposals(self) -> List[Dict[str, Any]]:
        if not self._proposals_path.exists():
            return []
        entries = []
        for line in self._proposals_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries

    def _save_proposals(self, proposals: List[Dict[str, Any]]) -> None:
        self._proposals_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._proposals_path, "w", encoding="utf-8") as f:
            for p in proposals:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._event_emitter:
            try:
                self._event_emitter.emit(event_type, payload, source="evolution_orchestrator", severity="info")
            except Exception:
                pass

    def _emit_cycle_event(self, result: CycleResult) -> None:
        self._emit_event("EvolutionCycleCompleted", {
            "acted": result.acted,
            "applied_count": result.applied_count,
            "queued_count": result.queued_count,
            "skipped_count": result.skipped_count,
            "error_count": len(result.errors),
            "attributions": [
                {"category": a.category, "confidence": a.confidence, "target": a.target_file}
                for a in result.attributions
            ],
        })
