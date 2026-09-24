// FlowDesk Electron 主进程（M9，机器 A 维护）
// 职责：管理后端进程并创建客户端窗口。
//
// 启动决策链（按优先级）：
// 1. VITE_DEV_SERVER_URL       前端开发模式（后端自行启动）
// 2. FLOWDESK_SERVER_URL       显式服务端地址（打包写死/环境变量）
// 3. 局域网自动发现            UDP 广播（服务端 launcher.py 周期广播 FlowDesk:<port>）
// 4. 记忆地址                  上次连接成功的服务端（userData/flowdesk-server.json）
// 5. 本地一体模式（兜底）       拉起内嵌后端，标题标注"本地模式"
//
// 安全原则：业务逻辑与权限判断全部在服务端；本文件只做进程管理与窗口加载。
const {app, BrowserWindow, dialog} = require('electron');
const {spawn} = require('child_process');
const dgram = require('dgram');
const fs = require('fs');
const path = require('path');
const http = require('http');

const SOURCE_DIR = path.join(__dirname, '..');          // 开发期：Program/source
const LAUNCHER = path.join(SOURCE_DIR, 'launcher.py');
// 开发期优先项目 venv 的 Python；打包后优先内嵌的后端 exe（见 resolveBackend()）
const VENV_PYTHON = path.join(SOURCE_DIR, '.venv', 'Scripts', 'python.exe');

// 与服务端 launcher.py 一致的 UDP 发现端口
const DISCOVERY_PORT = 45678;
// 记忆文件：上次成功连接的服务端地址（IP 变化环境下客户端仍能自动重连）
const MEMORY_FILE = () => path.join(app.getPath('userData'), 'flowdesk-server.json');

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

// 局域网自动发现：监听 UDP 广播 "FlowDesk:<port>"，返回服务端地址（自动携带当前 IP）
function discoverServer(timeoutMs = 2500) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (url) => { if (!done) { done = true; try { sock.close(); } catch (e) {} resolve(url); } };
    let sock;
    try { sock = dgram.createSocket('udp4'); } catch (e) { return finish(null); }
    sock.on('message', (msg, rinfo) => {
      const text = msg.toString();
      if (text.startsWith('FlowDesk:')) {
        const port = Number(text.slice('FlowDesk:'.length));
        if (port) finish(`http://${rinfo.address}:${port}/`);
      }
    });
    sock.on('error', () => finish(null));
    try { sock.bind(DISCOVERY_PORT, () => { try { sock.setBroadcast(true); } catch (e) {} }); } catch (e) { return finish(null); }
    setTimeout(() => finish(null), timeoutMs);
  });
}

// 记忆地址读写（IP 会变的环境：记住上次成功的服务器，重启后先试它）
function rememberServer(url) {
  try { fs.writeFileSync(MEMORY_FILE(), JSON.stringify({url})); } catch (e) {}
}
function rememberedServer() {
  try { return JSON.parse(fs.readFileSync(MEMORY_FILE(), 'utf8')).url || null; } catch (e) { return null; }
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
    console.log('[FlowDesk] embedded backend NOT found at ' + exe);
  }
  if (fs.existsSync(VENV_PYTHON)) {
    return {cmd: VENV_PYTHON, args: [LAUNCHER, '--headless', '--host', '127.0.0.1', '--port']};
  }
  return {cmd: 'python', args: [LAUNCHER, '--headless', '--host', '127.0.0.1', '--port']};
}

function startBackend(port) {
  const {cmd, args} = resolveBackend();
  console.log('[FlowDesk] startBackend port=' + port + ' cmd=' + cmd);
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
  console.log('[FlowDesk] resourcesPath=' + (process.resourcesPath || 'N/A'));
  console.log('[FlowDesk] __dirname=' + __dirname);
  let activeUrl;
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    activeUrl = devUrl;
    createWindow(activeUrl);
  } else {
    // 1) 显式配置的服务端地址（打包写死 / 环境变量）
    const explicit = process.env.FLOWDESK_SERVER_URL;
    let connected = explicit ? await probeServer(explicit) : false;
    if (connected) activeUrl = explicit;

    // 2) 局域网自动发现（免配置：服务端 IP 变化也能跟上）
    if (!connected) {
      const found = await discoverServer(2500);
      if (found) {
        connected = await probeServer(found);
        if (connected) activeUrl = found;
      }
    }

    // 3) 记忆地址（上次成功连接的服务器）
    if (!connected) {
      const mem = rememberedServer();
      if (mem) {
        connected = await probeServer(mem);
        if (connected) activeUrl = mem;
      }
    }

    if (connected) {
      rememberServer(activeUrl);
      createWindow(activeUrl);
    } else {
      // 4) 兜底：本地一体模式
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
