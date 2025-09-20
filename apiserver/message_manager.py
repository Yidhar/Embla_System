#!/usr/bin/env python3
"""
统一的消息管理模块
支持多会话、多agent的消息存储和拼接
"""

import asyncio
import uuid
import logging
import re
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

class MessageManager:
    """统一的消息管理器"""
    
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        # 从配置文件读取最大历史轮数，默认为10轮
        try:
            from system.config import config
            self.max_history_rounds = config.api.max_history_rounds
            self.max_messages_per_session = self.max_history_rounds * 2  # 每轮对话包含用户和助手各一条消息
            self.persistent_context = config.api.persistent_context
            self.context_load_days = config.api.context_load_days
            self.log_dir = config.system.log_dir
            self.ai_name = config.system.ai_name
        except ImportError:
            self.max_history_rounds = 10
            self.max_messages_per_session = 20  # 默认20条消息
            self.persistent_context = True
            self.context_load_days = 3
            self.log_dir = Path("logs")
            self.ai_name = "娜迦"
            logger.warning("无法导入配置，使用默认历史轮数设置")
    
    def generate_session_id(self) -> str:
        """生成唯一的会话ID"""
        return str(uuid.uuid4())
    
    def create_session(self, session_id: Optional[str] = None) -> str:
        """创建新会话"""
        if not session_id:
            session_id = self.generate_session_id()
        
        # 初始化会话
        self.sessions[session_id] = {
            "created_at": asyncio.get_event_loop().time(),
            "messages": [],
            "agent_type": "default",  # 可以扩展支持不同agent类型
            "last_activity": asyncio.get_event_loop().time()
        }
        
        # 如果启用持久化上下文，尝试加载历史对话
        if self.persistent_context:
            self._load_persistent_context_for_session(session_id)
        
        logger.info(f"创建新会话: {session_id}")
        return session_id
    
    def _load_persistent_context_for_session(self, session_id: str):
        """为指定会话加载持久化上下文"""
        try:
            # 加载历史对话
            recent_messages = self.load_recent_context(
                days=self.context_load_days,
                max_messages=self.max_messages_per_session
            )
            
            if recent_messages:
                self.sessions[session_id]["messages"] = recent_messages
                logger.info(f"会话 {session_id} 加载了 {len(recent_messages)} 条历史对话")
            else:
                logger.debug(f"会话 {session_id} 未找到历史对话记录")
                
        except Exception as e:
            logger.warning(f"为会话 {session_id} 加载持久化上下文失败: {e}")
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话信息"""
        return self.sessions.get(session_id)
    
    def add_message(self, session_id: str, role: str, content: str) -> bool:
        """向会话添加消息"""
        if session_id not in self.sessions:
            logger.warning(f"会话不存在: {session_id}")
            return False
        
        session = self.sessions[session_id]
        session["messages"].append({"role": role, "content": content})
        session["last_activity"] = asyncio.get_event_loop().time()
        
        # 限制消息数量
        if len(session["messages"]) > self.max_messages_per_session:
            session["messages"] = session["messages"][-self.max_messages_per_session:]
        
        logger.debug(f"会话 {session_id} 添加消息: {role} - {content[:50]}...")
        return True
    
    def get_messages(self, session_id: str) -> List[Dict]:
        """获取会话的所有消息"""
        session = self.sessions.get(session_id)
        return session["messages"] if session else []
    
    def get_recent_messages(self, session_id: str, count: Optional[int] = None) -> List[Dict]:
        """获取会话的最近消息"""
        if count is None:
            count = self.max_messages_per_session
        messages = self.get_messages(session_id)
        return messages[-count:] if messages else []
    
    def build_conversation_messages(self, session_id: str, system_prompt: str, 
                                  current_message: str, include_history: bool = True) -> List[Dict]:
        """构建完整的对话消息列表"""
        messages = []
        
        # 添加系统提示词
        messages.append({"role": "system", "content": system_prompt})
        
        # 添加历史对话
        if include_history:
            recent_messages = self.get_recent_messages(session_id)
            messages.extend(recent_messages)
        
        # 添加当前用户消息
        messages.append({"role": "user", "content": current_message})
        
        return messages
    
    def build_conversation_messages_from_memory(self, memory_messages: List[Dict], system_prompt: str, 
                                              current_message: str, max_history_rounds: int = None) -> List[Dict]:
        """
        从内存消息列表构建对话消息（用于UI界面）
        
        Args:
            memory_messages: 内存中的消息列表
            system_prompt: 系统提示词
            current_message: 当前用户消息
            max_history_rounds: 最大历史轮数，默认使用配置值
            
        Returns:
            List[Dict]: 完整的对话消息列表
        """
        messages = []
        
        # 添加系统提示词
        messages.append({"role": "system", "content": system_prompt})
        
        # 计算最大消息数量
        if max_history_rounds is None:
            max_history_rounds = self.max_history_rounds
        
        max_messages = max_history_rounds * 2  # 每轮对话包含用户和助手各一条消息
        
        # 添加历史对话（限制数量）
        if memory_messages:
            recent_messages = memory_messages[-max_messages:]
            messages.extend(recent_messages)
        
        # 添加当前用户消息
        messages.append({"role": "user", "content": current_message})
        
        return messages
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """获取会话详细信息"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        return {
            "session_id": session_id,
            "created_at": session["created_at"],
            "last_activity": session["last_activity"],
            "message_count": len(session["messages"]),
            "conversation_rounds": len(session["messages"]) // 2,
            "agent_type": session["agent_type"],
            "max_history_rounds": self.max_history_rounds,  # 添加最大历史轮数信息
            "last_message": session["messages"][-1]["content"][:100] + "..." if session["messages"] else "无对话历史"
        }
    
    def get_all_sessions_info(self) -> Dict[str, Dict]:
        """获取所有会话信息"""
        sessions_info = {}
        for session_id, session in self.sessions.items():
            sessions_info[session_id] = self.get_session_info(session_id)
        return sessions_info
    
    def delete_session(self, session_id: str) -> bool:
        """删除指定会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"删除会话: {session_id}")
            return True
        return False
    
    def clear_all_sessions(self) -> int:
        """清空所有会话"""
        count = len(self.sessions)
        self.sessions.clear()
        logger.info(f"清空所有会话，共 {count} 个")
        return count
    
    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """清理过期会话"""
        current_time = asyncio.get_event_loop().time()
        expired_sessions = []
        
        for session_id, session in self.sessions.items():
            if current_time - session["last_activity"] > max_age_hours * 3600:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self.sessions[session_id]
        
        if expired_sessions:
            logger.info(f"清理了 {len(expired_sessions)} 个过期会话")
        
        return len(expired_sessions)
    
    def set_agent_type(self, session_id: str, agent_type: str) -> bool:
        """设置会话的agent类型"""
        if session_id in self.sessions:
            self.sessions[session_id]["agent_type"] = agent_type
            return True
        return False
    
    def get_agent_type(self, session_id: str) -> Optional[str]:
        """获取会话的agent类型"""
        session = self.sessions.get(session_id)
        return session["agent_type"] if session else None
    
    # ========== 日志解析功能 ==========
    
    def _parse_log_line(self, line: str) -> Optional[tuple]:
        """
        解析单行日志内容
        
        Args:
            line: 日志行内容
            
        Returns:
            tuple: (role, content) 或 None
        """
        line = line.strip()
        if not line:
            return None
        
        # 匹配格式：[时间] 用户: 内容 或 [时间] AI名称: 内容
        pattern = r'^\[(\d{2}:\d{2}:\d{2})\] (用户|' + re.escape(self.ai_name) + r'): (.+)$'
        match = re.match(pattern, line)
        
        if match:
            time_str, speaker, content = match.groups()
            if speaker == "用户":
                role = "user"
            else:
                role = "assistant"
            return (role, content.strip())
        
        return None
    
    def _is_message_start_line(self, line: str) -> bool:
        """
        判断是否为消息开始行
        
        Args:
            line: 日志行内容
            
        Returns:
            bool: 是否为消息开始行
        """
        line = line.strip()
        if not line:
            return False
        
        # 匹配格式：[时间] 用户: 或 [时间] AI名称:
        pattern = r'^\[(\d{2}:\d{2}:\d{2})\] (用户|' + re.escape(self.ai_name) + r'):'
        return bool(re.match(pattern, line))
    
    def parse_log_file(self, log_file_path: str) -> List[Dict]:
        """
        解析单个日志文件，提取对话内容
        按照日志记录代码的格式：每轮对话包含用户消息和AI回复，用50个-分隔
        
        Args:
            log_file_path: 日志文件路径
            
        Returns:
            List[Dict]: 对话消息列表，格式为[{"role": "user/assistant", "content": "内容"}]
        """
        messages = []
        
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 以50个-分割对话轮次（按照日志记录代码的格式）
            conversation_blocks = content.split('-' * 50)
            
            for block in conversation_blocks:
                block = block.strip()
                if not block:
                    continue
                
                # 解析每个对话块中的消息
                block_messages = self._parse_conversation_block(block)
                messages.extend(block_messages)
                        
        except FileNotFoundError:
            logger.debug(f"日志文件不存在: {log_file_path}")
        except Exception as e:
            logger.error(f"解析日志文件失败 {log_file_path}: {e}")
        
        return messages
    
    def _parse_conversation_block(self, block: str) -> List[Dict]:
        """
        解析单个对话块，提取其中的所有消息
        每块包含用户消息和AI回复，支持多行内容
        
        Args:
            block: 对话块内容
            
        Returns:
            List[Dict]: 消息列表
        """
        messages = []
        lines = block.split('\n')
        current_message = None
        current_content_lines = []
        
        for line in lines:
            line = line.rstrip('\n\r')  # 移除行尾换行符，但保留内容中的换行
            
            # 检查是否为消息开始行
            if self._is_message_start_line(line):
                # 保存前一个消息
                if current_message is not None and current_content_lines:
                    content = '\n'.join(current_content_lines)
                    messages.append({
                        "role": current_message["role"], 
                        "content": content
                    })
                
                # 开始新消息
                result = self._parse_log_line(line)
                if result:
                    role, content = result
                    current_message = {"role": role}
                    current_content_lines = [content] if content else []
                else:
                    current_message = None
                    current_content_lines = []
            
            # 如果当前有活跃消息，且不是消息开始行，则作为内容行处理
            elif current_message is not None:
                # 跳过分隔线和空行
                if line.strip() and not line.strip().startswith('---') and not line.strip().startswith('--'):
                    current_content_lines.append(line)
        
        # 保存最后一个消息
        if current_message is not None and current_content_lines:
            content = '\n'.join(current_content_lines)
            messages.append({
                "role": current_message["role"], 
                "content": content
            })
        
        return messages
    
    def get_log_files_by_date(self, days: int = 3) -> List[str]:
        """
        获取最近几天的日志文件路径
        
        Args:
            days: 要获取的天数
            
        Returns:
            List[str]: 日志文件路径列表，按日期倒序排列
        """
        log_files = []
        today = datetime.now()
        
        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            log_file = self.log_dir / f"{date_str}.log"
            
            if log_file.exists():
                log_files.append(str(log_file))
        
        # 按日期倒序排列（最新的在前）
        log_files.reverse()
        return log_files
    
    def load_recent_context(self, days: int = 3, max_messages: int = None) -> List[Dict]:
        """
        加载最近几天的对话上下文
        
        Args:
            days: 要加载的天数
            max_messages: 最大消息数量限制
            
        Returns:
            List[Dict]: 对话消息列表
        """
        all_messages = []
        log_files = self.get_log_files_by_date(days)
        
        logger.info(f"开始加载最近 {days} 天的日志文件: {log_files}")
        
        for log_file in log_files:
            messages = self.parse_log_file(log_file)
            all_messages.extend(messages)
            logger.debug(f"从 {log_file} 加载了 {len(messages)} 条消息")
        
        # 限制消息数量
        if max_messages and len(all_messages) > max_messages:
            all_messages = all_messages[-max_messages:]
            logger.info(f"限制消息数量为 {max_messages} 条")
        
        logger.info(f"总共加载了 {len(all_messages)} 条历史对话")
        return all_messages
    
    def get_context_statistics(self, days: int = 7) -> Dict:
        """
        获取上下文统计信息
        
        Args:
            days: 统计天数
            
        Returns:
            Dict: 统计信息
        """
        log_files = self.get_log_files_by_date(days)
        total_messages = 0
        user_messages = 0
        assistant_messages = 0
        
        for log_file in log_files:
            messages = self.parse_log_file(log_file)
            total_messages += len(messages)
            
            for msg in messages:
                if msg["role"] == "user":
                    user_messages += 1
                else:
                    assistant_messages += 1
        
        return {
            "total_files": len(log_files),
            "total_messages": total_messages,
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "days_covered": days
        }

# 全局消息管理器实例
message_manager = MessageManager() 