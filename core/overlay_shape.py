"""Форма окна HUD-виджета: от примитивов страницы до региона Win32.

Зачем это вообще есть. Окно виджета непрозрачно (`OVERLAY_BACKGROUND`) и всегда
прямоугольно, а виджеты рисуют не прямоугольники: радар — круг, приборы —
таблетку, рация — карточку со скруглением, у тем с фаской срезан угол. Всё, что
вне фигуры, было чёрным фоном окна поверх трассы. Прозрачность по пикселям на
этом стеке недостижима (история попыток — в `app.pyw`), поэтому лишнее убирается
не альфой, а РЕГИОНОМ окна: система просто не отдаёт эти пиксели окну, и там
видно игру.

Замерено на живом окне виджета (WebView2, layered), четыре точки экрана:

    без региона : углы (18,18,18)  центр (18,18,18)
    эллипс      : углы (32,32,32)  центр (18,18,18)   ← углы стали обоями

Отдельно замерено: снятие `WS_EX_LAYERED` убивает окно целиком. Стиль обязан
остаться — с регионом он совместим.

Форму задаёт СТРАНИЦА, а не этот модуль: она зависит от темы (фаска, радиус
карточки рации из CSS-переменной) и от состояния (карточка рации есть или нет).
Захардкоженная в Python копия геометрии разъехалась бы с вёрсткой молча — тот
самый класс багов, на котором проект уже обжигался. Здесь только арифметика:
примитивы в БАЗОВЫХ координатах виджета → пиксели окна.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Примитивы, которые понимает страница и умеет построить GDI.
KINDS = frozenset({"rect", "round-rect", "ellipse", "polygon"})


@dataclass(frozen=True)
class Primitive:
    """Одна фигура в пикселях ОКНА, готовая к передаче в GDI."""

    kind: str
    #: rect/round-rect/ellipse: (left, top, right, bottom); polygon: пусто.
    box: tuple[int, int, int, int] = (0, 0, 0, 0)
    #: round-rect: радиус скругления в пикселях окна.
    radius: int = 0
    #: polygon: точки контура в пикселях окна.
    points: tuple[tuple[int, int], ...] = ()


def _number(value: object, fallback: float = 0.0) -> float:
    """Числа приходят из JSON браузера: строка, None и NaN здесь норма."""
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if result != result or result in (float("inf"), float("-inf")):
        return fallback
    return result


def _scaled(value: object, scale: float, limit: int) -> int:
    """Базовая координата → пиксель окна, зажатый в его габариты."""
    return max(0, min(limit, int(round(_number(value) * scale))))


def scale_primitives(
    raw: object, *, width: int, height: int, base_width: int, base_height: int,
) -> tuple[Primitive, ...]:
    """Пересчитать примитивы страницы в пиксели окна.

    Масштаб берётся из отношения реального окна к базовому размеру виджета, а не
    из сохранённого множителя: окно — единственная правда о том, сколько на
    экране пикселей, и `place_over` его дополнительно зажимает клиентской
    областью игры. Считай мы по множителю, у прижатого к краю окна форма
    вылезала бы за его границы.

    Мусор игнорируется по одному примитиву, а не роняет всю форму: страница
    перезапишет её на следующем обновлении, а окно без формы — это ровно
    сегодняшнее поведение, то есть безопасный откат.
    """
    if not isinstance(raw, (list, tuple)) or base_width <= 0 or base_height <= 0:
        return ()
    scale_x = width / base_width
    scale_y = height / base_height
    result: list[Primitive] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind not in KINDS:
            continue
        if kind == "polygon":
            points = item.get("points")
            if not isinstance(points, (list, tuple)) or len(points) < 3:
                continue
            corners: list[tuple[int, int]] = []
            for point in points:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                corners.append((
                    _scaled(point[0], scale_x, width),
                    _scaled(point[1], scale_y, height),
                ))
            if len(corners) >= 3:
                result.append(Primitive(kind="polygon", points=tuple(corners)))
            continue

        left = _scaled(item.get("x"), scale_x, width)
        top = _scaled(item.get("y"), scale_y, height)
        right = _scaled(_number(item.get("x")) + _number(item.get("w")), scale_x, width)
        bottom = _scaled(_number(item.get("y")) + _number(item.get("h")), scale_y, height)
        if right <= left or bottom <= top:
            continue
        radius = 0
        if kind == "round-rect":
            # Радиус скругления масштабируется по меньшей оси: по большей он
            # превратил бы круглую таблетку в овал при неравном масштабе.
            radius = max(0, int(round(_number(item.get("r")) * min(scale_x, scale_y))))
            # Скругление больше половины стороны GDI рисует непредсказуемо.
            radius = min(radius, (right - left) // 2, (bottom - top) // 2)
            if radius <= 0:
                kind = "rect"
        result.append(Primitive(kind=kind, box=(left, top, right, bottom), radius=radius))
    return tuple(result)


def build_region(primitives: tuple[Primitive, ...]):
    """Объединить примитивы в один HRGN. Пусто на входе → None.

    Владение: успешный `SetWindowRgn` ЗАБИРАЕТ регион себе, и удалять его после
    этого нельзя. Поэтому удаляются здесь только промежуточные куски, а
    результат уходит наружу живым.
    """
    if not primitives:
        return None
    import ctypes

    gdi32 = ctypes.windll.gdi32
    combined = None
    for item in primitives:
        piece = _create(gdi32, item)
        if not piece:
            continue
        if combined is None:
            combined = piece
            continue
        gdi32.CombineRgn(combined, combined, piece, 2)  # RGN_OR
        gdi32.DeleteObject(piece)
    return combined


def _create(gdi32, item: Primitive):
    """Один примитив → HRGN. Неизвестное молча пропускается."""
    left, top, right, bottom = item.box
    if item.kind == "rect":
        return gdi32.CreateRectRgn(left, top, right, bottom)
    if item.kind == "ellipse":
        return gdi32.CreateEllipticRgn(left, top, right, bottom)
    if item.kind == "round-rect":
        # GDI ждёт ШИРИНУ и ВЫСОТУ эллипса скругления, а не радиус.
        return gdi32.CreateRoundRectRgn(
            left, top, right, bottom, item.radius * 2, item.radius * 2)
    if item.kind == "polygon":
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        points = (POINT * len(item.points))(*[POINT(x, y) for x, y in item.points])
        return gdi32.CreatePolygonRgn(points, len(item.points), 1)  # ALTERNATE
    return None
