from dataclasses import replace

import pytest

from src.common.schemas import ActionType
from src.strategy.action_policy import ActionPolicy
from src.strategy.interfaces import Decision, LegalAction, Observation


# 建立固定的測試手牌
# 使用不同牌型驗證棄牌、吃牌、碰牌、過牌及三種槓牌
# 牌 ID 0~33 為一般牌，34~41 為花牌
DISCARD_HAND = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27, 33)
CHI_HAND = (0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 3, 4, 6, 7, 33)
PONG_HAND = (0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 33, 33, 6, 7, 24)
PASS_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 6, 7)
MING_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 27, 27, 33, 33, 33)
AN_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 33, 33, 33, 33)
JIA_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 33)


# 建立測試使用的牌局觀察資訊
# 可以指定自己的手牌、已公開副露及牌牆剩餘張數
def make_observation(hand, melds = (), remaining_tiles = 80):
    return Observation(
        # 將指定手牌轉成不可變的 tuple
        hand = tuple(hand),

        # 預設四位玩家都沒有打出任何牌
        discards = ((), (), (), ()),

        # 預設只有玩家 0 可能存在公開副露
        melds = (tuple(melds), (), (), ()),

        # 預設四位玩家都沒有公開花牌
        flowers = ((), (), (), ()),

        # 目前輪到玩家 0
        current_player = 0,

        # Agent 的座位設定為玩家 0
        seat = 0,

        # 設定公開可取得的剩餘牌數
        remaining_tiles = remaining_tiles,
    )


# 根據指定手牌建立所有棄牌候選動作
def make_discards(hand):
    return [
        # 每一種不同的手牌建立一個 DISCARD 動作
        LegalAction(id = f"discard_{tile}", action = ActionType.DISCARD, tile = tile)

        # set 去除重複牌種，sorted 固定動作順序
        for tile in sorted(set(hand))
    ]


# 建立一個合法的 PASS 動作
def make_pass():
    return LegalAction(id = "pass", action = ActionType.PASS)


# 建立指定種類的槓牌動作
# ming：明槓，an：暗槓，jia：加槓
def make_kong(kind):
    return LegalAction(
        id = f"kong_{kind}_33",
        action = ActionType.KONG,

        # 固定使用牌 ID 33 進行測試
        tile = 33,

        # 槓牌由四張相同的牌組成
        tiles = (33, 33, 33, 33),

        # 記錄目前測試的槓牌種類
        kong_type = kind,
    )


# 測試 1：胡牌是否具有最高優先順序
def test_win_has_priority():
    # 建立合法胡牌動作
    win = LegalAction(id = "win_27", action = ActionType.WIN, tile = 27)

    # 同時提供暗槓、棄牌與胡牌候選動作
    actions = [make_kong("an"), *make_discards(AN_HAND), win]

    # 執行統一策略決策
    decision = ActionPolicy().decide(make_observation(AN_HAND), actions)

    # 只要 Rules 提供合法 WIN，就必須優先選擇胡牌
    # is 用來確認回傳的是原本提供的 WIN 物件
    assert decision.action is win


# 測試 2：吃碰決策與 PASS 判斷
# parametrize 會使用下列三組資料分別執行測試
@pytest.mark.parametrize("hand, action, expected", [
    (
        # 測試吃牌後能改善向聽數的情況
        CHI_HAND,
        LegalAction(id = "chi_3_4_5", action = ActionType.CHI, tile = 5, tiles = (3, 4, 5)),
        ActionType.CHI,
    ),
    (
        # 測試碰牌後能改善向聽數的情況
        PONG_HAND,
        LegalAction(id = "pong_33", action = ActionType.PONG, tile = 33, tiles = (33, 33, 33)),
        ActionType.PONG,
    ),
    (
        # 測試碰牌沒有改善向聽數，應選擇 PASS
        PASS_HAND,
        LegalAction(id = "pong_27", action = ActionType.PONG, tile = 27, tiles = (27, 27, 27)),
        ActionType.PASS,
    ),
])
def test_meld_and_pass_decisions(hand, action, expected):
    # 提供吃碰動作及 PASS，讓策略自行比較
    actions = [action, make_pass()]

    # 執行策略決策
    decision = ActionPolicy().decide(make_observation(hand), actions)

    # 確認選出的動作符合預期
    assert decision.action.action == expected

    # 確認決策沒有超出 Rules 提供的合法動作
    assert decision.action in actions


