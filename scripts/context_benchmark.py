#!/usr/bin/env python3
"""
上下文处理优化基准测试 -- 基于 session JSON 真实对话数据

从 sessions/*.json 加载完整对话记录，模拟 build_conversation_messages() 的实际行为，
对比 skill 注入优化前后每轮 LLM 请求的上下文大小。

优化内容：
  旧方案：skill 完整指令嵌入用户消息（每条历史消息都重复携带）
  新方案：skill 完整指令注入系统提示词（一次性），用户消息只带简短标记

用法：
    cd NagaAgent
    python -X utf8 scripts/context_benchmark.py
"""

import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
SESSIONS_DIR = PROJECT_ROOT / "sessions"
PROMPTS_DIR = PROJECT_ROOT / "system" / "prompts"

FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 1.5 字/token，英文约 4 字符/token）"""
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def load_skills() -> dict:
    """加载所有 skill 指令"""
    skills = {}
    for skill_path in SKILLS_DIR.iterdir():
        if not skill_path.is_dir() or skill_path.name.startswith('.'):
            continue
        skill_file = skill_path / "SKILL.md"
        if not skill_file.exists():
            continue
        content = skill_file.read_text(encoding='utf-8')
        match = FRONTMATTER_PATTERN.match(content)
        instructions = content[match.end():].strip() if match else content.strip()
        skills[skill_path.name] = instructions
    return skills


def load_all_sessions() -> list:
    """从 sessions/ 加载所有真实会话 JSON（完整消息，不截断）"""
    sessions = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            msgs = data.get("messages", [])
            if len(msgs) >= 2:
                sessions.append({
                    "id": data.get("session_id", f.stem),
                    "messages": msgs,
                    "created_at": data.get("created_at", ""),
                    "file": f.name,
                })
        except Exception:
            pass
    # 按消息数量降序排列
    sessions.sort(key=lambda s: len(s["messages"]), reverse=True)
    return sessions


def load_base_system_prompt() -> str:
    """加载基础系统提示词"""
    prompt_file = PROMPTS_DIR / "conversation_style_prompt.txt"
    if prompt_file.exists():
        return prompt_file.read_text(encoding='utf-8')
    return "(系统提示词文件不存在)"


def load_tool_prompt() -> str:
    """加载工具调用提示词"""
    prompt_file = PROMPTS_DIR / "agentic_tool_prompt.txt"
    if prompt_file.exists():
        return prompt_file.read_text(encoding='utf-8')
    return ""


# ---------------------------------------------------------------------------
# 上下文模拟
# ---------------------------------------------------------------------------

def build_time_info() -> str:
    now = datetime.now()
    return (
        f"\n\n[当前时间信息]\n"
        f"当前日期: {now.strftime('%Y年%m月%d日')}\n"
        f"当前时间: {now.strftime('%H:%M:%S')}\n"
        f"当前星期: {now.strftime('%A')}\n"
    )


def simulate_context_old(
    base_prompt: str, tool_prompt: str, skill_instructions: str,
    skill_name: str, history_messages: list, current_user_msg: str,
) -> list:
    """模拟旧方案的 messages 列表构建

    旧方案：
      - 系统提示词 = base_prompt + skills_metadata_list + tool_prompt + time_info
      - 用户消息 = "[技能指令]...\n{skill_instructions}\n\n[用户输入] {msg}"
      - 历史中的用户消息也带着 skill 指令（因为 effective_message 保存时包含指令）
    """
    # 系统提示词（不含 skill 指令，只含元数据列表）
    skills_metadata = "## 可用技能\n\n(技能元数据列表，约500字符)\n"
    system_content = base_prompt + "\n\n" + skills_metadata + "\n\n" + tool_prompt + build_time_info()

    messages = [{"role": "system", "content": system_content}]

    # 历史消息（旧方案中用户消息携带完整 skill 指令）
    for msg in history_messages:
        if msg["role"] == "user":
            old_user_msg = (
                f"[技能指令] 请严格按照以下技能要求处理我的输入，直接输出结果：\n"
                f"{skill_instructions}\n\n"
                f"[用户输入] {msg['content']}"
            )
            messages.append({"role": "user", "content": old_user_msg})
        else:
            messages.append(msg)

    # 当前用户消息（也带 skill 指令）
    current_msg = (
        f"[技能指令] 请严格按照以下技能要求处理我的输入，直接输出结果：\n"
        f"{skill_instructions}\n\n"
        f"[用户输入] {current_user_msg}"
    )
    messages.append({"role": "user", "content": current_msg})

    return messages


def simulate_context_new(
    base_prompt: str, tool_prompt: str, skill_instructions: str,
    skill_name: str, history_messages: list, current_user_msg: str,
) -> list:
    """模拟新方案的 messages 列表构建

    新方案：
      - 系统提示词 = base_prompt + tool_prompt + time_info + skill_full_instructions（末尾，最高优先级）
      - 历史用户消息 = 原始消息（不含任何标记，save时用的是 request.message）
      - 当前用户消息 = "[使用技能: X] {msg}"
    """
    # 系统提示词（skill 完整指令放在末尾，确保最高优先级）
    skill_section = (
        f"\n\n## 当前激活技能: {skill_name}\n\n"
        f"[最高优先级指令] 以下技能指令优先于所有其他行为规则。"
        f"你必须严格按照技能要求处理用户输入，直接输出结果：\n"
        f"{skill_instructions}"
    )
    system_content = base_prompt + "\n\n" + tool_prompt + build_time_info() + skill_section

    messages = [{"role": "system", "content": system_content}]

    # 历史消息（新方案中保存的是原始用户消息）
    for msg in history_messages:
        messages.append(msg)

    # 当前用户消息（简短标记）
    current_msg = f"[使用技能: {skill_name}] {current_user_msg}"
    messages.append({"role": "user", "content": current_msg})

    return messages


def calc_total_chars(messages: list) -> int:
    return sum(len(m["content"]) for m in messages)


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------

def run_benchmark():
    print("=" * 80)
    print("上下文处理优化基准测试 -- 基于 Session JSON 真实数据")
    print("=" * 80)
    print()

    # 加载真实数据
    skills = load_skills()
    sessions = load_all_sessions()
    base_prompt = load_base_system_prompt()
    tool_prompt = load_tool_prompt()

    print(f"数据来源：")
    print(f"  - skills 目录：{len(skills)} 个技能")
    print(f"  - sessions 目录：{len(sessions)} 个会话")
    print()

    if not sessions:
        print("  (无 session JSON 数据)")
        return

    # ====== 第一部分：真实 skill 指令体积 ======
    print("## 1. 真实 Skill 指令体积")
    print()
    print(f"{'Skill':<25} {'字符数':>8} {'估算 Token':>10}")
    print("-" * 48)
    for name in sorted(skills, key=lambda n: -len(skills[n])):
        chars = len(skills[name])
        tokens = estimate_tokens(skills[name])
        print(f"{name:<25} {chars:>8} {tokens:>10}")
    print()

    # ====== 第二部分：真实 Session 数据统计 ======
    print("## 2. 真实 Session 数据统计")
    print()

    total_user_msgs = 0
    total_asst_msgs = 0
    total_user_chars = 0
    total_asst_chars = 0

    for session in sessions:
        session_user = 0
        session_asst = 0
        session_user_chars = 0
        session_asst_chars = 0
        for msg in session["messages"]:
            if msg["role"] == "user":
                session_user += 1
                session_user_chars += len(msg["content"])
            elif msg["role"] == "assistant":
                session_asst += 1
                session_asst_chars += len(msg["content"])

        total_user_msgs += session_user
        total_asst_msgs += session_asst
        total_user_chars += session_user_chars
        total_asst_chars += session_asst_chars

        rounds = min(session_user, session_asst)
        print(f"  会话 {session['id'][:8]}... ({session['file']})")
        print(f"    消息数: {len(session['messages'])} ({session_user} 用户 + {session_asst} 助手 = {rounds} 轮)")
        print(f"    用户消息: {session_user_chars:,} 字符 (平均 {session_user_chars // max(session_user, 1)} 字符/条)")
        print(f"    助手消息: {session_asst_chars:,} 字符 (平均 {session_asst_chars // max(session_asst, 1)} 字符/条)")
        print()

    print(f"  汇总：{total_user_msgs} 条用户消息 ({total_user_chars:,} 字符)，"
          f"{total_asst_msgs} 条助手消息 ({total_asst_chars:,} 字符)")
    print()

    # ====== 第三部分：逐轮上下文大小对比（每个 session） ======
    print("## 3. 逐轮上下文大小对比")
    print()

    # 选取代表性 skill
    demo_skills = ["verify-authenticity", "solve", "naga-config"]
    demo_skills = [s for s in demo_skills if s in skills]
    if not demo_skills:
        demo_skills = list(skills.keys())[:3]

    for session in sessions:
        msgs = session["messages"]
        rounds = len(msgs) // 2

        print(f"=== 会话: {session['id'][:8]}... ({rounds} 轮, {len(msgs)} 条消息) ===")
        print()

        for skill_name in demo_skills:
            skill_instructions = skills[skill_name]
            skill_chars = len(skill_instructions)
            skill_tokens = estimate_tokens(skill_instructions)

            print(f"--- 技能: {skill_name} ({skill_chars} 字符 / {skill_tokens} token) ---")
            print()
            print(f"{'轮次':>4}  {'用户消息预览':>20}  {'旧方案总计':>12}  {'新方案总计':>12}  "
                  f"{'节省字符':>10}  {'节省 Token':>10}  {'节省率':>8}")
            print("-" * 100)

            # 逐轮递增历史，模拟真实的 build_conversation_messages
            user_turns = []
            asst_turns = []
            turn_idx = 0

            for i in range(0, len(msgs) - 1, 2):
                if msgs[i]["role"] != "user":
                    continue
                user_msg = msgs[i]
                asst_msg = msgs[i+1] if i+1 < len(msgs) else None

                # 前面的轮次作为历史
                history = []
                for u, a in zip(user_turns, asst_turns):
                    history.append(u)
                    history.append(a)

                current_user_text = user_msg["content"]
                turn_idx += 1

                # 旧方案
                old_messages = simulate_context_old(
                    base_prompt, tool_prompt, skill_instructions,
                    skill_name, history, current_user_text,
                )
                old_total = calc_total_chars(old_messages)

                # 新方案
                new_messages = simulate_context_new(
                    base_prompt, tool_prompt, skill_instructions,
                    skill_name, history, current_user_text,
                )
                new_total = calc_total_chars(new_messages)

                saved = old_total - new_total
                saved_tokens = estimate_tokens("X" * abs(saved)) if saved > 0 else -estimate_tokens("X" * abs(saved))
                rate = saved / old_total * 100 if old_total > 0 else 0

                user_preview = current_user_text[:18].replace('\n', ' ')
                print(f"{turn_idx:>4}  {user_preview:<20}  {old_total:>12,}  {new_total:>12,}  "
                      f"{saved:>10,}  {saved_tokens:>10,}  {rate:>7.1f}%")

                # 累积历史
                user_turns.append(user_msg)
                if asst_msg:
                    asst_turns.append(asst_msg)

            print()

    # ====== 第四部分：全量 skill 汇总（使用所有 session 合并的完整历史） ======
    print("## 4. 全量汇总：各 skill 在每个 session 末轮的节省量")
    print()
    print(f"{'Skill':<25} {'指令大小':>8}  {'会话':>10}  {'轮数':>4}  "
          f"{'旧方案末轮':>12}  {'新方案末轮':>12}  {'节省字符':>10}  {'节省率':>8}")
    print("-" * 105)

    for session in sessions:
        msgs = session["messages"]
        rounds = len(msgs) // 2

        # 构建完整历史（除最后一轮外的所有消息）
        full_history = msgs[:-2] if len(msgs) >= 4 else []
        last_user_msg = ""
        for m in reversed(msgs):
            if m["role"] == "user":
                last_user_msg = m["content"]
                break

        for skill_name in sorted(skills, key=lambda n: -len(skills[n])):
            si = skills[skill_name]

            old_messages = simulate_context_old(
                base_prompt, tool_prompt, si, skill_name, full_history, last_user_msg,
            )
            new_messages = simulate_context_new(
                base_prompt, tool_prompt, si, skill_name, full_history, last_user_msg,
            )

            old_total = calc_total_chars(old_messages)
            new_total = calc_total_chars(new_messages)
            saved = old_total - new_total
            rate = saved / old_total * 100 if old_total > 0 else 0

            print(f"{skill_name:<25} {len(si):>8}  {session['id'][:8]:>10}  {rounds:>4}  "
                  f"{old_total:>12,}  {new_total:>12,}  {saved:>10,}  {rate:>7.1f}%")

        print()

    # ====== 第五部分：基础上下文组成分析 ======
    print("## 5. 基础上下文组成（不含 skill 时）")
    print()
    base_chars = len(base_prompt)
    tool_chars = len(tool_prompt)
    time_chars = len(build_time_info())
    print(f"  conversation_style_prompt.txt:  {base_chars:>6} 字符 / {estimate_tokens(base_prompt):>5} token")
    print(f"  agentic_tool_prompt.txt:        {tool_chars:>6} 字符 / {estimate_tokens(tool_prompt):>5} token")
    print(f"  时间信息:                       {time_chars:>6} 字符 / {estimate_tokens(build_time_info()):>5} token")
    print(f"  系统提示词合计:                 {base_chars + tool_chars + time_chars:>6} 字符 / "
          f"{estimate_tokens(base_prompt + tool_prompt + build_time_info()):>5} token")
    print()
    print("  优化前：skill 指令在系统提示词外（用户消息中），每轮重复")
    print("  优化后：skill 指令在系统提示词内，只出现一次")
    print()


if __name__ == "__main__":
    run_benchmark()
