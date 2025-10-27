#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用任务调度器使用示例
展示如何将智能记忆管理集成到Agent服务中
"""

import asyncio
import json
from typing import Dict, Any
from task_scheduler import get_task_scheduler, TaskStep

async def example_usage():
    """使用示例"""
    
    # 获取任务调度器实例
    scheduler = get_task_scheduler()
    
    # 设置LLM配置（用于智能压缩）
    llm_config = {
        "model": "gpt-3.5-turbo",
        "api_key": "your-api-key",
        "api_base": "https://api.openai.com/v1"
    }
    scheduler.set_llm_config(llm_config)
    
    # 示例1: 基本任务执行
    print("=== 示例1: 基本任务执行 ===")
    tasks = [
        {
            "id": "task_001",
            "type": "file_operation",
            "purpose": "读取配置文件",
            "params": {"file_path": "/etc/config.json", "operation": "read"}
        },
        {
            "id": "task_002", 
            "type": "network_request",
            "purpose": "获取API数据",
            "params": {"url": "https://api.example.com/data", "method": "GET"}
        }
    ]
    
    results = await scheduler.schedule_parallel_execution(tasks)
    print(f"执行结果: {results}")
    
    # 示例2: 手动添加任务步骤
    print("\n=== 示例2: 手动添加任务步骤 ===")
    task_id = "task_003"
    
    # 添加成功步骤
    step1 = TaskStep(
        step_id="step_001",
        task_id=task_id,
        purpose="连接数据库",
        content="mysql -h localhost -u root -p",
        output="连接成功，数据库版本: 8.0.25",
        success=True
    )
    await scheduler.add_task_step(task_id, step1)
    
    # 添加失败步骤
    step2 = TaskStep(
        step_id="step_002", 
        task_id=task_id,
        purpose="执行查询",
        content="SELECT * FROM users WHERE id = 999",
        output="",
        success=False,
        error="表 'users' 不存在"
    )
    await scheduler.add_task_step(task_id, step2)
    
    # 添加带分析的步骤
    step3 = TaskStep(
        step_id="step_003",
        task_id=task_id,
        purpose="分析错误",
        content="SHOW TABLES",
        output="tables: ['products', 'orders', 'customers']",
        analysis={
            "analysis": "发现关键问题：用户表名为'customers'而非'users'，需要修正查询语句"
        },
        success=True
    )
    await scheduler.add_task_step(task_id, step3)
    
    # 示例3: 获取记忆摘要
    print("\n=== 示例3: 获取记忆摘要 ===")
    
    # 获取任务记忆摘要
    task_summary = await scheduler.get_task_memory_summary(task_id)
    print(f"任务 {task_id} 记忆摘要:\n{task_summary}")
    
    # 获取全局记忆摘要
    global_summary = await scheduler.get_global_memory_summary()
    print(f"\n全局记忆摘要:\n{global_summary}")
    
    # 获取失败尝试摘要
    failed_attempts = await scheduler.get_failed_attempts_summary()
    print(f"\n失败尝试摘要: {failed_attempts}")
    
    # 示例4: 任务状态查询
    print("\n=== 示例4: 任务状态查询 ===")
    
    # 查询特定任务状态
    task_status = await scheduler.get_task_status("task_001")
    print(f"任务状态: {task_status}")
    
    # 获取运行中任务
    running_tasks = await scheduler.get_running_tasks()
    print(f"运行中任务: {running_tasks}")

async def agent_integration_example():
    """Agent服务集成示例"""
    
    scheduler = get_task_scheduler()
    
    # 模拟Agent执行流程
    class ExampleAgent:
        def __init__(self, agent_id: str):
            self.agent_id = agent_id
            self.scheduler = scheduler
        
        async def execute_task(self, task_description: str) -> Dict[str, Any]:
            """执行任务并记录步骤"""
            task_id = f"{self.agent_id}_{int(asyncio.get_event_loop().time())}"
            
            # 步骤1: 分析任务
            analysis_step = TaskStep(
                step_id=f"{task_id}_analysis",
                task_id=task_id,
                purpose="分析任务需求",
                content=f"分析任务: {task_description}",
                output="任务分析完成，需要执行3个子步骤",
                success=True
            )
            await self.scheduler.add_task_step(task_id, analysis_step)
            
            # 步骤2: 执行子任务
            execution_step = TaskStep(
                step_id=f"{task_id}_execution",
                task_id=task_id,
                purpose="执行主要任务",
                content=f"执行: {task_description}",
                output="任务执行成功，生成了结果文件",
                success=True
            )
            await self.scheduler.add_task_step(task_id, execution_step)
            
            # 步骤3: 验证结果
            validation_step = TaskStep(
                step_id=f"{task_id}_validation",
                task_id=task_id,
                purpose="验证执行结果",
                content="验证输出文件完整性",
                output="验证通过，文件大小: 1024KB",
                analysis={
                    "analysis": "关键发现：任务执行成功，输出文件格式正确，可以进入下一阶段"
                },
                success=True
            )
            await self.scheduler.add_task_step(task_id, validation_step)
            
            return {
                "task_id": task_id,
                "status": "completed",
                "result": "任务执行成功"
            }
    
    # 创建Agent实例
    agent = ExampleAgent("agent_001")
    
    # 执行任务
    result = await agent.execute_task("处理用户数据并生成报告")
    print(f"Agent执行结果: {result}")
    
    # 获取任务记忆
    memory_summary = await scheduler.get_task_memory_summary(result["task_id"])
    print(f"\n任务记忆摘要:\n{memory_summary}")

if __name__ == "__main__":
    # 运行示例
    asyncio.run(example_usage())
    print("\n" + "="*60 + "\n")
    asyncio.run(agent_integration_example())
