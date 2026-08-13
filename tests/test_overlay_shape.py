"""Арифметика формы окна: базовые координаты страницы → пиксели окна."""

from core.overlay_shape import Primitive, scale_primitives

BASE = {"base_width": 300, "base_height": 300}


def test_primitives_follow_the_window_not_the_saved_scale():
    """Масштаб берётся из реального окна.

    Окно дополнительно зажимается клиентской областью игры (`place_over`), и
    считай мы форму по сохранённому множителю, у прижатого к краю виджета она
    вылезала бы за границы окна.
    """
    shapes = scale_primitives(
        [{"kind": "ellipse", "x": 24, "y": 24, "w": 252, "h": 252}],
        width=150, height=150, **BASE,
    )

    assert shapes == (Primitive(kind="ellipse", box=(12, 12, 138, 138)),)


def test_shape_never_leaves_the_window():
    """Кусок формы за краем окна зажимается, а не уезжает в отрицательные."""
    shapes = scale_primitives(
        [{"kind": "rect", "x": -40, "y": -40, "w": 900, "h": 900}],
        width=300, height=300, **BASE,
    )

    assert shapes[0].box == (0, 0, 300, 300)


def test_round_rect_radius_scales_by_the_smaller_axis():
    """При неравном масштабе радиус по большей оси сделал бы из круга овал."""
    shapes = scale_primitives(
        [{"kind": "round-rect", "x": 0, "y": 0, "w": 300, "h": 300, "r": 40}],
        width=300, height=150, **BASE,
    )

    assert shapes[0].radius == 20


def test_round_rect_radius_is_capped_at_half_the_side():
    """Скругление больше половины стороны GDI рисует непредсказуемо."""
    shapes = scale_primitives(
        [{"kind": "round-rect", "x": 0, "y": 0, "w": 100, "h": 40, "r": 90}],
        width=300, height=300, **BASE,
    )

    assert shapes[0].radius == 20


def test_degenerate_round_rect_becomes_a_plain_rect():
    """Нулевой радиус после масштабирования — это прямоугольник, а не ошибка."""
    shapes = scale_primitives(
        [{"kind": "round-rect", "x": 0, "y": 0, "w": 300, "h": 300, "r": 1}],
        width=30, height=30, **BASE,
    )

    assert shapes[0].kind == "rect"
    assert shapes[0].radius == 0


def test_junk_drops_one_primitive_and_keeps_the_rest():
    """Форма приходит из браузера: строки, None и NaN здесь норма.

    Пропускается ровно испорченный кусок — ронять из-за него всю форму нельзя,
    иначе одна опечатка в вёрстке возвращала бы чёрный прямоугольник целиком.
    """
    shapes = scale_primitives(
        [
            {"kind": "ellipse", "x": 0, "y": 0, "w": 300, "h": 300},
            {"kind": "rect", "x": "nonsense", "y": None, "w": float("nan"), "h": 10},
            {"kind": "unknown-shape", "x": 0, "y": 0, "w": 10, "h": 10},
            "not a dict",
            {"kind": "rect", "x": 0, "y": 0, "w": 300, "h": 12},
        ],
        width=300, height=300, **BASE,
    )

    assert [item.kind for item in shapes] == ["ellipse", "rect"]
    assert shapes[1].box == (0, 0, 300, 12)


def test_empty_shape_means_no_region_at_all():
    """Нет формы — нет региона: окно остаётся прямоугольным, как сегодня.

    Это безопасный откат для страницы, которая ничего не сообщила (старая
    сборка webui/, превью в браузере).
    """
    assert scale_primitives(None, width=300, height=300, **BASE) == ()
    assert scale_primitives([], width=300, height=300, **BASE) == ()
    assert scale_primitives(
        [{"kind": "rect", "x": 0, "y": 0, "w": 0, "h": 0}],
        width=300, height=300, **BASE,
    ) == ()


def test_polygon_needs_three_usable_points():
    """Фаска — треугольный вырез; из двух точек контура не бывает."""
    assert scale_primitives(
        [{"kind": "polygon", "points": [[0, 0], [10, 10]]}],
        width=300, height=300, **BASE,
    ) == ()

    shapes = scale_primitives(
        [{"kind": "polygon", "points": [[0, 0], [300, 0], [300, 300], [11, 300]]}],
        width=150, height=150, **BASE,
    )

    assert shapes[0].points == ((0, 0), (150, 0), (150, 150), (6, 150))


def test_a_broken_base_size_cannot_divide_by_zero():
    assert scale_primitives(
        [{"kind": "rect", "x": 0, "y": 0, "w": 10, "h": 10}],
        width=300, height=300, base_width=0, base_height=300,
    ) == ()
