function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function copyText(text, button) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "true");
      helper.style.position = "absolute";
      helper.style.left = "-9999px";
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      document.body.removeChild(helper);
    }
    if (button) {
      const original = button.textContent;
      button.textContent = "Copied";
      setTimeout(() => {
        button.textContent = original;
      }, 1200);
    }
  } catch (error) {
    console.error(error);
  }
}

function renderToneCards(result) {
  const tones = result.tones || {};
  const cards = Object.entries(tones).map(([tone, body]) => {
    const toneLabel = tone.charAt(0).toUpperCase() + tone.slice(1);
    const safeBody = escapeHtml(body).replaceAll("\n", "<br>");
    return `
      <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="mb-4 flex items-center justify-between gap-4">
          <h4 class="text-lg font-bold text-slate-900">${toneLabel}</h4>
          <button data-copy="${tone}" class="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-900 hover:text-slate-900">
            Copy
          </button>
        </div>
        <p class="copy-target whitespace-normal text-sm leading-7 text-slate-700">${safeBody}</p>
      </article>
    `;
  }).join("");

  return `
    <div class="space-y-4">
      <div class="rounded-3xl border border-slate-200 bg-slate-50 p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p class="text-xs font-bold uppercase tracking-[0.24em] text-slate-500">SEO snapshot</p>
            <h3 class="mt-2 text-xl font-bold text-slate-900">${escapeHtml(result.seo.meta_title || result.title)}</h3>
          </div>
          <button data-copy-all class="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700">
            Copy all
          </button>
        </div>
        <p class="mt-4 text-sm leading-6 text-slate-600">${escapeHtml(result.seo.meta_description || "")}</p>
        <div class="mt-4 flex flex-wrap gap-2">
          ${(result.seo.keywords || []).map((keyword) => `<span class="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700 ring-1 ring-slate-200">${escapeHtml(keyword)}</span>`).join("")}
        </div>
      </div>
      <div class="grid gap-4">
        ${cards}
      </div>
    </div>
  `;
}

function wireCopyButtons(container, result) {
  container.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => {
      const tone = button.getAttribute("data-copy");
      copyText(result.tones[tone], button);
    });
  });

  const copyAll = container.querySelector("[data-copy-all]");
  if (copyAll) {
    copyAll.addEventListener("click", () => {
      const bundle = [
        `Meta title: ${result.seo.meta_title}`,
        `Meta description: ${result.seo.meta_description}`,
        `Keywords: ${(result.seo.keywords || []).join(", ")}`,
        "",
        `Professional:\n${result.tones.professional}`,
        "",
        `Casual:\n${result.tones.casual}`,
        "",
        `Urgent:\n${result.tones.urgent}`,
      ].join("\n");
      copyText(bundle, copyAll);
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("generator-form");
  const output = document.getElementById("output-panel");
  const status = document.getElementById("form-status");
  const submitButton = document.getElementById("submit-button");

  const initialResult = window.__INITIAL_DEMO__;
  if (initialResult && output) {
    output.innerHTML = renderToneCards(initialResult);
    wireCopyButtons(output, initialResult);
  }

  if (!form || !output || !status || !submitButton) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.textContent = "Generating three tone variants...";
    submitButton.disabled = true;
    submitButton.classList.add("opacity-70");

    const formData = new FormData(form);
    const payload = {
      title: formData.get("title"),
      specs: formData.get("specs"),
      audience: formData.get("audience"),
    };

    try {
      const response = await fetch("/submit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || "Generation failed");
      }

      output.innerHTML = renderToneCards(data);
      wireCopyButtons(output, data);
      status.textContent = "Ready to copy.";
    } catch (error) {
      status.textContent = error.message || "Something went wrong.";
    } finally {
      submitButton.disabled = false;
      submitButton.classList.remove("opacity-70");
    }
  });
});
