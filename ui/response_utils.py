import json

def extract_message(response: str) -> str:
    """
    解析后端返回的json字符串，优先取data.content，其次message，否则原样返回
    支持递归解析嵌套JSON和多步数组，自动用\n分隔多条消息
    :param response: 后端返回的json字符串
    :return: message内容（若解析失败则原样返回）
    """
    if not isinstance(response, str):
        return str(response)
    
    # 先尝试直接解析
    try:
        data = json.loads(response)
        # 如果是数组，递归拼接所有消息
        if isinstance(data, list):
            return '\n'.join([_recursive_extract(item) for item in data if _recursive_extract(item)])
        extracted = _recursive_extract(data)
        if extracted and extracted != response:
            return extracted
    except:
        pass
    
    # 如果失败，尝试查找JSON子串
    try:
        # 查找可能的JSON起始位置
        start_pos = response.find('{')
        if start_pos >= 0:
            # 从第一个{开始尝试解析
            json_part = response[start_pos:]
            data = json.loads(json_part)
            if isinstance(data, list):
                return '\n'.join([_recursive_extract(item) for item in data if _recursive_extract(item)])
            extracted = _recursive_extract(data)
            if extracted:
                return extracted
    except:
        pass
    
    return response

def _recursive_extract(data) -> str:
    """递归提取消息内容"""
    if isinstance(data, dict):
        # 优先级：data.content > message > content > text > value
        for key in ['data', 'message', 'content', 'text', 'value']:
            if key in data:
                value = data[key]
                if isinstance(value, dict):
                    # 递归处理嵌套字典
                    nested_result = _recursive_extract(value)
                    if nested_result:
                        return nested_result
                elif isinstance(value, str) and value.strip():
                    # 检查是否还是JSON格式
                    try:
                        nested_data = json.loads(value)
                        nested_result = _recursive_extract(nested_data)
                        if nested_result:
                            return nested_result
                    except:
                        pass
                    return value.strip()
                elif value is not None:
                    return str(value).strip()
        
        # 如果没有找到标准字段，返回第一个字符串值
        for value in data.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
    elif isinstance(data, str):
        return data.strip()
    
    return ""
