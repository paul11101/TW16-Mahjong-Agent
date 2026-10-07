"""台灣16張麻將 Agent 測試介面（FastAPI）。

啟動方式（專案根目錄）：
    uvicorn test_interface.app:app --reload

控制狀態（app 層級，僅用來示範 開始／暫停／停止 的安全閘門）：
    ready   可以執行
    paused  暫停中，拒絕執行
    stopped 已停止，拒絕執行，需按「重設」才能回到 ready

W3 D1：首頁加入四人牌桌顯示（/api/table），資料由 table_view.py 整理。
"""

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from test_interface.agent_runner import SEAT, make_fake_game_state, run_agent
from test_interface.table_page import INDEX_HTML
from test_interface.table_view import (  # noqa: F401  (tile_label 供測試與舊程式使用)
    preview_reaction_table,
    preview_table,
    tile_label,
)

app = FastAPI(
    title="TW16 Mahjong Agent Test Interface",
    version="0.3.0",
)

# JSONL log 輸出資料夾（測試時可改掉）
LOG_DIR = "logs"

_control = {"state": "ready"}
_layout: dict = {"data": None}  
_clicks: list = []
_reactions: list = []


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
def get_table(scenario: str = "turn"):
    """四人牌桌顯示資料（假牌局；只顯示，不執行動作）。

    scenario=reaction：上家剛打牌、輪到我反應（吃／碰／過），W4 測試用。
    """
    if scenario == "reaction":
        return preview_reaction_table()
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
    _clicks.clear()
    _reactions.clear()
    return {"control_state": _control["state"]}


@app.post("/api/layout")
def set_layout(payload: dict = Body(...)):
    """網頁回報每張牌的 DOM 牌框（data-tile / data-seat / data-zone）。"""
    _layout["data"] = payload
    return {"ok": True, "tiles": len(payload.get("tiles", []))}


@app.get("/api/layout")
def get_layout():
    return _layout["data"] or {}


@app.post("/api/discard")
def record_discard(payload: dict = Body(...)):
    """網頁回報：使用者／Agent 點了某張手牌（W3 D4 用來確認點擊真的送到網頁）。"""
    _clicks.append({"tile": payload.get("tile"), "seat": payload.get("seat")})
    return {"ok": True, "count": len(_clicks)}


@app.get("/api/clicks")
def get_clicks():
    return {"clicks": list(_clicks)}


@app.post("/api/react")
def record_reaction(payload: dict = Body(...)):
    """網頁回報：點了反應按鈕（kind=button）或吃／槓的組合（kind=choice）。"""
    _reactions.append(
        {
            "kind": payload.get("kind"),
            "action": payload.get("action"),
            "id": payload.get("id"),
        }
    )
    return {"ok": True, "count": len(_reactions)}


@app.get("/api/reactions")
def get_reactions():
    return {"reactions": list(_reactions)}