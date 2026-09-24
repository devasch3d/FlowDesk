// FlowDesk preload 脚本：以最小权限向页面暴露只读信息。
// 安全默认：contextIsolation=true、nodeIntegration=false。
const {contextBridge} = require('electron');

contextBridge.exposeInMainWorld('flowdesk', {
  version: '0.1.0',
  platform: process.platform,
});