# 測試 3：確認統一策略入口能處理三種槓牌
@pytest.mark.parametrize("kind, hand, melds", [
    (
        # 明槓：從自己的手牌提供三張相同的牌
        "ming", MING_HAND, (),
    ),
    (
        # 暗槓：自己的手牌持有四張相同的牌
        "an", AN_HAND, (),
    ),
    (
        # 加槓：原本已有碰牌，再補上一張相同的牌
        "jia", JIA_HAND, ((33, 33, 33),),
    ),
])
def test_three_kong_types(kind, hand, melds):
    # 建立目前測試的槓牌動作
    kong = make_kong(kind)

    # 明槓通常發生在他人出牌後，因此提供 PASS
    # 暗槓與加槓則提供一般棄牌作為替代選項
    alternatives = [make_pass()] if kind == "ming" else make_discards(hand)

    # 將槓牌及替代動作組成合法候選清單
    actions = [kong, *alternatives]

    # 建立含有對應副露資訊的 Observation
    decision = ActionPolicy().decide(make_observation(hand, melds), actions)

    # 確認策略選擇原本提供的槓牌動作
    assert decision.action is kong


# 測試 4：棄牌策略是否使用公開資訊
def test_discard_uses_public_information():
    # 建立測試牌局
    # 河牌中已經出現三張牌 ID 33
    # 自己手上還有一張，因此這種牌已經全部可見
    observation = replace(
        make_observation(DISCARD_HAND),
        discards = ((33, 33, 33), (), (), ()),
    )

    # 提供兩種合法棄牌選項
    actions = [
        LegalAction(id = "discard_27", action = ActionType.DISCARD, tile = 27),
        LegalAction(id = "discard_33", action = ActionType.DISCARD, tile = 33),
    ]

    # 執行策略決策
    decision = ActionPolicy().decide(observation, actions)

    # 預期打出 33，保留未見張數較有利的牌型
    assert decision.action.id == "discard_33"

    # 確認向聽數對應的決策分數
    assert decision.score == 0.0

    # 確認決策原因包含有效進張的未見張數上限
    assert "unseen_upper_bound = 3" in decision.reason


# 測試 5：已經副露時，向聽數計算是否正確
def test_discard_uses_own_meld_count():
    # 建立已有一組副露的手牌
    hand = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 33)

    # 玩家 0 已經公開碰出三張牌 ID 30
    observation = make_observation(hand, melds = ((30, 30, 30),))

    # 建立所有合法棄牌動作
    actions = make_discards(hand)

    # 執行統一策略決策
    decision = ActionPolicy().decide(observation, actions)

    # 確認選出的動作存在於合法清單中
    assert decision.action in actions

    # 確認最後選擇棄牌
    assert decision.action.action == ActionType.DISCARD

    # 測試牌型預期的向聽數為 0
    assert decision.score == 0.0

    # 確認決策原因包含正確的向聽數
    assert "shanten = 0," in decision.reason


# 測試 6：剩餘牌數不符合槓牌策略條件時，應選擇 PASS
# 分別測試剩餘 0 張、16 張及未知三種情況
@pytest.mark.parametrize("remaining_tiles", [0, 16, None])
def test_unavailable_ming_kong_uses_pass(remaining_tiles):
    # 建立指定剩餘牌數的牌局
    observation = make_observation(MING_HAND, remaining_tiles = remaining_tiles)

    # 同時提供明槓與 PASS
    actions = [make_kong("ming"), make_pass()]

    # 執行策略決策
    decision = ActionPolicy().decide(observation, actions)

    # 確認不主動槓牌，而是選擇原本的 PASS
    assert decision.action == actions[1]


# 測試 7：不適合暗槓時，是否改選合法棄牌
@pytest.mark.parametrize("remaining_tiles", [0, 16, None])
def test_unavailable_an_kong_uses_public_discard(remaining_tiles):
    # 建立指定剩餘牌數的暗槓測試牌局
    observation = make_observation(AN_HAND, remaining_tiles = remaining_tiles)

    # 提供暗槓及所有合法棄牌
    actions = [make_kong("an"), *make_discards(AN_HAND)]

    # 執行策略決策
    decision = ActionPolicy().decide(observation, actions)

    # 不適合槓牌時，必須選擇棄牌
    assert decision.action.action == ActionType.DISCARD

    # 棄牌必須屬於原本的合法清單
    assert decision.action in actions

    # 確認使用公開資訊棄牌策略
    assert "unseen_upper_bound =" in decision.reason


