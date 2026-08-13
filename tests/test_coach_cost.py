"""Цена ошибки в миллисекундах (core/coach_ai/cost.py).

Главные тесты здесь — те же, что у нормализации в compare.py: цена, которая
появляется у ВСЕХ поворотов сразу, бесполезна ровно так же, как совет «ты
медленнее везде». Плюс отдельная группа на потенциал круга: он обещает пилоту
достижимое время, и обещание должно быть честным.
"""
from core.coach_ai import cost as cost_mod
from core.coach_ai.cost import CornerHistory
from core.coach_ai.models import CornerMetrics


def _corners(spec: dict[int, int]) -> dict[int, CornerMetrics]:
    """spec: {corner_id: duration_ms}. Остальные метрики для цены не нужны."""
    return {
        cid: CornerMetrics(corner_id=cid, brake_point_m=100.0 * cid,
                           min_speed_kmh=120.0, throttle_point_m=100.0 * cid + 40,
                           duration_ms=duration)
        for cid, duration in spec.items()
    }


def _flat(n: int, duration: int) -> dict[int, int]:
    return {i: duration for i in range(1, n + 1)}


def _history(laps: list[dict[int, int]], lap_time_ms: int = 90_000) -> CornerHistory:
    history = CornerHistory()
    for number, spec in enumerate(laps, start=1):
        history.add_lap(number, lap_time_ms, _corners(spec))
    return history


# ── Цена поворота ────────────────────────────────────────────────────────────

def test_uniform_slowness_costs_nothing():
    """Медленнее на 300 мс в КАЖДОМ повороте — это топливо и резина.

    Если бы нормализация здесь не работала, у каждого поворота появилась бы своя
    «цена», сумма надулась бы вдвое против реальной потери круга, и доля каждого
    поворота потеряла бы смысл — а именно по доле пилот выбирает, чем заняться.
    """
    reference = _corners(_flat(8, 4000))
    history = _history([_flat(8, 4300)] * 5)

    assert history.costs(reference) == []


def test_local_loss_is_priced_even_under_uniform_slowness():
    """Общее отставание есть, но в третьем оно кратно больше — вот это техника."""
    reference = _corners(_flat(8, 4000))
    laps = []
    for _ in range(5):
        spec = _flat(8, 4300)
        spec[3] = 4700          # +700 к эталону, из них 300 — общий сдвиг круга
        laps.append(spec)
    history = _history(laps)

    costs = history.costs(reference, {3: "Turn 3"})

    assert [c.corner_id for c in costs] == [3]
    assert costs[0].cost_ms == 400.0
    assert costs[0].corner_name == "Turn 3"
    assert costs[0].laps == 5


def test_costs_are_sorted_by_price():
    reference = _corners(_flat(8, 4000))
    laps = []
    for _ in range(5):
        spec = _flat(8, 4000)
        spec[2] = 4150
        spec[6] = 4400
        laps.append(spec)
    history = _history(laps)

    costs = history.costs(reference)

    assert [c.corner_id for c in costs] == [6, 2]
    assert costs[0].cost_ms > costs[1].cost_ms


def test_shares_sum_to_one():
    """Доля отвечает на вопрос «сколько внимания сюда» и обязана быть замкнутой."""
    reference = _corners(_flat(8, 4000))
    laps = []
    for _ in range(5):
        spec = _flat(8, 4000)
        spec[2] = 4150
        spec[6] = 4400
        laps.append(spec)
    history = _history(laps)

    costs = history.costs(reference)

    assert abs(sum(c.share for c in costs) - 1.0) < 1e-6


def test_one_bad_lap_does_not_create_a_cost():
    """Медиана, а не худшее: разовый вылет — не привычка.

    Это ровно та граница, за которой коуч превращается в сирену: разовую ошибку
    пилот почувствовал сам, и назначать за неё главную работу сессии нельзя.
    """
    reference = _corners(_flat(8, 4000))
    laps = [_flat(8, 4000) for _ in range(5)]
    laps[2] = dict(laps[2])
    laps[2][4] = 7000           # один катастрофический проезд
    history = _history(laps)

    assert [c.corner_id for c in history.costs(reference)] == []


