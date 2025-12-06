import os
import platform
import subprocess
import shutil
import sys
from pathlib import Path

def get_python_command():
    """
    在 PATH 中查找可用的 python 可执行文件。
    尝试顺序: python3 -> python -> py
    返回: 可用的命令字符串 (如 "python") 或 None
    """
    # 常见 Python 命令列表
    candidates = ["python3", "python", "py"]
    
    for cmd in candidates:
        if shutil.which(cmd):
            try:
                # 验证命令是否真的可执行
                subprocess.run([cmd, "--version"], capture_output=True, check=True)
                return cmd
            except subprocess.CalledProcessError:
                continue
    return None

if __name__ == "__main__":
    print("🚀 开始进行初始化")
    repo_root = Path(__file__).parent.resolve()

    # ---------------------------------------------------------
    # 1. 检测 Python 环境
    # ---------------------------------------------------------
    python_cmd = get_python_command()

    if not python_cmd:
        print("\n   ❌ 错误: 未在系统中检测到 Python。")
        print("   👉 请前往 https://www.python.org/downloads/ 安装 Python 后重试。")
        sys.exit(1)
    
    # 获取一下具体的版本号仅作显示用
    try:
        ver_proc = subprocess.run([python_cmd, "--version"], capture_output=True, text=True)
        ver_str = (ver_proc.stdout or ver_proc.stderr).strip()
        print(f"   ✅ 检测到 Python: {python_cmd} ({ver_str})")
    except:
        print(f"   ✅ 检测到 Python: {python_cmd}")

    # ---------------------------------------------------------
    # 2. 检测并确保 uv 已安装
    # ---------------------------------------------------------
    if not shutil.which("uv"):
        print("   ℹ️ 未检测到 uv，正在尝试使用 pip 自动安装...")
        try:
            # 使用检测到的 python 安装 uv
            subprocess.run([python_cmd, "-m", "pip", "install", "uv"], check=True)
            print("   ✅ uv 安装成功!")
        except subprocess.CalledProcessError as e:
            print(f"\n   ❌ uv 自动安装失败: {e}")
            print("   👉 请尝试手动运行: pip install uv")
            sys.exit(1)
    else:
        print("   ✅ 检测到 uv 已安装")

    # ---------------------------------------------------------
    # 3. 使用 uv 同步依赖和安装 Playwright
    # ---------------------------------------------------------
    print("\n   ⚙️ 正在使用 uv 同步依赖 (uv sync)...")
    try:
        # 这一步会根据 pyproject.toml / uv.lock 创建虚拟环境并安装包
        subprocess.run(["uv", "sync"], check=True, cwd=repo_root)
        
        print("   ⚙️ 正在使用 uv 安装 Playwright 浏览器组件...")
        # 使用 uv run 在虚拟环境中执行命令
        subprocess.run(["uv", "run", "playwright", "install", "chromium"], check=True, cwd=repo_root)
    except subprocess.CalledProcessError as e:
        print(f"\n   ❌ 初始化依赖失败: {e}")
        print("   👉 请检查网络连接或 uv 配置。")
        sys.exit(1)

    # ---------------------------------------------------------
    # 4. 配置文件处理 (config.json)
    # ---------------------------------------------------------
    cfg = repo_root / "config.json"
    example = repo_root / "config.json.example"

    if not cfg.exists():
        if example.exists():
            try:
                shutil.copyfile(str(example), str(cfg))
                print("\n   ✅ 已从示例创建 config.json")
            except Exception as e:
                print(f"   ❌ 创建 config.json 失败: {e}")
        else:
            print("   ⚠️ config.json.example 不存在，跳过配置文件创建。")
    else:
        print("\n   ✅ config.json 已存在，跳过创建。")

    # 尝试打开配置文件供用户编辑
    if cfg.exists():
        print("   📥 正在尝试打开 config.json ...")
        try:
            if platform.system() == "Windows":
                os.startfile(str(cfg))
            elif platform.system() == "Darwin": # macOS
                subprocess.run(["open", str(cfg)], check=True)
            else: # Linux
                subprocess.run(["xdg-open", str(cfg)], check=True)
        except Exception as e:
            print(f"打开失败：{e}，请手动进行配置。")

    print("\n🎉 初始化全部完成！请运行启动脚本 (如 start.bat 或 start.sh)。")
