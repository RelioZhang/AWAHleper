@echo off
rem AWA Data Manager V3.0 - launch without console window
rem Uses pythonw so no black command prompt appears.
cd /d "%~dp0"

set "PYW="
for %%P in (pythonw.exe) do if not "%%~$PATH:P"=="" set "PYW=%%~$PATH:P"

if not defined PYW (
    if exist "%LocalAppData%\Programs\Python\Python313\pythonw.exe" set "PYW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
)
if not defined PYW (
    if exist "%LocalAppData%\Programs\Python\Python312\pythonw.exe" set "PYW=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
)
if not defined PYW (
    if exist "%LocalAppData%\Programs\Python\Python311\pythonw.exe" set "PYW=%LocalAppData%\Programs\Python\Python311\pythonw.exe"
)

if not defined PYW (
    echo pythonw.exe not found. Please install Python 3.9+ and add it to PATH.
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0launcher.py" %*
exit /b 0
