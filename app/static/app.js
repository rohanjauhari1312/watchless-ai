const app = document.getElementById("app");
let state = { cameras: [], activeCamera: null, tab: "frames", highlightTs: null };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    body: opts.body instanceof FormData ? opts.body : opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

async function boot() {
  await loadCameras();
  renderDashboard();
}

async function loadCameras() {
  state.cameras = await api("/api/cameras");
}

function renderDashboard() {
  state.activeCamera = null;
  app.innerHTML = `
    <div class="top-bar">
      <h1>WatchlessAI</h1>
    </div>

    <div class="panel">
      <h2>Add a camera</h2>
      <div class="row" style="margin-bottom:10px;">
        <input id="camName" placeholder="Camera name (e.g. Front door)" style="flex:1;">
      </div>
      <div class="row">
        <input id="camRtsp" placeholder="rtsp:// stream URL" style="flex:1;">
        <button id="addRtspBtn">Add live stream</button>
      </div>
      <div class="row" style="margin-top:8px;">
        <input id="camFile" type="file" accept="video/*" style="flex:1;">
        <button id="addFileBtn">Upload clip</button>
      </div>
      <div class="error hidden" id="camError"></div>
    </div>

    <div class="panel">
      <h2>Cameras</h2>
      <div id="cameraList"></div>
    </div>
  `;

  document.getElementById("addRtspBtn").onclick = async () => {
    const name = document.getElementById("camName").value.trim();
    const rtsp_url = document.getElementById("camRtsp").value.trim();
    const errEl = document.getElementById("camError");
    errEl.classList.add("hidden");
    if (!name || !rtsp_url) { errEl.textContent = "Name and RTSP URL required."; errEl.classList.remove("hidden"); return; }
    try {
      await api("/api/cameras", { method: "POST", body: { name, rtsp_url } });
      await loadCameras();
      renderDashboard();
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.remove("hidden");
    }
  };

  document.getElementById("addFileBtn").onclick = async () => {
    const name = document.getElementById("camName").value.trim();
    const fileInput = document.getElementById("camFile");
    const errEl = document.getElementById("camError");
    errEl.classList.add("hidden");
    if (!name || !fileInput.files[0]) { errEl.textContent = "Name and a video file required."; errEl.classList.remove("hidden"); return; }
    const formData = new FormData();
    formData.append("name", name);
    formData.append("file", fileInput.files[0]);
    try {
      const cam = await api("/api/cameras/upload", { method: "POST", body: formData });
      await api(`/api/cameras/${cam.id}/start`, { method: "POST" });
      await loadCameras();
      state.activeCamera = state.cameras.find(c => c.id === cam.id);
      state.tab = "chat";
      await renderCamera();
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.remove("hidden");
    }
  };

  const list = document.getElementById("cameraList");
  if (state.cameras.length === 0) {
    list.innerHTML = `<div class="muted">No cameras yet.</div>`;
  } else {
    list.innerHTML = state.cameras.map(c => `
      <div class="card">
        <div>
          <div style="font-weight:500;">${escapeHtml(c.name)}</div>
          <div class="muted">${escapeHtml(c.source)}</div>
        </div>
        <div class="row">
          <span class="pill ${c.active ? "live" : ""}">${c.active ? "monitoring" : "stopped"}</span>
          <button class="secondary" data-open="${c.id}">Open</button>
        </div>
      </div>
    `).join("");
    list.querySelectorAll("[data-open]").forEach(btn => {
      btn.onclick = () => openCamera(parseInt(btn.dataset.open));
    });
  }
}

async function openCamera(id) {
  state.activeCamera = state.cameras.find(c => c.id === id);
  state.tab = "frames";
  await renderCamera();
}

async function renderCamera() {
  const c = state.activeCamera;
  app.innerHTML = `
    <span class="back" id="backBtn">&larr; Cameras</span>
    <div class="top-bar">
      <h1>${escapeHtml(c.name)}</h1>
      <div class="row">
        <span class="pill ${c.active ? "live" : ""}" id="statusPill">${c.active ? "monitoring" : "stopped"}</span>
        <button id="toggleBtn" class="${c.active ? "danger" : ""}">${c.active ? "Stop" : "Start"}</button>
      </div>
    </div>
    <div class="tabs">
      <button data-tab="frames" class="${state.tab === "frames" ? "active" : ""}">Frames</button>
      <button data-tab="alerts" class="${state.tab === "alerts" ? "active" : ""}">Alerts</button>
      <button data-tab="chat" class="${state.tab === "chat" ? "active" : ""}">Ask</button>
    </div>
    <div id="tabContent"></div>
  `;
  document.getElementById("backBtn").onclick = renderDashboard;
  document.getElementById("toggleBtn").onclick = async () => {
    const c2 = state.activeCamera;
    await api(`/api/cameras/${c2.id}/${c2.active ? "stop" : "start"}`, { method: "POST" });
    await loadCameras();
    state.activeCamera = state.cameras.find(x => x.id === c2.id);
    renderCamera();
  };
  app.querySelectorAll("[data-tab]").forEach(btn => {
    btn.onclick = () => { state.tab = btn.dataset.tab; renderCamera(); };
  });

  const content = document.getElementById("tabContent");
  if (state.tab === "frames") await renderFramesTab(content);
  if (state.tab === "alerts") await renderAlertsTab(content);
  if (state.tab === "chat") renderChatTab(content);
}

