@echo off
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
        echo δ�ҵ����⻷��
		pause
        exit
    )
)

python main.py
pause
