
---

# Part 2 — Remediation Instructions (Step by Step)

> These are concrete, ordered instructions to turn the prototype into something
> that can safely sit in front of a real gate. Each step lists the issue IDs it
> resolves (C1…L6 from Part 1), the files to touch, and reference code.
> Run the test suite after every step: `python tests/test_pipeline.py`.

---

## Step 0 — Prerequisites (fix runnability first) [H3, M4]

Do this before anything else, so you can verify each later step.

1. **Make the test suite pass on a fresh clone.**
   - Add a download script `tools/fetch_weights.py` that pulls the trained
     weights from GitHub Releases / Google Drive / Colab export into
     `runs/detect/smartgate-colab-v6-<variant>/weights/best.pt`, **or** commit
     them via Git LFS (see Step 12).
   - Interim workaround: copy the shipped artifacts into the expected layout:
     ```powershell
     mkdir -p runs/detect/smartgate-colab-v6-yolov8n/weights
     copy smartgate-artifacts-Y8N\best.pt runs\detect\smartgate-colab-v6-yolov8n\weights\best.pt
     ```
2. **Fix `requirements.txt`** — split it:
   ```text
   # requirements.txt (core)
   opencv-python-headless>=4.8
   numpy>=1.24
   Pillow>=10.0
   Flask>=3.0
   waitress>=3.0

   # requirements-ocr.txt (pick ONE)
   paddleocr>=3.0
   paddlepaddle>=3.0
   # easyocr>=1.7        # alternative backend

   # requirements-yolo.txt
   ultralytics>=8.2
   # opencv-contrib-python>=4.8   # only for AprilTag stickers

   # requirements-dev.txt
   requests>=2.31        # tools/fetch_samples.py
   ```
3. **Make missing weights a skip, not a failure** in
   `tests/test_pipeline.py::test_model_variant`:
   ```python
   if detect_yolo.weights_path() is None:
       print("  skip  bobot YOLO tidak ada — salin artefak ke runs/detect/ dulu")
       return
   ```
4. **Fix the `Path` annotation** in `app/web.py` (L1):
   ```python
   from pathlib import Path   # add to imports
   ```
5. Remove the unused `ROLE_CHOICES` constant in `app/web.py` (L2) — it is
   replaced by real auth in Step 1.

**Verify:** `python tests/test_pipeline.py` runs the full 80+ checks green
(or explicitly skips the weight checks).

---

## Step 1 — Authentication & Authorization [C1]

The `users` table already exists. Wire it up with Flask sessions.

**New file `app/auth.py`:**
```python
from functools import wraps
from flask import session, redirect, url_for, request, abort

from . import db

def login(username: str) -> None:
    with db.session() as conn:
        row = conn.execute(
            "SELECT username, role FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        raise ValueError("user tidak dikenal")
    session.clear()
    session["user"] = row["username"]
    session["role"] = row["role"]

def current_user() -> str | None:
    return session.get("user")

def current_role() -> str | None:
    return session.get("role")

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                return {"error": "UNAUTHENTICATED"}, 401
            return redirect(url_for("login_page", next=request.path))
        return view(*args, **kwargs)
    return wrapper

def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_role() != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapper
```

**In `app/web.py` (`create_app`):**
```python
app.secret_key = os.environ["SGS_SECRET_KEY"]  # 32+ random bytes, required
# Protect EVERY route:
@app.post("/api/settings")          -> @login_required @admin_required
@app.get("/api/settings")           -> @login_required
@app.post("/vehicles/save")         -> @login_required @admin_required
@app.post("/vehicles/<id>/delete")  -> @login_required @admin_required
@app.post("/api/logs/<id>/action")  -> @login_required
# pages: @login_required on dashboard/logs/log_detail/vehicles/training
```

**Verify:** anonymous `curl -X POST /api/settings` returns **401**;
`satpam`-role user gets **403** on `/api/settings`; changing thresholds as
admin works and is logged.

---

## Step 2 — Server-side audit identity [C2]

Never trust `username` from the client.

