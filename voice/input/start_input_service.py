#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语音输入服务启动脚本 # 一行说明 #"""
import argparse  # 参数 #
from system.config import config  # 配置 #


def check_dependencies() -> bool:
    missing = []  # 缺失列表 #
    try:
        import sounddevice  # noqa: F401 #
    except Exception:
        missing.append("sounddevice")  # 记录 #
    try:
        import soundfile  # noqa: F401 #
    except Exception:
        missing.append("soundfile")  # 记录 #
    try:
        import onnxruntime  # noqa: F401 #
    except Exception:
        missing.append("onnxruntime")  # 记录 #
    try:
        import fastapi  # noqa: F401 #
    except Exception:
        missing.append("fastapi")  # 记录 #
    try:
        import uvicorn  # noqa: F401 #
    except Exception:
        missing.append("uvicorn")  # 记录 #
    try:
        import nagaagent_core.vendors.numpy as numpy  # noqa: F401 #
    except Exception:
        missing.append("numpy")  # 记录 #
    try:
        import nagaagent_core.vendors.scipy as scipy  # noqa: F401 #
    except Exception:
        missing.append("scipy")  # 记录 #
    try:
        from nagaagent_core.vendors.httpx import Client as _HttpxClient  # 占位以检查可用性 #
        import nagaagent_core.vendors.httpx as httpx
    except Exception:
        httpx = None
    
    if missing:
        print("❌ 语音输入服务缺少依赖: " + ", ".join(missing))  # 打印 #
        print("请执行: pip install -r voice/input/requirements.txt")  # 提示 #
        print("注意：语音输入服务需要onnxruntime库支持VAD功能")  # 说明 #
        return False  # 返回 #
    return True  # 通过 #


def main():
    parser = argparse.ArgumentParser(description="语音输入服务启动器")  # 参数解析 #
    parser.add_argument("--port", type=int, help="自定义端口")  # 端口 #
    parser.add_argument("--check-deps", action="store_true", help="检查依赖")  # 检查 #
    parser.add_argument("--mode", choices=["http", "websocket", "both"], default="both", help="服务模式")  # 模式 #
    args = parser.parse_args()  # 解析 #

    if args.check_deps:
        if check_dependencies():
            print("✅ 所有依赖已安装")  # 成功 #
        else:
            print("❌ 依赖检查失败")  # 失败 #
        return  # 返回 #

    if not check_dependencies():
        return  # 依赖缺失 #

    port = args.port or config.asr.port  # 端口 #
    
    print("=" * 50)  # 分隔线 #
    print("🎤 NagaAgent 语音输入服务（ASR + VAD）")  # 标题 #
    print("=" * 50)  # 分隔线 #
    print(f"📋 配置信息:")  # 配置 #
    print(f"   端口: {port}")  # 端口 #
    print(f"   模式: {args.mode}")  # 模式 #
    print(f"   设备: {config.asr.device_index or '自动'}")
    print(f"   采样率: {config.asr.sample_rate_in}Hz")  # 采样率 #
    print(f"   VAD阈值: {config.asr.vad_threshold}")  # VAD阈值 #
    print(f"   静音阈值: {config.asr.silence_ms}ms")  # 静音阈值 #
    print(f"   识别引擎: {config.asr.engine}")  # 识别引擎 #
    print(f"   模型路径: {config.asr.local_model_path}")  # 模型路径 #
    print("=" * 50)  # 分隔线 #
    
    import uvicorn  # 导入 #
    from voice.input.server import app  # 导入 #
    
    print(f"🚀 启动语音输入服务: http://127.0.0.1:{port}")  # 提示 #
    if args.mode in ["websocket", "both"]:
        print(f"🔌 WebSocket端点: ws://127.0.0.1:{port}/v1/audio/asr_ws")  # WebSocket #
    
    uvicorn.run(app, host="0.0.0.0", port=port)  # 启动 #


if __name__ == "__main__":
    main()  # 入口 #


