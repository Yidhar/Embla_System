# Live2D 模型文件夹

Live2D 模型存放在 `ui/live2d/live2d_models/` 下。仓库内自带一个示例模型 `kasane_teto`，其结构与官方 Cubism 导出的目录一致，可作为导入新模型的参考。

## 当前目录示例

```
live2d_models/
├── README.md
└── kasane_teto/
    ├── kasane_teto.model3.json
    ├── kasane_teto.moc3
    ├── kasane_teto.physics3.json
    ├── Expressions/
    │   ├── *.exp3.json
    └── Motions/
        ├── *.motion3.json
```

> 📌 **提示**：如果你的模型有额外的 `Textures/`、`Pose/`、`HitAreas/` 等目录，请原样放置在模型文件夹内，保持相对路径不变即可。

## 添加自定义模型

1. 将完整的模型目录复制到 `ui/live2d/live2d_models/<你的模型名>/`。确保 `.model3.json` 内引用的文件（贴图、表情、动作等）都存在于该目录中。
2. 在主配置（`config.json` 或 `.local` 覆盖）中启用 Live2D，并指向新的模型路径：

```json
{
  "live2d": {
    "enabled": true,
    "model_path": "ui/live2d/live2d_models/<你的模型名>/<模型文件>.model3.json",
    "fallback_image": "ui/img/standby.png",
    "scale_factor": 1.0
  }
}
```

> 相对路径会自动基于项目根目录解析，也支持包含中文/日文等非 ASCII 字符的目录名。

3. 若需要在 `live2d_config.json` 中配置测试数据，请同步更新 `model.default_model_path` 并把 `module_enabled` 置为 `true`。

## 验证步骤

1. 启动桌面端，确认日志中出现 `Live2D 配置对话框加载动作`，并能列出 `motions`、`expressions` 数量。
2. 打开动作配置对话框，检查 `全部 / 动作 / 表情` 标签是否显示刚导入的项目。
3. 在侧栏面板选择并触发动作或表情，确认模型能正确响应。

## 常见问题

- **模型路径包含非 ASCII 字符**：从 v4.0 起加载逻辑已支持非 ASCII 路径，不会再强制回退到 `kasane_teto`。若仍加载失败，请检查路径是否指向真实存在的 `.model3.json`。
- **动作/表情数量为 0**：确保 `model3.json` 的 `FileReferences` 中声明了 `Motions` / `Expressions`，或者对应目录下有 `.motion3.json` / `.exp3.json` 文件。
- **依赖缺失**：确认安装 `live2d-py` 与 `PyQt5`，否则系统会自动回退到图片模式。
