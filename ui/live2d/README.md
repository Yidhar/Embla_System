# Live2D集成模块

这是NAGA Agent项目中独立的Live2D集成模块，不依赖外部的Live2D-Virtual-Girlfriend项目。

## 模块结构

```
ui/live2d/
├── __init__.py          # 模块初始化文件
├── renderer.py          # Live2D渲染器
├── animator.py          # 动画系统
├── widget.py            # Live2D Widget组件
├── live2d_models/       # Live2D模型文件夹
│   └── characters/      # 角色模型
│       ├── llny/        # llny角色
│       └── cat/         # cat角色
└── README.md            # 说明文档
```

## 主要组件

### 1. Live2DRenderer (renderer.py)
- 负责Live2D模型的加载、渲染和基础操作
- 提供模型参数设置、动作触发等功能
- 独立于UI组件，可复用

### 2. Live2DAnimator (animator.py)
- 动画系统管理器
- 包含多种动画器：
  - `BlinkAnimator`: 眨眼动画
  - `EyeBallAnimator`: 眼球跟踪动画
  - `BodyAngleAnimator`: 身体摆动动画
  - `BreathAnimator`: 呼吸动画
  - `EmotionAnimator`: 情绪动画

### 3. Live2DWidget (widget.py)
- 基于QGLWidget的Live2D显示组件
- 集成渲染器和动画系统
- 提供鼠标交互功能

## 使用方法

### 基本使用
```python
from ui.live2d import Live2DWidget

# 创建Live2D Widget
live2d_widget = Live2DWidget(parent)

# 加载模型
success = live2d_widget.load_model("path/to/model.model3.json")

# 设置情绪
live2d_widget.set_emotion("happy", intensity=0.8)

# 触发动作
live2d_widget.trigger_motion("tap", 0)
```

### 在Live2DSideWidget中使用
```python
from ui.live2d_side_widget import Live2DSideWidget

# 创建侧栏Widget
side_widget = Live2DSideWidget()

# 设置Live2D模型
side_widget.set_live2d_model("ui/live2d/live2d_models/characters/llny/mianfeimox/llny.model3.json")

# 设置回退图片
side_widget.set_fallback_image("path/to/image.png")
```

## 特性

- ✅ 独立的模块设计，不依赖外部项目
- ✅ 完整的动画系统支持
- ✅ 鼠标交互功能
- ✅ 自动回退到图片模式
- ✅ 资源管理和清理
- ✅ 错误处理和日志记录

## 依赖要求

- `live2d-py`: Live2D Python绑定
- `PyQt5`: GUI框架
- `opensimplex`: 噪声生成（可选，用于更自然的动画）

### 噪声模块安装

为了获得最佳的动画效果，建议安装噪声模块：

```bash
# 安装opensimplex（纯Python实现，无需编译）
pip install opensimplex
```

**注意**：如果没有安装opensimplex模块，系统会自动降级到简化模式，使用正弦波生成动画。

## 配置

Live2D功能可以通过配置文件启用：

```json
{
  "live2d": {
    "enabled": true,
    "model_path": "ui/live2d/live2d_models/characters/llny/mianfeimox/llny.model3.json",
    "fallback_image": "ui/standby.png"
  }
}
```

## 注意事项

1. 确保已安装`live2d-py`包
2. 模型文件路径必须正确
3. 如果Live2D不可用，会自动回退到图片模式
4. 动画系统需要噪声模块支持，但可以降级运行
