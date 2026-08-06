"""Session-aware phrase selection without the usual template-mode repetition.

Each logical pool is played as a shuffled deck: every line is used once before
the deck is refilled.  Refills avoid repeating the line at the cycle boundary.
The global deck is intentionally shared by commentary and engineer channels so
the whole spoken experience can be reshuffled when a new race starts.
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class PhraseDeck:
    """Draw phrases from keyed shuffle bags, safely across worker threads."""

    _remaining: dict[str, list[str]] = field(default_factory=dict)
    _signatures: dict[str, tuple[str, ...]] = field(default_factory=dict)
    _last: dict[str, str] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def pick(self, pool: Sequence[str], key: str) -> str:
        if not pool:
            return ""

        signature = tuple(pool)
        if len(signature) == 1:
            return signature[0]

        with self._lock:
            remaining = self._remaining.get(key)
            if not remaining or self._signatures.get(key) != signature:
                remaining = list(signature)
                random.shuffle(remaining)

                # draw() pops from the end.  Keep a refill from starting with
                # the line that ended the previous cycle.
                if remaining[-1] == self._last.get(key):
                    swap_idx = next((
                        i for i, phrase in enumerate(remaining[:-1])
                        if phrase != remaining[-1]
                    ), None)
                    if swap_idx is not None:
                        remaining[-1], remaining[swap_idx] = (
                            remaining[swap_idx], remaining[-1]
                        )

                self._remaining[key] = remaining
                self._signatures[key] = signature

            phrase = remaining.pop()
            self._last[key] = phrase
            return phrase

    def reset(self) -> None:
        """Forget all decks so the next race gets a newly shuffled delivery."""
        with self._lock:
            self._remaining.clear()
            self._signatures.clear()
            self._last.clear()


_DECK = PhraseDeck()


def pick_phrase(pool: Sequence[str], key: str) -> str:
    return _DECK.pick(pool, key)


def reset_phrase_cycles() -> None:
    _DECK.reset()
