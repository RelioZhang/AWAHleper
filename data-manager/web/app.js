/* ============================================================
   AWA 声学数据管理 · 前端逻辑
   - 数据来自本地服务 /api/*
   - 图表用 Canvas 自绘，不依赖任何第三方库
   ============================================================ */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/* 曲线定义：颜色对齐 AWA 助手的取色 */
const METRICS = [
  { key: 'LFmax', color: '#141414' },
  { key: 'LFmin', color: '#17c60c' },
  { key: 'LSmax', color: '#b9c0c8' },
  { key: 'LSmin', color: '#e000d8' },
  { key: 'Leq,T', color: '#1246d4' },
];

const state = {
  dir: '',
  cat: '13OCT',
  categories: [],
  instrument: {},
  headers: [],
  rows: [],
  kind: 'empty',
  note: '',
  filter: '',
  selectedFile: null,
  detail: null,
  cleared: false,
  recent: [],
  suggest: [],
  vis: Object.fromEntries(METRICS.map(m => [m.key, true])),
  cache: new Map(),
  w: 0, h: 0,
};

const canvas = $('#chart');
const ctx = canvas.getContext('2d');

/* ============================================================ 基础工具 */
function toast(msg, ms = 2200) {
  const el = $('#toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, ms);
}

function showLoading(on) { $('#loading').hidden = !on; }

async function api(path) {
  const r = await fetch(path, { cache: 'no-store' });
  const ct = r.headers.get('content-type') || '';
  if (!ct.includes('json')) throw new Error('服务无响应，请确认 server.py 仍在运行');
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || '请求失败');
  return j;
}

const fmtDb = v => (v === null || v === undefined || Number.isNaN(v)) ? '—' : Number(v).toFixed(1);

function fmtHz(h) {
  h = Number(h);
  if (h >= 1000) {
    const s = (h / 1000).toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    return s + 'k';
  }
  return String(Math.round(h * 10) / 10);
}

function catLabel(key) {
  const c = state.categories.find(x => x.key === key);
  return c ? c.label : key;
}

/* ============================================================ 左栏分类 */
function renderCats() {
  const ul = $('#catList');
  ul.innerHTML = '';
  state.categories.forEach(c => {
    const li = document.createElement('li');
    li.dataset.cat = c.key;
    if (c.key === state.cat) li.classList.add('active');
    if (!c.count) li.classList.add('dim');
    li.innerHTML = `<span class="cdot"></span><span class="cname">${c.label}</span>
      <span class="badge${c.count ? '' : ' zero'}">${c.count}</span>`;
    li.addEventListener('click', () => loadTable(c.key));
    ul.appendChild(li);
  });
}

function renderInstrument() {
  const i = state.instrument || {};
  $('#insModel').textContent = i.model || '—';
  $('#insSerial').textContent = i.serial || '—';
  $('#insRange').textContent = i.range || '—';
}

/* ============================================================ 数据读取 */
async function scan(dir) {
  showLoading(true);
  try {
    const j = await api('/api/scan' + (dir ? '?dir=' + encodeURIComponent(dir) : ''));
    state.dir = j.dir;
    state.categories = j.categories;
    state.instrument = j.instrument || {};
    state.recent = j.recent || [];
    state.suggest = j.suggest || [];
    state.cleared = false;
    state.cache.clear();
    renderCats();
    renderInstrument();
    renderDirChips();

    const awaCount = j.categories.find(c => c.key === '13OCT')?.count || 0;
    $('#stDir').textContent = '数据目录：' + j.dir;
    $('#stCount').textContent = `文件 ${j.files} 个 · 1/3OCT ${awaCount} 份`;
    $('#stTime').textContent = `读取耗时 ${j.elapsedMs} ms`;
    $('#tbNote').textContent = '本地服务 · ' + (j.instrument?.model || 'AWA');
    $('#dirInput').value = j.dir;

    await loadTable(state.cat);
    if (!j.files) {
      $('#dirInput').value = j.dir;
      $('#modal').hidden = false;
      toast('该目录下没有 AWA 文件，请选择本次测试数据所在的文件夹', 3200);
      return;
    }
    $('#modal').hidden = true;
    toast(`读取完成：${j.files} 个文件，用时 ${j.elapsedMs} ms`);
    if (j.errors && j.errors.length) {
      toast(`有 ${j.errors.length} 个文件解析失败，详见控制台`, 3200);
      console.warn('解析失败：', j.errors);
    }
  } catch (e) {
    toast('读取失败：' + e.message, 3200);
  } finally {
    showLoading(false);
  }
}

