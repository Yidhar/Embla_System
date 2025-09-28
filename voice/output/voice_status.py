#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音服务状态检查模块
"""
import sys
import os
import asyncio
from nagaagent_core.core import aiohttp
import socket
import time
from typing import Dict, Any, Optional

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from system.config import config

class VoiceServiceStatus:
    """语音服务状态检查器"""
    
    def __init__(self):
        self.base_url = f"http://127.0.0.1:{config.tts.port}"
        self.timeout = 5  # 5秒超时
    
    def check_port_available(self) -> bool:
        """检查端口是否可用"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                result = s.connect_ex(('127.0.0.1', config.tts.port))
                return result == 0
        except Exception:
            return False
    
    async def check_http_health(self) -> Dict[str, Any]:
        """检查HTTP服务健康状态"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                # 检查根路径
                async with session.get(f"{self.base_url}/") as response:
                    if response.status == 200:
                        return {
                            "status": "healthy",
                            "message": "HTTP服务正常运行",
                            "response_time": response.headers.get("X-Response-Time", "unknown")
                        }
                    else:
                        return {
                            "status": "unhealthy",
                            "message": f"HTTP服务响应异常: {response.status}",
                            "response_time": "unknown"
                        }
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "message": "HTTP服务响应超时",
                "response_time": "timeout"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"HTTP服务检查失败: {str(e)}",
                "response_time": "error"
            }
    
    async def test_tts_functionality(self) -> Dict[str, Any]:
        """测试TTS功能"""
        try:
            test_text = "测试语音合成功能"
            headers = {"Authorization": f"Bearer {config.tts.api_key}"} if config.tts.require_api_key else {}
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(
                    f"{self.base_url}/v1/audio/speech",
                    json={
                        "input": test_text,
                        "voice": config.tts.default_voice,
                        "response_format": config.tts.default_format,
                        "speed": config.tts.default_speed
                    },
                    headers=headers
                ) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        return {
                            "status": "success",
                            "message": "TTS功能正常",
                            "audio_size": len(audio_data),
                            "test_text": test_text
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "status": "error",
                            "message": f"TTS功能测试失败: {response.status} - {error_text}",
                            "audio_size": 0,
                            "test_text": test_text
                        }
        except Exception as e:
            return {
                "status": "error",
                "message": f"TTS功能测试异常: {str(e)}",
                "audio_size": 0,
                "test_text": test_text
            }
    
    async def get_full_status(self) -> Dict[str, Any]:
        """获取完整服务状态"""
        port_status = self.check_port_available()
        http_status = await self.check_http_health()
        
        status_info = {
            "port_available": port_status,
            "http_health": http_status,
            "config": {
                "port": config.tts.port,
                "default_voice": config.tts.default_voice,
                "default_format": config.tts.default_format,
                "default_speed": config.tts.default_speed,
                "require_api_key": config.tts.require_api_key
            },
            "timestamp": time.time()
        }
        
        # 如果HTTP服务正常，测试TTS功能
        if port_status and http_status["status"] == "healthy":
            tts_status = await self.test_tts_functionality()
            status_info["tts_functionality"] = tts_status
        
        return status_info
    
    def print_status(self, status: Dict[str, Any]):
        """打印状态信息"""
        print("=" * 50)
        print("🎤 语音服务状态检查")
        print("=" * 50)
        
        # 端口状态
        port_status = "✅ 可用" if status["port_available"] else "❌ 不可用"
        print(f"端口 {config.tts.port}: {port_status}")
        
        # HTTP健康状态
        http_status = status["http_health"]
        status_icon = "✅" if http_status["status"] == "healthy" else "❌"
        print(f"HTTP服务: {status_icon} {http_status['message']}")
        
        # TTS功能状态
        if "tts_functionality" in status:
            tts_status = status["tts_functionality"]
            status_icon = "✅" if tts_status["status"] == "success" else "❌"
            print(f"TTS功能: {status_icon} {tts_status['message']}")
            if tts_status["status"] == "success":
                print(f"   测试音频大小: {tts_status['audio_size']} bytes")
        
        # 配置信息
        print("\n📋 配置信息:")
        config_info = status["config"]
        print(f"   默认语音: {config_info['default_voice']}")
        print(f"   默认格式: {config_info['default_format']}")
        print(f"   默认语速: {config_info['default_speed']}")
        print(f"   需要API密钥: {config_info['require_api_key']}")
        
        print("=" * 50)

async def main():
    """主函数"""
    status_checker = VoiceServiceStatus()
    status = await status_checker.get_full_status()
    status_checker.print_status(status)
    
    # 返回状态码
    if status["port_available"] and status["http_health"]["status"] == "healthy":
        return 0
    else:
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 