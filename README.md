# FlowDesk

AI 驱动的个人与小团队工作管理平台：**桌面客户端（Electron）＋云端服务端**，联网在线、多用户协作、数据自控。

## 产品定位

在一个工作台里完成「建立空间 → 创建项目 → 拆解任务 → 成员执行 → 评论/文件协作 → 仪表盘汇总 → AI 理解项目状态」的完整闭环。典型场景：个人 Side Project、软件开发、课程小组、比赛团队、自由职业、小型创业团队。

- **解决什么问题**：项目、任务、文件、讨论散落在表格/聊天/网盘，状态靠口头同步。FlowDesk 将协作收拢到一条闭环，状态实时可见、全程留痕，AI 基于项目数据提供拆解、总结、搜索与经确认的执行。
- **为什么选择 FlowDesk**：一体化闭环、AI Copilot 原生内置、桌面客户端专注体验、数据可控（自部署服务端）、轻量适用小团队。

## 功能范围

- **M1 Project（已完成）**：项目增删改查、搜索筛选、日期校验、乐观锁、JSON 导出。
- **M2 Account（已完成）**：注册/登录/退出/保持登录、会话管理、scrypt 密码哈希、按 owner_id 的项目权限隔离、登录限流、数据库迁移与备份。
- **M3 Workspace（已完成）**：空间 + 成员多对多、Owner/Admin/Member 角色权限矩阵、按邮箱邀请成员。
- **M4 Task（已完成）**：任务全生命周期（状态/优先级/负责人/截止日/If-Match 乐观锁）。
- **M5 Files（已完成）**：项目附件上传/下载/删除（本地存储、文件名消毒）。
- **M6 Dashboard（已完成）**：空间/项目统计聚合 + 仪表盘视图。
- **M7 Collaboration（已完成）**：任务评论 + 活动动态（全员留痕）。
- **M8 AI Copilot（已完成）**：AI 会话、项目理解、任务提案（经确认才落库，OpenAI 兼容 API）。
- **M9 Electron 客户端 + 服务端化（已完成）**：桌面客户端壳（自动拉起后端）、联网服务端模式（跨源/Host 白名单、远程访问），见 `03-技术架构.md` 第 7 节。

> 架构基线：`03-技术架构.md`（客户端/服务端分层、技术栈、API 契约、M9 联网部署，A 维护）。
> 代码位置：`Program/source/`（详见其中 README.md）。

## 多机协作

- 协作模型：单仓库 + `main` 保护分支 + 每人 `feat/机器编号` 分支 + PR 合入（详见 `01-协作规范.md`）。
- 机器与目录归属：见 `02-任务切分表.md`（当前 A–F 在岗，G 王鹄毅暂离、测试与发布由 A 暂代）。
- 成员操作手册：见 `多机协作成员操作手册.pdf`（仓库外，与规范配套）。
- Agent 提示词模板：`prompts/`（通用边界 + Codex Plus + 豆包工作版）。
- 新机器接入：`powershell -ExecutionPolicy Bypass -File scripts/setup-machine.ps1 -Machine X`（X 为你的机器编号）。

## 仓库内文件导航

| 文件/目录 | 作用 |
| --- | --- |
| `01-协作规范.md` | 分支/所有权/提交/PR/冲突规则，唯一维护人：机器 A |
| `02-任务切分表.md` | 机器 → 分支 → 目录归属，新增机器由负责人（A）维护 |
| `03-技术架构.md` | 产品形态、分层架构、技术栈、API 契约（A 维护） |
| `prompts/` | 各工具 Agent 的边界指令与提示词模板 |
| `scripts/setup-machine.ps1` | 每台机器一次性初始化脚本 |
| `Program/source/` | 项目源码（backend / frontend / tests） |
| `References/` | 需求文档 |

## 给开发者的快速开始

```powershell
cd Program\source
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe launcher.py        # 本地单机：自动打开浏览器
```

**桌面客户端**（M9）：

```powershell
cd Program\source\frontend; npm ci; npm run build   # 先出前端产物
cd ..\desktop; npm install; npm start               # 自动拉起后端 + 客户端窗口
```

**联网服务端**（多用户远程访问，详见 `03-技术架构.md` §7）：

```powershell
# 服务器上（示例端口 8000）
$env:FLOWDESK_ALLOWED_HOSTS="*"
.\.venv\Scripts\python.exe launcher.py --host 0.0.0.0 --port 8000
# 客户端机器上：FLOWDESK_BACKEND_URL 指向服务器即联网协作
$env:FLOWDESK_BACKEND_URL="http://<服务器IP>:8000"; npm start
```

测试：`.\.venv\Scripts\python.exe -m pytest tests/ -q`；前端构建：`cd frontend; npm ci; npm run build`。

## 客户端打包（正式分发）

产物：`Program\source\desktop\release\FlowDesk-0.1.0-win.zip`（解压即用，**内嵌后端 exe**，目标电脑无需装 Python/Node）。

```powershell
# 1) 后端打成独立 exe（PyInstaller onedir → Program\source\dist\flowdesk-backend\）
cd Program\source
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --name flowdesk-backend `
  --add-data "frontend/dist;frontend/dist" --collect-submodules uvicorn --collect-submodules sqlalchemy `
  --hidden-import multipart launcher.py

# 2) 客户端打包（内嵌后端 + 自动连接/降级逻辑）
cd desktop
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"   # 国内镜像（可选）
npx electron-builder --win zip        # 便携 zip（推荐分发）
npx electron-builder --win portable   # 自解压单 exe（已知问题：内嵌后端未拉起，暂用 zip）
npx electron-builder --win nsis       # 安装版
```

**客户端启动决策**（`desktop/main.js`）：先探测 `FLOWDESK_SERVER_URL`（默认 `http://192.168.1.23:8000`，打包前在 main.js 改为你的固定 IP）→ 连上 = 联网协作；连不上 = 自动降级本机模式（内嵌后端）。

## 固定 IP（服务端常驻前提）

1. 浏览器进入路由器后台（常见 `192.168.x.1`）→ 登录
2. 找到「DHCP 服务器 / 静态地址分配 / 地址保留」
3. 添加一条：服务端电脑的 **MAC 地址** → 分配固定 IP（如 `192.168.223.100`）
4. 保存后重启该电脑网络；`ipconfig` 确认 IP 不再变化
5. 把该 IP 填进 `desktop/main.js` 的 `DEFAULT_SERVER_URL` 后重新打包，其他电脑双击即自动连上
