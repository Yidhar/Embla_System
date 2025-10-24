#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D配置管理器
负责加载、验证和管理Live2D模块的所有配置参数
支持从主配置系统（system/config.py）读取配置
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger("live2d.config")


@dataclass
class ModelConfig:
    """模型配置"""
    default_model_path: str = "ui/live2d/live2d_models/kasane_teto/kasane_teto.model3.json"
    fallback_image_path: str = "ui/img/standby.png"
    auto_load_on_start: bool = True
    scale_factor: float = 1.0  # 模型缩放因子
    enable_mouse_wheel_zoom: bool = False  # 是否启用鼠标滚轮缩放
    min_scale: float = 0.5  # 最小缩放比例
    max_scale: float = 3.0  # 最大缩放比例


@dataclass
class PerformanceConfig:
    """性能配置"""
    target_fps: int = 120
    adaptive_fps: bool = True
    min_fps: int = 30
    max_fps: int = 144
    enable_canvas: bool = True
    canvas_opacity: float = 1.0


@dataclass
class InteractionConfig:
    """交互配置"""
    enable_eye_tracking: bool = True
    enable_click_interaction: bool = True


@dataclass
class AnimatorConfigData:
    """单个动画器配置"""
    enabled: bool = True
    weight: float = 1.0
    smooth_factor: float = 0.1
    use_smoothing: bool = True


@dataclass
class BlinkConfigData(AnimatorConfigData):
    """眨眼动画配置"""
    min_interval: float = 2.0
    max_interval: float = 4.0
    duration: float = 0.1


@dataclass
class EyeTrackingConfigData(AnimatorConfigData):
    """眼球追踪配置"""
    max_range_x: float = 1.0
    max_range_y: float = 1.0


@dataclass
class BodyAngleConfigData(AnimatorConfigData):
    """身体角度配置"""
    angle_range: float = 0.1
    speed: float = 0.3


@dataclass
class BreathConfigData(AnimatorConfigData):
    """呼吸动画配置"""
    speed: float = 1.0


@dataclass
class EmotionConfigData(AnimatorConfigData):
    """情绪动画配置"""
    transition_duration: float = 0.3
    default_emotion: str = "neutral"


