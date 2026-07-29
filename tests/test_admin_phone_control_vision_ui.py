"""Static contract for Brief 123's phone-control vision override card."""
from pathlib import Path

from admin_static_assets import read_admin_client_source, read_admin_page


ROOT = Path(__file__).parents[1]
I18N = (ROOT / "admin" / "static" / "i18n.js").read_text(encoding="utf-8")


def test_model_routing_page_exposes_phone_control_vision_override_with_inheritance_copy():
    page = read_admin_page("model-routing")
    source = read_admin_client_source()

    for marker in (
        'id="phone-vision-enabled"',
        'id="phone-vision-model"',
        'id="phone-vision-base-url"',
        'id="phone-vision-api-key"',
        'data-action="savePhoneControlVisionParams"',
        'status.phone_vision.hint',
        'status.phone_vision.inherit',
    ):
        assert marker in page
    for marker in (
        "function loadPhoneControlVisionParams()",
        "function savePhoneControlVisionParams()",
        "'/vision-params/phone-control'",
        "loadPhoneControlVisionParams();",
    ):
        assert marker in source


def test_phone_control_vision_copy_has_matching_english_and_chinese_keys():
    for key in (
        "status.phone_vision.title",
        "status.phone_vision.hint",
        "status.phone_vision.inherit",
        "status.phone_vision.saved",
    ):
        assert I18N.count(f"'{key}'") == 2
