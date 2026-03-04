"""
测试基线只读隔离机制

实现 NGA-WS17-001: 测试基线只读隔离
防止测试毒化（Test Poisoning）- 修改测试骗过验证。

参考文档:
- doc/13-security-blindspots-and-hardening.md (R5)
- doc/task/17-ws-quality-release-and-ops-readiness.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set


@dataclass
class TestBaselineConfig:
    """测试基线配置"""
    __test__ = False

    # Golden Suite 目录（只读保护）
    golden_suite_dirs: Set[str]

    # 允许修改的测试目录（工作区测试）
    workspace_test_dirs: Set[str]

    # 审批白名单（允许修改 golden suite 的特殊情况）
    approval_whitelist: Set[str]

    # 项目根目录
    project_root: Path

    @classmethod
    def default(cls, project_root: Optional[Path] = None) -> TestBaselineConfig:
        """默认配置"""
        if project_root is None:
            project_root = Path(__file__).parent.parent

        return cls(
            golden_suite_dirs={
                "tests/critical",    # 关键守护测试（如存在）
                "tests/golden",      # Golden 测试套件（如果存在）
            },
            workspace_test_dirs={
                "tests",             # 通用测试目录
                "tests/integration", # 集成测试
            },
            approval_whitelist=set(),  # 默认无白名单
            project_root=project_root,
        )


class TestBaselineGuard:
    """
    测试基线守卫

    防止测试毒化的核心机制：
    1. Golden Suite 只读保护
    2. 修改检测与拦截
    3. 审批白名单管理
    """
    __test__ = False

    def __init__(self, config: Optional[TestBaselineConfig] = None):
        self.config = config or TestBaselineConfig.default()

    def is_golden_suite_path(self, file_path: str | Path) -> bool:
        """判断是否为 Golden Suite 路径"""
        path = Path(file_path)

        # 转换为相对路径
        try:
            rel_path = path.relative_to(self.config.project_root)
        except ValueError:
            # 不在项目根目录内
            return False

        rel_parts = tuple(part.lower() for part in rel_path.parts)

        # 检查是否在 golden suite 目录内（兼容 Windows/Posix 分隔符）
        for golden_dir in self.config.golden_suite_dirs:
            prefix_parts = tuple(part.lower() for part in Path(golden_dir).parts)
            if rel_parts[: len(prefix_parts)] == prefix_parts:
                return True

        return False

    def is_test_file(self, file_path: str | Path) -> bool:
        """判断是否为测试文件"""
        path = Path(file_path)
        name = path.name

        # 常见测试文件模式
        test_patterns = [
            name.startswith("test_"),
            name.endswith("_test.py"),
            "test" in path.parts,
            "tests" in path.parts,
        ]

        return any(test_patterns)

    def check_modification_allowed(
        self,
        file_path: str | Path,
        requester: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        检查是否允许修改测试文件

        Returns:
            (allowed, reason)
        """
        path = Path(file_path)

        # 非测试文件：允许
        if not self.is_test_file(path):
            return True, "Not a test file"

        # Golden Suite 文件：需要审批
        if self.is_golden_suite_path(path):
            # 检查审批白名单
            if requester and requester in self.config.approval_whitelist:
                return True, f"Approved by whitelist: {requester}"

            return False, (
                f"Golden Suite file modification blocked: {path}\n"
                f"Golden Suite files are read-only to prevent test poisoning.\n"
                f"If you need to modify this file, request approval first."
            )

        # 工作区测试文件：允许
        return True, "Workspace test file"

    def validate_test_changes(
        self,
        changed_files: list[str | Path],
        requester: Optional[str] = None,
    ) -> tuple[bool, list[str]]:
        """
        验证测试文件变更

        Returns:
            (all_allowed, blocked_files)
        """
        blocked_files = []

        for file_path in changed_files:
            allowed, reason = self.check_modification_allowed(file_path, requester)
            if not allowed:
                blocked_files.append(f"{file_path}: {reason}")

        return len(blocked_files) == 0, blocked_files

    def add_to_whitelist(self, requester: str) -> None:
        """添加到审批白名单"""
        self.config.approval_whitelist.add(requester)

    def remove_from_whitelist(self, requester: str) -> None:
        """从审批白名单移除"""
        self.config.approval_whitelist.discard(requester)


