"""Style-based policy wrapper that leaves the frozen BaselinePolicy unchanged."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from src.common.schemas import ActionType
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import Decision, LegalAction, LegalActions, Observation
from src.strategy.meld_policy import MeldShantenCalculator, evaluate_meld_details
from src.strategy.tile_efficiency import remove_discard


@dataclass(frozen=True)
class BotStyleConfig:
    """Relative preferences used to rank actions already allowed by Rules."""

    baseline_weight: float = 1.0
    shanten_weight: float = 0.0
    chi_bias: float = 0.0
    pong_bias: float = 0.0
    kong_bias: float = 0.0
    honor_keep_weight: float = 0.0
    safe_tile_weight: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "baseline_weight",
            "shanten_weight",
            "chi_bias",
            "pong_bias",
            "kong_bias",
            "honor_keep_weight",
            "safe_tile_weight",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if self.baseline_weight < 0 or self.shanten_weight < 0:
            raise ValueError("baseline_weight and shanten_weight must be non-negative")
        if self.honor_keep_weight < 0 or self.safe_tile_weight < 0:
            raise ValueError("honor_keep_weight and safe_tile_weight must be non-negative")


AGGRESSIVE = BotStyleConfig(
    baseline_weight=0.25,
    shanten_weight=1.0,
    chi_bias=2.0,
    pong_bias=2.0,
    kong_bias=1.5,
    honor_keep_weight=0.0,
)
MENZEN_DEFENSIVE = BotStyleConfig(
    baseline_weight=0.5,
    shanten_weight=0.5,
    chi_bias=-2.0,
    pong_bias=-1.5,
    kong_bias=-0.5,
    honor_keep_weight=1.0,
    safe_tile_weight=2.0,
)
BALANCED = BotStyleConfig(
    baseline_weight=1.0,
    shanten_weight=0.25,
    chi_bias=0.25,
    pong_bias=0.25,
    kong_bias=0.25,
    honor_keep_weight=0.1,
    safe_tile_weight=0.25,
)

BOT_STYLE_PRESETS = {
    "aggressive": AGGRESSIVE,
    "menzen_defensive": MENZEN_DEFENSIVE,
    "balanced": BALANCED,
}


def get_bot_style(name: str) -> BotStyleConfig:
    try:
        return BOT_STYLE_PRESETS[name]
    except KeyError as error:
        raise ValueError(
            f"unknown bot style {name!r}; choose from {', '.join(BOT_STYLE_PRESETS)}"
        ) from error


class WeightedPolicyWrapper:
    """Wrap BaselinePolicy and apply style preferences without inventing actions."""

    strategy_version = "baseline_style_wrapper_v1"

    def __init__(
        self,
        config: BotStyleConfig | str = BALANCED,
        *,
        baseline: BaselinePolicy | None = None,
    ) -> None:
        if isinstance(config, str):
            config = get_bot_style(config)
        if not isinstance(config, BotStyleConfig):
            raise TypeError("config must be BotStyleConfig or a style preset name")

        self.config = config
        self.baseline = baseline or BaselinePolicy()

    def decide(
        self,
        observation: Observation,
        legal_actions: LegalActions,
    ) -> Decision:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("legal_actions cannot be empty")

        baseline_decision = self.baseline.decide(observation, actions)
        self._require_legal(baseline_decision.action, actions)

        if any(action.action == ActionType.WIN for action in actions):
            return baseline_decision

        meld_actions = tuple(
            action for action in actions
            if action.action in (ActionType.CHI, ActionType.PONG, ActionType.KONG)
        )
        if meld_actions:
            chosen = self._choose_meld(
                observation,
                actions,
                meld_actions,
                baseline_decision.action,
            )
        else:
            discards = tuple(
                action for action in actions if action.action == ActionType.DISCARD
            )
            chosen = self._choose_discard(
                observation,
                actions,
                discards,
                baseline_decision.action,
            )

        self._require_legal(chosen, actions)
        return Decision(
            action=chosen,
            score=baseline_decision.score,
            reason=(
                f"{baseline_decision.reason}; style={self.config}; "
                f"selected={chosen.id}"
            ),
            candidate_evaluations=baseline_decision.candidate_evaluations,
        )

    def _choose_discard(
        self,
        observation: Observation,
        legal_actions: tuple[LegalAction, ...],
        discards: tuple[LegalAction, ...],
        baseline_action: LegalAction,
    ) -> LegalAction:
        if not discards:
            return baseline_action

        opponents = tuple(seat for seat in range(4) if seat != observation.seat)
        calculator = MeldShantenCalculator(
            len(observation.melds[observation.seat])
        )

        def rank(action: LegalAction) -> tuple[float, int]:
            tile = action.tile
            if tile is None or not 0 <= tile < 34:
                raise ValueError(f"invalid legal discard tile: {tile!r}")

            shanten = calculator.calculate(
                remove_discard(observation.hand, tile)
            )
            seen_safe = sum(
                tile in observation.discards[seat]
                for seat in opponents
            )
            score = (
                self.config.baseline_weight * (action == baseline_action)
                - self.config.shanten_weight * shanten
                - self.config.honor_keep_weight * (tile >= 27)
                + self.config.safe_tile_weight * seen_safe
            )
            # Prefer the original baseline recommendation on exact score ties.
            return score, int(action == baseline_action)

        return max(discards, key=rank)

    def _choose_meld(
        self,
        observation: Observation,
        legal_actions: tuple[LegalAction, ...],
        meld_actions: tuple[LegalAction, ...],
        baseline_action: LegalAction,
    ) -> LegalAction:
        pass_action = next(
            (action for action in legal_actions if action.action == ActionType.PASS),
            None,
        )
        meld_count = len(observation.melds[observation.seat])
        calculator = MeldShantenCalculator(meld_count)
        current_shanten = calculator.calculate(observation.hand)
        biases = {
            ActionType.CHI: self.config.chi_bias,
            ActionType.PONG: self.config.pong_bias,
            ActionType.KONG: self.config.kong_bias,
        }

        candidates: list[tuple[float, int, LegalAction]] = []
        if pass_action is not None:
            candidates.append((
                self.config.baseline_weight
                if pass_action == baseline_action
                else 0.0,
                int(pass_action == baseline_action),
                pass_action,
            ))

        for action in meld_actions:
            improvement = 0
            if action.action in (ActionType.CHI, ActionType.PONG):
                next_shanten, _, _ = evaluate_meld_details(
                    observation.hand,
                    action,
                    meld_count,
                )
                improvement = current_shanten - next_shanten
            score = (
                biases[action.action]
                + self.config.shanten_weight * improvement
                + self.config.baseline_weight * (action == baseline_action)
            )
            candidates.append((score, int(action == baseline_action), action))

        if not candidates:
            return baseline_action
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    @staticmethod
    def _require_legal(
        action: LegalAction,
        legal_actions: tuple[LegalAction, ...],
    ) -> None:
        if action not in legal_actions:
            raise ValueError("policy selected an action outside legal_actions")
