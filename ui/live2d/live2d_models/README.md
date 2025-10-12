# Live2D模型文件夹

这是NAGA Agent项目的独立Live2D模型文件夹，不依赖外部的Live2D-Virtual-Girlfriend项目。

## 文件夹结构

```
live2d_models/
├── characters/           # 角色文件夹
│   ├── llny/            # llny角色
│   │   ├── llny.json    # 角色配置文件
│   │   ├── exp.json     # 表情配置文件
│   │   ├── mianfeimox/  # 模型文件夹
│   │   │   ├── llny.model3.json    # 主模型文件
│   │   │   ├── llny.moc3           # 模型数据
│   │   │   ├── llny.physics3.json  # 物理配置
│   │   │   ├── expressions/        # 表情文件夹
│   │   │   ├── motions/            # 动作文件夹
│   │   │   └── llny.4096/          # 纹理文件夹
│   │   └── 人设.txt     # 角色设定
│   └── cat/             # cat角色
│       ├── cat.json     # 角色配置文件
│       ├── exp.json     # 表情配置文件
│       ├── whitecatfree_vts/  # 模型文件夹
│       │   ├── sdwhite cat free.model3.json  # 主模型文件
│       │   ├── SDwhite cat free.moc3         # 模型数据
│       │   ├── SDwhite cat free.physics3.json # 物理配置
│       │   └── SDwhite cat free.2048/        # 纹理文件夹
│       └── 人设.txt     # 角色设定
└── README.md            # 说明文档
```

## 使用方法

### 在配置文件中设置Live2D模型路径

```json
{
  "live2d": {
    "enabled": true,
    "model_path": "live2d_models/characters/llny/mianfeimox/llny.model3.json",
    "fallback_image": "ui/standby.png"
  }
}
```

### 可用的模型

1. **llny模型**：
   - 路径：`live2d_models/characters/llny/mianfeimox/llny.model3.json`
   - 特点：完整的表情和动作支持

2. **cat模型**：
   - 路径：`live2d_models/characters/cat/whitecatfree_vts/sdwhite cat free.model3.json`
   - 特点：简洁的猫娘角色

## 注意事项

1. 所有模型文件都是独立的，不依赖外部项目
2. 模型文件路径使用相对路径，基于项目根目录
3. 支持.model3.json格式的Live2D模型
4. 包含完整的纹理、动作和表情文件
