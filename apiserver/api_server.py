#!/usr/bin/env python3
"""
NagaAgent API服务器
提供RESTful API接口访问NagaAgent功能
"""

import asyncio
import json
import sys
import traceback
import os
import logging
import uuid
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, AsyncGenerator, Any

# 在导入其他模块前先设置HTTP库日志级别
logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore.connection").setLevel(logging.WARNING)

# 创建logger实例
logger = logging.getLogger(__name__)

from nagaagent_core.api import uvicorn
from nagaagent_core.api import FastAPI, HTTPException, Request, UploadFile, File, Form
from nagaagent_core.api import CORSMiddleware
from nagaagent_core.api import StreamingResponse
from nagaagent_core.api import StaticFiles
from pydantic import BaseModel
from nagaagent_core.core import aiohttp
import shutil
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 工具调用模块（仅用于流式接口）
from .message_manager import message_manager  # 导入统一的消息管理器

from .llm_service import get_llm_service  # 导入LLM服务

# 导入配置系统
try:
    from system.config import config, AI_NAME  # 使用新的配置系统
    from system.config import get_prompt  # 导入提示词仓库
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from system.config import config, AI_NAME  # 使用新的配置系统
    from system.config import get_prompt  # 导入提示词仓库
from ui.response_utils import extract_message  # 导入消息提取工具

# conversation_core已删除，相关功能已迁移到apiserver

# 统一后台意图分析触发函数
def _trigger_background_analysis(session_id: str):
    """统一触发后台意图分析"""  # 统一入口，避免重复代码
    try:
        from system.background_analyzer import get_background_analyzer  # 延迟导入，避免启动时依赖问题
        background_analyzer = get_background_analyzer()  # 获取全局实例
        recent_messages = message_manager.get_recent_messages(session_id, count=6)  # 获取最近对话
        asyncio.create_task(background_analyzer.analyze_intent_async(recent_messages, session_id))  # 异步执行
    except Exception as e:
        print(f"后台意图分析触发失败: {e}")  # 失败不影响主流程

# 统一保存对话与日志函数
def _save_conversation_and_logs(session_id: str, user_message: str, assistant_response: str):
    """统一保存对话历史与日志"""  # 统一入口，避免重复代码
    try:
        # 保存对话历史到消息管理器
        message_manager.add_message(session_id, "user", user_message)
        message_manager.add_message(session_id, "assistant", assistant_response)
        
        # 保存对话日志到文件
        message_manager.save_conversation_log(
            user_message, 
            assistant_response, 
            dev_mode=False  # 开发者模式已删除
        )
    except Exception as e:
        print(f"保存对话与日志失败: {e}")  # 失败不影响主流程

