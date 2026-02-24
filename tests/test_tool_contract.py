"""
测试 Tool Contract 统一字段模型

验收标准（NGA-WS10-001）:
- native_call 与 mcp_call 返回字段一致性检查通过
"""

from pathlib import Path
import uuid

import pytest
from system.artifact_store import ArtifactStore, ArtifactStoreConfig
import system.artifact_store as artifact_store_module
from system.tool_contract import (
    ExecutionScope,
    RiskLevel,
    ToolCallEnvelope,
    ToolResultEnvelope,
    build_tool_result_with_artifact,
)


class TestToolCallEnvelope:
    """测试工具调用契约封装"""

    def test_default_creation(self):
        """测试默认创建"""
        envelope = ToolCallEnvelope(tool_name="test_tool")

        assert envelope.tool_name == "test_tool"
        assert envelope.call_id.startswith("call_")
        assert envelope.trace_id.startswith("trace_")
        assert envelope.risk_level == RiskLevel.READ_ONLY
        assert envelope.execution_scope == ExecutionScope.LOCAL
        assert envelope.requires_global_mutex is False

    def test_from_legacy_call_native(self):
        """测试从旧格式 native_call 转换"""
        legacy_call = {
            "agentType": "native",
            "tool_name": "read_file",
            "_tool_call_id": "call_123",
            "arguments": {"path": "/test/file.txt"},
        }

        envelope = ToolCallEnvelope.from_legacy_call(
            legacy_call,
            session_id="session_456",
            trace_id="trace_789",
        )

        assert envelope.tool_name == "read_file"
        assert envelope.call_id == "call_123"
        assert envelope.trace_id == "trace_789"
        assert envelope.session_id == "session_456"
        assert envelope.risk_level == RiskLevel.READ_ONLY
        assert envelope.validated_args == {"path": "/test/file.txt"}

    def test_from_legacy_call_mcp(self):
        """测试从旧格式 mcp_call 转换"""
        legacy_call = {
            "agentType": "mcp",
            "service_name": "game_guide",
            "tool_name": "ask_guide",
            "_tool_call_id": "mcp_call_abc",
            "arguments": {"question": "test"},
        }

        envelope = ToolCallEnvelope.from_legacy_call(legacy_call)

        assert envelope.tool_name == "ask_guide"
        assert envelope.call_id == "mcp_call_abc"
        assert envelope.risk_level == RiskLevel.READ_ONLY

    def test_risk_level_inference(self):
        """测试风险等级推断"""
        # 只读工具
        read_call = {"tool_name": "read_file", "arguments": {}}
        envelope = ToolCallEnvelope.from_legacy_call(read_call)
        assert envelope.risk_level == RiskLevel.READ_ONLY

        # 写入工具
        write_call = {"tool_name": "write_file", "arguments": {}}
        envelope = ToolCallEnvelope.from_legacy_call(write_call)
        assert envelope.risk_level == RiskLevel.WRITE_REPO

        # 部署工具
        deploy_call = {"tool_name": "restart_service", "arguments": {}}
        envelope = ToolCallEnvelope.from_legacy_call(deploy_call)
        assert envelope.risk_level == RiskLevel.DEPLOY

        # 密钥工具
        secret_call = {"tool_name": "get_secret", "arguments": {}}
        envelope = ToolCallEnvelope.from_legacy_call(secret_call)
        assert envelope.risk_level == RiskLevel.SECRETS

    def test_execution_scope_inference(self):
        """测试执行范围推断"""
        # 局部动作
        local_call = {"tool_name": "read_file", "arguments": {}}
        envelope = ToolCallEnvelope.from_legacy_call(local_call)
        assert envelope.execution_scope == ExecutionScope.LOCAL
        assert envelope.requires_global_mutex is False

        # 全局动作
        global_call = {"tool_name": "npm_install", "arguments": {}}
        envelope = ToolCallEnvelope.from_legacy_call(global_call)
        assert envelope.execution_scope == ExecutionScope.GLOBAL
        assert envelope.requires_global_mutex is True

    def test_to_dict_serialization(self):
        """测试序列化为字典"""
        envelope = ToolCallEnvelope(
            tool_name="test_tool",
            call_id="call_123",
            trace_id="trace_456",
            risk_level=RiskLevel.WRITE_REPO,
        )

        data = envelope.to_dict()

        assert data["tool_name"] == "test_tool"
        assert data["call_id"] == "call_123"
        assert data["trace_id"] == "trace_456"
        assert data["risk_level"] == "write_repo"
        assert data["execution_scope"] == "local"


