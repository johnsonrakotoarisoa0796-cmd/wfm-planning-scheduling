(() => {
  function syncSkillSelect(campaignSelect) {
    const target = document.querySelector(campaignSelect.dataset.skillFilter);
    if (!target) return;

    const campaignId = campaignSelect.value;
    const current = target.value;
    let visibleCount = 0;
    [...target.options].forEach((option) => {
      if (!option.dataset.campaignId) {
        option.hidden = false;
        option.disabled = false;
        return;
      }
      const visible = !campaignId || option.dataset.campaignId === campaignId;
      option.hidden = !visible;
      option.disabled = !visible;
      if (visible) visibleCount += 1;
    });

    if (current && [...target.options].some((o) => o.value === current && !o.disabled)) {
      target.value = current;
    } else if (visibleCount) {
      const first = [...target.options].find((o) => !o.disabled && o.value);
      target.value = first ? first.value : "";
    } else {
      target.value = "";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-skill-filter]").forEach((campaignSelect) => {
      syncSkillSelect(campaignSelect);
      campaignSelect.addEventListener("change", () => syncSkillSelect(campaignSelect));
    });
  });
})();