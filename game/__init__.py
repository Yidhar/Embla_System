"""
NagaAgent Game - 多智能体博弈系统

专注于通过结构化协作和基于Philoss的创新性评估来解决LLM在多智能体协作中的问题
"""

from .core.models.data_models import (
    Agent,
    InteractionGraph, 
    GameResult,
    HiddenState,
    TextBlock,
    NoveltyScore,
    GeneratedRole,
    RoleGenerationRequest,
    PromptTemplate,
    ThinkingVector
)

from .core.interaction_graph.role_generator import RoleGenerator
from .core.interaction_graph.signal_router import SignalRouter
from .core.interaction_graph.dynamic_dispatcher import DynamicDispatcher
from .core.interaction_graph.distributor import Distributor
from .core.interaction_graph.prompt_generator import PromptGenerator

from .core.self_game.actor import GameActor
from .core.self_game.criticizer import GameCriticizer  
from .core.self_game.checker.philoss_checker import PhilossChecker
from .core.self_game.game_engine import GameEngine

from .naga_game_system import NagaGameSystem

__version__ = "1.0.0"
__author__ = "NagaAgent Team"

__all__ = [
    # Data Models
    'Agent',
    'InteractionGraph', 
    'GameResult',
    'HiddenState',
    'TextBlock',
    'NoveltyScore',
    'GeneratedRole',
    'RoleGenerationRequest', 
    'PromptTemplate',
    'ThinkingVector',
    
    # Interaction Graph Components
    'RoleGenerator',
    'SignalRouter', 
    'DynamicDispatcher',
    'Distributor',
    'PromptGenerator',
    
    # Self Game Components
    'GameActor',
    'GameCriticizer',
    'PhilossChecker',
    'GameEngine',
    
    # Main System
    'NagaGameSystem',
] 
 
 
 
 
 