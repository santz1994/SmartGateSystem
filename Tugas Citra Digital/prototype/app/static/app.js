/* Front-end prototipe: tanpa framework, tanpa build step. */

const $ = (sel) => document.querySelector(sel);

function badge(alert) {
  return `<span class="badge ${alert}">${alert}</span>`;
}

function renderResult(data) {
  const frames = data.frames
    .map(
      (f) => `<tr>
        <td>${f.label}</td>
        <td>${f.cctv_role || 'manual'}</td>
        <td><code>${f.plate_text || '—'}</code></td>
        <td>${f.plate_confidence.toFixed(2)}</td>
        <td><code>${f.sticker_code || '—'}</code></td>
        <td>${f.sticker_confidence.toFixed(2)}</td>
        <td>${f.sharpness.toFixed(0)}</td>
        <td>${f.is_best_frame ? '<span class="badge GREEN">BEST</span>' : ''}</td>
      </tr>`
    )
    .join('');

  const vehicle = data.matched_vehicle
    ? `<tr><td>Pemilik</td><td>${data.matched_vehicle.owner_name} (${data.matched_vehicle.owner_type})</td></tr>`
    : '';

  return `
    <div class="result-head">
      ${badge(data.alert)}
      <span class="big">${data.decision_label}</span>
    </div>
    <table class="kv">
      <tr><td>Kode keputusan</td><td><code>${data.decision}</code></td></tr>
      <tr><td>Alasan</td><td>${data.reason}</td></tr>
      <tr><td>Plat</td><td><code>${data.plate_text || '—'}</code> (${data.plate_confidence.toFixed(2)})</td></tr>
      <tr><td>Stiker</td><td><code>${data.sticker_code || '—'}</code> (${data.sticker_confidence.toFixed(2)})</td></tr>
      <tr><td>Skor fusi</td><td>${data.fused_score.toFixed(2)} (plat ${data.plate_score.toFixed(2)} / stiker ${data.sticker_score.toFixed(2)})</td></tr>
      <tr><td>Sumber citra</td><td>${data.sources}</td></tr>
      <tr><td>Backend OCR</td><td><code>${data.ocr_backend}</code></td></tr>
      <tr><td>Pembacaan plat</td><td>${data.plate_enabled ? 'Aktif' : 'Nonaktif'}</td></tr>
      <tr><td>Pembacaan stiker</td><td>${data.sticker_enabled ? 'Aktif' : 'Nonaktif'}</td></tr>
      ${vehicle}
      <tr><td>Session</td><td><code>${data.session_id}</code></td></tr>
    </table>
    ${data.snapshot_url ? `<p><img class="snapshot" src="/${data.snapshot_url}" alt="snapshot"></p>` : ''}
    ${data.frames.some((f) => f.diagnostic_paths && f.diagnostic_paths.length)
      ? `<p class="muted small">Crop diagnostik gagal:
          ${data.frames.flatMap((f) => f.diagnostic_paths || [])
            .map((path) => `<a href="/diagnostics/${path.replace('diag/ocr_failed/', '')}" target="_blank">${path.split('/').pop()}</a>`)
            .join(' · ')}
        </p>`
      : ''}
    <table class="data">
      <thead><tr><th>Frame</th><th>Sumber</th><th>Plat</th><th>Conf</th><th>Stiker</th><th>Conf</th><th>Ketajaman</th><th></th></tr></thead>
      <tbody>${frames}</tbody>
    </table>
    ${data.log_id ? `<p><a class="btn" href="/logs/${data.log_id}">Lihat detail &amp; tahap pipeline</a></p>` : ''}
  `;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { ok: res.ok, data: await res.json() };
}

/* --- Simulasi CCTV --- */
const simButton = $('#sim-run');
if (simButton) {
  simButton.addEventListener('click', async () => {
    simButton.disabled = true;
    simButton.textContent = 'Memproses…';
    try {
      const { ok, data } = await postJSON('/api/simulate', {
        plate: $('#sim-plate').value,
        sticker: $('#sim-sticker').value,
        hard: $('#sim-hard').checked,
      });
      if (!ok) throw new Error(data.error || 'Gagal');
      window.location.href = `/logs/${data.log_id}`;
    } catch (err) {
      alert(`Simulasi gagal: ${err.message}`);
    } finally {
      simButton.disabled = false;
      simButton.textContent = 'Jalankan Simulasi';
    }
  });
}

