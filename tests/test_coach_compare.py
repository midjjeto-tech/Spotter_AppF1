"""Нормализованное сравнение с эталоном (core/coach_ai/compare.py).

Тесты на нормализацию здесь — главные: именно она отличает полезный коуч от
бесполезного, который сообщает «ты медленнее везде».
"""
from core.coach_ai.compare import compare_lap, corner_deltas
from core.coach_ai.models import CornerMetrics


def _lap(spec: dict) -> dict[int, CornerMetrics]:
    """spec: {corner_id: (brake_m, min_speed, throttle_m, duration_ms)}"""
    return {cid: CornerMetrics(cid, *vals) for cid, vals in spec.items()}


def _flat(n: int, duration: int) -> dict:
    return {i: (100.0 * i, 120.0, 100.0 * i + 40, duration) for i in range(1, n + 1)}


def test_uniform_slowness_produces_no_advice():
    """Медленнее на полсекунды в КАЖДОМ повороте — это топливо, не техника."""
    ref = _lap(_flat(8, 4000))
    cur = _lap(_flat(8, 4500))

    assert compare_lap(cur, ref, {}) is None


def test_local_loss_is_reported_even_under_uniform_slowness():
    """Общее отставание есть, но в третьем повороте оно кратно больше — вот это
    уже техника, и об этом стоит сказать."""
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4500)
    spec[3] = (300.0, 120.0, 340.0, 6000)
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {3: "Turn 3"})

    assert advice is not None
    assert advice.corner_id == 3
    assert advice.metric == "duration"
    assert advice.corner_name == "Turn 3"
    assert advice.badness > 0


def test_too_few_comparable_corners_stays_silent():
    """Меньше пяти общих поворотов — медиана неустойчива, молчим."""
    ref = _lap(_flat(4, 4000))
    spec = _flat(4, 4000)
    spec[3] = (300.0, 120.0, 340.0, 6000)
    cur = _lap(spec)

    assert compare_lap(cur, ref, {}) is None


def test_early_braking_is_reported():
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[5] = (500.0 - 30.0, 120.0, 540.0, 4000)   # тормозит на 30 м раньше
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice.corner_id == 5
    assert advice.metric == "brake"
    assert advice.raw < 0


def test_later_braking_than_reference_is_not_a_mistake():
    """Тормозить ПОЗЖЕ эталона — прогресс, а не ошибка. Молчим."""
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[5] = (500.0 + 30.0, 120.0, 540.0, 4000)
    cur = _lap(spec)

    assert compare_lap(cur, ref, {}) is None


def test_uniform_early_braking_is_fuel_not_technique():
    """Тяжёлая машина тормозит раньше в КАЖДОМ повороте. Нормализация обязана
    съедать это так же, как общее отставание по времени."""
    ref = _lap(_flat(8, 4000))
    cur = _lap({i: (100.0 * i - 25.0, 120.0, 100.0 * i + 40, 4000)
                for i in range(1, 9)})

    assert compare_lap(cur, ref, {}) is None


def test_slow_apex_is_reported():
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[2] = (200.0, 100.0, 240.0, 4000)   # на 20 км/ч медленнее в апексе
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice.corner_id == 2
    assert advice.metric == "min_speed"


def test_late_throttle_is_reported():
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[6] = (600.0, 120.0, 640.0 + 40.0, 4000)
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice.corner_id == 6
    assert advice.metric == "throttle"
    assert advice.raw > 0


def test_missing_metric_on_either_side_is_skipped():
    """Пологая связка без торможения не должна давать сравнение по тормозу."""
    ref = _lap(_flat(8, 4000))
    ref[4] = CornerMetrics(4, None, 120.0, 440.0, 4000)
    spec = _flat(8, 4000)
    spec[4] = (0.0, 120.0, 440.0, 4000)
    cur = _lap(spec)

    assert compare_lap(cur, ref, {}) is None


def test_corner_absent_from_reference_is_skipped():
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[99] = (9900.0, 60.0, 9940.0, 9000)
    cur = _lap(spec)

    assert compare_lap(cur, ref, {}) is None


# ── Причина важнее следствия ─────────────────────────────────────────────────
# `duration` отвечает на вопрос ГДЕ, три остальные метрики — на вопрос ЧТО
# ДЕЛАТЬ. Пока все четыре ранжировались вместе, коуч на реальном раскладе
# говорил «этот поворот стоит тебе времени», ХОТЯ ЗНАЛ, что пилот тормозит рано.

def test_the_cause_is_named_instead_of_the_lost_time():
    """Пилот тормозит на 25 м раньше в седьмом и теряет там же 400 мс сверх
    общего отставания. По отношению к порогам `duration` выигрывала (2.7 против
    2.1), и подсказка выходила бесполезной: «теряешь время» пилот и сам
    чувствует, а вот «тормоз можно оттянуть» — это указание."""
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4300)
    spec[7] = (700.0 - 25.0, 120.0, 740.0, 4700)
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice is not None
    assert advice.corner_id == 7
    assert advice.metric == "brake"


def test_lost_time_is_still_reported_when_no_cause_explains_it():
    """Обратная сторона: если ни одна причинная метрика не вышла за свой порог,
    молчать нельзя — «здесь уходит основное время» остаётся честным ответом
    последней надежды."""
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[5] = (500.0, 120.0, 540.0, 4800)   # только длительность, вводы как в эталоне
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice is not None
    assert advice.corner_id == 5
    assert advice.metric == "duration"


def test_a_weak_cause_still_beats_the_symptom():
    """Причина сразу за своим порогом обыгрывает следствие далеко за своим — и
    это осознанный размен: слабое, но применимое указание полезнее сильной
    констатации. Если живой заезд покажет, что причины срабатывают слишком
    охотно, поднимать надо ИХ пороги, а не возвращать соревнование."""
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[2] = (200.0 - 13.0, 120.0, 240.0, 5000)   # 13 м при пороге 12
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice.metric == "brake"


def test_deltas_table_covers_every_common_corner():
    ref = _lap(_flat(8, 4000))
    cur = _lap(_flat(8, 4200))

    rows = corner_deltas(cur, ref, {})

    assert len(rows) == 8
    assert all(r["duration_ms"] == 200 for r in rows)
    assert all(r["brake_delta"] == 0 for r in rows)


def test_deltas_table_reports_none_for_missing_metric():
    ref = _lap(_flat(8, 4000))
    ref[4] = CornerMetrics(4, None, 120.0, 440.0, 4000)
    cur = _lap(_flat(8, 4000))

    row = next(r for r in corner_deltas(cur, ref, {}) if r["corner_id"] == 4)

    assert row["brake_delta"] is None
    assert row["duration_ms"] == 0
