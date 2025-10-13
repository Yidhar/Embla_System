import json
import os
from pathlib import Path
from typing import Dict, Any, List
from langchain_community.utilities import SearxSearchWrapper
from system.config import config

class OnlineSearchAgent:
    
    name = "OnlineSearchAgent"
    instructions = "使用SearXNG进行网页搜索，并将结果作为外部信息提供给AI参考"
    
    def __init__(self):
        # 从配置中获取SearXNG URL
        self.searxng_url = None
        self.engines = ["google"]
        self.num_results = 5
        
        # 1: 从全局config对象读取
        try:
            if hasattr(config, 'online_search'):
                search_config = config.online_search
                if hasattr(search_config, 'searxng_url') and search_config.searxng_url:
                    self.searxng_url = search_config.searxng_url
                if hasattr(search_config, 'engines') and search_config.engines:
                    self.engines = search_config.engines
                if hasattr(search_config, 'num_results') and search_config.num_results:
                    self.num_results = int(search_config.num_results)
        except Exception as e:
            print(f"[WARN] 从全局配置读取SearXNG配置时出错: {e}")
            
        # 2: 直接从根目录config.json文件读取
        if not self.searxng_url:
            try:
                config_path = Path(__file__).parent.parent.parent / "config.json"
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if 'online_search' in config_data:
                        if 'searxng_url' in config_data['online_search']:
                            self.searxng_url = config_data['online_search']['searxng_url']
                        if 'engines' in config_data['online_search']:
                            self.engines = config_data['online_search']['engines']
                        if 'num_results' in config_data['online_search']:
                            self.num_results = int(config_data['online_search']['num_results'])
            except Exception as e:
                print(f"[WARN] 从config.json文件读取SearXNG配置时出错: {e}")
        
        # 3: 从环境变量读取
        if not self.searxng_url:
            env_url = os.getenv("SEARXNG_URL")
            if env_url:
                self.searxng_url = env_url
            
        # 如果仍然没有URL，使用默认值
        if not self.searxng_url:
            self.searxng_url = "http://localhost:8080"
        
        # 初始化SearX搜索包装器
        try:
            self.search_wrapper = SearxSearchWrapper(searx_host=self.searxng_url)
            print(f"[OK] OnlineSearchAgent初始化完成，SearXNG URL: {self.searxng_url}, 引擎: {self.engines}, 结果数: {self.num_results}")
        except Exception as e:
            print(f"[ERROR] 初始化SearXSearchWrapper失败: {e}")
            self.search_wrapper = None
    
    async def search(self, query: str, engines: List[str] = None, num_results: int = None) -> Dict[str, Any]:
        """执行搜索"""
        if not self.search_wrapper:
            return {"success": False, "error": "SearXNG搜索包装器未正确初始化"}
        
        try:
            # 使用参数或默认值
            search_engines = engines or self.engines
            search_num_results = num_results or self.num_results
            
            # 构建查询参数
            kwargs = {
                "engines": search_engines,
                "num_results": search_num_results
            }
            
            # 执行搜索
            results = self.search_wrapper.run(query, **kwargs)
            
            if results:
                # 格式化为AI可用的格式
                formatted_results = "外部搜索信息:\n"
                
                # 如果结果是字符串，尝试解析为结构化数据
                if isinstance(results, str):
                    formatted_results += results
                else:
                    # 如果结果是列表，格式化每个结果
                    for i, result in enumerate(results, 1):
                        formatted_results += f"  - 结果 {i}:\n"
                        if hasattr(result, 'title'):
                            formatted_results += f"    - 标题: {result.title}\n"
                        if hasattr(result, 'link'):
                            formatted_results += f"    - 链接: {result.link}\n"
                        if hasattr(result, 'snippet'):
                            formatted_results += f"    - 摘要: {result.snippet}\n"
                        formatted_results += "\n"
                
                return {
                    "success": True, 
                    "data": formatted_results,
                    "raw_data": results if isinstance(results, list) else [results]
                }
            else:
                return {
                    "success": False, 
                    "error": "搜索未返回结果"
                }

        except Exception as e:
            return {"success": False, "error": f"搜索执行失败: {str(e)}"}

    async def handle_handoff(self, data: dict) -> str:
        """处理搜索请求"""
        try:
            tool_name = data.get("tool_name", "").lower()
            
            if tool_name == "网页搜索":
                query = data.get("query")
                if not query:
                    return json.dumps({
                        "status": "error",
                        "message": "搜索需要指定查询内容（query参数）",
                        "data": {}
                    }, ensure_ascii=False)
                
                # 获取可选参数
                engines = data.get("engines")
                num_results = data.get("num_results")
                
                # 执行搜索
                search_result = await self.search(query, engines, num_results)
                
                if search_result["success"]:
                    return json.dumps({
                        "status": "ok",
                        "message": "搜索完成",
                        "data": search_result["data"],
                        "raw_data": search_result.get("raw_data", [])
                    }, ensure_ascii=False)
                else:
                    return json.dumps({
                        "status": "error",
                        "message": f"搜索失败: {search_result['error']}",
                        "data": {}
                    }, ensure_ascii=False)
            else:
                return json.dumps({
                    "status": "error",
                    "message": f"不支持的操作: {tool_name}，支持的操作：网页搜索",
                    "data": {}
                }, ensure_ascii=False)
                
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"搜索Agent处理异常: {str(e)}",
                "data": {}
            }, ensure_ascii=False)


def create_online_search_agent():
    """创建OnlineSearchAgent实例"""
    return OnlineSearchAgent()


def validate_agent_config():
    """验证Agent配置"""
    try:
        # 检查SearXNG URL
        searxng_url = None
        
        # 方法1: 从全局配置读取
        try:
            if hasattr(config, 'online_search') and hasattr(config.online_search, 'searxng_url'):
                searxng_url = config.online_search.searxng_url
        except Exception:
            pass
            
        # 方法2: 从config.json文件读取
        if not searxng_url:
            try:
                config_path = Path(__file__).parent.parent.parent / "config.json"
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if 'online_search' in config_data and 'searxng_url' in config_data['online_search']:
                        searxng_url = config_data['online_search']['searxng_url']
            except Exception:
                pass
        
        # 方法3: 从环境变量读取
        if not searxng_url:
            searxng_url = os.getenv("SEARXNG_URL")
        
        if not searxng_url or searxng_url == "http://localhost:8080":
            return False, "SearXNG URL未配置，将使用默认值"
        
        return True, "配置验证通过"
    except Exception as e:
        return False, f"配置验证失败: {str(e)}"


def get_agent_dependencies():
    """获取Agent依赖"""
    return [
        "langchain-community",
        "json",
        "os"
    ]