import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const checks = [
  ['Node 版本 >= 18', Number.parseInt(process.versions.node, 10) >= 18, process.versions.node],
  ['vite 可执行文件', existsSync(join(root, 'node_modules', 'vite', 'bin', 'vite.js'))],
  ['@vitejs/plugin-react', existsSync(join(root, 'node_modules', '@vitejs/plugin-react'))],
  ['index.html', existsSync(join(root, 'index.html'))],
  ['src/main.tsx', existsSync(join(root, 'src/main.tsx'))],
];

console.log('=== 前端环境自检 ===');
console.log('目录:', root);
let ok = true;
for (const [name, pass, extra] of checks) {
  const mark = pass ? 'OK' : 'FAIL';
  console.log(`  [${mark}] ${name}${extra !== undefined && extra !== true ? ` (${extra})` : ''}`);
  if (!pass) ok = false;
}
if (!ok) {
  console.log('\n请先执行: cd frontend && npm install');
  process.exit(1);
}
console.log('\n全部通过。请运行: npm run dev');
process.exit(0);
