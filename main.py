# 标准库导入
import asyncio
import logging
import os
import socket
import sys
import threading
import time
import warnings

# 过滤弃用警告，提升启动体验
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*websockets.legacy.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*WebSocketServerProtocol.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*websockets.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*uvicorn.*")

# 修复Windows socket兼容性问题
if not hasattr(socket, 'EAI_ADDRFAMILY'):
    # Windows系统缺少这些错误码，添加兼容性常量
    socket.EAI_ADDRFAMILY = -9
    socket.EAI_AGAIN = -3
    socket.EAI_BADFLAGS = -1
    socket.EAI_FAIL = -4
    socket.EAI_MEMORY = -10
    socket.EAI_NODATA = -5
    socket.EAI_NONAME = -2
    socket.EAI_OVERFLOW = -12
    socket.EAI_SERVICE = -8
    socket.EAI_SOCKTYPE = -7
    socket.EAI_SYSTEM = -11

# 第三方库导入
# 优先使用仓库内的本地包，防止导入到系统已安装的旧版 nagaagent_core #
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))  # 统一入口 #
LOCAL_PKG_DIR = os.path.join(REPO_ROOT, "nagaagent-core")  # 统一入口 #
if LOCAL_PKG_DIR not in sys.path:
    sys.path.insert(0, LOCAL_PKG_DIR)  # 优先使用本地包 #

from nagaagent_core.vendors.PyQt5.QtGui import QIcon  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtWidgets import QApplication  # 统一入口 #

# 本地模块导入
from system.system_checker import run_system_check, run_quick_check
from system.config import config, AI_NAME

# V14版本已移除早期拦截器，采用运行时猴子补丁

# conversation_core已删除，相关功能已迁移到apiserver
from summer_memory.memory_manager import memory_manager
from summer_memory.task_manager import start_task_manager, task_manager
from ui.pyqt_chat_window import ChatWindow
from ui.tray.console_tray import integrate_console_tray

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("summer_memory")
logger.setLevel(logging.INFO)

