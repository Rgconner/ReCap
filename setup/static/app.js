const TOKEN_KEY = 'recap_setup_token';

let currentCameras = [];
let currentConfig = null;

function getToken() {
    return sessionStorage.getItem(TOKEN_KEY) || '';
}

function setToken(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
}

function setStatus(message, isError = false, targetId = 'statusMsg') {
    const el = document.getElementById(targetId);
    el.textContent = message;
    el.className = isError ? 'text-sm text-red-400 mt-2' : 'text-sm text-gray-500 mt-2';
}

/** Wraps a click handler so no failure — HTTP error, thrown exception,
 * anything — can ever leave the button looking like it did nothing. */
function withStatus(fn) {
    return async (...args) => {
        try {
            await fn(...args);
        } catch (err) {
            console.error(err);
            setStatus(`Unexpected error: ${err && err.message ? err.message : err}`, true);
        }
    };
}

async function apiFetch(path, opts = {}) {
    const headers = Object.assign({}, opts.headers, { 'X-Setup-Token': getToken() });
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    if (res.status === 401) {
        setStatus('Invalid or missing token — check the Setup Token field.', true);
    }
    return res;
}

async function errorDetail(res) {
    try {
        const body = await res.json();
        if (typeof body.detail === 'string') {
            return body.detail;
        }
        if (Array.isArray(body.detail)) {
            // FastAPI/Pydantic validation-error shape: a list of {msg, loc, ...}
            // objects, not a string — stringifying the array directly would
            // render as "[object Object]".
            return body.detail.map((e) => e.msg || JSON.stringify(e)).join('; ');
        }
        return body.detail !== undefined ? JSON.stringify(body.detail) : res.status;
    } catch {
        return res.status;
    }
}

// --- ROI overlay ---

const ROI_COLORS = ['#fa4d56', '#42be65', '#4589ff', '#ff832b', '#d12771', '#a56eff', '#08bdba', '#ee5396'];
// Distinct from ROI_COLORS and from the physical yellow markers themselves,
// so the overlay's idea of a marker position never gets mistaken for the
// real yellow dot it's supposed to line up with.
const MARKER_COLOR = '#ffffff';
const MARKER_RADIUS_DIVISOR = 60;

/** Repositions the overlay canvas to exactly cover the rendered <img> box
 * (which can be smaller than its container, and resizes with the viewport
 * since it's max-w-full/max-h-full) and redraws the ROIs on it. */
function positionRoiOverlay() {
    const img = document.getElementById('snapshotImg');
    const canvas = document.getElementById('roiOverlay');
    if (img.classList.contains('hidden') || !img.naturalWidth) {
        canvas.classList.add('hidden');
        return;
    }
    canvas.style.left = `${img.offsetLeft}px`;
    canvas.style.top = `${img.offsetTop}px`;
    canvas.style.width = `${img.clientWidth}px`;
    canvas.style.height = `${img.clientHeight}px`;
    // Drawing buffer matches the frame's real resolution, so ROI rects can be
    // drawn straight from their raw pixel coordinates — the CSS size above
    // handles display scaling the same way the <img> itself scales.
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    canvas.classList.remove('hidden');
    drawRoiOverlay();
}

function drawRoiOverlay() {
    const canvas = document.getElementById('roiOverlay');
    if (canvas.classList.contains('hidden')) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const lineWidth = Math.max(2, canvas.width / 400);
    const fontSize = Math.max(14, canvas.width / 60);
    ctx.font = `${fontSize}px sans-serif`;
    ctx.lineJoin = 'round';
    roiRowsFromDom().forEach((roi, i) => {
        if (!roi.id) return;
        const color = ROI_COLORS[i % ROI_COLORS.length];
        const w = roi.x2 - roi.x1;
        const h = roi.y2 - roi.y1;
        const labelX = roi.x1 + lineWidth;
        const labelY = roi.y1 + fontSize;

        // Dark halo first (wider stroke/text) so the colored line and label
        // stay legible over bright, glare-heavy regions of the frame, not
        // just the darker ones.
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.85)';
        ctx.lineWidth = lineWidth + 3;
        ctx.strokeRect(roi.x1, roi.y1, w, h);
        ctx.lineWidth = fontSize / 4;
        ctx.strokeText(roi.id, labelX, labelY);

        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.strokeRect(roi.x1, roi.y1, w, h);
        ctx.fillStyle = color;
        ctx.fillText(roi.id, labelX, labelY);
    });

    const radius = Math.max(6, canvas.width / MARKER_RADIUS_DIVISOR);
    alignmentMarkersFromDom().forEach((marker) => {
        if (!marker.id) return;
        const labelX = marker.x + radius + 4;
        const labelY = marker.y + fontSize / 3;

        ctx.strokeStyle = 'rgba(0, 0, 0, 0.85)';
        ctx.lineWidth = lineWidth + 3;
        drawCrosshair(ctx, marker.x, marker.y, radius);
        ctx.lineWidth = fontSize / 4;
        ctx.strokeText(marker.id, labelX, labelY);

        ctx.strokeStyle = MARKER_COLOR;
        ctx.lineWidth = lineWidth;
        drawCrosshair(ctx, marker.x, marker.y, radius);
        ctx.fillStyle = MARKER_COLOR;
        ctx.fillText(marker.id, labelX, labelY);
    });
}

