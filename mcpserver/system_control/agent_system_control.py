from agents import Agent
from system.config import config  # 统一变量管理 #
import asyncio
import json
try:
    import screen_brightness_control as sbc  # 屏幕亮度调节 #
except ImportError:
    sbc = None
try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    import comtypes  # COM组件初始化 #
except ImportError:
    AudioUtilities = None

class SystemControlAgent(Agent):
    """系统控制Agent #"""
    name = "SystemControlAgent"  # Agent名称 #
    instructions = "系统控制：定时关机、定时重启、亮度、音量调节"  # 角色描述 #
    def __init__(self):
        super().__init__(
            name=self.name,
            instructions=self.instructions,
            tools=[],
            model=config.api.model
        )
        self._shutdown_pending = False  # 关机待确认状态 #
        self._shutdown_time = 0  # 待确认的关机时间 #

    async def handle_handoff(self, data: dict) -> str:
        # 使用tool_name参数，与LLM生成的工具调用格式匹配
        action = data.get("tool_name")
        if not action:
            return json.dumps({"status": "error", "message": "缺少tool_name参数", "data": {}}, ensure_ascii=False)
            
        if action == "定时关机":
            time_sec = int(data.get("time", 0))
            import keyboard
            import threading
            import time as time_module
            
            # 键盘监听确认
            result = {"confirmed": None, "key_pressed": None}
            
            def on_key_press(event):
                if event.name.lower() in ['y', 'n']:
                    result["key_pressed"] = event.name.lower()
                    result["confirmed"] = (event.name.lower() == 'y')
                    keyboard.unhook_all()  # 停止监听
            
            # 开始监听键盘
            keyboard.on_press(on_key_press)
            
            time_str = f"{time_sec}秒后" if time_sec > 0 else "立即"
            print(f"【系统控制】请在10秒内按 y 键（确认关机）或 n 键（取消），否则自动取消。")
            print(f"确认要{time_str}关机吗？(按y/n键): ")
            
            # 等待10秒或按键
            start_time = time_module.time()
            while time_module.time() - start_time < 10:
                if result["key_pressed"] is not None:
                    break
                time_module.sleep(0.1)
            
            # 停止监听
            keyboard.unhook_all()
            
            if result["key_pressed"] is None:
                return json.dumps({"status": "cancelled", "message": "10秒未按键，关机已自动取消", "data": {}}, ensure_ascii=False)
            
            if result["confirmed"]:
                import os
                os.system(f"shutdown /s /t {time_sec}")
                return json.dumps({"status": "success", "message": f"关机已确认，{time_sec}秒后关机", "data": {}}, ensure_ascii=False)
            else:
                return json.dumps({"status": "cancelled", "message": "关机已取消", "data": {}}, ensure_ascii=False)
        elif action == "定时重启":
            time_sec = int(data.get("time", 0))
            import keyboard
            import threading
            import time as time_module
            
            # 键盘监听确认
            result = {"confirmed": None, "key_pressed": None}
            
            def on_key_press(event):
                if event.name.lower() in ['y', 'n']:
                    result["key_pressed"] = event.name.lower()
                    result["confirmed"] = (event.name.lower() == 'y')
                    keyboard.unhook_all()  # 停止监听
            
            # 开始监听键盘
            keyboard.on_press(on_key_press)
            
            time_str = f"{time_sec}秒后" if time_sec > 0 else "立即"
            print(f"【系统控制】请在10秒内按 y 键（确认重启）或 n 键（取消），否则自动取消。")
            print(f"确认要{time_str}重启吗？(按y/n键): ")
            
            # 等待10秒或按键
            start_time = time_module.time()
            while time_module.time() - start_time < 10:
                if result["key_pressed"] is not None:
                    break
                time_module.sleep(0.1)
            
            # 停止监听
            keyboard.unhook_all()
            
            if result["key_pressed"] is None:
                return json.dumps({"status": "cancelled", "message": "10秒未按键，重启已自动取消", "data": {}}, ensure_ascii=False)
            
            if result["confirmed"]:
                import os
                os.system(f"shutdown /r /t {time_sec}")
                return json.dumps({"status": "success", "message": f"重启已确认，{time_sec}秒后重启", "data": {}}, ensure_ascii=False)
            else:
                return json.dumps({"status": "cancelled", "message": "重启已取消", "data": {}}, ensure_ascii=False)
        elif action == "设置亮度":
            value = int(data.get("value", 50))
            if sbc:
                sbc.set_brightness(value)
                return json.dumps({"status": "success", "message": f"亮度已设置为{value}", "data": {"brightness": value}}, ensure_ascii=False)
            else:
                return json.dumps({"status": "error", "message": "未安装screen_brightness_control库，无法调节亮度", "data": {}}, ensure_ascii=False)
        elif action == "设置音量":
            value = int(data.get("value", 50))
            if AudioUtilities:
                try:
                    comtypes.CoInitialize()  # 初始化COM组件 #
                    devices = AudioUtilities.GetSpeakers()
                    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                    volume.SetMasterVolumeLevelScalar(value/100, None)
                    return json.dumps({"status": "success", "message": f"音量已设置为{value}", "data": {"volume": value}}, ensure_ascii=False)
                except Exception as e:
                    return json.dumps({"status": "error", "message": f"音量设置失败: {e}", "data": {}}, ensure_ascii=False)
                finally:
                    comtypes.CoUninitialize()  # 清理COM组件 #
            else:
                return json.dumps({"status": "error", "message": "未安装pycaw库，无法调节音量", "data": {}}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "message": f"未知操作: {action}", "data": {}}, ensure_ascii=False)

# 工厂函数，用于动态注册系统创建实例
def create_system_control_agent():
    """创建SystemControlAgent实例的工厂函数"""
    return SystemControlAgent() 