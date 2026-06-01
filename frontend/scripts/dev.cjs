const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const root = path.join(__dirname, '..');
const logFile = path.join(root, 'dev-start.log');
const viteBin = path.join(root, 'node_modules', 'vite', 'bin', 'vite.js');

function out(msg) {
  const line = String(msg);
  process.stdout.write(line + '\n');
  try {
    fs.appendFileSync(logFile, line + '\n', 'utf8');
  } catch (_) {}
}

function fail(msg) {
  out('\n[前端启动失败] ' + msg);
  out('请打开日志: ' + logFile);
  out('或运行: powershell -ExecutionPolicy Bypass -File start-dev.ps1');
  process.exit(1);
}

try {
  fs.writeFileSync(logFile, '--- dev start ' + new Date().toISOString() + ' ---\n', 'utf8');
} catch (_) {}

out('[dev] Node: ' + process.version);
out('[dev] 可执行文件: ' + process.execPath);
out('[dev] 目录: ' + root);

if (parseInt(process.versions.node, 10) < 18) {
  fail('Node 版本过旧，需要 18+');
}
if (!fs.existsSync(viteBin)) {
  fail('未找到 vite，请执行 npm install');
}

out('[dev] 正在启动 Vite http://127.0.0.1:5173/ （Ctrl+C 停止）');

const child = spawn(process.execPath, [viteBin, '--host', '127.0.0.1', '--port', '5173'], {
  cwd: root,
  stdio: 'inherit',
  env: process.env,
  windowsHide: false,
});

child.on('error', (err) => {
  fail('spawn 失败: ' + err.message);
});

child.on('exit', (code, signal) => {
  if (signal) {
    fail('进程被终止: ' + signal);
  }
  if (code && code !== 0) {
    fail('Vite 退出码 ' + code + '（端口占用可先: netstat -ano | findstr :5173）');
  }
});
