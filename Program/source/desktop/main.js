// FlowDesk Electron 主进程（M9，机器 A 维护）
// 职责：创建客户端窗口，加载前端界面。
// - 生产模式：加载 frontend/dist/index.html（先执行 npm run build）
// - 开发模式：设置环境变量 VITE_DEV_SERVER_URL=http://localhost:5173 后启动（连 Vite dev server）
// 注意：业务逻辑与权限判断全部在服务端，本文件只做窗口与加载。
const {app, BrowserWindow} = require('electron');
const path = require('path');

function createWindow() {
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

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    win.loadURL(devUrl);
  } else {
    win.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'));
  }
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
