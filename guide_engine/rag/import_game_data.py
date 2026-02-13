"""
游戏数据导入脚本

将游戏数据处理后导入 ChromaDB 向量数据库

使用方法（在项目根目录）:
    uv run python -m guide_engine.rag.import_game_data --game arknights
    uv run python -m guide_engine.rag.import_game_data --game arknights --dry-run
"""

from __future__ import annotations

import json
import asyncio
import argparse
from pathlib import Path
from typing import Dict, Type, List

from .base import BaseProcessor, Document
from .processors.arknights import ArknightsProcessor
from .processors.genshin import GenshinProcessor
from .processors.starrail import StarrailProcessor
from .processors.zenless import ZenlessProcessor
from .processors.wutheringwaves import WutheringWavesProcessor
from .processors.pgr import PGRProcessor
from .processors.umamusume import UmaMusumeProcessor
from ..chroma_service import ChromaService
from ..models import get_guide_engine_settings

# 注册所有处理器
PROCESSORS: Dict[str, Type[BaseProcessor]] = {
    "arknights": ArknightsProcessor,
    "genshin": GenshinProcessor,
    "starrail": StarrailProcessor,
    "zenless": ZenlessProcessor,
    "wutheringwaves": WutheringWavesProcessor,
    "pgr": PGRProcessor,
    "umamusume": UmaMusumeProcessor,
}


