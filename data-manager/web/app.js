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
  fields: [],
  sort: { col: -1, dir: 1 },
  conds: [],
  editCount: 0,
  editedCells: new Set(),
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

async function postJSON(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || '请求失败');
  return j;
}

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
    state.editedCells = new Set();
    updateEditBadge();
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
    state.headers = []; state.rows = []; state.fields = []; state.kind = 'empty';
    renderTable('数据已清空，请点击【数据读取】重新加载');
    resetChart();
    return;
  }

  try {
    const j = await api('/api/table?cat=' + encodeURIComponent(cat));
    state.headers = j.headers;
    state.rows = j.rows;
    state.fields = j.fields || [];
    state.kind = j.kind;
    state.note = j.note;
    state.selectedFile = null;
    state.detail = null;
    state.editCount = j.editCount || 0;
    state.sort = { col: -1, dir: 1 };
    state.conds = [];
    updateEditBadge();
    buildFilterCols();
    renderTable();
    resetChart();
    $('#stCount').textContent = `${catLabel(cat)}：${j.rows.length} 行`;
    if (j.kind === 'spectrum' && j.rows.length) selectRow(0);
  } catch (e) {
    toast('读取列表失败：' + e.message, 3000);
  }
}

/* ---------- 取值：数字优先，日期/时间按字符串 ---------- */
function toNum(v) {
  const s = String(v ?? '').trim();
  if (!s || !/^-?\d+(\.\d+)?$/.test(s)) return null;
  return parseFloat(s);
}

function cellValue(row, ci) {
  const raw = row[ci];
  const n = toNum(raw);
  return n === null ? String(raw ?? '') : n;
}

/* ---------- 筛选 + 排序 ---------- */
const OPS = [
  { k: 'contains', label: '包含' },
  { k: 'notContain', label: '不包含' },
  { k: 'eq', label: '等于' },
  { k: 'ne', label: '不等于' },
  { k: 'gt', label: '大于' },
  { k: 'ge', label: '大于等于' },
  { k: 'lt', label: '小于' },
  { k: 'le', label: '小于等于' },
  { k: 'between', label: '介于' },
  { k: 'empty', label: '为空' },
  { k: 'notEmpty', label: '不为空' },
];

function matchCond(val, cond) {
  const want = cond.val;
  const raw = String(val ?? '').trim();
  const isBlank = raw === '' || raw === '—';
  if (cond.op === 'empty') return isBlank;
  if (cond.op === 'notEmpty') return !isBlank;

  // 大小比较：空值一律不参与，避免 '—' > '50' 这类字符串比较误命中
  const relational = ['gt', 'ge', 'lt', 'le', 'between'].includes(cond.op);
  if (relational && isBlank) return false;

  const a = toNum(raw);
  const b = toNum(want);
  const numeric = a !== null && b !== null;

  switch (cond.op) {
    case 'contains':
      return raw.toLowerCase().includes(String(want).toLowerCase());
    case 'notContain':
      return !raw.toLowerCase().includes(String(want).toLowerCase());
    case 'eq':
      return numeric ? a === b : raw.toLowerCase() === String(want).toLowerCase();
    case 'ne':
      return numeric ? a !== b : raw.toLowerCase() !== String(want).toLowerCase();
    case 'gt':
      return numeric ? a > b : raw > String(want);
    case 'ge':
      return numeric ? a >= b : raw >= String(want);
    case 'lt':
      return numeric ? a < b : raw < String(want);
    case 'le':
      return numeric ? a <= b : raw <= String(want);
    case 'between': {
      if (!numeric) return true;
      const c = toNum(cond.val2);
      if (c === null) return a >= b;
      const lo = Math.min(b, c), hi = Math.max(b, c);
      return a >= lo && a <= hi;
    }
    default:
      return true;
  }
}

function activeConds() {
  return state.conds.filter(c => c.col >= 0 && c.op &&
    (c.op === 'empty' || c.op === 'notEmpty' || String(c.val).trim() !== ''));
}

function filteredRows() {
  let rows = state.rows;
  const conds = activeConds();
  if (conds.length) {
    rows = rows.filter(r => conds.every(c => matchCond(r[c.col], c)));
  }
  if (state.filter) {
    const q = state.filter.toLowerCase();
    rows = rows.filter(r => r.some(c => String(c).toLowerCase().includes(q)));
  }
  return rows;
}

