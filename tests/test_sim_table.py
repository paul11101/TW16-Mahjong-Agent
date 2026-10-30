"""W6 測試牌桌（SimTable）、觀察器、網頁端點，以及「整局從頭打到尾」的整合測試。

不點擊、不需要瀏覽器：回合函式直接把策略決策套到 SimTable（等同於點擊後網頁收到回報）。
執行方式（專案根目錄）：
    python -m tests.test_sim_table
或
    python -m pytest tests/test_sim_table.py -v
"""

import random

from src.common.schemas import ActionReceipt, ActionType
from src.control.game_runner import (
    PHASE_MY_TURN,
    PHASE_OVER,
    PHASE_REACTION,
    PHASE_WAITING,
    GameRunner,
)
from src.control.controller import AgentController
from src.control.pipeline import TurnResult, get_reaction_rules_actions
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.action_policy import ActionPolicy
from src.strategy.adapters import (
    actions_to_legal_actions,
    action_to_legal_action,
    game_state_to_observation,
)
from test_interface import app as app_module
from test_interface.fakes import FakeMouse
from test_interface.sim_table import PHASE_OVER as SIM_OVER
from test_interface.sim_table import PHASE_REACTION as SIM_REACTION
from test_interface.sim_table import PHASE_TURN as SIM_TURN
from test_interface.sim_table import SimTable
from test_interface.table_page import INDEX_HTML
from test_interface.web_observer import (
    WebObserver,
    classify_view,
    fetch_fresh_layout,
    make_boxes_fn,
    state_from_view,
    view_fingerprint,
)
from tests._runner import run_module
from tests.helpers import FakeClock


def _play_random(seed, rng_seed=0, limit=800):
    """隨機選合法動作打完一局，回傳 (table, 看過的階段集合, 反應動作種類計數)。"""
    table = SimTable(seed)
    rng = random.Random(rng_seed)
    seen, kinds, n = set(), {}, 0
    while table.phase != SIM_OVER:
        n += 1
        assert n < limit, "牌局沒有結束"
        seen.add(table.phase)
        if table.phase == SIM_TURN:
            assert table.agent_discard(rng.choice(table.state.players[0].hand))
            continue
        acts = [action_to_legal_action(a) for a in table._agent_actions]
        pick = rng.choice(acts)
        kind = ActionType(pick.action).value
        kinds[kind] = kinds.get(kind, 0) + 1
        siblings = [a for a in acts if a.action == pick.action]
        if kind in ("chi", "kong") and len(siblings) > 1:
            assert table.agent_react("button", kind)
            assert table.agent_react("choice", choice_id=pick.id)
        else:
            assert table.agent_react("button", kind)
    return table, seen, kinds


def test_deal_and_hidden_hands():
    table = SimTable(1)
    view = table.view()

    assert table.phase == SIM_TURN
    assert len(table.state.players[0].hand) == 17  # 莊家
    me = view["players"][0]
    assert me["is_self"] and len(me["hand"]) == 17
    assert all(p["hand"] is None for p in view["players"][1:])
    assert view["phase"] == SIM_TURN and view["game_over"] is False
    assert not any(view["buttons"][k] for k in ("chi", "pong", "pass"))  # 自己回合只可能有 槓／胡
    assert SimTable(1).view() == SimTable(1).view()  # 同 seed 同牌局


def test_wrong_actions_are_rejected():
    table = SimTable(1)
    assert table.agent_discard(99) is False
    assert table.agent_react("button", "pass") is False  # 不是反應階段
    before = table.view()
    assert table.agent_discard(41) is False
    assert table.view() == before


def test_random_games_finish_and_reach_all_phases():
    seen_all, kinds_all = set(), {}
    for seed in range(25):
        table, seen, kinds = _play_random(seed, rng_seed=seed)
        seen_all |= seen
        for k, v in kinds.items():
            kinds_all[k] = kinds_all.get(k, 0) + v
        assert table.state.is_over and table.result in ("win", "draw")
        assert table.view()["game_over"] is True

    assert {SIM_TURN, SIM_REACTION} <= seen_all
    assert {"pass", "chi", "pong"} <= set(kinds_all)  # 有遇到吃、碰，也有兩步驟選組合


