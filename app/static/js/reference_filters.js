(() => {
  function syncSkillSelect(campaignSelect) {
    const target = document.querySelector(campaignSelect.dataset.skillFilter);
    if (!target) return;

    const campaignId = campaignSelect.value;
    const current = target.value;
    const seenLabels = new Set();

    [...target.options].forEach((option) => {
      if (!option.dataset.campaignId) {
        option.hidden = false;
        option.disabled = false;
        return;
      }

      const visible = !campaignId || option.dataset.campaignId === campaignId;
      const labelKey = option.textContent.trim().toLocaleLowerCase();
      const duplicate = visible && seenLabels.has(labelKey);

      option.hidden = !visible || duplicate;
      option.disabled = !visible || duplicate;

      if (visible && !duplicate) {
        seenLabels.add(labelKey);
      }
    });

    target.disabled = false;
    target.setAttribute("aria-disabled", "false");

    if (current && [...target.options].some((o) => o.value === current && !o.disabled)) {
      target.value = current;
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