function sortedRows(rows) {
  const { col, dir } = state.sort;
  if (col < 0 || dir === 0) return rows;
  const decorated = rows.map((r, i) => ({ r, i }));
  decorated.sort((x, y) => {
    const ra = String(x.r[col] ?? '').trim();
    const rb = String(y.r[col] ?? '').trim();
    const ba = ra === '' || ra === '—';
    const bb = rb === '' || rb === '—';
    if (ba !== bb) return ba ? 1 : -1;          // 空值恒排末尾，不随升降序翻转
    const a = cellValue(x.r, col);
    const b = cellValue(y.r, col);
    let c;
    if (typeof a === 'number' && typeof b === 'number') c = a - b;
    else c = String(a).localeCompare(String(b), 'zh-CN', { numeric: true });
    return c !== 0 ? c * dir : x.i - y.i;      // 相等时保持原序，避免跳动
  });
  return decorated.map(d => d.r);
}

function visibleRows() {
  return sortedRows(filteredRows());
}

function renderTable(emptyMsg) {
  const theadRow = $('#tbl thead tr');
  const tbody = $('#tbl tbody');
  theadRow.innerHTML = '';
  tbody.innerHTML = '';

  const totalW = state.headers.reduce((s, h) => s + h[1], 0);
  $('#tbl').style.minWidth = totalW ? totalW + 'px' : '0';

  const idxLabel = state.sort.col === 0 ? '序号' : '序号';
  state.headers.forEach(([label, w], ci) => {
    const th = document.createElement('th');
    th.style.width = w + 'px';
    th.title = ci === 0 ? `${label}（点击按原始顺序排序）` : `${label}（点击排序）`;
    const mark = document.createElement('i');
    mark.className = 'sortmark';
    const sorted = state.sort.col === ci && state.sort.dir !== 0;
    mark.textContent = sorted ? (state.sort.dir > 0 ? '▲' : '▼') : '⇅';
    th.appendChild(document.createTextNode(label));
    th.appendChild(mark);
    if (sorted) th.classList.add('sorted');
    th.addEventListener('click', () => toggleSort(ci));
    theadRow.appendChild(th);
  });

  const rows = visibleRows();
  const frag = document.createDocumentFragment();
  rows.forEach(row => {
    const idx = state.rows.indexOf(row);
    const tr = document.createElement('tr');
    tr.dataset.i = idx;
    tr.dataset.file = row[1];
    const fieldMap = state.fields[idx] || {};
    row.forEach((cell, ci) => {
      const td = document.createElement('td');
      const txt = String(cell ?? '');
      if (ci === 0) td.className = 'idx';
      else if (txt !== '' && /^-?\d+(\.\d+)?$/.test(txt)) td.className = 'num';
      td.textContent = txt;
      td.title = txt;

      const f = fieldMap[ci];
      if (f && f.ro) {
        td.classList.add('readonly');
        td.title = `${txt}　（来自同编号频谱文件，只读）`;
      } else if (f) {
        const isDirty = (state.editedCells || new Set()).has(`${idx}:${ci}`);
        td.classList.add('editable');
        if (isDirty) td.classList.add('modified');
        td.title = `${txt}　（双击或直接输入可修改）`;
        td.dataset.col = ci;
        td.addEventListener('click', ev => {
          // 单击仍用于选中行，仅当已在编辑态才吞掉
          if (td.querySelector('input')) ev.stopPropagation();
        });
        td.addEventListener('dblclick', ev => {
          ev.stopPropagation();
          beginEdit(td, idx, ci, f, txt);
        });
      }
      tr.appendChild(td);
    });
    if (state.selectedFile && row[1] === state.selectedFile) tr.classList.add('sel');
    tr.addEventListener('click', () => selectRow(idx));
    frag.appendChild(tr);
  });
  tbody.appendChild(frag);

  const empty = $('#tableEmpty');
  const filteredOut = state.rows.length && !rows.length;
  if (!rows.length) {
    empty.hidden = false;
    empty.textContent = filteredOut
      ? '没有符合当前条件的数据，请调整或清空筛选条件'
      : (emptyMsg || state.note || '该分类暂无数据');
  } else {
    empty.hidden = true;
  }
  updateFpStat();
}