/* --- Upload foto manual --- */
const uploadForm = $('#upload-form');
if (uploadForm) {
  uploadForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const files = $('#upload-files').files;
    if (!files.length) return;
    const box = $('#upload-result');
    box.innerHTML = '<p class="muted">Memproses…</p>';

    const form = new FormData();
    for (const file of files) form.append('images', file);

    try {
      const res = await fetch('/api/evaluate', { method: 'POST', body: form });
      const data = await res.json();
      box.innerHTML = res.ok ? renderResult(data) : `<p class="bad">${data.error}</p>`;
    } catch (err) {
      box.innerHTML = `<p class="bad">Gagal: ${err.message}</p>`;
    }
  });
}

/* --- Tindakan satpam --- */
document.querySelectorAll('button[data-action]').forEach((button) => {
  button.addEventListener('click', async () => {
    const note = $('#guard-note').value.trim();
    if (!note) {
      $('#guard-msg').textContent = 'Catatan wajib diisi untuk audit.';
      return;
    }
    const { ok, data } = await postJSON(`/api/logs/${button.dataset.log}/action`, {
      action: button.dataset.action,
      username: $('#guard-user').value,
      note,
    });
    $('#guard-msg').textContent = data.message;
    if (ok) setTimeout(() => window.location.reload(), 700);
  });
});

