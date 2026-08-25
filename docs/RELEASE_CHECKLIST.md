# Spotter App release checklist

Финальный релиз создаётся только командой `powershell -File scripts/release.ps1`.
Обычный `build.ps1` создаёт dev-сборку и сам предупреждает, что публиковать её
нельзя.

## До сборки

- рабочее дерево чистое, release candidate находится в отдельном commit;
- Python совпадает с `.python-version`, а `requirements-release.lock` обновлён
  из `requirements-release.in` с hashes;
- версии совпадают в `config.py`, `NewSpotterUI/package.json` и
  `installer/SpotterApp.iss`;
- версия ещё не имеет git-тега;
- заданы `SPOTTER_SIGN_CERT_THUMBPRINT`, `SPOTTER_SIGN_TIMESTAMP_URL` и при
  необходимости полный путь `SPOTTER_SIGNTOOL`;
- Node.js и закреплённый в `package.json` pnpm доступны в `PATH`;
- Inno Setup 6 установлен.

iRacing в `0.2` не является release-функцией: адаптер не завершён, а upstream
`pyirsdk 1.1.7` не воспроизводится в изолированной Python 3.12-среде. F1-сборка
должна показывать штатную диагностику `iracing_no_lib`, а не молча тащить
непроверенный локальный wheel.

Release-сценарий пересоздаёт `.release-venv` строго из lock-файла, затем сам
требует полный pytest, frontend lint/typecheck/build,
production dependency audit, установщик, действительные Authenticode-подписи,
чистоту дерева после сборки и создаёт SHA-256/manifest в `dist/release/`.

## Живая приёмка установленного EXE

- чистая установка без прав администратора и запуск после перезагрузки;
- обновление поверх предыдущей версии сохраняет настройки и DPAPI-ключи;
- полный заезд F1 25: UDP, инженер, споттер, Coach и завершение с финальной
  классификацией;
- RaceFeed включён, публикации и архив видны в реальном UI;
- каждый HUD работает в своём окне, нет серой/сплошной поверхности над игрой;
- alt-tab, перезапуск HUD и закрытие приложения не оставляют процессы/порты;
- Piper говорит без сети, ошибки Yandex/GigaChat дают безопасный fallback;
- приглушение игры всегда восстанавливается после реплики и после сбоя;
- второй экран проверен с другого устройства в локальной сети;
- uninstall/reinstall и откат на предыдущий установщик проверены отдельно.

## Публикация

- сверить подписи всех трёх EXE и SHA-256 с `dist/release/`;
- записать известные ограничения и результат живой приёмки в release notes;
- создать подписанный аннотированный тег `v<version>` на commit из manifest;
- хранить установщик, manifest, checksums и предыдущую рабочую версию вместе.
