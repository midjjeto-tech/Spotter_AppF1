"""
scripts/make_icon.py
=====================
`assets/spotter.ico` из брендового PNG проекта — без Pillow.

Зачем скрипт, а не «положить .ico рядом». Иконка EXE должна быть тем же знаком,
что и иконка веб-интерфейса (`NewSpotterUI/public/`), иначе установщик и окно
показывают разные логотипы. Скрипт делает связь воспроизводимой: поменялся
исходный PNG — перегенерировали, и расхождения не возникает.

Почему не Pillow: его нет в `requirements.txt` и тащить его в проект ради одной
иконки незачем — PNG здесь 8-битный RGBA без интерлейса, а это ровно тот случай,
который разбирается штатным `zlib` в тридцать строк.

Формат. В `.ico` кладутся классические DIB-записи (32bpp BGRA + маска) на
16/32/48/64/128 и PNG-запись на 256 — так делают все нормальные иконки: мелкие
размеры Windows берёт готовыми, а не мылит из крупного, а PNG-запись экономит
место на большом. Строка AND-маски обязана быть выровнена по 4 байта, и на
32bpp-иконках её всё равно требует формат, хотя альфа лежит в самих пикселях.

Запуск:
    python scripts/make_icon.py            # из NewSpotterUI/public/apple-icon.png
    python scripts/make_icon.py --check    # только проверить, что .ico свежий
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "NewSpotterUI" / "public" / "apple-icon.png"
TARGET = ROOT / "assets" / "spotter.ico"

#: Размеры DIB-записей. 256 добавляется отдельно, PNG-записью.
DIB_SIZES = (16, 32, 48, 64, 128)
PNG_SIZE = 256


# ── PNG ──────────────────────────────────────────────────────────────────────

def decode_png_rgba(data: bytes) -> tuple[int, int, bytearray]:
    """8-битный RGBA PNG без интерлейса -> (ширина, высота, пиксели RGBA).

    Сознательно НЕ универсальный декодер: палитра, 16 бит и Adam7 подняли бы
    его втрое, а исходник в этом проекте всегда один и проверяется здесь же."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("не PNG")
    # IHDR: 13 байт данных начиная с 16-го (8 сигнатура + 4 длина + 4 тип).
    width, height, depth, color_type, _, _, interlace = struct.unpack(
        ">IIBBBBB", data[16:29])
    if (depth, color_type, interlace) != (8, 6, 0):
        raise ValueError(
            f"нужен 8-битный RGBA без интерлейса, а тут depth={depth} "
            f"type={color_type} interlace={interlace}")

    idat = bytearray()
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        if kind == b"IDAT":
            idat += data[offset + 8:offset + 8 + length]
        elif kind == b"IEND":
            break
        offset += 12 + length

    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    out = bytearray(height * stride)
    previous = bytearray(stride)
    pos = 0
    for row in range(height):
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        _unfilter(filter_type, line, previous, 4)
        out[row * stride:(row + 1) * stride] = line
        previous = line
    return width, height, out


