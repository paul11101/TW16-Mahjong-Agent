"""台灣16張麻將 Agent 測試介面（FastAPI）。

啟動方式（專案根目錄）：
    uvicorn test_interface.app:app --reload

控制狀態（app 層級，僅用來示範 開始／暫停／停止 的安全閘門）：
    ready   可以執行
    paused  暫停中，拒絕執行
    stopped 已停止，拒絕執行，需按「重設」才能回到 ready

W3 D1：首頁加入四人牌桌顯示（/api/table），資料由 table_view.py 整理。
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from test_interface.agent_runner import SEAT, make_fake_game_state, run_agent
from test_interface.table_page import INDEX_HTML
from test_interface.table_view import preview_table, tile_label  # noqa: F401  (tile_label 供測試與舊程式使用)

app = FastAPI(
    title="TW16 Mahjong Agent Test Interface",
    version="0.3.0",
)

# JSONL log 輸出資料夾（測試時可改掉）
LOG_DIR = "logs"

_control = {"state": "ready"}


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


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


@app.get("/api/table")
def get_table():
    """四人牌桌顯示資料（假牌局；只顯示，不執行動作）。"""
    return preview_table()


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