class GameDataImporter:
    """游戏数据导入器"""

    def __init__(self, chroma_service: ChromaService | None = None):
        self.chroma = chroma_service or ChromaService()
        self.stats: dict[str, object] = {
            "total_documents": 0,
            "total_chunks": 0,
            "games_processed": [],
        }

    async def import_game(
        self,
        game_id: str,
        dry_run: bool = False,
        verbose: bool = True,
        collection_type: str = "guides",
    ) -> Dict[str, object]:
        """导入单个游戏的数据"""
        if game_id not in PROCESSORS:
            raise ValueError(f"Unknown game: {game_id}. Available: {list(PROCESSORS.keys())}")

        settings = get_guide_engine_settings()
        data_dir = Path(settings.gamedata_dir)

        processor_class = PROCESSORS[game_id]
        processor = processor_class()

        if verbose:
            print(f"\n{'='*50}")
            print(f"Processing: {game_id}")
            print(f"Data dir: {data_dir}")
            print(f"{'='*50}")

        # 读取数据文件
        data_files = processor.get_data_files()
        all_data: dict[str, object] = {}

        for entity_type, filename in data_files.items():
            file_path = data_dir / filename
            if not file_path.exists():
                print(f"  Warning: {file_path} not found, skipping")
                continue

            with open(file_path, "r", encoding="utf-8") as f:
                file_data = json.load(f)

            if isinstance(file_data, list):
                all_data[entity_type] = file_data
            elif isinstance(file_data, dict) and entity_type in file_data:
                all_data[entity_type] = file_data[entity_type]
            elif isinstance(file_data, dict):
                all_data[entity_type] = file_data
            else:
                all_data[entity_type] = []

            if verbose:
                data_item = all_data[entity_type]
                count = len(data_item) if isinstance(data_item, (list, dict)) else 1
                print(f"  Loaded {filename}: {count} items")

        # 处理数据
        documents: List[Document] = processor.process(all_data)

        # 按 collection_type 过滤文档
        if collection_type == "enemies":
            documents = [doc for doc in documents if doc.entity_type == "enemy"]
        elif collection_type == "guides":
            documents = [doc for doc in documents if doc.entity_type != "enemy"]

        if verbose:
            print(f"\n  Generated {len(documents)} documents")

        total_chunks = sum(len(doc.chunks) for doc in documents)
        if verbose:
            print(f"  Total chunks: {total_chunks}")

            chunk_type_counts: dict[str, int] = {}
            for doc in documents:
                for chunk in doc.chunks:
                    chunk_type_counts[chunk.chunk_type.value] = chunk_type_counts.get(chunk.chunk_type.value, 0) + 1
            for ct, count in sorted(chunk_type_counts.items()):
                print(f"    - {ct}: {count}")

        if verbose and documents:
            print(f"\n  Sample chunks from first document ({documents[0].entity_name}):")
            for chunk in documents[0].chunks[:3]:
                preview = chunk.content[:100].replace("\n", " ") + "..."
                print(f"    [{chunk.chunk_type.value}] {preview}")

        # 导入到向量库
        if not dry_run:
            if verbose:
                print(f"\n  Importing to ChromaDB...")

            await self.chroma.create_collection(game_id, collection_type)

            chroma_docs: list[dict[str, object]] = []
            seen_ids: set[str] = set()
            duplicates = 0
            for doc in documents:
                for chunk in doc.chunks:
                    if chunk.id in seen_ids:
                        duplicates += 1
                        continue
                    seen_ids.add(chunk.id)
                    chroma_docs.append({
                        "id": chunk.id,
                        "title": f"{chunk.entity_name} - {chunk.chunk_type.value}",
                        "content": chunk.content,
                        "doc_type": chunk.chunk_type.value,
                        "source_url": "",
                        "version": "1.0.0",
                        "metadata": chunk.to_dict()
                    })
            if duplicates > 0 and verbose:
                print(f"  Skipped {duplicates} duplicate chunks")

            inserted = await self.chroma.insert_documents(game_id, chroma_docs, collection_type)
            if verbose:
                print(f"  Inserted {inserted} chunks to ChromaDB")

        games_list: list[str] = self.stats["games_processed"]  # type: ignore[assignment]
        self.stats["total_documents"] = int(self.stats["total_documents"]) + len(documents)  # type: ignore[arg-type]
        self.stats["total_chunks"] = int(self.stats["total_chunks"]) + total_chunks  # type: ignore[arg-type]
        games_list.append(game_id)

        return {
            "game_id": game_id,
            "documents": len(documents),
            "chunks": total_chunks,
            "dry_run": dry_run,
        }

    async def import_all(
        self,
        dry_run: bool = False,
        verbose: bool = True,
        collection_type: str = "guides",
    ) -> Dict[str, object]:
        """导入所有已注册游戏的数据"""
        results: list[dict[str, object]] = []
        for game_id in PROCESSORS:
            try:
                result = await self.import_game(game_id, dry_run, verbose, collection_type)
                results.append(result)
            except Exception as e:
                print(f"Error processing {game_id}: {e}")
                results.append({"game_id": game_id, "error": str(e)})

        return {"results": results, "stats": self.stats}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import game data to ChromaDB")
    parser.add_argument("--game", "-g", type=str, help="Game ID to import (e.g., arknights)")
    parser.add_argument("--all", "-a", action="store_true", help="Import all games")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Process without importing")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")
    parser.add_argument(
        "--collection-type", "-t", type=str, default="guides",
        choices=["guides", "wiki", "enemies"],
        help="Target collection type (default: guides)",
    )

    args = parser.parse_args()

    if not args.game and not args.all:
        parser.print_help()
        print("\nAvailable games:", list(PROCESSORS.keys()))
        return

    importer = GameDataImporter()
    verbose = not args.quiet

    if args.all:
        await importer.import_all(dry_run=args.dry_run, verbose=verbose, collection_type=args.collection_type)
    else:
        await importer.import_game(args.game, dry_run=args.dry_run, verbose=verbose, collection_type=args.collection_type)

    print(f"\n{'='*50}")
    print("Import Summary")
    print(f"{'='*50}")
    print(f"Total documents: {importer.stats['total_documents']}")
    print(f"Total chunks: {importer.stats['total_chunks']}")
    games_list: list[str] = importer.stats["games_processed"]  # type: ignore[assignment]
    print(f"Games processed: {', '.join(games_list)}")
    if args.dry_run:
        print("\n(Dry run - no data was imported)")


if __name__ == "__main__":
    asyncio.run(main())
