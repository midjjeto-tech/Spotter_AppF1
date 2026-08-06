"""Петля подтверждения: инженер предложил — пилот принял или отказался.

Что это МОЖЕТ и чего не может. Приложение не управляет игрой: «да» пилота не
заводит машину в боксы и не меняет режим ERS. Меняется поведение ИНЖЕНЕРА — он
подтверждает договорённость, перестаёт предлагать одно и то же и уважает отказ.
Это настоящий эффект, и обещать больше нельзя: подтверждение, за которым ничего
не следует, — худший вид фальши в такой системе.

Команды («замолчи», «повтори») уже разбираются `classify_command` ДО тем, и
«да»/«нет» туда добавлять нельзя: они утащили бы в команду любую обычную речь
пилота. Решение распознаётся отдельным классификатором и только тогда, когда
предложение реально висит.
"""
import pytest

from commentator import radio_answer
from core.radio import phrases, policy
from core.strategy_ai.agreement import StrategyAgreement


PROPOSAL = "STRAT_UNDERCUT"


@pytest.fixture
def deal():
    return StrategyAgreement(window=30.0, decline_cooldown=300.0)


# ── Распознавание решения ────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "да", "давай", "согласен", "подтверждаю", "поехали", "делаем",
])
def test_agreement_is_recognised(said):
    assert radio_answer.classify_decision(said) == "accept"


@pytest.mark.parametrize("said", [
    "нет", "не надо", "отставить", "остаёмся", "рано ещё",
])
def test_refusal_is_recognised(said):
    assert radio_answer.classify_decision(said) == "decline"


@pytest.mark.parametrize("said", [
    "какая погода", "нормально", "сколько кругов осталось", "",
])
def test_ordinary_speech_is_not_a_decision(said):
    assert radio_answer.classify_decision(said) is None


def test_decision_words_are_not_global_commands():
    """Ключевое: «да» и «нет» НЕ должны попасть в `classify_command`, иначе они
    перехватывали бы обычную речь пилота вне всякого предложения."""
    for said in ("да", "нет", "давай", "не надо"):
        assert radio_answer.classify_command(said) is None


# ── Окно решения ─────────────────────────────────────────────────────────────

def test_nothing_pending_by_default(deal):
    assert deal.pending(100.0) is None


def test_a_proposal_opens_the_window(deal):
    deal.propose(PROPOSAL, 100.0)
    assert deal.pending(110.0) == PROPOSAL


def test_the_window_closes_on_its_own(deal):
    """Молчание — это тоже ответ: пилот занят, и висеть в ожидании бесконечно
    нельзя, иначе «да» через десять минут примет давно неактуальный план."""
    deal.propose(PROPOSAL, 100.0)
    assert deal.pending(131.0) is None


def test_accepting_closes_the_window(deal):
    deal.propose(PROPOSAL, 100.0)
    assert deal.accept(110.0) == PROPOSAL
    assert deal.pending(111.0) is None


def test_accepting_nothing_is_not_an_error(deal):
    """Пилот сказал «да» без всякого предложения — это не решение, а реплика."""
    assert deal.accept(100.0) is None


# ── Эффект: предложение не повторяется ───────────────────────────────────────

def test_a_declined_proposal_is_not_repeated(deal):
    """Главный СМЫСЛ петли. Без него отказ ничего не меняет, и инженер
    продолжает предлагать то же самое — это ровно то поведение, ради отмены
    которого всё писалось."""
    deal.propose(PROPOSAL, 100.0)
    deal.decline(110.0)
    assert deal.is_suppressed(PROPOSAL, 120.0)


def test_the_refusal_expires(deal):
    """Отказ не вечен: обстановка меняется, и через несколько минут тот же
    андеркат может стать единственным разумным ходом."""
    deal.propose(PROPOSAL, 100.0)
    deal.decline(110.0)
    assert not deal.is_suppressed(PROPOSAL, 500.0)


def test_a_refusal_does_not_silence_other_proposals(deal):
    """Отказ от андерката — не отказ от всего. Иначе одно «нет» выключало бы
    стратегию целиком."""
    deal.propose(PROPOSAL, 100.0)
    deal.decline(110.0)
    assert not deal.is_suppressed("STRAT_OVERCUT", 120.0)


