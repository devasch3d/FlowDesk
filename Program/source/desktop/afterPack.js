// CI 上没有 Developer ID 证书时，electron-builder 会跳过签名，
// 产出的 .app 保留 Electron 出厂的 linker-signed 签名但包内容已改变 → 签名封印失效，
// Apple Silicon 上表现为“已损坏，无法打开”。此钩子在打 dmg 前对 .app 做 ad-hoc 重签名，
// 使应用至少可以通过“右键 → 打开”启动。正式分发仍需 Developer ID 签名 + 公证。
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  if (!fs.existsSync(appPath)) return;
  console.log('[afterPack] ad-hoc signing ' + appPath);
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', appPath], {stdio: 'inherit'});
  execFileSync('codesign', ['--verify', '--deep', '--strict', appPath], {stdio: 'inherit'});
  console.log('[afterPack] signature OK');
};