def test_loss_below_noise_threshold_is_not_a_cost():
    reference = _corners(_flat(8, 4000))
    laps = []
    for _ in range(5):
        spec = _flat(8, 4000)
        spec[5] = 4000 + int(cost_mod.MIN_COST_MS) - 5
        laps.append(spec)
    history = _history(laps)

    assert history.costs(reference) == []


def test_too_few_laps_is_silence():
    reference = _corners(_flat(8, 4000))
    laps = []
    for _ in range(cost_mod.MIN_LAPS - 1):
        spec = _flat(8, 4000)
        spec[3] = 4500
        laps.append(spec)
    history = _history(laps)

    assert history.costs(reference) == []


def test_too_few_comparable_corners_is_silence():
    """Меньше пяти общих поворотов — медиана круга неустойчива.

    Ровно тот же порог и та же причина, что в compare.py: считать нормализацию
    по трём точкам значит выдавать шум за вывод.
    """
    n = cost_mod.MIN_COMPARABLE_CORNERS - 1
    reference = _corners(_flat(n, 4000))
    laps = []
    for _ in range(5):
        spec = _flat(n, 4000)
        spec[2] = 4500
        laps.append(spec)
    history = _history(laps)

    assert history.costs(reference) == []


def test_corner_missing_from_reference_is_skipped():
    """Поворот, которого нет в эталоне, сравнивать не с чем."""
    reference = _corners(_flat(8, 4000))
    laps = []
    for _ in range(5):
        spec = _flat(8, 4000)
        spec[99] = 9000          # новый поворот, в эталоне отсутствует
        laps.append(spec)
    history = _history(laps)

    assert [c.corner_id for c in history.costs(reference)] == []


def test_faster_than_reference_is_not_a_negative_cost():
    """Быстрее эталона — это не «отрицательная потеря», это просто не потеря."""
    reference = _corners(_flat(8, 4000))
    laps = []
    for _ in range(5):
        spec = _flat(8, 4000)
        spec[3] = 3600
        laps.append(spec)
    history = _history(laps)

    assert history.costs(reference) == []


def test_empty_reference_is_silence():
    assert _history([_flat(8, 4000)] * 5).costs({}) == []


def test_pit_style_broken_lap_is_never_recorded_without_time():
    history = CornerHistory()
    history.add_lap(1, 0, _corners(_flat(8, 4000)))
    history.add_lap(2, 90_000, {})

    assert history.lap_count == 0


def test_history_window_is_bounded():
    history = CornerHistory()
    for lap in range(CornerHistory.MAX_LAPS + 20):
        history.add_lap(lap, 90_000, _corners(_flat(8, 4000)))

    assert history.lap_count == CornerHistory.MAX_LAPS


# ── Потенциал круга ──────────────────────────────────────────────────────────

# Потенциал нормализуется по кругу так же, как цена поворота, и по той же
# причине — значит и порог тот же: круг, на котором сравнимых поворотов меньше
# MIN_COMPARABLE_CORNERS, в расчёт не идёт. Поэтому в тестах ниже по пять
# поворотов, а не по два-три: с тремя медиана круга — это не сдвиг круга, а шум.

def test_potential_sums_the_drivers_own_best_corners():
    """Потенциал собирается из СВОИХ лучших проездов, а не из чужого темпа."""
    history = CornerHistory()
    history.add_lap(1, 90_000, _corners({1: 4000, 2: 4000, 3: 4000, 4: 4000, 5: 4000}))
    history.add_lap(2, 89_000, _corners({1: 3800, 2: 4000, 3: 4000, 4: 4000, 5: 4000}))
    history.add_lap(3, 89_500, _corners({1: 4000, 2: 3700, 3: 4000, 4: 4000, 5: 4000}))

    potential = history.potential()

    assert potential is not None
    assert potential.best_lap_ms == 89_000
    # На лучшем круге первый поворот уже был лучшим (3800), а второй проехан на
    # 300 мс хуже собственного лучшего — вот и весь запас.
    assert potential.gain_ms == 300
    assert potential.potential_ms == 88_700
    assert potential.corners_counted == 5
    assert potential.clamped is False


