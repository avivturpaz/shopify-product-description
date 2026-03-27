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
      setTimeout(() => { button.textContent = original; }, 1200);
    }
  } catch (error) {
    console.error(error);
  }
}

function renderToneCards(result) {
  // Support both {tones: {...}} and flat {professional, casual, urgent}
  const tones = result.tones || result;
  const seo = result.seo || null;

  const toneOrder = ["professional", "casual", "urgent"];
  const cards = toneOrder
    .filter((tone) => tones[tone])
    .map((tone) => {
      const toneLabel = tone.charAt(0).toUpperCase() + tone.slice(1);
      const safeBody = escapeHtml(tones[tone]).replaceAll("\n", "<br>");
      return `
        <div class="output-card" style="margin-bottom:12px;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px;">
            <h4 style="margin:0; font-size:1rem; font-weight:800; color:#0f172a;">${toneLabel}</h4>
            <button data-copy="${tone}" class="small-cta" style="padding:6px 16px; font-size:0.85rem;">
              Copy
            </button>
          </div>
          <p class="copy-target" data-tone="${tone}" style="font-size:0.95rem; color:#334155; line-height:1.7; margin:0;">${safeBody}</p>
        </div>
      `;
    }).join("");

  let seoHtml = "";
  if (seo) {
    const keywords = (seo.keywords || [])
      .map((k) => `<span style="background:#f1f5f9; border-radius:999px; padding:3px 10px; font-size:0.8rem; font-weight:600; color:#475569; margin:2px 2px 0 0; display:inline-block;">${escapeHtml(k)}</span>`)
      .join("");
    seoHtml = `
      <div class="output-card" style="background:#f8fafc; margin-bottom:12px;">
        <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:8px;">
          <div>
            <p class="panel-title" style="color:#64748b;">SEO snapshot</p>
            <h3 style="margin:6px 0 0; font-size:1.1rem; font-weight:800; color:#0f172a;">${escapeHtml(seo.meta_title || "")}</h3>
          </div>
          <button data-copy-all class="small-cta" style="padding:6px 16px; font-size:0.85rem; white-space:nowrap;">
            Copy all
          </button>
        </div>
        <p style="font-size:0.9rem; color:#475569; line-height:1.6; margin:8px 0;">${escapeHtml(seo.meta_description || "")}</p>
        <div style="margin-top:8px;">${keywords}</div>
      </div>
    `;
  }

  return seoHtml + cards;
}

function wireCopyButtons(container, result) {
  const tones = result.tones || result;

  container.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => {
      const tone = button.getAttribute("data-copy");
      copyText(tones[tone] || "", button);
    });
  });

  const copyAll = container.querySelector("[data-copy-all]");
  if (copyAll && result.seo) {
    copyAll.addEventListener("click", () => {
      const bundle = [
        `Meta title: ${result.seo.meta_title}`,
        `Meta description: ${result.seo.meta_description}`,
        `Keywords: ${(result.seo.keywords || []).join(", ")}`,
        "",
        `Professional:\n${tones.professional || ""}`,
        "",
        `Casual:\n${tones.casual || ""}`,
        "",
        `Urgent:\n${tones.urgent || ""}`,
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

  // Render initial demo (flat {professional, casual, urgent} format)
  const initialResult = window.__INITIAL_DEMO__;
  if (initialResult && output && Object.keys(initialResult).length > 0) {
    output.innerHTML = renderToneCards(initialResult);
    wireCopyButtons(output, initialResult);
  }

  if (!form || !output || !status || !submitButton) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    // Show spinner
    output.innerHTML = `
      <div class="output-card" style="text-align:center; padding:40px 20px;">
        <div style="display:inline-block; width:36px; height:36px; border:3px solid rgba(251,191,36,0.3); border-top-color:#fbbf24; border-radius:50%; animation:spin 0.8s linear infinite;"></div>
        <p style="margin-top:16px; color:#94a3b8; font-size:0.95rem;">Generating three tone variants…</p>
      </div>
    `;
    status.textContent = "Generating…";
    submitButton.disabled = true;

    const formData = new FormData(form);
    const payload = {
      title: formData.get("title"),
      specs: formData.get("specs"),
      audience: formData.get("audience"),
    };

    try {
      const response = await fetch("/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();

      if (!response.ok || !data.success) {
        const payUrl = data.pay_url || "/pay";
        if (response.status === 429) {
          output.innerHTML = `
            <div class="output-card" style="text-align:center; padding:32px 20px;">
              <p style="font-size:1rem; font-weight:700; color:#0f172a; margin:0 0 12px;">${escapeHtml(data.error || "Limit reached")}</p>
              <a href="${escapeHtml(payUrl)}" class="cta" style="display:inline-block;">Get unlimited access — $15</a>
            </div>
          `;
          status.textContent = "Free limit reached.";
          return;
        }
        throw new Error(data.error || "Generation failed");
      }

      output.innerHTML = renderToneCards(data);
      wireCopyButtons(output, data);
      status.textContent = "Done — ready to copy.";
      output.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      output.innerHTML = `<div class="output-card"><p style="color:#ef4444; margin:0;">${escapeHtml(error.message || "Something went wrong.")}</p></div>`;
      status.textContent = "Error — try again.";
    } finally {
      submitButton.disabled = false;
    }
  });
});
