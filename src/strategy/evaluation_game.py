from typing import Sequence

from src.common.schemas import ActionType
from src.rules.fan_calculator import FanCalculator
from src.rules.game_result import GameResult, GameResultPresenter, WinType
from src.rules.game_state import GameState, is_basic_win
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action, RulesetConfig
from src.rules.settlement_calculator import SettlementCalculator
from .adapters import actions_to_legal_actions, game_state_to_observation
from .interfaces import Decision, Strategy


# 策略只取得自己的觀測與合法動作，回傳非法選擇時直接報錯
def _choose(state, seat, policy, actions):
    legal = actions_to_legal_actions(actions)
    decision = policy.decide(game_state_to_observation(state, seat), tuple(legal))
    if not isinstance(decision, Decision) or decision.action not in legal:
        raise ValueError(f"player {seat} returned an illegal decision")
    return actions[legal.index(decision.action)]


# 重用 Rules 計台與付分，保存換莊前的單局結果
def _finish(state, config, before, round_info, *, winners=(), loser=None, tile=None):
    kind = WinType.DRAW
    scores, fans = dict(before), {}
    if winners:
        kind = WinType.SELF_DRAW if loser is None else WinType.DISCARD_WIN
        for seat in winners:
            player = state.players[seat]
            hand = player.hand if loser is None else player.hand + [tile]
            total, details = FanCalculator().calculate(
                hand, winner_seat=seat, dealer_seat=round_info["dealer"],
                lian_zhuang=round_info["lian_zhuang"], is_self_draw=loser is None,
                melds=player.melds, flowers=player.flowers, config=config,
            )
            scores = SettlementCalculator().settle(
                scores, winner_seat=seat, total_fans=total,
                is_self_draw=loser is None, loser_seat=loser,
            )
            fans[seat] = (total, details)
    for seat, score in scores.items():
        state.players[seat].score = score

    # 流局摸牌可能已更新連莊，結果仍記錄本局開始時的莊家資料
    snapshot = state.model_copy(update=round_info)
    result = GameResultPresenter.create_result(
        snapshot, round_number=1, scores_before=before, winner_seats=winners,
        loser_seat=loser, win_type=kind, winner_fan_results=fans,
    )
    if not state.is_over:
        state.complete_round(winner_seats=list(winners))
    return result


# 執行一局已發牌的獨立牌局；達到步數上限視為失敗，不當成流局
def play_round(
    state: GameState, policies: Sequence[Strategy],
    config: RulesetConfig | None = None, *, max_steps: int = 500,
) -> GameResult:
    config = config or RulesetConfig()
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")
    if len(policies) != 4 or set(state.players) != set(range(4)):
        raise ValueError("four players and policies are required")
    if config.hand_size != 16 or not config.rule_mechanics.auto_flower_replacement:
        raise ValueError("evaluation requires 16 tiles and automatic flower replacement")
    if state.is_over or state.current_turn != state.dealer or state.last_discard is not None:
        raise ValueError("state must be a freshly dealt round")
    if any(p.melds or len(p.hand) != 16 + (seat == state.dealer)
           for seat, p in state.players.items()):
        raise ValueError("invalid initial hands")

    generator = LegalActionGenerator(config)
    before = {seat: p.score for seat, p in state.players.items()}
    round_info = {key: getattr(state, key) for key in ("dealer", "round_wind", "lian_zhuang")}
    last_drawn = state.players[state.dealer].hand[-1]
    needs_draw = False

    for _ in range(max_steps):
        seat = state.current_turn
        player = state.players[seat]
        if needs_draw:
            drawn = state.draw_tile(config=config)
            if drawn is None:
                return _finish(state, config, before, round_info)
            last_drawn = drawn.tile_id
        needs_draw = False

        # 吃碰後不能再摸牌，也不能將吃碰取得的牌當成自摸
        if len(player.hand) != 17 - 3 * len(player.melds):
            raise ValueError(f"unexpected hand size at player {seat}")
        actions = generator.get_turn_player_actions(
            hand=player.hand, last_drawn_tile=last_drawn,
            melded_pongs=[m.tiles[0] for m in player.melds if m.meld_type == ActionType.PONG],
            can_win_self_draw=last_drawn is not None and state.is_basic_win(seat),
        )
        chosen = _choose(state, seat, policies[seat], actions)
        if chosen.action_type == ActionType.WIN:
            return _finish(state, config, before, round_info, winners=(seat,))

        drawn = state.apply_action(seat, chosen, config=config)
        if chosen.action_type == ActionType.KONG:
            if drawn is None:
                return _finish(state, config, before, round_info)
            last_drawn = drawn.tile_id
            continue  # Rules 已完成槓後補牌，不再額外摸牌

        last_drawn = None
        tile = chosen.tile_id
        reactions = {}
        for other in range(4):
            if other == seat:
                continue
            opponent = state.players[other]
            actions = generator.get_response_actions(
                hand=opponent.hand, target_tile=tile,
                is_previous_player=other == (seat + 1) % 4,
                can_win_honin=is_basic_win(opponent.hand + [tile], len(opponent.melds)),
                passed_win=opponent.passed_win,
            )
            reactions[other] = _choose(state, other, policies[other], actions)

        # 先收齊決策；有胡牌卻選吃碰槓或過，也要記錄過水
        for other, reaction in reactions.items():
            if reaction.action_type != ActionType.WIN:
                state.apply_action(other, Action(action_type=ActionType.PASS), config=config)
        resolved = state.resolve_reaction_priority(reactions, config=config)
        winners = tuple(p for p, a in resolved.items() if a.action_type == ActionType.WIN)
        if winners:
            return _finish(
                state, config, before, round_info, winners=winners, loser=seat, tile=tile,
            )
        if resolved:
            other, reaction = next(iter(resolved.items()))
            drawn = state.apply_action(other, reaction, config=config)
            if reaction.action_type == ActionType.KONG:
                if drawn is None:
                    return _finish(state, config, before, round_info)
                last_drawn = drawn.tile_id
        else:
            needs_draw = True
    raise RuntimeError(f"round exceeded {max_steps} steps")