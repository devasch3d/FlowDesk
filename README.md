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
- **路线图**：M4 Task → M5 Files → M6 Dashboard/Search → M7 Collaboration → M8 AI Copilot → **M9 Electron 客户端封装**。

> 架构基线：`03-技术架构.md`（客户端/服务端分层、技术栈、API 契约原则，A 维护）。
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
.\.venv\Scripts\python.exe launcher.py
```

测试：`.\.venv\Scripts\python.exe -m pytest tests/ -q`；前端构建：`cd frontend; npm ci; npm run build`。
