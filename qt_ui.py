from __future__ import annotations

import threading
from typing import Any

import psutil
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QHeaderView,
    QStackedWidget,
    QTableWidgetItem,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    ComboBox,
    setTheme,
    SubtitleLabel,
    SwitchButton,
    TableWidget,
    TitleLabel,
    LineEdit,
    ListWidget,
    Theme,
)


class PageCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('page_card')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(10)
        self.layout.setContentsMargins(16, 16, 16, 16)

    def add_widget(self, widget: QWidget) -> None:
        self.layout.addWidget(widget)

    def add_layout(self, layout: QVBoxLayout) -> None:
        self.layout.addLayout(layout)


class StatCard(PageCard):
    def __init__(self, title: str, value: str, parent=None):
        super().__init__(parent=parent)
        self.title_label = SubtitleLabel(title, self)
        self.title_label.setObjectName('stat_label')
        self.value_label = TitleLabel(value, self)
        self.value_label.setObjectName('stat_value')
        self.layout.addWidget(self.title_label)
        self.layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class OverviewPage(QWidget):
    def __init__(self, engine, settings: dict[str, Any], parent=None):
        super().__init__(parent=parent)
        self.setObjectName('overview')
        self.engine = engine
        self.settings = settings

        layout = QHBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(24, 24, 24, 24)

        left_column = QVBoxLayout()
        left_column.setSpacing(18)

        self.status_card = PageCard(self)
        self.status_card.setObjectName('status_card')
        self.status_card.add_widget(SubtitleLabel('Состояние комментатора', self.status_card))

        status_header = QHBoxLayout()
        self.status_dot = QLabel('●', self.status_card)
        self.status_dot.setObjectName('status_dot')
        self.status_text = SubtitleLabel('Ожидание подключения к игре', self.status_card)
        status_header.addWidget(self.status_dot)
        status_header.addWidget(self.status_text)
        status_header.addStretch(1)
        self.status_card.add_layout(status_header)

        self.state_grid = QGridLayout()
        self.state_grid.setHorizontalSpacing(12)
        self.state_grid.setVerticalSpacing(12)
        self.state_grid.addWidget(SubtitleLabel('Статус', self.status_card), 0, 0)
        self.state_grid.addWidget(SubtitleLabel('Сигнал', self.status_card), 0, 1)
        self.state_grid.addWidget(SubtitleLabel('Игра', self.status_card), 0, 2)
        self.state_grid.addWidget(SubtitleLabel('Время работы', self.status_card), 0, 3)

        self.status_state = TitleLabel('Ожидание', self.status_card)
        self.signal_state = TitleLabel('Нет сигнала', self.status_card)
        self.game_state = TitleLabel('F1 25', self.status_card)
        self.uptime_state = TitleLabel('00:00:00', self.status_card)

        self.state_grid.addWidget(self.status_state, 1, 0)
        self.state_grid.addWidget(self.signal_state, 1, 1)
        self.state_grid.addWidget(self.game_state, 1, 2)
        self.state_grid.addWidget(self.uptime_state, 1, 3)
        self.status_card.add_layout(self.state_grid)
        left_column.addWidget(self.status_card)

        self.quick_card = PageCard(self)
        self.quick_card.add_widget(SubtitleLabel('Настройки быстрого доступа', self.quick_card))
        self.commentary_toggle = SwitchButton(self.quick_card)
        self.commentary_toggle.setText('Комментарий')
        self.autovoice_toggle = SwitchButton(self.quick_card)
        self.autovoice_toggle.setText('Автоозвучивание')
        self.critical_toggle = SwitchButton(self.quick_card)
        self.critical_toggle.setText('Критические события')
        self.position_combo = ComboBox(self.quick_card)
        self.position_combo.addItems(['Авто', 'Текущий пилот', 'Лидер'])
        self.position_combo.setPlaceholderText('Позиция комментатора')
        self.quick_card.add_widget(self.commentary_toggle)
        self.quick_card.add_widget(self.autovoice_toggle)
        self.quick_card.add_widget(self.critical_toggle)
        self.quick_card.add_widget(self.position_combo)

        action_row = QHBoxLayout()
        self.connect_button = PrimaryPushButton('Подключить к игре', self.quick_card)
        self.voice_test_button = PushButton('Тест озвучки', self.quick_card)
        self.clear_logs_button = PushButton('Очистить логи', self.quick_card)
        action_row.addWidget(self.connect_button)
        action_row.addWidget(self.voice_test_button)
        action_row.addWidget(self.clear_logs_button)
        self.quick_card.add_layout(action_row)
        left_column.addWidget(self.quick_card)
        left_column.addStretch(1)

        right_column = QVBoxLayout()
        right_column.setSpacing(18)

        self.session_card = PageCard(self)
        self.session_card.add_widget(SubtitleLabel('Текущая сессия', self.session_card))
        self.session_grid = QGridLayout()
        self.session_grid.setHorizontalSpacing(16)
        self.session_grid.setVerticalSpacing(16)
        self.session_grid.addWidget(SubtitleLabel('Круг', self.session_card), 0, 0)
        self.session_grid.addWidget(SubtitleLabel('Позиция', self.session_card), 0, 1)
        self.session_grid.addWidget(SubtitleLabel('Скорость', self.session_card), 0, 2)
        self.session_grid.addWidget(SubtitleLabel('Передача', self.session_card), 0, 3)
        self.session_grid.addWidget(SubtitleLabel('Топливо', self.session_card), 0, 4)
        self.lap_label = TitleLabel('—', self.session_card)
        self.position_label = TitleLabel('—', self.session_card)
        self.speed_label = TitleLabel('—', self.session_card)
        self.gear_label = TitleLabel('—', self.session_card)
        self.fuel_label = TitleLabel('—', self.session_card)
        self.session_grid.addWidget(self.lap_label, 1, 0)
        self.session_grid.addWidget(self.position_label, 1, 1)
        self.session_grid.addWidget(self.speed_label, 1, 2)
        self.session_grid.addWidget(self.gear_label, 1, 3)
        self.session_grid.addWidget(self.fuel_label, 1, 4)
        self.session_card.add_layout(self.session_grid)
        right_column.addWidget(self.session_card)

        self.events_card = PageCard(self)
        self.events_card.add_widget(SubtitleLabel('Последние события', self.events_card))
        self.events_list = ListWidget(self.events_card)
        self.events_list.setSpacing(6)
        self.events_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.events_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_column.addWidget(self.events_card)

        self.logs_card = PageCard(self)
        self.logs_card.add_widget(SubtitleLabel('Логи', self.logs_card))
        self.log_tabs = QTabWidget(self.logs_card)
        self.log_all = ListWidget(self.log_tabs)
        self.log_info = ListWidget(self.log_tabs)
        self.log_warn = ListWidget(self.log_tabs)
        self.log_error = ListWidget(self.log_tabs)
        self.log_tabs.addTab(self.log_all, 'Все')
        self.log_tabs.addTab(self.log_info, 'Инфо')
        self.log_tabs.addTab(self.log_warn, 'Предупреждения')
        self.log_tabs.addTab(self.log_error, 'Ошибки')
        self.logs_card.add_widget(self.log_tabs)
        right_column.addWidget(self.logs_card)

        layout.addLayout(left_column, 3)
        layout.addLayout(right_column, 4)

    def update_state(self, state: dict[str, Any], cpu: str, ram: str) -> None:
        connected = state.get('connected', False)
        self.status_dot.setText('●')
        if connected:
            self.status_dot.setStyleSheet('color: #3ddc84')
            self.status_text.setText('Готово к работе')
            self.status_state.setText('Активен')
            self.signal_state.setText('Есть сигнал')
        else:
            self.status_dot.setStyleSheet('color: #e02631')
            self.status_text.setText('Ожидание подключения к игре')
            self.status_state.setText('Ожидание')
            self.signal_state.setText('Нет сигнала')

        self.game_state.setText('F1 25')
        telemetry = state.get('telemetry', {})
        self.lap_label.setText(str(telemetry.get('lap', '—')))
        self.position_label.setText(str(telemetry.get('position', '—')))
        self.speed_label.setText(str(telemetry.get('speed', '—')))
        self.gear_label.setText(str(telemetry.get('gear', '—')))
        self.fuel_label.setText(str(telemetry.get('fuel', '—')))

        uptime = state.get('uptime', '00:00:00')
        self.uptime_state.setText(uptime)

        self.events_list.clear()
        feed = state.get('feed', []) or []
        if not feed:
            item = QListWidgetItem('Нет событий')
            item.setForeground(QColor('#9ca3af'))
            self.events_list.addItem(item)
        else:
            for entry in feed[:6]:
                text = f"{entry.get('time', '')} — {entry.get('driver', '')} {entry.get('phrase', '')}"
                item = QListWidgetItem(text)
                item.setForeground(QColor(entry.get('color', '#9CA3AF')))
                self.events_list.addItem(item)

        self._update_logs(feed)

    def _update_logs(self, feed: list[dict[str, Any]]) -> None:
        for widget in (self.log_all, self.log_info, self.log_warn, self.log_error):
            widget.clear()

        if not feed:
            item = QListWidgetItem('Логов пока нет')
            item.setForeground(QColor('#9ca3af'))
            for widget in (self.log_all, self.log_info, self.log_warn, self.log_error):
                widget.addItem(item.clone())
            return

        for entry in feed[:20]:
            line = f"{entry.get('time', '')} · {entry.get('event_code', '')} · {entry.get('phrase', '')}"
            log_item = QListWidgetItem(line)
            color = QColor(entry.get('color', '#9CA3AF'))
            log_item.setForeground(color)
            self.log_all.addItem(log_item)

            if entry.get('priority') == 'critical':
                self.log_error.addItem(QListWidgetItem(line))
            elif entry.get('color', '') in ('#FFD700', '#F2C029'):
                self.log_warn.addItem(QListWidgetItem(line))
            else:
                self.log_info.addItem(QListWidgetItem(line))


class RacePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('race')
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(24, 24, 24, 24)

        self.title = TitleLabel('Положение в гонке', self)
        layout.addWidget(self.title)

        self.summary_card = PageCard(self)
        self.summary_leader = SubtitleLabel('Лидер: —', self.summary_card)
        self.summary_count = SubtitleLabel('Список гонщиков: 0', self.summary_card)
        self.summary_card.add_widget(self.summary_leader)
        self.summary_card.add_widget(self.summary_count)
        layout.addWidget(self.summary_card)

        self.grid_table = TableWidget(self)
        self.grid_table.setColumnCount(4)
        self.grid_table.setHorizontalHeaderLabels(['Позиция', 'Гонщик', 'Команда', 'Круг'])
        self.grid_table.verticalHeader().setVisible(False)
        self.grid_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.grid_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid_table.setShowGrid(False)
        self.grid_table.setAlternatingRowColors(True)
        self.grid_table.horizontalHeader().setStretchLastSection(True)
        self.grid_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        layout.addWidget(self.grid_table)
        layout.addStretch(1)

    def update_state(self, state: dict[str, Any]) -> None:
        race = state.get('race', {})
        leader = race.get('leader', '—')
        grid = race.get('grid', []) or []
        self.summary_leader.setText(f'Лидер: {leader}')
        self.summary_count.setText(f'Список гонщиков: {len(grid)}')

        self.grid_table.setRowCount(len(grid))
        for row, driver in enumerate(grid):
            self.grid_table.setItem(row, 0, QTableWidgetItem(str(driver.get('position', '—'))))
            self.grid_table.setItem(row, 1, QTableWidgetItem(driver.get('driver', '—')))
            self.grid_table.setItem(row, 2, QTableWidgetItem(driver.get('team', '—')))
            self.grid_table.setItem(row, 3, QTableWidgetItem(str(driver.get('lap', '—'))))

        if not grid:
            self.grid_table.setRowCount(0)


class CommentatorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('commentary')
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(24, 24, 24, 24)

        self.title = TitleLabel('События и штрафы', self)
        layout.addWidget(self.title)

        self.status_card = PageCard(self)
        self.now_speaking_label = SubtitleLabel('Сейчас: —', self.status_card)
        self.status_card.add_widget(self.now_speaking_label)
        layout.addWidget(self.status_card)

        self.feed_list = ListWidget(self)
        self.feed_list.setSpacing(6)
        self.feed_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.feed_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.feed_list)

    def update_state(self, state: dict[str, Any]) -> None:
        self.now_speaking_label.setText(
            f"Сейчас: {state.get('now_speaking') or '—'}"
        )
        self.feed_list.clear()
        feed = state.get('feed', []) or []
        if not feed:
            item = QListWidgetItem('Нет событий')
            item.setForeground(QColor('#9ca3af'))
            self.feed_list.addItem(item)
            return

        for entry in feed:
            text = f"{entry.get('time', '')} — {entry.get('driver', '')} {entry.get('phrase', '')}"
            item = QListWidgetItem(text)
            color = QColor(entry.get('color', '#9CA3AF'))
            item.setForeground(color)
            if entry.get('muted'):
                item.setForeground(QColor('#787878'))
            self.feed_list.addItem(item)


