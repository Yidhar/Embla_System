from __future__ import annotations

import json
import logging
import os
import webbrowser
from pathlib import Path
from typing import Iterable, Sequence, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_KNOWLEDGE_GRAPH_DIR = _PROJECT_ROOT / "logs" / "knowledge_graph"
QUINTUPLES_JSON_PATH = _KNOWLEDGE_GRAPH_DIR / "quintuples.json"
GRAPH_HTML_PATH = _KNOWLEDGE_GRAPH_DIR / "graph.html"

_TYPE_COLORS = {
    "人物": "#FF6B6B",
    "地点": "#4ECDC4",
    "组织": "#45B7D1",
    "物品": "#96CEB4",
    "概念": "#FFEAA7",
    "时间": "#DDA0DD",
    "事件": "#F4A460",
    "活动": "#FFB347",
}
_DEFAULT_COLOR = "#CCCCCC"


def load_quintuples_from_json(json_path: Path | str = QUINTUPLES_JSON_PATH) -> set[Tuple[str, str, str, str, str]]:
    """从 quintuples.json 读取五元组数据。"""
    path = Path(json_path)
    try:
        if not path.exists():
            logger.warning("五元组文件不存在: %s", path)
            return set()

        data = json.loads(path.read_text(encoding="utf-8"))
        result = {tuple(item) for item in data}
        logger.info("从 %s 读取到 %s 条唯一五元组", path, len(result))
        return result
    except json.JSONDecodeError as exc:
        logger.error("五元组文件 JSON 格式错误: %s (%s)", path, exc)
        return set()
    except Exception as exc:
        logger.error("读取五元组文件失败: %s (%s)", path, exc)
        return set()


def _filter_valid_quintuples(
    quintuples: Iterable[Sequence[object]],
) -> list[Tuple[str, str, str, str, str]]:
    valid_rows: list[Tuple[str, str, str, str, str]] = []
    for item in quintuples:
        if not isinstance(item, (tuple, list)) or len(item) != 5:
            continue
        row = tuple(str(value).strip() for value in item)
        if all(row):
            valid_rows.append(row)  # type: ignore[arg-type]
    return valid_rows


def visualize_quintuples(
    *,
    json_path: Path | str = QUINTUPLES_JSON_PATH,
    output_path: Path | str = GRAPH_HTML_PATH,
    auto_open: bool = True,
) -> Path | None:
    """从 JSON 文件读取五元组并生成可视化图谱。"""
    quintuples = load_quintuples_from_json(json_path)
    if not quintuples:
        logger.warning("未获取到五元组，跳过图谱生成")
        return None

    valid_quintuples = _filter_valid_quintuples(quintuples)
    if not valid_quintuples:
        logger.warning("未发现有效五元组，跳过图谱生成")
        return None

    from pyvis.network import Network

    net = Network(height="1600px", width="100%", notebook=False)
    net.use_template = False
    net.barnes_hut()
    net.set_options(
        """
        var options = {
          "physics": {
            "barnesHut": {
              "gravitationalConstant": -8000,
              "springLength": 100,
              "springConstant": 0.04
            },
            "minVelocity": 0.75
          }
        }
        """
    )

    added_nodes: set[str] = set()
    for head, head_type, relation, tail, tail_type in valid_quintuples:
        if head not in added_nodes:
            net.add_node(
                head,
                label=f"{head}\n({head_type})",
                color=_TYPE_COLORS.get(head_type, _DEFAULT_COLOR),
                font={"size": 20},
            )
            added_nodes.add(head)
        if tail not in added_nodes:
            net.add_node(
                tail,
                label=f"{tail}\n({tail_type})",
                color=_TYPE_COLORS.get(tail_type, _DEFAULT_COLOR),
                font={"size": 20},
            )
            added_nodes.add(tail)
        net.add_edge(head, tail, label=relation, length=120, font={"size": 18})

    html_path = Path(output_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(html_path))
    logger.info(
        "知识图谱可视化完成: %s (nodes=%s, edges=%s)",
        html_path,
        len(added_nodes),
        len(valid_quintuples),
    )

    if auto_open:
        try:
            webbrowser.open(f"file:///{os.path.abspath(html_path)}")
        except Exception as exc:
            logger.warning("自动打开浏览器失败: %s", exc)

    return html_path


if __name__ == "__main__":
    generated = visualize_quintuples()
    if generated is None:
        print("未生成知识图谱，请检查 logs/knowledge_graph/quintuples.json 是否存在且内容有效。")
    else:
        print(f"知识图谱已生成：{generated}")