# 过滤HTTP相关日志
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# 服务管理器类
class ServiceManager:
    """服务管理器 - 统一管理所有后台服务"""
    
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.bg_thread = None
        self.api_thread = None
        self.agent_thread = None
        self.tts_thread = None
        self._services_ready = False  # 服务就绪状态
    
    def start_background_services(self):
        """启动后台服务 - 异步非阻塞"""
        logger.info("正在启动后台服务...")
        
        # 启动后台任务管理器
        self.bg_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.bg_thread.start()
        logger.info(f"后台服务线程已启动: {self.bg_thread.name}")
        
        # 移除阻塞等待，改为异步检查
        # time.sleep(1)  # 删除阻塞等待
    
    def _run_event_loop(self):
        """运行事件循环"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._init_background_services())
        logger.info("后台服务事件循环已启动")
    
    async def _init_background_services(self):
        """初始化后台服务 - 优化启动流程"""
        logger.info("正在启动后台服务...")
        try:
            # 启动任务管理器
            await start_task_manager()
            
            # 标记服务就绪
            self._services_ready = True
            logger.info(f"任务管理器状态: running={task_manager.is_running}")
            
            # 保持事件循环活跃
            while True:
                await asyncio.sleep(3600)  # 每小时检查一次
        except Exception as e:
            logger.error(f"后台服务异常: {e}")
    
    def check_port_available(self, host, port):
        """检查端口是否可用"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return True
        except OSError:
            return False
    
    def start_all_servers(self):
        """并行启动所有服务：API(可选)、MCP、Agent、TTS - 优化版本"""
        print("🚀 正在并行启动所有服务...")
        print("=" * 50)
        threads = []
        service_status = {}  # 服务状态跟踪
        
        try:
            # 预检查所有端口，减少重复检查
            port_checks = {
                'api': config.api_server.enabled and config.api_server.auto_start and 
                      self.check_port_available(config.api_server.host, config.api_server.port),
                'mcp': self.check_port_available("0.0.0.0", 8003),
                'agent': self.check_port_available("0.0.0.0", 8001),
                'tts': self.check_port_available("0.0.0.0", config.tts.port)
            }
            
            # API服务器（可选）
            if port_checks['api']:
                api_thread = threading.Thread(target=self._start_api_server, daemon=True)
                threads.append(("API", api_thread))
                service_status['API'] = "准备启动"
            elif config.api_server.enabled and config.api_server.auto_start:
                print(f"⚠️  API服务器: 端口 {config.api_server.port} 已被占用，跳过启动")
                service_status['API'] = "端口占用"
            
            # MCP服务器
            if port_checks['mcp']:
                mcp_thread = threading.Thread(target=self._start_mcp_server, daemon=True)
                threads.append(("MCP", mcp_thread))
                service_status['MCP'] = "准备启动"
            else:
                print(f"⚠️  MCP服务器: 端口 8003 已被占用，跳过启动")
                service_status['MCP'] = "端口占用"
            
            # Agent服务器
            if port_checks['agent']:
                agent_thread = threading.Thread(target=self._start_agent_server, daemon=True)
                threads.append(("Agent", agent_thread))
                service_status['Agent'] = "准备启动"
            else:
                print(f"⚠️  Agent服务器: 端口 8001 已被占用，跳过启动")
                service_status['Agent'] = "端口占用"
            
            # TTS服务器
            if port_checks['tts']:
                tts_thread = threading.Thread(target=self._start_tts_server, daemon=True)
                threads.append(("TTS", tts_thread))
                service_status['TTS'] = "准备启动"
            else:
                print(f"⚠️  TTS服务器: 端口 {config.tts.port} 已被占用，跳过启动")
                service_status['TTS'] = "端口占用"
            
            # 显示服务启动计划
            print("\n📋 服务启动计划:")
            for service, status in service_status.items():
                if status == "准备启动":
                    print(f"   🔄 {service}服务器: 正在启动...")
                else:
                    print(f"   ⚠️  {service}服务器: {status}")
            
            print("\n🚀 开始启动服务...")
            print("-" * 30)
            
            # 批量启动所有线程
            for name, thread in threads:
                thread.start()
                print(f"✅ {name}服务器: 启动线程已创建")
            
            print("-" * 30)
            print(f"🎉 服务启动完成: {len(threads)} 个服务正在后台运行")
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ 并行启动服务异常: {e}")
    
    def _start_api_server(self):
        """内部API服务器启动方法"""
        try:
            from nagaagent_core.api import uvicorn
            
            uvicorn.run(
                "apiserver.api_server:app",
                host=config.api_server.host,
                port=config.api_server.port,
                log_level="error",
                access_log=False,
                reload=False,
                ws_ping_interval=None,  # 禁用WebSocket ping
                ws_ping_timeout=None    # 禁用WebSocket ping超时
            )
        except ImportError as e:
            print(f"   ❌ API服务器依赖缺失: {e}")
        except Exception as e:
            print(f"   ❌ API服务器启动失败: {e}")
    
    def _start_mcp_server(self):
        """内部MCP服务器启动方法"""
        try:
            import uvicorn
            from mcpserver.mcp_server import app
            
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=8003,
                log_level="error",
                access_log=False,
                reload=False,
                ws_ping_interval=None,  # 禁用WebSocket ping
                ws_ping_timeout=None    # 禁用WebSocket ping超时
            )
        except Exception as e:
            print(f"   ❌ MCP服务器启动失败: {e}")
    
    def _start_agent_server(self):
        """内部Agent服务器启动方法"""
        try:
            import uvicorn
            from agentserver.agent_server import app
            
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=8001,
                log_level="error",
                access_log=False,
                reload=False,
                ws_ping_interval=None,  # 禁用WebSocket ping
                ws_ping_timeout=None    # 禁用WebSocket ping超时
            )
        except Exception as e:
            print(f"   ❌ Agent服务器启动失败: {e}")
    
    def _start_tts_server(self):
        """内部TTS服务器启动方法"""
        try:
            from voice.output.start_voice_service import start_http_server
            start_http_server()
        except Exception as e:
            print(f"   ❌ TTS服务器启动失败: {e}")
    
    def _start_naga_portal_auto_login(self):
        """启动NagaPortal自动登录（异步）"""
        try:
            # 检查是否配置了NagaPortal
            if not config.naga_portal.username or not config.naga_portal.password:
                return  # 静默跳过，不输出日志
            
            # 在新线程中异步执行登录
            def run_auto_login():
                try:
                    import sys
                    import os
                    # 添加项目根目录到Python路径
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    sys.path.insert(0, project_root)
                    
                    from mcpserver.agent_naga_portal.portal_login_manager import auto_login_naga_portal
                    
                    # 创建新的事件循环
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    try:
                        # 执行自动登录
                        result = loop.run_until_complete(auto_login_naga_portal())
                        
                        if result['success']:
                            # 登录成功，显示状态
                            print("✅ NagaPortal自动登录成功")
                            self._show_naga_portal_status()
                        else:
                            # 登录失败，显示错误
                            error_msg = result.get('message', '未知错误')
                            print(f"❌ NagaPortal自动登录失败: {error_msg}")
                            self._show_naga_portal_status()
                    finally:
                        loop.close()
                        
                except Exception as e:
                    # 登录异常，显示错误
                    print(f"❌ NagaPortal自动登录异常: {e}")
                    self._show_naga_portal_status()
            
            # 启动后台线程
            import threading
            login_thread = threading.Thread(target=run_auto_login, daemon=True)
            login_thread.start()
            
        except Exception as e:
            # 启动异常，显示错误
            print(f"❌ NagaPortal自动登录启动失败: {e}")
            self._show_naga_portal_status()

    def _show_naga_portal_status(self):
        """显示NagaPortal状态（登录完成后调用）"""
        try:
            from mcpserver.agent_naga_portal.portal_login_manager import get_portal_login_manager
            login_manager = get_portal_login_manager()
            status = login_manager.get_status()
            cookies = login_manager.get_cookies()
            
            print(f"🌐 NagaPortal状态:")
            print(f"   地址: {config.naga_portal.portal_url}")
            print(f"   用户: {config.naga_portal.username[:3]}***{config.naga_portal.username[-3:] if len(config.naga_portal.username) > 6 else '***'}")
            
            if cookies:
                print(f"🍪 Cookie信息 ({len(cookies)}个):")
                for name, value in cookies.items():
                    print(f"   {name}: {value}")
            else:
                print(f"🍪 Cookie: 未获取到")
            
            user_id = status.get('user_id')
            if user_id:
                print(f"👤 用户ID: {user_id}")
            else:
                print(f"👤 用户ID: 未获取到")
                
            # 显示登录状态
            if status.get('is_logged_in'):
                print(f"✅ 登录状态: 已登录")
            else:
                print(f"❌ 登录状态: 未登录")
                if status.get('login_error'):
                    print(f"   错误: {status.get('login_error')}")
                    
        except Exception as e:
            print(f"🍪 NagaPortal状态获取失败: {e}")
    
    def _start_mqtt_status_check(self):
        """启动物联网通讯连接并显示状态（异步）"""
        try:
            # 检查是否配置了物联网通讯
            if not config.mqtt.enabled:
                return  # 静默跳过，不输出日志
            
            # 在新线程中异步执行物联网通讯连接
            def run_mqtt_connection():
                try:
                    import sys
                    import os
                    import time
                    # 添加项目根目录到Python路径
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    sys.path.insert(0, project_root)
                    
                    try:
                        from mqtt_tool.device_switch import device_manager
                        
                        # 尝试连接物联网设备
                        if hasattr(device_manager, 'connect'):
                            success = device_manager.connect()
                            if success:
                                print("🔗 物联网通讯状态: 已连接")
                            else:
                                print("⚠️ 物联网通讯状态: 连接失败（将在使用时重试）")
                        else:
                            print("❌ 物联网通讯功能不可用")
                            
                    except Exception as e:
                        print(f"⚠️ 物联网通讯连接失败: {e}")
                        
                except Exception as e:
                    print(f"❌ 物联网通讯连接异常: {e}")
            
            # 启动后台线程
            import threading
            mqtt_thread = threading.Thread(target=run_mqtt_connection, daemon=True)
            mqtt_thread.start()
            
        except Exception as e:
            print(f"❌ 物联网通讯连接启动失败: {e}")
    
    def _load_persistent_context(self):
        """从日志文件加载历史对话上下文"""
        if not config.api.context_parse_logs:
            return
            
        try:
            from apiserver.message_manager import message_manager
            
            # 计算最大消息数量
            max_messages = config.api.max_history_rounds * 2
            
            # 加载历史对话
            recent_messages = message_manager.load_recent_context(
                days=config.api.context_load_days,
                max_messages=max_messages
            )
            
            if recent_messages:
                logger.info(f"✅ 从日志文件加载了 {len(recent_messages)} 条历史对话")
                
                # 显示统计信息
                try:
                    from apiserver.message_manager import parser
                    stats = parser.get_context_statistics(config.api.context_load_days)
                    logger.info(f"📊 上下文统计: {stats['total_files']}个文件, {stats['total_messages']}条消息")
                except ImportError:
                    logger.info("📊 上下文统计: 日志解析器不可用")
            else:
                logger.info("📝 未找到历史对话记录，将开始新的对话")
                
        except ImportError:
            logger.warning("⚠️ 日志解析器模块未找到，跳过持久化上下文加载")
        except Exception as e:
            logger.error(f"❌ 加载持久化上下文失败: {e}")
            # 失败时不影响正常使用，继续使用空上下文
    
    def _init_voice_system(self):
        """初始化语音处理系统"""
        try:
            if config.system.voice_enabled:
                logger.info("语音功能已启用（语音输入+输出），由UI层管理")
            else:
                logger.info("语音功能已禁用")
        except Exception as e:
            logger.warning(f"语音系统初始化失败: {e}")
    
    def _init_memory_system(self):
        """初始化记忆系统"""
        try:
            if memory_manager and memory_manager.enabled:
                logger.info("夏园记忆系统已初始化")
            else:
                logger.info("夏园记忆系统已禁用")
        except Exception as e:
            logger.warning(f"记忆系统初始化失败: {e}")
    
    def _init_mcp_services(self):
        """初始化MCP服务系统"""
        try:
            # MCP服务现在由mcpserver独立管理，这里只需要记录日志
            logger.info("MCP服务系统由mcpserver独立管理")
        except Exception as e:
            logger.error(f"MCP服务系统初始化失败: {e}")
    
    
    def show_naga_portal_status(self):
        """显示NagaPortal配置状态（手动调用）"""
        try:
            if config.naga_portal.username and config.naga_portal.password:
                print(f"🌐 NagaPortal: 已配置账户信息")
                print(f"   地址: {config.naga_portal.portal_url}")
                print(f"   用户: {config.naga_portal.username[:3]}***{config.naga_portal.username[-3:] if len(config.naga_portal.username) > 6 else '***'}")
                
                # 获取并显示Cookie信息
                try:
                    from mcpserver.agent_naga_portal.portal_login_manager import get_portal_login_manager
                    login_manager = get_portal_login_manager()
                    status = login_manager.get_status()
                    cookies = login_manager.get_cookies()
                    
                    if cookies:
                        print(f"🍪 Cookie信息 ({len(cookies)}个):")
                        for name, value in cookies.items():
                            # 显示完整的cookie名称和值
                            print(f"   {name}: {value}")
                    else:
                        print(f"🍪 Cookie: 未获取到")
                    
                    user_id = status.get('user_id')
                    if user_id:
                        print(f"👤 用户ID: {user_id}")
                    else:
                        print(f"👤 用户ID: 未获取到")
                        
                    # 显示登录状态
                    if status.get('is_logged_in'):
                        print(f"✅ 登录状态: 已登录")
                    else:
                        print(f"❌ 登录状态: 未登录")
                        if status.get('login_error'):
                            print(f"   错误: {status.get('login_error')}")
                        
                except Exception as e:
                    print(f"🍪 状态获取失败: {e}")
            else:
                print(f"🌐 NagaPortal: 未配置账户信息")
                print(f"   如需使用NagaPortal功能，请在config.json中配置naga_portal.username和password")
        except Exception as e:
            print(f"🌐 NagaPortal: 配置检查失败 - {e}")

