import asyncio  # 异步 #
import json  # JSON #
import base64  # base64 #
from typing import AsyncGenerator, Optional  # 类型 #
import aiohttp  # HTTP客户端 #

from system.config import config  # 配置 #
from .asr_client import transcribe_wav_bytes  # 转写 #
from .vad_worker import VADWorker  # 采集线程 #


class VoiceInputIntegration:
    """语音输入集成接口，与对话核心集成 # 一行说明 #"""
    
    def __init__(self):
        self.vad_worker: Optional[VADWorker] = None  # VAD工作器 #
        self.is_listening = False  # 监听状态 #
        self._audio_queue = asyncio.Queue()  # 音频队列 #
        self._stop_event = asyncio.Event()  # 停止事件 #

    async def stt_stream(self) -> AsyncGenerator[str, None]:
        """语音转文本流式接口，供对话核心调用 # 一行说明 #"""
        if not self.is_listening:
            await self._start_listening()  # 启动监听 #
        
        try:
            while not self._stop_event.is_set():
                try:
                    # 等待音频数据 #
                    wav_bytes, latency = await asyncio.wait_for(
                        self._audio_queue.get(), 
                        timeout=1.0  # 1秒超时 #
                    )
                    
                    # 调用 ASR #
                    text = transcribe_wav_bytes(wav_bytes)
                    if text and text.strip():
                        yield text.strip()  # 返回识别文本 #
                        
                except asyncio.TimeoutError:
                    continue  # 超时继续循环 #
                except Exception as e:
                    print(f"语音识别异常: {e}")  # 异常处理 #
                    continue
                    
        finally:
            await self._stop_listening()  # 停止监听 #

    async def _start_listening(self):
        """启动语音监听 # 一行说明 #"""
        if self.is_listening:
            return  # 已启动 #
        
        def on_utterance(wav_bytes: bytes, latency: float):
            """音频片段回调 # 一行说明 #"""
            if not self._stop_event.is_set():
                # 异步添加到队列 #
                asyncio.create_task(self._audio_queue.put((wav_bytes, latency)))
        
        try:
            self.vad_worker = VADWorker(on_utterance)  # 创建工作器 #
            self.vad_worker.start()  # 启动 #
            self.is_listening = True  # 设置状态 #
            print("🎤 语音监听已启动")  # 提示 #
        except Exception as e:
            print(f"❌ 启动语音监听失败: {e}")  # 错误提示 #

    async def _stop_listening(self):
        """停止语音监听 # 一行说明 #"""
        if not self.is_listening:
            return  # 未启动 #
        
        self._stop_event.set()  # 设置停止标志 #
        
        if self.vad_worker and self.vad_worker.is_alive():
            self.vad_worker.stop()  # 停止工作器 #
            self.vad_worker.join(timeout=2)  # 等待停止 #
        
        self.is_listening = False  # 重置状态 #
        print("🔇 语音监听已停止")  # 提示 #

    async def start_listening(self):
        """手动启动监听 # 一行说明 #"""
        await self._start_listening()

    async def stop_listening(self):
        """手动停止监听 # 一行说明 #"""
        await self._stop_listening()

    def is_active(self) -> bool:
        """检查是否正在监听 # 一行说明 #"""
        return self.is_listening and self.vad_worker and self.vad_worker.is_alive()

    async def transcribe_file(self, file_path: str) -> Optional[str]:
        """转写音频文件 # 一行说明 #"""
        try:
            with open(file_path, 'rb') as f:
                audio_data = f.read()  # 读取文件 #
            return transcribe_wav_bytes(audio_data)  # 转写 #
        except Exception as e:
            print(f"文件转写失败: {e}")  # 错误提示 #
            return None

    async def transcribe_base64(self, audio_base64: str) -> Optional[str]:
        """转写 Base64 音频 # 一行说明 #"""
        try:
            audio_data = base64.b64decode(audio_base64.encode("utf-8"))  # 解码 #
            return transcribe_wav_bytes(audio_data)  # 转写 #
        except Exception as e:
            print(f"Base64转写失败: {e}")  # 错误提示 #
            return None


# 全局实例 #
_voice_integration: Optional[VoiceInputIntegration] = None


def get_voice_integration() -> VoiceInputIntegration:
    """获取语音输入集成实例 # 一行说明 #"""
    global _voice_integration
    if _voice_integration is None:
        _voice_integration = VoiceInputIntegration()  # 创建实例 #
    return _voice_integration


async def start_voice_listening():
    """启动语音监听 # 一行说明 #"""
    integration = get_voice_integration()
    await integration.start_listening()


async def stop_voice_listening():
    """停止语音监听 # 一行说明 #"""
    integration = get_voice_integration()
    await integration.stop_listening()


def is_voice_active() -> bool:
    """检查语音是否激活 # 一行说明 #"""
    integration = get_voice_integration()
    return integration.is_active()
