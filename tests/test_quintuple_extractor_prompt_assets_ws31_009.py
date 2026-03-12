from summer_memory.quintuple_extractor import (
    _build_json_fallback_prompt,
    _build_structured_messages,
)


def test_quintuple_structured_messages_use_canonical_prompt_assets() -> None:
    messages = _build_structured_messages("小明在公园里踢足球。")

    assert messages[0]["role"] == "system"
    assert "专业的中文文本信息抽取专家" in messages[0]["content"]
    assert "五元组格式为" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "小明在公园里踢足球。" in messages[1]["content"]
    assert "{text}" not in messages[1]["content"]


def test_quintuple_json_fallback_prompt_uses_canonical_prompt_asset() -> None:
    prompt = _build_json_fallback_prompt("如果我是鸟，我会飞到月球。")

    assert "JSON 数组格式返回" in prompt
    assert "如果我是鸟，我会飞到月球。" in prompt
    assert "除了 JSON 数据" in prompt
    assert "{text}" not in prompt
