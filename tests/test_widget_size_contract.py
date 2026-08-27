"""Габариты виджетов оверлея живут в ДВУХ файлах и обязаны совпадать.

`core/overlay_window.py::HUD_WIDGETS` задаёт размер нативного окна, а
`NewSpotterUI/.../in-game-overlay.tsx::WIDGET_SIZE` — размер коробки, в которой
рисуется содержимое. Комментарии в обоих файлах требуют держать их равными, но
до 2026-08-27 это ничем не проверялось: расхождение даёт либо чёрную кайму
вокруг содержимого, либо обрезанный виджет, и видно это только глазами поверх
запущенной игры.

Тест читает TSX текстом. Это осознанный размен: поднимать node ради одной
таблицы дороже, чем разобрать её регуляркой, а формат таблицы стабильный и
проверяется тем же тестом (если он перестанет разбираться, тест упадёт, а не
промолчит).
"""
import re
from pathlib import Path

from core.overlay_window import HUD_WIDGETS

_TSX = (Path(__file__).resolve().parents[1]
        / "NewSpotterUI" / "components" / "spotter" / "overlay"
        / "in-game-overlay.tsx")

_TABLE_RE = re.compile(
    r"const WIDGET_SIZE:\s*Record<WidgetId,\s*\{[^}]*\}>\s*=\s*\{(.*?)\n\}",
    re.DOTALL)
_ROW_RE = re.compile(
    r"(\w+):\s*\{\s*width:\s*(\d+),\s*height:\s*(\d+)\s*\}")


def _tsx_sizes() -> dict[str, tuple[int, int]]:
    source = _TSX.read_text(encoding="utf-8")
    table = _TABLE_RE.search(source)
    assert table, (
        "не найдена таблица WIDGET_SIZE в in-game-overlay.tsx — если её "
        "переименовали или переформатировали, поправьте разбор здесь, а не "
        "удаляйте проверку")
    rows = dict(
        (name, (int(width), int(height)))
        for name, width, height in _ROW_RE.findall(table.group(1)))
    assert rows, "таблица WIDGET_SIZE разобралась пустой"
    return rows


def test_widget_sizes_match_between_python_and_tsx():
    """Главный инвариант файла: одна цифра, два места, ноль расхождений."""
    tsx = _tsx_sizes()
    python = {name: (spec.width, spec.height) for name, spec in HUD_WIDGETS.items()}

    assert tsx == python, (
        "габариты разошлись между core/overlay_window.py и in-game-overlay.tsx:\n"
        + "\n".join(
            f"  {name}: python={python.get(name)} tsx={tsx.get(name)}"
            for name in sorted(set(python) | set(tsx))
            if python.get(name) != tsx.get(name)))


def test_widget_sets_match():
    """Виджет, заведённый только с одной стороны, не нарисуется или не получит
    окна. Проверяется отдельно от размеров: сообщение об ошибке должно называть
    причину, а не показывать разницу двух словарей целиком."""
    assert set(_tsx_sizes()) == set(HUD_WIDGETS)