class Live2DConfigManager:
    """Live2D配置管理器"""

    DEFAULT_CONFIG_PATH = "ui/live2d/live2d_config.json"

    def __init__(self, config_path: Optional[str] = None, use_main_config: bool = True):
        """
        初始化配置管理器

        参数:
            config_path: 配置文件路径，为None时使用默认路径
            use_main_config: 是否优先使用主配置系统（system/config.py）
        """
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.use_main_config = use_main_config
        self._config_data: Dict[str, Any] = {}
        self.module_enabled: bool = True

        # 配置对象
        self.model: Optional[ModelConfig] = None
        self.performance: Optional[PerformanceConfig] = None
        self.interaction: Optional[InteractionConfig] = None
        self.blink: Optional[BlinkConfigData] = None
        self.eye_tracking: Optional[EyeTrackingConfigData] = None
        self.body_angle: Optional[BodyAngleConfigData] = None
        self.breath: Optional[BreathConfigData] = None
        self.emotion: Optional[EmotionConfigData] = None

        # 加载配置
        self.load()

    def load(self) -> bool:
        """
        从文件加载配置（优先从主配置系统读取）

        返回:
            bool: 加载是否成功
        """
        # 先加载Live2D模块自己的配置文件（作为默认值）
        local_config_loaded = self._load_local_config()

        # 如果启用主配置优先，尝试从主配置读取并覆盖
        if self.use_main_config:
            main_config_loaded = self._load_from_main_config()
            if main_config_loaded:
                logger.debug("Live2D配置已从主配置系统加载")  # 改为DEBUG级别，减少启动时日志噪音
                return True

        # 如果主配置不可用或未启用，使用本地配置
        if local_config_loaded:
            logger.debug("Live2D配置已从本地配置文件加载")  # 改为DEBUG级别，减少启动时日志噪音
            return True

        # 都失败了，使用默认配置
        logger.warning("无法加载配置文件，使用默认配置")
        self._load_defaults()
        return False

    def _load_local_config(self) -> bool:
        """
        从本地配置文件加载

        返回:
            bool: 加载是否成功
        """
        try:
            # 查找配置文件
            config_file = self._find_config_file()

            if not config_file:
                return False

            # 读取JSON文件
            with open(config_file, 'r', encoding='utf-8') as f:
                self._config_data = json.load(f)

            # 解析配置
            self._parse_config()

            logger.debug(f"本地配置文件加载成功: {config_file}")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"配置文件JSON格式错误: {e}")
            return False
        except Exception as e:
            logger.error(f"本地配置加载失败: {type(e).__name__}: {e}")
            return False

    def _load_from_main_config(self) -> bool:
        """
        从主配置系统（system/config.py）加载配置

        返回:
            bool: 加载是否成功
        """
        try:
            # 尝试导入主配置
            from system.config import config as main_config

            if not hasattr(main_config, 'live2d'):
                logger.debug("主配置中不包含live2d配置")
                return False

            live2d_config = main_config.live2d

            # 映射主配置到Live2D配置
            # 模型配置
            if self.model is None:
                self.model = ModelConfig()

            if hasattr(live2d_config, 'model_path') and live2d_config.model_path:
                self.model.default_model_path = live2d_config.model_path
            if hasattr(live2d_config, 'fallback_image') and live2d_config.fallback_image:
                self.model.fallback_image_path = live2d_config.fallback_image
            if hasattr(live2d_config, 'auto_switch'):
                self.model.auto_load_on_start = live2d_config.auto_switch
            if hasattr(live2d_config, 'scale_factor'):
                self.model.scale_factor = float(live2d_config.scale_factor)
            if hasattr(live2d_config, 'enabled'):
                self.module_enabled = bool(live2d_config.enabled)
                if not self.module_enabled:
                    self.model.auto_load_on_start = False
                    if self.interaction:
                        self.interaction.enable_eye_tracking = False
                        self.interaction.enable_click_interaction = False
                    for animator in [self.blink, self.eye_tracking, self.body_angle, self.breath, self.emotion]:
                        if animator:
                            animator.enabled = False
            self._config_data['module_enabled'] = self.module_enabled

            # 交互配置
            if self.interaction is None:
                self.interaction = InteractionConfig()

            if hasattr(live2d_config, 'touch_interaction'):
                self.interaction.enable_click_interaction = live2d_config.touch_interaction
            if hasattr(live2d_config, 'animation_enabled'):
                # animation_enabled 映射到眼球追踪和其他动画
                if not live2d_config.animation_enabled:
                    # 如果禁用动画，禁用所有动画器
                    if self.blink:
                        self.blink.enabled = False
                    if self.eye_tracking:
                        self.eye_tracking.enabled = False
                    if self.body_angle:
                        self.body_angle.enabled = False
                    if self.breath:
                        self.breath.enabled = False

            logger.debug("成功从主配置系统加载Live2D配置")  # 改为DEBUG级别，减少启动时日志噪音
            return True

        except ImportError as e:
            logger.debug(f"无法导入主配置系统: {e}")
            return False
        except Exception as e:
            logger.warning(f"从主配置加载失败: {type(e).__name__}: {e}")
            return False

    def _find_config_file(self) -> Optional[str]:
        """
        查找配置文件

        返回:
            Optional[str]: 配置文件的绝对路径，未找到返回None
        """
        # 尝试直接路径
        if os.path.isabs(self.config_path):
            if os.path.exists(self.config_path):
                return self.config_path
        else:
            # 尝试相对于当前目录
            if os.path.exists(self.config_path):
                return os.path.abspath(self.config_path)

            # 尝试相对于脚本目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(script_dir, "live2d_config.json")
            if os.path.exists(config_file):
                return config_file

            # 尝试相对于项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
            config_file = os.path.join(project_root, self.config_path)
            if os.path.exists(config_file):
                return config_file

        return None

    def _parse_config(self):
        """解析配置数据到配置对象"""
        try:
            # 模型配置
            model_data = self._config_data.get('model', {})
            self.model = ModelConfig(**model_data)

            # 性能配置
            perf_data = self._config_data.get('performance', {})
            self.performance = PerformanceConfig(**perf_data)

            # 交互配置
            inter_data = self._config_data.get('interaction', {})
            self.interaction = InteractionConfig(**inter_data)

            # 动画器配置
            animators = self._config_data.get('animators', {})
            self.blink = BlinkConfigData(**animators.get('blink', {}))
            self.eye_tracking = EyeTrackingConfigData(**animators.get('eye_tracking', {}))
            self.body_angle = BodyAngleConfigData(**animators.get('body_angle', {}))
            self.breath = BreathConfigData(**animators.get('breath', {}))
            self.emotion = EmotionConfigData(**animators.get('emotion', {}))

            # 表情配置

            # 动作配置

            # 日志配置

            # 高级配置


            if 'module_enabled' in self._config_data:
                self.module_enabled = bool(self._config_data['module_enabled'])
                if not self.module_enabled and self.model:
                    self.model.auto_load_on_start = False
            else:
                self._config_data['module_enabled'] = self.module_enabled

            logger.debug("配置解析完成")

        except Exception as e:
            logger.error(f"配置解析失败: {type(e).__name__}: {e}")
            self._load_defaults()

    def _load_defaults(self):
        """加载默认配置"""
        self.module_enabled = True
        self._config_data['module_enabled'] = self.module_enabled
        self.model = ModelConfig()
        self.performance = PerformanceConfig()
        self.interaction = InteractionConfig()
        self.blink = BlinkConfigData()
        self.eye_tracking = EyeTrackingConfigData()
        self.body_angle = BodyAngleConfigData()
        self.breath = BreathConfigData()
        self.emotion = EmotionConfigData()

        logger.info("使用默认配置")

    def save(self, config_path: Optional[str] = None) -> bool:
        """
        保存配置到文件

        参数:
            config_path: 保存路径，为None时使用当前路径

        返回:
            bool: 保存是否成功
        """
        try:
            save_path = config_path or self.config_path

            self._config_data['module_enabled'] = self.module_enabled
            # 构建配置字典
            config_dict = {
                'module_enabled': self.module_enabled,
                'model': asdict(self.model) if self.model else {},
                'performance': asdict(self.performance) if self.performance else {},
                'interaction': asdict(self.interaction) if self.interaction else {},
                'animators': {
                    'blink': asdict(self.blink) if self.blink else {},
                    'eye_tracking': asdict(self.eye_tracking) if self.eye_tracking else {},
                    'body_angle': asdict(self.body_angle) if self.body_angle else {},
                    'breath': asdict(self.breath) if self.breath else {},
                    'emotion': asdict(self.emotion) if self.emotion else {}
                },
            }

            # 确保目录存在
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

            # 写入文件
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)

            logger.info(f"配置已保存到: {save_path}")
            return True

        except Exception as e:
            logger.error(f"配置保存失败: {type(e).__name__}: {e}")
            return False

    def get_animator_config(self, animator_name: str) -> Optional[AnimatorConfigData]:
        """
        获取指定动画器的配置

        参数:
            animator_name: 动画器名称（blink, eye_tracking, body_angle, breath, emotion）

        返回:
            Optional[AnimatorConfigData]: 配置对象，未找到返回None
        """
        animator_map = {
            'blink': self.blink,
            'eye_tracking': self.eye_tracking,
            'body_angle': self.body_angle,
            'breath': self.breath,
            'emotion': self.emotion
        }
        return animator_map.get(animator_name)

    def get_model_path(self, relative_to_project: bool = True) -> str:
        """
        获取模型路径

        参数:
            relative_to_project: 是否相对于项目根目录

        返回:
            str: 模型路径
        """
        if not self.model:
            return ""

        path = self.model.default_model_path

        if relative_to_project and not os.path.isabs(path):
            # 转换为绝对路径
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(script_dir))
            path = os.path.join(project_root, path)

        return path

    def validate(self) -> bool:
        """
        验证配置有效性

        返回:
            bool: 配置是否有效
        """
        try:
            # 验证性能配置
            if self.performance:
                assert 1 <= self.performance.target_fps <= 240, "target_fps必须在1-240之间"
                assert self.performance.min_fps <= self.performance.target_fps <= self.performance.max_fps, "FPS范围设置错误"
                assert 0.0 <= self.performance.canvas_opacity <= 1.0, "canvas_opacity必须在0-1之间"

            # 验证动画器权重
            for animator_name in ['blink', 'eye_tracking', 'body_angle', 'breath', 'emotion']:
                animator = self.get_animator_config(animator_name)
                if animator:
                    assert 0.0 <= animator.weight <= 2.0, f"{animator_name}的weight必须在0-2之间"
                    assert 0.0 <= animator.smooth_factor <= 1.0, f"{animator_name}的smooth_factor必须在0-1之间"

            # 验证眨眼间隔
            if self.blink:
                assert 0.1 <= self.blink.min_interval <= self.blink.max_interval, "眨眼间隔设置错误"
                assert 0.01 <= self.blink.duration <= 1.0, "眨眼持续时间必须在0.01-1秒之间"

            logger.info("配置验证通过")
            return True

        except AssertionError as e:
            logger.error(f"配置验证失败: {e}")
            return False
        except Exception as e:
            logger.error(f"配置验证异常: {type(e).__name__}: {e}")
            return False

    def to_dict(self) -> Dict[str, Any]:
        """
        将配置转换为字典

        返回:
            Dict[str, Any]: 配置字典
        """
        result = self._config_data.copy()
        result['module_enabled'] = self.module_enabled
        return result

    def is_enabled(self) -> bool:
        """返回Live2D模块是否启用"""
        return self.module_enabled

    def update_from_dict(self, config_dict: Dict[str, Any]):
        """
        从字典更新配置

        参数:
            config_dict: 配置字典
        """
        self._config_data.update(config_dict)
        self._parse_config()
        logger.info("配置已从字典更新")


# 全局配置实例
_global_config: Optional[Live2DConfigManager] = None


def get_config(config_path: Optional[str] = None) -> Live2DConfigManager:
    """
    获取全局配置实例（单例模式）

    参数:
        config_path: 配置文件路径

    返回:
        Live2DConfigManager: 配置管理器实例
    """
    global _global_config

    if _global_config is None:
        _global_config = Live2DConfigManager(config_path)

    return _global_config


def reload_config(config_path: Optional[str] = None) -> Live2DConfigManager:
    """
    重新加载配置（强制刷新）

    参数:
        config_path: 配置文件路径

    返回:
        Live2DConfigManager: 新的配置管理器实例
    """
    global _global_config
    _global_config = Live2DConfigManager(config_path)
    return _global_config
