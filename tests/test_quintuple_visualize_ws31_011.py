from pathlib import Path

from summer_memory.quintuple_visualize import _filter_valid_quintuples, load_quintuples_from_json


def test_load_quintuples_from_json_reads_unique_rows(tmp_path: Path) -> None:
    source = tmp_path / "quintuples.json"
    source.write_text(
        '[["小明","人物","在","公园","地点"],["小明","人物","在","公园","地点"]]',
        encoding="utf-8",
    )

    result = load_quintuples_from_json(source)

    assert result == {("小明", "人物", "在", "公园", "地点")}


def test_filter_valid_quintuples_drops_invalid_rows() -> None:
    result = _filter_valid_quintuples(
        [
            ("小明", "人物", "在", "公园", "地点"),
            ("", "人物", "在", "公园", "地点"),
            ("小红", "人物", "喜欢", "读书"),
        ]
    )

    assert result == [("小明", "人物", "在", "公园", "地点")]
