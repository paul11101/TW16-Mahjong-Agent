def execute_action(action):
    """模擬執行動作，不進行實際滑鼠操作。"""
    if not action:
        return {
            "success": False,
            "message": "沒有可執行的動作",
        }

    if action.get("type") != "discard":
        return {
            "success": False,
            "message": "目前測試控制器只支援出牌",
        }

    tile = action.get("tile")

    if not tile:
        return {
            "success": False,
            "message": "缺少要打出的牌",
        }

    return {
        "success": True,
        "message": f"測試模式：模擬點擊 {tile}",
        "clicked_tile": tile,
    }