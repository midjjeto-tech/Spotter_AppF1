// Преобразование ленты бэкенда (state.feed: {time, event_code, phrase, color,
// driver, muted, channel}) в модели экранов Events и Logs.
//
// Коды событий бывают двух видов:
//  1) сырые коды F1-телеметрии (OVTK/PENA/RTMT/... — core/packets.py::parse_event);
//  2) синтетические коды самого Spotter'а (SPOTTER_*, STRAT_*, ENGINEER_*,
//     DAMAGE_*, POSITION_CALL, ... — см. commentator/planner.py::_BASE_IMPORTANCE
//     и commentator/templates.py, это два самых полных списка в бэкенде).
// Раньше здесь были только коды из (1), и половина живой ленты рендерилась сырым
// кодом с серой иконкой «info». При добавлении нового event_code в бэкенд —
// дописывать его сюда, иначе он снова станет сырой строкой.

import type { FeedItem } from "./api"
import type { RaceEvent, LogEntry } from "./spotter-data"

const KIND: Record<string, RaceEvent["kind"]> = {
  // ── Позиции и борьба ──────────────────────────────────────────────────────
  OVTK: "overtake",
  ATTACK: "overtake",
  ATTACK_ZONE: "overtake",
  BATTLE: "overtake",
  DEFENSE: "overtake",
  POSITION_CALL: "overtake",
  POSITION_CALL_OWN_PIT: "overtake",
  LEADER_CHANGE: "overtake",

  // ── Темп круга ────────────────────────────────────────────────────────────
  FTLP: "fastest",
  PUSH_LAP: "fastest",
  QUALI_LAP: "fastest",
  FINAL_LAP: "fastest",
  F1_BENCH: "fastest",
  F1_SECTOR_BENCH: "fastest",
  CAREER_PB: "fastest",
  CAREER_SECTOR_PB: "fastest",

  // ── Пит-стопы ─────────────────────────────────────────────────────────────
  PIT: "pit",
  PITS: "pit",
  PIT_IN: "pit",
  PIT_OUT: "pit",
  PIT_EXIT: "pit",
  PIT_WINDOW_OPEN: "pit",
  PIT_WINDOW_APPROACH: "pit",
  PIT_CALL_NOTICE: "pit",

  // ── Штрафы ────────────────────────────────────────────────────────────────
  PENA: "penalty",
  PENS: "penalty",
  ENGINEER_PENA_TRACK_LIMITS: "penalty",
  ENGINEER_TRACK_LIMITS_WARNING: "penalty",

  // ── Инциденты и повреждения ───────────────────────────────────────────────
  RTMT: "incident",
  COLL: "incident",
  SPIN: "incident",
  OFFT: "incident",
  DAMAGE_WING: "incident",
  DAMAGE_FLOOR: "incident",
  DAMAGE_GEARBOX: "incident",
  DAMAGE_ENGINE: "incident",
  DAMAGE_HEAVY: "incident",
  DAMAGE_TYRE_CRITICAL: "incident",

  // ── Флаги, нейтрализация, границы сессии ──────────────────────────────────
  SCAR: "flag",
  VSCA: "flag",
  SAFETY_CAR_DEPLOYED: "flag",
  SAFETY_CAR_ENDING: "flag",
  SAFETY_CAR_CLEAR: "flag",
  RDFL: "flag",
  CHQF: "flag",
  RCWN: "flag",
  SSTA: "flag",
  SEND: "flag",
  LGOT: "flag",
  STLG: "flag",

  // ── Споттер (соседи по трассе) ────────────────────────────────────────────
  SPOTTER_CAR_LEFT: "spotter",
  SPOTTER_CAR_RIGHT: "spotter",
  SPOTTER_CAR_BOTH: "spotter",
  SPOTTER_CLEAR: "spotter",

  // ── Канал инженера ────────────────────────────────────────────────────────
  ENGINEER_GAP_DIGEST: "engineer",
  ENGINEER_RAIN_ADVISORY: "engineer",
  PRE_RACE_PEP_TALK: "engineer",
  USER_Q: "engineer",

  // ── Стратегия ─────────────────────────────────────────────────────────────
  STRAT_PIT: "strategy",
  STRAT_UNDERCUT: "strategy",
  STRAT_OVERCUT: "strategy",
  STRAT_SAVE: "strategy",
  STRAT_PUSH: "strategy",
  STRAT_FUEL: "strategy",
  STRAT_ERS_SAVE: "strategy",
  STRAT_ERS_OVERTAKE: "strategy",
  STRAT_BOX_CALL_1: "strategy",
  STRAT_BOX_CALL_2: "strategy",
  STRAT_BOX_CALL_3: "strategy",

  // ── Резина ────────────────────────────────────────────────────────────────
  TYRE_WARN: "tyre",
  TYRE_WEAR_HIGH: "tyre",
  TYRE_CLIFF: "tyre",

  // ── Итоги и карьера ───────────────────────────────────────────────────────
  STORY: "story",
  CAREER_RECAP: "story",
  CHAMPIONSHIP: "story",
  MILESTONE: "story",
  RACEFEED_DOTD: "story",
  POST_RACE_INTERVIEW: "story",

  // ── Телеметрия и служебное ────────────────────────────────────────────────
  DRSE: "info",
  DRSD: "info",
  DRS_ALLOWED_ON: "info",
  DRS_ALLOWED_OFF: "info",
  DRS_PROXIMITY_ENTER: "info",
  DRS_PROXIMITY_EXIT: "info",
  DRS_PROXIMITY_ENTER_AND_ALLOWED: "info",
  TMPT: "info",
  SPTP: "info",
  BUTN: "info",
  FLBK: "info",
  AMBIENT: "info",
}

