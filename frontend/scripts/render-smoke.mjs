/**
 * 渲染冒烟：在 jsdom 里真实执行打包产物，确认 React 挂载后确实产出内容。
 *
 * 存在的理由：只检查「HTML 返回 200 / 引用了 assets」是抓不到白屏的。
 * SPA 的外壳 HTML 无论应用是否崩溃都长一个样，只有真正跑一遍才知道。
 *
 * 用法：先 npm run build，再 node scripts/render-smoke.mjs
 */
import { JSDOM } from 'jsdom';
import { readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const DIST_ASSETS = join(process.cwd(), 'dist', 'assets');

if (!existsSync(DIST_ASSETS)) {
  console.error('找不到 dist/assets，请先执行 npm run build');
  process.exit(1);
}

const bundle = readdirSync(DIST_ASSETS).find((f) => f.endsWith('.js'));
if (!bundle) {
  console.error('dist/assets 下没有 JS 产物');
  process.exit(1);
}

const DOM_GLOBALS = [
  'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement', 'HTMLSelectElement',
  'Element', 'Node', 'Event', 'CustomEvent', 'MouseEvent', 'KeyboardEvent',
  'MutationObserver', 'requestAnimationFrame', 'cancelAnimationFrame',
  'getComputedStyle', 'matchMedia', 'location', 'history', 'localStorage',
  'sessionStorage', 'DOMParser', 'XMLHttpRequest', 'Text', 'SVGElement', 'Image',
  'HTMLAnchorElement', 'HTMLButtonElement', 'HTMLFormElement',
];

const USER = {
  id: 'u1',
  username: 'admin',
  displayName: '开发管理员',
  isAdmin: true,
};

// React 把渲染错误放到微任务里抛，try/catch 拦不到，会直接打断进程。
// 在进程级接住，才能报成一条 FAIL 而不是让后面的用例跑不起来。
let pending = [];
let renderSeq = 0;
// 画布颜色格式违规累计。应用层会 try/catch 兜住（装饰层不该能弄白屏），
// 但格式错误必须让冒烟失败，否则它会一直潜伏到真实浏览器里才爆。
let canvasViolations = [];
const collect = (error) => {
  pending.push(error instanceof Error ? error : new Error(String(error)));
};
process.on('uncaughtException', collect);
process.on('unhandledRejection', collect);

async function render(mode, preset, path = '/') {
  pending = [];
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
    url: 'http://localhost:8000' + path,
    pretendToBeVisual: true,
  });
  const { window } = dom;

  globalThis.window = window;
  globalThis.document = window.document;
  Object.defineProperty(globalThis, 'navigator', {
    value: window.navigator,
    configurable: true,
    writable: true,
  });
  for (const key of DOM_GLOBALS) {
    if (window[key] !== undefined) {
      try { globalThis[key] = window[key]; } catch {}
    }
  }

  // jsdom 不实现 matchMedia，补一个一律「不偏好深色」的桩
  if (typeof window.matchMedia !== 'function') {
    window.matchMedia = (query) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
    });
  }
  globalThis.matchMedia = window.matchMedia;

  // jsdom 没有 canvas 后端，取上下文会往 console 抛 "Not implemented"。
  // 但不能简单桩成 null——那样子画布代码路径根本不会被执行。
  // 曾经有一个 canvas 颜色格式错误（把 CSS 的空格 rgb(r g b / a) 喂给
  // addColorStop）把整个应用炸成白屏，而冒烟因为 getContext 返回 null 全绿。
  // 所以这里给一个假 2d 上下文，并让 addColorStop 严格按浏览器规矩校验：
  // 只认逗号形式 rgba(r, g, b, a)，空格形式记一次违规并抛 SyntaxError。
  const CANVAS_COLOR = /^rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(,\s*[\d.]+\s*)?\)$/;
  const fakeGradient = () => ({
    addColorStop(offset, color) {
      if (typeof color !== 'string' || !CANVAS_COLOR.test(color.trim())) {
        canvasViolations.push(`addColorStop(${JSON.stringify(color)})`);
        throw new SyntaxError(
          `Failed to execute 'addColorStop' on 'CanvasGradient': The value provided ('${color}') could not be parsed as a color.`
        );
      }
    },
  });
  const fakeCtx = () => ({
    canvas: null,
    globalAlpha: 1,
    setTransform() {},
    clearRect() {},
    fillRect() {},
    drawImage() {},
    createRadialGradient: fakeGradient,
    createLinearGradient: fakeGradient,
  });
  try {
    window.HTMLCanvasElement.prototype.getContext = () => fakeCtx();
  } catch {}

  if (preset) {
    try { window.localStorage.setItem('mojuan-theme', preset); } catch {}
  }

  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    });

  globalThis.fetch = async (url) => {
    const path = String(url);
    if (path.endsWith('/api/auth/me')) {
      return mode === 'logged-in' ? json({ user: USER }) : json({ detail: '未登录' }, 401);
    }
    if (path.endsWith('/api/banks')) return json({ banks: [] });
    if (path.endsWith('/api/exam-templates')) return json({ templates: [] });
    if (path.endsWith('/api/settings')) {
      return json({
        settings: { ai_api_key_configured: 'false', ai_base_url: '', ai_model: '' },
        isAdmin: true,
      });
    }
    if (path.includes('/api/history')) {
      return json({
        practice: [
          {
            id: 'h1',
            bankId: null,
            bankName: null,
            filters: {},
            order: 'random',
            total: 10,
            answered: 4,
            correct: 3,
            startedAt: '2026-10-19T09:00:00+00:00',
            finishedAt: '2026-10-19T09:06:00+00:00',
          },
        ],
        exams: [],
      });
    }
    return json({});
  };
  window.fetch = globalThis.fetch;

  const errors = [];
  const originalError = console.error;
  const originalWarn = console.warn;
  console.error = (...a) => errors.push('error: ' + a.map(String).join(' ').slice(0, 200));
  console.warn = (...a) => errors.push('warn: ' + a.map(String).join(' ').slice(0, 150));

  let crash = null;
  try {
    // 每次都要新的模块实例：同一 URL 的二次 import 会命中 ESM 缓存不再执行，
    // 所以 key 必须每次都不同，用递增序号而不是模式名。
    await import(
      'file:///' + join(DIST_ASSETS, bundle).replace(/\\/g, '/') + '?render=' + ++renderSeq
    );
  } catch (error) {
    crash = error;
  }
  await new Promise((resolve) => setTimeout(resolve, 500));
  if (!crash && pending.length) crash = pending[0];

  console.error = originalError;
  console.warn = originalWarn;

  const text = window.document
    .getElementById('root')
    .textContent.replace(/\s+/g, ' ')
    .trim();

  return {
    crash,
    errors,
    text,
    length: text.length,
    theme: window.document.documentElement.dataset.theme,
    hasDock: Boolean(window.document.querySelector('nav[aria-label="主导航"]')),
  };
}