function toggleSort(ci) {
  if (state.sort.col !== ci) {
    state.sort = { col: ci, dir: 1 };
  } else {
    // 升序 → 降序 → 取消
    state.sort.dir = state.sort.dir === 1 ? -1 : 0;
    if (state.sort.dir === 0) state.sort.col = -1;
  }
  renderTable();
}

/* ---------- 单元格就地编辑 ---------- */
function beginEdit(td, idx, ci, field, cur) {
  if (td.querySelector('input')) return;
  const input = document.createElement('input');
  input.className = 'cell-input';
  input.type = 'text';
  input.value = cur === '—' ? '' : cur;
  if (field.t === 'num') input.inputMode = 'decimal';
  td.textContent = '';
  td.appendChild(input);
  input.focus();
  input.select();

  let done = false;

  const cancel = () => {
    if (done) return;
    done = true;
    renderTable();
  };

  const commit = async () => {
    if (done) return;
    const val = input.value.trim();
    if (val === (cur === '—' ? '' : cur)) return cancel();
    done = true;
    await saveCell(idx, ci, field, val, cur);
  };

  input.addEventListener('keydown', ev => {
    if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
    else if (ev.key === 'Escape') { ev.preventDefault(); cancel(); }
    else if (ev.key === 'Tab') { ev.preventDefault(); commit(); }
  });
  input.addEventListener('blur', () => { if (!done) commit(); });
}

async function saveCell(idx, ci, field, val, oldTxt) {
  const row = state.rows[idx];
  const file = row[1];
  try {
    await postJSON('/api/edit', { file, path: field.p, value: val });
  } catch (e) {
    toast('保存失败：' + e.message, 3200);
    return renderTable();
  }

  // 本地同步：更新表格显示 & 曲线数据
  const shown = field.t === 'num'
    ? (val === '' ? '—' : (Number(val).toFixed(1)))
    : val;
  row[ci] = shown;

  if (!state.editedCells) state.editedCells = new Set();
  state.editedCells.add(`${idx}:${ci}`);
  if (val === '' || val === String(oldTxt)) state.editedCells.delete(`${idx}:${ci}`);

  state.detail = null;
  state.cache.delete(file);
  const allCells = Object.keys(state.fields[idx] || {}).filter(k => state.editedCells.has(`${idx}:${k}`));
  state.editCount = Math.max(state.editCount || 0, allCells.length);
  updateEditBadge();

  renderTable();
  const td = $('#tbl tbody tr[data-i="' + idx + '"] td:nth-child(' + (ci + 1) + ')');
  if (td) { td.classList.add('dirty-flash'); }
  toast(`已记录修改（原始 AWA 文件未改动）`, 1600);

  if (state.selectedFile === file) {
    await loadDetail(file);
  }
}

function updateEditBadge() {
  const n = state.editCount || 0;
  const badge = $('#editBadge');
  badge.textContent = n;
  badge.hidden = !n;
  $('#btnRevert').disabled = !n;
}

async function revertEdits() {
  const file = state.selectedFile && state.editedCells &&
    [...state.editedCells].some(k => state.rows[Number(k.split(':')[0])]?.[1] === state.selectedFile)
    ? state.selectedFile : null;
  const scope = file ? `文件 ${file} 的` : '本目录全部';
  if (!confirm(`确定撤销${scope}修改吗？\n原始 AWA 文件不受影响，撤销后显示回到仪器原始值。`)) return;
  try {
    const j = await postJSON('/api/revert', file ? { file } : {});
    state.editedCells = new Set();
    state.editCount = j.count || 0;
    state.cache.clear();
    updateEditBadge();
    const data = await api('/api/table?cat=' + encodeURIComponent(state.cat));
    state.rows = data.rows;
    state.fields = data.fields || [];
    renderTable();
    if (state.selectedFile) await loadDetail(state.selectedFile);
    toast(`已撤销 ${j.reverted} 处修改`, 2000);
  } catch (e) {
    toast('撤销失败：' + e.message, 3000);
  }
}

/* ---------- 筛选面板 ---------- */
function buildFilterCols() {
  const rowsEl = $('#fpRows');
  rowsEl.innerHTML = '';
  state.conds = [];
}