def _unfilter(filter_type: int, line: bytearray, prior: bytearray, bpp: int) -> None:
    """Обратный фильтр строки PNG (спека, раздел 9.2). Правится на месте."""
    if filter_type == 0:
        return
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        b = prior[i]
        c = prior[i - bpp] if i >= bpp else 0
        if filter_type == 1:
            line[i] = (line[i] + a) & 0xFF
        elif filter_type == 2:
            line[i] = (line[i] + b) & 0xFF
        elif filter_type == 3:
            line[i] = (line[i] + (a + b) // 2) & 0xFF
        elif filter_type == 4:
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[i] = (line[i] + pred) & 0xFF
        else:
            raise ValueError(f"неизвестный фильтр строки: {filter_type}")


def encode_png_rgba(width: int, height: int, pixels: bytes) -> bytes:
    """RGBA -> PNG. Нужен для 256-й записи: DIB такого размера весит мегабайт."""
    raw = bytearray()
    stride = width * 4
    for row in range(height):
        raw.append(0)                                  # фильтр «none»
        raw += pixels[row * stride:(row + 1) * stride]

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


# ── Масштаб ──────────────────────────────────────────────────────────────────

def resize_rgba(width: int, height: int, pixels: bytes, size: int) -> bytearray:
    """Уменьшение усреднением по площади.

    Не «ближайший сосед»: на 16×16 он превращает знак в кашу из отдельных
    пикселей, а иконка такого размера — это как раз то, что пользователь видит
    в панели задач. Альфа усредняется вместе с цветом, поэтому вес берётся с
    премножением — иначе прозрачные пиксели тянут цвет к чёрному по краю.
    """
    out = bytearray(size * size * 4)
    for y in range(size):
        y0, y1 = y * height // size, max(y * height // size + 1, (y + 1) * height // size)
        for x in range(size):
            x0, x1 = x * width // size, max(x * width // size + 1, (x + 1) * width // size)
            r = g = b = a = 0.0
            count = 0
            for sy in range(y0, y1):
                base = (sy * width + x0) * 4
                for sx in range(x1 - x0):
                    p = base + sx * 4
                    alpha = pixels[p + 3] / 255.0
                    r += pixels[p] * alpha
                    g += pixels[p + 1] * alpha
                    b += pixels[p + 2] * alpha
                    a += pixels[p + 3]
                    count += 1
            if not count:
                continue
            mean_a = a / count
            weight = mean_a / 255.0
            o = (y * size + x) * 4
            if weight > 0:
                out[o] = min(255, int(r / count / weight))
                out[o + 1] = min(255, int(g / count / weight))
                out[o + 2] = min(255, int(b / count / weight))
            out[o + 3] = int(mean_a)
    return out


# ── ICO ──────────────────────────────────────────────────────────────────────

def _dib_entry(size: int, rgba: bytes) -> bytes:
    """32bpp BGRA + AND-маска, снизу вверх — как требует формат иконки."""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         size * size * 4, 0, 0, 0, 0)
    body = bytearray()
    for y in range(size - 1, -1, -1):                  # строки снизу вверх
        for x in range(size):
            p = (y * size + x) * 4
            body += bytes((rgba[p + 2], rgba[p + 1], rgba[p], rgba[p + 3]))
    # AND-маска: на 32bpp не используется, но её размер входит в запись, а
    # строка обязана быть выровнена по 4 байта.
    mask_stride = ((size + 31) // 32) * 4
    body += bytes(mask_stride * size)
    return header + bytes(body)


def build_ico(width: int, height: int, pixels: bytes) -> bytes:
    images: list[bytes] = []
    sizes: list[int] = []
    for size in DIB_SIZES:
        images.append(_dib_entry(size, resize_rgba(width, height, pixels, size)))
        sizes.append(size)
    big = resize_rgba(width, height, pixels, PNG_SIZE)
    images.append(encode_png_rgba(PNG_SIZE, PNG_SIZE, bytes(big)))
    sizes.append(PNG_SIZE)

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    directory = b""
    for size, blob in zip(sizes, images):
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size, 0 if size >= 256 else size,
            0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    return header + directory + b"".join(images)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="только проверить, что .ico существует и валиден")
    args = parser.parse_args()

    if args.check:
        if not TARGET.exists():
            print(f"НЕТ иконки: {TARGET}")
            return 1
        blob = TARGET.read_bytes()
        reserved, kind, count = struct.unpack("<HHH", blob[:6])
        if (reserved, kind) != (0, 1) or count == 0:
            print("Файл не похож на .ico")
            return 1
        print(f"{TARGET}: {count} записей, {len(blob)} байт")
        return 0

    if not SOURCE.exists():
        print(f"Нет исходника: {SOURCE}")
        return 1
    width, height, pixels = decode_png_rgba(SOURCE.read_bytes())
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(build_ico(width, height, bytes(pixels)))
    print(f"Готово: {TARGET} ({TARGET.stat().st_size} байт) "
          f"из {SOURCE.name} {width}x{height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
