"""Наполняет core/openf1_seed.py::SECTOR_SEED реальными секторными эталонами
из OpenF1. Одноразовый/редко запускаемый dev-инструмент — печатает готовый
Python-литерал в stdout, вставка в openf1_seed.py вручную. Перезапустить с
другим YEAR, когда понадобится обновить сид (например, после завершения
следующего сезона). Не часть приложения — не импортируется и не вшивается в EXE."""
from __future__ import annotations

from analytics.loader import TRACK_ID_TO_GP
from core.f1_benchmark import TRACK_ID_TO_CIRCUIT
from core.openf1_client import OpenF1Client

YEAR = 2025
MAX_SECTOR_MS = 90_000   # санити-фильтр: сектор длиннее 90с — считаем мусором


def main() -> None:
    client = OpenF1Client()
    seed: dict[str, dict] = {}
    for track_id, circuit_id in sorted(TRACK_ID_TO_CIRCUIT.items()):
        gp_name = TRACK_ID_TO_GP.get(track_id, ("", ""))[1]
        session_key = client.get_session_key(YEAR, circuit_id)
        if session_key is None:
            reason = "заблокирован (live-сессия)" if client.blocked_by_live_session else "нет session_key"
            print(f"# {circuit_id}: пропущена — {reason}")
            continue
        sectors = client.get_best_sectors(session_key)
        if sectors is None:
            print(f"# {circuit_id}: пропущена — нет валидных секторов")
            continue
        if any(not (0 < ms <= MAX_SECTOR_MS) for ms in sectors.values()):
            print(f"# {circuit_id}: пропущена — санити-фильтр не пройден ({sectors})")
            continue
        seed[circuit_id] = {"year": YEAR, "event": gp_name, "sectors": sectors}

    print("\nSECTOR_SEED: dict[str, dict] = {")
    for circuit_id, entry in seed.items():
        print(f'    "{circuit_id}": {entry!r},')
    print("}")
    print(f"\n# Итого: {len(seed)}/{len(TRACK_ID_TO_CIRCUIT)} трасс")


if __name__ == "__main__":
    main()
