"""Intent analysis: extract tool-call intents from text."""

from __future__ import annotations

from typing import Any, Dict, List

from .json_parser import parse_non_standard_json, validate_tool_call


class IntentAnalyzer:
    def analyze_conversation(self, conversation: str) -> Dict[str, Any]:
        try:
            tool_calls = [
                tc
                for tc in parse_non_standard_json(conversation)
                if isinstance(tc, dict) and validate_tool_call(tc)
            ]
            return {
                "has_tasks": len(tool_calls) > 0,
                "tool_calls": tool_calls,
                "total_count": len(tool_calls),
            }
        except Exception as exc:
            return {
                "has_tasks": False,
                "error": str(exc),
                "tool_calls": [],
                "total_count": 0,
            }

    def extract_tool_calls(self, conversation: str) -> List[Dict[str, Any]]:
        return self.analyze_conversation(conversation).get("tool_calls", [])

    def validate_tool_call_format(self, tool_call: Dict[str, Any]) -> bool:
        return validate_tool_call(tool_call)

    def get_tool_call_summary(self, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "total": len(tool_calls),
            "by_agent_type": {},
            "task_types": [],
        }
        task_types: set[str] = set()

        for tool_call in tool_calls:
            agent_type = str(tool_call.get("agentType") or "").strip().lower() or "unknown"
            summary["by_agent_type"][agent_type] = summary["by_agent_type"].get(agent_type, 0) + 1
            task_type = tool_call.get("task_type")
            if isinstance(task_type, str) and task_type.strip():
                task_types.add(task_type.strip())

        summary["task_types"] = sorted(task_types)
        return summary
