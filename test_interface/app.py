"""台灣16張麻將 Agent 測試介面（FastAPI）。

啟動方式（專案根目錄）：
    uvicorn test_interface.app:app --reload

控制狀態（app 層級，僅用來示範 開始／暫停／停止 的安全閘門）：
    ready   可以執行
    paused  暫停中，拒絕執行
    stopped 已停止，拒絕執行，需按「重設」才能回到 ready
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from test_interface.agent_runner import SEAT, make_fake_game_state, run_agent

app = FastAPI(
    title="TW16 Mahjong Agent Test Interface",
    version="0.2.0",
)

# JSONL log 輸出資料夾（測試時可改掉）
LOG_DIR = "logs"

_control = {"state": "ready"}

_HONORS = {
    27: "東", 28: "南", 29: "西", 30: "北",
    31: "中", 32: "發", 33: "白",
}
_NUMS = "一二三四五六七八九"


def tile_label(tile_id: int) -> str:
    """牌 ID -> 中文名稱（僅供介面顯示）。"""
    if 0 <= tile_id <= 8:
        return _NUMS[tile_id] + "萬"
    if 9 <= tile_id <= 17:
        return _NUMS[tile_id - 9] + "筒"
    if 18 <= tile_id <= 26:
        return _NUMS[tile_id - 18] + "條"
    if tile_id in _HONORS:
        return _HONORS[tile_id]
    return f"牌{tile_id}"


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <title>台灣16張麻將 Agent 測試介面</title>
    </head>

    <body>
        <h1>台灣16張麻將 Agent 測試介面</h1>

        <p>控制狀態：<strong id="controlState">-</strong></p>

        <hr>

        <h2>牌局資訊</h2>
        <p id="gameInfo">載入中...</p>

        <h2>操作</h2>
        <button id="startButton">開始</button>
        <button id="pauseButton">暫停</button>
        <button id="resumeButton">繼續</button>
        <button id="stopButton">停止</button>
        <button id="resetButton">重設</button>

        <h2>手牌</h2>
        <p id="hand">載入中...</p>

        <h2>系統訊息</h2>
        <pre id="systemMessage">等待測試資料...</pre>

        <script>
        const $ = (id) => document.getElementById(id);

        async function refreshState() {
            const response = await fetch("/api/state");
            const s = await response.json();
            $("controlState").textContent = s.control_state;
            $("gameInfo").textContent =
                "目前玩家：玩家 " + s.current_turn + "　剩餘牌數：" + s.wall_count;
            $("hand").textContent = s.hand.map((t) => t.name).join("　");
        }

        async function post(path) {
            $("systemMessage").textContent = "處理中...";
            try {
                const response = await fetch(path, { method: "POST" });
                const result = await response.json();
                $("systemMessage").textContent = JSON.stringify(result, null, 2);
            } catch (error) {
                $("systemMessage").textContent = "執行失敗：" + error.message;
            }
            await refreshState();
        }

        $("startButton").addEventListener("click", () => post("/api/run"));
        $("pauseButton").addEventListener("click", () => post("/api/pause"));
        $("resumeButton").addEventListener("click", () => post("/api/resume"));
        $("stopButton").addEventListener("click", () => post("/api/stop"));
        $("resetButton").addEventListener("click", () => post("/api/reset"));

        refreshState();
        </script>
    </body>
    </html>
    """


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "tw16-mahjong-test-interface",
    }


@app.get("/api/state")
def get_state():
    state = make_fake_game_state("preview")
    hand = state.players[SEAT].hand
    return {
        "control_state": _control["state"],
        "current_turn": state.current_turn,
        "wall_count": state.wall_count,
        "hand": [{"id": t, "name": tile_label(t)} for t in sorted(hand)],
    }


@app.post("/api/run")
def run_test_agent():
    if _control["state"] != "ready":
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "message": f"目前狀態為 {_control['state']}，無法執行",
            },
        )
    return run_agent(log_dir=LOG_DIR)


@app.post("/api/pause")
def pause_agent():
    if _control["state"] == "ready":
        _control["state"] = "paused"
    return {"control_state": _control["state"]}


@app.post("/api/resume")
def resume_agent():
    if _control["state"] == "paused":
        _control["state"] = "ready"
    return {"control_state": _control["state"]}


@app.post("/api/stop")
def stop_agent():
    _control["state"] = "stopped"
    return {"control_state": _control["state"]}


@app.post("/api/reset")
def reset_agent():
    _control["state"] = "ready"
    return {"control_state": _control["state"]}