const TITLE: Record<string, string> = {
  // ── Позиции и борьба ──
  OVTK: "Обгон",
  ATTACK: "Атака",
  ATTACK_ZONE: "Зона атаки",
  BATTLE: "Борьба",
  DEFENSE: "Защита позиции",
  POSITION_CALL: "Позиция",
  POSITION_CALL_OWN_PIT: "Позиция после пита",
  LEADER_CHANGE: "Смена лидера",

  // ── Темп круга ──
  FTLP: "Быстрый круг",
  PUSH_LAP: "Атакующий круг",
  QUALI_LAP: "Квалификационный круг",
  FINAL_LAP: "Последний круг",
  F1_BENCH: "Сравнение с F1",
  F1_SECTOR_BENCH: "Сектор против F1",
  CAREER_PB: "Личный рекорд",
  CAREER_SECTOR_PB: "Рекорд сектора",

  // ── Пит-стопы ──
  PIT: "Пит-стоп",
  PITS: "Пит-стоп",
  PIT_IN: "Заезд на пит",
  PIT_OUT: "Выезд с пита",
  PIT_EXIT: "Выезд с пита",
  PIT_WINDOW_OPEN: "Окно пит-стопа открыто",
  PIT_WINDOW_APPROACH: "Окно пит-стопа близко",
  PIT_CALL_NOTICE: "Вызов на пит",

  // ── Штрафы ──
  PENA: "Штраф",
  PENS: "Штраф",
  ENGINEER_PENA_TRACK_LIMITS: "Штраф за трек-лимиты",
  ENGINEER_TRACK_LIMITS_WARNING: "Предупреждение о трек-лимитах",

  // ── Инциденты и повреждения ──
  RTMT: "Сход",
  COLL: "Контакт",
  SPIN: "Разворот",
  OFFT: "Вылет",
  DAMAGE_WING: "Повреждено антикрыло",
  DAMAGE_FLOOR: "Повреждено днище",
  DAMAGE_GEARBOX: "Повреждена коробка",
  DAMAGE_ENGINE: "Повреждён двигатель",
  DAMAGE_HEAVY: "Тяжёлые повреждения",
  DAMAGE_TYRE_CRITICAL: "Критическое состояние шины",

  // ── Флаги, нейтрализация, границы сессии ──
  SCAR: "Сейфти-кар",
  VSCA: "Виртуальный SC",
  SAFETY_CAR_DEPLOYED: "Сейфти-кар на трассе",
  SAFETY_CAR_ENDING: "Сейфти-кар уходит",
  SAFETY_CAR_CLEAR: "Трасса свободна",
  RDFL: "Красный флаг",
  CHQF: "Финиш",
  RCWN: "Победитель гонки",
  SSTA: "Старт сессии",
  SEND: "Конец сессии",
  LGOT: "Старт",
  STLG: "Стартовая решётка",

  // ── Споттер ──
  SPOTTER_CAR_LEFT: "Машина слева",
  SPOTTER_CAR_RIGHT: "Машина справа",
  SPOTTER_CAR_BOTH: "Машины с двух сторон",
  SPOTTER_CLEAR: "Чисто",

  // ── Канал инженера ──
  ENGINEER_GAP_DIGEST: "Сводка по разрывам",
  ENGINEER_RAIN_ADVISORY: "Прогноз дождя",
  PRE_RACE_PEP_TALK: "Напутствие перед стартом",
  USER_Q: "Вопрос инженеру",

  // ── Стратегия ──
  STRAT_PIT: "Стратегия: пит-стоп",
  STRAT_UNDERCUT: "Стратегия: андеркат",
  STRAT_OVERCUT: "Стратегия: оверкат",
  STRAT_SAVE: "Стратегия: беречь",
  STRAT_PUSH: "Стратегия: пуш",
  STRAT_FUEL: "Стратегия: топливо",
  STRAT_ERS_SAVE: "Стратегия: беречь ERS",
  STRAT_ERS_OVERTAKE: "Стратегия: ERS на обгон",
  STRAT_BOX_CALL_1: "Бокс — круг 1",
  STRAT_BOX_CALL_2: "Бокс — круг 2",
  STRAT_BOX_CALL_3: "Бокс — круг 3",

  // ── Резина ──
  TYRE_WARN: "Износ резины",
  TYRE_WEAR_HIGH: "Высокий износ резины",
  TYRE_CLIFF: "Резина «упала»",

  // ── Итоги и карьера ──
  STORY: "Итог сессии",
  CAREER_RECAP: "Карьерная сводка",
  CHAMPIONSHIP: "Чемпионат",
  MILESTONE: "Достижение",
  RACEFEED_DOTD: "Гонщик дня",
  POST_RACE_INTERVIEW: "Интервью после гонки",

  // ── Телеметрия и служебное ──
  DRSE: "DRS включён",
  DRSD: "DRS выключен",
  DRS_ALLOWED_ON: "DRS разрешён",
  DRS_ALLOWED_OFF: "DRS запрещён",
  DRS_PROXIMITY_ENTER: "В зоне DRS",
  DRS_PROXIMITY_EXIT: "Вышел из зоны DRS",
  DRS_PROXIMITY_ENTER_AND_ALLOWED: "DRS доступен",
  TMPT: "Смена состава шин",
  SPTP: "Speed trap",
  BUTN: "Нажата кнопка",
  FLBK: "Перемотка",
  AMBIENT: "Фоновая реплика",
}

