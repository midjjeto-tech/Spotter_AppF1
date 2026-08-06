from core.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, _vk_from_settings


def test_vk_from_settings_valid_letter():
    assert _vk_from_settings(
        {"ctrl": True, "alt": True, "shift": False, "key": "V"}
    ) == (MOD_CONTROL | MOD_ALT, ord("V"))


def test_vk_from_settings_lowercase_key_normalized():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": "v"}
    ) == (MOD_CONTROL, ord("V"))


def test_vk_from_settings_digit():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": "5"}
    ) == (MOD_CONTROL, ord("5"))


def test_vk_from_settings_function_key():
    assert _vk_from_settings(
        {"ctrl": False, "alt": True, "shift": False, "key": "F5"}
    ) == (MOD_ALT, 0x70 + 4)


def test_vk_from_settings_f24_upper_bound():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": "F24"}
    ) == (MOD_CONTROL, 0x70 + 23)


def test_vk_from_settings_shift_modifier():
    assert _vk_from_settings(
        {"ctrl": False, "alt": False, "shift": True, "key": "Q"}
    ) == (MOD_SHIFT, ord("Q"))


def test_vk_from_settings_allows_single_key_without_modifier():
    assert _vk_from_settings(
        {"ctrl": False, "alt": False, "shift": False, "key": "V"}
    ) == (0, ord("V"))


def test_vk_from_settings_accepts_named_key():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": "ESCAPE"}
    ) == (MOD_CONTROL, 0x1B)


def test_vk_from_settings_accepts_space_without_modifier():
    assert _vk_from_settings(
        {"ctrl": False, "alt": False, "shift": False, "key": "SPACE"}
    ) == (0, 0x20)


def test_vk_from_settings_accepts_arrow_numpad_and_punctuation():
    assert _vk_from_settings({"key": "ARROW_UP"}) == (0, 0x26)
    assert _vk_from_settings({"key": "NUM7"}) == (0, 0x67)
    assert _vk_from_settings({"key": "SEMICOLON"}) == (0, 0xBA)


def test_vk_from_settings_accepts_media_key():
    assert _vk_from_settings({"key": "MEDIA_PLAY_PAUSE"}) == (0, 0xB3)


def test_vk_from_settings_rejects_unknown_or_modifier_only_key():
    assert _vk_from_settings({"key": "CONTROL"}) is None
    assert _vk_from_settings({"key": "NO_SUCH_KEY"}) is None


def test_vk_from_settings_none_input():
    assert _vk_from_settings(None) is None


def test_vk_from_settings_missing_key():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": ""}
    ) is None