class TestToolResultEnvelope:
    """测试工具执行结果封装"""

    def test_from_legacy_result_small(self):
        """测试从旧格式结果转换（小数据）"""
        result = ToolResultEnvelope.from_legacy_result(
            call_id="call_123",
            trace_id="trace_456",
            tool_name="test_tool",
            result="Small result",
            status="ok",
            duration_ms=100.5,
        )

        assert result.call_id == "call_123"
        assert result.trace_id == "trace_456"
        assert result.tool_name == "test_tool"
        assert result.status == "ok"
        assert result.display_preview == "Small result"
        assert result.narrative_summary == "Small result"
        assert result.raw_result_ref is None
        assert result.forensic_artifact_ref is None
        assert result.truncated is False
        assert result.total_chars == 12
        assert result.duration_ms == 100.5

    def test_from_legacy_result_large(self):
        """测试从旧格式结果转换（大数据截断）"""
        large_result = "x" * 10000
        result = ToolResultEnvelope.from_legacy_result(
            call_id="call_123",
            trace_id="trace_456",
            tool_name="test_tool",
            result=large_result,
        )

        assert result.truncated is True
        assert result.total_chars == 10000
        assert len(result.display_preview) == 8000 + len("\n...[TRUNCATED]")
        assert result.display_preview.endswith("[TRUNCATED]")
        assert result.narrative_summary == result.display_preview
        assert result.forensic_artifact_ref is None

    def test_to_dict_serialization(self):
        """测试序列化为字典"""
        result = ToolResultEnvelope(
            call_id="call_123",
            trace_id="trace_456",
            tool_name="test_tool",
            status="ok",
            display_preview="Test result",
            total_chars=11,
        )

        data = result.to_dict()

        assert data["call_id"] == "call_123"
        assert data["trace_id"] == "trace_456"
        assert data["tool_name"] == "test_tool"
        assert data["status"] == "ok"
        assert data["display_preview"] == "Test result"
        assert data["narrative_summary"] == "Test result"
        assert data["raw_result_ref"] is None
        assert data["forensic_artifact_ref"] is None


