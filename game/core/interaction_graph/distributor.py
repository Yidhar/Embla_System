"""
Distributor - 角色分配器
通过大模型API动态生成与任务相关的功能性角色
"""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, Tuple

from ..models.data_models import Task, RoleGenerationRequest, GeneratedRole
from ..models.config import GameConfig

logger = logging.getLogger(__name__)


class Distributor:
    """角色分配器 - 通过大模型API生成角色"""
    
    def __init__(self, config: GameConfig, naga_conversation=None):
        """
        初始化Distributor
        
        Args:
            config: 游戏配置
            naga_conversation: NagaAgent的会话实例,用于API调用
        """
        self.config = config
        self.naga_conversation = naga_conversation
        self._init_naga_api()
    
    def _init_naga_api(self):
        """初始化NagaAgent API连接"""
        if self.naga_conversation is None:
            try:
                # 导入NagaAgent的对话核心
                from system.conversation_core import NagaConversation
                self.naga_conversation = NagaConversation()
                logger.info("成功初始化NagaAgent API连接")
            except ImportError as e:
                logger.warning(f"无法导入NagaAgent API, 将使用回退逻辑: {e}")
                self.naga_conversation = None
    
    async def generate_roles(self, task: Task, expected_count_range: Tuple[int, int]) -> List[GeneratedRole]:
        """
        生成角色列表
        
        Args:
            task: 任务对象
            expected_count_range: 期望角色数量范围 (min, max)
            
        Returns:
            生成的角色列表
        """
        try:
            logger.info(f"开始生成任务角色:{task.description}")
            
            # 创建角色生成请求
            request = RoleGenerationRequest(
                task_description=task.description,
                domain=task.domain,
                expected_count_range=expected_count_range,
                constraints=task.constraints
            )
            
            # 生成角色生成提示词
            generation_prompt = self._build_role_generation_prompt(request)
            
            # 调用大模型API
            response = await self._call_llm_api(generation_prompt)
            
            # 解析生成结果
            roles = self._parse_roles_from_response(response)
            
            # 纯验证
            validated_roles = self._validate_generated_roles(roles, request)

            # 不强制补足到最小数量。仅当数量为0时，做最小回退，确保至少1个执行角色。
            if len(validated_roles) == 0:
                logger.warning("生成结果为空，进行最小回退生成1个执行角色")
                fallback_roles = await self._fallback_generate_roles(task, (1, 1))
                validated_roles.extend(fallback_roles)

            logger.info(f"成功生成{len(validated_roles)}个角色")
            return validated_roles
            
        except Exception as e:
            logger.error(f"角色生成失败:{e}")
            return await self._fallback_generate_roles(task, expected_count_range)
    
    def _build_role_generation_prompt(self, request: RoleGenerationRequest) -> str:
        """构建角色生成的系统提示词"""
        min_count, max_count = request.expected_count_range
        
        constraints_text = ""
        if request.constraints:
            constraints_text = f"\n约束条件:\n" + "\n".join(f"- {constraint}" for constraint in request.constraints)
        
        prompt = f"""# 任务:智能体角色生成

你是一个专业的团队组建专家,需要根据给定任务生成最优的角色分工方案.

## 任务信息
- **任务描述**: {request.task_description}
- **领域类型**: {request.domain}
- **角色数量**: {min_count}-{max_count}个角色{constraints_text}

## 重要约束
⚠️ **禁止生成"需求方"、"用户"、"客户"等角色** - 系统已自动包含需求方节点,你只需要生成执行任务的专业角色.

## 生成要求
1. **角色设计原则**:
   - 每个角色都有明确的专业职责
   - 角色之间形成有效的协作链条
   - 避免职责重叠和功能冗余
   - 确保能够完整覆盖任务需求
   - 专注于任务执行角色,不要生成需求提出方角色

2. **角色信息要求**:
   - name: 角色的具体名称
   - role_type: 角色类型分类
   - responsibilities: 详细的职责列表（3-5个）
   - skills: 需要的专业技能（4-6个）
   - output_requirements: 该角色的预期输出内容
   - priority_level: 优先级（1-10）

3. **输出格式**:
严格按照以下JSON格式输出,不要添加任何解释文本:

```json
{{
    "roles": [
        {{
            "name": "角色名称",
            "role_type": "角色类型",
            "responsibilities": ["职责1", "职责2", "职责3"],
            "skills": ["技能1", "技能2", "技能3", "技能4"],
            "output_requirements": "该角色需要输出的具体内容描述",
            "priority_level": 8
        }}
    ]
}}
```

## 领域参考
根据"{request.domain}"领域的特点,请生成专业、实用且互补的角色组合.

## 协作提示
生成的角色需要能够:
1. 接收需求方的初始需求
2. 相互协作完成任务
3. 最终将方案交付给需求方

请立即开始生成角色方案:"""

        return prompt
    
    async def _call_llm_api(self, prompt: str) -> str:
        """调用大模型API"""
        if self.naga_conversation is None:
            raise RuntimeError("NagaAgent API未初始化")
        response = await self.naga_conversation.get_response(prompt, temperature=0.7)
        return response
    
    def _parse_roles_from_response(self, response: str) -> List[Dict[str, Any]]:
        """从API响应中解析角色信息"""
        try:
            # 提取JSON部分
            json_start = response.find('```json')
            json_end = response.find('```', json_start + 7)
            
            if json_start != -1 and json_end != -1:
                json_str = response[json_start + 7:json_end].strip()
            else:
                # 尝试直接解析整个响应
                json_str = response.strip()
                # 如果响应包含其他文本,尝试找到JSON部分
                if json_str.startswith('{'):
                    json_end = json_str.rfind('}') + 1
                    json_str = json_str[:json_end]
            
            # 解析JSON
            data = json.loads(json_str)
            
            if 'roles' in data:
                return data['roles']
            else:
                logger.warning("响应中未找到'roles'字段")
                return []
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败:{e}")
            logger.error(f"响应内容:{response}")
            return []
        except Exception as e:
            logger.error(f"角色解析失败:{e}")
            return []
    
    def _validate_generated_roles(self, raw_roles: List[Dict[str, Any]], 
                                  request: RoleGenerationRequest) -> List[GeneratedRole]:
        """验证并转换生成的角色"""
        validated_roles: List[GeneratedRole] = []
        min_count, max_count = request.expected_count_range
        
        for i, role_data in enumerate(raw_roles):
            try:
                # 验证必需字段
                required_fields = ['name', 'role_type', 'responsibilities', 'skills', 'output_requirements']
                if not all(field in role_data for field in required_fields):
                    logger.warning(f"角色{i}缺少必需字段,跳过")
                    continue
                
                # 创建GeneratedRole对象
                role = GeneratedRole(
                    name=str(role_data['name']).strip(),
                    role_type=str(role_data['role_type']).strip(),
                    responsibilities=self._ensure_list(role_data['responsibilities']),
                    skills=self._ensure_list(role_data['skills']),
                    output_requirements=str(role_data['output_requirements']).strip(),
                    priority_level=int(role_data.get('priority_level', 5))
                )
                
                # 基本有效性
                if role.name and role.role_type and role.responsibilities and role.skills:
                    validated_roles.append(role)
            except Exception as e:
                logger.error(f"验证角色{i}失败:{e}")
                continue
        
        # 数量过多时按照优先级裁剪
        if len(validated_roles) > max_count:
            validated_roles = sorted(validated_roles, key=lambda x: x.priority_level, reverse=True)[:max_count]
        
        return validated_roles
    
    def _ensure_list(self, value: Any) -> List[str]:
        """确保值是字符串列表"""
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, str):
            return [value.strip()] if value.strip() else []
        else:
            return []
    
    async def _fallback_generate_roles(self, task: Task, expected_count_range: Tuple[int, int]) -> List[GeneratedRole]:
        """动态回退生成(无任何固定枚举):
        1) 二次LLM调用(更严格格式)
        2) 若LLM不可用/失败: 基于任务文本生成通用执行角色(名称: 执行角色N),职责/技能从任务派生
        """
        min_count, max_count = expected_count_range
        target_count = max(min_count, 1)

        # 方案1: 再次尝试LLM(更严格)
        if self.naga_conversation is not None:
            strict_prompt = f"""# 任务: 智能体角色补全

你需要为如下任务严格输出JSON,禁止任何额外文字.禁止出现"需求方"/"用户"/"客户".

任务: {task.description}
领域: {task.domain}
数量: {target_count}

JSON格式:
{{"roles":[{{"name":"...","role_type":"...","responsibilities":["..."],"skills":["..."],"output_requirements":"...","priority_level":7}}]}}
"""
            try:
                resp = await self.naga_conversation.get_response(strict_prompt, temperature=0.4)
                roles = self._parse_roles_from_response(resp)
                out: List[GeneratedRole] = []
                for r in roles[:target_count]:
                    try:
                        out.append(GeneratedRole(
                            name=str(r['name']).strip(),
                            role_type=str(r['role_type']).strip(),
                            responsibilities=self._ensure_list(r['responsibilities']),
                            skills=self._ensure_list(r['skills']),
                            output_requirements=str(r['output_requirements']).strip(),
                            priority_level=int(r.get('priority_level', 5))
                        ))
                    except Exception:
                        continue
                if out:
                    return out[:target_count]
            except Exception as e:
                logger.warning(f"严格回退LLM生成失败: {e}")
        
        # 方案2: 算法化占位(基于任务文本,非领域枚举)
        def derive_phrases(text: str, n: int) -> List[str]:
            text = (text or "").strip()
            if not text:
                return ["需求分析", "方案设计", "实施推进", "质量评估"][:n]
            # 简单从文本切片构造短语
            chunks = [text[i:i+4] for i in range(0, len(text), 4)]
            base = [c for c in chunks if c.strip()]
            base = base or ["需求分析", "方案设计", "实施推进", "质量评估"]
            return (base + ["协作沟通", "风险管理"])[:n]
        
        roles_out: List[GeneratedRole] = []
        for i in range(target_count):
            resp = ["负责阶段性工作", "推动协作闭环", "保证交付质量"]
            skills = derive_phrases(task.description, 4)
            roles_out.append(GeneratedRole(
                name=f"执行角色{i+1}",
                role_type="执行者",
                responsibilities=resp,
                skills=skills,
                output_requirements="本阶段结构化输出",
                priority_level=max(1, 10 - i)
            ))
        return roles_out
    
    async def assign_collaboration_permissions(self, roles: List[GeneratedRole]) -> Dict[str, List[str]]:
        """
        为角色分配协作权限
        
        Args:
            roles: 生成的角色列表
            
        Returns:
            角色权限映射 {role_name: [connected_role_names]}
        """
        try:
            logger.info(f"开始为{len(roles)}个角色分配协作权限")
            
            # 构建权限分配提示词
            permission_prompt = self._build_permission_assignment_prompt(roles)
            
            # 调用大模型API
            response = await self._call_llm_api(permission_prompt)
            
            # 解析权限分配结果
            permissions = self._parse_permissions_from_response(response, roles)
            
            logger.info("成功分配协作权限")
            return permissions
            
        except Exception as e:
            logger.error(f"权限分配失败:{e}")
            # 返回默认权限（全连通/按优先级相邻连通）
            return self._get_default_permissions(roles)
    
    def _build_permission_assignment_prompt(self, roles: List[GeneratedRole]) -> str:
        """构建权限分配提示词"""
        roles_info = []
        for i, role in enumerate(roles):
            roles_info.append(f"{i+1}. {role.name}（{role.role_type}）")
            roles_info.append(f"   - 职责:{', '.join(role.responsibilities[:3])}")
            roles_info.append(f"   - 优先级:{role.priority_level}")
        
        roles_text = "\n".join(roles_info)
        
        prompt = f"""# 任务:角色协作权限分配

根据以下角色信息,设计合理的协作权限结构,确保高效协作并避免无效沟通.

## 角色信息
{roles_text}

## 特殊节点说明
系统已自动包含"需求方"节点:
- 需求方将连接到优先级最高的角色（通常是项目负责人/产品经理）
- 优先级最高的角色完成工作后可以将结果返回给需求方
- 你只需要设计上述角色之间的协作权限

## 权限设计原则
1. **层级协作**:高优先级角色可以与更多角色直接沟通
2. **专业互补**:相关专业领域的角色应能直接沟通
3. **避免跨越**:不同层级的角色需要通过中介沟通
4. **流程顺序**:按工作流程安排协作顺序
5. **回路设计**:确保最终能将结果传递给需求方

## 输出格式
严格按照以下JSON格式输出:

```json
{{
    "permissions": {{
        "角色名称1": ["可直接沟通的角色名称1", "可直接沟通的角色名称2"],
        "角色名称2": ["可直接沟通的角色名称1", "可直接沟通的角色名称3"]
    }}
}}
```

请根据角色特点和协作需求,设计最优的权限分配方案:"""

        return prompt
    
    def _parse_permissions_from_response(self, response: str, roles: List[GeneratedRole]) -> Dict[str, List[str]]:
        """解析权限分配响应"""
        try:
            # 提取JSON部分
            json_start = response.find('```json')
            json_end = response.find('```', json_start + 7)
            
            if json_start != -1 and json_end != -1:
                json_str = response[json_start + 7:json_end].strip()
            else:
                json_str = response.strip()
                if json_str.startswith('{'):
                    json_end = json_str.rfind('}') + 1
                    json_str = json_str[:json_end]
            
            data = json.loads(json_str)
            
            if 'permissions' in data:
                return data['permissions']
            else:
                logger.warning("权限响应中未找到'permissions'字段")
                return self._get_default_permissions(roles)
                
        except Exception as e:
            logger.error(f"权限解析失败:{e}")
            return self._get_default_permissions(roles)
    
    def _get_default_permissions(self, roles: List[GeneratedRole]) -> Dict[str, List[str]]:
        """获取默认权限（基于优先级的简单规则）"""
        permissions = {}
        # 按优先级排序
        sorted_roles = sorted(roles, key=lambda x: x.priority_level, reverse=True)
        
        for i, role in enumerate(sorted_roles):
            connected_roles = []
            if i == 0:
                connected_roles = [r.name for r in sorted_roles[1:]]
            elif i < len(sorted_roles) - 1:
                connected_roles.append(sorted_roles[i-1].name)
                connected_roles.append(sorted_roles[i+1].name)
            else:
                connected_roles.append(sorted_roles[0].name)
            permissions[role.name] = list(dict.fromkeys(connected_roles))
        
        return permissions 
 