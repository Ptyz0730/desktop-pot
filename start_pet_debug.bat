@echo off
chcp 65001 >nul
rem 带控制台启动：能看到报错信息，方便排查为什么看不到宠物。
setlocal
set HERE=%~dp0
set PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
if not exist "%PY%" set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
"%PY%" "%HERE%desktop_pet.py" %*
echo.
echo 桌宠已退出。
pause
endlocal
