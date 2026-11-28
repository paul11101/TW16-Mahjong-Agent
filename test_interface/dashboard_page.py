"""儀表板首頁 HTML（W7，唯讀）。內容由 /api/dashboard 取得 JSON 後在前端渲染，全部用 textContent 寫入。"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>整合儀表板</title>
<style>
body { font-family: "Microsoft JhengHei", "Noto Sans TC", sans-serif; margin: 16px; background: #f4f1ea; color: #222; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 20px 0 8px; }
h3 { font-size: 15px; margin: 12px 0 6px; }
table { border-collapse: collapse; background: #fff; margin-bottom: 8px; }
th, td { border: 1px solid #ccc; padding: 4px 10px; font-size: 13px; text-align: left; }
th { background: #e8e3d6; }
.ok { color: #1b7f3a; font-weight: 700; }
.bad { color: #b3261e; font-weight: 700; }
.muted { color: #777; }
</style>
</head>
<body>
<h1>整合儀表板（唯讀）</h1>
<div class="muted" id="updated">載入中...</div>
<h2>批次報表</h2>
<div id="reports">載入中...</div>
<h2>最近對局</h2>
<div id="games">載入中...</div>
<h2>步驟與候選分數</h2>
<div id="steps" class="muted">點上面「最近對局」的一列</div>
<h2>策略比較</h2>
<div class="muted">A 當基準、B 當比較；請選同一組 seed 跑的兩批（只列最近 5 批）</div>
<div><select id="cmpA"></select> vs <select id="cmpB"></select> <button id="cmpBtn">比較</button></div>
<div id="cmp"></div>
<script>
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

function fmt(v, unit) {
  if (v === null || v === undefined) return '-';
  if (unit === 'ratio') return (v * 100).toFixed(2) + '%';
  if (unit === 'ms') return Math.round(v) + ' ms';
  return String(v);
}

function table(headers, rows) {
  const t = el('table');
  const head = el('tr');
  headers.forEach((h) => head.appendChild(el('th', null, h)));
  t.appendChild(head);
  rows.forEach((r) => {
    const tr = el('tr');
    r.forEach((c) => {
      const cls = (c && typeof c === 'object') ? c.cls : null;
      const text = (c && typeof c === 'object') ? c.text : c;
      tr.appendChild(el('td', cls, text === null || text === undefined ? '-' : String(text)));
    });
    t.appendChild(tr);
  });
  return t;
}

function status(ok) {
  if (ok === null || ok === undefined) return { text: '—', cls: 'muted' };
  return ok ? { text: '達標', cls: 'ok' } : { text: '未達標', cls: 'bad' };
}

function render(data) {
  fillSelects(data.reports.map((r) => r.batch_id));
  const box = $('reports');
  box.textContent = '';
  if (data.reports.length === 0) box.textContent = '還沒有批次報表（執行 python -m test_interface.run_batch）';
  data.reports.forEach((r) => {
    const req = r.requested_games === null || r.requested_games === undefined ? '' : '/' + r.requested_games;
    box.appendChild(el('h3', null, r.batch_id + '：' + r.games + req + ' 局，人工介入 ' + r.interventions + ' 次'));
    box.appendChild(table(
      ['指標', '實測', '目標', '結果', '備註'],
      r.targets.map((c) => [c.name, fmt(c.value, c.unit), c.target, status(c.ok), c.note]),
    ));
    box.appendChild(table(
      ['局', 'seed', '打完', '原因', '介入', 'UI 成功/動作', '多餘點擊'],
      r.rows.map((g) => [g.game_id, g.seed, g.finished, g.reason, g.interventions, g.ui_success + '/' + g.ui_actions, g.extra_clicks]),
    ));
  });

  const games = $('games');
  games.textContent = '';
  if (data.games.length === 0) games.textContent = '還沒有對局紀錄';
  else {
    const t = table(
      ['game_id', '完整', '步數', '打完', '原因', '介入', 'UI 成功/動作', 'p95 (ms)'],
      data.games.map((g) => [g.game_id, g.complete, g.steps, g.finished, g.reason, g.interventions,
        g.ui_actions === null || g.ui_actions === undefined ? '-' : g.ui_success + '/' + g.ui_actions,
        g.latency_p95_ms === null || g.latency_p95_ms === undefined ? '-' : Math.round(g.latency_p95_ms)]),
    );
    t.querySelectorAll('tr').forEach((row, i) => {
      if (i === 0) return;
      row.style.cursor = 'pointer';
      row.addEventListener('click', () => showSteps(row.firstChild.textContent));
    });
    games.appendChild(t);
  };
}

async function showSteps(gameId) {
  const box = $('steps');
  box.textContent = '載入中...';
  try {
    const response = await fetch('/api/game_record/' + encodeURIComponent(gameId));
    if (!response.ok) { box.textContent = '讀不到 ' + gameId; return; }
    const data = await response.json();
    box.textContent = '';
    box.appendChild(el('h3', null, gameId));
    box.appendChild(table(
      ['#', '階段', '策略', '動作', '結果', '錯誤', '候選分數（前 5）'],
      data.steps.map((s) => {
        const c = ((s.detail && s.detail.candidates) || []).slice()
          .sort((a, b) => b.score - a.score).slice(0, 5)
          .map((x) => x.id + '=' + Number(x.score).toFixed(3)).join('  ');
        return [s.index, s.phase, (s.detail && s.detail.strategy_version) || '-', s.action_id, s.skipped ? '略過' : (s.success ? '成功' : '失敗'), s.error, c || '-'];
      }),
    ));
  } catch (error) {
    box.textContent = '讀取失敗：' + error.message;
  }
}

async function load() {
  try {
    const response = await fetch('/api/dashboard');
    render(await response.json());
    $('updated').textContent = '更新時間：' + new Date().toLocaleTimeString() + '（每 3 秒自動更新）';
  } catch (error) {
    $('updated').textContent = '讀取失敗：' + error.message;
  }
}

function fillSelects(ids) {
  const key = ids.join('|');
  if (fillSelects.last === key) return;  // 每 3 秒自動更新，清單沒變就不要重建（會洗掉使用者的選擇）
  fillSelects.last = key;
  ['cmpA', 'cmpB'].forEach((id, k) => {
    const s = $(id);
    const keep = s.value;
    s.textContent = '';
    ids.forEach((i) => { const o = document.createElement('option'); o.value = i; o.textContent = i; s.appendChild(o); });
    if (keep && ids.includes(keep)) s.value = keep;
    else s.value = k === 0 ? (ids[1] || ids[0] || '') : (ids[0] || '');
  });
}

function fmtDiff(d, unit) {
  if (d === null || d === undefined) return '-';
  if (unit === 'ratio') return (d > 0 ? '+' : '') + (d * 100).toFixed(2) + ' pt';
  if (unit === 'ms') return (d > 0 ? '+' : '') + Math.round(d) + ' ms';
  return (d > 0 ? '+' : '') + d;
}

async function compare() {
  const box = $('cmp');
  const a = $('cmpA').value, b = $('cmpB').value;
  if (!a || !b) { box.textContent = '還沒有批次報表'; return; }
  try {
    const response = await fetch('/api/compare?a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b));
    if (!response.ok) { box.textContent = '讀不到批次報表'; return; }
    const data = await response.json();
    box.textContent = '';
    box.appendChild(el('h3', null, 'A：' + data.a.batch_id + '（' + (data.a.strategy_version || '策略未記錄') + '）　B：' +
      data.b.batch_id + '（' + (data.b.strategy_version || '策略未記錄') + '）'));
    box.appendChild(table(['指標', 'A', 'B', 'B − A'],
      data.rows.map((r) => [r.name, fmt(r.a, r.unit), fmt(r.b, r.unit), fmtDiff(r.diff, r.unit)])));
  } catch (error) {
    box.textContent = '讀取失敗：' + error.message;
  }
}
$('cmpBtn').addEventListener('click', compare);

load();
setInterval(load, 3000);
</script>
</body>
</html>
"""