"""Иконка EXE собирается из брендового PNG проекта без Pillow.

Тест держит не «файл существует», а то, что он ВАЛИДЕН как .ico: битая иконка
не ломает сборку, она просто молча не показывается — тот самый класс тихой
деградации, который в этом проекте запрещён.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import make_icon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _entries(blob: bytes) -> list[dict]:
    reserved, kind, count = struct.unpack("<HHH", blob[:6])
    assert (reserved, kind) == (0, 1)
    out = []
    for i in range(count):
        off = 6 + 16 * i
        w, h, _c, _r, _p, bpp, size, data_off = struct.unpack(
            "<BBBBHHII", blob[off:off + 16])
        out.append({"w": w or 256, "h": h or 256, "bpp": bpp,
                    "blob": blob[data_off:data_off + size]})
    return out


def test_the_shipped_icon_is_a_valid_multi_size_ico():
    path = ROOT / "assets" / "spotter.ico"
    assert path.exists(), "иконка не сгенерирована: python scripts/make_icon.py"

    entries = _entries(path.read_bytes())

    assert len(entries) >= 5
    sizes = {e["w"] for e in entries}
    # Мелкие размеры Windows обязан взять готовыми, а не мылить из крупного.
    assert {16, 32, 48} <= sizes
    assert 256 in sizes
    assert all(e["bpp"] == 32 for e in entries)


def test_every_entry_decodes_as_what_the_directory_promises():
    entries = _entries((ROOT / "assets" / "spotter.ico").read_bytes())

    for entry in entries:
        blob = entry["blob"]
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", blob[16:24])
        else:
            _hs, width, doubled, _planes, _bits = struct.unpack("<iiiHH", blob[:16])
            height = doubled // 2      # DIB иконки хранят двойную высоту
        assert (width, height) == (entry["w"], entry["h"])


def test_the_mark_is_not_blank():
    """Пустая, но валидная иконка — ровно то, что тест на существование файла
    пропустил бы."""
    entries = _entries((ROOT / "assets" / "spotter.ico").read_bytes())
    small = next(e for e in entries if e["w"] == 32)
    pixels = small["blob"][40:]

    centre = [pixels[(y * 32 + x) * 4 + 3] for y in range(12, 20) for x in range(12, 20)]
    assert max(centre) > 0, "центр иконки полностью прозрачен — знака нет"


def test_png_roundtrip_survives_decode_and_encode():
    """Декодер и кодировщик обязаны сходиться: на них стоит вся генерация."""
    source = ROOT / "NewSpotterUI" / "public" / "icon-dark-32x32.png"
    width, height, pixels = make_icon.decode_png_rgba(source.read_bytes())

    again = make_icon.decode_png_rgba(
        make_icon.encode_png_rgba(width, height, bytes(pixels)))

    assert again[0] == width and again[1] == height
    assert bytes(again[2]) == bytes(pixels)


def test_a_non_rgba_png_is_refused_loudly():
    """Молча собрать мусор из палитрового PNG хуже, чем отказаться."""
    fake = bytearray(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR")
    fake += struct.pack(">IIBBBBB", 8, 8, 8, 3, 0, 0, 0)     # type=3, палитра
    try:
        make_icon.decode_png_rgba(bytes(fake))
    except ValueError as exc:
        assert "RGBA" in str(exc)
    else:
        raise AssertionError("палитровый PNG принят молча")


def test_resize_keeps_a_solid_block_solid():
    """Усреднение по площади не должно ни размывать альфу сплошного знака, ни
    тянуть цвет к чёрному по краю."""
    size = 16
    pixels = bytearray()
    for _ in range(size * size):
        pixels += bytes((200, 100, 50, 255))

    out = make_icon.resize_rgba(size, size, bytes(pixels), 8)

    assert set(out[3::4]) == {255}
    assert out[0] == 200 and out[1] == 100 and out[2] == 50