**`app/web.py::api_guard_action`:**
```python
@app.post("/api/logs/<int:log_id>/action")
@login_required
def api_guard_action(log_id: int) -> Any:
    payload = request.get_json(silent=True) or {}
    ok, message = service.guard_action(
        log_id,
        str(payload.get("action", "")),
        auth.current_user(),          # <-- from session, not request body
        str(payload.get("note") or ""),
    )
    return jsonify({"ok": ok, "message": message}), (200 if ok else 400)
```

**`app/templates/log_detail.html`:** replace the `<select id="guard-user">`
dropdown with `{{ auth.current_user() }}` (read-only text).

**`app/static/app.js`:** delete `username` from the POST body in the guard
action handler.

**Verify:** tampering with the request body no longer changes `override_by`;
DB shows the session user.

---

## Step 3 — Kill XSS in the frontend [C3, H1]

**`app/static/app.js`** — add an escape helper and use it for **every**
interpolated value in `renderResult` and error paths:
```javascript
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// then:  <td><code>${esc(f.plate_text) || '—'}</code></td>
//        <td>${esc(data.reason)}</td>
//        ${esc(data.matched_vehicle.owner_name)}   etc.
```
Better long-term: build DOM nodes with `textContent` instead of `innerHTML`.

**H1 — `app/templates/vehicles.html`:** remove the inline `onsubmit` JS string:
```html
<button class="small" type="submit"
        data-confirm="Hapus kendaraan {{ row.plate_number|e }}?">Hapus</button>
```
```javascript
document.querySelectorAll('button[data-confirm]').forEach((b) =>
  b.addEventListener('click', (e) => {
    if (!confirm(b.dataset.confirm)) e.preventDefault();
  }));
```
(`data-*` attributes are HTML-escaped by Jinja and never re-parsed as JS.)

**Verify:** create a vehicle with owner name `<img src=x onerror=alert(1)>`
and plate `A');alert(1);//` — no script execution anywhere.

---

## Step 4 — Gate the QR/sticker trust chain [H2]

**`app/sticker.py::decode_sticker`** — reject unsigned payloads in production:
```python
REQUIRE_SIGNED = os.getenv("SGS_REQUIRE_SIGNED_STICKER", "1") == "1"
CODE_PATTERN = re.compile(r"^STK-[A-Z0-9-]{3,32}$")

# in every legacy return path:
if REQUIRE_SIGNED:
    return None, 0.0, "qrcode_unsigned_rejected"
if not CODE_PATTERN.fullmatch(payload):
    return None, 0.0, "qrcode_bad_format"
return payload, confidence, "qrcode_legacy"
```
Also stop returning raw QR text as `sticker_code` — only accept codes that
exist in `master_vehicles.sticker_code` at match time (already checked by
`db.find_vehicle`, so the display path should show `—` for unknown payloads).

**Verify:** an arbitrary QR (`<img onerror=...>`, `HELLO`) yields no sticker
code; only `SGS1.*` signed tokens and well-formed `STK-*` codes pass.

---

## Step 5 — CSRF protection [H5]

With sessions in place (Step 1), add per-session tokens:

```python
import secrets
@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "DELETE"):
        token = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
        if not secrets.compare_digest(token or "", session.get("csrf", "")):
            abort(403, "CSRF token invalid")

@app.context_processor
def inject_csrf():
    session.setdefault("csrf", secrets.token_hex(16))
    return {"csrf_token": session["csrf"]}
```
Add `<input type="hidden" name="csrf" value="{{ csrf_token }}">` to the vehicle
forms and `X-CSRF-Token: {{ csrf_token }}` header in `app.js` fetches.

---

## Step 6 — Docs ↔ implementation alignment [H4]

- If auth (Steps 1–2) is implemented, mark the auth sections of `docs/API.md`
  as "implemented in prototype" and document the session login endpoint.
- If not, add to `README.md` at the top:
  > ⚠️ Prototype tanpa autentikasi — hanya untuk demo di localhost.
  > Jangan sambungkan ke perangkat gerbang nyata.
- Remove or implement the dangling `password_hash` / `POSTGRES_PASSWORD`
  references in `docs/DATABASE.md` / `docs/TECHNICAL.md`.

---

## Step 7 — Snapshot lifecycle [M1]

Mirror the diagnostics ring buffer for `data/snapshots/` in
`app/service.py`:

