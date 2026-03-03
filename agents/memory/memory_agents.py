"""Memory Maintenance Utility Agents — Phase 3.5.

Four utility agents that form the memory lifecycle pipeline:
  ① LogScrubber     — deterministic + small-model log cleaning
  ② FormatConverter — deterministic JSONL/raw → standard experience MD
  ③ MemoryCompressor — small-model memory compression for old entries
  ④ ExperienceDistiller — medium-model pattern extraction → domain knowledge

Trigger Matrix:
  LogScrubber      → Dev Agent completes task, before experience write
  FormatConverter  → chained after LogScrubber output
  MemoryCompressor → post-GC / file count ≥ threshold / manual
  ExperienceDistiller → same-tag experience count ≥ threshold
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ① LogScrubber
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+$", re.MULTILINE)


@dataclass
class ScrubResult:
    """Output of LogScrubber."""
    cleaned_text: str
    summary: str
    original_length: int
    cleaned_length: int
    noise_ratio: float  # 0.0 = no noise removed, 1.0 = all noise


class LogScrubber:
    """Deterministic + optional LLM-based log cleaning.

    Phase 1 (always): deterministic noise removal
    Phase 2 (optional): LLM summarization via ``summarizer`` callback

    Usage::

        scrubber = LogScrubber(max_output_chars=2000)
        result = scrubber.scrub(raw_log)
        # or with LLM summarization:
        scrubber = LogScrubber(summarizer=my_llm_summarize_fn)
        result = scrubber.scrub(raw_log)
    """

    def __init__(
        self,
        *,
        max_output_chars: int = 2000,
        max_repeat_lines: int = 3,
        summarizer: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._max_output = max_output_chars
        self._max_repeat = max_repeat_lines
        self._summarizer = summarizer

    def scrub(self, raw_log: str) -> ScrubResult:
        """Clean a raw execution log.

        Returns ScrubResult with cleaned_text + optional summary.
        """
        original_len = len(raw_log)

        # Phase 1: deterministic cleaning
        text = self._strip_ansi(raw_log)
        text = self._collapse_blanks(text)
        text = self._strip_trailing_whitespace(text)
        text = self._deduplicate_lines(text)
        text = self._truncate(text)

        cleaned_len = len(text)
        noise_ratio = 1.0 - (cleaned_len / max(original_len, 1))

        # Phase 2: LLM summarization (if available)
        summary = ""
        if self._summarizer:
            try:
                summary = self._summarizer(text)
            except Exception as exc:
                logger.warning("LogScrubber summarizer failed: %s", exc)
                summary = self._heuristic_summary(text)
        else:
            summary = self._heuristic_summary(text)

        return ScrubResult(
            cleaned_text=text,
            summary=summary,
            original_length=original_len,
            cleaned_length=cleaned_len,
            noise_ratio=round(noise_ratio, 3),
        )

    # ── Deterministic cleaning steps ──

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return _ANSI_RE.sub("", text)

    @staticmethod
    def _collapse_blanks(text: str) -> str:
        return _MULTI_BLANK_RE.sub("\n\n", text)

    @staticmethod
    def _strip_trailing_whitespace(text: str) -> str:
        return _TRAILING_SPACE_RE.sub("", text)

    def _deduplicate_lines(self, text: str) -> str:
        lines = text.splitlines()
        result: List[str] = []
        prev_line = None
        repeat_count = 0

        for line in lines:
            if line == prev_line:
                repeat_count += 1
                if repeat_count == self._max_repeat:
                    result.append(f"  ... (×{repeat_count + 1})")
                elif repeat_count > self._max_repeat:
                    # Update the count marker
                    if result and result[-1].startswith("  ... (×"):
                        result[-1] = f"  ... (×{repeat_count + 1})"
                # Skip line if over the repeat threshold
                continue
            else:
                prev_line = line
                repeat_count = 0
                result.append(line)

        return "\n".join(result)

    def _truncate(self, text: str) -> str:
        if len(text) <= self._max_output:
            return text
        half = self._max_output // 2
        return (
            text[:half]
            + f"\n\n... [截断: 原始 {len(text)} 字符, 显示前后各 {half}] ...\n\n"
            + text[-half:]
        )

    @staticmethod
    def _heuristic_summary(text: str, max_tokens: int = 200) -> str:
        """Extract key lines heuristically (no LLM)."""
        key_patterns = [
            re.compile(r"(?i)(error|exception|traceback|failed|fatal)"),
            re.compile(r"(?i)(success|passed|completed|done|fixed)"),
            re.compile(r"(?i)(created|modified|deleted|updated)"),
        ]
        key_lines: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            for pattern in key_patterns:
                if pattern.search(stripped):
                    key_lines.append(stripped)
                    break

        if not key_lines:
            # Fallback: first 5 non-empty lines
            key_lines = [
                l.strip() for l in text.splitlines()
                if l.strip()
            ][:5]

        summary_text = "\n".join(key_lines[:10])
        # Rough token limit
        if len(summary_text) > max_tokens * 4:
            summary_text = summary_text[: max_tokens * 4] + "..."
        return summary_text


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ② FormatConverter
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class ConvertedExperience:
    """Standard experience format ready for L1 write."""
    name: str
    title: str
    task_id: str
    outcome: str
    problem: str
    solution: str
    files: List[str]
    tags: List[str]


class FormatConverter:
    """Deterministic format converter — no LLM required.

    Converts various input formats into the standard L1 experience schema.

    Usage::

        converter = FormatConverter()
        exp = converter.from_scrub_result(scrub_result, task_id="t-001", ...)
        exp = converter.from_jsonl_record(record)
        exp = converter.from_raw_text(text, task_id="t-002", ...)
    """

    def from_scrub_result(
        self,
        scrub: ScrubResult,
        *,
        name: str,
        task_id: str,
        outcome: str = "success",
        files: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> ConvertedExperience:
        """Convert a ScrubResult into standard experience format."""
        return ConvertedExperience(
            name=name,
            title=name.replace("_", " ").title(),
            task_id=task_id,
            outcome=outcome,
            problem=self._extract_problem(scrub.cleaned_text),
            solution=self._extract_solution(scrub.summary),
            files=files or self._extract_files(scrub.cleaned_text),
            tags=tags or self._extract_tags(scrub.cleaned_text),
        )

    def from_jsonl_record(self, record: Dict[str, Any]) -> ConvertedExperience:
        """Convert a JSONL episodic record to standard format."""
        narrative = str(record.get("narrative_summary", ""))
        hints = record.get("fetch_hints", [])
        source = str(record.get("source_tool", ""))
        session = str(record.get("session_id", ""))

        # Derive a descriptive name from narrative
        name = self._derive_name(narrative)

        return ConvertedExperience(
            name=name,
            title=narrative[:80] if narrative else "Untitled Experience",
            task_id=str(record.get("record_id", session)),
            outcome="success",
            problem="",
            solution=narrative,
            files=[h for h in hints if "." in h and "/" in h],
            tags=[h for h in hints if not ("." in h and "/" in h)][:5],
        )

    def from_raw_text(
        self,
        text: str,
        *,
        name: str,
        task_id: str,
        outcome: str = "success",
        tags: Optional[List[str]] = None,
    ) -> ConvertedExperience:
        """Convert raw unstructured text into standard format."""
        return ConvertedExperience(
            name=name,
            title=name.replace("_", " ").title(),
            task_id=task_id,
            outcome=outcome,
            problem=self._extract_problem(text),
            solution=text[:500],
            files=self._extract_files(text),
            tags=tags or self._extract_tags(text),
        )

    # ── Extraction helpers (deterministic) ──

    _FILE_REF_RE = re.compile(r"`([a-zA-Z0-9_/\\.]+\.[a-z]{1,5})`")
    _TAG_WORD_RE = re.compile(r"\b(refactor|fix|bug|feature|test|deploy|config|api|db)\b", re.I)

    def _extract_files(self, text: str) -> List[str]:
        return list(dict.fromkeys(self._FILE_REF_RE.findall(text)))

    def _extract_tags(self, text: str) -> List[str]:
        tags = list(dict.fromkeys(
            m.lower() for m in self._TAG_WORD_RE.findall(text)
        ))
        return tags[:5]

    @staticmethod
    def _extract_problem(text: str) -> str:
        for line in text.splitlines():
            low = line.strip().lower()
            if any(kw in low for kw in ("error", "fail", "problem", "issue", "bug")):
                return line.strip()[:200]
        return ""

    @staticmethod
    def _extract_solution(text: str) -> str:
        for line in text.splitlines():
            low = line.strip().lower()
            if any(kw in low for kw in ("fix", "solved", "solution", "resolved", "success")):
                return line.strip()[:200]
        return text[:200] if text else ""

    @staticmethod
    def _derive_name(narrative: str) -> str:
        words = re.findall(r"[a-zA-Z_]{3,}", narrative)
        if words:
            return "_".join(words[:4]).lower()
        # CJK fallback
        cjk = re.findall(r"[\u4e00-\u9fff]{2,}", narrative)
        if cjk:
            return "_".join(cjk[:3])
        return "unnamed_experience"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ③ MemoryCompressor
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class CompressionReport:
    """Report from a compression run."""
    files_scanned: int
    files_compressed: int
    files_archived: int
    original_total_chars: int
    compressed_total_chars: int
    compression_ratio: float


class MemoryCompressor:
    """Compresses old episodic memories to reduce token cost.

    Strategies:
    - Merge related experiences (same tag) into summary files
    - Truncate verbose sections (keep core problem/solution, drop details)
    - Archive originals to ``_archive/`` subdirectory

    Usage::

        compressor = MemoryCompressor(
            episodic_dir=Path("memory/episodic"),
            max_age_days=7,
        )
        report = compressor.compress()
    """

    def __init__(
        self,
        episodic_dir: Path,
        *,
        max_age_days: int = 7,
        file_count_threshold: int = 50,
        summarizer: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._episodic_dir = episodic_dir
        self._max_age_days = max_age_days
        self._threshold = file_count_threshold
        self._summarizer = summarizer

    def should_compress(self) -> bool:
        """Check if compression is warranted."""
        if not self._episodic_dir.exists():
            return False
        count = sum(1 for _ in self._episodic_dir.glob("exp_*.md"))
        return count >= self._threshold

    def compress(self) -> CompressionReport:
        """Run compression on old experience files.

        Returns CompressionReport.
        """
        if not self._episodic_dir.exists():
            return CompressionReport(0, 0, 0, 0, 0, 0.0)

        archive_dir = self._episodic_dir / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        exp_files = sorted(self._episodic_dir.glob("exp_*.md"))
        old_files = self._filter_old_files(exp_files)

        original_total = 0
        compressed_total = 0
        archived_count = 0

        # Group by primary tag
        tag_groups: Dict[str, List[Path]] = {}
        for f in old_files:
            content = f.read_text(encoding="utf-8")
            original_total += len(content)
            primary_tag = self._get_primary_tag(content)
            tag_groups.setdefault(primary_tag, []).append(f)

        compressed_count = 0
        for tag, files in tag_groups.items():
            if len(files) < 2:
                continue  # Not worth merging a single file

            merged = self._merge_experiences(files, tag)
            compressed_total += len(merged)
            compressed_count += 1

            # Write merged file
            merge_name = f"compressed_{tag}_{self._today()}.md"
            (self._episodic_dir / merge_name).write_text(merged, encoding="utf-8")

            # Archive originals
            for f in files:
                target = archive_dir / f.name
                f.rename(target)
                archived_count += 1

        ratio = 1.0 - (compressed_total / max(original_total, 1))

        return CompressionReport(
            files_scanned=len(exp_files),
            files_compressed=compressed_count,
            files_archived=archived_count,
            original_total_chars=original_total,
            compressed_total_chars=compressed_total,
            compression_ratio=round(ratio, 3),
        )

    def _filter_old_files(self, files: List[Path]) -> List[Path]:
        """Filter files older than max_age_days by parsing date from filename."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._max_age_days)
        cutoff_str = cutoff.strftime("%Y%m%d")

        old: List[Path] = []
        for f in files:
            # Filename format: exp_YYYYMMDD_slug.md
            match = re.match(r"exp_(\d{8})_", f.name)
            if match and match.group(1) < cutoff_str:
                old.append(f)
        return old

    def _merge_experiences(self, files: List[Path], tag: str) -> str:
        """Merge multiple experience files into a compressed summary."""
        parts = [f"# 压缩经验合集：{tag}\n\n> 合并自 {len(files)} 个经验文件\n"]

        for f in files:
            content = f.read_text(encoding="utf-8")
            # Extract just title and core sections (truncated)
            title = self._extract_title(content)
            problem = self._extract_section(content, "问题")[:150]
            solution = self._extract_section(content, "解决方案")[:150]
            outcome = self._extract_field(content, "outcome")

            parts.append(
                f"\n## {title}\n"
                f"- outcome: {outcome}\n"
                f"- problem: {problem}\n"
                f"- solution: {solution}\n"
            )

        if self._summarizer:
            try:
                full_text = "\n".join(parts)
                return self._summarizer(full_text)
            except Exception:
                pass

        return "\n".join(parts)

    @staticmethod
    def _extract_title(content: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return "untitled"

    @staticmethod
    def _extract_section(content: str, heading: str) -> str:
        lines = content.splitlines()
        capturing = False
        section: List[str] = []
        for line in lines:
            if line.strip().startswith(f"## {heading}"):
                capturing = True
                continue
            if capturing:
                if line.strip().startswith("## "):
                    break
                section.append(line)
        return "\n".join(section).strip()

    @staticmethod
    def _extract_field(content: str, field_name: str) -> str:
        for line in content.splitlines():
            if line.strip().startswith(f"{field_name}:"):
                return line.split(":", 1)[1].strip()
        return ""

    @staticmethod
    def _get_primary_tag(content: str) -> str:
        for line in content.splitlines():
            if line.startswith("tags:"):
                tags = re.findall(r"#([a-zA-Z0-9_\u4e00-\u9fff]+)", line)
                return tags[0] if tags else "other"
        return "other"

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ④ ExperienceDistiller
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class DistillationResult:
    """Result of experience distillation."""
    tag: str
    source_count: int
    domain_file: Optional[Path]
    patterns: List[str]
    rules: List[str]


class ExperienceDistiller:
    """Extracts recurring patterns from related experiences → domain knowledge.

    Analyzes experiences sharing the same tag, finds patterns, and
    writes distilled knowledge to ``memory/domain/``.

    Uses a medium-capability model for reasoning-heavy pattern extraction,
    with a deterministic fallback.

    Usage::

        distiller = ExperienceDistiller(
            episodic_dir=Path("memory/episodic"),
            domain_dir=Path("memory/domain"),
        )
        result = distiller.distill(tag="pipeline")
    """

    def __init__(
        self,
        episodic_dir: Path,
        domain_dir: Path,
        *,
        min_experiences: int = 5,
        distill_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._episodic_dir = episodic_dir
        self._domain_dir = domain_dir
        self._min_experiences = min_experiences
        self._distill_fn = distill_fn

    def should_distill(self, tag: str) -> bool:
        """Check if enough experiences exist for distillation."""
        count = self._count_tag_experiences(tag)
        return count >= self._min_experiences

    def distill(self, tag: str) -> DistillationResult:
        """Distill experiences with the given tag into domain knowledge.

        Returns DistillationResult.
        """
        experiences = self._load_tag_experiences(tag)

        if len(experiences) < self._min_experiences:
            return DistillationResult(
                tag=tag,
                source_count=len(experiences),
                domain_file=None,
                patterns=[],
                rules=[],
            )

        # Extract patterns
        if self._distill_fn:
            try:
                combined = self._combine_experiences(experiences)
                llm_output = self._distill_fn(combined)
                patterns, rules = self._parse_llm_distillation(llm_output)
            except Exception as exc:
                logger.warning("Distillation LLM failed: %s, using heuristic", exc)
                patterns, rules = self._heuristic_distillation(experiences)
        else:
            patterns, rules = self._heuristic_distillation(experiences)

        # Write domain knowledge
        domain_file = self._write_domain_knowledge(tag, patterns, rules, len(experiences))

        return DistillationResult(
            tag=tag,
            source_count=len(experiences),
            domain_file=domain_file,
            patterns=patterns,
            rules=rules,
        )

    def scan_all_tags(self) -> List[str]:
        """Find all tags that meet the distillation threshold."""
        if not self._episodic_dir.exists():
            return []

        tag_counts: Dict[str, int] = {}
        for f in self._episodic_dir.glob("exp_*.md"):
            content = f.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("tags:"):
                    for tag in re.findall(r"#([a-zA-Z0-9_\u4e00-\u9fff]+)", line):
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return [t for t, c in tag_counts.items() if c >= self._min_experiences]

    # ── Internal ──

    def _count_tag_experiences(self, tag: str) -> int:
        if not self._episodic_dir.exists():
            return 0
        count = 0
        for f in self._episodic_dir.glob("exp_*.md"):
            content = f.read_text(encoding="utf-8")
            if f"#{tag}" in content:
                count += 1
        return count

    def _load_tag_experiences(self, tag: str) -> List[Dict[str, str]]:
        experiences: List[Dict[str, str]] = []
        if not self._episodic_dir.exists():
            return experiences

        for f in sorted(self._episodic_dir.glob("exp_*.md")):
            content = f.read_text(encoding="utf-8")
            if f"#{tag}" not in content:
                continue
            experiences.append({
                "filename": f.name,
                "content": content,
            })
        return experiences

    @staticmethod
    def _combine_experiences(experiences: List[Dict[str, str]]) -> str:
        parts = []
        for i, exp in enumerate(experiences, 1):
            parts.append(f"--- Experience {i}: {exp['filename']} ---")
            # Truncate each experience to save tokens
            parts.append(exp["content"][:1000])
        return "\n\n".join(parts)

    @staticmethod
    def _parse_llm_distillation(output: str) -> tuple:
        patterns: List[str] = []
        rules: List[str] = []
        section = None
        for line in output.splitlines():
            stripped = line.strip()
            # Check list items first (before section detection)
            if stripped.startswith("- ") or stripped.startswith("* "):
                item = stripped[2:].strip()
                if section == "patterns":
                    patterns.append(item)
                elif section == "rules":
                    rules.append(item)
                continue
            # Section detection (only for non-list lines)
            if "pattern" in stripped.lower() or "模式" in stripped:
                section = "patterns"
            elif "rule" in stripped.lower() or "规则" in stripped:
                section = "rules"
        return patterns, rules

    @staticmethod
    def _heuristic_distillation(
        experiences: List[Dict[str, str]]
    ) -> tuple:
        """Deterministic fallback: extract common files and outcomes."""
        file_counts: Dict[str, int] = {}
        outcomes: Dict[str, int] = {}
        problems: List[str] = []

        file_re = re.compile(r"`([a-zA-Z0-9_/\\.]+\.[a-z]{1,5})`")
        for exp in experiences:
            content = exp["content"]
            for f in file_re.findall(content):
                file_counts[f] = file_counts.get(f, 0) + 1
            for line in content.splitlines():
                if line.startswith("outcome:"):
                    outcome = line.split(":", 1)[1].strip()
                    outcomes[outcome] = outcomes.get(outcome, 0) + 1
                if line.startswith("## 问题"):
                    idx = content.index(line)
                    next_section = content.find("##", idx + 5)
                    if next_section > 0:
                        problems.append(content[idx:next_section].strip()[:100])

        # Patterns: frequently touched files
        patterns = [
            f"文件 `{f}` 在 {c} 次经验中被修改"
            for f, c in sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            if c >= 2
        ]

        # Rules: derived from common patterns
        rules = []
        if patterns:
            rules.append("修改高频文件时应优先运行相关测试")
        success_rate = outcomes.get("success", 0) / max(sum(outcomes.values()), 1)
        if success_rate < 0.7:
            rules.append("该领域任务失败率较高，建议增加 Review 步骤")

        return patterns, rules

    def _write_domain_knowledge(
        self,
        tag: str,
        patterns: List[str],
        rules: List[str],
        source_count: int,
    ) -> Path:
        self._domain_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._domain_dir / f"distilled_{tag}.md"

        pattern_lines = "\n".join(f"- {p}" for p in patterns) or "- 无明显模式"
        rule_lines = "\n".join(f"- {r}" for r in rules) or "- 无特殊规则"

        content = (
            f"# 领域知识：{tag}\n\n"
            f"> 自动蒸馏自 {source_count} 个经验 | "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"## 反复出现的模式\n{pattern_lines}\n\n"
            f"## 推荐规则\n{rule_lines}\n"
        )
        filepath.write_text(content, encoding="utf-8")
        return filepath


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Pipeline orchestration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run_post_task_pipeline(
    raw_log: str,
    *,
    name: str,
    task_id: str,
    outcome: str = "success",
    files: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    memory_root: Optional[Path] = None,
    scrubber: Optional[LogScrubber] = None,
    converter: Optional[FormatConverter] = None,
) -> ConvertedExperience:
    """Run the full post-task pipeline: scrub → convert → ready for L1 write.

    This is the primary integration point called after a Dev Agent
    completes its task.

    Returns ConvertedExperience ready for ``L1MemoryManager.write_experience()``.
    """
    _scrubber = scrubber or LogScrubber()
    _converter = converter or FormatConverter()

    scrub_result = _scrubber.scrub(raw_log)
    experience = _converter.from_scrub_result(
        scrub_result,
        name=name,
        task_id=task_id,
        outcome=outcome,
        files=files,
        tags=tags,
    )

    logger.info(
        "Post-task pipeline: %s → scrubbed %d→%d chars (noise %.1f%%) → experience ready",
        name, scrub_result.original_length, scrub_result.cleaned_length,
        scrub_result.noise_ratio * 100,
    )

    return experience


__all__ = [
    "CompressionReport",
    "ConvertedExperience",
    "DistillationResult",
    "ExperienceDistiller",
    "FormatConverter",
    "LogScrubber",
    "MemoryCompressor",
    "ScrubResult",
    "run_post_task_pipeline",
]
