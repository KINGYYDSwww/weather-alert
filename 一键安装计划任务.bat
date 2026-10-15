@echo off
title 天气预警推送 - 一键安装计划任务
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo 正在申请管理员权限，请在弹窗中点“是”...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)
echo 正在安装计划任务：每 10 分钟自动监测天气预警并推送到手机
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_task.ps1"
echo.
echo 安装流程结束。按任意键关闭本窗口。
pause >nul