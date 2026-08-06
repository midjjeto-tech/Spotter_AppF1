"""core/broadcast/models.py — BroadcastMessage dataclass."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BroadcastMessage:
    text: str
    style: str    # persona used: "tv"|"hype"|"calm"|"toxic"
    priority: str # "high"|"medium"|"low"
    source: str   # "llm" | "template"
