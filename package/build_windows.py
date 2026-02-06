#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NagaAgent Windows 打包脚本
使用 PyInstaller 生成单文件 EXE
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

# 项目路径
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent
SPEC_FILE = SCRIPT_DIR / 'spec' / 'nagaagent_win.spec'
DIST_DIR = PROJECT_ROOT / 'dist'
BUILD_DIR = PROJECT_ROOT / 'build'


def check_platform():
    """检查是否在 Windows 平台"""
    if sys.platform != 'win32':
        print("警告: 当前不在 Windows 平台，打包可能不兼容")
        response = input("是否继续? (y/n): ")
        if response.lower() != 'y':
            sys.exit(1)


def check_pyinstaller():
    """检查 PyInstaller 是否安装"""
    try:
        import PyInstaller
        print(f"PyInstaller 版本: {PyInstaller.__version__}")
        return True
    except ImportError:
        print("错误: PyInstaller 未安装")
        print("请运行: pip install pyinstaller")
        return False


def clean_build():
    """清理旧的构建文件"""
    print("\n清理旧的构建文件...")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"  已删除: {BUILD_DIR}")

    # 只清理 Windows 相关的 dist 文件
    exe_file = DIST_DIR / 'NagaAgent.exe'
    if exe_file.exists():
        exe_file.unlink()
        print(f"  已删除: {exe_file}")


def run_pyinstaller():
    """运行 PyInstaller 打包"""
    print("\n开始 PyInstaller 打包...")
    print(f"使用 spec 文件: {SPEC_FILE}")

    if not SPEC_FILE.exists():
        print(f"错误: spec 文件不存在: {SPEC_FILE}")
        return False

    # 构建命令
    cmd = [
        sys.executable,
        '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        str(SPEC_FILE)
    ]

    print(f"执行命令: {' '.join(cmd)}")
    print("-" * 50)

    # 执行打包
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=False
    )

    return result.returncode == 0


def verify_output():
    """验证打包输出"""
    exe_file = DIST_DIR / 'NagaAgent.exe'

    if exe_file.exists():
        size_mb = exe_file.stat().st_size / (1024 * 1024)
        print(f"\n打包成功!")
        print(f"  输出文件: {exe_file}")
        print(f"  文件大小: {size_mb:.2f} MB")
        return True
    else:
        print("\n打包失败: 未找到输出文件")
        return False


def create_release_package():
    """创建发布包（ZIP）"""
    print("\n创建发布包...")

    exe_file = DIST_DIR / 'NagaAgent.exe'
    if not exe_file.exists():
        print("错误: EXE 文件不存在")
        return False

    # 创建发布目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    release_name = f"NagaAgent_Win64_{timestamp}"
    release_dir = DIST_DIR / release_name
    release_dir.mkdir(parents=True, exist_ok=True)

    # 复制文件
    shutil.copy2(exe_file, release_dir / 'NagaAgent.exe')

    # 复制配置示例
    config_example = PROJECT_ROOT / 'config.json.example'
    if config_example.exists():
        shutil.copy2(config_example, release_dir / 'config.json.example')

    # 创建 README
    readme_content = """NagaAgent - 智能对话助手
========================

使用说明:
1. 首次运行前，请将 config.json.example 复制为 config.json
2. 编辑 config.json 配置你的 API 密钥等信息
3. 双击 NagaAgent.exe 启动程序

注意事项:
- 首次启动可能需要较长时间（单文件模式需要解压资源）
- 如遇到杀毒软件误报，请添加信任
- 日志文件保存在程序同目录下的 logs 文件夹

版本: 4.0.0
"""
    (release_dir / '使用说明.txt').write_text(readme_content, encoding='utf-8')

    # 创建 ZIP
    zip_file = DIST_DIR / f"{release_name}.zip"
    shutil.make_archive(str(zip_file.with_suffix('')), 'zip', DIST_DIR, release_name)

    # 清理临时目录
    shutil.rmtree(release_dir)

    print(f"  发布包: {zip_file}")
    print(f"  大小: {zip_file.stat().st_size / (1024 * 1024):.2f} MB")

    return True


def main():
    """主函数"""
    print("=" * 50)
    print("NagaAgent Windows 打包脚本")
    print("=" * 50)

    # 检查平台
    check_platform()

    # 检查 PyInstaller
    if not check_pyinstaller():
        sys.exit(1)

    # 清理
    clean_build()

    # 打包
    if not run_pyinstaller():
        print("\n打包过程中出现错误")
        sys.exit(1)

    # 验证
    if not verify_output():
        sys.exit(1)

    # 创建发布包
    create_release_package()

    print("\n" + "=" * 50)
    print("打包完成!")
    print("=" * 50)


if __name__ == '__main__':
    main()