function drawCrosshair(ctx, x, y, radius) {
    ctx.beginPath();
    ctx.moveTo(x - radius, y);
    ctx.lineTo(x + radius, y);
    ctx.moveTo(x, y - radius);
    ctx.lineTo(x, y + radius);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.stroke();
}

// --- ROI rows ---

function roiRowsFromDom() {
    return Array.from(document.querySelectorAll('#roiList .roi-row')).map((row) => ({
        id: row.querySelector('.roi-id').value.trim(),
        x1: parseInt(row.querySelector('.roi-x1').value, 10) || 0,
        y1: parseInt(row.querySelector('.roi-y1').value, 10) || 0,
        x2: parseInt(row.querySelector('.roi-x2').value, 10) || 0,
        y2: parseInt(row.querySelector('.roi-y2').value, 10) || 0,
    }));
}

function addRoiRow(roi) {
    roi = roi || { id: '', x1: 0, y1: 0, x2: 0, y2: 0 };
    const row = document.createElement('div');
    row.className = 'roi-row flex gap-1 items-center';
    row.innerHTML = `
        <input class="roi-id input-field w-14 p-1 rounded text-xs" placeholder="id" value="${roi.id}">
        <input class="roi-x1 input-field w-12 p-1 rounded text-xs" type="number" placeholder="x1" value="${roi.x1}">
        <input class="roi-y1 input-field w-12 p-1 rounded text-xs" type="number" placeholder="y1" value="${roi.y1}">
        <input class="roi-x2 input-field w-12 p-1 rounded text-xs" type="number" placeholder="x2" value="${roi.x2}">
        <input class="roi-y2 input-field w-12 p-1 rounded text-xs" type="number" placeholder="y2" value="${roi.y2}">
        <button class="remove-roi btn-secondary px-2 py-1 rounded text-xs" type="button">&times;</button>
    `;
    row.querySelector('.remove-roi').addEventListener('click', () => {
        row.remove();
        refreshCaptureRoiSelect();
        drawRoiOverlay();
    });
    row.querySelectorAll('input').forEach((input) => {
        input.addEventListener('change', refreshCaptureRoiSelect);
        input.addEventListener('input', drawRoiOverlay);
    });
    document.getElementById('roiList').appendChild(row);
    refreshCaptureRoiSelect();
    drawRoiOverlay();
}

function refreshCaptureRoiSelect() {
    const select = document.getElementById('captureRoiSelect');
    const previous = select.value;
    const rois = roiRowsFromDom().filter((r) => r.id);
    select.innerHTML = rois.map((r) => `<option value="${r.id}">${r.id}</option>`).join('');
    if (rois.some((r) => r.id === previous)) {
        select.value = previous;
    }
}

// --- Alignment markers ---

function alignmentMarkersFromDom() {
    return Array.from(document.querySelectorAll('#alignmentList .marker-row')).map((row) => ({
        id: row.querySelector('.marker-id').value.trim(),
        x: parseInt(row.querySelector('.marker-x').value, 10) || 0,
        y: parseInt(row.querySelector('.marker-y').value, 10) || 0,
    }));
}

