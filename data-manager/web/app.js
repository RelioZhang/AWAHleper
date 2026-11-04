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
  fields: [],
  bandCols: [],
  bandStart: -1,
  extraStart: -1,
  kind: 'empty',
  note: '',
  filter: '',
  selectedFile: null,
  detail: null,
  cleared: false,
  recent: [],
  suggest: [],
  sort: { col: -1, dir: 1 },
  conds: [],
  editCount: 0,
  editedCells: new Set(),
  picked: new Set(),          // 批量整理勾选的测量组编号
  tagFilter: '',              // 按标记过滤：'' | 噪声级 | 隔声
  tagCounts: {},
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
    const view = isEditMode() ? '&view=organize' : '';
    const tag = (isEditMode() && state.tagFilter) ? '&tag=' + encodeURIComponent(state.tagFilter) : '';
    const j = await api('/api/table?cat=' + encodeURIComponent(cat) + view + tag);
    state.tagCounts = j.tagCounts || {};
    state.headers = j.headers;
    state.rows = j.rows;
    state.fields = j.fields || [];
    state.kind = j.kind;
    state.note = j.note;
    state.bandCols = j.bandCols || [];
    state.bandStart = (typeof j.bandStart === 'number') ? j.bandStart : -1;
    state.extraStart = (typeof j.extraStart === 'number') ? j.extraStart : -1;
    state.selectedFile = null;
    state.detail = null;
    state.editCount = j.editCount || 0;
    state.sort = { col: -1, dir: 1 };
    applySavedSort();                 // 恢复上次的排序（按列名匹配）
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

  const totalW = state.headers.reduce(
    (sum, [label, w]) => sum + colWidth(state.cat, label, w), 0);
  $('#tbl').style.minWidth = totalW ? totalW + 'px' : '0';
  // 列多时固定序号与文件名，横向滚动不丢定位
  const tblEl = $('#tbl');
  const firstW = state.headers.length ? colWidth(state.cat, state.headers[0][0], state.headers[0][1]) : 58;
  tblEl.classList.toggle('sticky-cols', state.headers.length > 12);
  tblEl.style.setProperty('--idx-w', firstW + 'px');
  requestAnimationFrame(updateHScrollTip);

  // 整理模式：最前面加一列勾选框
  if (isEditMode()) {
    const th0 = document.createElement('th');
    th0.className = 'pickcol';
    const all = document.createElement('input');
    all.type = 'checkbox';
    all.title = '全选 / 取消全选（按测量组）';
    const shown = visibleRows();
    all.checked = shown.length > 0 && shown.every(r => state.picked.has(groupIdOf(r[1])));
    all.addEventListener('click', ev => ev.stopPropagation());
    all.addEventListener('change', () => {
      shown.forEach(r => {
        const g = groupIdOf(r[1]);
        if (all.checked) state.picked.add(g); else state.picked.delete(g);
      });
      renderTable();
      updateBatchUI();
    });
    th0.appendChild(all);
    theadRow.appendChild(th0);
  }

  state.headers.forEach(([label, w], ci) => {
    const th = document.createElement('th');
    const width = colWidth(state.cat, label, w);
    th.style.width = width + 'px';
    th.style.minWidth = width + 'px';
    th.title = `${label}（点击排序，拖动右边缘调列宽）`;

    // 文字放在内层，便于省略号生效，同时给拖拽把手留位置
    const inner = document.createElement('span');
    inner.className = 'th-inner';
    const mark = document.createElement('i');
    mark.className = 'sortmark';
    const sorted = state.sort.col === ci && state.sort.dir !== 0;
    mark.textContent = sorted ? (state.sort.dir > 0 ? '▲' : '▼') : '⇅';
    inner.appendChild(document.createTextNode(label));
    inner.appendChild(mark);
    th.appendChild(inner);

    // 列宽拖拽把手
    const grip = document.createElement('span');
    grip.className = 'colgrip';
    grip.addEventListener('mousedown', ev => startColResize(ev, th, label, ci));
    grip.addEventListener('click', ev => ev.stopPropagation());
    th.appendChild(grip);

    if (sorted) th.classList.add('sorted');
    if (state.bandStart >= 0 && ci >= state.bandStart) {
      const isExtra = state.extraStart >= 0 && ci >= state.extraStart;
      th.classList.add(isExtra ? 'matchhead' : 'bandhead');
    }
    th.addEventListener('click', ev => {
      if (ev.target === grip) return;
      toggleSort(ci);
    });
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
    if (isEditMode()) {
      const gid = groupIdOf(row[1]);
      const td0 = document.createElement('td');
      td0.className = 'pickcell';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = state.picked.has(gid);
      cb.addEventListener('click', ev => ev.stopPropagation());
      cb.addEventListener('change', () => {
        if (cb.checked) state.picked.add(gid); else state.picked.delete(gid);
        // 同组其他行同步勾选状态
        $$('#tbl tbody tr').forEach(o => {
          if (groupIdOf(o.dataset.file) === gid) {
            o.classList.toggle('picked', cb.checked);
            const c = o.querySelector('.pickcell input');
            if (c) c.checked = cb.checked;
          }
        });
        tr.classList.toggle('picked', cb.checked);
        updateBatchUI();
      });
      td0.appendChild(cb);
      tr.appendChild(td0);
      if (state.picked.has(gid)) tr.classList.add('picked');
    }
    row.forEach((cell, ci) => {
      const td = document.createElement('td');
      const txt = String(cell ?? '');
      if (ci === 0) td.className = 'idx';
      else if (state.bandStart >= 0 && ci >= state.bandStart) {
        const isExtra = state.extraStart >= 0 && ci >= state.extraStart;
        td.classList.add(isExtra ? 'matchext' : 'bandcell');
      }
      else if (txt !== '' && /^-?\d+(\.\d+)?$/.test(txt)) td.className = 'num';
      td.textContent = txt;
      td.title = txt;

      const f = fieldMap[ci];
      // 标记列单独处理
      if (f && f.t === 'tag') {
        td.classList.add('tagcell');
        const tag = String(cell || '');
        if (isEditMode()) {
          const sel = document.createElement('select');
          sel.className = 'tagsel';
          [['', '—'], ['噪声级', '噪声级'], ['隔声', '隔声']].forEach(([v, lb]) => {
            const o = document.createElement('option');
            o.value = v; o.textContent = lb;
            if (v === tag) o.selected = true;
            sel.appendChild(o);
          });
          sel.addEventListener('click', ev => ev.stopPropagation());
          sel.addEventListener('change', ev => {
            ev.stopPropagation();
            setTag(idx, ci, sel.value);
          });
          td.textContent = '';
          td.appendChild(sel);
        } else {
          td.textContent = tag || '—';
          if (tag) td.classList.add(tag === '噪声级' ? 't-noise' : 't-insul');
        }
        tr.appendChild(td);
        return;
      }
      if (f) {
        const isDirty = (state.editedCells || new Set()).has(`${idx}:${ci}`);
        if (isDirty) td.classList.add('modified');
        // 只有整理模式才允许就地编辑；原始数据保持只读
        if (isEditMode()) {
          td.classList.add('editable');
          td.dataset.cellCi = ci;
          if (f.one === 'group') td.classList.add('grp');
          td.title = f.one === 'group'
            ? `${txt}　（单击修改，Tab 跳到下一格，同步到同编号的 1/3OCT·OCT·STA·NUM 文件）`
            : `${txt}　（单击修改，Tab 跳到下一格）`;
          // 单击即进入编辑，同时仍选中该行（便于看曲线）
          td.addEventListener('click', ev => {
            ev.stopPropagation();
            selectRow(idx);
            beginEdit(td, idx, ci, f, txt);
          });
        } else if (isDirty) {
          td.title = `${txt}　（已在数据整理中修改；原始数据只读）`;
        }
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
  updateTagBar();
}

/* ---------- 排序状态持久化 ---------- */
/* 各分类列索引不同，用「列名」做键才能在分类间复用；存 localStorage 跨会话保留 */
const SORT_KEY = 'awa.sort.v1';

function loadSortMap() {
  try {
    const j = JSON.parse(localStorage.getItem(SORT_KEY) || '{}');
    return (j && typeof j === 'object') ? j : {};
  } catch (e) { return {}; }
}

function saveSort() {
  const map = loadSortMap();
  const colName = state.sort.col >= 0 ? state.headers[state.sort.col]?.[0] : '';
  if (!colName || !state.sort.dir) delete map[state.cat];
  else map[state.cat] = { col: colName, dir: state.sort.dir };
  try { localStorage.setItem(SORT_KEY, JSON.stringify(map)); } catch (e) { /* 隐私模式忽略 */ }
}

function applySavedSort() {
  const saved = loadSortMap()[state.cat];
  if (!saved || !saved.dir) return;
  const ci = state.headers.findIndex(h => h[0] === saved.col);
  if (ci >= 0) state.sort = { col: ci, dir: saved.dir };
}

/* ---------- 列宽：可拖动，并按分类+列名记忆 ---------- */
const WIDTH_KEY = 'awa.widths.v1';

function loadWidths() {
  try {
    const j = JSON.parse(localStorage.getItem(WIDTH_KEY) || '{}');
    return (j && typeof j === 'object') ? j : {};
  } catch (e) { return {}; }
}

function colWidth(cat, label, fallback) {
  const m = loadWidths()[cat];
  const w = m && m[label];
  return (typeof w === 'number' && w >= 40) ? w : fallback;
}

function setColWidth(cat, label, w) {
  const all = loadWidths();
  (all[cat] = all[cat] || {})[label] = Math.round(w);
  try { localStorage.setItem(WIDTH_KEY, JSON.stringify(all)); } catch (e) { /* ignore */ }
}

function startColResize(ev, th, label, ci) {
  ev.preventDefault();
  ev.stopPropagation();
  const startX = ev.clientX;
  const startW = th.getBoundingClientRect().width;
  document.body.classList.add('col-resizing');

  const onMove = e => {
    const w = Math.max(46, startW + (e.clientX - startX));
    th.style.width = w + 'px';
    th.style.minWidth = w + 'px';
  };
  const onUp = () => {
    document.body.classList.remove('col-resizing');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    const finalW = th.getBoundingClientRect().width;
    setColWidth(state.cat, label, finalW);
    // 同步到表头下拉宽条消失后的布局
    renderTable();
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

/* ---------- 横向滚动提示 ---------- */
function updateHScrollTip() {
  const wrap = $('.tablewrap');
  const tip = $('#hscrollTip');
  if (!wrap || !tip) return;
  const overflow = wrap.scrollWidth - wrap.clientWidth;
  tip.classList.toggle('show', overflow > 8);
}

function toggleSort(ci) {
  if (state.sort.col !== ci) {
    state.sort = { col: ci, dir: 1 };
  } else {
    // 升序 → 降序 → 取消
    state.sort.dir = state.sort.dir === 1 ? -1 : 0;
    if (state.sort.dir === 0) state.sort.col = -1;
  }
  saveSort();
  renderTable();
}

/* ---------- 单元格就地编辑 ---------- */
/* 编辑中的状态，供 Tab 跳格使用 */
let editing = null;   // { idx, ci }

/* 找到下一个可编辑单元格；dir=1 向后，-1 向前（跳过只读列与频带以外的列） */
function nextEditableCell(idx, ci, dir) {
  const rows = visibleRows();
  const total = rows.length;
  if (!total) return null;
  let ri = rows.indexOf(state.rows[idx]);
  if (ri < 0) ri = 0;
  let c = ci;

  for (let step = 0; step < 4000; step++) {
    c += dir;
    if (c >= state.headers.length) {
      c = 0;
      ri += 1;
      if (ri >= total) return null;
    } else if (c < 0) {
      c = state.headers.length - 1;
      ri -= 1;
      if (ri < 0) return null;
    }
    const row = rows[ri];
    const i = state.rows.indexOf(row);
    const f = (state.fields[i] || {})[c];
    if (f && !f.ro && (f.t === 'tag' || f.t === 'num' || f.t === 'text')) {
      return { idx: i, ci: c, field: f };
    }
  }
  return null;
}

function beginEdit(td, idx, ci, field, cur) {
  if (editing && editing.idx === idx && editing.ci === ci) return;

  // 已有一格在编辑就先提交它，避免丢改动
  if (editing) {
    const prev = document.querySelector('.cell-input');
    if (prev) prev.blur();
  }

  const tagCell = field.t === 'tag';
  let input;

  if (tagCell) {
    input = document.createElement('select');
    input.className = 'cell-input';
    [['', '—'], ['噪声级', '噪声级'], ['隔声', '隔声']].forEach(([v, lb]) => {
      const o = document.createElement('option');
      o.value = v;
      o.textContent = lb;
      if (v === cur) o.selected = true;
      input.appendChild(o);
    });
  } else {
    // textarea 才能容纳多行粘贴（从 Excel 拷一列过来也不会被截断）
    input = document.createElement('textarea');
    input.className = 'cell-input';
    input.rows = 1;
    input.spellcheck = false;
    input.value = cur === '—' ? '' : String(cur);
    if (field.t === 'num') input.inputMode = 'decimal';
  }

  td.textContent = '';
  td.classList.add('editing');
  td.appendChild(input);
  editing = { idx, ci };

  input.focus();
  if (!tagCell) input.select();

  let done = false;

  const cancel = () => {
    if (done) return;
    done = true;
    editing = null;
    renderTable();
  };

  const commit = async (dir = 0) => {
    if (done) return;
    const raw = input.value;
    const val = String(raw).trim().replace(/\s+/g, ' ');
    const before = cur === '—' ? '' : String(cur ?? '');
    done = true;
    const target = dir ? nextEditableCell(idx, ci, dir) : null;

    if (val === before) {
      editing = null;
      renderTable();
      if (target) focusCell(target);
      return;
    }
    await saveCell(idx, ci, field, val, cur);
    if (target) focusCell(target);
  };

  if (!tagCell) {
    input.addEventListener('paste', ev => {
      if (handlePasteCells(ev, idx, ci, field)) {
        done = true;
        editing = null;
        renderTable();
      }
    });
  }

  input.addEventListener('keydown', ev => {
    // 选择框里用方向键切换，不拦截
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      commit(0);
    } else if (ev.key === 'Escape') {
      ev.preventDefault();
      cancel();
    } else if (ev.key === 'Tab') {
      // Tab / Shift+Tab 提交并跳到相邻可编辑格
      ev.preventDefault();
      commit(ev.shiftKey ? -1 : 1);
    }
  });

  if (tagCell) {
    input.addEventListener('change', () => commit(0));
  }
  input.addEventListener('blur', () => { if (!done) commit(0); });
}

/* ---------- 粘贴多行：从 Excel 拷一列过来，自动往下填 ---------- */
function handlePasteCells(ev, idx, ci, field) {
  const text = (ev.clipboardData || window.clipboardData)?.getData('text') || '';
  if (!text) return false;
  // 单值：交给浏览器默认行为
  const lines = text.replace(/\r\n|\r/g, '\n').split('\n').filter(x => x !== '');
  if (lines.length <= 1) return false;
  ev.preventDefault();

  const rows = visibleRows();
  let ri = rows.indexOf(state.rows[idx]);
  if (ri < 0) return true;

  // 先收集要写的行，再串行提交（避免逐次重绘导致后续定位失败）
  const jobs = [];
  for (let k = 0; k < lines.length && ri + k < rows.length; k++) {
    const target = state.rows.indexOf(rows[ri + k]);
    const tf = (state.fields[target] || {})[ci] || field;
    jobs.push({ idx: target, field: tf, value: lines[k].trim(),
                old: state.rows[target][ci] });
  }
  (async () => {
    for (const job of jobs) {
      try {
        await postJSON('/api/edit', {
          file: state.rows[job.idx][1], path: job.field.p, value: job.value,
        });
        const shown = job.field.t === 'num'
          ? (job.value === '' ? '—' : Number(job.value).toFixed(1))
          : job.value;
        // 元数据要同步到同组其他行
        const gid = groupIdOf(state.rows[job.idx][1]);
        state.rows.forEach((r, i) => {
          if (i === job.idx || (job.field.one === 'group' && groupIdOf(r[1]) === gid)) {
            r[ci] = shown;
          }
        });
      } catch (e) { /* 单行失败不阻断其余 */ }
    }
    state.cache.clear();
    state.detail = null;
    renderTable();
    if (state.selectedFile) await loadDetail(state.selectedFile);
    toast(`已粘贴 ${jobs.length} 行到「${state.headers[ci][0]}」列`, 2400);
  })();
  return true;
}

/* 编辑完成后把焦点交给下一格（需等表格重绘完） */
function focusCell(target) {
  requestAnimationFrame(() => {
    const tr = document.querySelector(`#tbl tbody tr[data-i="${target.idx}"]`);
    if (!tr) return;
    const td = tr.children[cellIndexInDom(target.ci)];
    if (!td) return;
    td.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    beginEdit(td, target.idx, target.ci, target.field,
              td.textContent.trim());
  });
}

/* 键盘直接输入：停在某格时敲字符即进入编辑（Excel 手感） */
document.addEventListener('keydown', ev => {
  if (!isEditMode()) return;
  if (document.querySelector('.cell-input')) return;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (ev.key.length !== 1) return;
  const el = document.activeElement;
  if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
  const td = el && el.closest ? el.closest('#tbl td.editable') : null;
  if (!td) return;
  const tr = td.parentElement;
  const idx = Number(tr.dataset.i);
  const ci = Number(td.dataset.cellCi);
  const f = (state.fields[idx] || {})[ci];
  if (!f) return;
  ev.preventDefault();
  beginEdit(td, idx, ci, f, td.textContent.trim());
  const input = td.querySelector('.cell-input');
  if (input) { input.value = ev.key; }
});

/* 因为整理模式多了勾选列，DOM 里的列号会整体右移一位 */
function cellIndexInDom(ci) {
  return isEditMode() ? ci + 1 : ci;
}

/* 测量组：同一编号的 1_3_/OCT_/STA_/NUM_ 是同一次测量，元数据需同步 */
function groupIdOf(file) {
  const m = String(file).replace(/\.[^.]+$/, '').match(/(\d+)\D*$/);
  return m ? m[1] : String(file);
}

async function saveCell(idx, ci, field, val, oldTxt) {
  const row = state.rows[idx];
  const file = row[1];
  let res;
  try {
    res = await postJSON('/api/edit', { file, path: field.p, value: val });
  } catch (e) {
    toast('保存失败：' + e.message, 3200);
    return renderTable();
  }

  const shown = field.t === 'num'
    ? (val === '' ? '—' : (Number(val).toFixed(1)))
    : val;

  // 组联动：同编号其他文件也一起改成同一个值
  const gid = groupIdOf(file);
  let synced = 0;
  state.rows.forEach((r, i) => {
    if (i !== idx && gid && groupIdOf(r[1]) === gid) {
      r[ci] = shown;
      if (!state.editedCells) state.editedCells = new Set();
      state.editedCells.add(`${i}:${ci}`);
      synced++;
    }
  });

  row[ci] = shown;
  if (!state.editedCells) state.editedCells = new Set();
  state.editedCells.add(`${idx}:${ci}`);
  if (val === '' || val === String(oldTxt)) state.editedCells.delete(`${idx}:${ci}`);

  state.detail = null;
  state.cache.clear();                  // 组内文件都被改过，缓存全清
  state.editCount = Math.max(state.editCount || 0, (res.edits || 0), 1);
  updateEditBadge();

  renderTable();
  const td = $('#tbl tbody tr[data-i="' + idx + '"] td:nth-child(' + (ci + 1) + ')');
  if (td) td.classList.add('dirty-flash');

  const colName = state.headers[ci]?.[0] || '';
  const groupNote = (field.one === 'group')
    ? `「${colName}」已同步到同组 ${synced + 1} 个文件`
    : '已记录修改';
  toast(`${groupNote}（原始 AWA 文件未改动）`, 2200);

  if (state.selectedFile && groupIdOf(state.selectedFile) === gid) {
    await loadDetail(state.selectedFile);
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
  // 原始数据为只读视图，曲线点仅可查看不可修改
  if (!document.body.classList.contains('view-org')) {
    toast(`原始数据只读：${p.metric} ${fmtHz(p.b)}Hz = ${p.v.toFixed(1)} dB\n如需修改请到【数据整理】`, 2600);
    return;
  }
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
  saveSort();
  renderCondRows();
  renderTable();
  toast('已清空筛选与排序');
});
$('#btnRevert').addEventListener('click', revertEdits);

/* -------- 曲线区折叠 -------- */
const COLLAPSE_KEY = 'awa.chartCollapsed.v1';

function setChartCollapsed(on) {
  document.body.classList.toggle('chart-collapsed', !!on);
  try { localStorage.setItem(COLLAPSE_KEY, on ? '1' : '0'); } catch (e) { /* ignore */ }
  // 折叠/展开后画布尺寸变了，重绘一次
  requestAnimationFrame(() => {
    draw();
    updateHScrollTip();
  });
}

function toggleChart() {
  setChartCollapsed(!document.body.classList.contains('chart-collapsed'));
}

$('#btnToggleChart').addEventListener('click', ev => {
  ev.stopPropagation();
  toggleChart();
});
$('#chartExpandHint').addEventListener('click', toggleChart);

document.addEventListener('keydown', ev => {
  if (ev.altKey && (ev.key === 'c' || ev.key === 'C')) {
    ev.preventDefault();
    toggleChart();
  }
});

/* 恢复上次的折叠状态 */
try {
  if (localStorage.getItem(COLLAPSE_KEY) === '1') {
    document.body.classList.add('chart-collapsed');
  }
} catch (e) { /* ignore */ }

/* 表格空白处双击不再触发文件定位，改为提示可编辑 */
$('#tbl').addEventListener('dblclick', e => {
  if (e.target.closest('td')) return;
});

$$('.mod').forEach(btn => {
  btn.addEventListener('click', () => {
    const mod = btn.dataset.mod;
    if (mod === 'data' || mod === 'organize'
        || mod === 'report_noise' || mod === 'report_insul') {
      switchModule(mod);
      return;
    }
    toast('该模块尚未开发，当前可用【数据管理】【数据整理】【报告生成】');
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
  rzTimer = setTimeout(() => { draw(); updateHScrollTip(); }, 60);
}).observe($('.chartwrap'));

new ResizeObserver(() => updateHScrollTip()).observe($('.tablewrap'));
$('.tablewrap').addEventListener('scroll', () => {
  const tip = $('#hscrollTip');
  if (tip && tip.classList.contains('show')) {
    clearTimeout(tip._t);
    tip._t = setTimeout(() => tip.classList.remove('show'), 900);
  }
}, { passive: true });



/* ---------- 测量标记（噪声级 / 隔声） ---------- */
$$('#tagBar .tagchip').forEach(btn => {
  btn.addEventListener('click', () => setTagFilter(btn.dataset.tag || ''));
});


async function setTag(idx, ci, value) {
  const row = state.rows[idx];
  const gid = groupIdOf(row[1]);
  try {
    await postJSON('/api/edit', { file: row[1], path: '_tag', value });
  } catch (e) {
    return toast('标记失败：' + e.message, 3000);
  }
  // 同组所有行同步显示
  state.rows.forEach(r => {
    if (groupIdOf(r[1]) === gid) r[ci] = value;
  });
  state.cache.clear();
  renderTable();
  updateTagBar();
  toast(value ? `已标记为「${value}」` : '已清除标记', 1800);

  // 当前有过滤条件且这行不再匹配时，重新取表
  if (state.tagFilter && value !== state.tagFilter) {
    await loadTable(state.cat);
  }
}

/* 两个分类默认关注的标记类型 */
const DEFAULT_TAG = { '13OCT': '隔声', 'OCT': '噪声级' };

function ensureTagFilterDefault() {
  if (state.tagFilter === undefined || state.tagFilter === null) state.tagFilter = '';
  return state.tagFilter;
}

function updateTagBar() {
  const bar = $('#tagBar');
  if (!bar) return;
  if (!isEditMode()) { bar.hidden = true; return; }
  bar.hidden = false;
  const tc = state.tagCounts || {};
  const def = DEFAULT_TAG[state.cat] || '';
  const total = (tc['噪声级'] || 0) + (tc['隔声'] || 0) + (tc['未标记'] || 0);
  $$('#tagBar .tagchip').forEach(btn => {
    const v = btn.dataset.tag || '';
    btn.classList.toggle('on', state.tagFilter === v);
    const n = v ? (tc[v] || 0) : total;
    btn.querySelector('b').textContent = n;
  });
  const hint = $('#tagHint');
  if (hint) {
    hint.textContent = state.tagFilter
      ? `当前只显示「${state.tagFilter}」，共 ${tc[state.tagFilter] || 0} 组`
      : `当前显示全部 ${total} 组（本分类常用：${def}）`;
  }
}

function setTagFilter(v) {
  state.tagFilter = v;
  updateTagBar();
  loadTable(state.cat);
}

/* ============================================================ 模块模式 */
/* 两个模块共用同一套界面，唯一差别是「能不能改」 */
function isEditMode() {
  return document.body.classList.contains('view-org');
}

function switchModule(mod) {
  $$('.mod').forEach(b => b.classList.toggle('active', b.dataset.mod === mod));

  // 报告生成是独立视图
  if (mod === 'report_noise' || mod === 'report_insul') {
    const isNoise = mod === 'report_noise';
    rp.kind = isNoise ? '噪声级' : '隔声';
    document.body.classList.add('view-report');
    document.body.classList.remove('view-org');
    $('#viewRaw').hidden = true;
    $('#viewReport').hidden = false;
    $('#tbBadge').textContent = isNoise ? '报告·噪声级' : '报告·隔声';
    const bar0 = $('#modeBar');
    bar0.classList.remove('editable');
    $('#mbText').textContent = isNoise
      ? '报告·噪声级 · 只列数据管理中标为「噪声级」的 OCT 测量，输出 NC 评价值'
      : '报告·隔声 · 只列数据管理中标为「隔声」的 1/3OCT 测量，输出 NIC 评价值';
    $('#mbIcon').innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12"><rect x="2.5" y="1.5" width="8" height="13" rx="1" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M4.5 5h4M4.5 8h4M4.5 11h2" stroke="currentColor" stroke-width="1.2"/><path d="M9 13l2-2.5 1.6 1.6 2-2.6" stroke="currentColor" stroke-width="1.3" fill="none"/></svg>';
    $('#mbActions').innerHTML = '';
    applyReportKind();
    loadReport();
    return;
  }

  document.body.classList.remove('view-report');
  $('#viewReport').hidden = true;
  $('#viewRaw').hidden = false;

  const edit = mod === 'organize';
  document.body.classList.toggle('view-org', edit);

  $('#tbBadge').textContent = edit ? '数据整理' : '原始数据';
  const st = $('#sideTag');
  if (st) {
    st.textContent = edit ? '可整理' : '只读';
    st.classList.toggle('org', edit);
  }
  const bar = $('#modeBar');
  bar.classList.toggle('editable', edit);
  $('#mbIcon').innerHTML = edit
    ? '<svg viewBox="0 0 16 16" width="12" height="12"><path d="M11.5 2.5l2 2-8 8H3.5v-2l8-8z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>'
    : '<svg viewBox="0 0 16 16" width="12" height="12"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M5.5 7V5a2.5 2.5 0 015 0v2" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';
  $('#mbText').textContent = edit
    ? '数据整理 · 可修改测点名、日期、时间与频带值；原始 AWA 文件始终不被改写'
    : '原始数据只读 · 可查看、排序、筛选与导出；如需修改请切换到【数据整理】';
  $('#mbActions').innerHTML = '';

  // 缩放一下让布局重算（表格多了/少了勾选列）
  if (!edit) {
    state.picked.clear();
    $('#batchDrawer').hidden = true;
    $('#btnBatch').style.display = '';
  } else {
    $('#btnBatch').style.display = '';
  }
  // 两种视图的列不同（原始看全部频带，整理只看关注区间），需重新取表
  if (!state.cleared) loadTable(state.cat);
  updateBatchUI();
}

/* ============================================================ 报告生成 */
const rp = {
  items: [],
  groups: [],
  rows: [],
  cur: -1,
  detail: null,
  kind: '隔声',        // 当前模块：隔声 / 噪声级
};

async function loadReport() {
  try {
    const j = await api('/api/report/plan');
    const all = j.items || [];
    // 只保留本模块对应类型的行（清单是同一份，按类型分流展示）
    rp.items = all.filter(it => (it.kind || '隔声') === rp.kind);
    rp._allItems = all;
    rp.groups = j.groups || [];
    const c = await api('/api/report/compute');
    const rows = c.rows || [];
    // 计算结果与 all 同序，按同样规则过滤
    rp.rows = rows.filter((r, i) => ((all[i] || {}).kind || '隔声') === rp.kind);
    rp.cur = -1;
    fillGroupSelects();
    renderReportTable();
    if (rp.items.length) selectReportRow(0);
    else clearReportDetail();
  } catch (e) {
    toast('读取报告清单失败：' + e.message, 3200);
  }
}

/* 按模块类型调整界面：噪声级只看单文件，隔声看内外两侧 */
function applyReportKind() {
  const isNoise = rp.kind === '噪声级';

  // 按 data-kind 标记的字段只在该类型下显示
  $$('.rp-field[data-kind]').forEach(el => {
    el.hidden = el.dataset.kind !== rp.kind;
  });
  // 隔声才需要内/外侧
  const innerField = $('#rpInner').closest('.rp-field');
  const outerField = $('#rpOuter').closest('.rp-field');
  if (innerField) innerField.hidden = isNoise;
  if (outerField) outerField.hidden = isNoise;

  // 噪声级只需选文件，复用「内侧」下拉的选项，但标签改成「文件」
  const innerLabel = innerField ? innerField.querySelector('label') : null;
  if (innerLabel) innerLabel.textContent = isNoise ? '文件' : '内侧';

  // 两张表切换
  $('#rpNoiseTbl').hidden = !isNoise;
  $('#rpTbl').hidden = isNoise;

  const kd = $('#rpKind');
  kd.value = rp.kind;
  kd.disabled = true;

  document.body.classList.toggle('rp-noise', isNoise);
  document.body.classList.toggle('rp-insul', !isNoise);
  $('#rpTitleLabel').textContent = isNoise ? '报告生成 · 噪声级' : '报告生成 · 隔声';
  $('#rpListHead').textContent = isNoise ? '噪声级实测（倍频带）' : '隔声测点';
  const hint = $('#rpHint');
  if (hint) {
    hint.textContent = isNoise
      ? '列 = 房间 × 工况，行 = 8 个倍频带，末两行为 NC 实测 / 设计'
      : '一测点一行，填内侧/外侧文件与设计值，右下预览 NIC 曲线';
  }
}

function fillGroupSelects() {
  const opts = ['<option value="">（未选）</option>'];
  rp.groups.forEach(g => {
    opts.push(`<option value="${g.f13}|${g.f11}">${g.label}</option>`);
  });
  const html = opts.join('');
  $('#rpInner').innerHTML = html;
  $('#rpOuter').innerHTML = html;
}

function parseSel(val) {
  if (!val) return ['', ''];
  const [a, b] = val.split('|');
  return [a || '', b || ''];
}

function renderReportTable() {
  if (rp.kind === '噪声级') { renderNoiseTable(); return; }
  const tb = $('#rpTbl tbody');
  tb.innerHTML = '';
  const frag = document.createDocumentFragment();
  rp.items.forEach((it, i) => {
    const row = rp.rows[i] || {};
    const tr = document.createElement('tr');
    if (i === rp.cur) tr.classList.add('sel');

    const isNoise = rp.kind === '噪声级';
    const cells = [
      [String(i + 1), 'c'],
      [it.name || '—', ''],
      [it.kind, 'c'],
      [isNoise ? (it.file || '—') : (it.inner || '—'), ''],
      [isNoise ? '' : (it.outer || '—'), ''],
      [row.value || (row.ok ? '—' : '缺数据'), 'c'],
    ];
    cells.forEach(([v, cls]) => {
      const td = document.createElement('td');
      td.textContent = v;
      if (cls) td.className = cls;
      td.title = v;
      tr.appendChild(td);
    });
    const tdJ = document.createElement('td');
    tdJ.className = 'c';
    if (row.passFlag) {
      tdJ.textContent = row.passFlag;
      tdJ.classList.add(row.passFlag === '满足' ? 'rp-pass' : 'rp-fail');
    } else {
      tdJ.textContent = '—';
    }
    tr.appendChild(tdJ);

    tr.addEventListener('click', () => selectReportRow(i));
    frag.appendChild(tr);
  });
  tb.appendChild(frag);

  $('#rpCount').textContent =
    `${rp.items.length} 条 · ${rp.rows.filter(r => r.ok).length} 条有效`;
  const empty = $('#rpEmpty');
  empty.hidden = rp.items.length > 0;
  empty.textContent = '清单是空的，点【添加测点】或【按时序配对】开始';
}

/* 噪声级交叉表：行=8 倍频带，列=房间×工况，末两行 NC 实测/设计 */
const NOISE_BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000];

function fmtHz(hz) {
  return hz >= 1000 ? `${hz / 1000}k` : String(hz);
}

function renderNoiseTable() {
  const thead = $('#rpNoiseTbl thead');
  const tbody = $('#rpNoiseTbl tbody');
  thead.innerHTML = '';
  tbody.innerHTML = '';

  const cols = rp.items;
  if (!cols.length) {
    $('#rpEmpty').hidden = false;
    $('#rpEmpty').textContent = '还没有噪声级测点。先在【数据整理】把 OCT 数据标为「噪声级」，再点【按时序配对】';
    return;
  }
  $('#rpEmpty').hidden = true;

  // 第一行：房间（相邻同房间合并）
  const tr1 = document.createElement('tr');
  const corner = document.createElement('th');
  corner.rowSpan = 2;
  corner.className = 'corner';
  corner.innerHTML = '倍频带<br>中心频率<br>(Hz)';
  tr1.appendChild(corner);

  let i = 0;
  while (i < cols.length) {
    const room = (cols[i].room || cols[i].name || '未命名').trim();
    let j = i;
    while (j + 1 < cols.length &&
           (cols[j + 1].room || cols[j + 1].name || '未命名').trim() === room) j++;
    const th = document.createElement('th');
    th.textContent = room;
    th.colSpan = j - i + 1;
    th.className = 'room';
    tr1.appendChild(th);
    i = j + 1;
  }
  thead.appendChild(tr1);

  // 第二行：工况
  const tr2 = document.createElement('tr');
  cols.forEach((it, k) => {
    const th = document.createElement('th');
    th.textContent = it.cond || `测点${k + 1}`;
    th.className = 'cond';
    tr2.appendChild(th);
  });
  thead.appendChild(tr2);

  // 8 个倍频带 × 各列
  NOISE_BANDS.forEach((hz, bi) => {
    const tr = document.createElement('tr');
    const th = document.createElement('td');
    th.className = 'hz';
    th.textContent = fmtHz(hz);
    tr.appendChild(th);
    cols.forEach((it, k) => {
      const row = rp.rows[k] || {};
      const bands = row.bands || [];
      const td = document.createElement('td');
      const v = bands[bi];
      td.textContent = (v == null) ? '—' : Number(v).toFixed(1);
      td.className = 'num';
      td.dataset.col = k;
      td.dataset.band = bi;
      td.title = `${it.room || ''} ${it.cond || ''}　${fmtHz(hz)}Hz`;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  // NC 实测 / NC 设计
  [['NC\n（实测值）', r => r.value || '—'],
   ['NC\n（设计值）', r => (rp.items[0] && null) || r.design || '—']]
    .forEach(([label, getter], ri) => {
      const tr = document.createElement('tr');
      tr.className = 'ncrow';
      const th = document.createElement('td');
      th.className = 'hz';
      th.innerHTML = label.replace('\n', '<br>');
      tr.appendChild(th);
      cols.forEach((it, k) => {
        const row = rp.rows[k] || {};
        const td = document.createElement('td');
        if (ri === 0) {
          td.textContent = row.value || '—';
          td.className = 'num nc';
        } else {
          td.textContent = it.design || '/';
          td.className = 'num';
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
}

function selectReportRow(i) {
  rp.cur = i;
  const it = rp.items[i];
  if (!it) return;

  $('#rpName').value = it.name || '';
  $('#rpKind').value = it.kind || '隔声';
  $('#rpTableNo').value = it.table || '';
  $('#rpDesign').value = it.design || '';
  $('#rpRoom').value = it.room || '';
  $('#rpCond').value = it.cond || '';
  const fname = rp.kind === '噪声级' ? (it.file || it.inner || '') : (it.inner || '');
  const [f13, f11] = [fname, ''];
  $('#rpInner').value = `${f13}|${f11}`;
  $('#rpOuter').value = `${it.outer || ''}|${it.outer ? '' : ''}`;

  // 外侧：按 outer 文件名反查选项
  const optsOuter = [...$('#rpOuter').options];
  const hit = optsOuter.find(o => {
    const [a, b] = parseSel(o.value);
    return a === it.outer || b === it.outer;
  });
  if (hit) $('#rpOuter').value = hit.value;

  const optsInner = [...$('#rpInner').options];
  const hitIn = optsInner.find(o => {
    const [a, b] = parseSel(o.value);
    return a === it.inner || b === it.inner;
  });
  if (hitIn) $('#rpInner').value = hitIn.value;

  renderReportTable();
  if (rp.kind === '隔声') loadReportDetail(i);
}

function clearReportDetail() {
  rp.detail = null;
  $('#rpRating').textContent = '—';
  $('#rpJudge').textContent = '';
  $('#rpBandTbl tbody').innerHTML = '';
  $('#rpChartTitle').textContent = '选择左侧测点查看曲线';
  const cv = $('#rpCanvas');
  const g = cv.getContext('2d');
  g.clearRect(0, 0, cv.width, cv.height);
  g.fillStyle = '#f7fafd';
  g.fillRect(0, 0, cv.width, cv.height);
}

async function loadReportDetail(i) {
  // 页面上是过滤后的行；服务端清单是完整的，需换算原始下标
  const target = rp.items[i];
  const all = rp._allItems || rp.items;
  const realIdx = target ? all.indexOf(target) : -1;
  if (realIdx < 0) return;
  try {
    const d = await api('/api/report/detail?i=' + realIdx);
    rp.detail = d;
    $('#rpRating').textContent = d.value || (d.dataOk ? '—' : '缺数据');
    const judge = $('#rpJudge');
    judge.textContent = d.passFlag ? `判定：${d.passFlag}` : '';
    judge.style.color = d.passFlag === '满足' ? '#2c6b48'
                       : d.passFlag === '不满足' ? '#c0392b' : '';
    renderBandTable(d);
    $('#rpChartTitle').textContent =
      `${d.item.name || ''}　${d.kind === '噪声级' ? 'NC 评价' : '声压级差 NR'}`;
    drawReportChart(d);
  } catch (e) {
    toast('读取明细失败：' + e.message, 3000);
  }
}

function renderBandTable(d) {
  const tb = $('#rpBandTbl tbody');
  tb.innerHTML = '';
  const bands = d.bands || [];
  if (!bands.length) return;

  if (d.kind === '噪声级') {
    // 单列：8 个倍频程声压级
    bands.forEach(b => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td class="lbl">${b.label}</td><td>${b.value ?? '—'}</td>
                      <td class="lbl"></td><td></td>`;
      tb.appendChild(tr);
    });
    return;
  }

  // 隔声：两栏各 9 行
  const half = Math.ceil(bands.length / 2);
  for (let i = 0; i < half; i++) {
    const a = bands[i];
    const b = bands[i + half];
    const tr = document.createElement('tr');
    if (a && a.deficit > 0) tr.classList.add('deficit');
    const cell = (x) => x
      ? `<td class="lbl">${x.label}</td><td>${x.value ?? '—'}</td>`
      : '<td class="lbl"></td><td></td>';
    tr.innerHTML = cell(a) + cell(b);
    if (b && b.deficit > 0) tr.classList.add('deficit');
    tb.appendChild(tr);
  }
}

/* NIC 曲线：横轴频带（对数），纵轴 dB */
function drawReportChart(d) {
  const cv = $('#rpCanvas');
  const rect = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const W = Math.max(rect.width, 320);
  const H = Math.max(rect.height, 170);
  cv.width = W * dpr;
  cv.height = H * dpr;
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  g.fillStyle = '#fff';
  g.fillRect(0, 0, W, H);

  const bands = (d.bands || []).filter(b => b.value != null);
  if (!bands.length) {
    g.fillStyle = '#9aa8b6';
    g.font = '12px "Microsoft YaHei"';
    g.textAlign = 'center';
    g.fillText('该测点没有可用的频带数据', W / 2, H / 2);
    return;
  }

  const pad = { l: 40, r: 12, t: 14, b: 26 };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;

  const vals = bands.map(b => b.value);
  (d.kind === '隔声' ? bands : []).forEach(b => {
    if (b.contour != null) vals.push(b.contour);
  });
  let lo = Math.floor(Math.min(...vals) / 5) * 5 - 5;
  let hi = Math.ceil(Math.max(...vals) / 5) * 5 + 5;
  if (hi - lo < 20) { hi = lo + 20; }

  const n = bands.length;
  const X = i => pad.l + (n > 1 ? iw * i / (n - 1) : iw / 2);
  const Y = v => pad.t + ih - (v - lo) / (hi - lo) * ih;

  // 网格
  g.strokeStyle = '#eef3f8';
  g.lineWidth = 1;
  const stepY = Math.max(5, Math.round((hi - lo) / 6 / 5) * 5);
  for (let v = lo; v <= hi + 1e-6; v += stepY) {
    g.beginPath(); g.moveTo(pad.l, Y(v)); g.lineTo(W - pad.r, Y(v)); g.stroke();
    g.fillStyle = '#8b9aa9';
    g.font = '10px Consolas';
    g.textAlign = 'right';
    g.fillText(String(v), pad.l - 5, Y(v) + 3);
  }

  // 频带标签
  g.fillStyle = '#8b9aa9';
  g.font = '10px Consolas';
  g.textAlign = 'center';
  bands.forEach((b, i) => {
    if (n > 12 && i % 2 === 1) return;
    g.fillText(b.label, X(i), H - pad.b + 13);
  });

  // 扣分频带阴影
  if (d.kind === '隔声') {
    bands.forEach((b, i) => {
      if (!b.deficit || b.deficit <= 0 || b.contour == null) return;
      const w = Math.max(iw / Math.max(n - 1, 1) * 0.7, 6);
      g.fillStyle = 'rgba(240,170,140,.28)';
      g.fillRect(X(i) - w / 2, Y(b.contour), w, Y(b.value) - Y(b.contour));
    });

    // 轮廓线
    g.strokeStyle = '#d0552f';
    g.lineWidth = 1.6;
    g.setLineDash([5, 4]);
    g.beginPath();
    let started = false;
    bands.forEach((b, i) => {
      if (b.contour == null) return;
      const x = X(i), y = Y(b.contour);
      if (!started) { g.moveTo(x, y); started = true; } else g.lineTo(x, y);
    });
    g.stroke();
    g.setLineDash([]);
  }

  // 实测曲线
  g.strokeStyle = '#2b7fc4';
  g.lineWidth = 2;
  g.beginPath();
  bands.forEach((b, i) => {
    const x = X(i), y = Y(b.value);
    if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
  });
  g.stroke();

  // 数据点
  g.fillStyle = '#2b7fc4';
  bands.forEach((b, i) => {
    g.beginPath();
    g.arc(X(i), Y(b.value), 2.2, 0, Math.PI * 2);
    g.fill();
  });

  // 右下角评价值
  if (d.value) {
    g.fillStyle = '#1b5f98';
    g.font = 'bold 13px "Microsoft YaHei"';
    g.textAlign = 'right';
    g.fillText(d.value, W - pad.r, H - 4);
  }
}

/* ---------- 清单编辑 ---------- */
function collectItems() {
  // 保存要写完整清单（两种类型都在里面），否则会丢掉另一个模块的行
  const all = rp._allItems || rp.items;
  return all.map((it, i) => ({ ...it, order: i + 1 }));
}

async function saveReportPlan(quiet) {
  try {
    await postJSON('/api/report/plan', { items: collectItems() });
    if (!quiet) toast('清单已保存', 1600);
    return true;
  } catch (e) {
    toast('保存失败：' + e.message, 3000);
    return false;
  }
}

function applyFormToItem() {
  const it = rp.items[rp.cur];
  if (!it) return;
  it.name = $('#rpName').value.trim();
  it.kind = rp.kind;
  it.table = $('#rpTableNo').value.trim();
  it.design = $('#rpDesign').value.trim();
  it.room = ($('#rpRoom').value || '').trim();
  it.cond = ($('#rpCond').value || '').trim();

  if (rp.kind === '噪声级') {
    // 噪声级只有单文件
    const [f13, f11] = parseSel($('#rpInner').value);
    it.file = f11 || f13;          // 优先 OCT 文件
    it.inner = it.file;
    it.outer = '';
  } else {
    const [inA, inB] = parseSel($('#rpInner').value);
    it.inner = inA || inB;
    const [outA, outB] = parseSel($('#rpOuter').value);
    it.outer = outA || outB;
  }
}

async function refreshReport() {
  const c = await api('/api/report/compute');
  rp.rows = c.rows || [];
  renderReportTable();
  if (rp.cur >= 0) loadReportDetail(rp.cur);
}

['#rpName', '#rpTableNo', '#rpDesign', '#rpRoom', '#rpCond'].forEach(sel => {
  $(sel).addEventListener('change', async () => {
    applyFormToItem();
    await saveReportPlan(true);
    await refreshReport();
  });
});
$('#rpKind').addEventListener('change', async () => {
  applyFormToItem();
  await saveReportPlan(true);
  await refreshReport();
});
['#rpInner', '#rpOuter'].forEach(sel => {
  $(sel).addEventListener('change', async () => {
    applyFormToItem();
    await saveReportPlan(true);
    await refreshReport();
  });
});

$('#rpAdd').addEventListener('click', async () => {
  const all = rp._allItems || [];
  all.push({
    name: '', kind: rp.kind, table: '', order: all.length + 1,
    file: '', inner: '', outer: '', design: '',
    room: ($('#rpRoom').value || '').trim(),
    cond: '',
  });
  rp._allItems = all;
  await postJSON('/api/report/plan', {
    items: all.map((it, i) => ({ ...it, order: i + 1 })),
  });
  await loadReport();
  rp.cur = rp.items.length - 1;
  if (rp.cur >= 0) selectReportRow(rp.cur);
});

$('#rpDel').addEventListener('click', async () => {
  if (rp.cur < 0 || rp.cur >= rp.items.length) return toast('先选中一行', 2000);
  rp.items.splice(rp.cur, 1);
  await saveReportPlan(true);
  rp.cur = Math.min(rp.cur, rp.items.length - 1);
  await refreshReport();
  if (rp.cur >= 0) selectReportRow(rp.cur);
  else clearReportDetail();
});

$('#rpPair').addEventListener('click', async () => {
  if (!confirm('按测量时序重新生成配对草稿？\n会覆盖当前清单。')) return;
  rp.items = [];
  try {
    const j = await api('/api/report/plan?suggest=1');
    // 强制重建：先删空再让服务端重新建议
    await postJSON('/api/report/plan', { items: [] });
    const k = await api('/api/report/plan');
    rp.items = k.items || [];
    rp.groups = k.groups || rp.groups;
    await saveReportPlan(true);
    await loadReport();
    toast(`已生成 ${rp.items.length} 条配对草稿，请核对内侧/外侧`, 3000);
  } catch (e) {
    toast('生成失败：' + e.message, 3000);
  }
});

$('#rpSave').addEventListener('click', () => saveReportPlan(false));

$('#rpExport').addEventListener('click', async () => {
  const project = $('#rpProject').value.trim() || '报告';
  try {
    const j = await postJSON('/api/report/export', {
      meta: { project },
    });
    const a = document.createElement('a');
    a.href = j.url;
    a.download = j.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(`已生成 ${j.rows} 行报告：${j.name}（${j.okCount} 行有效）`, 3600);
  } catch (e) {
    toast('生成失败：' + e.message, 3200);
  }
});

window.addEventListener('resize', () => {
  if (rp.detail && !$('#viewReport').hidden) drawReportChart(rp.detail);
});

/* ============================================================ 批量整理 */
function updateBatchUI() {
  const n = state.picked.size;
  const btn = $('#btnBatch');
  if (btn) {
    btn.querySelector('span').textContent = n ? `批量整理 (${n})` : '批量整理';
    btn.classList.toggle('primary', n > 0);
  }
  const sub = $('#bdSub');
  if (sub) {
    sub.textContent = n
      ? `已选 ${n} 个测量组 · 将同步到这些组内的全部文件`
      : '勾选下方行，或使用右侧快捷选择';
  }
  updateBdPreview();
}

function allGroupsInView() {
  const seen = new Map();
  visibleRows().forEach(r => {
    const g = groupIdOf(r[1]);
    if (!seen.has(g)) seen.set(g, r[1]);
  });
  return seen;
}

function pickedFiles() {
  const out = [];
  const seen = new Set();
  visibleRows().forEach(r => {
    const g = groupIdOf(r[1]);
    if (state.picked.has(g) && !seen.has(g)) { seen.add(g); out.push(r[1]); }
  });
  return out;
}

function tplValue(tpl, gid, idx, total) {
  return String(tpl).replace(/\{gid\}/g, gid)
                    .replace(/\{i\}/g, idx)
                    .replace(/\{n\}/g, total);
}

function updateBdPreview() {
  const box = $('#bdPreview');
  if (!box) return;
  const tpl = ($('#bdNameTpl')?.value || '').trim();
  const files = pickedFiles();
  if (!files.length) {
    box.textContent = tpl ? '预览：请先勾选数据行' : '预览：—';
    box.classList.remove('has');
    return;
  }
  const gids = [...new Set(files.map(f => groupIdOf(f)))];
  if (!tpl) {
    box.textContent = `已选 ${gids.length} 组 / ${files.length} 行`;
    box.classList.remove('has');
    return;
  }
  const demo = gids.slice(0, 3).map((g, i) => tplValue(tpl, g, i + 1, gids.length));
  box.textContent = '预览：' + demo.join('，') +
    (gids.length > 3 ? ` …（共 ${gids.length} 组）` : '');
  box.classList.add('has');
}

async function applyBatch(path, value, label) {
  const files = pickedFiles();
  if (!files.length) return toast('请先勾选要整理的数据行', 2600);
  if (value == null || String(value).trim() === '') return toast('请填写要应用的' + label);

  try {
    const j = await postJSON('/api/batch', { files, path, value, group: true });
    // 本地同步显示
    const shown = path === 'point' ? null : String(value);
    const gids = [...new Set(files.map(f => groupIdOf(f)))];
    const tplUsed = path === 'point' ? String(value) : null;
    state.rows.forEach(r => {
      const gi = gids.indexOf(groupIdOf(r[1]));
      if (gi < 0) return;
      if (path === 'point') {
        const col = state.headers.findIndex(h => h[0] === '测点名');
        if (col >= 0) r[col] = tplValue(tplUsed, groupIdOf(r[1]), gi + 1, gids.length);
      } else if (path === 'date') {
        const col = state.headers.findIndex(h => h[0] === '测试日期');
        if (col >= 0) r[col] = shown;
      } else if (path === 'time') {
        const col = state.headers.findIndex(h => h[0] === '测试时间');
        if (col >= 0) r[col] = shown;
      }
    });
    state.cache.clear();
    state.detail = null;
    state.editCount = Math.max(state.editCount || 0, j.edits || 0);
    updateEditBadge();
    renderTable();
    if (state.selectedFile) await loadDetail(state.selectedFile);
    toast(`${label}：已更新 ${j.groups} 组 / ${j.written} 个文件（原始 AWA 未改动）`, 2800);
  } catch (e) {
    toast('应用失败：' + e.message, 3200);
  }
}

/* 快捷选择 */
function selectBy(pred, label) {
  state.picked.clear();
  visibleRows().forEach(r => {
    const g = groupIdOf(r[1]);
    if (pred(r, g)) state.picked.add(g);
  });
  renderTable();
  updateBatchUI();
  toast(`已选中 ${state.picked.size} 组（${label}）`, 1800);
}

function dupPointSet() {
  const cnt = {};
  const col = state.headers.findIndex(h => h[0] === '测点名');
  if (col < 0) return new Set();
  state.rows.forEach(r => { if (r[col]) cnt[r[col]] = (cnt[r[col]] || 0) + 1; });
  return new Set(Object.keys(cnt).filter(k => cnt[k] > 1));
}

$('#btnBatch').addEventListener('click', () => {
  if (!isEditMode()) {
    toast('原始数据只读，请切换到【数据整理】后再批量操作', 2800);
    return;
  }
  const d = $('#batchDrawer');
  d.hidden = !d.hidden;
  updateBatchUI();
});

$('#bdClose').addEventListener('click', () => { $('#batchDrawer').hidden = true; });

$('#bdSelAll').addEventListener('click', () => selectBy(() => true, '全部'));
$('#bdSelNone').addEventListener('click', () => {
  state.picked.clear(); renderTable(); updateBatchUI();
});
$('#bdSelUnnamed').addEventListener('click', () => {
  const col = state.headers.findIndex(h => h[0] === '测点名');
  selectBy(r => !r[col] || /^DATA_\d+$/i.test(r[col]), '未命名');
});
$('#bdSelDup').addEventListener('click', () => {
  const col = state.headers.findIndex(h => h[0] === '测点名');
  const dup = dupPointSet();
  selectBy(r => dup.has(r[col]), '重复点名');
});

$('#bdNameTpl').addEventListener('input', updateBdPreview);
$('#bdApplyName').addEventListener('click', () => {
  const tpl = ($('#bdNameTpl').value || '').trim();
  if (!tpl) return toast('请填写命名规则，例如 三层-会议室-{i}');
  applyBatch('point', tpl, '批量命名');
});
$('#bdApplyDate').addEventListener('click', () =>
  applyBatch('date', $('#bdDate').value, '批量改日期'));
$('#bdApplyTime').addEventListener('click', () =>
  applyBatch('time', $('#bdTime').value, '批量改测试时间'));

$('#bdExport').addEventListener('click', () => {
  const files = pickedFiles();
  if (!files.length) return toast('请先勾选要导出的数据行', 2400);
  const url = '/api/export?cat=' + encodeURIComponent(state.cat) +
              '&files=' + encodeURIComponent(files.join(','));
  const a = document.createElement('a');
  a.href = url; a.download = '';
  document.body.appendChild(a); a.click(); a.remove();
  toast(`正在导出 ${files.length} 行（含整理后的值）`, 2400);
});

$('#bdRevert').addEventListener('click', async () => {
  if (!confirm('确定撤销本目录全部整理结果吗？\n原始 AWA 文件始终不受影响。')) return;
  try {
    const j = await postJSON('/api/revert', {});
    state.cache.clear();
    state.detail = null;
    state.editCount = 0;
    state.editedCells = new Set();
    updateEditBadge();
    const data = await api('/api/table?cat=' + encodeURIComponent(state.cat));
    state.rows = data.rows;
    state.fields = data.fields || [];
    renderTable();
    if (state.selectedFile) await loadDetail(state.selectedFile);
    toast(`已撤销 ${j.reverted} 个文件的整理`, 2200);
  } catch (e) { toast('撤销失败：' + e.message, 3000); }
});

/* ============================================================ 启动 */
/* 心跳：桌面启动器靠它判断窗口是否还开着；页面关掉即停止 */
function startHeartbeat() {
  const beat = () => {
    if (document.visibilityState === 'hidden') return;
    fetch('/api/ping', { cache: 'no-store' }).catch(() => {});
  };
  beat();
  setInterval(beat, 3000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') beat();
  });
}

(function boot() {
  drawEmptyGrid();
  startHeartbeat();
  // 首次进入自动读一次，省得用户先点按钮；点击【数据读取】可随时重扫
  scan(null);
})();
