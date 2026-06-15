(function () {
  // i18n: window.I18N is the active-locale msgid→msgstr map injected by the
  // template. t() mirrors gettext — the English source string is the key; a
  // missing translation falls back to that key. t() also supports %(name)s
  // named interpolation so dynamic strings stay one translatable msgid.
  const I18N = window.I18N || {};
  function t(str, vars) {
    let out = Object.prototype.hasOwnProperty.call(I18N, str) ? I18N[str] : str;
    if (vars) {
      out = out.replace(/%\((\w+)\)s/g, (m, k) =>
        Object.prototype.hasOwnProperty.call(vars, k) ? vars[k] : m);
    }
    return out;
  }

  const root = document.documentElement;
  const appShell = document.getElementById("app-shell");
  const sidebar = document.getElementById("sidebar");
  const contentPanel = document.getElementById("content-panel");
  const searchInput = document.getElementById("file-search");
  const themeSelect = document.getElementById("theme-select");
  const mermaidThemeSelect = document.getElementById("mermaid-theme-select");
  const fontSelect = document.getElementById("font-select");
  const widthSelect = document.getElementById("width-select");
  const sidebarCollapse = document.getElementById("sidebar-collapse");
  const sidebarShow = document.getElementById("sidebar-show");
  const selectedPath = new URLSearchParams(window.location.search).get("file") || "";
  const contentScrollKey = `markwright-content-scroll:${selectedPath}`;
  const sidebarScrollKey = "markwright-sidebar-scroll";
  const sidebarHiddenKey = "markwright-sidebar-hidden";

  const THEMES = ["light", "dark", "sepia", "nord", "solarized-light", "solarized-dark", "retro-sun", "monokai", "gruvbox-dark-hard", "github-light-default", "quiet-light", "dracula", "one-dark", "one-light", "tokyo-night", "catppuccin-mocha", "catppuccin-latte", "night-owl", "material-palenight", "ayu-light", "cobalt2"];
  const DARK_THEMES = new Set(["dark", "nord", "solarized-dark", "monokai", "gruvbox-dark-hard", "dracula", "one-dark", "tokyo-night", "catppuccin-mocha", "night-owl", "material-palenight", "cobalt2"]);

  // Mermaid diagram theme. The selector offers:
  //   "auto"             -> custom theme derived from the active page palette
  //   "palette:<theme>"  -> custom theme derived from a specific page palette
  //   a mermaid built-in -> "default"/"neutral"/"dark"/"forest"/"base"
  // The palette-derived themes use mermaid's "base" theme plus themeVariables
  // pulled straight from the page's CSS custom properties, so they stay in
  // sync with the general themes (single source of truth in style.css).
  const MERMAID_BUILTINS = new Set(["default", "neutral", "dark", "forest", "base"]);
  const MERMAID_PREFS = new Set(["auto", ...THEMES.map((t) => "palette:" + t), ...MERMAID_BUILTINS]);
  const mermaidThemeKey = "markwright-mermaid-theme";

  function mermaidThemePref() {
    const stored = localStorage.getItem(mermaidThemeKey) || "auto";
    return MERMAID_PREFS.has(stored) ? stored : "auto";
  }

  // Read a page theme's palette by resolving its CSS custom properties on a
  // throwaway element carrying the matching data-theme attribute.
  function readPalette(themeName) {
    const probe = document.createElement("div");
    probe.dataset.theme = THEMES.includes(themeName) ? themeName : "light";
    probe.style.display = "none";
    document.body.appendChild(probe);
    const cs = getComputedStyle(probe);
    const get = (name) => cs.getPropertyValue(name).trim();
    const palette = {
      bg: get("--bg"),
      panel: get("--panel"),
      panelAlt: get("--panel-alt"),
      text: get("--text"),
      muted: get("--muted"),
      border: get("--border"),
      accent: get("--accent"),
      accentSoft: get("--accent-soft"),
    };
    probe.remove();
    return palette;
  }

  function isDarkColor(hex) {
    const m = /^#?([0-9a-fA-F]{6})$/.exec(hex || "");
    if (!m) return false;
    const n = parseInt(m[1], 16);
    const r = (n >> 16) & 255;
    const g = (n >> 8) & 255;
    const b = n & 255;
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5;
  }

  // Linearly blend two 6-digit hex colors (t=0 -> a, t=1 -> b). Returns `a`
  // unchanged if either input isn't a parseable hex, so it degrades safely.
  function mixHex(a, b, t) {
    const ma = /^#?([0-9a-fA-F]{6})$/.exec(a || "");
    const mb = /^#?([0-9a-fA-F]{6})$/.exec(b || "");
    if (!ma || !mb) return a;
    const na = parseInt(ma[1], 16);
    const nb = parseInt(mb[1], 16);
    const lerp = (x, y) => Math.round(x + (y - x) * t);
    const r = lerp((na >> 16) & 255, (nb >> 16) & 255);
    const g = lerp((na >> 8) & 255, (nb >> 8) & 255);
    const bch = lerp(na & 255, nb & 255);
    return "#" + ((1 << 24) | (r << 16) | (g << 8) | bch).toString(16).slice(1);
  }

  function paletteThemeConfig(themeName) {
    const p = readPalette(themeName);
    return {
      theme: "base",
      themeVariables: {
        darkMode: isDarkColor(p.bg),
        background: p.bg,
        primaryColor: p.panelAlt,
        primaryTextColor: p.text,
        primaryBorderColor: p.accent,
        secondaryColor: p.accentSoft,
        secondaryTextColor: p.text,
        secondaryBorderColor: p.border,
        tertiaryColor: p.panel,
        tertiaryTextColor: p.text,
        tertiaryBorderColor: p.border,
        lineColor: p.accent,
        textColor: p.text,
        mainBkg: p.panelAlt,
        nodeBorder: p.accent,
        // Subgraph (cluster) fill: a faint accent tint of the page base so the
        // group reads as a lightly theme-colored canvas with nodes (panelAlt)
        // floating on top; border is a stronger accent blend for definition.
        clusterBkg: mixHex(p.bg, p.accent, 0.1),
        clusterBorder: mixHex(p.border, p.accent, 0.5),
        titleColor: p.text,
        edgeLabelBackground: p.panel,
        labelBoxBkgColor: p.panelAlt,
        noteBkgColor: p.accentSoft,
        noteTextColor: p.text,
        noteBorderColor: p.border,
        actorBkg: p.panelAlt,
        actorBorder: p.accent,
        actorTextColor: p.text,
        pie1: p.accent,
        pie2: p.accentSoft,
      },
    };
  }

  // Returns the config object passed to mermaid.initialize for the current
  // preference. Builtins clear themeVariables so a prior palette doesn't bleed.
  function mermaidConfigFor(pref) {
    if (pref === "auto") return paletteThemeConfig(root.dataset.theme);
    if (pref.indexOf("palette:") === 0) return paletteThemeConfig(pref.slice(8));
    if (MERMAID_BUILTINS.has(pref)) return { theme: pref, themeVariables: {} };
    return paletteThemeConfig(root.dataset.theme);
  }

  // Shared with the inline init script in index.html so the first render and
  // every re-render resolve the theme identically.
  window.__mermaidThemeConfig = function () {
    return mermaidConfigFor(mermaidThemePref());
  };

  function applyTheme(theme) {
    const resolved = THEMES.includes(theme) ? theme : "light";
    root.dataset.theme = resolved;
    if (themeSelect) themeSelect.value = resolved;
  }

  function applySidebarHidden(hidden) {
    appShell.classList.toggle("is-sidebar-hidden", hidden);
    if (sidebarCollapse) sidebarCollapse.setAttribute("aria-expanded", String(!hidden));
    if (sidebarShow) sidebarShow.setAttribute("aria-expanded", String(!hidden));
  }

  function setSidebarHidden(hidden) {
    localStorage.setItem(sidebarHiddenKey, String(hidden));
    applySidebarHidden(hidden);
  }

  // Auto dark mode: with no explicit choice, follow the OS preference (and keep
  // following it live until the user picks a theme, which is then persisted).
  const prefersDarkMq = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
  const systemTheme = () => (prefersDarkMq && prefersDarkMq.matches ? "dark" : "light");
  applyTheme(localStorage.getItem("markwright-theme") || systemTheme());
  if (prefersDarkMq && prefersDarkMq.addEventListener) {
    prefersDarkMq.addEventListener("change", function () {
      if (!localStorage.getItem("markwright-theme")) applyTheme(systemTheme());
    });
  }
  applySidebarHidden(localStorage.getItem(sidebarHiddenKey) === "true");

  if (sidebarCollapse) sidebarCollapse.addEventListener("click", () => setSidebarHidden(true));
  if (sidebarShow) sidebarShow.addEventListener("click", () => setSidebarHidden(false));

  // --- Keyboard shortcuts help + global single-key shortcuts ---------------
  // A help dialog listing every shortcut (opened from the ⌨ button or "?"),
  // plus a handful of app-wide single-key shortcuts. All single-key shortcuts
  // bail while the user is typing or editing, mirroring the focus-mode "f".
  (function setupShortcuts() {
    const modal = document.getElementById("shortcuts-modal");
    const openBtn = document.getElementById("shortcuts-toggle");
    const closeBtn = document.getElementById("shortcuts-close");
    if (!modal) return;
    let lastFocused = null;

    function isOpen() { return !modal.hidden; }
    function setOpen(open) {
      if (open) lastFocused = document.activeElement;
      modal.hidden = !open;
      if (openBtn) openBtn.setAttribute("aria-expanded", String(open));
      if (open) {
        (closeBtn || modal).focus();
      } else if (lastFocused && lastFocused.focus) {
        lastFocused.focus();
      }
    }

    if (openBtn) openBtn.addEventListener("click", () => setOpen(!isOpen()));
    if (closeBtn) closeBtn.addEventListener("click", () => setOpen(false));
    // Click on the backdrop (outside the card) closes.
    modal.addEventListener("click", (event) => { if (event.target === modal) setOpen(false); });

    function clickIf(id) {
      const el = document.getElementById(id);
      if (el && !el.disabled) el.click();
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) { event.preventDefault(); setOpen(false); return; }
      if (event.ctrlKey || event.metaKey || event.altKey) return;

      const ae = document.activeElement;
      const typing = ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.isContentEditable ||
                            (ae.closest && ae.closest(".CodeMirror")));
      // "?" (Shift+/) opens help from anywhere except while typing.
      if (event.key === "?") {
        if (typing) return;
        event.preventDefault();
        setOpen(!isOpen());
        return;
      }
      if (typing || editActive || isOpen()) return;

      switch (event.key) {
        case "/":
          if (searchInput) { event.preventDefault(); searchInput.focus(); searchInput.select(); }
          break;
        case "b":
        case "B":
          event.preventDefault();
          setSidebarHidden(!appShell.classList.contains("is-sidebar-hidden"));
          break;
        case "s":
        case "S":
          event.preventDefault();
          clickIf("source-view-toggle");
          break;
        case "e":
        case "E":
          event.preventDefault();
          clickIf("edit-toggle");
          break;
        case "t":
        case "T": {
          // Back to top — reuse the floating button's mobile-aware scroll.
          const topBtn = document.querySelector(".back-to-top");
          if (topBtn) { event.preventDefault(); topBtn.click(); }
          break;
        }
      }
    });
  })();

  const tocCollapse = document.getElementById("toc-collapse");
  const tocShow = document.getElementById("toc-show");
  const tocHiddenKey = "markwright-toc-hidden";

  function applyTocHidden(hidden) {
    appShell.classList.toggle("is-toc-hidden", hidden);
    if (tocCollapse) tocCollapse.setAttribute("aria-expanded", String(!hidden));
    if (tocShow) tocShow.setAttribute("aria-expanded", String(!hidden));
  }

  function setTocHidden(hidden) {
    localStorage.setItem(tocHiddenKey, String(hidden));
    applyTocHidden(hidden);
  }

  if (tocCollapse || tocShow) {
    applyTocHidden(localStorage.getItem(tocHiddenKey) === "true");
    if (tocCollapse) tocCollapse.addEventListener("click", () => setTocHidden(true));
    if (tocShow) tocShow.addEventListener("click", () => setTocHidden(false));
  }

  // Frontmatter panel: on-screen show/hide (persisted, default shown). The
  // toggle button is disabled when the current doc has no panel; PDF
  // visibility is a separate, export-time option.
  const frontmatterToggle = document.getElementById("frontmatter-toggle");
  const frontmatterHiddenKey = "markwright-frontmatter-hidden";
  // Whether *this* document actually has a frontmatter panel. The hidden state
  // is a global, persisted preference, so without this distinction a hidden
  // panel and a document that simply has no frontmatter look identical.
  const hasFrontmatter = !!document.querySelector(".frontmatter-panel");

  function applyFrontmatterHidden(hidden) {
    root.classList.toggle("is-frontmatter-hidden", hidden);
    if (!frontmatterToggle) return;
    frontmatterToggle.setAttribute("aria-pressed", String(!hidden));
    // Truthful, state-specific tooltip so it's always clear (a) whether the
    // document has frontmatter at all and (b) whether it's shown or hidden.
    frontmatterToggle.title = !hasFrontmatter
      ? t("This document has no frontmatter")
      : hidden
        ? t("Frontmatter hidden — click to show")
        : t("Hide frontmatter panel");
  }

  applyFrontmatterHidden(localStorage.getItem(frontmatterHiddenKey) === "true");

  if (frontmatterToggle && hasFrontmatter) {
    frontmatterToggle.disabled = false;
    frontmatterToggle.addEventListener("click", function () {
      const hidden = !root.classList.contains("is-frontmatter-hidden");
      localStorage.setItem(frontmatterHiddenKey, String(hidden));
      applyFrontmatterHidden(hidden);
    });
  }

  function setupMermaidBlocks() {
    document.querySelectorAll("pre.mermaid").forEach(function (pre) {
      if (pre.closest(".mermaid-block")) return;
      if (pre.dataset.source === undefined) return;

      const wrapper = document.createElement("div");
      wrapper.className = "mermaid-block";

      const toolbar = document.createElement("div");
      toolbar.className = "mermaid-toolbar";

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "mermaid-toggle";
      toggle.textContent = t("Show source");
      toggle.setAttribute("aria-label", t("Toggle diagram source"));

      const copyButton = makeCopyButton();
      copyButton.classList.add("mermaid-copy");

      toolbar.appendChild(toggle);
      toolbar.appendChild(copyButton);

      const sourcePre = document.createElement("pre");
      sourcePre.className = "mermaid-source";
      sourcePre.hidden = true;
      const code = document.createElement("code");
      code.textContent = pre.dataset.source;
      sourcePre.appendChild(code);

      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(toolbar);
      wrapper.appendChild(pre);
      wrapper.appendChild(sourcePre);
    });
  }

  function resetMermaidBlocksToDiagram() {
    document.querySelectorAll(".mermaid-block.is-source").forEach(function (block) {
      block.classList.remove("is-source");
      const pre = block.querySelector("pre.mermaid");
      const sourcePre = block.querySelector("pre.mermaid-source");
      const toggle = block.querySelector(".mermaid-toggle");
      if (pre) pre.hidden = false;
      if (sourcePre) sourcePre.hidden = true;
      if (toggle) toggle.textContent = t("Show source");
    });
  }

  function renderMermaid() {
    const mermaid = window.__mermaid;
    if (!mermaid) return;
    resetMermaidBlocksToDiagram();
    document.querySelectorAll("pre.mermaid").forEach(function (el) {
      if (el.dataset.source !== undefined) {
        el.removeAttribute("data-processed");
        el.innerHTML = el.dataset.source;
      }
    });
    mermaid.initialize(Object.assign({ startOnLoad: false }, mermaidConfigFor(mermaidThemePref())));
    Promise.resolve(mermaid.run({ querySelector: "pre.mermaid" })).finally(setupMermaidBlocks);
  }

  window.__onMermaidRendered = setupMermaidBlocks;

  document.addEventListener("click", function (event) {
    const toggle = event.target.closest && event.target.closest(".mermaid-toggle");
    if (!toggle) return;
    const block = toggle.closest(".mermaid-block");
    if (!block) return;
    const pre = block.querySelector("pre.mermaid");
    const sourcePre = block.querySelector("pre.mermaid-source");
    const showingSource = block.classList.toggle("is-source");
    if (pre) pre.hidden = showingSource;
    if (sourcePre) sourcePre.hidden = !showingSource;
    toggle.textContent = showingSource ? t("Show diagram") : t("Show source");
  });

  if (themeSelect) {
    themeSelect.addEventListener("change", function () {
      const nextTheme = themeSelect.value;
      localStorage.setItem("markwright-theme", nextTheme);
      applyTheme(nextTheme);
      // Only re-render diagrams when their theme tracks the general theme;
      // an explicit diagram theme stays put regardless of the page theme.
      if (mermaidThemePref() === "auto") renderMermaid();
    });
  }

  if (mermaidThemeSelect) {
    mermaidThemeSelect.value = mermaidThemePref();
    mermaidThemeSelect.addEventListener("change", function () {
      const next = MERMAID_PREFS.has(mermaidThemeSelect.value) ? mermaidThemeSelect.value : "auto";
      localStorage.setItem(mermaidThemeKey, next);
      renderMermaid();
    });
  }

  // Appearance settings popover (theme/font/diagram/width/font-size). Same
  // open/close pattern as the export popover: toggle on click, click-outside
  // and Escape close it; clicks inside (incl. the selects) keep it open.
  const settingsToggle = document.getElementById("settings-toggle");
  const settingsPopover = document.getElementById("settings-popover");
  if (settingsToggle && settingsPopover) {
    const setSettingsOpen = (open) => {
      settingsPopover.hidden = !open;
      settingsToggle.setAttribute("aria-expanded", String(open));
    };
    settingsToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      setSettingsOpen(settingsPopover.hidden);
    });
    settingsPopover.addEventListener("click", (event) => event.stopPropagation());
    document.addEventListener("click", () => {
      if (!settingsPopover.hidden) setSettingsOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !settingsPopover.hidden) setSettingsOpen(false);
    });
  }

  const FONT_FALLBACKS = {
    sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    serif: 'Georgia, "Times New Roman", serif',
  };
  const SYSTEM_FONT = FONT_FALLBACKS.sans;
  const FONTS = [
    { key: "", label: "System default" },
    { key: "Inter", label: "Inter", google: "Inter:wght@400;600;700", fallback: "sans" },
    { key: "Roboto", label: "Roboto", google: "Roboto:wght@400;500;700", fallback: "sans" },
    { key: "Open Sans", label: "Open Sans", google: "Open+Sans:wght@400;600;700", fallback: "sans" },
    { key: "Lato", label: "Lato", google: "Lato:wght@400;700", fallback: "sans" },
    { key: "Source Sans 3", label: "Source Sans 3", google: "Source+Sans+3:wght@400;600;700", fallback: "sans" },
    { key: "IBM Plex Sans", label: "IBM Plex Sans", google: "IBM+Plex+Sans:wght@400;600;700", fallback: "sans" },
    { key: "Merriweather", label: "Merriweather", google: "Merriweather:wght@400;700", fallback: "serif" },
    { key: "Lora", label: "Lora", google: "Lora:wght@400;600;700", fallback: "serif" },
    { key: "Source Serif 4", label: "Source Serif 4", google: "Source+Serif+4:wght@400;600;700", fallback: "serif" },
    { key: "Atkinson Hyperlegible", label: "Atkinson Hyperlegible", google: "Atkinson+Hyperlegible:wght@400;700", fallback: "sans" },
    { key: "Montserrat", label: "Montserrat", google: "Montserrat:wght@400;600;700", fallback: "sans" },
    { key: "Poppins", label: "Poppins", google: "Poppins:wght@400;500;700", fallback: "sans" },
    { key: "Nunito", label: "Nunito", google: "Nunito:wght@400;600;700", fallback: "sans" },
    { key: "Raleway", label: "Raleway", google: "Raleway:wght@400;600;700", fallback: "sans" },
    { key: "Work Sans", label: "Work Sans", google: "Work+Sans:wght@400;600;700", fallback: "sans" },
    { key: "Noto Sans", label: "Noto Sans", google: "Noto+Sans:wght@400;600;700", fallback: "sans" },
    { key: "Nunito Sans", label: "Nunito Sans", google: "Nunito+Sans:wght@400;600;700", fallback: "sans" },
    { key: "Playfair Display", label: "Playfair Display", google: "Playfair+Display:wght@400;600;700", fallback: "serif" },
    { key: "PT Serif", label: "PT Serif", google: "PT+Serif:wght@400;700", fallback: "serif" },
    { key: "Roboto Slab", label: "Roboto Slab", google: "Roboto+Slab:wght@400;600;700", fallback: "serif" },
  ];
  const FONT_BY_KEY = Object.fromEntries(FONTS.map(f => [f.key, f]));

  function loadGoogleFont(font) {
    if (!font.google) return;
    const id = `gf-${font.key.replace(/\s+/g, "-")}`;
    if (document.getElementById(id)) return;
    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = `https://fonts.googleapis.com/css2?family=${font.google}&display=swap`;
    document.head.appendChild(link);
  }

  function applyFont(key) {
    const font = FONT_BY_KEY[key] || FONT_BY_KEY[""];
    if (!font.google) {
      root.style.setProperty("--font-body", SYSTEM_FONT);
      return;
    }
    loadGoogleFont(font);
    root.style.setProperty("--font-body", `"${font.key}", ${FONT_FALLBACKS[font.fallback]}`);
  }

  const WIDTHS = new Set(["narrow", "default", "wide", "full"]);
  function applyWidth(value) {
    const resolved = WIDTHS.has(value) ? value : "default";
    root.dataset.width = resolved;
    if (widthSelect) widthSelect.value = resolved;
  }
  applyWidth(localStorage.getItem("markwright-width") || "default");
  if (widthSelect) {
    widthSelect.addEventListener("change", function () {
      localStorage.setItem("markwright-width", widthSelect.value);
      applyWidth(widthSelect.value);
    });
  }

  const fontSizeDown = document.getElementById("font-size-down");
  const fontSizeUp = document.getElementById("font-size-up");
  const fontSizeReset = document.getElementById("font-size-reset");
  const fontSizeValue = document.getElementById("font-size-value");
  const contentFontSizeKey = "markwright-content-font-size";
  const CONTENT_FONT_SIZE_MIN = 12;
  const CONTENT_FONT_SIZE_MAX = 22;
  const CONTENT_FONT_SIZE_DEFAULT = 16;

  let contentFontSize = Number(localStorage.getItem(contentFontSizeKey));
  if (!(contentFontSize >= CONTENT_FONT_SIZE_MIN && contentFontSize <= CONTENT_FONT_SIZE_MAX)) {
    contentFontSize = CONTENT_FONT_SIZE_DEFAULT;
  }

  function applyContentFontSize() {
    root.style.setProperty("--content-font-size", contentFontSize + "px");
    if (fontSizeValue) fontSizeValue.textContent = String(contentFontSize);
    if (fontSizeReset) {
      fontSizeReset.disabled = contentFontSize === CONTENT_FONT_SIZE_DEFAULT;
      fontSizeReset.title = contentFontSize === CONTENT_FONT_SIZE_DEFAULT
        ? t("Font size (default)")
        : t("Reset font size to %(size)s", { size: CONTENT_FONT_SIZE_DEFAULT });
    }
    if (fontSizeDown) fontSizeDown.disabled = contentFontSize <= CONTENT_FONT_SIZE_MIN;
    if (fontSizeUp) fontSizeUp.disabled = contentFontSize >= CONTENT_FONT_SIZE_MAX;
  }

  function setContentFontSize(value) {
    const next = Math.min(CONTENT_FONT_SIZE_MAX, Math.max(CONTENT_FONT_SIZE_MIN, value));
    if (next === contentFontSize) return;
    contentFontSize = next;
    if (contentFontSize === CONTENT_FONT_SIZE_DEFAULT) {
      localStorage.removeItem(contentFontSizeKey);
    } else {
      localStorage.setItem(contentFontSizeKey, String(contentFontSize));
    }
    applyContentFontSize();
  }

  applyContentFontSize();

  if (fontSizeDown) fontSizeDown.addEventListener("click", function () { setContentFontSize(contentFontSize - 1); });
  if (fontSizeUp) fontSizeUp.addEventListener("click", function () { setContentFontSize(contentFontSize + 1); });
  if (fontSizeReset) fontSizeReset.addEventListener("click", function () { setContentFontSize(CONTENT_FONT_SIZE_DEFAULT); });

  if (fontSelect) {
    FONTS.forEach(f => {
      const opt = document.createElement("option");
      opt.value = f.key;
      opt.textContent = f.key === "" ? t("System default") : f.label;
      fontSelect.appendChild(opt);
    });
    const savedFont = localStorage.getItem("markwright-font") || "";
    fontSelect.value = FONT_BY_KEY[savedFont] ? savedFont : "";
    applyFont(fontSelect.value);
    fontSelect.addEventListener("change", function () {
      localStorage.setItem("markwright-font", fontSelect.value);
      applyFont(fontSelect.value);
    });
  }

  // Language switcher: a `lang` cookie (read server-side by select_locale)
  // drives the active locale. Setting it and reloading re-renders the page —
  // and its injected I18N catalog — in the chosen language.
  const langSelect = document.getElementById("lang-select");
  if (langSelect) {
    const current = (document.cookie.match(/(?:^|;\s*)lang=([^;]+)/) || [])[1] || "en";
    langSelect.value = current;
    langSelect.addEventListener("change", function () {
      // Persist for a year; path=/ so it applies to every route.
      document.cookie = "lang=" + langSelect.value + ";path=/;max-age=31536000;samesite=lax";
      window.location.reload();
    });
  }

  function makeCopyButton() {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-code";
    button.textContent = t("Copy");
    button.setAttribute("aria-label", t("Copy code to clipboard"));
    return button;
  }

  function addCopyButtons(scope) {
    const containers = (scope || document).querySelectorAll(".markdown-body pre:not(.mermaid):not(.mermaid-source)");
    containers.forEach(function (pre) {
      if (pre.querySelector(":scope > .copy-code")) return;
      pre.appendChild(makeCopyButton());
    });
  }

  document.addEventListener("click", async function (event) {
    const button = event.target.closest && event.target.closest(".copy-code");
    if (!button) return;
    let text;
    const block = button.closest(".mermaid-block");
    if (block) {
      const srcCode = block.querySelector(".mermaid-source code");
      text = srcCode ? srcCode.textContent : "";
    } else {
      const pre = button.closest("pre");
      if (!pre) return;
      const code = pre.querySelector("code");
      text = code
        ? code.textContent
        : Array.from(pre.childNodes)
            .filter(n => !(n.nodeType === 1 && n.classList && n.classList.contains("copy-code")))
            .map(n => n.textContent || "")
            .join("");
    }
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = t("Copied!");
      button.classList.add("is-copied");
    } catch (err) {
      button.textContent = t("Failed");
    }
    setTimeout(function () {
      button.textContent = t("Copy");
      button.classList.remove("is-copied");
    }, 1200);
  });

  addCopyButtons();

  // --- Reading aids (rendered view) ---------------------------------------
  (function setupReadingAids() {
    const mdBody = document.querySelector(".markdown-body");
    if (!mdBody || !selectedPath) return;

    // Word count + reading time in the header (computed before anchors are added
    // so the ¶ glyphs don't inflate the count).
    const heading = document.querySelector(".document-heading");
    const text = mdBody.innerText || mdBody.textContent || "";
    const words = (text.match(/\S+/g) || []).length;
    if (heading && words > 0) {
      const mins = Math.max(1, Math.round(words / 200));
      const meta = document.createElement("p");
      meta.className = "doc-meta";
      meta.textContent = t("%(words)s words · ~%(min)s min read", {
        words: words.toLocaleString(), min: mins,
      });
      heading.appendChild(meta);
    }

    // Hover anchor on each heading → copy a link to that section.
    mdBody.querySelectorAll("h1[id],h2[id],h3[id],h4[id],h5[id],h6[id]").forEach(function (h) {
      const a = document.createElement("a");
      a.className = "heading-anchor";
      a.href = "#" + h.id;
      a.textContent = "¶";
      a.title = t("Copy link to this section");
      a.setAttribute("aria-label", t("Copy link to this section"));
      a.addEventListener("click", function (event) {
        event.preventDefault();
        const url = location.origin + location.pathname + location.search + "#" + h.id;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(function () {
            a.classList.add("copied");
            setTimeout(function () { a.classList.remove("copied"); }, 1200);
          }).catch(function () {});
        }
        history.replaceState(null, "", "#" + h.id);
      });
      h.appendChild(a);
    });
  })();

  // --- Back-to-top button -------------------------------------------------
  (function setupBackToTop() {
    if (!contentPanel) return;
    const isMobile = () => window.matchMedia("(max-width: 820px)").matches;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "back-to-top";
    btn.textContent = "↑";
    btn.title = t("Back to top");
    btn.setAttribute("aria-label", t("Back to top"));
    btn.hidden = true;
    document.body.appendChild(btn);
    function onScroll() {
      const y = isMobile() ? window.scrollY : contentPanel.scrollTop;
      btn.hidden = y < 400;
    }
    contentPanel.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    btn.addEventListener("click", function () {
      if (isMobile()) window.scrollTo({ top: 0, behavior: "smooth" });
      else contentPanel.scrollTo({ top: 0, behavior: "smooth" });
    });
    onScroll();
  })();

  // --- Focus reading mode -------------------------------------------------
  (function setupFocusMode() {
    const focusToggle = document.getElementById("focus-read-toggle");
    if (!appShell || !contentPanel || !focusToggle) return;  // needs a selected doc
    const mdBody = document.querySelector(".markdown-body");

    const progress = document.createElement("div");
    progress.className = "reading-progress";
    progress.hidden = true;
    appShell.appendChild(progress);

    const exitBtn = document.createElement("button");
    exitBtn.type = "button";
    exitBtn.className = "focus-exit";
    exitBtn.textContent = "✕";
    exitBtn.title = t("Exit focus reading (Esc)");
    exitBtn.setAttribute("aria-label", t("Exit focus reading"));
    exitBtn.hidden = true;
    appShell.appendChild(exitBtn);

    const timeLeft = document.createElement("div");
    timeLeft.className = "focus-timeleft";
    timeLeft.hidden = true;
    appShell.appendChild(timeLeft);

    // Content-width cycle: reuses the appearance-settings width mechanism
    // (data-width + the markwright-width key), so changing it here is the same
    // global setting the width selector drives.
    const WIDTH_ORDER = ["narrow", "default", "wide", "full"];
    const WIDTH_LABELS = {
      narrow: t("Narrow"), default: t("Default"), wide: t("Wide"), full: t("Full"),
    };
    const widthBtn = document.createElement("button");
    widthBtn.type = "button";
    widthBtn.className = "focus-width";
    widthBtn.title = t("Change content width");
    widthBtn.setAttribute("aria-label", t("Change content width"));
    widthBtn.hidden = true;
    appShell.appendChild(widthBtn);

    function syncWidthBtn() {
      const cur = root.dataset.width || "default";
      widthBtn.textContent = WIDTH_LABELS[cur] || WIDTH_LABELS.default;
    }
    widthBtn.addEventListener("click", function () {
      const cur = root.dataset.width || "default";
      const next = WIDTH_ORDER[(WIDTH_ORDER.indexOf(cur) + 1) % WIDTH_ORDER.length];
      localStorage.setItem("markwright-width", next);
      applyWidth(next);
      syncWidthBtn();
      showControls();
    });

    let focusActive = false;
    let idleTimer = null;
    let totalMinutes = 0;
    const isMobile = () => window.matchMedia("(max-width: 820px)").matches;

    function scrollMetrics() {
      if (isMobile()) return { top: window.scrollY, max: document.documentElement.scrollHeight - window.innerHeight, vh: window.innerHeight };
      return { top: contentPanel.scrollTop, max: contentPanel.scrollHeight - contentPanel.clientHeight, vh: contentPanel.clientHeight };
    }

    function updateProgress() {
      const m = scrollMetrics();
      const p = m.max > 0 ? Math.min(1, m.top / m.max) : 0;
      progress.style.width = (p * 100) + "%";
      if (totalMinutes > 0) {
        timeLeft.textContent = p >= 0.995
          ? t("Almost done")
          : t("~%(min)s min left", { min: Math.max(1, Math.ceil(totalMinutes * (1 - p))) });
      }
    }

    function onFocusScroll() { if (focusActive) updateProgress(); }

    // Auto-hide: the exit control + time pill fade (and the cursor hides) on idle.
    function showControls() {
      appShell.classList.remove("is-focus-idle");
      clearTimeout(idleTimer);
      idleTimer = setTimeout(function () { if (focusActive) appShell.classList.add("is-focus-idle"); }, 2500);
    }
    function onFocusMouseMove() { if (focusActive) showControls(); }

    function focusScrollBy(delta, smooth) {
      const opts = { top: delta, behavior: smooth ? "smooth" : "auto" };
      if (isMobile()) window.scrollBy(opts); else contentPanel.scrollBy(opts);
    }

    function enterFocus() {
      if (focusActive) return;
      focusActive = true;
      appShell.classList.add("is-focus");
      focusToggle.setAttribute("aria-pressed", "true");
      if (mdBody) {
        totalMinutes = ((mdBody.innerText || "").match(/\S+/g) || []).length / 200;
      }
      progress.hidden = false;
      exitBtn.hidden = false;
      timeLeft.hidden = totalMinutes <= 0;
      widthBtn.hidden = false;
      syncWidthBtn();
      updateProgress();
      showControls();
      document.addEventListener("mousemove", onFocusMouseMove);
      const el = document.documentElement;
      if (el.requestFullscreen) el.requestFullscreen().catch(function () {});  // best-effort
    }

    function exitFocus() {
      if (!focusActive) return;
      focusActive = false;
      appShell.classList.remove("is-focus", "is-focus-idle");
      focusToggle.setAttribute("aria-pressed", "false");
      progress.hidden = true;
      exitBtn.hidden = true;
      timeLeft.hidden = true;
      widthBtn.hidden = true;
      clearTimeout(idleTimer);
      document.removeEventListener("mousemove", onFocusMouseMove);
      if (document.fullscreenElement) document.exitFullscreen().catch(function () {});
    }

    focusToggle.addEventListener("click", function () { focusActive ? exitFocus() : enterFocus(); });
    exitBtn.addEventListener("click", exitFocus);
    contentPanel.addEventListener("scroll", onFocusScroll, { passive: true });
    window.addEventListener("scroll", onFocusScroll, { passive: true });
    // Browser-driven fullscreen exit (Esc in true fullscreen) → leave focus too.
    document.addEventListener("fullscreenchange", function () {
      if (!document.fullscreenElement && focusActive) exitFocus();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && focusActive && diagramOverlay.hidden) { exitFocus(); return; }
      const ae = document.activeElement;
      const interactive = ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.isContentEditable ||
                                 ae.tagName === "BUTTON" || ae.tagName === "A" || (ae.closest && ae.closest(".CodeMirror")));
      // Keyboard paging while reading (focus mode only).
      if (focusActive && !interactive) {
        const page = scrollMetrics().vh * 0.9;
        if (event.key === " " || event.key === "PageDown") { event.preventDefault(); focusScrollBy(event.shiftKey ? -page : page, true); return; }
        if (event.key === "PageUp") { event.preventDefault(); focusScrollBy(-page, true); return; }
        if (event.key === "j") { event.preventDefault(); focusScrollBy(120, false); return; }
        if (event.key === "k") { event.preventDefault(); focusScrollBy(-120, false); return; }
      }
      if ((event.key === "f" || event.key === "F") && !event.ctrlKey && !event.metaKey && !event.altKey) {
        if (interactive || editActive) return;  // don't hijack 'f' while typing/editing
        event.preventDefault();
        focusActive ? exitFocus() : enterFocus();
      }
    });
  })();

  // --- Bookmarks ----------------------------------------------------------
  // Two kinds, both stored in localStorage and scoped per source root (so the
  // same relative path in two different sources can't collide):
  //   * file bookmarks  — favourite documents, pinned at the top of the sidebar
  //     and toggled by a star on each file row.
  //   * position bookmarks — a saved spot (heading) inside one document, listed
  //     and jumped-to from the header bookmark popover.
  (function setupBookmarks() {
    const ROOT = window.MARKWRIGHT_ROOT || "";
    const fileKey = `markwright-file-bookmarks:${ROOT}`;
    const posKey = `markwright-pos-bookmarks:${ROOT}`;
    const isMobile = () => window.matchMedia("(max-width: 820px)").matches;

    function readStore(key) {
      try {
        const v = JSON.parse(localStorage.getItem(key) || "[]");
        return Array.isArray(v) ? v : [];
      } catch (_) {
        return [];
      }
    }
    function writeStore(key, val) { localStorage.setItem(key, JSON.stringify(val)); }

    let fileBookmarks = readStore(fileKey);   // [{path, name}]
    let posBookmarks = readStore(posKey);     // [{file, id, label, y}]

    const isFileBookmarked = (path) => fileBookmarks.some((b) => b.path === path);
    function fileHref(path) {
      return "/?file=" + path.split("/").map(encodeURIComponent).join("/");
    }

    // --- Sidebar: "Bookmarked" section + per-row stars ---------------------
    const bookmarkTree = document.getElementById("bookmark-tree");
    const bookmarkTreeList = document.getElementById("bookmark-tree-list");

    function renderBookmarkTree() {
      if (!bookmarkTree || !bookmarkTreeList) return;
      bookmarkTreeList.replaceChildren();
      if (!fileBookmarks.length) {
        bookmarkTree.hidden = true;
        return;
      }
      bookmarkTree.hidden = false;
      fileBookmarks.forEach(function (b) {
        const li = document.createElement("li");
        li.className = "bookmark-tree-item";
        const a = document.createElement("a");
        a.className = "file-link";
        if (b.path === selectedPath) a.classList.add("is-active");
        a.href = fileHref(b.path);
        a.title = b.path;
        const name = document.createElement("span");
        name.className = "file-name";
        name.textContent = b.name || b.path;
        a.appendChild(name);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "bookmark-tree-remove";
        remove.title = t("Remove bookmark");
        remove.setAttribute("aria-label", t("Remove bookmark"));
        remove.textContent = "★";
        remove.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          toggleFileBookmark(b.path, b.name);
        });
        li.appendChild(a);
        li.appendChild(remove);
        bookmarkTreeList.appendChild(li);
      });
    }

    function syncRowStars() {
      document.querySelectorAll(".tree-file .tree-bookmark").forEach(function (star) {
        const on = isFileBookmarked(star.dataset.path);
        star.classList.toggle("is-on", on);
        star.textContent = on ? "★" : "☆";
        star.title = on ? t("Remove bookmark") : t("Bookmark this file");
        star.setAttribute("aria-pressed", String(on));
      });
    }

    function toggleFileBookmark(path, name) {
      if (!path) return;
      if (isFileBookmarked(path)) {
        fileBookmarks = fileBookmarks.filter((b) => b.path !== path);
      } else {
        fileBookmarks = fileBookmarks.concat([{ path: path, name: name || path }]);
      }
      writeStore(fileKey, fileBookmarks);
      renderBookmarkTree();
      syncRowStars();
      syncHeaderFileButton();
    }

    // Inject a star toggle into every file row. The real (case-preserving) path
    // and display name come from the link's title / .file-name, since the li's
    // data-file-path is lower-cased for search.
    document.querySelectorAll(".tree-file").forEach(function (li) {
      const link = li.querySelector(".file-link");
      if (!link) return;
      const path = link.getAttribute("title") || "";
      const nameEl = link.querySelector(".file-name");
      const name = nameEl ? nameEl.textContent : path;
      const star = document.createElement("button");
      star.type = "button";
      star.className = "tree-bookmark";
      star.dataset.path = path;
      star.dataset.name = name;
      star.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        toggleFileBookmark(path, name);
      });
      li.appendChild(star);
    });

    // --- Header popover: file toggle + position bookmarks -----------------
    const bookmarkToggle = document.getElementById("bookmark-toggle");
    const bookmarkPopover = document.getElementById("bookmark-popover");
    const bookmarkFileBtn = document.getElementById("bookmark-file");
    const bookmarkAdd = document.getElementById("bookmark-add");
    const bookmarkList = document.getElementById("bookmark-list");
    const bookmarkEmpty = document.getElementById("bookmark-empty");
    const currentFile = bookmarkToggle ? bookmarkToggle.dataset.file : "";
    const currentName = bookmarkToggle ? bookmarkToggle.dataset.name : "";
    let bookmarkFab = null;  // floating opener (created on scroll); see below

    function syncHeaderFileButton() {
      if (!bookmarkFileBtn) return;
      const on = isFileBookmarked(currentFile);
      bookmarkFileBtn.textContent = on ? t("★ Remove file bookmark") : t("☆ Bookmark this file");
      bookmarkFileBtn.classList.toggle("is-on", on);
      if (bookmarkToggle) bookmarkToggle.classList.toggle("is-on", on || posForCurrentFile().length > 0);
    }

    const posForCurrentFile = () => posBookmarks.filter((b) => b.file === currentFile);

    function scrollToPos(b) {
      if (b.id) {
        const el = document.getElementById(b.id);
        if (el) {
          el.scrollIntoView({ block: "start", behavior: "smooth" });
          return;
        }
      }
      const y = Number(b.y || 0);
      if (isMobile()) window.scrollTo({ top: y, behavior: "smooth" });
      else if (contentPanel) contentPanel.scrollTo({ top: y, behavior: "smooth" });
    }

    // Capture the heading currently nearest the top of the viewport (matching
    // the TOC active-heading logic) so a saved spot maps to a stable anchor;
    // falls back to a raw scroll offset when the page has no headings above.
    function captureCurrentSpot() {
      const headings = Array.from(document.querySelectorAll(
        ".markdown-body h1[id], .markdown-body h2[id], .markdown-body h3[id], " +
        ".markdown-body h4[id], .markdown-body h5[id], .markdown-body h6[id]"));
      const y = isMobile() ? window.scrollY : (contentPanel ? contentPanel.scrollTop : 0);
      const panelTop = contentPanel ? contentPanel.getBoundingClientRect().top : 0;
      let active = null;
      for (const h of headings) {
        if (h.getBoundingClientRect().top - panelTop <= 80) active = h;
        else break;
      }
      if (active) {
        return { file: currentFile, id: active.id, label: (active.textContent || "").replace(/¶$/, "").trim(), y: y };
      }
      const pct = Math.round(y); // raw offset; label gives the user a hint
      return { file: currentFile, id: "", label: t("Position at %(px)spx", { px: pct }), y: y };
    }

    function renderPosList() {
      if (!bookmarkList || !bookmarkEmpty) return;
      const items = posForCurrentFile();
      bookmarkList.replaceChildren();
      bookmarkEmpty.hidden = items.length > 0;
      items.forEach(function (b) {
        const li = document.createElement("li");
        li.className = "bookmark-list-item";
        const jump = document.createElement("button");
        jump.type = "button";
        jump.className = "bookmark-jump";
        jump.textContent = b.label || t("(untitled)");
        jump.title = b.label || "";
        jump.addEventListener("click", function () { scrollToPos(b); setOpen(false); });
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "bookmark-list-remove";
        remove.title = t("Remove");
        remove.setAttribute("aria-label", t("Remove"));
        remove.textContent = "×";
        remove.addEventListener("click", function () {
          posBookmarks = posBookmarks.filter((x) => x !== b);
          writeStore(posKey, posBookmarks);
          renderPosList();
          syncHeaderFileButton();
        });
        li.appendChild(jump);
        li.appendChild(remove);
        bookmarkList.appendChild(li);
      });
    }

    // Shared add-path for the popover button and the floating button. Dedupes
    // on heading id so tapping the same spot twice doesn't pile up entries.
    function addCurrentSpot() {
      const spot = captureCurrentSpot();
      if (spot.id && posBookmarks.some((b) => b.file === spot.file && b.id === spot.id)) {
        return false;
      }
      posBookmarks = posBookmarks.concat([spot]);
      writeStore(posKey, posBookmarks);
      renderPosList();
      syncHeaderFileButton();
      return true;
    }

    if (bookmarkFileBtn) {
      bookmarkFileBtn.addEventListener("click", function () {
        toggleFileBookmark(currentFile, currentName);
      });
    }
    if (bookmarkAdd) {
      // Brief "saved" feedback so adding from the floating panel feels responsive.
      let addFlashTimer = null;
      bookmarkAdd.addEventListener("click", function () {
        addCurrentSpot();
        bookmarkAdd.classList.add("is-saved");
        bookmarkAdd.textContent = t("✓ Bookmarked");
        clearTimeout(addFlashTimer);
        addFlashTimer = setTimeout(function () {
          bookmarkAdd.classList.remove("is-saved");
          bookmarkAdd.textContent = t("+ Bookmark this spot");
        }, 1200);
      });
    }

    // Popover open/close — same pattern as the settings/export popovers. The
    // popover can open in two places: anchored under the header 🔖 button, or
    // (when `floating`) pinned bottom-right via .is-floating so it stays usable
    // after the header scrolls away. Same element either way, so the add button
    // and the jump list are always together.
    function setOpen(open, floating) {
      if (!bookmarkPopover) return;
      bookmarkPopover.hidden = !open;
      bookmarkPopover.classList.toggle("is-floating", Boolean(open && floating));
      if (bookmarkToggle) bookmarkToggle.setAttribute("aria-expanded", String(open && !floating));
      if (bookmarkFab) bookmarkFab.setAttribute("aria-expanded", String(open && floating));
      if (open) { syncHeaderFileButton(); renderPosList(); }
    }
    if (bookmarkToggle && bookmarkPopover) {
      bookmarkToggle.addEventListener("click", function (event) {
        event.stopPropagation();
        setOpen(bookmarkPopover.hidden, false);
      });
      bookmarkPopover.addEventListener("click", (event) => event.stopPropagation());
      document.addEventListener("click", function () {
        if (!bookmarkPopover.hidden) setOpen(false);
      });
      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !bookmarkPopover.hidden) setOpen(false);
      });
    }

    // Floating opener — the header (and its 🔖 button) scrolls out of view, so
    // this FAB appears once scrolled and opens the same popover in floating mode,
    // keeping both "bookmark this spot" and the jump list reachable from anywhere.
    if (currentFile && contentPanel && bookmarkPopover) {
      bookmarkFab = document.createElement("button");
      bookmarkFab.type = "button";
      bookmarkFab.className = "bookmark-fab";
      bookmarkFab.textContent = "🔖";
      bookmarkFab.title = t("Tap to bookmark this spot · hold to open the list");
      bookmarkFab.setAttribute("aria-label", t("Tap to bookmark this spot · hold to open the list"));
      bookmarkFab.setAttribute("aria-expanded", "false");
      bookmarkFab.hidden = true;
      document.body.appendChild(bookmarkFab);

      function onFabScroll() {
        const y = isMobile() ? window.scrollY : contentPanel.scrollTop;
        // Keep the button while its floating panel is open even if scrolled back up.
        const open = bookmarkPopover.classList.contains("is-floating") && !bookmarkPopover.hidden;
        bookmarkFab.hidden = y < 400 && !open;
      }
      contentPanel.addEventListener("scroll", onFabScroll, { passive: true });
      window.addEventListener("scroll", onFabScroll, { passive: true });

      // Gesture: a tap quick-adds the current spot (with a checkmark flash); a
      // long-press opens the floating panel to jump to / manage saved spots.
      const LONG_PRESS_MS = 450;
      let pressTimer = null;
      let longPressed = false;
      let flashTimer = null;

      function flashSaved() {
        addCurrentSpot();
        bookmarkFab.classList.add("is-saved");
        bookmarkFab.textContent = "✓";
        clearTimeout(flashTimer);
        flashTimer = setTimeout(function () {
          bookmarkFab.classList.remove("is-saved");
          bookmarkFab.textContent = "🔖";
        }, 1200);
      }

      function openFloating() {
        longPressed = true;
        const wasFloating = bookmarkPopover.classList.contains("is-floating");
        setOpen(bookmarkPopover.hidden || !wasFloating, true);
      }

      bookmarkFab.addEventListener("pointerdown", function (event) {
        if (event.button && event.button !== 0) return;  // primary / touch only
        longPressed = false;
        clearTimeout(pressTimer);
        pressTimer = setTimeout(openFloating, LONG_PRESS_MS);
      });
      const cancelPress = function () { clearTimeout(pressTimer); };
      bookmarkFab.addEventListener("pointerup", cancelPress);
      bookmarkFab.addEventListener("pointerleave", cancelPress);
      bookmarkFab.addEventListener("pointercancel", cancelPress);
      // A long-press on touch would otherwise pop the context menu.
      bookmarkFab.addEventListener("contextmenu", function (event) { event.preventDefault(); });

      bookmarkFab.addEventListener("click", function (event) {
        event.stopPropagation();
        if (longPressed) { longPressed = false; return; }  // handled by openFloating
        flashSaved();
      });
      onFabScroll();
    }

    renderBookmarkTree();
    syncRowStars();
    syncHeaderFileButton();
  })();

  // collapsedIntent is the user's persisted intent — only mutated by manual
  // toggle / collapse-all clicks. Search may force-expand directories in the
  // DOM, but never touches this set; clearing the search restores from it.
  const collapsedDirsKey = "markwright-tree-collapsed";
  const collapsedIntent = (function () {
    try {
      const parsed = JSON.parse(localStorage.getItem(collapsedDirsKey) || "[]");
      return new Set(Array.isArray(parsed) ? parsed : []);
    } catch (_) {
      return new Set();
    }
  })();

  function persistIntent() {
    localStorage.setItem(collapsedDirsKey, JSON.stringify(Array.from(collapsedIntent)));
  }

  function applyCollapsedState(directory, collapsed) {
    directory.classList.toggle("is-collapsed", collapsed);
    const toggle = directory.querySelector(":scope > .tree-toggle");
    if (toggle) toggle.setAttribute("aria-expanded", String(!collapsed));
  }

  (function applyInitialIntent() {
    if (!collapsedIntent.size) return;
    document.querySelectorAll(".tree-directory").forEach(function (dir) {
      if (collapsedIntent.has(dir.dataset.dirPath)) applyCollapsedState(dir, true);
    });
  })();

  document.querySelectorAll(".tree-toggle").forEach(function (button) {
    button.addEventListener("click", function () {
      const directory = button.closest(".tree-directory");
      const collapsed = directory.classList.toggle("is-collapsed");
      button.setAttribute("aria-expanded", String(!collapsed));
      const path = directory.dataset.dirPath;
      if (path) {
        if (collapsed) collapsedIntent.add(path);
        else collapsedIntent.delete(path);
        persistIntent();
      }
      syncCollapseAllToggle();
    });
  });

  const collapseAllToggle = document.getElementById("tree-collapse-all");

  function setAllDirectoriesCollapsed(collapse) {
    document.querySelectorAll(".tree-directory").forEach(function (directory) {
      directory.classList.toggle("is-collapsed", collapse);
      const toggle = directory.querySelector(":scope > .tree-toggle");
      if (toggle) toggle.setAttribute("aria-expanded", String(!collapse));
    });
  }

  function syncCollapseAllToggle() {
    if (!collapseAllToggle) return;
    const directories = document.querySelectorAll(".tree-directory");
    if (!directories.length) {
      collapseAllToggle.hidden = true;
      return;
    }
    collapseAllToggle.hidden = false;
    const allCollapsed = Array.from(directories).every(function (dir) {
      return dir.classList.contains("is-collapsed");
    });
    collapseAllToggle.setAttribute("aria-pressed", String(allCollapsed));
    const label = collapseAllToggle.querySelector(".tree-collapse-all-label");
    if (label) label.textContent = allCollapsed ? t("Expand all") : t("Collapse all");
    const title = allCollapsed ? t("Expand all folders") : t("Collapse all folders");
    collapseAllToggle.title = title;
    collapseAllToggle.setAttribute("aria-label", title);
  }

  if (collapseAllToggle) {
    collapseAllToggle.addEventListener("click", function () {
      const shouldCollapse = collapseAllToggle.getAttribute("aria-pressed") !== "true";
      setAllDirectoriesCollapsed(shouldCollapse);
      collapsedIntent.clear();
      if (shouldCollapse) {
        document.querySelectorAll(".tree-directory").forEach(function (dir) {
          if (dir.dataset.dirPath) collapsedIntent.add(dir.dataset.dirPath);
        });
      }
      persistIntent();
      syncCollapseAllToggle();
    });
    syncCollapseAllToggle();
  }

  const treeSortSelect = document.getElementById("tree-sort");
  const treeSortKey = "markwright-tree-sort";
  const nameCollator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
  const SORT_COMPARATORS = {
    "name-asc": function (a, b) { return nameCollator.compare(a.dataset.name || "", b.dataset.name || ""); },
    "name-desc": function (a, b) { return nameCollator.compare(b.dataset.name || "", a.dataset.name || ""); },
    "date-desc": function (a, b) { return Number(b.dataset.mtime || 0) - Number(a.dataset.mtime || 0); },
    "date-asc": function (a, b) { return Number(a.dataset.mtime || 0) - Number(b.dataset.mtime || 0); },
  };

  function sortTree(mode) {
    const cmp = SORT_COMPARATORS[mode] || SORT_COMPARATORS["name-asc"];
    document.querySelectorAll(".file-tree ul").forEach(function (ul) {
      const items = Array.from(ul.children);
      items.sort(function (a, b) {
        const aDir = a.classList.contains("tree-directory");
        const bDir = b.classList.contains("tree-directory");
        if (aDir !== bDir) return aDir ? -1 : 1;
        return cmp(a, b);
      });
      items.forEach(function (item) { ul.appendChild(item); });
    });
  }

  if (treeSortSelect) {
    const savedSort = localStorage.getItem(treeSortKey) || "name-asc";
    treeSortSelect.value = SORT_COMPARATORS[savedSort] ? savedSort : "name-asc";
    sortTree(treeSortSelect.value);
    treeSortSelect.addEventListener("change", function () {
      localStorage.setItem(treeSortKey, treeSortSelect.value);
      sortTree(treeSortSelect.value);
    });
  }

  searchInput.addEventListener("input", function () {
    const query = searchInput.value.trim().toLowerCase();

    document.querySelectorAll(".tree-file").forEach(function (item) {
      const matches = item.dataset.filePath.includes(query);
      item.hidden = Boolean(query && !matches);
    });

    document.querySelectorAll(".tree-directory").forEach(function (directory) {
      const hasVisibleFile = Array.from(directory.querySelectorAll(".tree-file")).some(function (file) {
        return !file.hidden;
      });
      directory.hidden = Boolean(query && !hasVisibleFile);
      if (query && hasVisibleFile) {
        applyCollapsedState(directory, false);
      } else if (!query) {
        applyCollapsedState(directory, collapsedIntent.has(directory.dataset.dirPath));
      }
    });
    syncCollapseAllToggle();
  });

  const diagramOverlay = document.getElementById("diagram-overlay");
  const diagramStage = document.getElementById("diagram-overlay-stage");
  const zoomValueLabel = document.getElementById("diagram-zoom-value");
  const opacityValueLabel = document.getElementById("diagram-opacity-value");
  const overlayOpacityKey = "markwright-overlay-opacity";
  const OPACITY_STEP = 0.1;
  const OPACITY_MIN = 0.1;
  const OPACITY_MAX = 1.0;
  let overlayOpacity = parseFloat(localStorage.getItem(overlayOpacityKey));
  if (!(overlayOpacity >= OPACITY_MIN && overlayOpacity <= OPACITY_MAX)) {
    overlayOpacity = 1;
  }

  function applyOverlayOpacity() {
    diagramOverlay.style.setProperty("--overlay-opacity", String(overlayOpacity));
    opacityValueLabel.textContent = Math.round(overlayOpacity * 100) + "%";
  }

  function adjustOverlayOpacity(delta) {
    const next = Math.min(OPACITY_MAX, Math.max(OPACITY_MIN, overlayOpacity + delta));
    overlayOpacity = Math.round(next * 100) / 100;
    localStorage.setItem(overlayOpacityKey, String(overlayOpacity));
    applyOverlayOpacity();
  }

  applyOverlayOpacity();

  document.getElementById("diagram-opacity-down").addEventListener("click", function () {
    adjustOverlayOpacity(-OPACITY_STEP);
  });
  document.getElementById("diagram-opacity-up").addEventListener("click", function () {
    adjustOverlayOpacity(OPACITY_STEP);
  });

  let diagramScale = 1;
  let diagramTx = 0;
  let diagramTy = 0;
  let diagramDragging = false;
  let diagramPointerStartX = 0;
  let diagramPointerStartY = 0;
  let diagramOriginX = 0;
  let diagramOriginY = 0;
  let diagramDidDrag = false;

  const zoomPresetButtons = document.querySelectorAll(".diagram-zoom-preset");

  function applyDiagramTransform() {
    const svg = diagramStage.querySelector("svg");
    if (svg) {
      svg.style.transform = `translate(${diagramTx}px, ${diagramTy}px) scale(${diagramScale})`;
    }
    zoomValueLabel.textContent = Math.round(diagramScale * 100) + "%";
    // Highlight the preset (incl. 1×) that matches the current zoom, if any.
    zoomPresetButtons.forEach(function (btn) {
      const z = parseFloat(btn.dataset.zoom);
      btn.setAttribute("aria-pressed", String(Math.abs(diagramScale - z) < 0.001));
    });
  }

  function zoomDiagram(factor) {
    diagramScale = Math.min(8, Math.max(0.2, diagramScale * factor));
    applyDiagramTransform();
  }

  // Absolute zoom preset: set the scale and recenter (like 1×, but to any level).
  function setDiagramZoom(value) {
    diagramScale = Math.min(8, Math.max(0.2, value));
    diagramTx = 0;
    diagramTy = 0;
    applyDiagramTransform();
  }

  function resetDiagram() {
    diagramScale = 1;
    diagramTx = 0;
    diagramTy = 0;
    applyDiagramTransform();
  }

  function openDiagramOverlay(sourceSvg) {
    diagramStage.replaceChildren(sourceSvg.cloneNode(true));
    resetDiagram();
    diagramOverlay.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeDiagramOverlay() {
    diagramOverlay.hidden = true;
    diagramStage.replaceChildren();
    document.body.style.overflow = "";
  }

  document.addEventListener("click", function (event) {
    if (!diagramOverlay.hidden) return;
    const pre = event.target.closest && event.target.closest("pre.mermaid");
    if (!pre) return;
    const svg = pre.querySelector("svg");
    if (svg) openDiagramOverlay(svg);
  });

  document.getElementById("diagram-zoom-in").addEventListener("click", function () {
    zoomDiagram(1.25);
  });
  document.getElementById("diagram-zoom-out").addEventListener("click", function () {
    zoomDiagram(1 / 1.25);
  });
  document.getElementById("diagram-zoom-reset").addEventListener("click", resetDiagram);
  // 0.5× / 1.5× / 2× / 2.5× / 3× presets (the 1× button keeps its own reset handler).
  zoomPresetButtons.forEach(function (btn) {
    if (btn.id === "diagram-zoom-reset") return;
    btn.addEventListener("click", function () { setDiagramZoom(parseFloat(btn.dataset.zoom)); });
  });
  document.getElementById("diagram-close").addEventListener("click", closeDiagramOverlay);

  document.addEventListener("keydown", function (event) {
    if (diagramOverlay.hidden) return;
    if (event.key === "Escape") closeDiagramOverlay();
    else if (event.key === "+" || event.key === "=") zoomDiagram(1.25);
    else if (event.key === "-" || event.key === "_") zoomDiagram(1 / 1.25);
    else if (event.key === "0") resetDiagram();
  });

  diagramStage.addEventListener("wheel", function (event) {
    event.preventDefault();
    zoomDiagram(event.deltaY < 0 ? 1.1 : 1 / 1.1);
  }, { passive: false });

  diagramStage.addEventListener("pointerdown", function (event) {
    diagramDragging = true;
    diagramDidDrag = false;
    diagramPointerStartX = event.clientX;
    diagramPointerStartY = event.clientY;
    diagramOriginX = diagramTx;
    diagramOriginY = diagramTy;
    diagramStage.classList.add("is-panning");
    diagramStage.setPointerCapture(event.pointerId);
  });
  diagramStage.addEventListener("pointermove", function (event) {
    if (!diagramDragging) return;
    const dx = event.clientX - diagramPointerStartX;
    const dy = event.clientY - diagramPointerStartY;
    if (!diagramDidDrag && Math.hypot(dx, dy) > 4) diagramDidDrag = true;
    diagramTx = diagramOriginX + dx;
    diagramTy = diagramOriginY + dy;
    applyDiagramTransform();
  });
  function endDiagramDrag(event) {
    if (!diagramDragging) return;
    diagramDragging = false;
    diagramStage.classList.remove("is-panning");
    if (!diagramDidDrag && event.target === diagramStage) {
      closeDiagramOverlay();
    }
  }
  diagramStage.addEventListener("pointerup", endDiagramDrag);
  diagramStage.addEventListener("pointercancel", endDiagramDrag);

  const sourceInput = document.getElementById("source-input");
  const sourceOpen = document.getElementById("source-open");
  const sourceStatus = document.getElementById("source-status");

  function setSourceStatus(message, isError) {
    if (!sourceStatus) return;
    sourceStatus.textContent = message;
    sourceStatus.classList.toggle("is-error", Boolean(isError));
  }

  async function switchSource(value) {
    const trimmed = (value || "").trim();
    if (!trimmed) return;
    if (sourceOpen) sourceOpen.disabled = true;
    setSourceStatus(t("Loading…"), false);
    try {
      const res = await fetch("/api/source", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: trimmed }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setSourceStatus(data.error || t("Failed (%(status)s)", { status: res.status }), true);
        if (sourceOpen) sourceOpen.disabled = false;
        return;
      }
      setSourceStatus(t("Loaded — reloading…"), false);
      window.location.href = "/";
    } catch (err) {
      setSourceStatus(String(err && err.message ? err.message : err), true);
      if (sourceOpen) sourceOpen.disabled = false;
    }
  }

  if (sourceOpen) {
    sourceOpen.addEventListener("click", function () {
      switchSource(sourceInput && sourceInput.value);
    });
  }
  if (sourceInput) {
    sourceInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        switchSource(sourceInput.value);
      }
    });
  }
  document.querySelectorAll(".source-recent").forEach(function (button) {
    button.addEventListener("click", function () {
      switchSource(button.dataset.path);
    });
  });

  async function removeSource(path) {
    if (sourceOpen) sourceOpen.disabled = true;
    setSourceStatus(t("Removing…"), false);
    try {
      const res = await fetch("/api/source/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setSourceStatus(data.error || t("Failed (%(status)s)", { status: res.status }), true);
        if (sourceOpen) sourceOpen.disabled = false;
        return;
      }
      setSourceStatus(t("Removed — reloading…"), false);
      window.location.href = "/";
    } catch (err) {
      setSourceStatus(String(err && err.message ? err.message : err), true);
      if (sourceOpen) sourceOpen.disabled = false;
    }
  }

  const sourceViewToggle = document.getElementById("source-view-toggle");
  const articleBody = document.querySelector(".markdown-body");
  let cachedRenderedHtml = null;
  let cachedRawSource = null;
  let sourceViewActive = false;

  async function showSourceView() {
    if (!sourceViewToggle || !articleBody) return;
    const filePath = sourceViewToggle.dataset.file;
    if (!filePath) return;
    if (cachedRawSource === null) {
      sourceViewToggle.disabled = true;
      try {
        const res = await fetch(`/raw/${filePath.split("/").map(encodeURIComponent).join("/")}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        cachedRawSource = await res.text();
      } catch (err) {
        sourceViewToggle.disabled = false;
        return;
      }
      sourceViewToggle.disabled = false;
    }
    cachedRenderedHtml = articleBody.innerHTML;
    const pre = document.createElement("pre");
    pre.className = "source-view";
    const code = document.createElement("code");
    code.textContent = cachedRawSource;
    pre.appendChild(code);
    articleBody.replaceChildren(pre);
    addCopyButtons(articleBody);
    sourceViewActive = true;
    sourceViewToggle.setAttribute("aria-pressed", "true");
    sourceViewToggle.title = t("View rendered");
  }

  function showRenderedView() {
    if (!articleBody || cachedRenderedHtml === null) return;
    articleBody.innerHTML = cachedRenderedHtml;
    sourceViewActive = false;
    sourceViewToggle.setAttribute("aria-pressed", "false");
    sourceViewToggle.title = t("View source");
  }

  if (sourceViewToggle) {
    sourceViewToggle.addEventListener("click", function () {
      if (sourceViewActive) showRenderedView();
      else showSourceView();
    });
  }

  // --- Edit mode (text-only, local sources only) --------------------------
  // The edit button only renders for a local source (see `editable` in the
  // template), so its absence is the gate — no client-side source check needed.
  const editToggle = document.getElementById("edit-toggle");
  let editActive = false;
  let editorCM = null;
  let editorDoSave = null;  // set while editing, so Ctrl+S can trigger the save
  let editorSaved = false;  // a save happened this session → re-render on exit
  let editorIsDirty = () => false;  // module accessor for the unsaved-changes guard
  let editorEscape = null;          // Esc handler while editing (fullscreen / exit)
  let editorClearDraft = () => {};  // drop the localStorage draft on discard/save

  // CodeMirror is lazy-loaded from CDN the first time edit mode opens, so a plain
  // page view never pays for it. Failure (offline, blocked CDN) is non-fatal — the
  // editor falls back to the plain <textarea>.
  const CM_BASE = "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16";
  let cmReady = null;

  function loadCss(href) {
    return new Promise((resolve) => {
      if (document.querySelector(`link[data-cm="${href}"]`)) return resolve();
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.dataset.cm = href;
      link.onload = () => resolve();
      link.onerror = () => resolve();  // non-fatal: editor still works unstyled
      document.head.appendChild(link);
    });
  }

  // App theme id → a CodeMirror 5 theme that ships an exact/close match (loaded
  // on demand from the same CDN). Anything not listed falls back to the coarse
  // light/dark bucket below. Each value is both the theme name and its CSS file
  // basename, so a single-token theme is required (no "solarized dark" forms).
  const CM_THEME_MAP = {
    dracula: "dracula",
    "one-dark": "material-darker",
    "tokyo-night": "material-ocean",
    "catppuccin-mocha": "material-palenight",
    "night-owl": "material-ocean",
    "material-palenight": "material-palenight",
    cobalt2: "cobalt",
    monokai: "monokai",
    nord: "nord",
    "gruvbox-dark-hard": "gruvbox-dark",
  };

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[data-cm="${src}"]`)) return resolve();
      const s = document.createElement("script");
      s.src = src;
      s.dataset.cm = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(s);
    });
  }

  function ensureCodeMirror() {
    if (cmReady) return cmReady;
    cmReady = (async () => {
      loadCss(`${CM_BASE}/codemirror.min.css`);
      loadCss(`${CM_BASE}/addon/dialog/dialog.min.css`);
      await loadScript(`${CM_BASE}/codemirror.min.js`);
      await loadScript(`${CM_BASE}/mode/markdown/markdown.min.js`);
      // Addons (all need the core first): list continuation on Enter, and
      // find/replace (Ctrl-F / Ctrl-H via the dialog + search-cursor addons).
      await loadScript(`${CM_BASE}/addon/edit/continuelist.min.js`);
      await loadScript(`${CM_BASE}/addon/dialog/dialog.min.js`);
      await loadScript(`${CM_BASE}/addon/search/searchcursor.min.js`);
      await loadScript(`${CM_BASE}/addon/search/search.min.js`);
      return window.CodeMirror || null;
    })().catch(() => null);
    return cmReady;
  }

  async function enterEditMode() {
    if (!editToggle || !articleBody) return;
    const filePath = editToggle.dataset.file;
    if (!filePath) return;
    // Leave source view first so we restore from the rendered HTML, not a <pre>.
    if (sourceViewActive) showRenderedView();
    if (cachedRawSource === null) {
      editToggle.disabled = true;
      try {
        const res = await fetch(`/raw/${filePath.split("/").map(encodeURIComponent).join("/")}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        cachedRawSource = await res.text();
      } catch (err) {
        editToggle.disabled = false;
        return;
      }
      editToggle.disabled = false;
    }

    cachedRenderedHtml = articleBody.innerHTML;

    const wrap = document.createElement("div");
    wrap.className = "editor";
    const toolbar = document.createElement("div");
    toolbar.className = "editor-toolbar";
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "source-button";
    saveBtn.textContent = t("Save");
    saveBtn.title = t("Save (Ctrl+S)");
    // "Exit" leaves the editor (keeping saved work); it is *not* a discard — that
    // confusion is why the old "Cancel" label was renamed. "Discard changes"
    // reverts the text to the last saved/disk version but stays in the editor.
    const exitBtn = document.createElement("button");
    exitBtn.type = "button";
    exitBtn.className = "source-button secondary";
    exitBtn.textContent = t("Exit");
    exitBtn.title = t("Exit editor");
    const discardBtn = document.createElement("button");
    discardBtn.type = "button";
    discardBtn.className = "source-button secondary";
    discardBtn.textContent = t("Discard changes");
    discardBtn.title = t("Revert to the last saved version");
    discardBtn.disabled = true;

    // Formatting buttons (also bound to Ctrl/⌘+B/I/K below).
    function mkFmt(label, title, cls) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "icon-button editor-fmt" + (cls ? " " + cls : "");
      btn.textContent = label;
      btn.title = title;
      btn.setAttribute("aria-label", title);
      return btn;
    }
    const boldBtn = mkFmt("B", t("Bold (Ctrl+B)"), "fmt-bold");
    const italicBtn = mkFmt("I", t("Italic (Ctrl+I)"), "fmt-italic");
    const codeBtn = mkFmt("</>", t("Inline code"), "fmt-code");
    const linkBtn = mkFmt("↗", t("Insert link (Ctrl+K)"));
    const fmtGroup = document.createElement("div");
    fmtGroup.className = "editor-fmt-group";
    fmtGroup.append(boldBtn, italicBtn, codeBtn, linkBtn);

    const previewToggle = document.createElement("button");
    previewToggle.type = "button";
    previewToggle.className = "source-button secondary editor-preview-toggle";
    previewToggle.textContent = t("Preview");
    previewToggle.setAttribute("aria-pressed", "false");

    // Scroll-sync toggle: only meaningful in split (preview) mode, so it stays
    // hidden until Preview is on. Sync is enabled by default.
    const syncToggle = document.createElement("button");
    syncToggle.type = "button";
    syncToggle.className = "source-button secondary editor-sync-toggle";
    syncToggle.textContent = t("Sync scroll");
    syncToggle.title = t("Keep editor and preview scroll positions aligned");
    syncToggle.setAttribute("aria-pressed", "true");
    syncToggle.hidden = true;

    const fsBtn = document.createElement("button");
    fsBtn.type = "button";
    fsBtn.className = "icon-button editor-fs-toggle";
    fsBtn.textContent = "⛶";
    fsBtn.title = t("Toggle fullscreen");
    fsBtn.setAttribute("aria-label", t("Toggle fullscreen"));
    fsBtn.setAttribute("aria-pressed", "false");

    const dirtyFlag = document.createElement("span");
    dirtyFlag.className = "editor-dirty";
    dirtyFlag.hidden = true;
    dirtyFlag.textContent = "● " + t("Unsaved changes");
    const wordCount = document.createElement("span");
    wordCount.className = "editor-wordcount";
    const status = document.createElement("span");
    status.className = "editor-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    toolbar.append(saveBtn, exitBtn, discardBtn, fmtGroup, previewToggle, syncToggle, fsBtn, dirtyFlag, wordCount, status);

    // Draft autosave/recovery: a localStorage backup of unsaved edits, keyed per
    // source + file. If one exists and differs from disk, offer to restore it
    // (survives a crash / accidental close that the unsaved-changes guard can't).
    const draftKey = "markwright-draft:" + (window.MARKWRIGHT_ROOT || "") + ":" + filePath;
    editorClearDraft = () => { try { localStorage.removeItem(draftKey); } catch (_) {} };
    let initialContent = cachedRawSource;
    try {
      const raw = localStorage.getItem(draftKey);
      if (raw) {
        const d = JSON.parse(raw);
        if (d && typeof d.content === "string" && d.content !== cachedRawSource) {
          const when = d.savedAt ? new Date(d.savedAt).toLocaleString() : "";
          if (window.confirm(t("An unsaved draft from %(when)s was found. Restore it?", { when: when }))) {
            initialContent = d.content;
          } else {
            editorClearDraft();
          }
        } else {
          editorClearDraft();  // stale (matches disk or malformed)
        }
      }
    } catch (_) {}

    const textarea = document.createElement("textarea");
    textarea.className = "editor-textarea";
    textarea.spellcheck = false;
    textarea.value = initialContent;

    // Split body: editor pane + (optional) live-preview pane.
    const body = document.createElement("div");
    body.className = "editor-body";
    const editorPane = document.createElement("div");
    editorPane.className = "editor-pane";
    editorPane.appendChild(textarea);
    const previewPane = document.createElement("div");
    previewPane.className = "markdown-body editor-preview";
    previewPane.hidden = true;
    body.append(editorPane, previewPane);

    wrap.append(toolbar, body);
    articleBody.replaceChildren(wrap);

    editActive = true;
    editorSaved = false;
    editToggle.setAttribute("aria-pressed", "true");
    editToggle.title = t("Stop editing");
    if (sourceViewToggle) sourceViewToggle.disabled = true;

    const currentValue = () => (editorCM ? editorCM.getValue() : textarea.value);

    // Markdown formatting helpers (CodeMirror only; the plain-textarea fallback
    // keeps basic editing). wrapSel toggles markers around the selection.
    function wrapSel(before, after) {
      if (!editorCM) return;
      after = after === undefined ? before : after;
      const sel = editorCM.getSelection();
      if (sel) {
        editorCM.replaceSelection(before + sel + after);
      } else {
        const cur = editorCM.getCursor();
        editorCM.replaceSelection(before + after);
        editorCM.setCursor({ line: cur.line, ch: cur.ch + before.length });
      }
      editorCM.focus();
    }
    function insertLink() {
      if (!editorCM) return;
      const sel = editorCM.getSelection();
      if (sel) {
        editorCM.replaceSelection("[" + sel + "](url)");
        const cur = editorCM.getCursor();  // select the "url" placeholder
        editorCM.setSelection({ line: cur.line, ch: cur.ch - 4 }, { line: cur.line, ch: cur.ch - 1 });
      } else {
        const cur = editorCM.getCursor();
        editorCM.replaceSelection("[](url)");
        editorCM.setCursor({ line: cur.line, ch: cur.ch + 1 });
      }
      editorCM.focus();
    }

    // Upgrade the textarea to a CodeMirror editor (Markdown highlighting + line
    // numbers, list continuation, formatting + find/replace keys). On failure the
    // plain textarea is left in place.
    editorCM = null;
    const CM = await ensureCodeMirror();
    if (CM && editActive) {
      const themeName = root.dataset.theme;
      const isDark = DARK_THEMES.has(themeName);
      const cmTheme = CM_THEME_MAP[themeName] || (isDark ? "material-darker" : "default");
      // "default" is built into the core CSS; everything else loads on demand.
      if (cmTheme !== "default") await loadCss(`${CM_BASE}/theme/${cmTheme}.min.css`);
      editorCM = CM.fromTextArea(textarea, {
        mode: "markdown",
        theme: cmTheme,
        lineNumbers: true,
        lineWrapping: true,
        extraKeys: {
          "Enter": "newlineAndIndentContinueMarkdownList",
          "Ctrl-B": () => wrapSel("**", "**"),
          "Cmd-B": () => wrapSel("**", "**"),
          "Ctrl-I": () => wrapSel("*", "*"),
          "Cmd-I": () => wrapSel("*", "*"),
          "Ctrl-K": () => insertLink(),
          "Cmd-K": () => insertLink(),
        },
      });
      editorCM.setSize("100%", "60vh");
      editorCM.focus();
    } else {
      textarea.focus();
    }

    // Word/character count (both editors).
    function updateWordCount() {
      const v = currentValue();
      const words = (v.match(/\S+/g) || []).length;
      wordCount.textContent = t("%(w)s words · %(c)s chars", { w: words, c: v.length });
    }

    // Live preview: render the unsaved text via /api/render (debounced), shown in
    // a split pane. Mermaid blocks are re-run if the library is available.
    let previewActive = false;
    let previewTimer = null;
    async function renderPreview() {
      if (!previewActive) return;
      try {
        const res = await fetch("/api/render", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file: filePath, content: currentValue() }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        previewPane.innerHTML = data.html;
        const diagrams = previewPane.querySelectorAll("pre.mermaid");
        if (diagrams.length && window.__mermaid) {
          diagrams.forEach((el) => { el.dataset.source = el.textContent; el.removeAttribute("data-processed"); });
          try { window.__mermaid.run({ nodes: diagrams }); } catch (_) {}
        }
      } catch (err) {
        previewPane.textContent = String(err && err.message ? err.message : err);
      }
    }
    function schedulePreview() {
      if (!previewActive) return;
      clearTimeout(previewTimer);
      previewTimer = setTimeout(renderPreview, 350);
    }
    function togglePreview() {
      previewActive = !previewActive;
      previewPane.hidden = !previewActive;
      wrap.classList.toggle("is-split", previewActive);
      previewToggle.setAttribute("aria-pressed", String(previewActive));
      syncToggle.hidden = !previewActive;  // sync only applies in split mode
      if (editorCM) editorCM.refresh();  // re-measure after the width change
      if (previewActive) renderPreview().then(syncFromEditor);  // align on open
    }

    // Heading-anchored scroll sync between the editor and the live preview.
    // Headings are exact shared landmarks — the toc extension stamps an id on each
    // preview heading, and CodeMirror gives line→pixel offsets — so we pair them in
    // document order and interpolate *between adjacent headings*. A tall block
    // (diagram/code) then only skews its own section instead of the whole document
    // (which is what made pure-proportional sync lurch). With no headings the table
    // collapses to its virtual top/bottom endpoints, i.e. plain proportional.
    // Setting scrollTop queues a scroll event that fires before the next rAF, so a
    // flag raised here and cleared on rAF swallows that echo (no feedback loop).
    // Toggleable via the toolbar's "Sync scroll" button (on by default). The plain
    // <textarea> fallback (no CodeMirror) lacks a line→pixel API, so it stays
    // proportional. Setext headings (=== / --- underlines) are matched too.
    let scrollSyncing = false;
    let syncEnabled = true;
    const FENCE_RE = /^ {0,3}(```|~~~)/;
    const ATX_RE = /^ {0,3}#{1,6}\s/;
    function sourceHeadingLines() {
      const lines = currentValue().split("\n");
      const out = [];
      let inFence = false;
      for (let i = 0; i < lines.length; i++) {
        const ln = lines[i];
        if (FENCE_RE.test(ln)) { inFence = !inFence; continue; }
        if (inFence) continue;
        if (ATX_RE.test(ln)) { out.push(i); continue; }
        const next = lines[i + 1];  // setext: text line underlined by === or ---
        if (next !== undefined && /^ {0,3}(=+|-+)\s*$/.test(next) &&
            ln.trim() !== "" && !/^ {0,3}([-*+]|\d+\.)\s/.test(ln) && !/^ {0,3}>/.test(ln)) {
          out.push(i);
          i++;  // skip the underline row
        }
      }
      return out;
    }
    // Paired ascending anchor arrays in *content* coordinates: editor doc pixels
    // (eHeights) ↔ preview content pixels (pTops), bracketed by 0 and full height.
    function anchorTable() {
      const eHeights = [0];
      const pTops = [0];
      const srcLines = sourceHeadingLines();
      const pHeads = previewPane.querySelectorAll("h1,h2,h3,h4,h5,h6");
      const n = Math.min(srcLines.length, pHeads.length);
      const pBase = previewPane.getBoundingClientRect().top - previewPane.scrollTop;
      for (let i = 0; i < n; i++) {
        const ey = editorCM.heightAtLine(srcLines[i], "local");
        const py = pHeads[i].getBoundingClientRect().top - pBase;
        // keep both axes strictly ascending so interpolation segments stay valid
        if (ey > eHeights[eHeights.length - 1] && py > pTops[pTops.length - 1]) {
          eHeights.push(ey);
          pTops.push(py);
        }
      }
      eHeights.push(editorCM.getScrollInfo().height);
      pTops.push(previewPane.scrollHeight);
      return { eHeights, pTops };
    }
    function interp(x, xs, ys) {
      if (x <= xs[0]) return ys[0];
      for (let i = 1; i < xs.length; i++) {
        if (x <= xs[i]) {
          const span = xs[i] - xs[i - 1];
          const f = span > 0 ? (x - xs[i - 1]) / span : 0;
          return ys[i - 1] + f * (ys[i] - ys[i - 1]);
        }
      }
      return ys[ys.length - 1];
    }
    function syncFromEditor() {
      if (scrollSyncing || !previewActive || !syncEnabled) return;
      scrollSyncing = true;
      if (editorCM) {
        const { eHeights, pTops } = anchorTable();
        previewPane.scrollTop = interp(editorCM.getScrollInfo().top, eHeights, pTops);
      } else {
        const max = textarea.scrollHeight - textarea.clientHeight;
        const f = max > 0 ? textarea.scrollTop / max : 0;
        previewPane.scrollTop = f * (previewPane.scrollHeight - previewPane.clientHeight);
      }
      requestAnimationFrame(() => { scrollSyncing = false; });
    }
    function syncFromPreview() {
      if (scrollSyncing || !previewActive || !syncEnabled) return;
      scrollSyncing = true;
      if (editorCM) {
        const { eHeights, pTops } = anchorTable();
        editorCM.scrollTo(null, interp(previewPane.scrollTop, pTops, eHeights));
      } else {
        const max = previewPane.scrollHeight - previewPane.clientHeight;
        const f = max > 0 ? previewPane.scrollTop / max : 0;
        textarea.scrollTop = f * (textarea.scrollHeight - textarea.clientHeight);
      }
      requestAnimationFrame(() => { scrollSyncing = false; });
    }
    if (editorCM) editorCM.on("scroll", syncFromEditor);
    else textarea.addEventListener("scroll", syncFromEditor, { passive: true });
    previewPane.addEventListener("scroll", syncFromPreview, { passive: true });

    // Distraction-free / fullscreen: the editor fills the viewport.
    let fullscreen = false;
    function toggleFullscreen() {
      fullscreen = !fullscreen;
      wrap.classList.toggle("is-fullscreen", fullscreen);
      document.body.classList.toggle("editor-fs-lock", fullscreen);
      fsBtn.setAttribute("aria-pressed", String(fullscreen));
      if (editorCM) {
        editorCM.setSize("100%", fullscreen ? "100%" : "60vh");
        editorCM.refresh();
      }
    }

    // Image paste / drag-drop → upload next to the doc, insert `![](name)`.
    function insertAtCursor(text) {
      if (editorCM) { editorCM.replaceSelection(text); editorCM.focus(); }
      else {
        const s = textarea.selectionStart, e = textarea.selectionEnd;
        textarea.value = textarea.value.slice(0, s) + text + textarea.value.slice(e);
        textarea.selectionStart = textarea.selectionEnd = s + text.length;
        onEditorChange();
      }
    }
    async function uploadImage(file) {
      if (!file) return;
      const fd = new FormData();
      fd.append("file", filePath);
      const name = file.name || ("pasted." + ((file.type.split("/")[1]) || "png"));
      fd.append("image", file, name);
      status.classList.remove("is-error");
      status.textContent = t("Uploading image…");
      try {
        const res = await fetch("/api/upload-asset", { method: "POST", body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        insertAtCursor("![](" + data.path + ")");
        status.textContent = "";
      } catch (err) {
        status.classList.add("is-error");
        status.textContent = String(err && err.message ? err.message : err);
      }
    }

    // Dirty tracking: compare the live value against the loaded baseline. The
    // flag shows in the toolbar and the Save button is disabled while clean.
    let dirty = false;
    function updateDirty() {
      dirty = currentValue() !== cachedRawSource;
      dirtyFlag.hidden = !dirty;
      saveBtn.disabled = !dirty;
      discardBtn.disabled = !dirty;  // only meaningful when there's something to revert
    }
    // Debounced draft backup: store while dirty, clear once it matches disk.
    let draftTimer = null;
    function saveDraft() {
      try {
        if (dirty) localStorage.setItem(draftKey, JSON.stringify({ content: currentValue(), savedAt: Date.now() }));
        else editorClearDraft();
      } catch (_) {}
    }
    function scheduleDraft() {
      clearTimeout(draftTimer);
      draftTimer = setTimeout(saveDraft, 800);
    }

    function onEditorChange() {
      updateDirty();
      updateWordCount();
      schedulePreview();
      scheduleDraft();
    }
    if (editorCM) editorCM.on("change", onEditorChange);
    textarea.addEventListener("input", onEditorChange);  // plain-textarea fallback
    updateDirty();      // start clean → Save disabled (or dirty if a draft was restored)
    updateWordCount();
    editorIsDirty = () => dirty;  // expose to the navigation/close guard
    editorEscape = function () {
      if (document.querySelector(".CodeMirror-dialog")) return false;  // let find dialog close
      if (fullscreen) { toggleFullscreen(); return true; }
      exitEditMode();
      return true;
    };

    boldBtn.addEventListener("click", () => wrapSel("**", "**"));
    italicBtn.addEventListener("click", () => wrapSel("*", "*"));
    codeBtn.addEventListener("click", () => wrapSel("`", "`"));
    linkBtn.addEventListener("click", insertLink);
    previewToggle.addEventListener("click", togglePreview);
    syncToggle.addEventListener("click", () => {
      syncEnabled = !syncEnabled;
      syncToggle.setAttribute("aria-pressed", String(syncEnabled));
      if (syncEnabled) syncFromEditor();  // re-align immediately on enable
    });
    fsBtn.addEventListener("click", toggleFullscreen);

    // Paste smarts: a URL pasted over a selection becomes a link; a pasted image
    // uploads. Drag-and-dropped images upload too. (CodeMirror only.)
    if (editorCM) {
      editorCM.getInputField().addEventListener("paste", function (e) {
        const cd = e.clipboardData;
        if (!cd) return;
        const imgItem = Array.from(cd.items || []).find((it) => it.kind === "file" && it.type.startsWith("image/"));
        if (imgItem) { e.preventDefault(); uploadImage(imgItem.getAsFile()); return; }
        const text = cd.getData("text") || "";
        const sel = editorCM.getSelection();
        if (sel && /^(https?:\/\/|mailto:)\S+$/i.test(text.trim())) {
          e.preventDefault();
          editorCM.replaceSelection("[" + sel + "](" + text.trim() + ")");
        }
      });
      editorCM.on("drop", function (cm, e) {
        const files = e.dataTransfer && e.dataTransfer.files;
        const imgs = files ? Array.from(files).filter((f) => f.type.startsWith("image/")) : [];
        if (imgs.length) {
          e.preventDefault();
          try { cm.setCursor(cm.coordsChar({ left: e.clientX, top: e.clientY })); } catch (_) {}
          imgs.forEach(uploadImage);
        }
      });
    }

    async function doSave() {
      if (!dirty || saveBtn.disabled) return;
      saveBtn.disabled = true;
      exitBtn.disabled = true;
      discardBtn.disabled = true;
      status.classList.remove("is-error");
      status.textContent = t("Saving…");
      try {
        const res = await fetch("/api/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file: filePath, content: currentValue() }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        // Stay in the editor: adopt the saved text as the new baseline (clears
        // the dirty flag) and just confirm. The rendered view is refreshed only
        // when you leave edit mode (exitEditMode reloads when editorSaved).
        cachedRawSource = currentValue();
        editorSaved = true;
        editorClearDraft();        // saved == disk, no draft to recover
        updateDirty();             // content == baseline → clean, Save/Discard disabled
        exitBtn.disabled = false;
        status.textContent = t("Saved");
        if (editorCM) editorCM.focus(); else textarea.focus();
      } catch (err) {
        status.classList.add("is-error");
        status.textContent = String(err && err.message ? err.message : err);
        saveBtn.disabled = false;
        exitBtn.disabled = false;
        discardBtn.disabled = false;
      }
    }
    editorDoSave = doSave;
    // Revert to the last saved/disk version without leaving the editor. Destructive
    // (drops unsaved edits) so it confirms first; only reachable while dirty.
    function discardChanges() {
      if (!dirty) return;
      if (!window.confirm(t("Discard unsaved changes?"))) return;
      if (editorCM) editorCM.setValue(cachedRawSource); else textarea.value = cachedRawSource;
      editorClearDraft();
      updateDirty();
      updateWordCount();
      schedulePreview();
      status.textContent = "";
      if (editorCM) editorCM.focus(); else textarea.focus();
    }
    exitBtn.addEventListener("click", exitEditMode);
    discardBtn.addEventListener("click", discardChanges);
    saveBtn.addEventListener("click", doSave);
  }

  function exitEditMode() {
    if (!articleBody || cachedRenderedHtml === null) return;
    // Guard unsaved changes (Cancel / Stop-editing while dirty). Page navigations
    // are covered separately by the beforeunload handler.
    if (editActive && editorIsDirty() && !window.confirm(t("Discard unsaved changes?"))) return;
    editorClearDraft();           // explicit discard → drop the recovery draft
    editorIsDirty = () => false;
    editorEscape = null;
    document.body.classList.remove("editor-fs-lock");
    // If anything was saved this session the cached HTML is stale, so reload to
    // render the saved file (TOC/frontmatter included). Otherwise (pure cancel)
    // just restore the cached render — no network, no flicker.
    if (editorSaved) {
      window.location.reload();
      return;
    }
    articleBody.innerHTML = cachedRenderedHtml;  // discards the CodeMirror DOM
    editorCM = null;
    editorDoSave = null;
    editActive = false;
    editToggle.setAttribute("aria-pressed", "false");
    editToggle.title = t("Edit");
    if (sourceViewToggle) sourceViewToggle.disabled = false;
  }

  if (editToggle) {
    editToggle.addEventListener("click", function () {
      if (editActive) exitEditMode();
      else enterEditMode();
    });
    // Ctrl/Cmd+S saves while editing (and suppresses the browser's Save dialog).
    // CodeMirror leaves Ctrl-S unbound, so the keydown reaches here.
    document.addEventListener("keydown", function (event) {
      if (!editActive) return;
      if ((event.ctrlKey || event.metaKey) && (event.key === "s" || event.key === "S")) {
        event.preventDefault();
        if (editorDoSave) editorDoSave();
      } else if (event.key === "Escape" && editorEscape) {
        // Esc exits fullscreen, else leaves edit mode (a find dialog handles its
        // own Esc — editorEscape returns false there so we don't intercept).
        if (editorEscape()) event.preventDefault();
      }
    });
    // Unsaved-changes guard for page navigations (sidebar links, reload, tab
    // close, source switch — all trigger a real navigation → beforeunload).
    window.addEventListener("beforeunload", function (event) {
      if (editActive && editorIsDirty()) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }

  // --- File actions: new / rename / delete (local sources only) -----------
  // The kebab menu only renders for a local source (template `editable` gate),
  // so its presence is the client-side gate. Same open/close pattern as the
  // settings/export popovers.
  const fileMenuToggle = document.getElementById("file-menu-toggle");
  const fileMenuPopover = document.getElementById("file-menu-popover");
  if (fileMenuToggle && fileMenuPopover) {
    const fileMenuList = document.getElementById("file-menu-list");
    const fileMenuForm = document.getElementById("file-menu-form");
    const fmTitle = document.getElementById("fm-form-title");
    const fmInput = document.getElementById("fm-form-input");
    const fmSubmit = document.getElementById("fm-form-submit");
    const fmCancel = document.getElementById("fm-form-cancel");
    const fmStatus = document.getElementById("fm-form-status");
    let fmMode = null;        // "new" | "rename" | "delete"
    let fmCurrent = "";       // the file being renamed/deleted

    // Reset to the menu list (also called whenever the popover closes), so the
    // next open always starts from the action list, never a half-filled form.
    function showFileMenuList() {
      fmMode = null;
      fileMenuForm.hidden = true;
      fileMenuList.hidden = false;
      fmStatus.textContent = "";
      fmStatus.classList.remove("is-error");
    }

    const setFileMenuOpen = (open) => {
      fileMenuPopover.hidden = !open;
      fileMenuToggle.setAttribute("aria-expanded", String(open));
      if (!open) showFileMenuList();
    };
    fileMenuToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      setFileMenuOpen(fileMenuPopover.hidden);
    });
    fileMenuPopover.addEventListener("click", (event) => event.stopPropagation());
    document.addEventListener("click", () => {
      if (!fileMenuPopover.hidden) setFileMenuOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !fileMenuPopover.hidden) setFileMenuOpen(false);
    });

    // Swap the popover from the action list to the inline form for one action.
    // Replaces the old prompt()/confirm() dialogs (and their error alert()).
    function openFileForm(mode, current, name) {
      fmMode = mode;
      fmCurrent = current || "";
      fmStatus.textContent = "";
      fmStatus.classList.remove("is-error");
      const isDelete = mode === "delete";
      fmInput.hidden = isDelete;
      if (mode === "new") {
        fmTitle.textContent = t("New file");
        fmInput.value = "";
        fmInput.placeholder = t("notes.md or docs/notes.md");
        fmSubmit.textContent = t("Create");
        fmSubmit.classList.remove("danger");
      } else if (mode === "rename") {
        fmTitle.textContent = t("Rename file");
        fmInput.value = current;
        fmSubmit.textContent = t("Rename");
        fmSubmit.classList.remove("danger");
      } else {
        fmTitle.textContent = t('Delete "%(name)s"? This cannot be undone.', { name: name || current });
        fmSubmit.textContent = t("Delete");
        fmSubmit.classList.add("danger");
      }
      fileMenuList.hidden = true;
      fileMenuForm.hidden = false;
      // Focus the input for new/rename; for delete focus Cancel so a stray Enter
      // never deletes.
      (isDelete ? fmCancel : fmInput).focus();
    }

    const fmNew = document.getElementById("fm-new");
    if (fmNew) fmNew.addEventListener("click", () => openFileForm("new"));
    const fmRename = document.getElementById("fm-rename");
    if (fmRename) fmRename.addEventListener("click", () => openFileForm("rename", fmRename.dataset.file || ""));
    const fmDelete = document.getElementById("fm-delete");
    if (fmDelete) fmDelete.addEventListener("click", () => openFileForm("delete", fmDelete.dataset.file || "", fmDelete.dataset.name));

    fmCancel.addEventListener("click", showFileMenuList);

    fileMenuForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      let url, body, redirectTo;
      if (fmMode === "delete") {
        url = "/api/file/delete";
        body = { file: fmCurrent };
        redirectTo = () => "/";
      } else {
        const value = fmInput.value.trim();
        if (!value) { fmInput.focus(); return; }
        if (fmMode === "rename" && value === fmCurrent) { showFileMenuList(); return; }
        url = fmMode === "new" ? "/api/file/new" : "/api/file/rename";
        body = fmMode === "new" ? { path: value } : { file: fmCurrent, to: value };
        redirectTo = (data) => "/?file=" + encodeURIComponent(data.file);
      }
      fmSubmit.disabled = true;
      fmCancel.disabled = true;
      fmStatus.classList.remove("is-error");
      fmStatus.textContent = t("Working…");
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        window.location.href = redirectTo(data);
      } catch (err) {
        fmStatus.classList.add("is-error");
        fmStatus.textContent = String(err && err.message ? err.message : err);
        fmSubmit.disabled = false;
        fmCancel.disabled = false;
      }
    });
  }

  const exportButton = document.getElementById("export-pdf");
  const exportPopover = document.getElementById("export-popover");
  if (exportButton && exportPopover) {
    const exportHeader = {
      left: document.getElementById("export-header-left"),
      center: document.getElementById("export-header-center"),
      right: document.getElementById("export-header-right"),
    };
    const exportFooter = {
      left: document.getElementById("export-footer-left"),
      center: document.getElementById("export-footer-center"),
      right: document.getElementById("export-footer-right"),
    };
    const runButton = document.getElementById("export-run");
    const runDocxButton = document.getElementById("export-run-docx");
    const statusEl = document.getElementById("export-status");
    const includeToc = document.getElementById("export-include-toc");
    const includeCover = document.getElementById("export-include-cover");
    const includeFrontmatter = document.getElementById("export-include-frontmatter");
    const presetSelect = document.getElementById("export-preset");
    const manageButton = document.getElementById("export-manage");
    const file = exportButton.dataset.file || "";
    const docName = exportButton.dataset.name || "document";

    // Defaults mirror the previous single-field behavior, placed in the center
    // column (filename header, title/pagination footer).
    const DEFAULT_HEADER = { left: "", center: "{title}", right: "" };
    const DEFAULT_FOOTER = { left: "", center: "", right: "{page}/{total} · {date}" };

    function setBand(refs, cols) {
      refs.left.value = (cols && cols.left) || "";
      refs.center.value = (cols && cols.center) || "";
      refs.right.value = (cols && cols.right) || "";
    }

    setBand(exportHeader, DEFAULT_HEADER);
    setBand(exportFooter, DEFAULT_FOOTER);

    let presets = [];
    const EXPORT_PRESET_KEY = "markwright-export-preset";
    let presetSelectInitialized = false;

    function renderPresetSelect() {
      const current = presetSelect.value;
      presetSelect.innerHTML = '<option value="">Custom (no preset)</option>';
      presets.forEach(function (preset) {
        const opt = document.createElement("option");
        opt.value = preset.id;
        opt.textContent = preset.name;
        presetSelect.appendChild(opt);
      });
      if (!presetSelectInitialized) {
        // First populate: restore the last-used preset from localStorage (if it
        // still exists), then apply it so the bands/toggles reflect it.
        presetSelectInitialized = true;
        let stored = "";
        try { stored = localStorage.getItem(EXPORT_PRESET_KEY) || ""; } catch (_) {}
        presetSelect.value = presets.some((p) => p.id === stored) ? stored : "";
        presetSelect.dispatchEvent(new Event("change"));
        return;  // change handler already ran syncCoverToggle()
      }
      // Later re-renders (after save/delete): keep the in-session selection.
      presetSelect.value = presets.some((p) => p.id === current) ? current : "";
      syncCoverToggle();
    }

    async function loadPresets() {
      try {
        const res = await fetch("/api/pdf-presets");
        const data = await res.json();
        presets = Array.isArray(data.presets) ? data.presets : [];
      } catch (_) {
        presets = [];
      }
      renderPresetSelect();
      renderPresetList();
    }

    // The cover's content lives in a preset, so the cover toggle only applies
    // when one is selected.
    function syncCoverToggle() {
      const preset = presets.find((p) => p.id === presetSelect.value);
      includeCover.disabled = !preset;
      includeCover.checked = !!(preset && preset.coverEnabled);
    }

    presetSelect.addEventListener("change", function () {
      const preset = presets.find((p) => p.id === presetSelect.value);
      setBand(exportHeader, preset ? preset.header : DEFAULT_HEADER);
      setBand(exportFooter, preset ? preset.footer : DEFAULT_FOOTER);
      if (preset) {
        includeToc.checked = !!preset.includeToc;
        includeFrontmatter.checked = !!preset.includeFrontmatter;
      }
      syncCoverToggle();
      // Remember the choice (incl. "" = Custom) so the next export defaults to it.
      try { localStorage.setItem(EXPORT_PRESET_KEY, presetSelect.value); } catch (_) {}
    });

    function setPopoverOpen(open) {
      exportPopover.hidden = !open;
      exportButton.setAttribute("aria-expanded", String(open));
      if (open) exportHeader.center.focus();
    }

    exportButton.addEventListener("click", function (event) {
      event.stopPropagation();
      setPopoverOpen(exportPopover.hidden);
    });

    exportPopover.addEventListener("click", function (event) {
      event.stopPropagation();
    });

    document.addEventListener("click", function () {
      if (!exportPopover.hidden) setPopoverOpen(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !exportPopover.hidden && presetModal.hidden) {
        setPopoverOpen(false);
      }
    });

    // Pull the download filename out of a Content-Disposition header, preferring
    // the RFC 5987 `filename*=UTF-8''…` form (handles accents/spaces) over the
    // plain `filename="…"`.
    function filenameFromDisposition(header) {
      if (!header) return "";
      let m = /filename\*=UTF-8''([^;]+)/i.exec(header);
      if (m) {
        try { return decodeURIComponent(m[1]); } catch (_) { return m[1]; }
      }
      m = /filename="?([^";]+)"?/i.exec(header);
      return m ? m[1] : "";
    }

    // PDF carries the full band/margin set; Word (pandoc) honors file, preset,
    // the contents-page flag and the cover toggle — header/footer bands,
    // margins and the frontmatter panel are print-only.
    async function runExport(format) {
      runButton.disabled = true;
      if (runDocxButton) runDocxButton.disabled = true;
      statusEl.textContent = t("Generating…");
      statusEl.classList.remove("is-error");
      const params = new URLSearchParams({ file: file });
      if (presetSelect.value) params.set("preset", presetSelect.value);
      params.set("include_toc", includeToc.checked ? "1" : "0");
      params.set("include_cover", includeCover.checked && !includeCover.disabled ? "1" : "0");
      if (format === "pdf") {
        params.set("header_left", exportHeader.left.value);
        params.set("header_center", exportHeader.center.value);
        params.set("header_right", exportHeader.right.value);
        params.set("footer_left", exportFooter.left.value);
        params.set("footer_center", exportFooter.center.value);
        params.set("footer_right", exportFooter.right.value);
        params.set("include_frontmatter", includeFrontmatter.checked ? "1" : "0");
      }
      try {
        const response = await fetch(`/export/${format}?${params.toString()}`);
        if (!response.ok) {
          let message = t("Error %(status)s", { status: response.status });
          try {
            const data = await response.json();
            if (data && data.error) message = data.error;
          } catch (_) { /* non-JSON error body */ }
          throw new Error(message);
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        // The server resolves the preset's filename template (it has the
        // frontmatter/title) and sends it in Content-Disposition; honor it,
        // falling back to the document's own name.
        link.download =
          filenameFromDisposition(response.headers.get("Content-Disposition")) ||
          docName.replace(/\.[^.]+$/, "") + "." + format;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        statusEl.textContent = t("Done");
        setTimeout(() => setPopoverOpen(false), 600);
      } catch (error) {
        statusEl.textContent = error.message || t("Failed");
        statusEl.classList.add("is-error");
      } finally {
        runButton.disabled = false;
        if (runDocxButton) runDocxButton.disabled = false;
      }
    }

    runButton.addEventListener("click", () => runExport("pdf"));
    if (runDocxButton) runDocxButton.addEventListener("click", () => runExport("docx"));

    // ---- Preset manager modal ----
    const presetModal = document.getElementById("preset-modal");
    const presetList = document.getElementById("preset-list");
    const presetNew = document.getElementById("preset-new");
    const presetClose = document.getElementById("preset-close");
    const form = document.getElementById("preset-form");
    const pf = {
      id: document.getElementById("pf-id"),
      name: document.getElementById("pf-name"),
      header: {
        left: document.getElementById("pf-header-left"),
        center: document.getElementById("pf-header-center"),
        right: document.getElementById("pf-header-right"),
      },
      footer: {
        left: document.getElementById("pf-footer-left"),
        center: document.getElementById("pf-footer-center"),
        right: document.getElementById("pf-footer-right"),
      },
      logopos: document.getElementById("pf-logopos"),
      logo: document.getElementById("pf-logo"),
      preview: document.getElementById("pf-logo-preview"),
      previewImg: document.getElementById("pf-logo-img"),
      logoRemove: document.getElementById("pf-logo-remove"),
      pagesize: document.getElementById("pf-pagesize"),
      orientation: document.getElementById("pf-orientation"),
      fontscale: document.getElementById("pf-fontscale"),
      fontfamily: document.getElementById("pf-fontfamily"),
      filename: document.getElementById("pf-filename"),
      includetoc: document.getElementById("pf-include-toc"),
      includefrontmatter: document.getElementById("pf-include-frontmatter"),
      useFallback: document.getElementById("pf-use-fallback"),
      fallbackFields: document.getElementById("pf-fallback-fields"),
      fallbackValues: document.getElementById("pf-fallback-values"),
      coverEnabled: document.getElementById("pf-cover-enabled"),
      coverFields: document.getElementById("pf-cover-fields"),
      coverTitle: document.getElementById("pf-cover-title"),
      coverSubtitle: document.getElementById("pf-cover-subtitle"),
      coverMeta: document.getElementById("pf-cover-meta"),
      coverFooter: document.getElementById("pf-cover-footer"),
      coverImageSource: document.getElementById("pf-cover-image-source"),
      blankAfterCover: document.getElementById("pf-blank-after-cover"),
      coverUpload: document.getElementById("pf-cover-upload"),
      coverImage: document.getElementById("pf-cover-image"),
      coverPreview: document.getElementById("pf-cover-preview"),
      coverImg: document.getElementById("pf-cover-img"),
      coverRemove: document.getElementById("pf-cover-remove"),
      mt: document.getElementById("pf-mt"),
      mb: document.getElementById("pf-mb"),
      ml: document.getElementById("pf-ml"),
      mr: document.getElementById("pf-mr"),
      save: document.getElementById("pf-save"),
      duplicate: document.getElementById("pf-duplicate"),
      del: document.getElementById("pf-delete"),
      status: document.getElementById("pf-status"),
    };
    // Default filename template prefilled for new presets (mirrors the server's
    // DEFAULT_FILENAME_TEMPLATE: {title} always resolves to something).
    const DEFAULT_FILENAME_TEMPLATE = "{title}";
    let removeLogo = false;
    let removeCoverImage = false;

    // Reuse the screen font list so the PDF body-font choices match the viewer's.
    // The server (PDF_FONTS) loads the matching webfont before printing.
    if (pf.fontfamily) {
      FONTS.forEach(function (f) {
        const opt = document.createElement("option");
        opt.value = f.key;
        opt.textContent = f.key === "" ? t("System default") : f.label;
        pf.fontfamily.appendChild(opt);
      });
    }

    function showCoverPreview(src) {
      if (src) {
        pf.coverImg.src = src;
        pf.coverPreview.hidden = false;
      } else {
        pf.coverImg.removeAttribute("src");
        pf.coverPreview.hidden = true;
      }
    }

    function syncCoverFields() {
      pf.coverFields.hidden = !pf.coverEnabled.checked;
    }

    function syncFallbackFields() {
      pf.fallbackFields.hidden = !pf.useFallback.checked;
    }

    // The upload control only matters when the cover image source is a custom
    // upload (vs. the preset logo or none).
    function syncCoverUpload() {
      pf.coverUpload.hidden = pf.coverImageSource.value !== "custom";
    }

    function showPreview(src) {
      if (src) {
        pf.previewImg.src = src;
        pf.preview.hidden = false;
      } else {
        pf.previewImg.removeAttribute("src");
        pf.preview.hidden = true;
      }
    }

    function fillForm(preset) {
      removeLogo = false;
      removeCoverImage = false;
      pf.logo.value = "";
      pf.coverImage.value = "";
      pf.status.textContent = "";
      pf.status.classList.remove("is-error");
      if (preset) {
        pf.id.value = preset.id;
        pf.name.value = preset.name || "";
        setBand(pf.header, preset.header);
        setBand(pf.footer, preset.footer);
        pf.logopos.value = preset.logoPosition || "left";
        pf.pagesize.value = preset.pageSize || "A4";
        pf.orientation.value = preset.orientation || "portrait";
        pf.fontscale.value = preset.fontScale != null ? preset.fontScale : 100;
        if (pf.fontfamily) pf.fontfamily.value = preset.fontFamily || "";
        pf.filename.value = preset.fileNameTemplate || "";
        pf.includetoc.checked = !!preset.includeToc;
        pf.includefrontmatter.checked = !!preset.includeFrontmatter;
        pf.useFallback.checked = !!preset.useFallback;
        pf.fallbackValues.value = preset.fallbackValues || "";
        pf.coverEnabled.checked = !!preset.coverEnabled;
        pf.coverTitle.value = preset.coverTitle || "";
        pf.coverSubtitle.value = preset.coverSubtitle || "";
        pf.coverMeta.value = preset.coverMeta || "";
        pf.coverFooter.value = preset.coverFooter || "";
        pf.coverImageSource.value = preset.coverImageSource || "none";
        pf.blankAfterCover.checked = !!preset.blankAfterCover;
        showCoverPreview(preset.hasCoverImage ? `/api/pdf-presets/${preset.id}/cover-image?t=${Date.now()}` : "");
        const m = preset.margins || {};
        pf.mt.value = m.top != null ? m.top : 20;
        pf.mb.value = m.bottom != null ? m.bottom : 20;
        pf.ml.value = m.left != null ? m.left : 12;
        pf.mr.value = m.right != null ? m.right : 12;
        pf.del.hidden = false;
        pf.duplicate.hidden = false;
        showPreview(preset.hasLogo ? `/api/pdf-presets/${preset.id}/logo?t=${Date.now()}` : "");
      } else {
        pf.id.value = "";
        pf.name.value = "";
        setBand(pf.header, DEFAULT_HEADER);
        setBand(pf.footer, DEFAULT_FOOTER);
        pf.logopos.value = "left";
        pf.pagesize.value = "A4";
        pf.orientation.value = "portrait";
        pf.fontscale.value = 100;
        if (pf.fontfamily) pf.fontfamily.value = "";
        pf.filename.value = DEFAULT_FILENAME_TEMPLATE;
        pf.includetoc.checked = false;
        pf.includefrontmatter.checked = false;
        pf.useFallback.checked = false;
        pf.fallbackValues.value = "";
        pf.coverEnabled.checked = false;
        pf.coverTitle.value = "";
        pf.coverSubtitle.value = "";
        pf.coverMeta.value = "";
        pf.coverFooter.value = "";
        pf.coverImageSource.value = "none";
        pf.blankAfterCover.checked = false;
        showCoverPreview("");
        pf.mt.value = 20; pf.mb.value = 20; pf.ml.value = 12; pf.mr.value = 12;
        pf.del.hidden = true;
        pf.duplicate.hidden = true;
        showPreview("");
      }
      syncCoverFields();
      syncCoverUpload();
      syncFallbackFields();
      renderPresetList();
    }

    function renderPresetList() {
      if (!presetList) return;
      presetList.innerHTML = "";
      if (!presets.length) {
        const li = document.createElement("li");
        li.className = "preset-empty";
        li.textContent = t("No presets yet.");
        presetList.appendChild(li);
        return;
      }
      presets.forEach(function (preset) {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = preset.name;
        if (preset.id === pf.id.value) btn.classList.add("is-active");
        btn.addEventListener("click", () => fillForm(preset));
        li.appendChild(btn);
        presetList.appendChild(li);
      });
    }

    function openModal() {
      setPopoverOpen(false);
      presetModal.hidden = false;
      loadPresets().then(function () {
        const selected = presets.find((p) => p.id === presetSelect.value);
        fillForm(selected || null);
      });
    }

    function closeModal() {
      presetModal.hidden = true;
    }

    manageButton.addEventListener("click", function (event) {
      event.stopPropagation();
      openModal();
    });
    presetClose.addEventListener("click", closeModal);
    presetNew.addEventListener("click", () => fillForm(null));
    presetModal.addEventListener("click", function (event) {
      if (event.target === presetModal) closeModal();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !presetModal.hidden) closeModal();
    });

    pf.logo.addEventListener("change", function () {
      const fileObj = pf.logo.files && pf.logo.files[0];
      if (fileObj) {
        removeLogo = false;
        showPreview(URL.createObjectURL(fileObj));
      }
    });

    pf.logoRemove.addEventListener("click", function () {
      removeLogo = true;
      pf.logo.value = "";
      showPreview("");
    });

    pf.coverEnabled.addEventListener("change", syncCoverFields);
    pf.coverImageSource.addEventListener("change", syncCoverUpload);
    pf.useFallback.addEventListener("change", syncFallbackFields);

    pf.coverImage.addEventListener("change", function () {
      const fileObj = pf.coverImage.files && pf.coverImage.files[0];
      if (fileObj) {
        removeCoverImage = false;
        showCoverPreview(URL.createObjectURL(fileObj));
      }
    });

    pf.coverRemove.addEventListener("click", function () {
      removeCoverImage = true;
      pf.coverImage.value = "";
      showCoverPreview("");
    });

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (!pf.name.value.trim()) {
        pf.status.textContent = t("Name is required");
        pf.status.classList.add("is-error");
        return;
      }
      pf.save.disabled = true;
      pf.status.textContent = t("Saving…");
      pf.status.classList.remove("is-error");
      const fd = new FormData();
      fd.append("id", pf.id.value);
      fd.append("name", pf.name.value.trim());
      fd.append("headerLeft", pf.header.left.value);
      fd.append("headerCenter", pf.header.center.value);
      fd.append("headerRight", pf.header.right.value);
      fd.append("footerLeft", pf.footer.left.value);
      fd.append("footerCenter", pf.footer.center.value);
      fd.append("footerRight", pf.footer.right.value);
      fd.append("logoPosition", pf.logopos.value);
      fd.append("pageSize", pf.pagesize.value);
      fd.append("orientation", pf.orientation.value);
      fd.append("fontScale", pf.fontscale.value || "100");
      fd.append("fontFamily", pf.fontfamily ? pf.fontfamily.value : "");
      fd.append("fileNameTemplate", pf.filename.value);
      fd.append("includeToc", pf.includetoc.checked ? "1" : "0");
      fd.append("includeFrontmatter", pf.includefrontmatter.checked ? "1" : "0");
      fd.append("useFallback", pf.useFallback.checked ? "1" : "0");
      fd.append("fallbackValues", pf.fallbackValues.value);
      fd.append("coverEnabled", pf.coverEnabled.checked ? "1" : "0");
      fd.append("coverTitle", pf.coverTitle.value);
      fd.append("coverSubtitle", pf.coverSubtitle.value);
      fd.append("coverMeta", pf.coverMeta.value);
      fd.append("coverFooter", pf.coverFooter.value);
      fd.append("coverImageSource", pf.coverImageSource.value);
      fd.append("blankAfterCover", pf.blankAfterCover.checked ? "1" : "0");
      if (removeCoverImage) fd.append("removeCoverImage", "1");
      if (pf.coverImage.files && pf.coverImage.files[0]) fd.append("coverImage", pf.coverImage.files[0]);
      fd.append("margin_top", pf.mt.value || "20");
      fd.append("margin_bottom", pf.mb.value || "20");
      fd.append("margin_left", pf.ml.value || "12");
      fd.append("margin_right", pf.mr.value || "12");
      if (removeLogo) fd.append("removeLogo", "1");
      if (pf.logo.files && pf.logo.files[0]) fd.append("logo", pf.logo.files[0]);
      try {
        const res = await fetch("/api/pdf-presets", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || t("Error %(status)s", { status: res.status }));
        await loadPresets();
        presetSelect.value = data.preset.id;
        // An edit here must flow back to the popover. Re-dispatching the
        // select's change handler re-applies the whole preset from the freshly
        // reloaded list — bands *and* the TOC/frontmatter/cover toggles — so a
        // setBand-only sync can't leave those checkboxes stale.
        presetSelect.dispatchEvent(new Event("change"));
        fillForm(data.preset);
        pf.status.textContent = t("Saved");
      } catch (error) {
        pf.status.textContent = error.message || t("Failed");
        pf.status.classList.add("is-error");
      } finally {
        pf.save.disabled = false;
      }
    });

    pf.duplicate.addEventListener("click", async function () {
      if (!pf.id.value) return;
      pf.duplicate.disabled = true;
      pf.status.textContent = t("Duplicating…");
      pf.status.classList.remove("is-error");
      try {
        const res = await fetch("/api/pdf-presets/copy", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: pf.id.value }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || t("Error %(status)s", { status: res.status }));
        await loadPresets();
        // Load the new copy into the form for editing (export selection unchanged).
        fillForm(data.preset);
        pf.status.textContent = t("Duplicated");
      } catch (error) {
        pf.status.textContent = error.message || t("Failed");
        pf.status.classList.add("is-error");
      } finally {
        pf.duplicate.disabled = false;
      }
    });

    pf.del.addEventListener("click", async function () {
      if (!pf.id.value) return;
      if (!window.confirm(t('Delete preset "%(name)s"?', { name: pf.name.value }))) return;
      try {
        const res = await fetch("/api/pdf-presets/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: pf.id.value }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || t("Error %(status)s", { status: res.status }));
        if (presetSelect.value === pf.id.value) {
          presetSelect.value = "";
          presetSelect.dispatchEvent(new Event("change"));
        }
        await loadPresets();
        fillForm(null);
      } catch (error) {
        pf.status.textContent = error.message || t("Failed");
        pf.status.classList.add("is-error");
      }
    });

    loadPresets();
  }

  document.querySelectorAll(".source-recent-remove").forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      const path = button.dataset.path;
      const label = button.dataset.label || path;
      if (button.dataset.kind === "git") {
        const ok = window.confirm(t('Remove "%(label)s" from recents and delete the cached clone?', { label: label }));
        if (!ok) return;
      }
      removeSource(path);
    });
  });

  const tocPanel = document.getElementById("toc-panel");
  if (tocPanel) {
    const tocLinks = new Map();
    tocPanel.querySelectorAll("a[href^='#']").forEach(function (a) {
      tocLinks.set(decodeURIComponent(a.getAttribute("href").slice(1)), a);
    });
    const headings = Array.from(
      document.querySelectorAll(
        ".markdown-body h1[id], .markdown-body h2[id], .markdown-body h3[id], " +
        ".markdown-body h4[id], .markdown-body h5[id], .markdown-body h6[id]"
      )
    );

    // tocDriving / contentDriving guard against the two scroll handlers
    // ping-ponging: while one direction is steering, the other ignores the
    // scroll events its own programmatic scroll generates.
    let tocDriving = false;
    let contentDriving = false;
    let clearTocTimer = null;
    let clearContentTimer = null;

    function updateActiveToc(allowTocScroll) {
      if (!headings.length) return;
      const panelTop = contentPanel.getBoundingClientRect().top;
      let active = headings[0];
      for (const heading of headings) {
        if (heading.getBoundingClientRect().top - panelTop <= 80) {
          active = heading;
        } else {
          break;
        }
      }
      tocLinks.forEach(function (link) {
        link.classList.remove("is-active");
      });
      const activeLink = tocLinks.get(active.id);
      if (activeLink) {
        activeLink.classList.add("is-active");
        if (allowTocScroll &&
            (activeLink.offsetTop < tocPanel.scrollTop ||
             activeLink.offsetTop > tocPanel.scrollTop + tocPanel.clientHeight)) {
          activeLink.scrollIntoView({ block: "nearest" });
        }
      }
    }

    // TOC -> content: align the heading whose TOC entry sits at the top of the
    // TOC viewport to the top of the content pane.
    function syncContentFromToc() {
      if (!headings.length) return;
      // At the TOC's bottom the last entries can't reach the top edge, so map
      // straight to the content bottom to keep the tail reachable.
      if (tocPanel.scrollTop + tocPanel.clientHeight >= tocPanel.scrollHeight - 2) {
        contentPanel.scrollTop = contentPanel.scrollHeight;
        return;
      }
      const tocTop = tocPanel.getBoundingClientRect().top;
      let bestId = null;
      let bestDelta = Infinity;
      tocLinks.forEach(function (link, id) {
        const delta = link.getBoundingClientRect().top - tocTop;
        if (delta >= -4 && delta < bestDelta) {
          bestDelta = delta;
          bestId = id;
        }
      });
      if (bestId === null) return;
      const heading = document.getElementById(bestId);
      if (!heading) return;
      const panelTop = contentPanel.getBoundingClientRect().top;
      contentPanel.scrollTop += heading.getBoundingClientRect().top - panelTop - 12;
    }

    let contentScheduled = false;
    function onContentScroll() {
      if (tocDriving || contentScheduled) return;
      contentScheduled = true;
      requestAnimationFrame(function () {
        contentDriving = true;
        updateActiveToc(true);
        contentScheduled = false;
        clearTimeout(clearContentTimer);
        clearContentTimer = setTimeout(function () { contentDriving = false; }, 100);
      });
    }

    let tocScheduled = false;
    function onTocPanelScroll() {
      if (contentDriving || tocScheduled) return;
      tocScheduled = true;
      requestAnimationFrame(function () {
        tocDriving = true;
        syncContentFromToc();
        updateActiveToc(false);
        tocScheduled = false;
        clearTimeout(clearTocTimer);
        clearTocTimer = setTimeout(function () { tocDriving = false; }, 100);
      });
    }

    contentPanel.addEventListener("scroll", onContentScroll);
    tocPanel.addEventListener("scroll", onTocPanelScroll);
    window.addEventListener("resize", onContentScroll);
    updateActiveToc(true);
  }

  window.addEventListener("beforeunload", function () {
    if (!appShell.classList.contains("is-sidebar-hidden")) {
      localStorage.setItem(sidebarScrollKey, String(sidebar.scrollTop));
    }
    localStorage.setItem(contentScrollKey, String(contentPanel.scrollTop || window.scrollY));
  });

  window.addEventListener("load", function () {
    sidebar.scrollTop = Number(localStorage.getItem(sidebarScrollKey) || 0);
    const savedContentScroll = Number(localStorage.getItem(contentScrollKey) || 0);
    if (window.matchMedia("(max-width: 820px)").matches) {
      window.scrollTo({ top: savedContentScroll, behavior: "auto" });
    } else {
      contentPanel.scrollTop = savedContentScroll;
    }
  });

  if (selectedPath) {
    const watchUrl = `/api/mtime?file=${encodeURIComponent(selectedPath)}`;
    let baseline = null;
    let reloading = false;

    async function pollMtime() {
      if (reloading) return;
      // Pause auto-reload while editing: a live-reload mid-edit would discard the
      // open editor and any unsaved changes. We skip entirely (baseline frozen),
      // so on exit an external change is still detected and reloaded on the next
      // tick. An explicit save reloads on its own.
      if (editActive) return;
      try {
        const res = await fetch(watchUrl, { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (typeof data.mtime !== "number") return;
        if (baseline === null) {
          baseline = data.mtime;
        } else if (data.mtime > baseline) {
          reloading = true;
          setTimeout(() => window.location.reload(), 150);
        }
      } catch (_) {}
    }

    pollMtime();
    setInterval(pollMtime, 1000);
  }
})();
