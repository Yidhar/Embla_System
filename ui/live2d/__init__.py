#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D集成模块
独立于外部Live2D-Virtual-Girlfriend项目的Live2D功能实现
"""

from .renderer import Live2DRenderer
from .animator import Live2DAnimator
from .widget import Live2DWidget

__all__ = ['Live2DRenderer', 'Live2DAnimator', 'Live2DWidget']
