#!/usr/bin/env python3
"""
统一的消息管理模块
支持多会话、多agent的消息存储和拼接
"""

import asyncio
import uuid
import logging
import re
import sys
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# 工具函数
def now():
    """获取当前时间戳"""
    return time.strftime('%H:%M:%S:') + str(int(time.time() * 1000) % 10000)

def setup_logging():
    """统一配置日志系统"""
    try:
        from system.config import config
        log_level = getattr(logging, config.system.log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stderr)]
        )
        
        # 设置第三方库日志级别
        for logger_name in ["httpcore.connection", "httpcore.http11", "httpx", "openai._base_client", "asyncio"]:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
    except ImportError:
        # 如果无法导入配置，使用默认设置
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stderr)]
        )

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

        # 会话持久化存储目录
        self.sessions_dir = self.log_dir.parent / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # 启动时从磁盘加载所有会话
        self._load_all_sessions_from_disk()

    def _get_session_file(self, session_id: str) -> Path:
        """获取会话文件路径"""
        return self.sessions_dir / f"{session_id}.json"

    def _save_session_to_disk(self, session_id: str):
        """将单个会话保存到磁盘"""
        session = self.sessions.get(session_id)
        if not session:
            return
        try:
            import json
            data = {
                "session_id": session_id,
                "created_at": session["created_at"],
                "last_activity": session["last_activity"],
                "agent_type": session.get("agent_type", "default"),
                "temporary": session.get("temporary", False),
                "messages": session["messages"],
            }
            self._get_session_file(session_id).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"保存会话到磁盘失败 {session_id}: {e}")

    def _load_all_sessions_from_disk(self):
        """启动时从磁盘加载所有会话"""
        import json
        loaded = 0
        for f in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sid = data.get("session_id") or f.stem
                self.sessions[sid] = {
                    "created_at": data.get("created_at", ""),
                    "last_activity": data.get("last_activity", ""),
                    "agent_type": data.get("agent_type", "default"),
                    "temporary": data.get("temporary", False),
                    "messages": data.get("messages", []),
                }
                loaded += 1
            except Exception as e:
                logger.warning(f"加载会话文件失败 {f.name}: {e}")
        if loaded:
            logger.info(f"从磁盘加载了 {loaded} 个历史会话")

    def _delete_session_file(self, session_id: str):
        """从磁盘删除会话文件"""
        try:
            p = self._get_session_file(session_id)
            if p.exists():
                p.unlink()
        except Exception as e:
            logger.error(f"删除会话文件失败 {session_id}: {e}")
    
    def generate_session_id(self) -> str:
        """生成唯一的会话ID"""
        return str(uuid.uuid4())
    
    def create_session(self, session_id: Optional[str] = None, temporary: bool = False) -> str:
        """获取或创建会话

        Args:
            session_id: 会话ID，为空时自动生成
            temporary: 是否为临时会话（临时会话不持久化到磁盘，重启后消失）
        """
        if not session_id:
            session_id = self.generate_session_id()

        # 检查会话是否已存在（内存中）
        if session_id in self.sessions:
            logger.debug(f"使用现有会话: {session_id}")
            # 更新最后活动时间
            self.sessions[session_id]["last_activity"] = datetime.now().isoformat()
            return session_id

        # 初始化新会话（空消息列表，不注入历史）
        self.sessions[session_id] = {
            "created_at": datetime.now().isoformat(),
            "messages": [],
            "agent_type": "default",
            "last_activity": datetime.now().isoformat(),
            "temporary": temporary,
        }

        logger.info(f"创建{'临时' if temporary else ''}会话: {session_id}")
        return session_id
    
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
        session["last_activity"] = datetime.now().isoformat()

        # 限制消息数量
        if len(session["messages"]) > self.max_messages_per_session:
            session["messages"] = session["messages"][-self.max_messages_per_session:]

        logger.debug(f"会话 {session_id} 添加消息: {role} - {content[:50]}...")

        # 临时会话不持久化到磁盘
        if not session.get("temporary"):
            self._save_session_to_disk(session_id)
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
    
    def _get_previous_session_messages(self, current_session_id: str, max_messages: int = 20) -> List[Dict]:
        """获取上一个会话的最近消息（按最后活动时间排序，排除当前会话）"""
        candidates = [
            (sid, s) for sid, s in self.sessions.items()
            if sid != current_session_id and s.get("messages")
        ]
        if not candidates:
            return []
        # 按最后活动时间倒序，取最近的一个会话
        candidates.sort(key=lambda x: x[1].get("last_activity", ""), reverse=True)
        prev_messages = candidates[0][1]["messages"]
        return prev_messages[-max_messages:]

    def build_conversation_messages(self, session_id: str, system_prompt: str,
                                  current_message: str, include_history: bool = True) -> List[Dict]:
        """构建完整的对话消息列表

        会话自身的消息作为主要上下文；
        若启用 persistent_context 且本会话消息较少，则从上一个会话
        取最近的消息作为背景注入 LLM 上下文（不写入当前会话存储）。
        """
        messages = []

        # 添加系统提示词（时间信息已由 build_system_prompt() 统一注入）
        messages.append({"role": "system", "content": system_prompt})

        # 获取本会话的消息
        session_messages = self.get_recent_messages(session_id) if include_history else []

        # 启用持久化上下文时，从上一个会话取最近消息作为背景注入
        # 如果 system_prompt 中已包含 <compact> 压缩摘要，则跳过原始消息注入（避免重复）
        if self.persistent_context and "<compact>" not in system_prompt:
            prev_messages = self._get_previous_session_messages(session_id)
            if prev_messages:
                messages.extend(prev_messages)
                logger.debug(f"为会话 {session_id} 注入上一会话的 {len(prev_messages)} 条消息到 LLM 上下文")

        # 添加本会话的对话记录
        messages.extend(session_messages)

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

        # 添加系统提示词（时间信息已由 build_system_prompt() 统一注入）
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
            "last_active_at": session["last_activity"],
            "message_count": len(session["messages"]),
            "conversation_rounds": len(session["messages"]) // 2,
            "agent_type": session["agent_type"],
            "max_history_rounds": self.max_history_rounds,
            "temporary": session.get("temporary", False),
            "last_message": session["messages"][-1]["content"][:100] + "..." if session["messages"] else "无对话历史"
        }
    
    def get_all_sessions_info(self) -> List[Dict]:
        """获取所有会话信息（返回列表，按最近活跃时间倒序排列）"""
        sessions_list = []
        for session_id in self.sessions:
            info = self.get_session_info(session_id)
            if info:
                sessions_list.append(info)
        sessions_list.sort(key=lambda s: s.get("last_active_at", ""), reverse=True)
        return sessions_list
    
    def delete_session(self, session_id: str) -> bool:
        """删除指定会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            self._delete_session_file(session_id)
            logger.info(f"删除会话: {session_id}")
            return True
        return False
    
    def clear_all_sessions(self) -> int:
        """清空所有会话"""
        count = len(self.sessions)
        # 删除磁盘文件
        for session_id in list(self.sessions.keys()):
            self._delete_session_file(session_id)
        self.sessions.clear()
        logger.info(f"清空所有会话，共 {count} 个")
        return count
    
    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """清理过期会话"""
        now = datetime.now()
        max_age = timedelta(hours=max_age_hours)
        expired_sessions = []

        for session_id, session in self.sessions.items():
            try:
                last_active = datetime.fromisoformat(session["last_activity"])
                if now - last_active > max_age:
                    expired_sessions.append(session_id)
            except (ValueError, KeyError):
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            del self.sessions[session_id]
            self._delete_session_file(session_id)

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
    
    def save_conversation_log(self, user_message: str, assistant_message: str, dev_mode: bool = False):
        """
        保存对话日志到文件
        
        Args:
            user_message: 用户消息
            assistant_message: 助手回复
            dev_mode: 是否为开发者模式（开发者模式不保存日志）
        """
        if dev_mode:
            return  # 开发者模式不写日志
        
        try:
            from datetime import datetime
            import os
            
            # 获取当前时间
            now = datetime.now()
            date_str = now.strftime('%Y-%m-%d')
            time_str = now.strftime('%H:%M:%S')
            
            # 确保日志目录存在
            log_dir = str(self.log_dir)
            if not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
                logger.info(f"已创建日志目录: {log_dir}")
            
            # 保存对话日志
            log_file = os.path.join(log_dir, f"{date_str}.log")
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{time_str}] 用户: {user_message}\n")
                f.write(f"[{time_str}] {self.ai_name}: {assistant_message}\n")
                f.write("-" * 50 + "\n")
            
            logger.debug(f"已保存对话日志到: {log_file}")
            
        except Exception as e:
            logger.error(f"保存对话日志失败: {e}")
    
    def save_conversation_and_logs(self, session_id: str, user_message: str, assistant_response: str):
        """统一保存对话历史与日志 - 整合重复逻辑"""
        try:
            # 保存对话历史到消息管理器（临时会话的 add_message 内部已跳过磁盘持久化）
            self.add_message(session_id, "user", user_message)
            # 空响应不保存到会话历史，避免 LLM 在后续对话中模仿空回复模式
            if assistant_response and assistant_response.strip():
                self.add_message(session_id, "assistant", assistant_response)
            else:
                logger.warning(f"会话 {session_id}: assistant 响应为空，跳过保存到会话历史")

            # 临时会话不保存日志文件，也不触发记忆提取
            session = self.sessions.get(session_id)
            if session and session.get("temporary"):
                return

            # 保存对话日志到文件
            self.save_conversation_log(
                user_message,
                assistant_response,
                dev_mode=False  # 开发者模式已禁用
            )

            # 触发五元组自动提取（如果记忆系统已启用）
            try:
                # 优先使用远程 NagaMemory 服务
                from summer_memory.memory_client import get_remote_memory_client
                remote = get_remote_memory_client()
                if remote is not None:
                    import asyncio
                    asyncio.create_task(remote.add_memory(user_message, assistant_response))
                    logger.info(f"已提交远程记忆提取任务: {user_message[:50]}...")
                else:
                    # 回退到本地 summer_memory
                    from summer_memory.memory_manager import memory_manager
                    if memory_manager and memory_manager.enabled and memory_manager.auto_extract:
                        import asyncio
                        asyncio.create_task(memory_manager.add_conversation_memory(user_message, assistant_response))
                        logger.info(f"已提交五元组提取任务: {user_message[:50]}...")
            except ImportError as e:
                logger.warning(f"记忆系统未启用或导入失败: {e}")
        except Exception as e:
            logger.error(f"保存对话与日志失败: {e}")
    

    def get_all_sessions_api(self):
        """获取所有会话信息 - API接口"""
        try:
            # 清理过期会话
            self.cleanup_old_sessions()
            
            # 获取所有会话信息
            sessions_info = self.get_all_sessions_info()
            
            return {
                "status": "success",
                "sessions": sessions_info,
                "total_sessions": len(sessions_info)
            }
        except Exception as e:
            logger.error(f"获取会话信息错误: {e}")
            raise Exception(f"获取会话信息失败: {str(e)}")
    
    def get_session_detail_api(self, session_id: str):
        """获取指定会话的详细信息 - API接口"""
        try:
            session_info = self.get_session_info(session_id)
            if not session_info:
                raise Exception("会话不存在")
            
            return {
                "status": "success",
                "session_id": session_id,
                "session_info": session_info,
                "messages": self.get_messages(session_id),
                "conversation_rounds": session_info["conversation_rounds"]
            }
        except Exception as e:
            logger.error(f"获取会话详情错误: {e}")
            raise Exception(f"获取会话详情失败: {str(e)}")
    
    def delete_session_api(self, session_id: str):
        """删除指定会话 - API接口"""
        try:
            success = self.delete_session(session_id)
            if success:
                return {
                    "status": "success",
                    "message": f"会话 {session_id} 已删除"
                }
            else:
                raise Exception("会话不存在")
        except Exception as e:
            logger.error(f"删除会话错误: {e}")
            raise Exception(f"删除会话失败: {str(e)}")
    
    def clear_all_sessions_api(self):
        """清空所有会话 - API接口"""
        try:
            count = self.clear_all_sessions()
            return {
                "status": "success",
                "message": f"已清空 {count} 个会话"
            }
        except Exception as e:
            logger.error(f"清空会话错误: {e}")
            raise Exception(f"清空会话失败: {str(e)}")

# 全局消息管理器实例
message_manager = MessageManager() 