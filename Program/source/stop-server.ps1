# FlowDesk 局域网服务端停止脚本（机器 A）
# 用法： powershell -ExecutionPolicy Bypass -File stop-server.ps1
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root 'data\server.pid'
if (Test-Path $pidFile) {
    $serverPid = Get-Content $pidFile
    try {
        Stop-Process -Id $serverPid -Force -ErrorAction Stop
        Write-Host "已停止 FlowDesk 服务端（PID $serverPid）。"
    } catch { Write-Host '服务端进程已不在运行（可能已手动停止）。' }
    Remove-Item $pidFile -Force
} else {
    Write-Host '未找到 server.pid，服务端可能未通过 start-server.ps1 启动。'
}