function addCond() {
  const col = 2 < state.headers.length ? 2 : 0;
  state.conds.push({ col, op: 'contains', val: '', val2: '' });
  renderCondRows();
}

function renderCondRows() {
  const rowsEl = $('#fpRows');
  rowsEl.innerHTML = '';
  if (!state.conds.length) {
    const hint = document.createElement('div');
    hint.className = 'hint';
    hint.textContent = '还没有条件。点【+ 添加条件】按测点名、日期、声级等任意列组合筛选。';
    rowsEl.appendChild(hint);
  }

  state.conds.forEach((cond, i) => {
    const row = document.createElement('div');
    row.className = 'fp-row';

    const selCol = document.createElement('select');
    selCol.className = 'fp-col';
    state.headers.forEach(([label], ci) => {
      if (ci === 0) return;                       // 序号无筛选意义
      const o = document.createElement('option');
      o.value = ci;
      o.textContent = label;
      if (ci === cond.col) o.selected = true;
      selCol.appendChild(o);
    });
    selCol.addEventListener('change', () => {
      cond.col = Number(selCol.value);
      renderTable();
    });

    const selOp = document.createElement('select');
    selOp.className = 'fp-op';
    OPS.forEach(op => {
      const o = document.createElement('option');
      o.value = op.k;
      o.textContent = op.label;
      if (op.k === cond.op) o.selected = true;
      selOp.appendChild(o);
    });
    selOp.addEventListener('change', () => {
      cond.op = selOp.value;
      renderCondRows();
      renderTable();
    });

    const needVal = !['empty', 'notEmpty'].includes(cond.op);
    const inp = document.createElement('input');
    inp.className = 'fp-val';
    inp.placeholder = '值';
    inp.value = cond.val || '';
    inp.disabled = !needVal;
    inp.addEventListener('input', () => {
      cond.val = inp.value;
      renderTable();
    });
    inp.addEventListener('keydown', ev => { if (ev.key === 'Enter') renderTable(); });

    row.appendChild(selCol);
    row.appendChild(selOp);
    row.appendChild(inp);

    if (cond.op === 'between') {
      const inp2 = document.createElement('input');
      inp2.className = 'fp-val2';
      inp2.placeholder = '上限';
      inp2.value = cond.val2 || '';
      inp2.addEventListener('input', () => {
        cond.val2 = inp2.value;
        renderTable();
      });
      row.appendChild(inp2);
    }

    const del = document.createElement('button');
    del.className = 'fp-del';
    del.textContent = '×';
    del.title = '删除该条件';
    del.addEventListener('click', () => {
      state.conds.splice(i, 1);
      renderCondRows();
      renderTable();
    });
    row.appendChild(del);
    rowsEl.appendChild(row);
  });

  const n = activeConds().length;
  const badge = $('#filterBadge');
  badge.textContent = n;
  badge.hidden = !n;
  updateFpStat();
}

function updateFpStat() {
  const el = $('#fpStat');
  if (!el) return;
  const shown = visibleRows().length;
  const total = state.rows.length;
  const n = activeConds().length;
  const sortTxt = state.sort.col >= 0 && state.sort.dir
    ? `　排序：${state.headers[state.sort.col]?.[0] || ''} ${state.sort.dir > 0 ? '升序' : '降序'}`
    : '';
  el.textContent = n
    ? `符合条件 ${shown} 行 / 共 ${total} 行${sortTxt}`
    : `全部 ${total} 行${sortTxt}`;
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
      .map((b, i) => ({ x: xOf(i), y: rec.metrics[m.key]?.[b], b }))
      .filter(p => p.y !== null && p.y !== undefined)
      .map(p => ({ x: p.x, y: yOf(p.y), b: p.b, v: p.y }));
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
    // 记住屏幕坐标，供点击命中和悬停高亮
    m._pts = pts;
  });
  ctx.restore();

  // 悬停/编辑高亮的点
  const hp = chartHit.point;
  if (hp) {
    ctx.save();
    ctx.strokeStyle = '#e05a3a';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(hp.x, hp.y, 5, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = '#e05a3a';
    ctx.font = '11.5px Consolas,"Segoe UI",sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(`${fmtHz(hp.b)}Hz  ${hp.v.toFixed(1)} dB`, hp.x + 9, hp.y - 7);
    ctx.restore();
  }

  // 右下角信息
  if (active.length === 0) {
    ctx.fillStyle = '#a4b1be';
    ctx.font = '12px "Microsoft YaHei",sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('全部曲线已隐藏，请在上方勾选', a.x + a.w / 2, a.y + a.h / 2);
  }
}

