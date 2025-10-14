# 系统托盘模块使用说明

## 概述
系统托盘模块提供了完整的托盘功能，包括系统托盘图标、菜单、自启动功能等。支持两种模式：
- **GUI窗口托盘**：将PyQt主窗口隐藏到托盘
- **控制台托盘**：将终端控制台窗口隐藏到托盘

## 文件结构
```
ui/tray/
├── __init__.py              # 模块初始化文件
├── system_tray.py           # GUI窗口托盘核心功能
├── console_tray.py          # 控制台托盘核心功能
├── tray_integration.py      # GUI托盘集成模块
├── auto_start.py            # 自启动管理模块
└── README.md               # 使用说明文档
```

## 功能特性

### 1. GUI窗口托盘功能
- 系统托盘图标显示
- 右键菜单操作
- 双击显示主窗口
- 托盘消息通知

### 2. 控制台托盘功能
- 控制台窗口隐藏/显示
- 系统托盘图标管理
- 右键菜单操作
- 自启动功能

### 3. 自启动功能
- 注册表方式自启动
- 任务计划程序自启动
- 启动文件夹自启动
- 自启动状态管理

### 4. 窗口管理
- 最小化到托盘
- 从托盘恢复窗口
- 关闭确认对话框

## 使用方法

### GUI窗口托盘集成
```python
from ui.tray.tray_integration import integrate_tray_to_window

# 在主窗口创建后集成托盘功能
tray_integration = integrate_tray_to_window(main_window)
```

### 控制台托盘集成
```python
from ui.tray.console_tray import integrate_console_tray

# 集成控制台托盘功能
console_tray = integrate_console_tray()
```

### 使用装饰器
```python
from ui.tray.tray_integration import create_tray_enabled_app

@create_tray_enabled_app
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 窗口初始化代码
```

### 自启动管理
```python
from ui.tray.auto_start import get_auto_start_manager

# 获取自启动管理器
auto_start = get_auto_start_manager("registry")

# 启用自启动
auto_start.enable()

# 禁用自启动
auto_start.disable()

# 检查状态
if auto_start.is_enabled():
    print("自启动已启用")
```

## 启动方式

### 1. 普通启动（带控制台托盘）
```bash
# 使用start_with_tray.bat启动
start_with_tray.bat
```

### 2. 无控制台启动
```bash
# 使用pythonw启动（推荐）
pythonw main.py
```

### 3. 直接启动
```bash
# 直接使用python启动
python main.py
```

## 依赖库
```bash
pip install pystray pillow PyQt5
```

## 配置说明

### 托盘图标
- 默认使用 `ui/window_icon.png`
- 备用图标 `ui/standby.png`
- 支持自定义图标路径

### 自启动方式
1. **注册表方式**（推荐）：使用Windows注册表
2. **任务计划程序**：使用Windows任务计划
3. **启动文件夹**：使用启动文件夹快捷方式

### 托盘菜单
- 显示主窗口/控制台
- 隐藏到托盘
- 开机自启动开关
- 退出应用

## 控制台托盘功能

### 特性
- 自动检测控制台窗口句柄
- 支持隐藏/显示控制台窗口
- 托盘图标右键菜单
- 双击显示控制台

### 使用方法
1. 运行 `start_with_tray.bat`
2. 系统启动后会在托盘显示图标
3. 右键托盘图标选择"隐藏控制台"
4. 双击托盘图标或选择"显示控制台"恢复

### 快捷键
- 双击托盘图标：显示控制台
- 右键托盘图标：显示菜单

## 注意事项

1. **权限要求**：自启动功能需要管理员权限
2. **图标格式**：支持PNG、ICO等格式
3. **Pythonw启动**：建议使用pythonw.exe启动以隐藏控制台
4. **错误处理**：模块包含完整的异常处理
5. **控制台窗口**：控制台托盘功能需要控制台窗口句柄

## 故障排除

### 托盘图标不显示
- 检查图标文件是否存在
- 确认PyQt5安装正确
- 检查系统托盘区域是否可见

### 控制台托盘不工作
- 确认使用控制台模式启动
- 检查控制台窗口句柄获取
- 验证Windows API调用权限

### 自启动失败
- 确认管理员权限
- 检查注册表权限
- 验证启动路径正确性

### 窗口最小化问题
- 检查托盘集成是否正确
- 确认事件处理函数
- 验证窗口状态管理

## 更新日志

### v1.1.0
- 新增控制台托盘功能
- 支持控制台窗口隐藏/显示
- 优化托盘菜单结构
- 添加启动脚本

### v1.0.0
- 初始版本发布
- 基础托盘功能
- 自启动管理
- 窗口集成支持
