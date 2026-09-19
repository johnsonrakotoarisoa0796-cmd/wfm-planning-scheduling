from pathlib import Path


APP_CSS = Path("app/static/css/app.css")
BASE_CSS = Path("app/static/css/base.css")
THEME_JS = Path("app/static/js/theme.js")
TEMPLATES = Path("app/templates")


def test_mobile_backdrop_is_not_a_desktop_grid_item():
    css = APP_CSS.read_text(encoding="utf-8").replace(" ", "").replace("\n", "")

    # .mobile-backdrop is a sibling of .sidebar and .main-content inside
    # .app-shell. It must be removed from the desktop grid, then restored
    # only inside the mobile breakpoint where it acts as the overlay.
    assert ".mobile-backdrop{display:none}" in css
    assert ".mobile-backdrop{display:block;position:fixed" in css


def test_theme_system_has_persistent_light_and_dark_modes():
    base_css = BASE_CSS.read_text(encoding="utf-8")
    theme_js = THEME_JS.read_text(encoding="utf-8")

    assert ':root[data-theme="dark"]' in base_css
    assert "color-scheme: light" in base_css
    assert "color-scheme: dark" in base_css
    assert 'localStorage' in theme_js
    assert 'wfm-theme' in theme_js
    assert 'data-theme-toggle' in theme_js


def test_templates_do_not_reintroduce_inline_style_blocks():
    for template in TEMPLATES.rglob("*.html"):
        content = template.read_text(encoding="utf-8")
        assert "<style" not in content, f"Style block duplicated in {template}"


def test_only_dynamic_interval_bars_use_inline_style():
    for template in TEMPLATES.rglob("*.html"):
        if template.as_posix().endswith("partials/interval_strip.html"):
            continue
        content = template.read_text(encoding="utf-8")
        assert " style=" not in content, f"Inline style duplicated in {template}"
