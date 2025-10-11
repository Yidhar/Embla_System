import os
import logging
from system.config import config
# 设置日志
logger = logging.getLogger(__name__)

class MindmapTool():
    def __init__(self, window):
        self.window = window
        
    def open_mind_map(self):
        """打开心智云图"""
        try:
            # 检查是否存在知识图谱文件
            graph_file = "logs/knowledge_graph/graph.html"
            quintuples_file = "logs/knowledge_graph/quintuples.json"
            
            # 如果quintuples.json存在，删除现有的graph.html并重新生成
            if os.path.exists(quintuples_file):
                # 如果graph.html存在，先删除它
                if os.path.exists(graph_file):
                    try:
                        os.remove(graph_file)
                        logger.debug(f"已删除旧的graph.html文件")
                    except Exception as e:
                        logger.error(f"删除graph.html文件失败: {e}")
                
                # 生成新的HTML
                self.chat_tool.add_user_message("系统", "🔄 正在生成心智云图...")
                try:
                    from summer_memory.quintuple_visualize_v2 import visualize_quintuples
                    visualize_quintuples()
                    if os.path.exists(graph_file):
                        import webbrowser
                        # 获取正确的绝对路径
                        if os.path.isabs(graph_file):
                            abs_graph_path = graph_file
                        else:
                            # 如果是相对路径，基于项目根目录构建绝对路径
                            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                            abs_graph_path = os.path.join(current_dir, graph_file)
                        
                        webbrowser.open("file:///" + abs_graph_path)
                        self.chat_tool.add_user_message("系统", "🧠 心智云图已生成并打开")
                    else:
                        self.chat_tool.add_user_message("系统", "❌ 心智云图生成失败")
                except Exception as e:
                    self.chat_tool.add_user_message("系统", f"❌ 生成心智云图失败: {str(e)}")
            else:
                # 没有五元组数据，提示用户
                self.chat_tool.add_user_message("系统", "❌ 未找到五元组数据，请先进行对话以生成知识图谱")
        except Exception as e:
            self.chat_tool.add_user_message("系统", f"❌ 打开心智云图失败: {str(e)}")

from ..utils.lazy import lazy
@lazy
def mindmap():
    return MindmapTool(config.window)