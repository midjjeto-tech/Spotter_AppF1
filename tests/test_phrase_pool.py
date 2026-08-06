"""Non-repeating phrase decks shared by commentary and engineer channels."""
from __future__ import annotations

import random

from commentator.phrase_pool import PhraseDeck


def test_deck_exhausts_pool_before_repeating():
    random.seed(7)
    deck = PhraseDeck()
    pool = ["one", "two", "three", "four"]

    first_cycle = [deck.pick(pool, "event") for _ in pool]

    assert set(first_cycle) == set(pool)
    assert len(first_cycle) == len(set(first_cycle))


def test_deck_does_not_repeat_at_refill_boundary():
    random.seed(11)
    deck = PhraseDeck()
    pool = ["one", "two", "three"]

    draws = [deck.pick(pool, "event") for _ in range(len(pool) + 1)]

    assert draws[-1] != draws[-2]


def test_keys_have_independent_cycles():
    deck = PhraseDeck()

    assert deck.pick(["a"], "commentary") == "a"
    assert deck.pick(["b"], "engineer") == "b"


def test_reset_starts_fresh_decks():
    deck = PhraseDeck()
    deck.pick(["a", "b"], "event")

    deck.reset()

    assert deck._remaining == {}
    assert deck._last == {}
