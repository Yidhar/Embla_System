#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NagaAgent macOS 打包脚本
使用 PyInstaller 生成 APP 应用，并可选创建 DMG
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
SPEC_FILE = SCRIPT_DIR / 'spec' / 'nagaagent_mac.spec'
DIST_DIR = PROJECT_ROOT / 'dist'
BUILD_DIR = PROJECT_ROOT / 'build'


def check_platform():
    """检查是否在 macOS 平台"""
    if sys.platform != 'darwin':
        print("错误: 此脚本只能在 macOS 上运行")
        print("Windows 打包请使用 build_windows.py")
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


def check_create_dmg():
    """检查 create-dmg 是否安装"""
    result = subprocess.run(['which', 'create-dmg'], capture_output=True)
    if result.returncode != 0:
        print("警告: create-dmg 未安装，将跳过 DMG 创建")
        print("安装方法: brew install create-dmg")
        return False
    return True


def clean_build():
    """清理旧的构建文件"""
    print("\n清理旧的构建文件...")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"  已删除: {BUILD_DIR}")

    # 只清理 macOS 相关的 dist 文件
    app_dir = DIST_DIR / 'NagaAgent.app'
    if app_dir.exists():
        shutil.rmtree(app_dir)
        print(f"  已删除: {app_dir}")


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
    app_dir = DIST_DIR / 'NagaAgent.app'

    if app_dir.exists():
        # 计算 APP 大小
        total_size = sum(
            f.stat().st_size for f in app_dir.rglob('*') if f.is_file()
        )
        size_mb = total_size / (1024 * 1024)
        print(f"\n打包成功!")
        print(f"  输出文件: {app_dir}")
        print(f"  应用大小: {size_mb:.2f} MB")
        return True
    else:
        print("\n打包失败: 未找到输出文件")
        return False


def sign_app(app_path: Path, identity: str = None):
    """代码签名（可选）"""
    if identity is None:
        print("\n跳过代码签名（未提供签名身份）")
        return True

    print(f"\n正在签名应用: {identity}")

    cmd = [
        'codesign',
        '--force',
        '--deep',
        '--sign', identity,
        str(app_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("  签名成功")
        return True
    else:
        print(f"  签名失败: {result.stderr}")
        return False


def create_dmg(app_path: Path):
    """创建 DMG 安装包"""
    print("\n创建 DMG 安装包...")

    if not check_create_dmg():
        return False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dmg_name = f"NagaAgent_macOS_{timestamp}.dmg"
    dmg_path = DIST_DIR / dmg_name

    # create-dmg 命令
    cmd = [
        'create-dmg',
        '--volname', 'NagaAgent',
        '--volicon', str(SCRIPT_DIR / 'resources' / 'icon.icns'),
        '--window-pos', '200', '120',
        '--window-size', '600', '400',
        '--icon-size', '100',
        '--icon', 'NagaAgent.app', '175', '120',
        '--hide-extension', 'NagaAgent.app',
        '--app-drop-link', '425', '120',
        str(dmg_path),
        str(app_path)
    ]

    # 如果没有图标文件，移除图标相关参数
    icon_file = SCRIPT_DIR / 'resources' / 'icon.icns'
    if not icon_file.exists():
        cmd = [arg for arg in cmd if 'icon.icns' not in arg and arg != '--volicon']

    print(f"执行命令: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        size_mb = dmg_path.stat().st_size / (1024 * 1024)
        print(f"  DMG 创建成功: {dmg_path}")
        print(f"  大小: {size_mb:.2f} MB")
        return True
    else:
        print(f"  DMG 创建失败: {result.stderr}")
        # 尝试使用 hdiutil 作为备选
        return create_dmg_hdiutil(app_path)


def create_dmg_hdiutil(app_path: Path):
    """使用 hdiutil 创建简单的 DMG（备选方案）"""
    print("\n使用 hdiutil 创建 DMG...")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dmg_name = f"NagaAgent_macOS_{timestamp}.dmg"
    dmg_path = DIST_DIR / dmg_name

    # 创建临时目录
    temp_dir = DIST_DIR / 'dmg_temp'
    temp_dir.mkdir(exist_ok=True)

    # 复制 APP 到临时目录
    temp_app = temp_dir / 'NagaAgent.app'
    if temp_app.exists():
        shutil.rmtree(temp_app)
    shutil.copytree(app_path, temp_app)

    # 创建 Applications 链接
    apps_link = temp_dir / 'Applications'
    if apps_link.exists():
        apps_link.unlink()
    apps_link.symlink_to('/Applications')

    # 创建 DMG
    cmd = [
        'hdiutil', 'create',
        '-volname', 'NagaAgent',
        '-srcfolder', str(temp_dir),
        '-ov',
        '-format', 'UDZO',
        str(dmg_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # 清理临时目录
    shutil.rmtree(temp_dir)

    if result.returncode == 0:
        size_mb = dmg_path.stat().st_size / (1024 * 1024)
        print(f"  DMG 创建成功: {dmg_path}")
        print(f"  大小: {size_mb:.2f} MB")
        return True
    else:
        print(f"  DMG 创建失败: {result.stderr}")
        return False


def create_release_package():
    """创建发布包（ZIP，作为 DMG 的备选）"""
    print("\n创建发布包 (ZIP)...")

    app_dir = DIST_DIR / 'NagaAgent.app'
    if not app_dir.exists():
        print("错误: APP 文件不存在")
        return False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"NagaAgent_macOS_{timestamp}"
    zip_path = DIST_DIR / f"{zip_name}.zip"

    # 创建 ZIP
    shutil.make_archive(str(zip_path.with_suffix('')), 'zip', DIST_DIR, 'NagaAgent.app')

    print(f"  发布包: {zip_path}")
    print(f"  大小: {zip_path.stat().st_size / (1024 * 1024):.2f} MB")

    return True


def main():
    """主函数"""
    print("=" * 50)
    print("NagaAgent macOS 打包脚本")
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

    # APP 路径
    app_path = DIST_DIR / 'NagaAgent.app'

    # 可选：签名（需要开发者证书）
    # sign_app(app_path, "Developer ID Application: Your Name")

    # 创建 DMG
    dmg_success = create_dmg(app_path)

    # 如果 DMG 失败，创建 ZIP 作为备选
    if not dmg_success:
        create_release_package()

    print("\n" + "=" * 50)
    print("打包完成!")
    print("=" * 50)


if __name__ == '__main__':
    main()
