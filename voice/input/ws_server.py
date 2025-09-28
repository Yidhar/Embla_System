import asyncio  # 异步 #
import json  # JSON #
import base64  # base64 #
from typing import List  # 类型 #
import nagaagent_core.vendors.numpy as np  # 数值 #
from nagaagent_core.api import WebSocket, WebSocketDisconnect  # WebSocket #
from io import BytesIO  # 内存流 #
import soundfile as sf  # 音频 #

from system.config import config  # 配置 #
from .asr_client import transcribe_wav_bytes  # 转写 #
from .vad_utils import VADIterator  # VAD工具 #


class WebSocketManager:
    """WebSocket 连接管理器 # 一行说明 #"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []  # 活跃连接 #
        self.vad_iterator = VADIterator(speech_pad_ms=300)  # VAD迭代器 #
        self.current_speech = []  # 当前语音片段 #
        self.current_speech_tmp = []  # 临时缓存 #
        self.status = False  # 说话状态 #

    async def connect(self, websocket: WebSocket):
        await websocket.accept()  # 接受连接 #
        self.active_connections.append(websocket)  # 添加到列表 #

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)  # 移除连接 #

    async def broadcast(self, message: str):
        """广播消息给所有连接 # 一行说明 #"""
        for connection in self.active_connections:
            try:
                await connection.send_text(message)  # 发送消息 #
            except Exception:
                # 连接异常，移除 #
                self.active_connections.remove(connection)

    async def handle_websocket(self, websocket: WebSocket):
        """处理 WebSocket 连接 # 一行说明 #"""
        await self.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()  # 接收消息 #
                data = json.loads(data)  # 解析JSON #
                
                if data["type"] == "asr":  # ASR类型 #
                    await self._process_asr_data(websocket, data["data"])  # 处理 #
                elif data["type"] == "ping":  # 心跳 #
                    await websocket.send_text(json.dumps({"type": "pong"}))  # 响应 #
                    
        except WebSocketDisconnect:
            self.disconnect(websocket)  # 断开连接 #
        except Exception as e:
            print(f"WebSocket 处理异常: {e}")  # 异常处理 #
            self.disconnect(websocket)

    async def _process_asr_data(self, websocket: WebSocket, audio_data: str):
        """处理 ASR 音频数据 # 一行说明 #"""
        try:
            # 解码音频 #
            audio_bytes = base64.urlsafe_b64decode(audio_data.encode("utf-8"))
            samples = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # 累积音频块 #
            self.current_speech_tmp.append(samples)
            if len(self.current_speech_tmp) < 4:  # 等待足够数据 #
                return
            
            # 重采样到 16kHz #
            resampled = np.concatenate(self.current_speech_tmp.copy())
            resampled = (resampled / 32768.0).astype(np.float32)
            self.current_speech_tmp = []

            # VAD 处理 #
            for speech_dict, speech_samples in self.vad_iterator(resampled):
                if "start" in speech_dict:  # 开始说话 #
                    self.current_speech = []
                    self.status = True
                    await websocket.send_text(json.dumps({"type": "vad_start"}))  # 通知 #
                    
                if self.status:  # 说话中 #
                    self.current_speech.append(speech_samples)
                    
                is_last = "end" in speech_dict
                if is_last:  # 结束说话 #
                    self.status = False
                    if len(self.current_speech) > 0:
                        # 拼接完整语音 #
                        combined = np.concatenate(self.current_speech)
                        
                        # 转换为 WAV #
                        audio_bytes = self._to_wav_bytes(combined, 16000)
                        
                        # 调用 ASR #
                        text = transcribe_wav_bytes(audio_bytes)
                        if text:
                            # 发送识别结果 #
                            result = {
                                "type": "transcription",
                                "text": text,
                                "status": "final"
                            }
                            await websocket.send_text(json.dumps(result))
                            
                            # 广播给其他连接 #
                            await self.broadcast(json.dumps({
                                "type": "transcription_broadcast",
                                "text": text
                            }))
                        
                        self.current_speech = []  # 清空缓存 #
                        
        except Exception as e:
            print(f"ASR 处理异常: {e}")  # 异常处理 #
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"ASR 处理失败: {str(e)}"
            }))

    @staticmethod
    def _to_wav_bytes(samples: np.ndarray, sr: int) -> bytes:
        """转换音频为 WAV bytes # 一行说明 #"""
        buf = BytesIO()  # 缓冲 #
        sf.write(buf, samples, sr, format='WAV')  # 写WAV #
        return buf.getvalue()  # 返回字节 #


# 全局管理器 #
ws_manager = WebSocketManager()


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点 # 一行说明 #"""
    await ws_manager.handle_websocket(websocket)
