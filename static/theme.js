// Color theme: "system" (follow Windows), "light" or "dark", remembered in localStorage.
// Loaded as a classic blocking script in <head> so data-theme is set before the first paint (no flash).
(() => {
  const STORAGE_KEY = "n2-theme";
  const CHOICES = ["system", "light", "dark"];
  const LABELS = { system: "Match system", light: "Light", dark: "Dark" };
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const root = document.documentElement;

  function savedChoice() {
    const choice = localStorage.getItem(STORAGE_KEY);
    return CHOICES.includes(choice) ? choice : "system";
  }

  function systemTheme() {
    return systemDark.matches ? "dark" : "light";
  }

  // From "system", go to the opposite of what is showing, so every click from there changes the colors.
  function nextChoice(choice) {
    const opposite = systemTheme() === "dark" ? "light" : "dark";
    if (choice === "system") return opposite;
    if (choice === opposite) return systemTheme();
    return "system";
  }

  function apply() {
    const choice = savedChoice();
    root.dataset.themeChoice = choice;
    root.dataset.theme = choice === "system" ? systemTheme() : choice;
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    const label = `Theme: ${LABELS[choice]}${choice === "system" ? ` (${LABELS[systemTheme()].toLowerCase()})` : ""}`;
    button.title = `${label} - click for ${LABELS[nextChoice(choice)].toLowerCase()}`;
    button.setAttribute("aria-label", label);
  }

  apply();
  systemDark.addEventListener("change", apply);
  // Keep other windows of the app in step.
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) apply();
  });
  document.addEventListener("DOMContentLoaded", () => {
    apply();
    document.getElementById("theme-toggle").addEventListener("click", () => {
      const choice = nextChoice(savedChoice());
      localStorage.setItem(STORAGE_KEY, choice);
      apply();
      const detail = choice === "system" ? `${LABELS.system} (${LABELS[systemTheme()].toLowerCase()})` : LABELS[choice];
      document.dispatchEvent(new CustomEvent("n2:themechange", { detail: `Theme: ${detail}` }));
    });
  });
})();
