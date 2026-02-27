@echo off
chcp 65001

call .venv\Scripts\activate.bat
cd Embla_core
npm run dev
