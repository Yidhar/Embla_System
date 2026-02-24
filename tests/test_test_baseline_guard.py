"""
测试 Test Baseline Guard

验收标准（NGA-WS17-001）:
- 被测任务无法直接改写裁判测试
"""

import pytest
from pathlib import Path
from system.test_baseline_guard import (
    TestBaselineConfig,
    TestBaselineGuard,
    TestPoisoningDetector,
    check_test_baseline_compliance,
)


class TestTestBaselineGuard:
    """测试 TestBaselineGuard"""

    def test_default_config(self):
        """测试默认配置"""
        config = TestBaselineConfig.default()

        assert "autonomous/tests" in config.golden_suite_dirs
        assert "tests" in config.workspace_test_dirs
        assert len(config.approval_whitelist) == 0

    def test_is_golden_suite_path(self, tmp_path):
        """测试 Golden Suite 路径判断"""
        config = TestBaselineConfig.default(project_root=tmp_path)
        guard = TestBaselineGuard(config)

        # Golden Suite 路径
        golden_path = tmp_path / "autonomous" / "tests" / "test_example.py"
        assert guard.is_golden_suite_path(golden_path)

        # 非 Golden Suite 路径
        workspace_path = tmp_path / "tests" / "test_example.py"
        assert not guard.is_golden_suite_path(workspace_path)

    def test_is_test_file(self):
        """测试文件判断"""
        guard = TestBaselineGuard()

        # 测试文件
        assert guard.is_test_file("test_example.py")
        assert guard.is_test_file("example_test.py")
        assert guard.is_test_file("tests/test_example.py")

        # 非测试文件
        assert not guard.is_test_file("example.py")
        assert not guard.is_test_file("src/main.py")

    def test_check_modification_allowed_workspace(self, tmp_path):
        """测试工作区测试文件修改（允许）"""
        config = TestBaselineConfig.default(project_root=tmp_path)
        guard = TestBaselineGuard(config)

        workspace_test = tmp_path / "tests" / "test_example.py"
        allowed, reason = guard.check_modification_allowed(workspace_test)

        assert allowed is True
        assert "Workspace test file" in reason

    def test_check_modification_blocked_golden(self, tmp_path):
        """测试 Golden Suite 文件修改（阻止）"""
        config = TestBaselineConfig.default(project_root=tmp_path)
        guard = TestBaselineGuard(config)

        golden_test = tmp_path / "autonomous" / "tests" / "test_example.py"
        allowed, reason = guard.check_modification_allowed(golden_test)

        assert allowed is False
        assert "Golden Suite file modification blocked" in reason
        assert "test poisoning" in reason.lower()

    def test_check_modification_with_whitelist(self, tmp_path):
        """测试审批白名单（允许）"""
        config = TestBaselineConfig.default(project_root=tmp_path)
        guard = TestBaselineGuard(config)

        # 添加到白名单
        guard.add_to_whitelist("admin_user")

        golden_test = tmp_path / "autonomous" / "tests" / "test_example.py"
        allowed, reason = guard.check_modification_allowed(golden_test, requester="admin_user")

        assert allowed is True
        assert "Approved by whitelist" in reason

    def test_validate_test_changes(self, tmp_path):
        """测试批量验证"""
        config = TestBaselineConfig.default(project_root=tmp_path)
        guard = TestBaselineGuard(config)

        changed_files = [
            tmp_path / "tests" / "test_a.py",  # 允许
            tmp_path / "autonomous" / "tests" / "test_b.py",  # 阻止
            tmp_path / "src" / "main.py",  # 非测试文件，允许
        ]

        all_allowed, blocked_files = guard.validate_test_changes(changed_files)

        assert all_allowed is False
        assert len(blocked_files) == 1
        assert "test_b.py" in blocked_files[0]


class TestTestPoisoningDetector:
    """测试 TestPoisoningDetector"""

    def test_detect_weakened_assertions(self):
        """测试弱化断言检测"""
        detector = TestPoisoningDetector()

        test_content = """
def test_example():
    assert True  # 弱化断言
    assert 1 == 1  # 弱化断言
    assert result == expected  # 正常断言
"""

        issues = detector.detect_weakened_assertions(test_content)

        assert len(issues) == 2
        assert any("assert True" in desc for _, desc in issues)
        assert any("assert 1 == 1" in desc for _, desc in issues)

    def test_detect_test_skipping(self):
        """测试跳过检测"""
        detector = TestPoisoningDetector()

        test_content = """
@pytest.mark.skip(reason="temporarily disabled")
def test_example():
    pass

def test_normal():
    assert True
"""

        issues = detector.detect_test_skipping(test_content)

        assert len(issues) == 1
        assert "pytest.mark.skip" in issues[0][1]

    def test_detect_exception_swallowing(self):
        """测试异常吞噬检测"""
        detector = TestPoisoningDetector()

        test_content = """
def test_example():
    try:
        risky_operation()
    except:
        pass  # 吞噬异常
"""

        issues = detector.detect_exception_swallowing(test_content)

        assert len(issues) == 1
        assert "Exception swallowing" in issues[0][1]

    def test_analyze_test_file(self, tmp_path):
        """测试文件分析"""
        detector = TestPoisoningDetector()

        test_file = tmp_path / "test_example.py"
        test_file.write_text("""
def test_poisoned():
    assert True  # 弱化

@pytest.mark.skip
def test_skipped():
    pass
""")

        analysis = detector.analyze_test_file(test_file)

        assert len(analysis["weakened_assertions"]) == 1
        assert len(analysis["test_skipping"]) == 1
        assert detector.has_poisoning_patterns(analysis)


class TestCheckTestBaselineCompliance:
    """测试统一入口函数"""

    def test_compliance_check_passed(self, tmp_path):
        """测试合规检查通过"""
        # 创建工作区测试文件
        test_file = tmp_path / "tests" / "test_example.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("""
def test_normal():
    assert result == expected
""")

        compliant, report = check_test_baseline_compliance([test_file])

        assert compliant is True
        assert "Passed" in report

    def test_compliance_check_golden_blocked(self, tmp_path):
        """测试 Golden Suite 修改被阻止"""
        # 创建 Golden Suite 测试文件
        test_file = tmp_path / "autonomous" / "tests" / "test_example.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("""
def test_normal():
    assert result == expected
""")

        # 修改 TestBaselineGuard 的 project_root
        import system.test_baseline_guard as guard_module
        original_default = guard_module.TestBaselineConfig.default

        def patched_default(project_root=None):
            return original_default(project_root=tmp_path)

        guard_module.TestBaselineConfig.default = patched_default

        try:
            compliant, report = check_test_baseline_compliance([test_file])

            assert compliant is False
            assert "Golden Suite Modification Blocked" in report
        finally:
            guard_module.TestBaselineConfig.default = original_default

    def test_compliance_check_poisoning_detected(self, tmp_path):
        """测试毒化模式检测"""
        # 创建带毒化模式的测试文件
        test_file = tmp_path / "tests" / "test_poisoned.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("""
def test_poisoned():
    assert True  # 弱化断言

@pytest.mark.skip
def test_skipped():
    pass
""")

        compliant, report = check_test_baseline_compliance([test_file])

        assert compliant is False
        assert "Test Poisoning Patterns Detected" in report
        assert "weakened_assertions" in report
        assert "test_skipping" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
