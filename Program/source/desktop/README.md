# FlowDesk 桌面客户端（Electron 壳，M9）

机器 A 维护。职责：把现有 Vue 3 前端封装为桌面客户端。**只换壳，不改接口**——业务规则与权限判断全部在服务端完成。

## 目录

| 文件 | 作用 |
| --- | --- |
| `main.js` | Electron 主进程：管理后端进程、创建窗口、按模式加载前端 |
| `preload.js` | 预加载脚本：最小权限暴露只读信息（版本、平台） |
| `package.json` | Electron 依赖与启动脚本 |

## 三种加载模式（main.js，按优先级）

| 模式 | 触发 | 行为 |
| --- | --- | --- |
| 联网客户端 | `FLOWDESK_SERVER_URL`（兼容旧名 `FLOWDESK_BACKEND_URL`，如 `https://flowdesk.example.com`） | 直接连接外部服务端，不拉起本地后端；多用户各客户端指向同一服务端 = 在线协作 |
| 前端开发 | `VITE_DEV_SERVER_URL=http://localhost:5173` | 连 Vite dev server（后端自行启动） |
| 本地一体（默认） | 无以上变量 | 自动拉起 `launcher.py --headless`，轮询 `/api/health` 就绪后加载 `http://127.0.0.1:<port>/`；退出时自动结束后端 |

> 打包版启动决策链还包含局域网 UDP 自动发现与记忆地址兜底，详见仓库根 `README.md`。

## 本地运行

先构建前端（dist 是客户端的界面源）：

```powershell
cd ..\frontend
npm ci
npm run build
```

再启动客户端（本地一体模式，自动拉起后端，无需手动开服务）：

```powershell
cd ..\desktop
npm install
npm start
```

**macOS / Linux** 等价命令：

```bash
cd ../frontend && npm ci && npm run build
cd ../desktop && npm install && npm start
```

> 本地一体模式在开发期通过项目 `.venv` 或系统 `python` 拉起后端，请先按 `../README.md` 准备好 Python 环境（`pip install -r ../requirements.txt`）。

开发模式（改前端代码实时生效，需另开终端跑 `cd ..\frontend && npm run dev`）：

```powershell
cd ..\desktop
$env:VITE_DEV_SERVER_URL = "http://localhost:5173"
npm start
```

## 联网（服务端化）

服务器部署 `launcher.py --host 0.0.0.0`（详见仓库根 `03-技术架构.md` §7）；客户端机器指向服务端：

```powershell
cd ..\desktop
$env:FLOWDESK_SERVER_URL = "http://<服务器IP>:8000"
npm start
```

> 环境变量亦可写死在系统环境变量中，或后续接入设置界面。

## 打包分发（正式安装包）

推荐走 CI：推送 `v*` 标签后 GitHub Actions（`.github/workflows/release.yml`）自动构建并发布到 Releases：

- **Windows**：NSIS 安装包（`FlowDesk-<版本>-setup.exe`）+ 便携 zip
- **macOS**：dmg，Apple Silicon（arm64）与 Intel（x64）各一份

本地手动打包：先按仓库根 `README.md`「客户端打包」用 PyInstaller 产出 `dist/flowdesk-backend/`，再在本目录执行 `npx electron-builder --win nsis`（Windows）或 `npx electron-builder --mac dmg`（macOS）。

> macOS 产物未做 Developer ID 签名与公证，首次打开需右键 →「打开」，或在「系统设置 → 隐私与安全性」中允许。

## 后续路线

- [x] electron-builder 打包（Windows 安装包/便携版、macOS dmg）
- [ ] 自动更新
- [ ] 服务端地址配置界面（联网版指向云端服务端）
- [ ] macOS Developer ID 签名与公证
- [x] 打包时内嵌 Python 运行时（PyInstaller 后端，免安装 Python）
