"""
voice/tts.py
============
Озвучка через Piper (ONNX, CPU, нативный русский). Резерв — pyttsx3.
Streaming: синтез по предложениям, первый звук играет, пока генерится остальное.
Кэш фраз на диск (voice/cache.py) — повтор без синтеза. Кэш хранит «сухой»
звук; радио-эффект (voice/radio_fx.py) накладывается при воспроизведении.
Queue: события не перебивают и не накладываются.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Callable

import config
from voice.cache import TTSCache
from voice import radio_fx
from commentator.templates import SIMPLE
from new_tts.piper_tts import PiperVoiceEngine, PERSONA_VOICE
from new_tts.queue_handler import TTSQueue
from core.radio import voice_cast
from yandex_ai import voices

_log = logging.getLogger(__name__)

#: Персоны КОММЕНТАТОРА — единственное, что принимает set_persona(). Слоты
#: ролей (engineer/spotter) лежат в том же PERSONA_VOICE, поэтому прежней
#: проверки `persona in PERSONA_VOICE` стало недостаточно.
#: Литералы, а не импорт core.radio.voice_cast: voice/ не должен зависеть от
#: радио-конвейера, иначе тесты озвучки потянут его целиком.
_COMMENTATOR_PERSONAS: frozenset[str] = frozenset({"tv", "hype", "calm", "toxic"})

#: Слоты, звучащие ЧЕРЕЗ РАЦИЮ. Телекомментатор ведёт эфир, а не переговоры на
#: командной частоте, поэтому bandpass и щелчки к нему не применяются — это
#: разделяет каналы на слух раньше тембра и работает даже при совпавших
#: голосах. Строки, а не импорт voice_cast: voice/ не должен зависеть от
#: core.radio (иначе тесты озвучки тянут радио-конвейер).
_RADIO_SLOTS: frozenset[str] = frozenset({"engineer", "spotter"})


class Voice:
    def __init__(self, *_args, **_kwargs):
        self._engine = PiperVoiceEngine()
        self.pyttsx3_engine = None
        self.status_message = "Голос не запущен"
        # version tag invalidates stale cache. Bump on engine/voice/normalizer change.
        # v2: Ruslan default + расширенный ru_textnorm (англ.→кириллица, год→порядковое)
        # yandex-v2: фолбэк-аудио Piper больше не пишется в Yandex-ключ — старый
        #            «отравленный» кэш (Piper под y:-ключом) инвалидируется бампом.
        # yandex-v3 (07-08): core/pronunciation.py (04-07, ударение «Ферст+аппен» для
        #            Yandex) поменял ТЕКСТ, уходящий в TTS, но версию кэша тогда не
        #            бампнули — cache key = hash(version+text+speaker) не видит эту правку,
        #            поэтому WAV с "Ферстаппен", закэшированные ДО 04-07, продолжали
        #            звучать со старым произношением бесконечно (найдено при повторной
        #            жалобе 07-08 — код apply_yandex() был верным оба прошлых раза,
        #            проблема была не в нём, а в том, что кэш эту правку не инвалидировал).
        # yandex-v4 (07-09): core/pronunciation.py правка ТЕКСТА снова (убран
        #            ручной '+' для "ферстаппен", добавлен для "бортолето") —
        #            бампаем сразу в этот раз, не наступая на грабли yandex-v3.
        # yandex-v5 (07-21): явные ударения для Серхио Переса, Ландо Норриса и
        #            Макса Ферстаппена; Piper получил отдельные проверенные respell.
        # yandex-v6 (07-21): Jolpica/LLM-формы с латиницей и диакритикой
        #            (Sergio Pérez и остальные пилоты) приводятся к русским именам
        #            на общей границе TTS; старые WAV с побуквенным чтением невалидны.
        self._cache = TTSCache(os.path.join(config.DATA_DIR, "tts_cache"), version="yandex-v6")
        self._queue: TTSQueue | None = None
        self._queue_lock = threading.Lock()
        self._current_persona = "tv"
        self._radio_enabled = True
        self._global_vol: int = 80
        self._persona_vol: dict[str, int] = {}
        self._yandex = None                 # YandexSpeech | None (ставится из engine)
        self._voice_overrides: dict = {}    # персона -> {voice/emotion/speed}
        self._last_engine: str = ""         # движок, реально выдавший последнюю фразу
        self._last_fallback: bool = False   # Yandex прицеплен, но фраза ушла на Piper
        self._yandex_healthy: bool = True   # health-monitor (engine) пушит реальное значение
        self._health_reporter = None        # callback(ok: bool) — кормит health-monitor
        self._stream_lock = threading.Lock()
        self._current_stream = None         # активный sd.OutputStream (_play_wav), если есть
        # Наблюдатель реальных событий воспроизведения (см. set_playback_observer).
        self._playback_observer: Callable[[str, str | None], None] | None = None
        self._stop_event = threading.Event()
        self._setup_thread: threading.Thread | None = None
        self._prewarm_thread: threading.Thread | None = None
        self._started = False
        self._stopped = False

    def start(self) -> None:
        """Start voice resources explicitly; safe to call more than once."""
        if self._started or self._stopped:
            return
        self._started = True
        self.status_message = "Загрузка Piper..."
        self._configure_stdout()
        removed = self._cache.cleanup_tmp()
        if removed:
            _log.info("Removed %d stale .tmp files from TTS cache", removed)
        self._engine.start()
        self._setup_thread = threading.Thread(
            target=self._wait_and_setup, daemon=True, name="tts-setup")
        self._setup_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Cancel pending work and release audio/model resources boundedly."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        self._interrupt_playback()
        queue_obj = self._queue
        if queue_obj is not None:
            queue_obj.stop(timeout=min(timeout, 1.0))
        self._engine.stop(timeout=min(timeout, 1.0))
        deadline = time.monotonic() + max(0.0, timeout)
        for thread in (self._setup_thread, self._prewarm_thread):
            if thread is None or thread is threading.current_thread():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if self.pyttsx3_engine is not None:
            try:
                self.pyttsx3_engine.stop()
            except Exception:  # noqa: BLE001
                pass
        self.status_message = "Голос остановлен"

    def _configure_stdout(self) -> None:
        stdout = getattr(sys, "stdout", None)
        encoding = getattr(stdout, "encoding", None)
        if encoding is None or encoding.lower() != "utf-8":
            try:
                if stdout is not None:
                    stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

    def _wait_and_setup(self) -> None:
        """Ждёт загрузки Piper, затем создаёт Queue (если ещё нет) и прогревает кэш.
        Если Yandex уже активен, очередь создана в set_yandex — Piper лишь резерв."""
        self._engine.wait_until_ready(timeout=120.0)

        if self._stop_event.is_set():
            return

        if self._engine.is_ready:
            self._ensure_queue()
            self.status_message = getattr(self._engine, "status", "")
            self._prewarm_thread = threading.Thread(
                target=self._prewarm_cache, daemon=True, name="tts-prewarm")
            self._prewarm_thread.start()
        elif self._queue is None:
            # Piper не загрузился и Yandex не активен — пробуем pyttsx3-резерв.
            engine_err = getattr(self._engine, "status", "")
            self._init_pyttsx3()
            if self.pyttsx3_engine is not None:
                with self._queue_lock:
                    if self._queue is None:
                        self._queue = TTSQueue(speak_fn=self._say_pyttsx3_blocking,
                                               stop_fn=self._interrupt_playback)
            else:
                self.status_message = engine_err

    def _ensure_queue(self) -> None:
        """Создаёт очередь воспроизведения (через _play_blocking: Yandex→Piper), если её ещё нет."""
        with self._queue_lock:
            if self._queue is None:
                self._queue = TTSQueue(speak_fn=self._play_blocking,
                                       stop_fn=self._interrupt_playback)

    def _init_pyttsx3(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 180)
            for voice in engine.getProperty("voices"):
                name = (voice.name or "").lower()
                vid = (voice.id or "").lower()
                if "russian" in name or "ru" in vid:
                    engine.setProperty("voice", voice.id)
                    break
            self.pyttsx3_engine = engine
            self.status_message = "pyttsx3 активирован (резерв)"
        except Exception as exc:
            self.status_message = f"pyttsx3: {exc}"

    def _prewarm_cache(self) -> None:
        """Кэширует статичные фразы ТЕКУЩЕЙ персоны (контроль стоимости Yandex)."""
        if not config.YANDEX_PREWARM and self._yandex is not None:
            return
        try:
            persona = self._current_persona
            for phrases in SIMPLE.values():
                for phrase in phrases:
                    if self._stop_event.is_set():
                        return
                    if "{" in phrase:
                        continue
                    if self._queue is not None and not self._queue._queue.empty():
                        if self._stop_event.wait(0.2):
                            return
                        continue
                    cache_path = self._cache.path_for(phrase.strip(), self._voice_key(persona))
                    if not os.path.exists(cache_path):
                        self._generate_and_cache(phrase.strip(), persona)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ #
    # Публичный интерфейс (engine.py зависит от этих полей и методов)     #
    # ------------------------------------------------------------------ #

    @property
    def is_available(self) -> bool:
        return (self._yandex is not None) or self._engine.is_ready or self.pyttsx3_engine is not None

    @property
    def is_critical_active(self) -> bool:
        """True, пока сейчас проигрывается critical-приоритетная реплика (гейт
        core/engine.py ask_voice_question — не отвечаем на голосовой вопрос поверх критики)."""
        return self._queue is not None and self._queue.critical_active

    @property
    def engine_name(self) -> str:
        if self._yandex is not None:
            return "Yandex SpeechKit"
        if self._engine.is_ready:
            return "Piper (RU)"
        if self.pyttsx3_engine is not None:
            return "pyttsx3"
        return "Нет"

    @property
    def last_engine(self) -> str:
        """Движок, РЕАЛЬНО выдавший последнюю фразу (синтез или кэш)."""
        return self._last_engine

    @property
    def last_fallback(self) -> bool:
        """True, если Yandex прицеплен, но последняя фраза ушла на Piper-фолбэк."""
        return self._last_fallback

    @property
    def active_speaker(self) -> str:
        """Ярлык реально звучащего спикера для UI: «Яндекс: Филипп» / «Piper: Ruslan».

        Опирается на реально использованный движок (_last_engine); до первой фразы —
        на то, что прицеплено и здорово. Имя голоса берётся из текущей персоны
        (+ пользовательские оверрайды для Yandex), не из дефолтного списка Piper."""
        eng = self._last_engine
        persona = self._current_persona
        yandex_live = self._yandex is not None and self._yandex_healthy
        if eng == "Yandex SpeechKit" or (not eng and yandex_live):
            spec = voices.resolve(persona, self._voice_overrides)
            return f"Яндекс: {voices.display_name(spec['voice'])}"
        if eng == "Piper (RU)" or (not eng and self._engine.is_ready):
            name = PERSONA_VOICE.get(persona, PERSONA_VOICE.get("tv", ("ruslan", 1.0)))[0]
            return f"Piper: {name.capitalize()}"
        if eng == "pyttsx3" or self.pyttsx3_engine is not None:
            return "pyttsx3 (резерв)"
        return "—"

    def set_persona(self, persona: str) -> None:
        """Персона КОММЕНТАТОРА. Чужое значение (слот роли, опечатка) молча
        игнорируется, а НЕ сбрасывает выбор пользователя: слоты ролей лежат в
        том же PERSONA_VOICE, и прежняя проверка `persona in PERSONA_VOICE` их
        пропускала. Сбрасывать на "tv" тоже нельзя — пользователь, сидящий на
        "hype", терял бы свою персону из-за чужого вызова."""
        if persona in _COMMENTATOR_PERSONAS:
            self._current_persona = persona

    def set_radio_fx(self, enabled: bool) -> None:
        self._radio_enabled = bool(enabled)

    def _radio_for(self, persona: str | None) -> bool:
        """Накладывать ли эффект рации на эту конкретную реплику.

        Глобальный пользовательский тумблер главнее: выключенный radio_fx
        снимает эффект со всех каналов."""
        if not self._radio_enabled:
            return False
        return (persona or self._current_persona) in _RADIO_SLOTS

    def set_volume(self, global_vol: int, persona_volumes: dict[str, int]) -> None:
        self._global_vol = max(0, min(100, int(global_vol)))
        self._persona_vol = {k: max(0, min(100, int(v))) for k, v in persona_volumes.items()}

    def _effective_volume(self, persona: str | None = None) -> float:
        vol = self._persona_vol.get(persona or self._current_persona,
                                    self._global_vol)
        return vol / 100.0

    def set_yandex(self, speech_source) -> None:
        """Подключить Yandex как основной источник синтеза (None = только Piper).
        Очередь создаётся сразу — Yandex работает, не дожидаясь загрузки Piper.

        Оверрайды голосов переносятся в НОВЫЙ источник здесь, а не силами
        вызывающего. `YandexSpeech` держит их у себя (`_overrides`) отдельно от
        `Voice._voice_overrides`, и синхронизирует их только
        `set_voice_overrides()` — причём лишь если Yandex уже прицеплен в тот
        момент. Порядок при старте обратный: каст считается в
        `F1Engine.__init__` (Yandex ещё None), а источник появляется позже, в
        `_start_yandex()`. Без переноса здесь новый клиент уходил в синтез с
        пустыми оверрайдами и резолвил слоты ролей по голым каталожным
        дефолтам — то есть инженер получал голос комментатора при persona=tv и
        toxic, а кэш при этом писался под ключ ПРАВИЛЬНОГО голоса, так что
        испорченные WAV переживали починку настроек."""
        self._yandex = speech_source
        if speech_source is not None:
            if self._voice_overrides and hasattr(speech_source, "set_overrides"):
                speech_source.set_overrides(self._voice_overrides)
            self._ensure_queue()

    def set_yandex_healthy(self, ok: bool) -> None:
        """Health-monitor (engine) сообщает, доступен ли Yandex прямо сейчас.
        Когда False — _synthesize идёт сразу на Piper, без таймаут-штрафа Yandex.
        Когда снова True — следующая фраза автоматически уходит на Yandex."""
        self._yandex_healthy = bool(ok)

    def set_yandex_health_reporter(self, cb) -> None:
        """Колбэк callback(ok: bool): реальный результат синтеза Yandex кормит
        health-monitor (быстрее реагирует, чем только периодические пробы)."""
        self._health_reporter = cb

    def set_tts_version(self, version: str) -> None:
        """Forward TTS version ("v1"/"v3") to YandexSpeech if attached."""
        if self._yandex is not None and hasattr(self._yandex, "set_tts_version"):
            persona = getattr(self, "_current_persona", "?")
            _log.info("Voice.set_tts_version: %s | persona=%s", version, persona)
            self._yandex.set_tts_version(version)

    def set_voice_overrides(self, overrides: dict | None) -> None:
        self._voice_overrides = overrides or {}
        if self._yandex is not None and hasattr(self._yandex, "set_overrides"):
            self._yandex.set_overrides(self._voice_overrides)

    def _current_speed_scale(self) -> float:
        """Множитель темпа для реплики, которую воркер синтезирует прямо сейчас.

        Срочность читается с элемента очереди, а не приходит аргументом:
        `speak_fn` — двухаргументный колбэк (`text`, `persona`), и менять его
        сигнатуру ради одного числа не нужно — очередь уже отдаёт владельцу
        `current_item` (тем же приёмом пользуется `still_valid`).

        Вне воркера (прогрев кэша в фоне) текущего элемента нет, и тогда темп
        нейтральный: прогревать кэш под срочность нечего — она у каждой реплики
        своя."""
        queue = getattr(self, "_queue", None)
        if queue is None:
            return 1.0
        item = queue.current_item
        if item is None:
            return 1.0
        return voice_cast.speed_scale(getattr(item, "urgency", None))

    def _voice_key(self, persona: str, speed_scale: float = 1.0) -> str:
        """Ключ кэша зависит от РЕАЛЬНЫХ параметров синтеза, не от имени персоны.
        Версия рендера (v1/v3) — тоже параметр: один и тот же голос звучит
        по-разному, кэш между версиями смешивать нельзя.

        Множитель срочности добавляется в ключ ТОЛЬКО когда он не 1.0. Иначе
        весь уже накопленный кэш обесценился бы разом: у подавляющего
        большинства реплик срочность обычная, их ключ обязан остаться прежним.
        Синтез стоит денег, и разовая переозвучка всей библиотеки — реальная
        цена, а не теоретическая."""
        if self._yandex is not None:
            s = voices.resolve(persona, self._voice_overrides)
            ver = getattr(self._yandex, "tts_version", "v1")
            key = f"y:{ver}:{s['voice']}|{s['emotion']}|{s['speed']}"
            return key if speed_scale == 1.0 else f"{key}x{speed_scale}"
        # Piper темпа по срочности НЕ получает: его synthesize() параметра
        # скорости не имеет. Это резервный движок последней очереди, и молча
        # притворяться, будто он звучит так же, нельзя — поэтому оговорено тут.
        return f"piper:{persona}"

    def _interrupt_playback(self) -> None:
        """Прервать текущее воспроизведение (для critical-приоритета).

        Бьёт в self._current_stream (конкретный объект _play_wav), а не в
        модульный sd.stop() — тот делил глобальный указатель стрима между
        потоками и гонял с sd.play() из TTSQueue-воркера (access violation,
        ntdll.dll — закрыто 07-04). .abort() держим ПОД ЛОКОМ (не отпускаем
        до вызова) — иначе владеющий поток (_play_wav/_synthesize_streaming)
        может успеть между чтением указателя и .abort() дойти до своего
        .close() того же sd.OutputStream: два потока зовут нативные методы
        одного объекта без взаимного исключения — подозреваемый источник
        ДРУГОГО access violation, в ucrtbase.dll (см. открытая находка
        2026-07-09/07-13 в CONTEXT.md, тот же офсет дважды).

        Диагностическое логирование (2026-07-20): .abort() — жёсткая,
        немедленная остановка PortAudio-стрима без дренирования буфера, что
        стандартно даёт слышимый щелчок/хрип в точке обрыва. Раньше этим
        прерыванием пользовались только редкие critical-события (PENA/
        box-call), после появления споттера (SPOTTER_CAR_LEFT/RIGHT/BOTH,
        priority=critical) оно может срабатывать в разы чаще за гонку.
        Логируем факт и исход КАЖДОГО вызова — это единственная точка кода,
        где реально происходит abort, и раньше она была полностью немой
        (жалоба пользователя «звук иногда лагал или хрипел» после гонки со
        споттером не могла быть подтверждена по логу задним числом именно
        из-за этого молчания — см. CONTEXT.md)."""
        with self._stream_lock:
            stream = self._current_stream
            if stream is not None:
                _log.info("Voice._interrupt_playback: aborting active stream")
                try:
                    stream.abort()   # немедленно, без ожидания буфера — то, что нужно critical
                except Exception as exc:  # noqa: BLE001
                    _log.info("Voice._interrupt_playback: abort raised %r", exc)
            else:
                _log.info("Voice._interrupt_playback: no active stream to interrupt")

    def play_beep(self) -> None:
        """Короткий рут-сквелч — маркер «AI начал слушать» (push-to-talk, см.
        core/engine.py::_run_voice_question). Сначала глушит текущую фразу
        (_interrupt_playback — как реальная рация: входящая передача обрывает
        прежнюю), затем играет squelch через ОТДЕЛЬНЫЙ sd.OutputStream.
        close() — под тем же self._stream_lock, что и в _play_wav/
        _interrupt_playback (см. их докстринги про access violation в
        ucrtbase.dll, найдено 07-09/07-13, фикс 07-14) — не открывать эту
        гонку заново. radio_fx.squelch() — тот же синтез, что уже обрамляет
        фразы при включённом radio-эффекте (voice/radio_fx.py), играется
        ВСЕГДА (не зависит от self._radio_enabled — это отдельный,
        осознанный UX-сигнал, не часть тумблера «радио-эффект»)."""
        self._interrupt_playback()
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            return
        sr = 22050
        try:
            audio = radio_fx.squelch(sr)
        except Exception:  # noqa: BLE001
            return
        if audio.size == 0:
            return
        mul = self._effective_volume()
        if mul != 1.0:
            audio = audio * mul
        stream = None
        try:
            stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32", latency="low")
            with self._stream_lock:
                self._current_stream = stream
            stream.start()
            stream.write(np.ascontiguousarray(audio.reshape(-1, 1), dtype="float32"))
            stream.stop()
        except Exception:  # noqa: BLE001
            pass
        finally:
            with self._stream_lock:
                if self._current_stream is stream:
                    self._current_stream = None
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass

    def say(self, text: str, priority: str = "normal",
            persona: str | None = None, *,
            urgency: str | None = None,
            message_id: str | None = None,
            prepare: Callable[[], str | None] | None = None,
            still_valid: Callable[[], bool] | None = None) -> bool:
        """Ставит фразу в очередь воспроизведения.

        Возвращает True, если фраза ПРИНЯТА, и False, если очередь отказала
        (переполнена без менее срочной жертвы, либо остановлена) — раньше
        возвращалось True всегда, потому что отказа как наблюдаемого события не
        существовало.

        persona: озвучить конкретной персоной (например, "calm" = голос
        инженера для команд), None = текущая персона.
        urgency: четырёхуровневая срочность (core/radio/policy.py) для правил
        вытеснения. None = вывести из `priority`, поведение как раньше.
        message_id: id `RadioMessage`, чтобы вытеснение можно было отследить до
        конкретного сообщения.
        prepare: финальное разрешение волатильных данных. Вызывается воркером за
        миг до синтеза — там позади и пауза MIN_COMMENT_GAP, и эта очередь.
        Возвращает готовый текст либо None («уже неактуально»). Когда передан,
        `text` служит только фолбэком для логов.
        still_valid: повторная проверка перед playback, после сетевого синтеза.

        Диагностическое логирование (2026-07-20): раньше ни текст, ни
        приоритет произнесённой фразы нигде не попадали в лог (только
        метаданные синтеза Yandex — число сэмплов, без содержимого) — из-за
        этого нельзя было задним числом подтвердить, какая именно фраза
        играла в момент жалобы пользователя на «лагал/хрипел» звук после
        гонки со споттером. Строка ниже — единственная точка входа для ЛЮБОЙ
        озвучки (say() вызывается и из _commentary_loop, и из play_beep-
        смежных путей), поэтому покрывает всё, не только споттер."""
        if not text or not text.strip() or not self.is_available:
            return False
        if self._queue is not None:
            text = text.strip()
            _log.info("Voice.say: priority=%s persona=%s text=%r",
                      priority, persona or self._current_persona, text)
            result = self._queue.enqueue(
                text, priority=priority, persona=persona,
                urgency=urgency, message_id=message_id,
                prepare=prepare, still_valid=still_valid)
            # Отказ больше не молчит. Раньше очередь съедала фразу в
            # `except queue.Full: pass`: ни лога, ни возвращаемого значения — при
            # всплеске событий инженер проглатывал команду, и по логу это было
            # не восстановить.
            if not result.accepted:
                _log.warning("Voice.say dropped (%s): %r",
                             result.outcome.value, text)
            return result.accepted
        return False

    def test_say(self, text: str) -> bool:
        """Тестовое воспроизведение: очищает очередь, ставит фразу первой."""
        if self._queue is not None:
            self._queue.clear()
        t0 = time.monotonic()
        ok = self.say(text)
        _log.debug("test_say enqueued in %.1f ms", (time.monotonic() - t0) * 1000)
        return ok

    # ------------------------------------------------------------------ #
    # Воспроизведение (вызывается из TTSQueue._worker в фоновом потоке)   #
    # ------------------------------------------------------------------ #

    def _synthesize(self, text: str, persona: str, speed_scale: float = 1.0):
        """Вернуть (audio float32 mono, sr). Yandex первый, при неудаче — Piper.
        Запоминает РЕАЛЬНО использованный движок (self._last_engine/_last_fallback)
        для честного статуса в UI и выбора ключа кэша.

        `speed_scale` — множитель темпа по срочности. Piper его не принимает
        (см. `_voice_key`), поэтому на фолбэке срочность звучать перестаёт."""
        # Yandex — основной, но только если прицеплен И health-monitor считает его живым.
        # Когда упал, идём сразу на Piper без таймаут-штрафа (фикс залипания: как только
        # монитор вернёт healthy=True, следующая фраза снова уйдёт на Yandex).
        if self._yandex is not None and self._yandex_healthy:
            audio, sr = self._yandex.synthesize(text, persona, speed_scale)
            ok = audio is not None and len(audio) > 0
            if self._health_reporter is not None:
                try:
                    self._health_reporter(ok)   # реальный синтез кормит health-monitor
                except Exception:  # noqa: BLE001
                    pass
            if ok:
                self._last_engine = "Yandex SpeechKit"
                self._last_fallback = False
                return audio, sr
            # Yandex прицеплен, но синтез не дал звука → фолбэк на Piper
            if self._engine.is_ready:
                self._last_engine = "Piper (RU)"
                self._last_fallback = True
                return self._engine.synthesize(text, persona)
            return None, self._engine.sample_rate
        # Yandex не подключён ИЛИ помечен недоступным — штатный Piper (резерв)
        if self._engine.is_ready:
            self._last_engine = "Piper (RU)"
            self._last_fallback = self._yandex is not None  # прицеплен, но сейчас на Piper
            return self._engine.synthesize(text, persona)
        return None, self._engine.sample_rate

    def _yandex_streaming_eligible(self) -> bool:
        """Этап B работает только для v3-grpc — v1/REST-v3 не отдают чанки
        по мере готовности, буферизуются на уровне транспорта."""
        return (config.YANDEX_TTS_STREAMING_PLAYBACK
                and self._yandex is not None and self._yandex_healthy
                and getattr(self._yandex, "tts_version", None) == "v3-grpc")

    def _playback_gate(self) -> bool:
        """Актуально ли ещё то, что воркер собирается воспроизвести.

        Спрашивается ПОСЛЕ синтеза: сетевой запрос к Yandex сам занимает
        секунды, и звук может вернуться, когда сообщение уже неактуально
        (машина уехала, Safety Car убрали, окно пит-стопа закрылось). TTL даёт
        право НАЧАТЬ воспроизведение — уже начавшуюся фразу он не обрывает."""
        # _queue создаётся лениво (_ensure_queue) — до этого атрибута нет.
        queue = getattr(self, "_queue", None)
        item = getattr(queue, "current_item", None) if queue is not None else None
        if item is None or item.still_valid is None:
            return True
        try:
            return bool(item.still_valid())
        except Exception:  # noqa: BLE001
            _log.warning("playback gate raised, playing anyway", exc_info=True)
            return True

    def _current_message_id(self) -> str | None:
        queue = getattr(self, "_queue", None)
        item = getattr(queue, "current_item", None) if queue is not None else None
        return getattr(item, "message_id", None)

    def set_playback_observer(
            self, observer: "Callable[[str, str | None], None] | None") -> None:
        """Колбэк реальных событий воспроизведения: ("playing"|"completed", id).

        Нужен, чтобы состояние «говорит» бралось из момента старта
        `OutputStream`, а не из момента постановки в очередь: `say()`
        возвращается мгновенно, и прежний паттерн
        `set_speaking(True) / say() / set_speaking(False)` держал флаг
        поднятым микросекунды (дефект, найденный в Task 1)."""
        self._playback_observer = observer

    def _notify_playback(self, event: str) -> None:
        observer = getattr(self, "_playback_observer", None)
        if observer is None:
            return
        try:
            observer(event, self._current_message_id())
        except Exception:  # noqa: BLE001
            _log.debug("playback observer failed", exc_info=True)

    def _play_blocking(self, text: str, persona: str | None = None) -> None:
        persona = persona or self._current_persona
        from core.num_to_words import normalize
        text = normalize(text)
        # Темп берётся ЗДЕСЬ, пока элемент ещё текущий: ниже по стеку воркер уже
        # может снять его с очереди, и срочность потеряется.
        scale = self._current_speed_scale()
        vkey = self._voice_key(persona, scale)
        # Cache key считается ПОСЛЕ финального резолва (воркер уже вызвал
        # prepare()), поэтому ERS 60% и ERS 14% дают разные ключи, а фраза с
        # выброшенной клаузой — ключ своего короткого текста.
        cache_path = self._cache.path_for(text, vkey)
        if os.path.exists(cache_path):
            # звук из кэша: движок определяется ключом (y:* = Yandex, иначе Piper)
            self._last_engine = "Yandex SpeechKit" if vkey.startswith("y:") else "Piper (RU)"
            self._last_fallback = False
            t0 = time.monotonic()
            self._play_wav(cache_path, persona)
            _log.debug("playback from cache: %.0f ms", (time.monotonic() - t0) * 1000)
            return
        t0 = time.monotonic()
        if self._yandex_streaming_eligible():
            if self._play_streaming(text, persona, scale):
                _log.debug("playback streamed: %.0f ms", (time.monotonic() - t0) * 1000)
                return
            # Сбой ДО первого чанка — безопасно падаем на обычный буферный путь
            # (Yandex full retry -> Piper), ничего ещё не звучало.
        audio, sr = self._synthesize(text, persona, scale)
        if audio is None:
            return
        # Кэшируем под ключом РЕАЛЬНО использованного движка: фолбэк-аудио Piper не
        # пишем в Yandex-ключ, иначе после починки ключа кэш бы навсегда играл Piper.
        save_key = vkey if self._last_engine == "Yandex SpeechKit" else f"piper:{persona}"
        save_path = self._cache.path_for(text, save_key)
        self._save_wav(audio, sr, save_path)
        self._cache.evict_if_needed()
        # Синтез мог занять секунды — спрашиваем актуальность ещё раз. Сухой WAV
        # при этом ОСТАЁТСЯ в кэше: ключ корректен, и следующему такому же
        # сообщению он сэкономит сетевой запрос.
        if not self._playback_gate():
            _log.info("playback skipped after synthesis: message no longer current")
            return
        self._play_wav(save_path, persona)
        _log.debug("playback synthesized: %.0f ms", (time.monotonic() - t0) * 1000)

    def _play_streaming(self, text: str, persona: str = "tv",
                        speed_scale: float = 1.0) -> bool:
        """Играет по чанкам, как только они готовы (Yandex v3-grpc — Этап B;
        Piper — исходный путь до Yandex), кэширует «сухую» полную запись целиком.
        Радио-эффект накладывается на лету, в кэш не пишется.

        Возвращает True, если хоть что-то было проиграно (полный успех ИЛИ
        частичный сбой ПОСЛЕ начала — повтор через буферный путь дал бы
        задвоение речи, поэтому в этом случае просто логируем и считаем
        обработанным, без записи в кэш). False — ничего не проиграно (сбой
        ДО первого чанка ИЛИ чисто пустой поток без единого чанка): вызывающий
        (_play_blocking) безопасно падает на буферный путь.

        Ключ кэша сохранения вычисляется ЗДЕСЬ, из фактически выбранного
        use_yandex — не принимается готовым путём аргументом. Вызывающий
        (_play_blocking) резолвит vkey/eligibility ДО этого вызова, а
        self._yandex_healthy может измениться между тем моментом и стартом
        стрима (health-monitor работает в отдельном потоке) — если бы мы
        сохраняли под заранее вычисленный Yandex-путь, TOCTOU-гонка могла бы
        закэшировать Piper-аудио под Yandex-ключом навсегда (тот самый баг
        «yandex-v2», который buffered-путь уже предотвращает пересчётом
        save_key постфактум — см. комментарий в _play_blocking выше)."""
        use_yandex = (self._yandex is not None and self._yandex_healthy
                     and getattr(self._yandex, "tts_version", None) == "v3-grpc")
        if use_yandex:
            chunk_source = self._yandex.synthesize_streaming(
                text, persona, speed_scale)
            sr = config.YANDEX_TTS_SAMPLE_RATE
        else:
            chunk_source = self._engine.synthesize_streaming(text, persona)
            sr = self._engine.sample_rate

        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            return False

        dry_parts: list[np.ndarray] = []
        radio = self._radio_for(persona)
        mul = self._effective_volume(persona)
        stream = None
        mid_stream_error = False
        try:
            # Constructor lives INSIDE the try — a removed/busy output device
            # (headphones unplugged, exclusive-mode app) raises PortAudioError
            # here; if it were outside, the exception would escape this method
            # entirely (past _play_blocking, which does not wrap this call)
            # straight into TTSQueue._worker's blanket except-pass, silently
            # dropping the phrase with no buffered fallback and no status.
            stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32", latency="low")
            with self._stream_lock:
                self._current_stream = stream
            stream.start()
            for seg, seg_sr in chunk_source:
                if radio and not dry_parts:
                    stream.write((radio_fx.start_beep(sr) * mul).reshape(-1, 1))
                    stream.write((radio_fx.squelch(sr) * mul).reshape(-1, 1))
                dry_parts.append(seg)
                out = radio_fx.bandpass(seg, seg_sr) if radio else seg
                if mul != 1.0:
                    out = out * mul
                stream.write(np.ascontiguousarray(out.reshape(-1, 1), dtype="float32"))
            if radio and dry_parts:
                stream.write((radio_fx.squelch(sr) * mul).reshape(-1, 1))
        except Exception as exc:
            mid_stream_error = True
            if dry_parts:
                self.status_message = f"Стриминг прерван: {exc}"
        finally:
            if stream is not None:
                try:
                    stream.stop()
                except Exception:  # noqa: BLE001
                    pass
            # .close() держим под тем же локом, что и _interrupt_playback()'s
            # .abort() — иначе гонка close()/abort() на одном sd.OutputStream
            # из двух потоков (см. _interrupt_playback docstring).
            with self._stream_lock:
                if self._current_stream is stream:
                    self._current_stream = None
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass

        # Успех для health-monitor'а — только ПОЛНЫЙ, чистый стрим (ни исключения,
        # ни нуля чанков). Частичный сбой посреди стрима — тоже признак нездоровья
        # Yandex, даже если первый чанк успел прийти; иначе деградировавшая сеть
        # (обрыв после 1-го чанка на каждой фразе) никогда не переключит на Piper.
        ok_for_health = bool(dry_parts) and not mid_stream_error
        if use_yandex and self._health_reporter is not None:
            try:
                self._health_reporter(ok_for_health)
            except Exception:  # noqa: BLE001
                pass

        # Пустой поток чанков (0 штук) БЕЗ исключения — тоже провал, не успех:
        # без этого фраза тихо пропадала бы (return True, ничего не сыграно,
        # буферный фолбэк в _play_blocking не запускается).
        if not dry_parts:
            return False

        self._last_engine = "Yandex SpeechKit" if use_yandex else "Piper (RU)"
        self._last_fallback = False

        if mid_stream_error:
            # Уже что-то сыграно — не повторяем (задвоение речи), считаем
            # обработанным. НО обрезанную запись в кэш не пишем: иначе критическое
            # прерывание (_interrupt_playback -> stream.abort() -> write бросает
            # исключение) или обрыв сети навсегда закэшируют огрызок фразы под
            # рабочим ключом (файл кэша не имеет TTL и не самоисцеляется).
            return True

        full = np.concatenate(dry_parts).astype(np.float32)
        # Ключ по РЕАЛЬНО использованному движку (use_yandex), не по
        # self._yandex is not None — иначе TOCTOU-фолбэк на Piper пишет
        # его аудио под Yandex-ключ (self._voice_key() решала бы по
        # прицепленности, не по факту).
        # Множитель темпа обязан попасть в ключ и здесь: без него срочная
        # реплика легла бы в кэш под нейтральным ключом и потом звучала бы
        # ускоренной там, где спешить не надо.
        save_key = (self._voice_key(persona, speed_scale) if use_yandex
                    else f"piper:{persona}")
        save_path = self._cache.path_for(text, save_key)
        self._save_wav(full, sr, save_path)
        self._cache.evict_if_needed()
        return True

    def _generate_and_cache(self, text: str, persona: str) -> str | None:
        """Генерирует и кэширует «сухой» звук без воспроизведения."""
        cache_path = self._cache.path_for(text, self._voice_key(persona))
        if os.path.exists(cache_path):
            return cache_path
        audio, sr = self._synthesize(text, persona)
        if audio is not None:
            self._save_wav(audio, sr, cache_path)
            return cache_path
        return None

    def _save_wav(self, audio, sample_rate: int, path: str) -> None:
        """Save mono float32 as 16-bit WAV using soundfile (dry, no radio fx)."""
        try:
            import numpy as np
            import soundfile as sf
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            tmp = path + ".tmp"
            # format='WAV' must be explicit — soundfile can't infer it from .tmp
            sf.write(tmp, pcm, sample_rate, format="WAV", subtype="PCM_16")
            os.replace(tmp, path)
        except Exception as exc:
            self.status_message = f"Кэш TTS: {exc}"

    def _play_wav(self, path: str, persona: str | None = None) -> None:
        """Play a cached dry WAV, applying the radio effect on the fly if enabled.

        Dedicated sd.OutputStream per call, not module-level sd.play/wait —
        see _interrupt_playback for why."""
        try:
            import sounddevice as sd
            import soundfile as sf
            import numpy as np
            data, sr = sf.read(path, dtype="float32")
            if data.ndim > 1:
                data = data[:, 0]  # cache is mono, but be safe
            if self._radio_for(persona):
                data = np.concatenate([
                    radio_fx.start_beep(sr),
                    radio_fx.squelch(sr),
                    radio_fx.bandpass(data, sr),
                    radio_fx.squelch(sr),
                ]).astype(np.float32)
            mul = self._effective_volume(persona)
            if mul != 1.0:
                data = data * mul
            stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32", latency="low")
            with self._stream_lock:
                self._current_stream = stream
            try:
                stream.start()
                # Реальный старт звука — единственный честный источник состояния
                # «инженер говорит». Момент постановки в очередь им быть не может:
                # say() возвращается мгновенно.
                self._notify_playback("playing")
                stream.write(np.ascontiguousarray(data.reshape(-1, 1), dtype="float32"))
                stream.stop()   # blocks until the buffered audio drains — replaces sd.wait()
                self._notify_playback("completed")
            finally:
                # .close() держим под тем же локом, что и _interrupt_playback()'s
                # .abort() — иначе гонка close()/abort() на одном sd.OutputStream
                # из двух потоков (см. _interrupt_playback docstring).
                with self._stream_lock:
                    if self._current_stream is stream:
                        self._current_stream = None
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass
        except ImportError:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        except Exception as exc:
            self.status_message = f"WAV play: {exc}"

    # ------------------------------------------------------------------ #
    # pyttsx3 (резерв, если Piper не загрузился)                          #
    # ------------------------------------------------------------------ #

    def _say_pyttsx3_blocking(self, text: str, persona: str | None = None) -> None:
        try:
            self.pyttsx3_engine.say(text)
            self.pyttsx3_engine.runAndWait()
        except Exception as exc:
            self.status_message = f"pyttsx3: {exc}"
