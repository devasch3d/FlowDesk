// FlowDesk Electron 主进程（M9，机器 A 维护）
// 职责：管理后端进程并创建客户端窗口。
//
// 三种加载模式（按优先级）：
// 1. FLOWDESK_BACKEND_URL=...    联网客户端：直接连接外部服务端（远程/云部署），不拉起本地后端
// 2. VITE_DEV_SERVER_URL=...     前端开发模式：连接 Vite dev server（后端请自行启动）
// 3. 默认                        本地一体模式：自动拉起 launcher.py（headless），等待就绪后加载
//
// 安全原则：业务逻辑与权限判断全部在服务端；本文件只做进程管理与窗口加载。
const {app, BrowserWindow, dialog} = require('electron');
const {spawn} = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const SOURCE_DIR = path.join(__dirname, '..');          // Program/source
const LAUNCHER = path.join(SOURCE_DIR, 'launcher.py');
// 优先使用项目 venv 的 Python（依赖齐全）；未创建 venv 时退回 PATH 中的 python；可用 FLOWDESK_PYTHON 覆盖
const VENV_PYTHON = path.join(SOURCE_DIR, '.venv', 'Scripts', 'python.exe');
const PYTHON = process.env.FLOWDESK_PYTHON || (fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python');

let backend = null;
let quitting = false;

// 轮询后端 /api/health 直至就绪或超时
function waitForHealth(port, timeoutMs = 30000, intervalMs = 300) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      const req = http.get({host: '127.0.0.1', port, path: '/api/health', timeout: 2000}, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolve();
        retry();
      });
      req.on('error', retry);
      req.on('timeout', () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() > deadline) return reject(new Error(`后端服务在 ${timeoutMs / 1000}s 内未就绪，请查看 data/flowdesk.log`));
      setTimeout(tryOnce, intervalMs);
    };
    tryOnce();
  });
}

function startBackend(port) {
  backend = spawn(PYTHON, [LAUNCHER, '--headless', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: SOURCE_DIR,
    windowsHide: true,
    stdio: 'ignore',
  });
  backend.on('exit', (code) => {
    if (!quitting && code !== 0) {
      dialog.showErrorBox('FlowDesk 后端已退出', `后端进程异常退出（code=${code}）。\n请查看 data/flowdesk.log 或重新打开应用。`);
    }
  });
}

function createWindow(url) {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    title: 'FlowDesk',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  win.loadURL(url);
  win.on('closed', () => {});
  return win;
}

app.whenReady().then(async () => {
  let activeUrl;
  const remoteUrl = process.env.FLOWDESK_BACKEND_URL;
  if (remoteUrl) {
    // 联网客户端模式：连接外部服务端（多用户在线协作时，各成员客户端均指向同一服务端）
    activeUrl = remoteUrl;
    createWindow(activeUrl);
  } else {
    const devUrl = process.env.VITE_DEV_SERVER_URL;
    if (devUrl) {
      activeUrl = devUrl;
      createWindow(activeUrl);
    } else {
      // 本地一体模式：自动拉起后端
      const port = process.env.FLOWDESK_PORT
        ? Number(process.env.FLOWDESK_PORT)
        : 8756 + Math.floor(Math.random() * 500);
      startBackend(port);
      try {
        await waitForHealth(port);
      } catch (err) {
        dialog.showErrorBox('FlowDesk 启动失败', err.message);
        app.quit();
        return;
      }
      activeUrl = `http://127.0.0.1:${port}/`;
      createWindow(activeUrl);
    }
  }
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow(activeUrl);
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => {
  quitting = true;
  if (backend) {
    backend.kill();
    backend = null;
  }
});
