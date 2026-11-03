@echo off
chcp 65001 >nul
title 打包 AWA 数据管理
cd /d "%~dp0"

echo ==============================================
echo  将 AWA 数据管理打包为单文件 exe
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

echo [3/3] 开始打包（约 1-3 分钟）...
echo.
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "AWA数据管理" ^
    --icon NONE ^
    desktop.py

if errorlevel 1 (
    echo.
    echo [失败] 打包过程报错，请把上面的信息发给我
    pause
    exit /b 1
)

echo.
echo ==============================================
echo  完成！可执行文件在：
echo    %~dp0dist\AWA数据管理.exe
echo.
echo  这个 exe 可以单独拷给同事使用，
echo  对方电脑无需安装 Python。
echo ==============================================
echo.
pause