class TestPoisoningDetector:
    """
    测试毒化检测器

    检测常见的测试毒化模式：
    1. Assert 弱化（assert True, assert 1==1）
    2. 测试跳过（@pytest.mark.skip）
    3. 异常捕获吞噬（except: pass）
    """
    __test__ = False

    @staticmethod
    def detect_weakened_assertions(test_content: str) -> list[tuple[int, str]]:
        """
        检测弱化的断言

        Returns:
            [(line_number, issue_description), ...]
        """
        issues = []
        lines = test_content.split("\n")

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # 恒真断言
            if "assert True" in stripped and not stripped.startswith("#"):
                issues.append((line_num, "Weakened assertion: assert True"))

            if "assert 1 == 1" in stripped and not stripped.startswith("#"):
                issues.append((line_num, "Weakened assertion: assert 1 == 1"))

            # 空断言
            if stripped == "assert" or stripped == "assert()":
                issues.append((line_num, "Empty assertion"))

            # Pass 替代断言
            if stripped.startswith("# assert"):
                next_line = lines[line_num].strip() if line_num < len(lines) else ""
                if next_line.startswith("pass"):
                    issues.append((line_num, "Commented out assertion with pass"))

        return issues

    @staticmethod
    def detect_test_skipping(test_content: str) -> list[tuple[int, str]]:
        """检测测试跳过"""
        issues = []
        lines = test_content.split("\n")

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # pytest skip 装饰器
            if "@pytest.mark.skip" in stripped:
                issues.append((line_num, "Test skipped with @pytest.mark.skip"))

            if "@unittest.skip" in stripped:
                issues.append((line_num, "Test skipped with @unittest.skip"))

        return issues

    @staticmethod
    def detect_exception_swallowing(test_content: str) -> list[tuple[int, str]]:
        """检测异常吞噬"""
        issues = []
        lines = test_content.split("\n")

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # except ...: 后第一条有效语句是 pass，视为异常吞噬
            if not stripped.startswith("except") or ":" not in stripped:
                continue

            next_index = line_num
            while next_index < len(lines):
                next_line = lines[next_index].strip()
                if not next_line or next_line.startswith("#"):
                    next_index += 1
                    continue
                if next_line.startswith("pass"):
                    issues.append((line_num, "Exception swallowing: except ... pass"))
                break

        return issues

    def analyze_test_file(self, file_path: str | Path) -> dict[str, list[tuple[int, str]]]:
        """
        分析测试文件，检测所有毒化模式

        Returns:
            {
                "weakened_assertions": [...],
                "test_skipping": [...],
                "exception_swallowing": [...],
            }
        """
        path = Path(file_path)

        if not path.exists():
            return {}

        content: Optional[str] = None
        for encoding in ("utf-8", "gbk", "cp936"):
            try:
                content = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
            except Exception:
                return {}
        if content is None:
            return {}

        return {
            "weakened_assertions": self.detect_weakened_assertions(content),
            "test_skipping": self.detect_test_skipping(content),
            "exception_swallowing": self.detect_exception_swallowing(content),
        }

    def has_poisoning_patterns(self, analysis: dict[str, list[tuple[int, str]]]) -> bool:
        """判断是否存在毒化模式"""
        return any(len(issues) > 0 for issues in analysis.values())


def check_test_baseline_compliance(
    changed_files: list[str | Path],
    requester: Optional[str] = None,
) -> tuple[bool, str]:
    """
    检查测试基线合规性

    这是对外的统一入口函数。

    Returns:
        (compliant, report)
    """
    guard = TestBaselineGuard()
    detector = TestPoisoningDetector()

    # 1. 检查 Golden Suite 修改权限
    allowed, blocked_files = guard.validate_test_changes(changed_files, requester)

    if not allowed:
        report = "❌ Golden Suite Modification Blocked\n\n"
        report += "\n".join(blocked_files)
        return False, report

    # 2. 检测测试毒化模式
    poisoning_issues = []

    for file_path in changed_files:
        if not guard.is_test_file(file_path):
            continue

        analysis = detector.analyze_test_file(file_path)

        if detector.has_poisoning_patterns(analysis):
            poisoning_issues.append(f"\n📄 {file_path}:")

            for category, issues in analysis.items():
                if issues:
                    poisoning_issues.append(f"  {category}:")
                    for line_num, desc in issues:
                        poisoning_issues.append(f"    Line {line_num}: {desc}")

    if poisoning_issues:
        report = "⚠️  Test Poisoning Patterns Detected\n"
        report += "\n".join(poisoning_issues)
        report += "\n\nPlease review these changes carefully."
        return False, report

    # 3. 全部通过
    report = "✅ Test Baseline Compliance Check Passed\n"
    report += f"Checked {len(changed_files)} file(s), no issues found."
    return True, report


# 导出公共接口
__all__ = [
    "TestBaselineConfig",
    "TestBaselineGuard",
    "TestPoisoningDetector",
    "check_test_baseline_compliance",
]
