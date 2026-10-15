# 删除计划任务。
#   powershell -ExecutionPolicy Bypass -File .\uninstall_task.ps1
$ErrorActionPreference = "Stop"
$TaskName = "WeatherAlertPush"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "✅ 已删除计划任务 '$TaskName'。"
} else {
    Write-Host "未找到计划任务 '$TaskName'（无需删除）。"
}
