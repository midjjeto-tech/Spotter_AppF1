# SpeechKit v3 gRPC-транспорт (Этап A) — дизайн

Дата: 2026-07-09
Статус: утверждён пользователем (диалог 2026-07-08/09).

## Проблема

Бэклог-пункт «SpeechKit v3 через gRPC streaming (сейчас REST/NDJSON)» —
`yandex_ai/speech.py::_asynthesize_v3` уже читает NDJSON-поток чанков по REST,
но целиком, и только потом декодирует/играет. Настоящий streaming playback
(старт воспроизведения по мере поступления чанков) — отдельная, более крупная
задача (Этап B, переделка `voice/tts.py`). Этот документ описывает **только
Этап A**: замену транспорта REST→gRPC с ТЕМ ЖЕ поведением «ждём все чанки,
потом играем» — доказать, что gRPC вообще работает (авторизация, пакет,
упаковка в EXE), прежде чем трогать путь воспроизведения.

## Живая проверка (спайк, 2026-07-09) — факты, не предположения

Перед дизайном сделаны два реальных вызова к Yandex Cloud (израсходован тот же
порядок копеек, что и штатный `validate()`):

- `pip install yandexcloud grpcio` → пакет `yandexcloud` тянет за собой
  готовые скомпилированные gRPC-стабы `yandex.cloud.ai.tts.v3.*`
  (`tts_pb2.py`, `tts_service_pb2.py`, `tts_service_pb2_grpc.py`) — ручная
  компиляция `.proto` из `yandex-cloud/cloudapi` НЕ нужна.
- Сервис: `speechkit.tts.v3.Synthesizer`, метод `UtteranceSynthesis`
  (server-streaming). Синхронный `grpc.secure_channel` — живой вызов вернул
  293812 байт LPCM (≈3.06с аудио) за 1 чанк.
- Асинхронный `grpc.aio.secure_channel` — тот же результат, тоже успешно.
  Это важно: весь `yandex_ai/client.py` уже построен на asyncio-цикле в
  отдельном потоке (`YandexClient._run_loop`) — `grpc.aio` ложится в эту
  архитектуру без второго пула потоков.
- Авторизация: metadata `[("authorization", "Api-Key <ключ>")]` — ТОТ ЖЕ
  ключ и то же значение заголовка, что уже шлёт REST
  (`yandex_ai/credentials.py::auth_header`), просто как gRPC-metadata вместо
  HTTP-заголовка. Сработало с первой попытки, без IAM-токена.
- `UtteranceSynthesisRequest` содержит `unsafe_mode: bool` — «Automatically
  split long text to several utterances and bill accordingly» — механизм
  обхода лимита ~250 символов/24с у v3 (тот же лимит уже действует и у
  REST-версии v3, не новый риск от миграции, но полезно знать на будущее).

**Единственный оставшийся непроверенный риск — упаковка `grpcio` (нативное
расширение) в PyInstaller EXE.** Это не решается спайком, только реальной
сборкой — отдельная задача плана.

## Согласованный объём

- **Только транспорт, не воспроизведение.** `_asynthesize_v3_grpc()` собирает
  ВСЕ чанки через `async for`, конкатенирует, декодирует в тот же
  `numpy.float32`-пайплайн, что и `_asynthesize_v1`/`_asynthesize_v3` —
  identичный контракт (`np.ndarray | None`). Путь воспроизведения
  (`voice/tts.py`), кэш (`voice/cache.py`), радио-эффект — не трогаем вообще.
- **Третий вариант тумблера, не замена v3.** `set_tts_version()` принимает
  `"v1" | "v3" | "v3-grpc"`. Дефолт в `core/settings.py::DEFAULTS` НЕ
  меняется (остаётся `"v3"`) — `"v3-grpc"` доступен для ручного выбора/теста,
  не становится дефолтом в этом этапе.
- **Фолбэк — та же цепочка, что у v3.** `v3-grpc` неудачен → `v1` (переиспользует
  существующую логику `_try_once`/`synthesize()`, включая ремап премиальных
  голосов `_V1_VOICE_FALLBACK`).
