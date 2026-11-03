@echo off
chcp 65001 >nul
title 打包 AWA 数据管理
cd /d "%~dp0"

echo ==============================================
echo  将 AWA 数据管理打包为「免安装文件夹」
echo ==============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.9+
    pause
    exit /b 1
)

echo [1/3] 检查 PyInstaller ...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo      未安装，正在安装 ...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] 安装失败，请检查网络
        pause
        exit /b 1
    )
)

echo [2/3] 检查 PySide6 ...
python -c "import PySide6" 2>nul
if errorlevel 1 (
    echo      未安装，正在安装 ...
    python -m pip install PySide6
    if errorlevel 1 (
        echo [错误] 安装失败，请检查网络
        pause
        exit /b 1
    )
)

echo [3/3] 开始打包（约 2-4 分钟）...
echo.
rem 用 onedir 而不是 onefile：启动不用解压，1 秒内就能开；
rem 把 dist\AWA数据管理 整个文件夹压缩后发同事，解压双击 exe 即用。
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name "AWA数据管理" ^
    --hidden-import PySide6.QtSvg ^
    --exclude-module tkinter ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.QtWebEngineQuick ^
    --exclude-module PySide6.Qt3DCore ^
    --exclude-module PySide6.QtMultimedia ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtQml ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    --exclude-module pandas ^
    desktop.py

if errorlevel 1 (
    echo.
    echo [失败] 打包过程报错，请把上面的信息发给我
    pause
    exit /b 1
)

echo.
echo ==============================================
echo  完成！程序在：
echo    %~dp0dist\AWA数据管理\AWA数据管理.exe
echo.
echo  把 dist\AWA数据管理 整个文件夹压缩后发给同事，
echo  对方解压双击 exe 就能用，无需安装 Python。
echo ==============================================
echo.
pause
