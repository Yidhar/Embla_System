import threading  # 线程 #
import time  # 时间 #
from typing import Callable, Optional, List  # 类型 #

import nagaagent_core.vendors.numpy as np  # 数值 #
import sounddevice as sd  # 录音 #
import soundfile as sf  # 写wav #
from nagaagent_core.vendors.scipy.signal import resample  # 重采样 #
import onnxruntime as ort  # VAD推理 #
import io  # 内存流 #

from system.config import config  # 统一配置 #

try:
    import noisereduce as nr  # 降噪 #
except Exception:
    nr = None  # 缺失时禁用降噪 #


class VADWorker(threading.Thread):
    """麦克风采集+Silero VAD分段线程 # 一行说明 #"""

    def __init__(self, on_utterance: Callable[[bytes, float], None]):
        super().__init__(daemon=True)  # 守护线程 #
        self.on_utterance = on_utterance  # 回调 #
        self._stop = threading.Event()  # 停止事件 #
        self.session = ort.InferenceSession(config.asr.vad_model_path)  # 加载VAD #

        self.sr_in = config.asr.sample_rate_in  # 输入采样率 #
        self.frame_ms = config.asr.frame_ms  # 帧长ms #
        self.frame_samples = int(self.sr_in * self.frame_ms / 1000)  # 帧样本数 #
        self.resample_to = config.asr.resample_to  # 目标采样率 #
        self.num_points = int(self.frame_samples * (self.resample_to / self.sr_in))  # 重采样点数 #

        self.vad_threshold = config.asr.vad_threshold  # 阈值 #
        self.max_silence_frames = int(config.asr.silence_ms / self.frame_ms)  # 静音帧阈值 #

    def stop(self):
        self._stop.set()  # 置位停止 #

    def run(self):
        devices = sd.query_devices()  # 设备查询 #
        stream = sd.InputStream(channels=1, dtype="float32", samplerate=self.sr_in, device=config.asr.device_index)  # 输入流 #
        state = False  # 是否在说话 #
        silence_cnt = 0  # 静音计数 #
        current_speech: List[np.ndarray] = []  # 片段缓存 #
        start_t = 0.0  # 开始时间 #

        with stream as s:  # 打开流 #
            while not self._stop.is_set():  # 循环 #
                samples, _ = s.read(self.frame_samples)  # 读一帧 #
                frame = samples[:, 0]  # 单通道 #
                if config.asr.noise_reduce and nr is not None:  # 是否降噪 #
                    try:
                        frame = nr.reduce_noise(y=frame, sr=self.sr_in)  # 降噪 #
                    except Exception:
                        pass  # 忽略 #

                resampled = resample(frame, self.num_points).astype(np.float32)  # 重采样 #

                audio_data = np.expand_dims(resampled, axis=0)  # 扩维 #
                state_in = np.zeros((2, 1, 128), dtype=np.float32)  # 状态 #
                sr_in = np.array(self.resample_to, dtype=np.int64)  # 采样率 #
                ort_inputs = {"input": audio_data, "state": state_in, "sr": sr_in}  # onnx输入 #
                vad_prob = self.session.run(None, ort_inputs)[0]  # 推理 #
                speaking = bool(vad_prob > self.vad_threshold)  # 判定 #

                if speaking:  # 检测到语音 #
                    if not state:
                        start_t = time.time()  # 起始时间 #
                    state = True
                    silence_cnt = 0
                    current_speech.append(resampled)  # 累积 #
                else:
                    if state:
                        silence_cnt += 1
                        if silence_cnt > self.max_silence_frames:  # 结束 #
                            state = False
                            silence_cnt = 0
                            if len(current_speech) > 0:
                                utt = np.concatenate(current_speech)  # 拼接 #
                                current_speech = []
                                wav_bytes = self._to_wav_bytes(utt, self.resample_to)  # 转WAV #
                                self.on_utterance(wav_bytes, time.time() - start_t)  # 回调 #

    @staticmethod
    def _to_wav_bytes(samples: np.ndarray, sr: int) -> bytes:
        buf = io.BytesIO()  # 缓冲 #
        sf.write(buf, samples, sr, format='WAV')  # 写wav #
        return buf.getvalue()  # 返回字节 #