async function renderFramesTab(content) {
  content.innerHTML = `
    <div class="panel">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h2 style="margin:0;">Recent frames</h2>
        <button class="danger" id="clearFramesBtn">Clear all</button>
      </div>
      <div id="frameList" class="muted">Loading...</div>
    </div>
  `;
  document.getElementById("clearFramesBtn").onclick = async () => {
    if (!confirm("Delete all frames for this camera? This cannot be undone.")) return;
    await api(`/api/cameras/${state.activeCamera.id}/frames`, { method: "DELETE" });
    await renderFramesTab(content);
  };

  const frames = await api(`/api/cameras/${state.activeCamera.id}/frames`);
  const listEl = document.getElementById("frameList");
  if (frames.length === 0) {
    listEl.innerHTML = `<div class="muted">No frames captured yet. Start the camera to begin sampling.</div>`;
    return;
  }
  listEl.innerHTML = frames.map(f => `
    <div class="frame-item">
      <img src="/api/frames/${f.id}/image" loading="lazy">
      <div style="flex:1;">
        <div class="muted">${new Date(f.timestamp).toLocaleString()}</div>
        <div>${escapeHtml(f.summary || "")}</div>
      </div>
      <button class="secondary" data-del-frame="${f.id}">Delete</button>
    </div>
  `).join("");
  listEl.querySelectorAll("[data-del-frame]").forEach(btn => {
    btn.onclick = async () => {
      await api(`/api/frames/${btn.dataset.delFrame}`, { method: "DELETE" });
      await renderFramesTab(content);
    };
  });
}

async function renderAlertsTab(content) {
  content.innerHTML = `
    <div class="panel">
      <h2>Alert conditions</h2>
      <div class="row" style="margin-bottom:8px;">
        <input id="alertInput" placeholder="e.g. a package is left at the front door" style="flex:1;">
        <button id="addAlertBtn">Add</button>
      </div>
      <label class="row muted" style="align-items:center;gap:6px;margin-bottom:12px;cursor:pointer;">
        <input type="checkbox" id="alertAgentic" style="width:auto;">
        Agentic — checks recent history before alerting, avoids repeat alerts for the same ongoing situation
      </label>
      <button class="secondary" id="addSuspiciousBtn" style="margin-bottom:12px;">+ Suspicious activity (agentic preset)</button>
      <div id="alertList" class="muted">Loading...</div>
    </div>
    <div class="panel">
      <h2>Triggered events</h2>
      <div id="eventList" class="muted">Loading...</div>
    </div>
  `;
  document.getElementById("addAlertBtn").onclick = async () => {
    const val = document.getElementById("alertInput").value.trim();
    if (!val) return;
    const is_agentic = document.getElementById("alertAgentic").checked;
    await api(`/api/cameras/${state.activeCamera.id}/alerts`, { method: "POST", body: { condition_text: val, is_agentic } });
    await renderAlertsTab(content);
  };
  document.getElementById("addSuspiciousBtn").onclick = async () => {
    await api(`/api/cameras/${state.activeCamera.id}/alerts`, {
      method: "POST",
      body: { condition_text: "suspicious activity — anything that looks like an intrusion, concealment, or unusual behavior for this space", is_agentic: true },
    });
    await renderAlertsTab(content);
  };

  const [alerts, events] = await Promise.all([
    api(`/api/cameras/${state.activeCamera.id}/alerts`),
    api(`/api/cameras/${state.activeCamera.id}/alert-events`),
  ]);

  const alertList = document.getElementById("alertList");
  alertList.innerHTML = alerts.length === 0
    ? `<div class="muted">No alerts configured.</div>`
    : alerts.map(a => `
      <div class="card">
        <div>${escapeHtml(a.condition_text)} ${a.is_agentic ? '<span class="pill">agentic</span>' : ""}</div>
        <button class="danger" data-del-alert="${a.id}">Remove</button>
      </div>
    `).join("");
  alertList.querySelectorAll("[data-del-alert]").forEach(btn => {
    btn.onclick = async () => {
      await api(`/api/alerts/${btn.dataset.delAlert}`, { method: "DELETE" });
      await renderAlertsTab(content);
    };
  });

  const eventList = document.getElementById("eventList");
  eventList.innerHTML = events.length === 0
    ? `<div class="muted">No alerts triggered yet.</div>`
    : events.map(e => `
      <div class="frame-item">
        <div>
          <div class="muted">${new Date(e.triggered_at).toLocaleString()}</div>
          <div><strong>${escapeHtml(e.condition_text)}</strong> — ${escapeHtml(e.reason || "")}</div>
        </div>
      </div>
    `).join("");
}

