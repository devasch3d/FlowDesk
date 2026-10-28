// CI 上没有 Developer ID 证书时，electron-builder 会跳过签名，
// 产出的 .app 保留 Electron 出厂的 linker-signed 签名但包内容已改变 → 签名封印失效，
// Apple Silicon 上表现为“已损坏，无法打开”。此钩子在打 dmg 前对 .app 做 ad-hoc 重签名。
//
// 注意不能用 `codesign --force --deep`：它会剥掉 Electron 主程序与 Helper 的
// entitlements（JIT/内存执行相关），V8 启动即崩溃。必须按“先内层后外层”的顺序
// 逐个签名，并为各组件附上 Electron 官方发行版自带的 entitlements。
// 正式分发仍需 Developer ID 签名 + 公证。
const {execFileSync} = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ENT_MAIN = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>com.apple.security.cs.allow-jit</key><true/>
<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
<key>com.apple.security.cs.allow-dyld-environment-variables</key><true/>
<key>com.apple.security.cs.disable-library-validation</key><true/>
</dict></plist>`;

// Helper 必须只带 inherit 一项：Apple 规定 com.apple.security.inherit 不能与其他
// entitlement 组合，否则 AMFI 直接击杀进程（Renderer 的 JIT 权限由继承主程序获得）。
const ENT_HELPER = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>com.apple.security.inherit</key><true/>
</dict></plist>`;

function sign(target, entitlementsFile) {
  const args = ['--force', '--sign', '-', '--timestamp=none'];
  if (entitlementsFile) args.push('--entitlements', entitlementsFile);
  args.push(target);
  execFileSync('codesign', args, {stdio: 'inherit'});
}

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const appName = `${context.packager.appInfo.productFilename}.app`;
  const appPath = path.join(context.appOutDir, appName);
  if (!fs.existsSync(appPath)) return;

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fd-ent-'));
  const entMain = path.join(tmp, 'main.plist');
  const entHelper = path.join(tmp, 'helper.plist');
  fs.writeFileSync(entMain, ENT_MAIN);
  fs.writeFileSync(entHelper, ENT_HELPER);

  console.log('[afterPack] ad-hoc signing ' + appPath);
  const frameworks = path.join(appPath, 'Contents', 'Frameworks');

  // 1) Frameworks 内的 framework（Electron Framework 按官方惯例带主程序 entitlements）
  //    注意：x64 版 Electron 发行包内的 chrome_crashpad_handler 等嵌套 helper 完全未签名
  //    （x64 不强制签名），而 arm64 版自带签名——因此重签主二进制前必须先签最内层
  //    的 Helpers/Libraries，否则 codesign 校验子组件时报 "code object is not signed at all"。
  for (const name of fs.readdirSync(frameworks)) {
    const full = path.join(frameworks, name);
    if (name.endsWith('.framework')) {
      const inner = path.join(full, 'Versions', 'A');
      // 1a) framework 内嵌的独立可执行文件与动态库（先内层）
      for (const sub of ['Helpers', 'Libraries']) {
        const subDir = path.join(inner, sub);
        if (!fs.existsSync(subDir)) continue;
        for (const f of fs.readdirSync(subDir)) {
          const fPath = path.join(subDir, f);
          if (fs.statSync(fPath).isFile()) sign(fPath, entMain);
        }
      }
      // 1b) framework 主二进制（后外层）
      const bin = path.join(full, name.replace(/\.framework$/, ''));
      if (fs.existsSync(bin)) sign(bin, name === 'Electron Framework.framework' ? entMain : null);
    }
  }

  // 2) Helper 应用（Renderer 需要 JIT，全部按 helper entitlements 签）
  for (const name of fs.readdirSync(frameworks)) {
    if (!name.endsWith('.app')) continue;
    const helperBin = path.join(frameworks, name, 'Contents', 'MacOS', name.replace(/\.app$/, ''));
    if (fs.existsSync(helperBin)) sign(helperBin, entHelper);
    sign(path.join(frameworks, name), entHelper);
  }

  // 3) 内嵌后端（PyInstaller 已 ad-hoc 签过，重签保证封印一致）
  const backendDir = path.join(appPath, 'Contents', 'Resources', 'backend');
  const backendBin = path.join(backendDir, 'flowdesk-backend');
  if (fs.existsSync(backendBin)) sign(backendBin);

  // 4) 主程序与外层 bundle
  sign(path.join(appPath, 'Contents', 'MacOS', context.packager.appInfo.productFilename), entMain);
  sign(appPath, entMain);

  execFileSync('codesign', ['--verify', '--deep', '--strict', appPath], {stdio: 'inherit'});
  console.log('[afterPack] signature OK');
};
