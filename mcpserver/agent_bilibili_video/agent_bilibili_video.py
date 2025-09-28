# agent_bilibili_video.py # B站视频信息获取Agent
import json # 导入json模块
import asyncio
from nagaagent_core.vendors.agents import Agent, ComputerTool # 统一代理 #
from system.config import config, AI_NAME # 导入配置

# 导入bilibili-api-python库
from bilibili_api import video, sync

class BilibiliVideoTool:
    """B站视频信息工具类"""
    def __init__(self):
        pass

    async def get_video_info(self, bvid: str):
        """获取B站视频详细信息"""
        try:
            # 创建视频对象
            v = video.Video(bvid=bvid)
            
            # 获取视频信息
            info = await v.get_info()
            
            # 提取关键信息
            data = {
                "bvid": bvid,
                "title": info["title"],
                "desc": info["desc"],
                "duration": info["duration"],
                "pubdate": info["pubdate"],
                "view": info["stat"]["view"],
                "danmaku": info["stat"]["danmaku"],
                "comment": info["stat"]["comment"],
                "favorite": info["stat"]["favorite"],
                "coin": info["stat"]["coin"],
                "share": info["stat"]["share"],
                "like": info["stat"]["like"],
                "uploader": info["owner"]["name"],
                "mid": info["owner"]["mid"],
                "pic": info["pic"]
            }
            
            return {"status": "ok", "message": "获取视频信息成功", "data": data}
        except Exception as e:
            return {"status": "error", "message": f"获取视频信息失败: {str(e)}", "data": {}}

    async def handle(self, tool_name=None, bvid=None, **kwargs):
        """统一处理入口"""
        if not tool_name:
            return {"status": "error", "message": "缺少tool_name参数", "data": {}}
            
        if tool_name == "get_video_info":
            if not bvid:
                return {"status": "error", "message": "缺少bvid参数", "data": {}}
            return await self.get_video_info(bvid)
        else:
            return {"status": "error", "message": f"未知操作: {tool_name}", "data": {}}


class BilibiliVideoAgent(Agent):
    """B站视频信息Agent"""
    def __init__(self):
        self._tool = BilibiliVideoTool() # 预加载工具
        super().__init__(
            name="Bilibili Video Agent", # Agent名称
            instructions="B站视频信息获取智能体，可以获取B站视频的播放量、点赞数等信息", # 角色描述
            tools=[ComputerTool(self._tool)], # 注入工具
            model="bilibili-video-use-preview" # 使用统一模型
        )
        import sys
        sys.stderr.write('✅ BilibiliVideoAgent初始化完成\n')

    async def handle_handoff(self, task: dict) -> str:
        try:
            # 获取参数
            tool_name = task.get("tool_name")
            bvid = task.get("bvid")
            
            # 调用工具处理
            result = await self._tool.handle(tool_name, bvid)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return json.dumps({"status": "error", "message": str(e), "data": {}}, ensure_ascii=False)