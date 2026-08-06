"""Собрать CA-бандл корневых сертификатов НУЦ Минцифры для строгой TLS-проверки
GigaChat (endpoints Sber цепочкой уходят в Russian Trusted Root CA, которого нет
в стандартном certifi).

Что делает:
  1. Скачивает официальные сертификаты с gu.gov.ru:
       - Russian Trusted Root CA (RSA 2022)
       - Russian Trusted Sub CA  (RSA 2022)
     Первичная загрузка идёт БЕЗ проверки TLS (bootstrap: сам корень мы ещё не
     доверяем — классическая проблема установки нового корневого CA).
  2. Конвертирует DER(.cer) -> PEM (stdlib ssl, без openssl).
  3. Печатает SHA-256 отпечатки — СВЕРЬ их с опубликованными на
     https://www.gosuslugi.ru/crt перед использованием в релизе.
  4. Пишет бандл: <DATA_DIR>/certs/gigachat_ca_bundle.pem
     (Russian root+sub + стандартный certifi, если установлен — чтобы бандл
     годился и для любых других HTTPS-хостов SDK).

После запуска config.GIGACHAT_CA_BUNDLE подхватит бандл автоматически (см. config.py),
и provider включит verify_ssl_certs=True.

Запуск:  python scripts/setup_gigachat_certs.py
"""
from __future__ import annotations

import hashlib
import os
import ssl
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

# Официальные RSA-сертификаты НУЦ Минцифры (страница: https://www.gosuslugi.ru/crt).
CERT_URLS = {
    "Russian Trusted Root CA (RSA 2022)": "https://gu.gov.ru/certs/rootca_ssl_rsa2022.cer",
    "Russian Trusted Sub CA (RSA 2022)":  "https://gu.gov.ru/certs/subca_ssl_rsa2022.cer",
}
OUT_DIR = os.path.join(config.DATA_DIR, "certs")
OUT_BUNDLE = os.path.join(OUT_DIR, "gigachat_ca_bundle.pem")


def _download(url: str) -> bytes:
    # Bootstrap: корень ещё не доверяем -> без проверки TLS. Это ожидаемо для
    # первичной установки нового корневого CA; целостность подтверждается сверкой
    # SHA-256-отпечатка (печатается ниже) с официальным значением.
    ctx = ssl._create_unverified_context()  # noqa: S323 — намеренный bootstrap
    with urllib.request.urlopen(url, context=ctx, timeout=30) as r:  # noqa: S310
        return r.read()


def _to_pem(raw: bytes) -> str:
    # .cer с gu.gov.ru — DER. Если вдруг уже PEM — вернём как есть.
    if raw.lstrip().startswith(b"-----BEGIN CERTIFICATE-----"):
        return raw.decode("ascii")
    return ssl.DER_cert_to_PEM_cert(raw)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    pems: list[str] = []
    for name, url in CERT_URLS.items():
        try:
            raw = _download(url)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name}: не скачался ({exc})")
            print("       Проверь доступ к gu.gov.ru или скачай вручную со "
                  "https://www.gosuslugi.ru/crt и положи PEM в", OUT_BUNDLE)
            return 1
        pem = _to_pem(raw)
        fp = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
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
    print("СВЕРЬ отпечатки выше с https://www.gosuslugi.ru/crt перед релизом.")
    print("config.GIGACHAT_CA_BUNDLE подхватит его автоматически.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
