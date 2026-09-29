def choose_action(observation):
    """從合法動作中選擇第一個動作，作為測試策略。"""
    legal_actions = observation.get("legal_actions", [])

    if not legal_actions:
        return {
            "success": False,
            "action": None,
            "message": "沒有可執行的合法動作",
        }

    return {
        "success": True,
        "action": legal_actions[0],
        "message": "測試策略已選擇動作",
    }