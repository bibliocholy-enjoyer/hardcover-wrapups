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
