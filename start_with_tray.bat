@echo off
chcp 65001 >nul
title Naga Agent - Tray Mode
cd /d %~dp0
call .venv\Scripts\activate.bat
rem ----------------------------------------------
python main.py
pause