```python
MAX_SNAPSHOT_SESSIONS = 200   # or rotate by age/size

def _prune_snapshots() -> None:
    sessions = [p for p in config.SNAPSHOT_DIR.iterdir() if p.is_dir()]
    if len(sessions) <= MAX_SNAPSHOT_SESSIONS:
        return
    sessions.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in sessions[MAX_SNAPSHOT_SESSIONS:]:
        shutil.rmtree(stale, ignore_errors=True)
```
Call `_prune_snapshots()` at the end of `evaluate()` when `persist` is true.

---

## Step 8 — Resource caps & rate limiting [M2, M3]

```python
# app/service.py
import threading
_INFERENCE_SLOTS = threading.Semaphore(int(os.getenv("SGS_MAX_CONCURRENT_INFER", "2")))

# wrap the per-frame work in _process_frame:
with _INFERENCE_SLOTS:
    ...
```
- Cap the number of uploaded files per request (e.g. `len(files) <= 6`).
- `camera.html`: raise the auto-scan minimum interval to 1500 ms and capture
  1 frame (not 3) for preview scans.
- Deploy behind a real server + reverse proxy:
  ```powershell
  waitress-serve --host 127.0.0.1 --port 5000 run:app   # or gunicorn
  ```
- Add security headers:
  ```python
  @app.after_request
  def security_headers(resp):
      resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
      resp.headers["X-Content-Type-Options"] = "nosniff"
      resp.headers["X-Frame-Options"] = "DENY"
      resp.headers["Referrer-Policy"] = "same-origin"
      return resp
  ```
  (CSP also backstops any missed XSS.)

---

## Step 9 — Frontend behavior & mobile layout [M5, M6, L3, L4, L5]

- **Polling**: update only the pending list / stats table via
  `/api/alerts` DOM patching; wrap `setInterval` with
  `document.addEventListener('visibilitychange', ...)`.
- **Tables**: `<div class="table-scroll">` + `overflow-x:auto` in CSS.
- **Grid**: `.grid { grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr)); }`
- **Nav**: allow wrapping (`flex-wrap: wrap`) or a hamburger below 720px.
- **Touch targets**: `button, .btn { min-height: 44px; }`.
- **`training.html`**: move `<meta http-equiv="refresh">` into `<head>` via a
  `{% block head %}` in `base.html`, or use `setTimeout(()=>location.reload(), 15000)`.
- **Cache busting**: `url_for('static', filename='app.js', v=APP_VERSION)`.
- Guard `|float` filters in `training.html` with `|default(0, true)`.

---

## Step 10 — Repository hygiene [M7]

```powershell
git lfs install
git lfs track "*.pt" "*.onnx" "*.jpg" "*.png"
git add .gitattributes
```
Going forward: publish weights as GitHub Releases and keep only
`evaluation_summary.json` + a fetch script in the tree. (Rewriting the 558MB
history is optional — `git lfs migrate` — coordinate before force-pushing.)

---

## Step 11 — Final small cleanups [L1–L6]

- `ocr._ROBUST_CACHE`: key on `hashlib.sha1(crop.tobytes()).digest()` instead
  of raw bytes; add a TTL.
- Document that `active_backend()` is cached at first call (env changes need a
  restart).
- Remove/inline leftover styles in `training.html`.

---

## Final Verification Checklist

- [ ] `python tests/test_pipeline.py` — all checks green on a fresh clone
- [ ] Anonymous access: pages redirect to login; `/api/*` returns 401
- [ ] `satpam` cannot change settings/vehicles (403)
- [ ] Guard actions record the **session** user in `override_by`
- [ ] XSS payloads in owner name / plate / QR render inert
- [ ] Unsigned QR codes are rejected (`SGS_REQUIRE_SIGNED_STICKER=1`)
- [ ] CSRF token missing → 403 on POST
- [ ] Snapshots capped at `MAX_SNAPSHOT_SESSIONS`
- [ ] Concurrent inference capped; upload count/size capped
- [ ] `waitress-serve` (or gunicorn) behind reverse proxy; security headers present
- [ ] No horizontal scroll at 360px viewport; touch targets ≥ 44px
- [ ] Weights via LFS/Release download; repo clone < 50MB
