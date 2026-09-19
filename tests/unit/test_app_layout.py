from pathlib import Path


APP_CSS = Path("app/static/css/app.css")


def test_mobile_backdrop_is_not_a_desktop_grid_item():
    css = APP_CSS.read_text(encoding="utf-8")

    # .mobile-backdrop is a sibling of .sidebar and .main-content inside
    # .app-shell. It must be removed from the desktop grid, then restored
    # only inside the mobile breakpoint where it acts as the overlay.
    assert ".mobile-backdrop{display:none}" in css
    assert ".mobile-backdrop{display:block;position:fixed" in css