function renderChatTab(content) {
  content.innerHTML = `
    <div class="panel">
      <h2>Ask about this camera's footage</h2>
      <div id="chatLog" class="chat-log"></div>
      <div class="row">
        <input id="chatInput" placeholder="e.g. how long did the child study?" style="flex:1;">
        <button id="chatSendBtn">Ask</button>
      </div>
    </div>
  `;
  const log = document.getElementById("chatLog");
  log.addEventListener("click", (e) => {
    const btn = e.target.closest(".ts-link");
    if (btn) jumpToTimestamp(btn.dataset.ts);
  });
  const input = document.getElementById("chatInput");
  const send = async () => {
    const question = input.value.trim();
    if (!question) return;
    log.innerHTML += `<div class="chat-msg user">${escapeHtml(question)}</div>`;
    input.value = "";
    log.scrollTop = log.scrollHeight;
    const thinkingId = "thinking-" + Date.now();
    log.innerHTML += `<div class="chat-msg assistant muted" id="${thinkingId}">Thinking...</div>`;
    log.scrollTop = log.scrollHeight;
    try {
      const res = await api(`/api/cameras/${state.activeCamera.id}/chat`, { method: "POST", body: { question } });
      document.getElementById(thinkingId).outerHTML = `<div class="chat-msg assistant">${renderMarkdown(res.answer)}</div>`;
    } catch (e) {
      document.getElementById(thinkingId).outerHTML = `<div class="chat-msg assistant error">${escapeHtml(e.message)}</div>`;
    }
    log.scrollTop = log.scrollHeight;
  };
  document.getElementById("chatSendBtn").onclick = send;
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function renderMarkdown(str) {
  const lines = (str ?? "").split("\n");
  const htmlBlocks = [];
  let listBuffer = [];

  const flushList = () => {
    if (listBuffer.length) {
      htmlBlocks.push(`<ul>${listBuffer.join("")}</ul>`);
      listBuffer = [];
    }
  };

  const inline = (line) => escapeHtml(line)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<![*\w])\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "<em>$1</em>")
    .replace(/\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\b/g, '<button class="ts-link" data-ts="$1">$1</button>');

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) { flushList(); continue; }

    const bullet = line.match(/^[-*]\s+(.*)/);
    if (bullet) { listBuffer.push(`<li>${inline(bullet[1])}</li>`); continue; }

    flushList();
    const heading = line.match(/^#{1,3}\s+(.*)/);
    if (heading) { htmlBlocks.push(`<div class="chat-heading">${inline(heading[1])}</div>`); continue; }

    htmlBlocks.push(`<p>${inline(line)}</p>`);
  }
  flushList();
  return htmlBlocks.join("");
}

async function jumpToTimestamp(isoTs) {
  const frames = await api(`/api/cameras/${state.activeCamera.id}/frames`);
  const target = new Date(isoTs).getTime();
  let closest = null, minDiff = Infinity;
  for (const f of frames) {
    const diff = Math.abs(new Date(f.timestamp).getTime() - target);
    if (diff < minDiff) { minDiff = diff; closest = f; }
  }
  if (closest) showFrameModal(closest);
}

function showFrameModal(frame) {
  let modal = document.getElementById("frameModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "frameModal";
    modal.className = "frame-modal hidden";
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div class="frame-modal-inner">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:12px;">
        <span class="muted">${new Date(frame.timestamp).toLocaleString()}</span>
        <button class="secondary" id="closeFrameModal">Close</button>
      </div>
      <img src="/api/frames/${frame.id}/image">
      <div style="font-size:14px;">${escapeHtml(frame.summary || "")}</div>
    </div>
  `;
  modal.classList.remove("hidden");
  document.getElementById("closeFrameModal").onclick = () => modal.classList.add("hidden");
  modal.onclick = (e) => { if (e.target === modal) modal.classList.add("hidden"); };
}

boot();