# 測試 8：沒有安全替代動作時，應拒絕執行
def test_only_unavailable_kong_is_rejected():
    # 設定剩餘牌數為 16，未達原本槓牌策略要求
    observation = make_observation(AN_HAND, remaining_tiles = 16)

    # 只有暗槓，沒有其他合法替代動作
    # 預期策略主動回報錯誤，而不是強制槓牌
    with pytest.raises(ValueError, match = "no safe legal action available"):
        ActionPolicy().decide(observation, [make_kong("an")])


# 測試 9：只有 PASS 時，應直接選擇 PASS
def test_only_pass_returns_original_action():
    # 建立唯一合法的 PASS
    action = make_pass()

    # 執行策略決策
    decision = ActionPolicy().decide(make_observation(PASS_HAND), [action])

    # 確認回傳原本的 PASS 物件
    assert decision.action is action


# 測試 10：沒有任何合法動作時，應拋出錯誤
def test_empty_actions_are_rejected():
    # 空清單不應產生任何決策
    with pytest.raises(ValueError, match = "legal_actions cannot be empty"):
        ActionPolicy().decide(make_observation(DISCARD_HAND), [])


# 測試 11：策略不能把摸牌、補花當成一般決策
# parametrize 分別測試 DRAW_TILE 與 FLOWER_REPLACEMENT
@pytest.mark.parametrize("kind", [ActionType.DRAW_TILE, ActionType.FLOWER_REPLACEMENT])
def test_rule_events_are_not_player_decisions(kind):
    # 建立策略不支援的遊戲流程事件
    action = LegalAction(id = "rule_event", action = kind, tile = 34)

    # 這類事件應由 Rules 處理，因此策略必須拒絕
    with pytest.raises(ValueError, match = "unsupported decision action"):
        ActionPolicy().decide(make_observation(DISCARD_HAND), [action])


# 測試 12：防止子策略回傳不存在的合法動作
def test_illegal_child_decision_is_rejected(monkeypatch):
    # 建立統一策略
    policy = ActionPolicy()

    # 建立沒有被 Rules 授權的假胡牌動作
    fake_win = LegalAction(id = "not_allowed", action = ActionType.WIN, tile = 33)

    # 使用 monkeypatch 暫時替換副露策略的 decide()
    # 模擬子策略錯誤地回傳非法動作
    monkeypatch.setattr(
        policy.reaction_policy,
        "decide",
        lambda observation, actions: Decision(action = fake_win, score = 1.0, reason = "invalid"),
    )

    # 統一入口必須攔截不存在於合法清單的決策
    with pytest.raises(ValueError, match = "outside legal_actions"):
        policy.decide(make_observation(MING_HAND), [make_kong("ming"), make_pass()])


# 測試 13：策略決策不能修改輸入資料
def test_inputs_are_not_modified():
    # 建立已有碰牌的觀察資訊
    observation = make_observation(JIA_HAND, melds = ((33, 33, 33),))

    # 建立加槓及棄牌候選清單
    actions = [make_kong("jia"), *make_discards(JIA_HAND)]

    # 保存策略執行前的 Observation 與合法動作
    before_observation = replace(observation)
    before_actions = tuple(actions)

    # 執行策略
    ActionPolicy().decide(observation, actions)

    # 原本的牌局觀察資訊不得被修改
    assert observation == before_observation

    # 原本的合法候選動作及順序不得改變
    assert tuple(actions) == before_actions


# 測試 14：相同輸入應產生相同決策
def test_repeated_decisions_are_deterministic():
    # 建立固定的手牌與合法棄牌動作
    observation = make_observation(DISCARD_HAND)
    actions = make_discards(DISCARD_HAND)

    # 建立同一個策略實例
    policy = ActionPolicy()

    # 執行第一次決策，保存結果
    first = policy.decide(observation, actions)

    # 使用相同資訊重複執行三次
    for _ in range(3):
        # 沒有任何資訊改變時，策略結果必須一致
        assert policy.decide(observation, actions) == first