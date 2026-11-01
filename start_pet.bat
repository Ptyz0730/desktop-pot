@echo off
chcp 65001 >nul
rem 启动桌面宠物（无控制台窗口）。ASCII 文件名版本，路径兼容性最好。
setlocal
set HERE=%~dp0
set PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe
if not exist "%PY%" set PY=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe
if not exist "%PY%" set PY=pythonw
start "" "%PY%" "%HERE%desktop_pet.py" %*
endlocal
