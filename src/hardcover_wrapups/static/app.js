// While the image is being built (a few seconds), show that something is happening.
// The site works without this script.
document.addEventListener("submit", (event) => {
  const form = event.target;
  const busyText = form.dataset.busyText;
  if (!busyText) return;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  form.querySelector(".busy").textContent = busyText;
});

// Coming back with the browser's Back button can restore the disabled button; reset it.
window.addEventListener("pageshow", () => {
  document.querySelectorAll("form[data-busy-text]").forEach((form) => {
    form.querySelector("button[type=submit]").disabled = false;
    form.querySelector(".busy").textContent = "";
  });
});

// Keep the season in step with the month, unless someone picked a different season.
document.querySelectorAll("select[name=month]").forEach((month) => {
  const season = month.form.querySelector("select[name=theme]");
  if (!season) return;
  let previous = month.selectedOptions[0].dataset.season;
  month.addEventListener("change", () => {
    const next = month.selectedOptions[0].dataset.season;
    if (season.value === previous) season.value = next;
    previous = next;
  });
});

// Show the season and books-per-row fields only for the styles that use them.
// Hidden fields are disabled too, so they aren't checked or sent.
document.querySelectorAll("form [data-styles]").forEach((field) => {
  const form = field.closest("form");
  const update = () => {
    const style = form.querySelector("input[name=style]:checked")?.value;
    field.hidden = !field.dataset.styles.split(" ").includes(style);
    field.querySelectorAll("input, select").forEach((input) => { input.disabled = field.hidden; });
  };
  form.addEventListener("change", update);
  update();
});