/* ---------- 目录选择 ---------- */
function baseName(p) {
  const parts = String(p).replace(/[\\/]+$/, '').split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

function makeChip(label, sub, full, onClick) {
  const b = document.createElement('button');
  b.className = 'dchip';
  b.title = full;
  b.innerHTML = `<b></b><span></span>`;
  b.querySelector('b').textContent = label;
  b.querySelector('span').textContent = sub || '';
  b.addEventListener('click', onClick);
  return b;
}

function renderDirChips() {
  const recent = state.recent || [];
  const suggest = state.suggest || [];

  const rf = $('#recentField'), rl = $('#recentList');
  rf.hidden = !recent.length;
  rl.innerHTML = '';
  recent.forEach(p => {
    rl.appendChild(makeChip(baseName(p), p, p, () => applyDir(p)));
  });

  const sf = $('#suggestField'), sl = $('#suggestList');
  sf.hidden = !suggest.length;
  sl.innerHTML = '';
  suggest.forEach(s => {
    sl.appendChild(makeChip(s.name, `${s.count} 个 AWA · ${s.mtime}`, s.path, () => applyDir(s.path)));
  });
}

async function applyDir(path) {
  $('#dirInput').value = path;
  await scan(path);
}

async function pickDir() {
  const btn = $('#btnBrowse');
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '选择中…';
  toast('请在弹出的系统窗口中选择文件夹', 4000);
  try {
    const j = await api('/api/pick-dir');
    if (j.dir) {
      await applyDir(j.dir);
    } else {
      toast('已取消选择');
    }
  } catch (e) {
    toast('无法打开系统文件夹选择框，请直接粘贴路径：' + e.message, 5000);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

/* ============================================================ 列表 */
async function loadTable(cat) {
  state.cat = cat;
  state.filter = '';
  $('#filter').value = '';
  renderCats();

  if (state.cleared) {
    state.headers = []; state.rows = []; state.kind = 'empty';
    renderTable('数据已清空，请点击【数据读取】重新加载');
    resetChart();
    return;
  }

  try {
    const j = await api('/api/table?cat=' + encodeURIComponent(cat));
    state.headers = j.headers;
    state.rows = j.rows;
    state.kind = j.kind;
    state.note = j.note;
    state.selectedFile = null;
    state.detail = null;
    renderTable();
    resetChart();
    $('#stCount').textContent = `${catLabel(cat)}：${j.rows.length} 行`;
    if (j.kind === 'spectrum' && j.rows.length) selectRow(0);
  } catch (e) {
    toast('读取列表失败：' + e.message, 3000);
  }
}

function filteredRows() {
  if (!state.filter) return state.rows;
  const q = state.filter.toLowerCase();
  return state.rows.filter(r => r.some(c => String(c).toLowerCase().includes(q)));
}

function renderTable(emptyMsg) {
  const theadRow = $('#tbl thead tr');
  const tbody = $('#tbl tbody');
  theadRow.innerHTML = '';
  tbody.innerHTML = '';

  const totalW = state.headers.reduce((s, h) => s + h[1], 0);
  $('#tbl').style.minWidth = totalW ? totalW + 'px' : '0';

  state.headers.forEach(([label, w]) => {
    const th = document.createElement('th');
    th.textContent = label;
    th.style.width = w + 'px';
    th.title = label;
    theadRow.appendChild(th);
  });

  const rows = filteredRows();
  const frag = document.createDocumentFragment();
  rows.forEach(row => {
    const idx = state.rows.indexOf(row);
    const tr = document.createElement('tr');
    tr.dataset.i = idx;
    tr.dataset.file = row[1];
    row.forEach((cell, ci) => {
      const td = document.createElement('td');
      const txt = String(cell ?? '');
      td.textContent = txt;
      if (ci === 0) td.className = 'idx';
      else if (txt !== '' && /^-?\d+(\.\d+)?$/.test(txt)) td.className = 'num';
      td.title = txt;
      tr.appendChild(td);
    });
    if (state.selectedFile && row[1] === state.selectedFile) tr.classList.add('sel');
    tr.addEventListener('click', () => selectRow(idx));
    tr.addEventListener('dblclick', () => reveal(row[1]));
    frag.appendChild(tr);
  });
  tbody.appendChild(frag);

  const empty = $('#tableEmpty');
  if (!rows.length) {
    empty.hidden = false;
    empty.textContent = emptyMsg || (state.note || '该分类暂无数据');
  } else {
    empty.hidden = true;
  }
}

/* ============================================================ 选中与详情 */
function selectRow(idx) {
  const row = state.rows[idx];
  if (!row) return;
  state.selectedFile = row[1];
  $$('#tbl tbody tr').forEach(tr => tr.classList.toggle('sel', Number(tr.dataset.i) === idx));
  loadDetail(row[1]);
}

async function loadDetail(file) {
  try {
    let rec = state.cache.get(file);
    if (!rec) {
      rec = await api('/api/detail?f=' + encodeURIComponent(file));
      state.cache.set(file, rec);
    }
    if (state.selectedFile !== file) return;      // 快速连点时丢弃过期响应
    state.detail = rec;

    renderCurveBar(rec);
    $('#chartEmpty').hidden = true;
    draw();
  } catch (e) {
    toast('读取详情失败：' + e.message, 3000);
  }
}

/* ============================================================ 曲线条 */
function renderCurveBar(rec) {
  const bar = $('#curvebar');
  const isSpectrum = rec && (rec.kind === '1/3OCT' || rec.kind === 'OCT');
  bar.hidden = !isSpectrum;
  if (!isSpectrum) return;

  $$('.curve', bar).forEach(el => el.remove());

  METRICS.forEach(m => {
    const bands = rec.metrics[m.key] || {};
    const has = Object.keys(bands).length > 0;
    const el = document.createElement('div');
    el.className = 'curve' + (state.vis[m.key] ? '' : ' off');
    el.innerHTML = `
      <label class="curve-head">
        <input type="checkbox" ${state.vis[m.key] ? 'checked' : ''} ${has ? '' : 'disabled'}>
        <span class="chip" style="background:${m.color}"></span>
        <span class="cname">${m.key}</span>
      </label>
      <div class="cval">${has ? fmtDb(curveTotal(rec, m.key)) : '—'}</div>`;
    el.querySelector('input').addEventListener('change', ev => {
      state.vis[m.key] = ev.target.checked;
      el.classList.toggle('off', !ev.target.checked);
      draw();
    });
    bar.appendChild(el);
  });

  // 左下角标识：当前显示的计权列
  $('#stubVal').textContent = 'SPL(Z) dB';
}

function curveTotal(rec, metric) {
  const s = (rec.spl || {})[metric] || {};
  return s['Z'] ?? s['A'] ?? null;
}

/* ============================================================ 绘图 */
function fitCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  state.w = Math.max(320, Math.floor(rect.width));
  state.h = Math.max(120, Math.floor(rect.height));
  canvas.width = Math.floor(state.w * dpr);
  canvas.height = Math.floor(state.h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function padding() {
  return { l: 62, r: 26, t: 16, b: 46 };
}

function plotArea() {
  const p = padding();
  return { x: p.l, y: p.t, w: state.w - p.l - p.r, h: state.h - p.t - p.b };
}

function draw() {
  fitCanvas();
  ctx.clearRect(0, 0, state.w, state.h);
  const rec = state.detail;
  if (!rec) return drawEmptyGrid();
  switch (rec.kind) {
    case '1/3OCT':
    case 'OCT': return drawSpectrum(rec);
    case 'NUM': return drawDist(rec);
    case 'STA': return drawStats(rec);
    default: return drawEmptyGrid('该类型暂不支持图形预览');
  }
}

function yTicks(min, max, step) {
  const out = [];
  const start = Math.ceil(min / step) * step;
  for (let v = start; v <= max + 1e-9; v += step) out.push(Math.round(v * 10) / 10);
  return out;
}

function niceRange(values, fallback = [0, 100], pad = 3) {
  if (!values.length) return { min: fallback[0], max: fallback[1], step: 10 };
  let lo = Math.min(...values) - pad;
  let hi = Math.max(...values) + pad;
  const span = hi - lo;
  const step = span <= 25 ? 2 : span <= 60 ? 5 : 10;
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  if (hi - lo < step * 3) hi = lo + step * 3;
  return { min: lo, max: hi, step };
}

function drawGridY(min, max, step, unit = 'dB') {
  const a = plotArea();
  ctx.save();
  ctx.font = '11px Consolas,"Segoe UI",sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  yTicks(min, max, step).forEach(v => {
    const y = a.y + a.h - (v - min) / (max - min) * a.h;
    ctx.strokeStyle = '#e9eef4';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(a.x, Math.round(y) + .5);
    ctx.lineTo(a.x + a.w, Math.round(y) + .5);
    ctx.stroke();
    ctx.fillStyle = '#8b9aa9';
    ctx.fillText(v.toFixed(1), a.x - 8, y);
  });
  // 单位标识（左上）
  ctx.fillStyle = '#9dabb8';
  ctx.textAlign = 'left';
  ctx.font = '11px Consolas,"Segoe UI",sans-serif';
  ctx.fillText(unit, a.x - 54, a.y + 2);
  ctx.restore();
}

function drawAxes() {
  const a = plotArea();
  ctx.strokeStyle = '#c3cfda';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(a.x + .5, a.y);
  ctx.lineTo(a.x + .5, a.y + a.h + .5);
  ctx.lineTo(a.x + a.w, a.y + a.h + .5);
  ctx.stroke();
}

/* ---------- 空图：0~100 dB 网格 ---------- */
function drawEmptyGrid() {
  const a = plotArea();
  drawGridY(0, 100, 10);
  drawAxes();
  ctx.strokeStyle = '#f1f5f9';
  for (let i = 1; i < 12; i++) {
    const x = a.x + a.w * i / 12;
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + .5, a.y);
    ctx.lineTo(Math.round(x) + .5, a.y + a.h);
    ctx.stroke();
  }
}

/* ---------- 频谱曲线 ---------- */
function drawSpectrum(rec) {
  const a = plotArea();
  const bands = Array.from(new Set(
    METRICS.flatMap(m => Object.keys(rec.metrics[m.key] || {}).map(Number))
  )).sort((x, y) => x - y);
  if (!bands.length) return drawEmptyGrid('该文件没有频谱数据');

  const active = METRICS.filter(m => state.vis[m.key] && Object.keys(rec.metrics[m.key] || {}).length);
  const vals = [];
  active.forEach(m => bands.forEach(b => {
    const v = rec.metrics[m.key]?.[b];
    if (v !== null && v !== undefined) vals.push(v);
  }));
  const { min, max, step } = niceRange(vals, [0, 100]);

  drawGridY(min, max, step);
  drawAxes();

  const n = bands.length;
  const xOf = i => a.x + (n === 1 ? a.w / 2 : a.w * i / (n - 1));
  const yOf = v => a.y + a.h - (v - min) / (max - min) * a.h;

  // 纵向刻度线 + 频率标签（竖向，贴近 AWA 风格）
  ctx.save();
  ctx.strokeStyle = '#f2f6fa';
  ctx.lineWidth = 1;
  bands.forEach((b, i) => {
    const x = Math.round(xOf(i)) + .5;
    ctx.beginPath();
    ctx.moveTo(x, a.y);
    ctx.lineTo(x, a.y + a.h);
    ctx.stroke();
  });
  ctx.restore();

  ctx.save();
  ctx.font = '9.5px Consolas,"Segoe UI",sans-serif';
  ctx.fillStyle = '#6f8091';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  bands.forEach((b, i) => {
    const x = xOf(i);
    ctx.save();
    ctx.translate(x, a.y + a.h + 13);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(fmtHz(b), 0, 0);
    ctx.restore();
    ctx.strokeStyle = '#c9d5e1';
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + .5, a.y + a.h);
    ctx.lineTo(Math.round(x) + .5, a.y + a.h + 4);
    ctx.stroke();
  });
  ctx.restore();

  // 曲线
  ctx.save();
  ctx.beginPath();
  ctx.rect(a.x, a.y - 1, a.w, a.h + 1);
  ctx.clip();
  active.forEach(m => {
    const pts = bands
      .map((b, i) => ({ x: xOf(i), y: rec.metrics[m.key]?.[b] }))
      .filter(p => p.y !== null && p.y !== undefined)
      .map(p => ({ x: p.x, y: yOf(p.y) }));
    if (!pts.length) return;
    ctx.strokeStyle = m.color;
    ctx.lineWidth = 1.6;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
    if (pts.length <= 40) {
      ctx.fillStyle = m.color;
      pts.forEach(p => ctx.fillRect(p.x - 1.6, p.y - 1.6, 3.2, 3.2));
    }
  });
  ctx.restore();

  // 右下角信息
  if (active.length === 0) {
    ctx.fillStyle = '#a4b1be';
    ctx.font = '12px "Microsoft YaHei",sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('全部曲线已隐藏，请在上方勾选', a.x + a.w / 2, a.y + a.h / 2);
  }
}

