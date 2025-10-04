@echo off
chcp 65001 >nul
title Naga Agent - Tray Mode
cd /d "%~dp0"

set DIR=.venv
set DIRR=venv

if exist "%DIR%\" (
    call "%DIR%\Scripts\activate.bat"
) else (
    if exist "%DIRR%\" (
        call "%DIRR%\Scripts\activate.bat"
    ) else (
        echo 未查找到虚拟环境，请创建虚拟环境并安装依赖
        pause
        exit
    )
)

python main.py
pause
