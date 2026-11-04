@echo off
rem AWA 数据管理 V3.0 · 无黑窗启动
rem 用 pythonw 运行 launcher.py：不弹命令行窗口，界面以独立应用窗口打开
cd /d "%~dp0"

set "PYW="
for %%P in (pythonw.exe) do if not "%%~$PATH:P"=="" set "PYW=%%~$PATH:P"
if not defined PYW (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
        if exist "%%D\pythonw.exe" set "PYW=%%D\pythonw.exe"
    )
)

if not defined PYW (
    echo 未找到 pythonw.exe，请先安装 Python 3.9+ 并加入 PATH。
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0launcher.py" %*
exit /b 0