/* ---------- 声级分布 ---------- */
function drawDist(rec) {
  const a = plotArea();
  const pts = (rec.dist || []).filter(p => p[1] > 0);
  if (!pts.length) return drawEmptyGrid('该文件没有有效的声级分布数据');

  const maxPct = Math.max(...pts.map(p => p[1]));
  const { min, max } = niceRange([0, maxPct], [0, Math.max(10, maxPct)], 1);
  drawGridY(0, max, Math.max(2, Math.round(max / 8)), '%');

  const xs = pts.map(p => p[0]);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const xOf = v => a.x + (xMax === xMin ? a.w / 2 : a.w * (v - xMin) / (xMax - xMin));
  const yOf = v => a.y + a.h - (v - 0) / (max - 0) * a.h;

  drawAxes();

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(xOf(pts[0][0]), a.y + a.h);
  pts.forEach(p => ctx.lineTo(xOf(p[0]), yOf(p[1])));
  ctx.lineTo(xOf(pts[pts.length - 1][0]), a.y + a.h);
  ctx.closePath();
  const g = ctx.createLinearGradient(0, a.y, 0, a.y + a.h);
  g.addColorStop(0, 'rgba(43,127,196,.35)');
  g.addColorStop(1, 'rgba(43,127,196,.04)');
  ctx.fillStyle = g;
  ctx.fill();
  ctx.restore();

  ctx.strokeStyle = '#1246d4';
  ctx.lineWidth = 1.7;
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(xOf(p[0]), yOf(p[1])) : ctx.moveTo(xOf(p[0]), yOf(p[1]))));
  ctx.stroke();

  ctx.font = '10px Consolas,"Segoe UI",sans-serif';
  ctx.fillStyle = '#6f8091';
  ctx.textAlign = 'center';
  const n = 8;
  for (let i = 0; i <= n; i++) {
    const v = xMin + (xMax - xMin) * i / n;
    const x = xOf(v);
    ctx.fillText(v.toFixed(0), x, a.y + a.h + 16);
    ctx.strokeStyle = '#c9d5e1';
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + .5, a.y + a.h);
    ctx.lineTo(Math.round(x) + .5, a.y + a.h + 4);
    ctx.stroke();
  }
  ctx.textAlign = 'center';
  ctx.fillStyle = '#8b9aa9';
  ctx.fillText('声级 dB', a.x + a.w / 2, a.y + a.h + 34);
}

