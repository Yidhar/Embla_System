import os
from . import chat
from system.config import config, logger

class GameTool():
    def __init__(self, window):
        self.window = window
        self.self_game_enabled = False

    def toggle_self_game(self):
        """切换博弈论流程开关"""
        self.self_game_enabled = not self.self_game_enabled
        status = '启用' if self.self_game_enabled else '禁用'
        chat.add_user_message("系统", f"● 博弈论流程已{status}")

from ..utils.lazy import lazy
@lazy
def game():
    return GameTool(config.window)