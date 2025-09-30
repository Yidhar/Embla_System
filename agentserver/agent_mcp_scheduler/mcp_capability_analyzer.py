#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP能力分析器 - 分析MCP工具调用的能力和可行性
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class MCPCapabilityAnalyzer:
    """MCP能力分析器"""
    
    def __init__(self):
        """初始化能力分析器"""
        self.available_services = {}
        self.service_capabilities = {}
        
        logger.info("MCP能力分析器初始化完成")
    
    async def analyze_capabilities(self, query: str, tool_calls: List[Dict]) -> Dict[str, Any]:
        """分析MCP能力"""
        try:
            # 分析查询类型
            query_type = self._analyze_query_type(query)
            
            # 分析工具调用
            tool_analysis = self._analyze_tool_calls(tool_calls)
            
            # 评估可行性
            feasibility = self._assess_feasibility(query_type, tool_analysis)
            
            return {
                "query_type": query_type,
                "tool_analysis": tool_analysis,
                "feasibility": feasibility,
                "recommendations": self._generate_recommendations(query_type, tool_analysis, feasibility)
            }
            
        except Exception as e:
            logger.error(f"能力分析失败: {e}")
            return {
                "query_type": "unknown",
                "tool_analysis": {"error": str(e)},
                "feasibility": {"score": 0, "reason": "分析失败"},
                "recommendations": []
            }
    
    def _analyze_query_type(self, query: str) -> str:
        """分析查询类型"""
        query_lower = query.lower()
        
        # 文件操作
        if any(keyword in query_lower for keyword in ["文件", "file", "读取", "read", "写入", "write"]):
            return "file_operation"
        
        # 网络请求
        elif any(keyword in query_lower for keyword in ["请求", "request", "http", "api", "网络", "network"]):
            return "network_request"
        
        # 数据处理
        elif any(keyword in query_lower for keyword in ["数据", "data", "处理", "process", "分析", "analyze"]):
            return "data_processing"
        
        # 系统控制
        elif any(keyword in query_lower for keyword in ["系统", "system", "控制", "control", "执行", "execute"]):
            return "system_control"
        
        # 搜索查询
        elif any(keyword in query_lower for keyword in ["搜索", "search", "查找", "find", "查询", "query"]):
            return "search_query"
        
        else:
            return "general"
    
    def _analyze_tool_calls(self, tool_calls: List[Dict]) -> Dict[str, Any]:
        """分析工具调用"""
        if not tool_calls:
            return {"count": 0, "tools": [], "complexity": "none"}
        
        tools = []
        complexity_score = 0
        
        for tool_call in tool_calls:
            tool_name = tool_call.get("tool_name", "unknown")
            service_name = tool_call.get("service_name", "unknown")
            
            tools.append({
                "name": tool_name,
                "service": service_name,
                "parameters": tool_call.get("parameters", {})
            })
            
            # 计算复杂度分数
            complexity_score += self._calculate_tool_complexity(tool_call)
        
        return {
            "count": len(tool_calls),
            "tools": tools,
            "complexity": self._get_complexity_level(complexity_score),
            "complexity_score": complexity_score
        }
    
    def _calculate_tool_complexity(self, tool_call: Dict) -> int:
        """计算工具复杂度"""
        complexity = 1  # 基础分数
        
        # 根据参数数量增加复杂度
        parameters = tool_call.get("parameters", {})
        complexity += len(parameters) * 0.5
        
        # 根据服务类型增加复杂度
        service_name = tool_call.get("service_name", "").lower()
        if "computer" in service_name or "control" in service_name:
            complexity += 2
        elif "file" in service_name or "data" in service_name:
            complexity += 1
        
        return int(complexity)
    
    def _get_complexity_level(self, score: float) -> str:
        """获取复杂度级别"""
        if score <= 2:
            return "simple"
        elif score <= 5:
            return "medium"
        else:
            return "complex"
    
    def _assess_feasibility(self, query_type: str, tool_analysis: Dict) -> Dict[str, Any]:
        """评估可行性"""
        score = 0
        reasons = []
        
        # 基于查询类型评分
        if query_type == "file_operation":
            score += 3
            reasons.append("文件操作支持良好")
        elif query_type == "network_request":
            score += 2
            reasons.append("网络请求需要验证")
        elif query_type == "data_processing":
            score += 3
            reasons.append("数据处理能力充足")
        elif query_type == "system_control":
            score += 1
            reasons.append("系统控制需要权限验证")
        elif query_type == "search_query":
            score += 4
            reasons.append("搜索查询支持优秀")
        else:
            score += 2
            reasons.append("通用查询支持")
        
        # 基于工具复杂度调整
        complexity = tool_analysis.get("complexity", "simple")
        if complexity == "simple":
            score += 2
            reasons.append("工具调用简单")
        elif complexity == "medium":
            score += 1
            reasons.append("工具调用中等复杂度")
        else:
            score -= 1
            reasons.append("工具调用复杂，可能影响成功率")
        
        # 基于工具数量调整
        tool_count = tool_analysis.get("count", 0)
        if tool_count == 0:
            score = 0
            reasons.append("没有可用的工具调用")
        elif tool_count == 1:
            score += 1
            reasons.append("单一工具调用，执行简单")
        elif tool_count <= 3:
            score += 0
            reasons.append("多个工具调用，需要协调")
        else:
            score -= 1
            reasons.append("工具调用过多，可能影响性能")
        
        # 确定可行性等级
        if score >= 4:
            feasibility_level = "high"
        elif score >= 2:
            feasibility_level = "medium"
        else:
            feasibility_level = "low"
        
        return {
            "score": max(0, min(5, score)),
            "level": feasibility_level,
            "reasons": reasons
        }
    
    def _generate_recommendations(self, query_type: str, tool_analysis: Dict, feasibility: Dict) -> List[str]:
        """生成建议"""
        recommendations = []
        
        feasibility_level = feasibility.get("level", "low")
        complexity = tool_analysis.get("complexity", "simple")
        tool_count = tool_analysis.get("count", 0)
        
        if feasibility_level == "low":
            recommendations.append("建议简化查询或使用更简单的工具调用")
        
        if complexity == "complex":
            recommendations.append("建议将复杂任务分解为多个简单步骤")
        
        if tool_count > 3:
            recommendations.append("建议减少同时执行的工具调用数量")
        
        if query_type == "system_control":
            recommendations.append("系统控制操作需要谨慎，建议先测试")
        
        if query_type == "network_request":
            recommendations.append("网络请求需要验证目标服务可用性")
        
        return recommendations
    
    def get_status(self) -> Dict[str, Any]:
        """获取分析器状态"""
        return {
            "enabled": True,
            "available_services": len(self.available_services),
            "service_capabilities": len(self.service_capabilities)
        }
