# Game Guide 攻略引擎测试指南

本文面向测试同学，提供从零开始的环境准备、功能验证、真实场景测试方法和过关标准。

## 目录

- [1. 测试环境要求](#1-测试环境要求)
- [2. 从零开始：安装与配置](#2-从零开始安装与配置)
- [3. 依赖服务准备](#3-依赖服务准备)
- [4. 快速功能验证（无需外部服务）](#4-快速功能验证无需外部服务)
- [5. 新功能测试场景](#5-新功能测试场景)
- [6. 真实场景集成测试](#6-真实场景集成测试)
- [6.7. ChromaDB 向量搜索验证](#67-chromadb-向量搜索验证)
- [6.8. Kantai 海域攻略搜索测试](#68-kantai-海域攻略搜索测试)
- [6.9. Kantai 装备/舰娘搜索测试](#69-kantai-装备舰娘搜索测试)
- [6.10. Kantai 深海栖舰搜索测试](#610-kantai-深海栖舰搜索测试)
- [8. 常见问题排查](#8-常见问题排查)

---

## 1. 测试环境要求

### 1.1 基础环境

- **Python**: 3.11+
- **包管理器**: 推荐使用 `uv`（项目已配置）
- **操作系统**: Linux/macOS/Windows
- **图形环境**: 若测试自动截图功能，需要图形桌面和显示器

### 1.2 外部服务（可选）

| 服务 | 用途 | 必需性 | 说明 |
|------|------|--------|------|
| **Embedding API** | 向量嵌入 | 必需 | OpenAI 兼容接口 |
| **LLM API** | 生成回答 | 集成测试必需 | 支持视觉模型更佳 |
| **Neo4j** | 知识图谱 | 可选 | 不启动会降级，但图谱功能不可用 |
| **ChromaDB** | 向量数据库 | 自动创建 | 本地持久化，无需额外服务 |

---

## 2. 从零开始：安装与配置

### 2.1 安装依赖

```bash
# 推荐方式
uv sync

# 备选方式
pip install -r requirements.txt
```

### 2.2 准备配置文件

```bash
# 复制示例配置
cp config.json.example config.json
```

### 2.3 最小配置示例

编辑 `config.json`，至少配置以下字段：

```jsonc
{
  "api": {
    "base_url": "https://你的模型网关/v1",
    "api_key": "sk-your-api-key",
    "model": "gpt-4o"
  },
  "guide_engine": {
    "enabled": true,
    "chroma_persist_dir": "./data/chroma",

    // Embedding API（必需）
    "embedding_api_base_url": "https://你的网关/v1",
    "embedding_api_key": "sk-your-embedding-key",
    "embedding_api_model": "text-embedding-3-small",

    // 攻略专用LLM（可选，需支持图片输入）
    "game_guide_llm_api_base_url": "https://你的视觉网关/v1",
    "game_guide_llm_api_key": "sk-your-vision-key",
    "game_guide_llm_api_model": "qwen-vl-plus",

    // Neo4j（可选）
    "neo4j_uri": "bolt://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "your_password",

    // 其他配置
    "prompt_dir": "./guide_engine/game_prompts",
    "screenshot_monitor_index": 1,
    "auto_screenshot_on_guide": true
  }
}
```

**配置说明**：

- `embedding_api_*`：向量嵌入服务，必须配置且可用
- `game_guide_llm_api_*`：攻略专用LLM，需支持图片输入，留空则回退到 `api.*` 配置
- `neo4j_*`：图数据库，不配置则图谱功能降级
- `auto_screenshot_on_guide`：默认是否自动截图

---

## 3. 依赖服务准备

### 3.1 Neo4j（推荐启动）

**Docker 快速启动**：

```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:5
```

**验证连接**：

访问 http://localhost:7474，使用 `neo4j/your_password` 登录。

**自动导入说明**：

系统在首次查询时会自动导入基础数据（如果检测到图谱为空）：
- 明日方舟：`data/arknights_cn_operators.json`
- 舰队Collection：`data/kantai-collection_start2.json`

若数据文件不存在，图谱功能会降级但不影响其他功能。

### 3.2 Embedding API（必需）

确保配置的 Embedding API 满足 OpenAI SDK `embeddings.create` 接口规范。

**快速验证**：

```bash
uv run python -c "
import asyncio
from guide_engine.chroma_service import ChromaService

async def test():
    service = ChromaService()
    vec = await service._embed_query('测试文本')
    print(f'向量维度: {len(vec)}')

asyncio.run(test())
"
```

预期输出：`向量维度: 1536`（或其他维度，取决于模型）

---

## 4. 快速功能验证（无需外部服务）

运行纯单元测试脚本，验证新迁移的核心功能：

```bash
uv run python scripts/test_guide_engine_features.py
```

**测试内容**：

1. ✅ **RAG 时效性权重系统** - 时间衰减、版本距离惩罚、内容类型分级
2. ✅ **别名感知实体提取** - 从 YAML 配置读取别名，正确识别干员
3. ✅ **Kantai 地图校验** - 舰C攻略模式缺少地图时触发追问
4. ✅ **Neo4j 格式化方法** - 干员信息、配合推荐格式化
5. ✅ **模组自动选择逻辑** - CalculationParams 支持模组参数

**预期输出**：

```
============================================================
测试结果汇总
============================================================
✅ 通过 - 时效性权重系统
✅ 通过 - 别名感知实体提取
✅ 通过 - Kantai地图校验
✅ 通过 - Neo4j格式化方法
✅ 通过 - 模组自动选择逻辑

总计: 5/5 通过

🎉 所有测试通过！
```

**过关标准**：所有 5 项测试通过。

---

## 5. 新功能测试场景

### 5.1 时效性权重系统

**功能说明**：对 ChromaDB 搜索结果按时效性重新加权排序，新内容权重更高。

**测试方法**：

已在 `test_guide_engine_features.py` 中覆盖，无需额外测试。

**验证点**：

- 无日期文档默认权重 0.7
- 今天发布文档权重接近 1.0
- 1年前活动攻略权重 < 0.3
- 已标记过时文档权重 0.1
- 排序后新内容排在前面

---

### 5.2 别名感知实体提取

**功能说明**：从 `arknights.yaml` 的 `entity_patterns.operator_aliases` 读取别名，支持"老银"→"银灰"等映射。

**测试方法**：

1. 检查配置文件：

```bash
cat guide_engine/game_prompts/arknights.yaml | grep -A 5 operator_aliases
```

预期输出：

```yaml
operator_aliases:
  "银灰": ["老银", "SilverAsh"]
  "能天使": ["能天", "苹果派", "Exusiai"]
  "艾雅法拉": ["羊", "小羊", "Eyjafjalla"]
```

2. 运行单元测试（已在 `test_guide_engine_features.py` 中）

**验证点**：

- "老银配队推荐" 识别出 "银灰"
- "苹果派DPS" 识别出 "能天使"
- `_guess_operator_name()` 支持别名参数

---

### 5.3 Neo4j Graph RAG 并行检索

**功能说明**：使用 `asyncio.gather` 并行执行 ChromaDB 向量搜索 + Neo4j 干员查询 + 配合关系查询。

**测试方法**：

需要 Neo4j 服务运行，参见 [6.3 Neo4j 图谱查询测试](#63-neo4j-图谱查询测试)。

**验证点**：

- ChromaDB 和 Neo4j 查询并行执行（通过日志时间戳验证）
- Neo4j 不可用时不阻塞 ChromaDB 返回
- 返回结果包含干员信息和配合推荐

---

### 5.4 Kantai 地图校验

**功能说明**：舰C攻略模式（FULL）下，若查询不含地图/海域信息，插入追问提示。

**测试方法**：

已在 `test_guide_engine_features.py` 中覆盖。

**验证点**：

- "编成推荐"（无地图）→ 触发追问
- "2-5编成推荐"（有地图）→ 不追问
- "E-3怎么打"（有地图）→ 不追问
- "海域3-2攻略"（有关键词）→ 不追问
- 非舰C游戏 → 不触发
- 非FULL模式 → 不触发

---

### 5.5 模组自动选择 + 详细属性格式化

**功能说明**：计算模式下自动选择干员第一个模组（Lv.3），默认满潜（潜能5），输出详细属性、信赖加成、模组加成。

**测试方法**：

需要游戏数据文件和 LLM API，参见 [6.2 伤害计算测试](#62-伤害计算测试)。

**验证点**：

- 计算结果包含"计算假设"（精英/等级/信赖/潜能）
- 包含"干员基础属性"（ATK/DEF/HP/攻击间隔/阻挡数）
- 包含"信赖加成"明细
- 包含"模组"信息（名称、等级、属性加成）
- 包含"计算后面板"（最终ATK/攻击间隔/单次伤害/DPS）
- 包含"技能数据"（SP/持续/总伤/攻击次数）
- 包含"计算详情"步骤

---

## 6. 真实场景集成测试

### 6.1 MCP 服务注册验证

**测试命令**：

```bash
uv run python -c "
from mcpserver.mcp_registry import auto_register_mcp, get_registered_services
auto_register_mcp()
print(get_registered_services())
"
```

**预期输出**：

```python
['game_guide', 'weather', 'time', ...]
```

**过关标准**：输出列表包含 `game_guide`。

---

### 6.2 伤害计算测试

**前置条件**：

- 已配置 LLM API
- 存在游戏数据文件：`data/arknights/gamedata/character_table.json`、`skill_table.json`、`uniequip_table.json`

**测试命令**：

```bash
uv run python scripts/test_game_guide_tool_call.py \
  --game-id arknights \
  --query "银灰S3专三DPS" \
  --tool-name calculate_damage \
  --test-pic ""
```

**预期输出**：

```
业务状态: ok
query_mode: calculation
response: 【精确计算结果】银灰 - 真银斩（专精三）

计算假设：
- 精英2 Lv.90，信赖200%，潜能5
- 敌人防御0，法抗0%

干员基础属性（精英2 Lv.90）：
- 基础攻击力: 560
- 防御力: 152
- 生命值: 1805
- 基础攻击间隔: 1.3秒
- 阻挡数: 2
- 信赖加成（200%）：攻击力+90

模组：真银斩·改 Lv.3（攻击力+60，攻速+8）

计算后面板：
- 最终攻击力: 1540（包含信赖、天赋、技能加成）
- 攻击间隔: 0.650秒（攻速200）
- 单次伤害: 3080（physical伤害）
- DPS: 4738

技能数据：
- SP消耗: 25，初始SP: 10
- 持续时间: 30秒
- 技能总伤: 142140
- 技能期间约46.2次攻击

计算详情：
- 最终攻击力: 1540
- 攻击间隔: 0.650s (攻速200)
- 单次伤害: 3080 (physical)
- DPS: 4738
```

**过关标准**：

- ✅ `status: ok`
- ✅ `query_mode: calculation`
- ✅ 输出包含"计算假设"、"干员基础属性"、"信赖加成"、"模组"、"计算后面板"、"技能数据"、"计算详情"
- ✅ 潜能显示为 5
- ✅ 模组信息存在且等级为 3

---

### 6.3 Neo4j 图谱查询测试

**前置条件**：

- Neo4j 服务运行中
- 已配置 `neo4j_uri`、`neo4j_user`、`neo4j_password`
- `arknights.yaml` 中 `graph_rag_enabled: true`

**测试命令**：

```bash
uv run python scripts/test_game_guide_tool_call.py \
  --game-id arknights \
  --query "银灰配队推荐" \
  --tool-name ask_guide \
  --test-pic ""
```

**预期输出**：

```
业务状态: ok
query_mode: full
response: 根据知识图谱，银灰的配队推荐如下：

## 干员信息: 银灰
- 稀有度: 5星
- 职业: 近卫
- 分支: 领主
- 特性: 阻挡数+1，可以进行远程攻击
...

## 银灰 的配合推荐
- 推进之王（推荐度 8/10）: 快速再部署配合，银灰S3可以快速清场
- 德克萨斯（推荐度 7/10）: 先锋配合，提供前期费用
...
```

**过关标准**：

- ✅ `status: ok`
- ✅ 输出包含"## 干员信息: 银灰"
- ✅ 输出包含"## 银灰 的配合推荐"
- ✅ 配合推荐包含其他干员名称和推荐理由

**验证 Neo4j 自动导入**：

首次查询时，系统会自动导入 `data/arknights_cn_operators.json`。查看日志：

```
[Neo4j] auto import completed: game_id=arknights, imported=XXX
```

---

### 6.4 别名查询测试

**测试命令**：

```bash
uv run python scripts/test_game_guide_tool_call.py \
  --game-id arknights \
  --query "老银S3专三DPS" \
  --tool-name calculate_damage \
  --test-pic ""
```

**预期输出**：

```
response: 【精确计算结果】银灰 - 真银斩（专精三）
...
```

**过关标准**：

- ✅ "老银" 被正确识别为 "银灰"
- ✅ 计算结果显示 "银灰"

---

### 6.5 Kantai 地图追问测试

**前置条件**：

- `kantai-collection.yaml` 中 `graph_rag_enabled: true`

**测试命令**：

```bash
uv run python scripts/test_game_guide_tool_call.py \
  --game-id kantai-collection \
  --query "编成推荐" \
  --tool-name ask_guide \
  --test-pic ""
```

**预期输出**：

```
response: 【流程要求】这是攻略模式且未给出具体关卡/海域，请先反问用户想打哪个图/海域（例如 2-5、3-2、E-3）。在得到关卡前不要给阵容与配装结论。
```

**过关标准**：

- ✅ 输出包含"反问用户想打哪个图/海域"
- ✅ 输出包含示例地图（2-5、3-2、E-3）

**对比测试（有地图）**：

```bash
uv run python scripts/test_game_guide_tool_call.py \
  --game-id kantai-collection \
  --query "2-5编成推荐" \
  --tool-name ask_guide \
  --test-pic ""
```

预期：不包含追问提示，直接给出编成建议。

---

### 6.7 ChromaDB 向量搜索验证

**功能说明**：验证 ChromaDB 4 个 collection 的向量搜索在不同搜索模式下均能正常返回结果。

**前置条件**：

- Embedding API（Ollama nomic-embed-text-v2-moe）运行中
- ChromaDB 已导入数据（4 个 collection）

**当前 ChromaDB 数据概况**：

| Collection | 文档数 | 内容 |
|------------|--------|------|
| `game_arknights_guides` | 4087 | 干员/敌人（攻略用） |
| `game_arknights` | 4087 | 干员/敌人（Wiki用） |
| `game_kantai_collection` | 1608 | 舰娘831 + 装备717 + 公式24 + 海域36 |
| `game_kantai_collection_enemies` | 841 | 深海栖舰 |

**测试命令（一键验证全部搜索模式）**：

```bash
uv run --no-sync python3 -c "
import asyncio
from guide_engine.chroma_service import ChromaService

async def test():
    s = ChromaService()
    tests = [
        ('arknights', '银灰技能', 'full', '全模式搜索干员'),
        ('arknights', '源石尘感染者', 'wiki_only', 'Wiki搜索敌人'),
        ('arknights', '大鲍勃', 'guides_only', 'Guides搜索BOSS'),
        ('kantai-collection', '2-4带路', 'wiki_only', '海域攻略搜索'),
        ('kantai-collection', '46cm三连装砲', 'wiki_only', '装备搜索'),
        ('kantai-collection', '深海栖舰', 'enemy_only', '深海敌舰搜索'),
        ('kantai-collection', 'getDayBattlePower', 'wiki_only', '伤害公式搜索'),
    ]
    passed = 0
    failed = 0
    for game_id, query, mode, desc in tests:
        results = await s.search(game_id, query, top_k=3, score_threshold=0.3, search_mode=mode)
        if results:
            scores = [f\"{r['score']:.2f}\" for r in results]
            print(f'  OK  {desc}: \"{query}\" -> {len(results)}条 {scores}')
            passed += 1
        else:
            print(f'  FAIL {desc}: \"{query}\" -> 无结果')
            failed += 1
    print(f'\n结果: {passed}/{passed+failed} 通过')

asyncio.run(test())
"
```

**预期输出**：

```
  OK  全模式搜索干员: "银灰技能" -> 3条 ['0.58', '0.55', '0.52']
  OK  Wiki搜索敌人: "源石尘感染者" -> 3条 ['0.49', '0.45', '0.42']
  OK  Guides搜索BOSS: "大鲍勃" -> 3条 ['0.55', '0.50', '0.48']
  OK  海域攻略搜索: "2-4带路" -> 3条 ['0.60', '0.55', '0.50']
  OK  装备搜索: "46cm三连装砲" -> 3条 ['0.65', '0.55', '0.50']
  OK  深海敌舰搜索: "深海栖舰" -> 3条 ['0.55', '0.50', '0.45']
  OK  伤害公式搜索: "getDayBattlePower" -> 3条 ['0.60', '0.55', '0.50']

结果: 7/7 通过
```

（具体分数会有差异，关键是全部显示 OK 且有结果返回）

**过关标准**：7/7 通过，所有搜索模式均有结果返回。

---

### 6.8 Kantai 海域攻略搜索测试

**测试命令**：

```bash
uv run python scripts/test_game_guide_tool_call.py \
  --game-id kantai-collection \
  --query "6-5怎么打 带路条件" \
  --tool-name ask_guide \
  --test-pic ""
```

**预期输出**：

```
[ChromaDB] Found X results for query: 6-5怎么打 带路条件
  [1] 6-5 xxx (score: 0.xx, collection: wiki)
业务状态: ok
```

**过关标准**：

- ✅ ChromaDB 搜到 6-5 海域相关文档
- ✅ LLM 回答包含带路条件、节点、制空值等内容
- ✅ `status: ok`

---

### 6.9 Kantai 装备/舰娘搜索测试

**测试命令**：

```bash
uv run python scripts/test_game_guide_tool_call.py \
  --game-id kantai-collection \
  --query "46cm三连装砲的属性" \
  --tool-name ask_guide \
  --test-pic ""
```

**预期输出**：

```
[ChromaDB] Found X results for query: 46cm三连装砲的属性
  [1] 46cm三连装砲 (score: 0.xx, collection: wiki)
业务状态: ok
```

**过关标准**：

- ✅ 搜到对应装备文档
- ✅ 回答包含火力、命中等属性数值

---

### 6.10 Kantai 深海栖舰搜索测试

**测试命令**：

```bash
uv run python scripts/test_game_guide_tool_call.py \
  --game-id kantai-collection \
  --query "深海双子栖姬的属性" \
  --tool-name ask_guide \
  --test-pic ""
```

**预期输出**：

```
[ChromaDB] Found X results for query: 深海双子栖姬的属性
  [1] xxx (score: 0.xx, collection: enemies)
业务状态: ok
```

**过关标准**：

- ✅ 从 `enemies` collection 搜到深海栖舰数据
- ✅ 回答包含敌舰属性（耐久、装甲、火力等）

---

### 6.6 自动截图测试

**前置条件**：

- 有图形桌面环境
- 或设置 `TEST_PIC_PATH` 环境变量

**测试命令（使用测试图片）**：

```bash
export TEST_PIC_PATH="/path/to/test_image.png"

uv run python scripts/test_game_guide_tool_call.py \
  --game-id arknights \
  --query "这关怎么打" \
  --tool-name ask_guide \
  --test-pic "/path/to/test_image.png"
```

**预期输出**：

```
metadata: {"auto_screenshot": {"width": 1920, "height": 1080, "monitor_index": 1, "source": "env:TEST_PIC_PATH"}}
```

**过关标准**：

- ✅ `metadata.auto_screenshot` 存在
- ✅ `source: "env:TEST_PIC_PATH"`

---

## 7. 过关标准

### 7.1 P0 级别（必须通过）

| 测试项 | 验证方法 | 过关标准 |
|--------|----------|----------|
| **MCP 服务注册** | 运行注册验证脚本 | 输出包含 `game_guide` |
| **功能单元测试** | `test_guide_engine_features.py` | 5/5 通过 |
| **基础查询** | `ask_guide` 工具调用 | `status: ok` |
| **ChromaDB 向量搜索** | 一键验证脚本（6.7节） | 7/7 搜索模式均有结果 |

### 7.2 P1 级别（重要功能）

| 测试项 | 验证方法 | 过关标准 |
|--------|----------|----------|
| **伤害计算** | 查询"银灰S3专三DPS" | 输出包含详细属性、模组、潜能5 |
| **别名识别** | 查询"老银S3专三DPS" | 正确识别为"银灰" |
| **Neo4j 图谱** | 查询"银灰配队推荐" | 输出包含干员信息和配合推荐 |
| **Kantai 地图校验** | 查询"编成推荐"（无地图） | 触发追问提示 |
| **Kantai 海域搜索** | 查询"6-5怎么打 带路条件" | 搜到海域数据并返回攻略 |
| **Kantai 装备搜索** | 查询"46cm三连装砲的属性" | 搜到装备并返回属性 |
| **Kantai 深海搜索** | 查询"深海双子栖姬" | 从 enemies collection 搜到数据 |

### 7.3 P2 级别（增强功能）

| 测试项 | 验证方法 | 过关标准 |
|--------|----------|----------|
| **自动截图** | 设置 `TEST_PIC_PATH` | `metadata.auto_screenshot` 存在 |
| **时效性排序** | 单元测试已覆盖 | 新内容排在前面 |

---

## 8. 常见问题排查

### 8.1 依赖问题

**问题**：`ModuleNotFoundError: No module named 'xxx'`

**解决**：

```bash
uv sync
# 或
pip install -r requirements.txt
```

---

### 8.2 Embedding API 失败

**问题**：`ChromaDB search failed: Embedding API error`

**排查步骤**：

1. 检查配置：

```bash
cat config.json | grep -A 3 embedding_api
```

2. 验证 API 可用性：

```bash
curl -X POST "https://你的网关/v1/embeddings" \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"input": "test", "model": "text-embedding-3-small"}'
```

3. 检查日志：

```bash
tail -f logs/app.log | grep -i embedding
```

---

### 8.3 Neo4j 连接失败

**问题**：`Neo4j connection failed`

**排查步骤**：

1. 检查 Neo4j 服务状态：

```bash
docker ps | grep neo4j
```

2. 验证连接：

```bash
curl http://localhost:7474
```

3. 检查配置：

```bash
cat config.json | grep -A 3 neo4j
```

4. 查看 Neo4j 日志：

```bash
docker logs neo4j
```

**注意**：Neo4j 不可用时，系统会降级但不影响其他功能。

---

### 8.4 游戏数据文件缺失

**问题**：`[GameDataLoader] 警告: character_table.json 不存在`

**解决**：

从 ArknightsGameData 仓库下载数据文件：

```bash
# 创建目录
mkdir -p data/arknights/gamedata

# 下载数据文件（示例）
wget https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/character_table.json \
  -O data/arknights/gamedata/character_table.json

wget https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/skill_table.json \
  -O data/arknights/gamedata/skill_table.json

wget https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/uniequip_table.json \
  -O data/arknights/gamedata/uniequip_table.json
```

---

### 8.5 自动截图失败

**问题**：`metadata.auto_screenshot_error: No display found`

**原因**：无图形桌面环境（如 SSH 服务器）

**解决**：使用 `TEST_PIC_PATH` 替代真实截图：

```bash
export TEST_PIC_PATH="/path/to/test_image.png"
```

---

### 8.6 LLM API 超时

**问题**：`LLM API timeout`

**排查步骤**：

1. 检查网络连接
2. 增加超时时间（在 `config.json` 中配置）
3. 切换到更快的模型
4. 检查 API 配额

---

## 9. 回归检查点

每次代码变更后，确保以下功能不受影响：

- ✅ MCP 服务注册正常
- ✅ `/chat/stream` 接口正常返回
- ✅ `config.json` 热更新生效
- ✅ 其他 MCP 服务（weather、time）不受影响
- ✅ 功能单元测试全部通过

---

## 10. 测试报告模板

```markdown
# Game Guide 测试报告

**测试日期**: YYYY-MM-DD
**测试人员**: XXX
**测试环境**: Linux/macOS/Windows

## 测试结果

### P0 级别
- [ ] MCP 服务注册: ✅/❌
- [ ] 功能单元测试: 5/5 通过 ✅/❌
- [ ] 基础查询: ✅/❌

### P1 级别
- [ ] 伤害计算（模组+潜能5）: ✅/❌
- [ ] 别名识别: ✅/❌
- [ ] Neo4j 图谱查询: ✅/❌
- [ ] Kantai 地图校验: ✅/❌

### P2 级别
- [ ] 自动截图: ✅/❌
- [ ] 时效性排序: ✅/❌

## 问题记录

| 问题描述 | 严重程度 | 状态 |
|----------|----------|------|
| XXX | P0/P1/P2 | 待修复/已修复 |

## 备注

（其他说明）
```

---

## 附录：快速命令参考

```bash
# 1. 安装依赖
uv sync

# 2. 功能单元测试
uv run python scripts/test_guide_engine_features.py

# 3. MCP 服务注册验证
uv run python -c "from mcpserver.mcp_registry import auto_register_mcp, get_registered_services; auto_register_mcp(); print(get_registered_services())"

# 4. ChromaDB 向量搜索一键验证（7项搜索模式）
uv run --no-sync python3 -c "
import asyncio
from guide_engine.chroma_service import ChromaService
async def test():
    s = ChromaService()
    tests = [
        ('arknights', '银灰技能', 'full', '全模式搜索干员'),
        ('arknights', '源石尘感染者', 'wiki_only', 'Wiki搜索敌人'),
        ('arknights', '大鲍勃', 'guides_only', 'Guides搜索BOSS'),
        ('kantai-collection', '2-4带路', 'wiki_only', '海域攻略搜索'),
        ('kantai-collection', '46cm三连装砲', 'wiki_only', '装备搜索'),
        ('kantai-collection', '深海栖舰', 'enemy_only', '深海敌舰搜索'),
        ('kantai-collection', 'getDayBattlePower', 'wiki_only', '伤害公式搜索'),
    ]
    passed = 0
    for game_id, query, mode, desc in tests:
        results = await s.search(game_id, query, top_k=3, score_threshold=0.3, search_mode=mode)
        status = 'OK' if results else 'FAIL'
        passed += 1 if results else 0
        scores = [f\"{r['score']:.2f}\" for r in results] if results else []
        print(f'  {status}  {desc}: \"{query}\" -> {len(results)}条 {scores}')
    print(f'\n结果: {passed}/{len(tests)} 通过')
asyncio.run(test())
"

# 5. 伤害计算测试
uv run python scripts/test_game_guide_tool_call.py --game-id arknights --query "银灰S3专三DPS" --tool-name calculate_damage --test-pic ""

# 6. 别名识别测试
uv run python scripts/test_game_guide_tool_call.py --game-id arknights --query "老银S3专三DPS" --tool-name calculate_damage --test-pic ""

# 7. 配队推荐测试（明日方舟）
uv run python scripts/test_game_guide_tool_call.py --game-id arknights --query "推荐一个高难图的地面队" --tool-name get_team_recommendation --test-pic ""

# 8. Neo4j 图谱测试
uv run python scripts/test_game_guide_tool_call.py --game-id arknights --query "银灰配队推荐" --tool-name ask_guide --test-pic ""

# 9. Kantai 地图校验测试（无地图，应追问）
uv run python scripts/test_game_guide_tool_call.py --game-id kantai-collection --query "编成推荐" --tool-name ask_guide --test-pic ""

# 10. Kantai 海域攻略测试
uv run python scripts/test_game_guide_tool_call.py --game-id kantai-collection --query "6-5怎么打 带路条件" --tool-name ask_guide --test-pic ""

# 11. Kantai 装备查询测试
uv run python scripts/test_game_guide_tool_call.py --game-id kantai-collection --query "46cm三连装砲的属性" --tool-name ask_guide --test-pic ""

# 12. Kantai 深海栖舰测试
uv run python scripts/test_game_guide_tool_call.py --game-id kantai-collection --query "深海双子栖姬的属性" --tool-name ask_guide --test-pic ""

# 13. 启动 Neo4j
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/your_password neo4j:5
```