def test_classify_and_fingerprint_from_visible_view():
    table = SimTable(1)
    view = table.view()
    assert classify_view(view) == PHASE_MY_TURN

    # 打一張牌之後，直到輪到自己或反應
    table.agent_discard(table.state.players[0].hand[0])
    view2 = table.view()
    phase2 = classify_view(view2)
    assert phase2 in (PHASE_MY_TURN, PHASE_REACTION, PHASE_OVER)
    assert view_fingerprint(view2, phase2) != view_fingerprint(view, PHASE_MY_TURN)

    # 找一個反應畫面
    for seed in range(30):
        t = SimTable(seed)
        for _ in range(40):
            if t.phase == SIM_REACTION:
                break
            if t.phase == SIM_TURN:
                t.agent_discard(t.state.players[0].hand[0])
            else:
                break
        if t.phase == SIM_REACTION:
            v = t.view()
            assert classify_view(v) == PHASE_REACTION and v["buttons"]["pass"]
            break
    else:
        raise AssertionError("30 局內沒有遇到反應畫面")


def test_state_from_view_matches_rules_actions():
    for seed in range(30):
        t = SimTable(seed)
        for _ in range(40):
            if t.phase != SIM_TURN:
                break
            t.agent_discard(t.state.players[0].hand[0])
        if t.phase != SIM_REACTION:
            continue

        view = t.view()
        state = state_from_view("g", view)
        assert state.players[0].hand == sorted(t.state.players[0].hand) or \
            sorted(state.players[0].hand) == sorted(t.state.players[0].hand)
        assert all(state.players[i].hand == [] for i in (1, 2, 3))  # 其他人的手牌保持未知

        mine = {action_to_legal_action(a).id for a in get_reaction_rules_actions(state, 0)}
        sim = {action_to_legal_action(a).id for a in t._agent_actions}
        assert mine == sim  # 整合端從畫面算出的合法反應 = 牌桌提供的反應
        return
    raise AssertionError("沒有找到反應情境")


def test_two_step_choice_requires_button_first():
    for seed in range(60):
        t = SimTable(seed)
        for _ in range(60):
            if t.phase != SIM_TURN:
                break
            t.agent_discard(t.state.players[0].hand[0])
        if t.phase != SIM_REACTION:
            continue
        chis = [action_to_legal_action(a) for a in t._agent_actions if ActionType(a.action_type) == ActionType.CHI]
        if len(chis) < 2:
            continue

        assert t.agent_react("choice", choice_id="pong_99") is False
        assert t.phase == SIM_REACTION
        assert t.agent_react("button", "chi") is True  # 第一步：只是選了「吃」，牌局沒前進
        assert t.phase == SIM_REACTION
        assert t.agent_react("choice", choice_id=chis[0].id) is True
        assert len(t.state.players[0].melds) == 1
        return
    raise AssertionError("沒有遇到多組合的吃牌")


# ------------------------------------------------------------------ 整局整合

def _receipt(ok):
    return ActionReceipt(
        receipt_id="r", game_id="g", event_id="e", decision_id="d",
        success=ok, ui_action_executed=True, state_verified=ok, latency_ms=10.0,
        error_code=None if ok else "CLICK_REJECTED",
    )


def _turn_fns(table):
    policy = ActionPolicy()

    def discard_turn(snap):
        state = state_from_view("g", snap.data)
        legal = actions_to_legal_actions(
            LegalActionGenerator().get_turn_player_actions(hand=list(state.players[0].hand))
        )
        decision = policy.decide(game_state_to_observation(state, 0), legal)
        ok = table.agent_discard(decision.action.tile)
        return TurnResult(legal_count=len(legal), decision=decision, receipt=_receipt(ok))

    def reaction_turn(snap):
        state = state_from_view("g", snap.data)
        legal = actions_to_legal_actions(get_reaction_rules_actions(state, 0))
        if all(a.action == ActionType.PASS for a in legal):
            return TurnResult(legal_count=len(legal), skipped=True)

        decision = policy.decide(game_state_to_observation(state, 0), legal)
        kind = ActionType(decision.action.action).value
        siblings = [a for a in legal if a.action == decision.action.action]
        ok = table.agent_react("button", kind)
        if ok and kind in ("chi", "kong") and len(siblings) > 1:
            ok = table.agent_react("choice", choice_id=decision.action.id)
        return TurnResult(legal_count=len(legal), decision=decision, receipt=_receipt(ok))

    return {PHASE_MY_TURN: discard_turn, PHASE_REACTION: reaction_turn}


def _run_full_game(seed, tmp_path):
    table = SimTable(seed)

    class Observer(WebObserver):
        def fetch_view(self):
            return table.view()

    controller = AgentController(game_id="g", mouse=FakeMouse())
    controller.start()
    clock = FakeClock()
    runner = GameRunner(
        controller, game_id=f"g{seed}", observe_fn=Observer("x").snapshot, turn_fns=_turn_fns(table),
        record_path=tmp_path / f"g{seed}.game.json",
        poll_interval=0.01, advance_timeout=1.0, pause_timeout=0.1, clock=clock, sleep=clock.sleep,
    )
    return table, runner.run(), runner


