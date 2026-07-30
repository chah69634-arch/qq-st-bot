"""Regression coverage for persisted admin navigation groups."""

from admin_static_assets import read_admin_client_source


def test_navigation_restore_discovers_all_rendered_groups():
    source = read_admin_client_source()

    assert "document.querySelectorAll('[id^=\"navgroup-\"]')" in source
    assert "const key = group.id.slice('navgroup-'.length);" in source
    assert "for(const key of ['create','ops','state','observe'])" not in source
    assert 'data-action-args=\'["external-tools"]\'' in source
    assert 'data-action-args=\'["presence"]\'' in source