class TestBuildToolResultWithArtifact:
    """测试带 artifact 支持的结果构建"""

    @staticmethod
    def _make_workspace_tempdir(prefix: str) -> Path:
        root = Path("tmp_ws15") / "test_tool_contract"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{prefix}{uuid.uuid4().hex[:8]}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_small_text_no_artifact(self):
        """测试小文本不创建 artifact"""
        result = build_tool_result_with_artifact(
            call_id="call_123",
            trace_id="trace_456",
            tool_name="test_tool",
            raw_output="Small output",
            content_type="text/plain",
        )

        assert result.truncated is False
        assert result.raw_result_ref is None
        assert result.forensic_artifact_ref is None
        assert result.display_preview == "Small output"
        assert result.narrative_summary == "Small output"
        payload = result.to_dict()
        assert payload["display_preview"] == "Small output"
        assert payload["narrative_summary"] == "Small output"
        assert payload["raw_result_ref"] is None
        assert payload["forensic_artifact_ref"] is None

    def test_large_text_truncated(self):
        """测试大文本截断"""
        large_output = "x" * 10000
        result = build_tool_result_with_artifact(
            call_id="call_123",
            trace_id="trace_456",
            tool_name="test_tool",
            raw_output=large_output,
            content_type="text/plain",
        )

        assert result.truncated is True
        assert result.total_chars == 10000
        assert len(result.display_preview) == 8000 + len("\n...[TRUNCATED]")

    def test_large_json_with_artifact(self, monkeypatch):
        """测试大 JSON 创建 artifact"""
        temp_root = self._make_workspace_tempdir("artifacts_case1_")
        temp_store = ArtifactStore(
            ArtifactStoreConfig(
                artifact_root=temp_root / "artifacts_case1",
                max_total_size_mb=64,
                max_single_artifact_mb=16,
                max_artifact_count=1000,
            )
        )
        monkeypatch.setattr(artifact_store_module, "_artifact_store", temp_store)

        large_json = '{"data": "' + ("x" * 10000) + '"}'
        result = build_tool_result_with_artifact(
            call_id="call_123",
            trace_id="trace_456",
            tool_name="test_tool",
            raw_output=large_json,
            content_type="application/json",
        )

        assert result.truncated is True
        assert result.raw_result_ref is not None
        assert result.forensic_artifact_ref == result.raw_result_ref
        assert result.narrative_summary == result.display_preview
        assert result.narrative_summary is not None
        assert "JSON object with keys:" in result.narrative_summary
        assert result.raw_result_ref.startswith("artifact_")
        assert result.fetch_hints is not None
        assert "jsonpath:$..error_code" in result.fetch_hints

    def test_large_json_artifact_roundtrip(self, monkeypatch):
        """测试 artifact 落盘后可回读（NGA-WS11-001/002）"""
        temp_root = self._make_workspace_tempdir("artifacts_case2_")
        temp_store = ArtifactStore(
            ArtifactStoreConfig(
                artifact_root=temp_root / "artifacts",
                max_total_size_mb=64,
                max_single_artifact_mb=16,
                max_artifact_count=1000,
            )
        )
        monkeypatch.setattr(artifact_store_module, "_artifact_store", temp_store)

        payload = {"trace_id": "trace_abc123", "error_code": 500, "message": "fatal"}
        large_json = '{"records": [' + ",".join([str(payload).replace("'", '"') for _ in range(400)]) + "]}"
        result = build_tool_result_with_artifact(
            call_id="call_123",
            trace_id="trace_456",
            tool_name="test_tool",
            raw_output=large_json,
            content_type="application/json",
        )

        assert result.raw_result_ref is not None
        assert result.forensic_artifact_ref == result.raw_result_ref
        ok, _, content = temp_store.retrieve(result.forensic_artifact_ref)
        assert ok is True
        assert content == large_json

        meta = temp_store.get_metadata(result.forensic_artifact_ref)
        assert meta is not None
        assert meta.source_tool == "test_tool"
        assert meta.source_call_id == "call_123"
        assert meta.source_trace_id == "trace_456"

    def test_forensic_artifact_ref_stable_when_summary_changes(self, monkeypatch):
        """测试摘要变化不影响证据引用（NGA-WS15-002）"""
        temp_root = self._make_workspace_tempdir("artifacts_case3_")
        temp_store = ArtifactStore(
            ArtifactStoreConfig(
                artifact_root=temp_root / "artifacts",
                max_total_size_mb=64,
                max_single_artifact_mb=16,
                max_artifact_count=1000,
            )
        )
        monkeypatch.setattr(artifact_store_module, "_artifact_store", temp_store)

        raw_payload = '{"events": [' + ",".join(['{"trace_id":"trace_fix","error_code":"E42"}'] * 600) + "]}"
        result = build_tool_result_with_artifact(
            call_id="call_123",
            trace_id="trace_456",
            tool_name="test_tool",
            raw_output=raw_payload,
            content_type="application/json",
        )
        original_ref = result.forensic_artifact_ref

        assert original_ref is not None
        result.narrative_summary = "Narrative rewritten for readability."
        result.display_preview = "Another summary view."

        payload = result.to_dict()
        assert payload["forensic_artifact_ref"] == original_ref
        assert payload["raw_result_ref"] == original_ref
        ok, _, roundtrip = temp_store.retrieve(original_ref)
        assert ok is True
        assert roundtrip == raw_payload


class TestFieldConsistency:
    """测试 native_call 与 mcp_call 字段一致性"""

    def test_native_and_mcp_have_same_fields(self):
        """验收标准：native_call 与 mcp_call 返回字段一致性"""
        # Native call
        native_call = {
            "agentType": "native",
            "tool_name": "read_file",
            "_tool_call_id": "call_native",
            "arguments": {"path": "/test.txt"},
        }
        native_envelope = ToolCallEnvelope.from_legacy_call(native_call)

        # MCP call
        mcp_call = {
            "agentType": "mcp",
            "service_name": "test_service",
            "tool_name": "test_tool",
            "_tool_call_id": "call_mcp",
            "arguments": {"param": "value"},
        }
        mcp_envelope = ToolCallEnvelope.from_legacy_call(mcp_call)

        # 验证字段一致性
        native_dict = native_envelope.to_dict()
        mcp_dict = mcp_envelope.to_dict()

        assert set(native_dict.keys()) == set(mcp_dict.keys())

        # 验证关键字段存在
        required_fields = [
            "tool_name", "call_id", "trace_id", "risk_level",
            "execution_scope", "validated_args", "timeout_ms",
            "input_schema_version", "caller_role",
        ]
        for field in required_fields:
            assert field in native_dict
            assert field in mcp_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
