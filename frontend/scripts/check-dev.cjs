const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const logFile = path.join(root, 'dev-start.log');

function out(msg) {
  const line = String(msg);
  process.stdout.write(line + '\n');
  try {
    fs.appendFileSync(logFile, line + '\n', 'utf8');
  } catch (_) {}
}

out('=== 前端环境自检 (check-dev.cjs) ===');
out('Node 路径: ' + process.execPath);
out('Node 版本: ' + process.version);
out('工作目录: ' + process.cwd());
out('脚本目录: ' + root);

const viteBin = path.join(root, 'node_modules', 'vite', 'bin', 'vite.js');
const rollupNative = path.join(
  root,
  'node_modules',
  '@rollup',
  'rollup-win32-x64-msvc',
  'rollup.win32-x64-msvc.node',
);

const checks = [
  ['Node 版本 >= 18', parseInt(process.versions.node, 10) >= 18],
  ['vite 文件', fs.existsSync(viteBin)],
  ['rollup 原生模块 (Windows)', fs.existsSync(rollupNative)],
  ['@vitejs/plugin-react', fs.existsSync(path.join(root, 'node_modules', '@vitejs/plugin-react'))],
  ['index.html', fs.existsSync(path.join(root, 'index.html'))],
  ['src/main.tsx', fs.existsSync(path.join(root, 'src/main.tsx'))],
];

let ok = true;

try {
  require('rollup');
  out('  [OK] require("rollup")');
} catch (e) {
  out('  [FAIL] require("rollup"): ' + e.message);
  ok = false;
}

const { execFileSync } = require('child_process');
try {
  const ver = execFileSync(process.execPath, [viteBin, '--version'], {
    cwd: root,
    encoding: 'utf8',
    timeout: 15000,
  }).trim();
  out('  [OK] vite --version → ' + ver);
} catch (e) {
  out('  [FAIL] vite --version（Node 可能崩溃）: ' + (e.message || e));
  out('  → 请执行: powershell -File fix-deps.ps1');
  ok = false;
}

for (const [name, pass] of checks) {
  out('  [' + (pass ? 'OK' : 'FAIL') + '] ' + name);
  if (!pass) ok = false;
}
if (!fs.existsSync(rollupNative)) {
  out('  [提示] 缺少 rollup 原生包，在 frontend 执行: npm install 或 .\\fix-deps.ps1');
}

if (!ok) {
  out('\n请先执行: npm install');
  out('详细日志: ' + logFile);
  process.exit(1);
}
out('\n全部通过。下一步: npm run dev  或  powershell -File start-dev.ps1');
out('日志文件: ' + logFile);
process.exit(0);
