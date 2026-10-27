"""可打完整一局的測試牌桌（W6）：用規則模組的 GameState 驅動，對手自動打牌。

用途：讓網頁測試介面能「真的」打完一局，Agent 點擊後牌局才會前進。
- 座位 0 = Agent（莊家，開局 17 張）；座位 1~3 = 簡單對手。
- 對手：摸什麼打什麼（沒有剛摸的牌就打第一張）；能胡就胡；別人打牌時只會「碰」或「胡」。
- 對手不是策略模組的工作，也不求強，只要能讓牌局順利推進、讓 Agent 遇到吃碰槓胡過的情境。

只做牌局推進，不做辨識、不做決策。所有規則判斷都呼叫規則模組。
Agent 這一側目前只支援：出牌、對他家打牌的 吃／碰／槓／胡／過（自摸胡牌留給之後）。

執行緒安全：網頁輪詢與點擊回報可能同時進來，所以公開方法都用同一把鎖。
"""

from __future__ import annotations

import random
import threading
from typing import Any

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState, create_shuffled_wall, is_basic_win
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action, RulesetConfig
from src.strategy.adapters import action_to_legal_action, actions_to_legal_actions
from test_interface.table_view import build_table_view

PHASE_TURN = "agent_turn"
PHASE_REACTION = "agent_reaction"
PHASE_OVER = "over"


