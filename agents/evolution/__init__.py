"""Self-evolution subsystem for Embla System."""

from .acl_checker import PromptACLChecker, PromptPermission
from .self_tools import read_my_prompt, list_my_prompts
from .prompt_mutator import update_my_prompt, PromptUpdateResult
from .tool_creator import register_new_tool, ToolRegistrationResult
from .pattern_detector import PatternDetector, EvolutionTriggerSignal
from .evolution_trigger import EvolutionTrigger, EvolutionDecision

__all__ = [
    "PromptACLChecker",
    "PromptPermission",
    "read_my_prompt",
    "list_my_prompts",
    "update_my_prompt",
    "PromptUpdateResult",
    "register_new_tool",
    "ToolRegistrationResult",
    "PatternDetector",
    "EvolutionTriggerSignal",
    "EvolutionTrigger",
    "EvolutionDecision",
]
