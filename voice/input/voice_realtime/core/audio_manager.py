#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
音频管理器
处理音频输入输出、录音、播放等功能
"""

import queue
import threading
import time
import base64
import logging
from typing import Optional, Callable
from contextlib import suppress

import numpy as np

# 尝试导入pyaudio，如果失败则提供友好提示
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    pyaudio = None

logger = logging.getLogger(__name__)


class AudioManager:
    """
    音频管理器
    负责音频的录制、播放和处理
    """

    def __init__(
        self,
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
        chunk_size_ms: int = 200,
        vad_threshold: float = 0.02,
        echo_suppression: bool = True
    ):
        """
        初始化音频管理器

        参数:
            input_sample_rate: 输入采样率（Hz）
            output_sample_rate: 输出采样率（Hz）
            chunk_size_ms: 音频块大小（毫秒）
            vad_threshold: 静音检测阈值（0-1）
            echo_suppression: 是否启用回声抑制
        """
        if not PYAUDIO_AVAILABLE:
            raise ImportError(
                "PyAudio is not installed. Please install it with: "
                "pip install pyaudio"
            )

        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.chunk_size_ms = chunk_size_ms
        self.vad_threshold = vad_threshold
        self.echo_suppression = echo_suppression

        # 计算缓冲区大小
        self.input_chunk_size = int(input_sample_rate * chunk_size_ms / 1000)
        self.output_chunk_size = int(output_sample_rate * chunk_size_ms / 1000)

        # PyAudio实例
        self.pya = None
        self.input_stream = None
        self.output_stream = None

        # 队列
        self.input_queue = queue.Queue()
        self.output_queue = queue.Queue()
        self.b64_output_queue = queue.Queue()

        # 状态控制
        self.is_running = False
        self.is_recording = False
        self.is_playing = False
        self.force_mute = False

        # AI响应状态
        self.ai_response_done = False
        self.empty_queue_count = 0

        # 线程
        self.input_thread = None
        self.output_decoder_thread = None
        self.output_player_thread = None

        # 回调函数
        self.on_audio_input: Optional[Callable[[bytes], None]] = None
        self.on_playback_started: Optional[Callable[[], None]] = None
        self.on_playback_ended: Optional[Callable[[], None]] = None

        # 统计信息
        self.stats = {
            'input_chunks': 0,
            'output_chunks': 0,
            'silence_chunks': 0,
            'muted_chunks': 0
        }

        logger.info(f"AudioManager initialized: input={input_sample_rate}Hz, "
                   f"output={output_sample_rate}Hz, chunk={chunk_size_ms}ms")

    def initialize(self) -> bool:
        """
        初始化音频设备

        返回:
            bool: 是否成功初始化
        """
        try:
            # 创建PyAudio实例
            self.pya = pyaudio.PyAudio()

            # 创建输入流（麦克风）
            self.input_stream = self.pya.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.input_sample_rate,
                input=True,
                frames_per_buffer=self.input_chunk_size
            )

            # 创建输出流（扬声器）
            self.output_stream = self.pya.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.output_sample_rate,
                output=True,
                frames_per_buffer=self.output_chunk_size
            )

            logger.info("Audio devices initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize audio devices: {e}")
            self._cleanup_streams()
            return False

    def start(self):
        """
        启动音频管理器
        """
        if self.is_running:
            logger.warning("AudioManager is already running")
            return

        self.is_running = True
        self.is_recording = True

        # 启动输入线程
        self.input_thread = threading.Thread(
            target=self._input_loop,
            daemon=True,
            name="AudioInput"
        )
        self.input_thread.start()

        # 启动输出解码线程
        self.output_decoder_thread = threading.Thread(
            target=self._output_decoder_loop,
            daemon=True,
            name="AudioDecoder"
        )
        self.output_decoder_thread.start()

        # 启动输出播放线程
        self.output_player_thread = threading.Thread(
            target=self._output_player_loop,
            daemon=True,
            name="AudioPlayer"
        )
        self.output_player_thread.start()

        logger.info("AudioManager started")

    def stop(self):
        """
        停止音频管理器
        """
        logger.info("Stopping AudioManager...")

        # 设置停止标志
        self.is_running = False
        self.is_recording = False
        self.is_playing = False
        self.force_mute = False
        self.ai_response_done = False
        self.empty_queue_count = 0

        # 清空队列
        self._clear_all_queues()

        # 等待线程结束
        for thread in [self.input_thread, self.output_decoder_thread, self.output_player_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=1.0)

        # 清理音频流
        self._cleanup_streams()

        logger.info("AudioManager stopped")

    def _cleanup_streams(self):
        """清理音频流"""
        if self.input_stream:
            try:
                if self.input_stream.is_active():
                    self.input_stream.stop_stream()
                self.input_stream.close()
            except:
                pass
            self.input_stream = None

        if self.output_stream:
            try:
                if self.output_stream.is_active():
                    self.output_stream.stop_stream()
                self.output_stream.close()
            except:
                pass
            self.output_stream = None

        if self.pya:
            try:
                self.pya.terminate()
            except:
                pass
            self.pya = None

    def _clear_all_queues(self):
        """清空所有队列"""
        for q in [self.input_queue, self.output_queue, self.b64_output_queue]:
            while not q.empty():
                with suppress(queue.Empty):
                    q.get_nowait()

    def _input_loop(self):
        """输入音频循环"""
        silence_duration = 0

        while self.is_running:
            try:
                if not self.input_stream:
                    time.sleep(0.1)
                    continue

                # 读取音频数据
                audio_data = self.input_stream.read(
                    self.input_chunk_size,
                    exception_on_overflow=False
                )

                # 统计
                self.stats['input_chunks'] += 1

                # 检查是否应该静音
                if self.force_mute or not self.is_recording:
                    self.stats['muted_chunks'] += 1
                    continue

                # 静音检测
                if self._is_silence(audio_data):
                    silence_duration += self.chunk_size_ms
                    self.stats['silence_chunks'] += 1
                    if silence_duration > 2000:  # 2秒静音跳过
                        continue
                else:
                    silence_duration = 0

                # 添加到队列
                self.input_queue.put(audio_data)

                # 触发回调
                if self.on_audio_input:
                    self.on_audio_input(audio_data)

            except Exception as e:
                if self.is_running:
                    logger.error(f"Input loop error: {e}")
                time.sleep(0.1)

    def _output_decoder_loop(self):
        """输出音频解码循环"""
        while self.is_running:
            try:
                # 从Base64队列获取数据
                audio_b64 = self.b64_output_queue.get(timeout=0.1)

                if audio_b64:
                    # 解码Base64
                    try:
                        audio_bytes = base64.b64decode(audio_b64)
                        # 添加到播放队列
                        self.output_queue.put(audio_bytes)
                    except Exception as e:
                        logger.error(f"Failed to decode audio: {e}")

            except queue.Empty:
                continue
            except Exception as e:
                if self.is_running:
                    logger.error(f"Decoder loop error: {e}")
                time.sleep(0.1)

    def _output_player_loop(self):
        """输出音频播放循环"""
        was_playing = False
        consecutive_empty = 0  # 连续空队列计数

        while self.is_running:
            try:
                # 从播放队列获取数据
                audio_chunk = None
                with suppress(queue.Empty):
                    audio_chunk = self.output_queue.get(timeout=0.1)

                if audio_chunk:
                    # 重置连续空计数
                    consecutive_empty = 0

                    # 开始播放
                    if not was_playing:
                        was_playing = True
                        self.is_playing = True
                        self.force_mute = True
                        self.empty_queue_count = 0
                        if self.on_playback_started:
                            self.on_playback_started()
                        logger.debug("Started audio playback")

                    # 播放音频
                    if self.output_stream:
                        self.output_stream.write(audio_chunk)
                        self.stats['output_chunks'] += 1
                else:
                    # 队列为空，检查是否结束播放
                    if was_playing:
                        self.empty_queue_count += 1
                        consecutive_empty += 1

                        # 更智能的结束判断
                        should_end = False

                        # 如果AI已完成且连续空队列达到阈值
                        if self.ai_response_done:
                            # 检查两个队列是否都真正为空
                            b64_empty = self.b64_output_queue.empty()
                            output_empty = self.output_queue.empty()

                            # 只有当两个队列都空且连续空闲时才结束
                            if b64_empty and output_empty and consecutive_empty > 7:
                                should_end = True
                                logger.info("AI response complete, both queues empty, ending after 0.7s")
                            elif consecutive_empty > 15:
                                # 增加一个更长的安全阈值
                                should_end = True
                                logger.info("AI response complete, extended wait reached")

                        # 防止永久等待的强制结束
                        if self.empty_queue_count > 30:
                            # 强制结束前，尝试播放剩余数据
                            remaining_chunks = 0
                            while not self.output_queue.empty():
                                try:
                                    chunk = self.output_queue.get_nowait()
                                    if self.output_stream and chunk:
                                        self.output_stream.write(chunk)
                                        remaining_chunks += 1
                                except:
                                    break

                            if remaining_chunks > 0:
                                logger.info(f"Flushed {remaining_chunks} remaining chunks before forcing end")

                            should_end = True
                            logger.warning("Queue idle for 3 seconds, forcing end")

                        if should_end:
                            # 最后的清理，确保没有残留数据
                            final_chunks = 0
                            while not self.output_queue.empty():
                                try:
                                    chunk = self.output_queue.get_nowait()
                                    if self.output_stream and chunk:
                                        self.output_stream.write(chunk)
                                        final_chunks += 1
                                except:
                                    break

                            if final_chunks > 0:
                                logger.debug(f"Played {final_chunks} final chunks before ending")

                            was_playing = False
                            self.empty_queue_count = 0
                            consecutive_empty = 0

                            # 最小延迟，让最后的音频完成
                            time.sleep(0.2)
                            self.is_playing = False
                            self.force_mute = False

                            # 确保缓冲区完全清空
                            self.clear_output_buffer()

                            if self.on_playback_ended:
                                self.on_playback_ended()
                            logger.debug("Ended audio playback")
                        else:
                            if self.empty_queue_count % 10 == 0:
                                logger.debug(f"Waiting for audio: {self.empty_queue_count}/30")
                    else:
                        self.empty_queue_count = 0

            except Exception as e:
                logger.error(f"Player loop error: {e}")
                time.sleep(0.1)

    def _is_silence(self, audio_data: bytes) -> bool:
        """检测音频是否为静音"""
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            energy = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            normalized_energy = energy / 32768.0
            return normalized_energy < self.vad_threshold
        except:
            return False

    def start_recording(self):
        """开始录音"""
        self.is_recording = True
        logger.info("Recording started")

    def stop_recording(self):
        """停止录音"""
        self.is_recording = False
        logger.info("Recording stopped")

    def add_output_audio(self, audio_b64: str):
        """添加要播放的音频（Base64格式）"""
        self.ai_response_done = False
        self.empty_queue_count = 0
        self.b64_output_queue.put(audio_b64)

    def mark_response_done(self):
        """标记AI响应已完成"""
        logger.info("AI response marked as done")
        self.ai_response_done = True

    def clear_output_buffer(self):
        """清空输出缓冲区（更彻底的清理）"""
        cleared_b64 = 0
        cleared_output = 0

        # 清空Base64队列
        while not self.b64_output_queue.empty():
            with suppress(queue.Empty):
                self.b64_output_queue.get_nowait()
                cleared_b64 += 1

        # 清空输出队列
        while not self.output_queue.empty():
            with suppress(queue.Empty):
                self.output_queue.get_nowait()
                cleared_output += 1

        # 重置状态标志
        self.ai_response_done = False
        self.empty_queue_count = 0

        if cleared_b64 > 0 or cleared_output > 0:
            logger.info(f"Output buffers cleared: b64={cleared_b64}, output={cleared_output}")
        else:
            logger.debug("Output buffers were already empty")

    def interrupt_playback(self):
        """中断AI播放"""
        logger.info("Interrupting playback")

        self.is_playing = False
        self.ai_response_done = True
        self.empty_queue_count = 0
        self.clear_output_buffer()

        # 重置音频流
        if self.output_stream:
            try:
                if self.output_stream.is_active():
                    self.output_stream.stop_stream()
                self.output_stream.close()

                # 重新创建输出流
                if self.pya:
                    self.output_stream = self.pya.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=self.output_sample_rate,
                        output=True,
                        frames_per_buffer=self.output_chunk_size
                    )
            except Exception as e:
                logger.error(f"Failed to reset audio stream: {e}")

        self.force_mute = False
        self.is_recording = True

        if self.on_playback_ended:
            self.on_playback_ended()

        logger.info("Playback interrupted and cleaned")

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            'is_running': self.is_running,
            'is_recording': self.is_recording,
            'is_playing': self.is_playing,
            'stats': self.stats.copy()
        }