# ruff: noqa: E402
# pyinstaller适配
import os
import sys
import subprocess
import locale

# Windows 控制台输出编码处理：
# 不强制改成 UTF-8，避免在非 UTF-8 codepage 下出现中文乱码。
def _configure_windows_console_streams():
    if sys.platform != "win32":
        return

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            is_tty = bool(getattr(stream, "isatty", lambda: False)())
            # Pipe output (Electron child process): force UTF-8 to avoid mojibake in renderer logs.
            target_encoding = "utf-8" if not is_tty else (getattr(stream, "encoding", None) or locale.getpreferredencoding(False) or "utf-8")
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding=target_encoding, errors="replace")
            elif hasattr(stream, "buffer"):
                import io

                setattr(sys, stream_name, io.TextIOWrapper(stream.buffer, encoding=target_encoding, errors="replace"))
        except Exception:
            pass


_configure_windows_console_streams()
if os.path.exists("_internal"):
    os.chdir("_internal")

# 打包库识别适配

# 检测是否在打包环境中
# PyInstaller打包后的程序会设置sys.frozen属性
IS_PACKAGED = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

# 标准库导入
import asyncio
import json as _json
import logging
from pathlib import Path
import re
import socket
import threading
import time
import warnings
from urllib.parse import urlparse
from urllib.request import getproxies

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

# 本地模块导入
from system.system_checker import run_system_check, run_quick_check
from system.config import config, AI_NAME

# V14版本已移除早期拦截器，采用运行时猴子补丁

# conversation_core已删除，相关功能已迁移到apiserver
from summer_memory.memory_manager import memory_manager
from summer_memory.task_manager import task_manager

# 统一日志系统初始化
from system.logging_setup import setup_logging
setup_logging()

logger = logging.getLogger("summer_memory")
logger.setLevel(logging.INFO)

# 优化Live2D相关日志输出，减少启动时的信息噪音
logging.getLogger("live2d").setLevel(logging.WARNING)
logging.getLogger("live2d.renderer").setLevel(logging.WARNING)
logging.getLogger("live2d.animator").setLevel(logging.WARNING)
logging.getLogger("live2d.widget").setLevel(logging.WARNING)
logging.getLogger("live2d.config").setLevel(logging.WARNING)
logging.getLogger("live2d.config_dialog").setLevel(logging.WARNING)
logging.getLogger("OpenGL").setLevel(logging.WARNING)
logging.getLogger("OpenGL.acceleratesupport").setLevel(logging.WARNING)

_BRAINSTEM_MAIN_BOOTSTRAP_ENV = "NAGA_BRAINSTEM_MAIN_BOOTSTRAP"
_BRAINSTEM_BOOTSTRAP_OWNER_ENV = "NAGA_BRAINSTEM_BOOTSTRAP_OWNER"
_BRAINSTEM_BOOTSTRAP_OWNER_MAIN = "main"
_BRAINSTEM_API_AUTOSTART_ENV = "NAGA_BRAINSTEM_AUTOSTART"
_BRAINSTEM_API_AUTOSTART_TIMEOUT_ENV = "NAGA_BRAINSTEM_AUTOSTART_TIMEOUT_SECONDS"
_BRAINSTEM_MAIN_STARTUP_OUTPUT = Path("scratch/reports/brainstem_control_plane_main_startup_ws28_024.json")


def _emit_progress(percent: int, phase: str):
    """向 stdout 发送结构化进度信号，供 Electron 主进程解析"""
    payload = {'percent': percent, 'phase': phase}

    try:
        api_port = int(getattr(config.api_server, 'port', 0))
        if 1 <= api_port <= 65535:
            payload['apiPort'] = api_port
    except Exception:
        pass

    try:
        from system.config import get_server_port
        agent_port = int(get_server_port('agent_server'))
        if 1 <= agent_port <= 65535:
            payload['agentPort'] = agent_port
    except Exception:
        pass

    print(f"##PROGRESS##{_json.dumps(payload)}", flush=True)