# 工具函数
def show_help():
    print('系统命令: 清屏, 查看索引, 帮助, 退出')

def show_index():
    print('主题分片索引已集成，无需单独索引查看')

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

# 延迟初始化 - 避免启动时阻塞
def _lazy_init_services():
    """延迟初始化服务 - 在需要时才初始化"""
    global service_manager, n
    if not hasattr(_lazy_init_services, '_initialized'):
        # 初始化服务管理器
        service_manager = ServiceManager()
        service_manager.start_background_services()
        
        # conversation_core已删除，相关功能已迁移到apiserver
        n = None
        
        # 初始化各个系统（conversation_core已删除，直接初始化服务）
        service_manager._init_mcp_services()
        service_manager._init_voice_system()
        service_manager._init_memory_system()
        service_manager._load_persistent_context()
        
        # 初始化进度文件
        with open('./ui/styles/progress.txt', 'w') as f:
            f.write('0')
        
        # 显示系统状态
        print("=" * 30)
        print(f"GRAG状态: {'启用' if memory_manager.enabled else '禁用'}")
        if memory_manager.enabled:
            stats = memory_manager.get_memory_stats()
            from summer_memory.quintuple_graph import graph, GRAG_ENABLED
            print(f"Neo4j连接: {'成功' if graph and GRAG_ENABLED else '失败'}")
        print("=" * 30)
        print(f'{AI_NAME}系统已启动')
        print("=" * 30)
        
        # 启动服务（并行异步）
        service_manager.start_all_servers()
        
        # 启动NagaPortal自动登录
        service_manager._start_naga_portal_auto_login()
        print("⏳ NagaPortal正在后台自动登录...")
        
        # 启动物联网通讯连接
        service_manager._start_mqtt_status_check()
        print("⏳ 物联网通讯正在后台初始化连接...")
        
        show_help()
        
        _lazy_init_services._initialized = True

