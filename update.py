#!/usr/bin/env python3
"""
更新脚本
- 检测 .git 目录并执行 git pull
- 检测 .is_package 文件（待定功能）
- 执行 uv sync 同步依赖
"""

import os
import subprocess
import sys


def run_command(command: str, description: str) -> int:
    """执行shell命令并返回退出码"""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=False,
            text=True
        )
        return result.returncode
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        return 1


def main() -> int:
    """主函数"""
    print("=" * 50)
    print("🚀 开始更新...")
    print("=" * 50)

    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)

    # 检测 .git 目录
    git_dir = os.path.join(project_root, ".git")
    if os.path.exists(git_dir):
        # 获取当前分支名
        result = subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True,
            capture_output=True,
            text=True
        )
        current_branch = result.stdout.strip() if result.returncode == 0 else "main"

        print(f"✅ 检测到 Git 仓库，当前分支: {current_branch}")
        print(f"🔄 执行 git pull origin {current_branch}...")
        ret = run_command(f"git pull origin {current_branch}", "拉取最新代码")
        if ret != 0:
            print(f"⚠️ git pull 返回非零状态码: {ret}")
    else:
        print("❌ 未检测到 .git 目录，退出")
        return 1

    # 检测 .is_package 文件（待定）
    is_package_file = os.path.join(project_root, ".is_package")
    if os.path.exists(is_package_file):
        print("⚠️ 检测到 .is_package 文件")
        print("📝 待定功能：此文件表示的更新逻辑尚未实现")
        # TODO: 实现 .is_package 的更新逻辑

    # 执行 uv sync
    print("\n🔄 执行 uv sync 同步依赖...")
    ret = run_command("uv sync", "同步依赖")
    if ret != 0:
        print(f"❌ uv sync 失败，返回码: {ret}")
        return 1

    print("\n" + "=" * 50)
    print("✅ 更新完成！")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())