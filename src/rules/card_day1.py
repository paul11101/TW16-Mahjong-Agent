TILE_ID_TO_NAME = {

    **{i: f"{i+1}m" for i in range(9)},

    **{i: f"{i-8}b" for i in range(9, 18)},

    **{i: f"{i-17}s" for i in range(18, 27)},

    27: "east", 28: "south", 29: "west", 30: "north",

    31: "red", 32: "green", 33: "white",

    34: "spring", 35: "summer", 36: "autumn", 37: "winter",

    38: "plum", 39: "orchid", 40: "chrysanthemum", 41: "bamboo"

}



# 反向映射：名稱至編碼

NAME_TO_TILE_ID = {v: k for k, v in TILE_ID_TO_NAME.items()}



# 輔助判斷函式

def is_flower(tile_id: int) -> bool:

    """判斷是否為花牌 (34~41)"""

    return 34 <= tile_id <= 41



def is_honor(tile_id: int) -> bool:

    """判斷是否為字牌 (27~33)"""

    return 27 <= tile_id <= 33



def is_suited(tile_id: int) -> bool:

    """判斷是否為數牌 (0~26)"""

    return 0 <= tile_id <= 26