"""測試介面首頁 HTML（W3 D1：加入四人牌桌顯示）。

純字串常數，不使用 f-string（CSS / JS 大量使用大括號）。
牌桌內容由 /api/table 取得 JSON 後在前端渲染，所有文字都用 textContent 寫入。

每張牌都是：<span class="tile ..." data-tile="牌ID" data-seat="座位">，
W3 D3 做「牌 → 座標映射」時可直接查詢 DOM 作為對照。
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>台灣16張麻將 Agent 測試介面</title>
<style>
body { font-family: "Microsoft JhengHei", "Noto Sans TC", sans-serif; margin: 16px; background: #f4f1ea; color: #222; }
h1 { margin: 0 0 8px; font-size: 22px; }
h2 { margin: 16px 0 8px; font-size: 17px; }
.toolbar button { padding: 6px 14px; margin-right: 6px; font-size: 14px; cursor: pointer; }

#table {
  display: grid;
  grid-template-columns: minmax(170px, 1fr) minmax(320px, 2fr) minmax(170px, 1fr);
  grid-template-areas:
    ". top ."
    "left center right"
    "bottom bottom bottom"
    "actions actions actions";
  gap: 10px;
  padding: 12px;
  border-radius: 12px;
  background: #1f6b4a;
  color: #fff;
}
.player { background: rgba(0, 0, 0, 0.22); border-radius: 8px; padding: 8px; }
.player.current { outline: 3px solid #ffd54a; }
.pos-top { grid-area: top; }
.pos-left { grid-area: left; }
.pos-right { grid-area: right; }
.pos-bottom { grid-area: bottom; }
.player-head { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 6px; }
.badge { font-size: 12px; padding: 1px 6px; border-radius: 10px; background: #555; }
.badge.dealer { background: #b3261e; }
.badge.turn { background: #ffd54a; color: #222; }
.badge.self { background: #1a5fb4; }
.muted { font-size: 12px; opacity: 0.8; }
.row { margin: 4px 0; display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.row-label { font-size: 12px; opacity: 0.8; margin-right: 4px; }
.meld { display: inline-flex; align-items: center; padding: 2px 4px; border-radius: 4px; background: rgba(255, 255, 255, 0.15); }
.meld-label { font-size: 12px; margin-right: 2px; }

.tile {
  display: inline-block;
  min-width: 26px;
  padding: 4px 2px;
  border: 1px solid #999;
  border-radius: 4px;
  background: #fffdf5;
  color: #222;
  font-size: 15px;
  line-height: 1.1;
  text-align: center;
  writing-mode: vertical-rl;
  text-orientation: upright;
}
.tile.wan { color: #b3261e; }
.tile.tong { color: #1a5fb4; }
.tile.tiao { color: #1b7f3a; }
.tile.honor { color: #222; font-weight: 700; }
.tile.flower { color: #c26a00; background: #fff3d6; }
.tile.back { background: #2f4f8f; border-color: #1c2f57; color: transparent; min-height: 34px; }
.tile.clicked { outline: 3px solid #ff5252; }
.river .tile { font-size: 13px; min-width: 22px; padding: 2px 1px; }

.center { grid-area: center; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 6px; text-align: center; }
.center .big { font-size: 20px; font-weight: 700; }

.actions { grid-area: actions; background: rgba(0, 0, 0, 0.22); border-radius: 8px; padding: 8px; }
button.reaction { padding: 6px 16px; font-size: 15px; border-radius: 6px; border: 1px solid #ccc; background: #fff; color: #222; }
button.reaction:disabled { opacity: 0.35; }
.chip { display: inline-block; padding: 3px 8px; margin: 2px; border-radius: 12px; background: rgba(255, 255, 255, 0.18); font-size: 13px; }
.chip.selected { background: #ffd54a; color: #222; font-weight: 700; }
.chip.choice { cursor: pointer; border: 1px solid rgba(255, 255, 255, 0.5); }
button.reaction, .chip { position: relative; }
button.reaction.clicked, .chip.clicked { outline: 3px solid #ff5252; }

pre { background: #fff; padding: 8px; border-radius: 6px; overflow-x: auto; }
#calib { position: fixed; left: 0; top: 0; width: 8px; height: 8px; background: #ff00ff; z-index: 9999; pointer-events: none; }
</style>
</head>

<body>
<div id="calib"></div>
<h1>台灣16張麻將 Agent 測試介面</h1>

<p>控制狀態：<strong id="controlState">-</strong>　<span id="gameInfo">載入中...</span></p>

<div class="toolbar">
  <button id="startButton">開始</button>
  <button id="pauseButton">暫停</button>
  <button id="resumeButton">繼續</button>
  <button id="stopButton">停止</button>
  <button id="resetButton">重設</button>
</div>

<h2>牌桌</h2>
<div id="table">載入中...</div>

<h2>系統訊息</h2>
<pre id="systemMessage">等待測試資料...</pre>

<script>
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

function tileClass(id) {
  if (id < 9) return 'wan';
  if (id < 18) return 'tong';
  if (id < 27) return 'tiao';
  if (id < 34) return 'honor';
  return 'flower';
}

function tileEl(t, seat, zone) {
  const e = el('span', 'tile ' + tileClass(t.id), t.name);
  e.dataset.tile = t.id;
  e.dataset.seat = seat;
  if (zone) e.dataset.zone = zone;
  return e;
}

function tileRow(label, tiles, seat, extraClass, zone) {
  const row = el('div', 'row ' + (extraClass || ''));
  row.appendChild(el('span', 'row-label', label));
  tiles.forEach((t) => row.appendChild(tileEl(t, seat, zone)));
  return row;
}

function renderPlayer(p) {
  const box = el('section', 'player pos-' + p.position + (p.is_current ? ' current' : ''));
  box.dataset.seat = p.seat_id;

  const head = el('div', 'player-head');
  head.appendChild(el('strong', null, p.wind + '家 玩家' + p.seat_id));
  if (p.is_self) head.appendChild(el('span', 'badge self', '我'));
  if (p.is_dealer) head.appendChild(el('span', 'badge dealer', '莊'));
  if (p.is_current) head.appendChild(el('span', 'badge turn', '輪到'));
  head.appendChild(el('span', 'muted', p.score + ' 分'));
  if (!p.is_self) head.appendChild(el('span', 'muted', '手牌 ' + p.hand_count + ' 張'));
  box.appendChild(head);

  const hand = el('div', 'row hand');
    if (p.hand) {
    p.hand.forEach((t) => {
      const e = tileEl(t, p.seat_id, 'hand');
      if (p.is_self) {
        e.style.cursor = 'pointer';
        e.addEventListener('click', async () => {
          e.classList.add('clicked');
          try {
            await fetch('/api/discard', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ tile: t.id, seat: p.seat_id }),
            });
          } catch (err) {}
        });
      }
      hand.appendChild(e);
    });
  } else {
    for (let i = 0; i < p.hand_count; i++) hand.appendChild(el('span', 'tile back'));
  }
  box.appendChild(hand);

  if (p.melds.length > 0) {
    const row = el('div', 'row');
    row.appendChild(el('span', 'row-label', '副露'));
    p.melds.forEach((m) => {
      const g = el('span', 'meld');
      g.appendChild(el('span', 'meld-label', m.label));
      m.tiles.forEach((t) => g.appendChild(tileEl(t, p.seat_id, 'meld')));
      row.appendChild(g);
    });
    box.appendChild(row);
  }

  if (p.flowers.length > 0) box.appendChild(tileRow('花牌', p.flowers, p.seat_id, ''));
  box.appendChild(tileRow('河牌', p.discards, p.seat_id, 'river'));
  return box;
}

function renderCenter(v) {
  const c = el('section', 'center');
  c.appendChild(el('div', 'big', v.round_wind + '風圈　剩餘 ' + v.wall_count + ' 張'));
  c.appendChild(el('div', 'muted', '莊家：玩家' + v.dealer + '　目前輪到：玩家' + v.current_turn));
  if (v.last_discard) {
    c.appendChild(el('div', 'muted', '最後一張打出：玩家' + v.last_discard.player_id + ' 的 ' + v.last_discard.tile.name));
  }
  return c;
}

async function sendReaction(payload, node) {
  node.classList.add('clicked');
  try {
    await fetch('/api/react', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (err) {}
}

function renderActions(v) {
  const box = el('section', 'actions');

  const labels = { chi: '吃', pong: '碰', kong: '槓', win: '胡', pass: '過' };
  const buttons = el('div', 'row');
  Object.keys(labels).forEach((k) => {
    const b = el('button', 'reaction', labels[k]);
    b.disabled = !v.buttons[k];
    b.dataset.action = k;
    b.addEventListener('click', () => sendReaction({ kind: 'button', action: k }, b));
    buttons.appendChild(b);
  });
  box.appendChild(buttons);

  const chips = el('div', 'row');
  chips.appendChild(el('span', 'row-label', '合法動作'));
  v.actions.forEach((a) => {
    const chip = el('span', 'chip' + (a.selected ? ' selected' : ''), a.label);
    // 吃／槓可能有多種組合：每個組合都是可點的「選牌」目標（data-choice = 動作 id）
    if (a.type === 'chi' || a.type === 'kong') {
      chip.classList.add('choice');
      chip.dataset.choice = a.id;
      chip.addEventListener('click', () => sendReaction({ kind: 'choice', id: a.id }, chip));
    }
    chips.appendChild(chip);
  });
  box.appendChild(chips);

  if (v.decision) {
    box.appendChild(el('div', 'muted',
      '策略選擇：' + v.decision.label + '　分數 ' + Number(v.decision.score).toFixed(2) + '　原因：' + v.decision.reason));
  }
  return box;
}

let layoutTimer = null;
function reportLayout() {
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(sendLayout, 150);
}
function rectOf(e) {
  const r = e.getBoundingClientRect();
  return { x: +r.x.toFixed(1), y: +r.y.toFixed(1), w: +r.width.toFixed(1), h: +r.height.toFixed(1) };
}
async function sendLayout() {
  const tiles = [];
  document.querySelectorAll('#table .tile[data-tile]').forEach((e) => {
    tiles.push({
      tile: Number(e.dataset.tile), seat: Number(e.dataset.seat), zone: e.dataset.zone || '',
      ...rectOf(e),
    });
  });
  const buttons = [];
  document.querySelectorAll('#table button.reaction[data-action]').forEach((e) => {
    buttons.push({ action: e.dataset.action, enabled: !e.disabled, ...rectOf(e) });
  });
  const choices = [];
  document.querySelectorAll('#table [data-choice]').forEach((e) => {
    choices.push({ id: e.dataset.choice, ...rectOf(e) });
  });
  const payload = {
    dpr: window.devicePixelRatio,
    inner: [window.innerWidth, window.innerHeight],
    outer: [window.outerWidth, window.outerHeight],
    tiles,
    buttons,
    choices,
  };
  try {
    await fetch('/api/layout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  } catch (e) {}
}
window.addEventListener('resize', reportLayout);
window.addEventListener('scroll', reportLayout);

function renderTable(v) {
  const root = $('table');
  root.textContent = '';
  v.players.forEach((p) => root.appendChild(renderPlayer(p)));
  root.appendChild(renderCenter(v));
  root.appendChild(renderActions(v));

  reportLayout();
}

async function refreshTable() {
  try {
    const response = await fetch('/api/table' + window.location.search);
    renderTable(await response.json());
  } catch (error) {
    $('table').textContent = '牌桌載入失敗：' + error.message;
  }
}

async function refreshState() {
  const response = await fetch('/api/state');
  const s = await response.json();
  $('controlState').textContent = s.control_state;
  $('gameInfo').textContent = '目前玩家：玩家 ' + s.current_turn + '　剩餘牌數：' + s.wall_count;
  await refreshTable();
}

async function post(path) {
  $('systemMessage').textContent = '處理中...';
  try {
    const response = await fetch(path, { method: 'POST' });
    const result = await response.json();
    $('systemMessage').textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    $('systemMessage').textContent = '執行失敗：' + error.message;
  }
  await refreshState();
}

$('startButton').addEventListener('click', () => post('/api/run'));
$('pauseButton').addEventListener('click', () => post('/api/pause'));
$('resumeButton').addEventListener('click', () => post('/api/resume'));
$('stopButton').addEventListener('click', () => post('/api/stop'));
$('resetButton').addEventListener('click', () => post('/api/reset'));

refreshState();
</script>
</body>
</html>
"""