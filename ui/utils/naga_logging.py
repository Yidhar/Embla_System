
import logging
from ..controller.tool_chat import chat
from system.config import config
# 设置日志

class NagaLogging:
    def __init__(self, name):
        self.logger = logging.getLogger(name)
        
    def append(self):
        
        if config.window != None:
            chat.append_log(self.logger.handlers[0].stream)

    def debug(self, message, show=True):
        self.logger.debug(message)
        if show:
            self.append()

    def info(self, message, show=True):
        self.logger.info(message)
        if show:
            self.append()

    def warning(self, message, show=True):
        self.logger.warning(message)
        if show:
            self.append()

    def error(self, message, show=True):
        self.logger.error(message)
        if show:
            self.append()
        
loggers = dict()
def getLogger(self, name):
    if name not in loggers:
        loggers[name] = NagaLogging(name)
    return loggers[name]