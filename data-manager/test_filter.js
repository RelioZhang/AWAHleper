/* 纯逻辑单测：筛选匹配 + 排序（不依赖 DOM） */
'use strict';

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

function matchCond(val, cond) {
  const want = cond.val;
  const raw = String(val ?? '').trim();
  const isBlank = raw === '' || raw === '—';
  if (cond.op === 'empty') return isBlank;
  if (cond.op === 'notEmpty') return !isBlank;

  const relational = ['gt', 'ge', 'lt', 'le', 'between'].includes(cond.op);
  if (relational && isBlank) return false;

  const a = toNum(raw);
  const b = toNum(want);
  const numeric = a !== null && b !== null;
  switch (cond.op) {
    case 'contains': return raw.toLowerCase().includes(String(want).toLowerCase());
    case 'notContain': return !raw.toLowerCase().includes(String(want).toLowerCase());
    case 'eq': return numeric ? a === b : raw.toLowerCase() === String(want).toLowerCase();
    case 'ne': return numeric ? a !== b : raw.toLowerCase() !== String(want).toLowerCase();
    case 'gt': return numeric ? a > b : raw > String(want);
    case 'ge': return numeric ? a >= b : raw >= String(want);
    case 'lt': return numeric ? a < b : raw < String(want);
    case 'le': return numeric ? a <= b : raw <= String(want);
    case 'between': {
      if (!numeric) return true;
      const c = toNum(cond.val2);
      if (c === null) return a >= b;
      const lo = Math.min(b, c), hi = Math.max(b, c);
      return a >= lo && a <= hi;
    }
    default: return true;
  }
}

function sortRows(rows, col, dir) {
  if (col < 0 || dir === 0) return rows;
  const dec = rows.map((r, i) => ({ r, i }));
  dec.sort((x, y) => {
    const ra = String(x.r[col] ?? '').trim();
    const rb = String(y.r[col] ?? '').trim();
    const ba = ra === '' || ra === '\u2014';
    const bb = rb === '' || rb === '\u2014';
    if (ba !== bb) return ba ? 1 : -1;
    const a = cellValue(x.r, col);
    const b = cellValue(y.r, col);
    let c;
    if (typeof a === 'number' && typeof b === 'number') c = a - b;
    else c = String(a).localeCompare(String(b), 'zh-CN', { numeric: true });
    return c !== 0 ? c * dir : x.i - y.i;
  });
  return dec.map(d => d.r);
}

/* ---------------- 断言 ---------------- */
let pass = 0, fail = 0;
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { pass++; } else { fail++; console.log(`✗ ${name}\n   期望 ${JSON.stringify(want)}\n   实际 ${JSON.stringify(got)}`); }
}

const rows = [
  ['1', '1_3_0001.AWA', 'DATA_0641', '2026-11-02', '13:58:54', '00h00m10s', '47.9'],
  ['2', '1_3_0002.AWA', 'DATA_0642', '2026-11-02', '14:05:00', '00h00m10s', '52.3'],
  ['3', '1_3_0003.AWA', '会议室', '2026-11-03', '09:12:00', '00h00m10s', '38.1'],
  ['4', '1_3_0004.AWA', '', '2026-11-03', '10:00:00', '00h00m10s', '—'],
];

/* 数值比较 */
eq('大于50', rows.filter(r => matchCond(r[6], { op: 'gt', val: '50' })).map(r => r[0]), ['2']);
eq('介于40和50', rows.filter(r => matchCond(r[6], { op: 'between', val: '40', val2: '50' })).map(r => r[0]), ['1']);
eq('介于50和40(反向)', rows.filter(r => matchCond(r[6], { op: 'between', val: '50', val2: '40' })).map(r => r[0]), ['1']);
eq('小于等于38.1', rows.filter(r => matchCond(r[6], { op: 'le', val: '38.1' })).map(r => r[0]), ['3']);

/* 空值 */
eq('为空', rows.filter(r => matchCond(r[2], { op: 'empty' })).map(r => r[0]), ['4']);
eq('不为空', rows.filter(r => matchCond(r[2], { op: 'notEmpty' })).map(r => r[0]), ['1', '2', '3']);
eq('破折号视为空', matchCond('—', { op: 'empty' }), true);

/* 文本 */
eq('包含DATA', rows.filter(r => matchCond(r[2], { op: 'contains', val: 'data' })).map(r => r[0]), ['1', '2']);
eq('不包含DATA', rows.filter(r => matchCond(r[2], { op: 'notContain', val: 'DATA' })).map(r => r[0]), ['3', '4']);
eq('等于会议室', rows.filter(r => matchCond(r[2], { op: 'eq', val: '会议室' })).map(r => r[0]), ['3']);

/* 多条件「并且」 */
const conds = [{ col: 6, op: 'gt', val: '40' }, { col: 3, op: 'eq', val: '2026-11-02' }];
eq('多条件', rows.filter(r => conds.every(c => matchCond(r[c.col], c))).map(r => r[0]), ['1', '2']);

/* 排序 */
eq('按声级升序', sortRows(rows, 6, 1).map(r => r[0]), ['3', '1', '2', '4']);
eq('按声级降序', sortRows(rows, 6, -1).map(r => r[0]), ['2', '1', '3', '4']);
eq('按文件名数值升序', sortRows(rows, 1, 1).map(r => r[0]), ['1', '2', '3', '4']);
eq('按日期升降', sortRows(rows, 3, 1).map(r => r[0]), ['1', '2', '3', '4']);
eq('取消排序保持原序', sortRows(rows, -1, 1).map(r => r[0]), ['1', '2', '3', '4']);

/* 排序稳定性 */
const same = [['1', 'b', '5'], ['2', 'a', '5'], ['3', 'c', '5']];
eq('相同值保持原序', sortRows(same, 2, 1).map(r => r[0]), ['1', '2', '3']);

console.log(`\n通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