# NagaAgent适配器 - 优化重复初始化
class NagaAgentAdapter:
    def __init__(s):
        # 使用全局实例，避免重复初始化
        _lazy_init_services()  # 确保服务已初始化
        s.naga = n  # 使用全局实例
    
    async def respond_stream(s, txt):
        async for resp in s.naga.process(txt):
            yield AI_NAME, resp, None, True, False

# 主程序入口
if __name__ == "__main__":
    import argparse

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="NagaAgent - 智能对话助手")
    parser.add_argument("--check-env", action="store_true", help="运行系统环境检测")
    parser.add_argument("--quick-check", action="store_true", help="运行快速环境检测")
    parser.add_argument("--force-check", action="store_true", help="强制运行环境检测（忽略缓存）")

    args = parser.parse_args()

    # 处理检测命令
    if args.check_env or args.quick_check:
        if args.quick_check:
            success = run_quick_check()
        else:
            success = run_system_check(force_check=args.force_check)
        sys.exit(0 if success else 1)

    # 系统环境检测
    print("🚀 正在启动NagaAgent...")
    print("=" * 50)

    # 执行系统检测（只在第一次启动时检测）
    if not run_system_check():
        print("\n❌ 系统环境检测失败，程序无法启动")
        print("请根据上述建议修复问题后重新启动")
        i=input("是否无视检测结果继续启动？是则按y，否则按其他任意键退出...")
        if i != "y" and i != "Y":
            sys.exit(1)

    print("\n🎉 系统环境检测通过，正在启动应用...")
    print("=" * 50)
    
    if not asyncio.get_event_loop().is_running():
        asyncio.set_event_loop(asyncio.new_event_loop())
    
    # 快速启动UI，后台服务延迟初始化
    app = QApplication(sys.argv)
    icon_path = os.path.join(os.path.dirname(__file__), "ui", "window_icon.png")
    app.setWindowIcon(QIcon(icon_path))
    
    # 集成控制台托盘功能
    console_tray = integrate_console_tray()
    
    # 立即显示UI，提升用户体验
    win = ChatWindow()
    win.setWindowTitle("NagaAgent")
    win.show()
    
    # 在UI显示后异步初始化后台服务
    def init_services_async():
        """异步初始化后台服务"""
        try:
            _lazy_init_services()
        except Exception as e:
            print(f"⚠️ 后台服务初始化异常: {e}")
    
    # 使用定时器延迟初始化，避免阻塞UI
    from nagaagent_core.vendors.PyQt5.QtCore import QTimer
    QTimer.singleShot(100, init_services_async)  # 100ms后初始化
    
    sys.exit(app.exec_())
