/**
 * FlowQL Studio - Frontend Application Logic
 * Integrates CodeMirror, compiler backend, Google Gemini AI advisory, and Material 3 UI.
 */

document.addEventListener("DOMContentLoaded", () => {
  // State
  let editor = null;
  let currentTarget = "python";
  let currentArtifacts = null;
  let astViewMode = "tree"; // "tree" or "json"
  let compileDebounceTimer = null;
  let activeErrorMarkers = [];

  // DOM Elements
  const codeEditorEl = document.getElementById("codeEditor");
  const cursorPosEl = document.getElementById("cursorPos");
  const btnCompile = document.getElementById("btnCompile");
  const btnAiReview = document.getElementById("btnAiReview");
  const btnClearEditor = document.getElementById("btnClearEditor");
  const btnThemeToggle = document.getElementById("btnThemeToggle");
  const themeIcon = document.getElementById("themeIcon");
  const exampleSelect = document.getElementById("exampleSelect");
  const segmentBtns = document.querySelectorAll(".segment-btn");

  // Diagnostics DOM
  const diagnosticsCard = document.getElementById("diagnosticsCard");
  const diagnosticsHeader = document.getElementById("diagnosticsHeader");
  const diagnosticsTitle = document.getElementById("diagnosticsTitle");
  const diagnosticsStatusIcon = document.getElementById("diagnosticsStatusIcon");
  const diagnosticsCountBadge = document.getElementById("diagnosticsCountBadge");
  const diagnosticsList = document.getElementById("diagnosticsList");
  const aiExplanationContainer = document.getElementById("aiExplanationContainer");
  const aiCauseText = document.getElementById("aiCauseText");
  const aiSnippetSection = document.getElementById("aiSnippetSection");
  const aiSuggestedCode = document.getElementById("aiSuggestedCode");
  const btnApplyFix = document.getElementById("btnApplyFix");
  const aiTipText = document.getElementById("aiTipText");
  const btnCloseAiExplain = document.getElementById("btnCloseAiExplain");

  // Output DOM
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");
  const emptyState = document.getElementById("emptyState");
  const loadingShimmer = document.getElementById("loadingShimmer");
  const outputCode = document.getElementById("outputCode");
  const btnCopyOutput = document.getElementById("btnCopyOutput");
  const btnDownloadOutput = document.getElementById("btnDownloadOutput");
  const optNotesBanner = document.getElementById("optNotesBanner");
  const optNotesText = document.getElementById("optNotesText");
  const tokensTableBody = document.getElementById("tokensTableBody");
  const astDisplay = document.getElementById("astDisplay");
  const btnToggleAstFormat = document.getElementById("btnToggleAstFormat");
  const irStepsList = document.getElementById("irStepsList");

  // AI Review DOM
  const aiReviewCard = document.getElementById("aiReviewCard");
  const aiReviewVerdict = document.getElementById("aiReviewVerdict");
  const aiReviewTips = document.getElementById("aiReviewTips");
  const btnCloseAiReview = document.getElementById("btnCloseAiReview");

  // Snackbar
  const snackbar = document.getElementById("snackbar");
  const snackbarText = document.getElementById("snackbarMessage");
  const snackbarIcon = document.getElementById("snackbarIcon");
  let snackbarTimeout = null;

  // 1. Initialize CodeMirror Editor
  function initCodeMirror() {
    if (window.CodeMirror) {
      // Define FlowQL Simple Syntax Mode
      if (CodeMirror.defineSimpleMode) {
        CodeMirror.defineSimpleMode("flowql", {
          start: [
            { regex: /#(.*)/, token: "comment" },
            { regex: /"(?:[^\\]|\\.)*?(?:"|$)/, token: "string" },
            {
              regex: /\b(dataset|load|let|print|filter|select|group|sort|asc|desc|limit|and|or|not|true|false|sum|avg|min|max|count)\b/,
              token: "keyword"
            },
            { regex: /\b(num|str|bool)\b/, token: "type" },
            { regex: /0x[a-f\d]+|[-+]?(?:\.\d+|\d+\.?\d*)(?:e[-+]?\d+)?/i, token: "number" },
            { regex: /==|!=|<=|>=|<|>|=|\+|-|\*|\/|%|\|/, token: "operator" },
            { regex: /[a-zA-Z_][a-zA-Z0-9_]*/, token: "variable" }
          ]
        });
      }

      editor = CodeMirror.fromTextArea(codeEditorEl, {
        lineNumbers: true,
        mode: "flowql",
        gutters: ["CodeMirror-linenumbers", "breakpoints"],
        lineWrapping: true,
        tabSize: 4,
        indentUnit: 4
      });

      // Cursor position updates
      editor.on("cursorActivity", () => {
        const pos = editor.getCursor();
        cursorPosEl.textContent = `Ln ${pos.line + 1}, Col ${pos.ch + 1}`;
      });

      // Auto-compile debounce (~600ms)
      editor.on("change", () => {
        clearTimeout(compileDebounceTimer);
        compileDebounceTimer = setTimeout(() => {
          compile(false);
        }, 600);
      });
    } else {
      // Fallback plain textarea
      codeEditorEl.addEventListener("input", () => {
        clearTimeout(compileDebounceTimer);
        compileDebounceTimer = setTimeout(() => {
          compile(false);
        }, 600);
      });
    }
  }

  function getEditorCode() {
    return editor ? editor.getValue() : codeEditorEl.value;
  }

  function setEditorCode(val) {
    if (editor) {
      editor.setValue(val);
    } else {
      codeEditorEl.value = val;
    }
  }

  // 2. Theme Management (Light/Dark)
  function initTheme() {
    const saved = localStorage.getItem("flowql_theme");
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = saved ? saved === "dark" : prefersDark;

    if (isDark) {
      document.body.classList.add("dark-theme");
      themeIcon.textContent = "light_mode";
    } else {
      document.body.classList.remove("dark-theme");
      themeIcon.textContent = "dark_mode";
    }
  }

  btnThemeToggle.addEventListener("click", () => {
    document.body.classList.toggle("dark-theme");
    const isDark = document.body.classList.contains("dark-theme");
    themeIcon.textContent = isDark ? "light_mode" : "dark_mode";
    localStorage.setItem("flowql_theme", isDark ? "dark" : "light");
    showSnackbar(isDark ? "Switched to Dark Theme" : "Switched to Light Theme", "palette");
  });

  // 3. Snackbar Notification
  function showSnackbar(message, icon = "check_circle", duration = 2500) {
    clearTimeout(snackbarTimeout);
    snackbarText.textContent = message;
    snackbarIcon.textContent = icon;
    snackbar.classList.add("visible");
    snackbarTimeout = setTimeout(() => {
      snackbar.classList.remove("visible");
    }, duration);
  }

  // 4. Ripple Effect
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn, .segment-btn");
    if (!btn) return;
    const circle = document.createElement("span");
    const diameter = Math.max(btn.clientWidth, btn.clientHeight);
    const radius = diameter / 2;
    const rect = btn.getBoundingClientRect();
    circle.style.width = circle.style.height = `${diameter}px`;
    circle.style.left = `${e.clientX - rect.left - radius}px`;
    circle.style.top = `${e.clientY - rect.top - radius}px`;
    circle.classList.add("ripple");
    const existing = btn.querySelector(".ripple");
    if (existing) existing.remove();
    btn.appendChild(circle);
  });

  // 5. Target Selector (Segmented Button)
  segmentBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      segmentBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentTarget = btn.dataset.target;
      compile(false);
      showSnackbar(`Target set to ${currentTarget === "python" ? "Python (pandas)" : "SQL (CTEs)"}`, "tune");
    });
  });

  // 6. Tabs Management
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.dataset.tab;
      tabBtns.forEach((b) => b.classList.remove("active"));
      tabPanes.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(targetTab).classList.add("active");
    });
  });

  // 7. Load Built-in Examples
  async function loadExamples() {
    try {
      const res = await fetch("/api/examples");
      if (!res.ok) return;
      const data = await res.json();
      const examples = data.examples || [];

      exampleSelect.innerHTML = `<option value="" disabled selected>Select an Example Program...</option>`;
      const groups = {};
      examples.forEach((ex) => {
        if (!groups[ex.category]) groups[ex.category] = [];
        groups[ex.category].push(ex);
      });

      for (const [cat, items] of Object.entries(groups)) {
        const optgroup = document.createElement("optgroup");
        optgroup.label = cat;
        items.forEach((item) => {
          const opt = document.createElement("option");
          opt.value = item.id;
          opt.textContent = item.name;
          opt.dataset.code = item.code;
          optgroup.appendChild(opt);
        });
        exampleSelect.appendChild(optgroup);
      }

      // Default load first valid example
      const defaultEx = examples.find((e) => e.id === "top_regions") || examples[0];
      if (defaultEx) {
        setEditorCode(defaultEx.code);
        compile(false);
      }
    } catch (e) {
      console.warn("Failed to fetch examples:", e);
    }
  }

  exampleSelect.addEventListener("change", (e) => {
    const selected = exampleSelect.options[exampleSelect.selectedIndex];
    if (selected && selected.dataset.code) {
      setEditorCode(selected.dataset.code);
      compile(true);
      showSnackbar(`Loaded: ${selected.textContent}`, "folder_open");
    }
  });

  // 8. Editor Error Highlighting
  function clearEditorErrors() {
    if (!editor) return;
    activeErrorMarkers.forEach((m) => m.clear && m.clear());
    activeErrorMarkers = [];
    editor.clearGutter("breakpoints");
    for (let i = 0; i < editor.lineCount(); i++) {
      editor.removeLineClass(i, "background", "cm-error-line");
    }
  }

  function highlightEditorErrors(errors) {
    if (!editor) return;
    clearEditorErrors();

    errors.forEach((err) => {
      const lineIdx = Math.max(0, (err.line || 1) - 1);
      editor.addLineClass(lineIdx, "background", "cm-error-line");

      // Gutter marker dot
      const marker = document.createElement("div");
      marker.className = "gutter-error-marker";
      marker.innerHTML = "●";
      marker.title = `[${err.code}] ${err.message}`;
      marker.onclick = () => jumpToLine(err.line, err.column);
      editor.setGutterMarker(lineIdx, "breakpoints", marker);

      // Underline token
      const colIdx = Math.max(0, (err.column || 1) - 1);
      const textMarker = editor.markText(
        { line: lineIdx, ch: colIdx },
        { line: lineIdx, ch: colIdx + 10 },
        {
          className: "cm-error-underline",
          attributes: { title: `[${err.code}] ${err.message}` }
        }
      );
      activeErrorMarkers.push(textMarker);
    });
  }

  function jumpToLine(line, col) {
    if (!editor) return;
    const l = Math.max(0, (line || 1) - 1);
    const c = Math.max(0, (col || 1) - 1);
    editor.setCursor({ line: l, ch: c });
    if (editor.scrollIntoView) {
      editor.scrollIntoView({ line: l, ch: c }, 40);
    }
    editor.focus();
  }

  // 9. Diagnostics Panel Update
  function updateDiagnostics(errors) {
    diagnosticsList.innerHTML = "";
    aiExplanationContainer.classList.add("hidden");

    if (!errors || errors.length === 0) {
      diagnosticsCard.classList.remove("has-errors");
      diagnosticsStatusIcon.textContent = "check_circle";
      diagnosticsTitle.textContent = "Diagnostics: Clean";
      diagnosticsCountBadge.textContent = "0 Errors";
      diagnosticsCountBadge.className = "badge badge-success";
      clearEditorErrors();
      return;
    }

    diagnosticsCard.classList.add("has-errors");
    diagnosticsStatusIcon.textContent = "error";
    diagnosticsTitle.textContent = `Diagnostics: ${errors.length} Issue${errors.length > 1 ? "s" : ""}`;
    diagnosticsCountBadge.textContent = `${errors.length} Error${errors.length > 1 ? "s" : ""}`;
    diagnosticsCountBadge.className = "badge badge-error";

    highlightEditorErrors(errors);

    errors.forEach((err) => {
      const row = document.createElement("div");
      row.className = "error-row";

      row.innerHTML = `
        <div class="error-row-left">
          <span class="error-chip">${escapeHtml(err.code)}</span>
          <span class="error-message" title="${escapeHtml(err.message)}">${escapeHtml(err.message)}</span>
        </div>
        <div class="error-row-right">
          <span class="error-loc-badge">Ln ${err.line}, Col ${err.column}</span>
          <button class="btn-ai-explain" title="Ask Google Gemini for explanation and fix">
            <span class="material-symbols-outlined" style="font-size: 15px;">psychology</span>
            <span>Explain with AI</span>
          </button>
        </div>
      `;

      // Jump to line on row click (excluding the Explain button)
      row.addEventListener("click", (e) => {
        if (!e.target.closest(".btn-ai-explain")) {
          jumpToLine(err.line, err.column);
        }
      });

      // Explain with AI trigger
      const btnExplain = row.querySelector(".btn-ai-explain");
      btnExplain.addEventListener("click", (e) => {
        e.stopPropagation();
        requestAiExplanation(err);
      });

      diagnosticsList.appendChild(row);
    });
  }

  diagnosticsHeader.addEventListener("click", () => {
    diagnosticsCard.classList.toggle("collapsed");
  });

  // 10. AI Error Explanation
  async function requestAiExplanation(err) {
    aiExplanationContainer.classList.remove("hidden");
    aiCauseText.textContent = "Analyzing error with Google Gemini...";
    aiSnippetSection.classList.add("hidden");
    aiTipText.textContent = "Please wait a moment...";

    try {
      const res = await fetch("/api/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          error: err,
          source: getEditorCode()
        })
      });

      const data = await res.json();
      aiCauseText.textContent = data.cause || "No cause provided.";
      aiTipText.textContent = data.tip || "Review syntax rules.";

      if (data.suggested_code) {
        aiSnippetSection.classList.remove("hidden");
        aiSuggestedCode.textContent = data.suggested_code;
        btnApplyFix.onclick = () => {
          let suggested = (data.suggested_code || "").trim();
          if (!suggested) return;

          // Strip any markdown code fences if Gemini formatted it as ```...```
          if (suggested.startsWith("```")) {
            suggested = suggested.replace(/^```[a-zA-Z]*\r?\n?/, "").replace(/\r?\n?```$/, "").trim();
          }

          // Case 1: Suggested code is a full program
          if (suggested.includes("dataset ") || suggested.includes("load ") || suggested.split("\n").length > 3) {
            setEditorCode(suggested);
          } 
          // Case 2: CodeMirror is active and we have an error line number
          else if (editor && typeof err.line === "number" && err.line > 0) {
            const lineIndex = Math.max(0, err.line - 1);
            if (lineIndex < editor.lineCount()) {
              const currentLineLength = editor.getLine(lineIndex).length;
              editor.replaceRange(
                suggested,
                { line: lineIndex, ch: 0 },
                { line: lineIndex, ch: currentLineLength }
              );
            } else {
              setEditorCode(suggested);
            }
          } 
          // Case 3: Fallback textarea or single line replacement
          else {
            const currentFull = getEditorCode();
            const lines = currentFull.split("\n");
            const lineIndex = Math.max(0, (err.line || 1) - 1);
            if (lineIndex < lines.length) {
              lines[lineIndex] = suggested;
              setEditorCode(lines.join("\n"));
            } else {
              setEditorCode(suggested);
            }
          }

          compile(true);
          showSnackbar("Applied suggested fix to editor", "auto_fix_high");
        };
      } else {
        aiSnippetSection.classList.add("hidden");
      }
    } catch (e) {
      aiCauseText.textContent = "AI hints unavailable: could not contact server.";
      aiTipText.textContent = "Compiler deterministic checks succeeded.";
    }
  }

  btnCloseAiExplain.addEventListener("click", () => {
    aiExplanationContainer.classList.add("hidden");
  });

  // 11. AI Code Review
  btnAiReview.addEventListener("click", async () => {
    const code = getEditorCode();
    if (!currentArtifacts || !currentArtifacts.target_code) {
      showSnackbar("Please compile a valid pipeline first", "info");
      return;
    }

    aiReviewCard.classList.remove("hidden");
    aiReviewVerdict.textContent = "Requesting Gemini review...";
    aiReviewTips.innerHTML = "<li>Analyzing pipeline structure...</li>";
    // Switch to output tab
    document.querySelector('.tab-btn[data-tab="tab-output"]').click();

    try {
      const res = await fetch("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: code,
          target_code: currentArtifacts.target_code,
          target_name: currentTarget.toUpperCase()
        })
      });
      if (!res.ok) {
        throw new Error(`Server returned status ${res.status}`);
      }
      const data = await res.json();
      aiReviewVerdict.textContent = data.verdict || "Review complete.";
      aiReviewTips.innerHTML = "";
      const tipsList = Array.isArray(data.tips) ? data.tips : [data.tips || "No specific tips."];
      tipsList.forEach((tip) => {
        const li = document.createElement("li");
        li.textContent = tip;
        aiReviewTips.appendChild(li);
      });
      if (data.available) {
        showSnackbar("AI Code Review completed", "auto_awesome");
      } else {
        showSnackbar("AI review unavailable", "info");
      }
    } catch (e) {
      aiReviewVerdict.textContent = "Could not reach FlowQL server.";
      aiReviewTips.innerHTML = "<li>Make sure the server is running (<code>uvicorn server:app --reload</code>).</li><li>Check your connection to localhost:8000.</li>";
    }
  });

  btnCloseAiReview.addEventListener("click", () => {
    aiReviewCard.classList.add("hidden");
  });

  // 12. Main Compiler Execution
  async function compile(showToast = true) {
    const source = getEditorCode().trim();
    if (!source) {
      emptyState.classList.remove("hidden");
      outputCode.textContent = "";
      updateDiagnostics([]);
      return;
    }

    emptyState.classList.add("hidden");
    loadingShimmer.classList.remove("hidden");

    try {
      const res = await fetch("/api/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: source,
          target: currentTarget,
          optimize: true
        })
      });

      const data = await res.json();
      currentArtifacts = data;

      // Update Diagnostics
      updateDiagnostics(data.errors || []);

      // Output Code
      if (data.target_code) {
        outputCode.textContent = data.target_code;
      } else {
        outputCode.textContent = data.errors && data.errors.length > 0 
          ? `# Compilation failed with ${data.errors.length} error(s).\n# See diagnostics panel on the left for details.` 
          : "# No target code generated.";
      }

      // Optimization Notes
      if (data.optimizations && data.optimizations.length > 0) {
        optNotesBanner.classList.remove("hidden");
        optNotesText.textContent = `Optimizations applied: ${data.optimizations.join(" | ")}`;
      } else {
        optNotesBanner.classList.add("hidden");
      }

      // Tokens View
      renderTokens(data.tokens || []);

      // AST View
      renderAst(data);

      // IR View
      renderIr(data.ir || []);

      if (showToast) {
        if (data.success) {
          showSnackbar("Compiled successfully", "check_circle");
        } else {
          showSnackbar(`Compilation failed (${data.errors.length} error${data.errors.length > 1 ? "s" : ""})`, "error");
        }
      }
    } catch (e) {
      console.error(e);
      showSnackbar("Compiler error: could not connect to server", "error");
    } finally {
      loadingShimmer.classList.add("hidden");
    }
  }

  // 13. Render Artifact Tabs
  function renderTokens(tokens) {
    tokensTableBody.innerHTML = "";
    tokens.forEach((t, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td><span class="token-chip">${escapeHtml(t.type)}</span></td>
        <td>${escapeHtml(t.value)}</td>
        <td>${t.line}</td>
        <td>${t.column}</td>
      `;
      tokensTableBody.appendChild(tr);
    });
  }

  function renderAst(data) {
    if (astViewMode === "tree") {
      astDisplay.textContent = data.ast_tree || "No AST available.";
      btnToggleAstFormat.textContent = "Switch to JSON";
    } else {
      astDisplay.textContent = data.ast ? JSON.stringify(data.ast, null, 2) : "No AST available.";
      btnToggleAstFormat.textContent = "Switch to Indented Tree";
    }
  }

  btnToggleAstFormat.addEventListener("click", () => {
    astViewMode = astViewMode === "tree" ? "json" : "tree";
    if (currentArtifacts) renderAst(currentArtifacts);
  });

  function renderIr(steps) {
    irStepsList.innerHTML = "";
    if (!steps || steps.length === 0) {
      irStepsList.innerHTML = `<p style="color: var(--md-text-secondary); font-size: 13px;">No IR steps available.</p>`;
      return;
    }

    steps.forEach((s) => {
      const card = document.createElement("div");
      card.className = "ir-step-card";

      const opClass = `op-${s.op.toLowerCase()}`;
      card.innerHTML = `
        <div class="ir-step-num">${s.step_id}</div>
        <div class="ir-op-chip ${opClass}">${escapeHtml(s.op)}</div>
        <div class="ir-step-details">
          <div class="ir-step-desc">${escapeHtml(s.comment || s.op)}</div>
          <div class="ir-step-tables">Input: ${escapeHtml(s.input || "—")} → Output: ${escapeHtml(s.output || "—")}</div>
        </div>
      `;
      irStepsList.appendChild(card);
    });
  }

  // 14. Action Buttons (Copy / Download / Clear)
  btnCopyOutput.addEventListener("click", () => {
    const code = outputCode.textContent;
    if (!code) return;
    navigator.clipboard.writeText(code).then(() => {
      showSnackbar("Copied output code to clipboard", "content_copy");
    });
  });

  btnDownloadOutput.addEventListener("click", () => {
    const code = outputCode.textContent;
    if (!code) return;
    const ext = currentTarget === "sql" ? "sql" : "py";
    const filename = `pipeline_output.${ext}`;
    const blob = new Blob([code], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    showSnackbar(`Downloaded ${filename}`, "download");
  });

  btnClearEditor.addEventListener("click", () => {
    setEditorCode("");
    outputCode.textContent = "";
    currentArtifacts = null;
    clearEditorErrors();
    updateDiagnostics([]);
    emptyState.classList.remove("hidden");
    showSnackbar("Editor cleared", "delete_outline");
  });

  btnCompile.addEventListener("click", () => compile(true));

  // Keyboard shortcut: Ctrl+Enter / Cmd+Enter to compile
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      compile(true);
    }
  });

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Initial Boot
  initTheme();
  initCodeMirror();
  loadExamples();
});
