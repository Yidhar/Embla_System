"""NagaAgent core proxy for markdown"""  #
import markdown as _md  #
from markdown import *  # noqa #

__all__ = getattr(_md, "__all__", [])  #