function addAlignmentRow(marker) {
    marker = marker || { id: '', x: 0, y: 0 };
    const row = document.createElement('div');
    row.className = 'marker-row flex gap-1 items-center';
    row.innerHTML = `
        <input class="marker-id input-field w-16 p-1 rounded text-xs" placeholder="id" value="${marker.id}">
        <input class="marker-x input-field w-20 p-1 rounded text-xs" type="number" placeholder="x" value="${marker.x}">
        <input class="marker-y input-field w-20 p-1 rounded text-xs" type="number" placeholder="y" value="${marker.y}">
        <button class="remove-marker btn-secondary px-2 py-1 rounded text-xs" type="button">&times;</button>
    `;
    row.querySelector('.remove-marker').addEventListener('click', () => {
        row.remove();
        drawRoiOverlay();
    });
    row.querySelectorAll('input').forEach((input) => input.addEventListener('input', drawRoiOverlay));
    document.getElementById('alignmentList').appendChild(row);
    drawRoiOverlay();
}

function renderAlignmentMarkers(markers) {
    const el = document.getElementById('alignmentList');
    el.innerHTML = '';
    const seed = markers && markers.length ? markers : [{ id: 'M1', x: 0, y: 0 }, { id: 'M2', x: 0, y: 0 }];
    seed.forEach(addAlignmentRow);
}

// --- Alarm outputs ---

function alarmOutputsFromDom() {
    return Array.from(document.querySelectorAll('#alarmOutputList .alarm-output-row')).map((row) => ({
        id: row.querySelector('.ao-id').value.trim(),
        gpio_pin: parseInt(row.querySelector('.ao-pin').value, 10) || 0,
        active_high: row.querySelector('.ao-active-high').checked,
    }));
}

function addAlarmOutputRow(output) {
    output = output || { id: '', gpio_pin: 27, active_high: true };
    const row = document.createElement('div');
    row.className = 'alarm-output-row flex gap-1 items-center';
    row.innerHTML = `
        <input class="ao-id input-field w-16 p-1 rounded text-xs" placeholder="id" value="${output.id}">
        <input class="ao-pin input-field w-14 p-1 rounded text-xs" type="number" placeholder="GPIO#" value="${output.gpio_pin}">
        <label class="text-xs text-gray-400 flex items-center gap-1">
            <input class="ao-active-high" type="checkbox" ${output.active_high ? 'checked' : ''}> active-high
        </label>
        <button class="remove-alarm-output btn-secondary px-2 py-1 rounded text-xs" type="button">&times;</button>
    `;
    row.querySelector('.remove-alarm-output').addEventListener('click', () => row.remove());
    document.getElementById('alarmOutputList').appendChild(row);
}

function renderAlarmOutputs(outputs) {
    const el = document.getElementById('alarmOutputList');
    el.innerHTML = '';
    const seed = outputs && outputs.length ? outputs : [{ id: 'primary', gpio_pin: 27, active_high: true }];
    seed.forEach(addAlarmOutputRow);
}

// --- Alarm policies ---

function alarmPoliciesFromDom() {
    return Array.from(document.querySelectorAll('#alarmPolicyList .alarm-policy-row')).map((row) => ({
        action: row.querySelector('.ap-action').value,
        mode: row.querySelector('.ap-mode').value,
        pulse_ms: parseInt(row.querySelector('.ap-pulse-ms').value, 10) || 300,
        outputs: row.querySelector('.ap-outputs').value.split(',').map((s) => s.trim()).filter(Boolean),
    }));
}

function addAlarmPolicyRow(policy) {
    policy = policy || { action: 'STOP', mode: 'latch', pulse_ms: 300, outputs: [] };
    const row = document.createElement('div');
    row.className = 'alarm-policy-row flex gap-1 items-center flex-wrap';
    row.innerHTML = `
        <select class="ap-action input-field p-1 rounded text-xs">
            <option value="WARN">WARN</option>
            <option value="STOP">STOP</option>
        </select>
        <select class="ap-mode input-field p-1 rounded text-xs">
            <option value="pulse">pulse</option>
            <option value="latch">latch</option>
        </select>
        <input class="ap-pulse-ms input-field w-16 p-1 rounded text-xs" type="number" placeholder="ms" value="${policy.pulse_ms}">
        <input class="ap-outputs input-field w-28 p-1 rounded text-xs" placeholder="output ids, comma-sep" value="${policy.outputs.join(', ')}">
        <button class="remove-alarm-policy btn-secondary px-2 py-1 rounded text-xs" type="button">&times;</button>
    `;
    row.querySelector('.ap-action').value = policy.action;
    row.querySelector('.ap-mode').value = policy.mode;
    row.querySelector('.remove-alarm-policy').addEventListener('click', () => row.remove());
    document.getElementById('alarmPolicyList').appendChild(row);
}

function renderAlarmPolicies(policies) {
    const el = document.getElementById('alarmPolicyList');
    el.innerHTML = '';
    (policies || []).forEach(addAlarmPolicyRow);
}

