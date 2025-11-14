import os
import platform
import subprocess
import shutil
import sys
from pathlib import Path
import re

def find_python_command(preferred_versions=None):
    """
    在 PATH 中查找可用的 python 可执行文件，并返回第一个匹配的命令及其版本输出。
    preferred_versions: 按优先级排列的命令列表（例如 ["python3.11", "python3", "python"]）
    返回 (命令, 版本输出字符串) 或 (None, None)
    """
    if preferred_versions is None:
        # <<< 变化开始: 调整了检测顺序，优先检测更通用的命令
        preferred_versions = ["python3", "python", "py", "python3.11"]
        # <<< 变化结束
    for cmd in preferred_versions:
        try:
            # 通过 `--version` 获取版本信息（部分 Python 将输出到 stderr）
            proc = subprocess.run([cmd, "--version"], capture_output=True, text=True, check=True)
            out = (proc.stdout or proc.stderr).strip()
            if out:
                return cmd, out
        except (FileNotFoundError, subprocess.CalledProcessError):
            # 命令不存在或执行失败，继续尝试下一个
            continue
    return None, None

def parse_version(version_output: str):
    """
    从版本输出字符串中解析出版本号（匹配 X.Y 或 X.Y.Z）
    返回匹配的版本字符串或 None
    """
    m = re.search(r"(\d+\.\d+\.\d+|\d+\.\d+)", version_output)
    return m.group(1) if m else None

def is_python_compatible() -> tuple[bool, str, str]:
    """
    检查 Python 版本。优先寻找 3.11，但也返回找到的其他版本信息。
    返回 (是否兼容3.11, 使用的 python 命令, 版本输出字符串)
    """
    # <<< 变化开始: 函数现在返回三个值，包括找到的任何python版本信息
    cmd, out = find_python_command()
    if not cmd:
        return False, "", ""
    ver = parse_version(out) or ""
    try:
        parts = [int(x) for x in ver.split(".")]
    except Exception:
        return False, cmd, out
    # 仅允许 3.11.x
    if len(parts) >= 2 and parts[0] == 3 and parts[1] == 11:
        return True, cmd, out
    return False, cmd, out
    # <<< 变化结束

def is_uv_available() -> bool:
    """
    检查是否安装并在 PATH 中可用的 `uv` 工具
    """
    return shutil.which("uv") is not None

