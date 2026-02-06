"""NagaAgent core proxy for playwright"""  #
import playwright as _pw  #
from playwright import *  # noqa #

__all__ = getattr(_pw, "__all__", [])  #

