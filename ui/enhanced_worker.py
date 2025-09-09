"""
增强版Worker类
支持进度更新、状态回调、错误处理和取消操作
"""

import asyncio
import time
from PyQt5.QtCore import QThread, pyqtSignal
from ui.response_utils import extract_message
from system.config import config, AI_NAME  # 导入配置模块

class EnhancedWorker(QThread):
    """增强版工作线程"""
    
    # 信号定义
    finished = pyqtSignal(str)  # 完成信号，返回最终结果
    progress_updated = pyqtSignal(int, str)  # 进度更新信号 (value, status)
    status_changed = pyqtSignal(str)  # 状态变化信号
    error_occurred = pyqtSignal(str)  # 错误发生信号
    partial_result = pyqtSignal(str)  # 部分结果信号（流式输出）
    
    def __init__(self, naga, user_input, parent=None):
        super().__init__(parent)
        self.naga = naga
        self.user_input = user_input
        self.is_cancelled = False
        self.result_buffer = []
        
        # 初始化语音集成模块
        try:
            from voice.output.voice_integration import get_voice_integration
            self.voice_integration = get_voice_integration()
        except Exception as e:
            print(f"语音集成初始化失败: {e}")
            self.voice_integration = None
        
    def cancel(self):
        """取消当前操作"""
        self.is_cancelled = True
        self.status_changed.emit("正在取消...")
        # 立即发出完成信号，避免UI等待
        self.finished.emit("操作已取消")
        
    def run(self):
        """主执行函数"""
        try:
            # 重置取消状态（确保新任务开始时状态正确）
            self.is_cancelled = False
            
            # 检查是否在开始前就被取消
            if self.is_cancelled:
                return
            
            self.status_changed.emit("正在初始化...")
            self.progress_updated.emit(10, "准备处理请求")
            
            if self.is_cancelled:
                return
                
            # 设置事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # 执行异步处理
                result = loop.run_until_complete(self.process_with_progress())
                
                if not self.is_cancelled and result:
                    # 提取最终消息
                    final_message = extract_message(result)
                    self.finished.emit(final_message)
                    
            finally:
                loop.close()
                
        except Exception as e:
            if not self.is_cancelled:  # 只有在未取消时才报告错误
                error_msg = f"处理失败: {str(e)}"
                self.error_occurred.emit(error_msg)
                self.finished.emit(f"抱歉，处理您的请求时遇到了问题：{error_msg}")
            
    async def process_with_progress(self):
        """带进度的异步处理"""
        start_time = time.time()
        
        try:
            self.status_changed.emit("正在思考...")
            self.progress_updated.emit(20, "分析您的问题")
            
            if self.is_cancelled:
                return ""
                
            # 开始处理
            result_chunks = []
            chunk_count = 0
            
            self.status_changed.emit("正在生成回复...")
            self.progress_updated.emit(40, "AI正在思考")
            
            async for chunk in self.naga.process(self.user_input):
                if self.is_cancelled:
                    break
                    
                chunk_count += 1
                
                # 处理chunk格式 - 不进行extract_message处理，直接累积原始内容
                if isinstance(chunk, tuple) and len(chunk) == 2:
                    speaker, content = chunk
                    if speaker == AI_NAME:
                        content_str = str(content)
                        result_chunks.append(content_str)
                        # 发送部分结果用于实时显示
                        self.partial_result.emit(content_str)
                else:
                    content_str = str(chunk)
                    result_chunks.append(content_str)
                    self.partial_result.emit(content_str)
                
                # 更新进度
                progress = min(90, 40 + chunk_count * 2)
                self.progress_updated.emit(progress, f"正在生成回复... ({chunk_count})")
                
                # 短暂休眠，让UI有时间更新
                await asyncio.sleep(0.01)
            
            if not self.is_cancelled:
                self.progress_updated.emit(95, "完成生成")
                full_result = ''.join(result_chunks)
                
                # 处理完成
                elapsed = time.time() - start_time
                self.status_changed.emit(f"完成 (用时 {elapsed:.1f}s)")
                self.progress_updated.emit(100, "处理完成")
                
                return full_result
            else:
                return ""
                
        except Exception as e:
            self.error_occurred.emit(f"异步处理错误: {str(e)}")
            raise


