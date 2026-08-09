; Установщик Spotter App (Inno Setup 6).
;
; Два компонента:
;   main  — само приложение, закрытый SpotterApp.exe под нашим EULA.
;   piper — офлайн-голос: piper.exe и две русские модели (denis, dmitri — обе
;   CC0; ruslan и irina удалены 2026-08-08, см. NOTICE). ОТДЕЛЬНАЯ программа
;           под GPL-3.0-or-later, поэтому она ставится в свою папку, со своим
;           текстом лицензии и ссылкой на исходный код. Мы её не изменяем и не
;           линкуем — приложение лишь запускает её как внешний процесс.
;
; Ставим В ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ, а не в Program Files. Причина не в удобстве:
; приложение пишет рядом с собой (settings.json, ключи, tts_cache, логи —
; config.py::DATA_DIR = папка исполняемого файла). В Program Files это упёрлось
; бы в права, а установка потребовала бы UAC.
;
; Сборка: ISCC.exe installer\SpotterApp.iss (вызывается из build.ps1)

#define AppName "Spotter App"
#define AppVersion "0.1.0"
#define AppExe "SpotterApp.exe"

[Setup]
AppId={{8F3C1A24-7B5E-4D18-9C6A-2E0B7D4F1A93}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Spotter App
DefaultDirName={localappdata}\Programs\Spotter App
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=SpotterApp-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Types]
Name: "full"; Description: "Полная установка"
Name: "custom"; Description: "Выборочная установка"; Flags: iscustom

[Components]
Name: "main"; Description: "Spotter App"; Types: full custom; Flags: fixed
; По умолчанию включён: обещание «говорит сразу, без ключей и без интернета»
; держится именно на нём. Снявший галочку получит системный голос Windows —
; об этом написано в описании, а не только в README.
Name: "piper"; Description: "Офлайн-голос Piper (иначе будет системный голос Windows)"; Types: full

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Components: main; Flags: ignoreversion
Source: "..\README.md";      DestDir: "{app}"; Components: main; Flags: ignoreversion
Source: "..\LICENSE";        DestDir: "{app}"; Components: main; Flags: ignoreversion
Source: "..\NOTICE";         DestDir: "{app}"; Components: main; Flags: ignoreversion

; --- Компонент офлайн-голоса (GPL-3.0-or-later) ---
; Пути обязаны совпадать с config.py: PIPER_EXE = {app}\piper\piper.exe,
; PIPER_VOICES_DIR = {app}\piper\voices. Рассинхрон здесь означает молчаливую
; потерю офлайн-голоса — приложение просто скажет «Piper не установлен».
Source: "..\dist\piper.exe";          DestDir: "{app}\piper";        Components: piper; Flags: ignoreversion
Source: "..\models\piper\ru_RU-*.onnx";      DestDir: "{app}\piper\voices"; Components: piper; Flags: ignoreversion
Source: "..\models\piper\ru_RU-*.onnx.json"; DestDir: "{app}\piper\voices"; Components: piper; Flags: ignoreversion
Source: "piper-COPYING.txt";          DestDir: "{app}\piper";        Components: piper; Flags: ignoreversion
Source: "piper-README.txt";           DestDir: "{app}\piper";        Components: piper; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}";     Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Данные пользователя, которые приложение создаёт рядом с собой. Настройки и
; ключи НЕ удаляем: переустановка не должна стирать введённый API-ключ.
Type: filesandordirs; Name: "{app}\tts_cache"
Type: filesandordirs; Name: "{app}\piper"
Type: files;          Name: "{app}\*.log"
Type: files;          Name: "{app}\*.log.1"
Type: files;          Name: "{app}\*.log.2"
