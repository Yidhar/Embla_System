import nagaagent_core.vendors.numpy as np  # 数值 #
import onnxruntime as ort  # 推理 #
from typing import Iterator, Dict, Tuple  # 类型 #


class VADIterator:
    """流式 VAD 迭代器，用于实时语音分段 # 一行说明 #"""

    def __init__(self, speech_pad_ms: int = 300):
        self.speech_pad_ms = speech_pad_ms  # 语音后填充 #
        self.sample_rate = 16000  # 采样率 #
        self.speech_pad_frames = int(speech_pad_ms * self.sample_rate / 1000)  # 填充帧数 #
        self.silence_frames = 0  # 静音帧计数 #
        self.speech_frames = 0  # 语音帧计数 #
        self.current_speech = []  # 当前语音片段 #
        self.is_speaking = False  # 是否在说话 #

    def __call__(self, audio_chunk: np.ndarray) -> Iterator[Tuple[Dict[str, bool], np.ndarray]]:
        """处理音频块，返回 VAD 事件和音频数据 # 一行说明 #"""
        if not self.is_speaking:  # 未在说话 #
            if self._detect_speech_start(audio_chunk):  # 检测开始 #
                self.is_speaking = True
                self.speech_frames = 0
                self.silence_frames = 0
                self.current_speech = []
                yield {"start": True, "end": False}, audio_chunk  # 开始事件 #
            else:
                yield {"start": False, "end": False}, audio_chunk  # 静音 #
        else:  # 正在说话 #
            self.current_speech.append(audio_chunk)  # 累积音频 #
            self.speech_frames += len(audio_chunk)
            
            if self._detect_speech_end(audio_chunk):  # 检测结束 #
                self.is_speaking = False
                # 添加后填充 #
                if self.speech_pad_frames > 0:
                    padding = np.zeros(self.speech_pad_frames, dtype=audio_chunk.dtype)
                    self.current_speech.append(padding)
                
                combined = np.concatenate(self.current_speech)  # 拼接 #
                yield {"start": False, "end": True}, combined  # 结束事件 #
                self.current_speech = []
            else:
                yield {"start": False, "end": False}, audio_chunk  # 继续说话 #

    def _detect_speech_start(self, audio_chunk: np.ndarray) -> bool:
        """检测语音开始 # 一行说明 #"""
        # 简单能量检测，可替换为 Silero VAD #
        energy = np.mean(audio_chunk ** 2)
        return energy > 0.01  # 能量阈值 #

    def _detect_speech_end(self, audio_chunk: np.ndarray) -> bool:
        """检测语音结束 # 一行说明 #"""
        # 连续静音检测 #
        energy = np.mean(audio_chunk ** 2)
        if energy < 0.005:  # 静音阈值 #
            self.silence_frames += len(audio_chunk)
        else:
            self.silence_frames = 0
        
        # 静音超过阈值认为结束 #
        silence_threshold = 0.5 * self.sample_rate  # 0.5秒 #
        return self.silence_frames > silence_threshold
