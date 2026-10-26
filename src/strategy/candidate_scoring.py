from dataclasses import replace

from src.common.schemas import ActionType

from .interfaces import CandidateEvaluation, LegalAction, LegalActions, Observation, Tile   
from .kong_policy import simulate_kong
from .meld_policy import MeldShantenCalculator, evaluate_meld_details
from .public_features import extract_public_features
from .tile_efficiency import effective_draws, evaluate_discard

# 評估單一候選，不負責選擇最後動作
def _score_action(
    observation: Observation,
    action: LegalAction,
    unseen: tuple[int, ...],
    calculator: MeldShantenCalculator,
) -> CandidateEvaluation:
    kind = action.action
    next_discard = None

    # 胡牌由 Rules 確認，不猜測缺少的胡牌牌面資訊
    if kind == ActionType.WIN:
        return CandidateEvaluation(
            action_id=action.id,
            score=1.0,
            scorable=True,
            reason="win is available; terminal action",
        )

    if kind == ActionType.DISCARD:
        if action.tile is None or not 0 <= action.tile < 34:
            raise ValueError("invalid discard tile")

        shanten, draws = evaluate_discard(
            observation.hand,
            action.tile,
            calculator,
        )
        next_discard = action.tile
        phase = "after discard"

    elif kind in (ActionType.CHI, ActionType.PONG):
        # 重用吃碰評估明細，避免重新計算最佳棄牌的有效進張
        shanten, draws, next_discard = evaluate_meld_details(
            observation.hand,
            action,
            len(observation.melds[observation.seat]),
        )
        phase = "after meld and planned discard"

    elif kind == ActionType.KONG:
        own_melds = observation.melds[observation.seat]

        remaining, meld_increase = simulate_kong(
            observation.hand,
            action,
            own_melds,
        )

        next_calculator = MeldShantenCalculator(
            len(own_melds) + meld_increase
        )

        # 只評估補牌前已知的手牌，不猜測補牌結果
        shanten = next_calculator.calculate(remaining)
        draws = effective_draws(
            remaining,
            next_calculator,
            current_shanten=shanten,
        )

        # 四張槓牌已經使用完畢，不能再算成有效進張
        draws = tuple(
            tile for tile in draws
            if tile != action.tile
        )

        phase = (
            f"kong_type = {action.kong_type}, "
            f"replacement_draw = pending"
        )

    elif kind == ActionType.PASS:
        # PASS 評估目前手牌，不預測下一次摸牌
        shanten = calculator.calculate(observation.hand)
        draws = effective_draws(
            observation.hand,
            calculator,
            current_shanten=shanten,
        )
        phase = "current hand after pass"

    else:
        raise ValueError(f"unsupported scoring action: {kind}")

    # 自己的牌移到河牌或副露後，已知牌的總數不變
    available = tuple(
        tile for tile in draws
        if unseen[tile] > 0
    )

    effective_count = len(available)
    unseen_count = sum(
        unseen[tile] for tile in available
    )

    # 分數只記錄負向聽數，不表示不同動作具有相同收益尺度
    return CandidateEvaluation(
        action_id=action.id,
        score=float(-shanten),
        shanten=shanten,
        effective_draws=effective_count,
        unseen_upper_bound=unseen_count,
        next_discard=next_discard,
        scorable=True,
        reason=(
            f"{phase}, shanten = {shanten}, "
            f"effective_draws = {effective_count}, "
            f"unseen_upper_bound = {unseen_count}, "
            f"next_discard = {next_discard}"
        ),
    )


# 依原始順序評估全部候選，不只保留最低向聽的動作
def score_candidates(
    observation: Observation,
    legal_actions: LegalActions,
) -> tuple[CandidateEvaluation, ...]:
    if not isinstance(observation, Observation):
        raise TypeError(
            "observation must be a Strategy Observation"
        )

    actions = tuple(legal_actions)

    if not actions:
        raise ValueError("legal_actions cannot be empty")

    # 動作 ID 必須唯一，才能正確對應候選評分
    if len({action.id for action in actions}) != len(actions):
        raise ValueError("action ids must be unique")

    # 每次呼叫只提取一次公開資訊
    # 觀測不一致時直接回報錯誤，不繼續產生評分
    public = extract_public_features(observation)

    calculator = MeldShantenCalculator(
        len(observation.melds[observation.seat])
    )

    results = []
    cache = {}

    for action in actions:
        # 同內容、不同 ID 的動作共用評估，但保留各自的結果
        key = (
            action.action,
            action.tile,
            action.tiles,
            action.kong_type,
        )

        if key not in cache:
            try:
                cache[key] = _score_action(
                    observation,
                    action,
                    public.unseen_upper_bounds,
                    calculator,
                )

            except ValueError as error:
                # 個別候選無法評估時保留原因，不填入假的零分
                cache[key] = CandidateEvaluation(
                    action_id=action.id,
                    reason=str(error),
                )

        results.append(
            replace(
                cache[key],
                action_id=action.id,
            )
        )

    # 快取只存在於這次呼叫，不沿用過期的公開資訊
    return tuple(results)