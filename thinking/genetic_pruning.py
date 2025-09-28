"""
遗传算法剪枝系统
基于适应度选择最优思考方案并进行遗传进化
"""

import random
import logging
from typing import List, Dict, Tuple, Optional
from .thinking_node import ThinkingNode, ThinkingBranch, ThinkingGeneration
from .config import TREE_THINKING_CONFIG

# numpy导入（可选，用于统计计算）
try:
    import nagaagent_core.vendors.numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    # fallback实现
    class np:
        @staticmethod
        def mean(data):
            return sum(data) / len(data) if data else 0

logger = logging.getLogger("GeneticPruning")

class GeneticPruning:
    """遗传算法剪枝器"""
    
    def __init__(self, api_client=None):
        self.api_client = api_client
        self.config = TREE_THINKING_CONFIG
        
        # 遗传算法参数
        self.selection_rate = self.config["selection_rate"]
        self.mutation_rate = self.config["mutation_rate"]
        self.crossover_rate = self.config["crossover_rate"]
        self.max_generations = self.config["max_generations"]
        
        # 进化历史
        self.generations: List[ThinkingGeneration] = []
        self.current_generation = 0
        
        print("[TreeThinkingEngine] 🧬 遗传算法剪枝系统初始化完成")
    
    async def evolve_thinking_tree(self, initial_nodes: List[ThinkingNode], 
                                  target_count: int = 3) -> List[ThinkingNode]:
        """
        对思考树进行遗传进化
        返回进化后的最优节点列表
        """
        try:
            if not initial_nodes:
                return []
            
            logger.info(f"开始遗传进化 - 初始节点: {len(initial_nodes)}, 目标数量: {target_count}")
            
            # 计算初始适应度
            await self._calculate_fitness(initial_nodes)
            
            # 创建初始代
            initial_generation = ThinkingGeneration(generation_id=0)
            initial_branch = ThinkingBranch()
            
            for node in initial_nodes:
                initial_branch.add_node(node)
            
            initial_generation.add_branch(initial_branch)
            self.generations.append(initial_generation)
            
            current_nodes = initial_nodes.copy()
            
            # 进化循环
            for generation_id in range(1, self.max_generations + 1):
                self.current_generation = generation_id
                
                logger.info(f"进化第 {generation_id} 代...")
                
                # 选择
                selected_nodes = self._selection(current_nodes, target_count * 2)
                
                # 交叉
                crossover_nodes = await self._crossover(selected_nodes)
                
                # 变异
                mutated_nodes = await self._mutation(crossover_nodes)
                
                # 合并并重新评估
                all_nodes = selected_nodes + crossover_nodes + mutated_nodes
                await self._calculate_fitness(all_nodes)
                
                # 精英保留策略
                current_nodes = self._elite_selection(all_nodes, target_count)
                
                # 记录当代
                gen = ThinkingGeneration(generation_id=generation_id)
                branch = ThinkingBranch()
                for node in current_nodes:
                    branch.add_node(node)
                gen.add_branch(branch)
                self.generations.append(gen)
                
                # 检查收敛条件
                if self._check_convergence(generation_id):
                    logger.info(f"在第 {generation_id} 代达到收敛")
                    break
            
            # 返回最终结果
            final_nodes = self._elite_selection(current_nodes, target_count)
            
            logger.info(f"遗传进化完成 - 最终节点数: {len(final_nodes)}")
            return final_nodes
            
        except Exception as e:
            logger.error(f"遗传进化失败: {e}")
            # 返回原始最优节点
            return self._elite_selection(initial_nodes, target_count)
    
    async def _calculate_fitness(self, nodes: List[ThinkingNode]):
        """计算节点适应度"""
        for node in nodes:
            # 多维度适应度计算
            fitness_score = 0.0
            
            # 内容质量 (40%)
            content_fitness = self._evaluate_content_quality(node.content)
            fitness_score += content_fitness * 0.4
            
            # 多样性贡献 (30%)
            diversity_fitness = self._evaluate_diversity(node, nodes)
            fitness_score += diversity_fitness * 0.3
            
            # 创新程度 (20%)
            innovation_fitness = self._evaluate_innovation(node.content)
            fitness_score += innovation_fitness * 0.2
            
            # 偏好匹配 (10%)
            preference_fitness = node.score / 5.0 if node.score > 0 else 0.5
            fitness_score += preference_fitness * 0.1
            
            # 更新适应度
            node.fitness = round(fitness_score, 3)
    
    def _evaluate_content_quality(self, content: str) -> float:
        """评估内容质量"""
        if not content:
            return 0.0
        
        quality_score = 0.0
        
        # 长度合理性
        length = len(content)
        if 50 <= length <= 300:
            quality_score += 0.3
        elif 30 <= length <= 500:
            quality_score += 0.2
        else:
            quality_score += 0.1
        
        # 信息密度
        words = content.split()
        unique_words = set(words)
        if len(words) > 0:
            density = len(unique_words) / len(words)
            quality_score += density * 0.3
        
        # 逻辑连贯性
        logical_connectors = ["因为", "所以", "然而", "但是", "因此", "由于"]
        connector_count = sum(1 for conn in logical_connectors if conn in content)
        quality_score += min(connector_count / 3, 0.4)
        
        return min(quality_score, 1.0)
    
    def _selection(self, nodes: List[ThinkingNode], count: int) -> List[ThinkingNode]:
        """适应度选择"""
        if not nodes:
            return []
        
        if len(nodes) <= count:
            return nodes.copy()
        
        # 按适应度排序，选择前count个
        sorted_nodes = sorted(nodes, key=lambda x: x.fitness, reverse=True)
        return sorted_nodes[:count]
    
    def _elite_selection(self, nodes: List[ThinkingNode], count: int) -> List[ThinkingNode]:
        """精英选择策略"""
        if not nodes:
            return []
        
        # 按适应度排序
        sorted_nodes = sorted(nodes, key=lambda x: x.fitness, reverse=True)
        
        # 选择前count个
        elite_nodes = sorted_nodes[:count]
        
        # 标记为被选择
        for node in elite_nodes:
            node.is_selected = True
        
        return elite_nodes
    
    def _evaluate_diversity(self, node: ThinkingNode, all_nodes: List[ThinkingNode]) -> float:
        """评估节点多样性贡献"""
        if len(all_nodes) <= 1:
            return 1.0
        
        # 计算与其他节点的差异度
        differences = []
        node_words = set(node.content.lower().split())
        
        for other_node in all_nodes:
            if other_node.id == node.id:
                continue
            
            other_words = set(other_node.content.lower().split())
            
            # Jaccard距离
            intersection = node_words & other_words
            union = node_words | other_words
            
            if union:
                jaccard_sim = len(intersection) / len(union)
                jaccard_dist = 1 - jaccard_sim
                differences.append(jaccard_dist)
        
        if differences:
            return float(np.mean(differences))
        else:
            return 1.0
    
    def _evaluate_innovation(self, content: str) -> float:
        """评估创新程度"""
        innovation_keywords = [
            "创新", "新颖", "独特", "突破", "原创", "改进", 
            "优化", "另类", "不同", "新思路", "创造"
        ]
        
        innovation_score = 0.0
        content_lower = content.lower()
        
        # 关键词匹配
        for keyword in innovation_keywords:
            if keyword in content_lower:
                innovation_score += 0.1
        
        # 独特表达检测
        unique_phrases = ["另一方面", "换个角度", "从另一个视角", "不妨考虑"]
        for phrase in unique_phrases:
            if phrase in content:
                innovation_score += 0.15
        
        return min(innovation_score, 1.0)
    
    async def _crossover(self, nodes: List[ThinkingNode]) -> List[ThinkingNode]:
        """改进的交叉操作 - 基于兄弟样本的思路交叉"""
        if len(nodes) < 2:
            return []
        
        crossover_nodes = []
        
        # 标记兄弟关系
        for i, node in enumerate(nodes):
            node.metadata["generation_index"] = i
            node.metadata["siblings"] = [j for j in range(len(nodes)) if j != i]
        
        # 成对交叉，生成新的思考路线
        for i in range(0, len(nodes) - 1, 2):
            if random.random() < self.crossover_rate:
                parent1 = nodes[i]
                parent2 = nodes[i + 1]
                
                children = await self._create_crossover_children_v2(parent1, parent2)
                crossover_nodes.extend(children)
        
        return crossover_nodes
    
    async def _create_crossover_children_v2(self, parent1: ThinkingNode, 
                                          parent2: ThinkingNode) -> List[ThinkingNode]:
        """基于思路融合的交叉子代生成"""
        try:
            # 为子代创建融合提示词
            crossover_prompt = f"""
请基于以下两个不同的思考角度，融合生成一个新的思考方案：

思考角度A（{parent1.branch_type}）：
{parent1.content[:300]}...

思考角度B（{parent2.branch_type}）：
{parent2.content[:300]}...

要求：
1. 融合两种思考角度的优点
2. 保持逻辑连贯性
3. 创造新的思考视角
4. 避免简单拼接，要有机融合
5. 长度控制在200-400字

请生成融合后的新思考内容：
"""
            
            # 使用中等偏高温度生成融合内容
            if self.api_client:
                fusion_content = await self.api_client.get_response(
                    crossover_prompt, 
                    temperature=0.8
                )
                
                # 创建融合子代
                child = ThinkingNode(
                    content=fusion_content.strip(),
                    temperature=(parent1.temperature + parent2.temperature) / 2,
                    generation=max(parent1.generation, parent2.generation) + 1,
                    branch_type=f"fusion_{parent1.branch_type}_{parent2.branch_type}",
                    metadata={
                        "crossover_parents": [parent1.id, parent2.id],
                        "parent1_branch": parent1.branch_type,
                        "parent2_branch": parent2.branch_type,
                        "is_crossover_child": True,
                        "generation_method": "思路融合"
                    }
                )
                
                # 使用新方法标注家族关系
                child.mark_as_crossover_child(parent1.id, parent2.id)
                
                # 添加分支谱系
                child.metadata["family_tree"]["branch_lineage"] = [
                    parent1.branch_type, 
                    parent2.branch_type, 
                    child.branch_type
                ]
                
                # 为父母添加子代记录
                parent1.add_child(child.id)
                parent2.add_child(child.id)
                
                logger.info(f"成功创建融合子代 {child.id[:8]}，融合 {parent1.branch_type} + {parent2.branch_type}")
                
                return [child]
            else:
                return []
                
        except Exception as e:
            logger.warning(f"思路融合交叉失败: {e}")
            return []
    
    async def _mutation(self, nodes: List[ThinkingNode]) -> List[ThinkingNode]:
        """变异操作 - 暂时注释，文本变异容易产生无意义内容"""
        # TODO: 需要开发更智能的文本变异方法
        # 当前简单的文本变异可能破坏思考的逻辑性和连贯性
        # 考虑的改进方向：
        # 1. 基于语义的变异
        # 2. 基于关键词替换的变异
        # 3. 基于句式重构的变异
        
        logger.info("变异操作暂时禁用，直接返回空列表")
        return []
        
        # 以下为原变异代码，已注释
        # mutated_nodes = []
        # for node in nodes:
        #     if random.random() < self.mutation_rate:
        #         mutated_node = await self._create_mutated_node(node)
        #         if mutated_node:
        #             mutated_nodes.append(mutated_node)
        # return mutated_nodes
    
    async def _create_mutated_node(self, parent: ThinkingNode) -> Optional[ThinkingNode]:
        """创建变异节点 - 暂时注释"""
        # TODO: 实现更智能的变异策略
        return None
        
        # 以下为原变异代码，已注释
        # try:
        #     # 简单的单词替换变异
        #     content = parent.content
        #     words = content.split()
        #     
        #     if len(words) > 5:
        #         # 随机替换一个词
        #         mutation_point = random.randint(0, len(words) - 1)
        #         # 这里应该有更智能的词汇替换逻辑
        #         words[mutation_point] = "[变异]" + words[mutation_point]
        #         
        #         mutated_content = ' '.join(words)
        #         
        #         # 创建变异节点
        #         mutated_node = ThinkingNode(
        #             content=mutated_content,
        #             temperature=parent.temperature + random.uniform(-0.1, 0.1),
        #             generation=parent.generation + 1,
        #             branch_type=parent.branch_type + "_mutated"
        #         )
        #         
        #         return mutated_node
        #     
        #     return None
        # except Exception as e:
        #     logger.warning(f"变异操作失败: {e}")
        #     return None
    
    async def _generate_content_variation(self, node: ThinkingNode) -> str:
        """生成内容变异 - 暂时注释"""
        # TODO: 实现基于语义的内容变异
        return node.content
        
        # 以下为原内容变异代码，已注释
        # try:
        #     variation_prompt = f"""
        # 请对以下思考内容进行轻微的角度调整或表达优化，保持核心观点不变：
        # 
        # 原内容：{node.content}
        # 
        # 要求：
        # 1. 保持主要观点和逻辑不变
        # 2. 可以调整表达方式或补充细节
        # 3. 避免改变核心结论
        # 4. 长度与原文相近
        # 
        # 优化后内容：
        # """
        #     
        #     varied_content = await self.api_client.get_response(
        #         variation_prompt, 
        #         temperature=node.temperature + 0.1
        #     )
        #     
        #     return varied_content.strip()
        #     
        # except Exception as e:
        #     logger.warning(f"内容变异生成失败: {e}")
        #     return node.content
    
    def _check_convergence(self, generation_id: int) -> bool:
        """检查收敛条件"""
        if generation_id < 2:
            return False
        
        # 获取最近两代的最佳适应度
        if len(self.generations) >= 2:
            current_best = self.generations[-1].best_fitness
            previous_best = self.generations[-2].best_fitness
            
            # 如果改进幅度很小，认为收敛
            if abs(current_best - previous_best) < 0.01:
                return True
        
        return False
    
    def get_evolution_summary(self) -> Dict:
        """获取进化过程摘要"""
        if not self.generations:
            return {"status": "未开始"}
        
        summary = {
            "total_generations": len(self.generations),
            "current_generation": self.current_generation,
            "evolution_history": []
        }
        
        for gen in self.generations:
            gen_info = {
                "generation_id": gen.generation_id,
                "best_fitness": gen.best_fitness,
                "avg_fitness": gen.avg_fitness,
                "diversity_score": gen.diversity_score,
                "branch_count": len(gen.branches)
            }
            summary["evolution_history"].append(gen_info)
        
        # 计算进化趋势
        if len(self.generations) > 1:
            first_gen = self.generations[0]
            last_gen = self.generations[-1]
            
            summary["fitness_improvement"] = (
                last_gen.best_fitness - first_gen.best_fitness
            )
            summary["convergence_trend"] = (
                last_gen.avg_fitness - first_gen.avg_fitness
            )
        
        return summary 