class SimTable:
    def __init__(self, seed: int = 1, *, agent_seat: int = 0, config: RulesetConfig | None = None) -> None:
        self.seed = seed
        self.seat = agent_seat
        self.config = config or RulesetConfig()
        self.generator = LegalActionGenerator(self.config)
        self._lock = threading.RLock()

        self.state = GameState(
            game_id=f"sim_{seed}",
            dealer=agent_seat,
            players={i: PlayerState(seat_id=i) for i in range(4)},
            wall=create_shuffled_wall(random.Random(seed)),
        )
        self.state.deal(self.config)

        self.phase = PHASE_TURN
        self.winner: int | None = None
        self.result: str | None = None  # "win" | "draw"
        self.history: list[str] = []

        self._agent_actions: list[Action] = []
        self._opp_reactions: dict[int, Action] = {}
        self._discarder = -1
        self._selected_button: str | None = None
        self._version = 0  # 每次牌面改變就加一；網頁回報牌框時會附上，Agent 用它確認牌框不是舊的

        self._advance()
        self._version += 1

    # ------------------------------------------------------------ 內部：牌局推進

    def _standing(self, player: PlayerState) -> int:
        return self.config.hand_size - 3 * len(player.melds)

    def _finish(self) -> None:
        self.phase = PHASE_OVER
        self.result = "win" if self.winner is not None else "draw"
        self.history.append(f"over: {self.result} winner={self.winner}")

    def _advance(self) -> None:
        """推進牌局，直到輪到 Agent 行動（出牌或反應）或牌局結束。"""
        s = self.state
        for _ in range(2000):
            if s.is_over:
                self._finish()
                return

            pid = s.current_turn
            player = s.players[pid]
            drawn: int | None = None

            if len(player.hand) == self._standing(player):
                action = s.draw_tile(player_id=pid, config=self.config)
                if action is None:  # 牌牆用完，draw_tile 已結算流局
                    self._finish()
                    return
                drawn = action.tile_id

            if pid == self.seat:
                self.phase = PHASE_TURN
                return

            can_win = s.is_basic_win(pid)
            tile_for_win = drawn if drawn is not None else player.hand[-1]
            actions = self.generator.get_turn_player_actions(
                hand=player.hand, last_drawn_tile=tile_for_win, can_win_self_draw=can_win
            )
            if any(a.action_type == ActionType.WIN for a in actions):
                self.winner = pid
                s.complete_round(winner_id=pid)
                self._finish()
                return

            discards = [a for a in actions if a.action_type == ActionType.DISCARD]
            choice = next((a for a in discards if a.tile_id == drawn), discards[0])
            if self._do_discard(pid, choice):
                return  # 等 Agent 反應

        raise RuntimeError("SimTable._advance 迴圈次數過多，牌局沒有結束")

    def _do_discard(self, pid: int, action: Action) -> bool:
        """打牌並收集反應。回傳 True 代表要等 Agent 決定反應。"""
        s = self.state
        s.apply_action(pid, action, config=self.config)
        tile = action.tile_id
        self.history.append(f"discard: player {pid} tile {tile}")

        opp: dict[int, Action] = {}
        agent_actions: list[Action] = []
        for q in range(4):
            if q == pid:
                continue
            qp = s.players[q]
            try:
                can_win = is_basic_win(qp.hand + [tile], meld_count=len(qp.melds))
            except ValueError:
                can_win = False
            acts = self.generator.get_response_actions(
                hand=qp.hand,
                target_tile=tile,
                is_previous_player=(q == (pid + 1) % 4),
                can_win_honin=can_win,
                passed_win=qp.passed_win,
            )
            if q == self.seat:
                agent_actions = acts
            else:
                pick = self._opponent_reaction(acts)
                if pick is not None:
                    opp[q] = pick

        if any(a.action_type != ActionType.PASS for a in agent_actions):
            self._agent_actions = agent_actions
            self._opp_reactions = opp
            self._discarder = pid
            self._selected_button = None
            self.phase = PHASE_REACTION
            return True

        self._resolve(opp, None, pid)
        return False

    @staticmethod
    def _opponent_reaction(actions: list[Action]) -> Action | None:
        for kind in (ActionType.WIN, ActionType.PONG):
            for a in actions:
                if a.action_type == kind:
                    return a
        return None

    def _resolve(self, opp: dict[int, Action], agent_action: Action | None, discarder: int) -> None:
        s = self.state
        reactions = dict(opp)
        if agent_action is not None and agent_action.action_type != ActionType.PASS:
            reactions[self.seat] = agent_action

        resolved = s.resolve_reaction_priority(reactions, config=self.config) if reactions else {}
        if resolved:
            pid, action = next(iter(resolved.items()))
            if action.action_type == ActionType.WIN:
                self.winner = pid
                s.complete_round(winner_id=pid)
                self.history.append(f"win: player {pid} ron")
            else:
                self.history.append(f"claim: player {pid} {ActionType(action.action_type).value}")
                s.apply_action(pid, action, config=self.config)  # 槓牌會自動補牌
        elif discarder != self.seat:
            # 沒有人吃碰胡：Agent 的「過」要記到規則狀態（過水規則）
            s.apply_action(self.seat, Action(action_type=ActionType.PASS), config=self.config)

    # ------------------------------------------------------------ Agent 動作（網頁點擊回報會呼叫）

    def agent_discard(self, tile: int) -> bool:
        with self._lock:
            if self.phase != PHASE_TURN:
                return False
            player = self.state.players[self.seat]
            if not 0 <= tile < 34 or tile not in player.hand:
                return False

            waiting = self._do_discard(self.seat, Action(action_type=ActionType.DISCARD, tile_id=tile))
            if not waiting:
                self._advance()
            self._version += 1
            return True

    def agent_react(self, kind: str | None, action: str | None = None, choice_id: str | None = None) -> bool:
        """kind='button'（action=chi/pong/kong/win/pass）或 kind='choice'（choice_id=chi_1_2_3）。"""
        with self._lock:
            if self.phase != PHASE_REACTION:
                return False

            legal = [(action_to_legal_action(a), a) for a in self._agent_actions]

            if kind == "button":
                if action == "pass":
                    return self._finish_reaction(None)
                matches = [raw for la, raw in legal if ActionType(la.action).value == action]
                if not matches:
                    return False
                if len(matches) == 1:
                    return self._finish_reaction(matches[0])
                self._selected_button = action  # 有多個組合，等第二步選組合
                return True

            if kind == "choice":
                for la, raw in legal:
                    same_kind = self._selected_button is None or ActionType(la.action).value == self._selected_button
                    if la.id == choice_id and same_kind:
                        return self._finish_reaction(raw)
                return False

            return False

    def _finish_reaction(self, agent_action: Action | None) -> bool:
        opp, discarder = self._opp_reactions, self._discarder
        self._agent_actions, self._opp_reactions, self._selected_button = [], {}, None
        self._resolve(opp, agent_action, discarder)
        self._advance()
        self._version += 1
        return True

    # ------------------------------------------------------------ 顯示與評測

    def view(self) -> dict[str, Any]:
        """牌桌顯示資料（只含玩家看得到的資訊；其他玩家手牌是 None）。"""
        with self._lock:
            player = self.state.players[self.seat]
            legal: list = []
            if self.phase == PHASE_REACTION:
                legal = actions_to_legal_actions(self._agent_actions)
            elif self.phase == PHASE_TURN:
                # 只列出打牌：避免暗槓等選項讓「反應按鈕」亮起，被誤判成反應階段
                legal = actions_to_legal_actions(
                    [a for a in self.generator.get_turn_player_actions(hand=list(player.hand))
                     if a.action_type == ActionType.DISCARD]
                )

            view = build_table_view(self.state, self.seat, legal_actions=legal)
            view["phase"] = self.phase
            view["game_over"] = self.phase == PHASE_OVER
            view["result"] = self.result
            view["winner"] = self.winner
            view["seed"] = self.seed
            view["version"] = self._version
            return view

    def evaluator_state(self) -> dict[str, Any]:
        """只給評測器對照用（Agent 不可讀取）：真實進度與結果。"""
        with self._lock:
            return {
                "seed": self.seed,
                "phase": self.phase,
                "result": self.result,
                "winner": self.winner,
                "wall_count": self.state.wall_count,
                "is_over": self.state.is_over,
                "agent_discards": len(self.state.players[self.seat].discards),
                "history_len": len(self.history),
            }