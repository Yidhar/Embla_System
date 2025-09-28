"""
PromptGenerator - 提示词生成器

为每个角色生成专用的system prompt,包含角色职责,协作关系,思维向量等
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from ..models.data_models import GeneratedRole, Task, ThinkingVector
from ..models.config import GameConfig

logger = logging.getLogger(__name__)

class PromptGenerator:
    """提示词生成器"""
    
    def __init__(self, config: GameConfig, naga_conversation=None):
        self.config = config
        self.naga_conversation = naga_conversation
        self.generation_count = 0
    
    async def generate_role_prompt(
        self,
        role: GeneratedRole,
        task: Task,
        collaboration_permissions: Dict[str, List[str]],
        all_roles: List[GeneratedRole]
    ) -> str:
        """为单个角色生成系统提示词(返回字符串)"""
        connections = collaboration_permissions.get(role.name, [])
        if not self.naga_conversation:
            return self._get_fallback_prompt(role, task, connections)
        
        prompt_request = self._build_prompt_generation_request(role, task, connections)
        try:
            generated = await self.naga_conversation.get_response(
                prompt_request,
                temperature=0.6
            )
            system_prompt = self._extract_system_prompt(generated, role)
            self.generation_count += 1
            return system_prompt
        except Exception as e:
            logger.warning(f"LLM提示词生成失败,使用备用: {e}")
            return self._get_fallback_prompt(role, task, connections)
    
    def _build_prompt_generation_request(self, role: GeneratedRole, task: Task, connections: List[str]) -> str:
        """构建提示词生成请求"""
        conn_text = ", ".join(connections) if connections else "无"
        return f"""# 任务: 为专业角色生成系统提示词

## 角色信息
- 角色名称: {role.name}
- 角色类型: {role.role_type}
- 核心职责: {', '.join(role.responsibilities)}
- 专业技能: {', '.join(role.skills)}
- 优先级: {role.priority_level}

## 任务背景
- 任务描述: {task.description}
- 任务领域: {task.domain}
- 关键需求: {', '.join(task.requirements[:3])}

## 协作环境
- 可协作对象: {conn_text}
- 团队: 多智能体协作

## 生成要求
请直接输出可作为system prompt使用的内容,包含: 身份定位/职责/协作方式/输出要求/风格与边界.
不需要任何额外说明或JSON标记,仅输出提示词正文.
"""
    
    def _extract_system_prompt(self, generated_content: str, role: GeneratedRole) -> str:
        content = generated_content.strip()
        if len(content) < 50:
            return self._get_default_system_prompt(role, None)
        return content
    
    def _get_fallback_prompt(self, role: GeneratedRole, task: Optional[Task] = None, connections: Optional[List[str]] = None) -> str:
        """备用提示词(字符串)"""
        conn_text = ", ".join(connections or []) if connections else "无"
        task_text = task.description if task else "当前任务"
        parts: List[str] = []
        parts.append(f"你是{role.name},一名专业的{role.role_type}.")
        parts.append("")
        parts.append("## 核心职责")
        for r in role.responsibilities:
            parts.append(f"- {r}")
        parts.append("")
        parts.append("## 专业技能")
        for s in role.skills:
            parts.append(f"- {s}")
        parts.append("")
        parts.append("## 协作关系")
        parts.append(f"- 你可以与以下对象直接协作: {conn_text}")
        parts.append("")
        parts.append("## 任务上下文")
        parts.append(f"- 任务: {task_text}")
        parts.append("")
        parts.append("## 输出要求")
        parts.append("1. 提供结构化、可执行的专业输出")
        parts.append("2. 覆盖需求理解/方案设计/实施建议/风险控制")
        parts.append("3. 语言专业清晰,可直接用于评审与实现")
        return "\n".join(parts)
    
    def _get_default_system_prompt(self, role: GeneratedRole, task: Optional[Task]) -> str:
        """默认提示词(字符串)"""
        return self._get_fallback_prompt(role, task, [])
    
    # 统计信息(可选)
    def get_generation_statistics(self) -> Dict[str, Any]:
        return {
            "total_generated": self.generation_count,
            "has_llm": self.naga_conversation is not None,
            "generator_status": "active"
        }

 
 