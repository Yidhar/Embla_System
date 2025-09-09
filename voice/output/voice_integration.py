#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音集成模块 - 重构版本：依赖apiserver的流式TTS实现
支持接收处理好的普通文本、并发音频合成和pygame播放
"""
import asyncio
import logging
import tempfile
import os
import threading
import time
import hashlib
import re
import io
import base64
from typing import Optional, List, Dict, Any
import aiohttp
import sys
from pathlib import Path
from queue import Queue, Empty

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from system.config import config, AI_NAME

logger = logging.getLogger("VoiceIntegration")

# 简化的句子结束标点（依赖apiserver的预处理）
SENTENCE_ENDINGS = ["。", "！", "？", "；", ".", "!", "?", ";"]

class VoiceIntegration:
    """语音集成模块 - 重构版本：依赖apiserver的流式TTS实现"""
    
    def __init__(self):
        self.provider = 'edge_tts'  # 默认使用Edge TTS
        self.tts_url = f"http://127.0.0.1:{config.tts.port}/v1/audio/speech"
        
        # 音频播放配置
        self.min_sentence_length = 5  # 最小句子长度（硬编码默认值）
        self.max_concurrent_tasks = 3  # 最大并发任务数（硬编码默认值）
        
        # 并发控制
        self.tts_semaphore = threading.Semaphore(2)  # 限制TTS请求并发数为2
        
        # 音频文件存储目录
        self.audio_temp_dir = Path("logs/audio_temp")
        self.audio_temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 流式处理状态
        self.text_buffer = ""  # 文本缓冲区
        self.is_processing = False  # 是否正在处理
        self.sentence_queue = Queue()  # 句子队列
        self.audio_queue = Queue()  # 音频队列
        
        # 播放状态控制
        self.is_playing = False
        self.current_playback = None
        
        # pygame音频初始化
        self._init_pygame_audio()
        
        # 启动音频播放工作线程
        self.audio_thread = threading.Thread(target=self._audio_player_worker, daemon=True)
        self.audio_thread.start()
        
        # 启动音频处理工作线程（持续运行）
        self.processing_thread = threading.Thread(target=self._audio_processing_worker, daemon=True)
        self.processing_thread.start()
        
        # 启动音频文件清理线程
        self.cleanup_thread = threading.Thread(target=self._audio_cleanup_worker, daemon=True)
        self.cleanup_thread.start()
        
        logger.info("语音集成模块初始化完成（重构版本 - 依赖apiserver）")

    def _init_pygame_audio(self):
        """初始化pygame音频系统"""
        try:
            import pygame
            pygame.init()
            
            try:
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
                logger.info("pygame音频系统初始化成功")
            except Exception as e:
                logger.warning(f"使用指定参数初始化失败，尝试默认参数: {e}")
                pygame.mixer.init()
                logger.info("pygame音频系统初始化成功（使用默认参数）")
            
            self.pygame_available = True
            logger.info(f"pygame版本: {pygame.version.ver}")
            
        except ImportError:
            logger.error("pygame未安装，语音播放功能不可用")
            self.pygame_available = False
        except Exception as e:
            logger.error(f"pygame音频初始化失败: {e}")
            self.pygame_available = False

    def receive_final_text(self, final_text: str):
        """接收最终完整文本 - 流式处理"""
        if not config.system.voice_enabled:
            return
            
        if final_text and final_text.strip():
            logger.info(f"接收最终文本: {final_text[:100]}")
            # 重置状态，为新的对话做准备
            self.reset_processing_state()
            # 流式处理最终文本
            self._process_text_stream(final_text)

    def receive_text_chunk(self, text: str):
        """接收文本片段 - 流式处理"""
        if not config.system.voice_enabled:
            return
            
        if text and text.strip():
            # 流式文本直接处理，不累积
            logger.debug(f"接收文本片段: {text[:50]}...")
            self._process_text_stream(text.strip())

    def _process_text_stream(self, text: str):
        """处理文本流 - 直接接收apiserver处理好的普通文本"""
        if not text:
            return
            
        # 将文本添加到缓冲区
        self.text_buffer += text
        
        # 检查是否形成完整句子（简单的标点检测）
        self._check_and_queue_sentences()
        
    def _check_and_queue_sentences(self):
        """检查并加入句子队列 - 简化版本，依赖apiserver的预处理"""
        if not self.text_buffer:
            return
            
        # 简单的句子结束检测（apiserver已经处理过复杂的标点分割）
        sentence_endings = SENTENCE_ENDINGS
        
        for ending in sentence_endings:
            if ending in self.text_buffer:
                # 找到句子结束位置
                end_pos = self.text_buffer.find(ending) + 1
                sentence = self.text_buffer[:end_pos]
                
                # 检查句子是否有效
                if sentence.strip():
                    # 加入句子队列
                    self.sentence_queue.put(sentence)
                    logger.info(f"加入句子队列: {sentence[:50]}...")
                    
                    # 音频处理线程始终在运行，无需检查启动状态
                
                # 更新缓冲区
                self.text_buffer = self.text_buffer[end_pos:]
                break
        
    def _start_audio_processing(self):
        """启动音频处理线程"""
        # 线程已经在初始化时启动，这里只需要设置状态
        if not self.is_processing:
            logger.debug("音频处理线程已启动，准备处理新的句子...")
        # 线程会自动从队列中获取句子进行处理
        
    def reset_processing_state(self):
        """重置处理状态，为新的对话做准备"""
        # 清空队列
        while not self.sentence_queue.empty():
            try:
                self.sentence_queue.get_nowait()
            except Empty:
                break
                
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except Empty:
                break
                
        # 重置状态（不重置is_processing，因为线程是持续运行的）
        self.text_buffer = ""
        
        logger.debug("语音处理状态已重置")
        
    def _audio_processing_worker(self):
        """音频处理工作线程 - 持续运行"""
        logger.info("音频处理工作线程启动")
        
        try:
            while True:
                try:
                    # 从句子队列获取句子，增加超时时间
                    sentence = self.sentence_queue.get(timeout=10)
                        
                    # 设置处理状态
                    self.is_processing = True
                    
                    # 生成音频
                    audio_data = self._generate_audio_sync(sentence)
                    if audio_data:
                        self.audio_queue.put(audio_data)
                        logger.debug(f"音频生成完成: {sentence[:30]}...")
                    else:
                        logger.warning(f"音频生成失败: {sentence[:30]}...")
                        
                except Empty:
                    # 队列为空，检查是否还有待处理的文本
                    if self.text_buffer.strip():
                        # 还有未处理的文本，继续等待
                        continue
                    else:
                        # 没有更多文本，继续等待新的句子
                        logger.debug("音频处理线程等待新的句子...")
                        self.is_processing = False
                        continue
                        
        except Exception as e:
            logger.error(f"音频处理工作线程错误: {e}")
            self.is_processing = False
        finally:
            self.is_processing = False
            logger.info("音频处理工作线程结束")

    def _generate_audio_sync(self, text: str) -> Optional[bytes]:
        """同步生成音频数据"""
        # 使用信号量控制并发
        if not self.tts_semaphore.acquire(timeout=10):  # 10秒超时
            logger.warning("TTS请求超时，跳过音频生成")
            return None
            
        try:
            # 文本预处理
            if not getattr(config.tts, 'remove_filter', False):
                from voice.output.handle_text import prepare_tts_input_with_context
                text = prepare_tts_input_with_context(text)
            
            if not text.strip():
                return None
                
            headers = {}
            if config.tts.require_api_key:
                headers["Authorization"] = f"Bearer {config.tts.api_key}"
            
            payload = {
                "input": text,
                "voice": config.tts.default_voice,
                "response_format": config.tts.default_format,
                "speed": config.tts.default_speed
            }
            
            # 使用requests进行同步调用
            import requests
            response = requests.post(
                self.tts_url,
                json=payload,
                headers=headers,
                timeout=30  # 硬编码超时时间（秒）
            )
            
            if response.status_code == 200:
                audio_data = response.content
                logger.debug(f"音频生成成功: {len(audio_data)} bytes")
                return audio_data
            else:
                logger.error(f"TTS API调用失败: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"生成音频数据异常: {e}")
            return None
        finally:
            # 释放信号量
            self.tts_semaphore.release()

    def _audio_player_worker(self):
        """音频播放工作线程"""
        logger.info("音频播放工作线程启动")
        
        # 在工作线程中检查pygame是否已初始化
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.init()
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
                logger.info("音频播放工作线程中pygame初始化成功")
        except Exception as e:
            logger.error(f"音频播放工作线程中pygame初始化失败: {e}")
            return
        
        try:
            while True:
                try:
                    # 从队列获取音频数据，增加超时时间
                    audio_data = self.audio_queue.get(timeout=30)  # 增加到30秒超时
                        
                    if audio_data:
                        # 播放音频数据
                        self._play_audio_data_sync(audio_data)
                        
                except Empty:
                    # 队列为空，继续等待
                    logger.debug("音频队列为空，继续等待...")
                    continue
                except Exception as e:
                    logger.error(f"音频播放工作线程错误: {e}")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"音频播放工作线程异常: {e}")
        finally:
            try:
                pygame.mixer.quit()
                pygame.quit()
            except:
                pass

    def _play_audio_data_sync(self, audio_data: bytes):
        """同步播放音频数据"""
        try:
            import pygame
            import io
            import time
            
            # 检查pygame是否初始化
            if not pygame.mixer.get_init():
                logger.warning("pygame mixer未初始化，尝试重新初始化")
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            
            # 停止当前正在播放的音频
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                time.sleep(0.1)  # 给一点时间让音频停止
            
            # 从内存中播放音频数据
            audio_io = io.BytesIO(audio_data)
            pygame.mixer.music.load(audio_io)
            pygame.mixer.music.play()
            
            # 等待播放完成
            start_time = time.time()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                # 防止无限等待，设置最长播放时间（5分钟）
                if time.time() - start_time > 300:
                    logger.warning("音频播放超时，强制停止")
                    pygame.mixer.music.stop()
                    break
            
            logger.debug("音频播放完成")
            
        except Exception as e:
            logger.error(f"播放音频数据失败: {e}")
            # 尝试重新初始化pygame
            try:
                pygame.mixer.quit()
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            except:
                pass

    def _audio_cleanup_worker(self):
        """音频文件清理工作线程"""
        logger.info("音频文件清理工作线程启动")
        
        while True:
            try:
                time.sleep(60)  # 每60秒清理一次（硬编码清理间隔）
                
                # 获取所有音频文件
                audio_files = list(self.audio_temp_dir.glob(f"*.{config.tts.default_format}"))
                
                # 清理文件
                files_to_clean = []
                for file_path in audio_files:
                    # 检查文件是否过旧（超过5分钟，硬编码超时时间）
                    if time.time() - file_path.stat().st_mtime > 300:
                        files_to_clean.append(file_path)
                
                if files_to_clean:
                    logger.info(f"开始清理 {len(files_to_clean)} 个音频文件")
                    for file_path in files_to_clean:
                        try:
                            file_path.unlink()
                            logger.debug(f"已删除音频文件: {file_path}")
                        except Exception as e:
                            logger.warning(f"删除音频文件失败: {file_path} - {e}")
                    
                    logger.info(f"音频文件清理完成，共清理 {len(files_to_clean)} 个文件")
                else:
                    logger.debug("本次清理检查完成，无需要清理的文件")
                    
            except Exception as e:
                logger.error(f"音频文件清理异常: {e}")
                time.sleep(5)

    def finish_processing(self):
        """完成处理，清理剩余内容"""
        # 处理剩余的文本
        if self.text_buffer.strip():
            # 将剩余文本作为最后一个句子处理
            remaining_text = self.text_buffer.strip()
            if remaining_text:
                self.sentence_queue.put(remaining_text)
                logger.debug(f"处理剩余文本: {remaining_text[:50]}...")
        
        # 不再发送完成信号，因为线程是持续运行的
        # 只需要清空文本缓冲区
        self.text_buffer = ""

    def get_debug_info(self) -> Dict[str, Any]:
        """获取调试信息"""
        return {
            "text_buffer_length": len(self.text_buffer),
            "sentence_queue_size": self.sentence_queue.qsize(),
            "audio_queue_size": self.audio_queue.qsize(),
            "is_processing": self.is_processing,
            "is_playing": self.is_playing,
            "temp_files": len(list(self.audio_temp_dir.glob(f"*.{config.tts.default_format}")))
        }

def get_voice_integration() -> VoiceIntegration:
    """获取语音集成实例"""
    if not hasattr(get_voice_integration, '_instance'):
        get_voice_integration._instance = VoiceIntegration()
    return get_voice_integration._instance