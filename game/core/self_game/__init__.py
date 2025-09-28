"""
Self Game Module - 自博弈模块

实现 Actor-Criticizer-Checker 三组件协同的闭环优化机制:
- Actor: 功能生成组件,执行具体任务
- Criticizer: 批判优化组件,多维度评估和建议  
- PhilossChecker: 创新性评估组件,基于Qwen2.5-VL的新颖度评分
- GameEngine: 整合三组件的完整博弈流程
"""

from .actor import GameActor
from .criticizer import GameCriticizer
from .checker.philoss_checker import PhilossChecker
from .game_engine import GameEngine

__all__ = [
    'GameActor',
    'GameCriticizer', 
    'PhilossChecker',
    'GameEngine'
] 
 
 
 