def test_potential_ignores_a_corner_driven_only_once():
    """Один проезд — это не «лучший проезд», это единственный замер."""
    history = CornerHistory()
    history.add_lap(1, 90_000, _corners(_flat(5, 4000)))
    history.add_lap(2, 89_000, _corners({**_flat(5, 4000), 9: 9000}))
    history.add_lap(3, 89_500, _corners({1: 3500, 2: 4000, 3: 4000, 4: 4000, 5: 4000}))

    potential = history.potential()

    assert potential is not None
    assert potential.corners_counted == 5      # девятый не в счёт
    assert potential.gain_ms == 500


def test_potential_clamps_an_impossible_single_corner_gain_and_says_so():
    """Больше двух секунд в одном повороте — это разворот или сбитый замер.

    Обещать круг, собранный из такого «запаса», нельзя: пилот его не проедет.
    Ограничение отражается в отчёте, а не прячется.
    """
    history = CornerHistory()
    history.add_lap(1, 95_000, _corners(_flat(5, 4000)))
    history.add_lap(2, 94_000, _corners({1: 9000, 2: 4000, 3: 4000, 4: 4000, 5: 4000}))
    history.add_lap(3, 94_500, _corners(_flat(5, 4000)))

    potential = history.potential()

    assert potential is not None
    assert potential.clamped is True
    assert potential.gain_ms == int(cost_mod.MAX_CORNER_GAIN_MS)


def test_potential_needs_laps():
    history = CornerHistory()
    history.add_lap(1, 90_000, _corners(_flat(5, 4000)))

    assert history.potential() is None


def test_potential_ignores_laps_with_too_few_comparable_corners():
    """Три поворота на круге — не сдвиг круга, а шум. Такой круг не участвует."""
    history = CornerHistory()
    for lap in range(1, 5):
        history.add_lap(lap, 90_000 - lap, _corners({1: 4000, 2: 4000, 3: 4000}))

    assert history.potential() is None


def test_uniform_lap_wide_drift_is_not_a_potential():
    """Топливо и резина двигают ВСЕ повороты сразу — это не запас техники.

    Ровно та же проверка, что у цены поворота выше, и ровно та же причина:
    без вычитания общего сдвига круга дрейф сессии копится в «потенциал». В
    живом заезде 2026-08-11 это дало 11418 мс обещанного запаса при 932 мс
    фактически найденных потерь.
    """
    history = CornerHistory()
    # Пилот едет одинаково, машина легчает: каждый круг быстрее предыдущего на
    # одну и ту же величину в КАЖДОМ повороте.
    for lap, shift in enumerate([300, 200, 100, 0], start=1):
        history.add_lap(lap, 92_000 - lap * 100,
                        _corners({cid: 4000 + shift for cid in range(1, 6)}))

    potential = history.potential()

    assert potential is not None
    assert potential.gain_ms == 0
    assert potential.potential_ms == potential.best_lap_ms


def test_potential_is_faster_than_the_best_lap_but_still_positive():
    history = _history([
        {1: 4000, 2: 4200, 3: 4100, 4: 4000, 5: 4000},
        {1: 3900, 2: 4100, 3: 4000, 4: 4000, 5: 4000},
        {1: 3950, 2: 4000, 3: 4050, 4: 4000, 5: 4000},
    ], lap_time_ms=91_000)

    potential = history.potential()

    assert potential is not None
    assert 0 < potential.potential_ms < potential.best_lap_ms


def test_reset_clears_history():
    history = _history([_flat(8, 4000)] * 5)
    history.reset()

    assert history.lap_count == 0
    assert history.potential() is None