class SettingsPage(QWidget):
    def __init__(self, engine, settings: dict[str, Any], parent=None):
        super().__init__(parent=parent)
        self.setObjectName('settings')
        self.engine = engine
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(24, 24, 24, 24)

        self.title = TitleLabel('Настройки', self)
        layout.addWidget(self.title)

        self.options_card = PageCard(self)
        self.commentary_toggle = SwitchButton(self.options_card)
        self.commentary_toggle.setText('Включить комментарий')
        self.options_card.add_widget(self.commentary_toggle)

        self.autovoice_toggle = SwitchButton(self.options_card)
        self.autovoice_toggle.setText('Автоозвучка')
        self.options_card.add_widget(self.autovoice_toggle)

        self.critical_toggle = SwitchButton(self.options_card)
        self.critical_toggle.setText('Критические события')
        self.options_card.add_widget(self.critical_toggle)

        self.persona_edit = LineEdit(self.options_card)
        self.persona_edit.setPlaceholderText('Персона (tv, sport, calm)')
        self.options_card.add_widget(self.persona_edit)

        self.min_gap_edit = LineEdit(self.options_card)
        self.min_gap_edit.setPlaceholderText('Минимальная пауза между фразами (сек)')
        self.options_card.add_widget(self.min_gap_edit)

        layout.addWidget(self.options_card)

        self.voice_card = PageCard(self)
        self.voice_engine_label = SubtitleLabel(f'Голосовой движок: {self.engine.voice.engine_name}', self.voice_card)
        self.voice_status_label = SubtitleLabel('', self.voice_card)
        self.voice_card.add_widget(self.voice_engine_label)
        self.voice_card.add_widget(self.voice_status_label)
        layout.addWidget(self.voice_card)

        button_row = QHBoxLayout()
        self.apply_button = PushButton('Применить', self)
        self.test_voice_button = PushButton('Проверить голос', self)
        self.clear_feed_button = PushButton('Очистить ленту', self)
        button_row.addWidget(self.apply_button)
        button_row.addWidget(self.test_voice_button)
        button_row.addWidget(self.clear_feed_button)
        layout.addLayout(button_row)
        layout.addStretch(1)

        self.apply_button.clicked.connect(self.apply_settings)
        self.test_voice_button.clicked.connect(self.test_voice)
        self.clear_feed_button.clicked.connect(self.clear_feed)

    def update_state(self, state: dict[str, Any], settings: dict[str, Any]) -> None:
        self.settings = settings
        self.commentary_toggle.setChecked(bool(settings.get('commentary_enabled', True)))
        self.autovoice_toggle.setChecked(bool(settings.get('autovoice_enabled', True)))
        self.critical_toggle.setChecked(bool(settings.get('critical_events_enabled', True)))
        self.persona_edit.setText(str(settings.get('persona', '')))
        self.min_gap_edit.setText(str(settings.get('min_comment_gap', 4.0)))
        self.voice_engine_label.setText(f'Голосовой движок: {self.engine.voice.engine_name}')

    def apply_settings(self) -> None:
        settings = {
            'commentary_enabled': self.commentary_toggle.isChecked(),
            'autovoice_enabled': self.autovoice_toggle.isChecked(),
            'critical_events_enabled': self.critical_toggle.isChecked(),
            'persona': self.persona_edit.text().strip() or self.settings.get('persona', ''),
        }
        try:
            settings['min_comment_gap'] = float(self.min_gap_edit.text())
        except ValueError:
            settings['min_comment_gap'] = self.settings.get('min_comment_gap', 4.0)

        self.engine.apply_settings(settings)
        self.settings.update(settings)
        self.voice_status_label.setText('Настройки применены')

    def test_voice(self) -> None:
        if not self.test_voice_button.isEnabled():
            return

        self.test_voice_button.setEnabled(False)
        self.voice_status_label.setText('Воспроизведение голоса...')
        threading.Thread(
            target=self._run_voice_test,
            daemon=True,
        ).start()

    def _run_voice_test(self) -> None:
        self.engine.voice.say('Голос Spotter App работает.')
        QTimer.singleShot(0, self._finish_voice_test)

    def _finish_voice_test(self) -> None:
        self.voice_status_label.setText('Голос проверен')
        self.test_voice_button.setEnabled(True)

    def clear_feed(self) -> None:
        self.engine.clear_feed()
        self.voice_status_label.setText('Лента событий очищена')


