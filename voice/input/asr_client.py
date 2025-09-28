import os  # 系统 #
from typing import Optional  # 类型 #
import nagaagent_core.vendors.numpy as np  # 数值 #

from system.config import config  # 统一配置 #


def transcribe_wav_bytes(audio_bytes: bytes) -> Optional[str]:
    """使用本地 FunASR 进行转写，返回文本或None # 简单说明 #"""
    try:
        # 检查是否启用本地 FunASR #
        if config.asr.engine != "local_funasr":
            print("❌ 本地 FunASR 未启用，请在配置中设置 engine: 'local_funasr'")  # 提示 #
            return None
        
        # 导入 FunASR #
        try:
            from funasr import AutoModel  # 导入 #
            from funasr.utils.postprocess_utils import rich_transcription_postprocess  # 后处理 #
        except ImportError:
            print("❌ 未安装 FunASR，请运行: pip install funasr")  # 依赖提示 #
            return None
        
        # 检查模型路径 #
        model_path = getattr(config.asr, 'local_model_path', None)  # 本地模型路径 #
        if not model_path or not os.path.exists(model_path):
            print("❌ 本地 FunASR 模型路径不存在，请检查配置")  # 路径提示 #
            return None
        
        # 加载模型 #
        try:
            asr_model = AutoModel(
                model=model_path,
                disable_update=True,
                device="cpu"  # 默认使用 CPU #
            )
        except Exception as e:
            print(f"❌ 加载 FunASR 模型失败: {e}")  # 加载失败 #
            return None
        
        # 转写音频 #
        from io import BytesIO  # 内存流 #
        audio_data = BytesIO(audio_bytes)  # 转换为流 #
        
        result = asr_model.generate(
            input=audio_data,
            cache={},
            language="zh",  # 默认中文 #
            ban_emo_unk=True,
            use_itn=False,
            disable_pbar=True
        )
        
        # 后处理 #
        if result and len(result) > 0:
            text = str(rich_transcription_postprocess(result[0]["text"])).replace(" ", "")  # 清理 #
            return text if text else None  # 返回 #
        
        return None  # 无结果 #
        
    except Exception as e:
        print(f"❌ FunASR 转写失败: {e}")  # 异常处理 #
        return None


