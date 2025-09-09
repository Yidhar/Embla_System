from fastapi import FastAPI, UploadFile, File, WebSocket  # Web框架 #
from fastapi.responses import JSONResponse  # 响应 #
import base64  # b64 #
from typing import Optional  # 类型 #
import sounddevice as sd  # 音频设备 #

from system.config import config  # 配置 #
from .schemas import TranscriptionResult  # 数据模型 #
from .asr_client import transcribe_wav_bytes  # 转写 #
from .vad_worker import VADWorker  # 采集线程 #
from .ws_server import websocket_endpoint  # WebSocket端点 #


app = FastAPI(title="NagaAgent ASR Service")  # 应用 #

worker: Optional[VADWorker] = None  # 全局工作器 #


@app.get("/health")
def health():
    return {"status": "ok"}  # 健康检查 #


@app.get("/devices")
def list_devices():
    """列出可用音频设备 # 一行说明 #"""
    try:
        devices = sd.query_devices()  # 查询设备 #
        input_devices = []  # 输入设备 #
        
        for i, device in enumerate(devices):
            if device['max_inputs'] > 0:  # 有输入能力 #
                input_devices.append({
                    "index": i,
                    "name": device['name'],
                    "channels": device['max_inputs'],
                    "sample_rate": device['default_samplerate']
                })
        
        return {
            "input_devices": input_devices,
            "default_input": sd.default.device[0] if sd.default.device else None
        }
    except Exception as e:
        return {"error": f"获取设备列表失败: {str(e)}"}  # 错误处理 #


@app.post("/v1/audio/transcriptions", response_model=TranscriptionResult)
async def transcriptions(file: UploadFile = File(...)):
    data = await file.read()  # 读取文件 #
    text = transcribe_wav_bytes(data)  # 转写 #
    return TranscriptionResult(text=text or "")  # 返回 #


@app.post("/v1/audio/transcriptions_b64", response_model=TranscriptionResult)
async def transcriptions_b64(payload: dict):
    audio64 = payload.get("audio", "")  # 读取base64 #
    data = base64.b64decode(audio64.encode("utf-8")) if audio64 else b""  # 解码 #
    text = transcribe_wav_bytes(data)  # 转写 #
    return TranscriptionResult(text=text or "")  # 返回 #


@app.post("/control/listen/start")
def listen_start():
    global worker  # 全局 #
    if worker and worker.is_alive():
        return {"status": "already_running"}  # 已运行 #

    def on_utt(wav_bytes: bytes, latency: float):
        transcribe_wav_bytes(wav_bytes)  # 识别 #
        # 可扩展：回调/WS广播 #

    worker = VADWorker(on_utt)  # 创建 #
    worker.start()  # 启动 #
    return {"status": "started"}  # 返回 #


@app.post("/control/listen/stop")
def listen_stop():
    global worker  # 全局 #
    if worker and worker.is_alive():
        worker.stop()  # 停止 #
        return {"status": "stopping"}  # 返回 #
    return {"status": "not_running"}  # 未运行 #


@app.websocket("/v1/audio/asr_ws")
async def websocket_endpoint_route(websocket: WebSocket):
    """WebSocket 实时 VAD + ASR 端点 # 一行说明 #"""
    await websocket_endpoint(websocket)


