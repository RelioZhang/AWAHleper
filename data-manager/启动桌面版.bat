@echo off
chcp 65001 >nul
title AWA 数据管理
cd /d "%~dp0"

rem 优先用 pythonw 启动，避免黑色命令行窗口
set "PYW="
where pythonw.exe >nul 2>nul && set "PYW=pythonw.exe"

if not defined PYW (
    echo 未找到 pythonw.exe，请确认已安装 Python 并加入 PATH。
    pause
    exit /b 1
)

start "" %PYW% "%~dp0desktop.py" %*
exit /b 0