/* ---------- STA 统计量 ---------- */
function drawStats(rec) {
  const a = plotArea();
  const st = rec.stats && Object.values(rec.stats)[0];
  if (!st) return drawEmptyGrid('该文件没有统计数据');
  const keys = ['LeqT', 'Lmax', 'Lmin', 'L10', 'L50', 'L90', 'L95'];
  const pairs = keys.filter(k => st[k] !== undefined).map(k => [k, st[k]]);
  if (!pairs.length) return drawEmptyGrid('该文件没有统计数据');

  const vals = pairs.map(p => p[1]);
  const { min, max, step } = niceRange([Math.min(...vals), Math.max(...vals)], [0, 100], 2);
  drawGridY(min, max, step);
  drawAxes();

  const gap = a.w / pairs.length;
  const bw = Math.min(46, gap * 0.5);
  pairs.forEach((p, i) => {
    const x = a.x + gap * i + gap / 2;
    const y = a.y + a.h - (p[1] - min) / (max - min) * a.h;
    const g = ctx.createLinearGradient(0, y, 0, a.y + a.h);
    g.addColorStop(0, '#5aa9dd');
    g.addColorStop(1, '#cfe6f7');
    ctx.fillStyle = g;
    ctx.fillRect(x - bw / 2, y, bw, a.y + a.h - y);
    ctx.strokeStyle = '#4a95c8';
    ctx.strokeRect(x - bw / 2 + .5, y + .5, bw - 1, a.y + a.h - y - 1);
    ctx.fillStyle = '#2b3947';
    ctx.font = '11px Consolas,"Segoe UI",sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(p[1].toFixed(1), x, y - 7);
    ctx.fillStyle = '#6f8091';
    ctx.font = '11px "Microsoft YaHei",sans-serif';
    ctx.fillText(p[0].replace('L', 'L'), x, a.y + a.h + 16);
  });
}

