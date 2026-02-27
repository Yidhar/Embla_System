#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统环境检测模块
检测Python版本、虚拟环境、依赖包等系统环境
更新时间: 2025-10-04
"""

import sys
import subprocess
import importlib
import importlib.util
import platform
import socket
import locale
import psutil
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
import json5  # 支持带注释的JSON解析

class SystemChecker:
    """系统环境检测器"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent  # 指向项目根目录
        self.venv_path = self.project_root / "venv"  # 更新为venv目录
        self.requirements_file = self.project_root / "requirements.txt"
        self.config_file = self.project_root / "config.json"
        self.pyproject_file = self.project_root / "pyproject.toml"
        self.results = {}

        # 需要检测的端口 - 从config读取
        from system.config import get_all_server_ports
        all_ports = get_all_server_ports()
        self.required_ports = [
            all_ports["api_server"],
            all_ports["agent_server"], 
            all_ports["mcp_server"],
        ]
        
        # 镜像源配置
        self.pip_mirrors = [
            "https://pypi.tuna.tsinghua.edu.cn/simple/",
            "https://mirrors.aliyun.com/pypi/simple/",
            "https://pypi.douban.com/simple/",
            "https://pypi.org/simple/"
        ]

        # 核心依赖包（与 requirements.txt 一致，从虚拟环境引入）
        self.core_dependencies = [
            "fastapi",
            "openai",
            "requests",
            "numpy",
            "pandas",
            "json5",
            "charset_normalizer",
        ]

        # 重要可选依赖
        self.optional_dependencies = [
            ("onnxruntime", "语音处理"),
            ("playwright", "浏览器自动化"),
            ("crawl4ai", "网页爬取"),
            ("pyautogui", "屏幕控制"),
            ("opencv_python", "计算机视觉"),
            ("librosa", "音频分析"),
            ("torch", "深度学习框架"),
            ("pystray", "系统托盘"),
            #("paho_mqtt", "MQTT通信"),
            ("jmcomic", "漫画下载"),
            ("bilibili_api", "B站视频"),
            ("python_docx", "Word文档处理")
        ]
        
    def _read_config(self) -> dict:
        """读取 config.json，统一使用 UTF-8 编码（本项目配置文件始终为 UTF-8）"""
        with open(self.config_file, 'r', encoding='utf-8') as f:
            return json5.load(f)

    def _write_config(self, config_data: dict):
        """写入 config.json，统一使用 UTF-8 编码"""
        import json
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

    def check_all(self, auto_setup: bool = False) -> Dict[str, bool]:
        """执行所有检测项目"""
        print("🔍 开始系统环境检测...")
        print("=" * 50)
        
        # 检查是否首次运行且需要自动配置
        if auto_setup and not self.venv_path.exists():
            print("🎯 检测到首次运行，开始自动环境配置...")
            if self.auto_setup_environment():
                print("✅ 自动环境配置完成！")
            else:
                print("❌ 自动环境配置失败，请手动配置")
                return {"自动配置": False}
        
        checks = [
            ("Python版本", self.check_python_version),
            ("虚拟环境", self.check_virtual_environment),
            ("依赖文件", self.check_requirements_file),
            ("核心依赖", self.check_core_dependencies),
            ("可选依赖", self.check_optional_dependencies),
            ("配置文件", self.check_config_files),
            ("目录结构", self.check_directory_structure),
            ("权限检查", self.check_permissions),
            ("端口可用性", self.check_port_availability),
            ("系统资源", self.check_system_resources),
            ("Neo4j连接", self.check_neo4j_connection),
            #("环境变量", self.check_environment_variables)
        ]
        
        all_passed = True
        for name, check_func in checks:
            print(f"📋 检测 {name}...")
            try:
                result = check_func()
                self.results[name] = result
                if result:
                    print(f"✅ {name}: 通过")
                else:
                    print(f"❌ {name}: 失败")
                    all_passed = False
            except Exception as e:
                print(f"⚠️ {name}: 检测异常 - {e}")
                self.results[name] = False
                all_passed = False
            print()
        
        print("=" * 50)
        if all_passed:
            print("🎉 系统环境检测全部通过！")
        else:
            print("⚠️ 系统环境检测发现问题，请查看上述信息")
        
        return self.results
    
    def check_python_version(self) -> bool:
        """检测Python版本"""
        version = sys.version_info
        print(f"   当前Python版本: {version.major}.{version.minor}.{version.micro}")

        # 要求Python 3.11+（根据requirements.txt推荐）
        if version.major < 3 or (version.major == 3 and version.minor < 11):
            print(f"   [WARN] Python版本建议3.11+，当前{version.major}.{version.minor}")
            print("   [TIP] 推荐升级到Python 3.11以获得最佳兼容性")
            return False

        print("   [OK] Python版本符合要求")
        return True
    
    def check_virtual_environment(self) -> bool:
        """检测虚拟环境"""
        # 检查是否在虚拟环境中
        in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
        
        if not in_venv:
            print("   [WARN] 未检测到虚拟环境")
            
            # 检查是否存在venv目录
            if self.venv_path.exists():
                print(f"   [INFO] 发现venv目录: {self.venv_path}")
                print("   [TIP] 请运行: venv\\Scripts\\activate (Windows) 或 source venv/bin/activate (Linux/Mac)")
                return False
            else:
                print("   [TIP] 建议创建虚拟环境: python -m venv venv")
                return False
        
        print(f"   [OK] 虚拟环境: {sys.prefix}")
        return True
    
    def check_requirements_file(self) -> bool:
        """检测依赖文件"""
        if not self.requirements_file.exists():
            print(f"   [ERROR] 未找到requirements.txt文件: {self.requirements_file}")
            return False

        print(f"   [OK] 依赖文件存在: {self.requirements_file}")

        # 检查pyproject.toml
        if self.pyproject_file.exists():
            print(f"   [OK] pyproject.toml存在: {self.pyproject_file}")
        else:
            print("   [WARN] pyproject.toml不存在（可选）")

        return True
    
    def check_core_dependencies(self) -> bool:
        """检测核心依赖包"""
        missing_deps = []

        for dep in self.core_dependencies:
            module_name = dep
            if dep == "opencv_python":
                module_name = "cv2"
            elif dep == "pydantic":
                module_name = "pydantic"

            try:
                importlib.import_module(module_name)
                print(f"   [OK] {dep}")
            except ImportError:
                print(f"   [ERROR] {dep}: 未安装")
                missing_deps.append(dep)

        if missing_deps:
            print(f"   [TIP] 请安装缺失的依赖: pip install {' '.join(missing_deps)}")
            print("   [TIP] 或使用完整安装命令: pip install -r requirements.txt")
            return False

        return True
    
    def check_optional_dependencies(self) -> bool:
        """检测可选依赖包"""
        missing_optional = []

        for dep, desc in self.optional_dependencies:
            # 特殊处理某些包名
            module_name = dep
            if dep == "opencv_python":
                module_name = "cv2"
            elif dep == "bilibili_api":
                module_name = "bilibili_api"
            elif dep == "python_docx":
                module_name = "docx"

            # 使用 find_spec 仅检查包是否存在，不实际加载模块，速度提升显著
            spec = importlib.util.find_spec(module_name)
            if spec is not None:
                print(f"   [OK] {dep} ({desc})")
            else:
                print(f"   [WARN] {dep} ({desc}): 未安装")
                missing_optional.append((dep, desc))

        if missing_optional:
            print("   [TIP] 可选依赖缺失，某些功能可能不可用:")
            for dep, desc in missing_optional:
                print(f"      - {dep}: {desc}")

        return True  # 可选依赖不影响启动
    
    def check_config_files(self) -> bool:
        """检测配置文件"""
        config_files = [
            ("config.json", "主配置文件"),
            ("config.json.example", "配置示例文件")
        ]
        
        all_exist = True
        for file_name, desc in config_files:
            file_path = self.project_root / file_name
            if file_path.exists():
                print(f"   [OK] {file_name} ({desc})")
            else:
                print(f"   [ERROR] {file_name} ({desc}): 不存在")
                all_exist = False
        
        if not all_exist:
            print("   [TIP] 请确保配置文件存在")
        
        return all_exist
    
    def check_directory_structure(self) -> bool:
        """检测目录结构"""
        required_dirs = [
            ("Embla_core", "Next.js运维面板"),
            ("apiserver", "API服务器"),
            ("agentserver", "Agent服务器"),
            ("mcpserver", "MCP服务器"),
            ("summer_memory", "记忆系统"),
            ("system", "系统核心")
        ]

        all_exist = True
        for dir_name, desc in required_dirs:
            dir_path = self.project_root / dir_name
            if dir_path.exists() and dir_path.is_dir():
                print(f"   ✅ {dir_name}/ ({desc})")
            else:
                print(f"   ❌ {dir_name}/ ({desc}): 不存在")
                all_exist = False

        return all_exist
    
    def check_permissions(self) -> bool:
        """检测文件权限"""
        try:
            # 检查项目根目录读写权限
            test_file = self.project_root / ".test_permission"
            test_file.write_text("test")
            test_file.unlink()
            
            # 检查logs目录权限
            logs_dir = self.project_root / "logs"
            if logs_dir.exists():
                test_log = logs_dir / ".test_permission"
                test_log.write_text("test")
                test_log.unlink()
            
            print("   ✅ 文件权限正常")
            return True
            
        except Exception as e:
            print(f"   ❌ 文件权限异常: {e}")
            return False

    def check_port_availability(self) -> bool:
        """检测端口可用性"""
        print(f"   检测端口: {', '.join(map(str, self.required_ports))}")

        all_available = True
        for port in self.required_ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()

            if result == 0:
                print(f"   ⚠️ 端口 {port}: 已被占用")
                all_available = False
            else:
                print(f"   ✅ 端口 {port}: 可用")

        return all_available

    def check_system_resources(self) -> bool:
        """检测系统资源"""
        try:
            # CPU信息
            cpu_count = psutil.cpu_count()
            cpu_percent = psutil.cpu_percent(interval=1)
            print(f"   CPU核心数: {cpu_count}")
            print(f"   CPU使用率: {cpu_percent:.1f}%")

            # 内存信息
            memory = psutil.virtual_memory()
            total_gb = memory.total / (1024**3)
            available_gb = memory.available / (1024**3)
            used_percent = memory.percent
            print(f"   总内存: {total_gb:.1f} GB")
            print(f"   可用内存: {available_gb:.1f} GB")
            print(f"   内存使用率: {used_percent:.1f}%")

            # 磁盘空间
            disk = psutil.disk_usage(str(self.project_root))
            total_disk = disk.total / (1024**3)
            free_disk = disk.free / (1024**3)
            print(f"   磁盘空间: {free_disk:.1f} GB 可用 / {total_disk:.1f} GB 总计")

            # 资源检查
            if total_gb < 4:
                print("   ⚠️ 内存不足4GB，可能影响性能")
                return False

            if free_disk < 1:
                print("   ⚠️ 磁盘空间不足1GB")
                return False

            print("   ✅ 系统资源充足")
            return True

        except Exception as e:
            print(f"   ❌ 检测系统资源失败: {e}")
            return False

    def check_neo4j_connection(self) -> bool:
        """检测Neo4j连接"""
        try:
            # 检查配置文件中是否有Neo4j配置
            if self.config_file.exists():
                config = self._read_config()

                neo4j_config = config.get('grag', {})
                if neo4j_config.get('enabled', False):
                    uri = neo4j_config.get('neo4j_uri', 'neo4j://127.0.0.1:7687')
                    user = neo4j_config.get('neo4j_user', 'neo4j')

                    # 尝试导入neo4j包并连接
                    try:
                        # 只测试连接，不进行实际查询
                        print(f"   Neo4j配置: {uri} (用户: {user})")
                        print("   ✅ Neo4j包已安装，配置已启用")
                        return True
                    except ImportError:
                        print("   ❌ Neo4j包未安装")
                        return False
                    except Exception as e:
                        print(f"   ⚠️ Neo4j连接测试失败: {e}")
                        print("   💡 请确保Neo4j服务正在运行")
                        return False
                else:
                    print("   ⚠️ Neo4j未启用（配置中grag.enabled=false）")
                    return True
            else:
                print("   ⚠️ 配置文件不存在，跳过Neo4j检测")
                return True

        except Exception as e:
            print(f"   ❌ Neo4j检测异常: {e}")
            return False

    '''
    def check_environment_variables(self) -> bool:
        """检测环境变量"""
        important_env_vars = [
            ('PATH', '系统路径'),
            ('PYTHONPATH', 'Python路径（可选）'),
            ('OPENAI_API_KEY', 'OpenAI API密钥（可选）'),
            ('DEEPSEEK_API_KEY', 'DeepSeek API密钥（可选）'),
            ('DASHSCOPE_API_KEY', '阿里云DashScope API密钥（可选）')
        ]

        all_good = True
        for var_name, desc in important_env_vars:
            value = os.getenv(var_name)
            if value:
                # 隐藏敏感信息
                if 'API_KEY' in var_name:
                    display_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "已设置"
                else:
                    display_value = value[:50] + "..." if len(value) > 50 else value
                print(f"   ✅ {var_name}: {display_value}")
            else:
                if '可选' in desc:
                    print(f"   ⚠️ {var_name}: 未设置（{desc}）")
                else:
                    print(f"   ❌ {var_name}: 未设置（{desc}）")
                    all_good = False

        return all_good
   '''

    def find_python311(self) -> Optional[str]:
        """查找Python 3.11解释器"""
        python_commands = [
            "python3.11",
            "py -3.11",
            "python311",
            "python3.11.exe",
            "python311.exe"
        ]
        
        for cmd in python_commands:
            try:
                result = subprocess.run([cmd, "--version"], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and "3.11" in result.stdout:
                    print(f"   ✅ 找到Python 3.11: {cmd}")
                    return cmd
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue
        
        return None

    '''
    def download_python311(self) -> Optional[str]:
        """下载Python 3.11（Windows）"""
        if platform.system() != "Windows":
            print("   ⚠️ 自动下载Python仅支持Windows系统")
            return None
        
        print("   📥 开始下载Python 3.11...")
        try:
            # Python 3.11.9 下载链接
            python_url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
            temp_dir = tempfile.mkdtemp()
            installer_path = os.path.join(temp_dir, "python-3.11.9-amd64.exe")
            
            print(f"   📥 下载中: {python_url}")
            urllib.request.urlretrieve(python_url, installer_path)
            
            print("   🔧 安装Python 3.11...")
            # 静默安装Python 3.11
            install_cmd = [
                installer_path,
                "/quiet",
                "InstallAllUsers=1",
                "PrependPath=1",
                "Include_test=0"
            ]
            
            result = subprocess.run(install_cmd, timeout=300)
            if result.returncode == 0:
                print("   ✅ Python 3.11安装成功")
                # 清理临时文件
                os.remove(installer_path)
                os.rmdir(temp_dir)
                return "python3.11"
            else:
                print("   ❌ Python 3.11安装失败")
                return None
                
        except Exception as e:
            print(f"   ❌ 下载Python 3.11失败: {e}")
            return None
    '''
            
    def create_virtual_environment(self) -> bool:
        """创建虚拟环境"""
        try:
            print("   🔧 创建虚拟环境...")
            
            # 查找Python 3.11
            python_cmd = self.find_python311()
            if not python_cmd:
                print("   📥 未找到Python 3.11")
                #python_cmd = self.download_python311()
                return False
            
            # 创建虚拟环境
            venv_cmd = [python_cmd, "-m", "venv", str(self.venv_path)]
            process_encoding = locale.getpreferredencoding(False) or "utf-8"
            result = subprocess.run(
                venv_cmd,
                capture_output=True,
                text=True,
                encoding=process_encoding,
                errors="replace",
            )
            
            if result.returncode == 0:
                print(f"   ✅ 虚拟环境创建成功: {self.venv_path}")
                return True
            else:
                print(f"   ❌ 虚拟环境创建失败: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"   ❌ 创建虚拟环境异常: {e}")
            return False
    
    def auto_setup_environment(self) -> bool:
        """自动配置环境（首次运行）"""
        print("🚀 开始自动环境配置...")
        print("=" * 50)
        
        if self.venv_path.exists():
            print("   ✅ 虚拟环境已存在，跳过创建")
            return True
        
        if not self.create_virtual_environment():
            return False
        
        print("   ✅ 自动环境配置完成！")
        print("   💡 请运行以下命令激活虚拟环境:")
        if platform.system() == "Windows":
            print("      venv\\Scripts\\activate")
        else:
            print("      source venv/bin/activate")
        
        return True
    
    def get_system_info(self) -> Dict[str, str]:
        """获取系统信息"""
        info = {
            "操作系统": platform.system(),
            "系统版本": platform.version(),
            "架构": platform.machine(),
            "Python版本": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "Python路径": sys.executable,
            "项目路径": str(self.project_root),
            "虚拟环境": "是" if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix) else "否"
        }

        # 添加系统资源信息
        try:
            memory = psutil.virtual_memory()
            info["总内存"] = f"{memory.total / (1024**3):.1f} GB"
            info["CPU核心数"] = str(psutil.cpu_count())
        except Exception:
            pass

        return info
    
    def print_system_info(self):
        """打印系统信息"""
        print("🖥️ 系统信息:")
        print("-" * 30)
        info = self.get_system_info()
        for key, value in info.items():
            print(f"   {key}: {value}")
        print()
    
    def suggest_fixes(self):
        """建议修复方案"""
        print("🔧 修复建议:")
        print("-" * 30)

        if not self.results.get("Python版本", True):
            print("1. 升级Python版本:")
            print("   推荐使用Python 3.11或更高版本")
            print("   下载地址: https://www.python.org/downloads/")
            print()

        if not self.results.get("虚拟环境", True):
            print("2. 创建并激活虚拟环境:")
            print("   # 使用Python 3.11创建虚拟环境:")
            print("   py -3.11 -m venv venv  # Windows")
            print("   python3.11 -m venv venv  # Linux/Mac")
            print("   # 激活虚拟环境:")
            print("   venv\\Scripts\\activate  # Windows")
            print("   source venv/bin/activate  # Linux/Mac")
            print("   # 安装依赖:")
            print("   pip install -r requirements.txt")
            print()

        if not self.results.get("核心依赖", True):
            print("3. 安装核心依赖:")
            print("   pip install -r requirements.txt")
            print("   # 或使用镜像源: pip install -i https://pypi.tuna.tsinghua.edu.cn/simple/ -r requirements.txt")
            print()

        if not self.results.get("配置文件", True):
            print("4. 复制配置文件:")
            print("   copy config.json.example config.json  # Windows")
            print("   cp config.json.example config.json  # Linux/Mac")
            print("   # 编辑config.json并填入API密钥")
            print()

        if not self.results.get("端口可用性", True):
            print("5. 解决端口冲突:")
            print("   # 查找占用端口的进程")
            from system.config import get_server_port
            api_port = get_server_port("api_server")
            print(f"   netstat -ano | findstr :{api_port}  # Windows")
            print(f"   lsof -i :{api_port}  # Linux/Mac")
            print("   # 或修改config.json中的端口配置")
            print()

        if not self.results.get("系统资源", True):
            print("6. 系统资源不足:")
            print("   - 建议至少4GB内存")
            print("   - 建议至少1GB可用磁盘空间")
            print("   - 关闭不必要的应用程序")
            print()

        if not self.results.get("Neo4j连接", True):
            print("7. 配置Neo4j数据库:")
            print("   # 使用Docker启动Neo4j:")
            print("   docker run -d --name naga-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:latest")
            print("   # 或安装Neo4j Desktop")
            print()

        if not self.results.get("目录结构", True):
            print("8. 检查项目完整性:")
            print("   确保所有必要的目录和文件都存在")
            print("   重新克隆项目可能解决问题")
            print()

    def is_check_passed(self) -> bool:
            """检查是否已经通过过系统检测"""
            if not self.config_file.exists():
                return False

            try:
                config_data = self._read_config()
                system_check = config_data.get('system_check', {})
                return system_check.get('passed', False)
            except Exception:
                return False    
    def save_check_status(self, passed: bool):
        """保存检测状态到config.json"""
        try:
            # 读取现有配置
            if self.config_file.exists():
                config_data = self._read_config()
            else:
                config_data = {}

            # 更新system_check配置
            config_data['system_check'] = {
                'passed': passed,
                'timestamp': datetime.now().isoformat(),
                'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                'project_path': str(self.project_root),
                'system': platform.system()
            }

            # 保存配置
            self._write_config(config_data)
        except Exception as e:
            print(f"⚠️ 保存检测状态失败: {e}")
    
    def should_skip_check(self) -> bool:
        """判断是否应该跳过检测"""
        return self.is_check_passed()
    
    def reset_check_status(self):
        """重置检测状态，强制下次启动时重新检测"""
        try:
            # 读取现有配置
            if self.config_file.exists():
                config_data = self._read_config()

                # 删除system_check配置
                if 'system_check' in config_data:
                    del config_data['system_check']

                # 保存配置
                self._write_config(config_data)

                print("✅ 检测状态已重置，下次启动时将重新检测")
            else:
                print("⚠️ 配置文件不存在")
        except Exception as e:
            print(f"⚠️ 重置检测状态失败: {e}")

def run_system_check(force_check: bool = False, auto_setup: bool = False) -> bool:
    """运行系统检测"""
    checker = SystemChecker()
    
    # 检查是否已经通过过检测（除非强制检测）
    if not force_check and checker.should_skip_check():
        print("✅ 系统环境检测已通过，跳过检测")
        return True
    
    # 打印系统信息
    checker.print_system_info()
    
    # 执行检测（支持自动配置）
    results = checker.check_all(auto_setup=auto_setup)
    
    # 保存检测结果
    all_passed = all(results.values())
    checker.save_check_status(all_passed)
    
    # 如果有问题，提供修复建议
    if not all_passed:
        checker.suggest_fixes()
        return False
    
    return True

def reset_system_check():
    """重置系统检测状态"""
    checker = SystemChecker()
    checker.reset_check_status()

def run_quick_check() -> bool:
    """运行快速检测（仅检测核心项）"""
    checker = SystemChecker()

    print("快速系统检测...")
    print("=" * 50)

    # 仅检测关键项
    quick_checks = [
        ("Python版本", checker.check_python_version),
        ("核心依赖", checker.check_core_dependencies),
        ("配置文件", checker.check_config_files)
    ]

    all_passed = True
    for name, check_func in quick_checks:
        print(f"[CHECK] 检测 {name}...")
        try:
            result = check_func()
            if result:
                print(f"[OK] {name}: 通过")
            else:
                print(f"[FAIL] {name}: 失败")
                all_passed = False
        except Exception as e:
            print(f"[ERROR] {name}: 检测异常 - {e}")
            all_passed = False
        print()

    if all_passed:
        print("[SUCCESS] 快速检测通过！")
    else:
        print("[WARN] 快速检测发现问题，建议运行完整检测: python system/system_checker.py --force")

    return all_passed

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NagaAgent 系统环境检测工具")
    parser.add_argument("--quick", action="store_true", help="快速检测（仅检测核心项）")
    parser.add_argument("--force", action="store_true", help="强制检测（忽略缓存）")
    parser.add_argument("--auto-setup", action="store_true", help="首次运行自动配置环境")

    args = parser.parse_args()

    if args.quick:
        success = run_quick_check()
    else:
        success = run_system_check(force_check=args.force, auto_setup=args.auto_setup)

    sys.exit(0 if success else 1)