# 回调工厂类 - 统一管理重复的回调函数
class CallbackFactory:
    """回调函数工厂类 - 消除重复定义"""
    
    @staticmethod
    def create_text_chunk_callback(pure_text_content_ref, is_streaming=False):
        """创建文本块回调函数"""
        def on_text_chunk(text: str, chunk_type: str):
            """处理文本块 - 累积纯文本内容"""
            if chunk_type == "chunk":
                pure_text_content_ref[0] += text
                # 不再向前端推送分句事件；SSE 增量由主循环直接推送
            return None
        return on_text_chunk
    
    @classmethod
    def create_callbacks(cls, pure_text_content_ref, is_streaming=False):
        """创建完整的回调函数集合"""
        return {
            'on_text_chunk': cls.create_text_chunk_callback(pure_text_content_ref, is_streaming)
        }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    try:
        print("[INFO] 正在初始化API服务器...")
        # conversation_core已删除，相关功能已迁移到apiserver
        print("[SUCCESS] API服务器初始化完成")
        yield
    except Exception as e:
        print(f"[ERROR] API服务器初始化失败: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("[INFO] 正在清理资源...")
        # MCP服务现在由mcpserver独立管理，无需清理

# 创建FastAPI应用
app = FastAPI(
    title="NagaAgent API",
    description="智能对话助手API服务",
    version="4.0.0",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 请求模型
class ChatRequest(BaseModel):
    message: str
    stream: bool = False
    session_id: Optional[str] = None
    use_self_game: bool = False
    disable_tts: bool = False  # V17: 支持禁用服务器端TTS
    return_audio: bool = False  # V19: 支持返回音频URL供客户端播放

class ChatResponse(BaseModel):
    response: str
    session_id: Optional[str] = None
    status: str = "success"



class SystemInfoResponse(BaseModel):
    version: str
    status: str
    available_services: List[str]
    api_key_configured: bool

class FileUploadResponse(BaseModel):
    filename: str
    file_path: str
    file_size: int
    file_type: str
    upload_time: str
    status: str = "success"
    message: str = "文件上传成功"

class DocumentProcessRequest(BaseModel):
    file_path: str
    action: str = "read"  # read, analyze, summarize
    session_id: Optional[str] = None


# API路由
@app.get("/", response_model=Dict[str, str])
async def root():
    """API根路径"""
    return {
        "name": "NagaAgent API",
        "version": "4.0.0",
        "status": "running",
        "docs": "/docs",
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "agent_ready": True,
        "timestamp": str(asyncio.get_event_loop().time())
    }

@app.get("/system/info", response_model=SystemInfoResponse)
async def get_system_info():
    """获取系统信息"""
    
    return SystemInfoResponse(
        version="4.0.0",
        status="running",
        available_services=[],  # MCP服务现在由mcpserver独立管理
        api_key_configured=bool(config.api.api_key and config.api.api_key != "sk-placeholder-key-not-set")
    )

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """普通对话接口 - 仅处理纯文本对话"""
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    
    try:
        # 分支: 启用博弈论流程（非流式，返回聚合文本）
        if request.use_self_game:
            # 配置项控制：失败时可跳过回退到普通对话 #
            skip_on_error = getattr(getattr(config, 'game', None), 'skip_on_error', True)  # 兼容无配置情况 #
            enabled = getattr(getattr(config, 'game', None), 'enabled', False)  # 控制总开关 #
            if enabled:
                try:
                    # 延迟导入以避免启动时循环依赖 #
                    from game.naga_game_system import NagaGameSystem  # 博弈系统入口 #
                    from game.core.models.config import GameConfig  # 博弈系统配置 #
                    # 创建系统并执行用户问题处理 #
                    system = NagaGameSystem(GameConfig())
                    system_response = await system.process_user_question(
                        user_question=request.message,
                        user_id=request.session_id or "api_user"
                    )
                    return ChatResponse(
                        response=system_response.content,
                        session_id=request.session_id,
                        status="success"
                    )
                except Exception as e:
                    print(f"[WARNING] 博弈论流程失败，将{ '回退到普通对话' if skip_on_error else '返回错误' }: {e}")  # 运行时警告 #
                    if not skip_on_error:
                        raise HTTPException(status_code=500, detail=f"博弈论流程失败: {str(e)}")
                    # 否则继续走普通对话流程 #
            # 若未启用或被配置跳过，则直接回退到普通对话分支 #

        # 获取或创建会话ID
        session_id = message_manager.create_session(request.session_id)
        
        # 构建系统提示词（不再注入服务信息）
        system_prompt = get_prompt("naga_system_prompt", ai_name=AI_NAME)
        
        # 使用消息管理器构建完整的对话消息（纯聊天，不触发工具）
        messages = message_manager.build_conversation_messages(
            session_id=session_id,
            system_prompt=system_prompt,
            current_message=request.message
        )
        
        # 用于累积纯文本内容
        pure_text_content = [""]  # 使用列表引用，便于在回调中修改
        
        # 调用LLM API - 流式模式
        timeout = aiohttp.ClientTimeout(total=120, connect=30, sock_read=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            
            async with session.post(
                f"{config.api.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": config.api.model,
                    "messages": messages,
                    "temperature": config.api.temperature,
                    "max_tokens": config.api.max_tokens,
                    "stream": True
                }
            ) as resp:
                if resp.status != 200:
                    error_detail = f"LLM API调用失败 (状态码: {resp.status})"
                    if resp.status == 401:
                        error_detail = "LLM API认证失败，请检查API密钥"
                    elif resp.status == 403:
                        error_detail = "LLM API访问被拒绝，请检查权限"
                    elif resp.status == 429:
                        error_detail = "LLM API请求过于频繁，请稍后重试"
                    elif resp.status >= 500:
                        error_detail = f"LLM API服务器错误 (状态码: {resp.status})"
                    raise HTTPException(status_code=resp.status, detail=error_detail)
                
                # 处理流式响应
                async for line in resp.content:
                    line_str = line.decode('utf-8').strip()
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            if 'choices' in data and len(data['choices']) > 0:
                                delta = data['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    content = delta['content']
                                    # 直接累积纯文本内容
                                    pure_text_content[0] += content
                        except json.JSONDecodeError:
                            continue
        
        # 处理完成
        
        # 统一保存对话历史与日志
        _save_conversation_and_logs(session_id, request.message, pure_text_content[0])
        
        
        # 异步触发后台意图分析 - 基于博弈论的背景分析机制
        _trigger_background_analysis(session_id)
        
        return ChatResponse(
            response=extract_message(pure_text_content[0]) if pure_text_content[0] else pure_text_content[0],
            session_id=session_id,
            status="success"
        )
    except Exception as e:
        print(f"对话处理错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口 - 流式文本处理交给streaming_tool_extractor"""
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    
    async def generate_response() -> AsyncGenerator[str, None]:
        complete_text = ""  # V19: 用于累积完整文本以生成音频
        try:
            # 获取或创建会话ID
            session_id = message_manager.create_session(request.session_id)
            
            # 发送会话ID信息
            yield f"data: session_id: {session_id}\n\n"
            
            # 构建系统提示词（不再注入服务信息）
            system_prompt = get_prompt("naga_system_prompt", ai_name=AI_NAME)
            
            # 使用消息管理器构建完整的对话消息
            messages = message_manager.build_conversation_messages(
                session_id=session_id,
                system_prompt=system_prompt,
                current_message=request.message
            )

            # 流式文本处理完全交给streaming_tool_extractor
            # apiserver不再负责累积文本内容

            # 初始化语音集成（根据voice_mode和return_audio决定）
            # V19: 如果客户端请求返回音频，则在服务器端生成
            voice_integration = None

            # V19: 混合模式下，如果请求return_audio，则在服务器生成音频
            # 修复双音频问题：return_audio时不启用实时TTS，只在最后生成完整音频
            should_enable_tts = (
                config.system.voice_enabled
                and not request.return_audio  # 修复：return_audio时不启用实时TTS
                and config.voice_realtime.voice_mode != "hybrid"
                and not request.disable_tts  # 兼容旧版本的disable_tts
            )

            if should_enable_tts:
                try:
                    from voice.output.voice_integration import get_voice_integration
                    voice_integration = get_voice_integration()
                    logger.info(f"[API Server] 实时语音集成已启用 (return_audio={request.return_audio}, voice_mode={config.voice_realtime.voice_mode})")
                except Exception as e:
                    print(f"语音集成初始化失败: {e}")
            else:
                if request.return_audio:
                    logger.info("[API Server] return_audio模式，将在最后生成完整音频")
                elif config.voice_realtime.voice_mode == "hybrid" and not request.return_audio:
                    logger.info("[API Server] 混合模式下且未请求音频，不处理TTS")
                elif request.disable_tts:
                    logger.info("[API Server] 客户端禁用了TTS (disable_tts=True)")

            # 初始化流式文本切割器（负责文本处理和TTS）
            # 修复：始终创建tool_extractor以累积文本内容，确保日志保存
            tool_extractor = None
            try:
                from .streaming_tool_extractor import StreamingToolCallExtractor
                tool_extractor = StreamingToolCallExtractor()
                # 只有在需要实时TTS且不是return_audio模式时，才设置voice_integration
                if voice_integration and not request.return_audio:
                    tool_extractor.set_callbacks(
                        on_text_chunk=None,  # 不需要回调，直接处理TTS
                        voice_integration=voice_integration
                    )
            except Exception as e:
                print(f"流式文本切割器初始化失败: {e}")
            
            # 定义LLM调用函数 - 支持真正的流式输出
            async def call_llm_stream(messages: List[Dict]) -> AsyncGenerator[str, None]:
                """调用LLM API - 流式模式"""
                nonlocal complete_text  # V19: 声明使用外层函数的变量

                # 增加超时配置
                timeout = aiohttp.ClientTimeout(
                    total=180,  # 总超时时间增加到3分钟
                    connect=60,  # 连接超时60秒
                    sock_read=120  # 读取超时120秒
                )

                # 配置连接器以处理长连接
                connector = aiohttp.TCPConnector(
                    force_close=False,
                    keepalive_timeout=120,
                    enable_cleanup_closed=True
                )

                async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                    logger.info(f"[API Server] 开始流式调用LLM: {config.api.base_url}")

                    async with session.post(
                        f"{config.api.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {config.api.api_key}",
                            "Content-Type": "application/json",
                            "Accept": "text/event-stream",
                            "Connection": "keep-alive"
                        },
                        json={
                            "model": config.api.model,
                            "messages": messages,
                            "temperature": config.api.temperature,
                            "max_tokens": config.api.max_tokens,
                            "stream": True  # 启用真正的流式输出
                        }
                    ) as resp:
                        if resp.status != 200:
                            error_detail = f"LLM API调用失败 (状态码: {resp.status})"
                            if resp.status == 401:
                                error_detail = "LLM API认证失败，请检查API密钥"
                            elif resp.status == 403:
                                error_detail = "LLM API访问被拒绝，请检查权限"
                            elif resp.status == 429:
                                error_detail = "LLM API请求过于频繁，请稍后重试"
                            elif resp.status >= 500:
                                error_detail = f"LLM API服务器错误 (状态码: {resp.status})"
                            raise HTTPException(status_code=resp.status, detail=error_detail)

                        logger.info(f"[API Server] LLM流式响应开始，状态码: {resp.status}")

                        # 处理流式响应，增加错误恢复机制
                        buffer = ""
                        try:
                            async for chunk in resp.content.iter_chunked(1024):  # 使用固定大小的块
                                if not chunk:
                                    break

                                try:
                                    # 解码并处理数据
                                    data = chunk.decode('utf-8')
                                    buffer += data

                                    # 按行分割处理
                                    lines = buffer.split('\n')
                                    buffer = lines[-1]  # 保留最后一个可能不完整的行

                                    for line in lines[:-1]:
                                        line_str = line.strip()
                                        if line_str.startswith('data: '):
                                            data_str = line_str[6:]
                                            if data_str == '[DONE]':
                                                break
                                            try:
                                                data = json.loads(data_str)
                                                if 'choices' in data and len(data['choices']) > 0:
                                                    delta = data['choices'][0].get('delta', {})
                                                    if 'content' in delta:
                                                        content = delta['content']
                                                        # 直接将增量内容推送给前端用于消息渲染
                                                        yield f"data: {content}\n\n"

                                                        # V19: 如果需要返回音频，累积文本
                                                        if request.return_audio:
                                                            complete_text += content

                                                        # 发送到流式文本切割器进行文本处理
                                                        # 修复：始终发送到tool_extractor以累积完整文本
                                                        if tool_extractor:
                                                            try:
                                                                await tool_extractor.process_text_chunk(content)
                                                            except Exception as e:
                                                                logger.error(f"[API Server] 流式文本切割器处理错误: {e}")

                                            except json.JSONDecodeError as je:
                                                logger.warning(f"[API Server] JSON解析错误: {je}, 数据: {data_str[:100]}")
                                                continue

                                except UnicodeDecodeError as ue:
                                    logger.warning(f"[API Server] 解码错误: {ue}")
                                    continue

                        except asyncio.CancelledError:
                            logger.info("[API Server] 流式响应被取消")
                            raise
                        except Exception as e:
                            logger.error(f"[API Server] 流式响应处理错误: {e}")
                            # 不抛出异常，继续处理
            
            # 处理流式响应
            async for chunk in call_llm_stream(messages):
                yield chunk
            
            # 处理完成

            # V19: 如果请求返回音频，在这里生成并返回音频URL
            if request.return_audio and complete_text:
                try:
                    logger.info(f"[API Server V19] 生成音频，文本长度: {len(complete_text)}")

                    # 使用服务器端的TTS生成音频
                    from voice.tts_wrapper import generate_speech_safe
                    import tempfile
                    import uuid

                    # 生成音频文件
                    tts_voice = config.voice_realtime.tts_voice or "zh-CN-XiaoyiNeural"
                    audio_file = generate_speech_safe(
                        text=complete_text,
                        voice=tts_voice,
                        response_format="mp3",
                        speed=1.0
                    )

                    # 直接使用voice/output播放音频，不再返回给客户端
                    try:
                        from voice.output.voice_integration import get_voice_integration
                        voice_integration = get_voice_integration()
                        voice_integration.receive_audio_url(audio_file)
                        logger.info(f"[API Server V19] 音频已直接播放: {audio_file}")
                    except Exception as e:
                        logger.error(f"[API Server V19] 音频播放失败: {e}")
                        # 如果播放失败，仍然返回给客户端作为备选
                        yield f"data: audio_url: {audio_file}\n\n"

                except Exception as e:
                    logger.error(f"[API Server V19] 音频生成失败: {e}")
                    # traceback已经在文件顶部导入，直接使用
                    print(f"[API Server V19] 详细错误信息:")
                    traceback.print_exc()

            # 完成流式文本切割器处理（非return_audio模式）
            if tool_extractor and not request.return_audio:
                try:
                    await tool_extractor.finish_processing()
                except Exception as e:
                    print(f"流式文本切割器完成处理错误: {e}")
            
            # 完成语音处理
            if voice_integration and not request.return_audio:  # V19: return_audio模式不需要这里的处理
                try:
                    import threading
                    threading.Thread(
                        target=voice_integration.finish_processing,
                        daemon=True
                    ).start()
                except Exception as e:
                    print(f"语音集成完成处理错误: {e}")

            # 流式处理完成后，获取完整文本用于保存
            complete_response = ""
            if tool_extractor:
                try:
                    # 获取完整文本内容
                    complete_response = tool_extractor.get_complete_text()
                except Exception as e:
                    print(f"获取完整响应文本失败: {e}")
            elif request.return_audio:
                # V19: 如果是return_audio模式，使用累积的文本
                complete_response = complete_text

            # 统一保存对话历史与日志
            _save_conversation_and_logs(session_id, request.message, complete_response)
            
            
            # 异步触发后台意图分析 - 基于博弈论的背景分析机制
            _trigger_background_analysis(session_id)
            
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            print(f"流式对话处理错误: {e}")
            # 使用顶部导入的traceback
            traceback.print_exc()
            yield f"data: 错误: {str(e)}\n\n"
    
    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "X-Accel-Buffering": "no"  # 禁用nginx缓冲
        }
    )


@app.get("/memory/stats")
async def get_memory_stats():
    """获取记忆统计信息"""
    
    try:
        # 记忆系统现在由main.py直接管理
        try:
            from summer_memory.memory_manager import memory_manager
            if memory_manager and memory_manager.enabled:
                stats = memory_manager.get_memory_stats()
                return {
                    "status": "success",
                    "memory_stats": stats
                }
            else:
                return {
                    "status": "success",
                    "memory_stats": {"enabled": False, "message": "记忆系统未启用"}
                }
        except ImportError:
            return {
                "status": "success",
                "memory_stats": {"enabled": False, "message": "记忆系统模块未找到"}
            }
    except Exception as e:
        print(f"获取记忆统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取记忆统计失败: {str(e)}")

@app.get("/sessions")
async def get_sessions():
    """获取所有会话信息"""
    try:
        # 清理过期会话
        message_manager.cleanup_old_sessions()
        
        # 获取所有会话信息
        sessions_info = message_manager.get_all_sessions_info()
        
        return {
            "status": "success",
            "sessions": sessions_info,
            "total_sessions": len(sessions_info)
        }
    except Exception as e:
        print(f"获取会话信息错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取会话信息失败: {str(e)}")

@app.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """获取指定会话的详细信息"""
    try:
        session_info = message_manager.get_session_info(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        return {
            "status": "success",
            "session_id": session_id,
            "session_info": session_info,
            "messages": message_manager.get_messages(session_id),
            "conversation_rounds": session_info["conversation_rounds"]
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"获取会话详情错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {str(e)}")

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    try:
        success = message_manager.delete_session(session_id)
        if success:
            return {
                "status": "success",
                "message": f"会话 {session_id} 已删除"
            }
        else:
            raise HTTPException(status_code=404, detail="会话不存在")
    except HTTPException:
        raise
    except Exception as e:
        print(f"删除会话错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")

@app.delete("/sessions")
async def clear_all_sessions():
    """清空所有会话"""
    try:
        count = message_manager.clear_all_sessions()
        return {
            "status": "success",
            "message": f"已清空 {count} 个会话"
        }
    except Exception as e:
        print(f"清空会话错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"清空会话失败: {str(e)}")

# 文件上传和文档处理接口
@app.post("/upload/document", response_model=FileUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    description: str = Form(None)
):
    """上传文档文件"""
    try:
        # 创建上传目录
        upload_dir = Path("uploaded_documents")
        upload_dir.mkdir(exist_ok=True)
        
        # 检查文件类型
        allowed_extensions = {".docx", ".doc", ".txt", ".pdf", ".md"}
        file_extension = Path(file.filename).suffix.lower()
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"不支持的文件类型: {file_extension}。支持的类型: {', '.join(allowed_extensions)}"
            )
        
        # 生成唯一文件名
        import time
        timestamp = str(int(time.time()))
        safe_filename = f"{timestamp}_{file.filename}"
        file_path = upload_dir / safe_filename
        
        # 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 获取文件信息
        file_size = file_path.stat().st_size
        upload_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        return FileUploadResponse(
            filename=file.filename,
            file_path=str(file_path),
            file_size=file_size,
            file_type=file_extension,
            upload_time=upload_time,
            message=f"文件 '{file.filename}' 上传成功"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")

@app.post("/document/process")
async def process_document(request: DocumentProcessRequest):
    """处理上传的文档"""
    
    try:
        file_path = Path(request.file_path)
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_path}")
        
        # 根据文件类型和操作类型处理文档
        if file_path.suffix.lower() == ".docx":
            # 使用Word MCP服务处理
            mcp_request = {
                "service_name": "office_word_mcp",
                "task": {
                    "tool_name": "get_document_text",
                    "filename": str(file_path)
                }
            }
            
            # 调用MCP服务
            # MCP服务现在由mcpserver独立管理，通过HTTP调用
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8003/schedule",
                    json=mcp_request,
                    timeout=30.0
                )
                result = response.json()
            
            if request.action == "read":
                return {
                    "status": "success",
                    "action": "read",
                    "file_path": request.file_path,
                    "content": result,
                    "message": "文档内容读取成功"
                }
            elif request.action == "analyze":
                # 让NAGA分析文档内容
                analysis_prompt = f"请分析以下文档内容，提供结构化的分析报告：\n\n{result}"
                llm_service = get_llm_service()
                analysis_result = await llm_service.get_response(analysis_prompt)
                
                return {
                    "status": "success",
                    "action": "analyze",
                    "file_path": request.file_path,
                    "analysis": analysis_result,
                    "message": "文档分析完成"
                }
            elif request.action == "summarize":
                # 让NAGA总结文档内容
                summary_prompt = f"请总结以下文档内容，提供简洁的摘要：\n\n{result}"
                llm_service = get_llm_service()
                summary_result = await llm_service.get_response(summary_prompt)
                
                return {
                    "status": "success",
                    "action": "summarize",
                    "file_path": request.file_path,
                    "summary": summary_result,
                    "message": "文档总结完成"
                }
        else:
            # 处理其他文件类型
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if request.action == "read":
                return {
                    "status": "success",
                    "action": "read",
                    "file_path": request.file_path,
                    "content": content,
                    "message": "文档内容读取成功"
                }
            elif request.action == "analyze":
                analysis_prompt = f"请分析以下文档内容，提供结构化的分析报告：\n\n{content}"
                llm_service = get_llm_service()
                analysis_result = await llm_service.get_response(analysis_prompt)
                
                return {
                    "status": "success",
                    "action": "analyze",
                    "file_path": request.file_path,
                    "analysis": analysis_result,
                    "message": "文档分析完成"
                }
            elif request.action == "summarize":
                summary_prompt = f"请总结以下文档内容，提供简洁的摘要：\n\n{content}"
                llm_service = get_llm_service()
                summary_result = await llm_service.get_response(summary_prompt)
                
                return {
                    "status": "success",
                    "action": "summarize",
                    "file_path": request.file_path,
                    "summary": summary_result,
                    "message": "文档总结完成"
                }
        
    except Exception as e:
        print(f"文档处理错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"文档处理失败: {str(e)}")

@app.get("/documents/list")
async def list_uploaded_documents():
    """获取已上传的文档列表"""
    try:
        upload_dir = Path("uploaded_documents")
        if not upload_dir.exists():
            return {
                "status": "success",
                "documents": [],
                "total": 0
            }
        
        documents = []
        for file_path in upload_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                documents.append({
                    "filename": file_path.name,
                    "file_path": str(file_path),
                    "file_size": stat.st_size,
                    "file_type": file_path.suffix.lower(),
                    "upload_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
                })
        
        # 按上传时间排序
        documents.sort(key=lambda x: x["upload_time"], reverse=True)
        
        return {
            "status": "success",
            "documents": documents,
            "total": len(documents)
        }
        
    except Exception as e:
        print(f"获取文档列表错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取文档列表失败: {str(e)}")

# 新增：日志解析相关API接口
@app.get("/logs/context/statistics")
async def get_log_context_statistics(days: int = 7):
    """获取日志上下文统计信息"""
    try:
        statistics = message_manager.get_context_statistics(days)
        return {
            "status": "success",
            "statistics": statistics
        }
    except Exception as e:
        print(f"获取日志上下文统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")

@app.get("/logs/context/load")
async def load_log_context(days: int = 3, max_messages: int = None):
    """加载日志上下文"""
    try:
        messages = message_manager.load_recent_context(days=days, max_messages=max_messages)
        return {
            "status": "success",
            "messages": messages,
            "count": len(messages),
            "days": days
        }
    except Exception as e:
        print(f"加载日志上下文错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"加载上下文失败: {str(e)}")