class SpotterWindow(QWidget):
    def __init__(self, engine, settings: dict[str, Any]):
        super().__init__()
        setTheme(Theme.DARK)

        self.engine = engine
        self.settings = settings

        self.overview_page = OverviewPage(self.engine, self.settings, self)
        self.race_page = RacePage(self)
        self.commentary_page = CommentatorPage(self)
        self.settings_page = SettingsPage(self.engine, self.settings, self)

        self.sidebar = QWidget(self)
        self.sidebar.setObjectName('sidebar')
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(16, 16, 16, 16)
        self.sidebar_layout.setSpacing(12)

        self.brand_label = TitleLabel('Spotter App', self.sidebar)
        self.brand_label.setObjectName('brand_title')
        self.brand_subtitle = SubtitleLabel('Комментатор F1', self.sidebar)
        self.brand_subtitle.setObjectName('brand_subtitle')
        self.sidebar_layout.addWidget(self.brand_label)
        self.sidebar_layout.addWidget(self.brand_subtitle)

        self.nav_overview = PushButton('Обзор', self.sidebar)
        self.nav_race = PushButton('Гонка', self.sidebar)
        self.nav_commentary = PushButton('События', self.sidebar)
        self.nav_settings = PushButton('Настройки', self.sidebar)
        for btn in (self.nav_overview, self.nav_race, self.nav_commentary, self.nav_settings):
            btn.setCheckable(True)
            btn.setObjectName('nav_button')
            btn.setFixedHeight(40)
            self.sidebar_layout.addWidget(btn)

        self.nav_overview.clicked.connect(lambda: self.switch_page(0))
        self.nav_race.clicked.connect(lambda: self.switch_page(1))
        self.nav_commentary.clicked.connect(lambda: self.switch_page(2))
        self.nav_settings.clicked.connect(lambda: self.switch_page(3))

        self.sidebar_layout.addStretch(1)

        self.status_pill = QLabel('Ожидание подключения', self.sidebar)
        self.status_pill.setObjectName('status_pill')
        self.sidebar_layout.addWidget(self.status_pill)

        self.active_nav = [self.nav_overview, self.nav_race, self.nav_commentary, self.nav_settings]
        self.switch_page(0)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.overview_page)
        self.stack.addWidget(self.race_page)
        self.stack.addWidget(self.commentary_page)
        self.stack.addWidget(self.settings_page)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.addWidget(self.stack)

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.sidebar)
        main_layout.addLayout(content_layout, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(main_layout)

        self.setWindowTitle('Spotter App')
        self.setWindowIcon(QIcon(':/qfluentwidgets/images/logo.png'))
        self.resize(1360, 840)

        self.setStyleSheet(
            """
            QWidget#page_card {
                background: #121418;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 20px;
            }
            QWidget#status_card {
                padding: 20px;
            }
            QLabel#status_dot {
                font-size: 18px;
                color: #e02631;
                margin-right: 8px;
            }
            TitleLabel, SubtitleLabel {
                color: #ffffff;
            }
            SubtitleLabel {
                color: #9ca3af;
            }
            QListWidget {
                background: transparent;
                border: none;
            }
            QListWidget::item {
                padding: 12px 10px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }
            QListWidget::item:selected {
                background: rgba(232, 0, 45, 0.14);
            }
            QLineEdit, ComboBox {
                background: #11161f;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
                color: #ffffff;
            }
            QLineEdit:focus, ComboBox:focus {
                border-color: rgba(232, 0, 45, 0.45);
            }
            QWidget#sidebar {
                background: #111318;
                border-right: 1px solid rgba(255, 255, 255, 0.08);
            }
            QWidget#sidebar QPushButton#nav_button {
                background: transparent;
                color: #d1d5db;
                border: 1px solid transparent;
                text-align: left;
                padding-left: 14px;
            }
            QWidget#sidebar QPushButton#nav_button:hover {
                background: rgba(255, 255, 255, 0.05);
                border-color: rgba(255, 255, 255, 0.08);
            }
            QWidget#sidebar QPushButton#nav_button:checked {
                background: rgba(232, 0, 45, 0.12);
                color: #ffffff;
            }
            QLabel#status_pill {
                padding: 10px 14px;
                border-radius: 14px;
                background: #161a21;
                color: #9ca3af;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
            """
        )

        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self.refresh_state)
        self._sync_timer.start(500)
        self.refresh_state()

    def switch_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for btn_idx, btn in enumerate(self.active_nav):
            btn.setChecked(btn_idx == index)

    def refresh_state(self) -> None:
        state = self.engine.get_state()
        cpu = f"{psutil.cpu_percent(interval=None):.0f}%"
        mem = psutil.virtual_memory()
        ram = f"{mem.percent:.0f}% ({round(mem.used / (1024**3), 1)} GB)"

        self.cpu_label.setText(f'CPU: {cpu}')
        self.ram_label.setText(f'RAM: {ram}')

        self.overview_page.update_state(state, cpu, ram)
        self.race_page.update_state(state)
        self.commentary_page.update_state(state)
        self.settings_page.update_state(state, self.settings)
