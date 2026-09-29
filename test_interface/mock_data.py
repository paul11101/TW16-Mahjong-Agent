def get_fake_observation():
    """取得測試用的假牌局資料。"""
    return {
        "current_player": 1,
        "round": 1,
        "hand": [
            "一萬", "二萬", "三萬",
            "四萬", "五萬", "六萬",
            "七萬", "八萬", "九萬",
            "一筒", "二筒", "三筒",
            "四筒", "五筒", "六筒",
        ],
        "legal_actions": [
            {
                "type": "discard",
                "tile": "一萬",
            },
            {
                "type": "discard",
                "tile": "二萬",
            },
        ],
    }