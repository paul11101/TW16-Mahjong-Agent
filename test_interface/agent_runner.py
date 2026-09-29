from test_interface.mock_data import get_fake_observation
from test_interface.mock_strategy import choose_action
from test_interface.mock_controller import execute_action


def run_agent():
    """執行一次假資料到模擬點擊的完整流程。"""

    # 1. 取得假牌局資料
    observation = get_fake_observation()

    # 2. 讓測試策略選擇動作
    decision = choose_action(observation)

    if not decision["success"]:
        return {
            "success": False,
            "observation": observation,
            "decision": decision,
            "execution": None,
            "message": decision["message"],
        }

    # 3. 模擬執行動作
    execution = execute_action(decision["action"])

    # 4. 整理結果
    return {
        "success": execution["success"],
        "observation": observation,
        "decision": decision,
        "execution": execution,
        "message": execution["message"],
    }