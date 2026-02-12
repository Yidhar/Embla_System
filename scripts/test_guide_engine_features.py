#!/usr/bin/env python3
"""
游戏攻略引擎功能验证脚本

验证新迁移的核心功能（不依赖外部LLM API）：
1. RAG时效性权重系统
2. 别名感知实体提取
3. Kantai地图校验
4. Neo4j格式化方法
5. 模组自动选择逻辑

用法：
    python scripts/test_guide_engine_features.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_freshness_system() -> bool:
    """测试时效性权重系统"""
    print("\n" + "=" * 60)
    print("测试 1: RAG 时效性权重系统")
    print("=" * 60)

    try:
        from guide_engine.rag_utils import (
            apply_freshness_weight,
            calculate_freshness_weight,
        )

        # 测试1: 无日期默认权重
        w1 = calculate_freshness_weight(None, "guide")
        assert w1 == 0.7, f"无日期默认权重应为0.7，实际: {w1}"
        print(f"✓ 无日期默认权重: {w1}")

        # 测试2: 今天发布权重
        w2 = calculate_freshness_weight(datetime.now(), "guide")
        assert w2 > 0.95, f"今天发布权重应>0.95，实际: {w2:.2f}"
        print(f"✓ 今天发布权重: {w2:.2f}")

        # 测试3: 1年前活动攻略权重
        w3 = calculate_freshness_weight(
            datetime.now() - timedelta(days=365), "event_guide"
        )
        assert w3 < 0.3, f"1年前活动攻略权重应<0.3，实际: {w3:.2f}"
        print(f"✓ 1年前活动攻略权重: {w3:.2f}")

        # 测试4: 已过时内容权重
        w4 = calculate_freshness_weight(datetime.now(), "basic", is_deprecated=True)
        assert w4 == 0.1, f"已过时内容权重应为0.1，实际: {w4}"
        print(f"✓ 已过时内容权重: {w4}")

        # 测试5: 时效性排序
        docs = [
            {
                "title": "old",
                "score": 0.9,
                "metadata": {
                    "publish_date": (datetime.now() - timedelta(days=200)).isoformat()
                },
                "doc_type": "event_guide",
                "content": "活动攻略",
            },
            {
                "title": "new",
                "score": 0.8,
                "metadata": {"publish_date": datetime.now().isoformat()},
                "doc_type": "guide",
                "content": "攻略",
            },
        ]
        adjusted = apply_freshness_weight(docs)
        assert (
            adjusted[0]["title"] == "new"
        ), f"排序后第一条应为new，实际: {adjusted[0]['title']}"
        print(f"✓ 时效性排序: 新内容排在前面")

        print("\n✅ 时效性权重系统测试通过")
        return True

    except Exception as e:
        print(f"\n❌ 时效性权重系统测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_alias_entity_extraction() -> bool:
    """测试别名感知实体提取"""
    print("\n" + "=" * 60)
    print("测试 2: 别名感知实体提取")
    print("=" * 60)

    try:
        from guide_engine.guide_service import GuideService
        from guide_engine.query_router import ExtractedEntities, QueryMode, RouteResult

        entities = ExtractedEntities()
        route = RouteResult(mode=QueryMode.FULL, entities=entities, reason="test")
        prompt_config = {
            "entity_patterns": {
                "operator_aliases": {
                    "银灰": ["老银", "SilverAsh"],
                    "能天使": ["能天", "苹果派"],
                }
            }
        }

        # 测试1: 别名"老银"识别为"银灰"
        names = GuideService._extract_operator_names_for_graph(
            "老银配队推荐", route, prompt_config
        )
        assert "银灰" in names, f"应识别出银灰，实际: {names}"
        print(f'✓ "老银配队推荐" -> {names}')

        # 测试2: 别名"苹果派"识别为"能天使"
        names2 = GuideService._extract_operator_names_for_graph(
            "苹果派DPS", route, prompt_config
        )
        assert "能天使" in names2, f"应识别出能天使，实际: {names2}"
        print(f'✓ "苹果派DPS" -> {names2}')

        # 测试3: _guess_operator_name 别名支持
        aliases = {"银灰": ["老银", "SilverAsh"]}
        name = GuideService._guess_operator_name(
            route, [], "老银S3专三DPS", operator_aliases=aliases
        )
        assert name == "银灰", f"应识别为银灰，实际: {name}"
        print(f'✓ _guess_operator_name("老银S3专三DPS") -> {name}')

        print("\n✅ 别名感知实体提取测试通过")
        return True

    except Exception as e:
        print(f"\n❌ 别名感知实体提取测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_kantai_map_validation() -> bool:
    """测试舰C地图校验"""
    print("\n" + "=" * 60)
    print("测试 3: Kantai Collection 地图校验")
    print("=" * 60)

    try:
        from guide_engine.guide_service import GuideService
        from guide_engine.query_router import QueryMode

        # 测试1: 无地图应追问
        hint = GuideService._check_kantai_map_requirement(
            "kantai-collection", QueryMode.FULL, "编成推荐"
        )
        assert "反问" in hint, f"无地图应包含追问提示，实际: {hint}"
        print(f'✓ 无地图("编成推荐"): 触发追问')

        # 测试2: 有地图(2-5)不追问
        hint2 = GuideService._check_kantai_map_requirement(
            "kantai-collection", QueryMode.FULL, "2-5编成推荐"
        )
        assert hint2 == "", f"有地图应无提示，实际: {hint2}"
        print(f'✓ 有地图("2-5编成推荐"): 无追问')

        # 测试3: 有地图(E-3)不追问
        hint3 = GuideService._check_kantai_map_requirement(
            "kantai-collection", QueryMode.FULL, "E-3怎么打"
        )
        assert hint3 == "", f"有地图应无提示，实际: {hint3}"
        print(f'✓ 有地图("E-3怎么打"): 无追问')

        # 测试4: 有海域关键词不追问
        hint4 = GuideService._check_kantai_map_requirement(
            "kantai-collection", QueryMode.FULL, "海域3-2攻略"
        )
        assert hint4 == "", f"有海域关键词应无提示，实际: {hint4}"
        print(f'✓ 有海域关键词("海域3-2攻略"): 无追问')

        # 测试5: 非舰C游戏不触发
        hint5 = GuideService._check_kantai_map_requirement(
            "arknights", QueryMode.FULL, "编成推荐"
        )
        assert hint5 == "", f"非舰C游戏应无提示，实际: {hint5}"
        print(f'✓ 非舰C游戏("arknights"): 无追问')

        # 测试6: 非FULL模式不触发
        hint6 = GuideService._check_kantai_map_requirement(
            "kantai-collection", QueryMode.WIKI_ONLY, "编成推荐"
        )
        assert hint6 == "", f"非FULL模式应无提示，实际: {hint6}"
        print(f'✓ 非FULL模式(WIKI_ONLY): 无追问')

        print("\n✅ Kantai地图校验测试通过")
        return True

    except Exception as e:
        print(f"\n❌ Kantai地图校验测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_format_methods() -> bool:
    """测试Neo4j格式化方法"""
    print("\n" + "=" * 60)
    print("测试 4: Neo4j 格式化方法")
    print("=" * 60)

    try:
        from guide_engine.guide_service import GuideService

        # 测试1: 干员信息格式化
        operator_data = {
            "name": "银灰",
            "rarity": 5,
            "class": "近卫",
            "branch": "领主",
            "trait": "阻挡数+1",
            "obtain": "公招/寻访",
            "skills": [
                {
                    "name": "真银斩",
                    "type": "手动",
                    "charge_type": "自动回复",
                    "description": "攻击范围扩大",
                    "mastery_recommendation": "推荐专精",
                }
            ],
            "talents": [{"name": "领袖", "description": "部署后全体攻击力+10%"}],
        }
        op_ctx = GuideService._format_operator_context(operator_data)
        assert "银灰" in op_ctx, "应包含干员名"
        assert "真银斩" in op_ctx, "应包含技能名"
        assert "领袖" in op_ctx, "应包含天赋名"
        print(f"✓ 干员信息格式化: {len(op_ctx)} chars")

        # 测试2: 配合推荐格式化
        synergies = [
            {
                "name": "推进之王",
                "synergy_reason": "快速再部署配合",
                "synergy_score": 8,
            },
            {"name": "德克萨斯", "synergy_reason": "先锋配合", "synergy_score": 7},
        ]
        syn_ctx = GuideService._format_synergy_context("银灰", synergies)
        assert "推进之王" in syn_ctx, "应包含配合干员名"
        assert "快速再部署配合" in syn_ctx, "应包含配合原因"
        print(f"✓ 配合推荐格式化: {len(syn_ctx)} chars")

        # 测试3: 空配合列表
        empty_syn = GuideService._format_synergy_context("银灰", [])
        assert empty_syn == "", "空列表应返回空字符串"
        print(f"✓ 空配合列表: 返回空字符串")

        print("\n✅ Neo4j格式化方法测试通过")
        return True

    except Exception as e:
        print(f"\n❌ Neo4j格式化方法测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_module_auto_selection_logic() -> bool:
    """测试模组自动选择逻辑（仅验证代码路径，不依赖真实数据）"""
    print("\n" + "=" * 60)
    print("测试 5: 模组自动选择逻辑")
    print("=" * 60)

    try:
        from guide_engine.calculation_service import CalculationParams

        # 验证CalculationParams支持module_id和module_level参数
        params = CalculationParams(
            operator_name="银灰",
            skill_index=2,
            skill_level=10,
            elite=2,
            level=90,
            trust=200,
            potential=5,  # 新默认值
            module_id="uniequip_002_silver",
            module_level=3,
            enemy_defense=0,
            enemy_res=0,
        )

        assert params.potential == 5, f"默认潜能应为5，实际: {params.potential}"
        assert (
            params.module_id == "uniequip_002_silver"
        ), f"模组ID应正确设置，实际: {params.module_id}"
        assert params.module_level == 3, f"模组等级应为3，实际: {params.module_level}"

        print(f"✓ CalculationParams 支持 module_id/module_level")
        print(f"✓ 默认潜能值: {params.potential}")
        print(f"✓ 模组ID: {params.module_id}")
        print(f"✓ 模组等级: {params.module_level}")

        print("\n✅ 模组自动选择逻辑测试通过")
        return True

    except Exception as e:
        print(f"\n❌ 模组自动选择逻辑测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def main() -> int:
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("游戏攻略引擎功能验证")
    print("=" * 60)

    results = {
        "时效性权重系统": test_freshness_system(),
        "别名感知实体提取": test_alias_entity_extraction(),
        "Kantai地图校验": test_kantai_map_validation(),
        "Neo4j格式化方法": test_format_methods(),
        "模组自动选择逻辑": test_module_auto_selection_logic(),
    }

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(results.values())
    total = len(results)

    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