// --- Templates (read-only list) ---

function renderTemplateList(templates) {
    const el = document.getElementById('templateList');
    if (!templates || !templates.length) {
        el.innerHTML = '<p class="text-sm text-gray-500">No templates captured yet.</p>';
        return;
    }
    el.innerHTML = templates
        .map((t) => `<div class="text-sm text-gray-300">${t.roi_id} — ${t.kind}</div>`)
        .join('');
}

// --- Cameras ---

function selectedCamera() {
    const select = document.getElementById('cameraSelect');
    const option = select.options[select.selectedIndex];
    if (!option) {
        return null;
    }
    return {
        by_path: option.value,
        video_index: parseInt(option.dataset.videoIndex, 10),
        w: parseInt(option.dataset.w, 10),
        h: parseInt(option.dataset.h, 10),
    };
}

async function refreshCameras() {
    const res = await apiFetch('/api/cameras');
    if (!res.ok) {
        setStatus(`Failed to list cameras: ${await errorDetail(res)}`, true);
        return;
    }
    const data = await res.json();
    currentCameras = data.cameras || [];
    const select = document.getElementById('cameraSelect');
    select.innerHTML = currentCameras
        .map((c) => {
            const label = `${c.by_path || c.port}${c.duplicate ? ' (DUPLICATE SERIAL)' : ''}`;
            return `<option value="${c.by_path}" data-video-index="${c.video_index}" data-w="${c.w}" data-h="${c.h}">${label}</option>`;
        })
        .join('');
    if (currentConfig && currentConfig.camera) {
        select.value = currentConfig.camera.by_path;
    }
    setStatus(`Found ${currentCameras.length} camera(s).`);
}

async function takeSnapshot() {
    const camera = selectedCamera();
    if (!camera || Number.isNaN(camera.video_index)) {
        setStatus('Select a camera first.', true);
        return;
    }
    const res = await apiFetch(`/api/snapshot?video_index=${camera.video_index}`);
    if (!res.ok) {
        setStatus(`Snapshot failed: ${await errorDetail(res)}`, true);
        return;
    }
    const blob = await res.blob();
    const img = document.getElementById('snapshotImg');
    const resolutionEl = document.getElementById('snapshotResolution');
    await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = URL.createObjectURL(blob);
    });
    img.classList.remove('hidden');
    document.getElementById('snapshotPlaceholder').classList.add('hidden');
    // The camera picker's w/h are a placeholder (audit_paths.py never opens
    // the device, so it can't report real resolution) — this is the actual
    // frame size, and what every ROI's x2/y2 has to fit inside.
    resolutionEl.textContent = `Actual frame size: ${img.naturalWidth} x ${img.naturalHeight}`;
    positionRoiOverlay();
    setStatus('Snapshot captured.');
}

async function captureTemplate(kind) {
    const camera = selectedCamera();
    const roiId = document.getElementById('captureRoiSelect').value;
    if (!camera) {
        setStatus('Select a camera first.', true, 'captureStatus');
        return;
    }
    if (!roiId) {
        setStatus('Add and save an ROI (with an id) before capturing.', true, 'captureStatus');
        return;
    }
    const res = await apiFetch('/api/capture-template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ by_path: camera.by_path, roi_id: roiId, kind }),
    });
    if (!res.ok) {
        const detail = await errorDetail(res);
        setStatus(`Capture failed: ${detail}`, true);
        setStatus(`Capture failed: ${detail}`, true, 'captureStatus');
        return;
    }
    const message = `Captured ${kind} template for ROI "${roiId}".`;
    setStatus(message);
    setStatus(message, false, 'captureStatus');
    await loadConfig();
}

// --- Config load/save ---

async function loadConfig() {
    const res = await apiFetch('/api/config');
    if (!res.ok) {
        setStatus(`Failed to load config: ${await errorDetail(res)}`, true);
        return;
    }
    const config = await res.json();
    currentConfig = config;

    if (!config) {
        renderAlignmentMarkers([]);
        renderTemplateList([]);
        renderAlarmOutputs([]);
        renderAlarmPolicies([]);
        setStatus('No config saved yet — fill in the fields and Save Configuration.');
        return;
    }

    document.getElementById('roiList').innerHTML = '';
    (config.rois || []).forEach(addRoiRow);
    refreshCaptureRoiSelect();
    renderAlignmentMarkers(config.alignment);
    drawRoiOverlay();
    renderTemplateList(config.templates);
    renderAlarmOutputs(config.alarm_outputs);
    renderAlarmPolicies(config.alarm_policies);

    if (config.camera && config.camera.by_path) {
        const select = document.getElementById('cameraSelect');
        const match = Array.from(select.options).find((o) => o.value === config.camera.by_path);
        if (match) {
            select.value = config.camera.by_path;
        }
    }
    setStatus('Config loaded.');
}

