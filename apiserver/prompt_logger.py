"""
Prompt保存工具类
用于保存发送给LLM的完整prompt消息
"""

import json
import os
import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class PromptLogger:
    """Prompt日志记录器"""
    
    def __init__(self):
        self.logs_dir = "logs/prompts"
        self._ensure_directory()
    
    def _ensure_directory(self):
        """确保日志目录存在"""
        os.makedirs(self.logs_dir, exist_ok=True)
    
    def _get_today_file(self) -> str:
        """获取今天的日志文件路径"""
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.logs_dir, f"prompts_{today}.json")
    
    def _load_existing_logs(self, file_path: str) -> List[Dict]:
        """加载现有的日志文件"""
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"加载prompt日志文件失败: {e}")
        return []
    
    def _save_logs(self, file_path: str, logs: List[Dict]):
        """保存日志到文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存prompt日志文件失败: {e}")
    
    def log_prompt(self, 
                   session_id: str, 
                   messages: List[Dict], 
                   api_response: Optional[Dict] = None,
                   api_status: str = "unknown") -> None:
        """
        记录prompt日志
        
        Args:
            session_id: 会话ID
            messages: 发送给LLM的完整消息列表
            api_response: API响应内容（可选）
            api_status: API响应状态
        """
        try:
            # 检查是否启用prompt保存
            from system.config import config, AI_NAME
            if not getattr(config.system, 'save_prompts', False):
                return
            
            # 创建日志条目
            log_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "session_id": session_id,
                "messages": messages,
                "api_status": api_status,
                "api_response": api_response
            }
            
            # 获取今天的日志文件
            file_path = self._get_today_file()
            
            # 加载现有日志
            existing_logs = self._load_existing_logs(file_path)
            
            # 添加新日志条目
            existing_logs.append(log_entry)
            
            # 保存到文件
            self._save_logs(file_path, existing_logs)
            
            logger.info(f"已保存prompt日志，会话ID: {session_id}")
            
        except Exception as e:
            logger.error(f"保存prompt日志失败: {e}")
    
    def get_today_logs(self) -> List[Dict]:
        """获取今天的prompt日志"""
        file_path = self._get_today_file()
        return self._load_existing_logs(file_path)
    
    def get_logs_by_date(self, date_str: str) -> List[Dict]:
        """根据日期获取prompt日志"""
        file_path = os.path.join(self.logs_dir, f"prompts_{date_str}.json")
        return self._load_existing_logs(file_path)
    
    def get_logs_by_session(self, session_id: str) -> List[Dict]:
        """根据会话ID获取prompt日志"""
        all_logs = []
        for filename in os.listdir(self.logs_dir):
            if filename.startswith("prompts_") and filename.endswith(".json"):
                file_path = os.path.join(self.logs_dir, filename)
                logs = self._load_existing_logs(file_path)
                session_logs = [log for log in logs if log.get("session_id") == session_id]
                all_logs.extend(session_logs)
        return all_logs


# 全局prompt日志记录器实例
prompt_logger = PromptLogger() 