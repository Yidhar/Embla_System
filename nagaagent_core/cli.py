#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NagaAgent Core CLI工具
"""

import sys
import argparse


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description="NagaAgent Core CLI工具")
    parser.add_argument("--version", action="version", version="1.0.1")
    parser.add_argument("--info", action="store_true", help="显示包信息")
    
    args = parser.parse_args()
    
    if args.info:
        print("NagaAgent Core v1.0.1")
        print("包含核心功能和API服务器相关依赖")
        print("核心依赖: mcp, openai, python-dotenv, requests, aiohttp")
        print("API依赖: flask, gevent, fastapi, uvicorn")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