// 每种模式只渲染一次：同一 URL 的二次 import 会命中 ESM 缓存不再执行，
// 拿到的是空 DOM，会让断言误判成白屏。
const anon = await render('anonymous');
const user = await render('logged-in');
const night = await render('logged-in', 'dark');
const day = await render('logged-in', 'light');
const importPage = await render('logged-in', null, '/import');
const practicePage = await render('logged-in', null, '/practice');
const examPage = await render('logged-in', null, '/exam');

const cases = [
  { label: '未登录', r: anon },
  { label: '已登录', r: user },
  { label: '已登录·夜间', r: night },
  { label: '已登录·日间', r: day },
  { label: '已登录·导入页', r: importPage },
  { label: '已登录·刷题页', r: practicePage },
  { label: '已登录·考试页', r: examPage },
];
const results = [];

for (const { label, r } of cases) {
  if (r.crash) {
    results.push({ label, ok: false, why: `渲染崩溃：${r.crash.name} ${r.crash.message}` });
  } else if (r.length < 10) {
    results.push({ label, ok: false, why: `渲染内容为空（${r.length} 字符），疑似白屏` });
  } else if (r.errors.length) {
    results.push({ label, ok: false, why: '控制台有输出：' + r.errors[0] });
  } else {
    results.push({ label, ok: true, why: `${r.length} 字符`, text: r.text.slice(0, 120) });
  }
}

const checks = [
  ['未登录渲染出登录表单', anon.text.includes('登录') && anon.text.includes('密码')],
  ['已登录渲染出底部 Dock 导航', user.hasDock && ['概览', '题库', '刷题', '考试', '设置'].every((n) => user.text.includes(n))],
  ['概览渲染出 Bento 瓦片', ['继续刷题', '模拟考试', '错题本', '开始使用'].every((n) => user.text.includes(n))],
  ['记录取全量并渲染出列表', user.text.includes('共 1 条') && user.text.includes('75%')],
  ['导入页渲染出三栏工作台', ['数据源', 'AI 对话', '提取结果'].every((n) => importPage.text.includes(n))],
  ['导入页渲染出审核确认位', importPage.text.includes('确认导入')],
  ['刷题页渲染出条件筛选', ['抽题条件', '全部题目', '随机刷题', '顺序刷题', '开始刷题'].every((n) => practicePage.text.includes(n))],
  ['考试页渲染出试卷位', examPage.text.includes('模拟考试') && examPage.text.includes('新建试卷')],
  ['未登录不出现导航与退出', !anon.text.includes('退出')],
  ['未预设时落到日间主题', user.theme === 'light'],
  ['预设夜间即生效', night.theme === 'dark'],
  ['预设日间即生效', day.theme === 'light'],
  ['两个主题下内容一致', night.length > 0 && Math.abs(night.length - day.length) < 8],
  ['画布颜色用逗号形式 rgba()', canvasViolations.length === 0],
];

console.log(`bundle: ${bundle}\n`);
for (const r of results) {
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.label}  ${r.why}`);
  if (r.text) console.log(`        ${r.text}`);
}
console.log('');
for (const [name, ok] of checks) {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`);
}

const failed = results.filter((r) => !r.ok).length + checks.filter(([, ok]) => !ok).length;
console.log(`\n通过 ${results.length + checks.length - failed} / 失败 ${failed}`);
process.exit(failed ? 1 : 0);
