from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="TW16 Mahjong Agent Test Interface",
    version="0.1.0"
)
# 開啟 uvicorn test_interface.app:app --reload

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

        <p>目前狀態：測試介面已啟動</p>

        <hr>

        <h2>牌局資訊</h2>
        <p>目前玩家：玩家 1</p>
        <p>回合：1</p>

        <h2>操作</h2>

        <button>開始</button>
        <button>暫停</button>
        <button>停止</button>

        <h2>玩家 1 手牌</h2>

        <p>
            一萬　 二萬　 三萬　 四萬　 五萬　 六萬　 七萬　 八萬
        </p>

        <p>
            九萬　 一筒　 二筒　 三筒　 四筒　 五筒　 六筒
        </p>

        <h2>系統訊息</h2>

        <p>等待測試資料...</p>

    </body>
    </html>
    """


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "tw16-mahjong-test-interface"
    }