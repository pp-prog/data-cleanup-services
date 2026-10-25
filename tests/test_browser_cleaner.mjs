// Node 下跑浏览器端清洗器的自检（与 Python 版 16 项自检对标）
// 用法：node tests/test_browser_cleaner.mjs
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const BC = require('../browser-cleaner.js');

const checks = BC.selfTest();
let pass = 0;
for (const c of checks) {
  console.log((c.ok ? 'PASS' : 'FAIL') + ' | ' + c.name + (c.detail ? ' | ' + c.detail : ''));
  if (c.ok) pass++;
}
console.log(`\n${pass}/${checks.length} 项通过`);
process.exit(pass === checks.length ? 0 : 1);
