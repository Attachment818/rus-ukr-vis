/**
 * Windows-friendly Vite launcher with clear errors (fixes silent npm run dev exit).
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const viteBin = join(root, 'node_modules', 'vite', 'bin', 'vite.js');

function fail(msg) {
  console.error('\n[前端启动失败]', msg);
  console.error('\n建议：');
  console.error('  1) cd frontend');
  console.error('  2) npm install');
  console.error('  3) node -v   （需要 Node 18+，推荐 20/22）');
  console.error('  4) npm run dev:check');
  console.error('  5) 或双击 frontend\\start-dev.cmd\n');
  process.exit(1);
}

const major = Number.parseInt(process.versions.node.split('.')[0] ?? '0', 10);
if (major < 18) {
  fail(`当前 Node ${process.versions.node} 过旧，Vite 5 需要 Node 18+。请升级 Node 或在 conda 外使用系统 Node。`);
}

if (!existsSync(viteBin)) {
  fail(`未找到 ${viteBin}，请先在 frontend 目录执行 npm install。`);
}

console.log(`[dev] Node ${process.versions.node}`);
console.log(`[dev] 工作目录 ${root}`);
console.log('[dev] 启动 Vite（按 Ctrl+C 停止）...\n');

const args = [viteBin, '--host', '127.0.0.1', ...process.argv.slice(2)];
const child = spawn(process.execPath, args, {
  cwd: root,
  stdio: 'inherit',
  env: process.env,
  windowsHide: false,
});

child.on('error', (err) => {
  console.error('[dev] 无法启动子进程:', err);
  process.exit(1);
});

child.on('exit', (code, signal) => {
  if (signal) {
    console.error(`[dev] Vite 被信号终止: ${signal}`);
    process.exit(1);
  }
  if (code && code !== 0) {
    console.error(`[dev] Vite 退出码 ${code}（若端口占用，可先 netstat -ano | findstr :5173 并结束对应 PID）`);
    process.exit(code);
  }
});
