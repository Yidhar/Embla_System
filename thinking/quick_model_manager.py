"""
快速响应小模型管理器
提供快速决策、JSON格式化、问题难度判断、结果打分、思考完整性判断等功能
"""

import asyncio
import logging
import json
import time
import re
from typing import Dict, Any, Optional, Union, List
from nagaagent_core.core import AsyncOpenAI
from system.config import (
    QUICK_MODEL_CONFIG, 
    OUTPUT_FILTER_CONFIG,
    DIFFICULTY_JUDGMENT_CONFIG,
    SCORING_SYSTEM_CONFIG,
    THINKING_COMPLETENESS_CONFIG,
    QUICK_DECISION_SYSTEM_PROMPT, 
    JSON_FORMAT_SYSTEM_PROMPT,
    DIFFICULTY_JUDGMENT_SYSTEM_PROMPT,
    RESULT_SCORING_SYSTEM_PROMPT,
    THINKING_COMPLETENESS_SYSTEM_PROMPT,
    NEXT_QUESTION_SYSTEM_PROMPT,
    API_KEY, 
    BASE_URL, 
    MODEL,
    config
)

logger = logging.getLogger("QuickModelManager")

# 全局变量保护机制，避免重复初始化
_QUICK_MODEL_MANAGER_GLOBAL_INITIALIZED = False