/* --- Kamera + auto scan plat --- */
const camVideo = $('#cam-video');
if (camVideo) {
  const canvas = $('#cam-canvas');
  const overlay = $('#cam-overlay');
  const resultBox = $('#cam-result');
  const statusEl = $('#cam-status');
  let stream = null;
  let timer = null;
  let busy = false;
  let plateEnabled = true;
  let stickerEnabled = true;

  function drawDetections(data) {
    /* Kotak area pembacaan (ROI) + kotak deteksi plat/stiker di atas video. */
    overlay.width = camVideo.clientWidth;
    overlay.height = camVideo.clientHeight;
    const ctx = overlay.getContext('2d');
    const sx = overlay.width / camVideo.videoWidth;
    const sy = overlay.height / camVideo.videoHeight;
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    // ROI zona gerbang (konvensi sama dengan pipeline.filter_gate_zone).
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.65)';
    ctx.setLineDash([10, 8]);
    ctx.lineWidth = 2;
    ctx.strokeRect(0.10 * overlay.width, 0.25 * overlay.height, 0.80 * overlay.width, 0.75 * overlay.height);
    ctx.setLineDash([]);

    const colors = { plate: '#22e06a', sticker: '#ffb020' };
    for (const frame of data.frames || []) {
      for (const det of frame.detections || []) {
        const [x1, y1, x2, y2] = det.bbox;
        // Kotak utama terang + label; kandidat sekunder tipis transparan saja
        // agar tampilan tidak "sibuk" saat latar ramai objek mirip plat.
        if (!det.primary) {
          ctx.strokeStyle = 'rgba(255,255,255,0.30)';
          ctx.lineWidth = 1;
          ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
          continue;
        }
        ctx.strokeStyle = colors[det.kind] || '#ffffff';
        ctx.lineWidth = 3;
        ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
        ctx.font = '16px sans-serif';
        const tag = `${det.kind} ${det.confidence.toFixed(2)}`;
        ctx.fillStyle = colors[det.kind] || '#ffffff';
        ctx.fillRect(x1 * sx, y1 * sy - 20, ctx.measureText(tag).width + 10, 20);
        ctx.fillStyle = '#000';
        ctx.fillText(tag, x1 * sx + 5, y1 * sy - 5);
      }
    }
    if (data.plate_text) {
      ctx.font = 'bold 22px sans-serif';
      ctx.fillStyle = '#22e06a';
      ctx.fillText(`${data.plate_text} (${data.plate_confidence.toFixed(2)})`, 12, overlay.height - 16);
    }
  }

  const snapBlob = () =>
    new Promise((resolve) => {
      const maxWidth = 960;
      const scale = Math.min(1, maxWidth / camVideo.videoWidth);
      canvas.width = Math.round(camVideo.videoWidth * scale);
      canvas.height = Math.round(camVideo.videoHeight * scale);
      canvas.getContext('2d').drawImage(camVideo, 0, 0);
      canvas.toBlob(resolve, 'image/jpeg', 0.78);
    });

  async function scan(persist) {
    if (busy) return;
    if (!stream || !camVideo.videoWidth) {
      if (persist) statusEl.textContent = 'Kamera belum siap — klik Aktifkan Kamera dulu.';
      // Video belum siap: jangan matikan loop auto scan, coba lagi interval berikut.
      if ($('#cam-auto').checked && stream) scheduleNext();
      return;
    }
    busy = true;
    statusEl.textContent = 'Memindai…';
    try {
      const blob = await snapBlob();
      const form = new FormData();
      form.append('images', blob, 'camera.jpg');
      const params = new URLSearchParams({
        persist: persist ? '1' : '0',
        plate: plateEnabled ? '1' : '0',
        sticker: persist && stickerEnabled ? '1' : '0',
        fast: persist ? '0' : '1',
      });
      const res = await fetch(`/api/evaluate?${params.toString()}`, { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Gagal memindai');
      resultBox.innerHTML = renderResult(data);
      drawDetections(data);
      statusEl.textContent = `Plat: ${data.plate_text || 'tidak terbaca'} (${data.plate_confidence.toFixed(2)}) — ${data.decision_label}`;
    } catch (err) {
      statusEl.textContent = `Gagal: ${err.message}`;
    } finally {
      busy = false;
      if ($('#cam-auto').checked && stream) scheduleNext();
    }
  }

  $('#cam-start').addEventListener('click', async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1280 } },
        audio: false,
      });
      camVideo.srcObject = stream;
      statusEl.textContent = 'Kamera aktif.';
      if ($('#cam-auto').checked) scheduleNext(true);
    } catch (err) {
      statusEl.textContent = `Kamera gagal: ${err.message}`;
    }
  });

  $('#cam-stop').addEventListener('click', () => {
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    camVideo.srcObject = null;
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    $('#cam-auto').checked = false;
    const ctx = overlay.getContext('2d');
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    statusEl.textContent = 'Kamera dimatikan.';
  });

  $('#cam-scan').addEventListener('click', () => scan(true));
  function updateToggle(button, enabled, label) {
    button.setAttribute('aria-pressed', String(enabled));
    button.textContent = `${label}: ${enabled ? 'Aktif' : 'Nonaktif'}`;
  }
  $('#cam-plate-toggle').addEventListener('click', (event) => {
    plateEnabled = !plateEnabled;
    updateToggle(event.currentTarget, plateEnabled, 'Plat');
    statusEl.textContent = plateEnabled
      ? 'Deteksi plat aktif.'
      : 'Deteksi plat nonaktif — nomor plat tidak akan dibaca.';
  });
  $('#cam-sticker-toggle').addEventListener('click', (event) => {
    stickerEnabled = !stickerEnabled;
    updateToggle(event.currentTarget, stickerEnabled, 'Stiker');
    statusEl.textContent = stickerEnabled
      ? 'Deteksi stiker aktif.'
      : 'Deteksi stiker nonaktif — stiker tidak akan dibaca.';
  });
  $('#cam-auto').addEventListener('change', (event) => {
    if (event.target.checked) {
      statusEl.textContent = 'Auto scan cepat aktif (preview plat, tanpa simpan log).';
      scheduleNext(true);
    } else if (timer) {
      clearTimeout(timer);
      timer = null;
      statusEl.textContent = 'Auto scan berhenti.';
    }
  });

  function scheduleNext(immediate = false) {
    if (timer) clearTimeout(timer);
    const ms = immediate ? 0 : Number($('#cam-interval').value) || 1000;
    timer = setTimeout(() => {
      timer = null;
      scan(false);
    }, ms);
  }
}

/* --- Polling alert dashboard --- */
if (window.SGS && window.SGS.pollAlerts) {
  let lastId = 0;
  setInterval(async () => {
    try {
      const res = await fetch('/api/alerts');
      const data = await res.json();
      if (lastId && data.latest_id > lastId) window.location.reload();
      lastId = data.latest_id;
    } catch {
      /* dashboard tetap jalan walau polling gagal */
    }
  }, 3000);
}
