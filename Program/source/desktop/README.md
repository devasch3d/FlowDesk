# FlowDesk 桌面客户端（Electron 壳，M9）

机器 A 维护。职责：把现有 Vue 3 前端封装为桌面客户端。**只换壳，不改接口**——业务规则与权限判断全部在服务端完成。

## 目录

| 文件 | 作用 |
| --- | --- |
| `main.js` | Electron 主进程：创建窗口、加载前端（生产加载 dist，开发加载 Vite dev server） |
| `preload.js` | 预加载脚本：最小权限暴露只读信息（版本、平台） |
| `package.json` | Electron 依赖与启动脚本 |

## 本地运行

先构建前端（dist 是客户端的界面源）：

```powershell
cd ..\frontend
npm ci
npm run build
```

再启动客户端（需要先启动后端服务，前端 API 指向 `http://127.0.0.1:8000`）：

```powershell
cd ..\desktop
npm install
npm start
```

开发模式（改前端代码实时生效，需另开终端跑 `cd ..\frontend && npm run dev`）：

```powershell
cd ..\desktop
$env:VITE_DEV_SERVER_URL = "http://localhost:5173"
npm start
```

## 后续路线（M9 完整落地时补充）

- [ ] electron-builder 打包（Windows 安装包/便携版）
- [ ] 自动更新
- [ ] 服务端地址配置界面（联网版指向云端服务端）
- [ ] 与 launcher.py 的整合（或独立服务端部署）
