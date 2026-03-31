from summer_memory.quintuple_rag_query import _build_keyword_prompt


def test_quintuple_rag_keyword_prompt_uses_canonical_prompt_asset() -> None:
    prompt = _build_keyword_prompt("小明在公园踢足球。", "谁在踢足球？", ollama=False)

    assert "JSON 格式的关键词列表" in prompt
    assert "小明在公园踢足球。" in prompt
    assert "谁在踢足球？" in prompt


def test_quintuple_rag_keyword_ollama_prompt_uses_canonical_prompt_asset() -> None:
    prompt = _build_keyword_prompt("小明在公园踢足球。", "谁在踢足球？", ollama=True)

    assert "直接返回关键词数组" in prompt
    assert "小明在公园踢足球。" in prompt
    assert "谁在踢足球？" in prompt
