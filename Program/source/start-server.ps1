# FlowDesk 局域网服务端一键启动脚本（机器 A）
# 用法： powershell -ExecutionPolicy Bypass -File start-server.ps1
# 效果： 启动后端(0.0.0.0:8000) → 自动开本机浏览器 → 显示局域网访问地址
# 停止： 运行 stop-server.ps1（或任务栏退出相关 python 进程）
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Write-Host '未找到 .venv\Scripts\python.exe，请先按 README 创建虚拟环境'; exit 1 }

# 已在运行？直接显示地址
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { Write-Host 'FlowDesk 已在运行（端口 8000）。'; $running = $true }
} catch { $running = $false }

if (-not $running) {
    # 启动服务：独立进程，关掉本窗口不影响服务
    $proc = Start-Process -FilePath $py -ArgumentList 'launcher.py','--host','0.0.0.0','--port','8000','--headless' -WindowStyle Hidden -PassThru
    # 等待就绪（最多 15 秒）
    $ok = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ok = $true; break }
        } catch {}
    }
    if (-not $ok) { Write-Host '启动失败，请查看 data\flowdesk.log'; exit 1 }
    # 记录 PID 供 stop-server.ps1 使用
    $dataDir = Join-Path $root 'data'
    if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }
    $proc.Id | Out-File (Join-Path $dataDir 'server.pid') -Encoding UTF8
    Write-Host 'FlowDesk 服务端已启动。'
}

# 取局域网 IPv4（跳过回环/APIPA/隧道）
$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
    Select-Object -First 1).IPAddress

Write-Host ''
Write-Host '访问地址：'
Write-Host '  本机    http://127.0.0.1:8000'
if ($ip) { Write-Host ("  局域网  http://{0}:8000   （手机/其他电脑，需同一 WiFi）" -f $ip) }
if ($ip) { Write-Host '  手机端建议把上面局域网地址加入浏览器书签，方便下次直接打开。' }

# 自动打开本机浏览器
try { Start-Process 'http://127.0.0.1:8000' } catch {}