- **Канал — один на всё время жизни `YandexClient`, не пересоздаётся на
  каждый вызов** (gRPC-каналы спроектированы как долгоживущие,
  мультиплексируемые — тот же принцип, что у одной aiohttp-сессии).
- **Упаковка в EXE — обязательная задача плана с реальной сборкой**, не
  предположение. `grpcio` — нативное расширение, тот же класс риска, что
  документированный ранее случай с torch DLL (`collect_all` не значит
  collect DLL).
- **Юнит-тесты мокают на уровне тонкой обёртки** (метод `YandexClient`,
  отдающий gRPC-стаб/поток), без реальной сети — тот же принцип, что у
  существующих тестов `_asynthesize_v3` (мок `post_json_raw`).

## Дизайн

### 1. `yandex_ai/credentials.py` — gRPC-metadata хелпер

```python
def grpc_auth_metadata(creds: Credentials) -> list[tuple[str, str]]:
    """То же значение Authorization, что и auth_header(), но как gRPC-metadata
    (нижний регистр ключа — требование gRPC), не HTTP-заголовок."""
    value = auth_header(creds)["Authorization"]
    return [("authorization", value)]
```

Переиспользует `auth_header()` — не дублирует ветку `iam`/`api_key`.

### 2. `yandex_ai/client.py` — долгоживущий gRPC-канал

```python
# в __init__:
        self._grpc_channel: "grpc.aio.Channel | None" = None

# в _init_session() (тот же async-контекст, что создаёт aiohttp.ClientSession):
        import grpc
        self._grpc_channel = grpc.aio.secure_channel(
            config.YANDEX_TTS_GRPC_ENDPOINT, grpc.ssl_channel_credentials())

# новый метод:
    def tts_synthesizer_stub(self):
        from yandex.cloud.ai.tts.v3 import tts_service_pb2_grpc
        return tts_service_pb2_grpc.SynthesizerStub(self._grpc_channel)
```

`stop()` дополняется закрытием канала (`await self._grpc_channel.close()`),
рядом с уже существующим закрытием aiohttp-сессии.

### 3. `config.py` — новая константа

```python
YANDEX_TTS_GRPC_ENDPOINT = "tts.api.cloud.yandex.net:443"
YANDEX_TTS_GRPC_TIMEOUT = 10.0   # секунд, тот же порядок что YANDEX_TTS_V3_TOTAL_TIMEOUT
```

### 4. `yandex_ai/speech.py` — новый путь синтеза

```python
async def _asynthesize_v3_grpc(self, text: str, voice: str, speed: float,
                                sr: int, emotion: str = "neutral") -> np.ndarray | None:
    """Synthesize using SpeechKit v3 Synthesizer.UtteranceSynthesis (gRPC,
    server-streaming). Этап A: собираем ВСЕ чанки, потом декодируем — то же
    поведение, что _asynthesize_v3 (REST/NDJSON), другой транспорт. Настоящий
    streaming playback — Этап B, отдельная задача (voice/tts.py)."""
    from yandex.cloud.ai.tts.v3 import tts_pb2
    hints = [tts_pb2.Hints(voice=voice), tts_pb2.Hints(speed=speed)]
    if emotion and emotion != "neutral":
        hints.append(tts_pb2.Hints(role=emotion))
    request = tts_pb2.UtteranceSynthesisRequest(
        text=text,
        hints=hints,
        output_audio_spec=tts_pb2.AudioFormatOptions(
            raw_audio=tts_pb2.RawAudio(
                audio_encoding=tts_pb2.RawAudio.LINEAR16_PCM,
                sample_rate_hertz=sr,
            )
        ),
        loudness_normalization_type=tts_pb2.UtteranceSynthesisRequest.LUFS,
    )
    metadata = self._client.grpc_metadata()
    stub = self._client.tts_synthesizer_stub()
    chunks: list[bytes] = []
    call = stub.UtteranceSynthesis(request, metadata=metadata,
                                   timeout=config.YANDEX_TTS_GRPC_TIMEOUT)
    async for response in call:
        chunks.append(response.audio_chunk.data)
    if not chunks:
        return None
    raw_pcm = b"".join(chunks)
    return np.frombuffer(raw_pcm, dtype="<i2").astype(np.float32) / 32768.0
```

