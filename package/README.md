# NagaAgent 打包模块

使用 PyInstaller 将 NagaAgent 打包为独立可执行文件。

## 目录结构

```
package/
├── __init__.py           # 模块初始化
├── build_all.py          # 一键打包脚本
├── build_windows.py      # Windows 打包脚本
├── build_macos.py        # macOS 打包脚本
├── spec/
│   ├── nagaagent_win.spec    # Windows PyInstaller 配置
│   └── nagaagent_mac.spec    # macOS PyInstaller 配置
├── hooks/                # PyInstaller hooks
│   ├── hook-OpenGL.py
│   ├── hook-PyQt5.py
│   ├── hook-live2d.py
│   ├── hook-onnxruntime.py
│   └── rthook-opengl.py
├── resources/            # 打包资源
│   ├── icon.ico          # Windows 图标
│   └── icon.icns         # macOS 图标
└── README.md             # 本文档
```

## 使用方法

### 环境准备

1. 安装 PyInstaller:
```bash
pip install pyinstaller
```

2. (可选) macOS 创建 DMG 需要安装 create-dmg:
```bash
brew install create-dmg
```

### 打包命令

#### 自动检测平台并打包
```bash
python -m package.build_all
```

#### 打包 Windows 版本
```bash
python -m package.build_all --windows
# 或
python -m package.build_windows
```

#### 打包 macOS 版本
```bash
python -m package.build_all --macos
# 或
python -m package.build_macos
```

### 输出位置

打包完成后，文件位于项目根目录的 `dist/` 文件夹:

- Windows: `dist/NagaAgent.exe` 和 `dist/NagaAgent_Win64_YYYYMMDD_HHMMSS.zip`
- macOS: `dist/NagaAgent.app` 和 `dist/NagaAgent_macOS_YYYYMMDD_HHMMSS.dmg`

## 图标文件

如需自定义图标，请将图标文件放置在 `resources/` 目录:

- Windows: `icon.ico` (推荐尺寸: 256x256)
- macOS: `icon.icns` (使用 iconutil 生成)

### 生成 macOS icns 图标

```bash
# 创建 iconset 目录
mkdir icon.iconset

# 准备各种尺寸的 PNG（需要 1024x1024 的源图）
sips -z 16 16     icon_1024.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon_1024.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon_1024.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon_1024.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon_1024.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon_1024.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon_1024.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon_1024.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon_1024.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 icon_1024.png --out icon.iconset/icon_512x512@2x.png

# 生成 icns
iconutil -c icns icon.iconset -o icon.icns
```

## 常见问题

### 1. 打包后体积过大

单文件模式会将所有依赖打包进一个文件，体积较大是正常的。可以考虑:
- 在 spec 文件中添加更多 `excludes`
- 使用 UPX 压缩（已默认启用）

### 2. 运行时缺少模块

如果运行打包后的程序提示缺少模块:
1. 在 spec 文件的 `hiddenimports` 中添加该模块
2. 重新打包

### 3. macOS 首次启动慢

单文件模式需要在启动时解压资源到临时目录，首次启动较慢是正常的。

### 4. Windows 杀毒软件误报

PyInstaller 打包的程序可能被某些杀毒软件误报:
1. 添加程序到信任列表
2. 考虑使用代码签名证书

## 开发说明

### 添加新的 Hook

如果引入了新的依赖库需要特殊处理，可以在 `hooks/` 目录添加相应的 hook 文件:

```python
# hooks/hook-yourlib.py
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules('yourlib')
datas = collect_data_files('yourlib')
```

### 修改打包配置

主要配置在 `spec/` 目录的 spec 文件中:
- `datas`: 需要包含的数据文件
- `hiddenimports`: 动态导入的模块
- `excludes`: 排除的模块（减小体积）