/* ============================================================ 清空 / 重置 */
function resetChart(clearDetail = true) {
  $('#chartEmpty').hidden = !!state.detail;
  if (clearDetail) state.detail = null;
  if (!state.detail) drawEmptyGrid();
}

/* ============================================================ 操作 */
async function reveal(file) {
  if (!file) return toast('请先在列表中选择一个文件');
  try {
    await api('/api/reveal?f=' + encodeURIComponent(file));
  } catch (e) {
    toast('打开失败：' + e.message);
  }
}

function exportData() {
  if (!state.rows.length) return toast('当前分类没有可导出的数据');
  const a = document.createElement('a');
  a.href = '/api/export?cat=' + encodeURIComponent(state.cat);
  a.download = '';
  document.body.appendChild(a);
  a.click();
  a.remove();
  toast(`正在导出「${catLabel(state.cat)}」共 ${state.rows.length} 行…`);
}

function clearAll() {
  state.cleared = true;
  state.rows = [];
  state.headers = [];
  state.kind = 'empty';
  state.selectedFile = null;
  state.detail = null;
  state.cache.clear();
  renderTable('数据已清空，请点击【数据读取】重新加载');
  resetChart();
  $('#curvebar').hidden = true;
  $('#stCount').textContent = '';
  $('#stTime').textContent = '';
  toast('已清空当前数据视图');
}

