from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from system.episodic_memory import EpisodicMemoryArchive, archive_tool_results_for_session


def _make_case_dir() -> Path:
    root = Path(".tmp_test_episodic_memory")
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / f"case_{uuid.uuid4().hex}"
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir


def test_archive_persists_and_reloads():
    case_dir = _make_case_dir()
    try:
        archive_path = case_dir / "episodic_archive.jsonl"
        store = EpisodicMemoryArchive(archive_path=archive_path, vector_dims=1024, session_boost=0.0)

        store.append_record(
            record_id="ep_seed_001",
            session_id="sess-a",
            source_tool="native:run_cmd",
            narrative_summary="修复 npm install E401 鉴权失败，更新 token 后恢复正常。",
            forensic_artifact_ref="artifact_auth_fix",
            fetch_hints=["grep:E401", "jsonpath:$..error_code"],
            timestamp=1_700_000_000.0,
        )

        assert archive_path.exists()

        reloaded = EpisodicMemoryArchive(archive_path=archive_path, vector_dims=1024, session_boost=0.0)
        hits = reloaded.search("npm install token 鉴权失败", session_id="sess-a", top_k=1, min_score=0.01)

        assert hits
        assert hits[0].record.record_id == "ep_seed_001"
        assert hits[0].record.forensic_artifact_ref == "artifact_auth_fix"
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_search_topk_is_stable_for_same_query():
    case_dir = _make_case_dir()
    try:
        store = EpisodicMemoryArchive(archive_path=case_dir / "episodic_archive.jsonl", vector_dims=2048, session_boost=0.0)

        expected = store.append_record(
            session_id="sess-a",
            source_tool="native:run_cmd",
            narrative_summary="定位并修复 pytest flaky timeout，增加重试和等待策略。",
            forensic_artifact_ref="artifact_pytest_fix",
        )
        other_1 = store.append_record(
            session_id="sess-a",
            source_tool="native:git_status",
            narrative_summary="检查 git working tree 状态并确认未提交文件。",
        )
        other_2 = store.append_record(
            session_id="sess-b",
            source_tool="native:read_file",
            narrative_summary="读取前端样式文件并调整配色变量。",
        )

        query = "pytest timeout flaky test 修复方案"
        first = store.search(query, top_k=3, min_score=0.01)
        second = store.search(query, top_k=3, min_score=0.01)

        first_ids = [hit.record.record_id for hit in first]
        second_ids = [hit.record.record_id for hit in second]

        assert first_ids == second_ids
        assert first_ids[0] == expected.record_id
        assert other_1.record_id in {hit.record.record_id for hit in store.search("git status", top_k=3, min_score=0.01)}
        assert other_2.record_id in {hit.record.record_id for hit in store.search("前端 配色 变量", top_k=3, min_score=0.01)}
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_archive_tool_result_and_reinjection_context():
    case_dir = _make_case_dir()
    try:
        store = EpisodicMemoryArchive(archive_path=case_dir / "episodic_archive.jsonl", vector_dims=2048, session_boost=0.0)

        tool_result = {
            "status": "success",
            "service_name": "native",
            "tool_name": "run_cmd",
            "result": (
                "[exit_code] 0\n"
                "[forensic_artifact_ref] artifact_cmd_001\n"
                "[fetch_hints] jsonpath:$..error_code, grep:E401\n"
                "[narrative_summary]\n"
                "已定位并修复 npm install E401 鉴权失败，切换到新的访问令牌。\n"
                "[display_preview]\n"
                "npm install completed with auth token refresh."
            ),
        }

        archived = archive_tool_results_for_session("sess-reinject", [tool_result], archive=store)
        assert len(archived) == 1
        assert archived[0].forensic_artifact_ref == "artifact_cmd_001"
        assert "jsonpath:$..error_code" in archived[0].fetch_hints

        hits = store.search("npm install e401", session_id="sess-reinject", top_k=1, min_score=0.01)
        assert hits
        assert hits[0].record.record_id == archived[0].record_id

        context = store.build_reinjection_context(
            query="npm install 还是 E401，怎么排查",
            session_id="sess-reinject",
            top_k=2,
            min_score=0.01,
        )
        assert "Episodic Memory Reinjection" in context
        assert "artifact_cmd_001" in context
        assert "jsonpath:$..error_code" in context
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
