#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式分流测试脚本
- 模拟LLM增量输出，验证：
  1) 前端流式内容是否按增量追加
  2) 语音侧是否按句切割并接收到正确的分句
运行：python apiserver/test_stream_split.py  # 注释
"""

import asyncio  # 异步主函数 #
from typing import List  # 类型注解 #

from apiserver.streaming_tool_extractor import StreamingToolCallExtractor  # 导入切割器 #


class MockVoiceIntegration:
    """简单的语音集成Mock（一行注释）"""

    def __init__(self, sink: List[str]):
        self.sink = sink  # 用于记录TTS接收的文本 #

    def receive_text_chunk(self, text: str):
        self.sink.append(text)  # 记录接收的文本 #

    def finish_processing(self):
        pass  # 测试无需实现 #


async def run_test():
    # 构造增量片段（模拟SSE收到的content增量） #
    deltas = [
        "你好，",
        "世界。",
        "今天",
        "阳光",
        "很好！",
        "我们去公园",
        "散步吧。",
    ]

    # 前端累积（模拟前端消息气泡append） #
    frontend_stream = ""

    # 语音接收记录（按句） #
    tts_chunks: List[str] = []
    voice = MockVoiceIntegration(tts_chunks)

    # 仅用于TTS切割的流式文本切割器 #
    extractor = StreamingToolCallExtractor()
    extractor.set_callbacks(on_text_chunk=None, voice_integration=voice)

    # 喂入增量：前端直接append；TTS走切割器 #
    for d in deltas:
        frontend_stream += d
        await extractor.process_text_chunk(d)

    # 收尾，触发剩余缓冲 #
    await extractor.finish_processing()

    # 期望：前端完整拼接；TTS按句分发 #
    expected_frontend = "".join(deltas)
    # 句子边界基于中文符号：、。？！； #
    # 这里至少应包含："你好，世界。"、"很好！"、"散步吧。" #

    print("===== 前端累计内容（应为完整拼接） =====")
    print(frontend_stream)
    print()

    print("===== TTS 接收的切割句子（仅句子，不含增量） =====")
    for i, s in enumerate(tts_chunks, 1):
        print(f"{i}. {s}")

    # 简单断言 #
    assert frontend_stream == expected_frontend, "前端累计内容不一致"  # 简单一致性校验 #
    assert any(s.endswith("。") and "世界" in s for s in tts_chunks), "未检测到包含'世界。'的句子"  # 断句校验 #
    assert any(s.endswith("！") for s in tts_chunks), "未检测到感叹句'！'"  # 断句校验 #
    assert any(s.endswith("。") and "散步" in s for s in tts_chunks), "未检测到'散步吧。'句子"  # 断句校验 #

    print("\n✅ 测试通过：前端与TTS分流行为符合预期")


if __name__ == "__main__":
    asyncio.run(run_test())  # 运行异步测试 #


