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
  else games.appendChild(table(
    ['game_id', '完整', '步數', '打完', '原因', '介入', 'UI 成功/動作', 'p95 (ms)'],
    data.games.map((g) => [g.game_id, g.complete, g.steps, g.finished, g.reason, g.interventions,
      g.ui_actions === null || g.ui_actions === undefined ? '-' : g.ui_success + '/' + g.ui_actions,
      g.latency_p95_ms === null || g.latency_p95_ms === undefined ? '-' : Math.round(g.latency_p95_ms)]),
  ));
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

load();
setInterval(load, 3000);
</script>
</body>
</html>
"""