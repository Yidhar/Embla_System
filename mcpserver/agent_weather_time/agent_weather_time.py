# agent_weather_time.py # 天气和时间查询Agent
import json
import aiohttp
import requests
import re
from datetime import datetime, timedelta
from system.config import config, AI_NAME

from mcpserver.agent_weather_time.city_codes import codes_map

IPIP_URL = "https://myip.ipip.net/"


class WeatherTimeTool:
    """天气和时间工具类"""
    def __init__(self):
        self._ip_info = None
        self._local_ip = None
        self._local_city = None
        self._get_local_ip_and_city()
        import asyncio
        try:
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self._preload_ip_info())
            except RuntimeError:
                self._ip_info = None
        except Exception:
            self._ip_info = None

    def _get_local_ip_and_city(self):
        """同步获取本地IP和城市"""
        try:
            resp = requests.get(IPIP_URL, timeout=5)
            resp.encoding = 'utf-8'
            html = resp.text
            match = re.search(r"当前 IP：([\d\.]+)\s+来自于：(.+?)\s{2,}", html)
            if match:
                self._local_ip = match.group(1)
                self._local_city = match.group(2)
            else:
                self._local_ip = None
                self._local_city = None
        except Exception as e:
            self._local_ip = None
            self._local_city = None

    async def _preload_ip_info(self):
        pass  # 兼容保留，不再异步获取IP

    async def get_weather(self, code):
        """调用itboy天气接口，返回实况天气+未来3天预报"""
        url = f'http://t.weather.itboy.net/api/weather/city/{code}'
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
                body: dict = data['data']
                now = {}

                for k, v in body.items():
                    if k == 'forecast':
                        continue
                    now[k] = v

                now['weather'] = body['forecast'][0]

                return now, body['forecast'][:3], body['forecast']

    async def handle(self, action=None, ip=None, city=None, query=None, format=None, **kwargs):
        """统一处理入口，支持LLM传入city参数或自动识别本地城市"""
        # 优先使用LLM传入的city参数，如果没有则使用本地城市
        if city and city.strip():
            city_str = city.strip()
            province, city_name = city_str, city_str
            match = re.match(r"^([\u4e00-\u9fa5]+) ([\u4e00-\u9fa5]+)$", city_str)
            if match:
                province = match.group(1)
                city_name = match.group(2)
            else:
                parts = city_str.split()
                if len(parts) >= 2:
                    province = parts[-2]
                    city_name = parts[-1]
                else:
                    province = ''
                    city_name = ''
        else:
            city_str = getattr(self, '_local_city', '') or ''
            if city_str.startswith('中国'):
                city_str = city_str[2:].strip()
            province, city_name = city_str, city_str
            if city_str:
                match = re.match(r"^([\u4e00-\u9fa5]+) ([\u4e00-\u9fa5]+)$", city_str)
                if match:
                    province = match.group(1)
                    city_name = match.group(2)
                else:
                    parts = city_str.split()
                    if len(parts) >= 2:
                        province = parts[-2]
                        city_name = parts[-1]
                    else:
                        province = ''
                        city_name = ''

        # 查询城市代码
        city_code = codes_map.get(f'{province}{city_name}')

        if not city_code:
            return {'status': 'error', 'message': f'未找到城市编码或该城市不存在: {city_name}, 确保city格式为{{省 市}}, 如:湖北 武汉, 直辖市请重复两遍市名, 如:北京 北京'}

        now, d3, d15 = await self.get_weather(city_code)

        # 今日天气查询
        if action in ['today_weather', 'current_weather', 'today']:
            return {'city': city_name, 'response': now}

        # 未来天气查询
        elif action in ['forecast_weather', 'future_weather', 'forecast', 'weather_forecast']:
            return {'city': city_name, 'response': d15}

        elif action in ['time', 'get_time', 'current_time']:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return {
                'status': 'ok',
                'message': '当前系统时间',
                'data': {
                    'time': current_time,
                    'city': city_name,
                    'province': province
                }
            }
        else:
            return {'status': 'error', 'message': f'未知操作: {action}'}


class WeatherTimeAgent:
    """天气和时间Agent"""
    name = "WeatherTime Agent"

    def __init__(self):
        self._tool = WeatherTimeTool()
        import sys
        ip_str = getattr(self._tool, '_local_ip', '未获取到IP')
        city_str = getattr(self._tool, '_local_city', '未知城市')
        sys.stderr.write(f'✅ WeatherTimeAgent初始化完成，登陆地址：{city_str}\n')

    async def handle_handoff(self, task: dict) -> str:
        try:
            action = task.get("tool_name")
            if not action:
                return json.dumps({"status": "error", "message": "缺少tool_name参数", "data": {}}, ensure_ascii=False)
            ip = task.get("ip")
            city = task.get("city")
            query = task.get("query")
            format = task.get("format")
            result = await self._tool.handle(action, ip, city, query, format)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e), "data": {}}, ensure_ascii=False)
