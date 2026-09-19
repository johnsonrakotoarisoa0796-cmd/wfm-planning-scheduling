from pathlib import Path
import re


APP_CSS = Path("app/static/css/app.css")
BASE_CSS = Path("app/static/css/base.css")
THEME_JS = Path("app/static/js/theme.js")
TEMPLATES = Path("app/templates")


def test_mobile_backdrop_is_not_a_desktop_grid_item():
    css = APP_CSS.read_text(encoding="utf-8")

    # The backdrop is a sibling of the sidebar/main content and must not
    # participate in the desktop grid. It is restored only at mobile widths.
    assert re.search(r"\.mobile-backdrop\s*\{\s*display\s*:\s*none\s*;?\s*\}", css)
    assert re.search(
        r"@media\s*\(max-width:\s*980px\)[\s\S]*?\.mobile-backdrop\s*\{\s*"
        r"display\s*:\s*block\s*;\s*position\s*:\s*fixed",
        css,
    )


def test_theme_system_has_persistent_light_and_dark_modes():
    base_css = BASE_CSS.read_text(encoding="utf-8")
    theme_js = THEME_JS.read_text(encoding="utf-8")

    assert ':root[data-theme="dark"]' in base_css
    assert "color-scheme: light" in base_css
    assert "color-scheme: dark" in base_css
    assert "localStorage" in theme_js
    assert "wfm-theme" in theme_js
    assert "data-theme-toggle" in theme_js


def test_templates_do_not_reintroduce_inline_style_blocks():
    for template in TEMPLATES.rglob("*.html"):
        content = template.read_text(encoding="utf-8")
        assert "<style" not in content, f"Style block duplicated in {template}"


def test_templates_do_not_reintroduce_layout_inline_styles():
    for template in TEMPLATES.rglob("*.html"):
        content = template.read_text(encoding="utf-8")
        assert " style=" not in content, f"Inline layout style duplicated in {template}"