if __name__ == "__main__":
    print("开始进行初始化")
    
    use_uv = is_uv_available()
    python_cmd = ""

    if use_uv:
        print("   ✅ 检测到 uv，将用以同步依赖，跳过python版本检测")
    else:
        print("   ℹ️ 未检测到 uv，正在检查 Python 环境...")
        is_compatible, found_cmd, version_output = is_python_compatible()
        
        if is_compatible:
            python_cmd = found_cmd
            print(f"   ✅ 检测到兼容的 Python 3.11: {python_cmd} ({version_output})")
            print("   ℹ️ 将使用 venv 和 pip 进行安装")
        elif found_cmd:
            print(f"   ⚠️ 未检测到 Python 3.11，但找到了: {found_cmd} ({version_output})")
            prompt = "   👉 是否要尝试使用此 Python 自动安装 'uv' 以继续? (y/n): "
            try:
                answer = input(prompt).lower().strip()
            except (EOFError, KeyboardInterrupt):
                # 用户按 Ctrl+C 或 Ctrl+D 中断
                print("\n   ❌ 操作已取消。")
                sys.exit(1)

            if answer in ['y', 'yes']:
                try:
                    print(f"   ⏳ 正在使用 {found_cmd} 安装 uv...")
                    subprocess.run([found_cmd, "-m", "pip", "install", "uv"], check=True)
                    print("   ✅ uv 安装成功!")
                    use_uv = True # 标记切换到 uv 路径
                except subprocess.CalledProcessError as e:
                    print(f"   ❌ uv 安装失败: {e}")
                    print("   ❌ 请手动安装 Python 3.11 或访问 https://docs.astral.sh/uv/getting-started/installation/ 手动安装 uv")
                    sys.exit(1)
            else:
                print("   ❌ 操作已取消。请安装 Python 3.11 或 uv 后重试。")
                sys.exit(1)
        else:
            print("   ❌ 未在 PATH 中找到任何可用的 Python 环境。")
            print("   ❌ 请安装 Python 3.11 或访问 https://docs.astral.sh/uv/getting-started/installation/ 安装 uv。")
            sys.exit(1)

    repo_root = Path(__file__).parent.resolve()
    
    if use_uv:
        # 使用 uv 来同步依赖并安装 playwright 的 chromium
        print("   ⚙️ 正在使用 uv 同步依赖...")
        try:
            subprocess.run(["uv", "sync"], check=True, cwd=repo_root)
            print("   ⚙️ 正在使用 uv 安装 Playwright browsers...")
            # uv run 会在uv管理的环境中执行命令
            subprocess.run(["uv", "run", "playwright", "install", "chromium"], check=True, cwd=repo_root)
        except subprocess.CalledProcessError as e:
            print(f"   ❌ uv 操作失败: {e}")
            sys.exit(1)
    else:
        # 使用传统的 venv/pip 流程
        venv_dir = repo_root / ".venv"
        print(f"   ⚙️ 正在创建虚拟环境到: {venv_dir}")
        try:
            subprocess.run([python_cmd, "-m", "venv", str(venv_dir)], check=True)
        except subprocess.CalledProcessError as e:
            print(f"   ❌ 创建虚拟环境失败: {e}")
            sys.exit(1)

        # 虚拟环境中 Python 可执行文件的路径（Windows 和类 Unix 不同）
        if platform.system() == "Windows":
            venv_python = venv_dir / "Scripts" / "python.exe"
        else:
            venv_python = venv_dir / "bin" / "python"

        if not venv_python.exists():
            print("   ❌ 虚拟环境 Python 未找到，安装中断")
            sys.exit(1)
            
        print("   ⚙️ 正在安装依赖...")
        try:
            subprocess.run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
            req_file = repo_root / "requirements.txt"
            if req_file.exists():
                subprocess.run([str(venv_python), "-m", "pip", "install", "-r", str(req_file)], check=True)
            else:
                print("   ⚠️ requirements.txt 未找到，跳过 pip 安装")
            
            print("   ⚙️ 正在安装 Playwright browsers...")
            subprocess.run([str(venv_python), "-m", "playwright", "install", "chromium"], check=True)
        except subprocess.CalledProcessError as e:
            print(f"   ❌ 依赖安装失败: {e}")
            sys.exit(1)

    
    # 处理配置文件 config.json：如果不存在则从 config.json.example 复制一份
    cfg = repo_root / "config.json"
    example = repo_root / "config.json.example"
    if not cfg.exists():
        if example.exists():
            try:
                shutil.copyfile(str(example), str(cfg))
                print("   ✅ 已创建 config.json")
            except Exception as e:
                print(f"   ❌ 复制 config.json.example 失败: {e}")
                sys.exit(1)
        else:
            print("   ❌ config.json.example 不存在，无法创建 config.json")
            sys.exit(1)
    else:
        print("   ✅ config.json 已存在")

    # 使用系统默认编辑器打开 config.json，便于用户编辑
    print("   📥 使用系统默认编辑器打开 config.json，请根据需要进行修改")
    try:
        if platform.system() == "Windows":
            os.startfile(str(cfg))
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(cfg)], check=True)
        else:
            subprocess.run(["xdg-open", str(cfg)], check=True)
    except Exception as e:
        print(f"   ⚠️ 无法自动打开 config.json: {e}")
        
    print("\n🎉 初始化完成，可以启动程序了（例如运行 start.bat / start.sh）")
