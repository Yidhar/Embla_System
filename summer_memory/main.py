from __future__ import annotations

import atexit
import logging
import subprocess
import traceback
from pathlib import Path
from typing import Iterable, Sequence

from .quintuple_extractor import config as runtime_config
from .quintuple_extractor import extract_quintuples
from .quintuple_graph import store_quintuples
from .quintuple_rag_query import query_knowledge, set_context
from .quintuple_visualize import visualize_quintuples

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_SUMMER_MEMORY_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SUMMER_MEMORY_DIR.parent
_DOCKER_COMPOSE_TEMPLATE_PATH = _SUMMER_MEMORY_DIR / "docker-compose.template.yml"
_DOCKER_COMPOSE_OUTPUT_PATH = _SUMMER_MEMORY_DIR / "docker-compose.yml"
_DEFAULT_GRAPH_HTML_PATH = _PROJECT_ROOT / "logs" / "knowledge_graph" / "graph.html"
_DEFAULT_SAMPLE_TEXTS = ("你好，我是 Embla。",)
_MANAGED_NEO4J_STARTED = False


def _neo4j_auth_value() -> str:
    return f"{runtime_config.grag.neo4j_user}/{runtime_config.grag.neo4j_password}"


def _project_relative(path: Path) -> str:
    try:
        return str(path.relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(path)


def generate_docker_compose(
    template_path: Path | str = _DOCKER_COMPOSE_TEMPLATE_PATH,
    output_path: Path | str = _DOCKER_COMPOSE_OUTPUT_PATH,
) -> Path:
    template_file = Path(template_path)
    output_file = Path(output_path)
    template = template_file.read_text(encoding="utf-8")
    rendered = (
        template.replace("${NEO4J_AUTH}", _neo4j_auth_value()).replace("${NEO4J_DB}", runtime_config.grag.neo4j_database)
    )
    output_file.write_text(rendered, encoding="utf-8")
    logger.info("已根据系统配置生成 %s", output_file)
    return output_file


def is_neo4j_running() -> bool:
    try:
        output = subprocess.check_output(
            ["docker", "ps", "--filter", "name=rag_neo4j", "--filter", "status=running", "--format", "{{.Names}}"]
        )
        return "rag_neo4j" in output.decode("utf-8")
    except Exception as exc:
        logger.debug("检查 Neo4j 容器状态失败: %s", exc)
        return False


def get_docker_compose_command() -> list[str] | None:
    for command in (["docker", "compose"], ["docker-compose"]):
        try:
            subprocess.run(command + ["version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return command
        except Exception:
            continue
    return None


def start_managed_neo4j_container() -> bool:
    global _MANAGED_NEO4J_STARTED
    if is_neo4j_running():
        logger.info("Neo4j 容器已在运行，跳过托管启动")
        return True

    compose_cmd = get_docker_compose_command()
    if not compose_cmd:
        logger.warning("未找到可用的 Docker Compose 命令，继续使用文件存储模式")
        return False

    try:
        generate_docker_compose()
        logger.info("正在启动托管 Neo4j 容器...")
        subprocess.run(compose_cmd + ["up", "-d"], check=True, cwd=str(_SUMMER_MEMORY_DIR))
        _MANAGED_NEO4J_STARTED = True
        logger.info("Neo4j 容器已启动")
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("启动托管 Neo4j 容器失败，将继续使用文件存储模式: %s", exc)
        return False


def stop_managed_neo4j_container() -> bool:
    global _MANAGED_NEO4J_STARTED
    if not _MANAGED_NEO4J_STARTED:
        return False

    compose_cmd = get_docker_compose_command()
    if not compose_cmd:
        logger.warning("无法关闭托管 Neo4j 容器：未找到 Docker Compose 命令")
        return False

    try:
        logger.info("正在关闭托管 Neo4j 容器...")
        subprocess.run(compose_cmd + ["down"], check=True, cwd=str(_SUMMER_MEMORY_DIR))
        logger.info("托管 Neo4j 容器已关闭")
        _MANAGED_NEO4J_STARTED = False
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("关闭托管 Neo4j 容器失败: %s", exc)
        return False


atexit.register(stop_managed_neo4j_container)


def _normalize_input_texts(texts: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for item in texts:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def batch_add_texts(texts: Sequence[str]) -> bool:
    try:
        normalized_texts = _normalize_input_texts(texts)
        if not normalized_texts:
            logger.warning("未提供可处理文本")
            return False

        all_quintuples = set()
        for text in normalized_texts:
            logger.info("处理文本: %s...", text[:50])
            quintuples = extract_quintuples(text)
            if not quintuples:
                logger.warning("文本未提取到五元组: %s", text)
                continue
            all_quintuples.update(quintuples)

        if not all_quintuples:
            logger.warning("未提取到任何五元组")
            return False

        valid_quintuples = [
            item
            for item in all_quintuples
            if len(item) == 5 and all(isinstance(value, str) and value.strip() for value in item)
        ]
        if len(valid_quintuples) < len(all_quintuples):
            logger.warning("过滤掉 %s 个无效五元组", len(all_quintuples) - len(valid_quintuples))

        if not valid_quintuples:
            logger.warning("无有效五元组")
            return False

        if not store_quintuples(valid_quintuples):
            logger.error("五元组存储失败")
            return False

        set_context(normalized_texts)
        logger.info("成功写入 %s 个五元组", len(valid_quintuples))
        return True
    except Exception as exc:
        logger.error("处理文本失败: %s", exc)
        return False


def batch_add_from_file(filename: str | Path) -> bool:
    file_path = Path(filename)
    try:
        if not file_path.exists():
            raise FileNotFoundError(f"文件 {file_path} 不存在")

        texts = [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not texts:
            logger.warning("文件 %s 为空", file_path)
            return False

        logger.info("读取文件 %s 共 %s 条文本", file_path, len(texts))
        return batch_add_texts(texts)
    except Exception as exc:
        logger.error("批量处理文件失败: %s", exc)
        traceback.print_exc()
        return False


def render_graph_visualization(*, auto_open: bool = True) -> Path | None:
    generated = visualize_quintuples(auto_open=auto_open)
    if generated is None:
        logger.warning("未生成知识图谱 HTML")
        return None
    return Path(generated)


def _prompt_input_texts() -> list[str]:
    print("请输入要处理的文本（每行一段，输入空行结束）：")
    rows: list[str] = []
    while True:
        text = input("> ")
        if not text.strip():
            break
        rows.append(text.strip())
    return rows or list(_DEFAULT_SAMPLE_TEXTS)


def _prompt_input_mode() -> str:
    print("请选择输入方式：")
    print("1 - 手动输入文本")
    print("2 - 从文件读取文本")
    return input("请输入 1 或 2：").strip()


def run_debug_cli() -> int:
    logger.info("summer_memory 调试入口启动")
    start_managed_neo4j_container()

    try:
        choice = _prompt_input_mode()
        if choice == "1":
            texts = _prompt_input_texts()
            success = batch_add_texts(texts)
        elif choice == "2":
            filename = input("请输入文件路径：").strip()
            success = batch_add_from_file(filename)
        else:
            print("无效输入，仅支持 1 或 2。程序退出。")
            return 1

        if not success:
            print("文本处理失败，请检查控制台日志。")
            return 1

        graph_path = render_graph_visualization(auto_open=True) or _DEFAULT_GRAPH_HTML_PATH
        print(f"\n知识图谱已生成：{_project_relative(graph_path)}")
        print("请输入查询问题（输入空行退出）：")
        while True:
            query = input("> ").strip()
            if not query:
                print("退出查询。")
                return 0
            print("\n查询结果：")
            print(query_knowledge(query))
            print("\n请输入下一个查询问题（输入空行退出）：")
    except KeyboardInterrupt:
        logger.info("用户中断程序")
        print("\n程序已中断。")
        return 130
    except Exception as exc:
        logger.error("调试入口运行失败: %s", exc)
        print(f"发生错误：{exc}")
        return 1


def main() -> int:
    return run_debug_cli()


if __name__ == "__main__":
    raise SystemExit(main())
