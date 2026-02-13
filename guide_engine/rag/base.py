"""
RAG 基类定义

提供文档、分块和处理器的基础抽象
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import hashlib
import re


class ChunkType(str, Enum):
    """分块类型"""
    BASIC = "basic"           # 基础信息
    SKILL = "skill"           # 技能
    TALENT = "talent"         # 天赋
    MODULE = "module"         # 模组/装备
    BUILDING = "building"     # 基建/非战斗技能
    EVENT = "event"           # 事件
    MATERIAL = "material"     # 材料
    GUIDE = "guide"           # 攻略文本


@dataclass
class Chunk:
    """
    文档分块

    一个完整的游戏实体（如干员）会被拆分成多个 Chunk
    每个 Chunk 是一个独立的可检索单元
    """
    id: str                          # 唯一标识
    game_id: str                     # 游戏ID
    entity_type: str                 # 实体类型
    entity_id: str                   # 实体ID
    entity_name: str                 # 实体名称
    chunk_type: ChunkType            # 分块类型
    chunk_index: int = 0             # 同类型分块的索引

    content: str = ""                # 分块文本内容
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "chunk_type": self.chunk_type.value,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "metadata": self.metadata,
        }


@dataclass
class Document:
    """
    游戏文档

    代表一个完整的游戏实体（干员、角色、敌人等）
    包含原始数据和处理后的分块
    """
    game_id: str
    entity_type: str
    entity_id: str
    entity_name: str
    raw_data: Dict[str, Any]
    chunks: List[Chunk] = field(default_factory=list)

    def add_chunk(
        self,
        chunk_type: ChunkType,
        content: str,
        chunk_index: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Chunk:
        id_source = f"{self.game_id}_{self.entity_type}_{self.entity_id}_{chunk_type.value}_{chunk_index}_{content}"
        chunk_id = hashlib.md5(id_source.encode('utf-8')).hexdigest()
        chunk_id = f"{self.game_id}_{chunk_id}"

        chunk = Chunk(
            id=chunk_id,
            game_id=self.game_id,
            entity_type=self.entity_type,
            entity_id=self.entity_id,
            entity_name=self.entity_name,
            chunk_type=chunk_type,
            chunk_index=chunk_index,
            content=content,
            metadata=metadata or {}
        )

        self.chunks.append(chunk)
        return chunk


class BaseProcessor(ABC):
    """
    数据处理器基类

    每个游戏实现自己的处理器，定义如何将原始数据转换为可检索的分块
    """

    game_id: str = ""

    @abstractmethod
    def process(self, data: Dict[str, Any]) -> List[Document]:
        pass

    @abstractmethod
    def get_data_files(self) -> Dict[str, str]:
        pass

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        return text.strip()