class StreamingWorker(EnhancedWorker):
    """流式处理Worker，专门优化流式对话体验 - 支持流式工具调用提取"""
    
    # 额外信号
    stream_chunk = pyqtSignal(str)  # 流式数据块
    stream_complete = pyqtSignal()  # 流式完成
    tool_call_detected = pyqtSignal(str)  # 工具调用检测信号
    tool_result_received = pyqtSignal(str)  # 工具结果信号
    
    def __init__(self, naga, user_input, parent=None):
        super().__init__(naga, user_input, parent)
        self.streaming_buffer = ""
        
        # 导入流式工具调用提取器
        try:
            # 添加项目根目录到Python路径
            import sys
            import os
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            
            from apiserver.streaming_tool_extractor import StreamingToolCallExtractor
            self.tool_extractor = StreamingToolCallExtractor(self.naga.mcp if hasattr(self.naga, 'mcp') else None)
            self.tool_extractor.set_callbacks(
                on_text_chunk=self._on_text_chunk_sync,
                on_sentence=self._on_sentence_sync,
                on_tool_result=self._on_tool_result_sync,
                tool_call_detected_signal=self.tool_call_detected.emit
            )
        except ImportError as e:
            print(f"流式工具调用提取器导入失败: {e}")
            self.tool_extractor = None
        
    async def _on_text_chunk(self, text: str, chunk_type: str):
        """处理文本块回调"""
        if chunk_type == "chunk":
            # 发送到前端显示
            self.stream_chunk.emit(text)
            
            # 异步发送到语音集成
            if self.voice_integration:
                try:
                    import threading
                    threading.Thread(
                        target=self.voice_integration.receive_text_chunk,
                        args=(text,),
                        daemon=True
                    ).start()
                except Exception as e:
                    print(f"语音集成错误: {e}")
    
    def _on_text_chunk_sync(self, text: str, chunk_type: str):
        """同步处理文本块回调（用于非异步环境）"""
        if chunk_type == "chunk":
            # 发送到前端显示
            self.stream_chunk.emit(text)
            
            # 异步发送到语音集成
            if self.voice_integration:
                try:
                    import threading
                    threading.Thread(
                        target=self.voice_integration.receive_text_chunk,
                        args=(text,),
                        daemon=True
                    ).start()
                except Exception as e:
                    print(f"语音集成错误: {e}")
    
    async def _on_sentence(self, sentence: str, sentence_type: str):
        """处理完整句子回调"""
        if sentence_type == "sentence":
            # 句子级别的特殊处理
            print(f"完成句子: {sentence}")
            # 可以在这里添加语音合成逻辑
    
    def _on_sentence_sync(self, sentence: str, sentence_type: str):
        """同步处理句子回调（用于非异步环境）"""
        if sentence_type == "sentence":
            # 句子级别的特殊处理
            # print(f"完成句子: {sentence}")  # 调试输出，已注释
            pass  # 可以在这里添加语音合成逻辑
    
    async def _on_tool_result(self, result: str, result_type: str):
        """处理工具结果回调"""
        if result_type == "tool_result":
            # 发送工具结果信号
            self.tool_result_received.emit(f"工具执行结果: {result[:100]}...")
            print(f"工具执行完成: {result[:100]}...")
        elif result_type == "tool_error":
            # 发送错误信号
            self.tool_result_received.emit(f"工具执行错误: {result}")
            print(f"工具执行错误: {result}")
    
    def _on_tool_result_sync(self, result: str, result_type: str):
        """同步处理工具结果回调（用于非异步环境）"""
        if result_type == "tool_result":
            # 发送工具结果信号
            self.tool_result_received.emit(f"工具执行结果: {result[:100]}...")
            print(f"工具执行完成: {result[:100]}...")
        elif result_type == "tool_error":
            # 发送错误信号
            self.tool_result_received.emit(f"工具执行错误: {result}")
            print(f"工具执行错误: {result}")
        
    async def process_with_progress(self):
        """流式处理优化版本 - 支持流式工具调用提取"""
        start_time = time.time()
        
        try:
            self.status_changed.emit("连接到AI...")
            self.progress_updated.emit(15, "建立连接")
            
            if self.is_cancelled:
                return ""
            
            self.status_changed.emit("正在思考...")
            self.progress_updated.emit(30, "[夏园系统]:正在使用CPU推理")
            
            # 开始流式处理
            result_chunks = []
            word_count = 0
            
            async for chunk in self.naga.process(self.user_input):
                if self.is_cancelled:
                    break
                
                # 处理chunk
                if isinstance(chunk, tuple) and len(chunk) == 2:
                    speaker, content = chunk
                    if speaker == AI_NAME:
                        content_str = str(content)
                        result_chunks.append(content_str)
                        
                        # 使用流式工具调用提取器处理
                        if self.tool_extractor:
                            try:
                                # 处理文本块，获取结果
                                results = await self.tool_extractor.process_text_chunk(content_str)
                                # 文本通过回调函数发送，不需要额外处理
                            except Exception as e:
                                print(f"工具调用提取器错误: {e}")
                                # 回退到原始处理方式
                                self.stream_chunk.emit(content_str)
                        else:
                            # 回退到原始处理方式
                            self.stream_chunk.emit(content_str)
                            
                            # 异步发送文本到语音集成模块
                            if self.voice_integration:
                                try:
                                    import threading
                                    threading.Thread(
                                        target=self.voice_integration.receive_text_chunk,
                                        args=(content_str,),
                                        daemon=True
                                    ).start()
                                except Exception as e:
                                    print(f"语音集成错误: {e}")
                        
                        # 更新缓冲区用于实时显示
                        self.streaming_buffer += content_str
                        word_count += len(content_str)
                else:
                    content_str = str(chunk)
                    result_chunks.append(content_str)
                    
                    # 使用流式工具调用提取器处理
                    if self.tool_extractor:
                        try:
                            # 处理文本块，获取结果
                            results = await self.tool_extractor.process_text_chunk(content_str)
                            # 文本通过回调函数发送，不需要额外处理
                        except Exception as e:
                            print(f"工具调用提取器错误: {e}")
                            # 回退到原始处理方式
                            self.stream_chunk.emit(content_str)
                    else:
                        # 回退到原始处理方式
                        self.stream_chunk.emit(content_str)
                        
                        # 异步发送文本到语音集成模块
                        if self.voice_integration:
                            try:
                                import threading
                                threading.Thread(
                                    target=self.voice_integration.receive_text_chunk,
                                    args=(content_str,),
                                    daemon=True
                                ).start()
                            except Exception as e:
                                print(f"语音集成错误: {e}")
                    
                    self.streaming_buffer += content_str
                    word_count += len(content_str)
                
                # 动态更新状态
                if word_count < 50:
                    status = "开始回复..."
                    progress = 35
                elif word_count < 200:
                    status = "正在详细解答..."
                    progress = 50
                elif word_count < 500:
                    status = "完善回答内容..."
                    progress = 70
                else:
                    status = "继续生成..."
                    progress = 85
                    
                self.progress_updated.emit(progress, f"{status} ({word_count}字)")
                
                # 减少休眠时间，提升响应速度
                await asyncio.sleep(0.001)
            
            # 完成处理
            if self.tool_extractor:
                await self.tool_extractor.finish_processing()
            
            if not self.is_cancelled:
                # 立即发送完成信号，不等待音频处理
                self.stream_complete.emit()
                
                # 流式处理已完成，语音集成由apiserver处理
                # 这里只需要完成处理信号
                if self.voice_integration:
                    try:
                        import threading
                        threading.Thread(
                            target=self.voice_integration.finish_processing,
                            daemon=True
                        ).start()
                    except Exception as e:
                        print(f"语音集成错误: {e}")
                
                elapsed = time.time() - start_time
                self.status_changed.emit(f"回复完成 (用时 {elapsed:.1f}s，{word_count}字)")
                self.progress_updated.emit(100, "完成")
                
                return ''.join(result_chunks)
            else:
                return ""
                
        except Exception as e:
            self.error_occurred.emit(f"流式处理错误: {str(e)}")
            raise


