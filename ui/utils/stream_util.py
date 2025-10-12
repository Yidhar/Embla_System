from nagaagent_core.vendors.PyQt5.QtCore import QThread, pyqtSignal
from ui.utils.response_util import extract_message
import requests
from system.config import config, logger

class _StreamHttpWorker(QThread):
    chunk = pyqtSignal(str)
    done = pyqtSignal()
    error = pyqtSignal(str)
    status = pyqtSignal(str)
    def __init__(self, url, payload):
        super().__init__()
        self.url = url
        self.payload = payload
        self._cancelled = False
    def cancel(self):
        self._cancelled = True
    def run(self):
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            self.status.emit("连接到AI...")
            # 设置重试策略 - 增加重试次数
            retry_strategy = Retry(
                total=3,  # 增加重试次数
                backoff_factor=1,  # 增加退避时间
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["POST"]  # 明确允许POST方法重试
            )
            # 创建session并配置重试
            session = requests.Session()
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            # 设置headers以支持更好的连接管理
            headers = {
                'Connection': 'keep-alive',
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',  # 明确接受SSE
                'Accept-Encoding': 'gzip, deflate',  # 支持压缩
                'User-Agent': 'NagaAgent-Client/1.0'  # 添加User-Agent
            }
            # 增加超时时间并配置流式请求
            timeout = (30, 120)  # (连接超时, 读取超时)
            resp = session.post(
                self.url,
                json=self.payload,
                headers=headers,
                timeout=timeout,
                stream=True,
                verify=False  # 如果有SSL问题可以临时禁用
            )
            if resp.status_code != 200:
                self.error.emit(
                    f"流式调用失败: HTTP {resp.status_code} - {resp.text[:200]}")
                return
            self.status.emit("正在生成回复...")
            # 使用更大的块大小来读取流
            buffer = []
            for line in resp.iter_lines(chunk_size=8192, decode_unicode=False):
                if self._cancelled:
                    break
                if line:
                    # 处理可能的编码问题
                    try:
                        # 使用UTF-8解码，忽略错误字符
                        line_str = line.decode(
                            'utf-8', errors='ignore').strip()
                        if line_str.startswith('data: '):
                            data_str = line_str[6:]
                            if data_str == '[DONE]':
                                break
                            # 过滤掉心跳包
                            if data_str and data_str != '':
                                # 直接把内容行交回主线程
                                self.chunk.emit(data_str)
                    except Exception as e:
                        print(f"解码错误: {e}")
                        continue
                else:
                    # 处理空行（SSE中心跳）
                    continue
            # 检查响应是否正常结束
            if not self._cancelled:
                resp.close()  # 显式关闭响应
                self.done.emit()
        except requests.exceptions.ChunkedEncodingError as e:
            self.error.emit(f"流式数据解码错误: {str(e)}")
            logger.exception("发生错误")
        except requests.exceptions.ConnectionError as e:
            self.error.emit(f"连接错误: {str(e)}")
            logger.exception("发生错误")
        except requests.exceptions.ReadTimeout as e:
            self.error.emit(f"读取超时: {str(e)}")
            logger.exception("发生错误")
        except requests.exceptions.RequestException as e:
            self.error.emit(f"请求异常: {str(e)}")
            logger.exception("发生错误")
        except Exception as e:
            import traceback
            error_msg = f"未知错误: {str(e)}\n详细信息: {traceback.format_exc()}"
            self.error.emit(error_msg)
            logger.exception("发生错误")

class _NonStreamHttpWorker(QThread):
    finished_text = pyqtSignal(str)
    error = pyqtSignal(str)
    status = pyqtSignal(str)
    def __init__(self, url, payload):
        super().__init__()
        self.url = url
        self.payload = payload
        self._cancelled = False
    def cancel(self):
        self._cancelled = True
    def run(self):
        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            self.status.emit("正在思考...")
            # 设置重试策略
            retry_strategy = Retry(
                total=2,
                backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            # 创建session并配置重试
            session = requests.Session()
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            # 设置headers以支持更好的连接管理
            headers = {
                'Connection': 'keep-alive',
                'Content-Type': 'application/json'
            }
            resp = session.post(self.url, json=self.payload,
                                headers=headers, timeout=120)
            if self._cancelled:
                return
            if resp.status_code != 200:
                self.error.emit(f"非流式调用失败: {resp.text}")
                return
            try:
                result = resp.json()
                final_message = extract_message(result.get("response", ""))
            except Exception:
                final_message = resp.text
            self.finished_text.emit(str(final_message))
        except Exception as e:
            self.error.emit(str(e))