# 安装 Windows 计划任务：每 N 分钟自动运行一次天气预警监测。
# 用法（推荐直接双击同目录的"一键安装计划任务.bat"，它会自动申请管理员权限）：
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -IntervalMinutes 5
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -PythonPath "C:\path\python.exe"
param(
    [int]$IntervalMinutes = 10,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MainPy = Join-Path $ScriptDir "main.py"

# 1) 确定 Python 解释器
if (-not $PythonPath) {
    $candidates = @(
        (Join-Path $ScriptDir "..\..\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"),
        ("C:\Users\" + $env:USERNAME + "\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe")
    )
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { $PythonPath = $c; break }
    }
}

if (-not $PythonPath -or -not (Test-Path $PythonPath)) {
    Write-Host "未找到 Python。请安装 Python 3.10+，或用 -PythonPath 指定 python.exe 完整路径。" -ForegroundColor Red
    exit 1
}
Write-Host "使用 Python: $PythonPath"

# 2) 注册计划任务
$TaskName = "WeatherAlertPush"
try {
    $Arg = '"' + $MainPy + '"'
    $Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $Arg -WorkingDirectory $ScriptDir
    $Trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
    $Principal = New-ScheduledTaskPrincipal -UserId ($env:USERDOMAIN + "\" + $env:USERNAME) -LogonType S4U -RunLevel Limited
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "指定地区天气预警主动推送工具" -Force | Out-Null

    Write-Host ("OK 已创建计划任务 '{0}'：每 {1} 分钟运行一次。" -f $TaskName, $IntervalMinutes) -ForegroundColor Green
    Write-Host "   查看/管理：taskschd.msc -> 任务计划程序库 -> $TaskName"
    Write-Host "   手动立即运行一次测试："
    Write-Host ("    {0} '{1}' --dry-run" -f $PythonPath, $MainPy)
    exit 0
}
catch {
    Write-Host ""
    Write-Host "创建计划任务失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "最常见原因是当前 PowerShell 没有管理员权限。" -ForegroundColor Yellow
    Write-Host "解决办法（任选其一）："
    Write-Host "  A. 直接双击本目录下的【一键安装计划任务.bat】，在弹窗点『是』即可。"
    Write-Host "  B. 以管理员身份打开 PowerShell，然后运行："
    Write-Host ("     powershell -ExecutionPolicy Bypass -File `"{0}`"" -f (Join-Path $ScriptDir 'install_task.ps1'))
    Write-Host "  C. 若无法获得管理员权限，改用【启动监测.bat】手动启动（见 README）。"
    exit 1
}
