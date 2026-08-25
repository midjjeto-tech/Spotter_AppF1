"""Собрать CA-бандл корневых сертификатов НУЦ Минцифры для строгой TLS-проверки
GigaChat (endpoints Sber цепочкой уходят в Russian Trusted Root CA, которого нет
в стандартном certifi).

Что делает:
  1. Скачивает официальные архивы по ссылкам со страницы Госуслуг:
       - Russian Trusted Root CA (RSA 2022)
       - Russian Trusted Sub CA (актуальные RSA-варианты)
     Загрузка проверяется обычной публичной TLS-цепочкой.
  2. Проверяет закреплённые SHA-256 отпечатки.
  3. Конвертирует DER/PEM(.cer) -> PEM (stdlib ssl, без openssl).
  4. Пишет бандл: <DATA_DIR>/certs/gigachat_ca_bundle.pem
     (Russian root+sub + стандартный certifi, если установлен — чтобы бандл
     годился и для любых других HTTPS-хостов SDK).

После запуска config.GIGACHAT_CA_BUNDLE подхватит бандл автоматически (см. config.py),
и provider включит verify_ssl_certs=True.

Запуск:  python scripts/setup_gigachat_certs.py
"""
from __future__ import annotations

import hashlib
import io
import os
import ssl
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

# Официальные ссылки со страницы https://www.gosuslugi.ru/crt, проверены
# 2026-08-19. Архивы отдаются по обычной публично доверенной TLS-цепочке, так
# что bootstrap с verify=False больше не нужен.
CERT_ARCHIVES = {
    "root": "https://gu-st.ru/content/lending/windows_russian_trusted_root_ca.zip",
    "sub": "https://gu-st.ru/content/lending/russian_trusted_sub_ca.zip",
}

# Пины защищают якорь доверия даже при ошибочной замене файла на сервере.
# Обновлять их можно только после сверки с официальной страницей Госуслуг.
CERT_FILES = {
    "Russian Trusted Root CA (RSA 2022)": (
        "root", "russian_trusted_root_ca.cer",
        "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31",
    ),
    "Russian Trusted Sub CA (RSA)": (
        "sub", "russian_trusted_sub_ca.cer",
        "bbbde2103e790b999ec62bd03cf625a5a2e7c316e10afe6a490eedead8b3fd9b",
    ),
    "Russian Trusted Sub CA (RSA 2024)": (
        "sub", "russian_trusted_sub_ca_2024.cer",
        "2155785036c900dbb5f1bb2a1569c80c55595bd6bf94867a29bbddbc7d88a3f2",
    ),
}
OUT_DIR = os.path.join(config.DATA_DIR, "certs")
OUT_BUNDLE = os.path.join(OUT_DIR, "gigachat_ca_bundle.pem")


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310
        return r.read()


def _to_pem(raw: bytes) -> str:
    # .cer с gu.gov.ru — DER. Если вдруг уже PEM — вернём как есть.
    if raw.lstrip().startswith(b"-----BEGIN CERTIFICATE-----"):
        return raw.decode("ascii")
    return ssl.DER_cert_to_PEM_cert(raw)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    pems: list[str] = []
    archives: dict[str, bytes] = {}
    for archive, url in CERT_ARCHIVES.items():
        try:
            archives[archive] = _download(url)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] архив {archive}: не скачался ({exc})")
            return 1

    for name, (archive, member, expected_fp) in CERT_FILES.items():
        try:
            with zipfile.ZipFile(io.BytesIO(archives[archive])) as bundle:
                raw = bundle.read(member)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name}: нет в архиве ({exc})")
            return 1
        pem = _to_pem(raw)
        fp = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
        if fp != expected_fp:
            print(f"[FAIL] {name}: SHA-256 не совпал")
            print(f"       ожидали {expected_fp}")
            print(f"       получили {fp}")
            return 1
        print(f"[OK] {name}")
        print(f"     SHA-256: {fp}")
        pems.append(pem.strip() + "\n")

    # Добавляем стандартные корни certifi (если есть) — бандл годится для любых хостов.
    try:
        import certifi
        with open(certifi.where(), encoding="ascii") as f:
            pems.append(f.read())
        print("[OK] добавлены стандартные корни certifi")
    except Exception:  # noqa: BLE001
        print("[warn] certifi не найден — бандл только с корнями Минцифры "
              "(для Sber-эндпоинтов достаточно)")

    with open(OUT_BUNDLE, "w", encoding="ascii") as f:
        f.write("\n".join(pems))
    print(f"\nБандл записан: {OUT_BUNDLE}")
    print("Отпечатки сверены с закреплёнными значениями официальных файлов.")
    print("config.GIGACHAT_CA_BUNDLE подхватит его автоматически.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
