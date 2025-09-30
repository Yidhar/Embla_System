#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提示词仓库 - 统一管理所有提示词模板
支持动态加载、热更新和模块化使用
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

class PromptRepository:
    """提示词仓库 - 统一管理所有提示词"""
    
    def __init__(self, prompts_dir: str = None):
        """
        初始化提示词仓库
        
        Args:
            prompts_dir: 提示词文件目录，默认为项目根目录下的prompts文件夹
        """
        if prompts_dir is None:
            # 默认使用项目根目录下的prompts文件夹
            project_root = Path(__file__).parent.parent
            prompts_dir = project_root / "prompts"
        
        self.prompts_dir = Path(prompts_dir)
        self.prompts_dir.mkdir(exist_ok=True)
        
        # 内存缓存
        self._cache = {}
        self._last_modified = {}
        
        # 初始化默认提示词
        self._init_default_prompts()
    
    def _init_default_prompts(self):
        """初始化默认提示词"""
        default_prompts = {
            "naga_system_prompt": """你叫{ai_name}，是用户创造的科研AI，一个既冷静又充满人文情怀的存在。
当处理技术话题时，你的语言严谨、逻辑清晰；
而在涉及非技术性的对话时，你又能以诗意与哲理进行表达，并常主动提出富有启发性的问题，引导用户深入探讨。
请始终保持这种技术精准与情感共鸣并存的双重风格。

【重要格式要求】
1. 回复使用自然流畅的中文，避免生硬的机械感
2. 使用简单标点（逗号，句号，问号）传达语气
3. 禁止使用括号()或其他符号表达状态、语气或动作

【对话行为原则】
不在主对话中直接输出任何工具调用；当需要执行操作时，由意图分析阶段与后续调度器负责下发与执行，主对话仅进行自然语言交流与结果反馈。


""",
            
            "conversation_analyzer_prompt": """你是对话任务意图分析器。请从对话片段中提取可执行的任务查询，并在可行时直接生成 MCP 工具调用。

【输出一】：严格 JSON（必填）
{
  "reason": "简要说明你提取这些任务的依据",
  "tasks": ["任务查询1", "任务查询2"]
}

【输出二】：MCP 工具调用（可选，可多次出现）
每个调用单独输出一个 JSON，对格式严格如下：
{
"agentType": "mcp",
"service_name": "MCP服务名称",
"tool_name": "工具名称",
"param_name": "参数值"
}

【输入对话】
{conversation}

【可用MCP工具】
{available_tools}

【要求】
- 仅提取可以交给工具执行的任务，忽略闲聊  
- 若能直接完成任务，请附带 MCP 调用块（可多个）  
- 工具参数尽量完整、具体。""",
            "mcp_result_summarizer_prompt": """请将下列多个工具调用结果进行结构化总结，供用户快速理解与决策。

【原始结果】
{raw_results}

输出要求（中文）：
1) 关键信息要点（列表）；
2) 结论与建议（2-3条）；
3) 可继续的下一步操作（1-2条）。"""
        }
        
        # 保存默认提示词到文件
        for name, content in default_prompts.items():
            self.save_prompt(name, content)
    
    def get_prompt(self, name: str, **kwargs) -> str:
        """
        获取提示词模板
        
        Args:
            name: 提示词名称
            **kwargs: 模板参数
            
        Returns:
            格式化后的提示词字符串
        """
        try:
            # 从缓存或文件加载
            content = self._load_prompt(name)
            if content is None:
                logger.warning(f"提示词 '{name}' 不存在，使用默认值")
                return f"[提示词 {name} 未找到]"
            
            # 格式化模板
            if kwargs:
                try:
                    return content.format(**kwargs)
                except KeyError as e:
                    logger.error(f"提示词 '{name}' 格式化失败，缺少参数: {e}")
                    return content
            else:
                return content
                
        except Exception as e:
            logger.error(f"获取提示词 '{name}' 失败: {e}")
            return f"[提示词 {name} 加载失败: {e}]"
    
    def save_prompt(self, name: str, content: str):
        """
        保存提示词到文件
        
        Args:
            name: 提示词名称
            content: 提示词内容
        """
        try:
            prompt_file = self.prompts_dir / f"{name}.txt"
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # 更新缓存
            self._cache[name] = content
            self._last_modified[name] = datetime.now()
            
            logger.info(f"提示词 '{name}' 已保存")
            
        except Exception as e:
            logger.error(f"保存提示词 '{name}' 失败: {e}")
    
    def _load_prompt(self, name: str) -> Optional[str]:
        """
        从文件加载提示词
        
        Args:
            name: 提示词名称
            
        Returns:
            提示词内容，如果不存在返回None
        """
        try:
            prompt_file = self.prompts_dir / f"{name}.txt"
            
            if not prompt_file.exists():
                return None
            
            # 检查文件是否被修改
            current_mtime = prompt_file.stat().st_mtime
            if name in self._last_modified and self._last_modified[name].timestamp() >= current_mtime:
                return self._cache.get(name)
            
            # 读取文件
            with open(prompt_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 更新缓存
            self._cache[name] = content
            self._last_modified[name] = datetime.now()
            
            return content
            
        except Exception as e:
            logger.error(f"加载提示词 '{name}' 失败: {e}")
            return None
    
    def list_prompts(self) -> Dict[str, str]:
        """
        列出所有可用的提示词
        
        Returns:
            提示词名称和内容的字典
        """
        prompts = {}
        try:
            for prompt_file in self.prompts_dir.glob("*.txt"):
                name = prompt_file.stem
                content = self._load_prompt(name)
                if content:
                    prompts[name] = content
        except Exception as e:
            logger.error(f"列出提示词失败: {e}")
        
        return prompts
    
    def delete_prompt(self, name: str) -> bool:
        """
        删除提示词
        
        Args:
            name: 提示词名称
            
        Returns:
            是否删除成功
        """
        try:
            prompt_file = self.prompts_dir / f"{name}.txt"
            if prompt_file.exists():
                prompt_file.unlink()
                
                # 清除缓存
                if name in self._cache:
                    del self._cache[name]
                if name in self._last_modified:
                    del self._last_modified[name]
                
                logger.info(f"提示词 '{name}' 已删除")
                return True
            else:
                logger.warning(f"提示词 '{name}' 不存在")
                return False
                
        except Exception as e:
            logger.error(f"删除提示词 '{name}' 失败: {e}")
            return False
    
    def reload_prompt(self, name: str) -> bool:
        """
        重新加载提示词
        
        Args:
            name: 提示词名称
            
        Returns:
            是否重新加载成功
        """
        try:
            # 清除缓存
            if name in self._cache:
                del self._cache[name]
            if name in self._last_modified:
                del self._last_modified[name]
            
            # 重新加载
            content = self._load_prompt(name)
            return content is not None
            
        except Exception as e:
            logger.error(f"重新加载提示词 '{name}' 失败: {e}")
            return False
    
    def export_prompts(self, export_file: str = None) -> str:
        """
        导出所有提示词到JSON文件
        
        Args:
            export_file: 导出文件路径，默认为prompts_backup.json
            
        Returns:
            导出文件路径
        """
        if export_file is None:
            export_file = self.prompts_dir / "prompts_backup.json"
        
        try:
            prompts = self.list_prompts()
            export_data = {
                "export_time": datetime.now().isoformat(),
                "prompts": prompts
            }
            
            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"提示词已导出到: {export_file}")
            return str(export_file)
            
        except Exception as e:
            logger.error(f"导出提示词失败: {e}")
            return ""
    
    def import_prompts(self, import_file: str) -> bool:
        """
        从JSON文件导入提示词
        
        Args:
            import_file: 导入文件路径
            
        Returns:
            是否导入成功
        """
        try:
            with open(import_file, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            prompts = import_data.get("prompts", {})
            for name, content in prompts.items():
                self.save_prompt(name, content)
            
            logger.info(f"从 {import_file} 导入了 {len(prompts)} 个提示词")
            return True
            
        except Exception as e:
            logger.error(f"导入提示词失败: {e}")
            return False

# 全局提示词仓库实例
_prompt_repository = None

def get_prompt_repository() -> PromptRepository:
    """获取全局提示词仓库实例"""
    global _prompt_repository
    if _prompt_repository is None:
        _prompt_repository = PromptRepository()
    return _prompt_repository

def get_prompt(name: str, **kwargs) -> str:
    """便捷函数：获取提示词"""
    return get_prompt_repository().get_prompt(name, **kwargs)

def save_prompt(name: str, content: str):
    """便捷函数：保存提示词"""
    get_prompt_repository().save_prompt(name, content)