/* ---------- 曲线点命中与就地编辑 ---------- */
const chartHit = { point: null, metric: null };

function hitPoint(ev) {
  const rec = state.detail;
  if (!rec || !['1/3OCT', 'OCT'].includes(rec.kind)) return null;
  const rect = canvas.getBoundingClientRect();
  const mx = ev.clientX - rect.left;
  const my = ev.clientY - rect.top;
  let best = null;
  let bestD = 12;                       // 命中半径（px）
  METRICS.forEach(m => {
    if (!state.vis[m.key] || !m._pts) return;
    m._pts.forEach(p => {
      const d = Math.hypot(p.x - mx, p.y - my);
      if (d < bestD) { bestD = d; best = { ...p, metric: m.key }; }
    });
  });
  return best;
}

canvas.addEventListener('mousemove', ev => {
  const p = hitPoint(ev);
  const rec = state.detail;
  if (!p) {
    if (chartHit.point) { chartHit.point = null; draw(); }
    canvas.style.cursor = '';
    canvas.title = '';
    return;
  }
  canvas.style.cursor = 'pointer';
  canvas.title = `${p.metric} · ${fmtHz(p.b)}Hz = ${p.v.toFixed(1)} dB（单击可修改）`;
  if (!chartHit.point || chartHit.point.x !== p.x || chartHit.point.y !== p.y) {
    chartHit.point = p;
    chartHit.metric = p.metric;
    draw();
  }
});

canvas.addEventListener('mouseleave', () => {
  if (chartHit.point) { chartHit.point = null; draw(); }
});

canvas.addEventListener('click', ev => {
  const p = hitPoint(ev);
  if (!p) return;
  editPoint(p);
});

function editPoint(p) {
  const rec = state.detail;
  const path = rec?.editPaths?.[p.metric]?.[p.b];
  if (!path) return toast('该点不可编辑');
  const val = prompt(
    `${p.metric}  ·  ${fmtHz(p.b)} Hz\n当前值 ${p.v.toFixed(1)} dB\n\n输入新值（留空撤销该点修改）：`,
    p.v.toFixed(1));
  if (val === null) return;
  const num = val.trim();
  if (num !== '' && !/^-?\d+(\.\d+)?$/.test(num)) return toast('请输入数字', 2000);

  postJSON('/api/edit', { file: rec.file, path, value: num })
    .then(async () => {
      state.cache.delete(rec.file);
      state.editCount = Math.max(state.editCount || 0, 1);
      updateEditBadge();
      chartHit.point = null;
      await loadDetail(rec.file);
      const data = await api('/api/table?cat=' + encodeURIComponent(state.cat));
      state.rows = data.rows;
      state.fields = data.fields || [];
      renderTable();
      toast('已记录修改（原始 AWA 文件未改动）', 1600);
    })
    .catch(e => toast('保存失败：' + e.message, 3000));
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
  state.fields = [];
  state.conds = [];
  state.editCount = 0;
  state.editedCells = new Set();
  state.kind = 'empty';
  state.selectedFile = null;
  state.detail = null;
  state.cache.clear();
  updateEditBadge();
  updateFpStat();
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

/* -------- 筛选面板 -------- */
$('#btnFilter').addEventListener('click', () => {
  const p = $('#filterPanel');
  p.hidden = !p.hidden;
  if (!p.hidden && !state.conds.length) addCond();
});
$('#fpClose').addEventListener('click', () => { $('#filterPanel').hidden = true; });
$('#fpAdd').addEventListener('click', () => { addCond(); renderTable(); });
$('#fpReset').addEventListener('click', () => {
  state.conds = [];
  state.sort = { col: -1, dir: 1 };
  renderCondRows();
  renderTable();
  toast('已清空筛选与排序');
});
$('#btnRevert').addEventListener('click', revertEdits);

/* 表格空白处双击不再触发文件定位，改为提示可编辑 */
$('#tbl').addEventListener('dblclick', e => {
  if (e.target.closest('td')) return;
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
