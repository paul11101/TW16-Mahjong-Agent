"""Reproducible, weighted selection of four-seat Bot lineups."""

from __future__ import annotations

import random
from math import isfinite
from typing import Mapping

from src.rules.weighted_policy import BOT_STYLE_PRESETS, WeightedPolicyWrapper

SEAT_NAMES = ("east", "south", "west", "north")
DEFAULT_OPPONENT_WEIGHTS = {
    "aggressive": 1.0,
    "menzen_defensive": 1.0,
    "balanced": 1.0,
}


class OpponentPool:
    """Sample each seat independently according to configured style weights."""

    def __init__(self, weights: Mapping[str, float] | None = None) -> None:
        configured = dict(DEFAULT_OPPONENT_WEIGHTS if weights is None else weights)
        if not configured:
            raise ValueError("opponent pool cannot be empty")

        for style, weight in configured.items():
            if style not in BOT_STYLE_PRESETS:
                raise ValueError(f"unknown opponent style: {style}")
            if (
                type(weight) not in (int, float)
                or not isfinite(weight)
                or weight < 0
            ):
                raise ValueError(
                    f"opponent weight for {style} must be finite and non-negative"
                )
        if not any(weight > 0 for weight in configured.values()):
            raise ValueError("at least one opponent weight must be positive")

        self.weights = configured
        self._styles = tuple(
            style for style, weight in configured.items() if weight > 0
        )
        scale = max(configured[style] for style in self._styles)
        cumulative: list[float] = []
        total = 0.0
        for style in self._styles:
            total += configured[style] / scale
            cumulative.append(total)
        self._cumulative_weights = tuple(cumulative)

    def sample_styles(self, seed: int) -> tuple[str, str, str, str]:
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a non-negative integer")

        rng = random.Random(seed)
        total = self._cumulative_weights[-1]
        selected: list[str] = []
        for _ in range(4):
            point = rng.random() * total
            selected_style = self._styles[-1]
            for style, boundary in zip(self._styles, self._cumulative_weights):
                if point < boundary:
                    selected_style = style
                    break
            selected.append(selected_style)
        return selected[0], selected[1], selected[2], selected[3]

    def create_policies(
        self,
        seed: int,
    ) -> tuple[tuple[str, str, str, str], tuple[WeightedPolicyWrapper, ...]]:
        styles = self.sample_styles(seed)
        policies = tuple(WeightedPolicyWrapper(style) for style in styles)
        return styles, policies
