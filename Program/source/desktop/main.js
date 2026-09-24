// FlowDesk Electron 主进程（M9，机器 A 维护）
// 职责：管理后端进程并创建客户端窗口。
//
// 启动决策链（按优先级）：
// 1. VITE_DEV_SERVER_URL    前端开发模式（后端自行启动）
// 2. 联网优先：探测 FLOWDESK_SERVER_URL（缺省 DEFAULT_SERVER_URL）
//    - 连上 → 联网协作模式（加载远程服务端）
//    - 连不上 → 自动降级本地一体模式（拉起本机后端，标题标注"本地模式"）
// 3. 兜底                    本地一体模式（同 2 的降级路径）
//
// 安全原则：业务逻辑与权限判断全部在服务端；本文件只做进程管理与窗口加载。
const {app, BrowserWindow, dialog} = require('electron');
const {spawn} = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const SOURCE_DIR = path.join(__dirname, '..');          // 开发期：Program/source
const LAUNCHER = path.join(SOURCE_DIR, 'launcher.py');
// 开发期优先项目 venv 的 Python；打包后优先内嵌的后端 exe（见 resolveBackend()）
const VENV_PYTHON = path.join(SOURCE_DIR, '.venv', 'Scripts', 'python.exe');

// 默认服务端地址：固定 IP 后改为 http://192.168.x.x:8000（打包前改这里）
// 运行时可用环境变量 FLOWDESK_SERVER_URL 覆盖（便于多套部署不改代码）
const DEFAULT_SERVER_URL = 'http://192.168.1.23:8000';
const SERVER_URL = process.env.FLOWDESK_SERVER_URL || DEFAULT_SERVER_URL;

let backend = null;
let quitting = false;

// 探测服务端是否可达（3 秒超时）
function probeServer(url, timeoutMs = 3000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (ok) => { if (!done) { done = true; resolve(ok); } };
    try {
      const u = new URL(url);
      const req = http.get({host: u.hostname, port: u.port || (u.protocol === 'https:' ? 443 : 80), path: '/api/health', timeout: timeoutMs}, (res) => {
        res.resume();
        finish(res.statusCode === 200);
      });
      req.on('error', () => finish(false));
      req.on('timeout', () => { req.destroy(); finish(false); });
      setTimeout(() => finish(false), timeoutMs + 200);
    } catch (e) { finish(false); }
  });
}

// 轮询本机后端 /api/health 直至就绪或超时
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

// 解析后端启动命令：打包环境（resources/backend/*.exe）→ 开发 venv python → PATH python
function resolveBackend() {
  if (process.resourcesPath) {
    const exe = path.join(process.resourcesPath, 'backend', 'flowdesk-backend.exe');
    if (fs.existsSync(exe)) return {cmd: exe, args: ['--headless', '--host', '127.0.0.1', '--port']};
  }
  if (fs.existsSync(VENV_PYTHON)) {
    return {cmd: VENV_PYTHON, args: [LAUNCHER, '--headless', '--host', '127.0.0.1', '--port']};
  }
  return {cmd: 'python', args: [LAUNCHER, '--headless', '--host', '127.0.0.1', '--port']};
}

function startBackend(port) {
  const {cmd, args} = resolveBackend();
  backend = spawn(cmd, [...args, String(port)], {
    cwd: SOURCE_DIR,
    windowsHide: true,
    stdio: 'ignore',
  });
  backend.on('exit', (code) => {
    if (!quitting && code !== 0) {
      dialog.showErrorBox('FlowDesk 后端已退出', `后端进程异常退出（code=${code}）。\n请查看 data/flowdesk.log 或重新打开应用。`);
    }
  });
  return backend;
}

function createWindow(url, localFallback = false) {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    title: localFallback ? 'FlowDesk（本地模式）' : 'FlowDesk',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  win.loadURL(url);
  return win;
}

app.whenReady().then(async () => {
  let activeUrl;
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    activeUrl = devUrl;
    createWindow(activeUrl);
  } else {
    // 联网优先：探测服务端
    const online = await probeServer(SERVER_URL);
    if (online) {
      activeUrl = SERVER_URL;
      createWindow(activeUrl);
    } else {
      // 降级：本地一体模式
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
      createWindow(activeUrl, true);
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
