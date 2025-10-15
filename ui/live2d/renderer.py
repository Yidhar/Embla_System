#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D渲染器（精简版）
负责Live2D模型的加载和渲染
"""

import os
import sys
import logging
import json
import glob
from typing import Optional, Callable, Dict, List, Any
from enum import Enum

logger = logging.getLogger("live2d.renderer")

# 尝试导入Live2D模块 - 避免与本地目录冲突
LIVE2D_AVAILABLE = False
live2d = None

# 保存当前路径
original_path = sys.path.copy()

# 临时移除当前目录和其父目录，确保导入系统包而非本地目录
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

paths_to_remove = [current_dir, parent_dir, grandparent_dir, '.', '']
temp_removed_paths = []

for path in paths_to_remove:
    if path in sys.path:
        sys.path.remove(path)
        temp_removed_paths.append(path)

try:
    # 清理已加载的模块
    modules_to_remove = [key for key in sys.modules.keys() if key.startswith('live2d')]
    for module_name in modules_to_remove:
        del sys.modules[module_name]

    # 现在导入系统的live2d包
    import live2d.v3 as live2d_v3
    live2d = live2d_v3
    LIVE2D_AVAILABLE = True
    logger.info("Live2D模块加载成功")

except ImportError as e:
    LIVE2D_AVAILABLE = False
    logger.warning(f"Live2D模块未安装: {e}")
    logger.info("请安装 live2d-py: pip install live2d-py")

finally:
    # 恢复原始路径
    for path in temp_removed_paths:
        if path not in sys.path:
            sys.path.append(path)


class RendererState(Enum):
    """渲染器状态"""
    UNINITIALIZED = "uninitialized"
    INITIALIZED = "initialized"
    MODEL_LOADED = "model_loaded"
    ERROR = "error"


class Live2DRenderer:
    """Live2D渲染器（精简版）"""

    def __init__(self, scale_factor: float = 1.0):
        """初始化渲染器"""
        self.model = None
        self.state = RendererState.UNINITIALIZED
        self.model_path = None
        self.width = 100
        self.height = 200
        self.scale_factor = scale_factor
        self.loaded_expressions = {}  # 初始化表情映射表

        # 加载emoji映射配置
        self.emoji_mapping = self._load_emoji_mapping()

        # 错误处理相关
        self._update_errors = 0
        self._draw_errors = 0
        self._max_errors_before_reset = 10

    def initialize(self) -> bool:
        """初始化Live2D"""
        if not LIVE2D_AVAILABLE:
            logger.error("Live2D模块不可用")
            self.state = RendererState.ERROR
            return False

        try:
            live2d.init()
            live2d.glewInit()
            self.state = RendererState.INITIALIZED
            logger.info("Live2D渲染器初始化成功")
            return True

        except Exception as e:
            logger.error(f"Live2D初始化失败: {e}")
            self.state = RendererState.ERROR
            return False

    def load_model(self, model_path: str, progress_callback: Optional[Callable[[float], None]] = None) -> bool:
        """加载Live2D模型"""
        if not LIVE2D_AVAILABLE or self.state == RendererState.UNINITIALIZED:
            logger.error("渲染器未初始化")
            return False

        model_path = os.path.normpath(model_path)
        if not os.path.exists(model_path):
            logger.error(f"模型文件不存在: {model_path}")
            return False

        try:
            if progress_callback:
                progress_callback(0.1)

            self.model = live2d.LAppModel()

            if progress_callback:
                progress_callback(0.3)

            self.model.LoadModelJson(model_path)

            if progress_callback:
                progress_callback(0.6)

            # 加载动作文件
            model_dir = os.path.dirname(model_path)
            self._load_motions(model_dir)

            # 加载表情文件
            self._load_expressions(model_dir)

            # 应用缩放
            scaled_width = int(self.width * self.scale_factor)
            scaled_height = int(self.height * self.scale_factor)
            self.model.Resize(scaled_width, scaled_height)

            # 基本设置
            self.model.SetAutoBlinkEnable(False)
            self.model.SetAutoBreathEnable(True)

            # 尝试关闭水印
            try:
                self.model.SetParameterValue("ParamWatermarkOFF", 1.0)
            except:
                pass

            if progress_callback:
                progress_callback(1.0)

            self.model_path = model_path
            self.state = RendererState.MODEL_LOADED
            logger.info(f"模型加载成功: {model_path}")
            return True

        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            self.model = None
            self.state = RendererState.INITIALIZED
            return False

    def _load_motions(self, model_dir: str):
        """加载动作文件"""
        motion_dir = os.path.join(model_dir, "Motions")
        if not os.path.exists(motion_dir):
            return

        motion_files = glob.glob(os.path.join(motion_dir, "*.motion3.json"))
        for motion_file in motion_files:
            try:
                motion_name = os.path.basename(motion_file).replace(".motion3.json", "")
                # 尝试注册动作到模型
                # 注意：live2d-py可能需要通过model3.json配置来加载动作
                logger.debug(f"发现动作文件: {motion_name} - {motion_file}")
            except Exception as e:
                logger.debug(f"动作文件处理失败 {motion_file}: {e}")

    def _load_expressions(self, model_dir: str):
        """加载表情文件 - 增强版，自动扫描目录"""
        expression_dir = os.path.join(model_dir, "Expressions")
        if not os.path.exists(expression_dir):
            return

        # 记录加载的表情
        self.loaded_expressions = {}  # 原始名称 -> 加载名称的映射

        # 扫描目录中的所有表情文件
        expression_files = glob.glob(os.path.join(expression_dir, "*.exp3.json"))
        logger.info(f"在 {expression_dir} 找到 {len(expression_files)} 个表情文件")

        for exp_file in expression_files:
            try:
                # 获取表情名称（不含扩展名）- 保持原始名称
                exp_name = os.path.basename(exp_file).replace(".exp3.json", "")

                # 尝试直接加载表情文件到模型，使用原始名称
                if hasattr(self.model, 'LoadExpression'):
                    self.model.LoadExpression(exp_name, exp_file)
                    self.loaded_expressions[exp_name] = exp_name
                    logger.info(f"加载表情: '{exp_name}' 从 {exp_file}")
            except Exception as e:
                logger.error(f"表情文件加载失败 {exp_file}: {e}")

        logger.info(f"成功加载 {len(self.loaded_expressions)} 个表情: {list(self.loaded_expressions.keys())}")

    def update(self):
        """更新模型状态 - 带错误恢复"""
        if not self.has_model():
            return

        try:
            self.model.Update()
            # 成功更新，重置错误计数
            self._update_errors = 0
        except Exception as e:
            self._update_errors += 1
            if self._update_errors < 3:
                # 前几次错误正常记录
                logger.error(f"模型更新失败: {e}")
            elif self._update_errors == 3:
                # 多次错误后降低日志级别
                logger.warning("模型更新持续失败，后续错误将静默处理")

            # 检查是否需要重置模型
            if self._update_errors >= self._max_errors_before_reset:
                logger.error("模型更新错误过多，尝试重置状态")
                self._reset_model_state()

    def draw(self):
        """绘制模型 - 带错误恢复"""
        if not self.has_model():
            return

        try:
            live2d.clearBuffer()
            self.model.Draw()
            # 成功绘制，重置错误计数
            self._draw_errors = 0
        except Exception as e:
            self._draw_errors += 1
            if self._draw_errors < 3:
                logger.error(f"模型绘制失败: {e}")
            elif self._draw_errors == 3:
                logger.warning("模型绘制持续失败，后续错误将静默处理")

            # 检查是否需要重置模型
            if self._draw_errors >= self._max_errors_before_reset:
                logger.error("模型绘制错误过多，尝试重置状态")
                self._reset_model_state()

    def _reset_model_state(self):
        """重置模型状态"""
        try:
            if self.model_path and self.state == RendererState.MODEL_LOADED:
                logger.info("正在重置模型状态...")
                # 保存当前路径
                path = self.model_path
                # 清理现有模型
                if self.model:
                    self.model = None
                # 重新加载模型
                self.load_model(path)
                # 重置错误计数
                self._update_errors = 0
                self._draw_errors = 0
                logger.info("模型状态重置完成")
        except Exception as e:
            logger.error(f"模型状态重置失败: {e}")
            self.state = RendererState.ERROR

    def resize(self, width: int, height: int):
        """调整模型大小"""
        if width <= 0 or height <= 0:
            return

        self.width = width
        self.height = height

        if self.has_model():
            try:
                scaled_width = int(width * self.scale_factor)
                scaled_height = int(height * self.scale_factor)
                self.model.Resize(scaled_width, scaled_height)
            except Exception as e:
                logger.error(f"调整大小失败: {e}")

    def set_scale_factor(self, scale_factor: float):
        """设置缩放因子"""
        if scale_factor <= 0:
            return

        self.scale_factor = scale_factor
        self.resize(self.width, self.height)

    def set_parameter(self, param_id: str, value: float, validate: bool = False):
        """设置模型参数 - 带错误保护"""
        if not self.has_model():
            return

        try:
            # 参数值范围限制
            value = max(-10.0, min(10.0, value))
            self.model.SetParameterValue(param_id, value)
        except Exception as e:
            # 静默处理参数设置错误，避免日志泛滥
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"设置参数失败 {param_id}: {e}")

    def get_parameter(self, param_id: str) -> float:
        """获取模型参数"""
        if not self.has_model():
            return 0.0

        try:
            return self.model.GetParameterValue(param_id)
        except:
            return 0.0

    def trigger_motion(self, group: str, index: int = 0, priority: int = 3):
        """触发动作"""
        if not self.has_model():
            return

        try:
            self.model.StartMotion(group, index, priority)
        except Exception as e:
            logger.debug(f"触发动作失败 {group}: {e}")

    def trigger_expression(self, expression_id: str):
        """触发表情"""
        if not self.has_model():
            logger.warning(f"无法触发表情 '{expression_id}': 模型未加载")
            return

        try:
            # 直接使用原始名称触发表情
            logger.info(f"正在触发表情: '{expression_id}'")
            self.model.SetExpression(expression_id)
            logger.info(f"表情 '{expression_id}' 触发成功")
        except Exception as e:
            logger.error(f"触发表情失败 '{expression_id}': {e}")
            # 打印所有已加载的表情供调试
            if hasattr(self, 'loaded_expressions'):
                logger.info(f"已加载的表情列表: {list(self.loaded_expressions.keys())}")

    def cleanup(self):
        """清理资源"""
        try:
            if self.model:
                self.model = None
                logger.info("模型资源已清理")

            self.state = RendererState.UNINITIALIZED
            self.model_path = None

        except Exception as e:
            logger.error(f"资源清理失败: {e}")

    def is_available(self) -> bool:
        """检查是否可用"""
        return LIVE2D_AVAILABLE and self.state != RendererState.UNINITIALIZED

    def has_model(self) -> bool:
        """检查是否已加载模型"""
        return self.model is not None and self.state == RendererState.MODEL_LOADED

    def get_error_reason(self) -> str:
        """获取错误原因"""
        if not LIVE2D_AVAILABLE:
            return "Live2D模块未安装"
        if self.state == RendererState.UNINITIALIZED:
            return "渲染器未初始化"
        if self.state == RendererState.ERROR:
            return "渲染器错误"
        if not self.has_model():
            return "模型未加载"
        return ""

    def _load_emoji_mapping(self) -> Dict[str, Any]:
        """加载emoji映射配置"""
        try:
            emoji_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emoji_mapping.json')
            if os.path.exists(emoji_file):
                with open(emoji_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.debug(f"Emoji映射文件不存在: {emoji_file}")
        except Exception as e:
            logger.debug(f"加载emoji映射失败: {e}")

        # 返回默认映射
        return {
            "motion_emoji_map": {"default": "🎭"},
            "expression_emoji_map": {"default": "😀"},
            "custom_model_emoji": {}
        }

    def get_model_info(self) -> dict:
        """获取模型信息"""
        return {
            'model_path': self.model_path,
            'width': self.width,
            'height': self.height,
            'scale_factor': self.scale_factor,
            'state': self.state.value,
            'model_loaded': self.has_model()
        }

    def _get_emoji_for_motion(self, motion_name: str) -> str:
        """获取动作对应的emoji"""
        # 获取当前模型的自定义映射
        model_name = os.path.basename(os.path.dirname(self.model_path)) if self.model_path else ""
        custom_mapping = self.emoji_mapping.get("custom_model_emoji", {}).get(model_name, {}).get("motions", {})

        # 优先使用模型特定的映射
        if motion_name in custom_mapping:
            return custom_mapping[motion_name]

        # 然后使用通用映射
        motion_map = self.emoji_mapping.get("motion_emoji_map", {})

        # 尝试完全匹配
        if motion_name in motion_map:
            return motion_map[motion_name]

        # 尝试部分匹配
        motion_lower = motion_name.lower()
        for key, emoji in motion_map.items():
            if key.lower() in motion_lower:
                return emoji

        # 返回默认图标
        return motion_map.get("default", "🎭")

    def _get_emoji_for_expression(self, exp_name: str) -> str:
        """获取表情对应的emoji"""
        # 获取当前模型的自定义映射
        model_name = os.path.basename(os.path.dirname(self.model_path)) if self.model_path else ""
        custom_mapping = self.emoji_mapping.get("custom_model_emoji", {}).get(model_name, {}).get("expressions", {})

        # 优先使用模型特定的映射
        if exp_name in custom_mapping:
            return custom_mapping[exp_name]

        # 然后使用通用映射
        exp_map = self.emoji_mapping.get("expression_emoji_map", {})

        # 尝试完全匹配
        if exp_name in exp_map:
            return exp_map[exp_name]

        # 尝试部分匹配
        exp_lower = exp_name.lower()
        for key, emoji in exp_map.items():
            if key.lower() in exp_lower:
                return emoji

        # 返回默认图标
        return exp_map.get("default", "😀")

    def detect_model_actions(self) -> Dict[str, List[Dict[str, str]]]:
        """从model3.json和目录扫描检测模型定义的动作和表情"""
        if not self.model_path:
            return {"motions": [], "expressions": []}

        result = {"motions": [], "expressions": []}
        model_dir = os.path.dirname(self.model_path)

        # 首先尝试从model3.json读取
        try:
            # 读取model3.json
            with open(self.model_path, 'r', encoding='utf-8') as f:
                model_config = json.load(f)

            # 解析Motions
            if "FileReferences" in model_config and "Motions" in model_config["FileReferences"]:
                motions_dict = model_config["FileReferences"]["Motions"]
                for motion_group, motion_list in motions_dict.items():
                    display_name = motion_group.replace("_", " ").title()

                    # 使用新的emoji获取方法
                    emoji = self._get_emoji_for_motion(motion_group)

                    result["motions"].append({
                        "name": motion_group,
                        "display": display_name,
                        "icon": emoji,
                        "group": motion_group
                    })

            # 解析Expressions - 从model3.json
            expressions_from_config = []
            if "FileReferences" in model_config and "Expressions" in model_config["FileReferences"]:
                expressions = model_config["FileReferences"]["Expressions"]
                for exp in expressions:
                    exp_name = exp.get("Name", "")
                    expressions_from_config.append(exp_name)

        except Exception as e:
            logger.debug(f"解析model3.json失败: {e}")

        # 然后扫描目录中的所有表情文件（补充model3.json中可能遗漏的）
        expression_dir = os.path.join(model_dir, "Expressions")
        if os.path.exists(expression_dir):
            expression_files = glob.glob(os.path.join(expression_dir, "*.exp3.json"))
            all_expressions = set()

            for exp_file in expression_files:
                exp_name = os.path.basename(exp_file).replace(".exp3.json", "")
                all_expressions.add(exp_name)

            # 为每个表情创建条目
            for exp_name in sorted(all_expressions):
                # 处理显示名称
                display_name = exp_name.replace("【", "").replace("】", " ").replace("_", " ")

                # 使用新的emoji获取方法
                emoji = self._get_emoji_for_expression(exp_name)

                result["expressions"].append({
                    "name": exp_name,
                    "display": display_name,
                    "icon": emoji
                })

        logger.info(f"从model3.json和目录扫描检测到动作: {len(result['motions'])}个, 表情: {len(result['expressions'])}个")
        return result
