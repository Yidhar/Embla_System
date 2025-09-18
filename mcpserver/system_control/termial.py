import subprocess
import os
import json
from typing import Dict, Any, Optional

class TerminalExecutor:
    """终端执行器类"""
    
    def __init__(self):
        self.default_timeout = 30  # 默认超时时间
    
    def execute_command(self, command: str, cwd: Optional[str] = None, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        执行系统指令
        
        Args:
            command: 要执行的指令
            cwd: 工作目录，默认为当前目录
            timeout: 超时时间，默认30秒
            
        Returns:
            包含执行结果的字典
        """
        if timeout is None:
            timeout = self.default_timeout
            
        if cwd is None:
            cwd = "."
            
        try:
            # 执行指令
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "status": "success",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command,
                "cwd": cwd
            }
            
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "message": f"指令执行超时 ({timeout}秒)",
                "command": command,
                "cwd": cwd
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"指令执行失败: {str(e)}",
                "command": command,
                "cwd": cwd
            }
    
    def execute_with_confirmation(self, command: str, cwd: Optional[str] = None, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        执行需要确认的指令（如关机、重启等）
        
        Args:
            command: 要执行的指令
            cwd: 工作目录
            timeout: 超时时间
            
        Returns:
            包含执行结果的字典
        """
        # 这里可以添加确认逻辑
        # 目前直接执行
        return self.execute_command(command, cwd, timeout)

# 全局实例
terminal_executor = TerminalExecutor()

def execute_system_command(command: str, cwd: Optional[str] = None, timeout: Optional[int] = None) -> str:
    """
    执行系统指令的便捷函数
    
    Args:
        command: 要执行的指令
        cwd: 工作目录
        timeout: 超时时间
        
    Returns:
        JSON格式的执行结果
    """
    result = terminal_executor.execute_command(command, cwd, timeout)
    return json.dumps(result, ensure_ascii=False)