class BatchWorker(EnhancedWorker):
    """批量处理Worker，适用于一次性获取完整结果"""
    
    def __init__(self, naga, user_input, parent=None):
        super().__init__(naga, user_input, parent)
        self.thinking_time = 0
        
    async def process_with_progress(self):
        """批量处理优化版本"""
        start_time = time.time()
        
        try:
            # 模拟思考阶段
            self.status_changed.emit("深度思考中...")
            
            for i in range(20, 60, 5):
                if self.is_cancelled:
                    return ""
                self.progress_updated.emit(i, f"思考中... ({i-15}%)")
                await asyncio.sleep(0.1)
            
            # 收集所有结果
            result_chunks = []
            self.status_changed.emit("生成完整回复...")
            
            async for chunk in self.naga.process(self.user_input):
                if self.is_cancelled:
                    break
                    
                # 不进行extract_message处理，直接累积原始内容
                if isinstance(chunk, tuple) and len(chunk) == 2:
                    speaker, content = chunk
                    if speaker == AI_NAME:
                        result_chunks.append(str(content))
                else:
                    result_chunks.append(str(chunk))
            
            if not self.is_cancelled:
                # 模拟流式处理，逐块发送给voice模块
                if self.voice_integration:
                    try:
                        final_text = ''.join(result_chunks)
                        # 模拟流式文本输入
                        import threading
                        def simulate_streaming():
                            # 按句子分割发送
                            sentences = final_text.split('。')
                            for sentence in sentences:
                                if sentence.strip():
                                    self.voice_integration.receive_text_chunk(sentence.strip() + '。')
                                    time.sleep(0.1)  # 模拟延迟
                            # 完成处理
                            self.voice_integration.finish_processing()
                        
                        threading.Thread(target=simulate_streaming, daemon=True).start()
                    except Exception as e:
                        print(f"语音集成错误: {e}")
                
                self.progress_updated.emit(90, "整理回复内容")
                await asyncio.sleep(0.2)  # 短暂等待，让用户看到进度
                
                elapsed = time.time() - start_time
                self.status_changed.emit(f"思考完成 (用时 {elapsed:.1f}s)")
                self.progress_updated.emit(100, "准备显示")
                
                return ''.join(result_chunks)
            else:
                return ""
                
        except Exception as e:
            self.error_occurred.emit(f"批量处理错误: {str(e)}")
            raise 