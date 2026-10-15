@echo off
title 天气预警推送 - 运行中（请勿关闭本窗口）
set "PY=python"
set "BUNDLED=%~dp0..\..\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED%" set "PY=%BUNDLED%"
echo 天气预警监测已启动，保持本窗口打开即可自动监测并推送。
echo 关闭本窗口即停止监测。
echo 若要开机自动运行（推荐），请改用“一键安装计划任务.bat”。
echo.
"%PY%" "%~dp0main.py" --loop
echo.
echo 监测已停止。按任意键关闭。
pause >nul