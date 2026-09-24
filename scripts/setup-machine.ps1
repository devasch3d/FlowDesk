# FlowDesk 多机协作 - 单机初始化脚本
# 用法: powershell -ExecutionPolicy Bypass -File scripts/setup-machine.ps1 -Machine A
# 每台机器只运行一次: 克隆仓库 -> 创建/切换到自己的分支 -> 同步 main

param(
    [Parameter(Mandatory=$true)]
    [string]$Machine
)

$ErrorActionPreference = 'Stop'

# ==== 按实际仓库地址修改 ====
$RepoUrl = 'https://github.com/devasch3d/FlowDesk.git'
$RepoName = 'FlowDesk'

Write-Host "== FlowDesk 初始化 (机器 $Machine) ==" -ForegroundColor Cyan

# 1. 检查 Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error '未检测到 Git，请先安装 Git for Windows: https://git-scm.com/download/win'
    exit 1
}

# 2. 是否已克隆
if (Test-Path $RepoName) {
    Write-Host "[跳过] 仓库已存在，直接进入 $RepoName" -ForegroundColor Yellow
} else {
    Write-Host "[1/4] 克隆仓库 ..."
    git clone $RepoUrl
    if ($LASTEXITCODE -ne 0) { Write-Error '克隆失败：请检查代理与网络（git ls-remote 验证）'; exit 1 }
}
Set-Location $RepoName

# 3. 拉取最新 main 并创建/切换分支
Write-Host "[2/4] 同步 main ..."
git fetch origin main
git pull origin main

$Branch = "feat/$Machine"
$remoteExists = git ls-remote --heads origin "refs/heads/$Branch"
if ($remoteExists) {
    Write-Host "[3/4] 远程分支 $Branch 已存在，切换到该分支 ..."
    git checkout -b $Branch "origin/$Branch" 2>$null
    if ($LASTEXITCODE -ne 0) { git checkout $Branch }
} else {
    Write-Host "[3/4] 创建并切换到新分支 $Branch ..."
    git checkout -b $Branch
}

# 4. 同步 main 到自己的分支
Write-Host "[4/4] 合并 main 到 $Branch ..."
git merge origin/main

Write-Host ""
Write-Host "== 完成 ==" -ForegroundColor Green
Write-Host "当前分支: $(git branch --show-current)"
Write-Host "你的负责目录见仓库根: 02-任务切分表.md"
Write-Host "开工前请阅读: 01-协作规范.md 与 prompts/ 下对应提示词模板"