def test_an_accepted_proposal_is_not_repeated_either(deal):
    """Договорились — значит договорились. Повторять принятое так же назойливо,
    как повторять отклонённое."""
    deal.propose(PROPOSAL, 100.0)
    deal.accept(110.0)
    assert deal.is_suppressed(PROPOSAL, 120.0)


def test_ignoring_a_proposal_lets_it_return(deal):
    """Пилот промолчал — договорённости нет, и предложить снова законно: он мог
    просто не услышать."""
    deal.propose(PROPOSAL, 100.0)
    assert not deal.is_suppressed(PROPOSAL, 200.0)


def test_reset_forgets_everything(deal):
    deal.propose(PROPOSAL, 100.0)
    deal.decline(110.0)
    deal.reset()
    assert not deal.is_suppressed(PROPOSAL, 120.0)
    assert deal.pending(120.0) is None


# ── Что вообще можно предлагать ──────────────────────────────────────────────

def test_pit_commands_are_not_proposals():
    """«Бокс, бокс» — команда, а не предложение к обсуждению. Спрашивать на неё
    согласия значит превратить безопасную команду в переговоры."""
    for code in ("STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3"):
        assert not policy.is_proposal(code), code


def test_strategy_suggestions_are_proposals():
    for code in ("STRAT_UNDERCUT", "STRAT_OVERCUT", "PIT_CALL_NOTICE"):
        assert policy.is_proposal(code), code


def test_reply_specs_exist_in_the_bank():
    for code in ("decision.accepted", "decision.declined"):
        assert code in phrases.codes(), code


def test_confirmation_never_promises_an_action():
    """Приложение игрой не управляет: «заезжаем» или «уже готово» были бы
    обещанием того, что не произойдёт. Подтверждать можно только ПЛАН."""
    forbidden = ("заезжа", "заводим", "уже гото", "выполня", "меняем резину")
    for code in ("decision.accepted", "decision.declined"):
        spec = phrases.spec_for(code)
        for pool in [spec.variants, *spec.character_variants.values()]:
            for variant in pool:
                low = variant.lower()
                assert not any(bad in low for bad in forbidden), variant


# ── Проводка ─────────────────────────────────────────────────────────────────

@pytest.fixture
def engine(monkeypatch):
    import core.engine as eng_mod
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = eng_mod.F1Engine({})
    return e


def test_no_pending_proposal_means_ordinary_speech(engine):
    """Без висящего предложения «да» — обычная реплика, а не согласие."""
    assert engine._resolve_strategy_decision("да") is None


def _pool(code: str) -> set[str]:
    spec = phrases.spec_for(code)
    return {v for pool in [spec.variants, *spec.character_variants.values()]
            for v in pool}


def test_accepting_a_live_proposal_is_confirmed(engine):
    import time as _time
    now = _time.time()
    engine._strategy_agreement.propose("STRAT_UNDERCUT", now)

    answer = engine._resolve_strategy_decision("давай")

    assert answer, "инженер промолчал в ответ на согласие"
    assert answer in _pool("decision.accepted"), answer
    # Согласие тоже закрывает вопрос: договорились — не предлагаем снова.
    assert engine._strategy_agreement.is_suppressed("STRAT_UNDERCUT", now + 10)


def test_the_refusal_answer_comes_from_the_declined_pool(engine):
    """Перепутать пулы значит ответить «работаем по этому плану» на «нет» —
    прямое непонимание пилота."""
    import time as _time
    engine._strategy_agreement.propose("STRAT_UNDERCUT", _time.time())
    answer = engine._resolve_strategy_decision("не надо")
    assert answer in _pool("decision.declined"), answer


def test_declining_suppresses_the_repeat(engine):
    """Тот самый эффект, ради которого петля существует."""
    import time as _time
    now = _time.time()
    engine._strategy_agreement.propose("STRAT_UNDERCUT", now)
    assert engine._resolve_strategy_decision("нет") is not None
    assert engine._strategy_agreement.is_suppressed("STRAT_UNDERCUT", now + 10)


def test_an_unrelated_question_during_a_proposal_is_not_a_decision(engine):
    """Пилот спросил про погоду, пока висит предложение — это вопрос, и
    съедать его как «нет» нельзя."""
    import time as _time
    engine._strategy_agreement.propose("STRAT_UNDERCUT", _time.time())
    assert engine._resolve_strategy_decision("какая погода") is None
