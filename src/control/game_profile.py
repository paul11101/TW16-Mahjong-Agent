"""遊戲設定檔（正式遊戲接入）：視窗標題、座位對應、手牌狀態判斷。

測試介面（DOM）換成真實遊戲（canvas 畫面）時，整合端要改的東西集中在這裡，
其他模組（pipeline / executor / verifier）不用動。

座位對應（以愛台灣打麻將畫面為準，自己永遠在下方）：
    內部 seat 0 = 自己（下）、1 = 下家（右）、2 = 對家（上）、3 = 上家（左）
    這與 test_interface/table_view.py 的 POSITIONS 一致。

只能從畫面看到「自己的手牌」，所以 state_from_visible_hand() 只填自己的手牌，
其他玩家保持未知（空），符合企劃書「未知牌保持未知」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.rules.game_state import GameState, PlayerState


@dataclass(frozen=True)
class GameProfile:
    name: str
    title_contains: str  # 視窗標題關鍵字
    exclude_titles: tuple[str, ...] = ()
    hand_size: int = 16  # 台麻 16 張；輪到自己摸牌後是 17 張


ITAIWANMJ16 = GameProfile(
    name="itaiwanmj16",
    # 桌面版標題：「愛台灣打麻將 [3.4.6.260909.111] x64」（版本號會變，所以只比對到「 [」）。
    # 網頁版的瀏覽器標題是「愛台灣打麻將 - ... - Microsoft Edge」，不含「[」，不會被誤抓。
    title_contains="愛台灣打麻將 [",
    exclude_titles=("Visual Studio Code",),
)

# classify_hand 的結果
HAND_MY_TURN = "my_turn"  # 手牌數 = 暗牌數 + 1：剛摸牌，輪到自己打
HAND_WAITING = "waiting"  # 手牌數 = 暗牌數：不是自己打牌的時候
HAND_HAS_FLOWER = "has_flower"  # 手上有花牌：等補花動畫結束，不要點
HAND_INCOMPLETE = "incomplete"  # 張數不對：視覺漏牌／動畫中／有槓牌，不要點


def is_flower(tile: int) -> bool:
    return 34 <= tile <= 41


def classify_hand(hand: Sequence[int], *, hand_size: int = 16, meld_count: int = 0) -> str:
    """依畫面上看到的手牌張數，判斷現在能不能出牌。

    meld_count：自己已副露幾組（吃碰各減 3 張暗牌）。槓牌會多出一張補牌，
    目前不處理，遇到槓請先人工確認（結果會是 incomplete，不會點擊）。
    """
    if any(is_flower(t) for t in hand):
        return HAND_HAS_FLOWER

    concealed = hand_size - 3 * meld_count
    count = len(hand)
    if count == concealed + 1:
        return HAND_MY_TURN
    if count == concealed:
        return HAND_WAITING
    return HAND_INCOMPLETE


def state_from_visible_hand(
    game_id: str,
    hand: Sequence[int],
    *,
    seat: int = 0,
    dealer: int = 0,
    wall_count: int = 144,
) -> GameState:
    """只用「畫面看得到的手牌」建立最小 GameState（給 run_discard_turn 用）。

    其他玩家的手牌、河牌、副露目前沒有視覺來源，保持空（未知）。
    """
    if not 0 <= seat <= 3 or not 0 <= dealer <= 3:
        raise ValueError("seat 與 dealer 必須在 0~3")

    players = {i: PlayerState(seat_id=i) for i in range(4)}
    players[seat].hand = list(hand)

    return GameState(
        game_id=game_id,
        dealer=dealer,
        current_turn=seat,
        wall_count=wall_count,
        players=players,
    )


def check_hand_row(
    boxes: Sequence,
    *,
    max_gap_ratio: float = 0.6,
    max_overlap_ratio: float = 0.3,
    max_y_ratio: float = 0.25,
) -> list[str]:
    """檢查視覺回傳的手牌牌框「排得像不像一排手牌」；回傳問題清單，空清單代表沒問題。

    只數張數不夠：視覺每種牌只回一個位置時，漏掉重複牌、又誤判出別張牌，
    張數剛好可能還是 16。真正的手牌是一排等寬、緊貼、同高的牌，所以檢查：
    - 相鄰牌框之間不能有大縫隙（> 牌寬 * max_gap_ratio -> 漏牌）
    - 相鄰牌框不能大量重疊（> 牌寬 * max_overlap_ratio -> 誤判）
    - 每張牌的 y 不能偏離手牌列中位數太多

    boxes 需有 tile / x / y / w / h（例如 TileBox）。
    """
    if not boxes:
        return ["沒有偵測到任何手牌"]

    ordered = sorted(boxes, key=lambda b: b.x)
    width = sorted(b.w for b in ordered)[len(ordered) // 2]
    height = sorted(b.h for b in ordered)[len(ordered) // 2]
    y_median = sorted(b.y for b in ordered)[len(ordered) // 2]

    problems: list[str] = []
    for box in ordered:
        if abs(box.y - y_median) > max_y_ratio * height:
            problems.append(f"牌 {box.tile} 的 y={box.y} 偏離手牌列（中位數 {y_median}）")

    for left, right in zip(ordered, ordered[1:]):
        gap = right.x - (left.x + left.w)
        if gap > max_gap_ratio * width:
            problems.append(f"牌 {left.tile} 與 {right.tile} 之間空了 {gap}px（牌寬約 {width}px），可能漏牌")
        elif -gap > max_overlap_ratio * width:
            problems.append(f"牌 {left.tile} 與 {right.tile} 重疊 {-gap}px，可能是誤判")

    return problems