# 服务管理器类
class ServiceManager:
    """服务管理器 - 统一管理所有后台服务"""
    
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.bg_thread = None
        self.api_thread = None
        self.agent_thread = None
        self.system_agent = None
        self._autonomous_task = None
        self._services_ready = False  # 服务就绪状态
        self.brainstem_bootstrap = {}
    
    def start_background_services(self):
        """启动后台服务 - 异步非阻塞"""
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
            # 任务管理器由memory_manager自动启动，无需手动启动
            # await start_task_manager()
            
            # 标记服务就绪
            self._services_ready = True
            logger.info(f"任务管理器状态: running={task_manager.is_running}")
            await self._try_start_autonomous_agent()
            
            # 保持事件循环活跃
            while True:
                await asyncio.sleep(3600)  # 每小时检查一次
        except Exception as e:
            logger.error(f"后台服务异常: {e}")

    async def _try_start_autonomous_agent(self):
        """Start the autonomous system agent on the background event loop."""
        try:
            auto_cfg = getattr(config, "autonomous", None)
            if auto_cfg is None or not getattr(auto_cfg, "enabled", False):
                logger.info("[Autonomous] disabled by config")
                return

            from autonomous.system_agent import SystemAgent

            cfg_payload = auto_cfg.model_dump() if hasattr(auto_cfg, "model_dump") else auto_cfg
            self.system_agent = SystemAgent(cfg_payload, repo_dir=os.getcwd())
            self._autonomous_task = asyncio.create_task(self.system_agent.start())
            logger.info("[Autonomous] system agent started")
        except Exception as exc:
            logger.error(f"[Autonomous] failed to start: {exc}")

    def _bootstrap_brainstem_control_plane_main_startup(
        self,
        *,
        manager=None,
        api_autostart_enabled=None,
        repo_root: Path | None = None,
    ):
        """主启动链托管 Brainstem 控制面，并声明 ownership，避免 API lifespan 重复托管。"""

        def _env_flag(name: str, default: bool) -> bool:
            raw = os.environ.get(str(name))
            if raw is None:
                return bool(default)
            normalized = str(raw).strip().lower()
            if not normalized:
                return bool(default)
            return normalized in {"1", "true", "yes", "on", "y"}

        def _env_float(name: str, default: float) -> float:
            raw = os.environ.get(str(name))
            if raw is None:
                return float(default)
            try:
                return float(raw)
            except (TypeError, ValueError):
                return float(default)

        root = (repo_root or Path(os.getcwd())).resolve()
        enabled = _env_flag(_BRAINSTEM_MAIN_BOOTSTRAP_ENV, True)
        api_enabled = (
            bool(config.api_server.enabled and config.api_server.auto_start)
            if api_autostart_enabled is None
            else bool(api_autostart_enabled)
        )
        report = {
            "enabled": False,
            "passed": False,
            "repo_root": str(root).replace("\\", "/"),
            "reason": "",
            "env": {
                "main_bootstrap_env": _BRAINSTEM_MAIN_BOOTSTRAP_ENV,
                "owner_env": _BRAINSTEM_BOOTSTRAP_OWNER_ENV,
                "api_autostart_env": _BRAINSTEM_API_AUTOSTART_ENV,
                "api_autostart_timeout_env": _BRAINSTEM_API_AUTOSTART_TIMEOUT_ENV,
            },
        }
        if not api_enabled:
            report["reason"] = "api_autostart_disabled"
            self.brainstem_bootstrap = report
            return report
        if not enabled:
            report["reason"] = "env_disabled"
            self.brainstem_bootstrap = report
            return report

        run_manager = manager
        if run_manager is None:
            from scripts.manage_brainstem_control_plane_ws28_017 import run_manage_brainstem_control_plane_ws28_017

            run_manager = run_manage_brainstem_control_plane_ws28_017

        report["enabled"] = True
        timeout_seconds = max(2.0, _env_float(_BRAINSTEM_API_AUTOSTART_TIMEOUT_ENV, 8.0))
        try:
            startup_report = run_manager(
                repo_root=root,
                action="start",
                output_file=_BRAINSTEM_MAIN_STARTUP_OUTPUT,
                start_timeout_seconds=timeout_seconds,
                force_restart=False,
            )
            report["startup_report"] = startup_report
            report["passed"] = bool(startup_report.get("passed"))
            if report["passed"]:
                os.environ[_BRAINSTEM_BOOTSTRAP_OWNER_ENV] = _BRAINSTEM_BOOTSTRAP_OWNER_MAIN
                os.environ[_BRAINSTEM_API_AUTOSTART_ENV] = "0"
                report["reason"] = "main_startup_managed"
                report["api_lifespan_autostart_disabled"] = True
                logger.info("[brainstem_bootstrap_main] control plane startup ensured and ownership set to main")
            else:
                report["reason"] = "main_startup_failed"
                report["api_lifespan_autostart_disabled"] = False
                logger.warning("[brainstem_bootstrap_main] control plane startup failed; api lifespan fallback remains enabled")
        except Exception as exc:
            report["reason"] = "main_startup_error"
            report["error"] = f"{type(exc).__name__}:{exc}"
            report["api_lifespan_autostart_disabled"] = False
            logger.error(f"[brainstem_bootstrap_main] startup error: {exc}")

        self.brainstem_bootstrap = report
        return report
    
    def check_port_available(self, host, port):
        """检查端口是否可用"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return True
        except OSError:
            return False

    def start_all_servers(self):
        """并行启动所有服务：API(可选)、MCP（不自动启动 Agent Server）"""
        print("🚀 正在并行启动所有服务...")
        print("=" * 50)
        threads = []
        service_status = {}  # 服务状态跟踪

        try:
            self._init_proxy_settings()
            brainstem_bootstrap = self._bootstrap_brainstem_control_plane_main_startup()
            if brainstem_bootstrap.get("enabled"):
                if brainstem_bootstrap.get("passed"):
                    print("✅ Brainstem 控制面: 主启动链托管成功（已禁用 API lifespan 重复托管）")
                    service_status["Brainstem"] = "主启动链托管"
                else:
                    print("⚠️ Brainstem 控制面: 主启动链托管失败，保留 API lifespan 自动托管回退")
                    service_status["Brainstem"] = "托管失败，保留回退"
            else:
                reason = str(brainstem_bootstrap.get("reason") or "disabled")
                service_status["Brainstem"] = f"跳过({reason})"
            # 预检查所有端口（端口已在启动前由 kill_port_occupiers 清理）
            from system.config import get_server_port
            port_checks = {
                'api': config.api_server.enabled and config.api_server.auto_start and
                      self.check_port_available(config.api_server.host, config.api_server.port),
                'mcp': self.check_port_available("0.0.0.0", get_server_port("mcp_server")),
            }

            # API服务器（可选）
            if port_checks['api']:
                api_thread = threading.Thread(target=self._start_api_server, daemon=True)
                threads.append(("API", api_thread))
                service_status['API'] = "准备启动"
            elif config.api_server.enabled and config.api_server.auto_start:
                print(f"⚠️  API服务器: 端口 {config.api_server.port} 已被占用，跳过启动")
                service_status['API'] = "端口占用"

            # MCP服务器（提供外部统一HTTP API）
            if port_checks['mcp']:
                mcp_thread = threading.Thread(target=self._start_mcp_server, daemon=True)
                threads.append(("MCP", mcp_thread))
                service_status['MCP'] = "准备启动"
            else:
                print(f"⚠️  MCP服务器: 端口 {get_server_port('mcp_server')} 已被占用，跳过启动")
                service_status['MCP'] = "端口占用"

            # Agent Server 服务不再随主进程自动启动
            service_status['AgentServer'] = "已禁用自动启动"
            
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

            # 等待服务启动：轮询端口可连接性，最长等 3s
            print("⏳ 等待服务初始化...")
            expected_ports = []
            if port_checks.get('api'):
                expected_ports.append(config.api_server.port)
            if port_checks.get('mcp'):
                expected_ports.append(get_server_port("mcp_server"))

            if expected_ports:
                for _ in range(15):  # 最多 15 × 0.2s = 3s
                    all_ready = True
                    for p in expected_ports:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(0.1)
                        if s.connect_ex(('127.0.0.1', p)) != 0:
                            all_ready = False
                        s.close()
                        if not all_ready:
                            break
                    if all_ready:
                        break
                    time.sleep(0.2)

            _emit_progress(45, "等待服务就绪...")

            print("-" * 30)
            print(f"🎉 服务启动完成: {len(threads)} 个服务正在运行")
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ 并行启动服务异常: {e}")

    def _init_proxy_settings(self):
        """初始化代理设置：本地地址始终 NO_PROXY，系统代理按配置/环境变量开关控制。"""

        def _parse_bool_env(name: str):
            raw = os.environ.get(name)
            if raw is None:
                return None
            value = str(raw).strip().lower()
            if value in {"1", "true", "yes", "on"}:
                return True
            if value in {"0", "false", "no", "off"}:
                return False
            return None

        def _split_no_proxy(raw: str):
            values = []
            if not raw:
                return values
            for segment in str(raw).replace(";", ",").split(","):
                item = segment.strip()
                if item:
                    values.append(item)
            return values

        def _sanitize_proxy_url(proxy_url: str):
            try:
                parsed = urlparse(str(proxy_url))
            except Exception:
                return str(proxy_url)

            if not parsed.scheme:
                return str(proxy_url)

            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""
            auth = ""
            if parsed.username:
                auth = f"{parsed.username}:***@"
            return f"{parsed.scheme}://{auth}{host}{port}"

        config_proxy_enabled = bool(getattr(config.api, "applied_proxy", False))
        env_proxy_override = _parse_bool_env("NAGA_USE_SYSTEM_PROXY")
        use_system_proxy = config_proxy_enabled if env_proxy_override is None else env_proxy_override
        print(
            f"系统代理开关: {use_system_proxy} "
            f"(config.api.applied_proxy={config_proxy_enabled}, env.NAGA_USE_SYSTEM_PROXY={env_proxy_override})"
        )

        proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
        has_env_proxy = any(os.environ.get(var) for var in proxy_vars)

        def _get_windows_registry_proxy():
            proxies = {}
            bypass = []
            if sys.platform != "win32":
                return proxies, bypass

            try:
                import winreg
            except ImportError:
                return proxies, bypass

            key = None
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                )
                proxy_enable = int(winreg.QueryValueEx(key, "ProxyEnable")[0])
                if proxy_enable:
                    proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
                    if proxy_server:
                        if "=" not in proxy_server and ";" not in proxy_server:
                            proxy_server = f"http={proxy_server};https={proxy_server};ftp={proxy_server}"

                        for segment in proxy_server.split(";"):
                            segment = segment.strip()
                            if not segment:
                                continue
                            if "=" in segment:
                                protocol, address = segment.split("=", 1)
                            else:
                                protocol, address = "http", segment
                            protocol = protocol.strip().lower()
                            address = address.strip()
                            if not address:
                                continue
                            if not re.match(r"(?:[^/:]+)://", address):
                                if protocol in ("http", "https", "ftp"):
                                    address = "http://" + address
                                elif protocol == "socks":
                                    address = "socks://" + address
                            proxies[protocol] = address

                        if proxies.get("socks"):
                            socks_proxy = re.sub(r"^socks://", "socks4://", proxies["socks"])
                            proxies["http"] = proxies.get("http") or socks_proxy
                            proxies["https"] = proxies.get("https") or socks_proxy

                try:
                    override_raw = str(winreg.QueryValueEx(key, "ProxyOverride")[0] or "")
                except OSError:
                    override_raw = ""

                if override_raw:
                    for item in override_raw.split(";"):
                        value = item.strip()
                        if not value:
                            continue
                        if value.lower() == "<local>":
                            bypass.extend(["localhost", "127.0.0.1", "::1"])
                        else:
                            bypass.append(value)
            except (OSError, ValueError, TypeError):
                pass
            finally:
                if key is not None:
                    key.Close()

            return proxies, bypass

        registry_proxies, registry_bypass = _get_windows_registry_proxy()
        synced_from_registry = False
        if has_env_proxy:
            proxy_source = "env"
        elif sys.platform == "win32" and registry_proxies:
            proxy_source = "windows_registry"
        else:
            proxy_source = "none"

        # Windows 下若仅使用系统代理（注册表）且无环境变量代理，
        # 先写入 HTTP(S)_PROXY，避免后续设置 NO_PROXY 使 urllib.getproxies 失去注册表回退。
        if use_system_proxy and sys.platform == "win32" and not has_env_proxy and registry_proxies:
            hydrate_mapping = {
                "http": ("HTTP_PROXY", "http_proxy"),
                "https": ("HTTPS_PROXY", "https_proxy"),
                "all": ("ALL_PROXY", "all_proxy"),
            }
            hydrated = []
            for scheme, env_names in hydrate_mapping.items():
                proxy_value = registry_proxies.get(scheme)
                if not proxy_value:
                    continue
                for env_name in env_names:
                    if not os.environ.get(env_name):
                        os.environ[env_name] = proxy_value
                hydrated.append(f"{scheme}={_sanitize_proxy_url(proxy_value)}")

            if hydrated:
                print(
                    "代理来源: Windows 系统代理（注册表），已同步到当前进程环境变量: "
                    + ", ".join(hydrated)
                )
                synced_from_registry = True
            has_env_proxy = True
            proxy_source = "windows_registry"

        # 始终确保本地服务通信不走代理，同时尽量保留系统代理例外列表
        no_proxy_values = ["localhost", "127.0.0.1", "0.0.0.0"]
        existing_no_proxy = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
        if not existing_no_proxy and registry_bypass:
            existing_no_proxy = ",".join(registry_bypass)
        if existing_no_proxy:
            no_proxy_values = _split_no_proxy(existing_no_proxy) + no_proxy_values

        dedup_no_proxy = []
        seen = set()
        for host in no_proxy_values:
            if host not in seen:
                seen.add(host)
                dedup_no_proxy.append(host)
        no_proxy_hosts = ",".join(dedup_no_proxy)
        os.environ["NO_PROXY"] = no_proxy_hosts
        os.environ["no_proxy"] = no_proxy_hosts
        print(f"已设置 NO_PROXY={no_proxy_hosts}")

        if use_system_proxy:
            if proxy_source == "env":
                print("代理来源: 进程环境变量（HTTP(S)_PROXY/ALL_PROXY）")
            elif proxy_source == "windows_registry":
                if not synced_from_registry:
                    print("代理来源: Windows 系统代理（已同步到当前进程环境变量）")
            else:
                print("代理来源: 未检测到环境变量或系统代理配置")

            detected_proxies = getproxies()
            proxy_entries = []
            for key in ("https", "http", "all", "socks", "ftp"):
                value = detected_proxies.get(key)
                if value:
                    proxy_entries.append(f"{key}={_sanitize_proxy_url(str(value))}")

            if proxy_entries:
                print(
                    "系统代理生效配置（当前进程）: "
                    + ", ".join(proxy_entries)
                )
            else:
                print("系统代理已启用，但当前进程未解析到可用代理配置")
            return

        print("检测到不启用代理，正在清空系统代理环境变量...")
        for var in proxy_vars:
            if var in os.environ:
                del os.environ[var]
                print(f"已清除代理环境变量: {var}")
    def _start_api_server(self):
        """内部API服务器启动方法"""
        try:
            import uvicorn
            from apiserver.api_server import app

            print(f"   🚀 API服务器: 正在启动 on {config.api_server.host}:{config.api_server.port}...")

            uvicorn.run(
                app,
                host=config.api_server.host,
                port=config.api_server.port,
                log_level="info",
                access_log=False,
                reload=False,
                ws_ping_interval=None,
                ws_ping_timeout=None
            )
        except ImportError as e:
            print(f"   ❌ API服务器依赖缺失: {e}", flush=True)
        except Exception as e:
            print(f"   ❌ API服务器启动失败: {e}", flush=True)
    
    def _start_mcp_server(self):
        """内部MCP服务器启动方法"""
        try:
            import uvicorn
            from mcpserver.mcp_server import app
            from system.config import get_server_port

            uvicorn.run(
                app,
                host="0.0.0.0",
                port=get_server_port("mcp_server"),
                log_level="error",
                access_log=False,
                reload=False,
                ws_ping_interval=None,
                ws_ping_timeout=None
            )
        except Exception as e:
            import traceback
            print(f"   ❌ MCP服务器启动失败: {e}", flush=True)
            traceback.print_exc()

    def _start_agent_server(self):
        """内部Agent服务器启动方法"""
        try:
            import uvicorn
            from agentserver.agent_server import app
            from system.config import get_server_port

            uvicorn.run(
                app,
                host="127.0.0.1",
                port=get_server_port("agent_server"),
                log_level="error",
                access_log=False,
                reload=False,
                ws_ping_interval=None,  # 禁用WebSocket ping
                ws_ping_timeout=None    # 禁用WebSocket ping超时
            )
        except Exception as e:
            import traceback
            print(f"   ❌ Agent服务器启动失败: {e}", flush=True)
            traceback.print_exc()
    
    def _init_memory_system(self):
        """初始化记忆系统"""
        try:
            if memory_manager and memory_manager.enabled:
                logger.info("夏园记忆系统已初始化（本地模式）")
            else:
                logger.info("夏园记忆系统已禁用（本地模式）")
        except Exception as e:
            logger.warning(f"记忆系统初始化失败: {e}")
    
    def _init_mcp_services(self):
        """初始化MCP服务系统 - in-process 注册 agent"""
        try:
            from mcpserver.mcp_registry import auto_register_mcp
            registered = auto_register_mcp()
            logger.info(f"MCP服务已注册（in-process），共 {len(registered)} 个: {registered}")
        except Exception as e:
            logger.error(f"MCP服务系统初始化失败: {e}")

def kill_port_occupiers():
    """启动前杀掉占用后端端口的进程（跨平台）"""
    def _decode_subprocess_output(data):
        if not data:
            return ""
        if isinstance(data, str):
            return data
        for encoding in ("utf-8", "cp936", "gbk"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    from system.config import get_all_server_ports
    all_ports = get_all_server_ports()
    ports = [
        all_ports["api_server"],
        all_ports["mcp_server"],
    ]
    my_pid = os.getpid()
    killed = False

    if sys.platform == "win32":
        for port in ports:
            try:
                result = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=False, check=False
                )
                stdout_text = _decode_subprocess_output(result.stdout)
                for line in stdout_text.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        if not parts:
                            continue
                        pid_str = parts[-1].strip()
                        if not pid_str.isdigit():
                            continue
                        pid = int(pid_str)
                        if pid != my_pid and pid > 0:
                            subprocess.run(
                                ["taskkill", "/F", "/PID", str(pid)],
                                capture_output=True,
                                text=False,
                                check=False,
                            )
                            print(f"   已终止占用端口 {port} 的进程 (PID {pid})")
                            killed = True
            except Exception as e:
                print(f"   ⚠️ 清理端口 {port} 时出错: {e}")
    else:
        # macOS/Linux: 合并为单次 lsof 调用
        try:
            port_args = ",".join(str(p) for p in ports)
            result = subprocess.run(
                ["lsof", "-ti", f":{port_args}"], capture_output=True, text=True
            )
            if result.stdout.strip():
                for pid_str in result.stdout.strip().split("\n"):
                    try:
                        pid = int(pid_str.strip())
                        if pid != my_pid and pid > 0:
                            os.kill(pid, 9)
                            print(f"   已终止占用端口的进程 (PID {pid})")
                            killed = True
                    except (ValueError, ProcessLookupError):
                        pass
        except Exception as e:
            print(f"   ⚠️ 清理端口时出错: {e}")

    if killed:
        time.sleep(0.5)  # SIGKILL 后端口释放很快，0.5s 足够


# 工具函数
def show_help():
    print('系统命令: 清屏, 查看索引, 帮助, 退出')

def show_index():
    print('主题分片索引已集成，无需单独索引查看')

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')


def check_and_update_if_needed() -> bool:
    """检查上次系统检测时间，如果检测通过且超过5天则执行更新"""
    from datetime import datetime
    import json5

    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

    if not os.path.exists(config_file):
        return False

    try:
        # 直接用 UTF-8 读取（本项目 config.json 始终为 UTF-8 编码）
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = json5.load(f)

        system_check = config_data.get('system_check', {})
        timestamp_str = system_check.get('timestamp')
        passed = system_check.get('passed', False)

        if not timestamp_str:
            return False

        # 只在检测通过的情况下才检查时间
        if not passed:
            return False

        # 解析时间戳
        last_check_time = datetime.fromisoformat(timestamp_str)
        now = datetime.now()
        days_since_last_check = (now - last_check_time).days

        # 如果超过5天
        if days_since_last_check >= 5:
            print(f"⚠️ 上次系统检测已超过 {days_since_last_check} 天，开始执行更新...")
            print("=" * 50)

            # 执行 update.py
            update_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update.py")
            if os.path.exists(update_script):
                result = subprocess.run([sys.executable, update_script], cwd=os.path.dirname(os.path.abspath(__file__)))
                if result.returncode == 0:
                    print("✅ 更新成功")
                else:
                    print(f"⚠️ 更新失败，返回码: {result.returncode}")
            else:
                print("⚠️ update.py 不存在，跳过更新")

            # 重置检测状态为 false
            config_data['system_check']['passed'] = False
            # 保存配置
            import json
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

            print("✅ 检测状态已重置为 false")
            print("=" * 50)
            print("🔄 正在重启程序...")
            # 重启程序
            os.execv(sys.executable, [sys.executable] + sys.argv)

        return False

    except Exception as e:
        print(f"⚠️ 检查上次检测时间失败: {e}")
        return False

# 延迟初始化 - 避免启动时阻塞
def _lazy_init_services():
    """延迟初始化服务 - 在需要时才初始化"""
    global service_manager, n
    if not hasattr(_lazy_init_services, '_initialized'):
        # 初始化服务管理器
        service_manager = ServiceManager()
        service_manager.start_background_services()
        _emit_progress(15, "初始化服务...")

        # conversation_core已删除，相关功能已迁移到apiserver
        n = None

        # 初始化各个系统
        service_manager._init_mcp_services()
        _emit_progress(20, "注册MCP服务...")
        service_manager._init_memory_system()
        _emit_progress(25, "初始化子系统...")
        
        # 显示系统状态
        print("=" * 30)
        print(f"GRAG状态: {'启用' if memory_manager.enabled else '禁用'}")
        if memory_manager.enabled:
            memory_manager.get_memory_stats()
            from summer_memory.quintuple_graph import get_graph, GRAG_ENABLED
            graph = get_graph()
            print(f"Neo4j连接: {'成功' if graph and GRAG_ENABLED else '失败'}")
        print("=" * 30)
        print(f'{AI_NAME}系统已启动')
        print("=" * 30)
        
        # 启动服务（并行异步）
        _emit_progress(30, "启动服务器...")
        service_manager.start_all_servers()
        _emit_progress(50, "后端就绪")
        
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
    parser.add_argument("--headless", action="store_true", help="无头模式（Electron/Web，跳过交互提示）")

    args = parser.parse_args()

    # 处理检测命令
    if args.check_env or args.quick_check:
        if args.quick_check:
            success = run_quick_check()
        else:
            success = run_system_check(force_check=args.force_check)
        sys.exit(0 if success else 1)

    # 检查上次系统检测时间，如果超过7天则执行更新
    check_and_update_if_needed()

    # 启动前清理占用端口的进程
    print("🔍 检查端口占用...")
    kill_port_occupiers()

    # 系统环境检测
    print("🚀 正在启动NagaAgent...")
    print("=" * 50)

    headless = args.headless or not sys.stdin.isatty()

    # 如果是打包环境，跳过所有环境检测
    if IS_PACKAGED:
        print("📦 检测到打包环境，跳过系统环境检测...")
    else:
        # 执行系统检测（只在第一次启动时检测）
        if not run_system_check():
            print("\n❌ 系统环境检测失败，程序无法启动")
            print("请根据上述建议修复问题后重新启动")
            if headless:
                print("⚠️ 无头模式：自动继续启动...")
            else:
                i=input("是否无视检测结果继续启动？是则按y，否则按其他任意键退出...")
                if i != "y" and i != "Y":
                    sys.exit(1)

    print("\n🎉 系统环境检测通过，正在启动应用...")
    print("=" * 50)

    if not asyncio.get_event_loop().is_running():
        asyncio.set_event_loop(asyncio.new_event_loop())

    # 启动后端服务
    _lazy_init_services()
    print("\n✅ 所有后端服务已启动，等待前端连接...")

    import signal

    def _shutdown(signum=None, frame=None):
        print("\n👋 正在关闭后端服务...")
        os._exit(0)

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _shutdown()
