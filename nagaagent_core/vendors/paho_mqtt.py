#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paho-mqtt 统一入口（import nagaagent_core.vendors.paho_mqtt as mqtt）"""

import paho.mqtt.client as client  # 客户端
import paho.mqtt as _mqtt  # 顶层命名空间
from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion

# 简单导出常用符号
Client = client.Client  # noqa: N816
__all__ = ["Client", "client", "_mqtt", "CallbackAPIVersion", "MQTTProtocolVersion"]


