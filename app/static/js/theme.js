(() => {
    const STORAGE_KEY = "wfm-theme";

    const getSystemTheme = () =>
        window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light";

    const getSavedTheme = () => {
        try {
            const saved = window.localStorage.getItem(STORAGE_KEY);
            return saved === "light" || saved === "dark" ? saved : null;
        } catch {
            return null;
        }
    };

    const applyTheme = (theme, persist = false) => {
        const normalized = theme === "dark" ? "dark" : "light";
        document.documentElement.dataset.theme = normalized;
        document.documentElement.style.colorScheme = normalized;

        if (persist) {
            try {
                window.localStorage.setItem(STORAGE_KEY, normalized);
            } catch {
                // localStorage may be unavailable in hardened browser contexts.
            }
        }

        document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
            const isDark = normalized === "dark";
            button.setAttribute("aria-pressed", String(isDark));
            button.setAttribute("title", isDark ? "Passer au mode clair" : "Passer au mode sombre");
            button.setAttribute("aria-label", isDark ? "Passer au mode clair" : "Passer au mode sombre");

            const icon = button.querySelector("[data-theme-icon]");
            const label = button.querySelector("[data-theme-label]");
            if (icon) icon.textContent = isDark ? "☀" : "◐";
            if (label) label.textContent = isDark ? "Mode clair" : "Mode sombre";
        });
    };

    applyTheme(getSavedTheme() || getSystemTheme());

    document.addEventListener("DOMContentLoaded", () => {
        applyTheme(getSavedTheme() || document.documentElement.dataset.theme || getSystemTheme());

        document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
            button.addEventListener("click", () => {
                const current = document.documentElement.dataset.theme || "light";
                applyTheme(current === "dark" ? "light" : "dark", true);
            });
        });
    });
})();