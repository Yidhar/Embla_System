# B站视频信息Agent

## 简介

B站视频信息Agent是一个MCP服务，用于获取B站视频的详细信息，包括播放量、点赞数、评论数等数据。

## 功能特性

- 获取B站视频标题和描述
- 获取视频播放量、弹幕数、评论数等统计数据
- 获取视频作者信息
- 支持通过BV号查询视频信息

## 安装依赖

在使用此服务前，请确保已安装以下依赖：

```bash
pip install bilibili-api-python
```

## 使用方法

在任务请求中指定以下参数：

```json
{
  "tool_name": "get_video_info",
  "bvid": "<B站视频BV号>"
}
```

### 示例

```json
{
  "tool_name": "get_video_info",
  "bvid": "BV1GJ411x7h7"
}
```

## 返回数据格式

```json
{
  "status": "ok",
  "message": "获取视频信息成功",
  "data": {
    "bvid": "BV1GJ411x7h7",
    "title": "视频标题",
    "desc": "视频描述",
    "duration": 213,
    "pubdate": 1612345678,
    "view": 1000000,
    "danmaku": 10000,
    "comment": 5000,
    "favorite": 50000,
    "coin": 30000,
    "share": 10000,
    "like": 100000,
    "uploader": "上传者名称",
    "mid": 123456789,
    "pic": "http://i0.hdslb.com/bfs/archive/..."
  }
}
```

## 错误处理

如果请求失败，将返回以下格式的错误信息：

```json
{
  "status": "error",
  "message": "错误描述",
  "data": {}
}
```
