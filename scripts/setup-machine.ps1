<#
.SYNOPSIS
  多机协作初始化脚本：克隆云端仓库、创建/切换到本机专属分支、同步 main。

.DESCRIPTION
  在每台机器上各运行一次。用法（在要放仓库的目录下执行）：
    powershell -ExecutionPolicy Bypass -File setup-machine.ps1 -Machine A
  机器 A/B 用 Codex Plus，机器 C/D 用豆包工作版，脚本通用。

.PARAMETER Machine
  机器标识：A / B / C / D，对应分支 feat/A ... feat/D。

.PARAMETER RepoUrl
  云端私有仓库远程地址（SSH 或 HTTPS）。默认是占位符，使用前必须替换。

.PARAMETER TargetDir
  仓库克隆到哪个目录，默认当前目录。
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "B", "C", "D")]
    [string]$Machine,

    # TODO: 替换为云端私有仓库地址（SSH 或 HTTPS）
    [string]$RepoUrl = "https://github.com/devasch3d/FlowDesk.git",

    [string]$TargetDir = "."
)

$ErrorActionPreference = "Stop"
$branch = "feat/$Machine"

Write-Host "==> 机器 $Machine 初始化：分支 $branch"

# 1. 克隆（或进入已有仓库）
if (-not (Test-Path (Join-Path $TargetDir ".git"))) {
    Write-Host "==> 克隆仓库..."
    git clone $RepoUrl $TargetDir
    if ($LASTEXITCODE -ne 0) { throw "克隆失败，请检查 RepoUrl 是否可访问、账号权限是否已开通" }
    Set-Location $TargetDir
}
else {
    Set-Location $TargetDir
    Write-Host "==> 仓库已存在，拉取远程信息..."
    git fetch --all --prune
}

# 2. 创建/切换到本机专属分支
$current = git branch --show-current
if ($current -ne $branch) {
    $localExists = git branch --list $branch
    $remoteExists = git ls-remote --heads origin "refs/heads/$branch"
    if ($localExists) {
        git checkout $branch
    }
    elseif ($remoteExists) {
        git checkout -b $branch "origin/$branch"
    }
    else {
        git checkout -b $branch
    }
    if ($LASTEXITCODE -ne 0) { throw "切换/创建分支失败" }
}

# 3. 同步 main（远端为空仓库时跳过并提示）
$mainExists = git ls-remote --heads origin main
if ($mainExists) {
    Write-Host "==> 同步 main 最新代码到 $branch ..."
    git pull origin main --rebase
    if ($LASTEXITCODE -ne 0) { throw "同步失败：可能与其他分支有冲突，请按规范第 6 节处理" }
}
else {
    Write-Host "==> 远端还没有 main（空仓库）。请先按 README 第 4 步推送初始提交，再回来同步。"
}

Write-Host ""
Write-Host "完成。当前分支：$(git branch --show-current)"
Write-Host "下一步："
Write-Host "  1) 按任务切分表只修改你负责的目录"
Write-Host "  2) 完成后 git add <你的文件> && git commit -m 'type(scope): 简述'"
Write-Host "  3) git push origin $branch"
Write-Host "  4) 到 Git 平台发起 PR：$branch -> main"