`YandexClient.grpc_metadata()` — тонкая обёртка `creds_mod.grpc_auth_metadata(self._creds)`,
чтобы `speech.py` не трогал `creds_mod` напрямую (тот же уровень косвенности,
что уже есть у `self._client.headers()` для REST).

`_try_once()` получает третью ветку:

```python
        if version == "v3-grpc":
            coro = self._asynthesize_v3_grpc(text, voice, speed, sr, emotion=emotion)
            timeout = config.YANDEX_TTS_GRPC_TIMEOUT + 1.0
```

`set_tts_version()`: `if version in ("v1", "v3", "v3-grpc")`.

`synthesize()`: фолбэк-ветка `if audio is None and version == "v3":` расширяется
до `if audio is None and version in ("v3", "v3-grpc"):` — оба нештатных пути
падают на `v1`, тем же кодом.

### 5. `core/engine.py` — валидация

`core/engine.py:328`: `if version in ("v1", "v3"):` → `if version in ("v1", "v3", "v3-grpc"):`.
Больше нигде тумблер не хардкожен (проверено grep'ом).

### 6. Упаковка (`requirements.txt`, `SpotterApp.spec`)

- `requirements.txt`: `yandexcloud>=0.X` (пин на версию, доказавшую
  совместимость в спайке), `grpcio` (тянется транзитивно, но явный пин не
  повредит).
- `SpotterApp.spec`: `yandexcloud`, `grpc`, `google.protobuf` в `collect_all`;
  `collect_dynamic_libs('grpc')` — нативное расширение gRPC не собирается
  через `collect_all` (тот же урок, что с torch DLL, см. CONTEXT.md).
- **Обязательная реальная сборка EXE** с `set_tts_version("v3-grpc")` и живым
  синтезом — единственный способ подтвердить, что упаковка не сломана.

## Отказоустойчивость

`_asynthesize_v3_grpc` ловит `grpc.aio.AioRpcError` в `_try_once`'s общем
`except Exception` (уже существующий блок классифицирует `hasattr(exc,
"status")` для aiohttp — для gRPC нужно добавить `hasattr(exc, "code")` ветку,
логирующую `f"gRPC {exc.code()}: {exc.details()}"`, чтобы фолбэк-сообщения
были такими же информативными, как HTTP-статусы у REST). Канал создаётся один
раз при старте `YandexClient` — если создание упадёт (нет сети на старте),
`self._grpc_channel` остаётся `None`, и `_asynthesize_v3_grpc` должен вернуть
`None` рано (guard в начале метода), а не бросать `AttributeError`.

## Тестирование

- `tests/test_yandex_version.py` (расширение) — `set_tts_version("v3-grpc")`
  принимается, `_try_once` диспетчерит на `_asynthesize_v3_grpc` (мок
  `_try_once` как у существующих `TestV1Path`/`TestV3Path`), фолбэк
  `v3-grpc → v1` (зеркалит `TestV3Fallback`).
- Новый набор тестов на `_asynthesize_v3_grpc` — мок
  `speech._client.tts_synthesizer_stub()`/`grpc_metadata()`, без реальной
  сети: успешный многочанковый ответ, пустой ответ → `None`, `role`-хинт
  только для не-neutral эмоции (зеркалит существующие тесты `_asynthesize_v3`).
- `tests/test_engine_*.py` — `core/engine.py:328` принимает `"v3-grpc"`.
- Реальный EXE-билд с живым тестовым синтезом через `v3-grpc` — ручная
  проверка, не автоматический тест (см. «Упаковка» выше).
- Полный `pytest` — без регрессий.
