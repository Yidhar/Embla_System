#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NagaAgent 一键打包脚本
自动检测平台并执行相应的打包流程
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()


def run_build(platform: str):
    """运行指定平台的打包脚本"""
    if platform == 'windows':
        script = SCRIPT_DIR / 'build_windows.py'
    elif platform == 'macos':
        script = SCRIPT_DIR / 'build_macos.py'
    else:
        print(f"错误: 不支持的平台 {platform}")
        return False

    if not script.exists():
        print(f"错误: 打包脚本不存在: {script}")
        return False

    print(f"\n运行 {platform} 打包脚本...")
    print("=" * 50)

    result = subprocess.run([sys.executable, str(script)])

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description='NagaAgent 打包工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python -m package.build_all              # 自动检测平台并打包
  python -m package.build_all --windows    # 打包 Windows 版本
  python -m package.build_all --macos      # 打包 macOS 版本
  python -m package.build_all --all        # 打包所有平台（需要对应环境）
        """
    )

    parser.add_argument(
        '--windows', '-w',
        action='store_true',
        help='打包 Windows EXE'
    )
    parser.add_argument(
        '--macos', '-m',
        action='store_true',
        help='打包 macOS APP/DMG'
    )
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='打包所有平台'
    )

    args = parser.parse_args()

    print("=" * 50)
    print("NagaAgent 一键打包工具")
    print("=" * 50)

    platforms = []

    if args.all:
        platforms = ['windows', 'macos']
    elif args.windows:
        platforms = ['windows']
    elif args.macos:
        platforms = ['macos']
    else:
        # 自动检测平台
        if sys.platform == 'win32':
            platforms = ['windows']
        elif sys.platform == 'darwin':
            platforms = ['macos']
        else:
            print(f"警告: 不支持的平台 {sys.platform}")
            print("请使用 --windows 或 --macos 指定目标平台")
            sys.exit(1)

    print(f"目标平台: {', '.join(platforms)}")

    success_count = 0
    fail_count = 0

    for platform in platforms:
        if run_build(platform):
            success_count += 1
        else:
            fail_count += 1

    print("\n" + "=" * 50)
    print("打包结果汇总")
    print("=" * 50)
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")

    if fail_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