class QuickModelManager:
    """快速响应小模型管理器"""
    
    def __init__(self):
        self.config = QUICK_MODEL_CONFIG
        self.enabled = self.config["enabled"]
        
        # 初始化小模型客户端
        self.quick_client = None
        if self.enabled and self.config["api_key"] and self.config["base_url"]:
            try:
                self.quick_client = AsyncOpenAI(
                    api_key=self.config["api_key"],
                    base_url=self.config["base_url"].rstrip('/') + '/'
                )
                # 只在首次初始化时输出日志
                global _QUICK_MODEL_MANAGER_GLOBAL_INITIALIZED
                if not _QUICK_MODEL_MANAGER_GLOBAL_INITIALIZED:
                    logger.info(f"快速模型初始化成功: {self.config['model_name']}")
                    _QUICK_MODEL_MANAGER_GLOBAL_INITIALIZED = True
            except Exception as e:
                logger.warning(f"快速模型初始化失败: {e}")
                self.enabled = False
        
        # 备用大模型客户端
        self.fallback_client = AsyncOpenAI(
            api_key=API_KEY,
            base_url=BASE_URL.rstrip('/') + '/'
        )
        
        # 统计信息
        self.stats = {
            "quick_model_calls": 0,
            "quick_model_successes": 0,
            "quick_model_failures": 0,
            "fallback_calls": 0,
            "total_time_saved": 0.0,
            "difficulty_judgments": 0,
            "scoring_operations": 0,
            "completeness_checks": 0,
            "outputs_filtered": 0
        }
        
        # 针对不同决策类型的专用系统提示词
        self.decision_system_prompts = {
            "binary": """你是一个二元判断助手，专门进行是/否的判断。
请根据用户的问题，仅回答"是"或"否"，不要添加任何解释或其他内容。
如果问题无法明确判断，请回答"否"。
【重要】：只输出最终结果，不要包含思考过程或<think>标签。""",
            
            "category": """你是一个分类助手，专门进行内容分类。
请根据用户的问题，给出简洁明确的分类结果。
只返回分类名称，不要添加解释。例如：技术问题、生活问题、学习问题等。
【重要】：只输出最终结果，不要包含思考过程或<think>标签。""",
            
            "score": """你是一个评分助手，专门进行数值评分。
请根据用户的问题，给出1-10的数值评分。
只返回数字，不要添加任何文字说明。例如：8
【重要】：只输出最终结果，不要包含思考过程或<think>标签。""",
            
            "priority": """你是一个优先级判断助手，专门判断任务优先级。
请根据用户描述，判断优先级等级。
只返回：高、中、低 其中之一，不要添加解释。
【重要】：只输出最终结果，不要包含思考过程或<think>标签。""",
            
            "sentiment": """你是一个情感分析助手，专门分析文本情感倾向。
请分析给定文本的情感倾向。
只返回：积极、消极、中性 其中之一，不要添加解释。
【重要】：只输出最终结果，不要包含思考过程或<think>标签。""",
            
            "urgency": """你是一个紧急度判断助手，专门判断事件紧急程度。
请根据用户描述，判断紧急程度。
只返回：紧急、普通、不紧急 其中之一，不要添加解释。
【重要】：只输出最终结果，不要包含思考过程或<think>标签。""",
            
            "complexity": """你是一个复杂度评估助手，专门评估任务复杂程度。
请根据用户描述，评估复杂度等级。
只返回：简单、中等、复杂 其中之一，不要添加解释。
【重要】：只输出最终结果，不要包含思考过程或<think>标签。""",
            
            "custom": """你是一个快速判断助手，专门进行简单决策。
请根据用户的问题给出简洁明确的判断结果，保持回答简短准确。
【重要】：只输出最终结果，不要包含思考过程或<think>标签。"""
        }
        
        # 只在首次初始化时输出日志
        if not _QUICK_MODEL_MANAGER_GLOBAL_INITIALIZED:
            logger.info(f"快速模型管理器初始化 - 启用状态: {self.enabled}")
            _QUICK_MODEL_MANAGER_GLOBAL_INITIALIZED = True
    
    def _filter_output(self, output: str) -> str:
        """过滤输出内容，移除<think>等标签内容"""
        if not OUTPUT_FILTER_CONFIG.get("filter_think_tags", True):
            return output
        
        filtered = output
        
        # 应用过滤模式
        for pattern in OUTPUT_FILTER_CONFIG.get("filter_patterns", []):
            filtered = re.sub(pattern, '', filtered, flags=re.DOTALL | re.IGNORECASE)
        
        # 清理多余空白字符
        if OUTPUT_FILTER_CONFIG.get("clean_output", True):
            filtered = re.sub(r'\s+', ' ', filtered).strip()
        
        # 记录过滤统计
        if filtered != output:
            self.stats["outputs_filtered"] += 1
            logger.debug(f"输出已过滤: {output[:50]}... -> {filtered[:50]}...")
        
        return filtered

    async def quick_decision(self, prompt: str, context: str = "", 
                           decision_type: str = "binary") -> Dict[str, Any]:
        """
        快速决策功能
        
        Args:
            prompt: 决策问题
            context: 上下文信息
            decision_type: 决策类型 (binary/category/score/priority/sentiment/urgency/complexity/custom)
        
        Returns:
            包含决策结果的字典
        """
        start_time = time.time()
        
        # 获取专用系统提示词
        system_prompt = self.decision_system_prompts.get(decision_type, self.decision_system_prompts["custom"])
        
        # 构建决策提示词
        decision_prompt = self._build_decision_prompt(prompt, context, decision_type)
        
        # 尝试使用快速模型
        if self.enabled and self.quick_client:
            try:
                result = await self._call_quick_model(
                    decision_prompt, 
                    system_prompt
                )
                
                if result:
                    # 过滤输出内容
                    filtered_result = self._filter_output(result)
                    # 验证输出格式
                    validated_result = self._validate_decision_output(filtered_result, decision_type)
                    
                    self.stats["quick_model_calls"] += 1
                    self.stats["quick_model_successes"] += 1
                    self.stats["total_time_saved"] += (time.time() - start_time)
                    
                    return {
                        "decision": validated_result,
                        "raw_output": result,
                        "filtered_output": filtered_result,
                        "model_used": "quick",
                        "response_time": time.time() - start_time,
                        "decision_type": decision_type
                    }
            except Exception as e:
                logger.warning(f"快速决策失败，降级到大模型: {e}")
                self.stats["quick_model_failures"] += 1
        
        # 降级到大模型
        try:
            result = await self._call_fallback_model(
                decision_prompt, 
                system_prompt
            )
            
            self.stats["fallback_calls"] += 1
            # 过滤和验证输出
            filtered_result = self._filter_output(result)
            validated_result = self._validate_decision_output(filtered_result, decision_type)
            
            return {
                "decision": validated_result,
                "raw_output": result,
                "filtered_output": filtered_result,
                "model_used": "fallback",
                "response_time": time.time() - start_time,
                "decision_type": decision_type
            }
        except Exception as e:
            logger.error(f"大模型决策也失败: {e}")
            return {
                "decision": self._get_fallback_decision(decision_type),
                "raw_output": "",
                "filtered_output": "",
                "model_used": "none",
                "response_time": time.time() - start_time,
                "error": str(e)
            }
    
    async def format_json(self, content: str, schema: Dict = None, 
                         format_type: str = "auto") -> Dict[str, Any]:
        """
        JSON格式化功能
        
        Args:
            content: 要格式化的内容
            schema: JSON模式定义
            format_type: 格式化类型 (auto/structured/simple)
        
        Returns:
            包含格式化结果的字典
        """
        start_time = time.time()
        
        # 构建格式化提示词
        format_prompt = self._build_format_prompt(content, schema, format_type)
        
        # 尝试使用快速模型
        if self.enabled and self.quick_client:
            try:
                result = await self._call_quick_model(
                    format_prompt, 
                    JSON_FORMAT_SYSTEM_PROMPT
                )
                
                if result:
                    # 过滤输出内容
                    filtered_result = self._filter_output(result)
                    
                    # 验证JSON格式
                    try:
                        parsed_json = json.loads(filtered_result)
                        self.stats["quick_model_calls"] += 1
                        self.stats["quick_model_successes"] += 1
                        self.stats["total_time_saved"] += (time.time() - start_time)
                        
                        return {
                            "json_result": parsed_json,
                            "raw_output": result,
                            "filtered_output": filtered_result,
                            "model_used": "quick",
                            "response_time": time.time() - start_time,
                            "format_type": format_type,
                            "valid_json": True
                        }
                    except json.JSONDecodeError as e:
                        logger.warning(f"快速模型JSON格式无效，降级到大模型: {e}")
                        self.stats["quick_model_failures"] += 1
            except Exception as e:
                logger.warning(f"快速格式化失败，降级到大模型: {e}")
                self.stats["quick_model_failures"] += 1
        
        # 降级到大模型
        try:
            result = await self._call_fallback_model(
                format_prompt, 
                JSON_FORMAT_SYSTEM_PROMPT
            )
            
            self.stats["fallback_calls"] += 1
            # 过滤输出内容
            filtered_result = self._filter_output(result)
            
            # 验证JSON格式
            try:
                parsed_json = json.loads(filtered_result)
                return {
                    "json_result": parsed_json,
                    "raw_output": result,
                    "filtered_output": filtered_result,
                    "model_used": "fallback",
                    "response_time": time.time() - start_time,
                    "format_type": format_type,
                    "valid_json": True
                }
            except json.JSONDecodeError as e:
                return {
                    "json_result": None,
                    "raw_output": result,
                    "filtered_output": filtered_result,
                    "model_used": "fallback",
                    "response_time": time.time() - start_time,
                    "format_type": format_type,
                    "valid_json": False,
                    "error": str(e)
                }
                
        except Exception as e:
            logger.error(f"大模型JSON格式化也失败: {e}")
            return {
                "json_result": None,
                "raw_output": "",
                "filtered_output": "",
                "model_used": "none",
                "response_time": time.time() - start_time,
                "error": str(e)
            }
    
    def _build_decision_prompt(self, prompt: str, context: str, 
                              decision_type: str) -> str:
        """构建决策提示词"""
        base_prompt = f"请对以下问题进行判断：\n\n{prompt}"
        
        if context:
            base_prompt += f"\n\n上下文信息：\n{context}"
        
        # 根据决策类型添加特定的输出要求
        output_instructions = {
            "binary": "\n\n请只回答：是 或 否",
            "category": "\n\n请给出简洁的分类名称",
            "score": "\n\n请给出1-10的数字评分",
            "priority": "\n\n请判断优先级：高、中、低",
            "sentiment": "\n\n请分析情感倾向：积极、消极、中性",
            "urgency": "\n\n请判断紧急程度：紧急、普通、不紧急",
            "complexity": "\n\n请评估复杂度：简单、中等、复杂",
            "custom": "\n\n请给出简洁的判断结果"
        }
        
        base_prompt += output_instructions.get(decision_type, output_instructions["custom"])
        return base_prompt
    
    def _validate_decision_output(self, output: str, decision_type: str) -> str:
        """验证和标准化决策输出"""
        output = output.strip()
        
        # 根据决策类型进行验证和标准化
        if decision_type == "binary":
            # 二元判断标准化
            if any(word in output for word in ["是", "yes", "对", "正确", "true", "1"]):
                return "是"
            elif any(word in output for word in ["否", "no", "错", "错误", "false", "0"]):
                return "否"
            else:
                # 如果输出不明确，返回原输出但加上警告
                return f"{output}(格式异常)"
        
        elif decision_type == "score":
            # 评分标准化
            import re
            numbers = re.findall(r'\d+', output)
            if numbers:
                score = int(numbers[0])
                return str(min(10, max(1, score)))  # 限制在1-10范围
            else:
                return "5(默认值)"
        
        elif decision_type == "priority":
            # 优先级标准化
            if any(word in output for word in ["高", "重要", "urgent", "high"]):
                return "高"
            elif any(word in output for word in ["低", "不重要", "low"]):
                return "低"
            else:
                return "中"
        
        elif decision_type == "sentiment":
            # 情感分析标准化
            if any(word in output for word in ["积极", "正面", "positive", "好", "满意"]):
                return "积极"
            elif any(word in output for word in ["消极", "负面", "negative", "坏", "不满"]):
                return "消极"
            else:
                return "中性"
        
        elif decision_type == "urgency":
            # 紧急度标准化
            if any(word in output for word in ["紧急", "急", "立即", "urgent"]):
                return "紧急"
            elif any(word in output for word in ["不紧急", "不急", "缓慢"]):
                return "不紧急"
            else:
                return "普通"
        
        elif decision_type == "complexity":
            # 复杂度标准化
            if any(word in output for word in ["复杂", "困难", "complex", "hard"]):
                return "复杂"
            elif any(word in output for word in ["简单", "容易", "simple", "easy"]):
                return "简单"
            else:
                return "中等"
        
        # 其他类型直接返回
        return output
    
    def _get_fallback_decision(self, decision_type: str) -> str:
        """获取降级默认决策结果"""
        fallback_decisions = {
            "binary": "否",
            "category": "未分类",
            "score": "5",
            "priority": "中",
            "sentiment": "中性",
            "urgency": "普通",
            "complexity": "中等",
            "custom": "无法判断"
        }
        
        return fallback_decisions.get(decision_type, "无法判断")
    
    def _build_format_prompt(self, content: str, schema: Dict, 
                           format_type: str) -> str:
        """构建格式化提示词"""
        base_prompt = f"请将以下内容转换为JSON格式：\n\n{content}"
        
        if schema:
            base_prompt += f"\n\n请按照以下模式格式化：\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
        elif format_type == "structured":
            base_prompt += """\n\n请使用结构化格式，包含以下字段：
{
  "title": "标题",
  "content": "主要内容", 
  "summary": "摘要",
  "keywords": ["关键词1", "关键词2"]
}"""
        elif format_type == "simple":
            base_prompt += """\n\n请使用简单格式：
{
  "result": "处理结果",
  "status": "成功/失败"
}"""
        
        base_prompt += "\n\n只输出JSON，不要其他内容："
        
        return base_prompt
    
    async def _call_quick_model(self, prompt: str, system_prompt: str) -> Optional[str]:
        """调用快速模型"""
        try:
            response = await asyncio.wait_for(
                self.quick_client.chat.completions.create(
                    model=self.config["model_name"],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.config["temperature"],
                    max_tokens=config.api.max_tokens
                ),
                timeout=self.config["timeout"]
            )
            
            return response.choices[0].message.content
            
        except asyncio.TimeoutError:
            logger.warning("快速模型调用超时")
            return None
        except RuntimeError as e:
            if "handler is closed" in str(e):
                logger.debug(f"忽略连接关闭异常: {e}")
                return None
            else:
                logger.warning(f"快速模型调用失败: {e}")
                return None
        except Exception as e:
            logger.warning(f"快速模型调用失败: {e}")
            return None
    
    async def _call_fallback_model(self, prompt: str, system_prompt: str) -> str:
        """调用备用大模型"""
        try:
            response = await self.fallback_client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=config.api.max_tokens
            )
            
            return response.choices[0].message.content
        except RuntimeError as e:
            if "handler is closed" in str(e):
                logger.debug(f"忽略连接关闭异常，重新创建客户端: {e}")
                # 重新创建客户端并重试
                self.fallback_client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL.rstrip('/') + '/')
                response = await self.fallback_client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=config.api.max_tokens
                )
                return response.choices[0].message.content
            else:
                raise
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_calls = self.stats["quick_model_calls"] + self.stats["fallback_calls"]
        
        if total_calls > 0:
            quick_success_rate = self.stats["quick_model_successes"] / self.stats["quick_model_calls"] if self.stats["quick_model_calls"] > 0 else 0
            quick_usage_rate = self.stats["quick_model_calls"] / total_calls
        else:
            quick_success_rate = 0
            quick_usage_rate = 0
        
        return {
            "enabled": self.enabled,
            "model_name": self.config["model_name"] if self.enabled else "未配置",
            "total_calls": total_calls,
            "quick_model_calls": self.stats["quick_model_calls"],
            "quick_model_successes": self.stats["quick_model_successes"],
            "quick_model_failures": self.stats["quick_model_failures"],
            "fallback_calls": self.stats["fallback_calls"],
            "quick_success_rate": f"{quick_success_rate:.2%}",
            "quick_usage_rate": f"{quick_usage_rate:.2%}",
            "total_time_saved": f"{self.stats['total_time_saved']:.2f}秒",
            
            # 新功能统计
            "difficulty_judgments": self.stats["difficulty_judgments"],
            "scoring_operations": self.stats["scoring_operations"],
            "completeness_checks": self.stats["completeness_checks"],
            "outputs_filtered": self.stats["outputs_filtered"],
            
            # 功能启用状态
            "features": {
                "difficulty_judgment": DIFFICULTY_JUDGMENT_CONFIG.get("enabled", True),
                "scoring_system": SCORING_SYSTEM_CONFIG.get("enabled", True),
                "thinking_completeness": THINKING_COMPLETENESS_CONFIG.get("enabled", True),
                "output_filter": OUTPUT_FILTER_CONFIG.get("filter_think_tags", True)
            }
        }
    
    def is_enabled(self) -> bool:
        """检查是否启用"""
        return self.enabled
    
    def update_config(self, new_config: Dict[str, Any]) -> bool:
        """更新配置"""
        try:
            # 更新配置
            for key, value in new_config.items():
                if key in self.config:
                    self.config[key] = value
            
            # 重新初始化客户端
            if self.config["enabled"] and self.config["api_key"] and self.config["base_url"]:
                self.quick_client = AsyncOpenAI(
                    api_key=self.config["api_key"],
                    base_url=self.config["base_url"].rstrip('/') + '/'
                )
                self.enabled = True
                logger.info("快速模型配置更新成功")
                return True
            else:
                self.enabled = False
                logger.info("快速模型已禁用")
                return True
                
        except Exception as e:
            logger.error(f"更新快速模型配置失败: {e}")
            return False
    
    async def judge_difficulty(self, question: str, context: str = "") -> Dict[str, Any]:
        """
        判断问题难度
        
        Args:
            question: 问题内容
            context: 上下文信息
        
        Returns:
            包含难度判断结果的字典
        """
        if not DIFFICULTY_JUDGMENT_CONFIG.get("enabled", True):
            return {"difficulty": "中等", "model_used": "disabled"}
        
        start_time = time.time()
        
        # 构建判断提示词
        prompt = f"请判断以下问题的难度：\n\n{question}"
        if context:
            prompt += f"\n\n上下文：{context}"
        
        try:
            # 尝试使用小模型
            if self.enabled and self.quick_client:
                result = await self._call_quick_model(
                    prompt, 
                    DIFFICULTY_JUDGMENT_SYSTEM_PROMPT
                )
                
                if result:
                    filtered_result = self._filter_output(result)
                    difficulty = self._validate_difficulty(filtered_result)
                    
                    self.stats["difficulty_judgments"] += 1
                    self.stats["quick_model_successes"] += 1
                    
                    return {
                        "difficulty": difficulty,
                        "raw_output": result,
                        "filtered_output": filtered_result,
                        "model_used": "quick",
                        "response_time": time.time() - start_time
                    }
            
            # 降级到大模型
            result = await self._call_fallback_model(prompt, DIFFICULTY_JUDGMENT_SYSTEM_PROMPT)
            filtered_result = self._filter_output(result)
            difficulty = self._validate_difficulty(filtered_result)
            
            self.stats["difficulty_judgments"] += 1
            self.stats["fallback_calls"] += 1
            
            return {
                "difficulty": difficulty,
                "raw_output": result,
                "filtered_output": filtered_result,
                "model_used": "fallback",
                "response_time": time.time() - start_time
            }
            
        except Exception as e:
            logger.error(f"难度判断失败: {e}")
            return {
                "difficulty": "中等",
                "model_used": "error",
                "error": str(e)
            }
    
    async def score_results(self, results: List[Dict], user_preferences: List[str] = None) -> List[Dict]:
        """
        对结果进行黑白名单打分
        
        Args:
            results: 思考结果列表
            user_preferences: 用户偏好列表
        
        Returns:
            包含评分的结果列表，已按分数排序和过滤
        """
        if not SCORING_SYSTEM_CONFIG.get("enabled", True):
            return results
        
        if not user_preferences:
            user_preferences = SCORING_SYSTEM_CONFIG.get("default_preferences", [])
        
        # 限制用户偏好数量
        max_prefs = SCORING_SYSTEM_CONFIG.get("max_user_preferences", 3)
        user_preferences = user_preferences[:max_prefs]
        
        scored_results = []
        
        for i, result in enumerate(results):
            try:
                # 构建评分提示
                prompt = f"""
请对以下思考结果进行评分：

思考结果：
{result.get('content', '')}

用户偏好：
{', '.join(user_preferences)}

请根据用户偏好对这个结果的匹配度和质量进行1-5分评分。
"""
                
                # 调用评分
                score_result = await self._get_score(prompt)
                score = score_result.get("score", 3)
                
                # 检查相似性惩罚
                similar_penalty = self._check_similarity_penalty(result, scored_results)
                final_score = max(1, score - similar_penalty)
                
                scored_result = result.copy()
                scored_result.update({
                    "score": final_score,
                    "original_score": score,
                    "similarity_penalty": similar_penalty,
                    "score_details": score_result
                })
                
                scored_results.append(scored_result)
                
            except Exception as e:
                logger.warning(f"评分失败，使用默认分数: {e}")
                scored_result = result.copy()
                scored_result["score"] = 3
                scored_results.append(scored_result)
        
        self.stats["scoring_operations"] += 1
        
        # 排序和过滤
        return self._filter_and_sort_results(scored_results)
    
    async def check_thinking_completeness(self, thinking_content: str, question: str = "") -> Dict[str, Any]:
        """
        检查思考完整性
        
        Args:
            thinking_content: 思考内容
            question: 原始问题
        
        Returns:
            包含完整性判断和可能的下一级问题的字典
        """
        if not THINKING_COMPLETENESS_CONFIG.get("enabled", True):
            return {"is_complete": True, "model_used": "disabled"}
        
        start_time = time.time()
        
        # 构建完整性判断提示
        prompt = f"""
请判断以下思考是否已经相对完整：

原始问题：{question}

思考内容：
{thinking_content}

请评估思考的完整性。
"""
        
        try:
            # 使用小模型判断完整性
            completeness_result = await self._call_quick_model(
                prompt, 
                THINKING_COMPLETENESS_SYSTEM_PROMPT
            )
            
            if completeness_result:
                filtered_result = self._filter_output(completeness_result)
                is_complete = filtered_result.strip() == "完整"
                
                result = {
                    "is_complete": is_complete,
                    "raw_output": completeness_result,
                    "filtered_output": filtered_result,
                    "model_used": "quick",
                    "response_time": time.time() - start_time
                }
                
                # 如果不完整，生成下一级问题
                if not is_complete and THINKING_COMPLETENESS_CONFIG.get("next_question_generation", True):
                    next_question = await self._generate_next_question(thinking_content, question)
                    result["next_question"] = next_question
                
                self.stats["completeness_checks"] += 1
                return result
            
        except Exception as e:
            logger.warning(f"完整性判断失败: {e}")
        
        # 默认认为完整
        return {
            "is_complete": True,
            "model_used": "error",
            "response_time": time.time() - start_time
        }
    
    async def _generate_next_question(self, thinking_content: str, original_question: str) -> str:
        """生成下一级思考问题"""
        prompt = f"""
基于以下不完整的思考，设计下一级需要深入思考的问题：

原始问题：{original_question}

当前思考：
{thinking_content}

请设计一个有助于完善思考的具体问题。
"""
        
        try:
            result = await self._call_quick_model(prompt, NEXT_QUESTION_SYSTEM_PROMPT)
            if result:
                return self._filter_output(result).strip()
        except Exception as e:
            logger.warning(f"生成下一级问题失败: {e}")
        
        return "需要进一步分析哪些方面？"
    
    async def _get_score(self, prompt: str) -> Dict[str, Any]:
        """获取评分结果"""
        try:
            if self.enabled and self.quick_client:
                result = await self._call_quick_model(prompt, RESULT_SCORING_SYSTEM_PROMPT)
                if result:
                    filtered_result = self._filter_output(result)
                    score = self._extract_score(filtered_result)
                    return {
                        "score": score,
                        "raw_output": result,
                        "filtered_output": filtered_result,
                        "model_used": "quick"
                    }
            
            # 降级到大模型
            result = await self._call_fallback_model(prompt, RESULT_SCORING_SYSTEM_PROMPT)
            filtered_result = self._filter_output(result)
            score = self._extract_score(filtered_result)
            
            return {
                "score": score,
                "raw_output": result,
                "filtered_output": filtered_result,
                "model_used": "fallback"
            }
            
        except Exception as e:
            logger.warning(f"获取评分失败: {e}")
            return {"score": 3, "error": str(e)}
    
    def _validate_difficulty(self, output: str) -> str:
        """验证和标准化难度输出"""
        output = output.strip()
        valid_levels = DIFFICULTY_JUDGMENT_CONFIG.get("difficulty_levels", ["简单", "中等", "困难", "极难"])
        
        for level in valid_levels:
            if level in output:
                return level
        
        # 默认返回中等
        return "中等"
    
    def _extract_score(self, output: str) -> int:
        """从输出中提取评分"""
        import re
        numbers = re.findall(r'\d+', output)
        if numbers:
            score = int(numbers[0])
            min_score, max_score = SCORING_SYSTEM_CONFIG.get("score_range", [1, 5])
            return max(min_score, min(max_score, score))
        return 3  # 默认分数
    
    def _check_similarity_penalty(self, current_result: Dict, existing_results: List[Dict]) -> int:
        """检查相似性惩罚"""
        threshold = SCORING_SYSTEM_CONFIG.get("similarity_threshold", 0.85)
        penalty = SCORING_SYSTEM_CONFIG.get("penalty_for_similar", 1)
        
        current_content = current_result.get('content', '')
        
        for existing in existing_results:
            if self._calculate_similarity(current_content, existing.get('content', '')) > threshold:
                return penalty
        
        return 0
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """简单的文本相似度计算"""
        if not text1 or not text2:
            return 0.0
        
        # 简单的词汇重叠相似度
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def _filter_and_sort_results(self, scored_results: List[Dict]) -> List[Dict]:
        """过滤和排序结果"""
        threshold = SCORING_SYSTEM_CONFIG.get("score_threshold", 2)
        min_required = SCORING_SYSTEM_CONFIG.get("min_results_required", 2)
        strict_filtering = SCORING_SYSTEM_CONFIG.get("strict_filtering", False)
        
        # 按分数排序
        scored_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        # 过滤低分结果：保留大于阈值的结果（2分及以下将被过滤）
        filtered_results = []
        high_score_results = [r for r in scored_results if r.get("score", 0) > threshold]
        
        # 记录详细的过滤过程
        logger.info(f"评分过滤详情:")
        logger.info(f"  - 阈值设置: {threshold}分（{threshold}分及以下将被过滤）")
        logger.info(f"  - 最少保留: {min_required}个结果")
        logger.info(f"  - 严格模式: {'启用' if strict_filtering else '禁用'}")
        logger.info(f"  - 原始结果数: {len(scored_results)}")
        for i, result in enumerate(scored_results):
            score = result.get("score", 0)
            status = "保留" if score > threshold else "过滤"
            logger.info(f"    结果{i+1}: {score}分 - {status}")
        logger.info(f"  - 高分结果数: {len(high_score_results)}个")
        
        if strict_filtering:
            # 严格模式：严格按阈值过滤，不保证最少数量
            filtered_results = high_score_results
            logger.info(f"  - 过滤策略: 严格模式，仅保留高分结果（{len(high_score_results)}个）")
        else:
            # 宽松模式：保证最少数量
            if len(high_score_results) >= min_required:
                filtered_results = high_score_results
                logger.info(f"  - 过滤策略: 使用高分结果（{len(high_score_results)}个）")
            else:
                # 如果高分结果不够，保留前N个最高分的
                filtered_results = scored_results[:min_required]
                logger.info(f"  - 过滤策略: 高分结果不足，保留前{min_required}个最高分结果")
        
        logger.info(f"  - 最终结果数: {len(filtered_results)}个")
        
        return filtered_results 