/** Подпись канала. Значения — commentator/channel_router.py. «commentary» —
 *  канал по умолчанию у подавляющего большинства событий: подписывать им каждую
 *  строку значит просто зашумить ленту, поэтому метка только у неочевидных. */
const CHANNEL_LABEL: Record<string, string> = {
  radio: "рация",
  overlay: "HUD",
}

export function feedToEvent(f: FeedItem, i: number): RaceEvent {
  const code = (f.event_code || "").toUpperCase()
  return {
    id: `${f.time}-${i}`,
    time: f.time,
    kind: KIND[code] ?? "info",
    title: TITLE[code] ?? (f.event_code || "Событие"),
    text: f.phrase,
    driver: f.driver || "",
    // muted приходит из core/engine.py: событие попало в ленту, но озвучено НЕ
    // было (порог важности, пауза, канал overlay, отключённый голос).
    spoken: f.muted !== true,
    channel: f.channel || "",
    channelLabel: CHANNEL_LABEL[f.channel || ""] ?? "",
  }
}

export function feedToLog(f: FeedItem): LogEntry {
  // У бэкенда нет уровней журнала — лента это события гонки. Вместо
  // декоративных INFO/WARN/ERR помечаем тем, что бэкенд реально знает:
  // прозвучала ли реплика вслух.
  return {
    time: f.time,
    type: f.muted === true ? "SILENT" : "SPOKEN",
    message: f.phrase,
    code: (f.event_code || "").toUpperCase(),
    title: TITLE[(f.event_code || "").toUpperCase()] ?? (f.event_code || "Событие"),
  }
}