async function saveConfig() {
    const camera = selectedCamera();
    if (!camera) {
        setStatus('Select a camera first.', true);
        return;
    }

    const base = currentConfig || {};
    const payload = {
        schema_version: base.schema_version || 1,
        detector_cmd: base.detector_cmd || 'python3 main.py',
        camera: { by_path: camera.by_path, video_index: camera.video_index, resolution: { w: camera.w, h: camera.h } },
        search_padding: base.search_padding ?? 20,
        created_at: base.created_at || new Date().toISOString(),
        rois: roiRowsFromDom(),
        alignment: alignmentMarkersFromDom(),
        templates: base.templates || [],
        alarm_outputs: alarmOutputsFromDom(),
        alarm_policies: alarmPoliciesFromDom(),
    };

    const res = await apiFetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        setStatus(`Save failed: ${await errorDetail(res)}`, true);
        return;
    }
    setStatus('Configuration saved.');
    await loadConfig();
}

// --- Alarm state ---

let alarmPollTimer = null;

function renderAlarmState(state) {
    const box = document.getElementById('alarmStateBox');
    const text = document.getElementById('alarmStateText');
    const clearBtn = document.getElementById('clearAlarm');

    box.classList.toggle('alarm-latched', !!state.latched);
    box.classList.toggle('alarm-ok', !state.latched);
    clearBtn.classList.toggle('hidden', !state.latched);

    if (!state.condition) {
        text.textContent = 'No data yet';
    } else if (state.latched) {
        text.textContent = `${state.action} — ${state.condition} (needs acknowledge)`;
    } else {
        text.textContent = `OK — ${state.condition}`;
    }
}

async function refreshAlarmState() {
    const res = await apiFetch('/api/alarm-state');
    if (!res.ok) return;
    renderAlarmState(await res.json());
}

async function clearAlarm() {
    const res = await apiFetch('/api/alarm-ack', { method: 'POST' });
    if (!res.ok) {
        setStatus(`Clear failed: ${await errorDetail(res)}`, true);
        return;
    }
    setStatus('Acknowledge sent — clears within a few seconds.');
    await refreshAlarmState();
}

function startAlarmPolling() {
    if (alarmPollTimer) return;
    refreshAlarmState();
    alarmPollTimer = setInterval(refreshAlarmState, 3000);
}

// --- Init ---

async function connect() {
    setToken(document.getElementById('setupToken').value.trim());
    await refreshCameras();
    await loadConfig();
    startAlarmPolling();
}

function init() {
    document.getElementById('setupToken').value = getToken();
    document.getElementById('connectToken').addEventListener('click', withStatus(connect));
    document.getElementById('refreshCameras').addEventListener('click', withStatus(refreshCameras));
    document.getElementById('takeSnapshot').addEventListener('click', withStatus(takeSnapshot));
    document.getElementById('addRoi').addEventListener('click', withStatus(() => addRoiRow()));
    document.getElementById('addAlignmentMarker').addEventListener('click', withStatus(() => addAlignmentRow()));
    document.getElementById('capturePresent').addEventListener('click', withStatus(() => captureTemplate('present')));
    document.getElementById('captureAbsent').addEventListener('click', withStatus(() => captureTemplate('absent')));
    document.getElementById('saveConfig').addEventListener('click', withStatus(saveConfig));
    document.getElementById('addAlarmOutput').addEventListener('click', withStatus(() => addAlarmOutputRow()));
    document.getElementById('addAlarmPolicy').addEventListener('click', withStatus(() => addAlarmPolicyRow()));
    document.getElementById('clearAlarm').addEventListener('click', withStatus(clearAlarm));

    renderAlignmentMarkers([]);
    renderAlarmOutputs([]);
    renderAlarmPolicies([]);

    window.addEventListener('resize', positionRoiOverlay);

    if (getToken()) {
        withStatus(connect)();
    } else {
        setStatus('Enter your setup token and click Connect to begin.');
    }
}

document.addEventListener('DOMContentLoaded', init);