def test_full_games_with_policy_finish_unattended(tmp_path):
    claims = 0
    for seed in range(12):
        table, summary, runner = _run_full_game(seed, tmp_path)

        assert summary.finished and summary.unattended, (seed, summary)
        assert summary.failed == 0 and summary.ui_success == summary.ui_actions
        assert table.state.is_over
        claims += len(table.state.players[0].melds)

        # 每一步都有留下紀錄（可回放）
        assert (tmp_path / f"g{seed}.game.json").exists()
        assert summary.steps == len(runner.records)
    assert claims > 0  # 這 12 局裡 Agent 至少吃碰過一次，策略的反應路徑有跑到


# ------------------------------------------------------------------ app 端點

def test_app_game_endpoints():
    app_module.reset_agent()
    assert app_module._game["table"] is None

    assert app_module.new_game(seed=3)["phase"] == SIM_TURN
    view = app_module.get_table("game")
    assert view["phase"] == SIM_TURN and view["seed"] == 3

    tile = view["players"][0]["hand"][0]["id"]
    app_module.record_discard({"tile": tile, "seat": 0})  # 網頁回報點擊 -> 牌局前進
    assert app_module.game_state()["agent_discards"] == 1
    assert app_module.get_table("game") != view

    app_module.reset_agent()
    assert app_module._game["table"] is None


def test_app_react_endpoint_advances_game():
    app_module.reset_agent()
    for seed in range(40):
        app_module.new_game(seed=seed)
        for _ in range(60):
            v = app_module.get_table("game")
            if v["phase"] != SIM_TURN:
                break
            app_module.record_discard({"tile": v["players"][0]["hand"][0]["id"], "seat": 0})
        if app_module.get_table("game")["phase"] == SIM_REACTION:
            app_module.record_reaction({"kind": "button", "action": "pass"})
            assert app_module.get_table("game")["phase"] != SIM_REACTION
            app_module.reset_agent()
            return
    app_module.reset_agent()
    raise AssertionError("沒有遇到反應畫面")


def test_page_polls_in_game_mode():
    assert "scenario') === 'game'" in INDEX_HTML
    assert "setInterval(refreshTable" in INDEX_HTML
    assert "牌局結束" in INDEX_HTML


# ------------------------------------------------------------------ W6 修正：牌框版本與版面

def test_view_version_changes_only_when_table_changes():
    table = SimTable(1)
    v0 = table.view()["version"]
    assert table.view()["version"] == v0  # 沒動作，版本不變
    table.agent_discard(table.state.players[0].hand[0])
    assert table.view()["version"] == v0 + 1
    assert table.agent_discard(99) is False  # 被拒絕的動作不算
    assert table.view()["version"] == v0 + 1


def test_fetch_fresh_layout_waits_for_matching_version():
    clock = FakeClock()
    answers = [{"version": 1}, {"version": 1}, {"version": 2, "tiles": []}]
    seen = []

    def fetch(_url):
        seen.append(1)
        return answers[min(len(seen) - 1, len(answers) - 1)]

    layout = fetch_fresh_layout("x", 2, fetch=fetch, sleep=clock.sleep, clock=clock)
    assert layout == {"version": 2, "tiles": []} and len(seen) == 3


def test_fetch_fresh_layout_times_out_and_none_skips_check():
    clock = FakeClock()
    assert fetch_fresh_layout("x", 5, fetch=lambda u: {"version": 4}, timeout=0.3,
                              sleep=clock.sleep, clock=clock) is None
    assert fetch_fresh_layout("x", None, fetch=lambda u: {"version": 4}) == {"version": 4}


def test_boxes_fn_returns_nothing_for_stale_layout():
    import numpy as np

    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    stale = make_boxes_fn("x", 0, version_fn=lambda: 2, fetch=lambda u: {"version": 1, "tiles": []}, timeout=0.1)
    assert stale(frame) == []

    fresh = make_boxes_fn("x", 0, version_fn=lambda: 1, fetch=lambda u: {"version": 1, "tiles": []}, timeout=0.1)
    assert fresh(frame) == []  # 同版但沒有牌框：回傳空清單，不拋錯


def test_page_reports_version_and_fits_long_games():
    assert "version: window.__tableVersion" in INDEX_HTML
    assert "#table.game .dock {" in INDEX_HTML
    assert "position: sticky; bottom: 0" in INDEX_HTML
    assert "dock.appendChild(actions)" in INDEX_HTML
    assert "visible: isTopmost(e, r)" in INDEX_HTML
    assert "#table.game .row.hand .tile.back { display: none" in INDEX_HTML


if __name__ == "__main__":
    run_module(globals(), "test_sim_table")