/* ============================================================ 事件绑定 */
$('#btnRead').addEventListener('click', () => scan(state.dir || null));
$('#btnExport').addEventListener('click', exportData);
$('#btnOpen').addEventListener('click', () => reveal(state.selectedFile));
$('#btnClear').addEventListener('click', clearAll);

$('#filter').addEventListener('input', e => {
  state.filter = e.target.value.trim();
  renderTable();
});

$$('.mod').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.dataset.mod === 'data') return;
    toast('该模块不在本 Demo 范围内，当前聚焦【数据管理】');
  });
});

$$('.wb').forEach(b => b.addEventListener('click', () => {
  toast(b.dataset.win === 'close'
    ? '请关闭浏览器标签页；如需停服务，在启动窗口按 Ctrl+C'
    : '浏览器内无法控制窗口，可直接拖动浏览器窗口');
}));

$('#btnSetting').addEventListener('click', () => {
  $('#dirInput').value = state.dir || '';
  renderDirChips();
  $('#modal').hidden = false;
});
$('#btnBrowse').addEventListener('click', pickDir);
$('#modalClose').addEventListener('click', () => { $('#modal').hidden = true; });
$('#modalOk').addEventListener('click', () => { $('#modal').hidden = true; });
$('#modal').addEventListener('click', e => {
  if (e.target.id === 'modal') $('#modal').hidden = true;
});
$('#btnApplyDir').addEventListener('click', async () => {
  const v = $('#dirInput').value.trim();
  if (!v) return toast('请输入数据目录');
  $('#modal').hidden = true;
  await scan(v);
});
$('#dirInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') $('#btnApplyDir').click();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') $('#modal').hidden = true;
});

/* 尺寸变化重绘 */
let rzTimer = null;
new ResizeObserver(() => {
  clearTimeout(rzTimer);
  rzTimer = setTimeout(draw, 60);
}).observe($('.chartwrap'));

/* ============================================================ 启动 */
(function boot() {
  drawEmptyGrid();
  // 首次进入自动读一次，省得用户先点按钮；点击【数据读取】可随时重扫
  scan(null);
})();
