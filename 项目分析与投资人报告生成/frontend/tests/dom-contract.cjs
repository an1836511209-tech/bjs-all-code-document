#!/usr/bin/env node
/**
 * DOM id 契约守卫（纯文本，无需浏览器，可进 CI）。
 *
 * 断言：
 *   1. console.js 里所有 $('#x') 引用的 id 都存在于 index.html
 *   2. 关键交互元素都进了 el 映射表（el 表是唯一来源）
 *   3. 反向：el 表里的每个 id 也在 index.html 里（防止拼错）
 *
 * 用法：node frontend/tests/dom-contract.cjs
 */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const moduleDir = path.join(ROOT, 'assets/modules');
const moduleFiles = fs.readdirSync(moduleDir).filter((name) => name.endsWith('.js')).sort();
const js = moduleFiles
  .map((name) => fs.readFileSync(path.join(moduleDir, name), 'utf8'))
  .join('\n');

const htmlIds = new Set([...html.matchAll(/id="([\w-]+)"/g)].map((m) => m[1]));

// el 映射表：从 `const el = {` 到第一个 `};`
const elStart = js.indexOf('const el = {');
assert.ok(elStart >= 0, 'console.js 里找不到 el 映射表');
const elEnd = js.indexOf('};', elStart);
const elBlock = js.slice(elStart, elEnd);
const elKeys = new Set([...elBlock.matchAll(/(\w+):\s*\$\('#([\w-]+)'\)/g)].map((m) => m[2]));

// console.js 里所有直接查询的 id
const queriedIds = new Set([...js.matchAll(/\$\('#([\w-]+)'\)/g)].map((m) => m[1]));

const problems = [];

for (const id of queriedIds) {
  if (!htmlIds.has(id)) problems.push(`console.js 查询了 #${id}，但 index.html 里没有`);
}

// 关键交互元素必须在 el 表里 —— 否则会退化成「各处随手 $('#x')」
const MUST_BE_IN_EL = [
  'input', 'sendBtn', 'skillSelect', 'messages', 'thread',
  'taskPanel', 'taskHead', 'taskBody', 'taskProgress',
  'convos', 'convosToggle', 'scrim',
  'preview', 'paper', 'previewToggle', 'convoFilesBody',
];
for (const id of MUST_BE_IN_EL) {
  if (!elKeys.has(id)) problems.push(`el 映射表缺少 #${id}`);
}

for (const id of elKeys) {
  if (!htmlIds.has(id)) problems.push(`el 映射表引用了不存在的 #${id}`);
}

console.log(`index.html id: ${htmlIds.size}  el 表: ${elKeys.size}  console 直接查询: ${queriedIds.size}`);

if (problems.length) {
  console.error('\n❌ DOM 契约不满足：');
  for (const item of problems) console.error('  - ' + item);
  process.exit(1);
}
console.log('✅ DOM 契约通过');
