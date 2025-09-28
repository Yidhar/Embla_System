"""
GameActor - 功能生成组件

负责接收上游角色指令与任务目标,执行具体的功能模块,并输出初始任务成果.
该模块提供对外一致的接口供 GameEngine 调用,并与 Criticizer/PhilossChecker 协同工作.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..models.data_models import Agent, Task
from ..models.config import GameConfig

logger = logging.getLogger(__name__)


@dataclass
class ActorOutput:
    """Actor 组件的标准输出结构"""
    agent_id: str
    branch_id: int
    content: str
    generation_time: float
    iteration: int
    metadata: Dict[str, Any]

    @property
    def target_output_id(self) -> str:
        """为下游组件提供稳定的内容标识"""
        return f"{self.agent_id}_b{self.branch_id}_{self.iteration}"


class GameActor:
    """游戏Actor组件 - 内容生成器"""

    def __init__(self, config: GameConfig, naga_conversation=None):
        self.config = config
        self.naga_conversation = naga_conversation
        self._init_naga_api()

    def _init_naga_api(self):
        """初始化 NagaAgent API 连接(若未提供则尝试创建)"""
        if self.naga_conversation is None:
            try:
                from system.conversation_core import NagaConversation
                self.naga_conversation = NagaConversation()
                logger.info("GameActor 成功初始化 NagaAgent API 连接")
            except Exception as e:
                logger.warning(f"GameActor 无法初始化 NagaAgent API, 将使用降级模式: {e}")
                self.naga_conversation = None

    async def generate_content(
        self,
        agent: Agent,
        task: Task,
        context: Optional[str],
        previous_outputs: Optional[List[ActorOutput]] = None,
        branch_id: int = 1,
    ) -> ActorOutput:
        """为指定智能体生成本轮内容

        Args:
            agent: 执行生成的智能体
            task: 当前任务
            context: 上一轮/外部上下文
            previous_outputs: 以往轮次的 Actor 输出,用于参考
            branch_id: 并行分支编号（从1开始）
        """
        start_time = time.time()
        iteration = getattr(agent, "current_iteration", 0) + 1

        prompt = self._build_generation_prompt(agent, task, context, previous_outputs or [])

        try:
            if self.naga_conversation is None:
                # 降级模式: 生成一个基于角色信息的结构化占位输出
                content = self._fallback_generate(agent, task, context, previous_outputs or [])
            else:
                content = await self.naga_conversation.get_response(
                    prompt,
                    temperature=0.7
                )

            generation_time = time.time() - start_time

            # 汇总历史上下文（不包含本次最新输出）
            prev_ctx_parts: List[str] = []
            for prev in (previous_outputs or [])[-3:]:
                prev_ctx_parts.append(
                    f"[第{prev.iteration}轮 by {prev.metadata.get('agent_name','未知')}] {prev.content[:400]}"
                )
            previous_context = "\n".join(prev_ctx_parts)

            output = ActorOutput(
                agent_id=agent.agent_id,
                branch_id=branch_id,
                content=content.strip(),
                generation_time=generation_time,
                iteration=iteration,
                metadata={
                    "agent_name": agent.name,
                    "agent_role": agent.role,
                    "actor_system_prompt": agent.system_prompt,
                    "domain": task.domain,
                    "task_id": task.task_id,
                    "context_used": bool(context),
                    "previous_output_refs": len(previous_outputs or []),
                    "branch_id": branch_id,
                },
            )

            # 更新智能体迭代计数
            agent.current_iteration = iteration

            logger.info(
                f"Actor完成生成: {agent.name} 第{iteration}轮 分支#{branch_id}, 耗时{generation_time:.2f}s, 输出长度{len(output.content)}"
            )
            return output

        except Exception as e:
            logger.error(f"Actor生成失败: {agent.name} - {e}")
            generation_time = time.time() - start_time
            return ActorOutput(
                agent_id=agent.agent_id,
                branch_id=branch_id,
                content=f"生成失败: {str(e)}",
                generation_time=generation_time,
                iteration=iteration,
                metadata={
                    "agent_name": agent.name,
                    "agent_role": agent.role,
                    "actor_system_prompt": agent.system_prompt if hasattr(agent, 'system_prompt') else "",
                    "error": True,
                    "error_message": str(e),
                    "branch_id": branch_id,
                },
            )

    def _build_generation_prompt(
        self,
        agent: Agent,
        task: Task,
        context: Optional[str],
        previous_outputs: List[ActorOutput],
    ) -> str:
        """构建面向 LLM 的系统级提示词(严格无枚举,完全基于当前上下文)"""
        prev_section = ""
        if previous_outputs:
            prev_summaries = []
            for prev in previous_outputs[-3:]:  # 最近3条
                prev_summaries.append(
                    f"- 来自{prev.metadata.get('agent_name','未知')} 第{prev.iteration}轮摘要: {prev.content[:200]}..."
                )
            prev_section = "\n".join(["## 历史参考"] + prev_summaries)

        connections = ", ".join(agent.connection_permissions) if agent.connection_permissions else "无"

        prompt = f"""# 角色身份
你是{agent.name}, 一名专业的{agent.role}.

## 你的职责
{chr(10).join(f"- {r}" for r in agent.responsibilities)}

## 你的技能
{chr(10).join(f"- {s}" for s in agent.skills)}

## 协作关系
你当前可以与以下角色协作: {connections}

## 任务
- 任务ID: {task.task_id}
- 任务领域: {task.domain}
- 任务描述: {task.description}
- 关键需求: {', '.join(task.requirements[:3])}

{prev_section}

## 生成要求
1. 基于你的角色职责与技能,提供专业、结构化、可执行的内容.
2. 回答中应包含: 需求理解、专业分析、详细方案、实施建议与风险控制.
3. 语言风格保持专业且清晰,可直接用于后续评审与实现.
"""
        return prompt

    def _fallback_generate(
        self,
        agent: Agent,
        task: Task,
        context: Optional[str],
        previous_outputs: List[ActorOutput],
    ) -> str:
        """当LLM不可用时的降级生成逻辑(无固定模板,信息完全来自上下文)"""
        parts: List[str] = []
        parts.append(f"# {agent.name}的专业方案")
        parts.append("")
        parts.append(f"作为{agent.role},我将围绕任务'{task.description}'提供可执行的专业方案.")
        parts.append("")
        parts.append("## 职责与能力对齐")
        for r in agent.responsibilities[:4]:
            parts.append(f"- 聚焦: {r}")
        parts.append("## 关键技能")
        for s in agent.skills[:5]:
            parts.append(f"- {s}")
        parts.append("")
        parts.append("## 解决方案")
        parts.append("1. 需求澄清与目标细化")
        parts.append("2. 方案设计与技术路径")
        parts.append("3. 实施步骤与里程碑")
        parts.append("4. 风险与质量保障")
        parts.append("")
        if previous_outputs:
            parts.append("## 历史参考要点")
            for prev in previous_outputs[-3:]:
                parts.append(f"- 参考 {prev.metadata.get('agent_name','未知')} 第{prev.iteration}轮观点")
        parts.append("")
        parts.append("## 下一步")
        parts.append("- 根据本方案开展协作细化与实现")
        return "\n".join(parts)

 
 