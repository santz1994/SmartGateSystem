# SmartGateSystem — Full Audit Report

> **Status 29 Oktober 2026.** Sebagian besar temuan sudah ditangani — lihat
> `part2-remediation.md`: runnability **H3** (test suite **102/102 lulus**,
> bobot via Git LFS + `tools/fetch_weights.py`, `ultralytics` terpasang),
> **C1** (login sesi + role admin/satpam + proteksi CSRF), **C2** (identitas
> audit dari sesi server, bukan body request), **C3** (escape `esc()` untuk
> semua output OCR/QR ke innerHTML), **H2** (stiker legacy ditolak saat
> `SGS_REQUIRE_SIGNED_STICKER=1`, default aktif). Optimasi performa CPU/OCR
> (scan cepat ±1,4 detik, CPU ±53%) dicatat di `docs/LAPORAN_KP_TEMUAN.md`.
> Skor runnability 5/10 di bawah berlaku saat audit berlangsung, bukan kondisi
> kini.

- **Repository**: https://github.com/santz1994/SmartGateSystem.git
- **Scope**: `Tugas Citra Digital/prototype/` (the Flask prototype = "the app") — all backend, frontend, tests, tooling scripts, and repository structure
- **Audit date**: 2026-10-21
- **Code size**: ~6,500 lines (12 Python modules in `app/` + 7 templates + app.js/CSS + tests/tools)
- **Method**: static code review + actually running `tests/test_pipeline.py` + secret/dangerous-sink scanning

---

## 1. Overall Verdict (Anti-Patterns / Quality)

**This is not AI-generated "template slop".** It is an image-processing project with real engineering judgment: comments explain *why* (not what), Indonesian NRKB plate rules are implemented in code, the decision chain is fail-safe, functions are pure for testability, and heavy imports are lazy-loaded. The UI is a pragmatic dark ops panel — no gradient text, glassmorphism, or AI color palettes.

**But as a gate/access-control system, the security model is fatally weak**: there is *zero* authentication at the application layer, while `docs/API.md` specifies JWT/401/internal-key auth that is nowhere implemented. Treat it as a **localhost demo prototype only — do not connect it to a real barrier**.

**Scores: code quality 7.5/10 · security 3/10 · frontend 6.5/10 · runnability 5/10 (tests fail out of the box; YOLO main path unusable on a fresh clone)**

### Issue Counts

| Severity | Count |
|---|---:|
| Critical | 3 |
| High | 5 |
| Medium | 7 |
| Low | 6 |

---

## 2. Detailed Findings (by severity)

### 🔴 Critical

#### C1. No authentication/authorization anywhere — anyone who can reach the port can steer gate decisions
- **Location**: `app/web.py` — all routes (`/api/*`, `/vehicles/*`, `/logs/*`)
- **Category**: Security (missing auth)
- **Description**: Every endpoint is anonymous. The worst combination is **`POST /api/settings`, which changes decision thresholds without any auth**:
  ```python
  for key, value in payload.items():
      if key not in config.DEFAULTS: continue
      db.set_setting(key, float(value))
  ```
  An attacker sets `fused_confidence_threshold` / `plat_confidence_threshold` to 0, after which `fusion.decide()` passes `plate_ok` and `fused_score >= fused_threshold` trivially → **any registered plate that OCR reads results in `AUTO_OPEN`**.
- **Impact**: Direct physical gate bypass. The settings cache (`db._settings_cache`) is also poisoned for all subsequent sessions.
- **Conflict with docs**: `docs/API.md` mandates 401 `UNAUTHENTICATED`, Bearer tokens, `X-Internal-Key`, tokened websockets — none implemented in the prototype (see H4).
- **Recommendation**: at minimum HTTP Basic/session login (the `users` table already exists and is never used! `SEED_USERS` were seeded for nothing); restrict `/api/settings` and `/vehicles/*` to admin; audit-log threshold changes.
- **Suggested command**: `/harden` (then `/normalize` for a unified auth middleware)

#### C2. Audit identity is client-supplied — audit trail is forgeable and non-repudiable
- **Location**: `app/web.py::api_guard_action` (`str(payload.get("username") or "satpam1")`); hardcoded dropdown `satpam1/admin` in `app/templates/log_detail.html`; `app/static/app.js` POSTs `$('#guard-user').value`
- **Category**: Security (audit integrity)
- **Description**: The DB layer gets it right — `gate_logs` has `CHECK (decision <> 'MANUAL_OVERRIDE' OR (override_by IS NOT NULL AND override_note IS NOT NULL))` — but `override_by` comes from the request body. Anyone can fabricate a "Budi Santoso approved" record in 3 seconds; `db.resolve_override()` never validates that the user exists or has the right role.
- **Impact**: "Who opened the gate for whom" is the core value of a gate system. This chain is forgeable today → the audit log cannot serve as evidence.
- **Recommendation**: take the current user from a server-side session; never accept `username` from the client; `resolve_override` must verify role ∈ (satpam, admin); consider two-person approval for bypass later.

#### C3. Stored/reflected XSS — innerHTML concatenates OCR results, QR payloads, and owner names
- **Location**: `app/static/app.js::renderResult` (~60 `${...}` interpolations into `box.innerHTML` / `resultBox.innerHTML`)
- **Category**: Security (XSS)
- **Description**: All of the following are injected into HTML unescaped:
  - `data.plate_text`, `data.sticker_code`, `data.reason` (server embeds threshold numbers into it)
  - `data.matched_vehicle.owner_name` (from the unauthenticated `/vehicles/save` form → anyone can write it)
  - `data.error`, `f.label`, `path.split('/').pop()`
  **Attack chains (no login required)**:
  1. `POST /vehicles/save` with `owner_name` = `<img src=x onerror=...>`; or
  2. Hold a QR sticker whose content is `<img src=x onerror=...>` up to the camera — the legacy branch of `sticker.decode_sticker()` returns arbitrary QR text as `sticker_code` (only uppercased, whitespace-stripped), which flows through `vote_sticker` → JSON → innerHTML into the guard's browser.
- **Impact**: Arbitrary JS in the guard/admin browser: tamper with the approval UI, steal snapshots and logs, forge operator actions.
- **Recommendation**: HTML-escape every field in `renderResult` (or use `textContent` / `document.createElement`); whitelist QR payload format (e.g. `^STK-[A-Z0-9-]+$`).
- **Suggested command**: `/harden`

### 🟠 High

#### H1. JS-context injection via `onsubmit="confirm('...{{ plate_number }}...')"`
- **Location**: `app/templates/vehicles.html` delete button
- **Description**: Jinja autoescape turns `'` into `&#39;`, but the browser decodes character references back to `'` before handing the attribute value to the JS parser — the classic "HTML escaping is insufficient for JS contexts". `plate_number` has no server-side length/charset validation (`maxlength=16` is client-side only); input like `x');fetch(...);//` injects.
- **Recommendation**: use `data-*` attributes + JS-bound confirm dialog; or the `|tojson` filter.

#### H2. The signed QR token is dead code in practice — legacy unsigned branch bypasses it
- **Location**: `app/sticker.py::decode_sticker`
- **Description**: Carefully implemented HMAC-SHA256 signed tokens (`SGS1.` prefix, expiry, jti) are immediately followed by `return detection.payload, ..., "qrcode_legacy"` — any unsigned QR is treated as a valid sticker code and matched against the DB. A C-grade lock with a universal key left in the keyhole. Forging a QR with `STK-WRG-0042` impersonates the registered vehicle (when the fused score flows through the sticker channel).
- **Recommendation**: disable legacy in production (`SGS_REQUIRE_SIGNED_STICKER=1`); randomize sticker codes so they aren't predictable sequences.

#### H3. Tests fail out of the box + YOLO main path unusable on a fresh clone
- **Location**: `tests/test_pipeline.py::test_model_variant` (line 370); `requirements.txt`; missing `runs/` directory
- **Measured evidence**:
  ```
  46 checks ok, then: GAGAL: varian yolov8n -> bobot v6-n (dapat None)  (exit code 2)
  ModuleNotFoundError: No module named 'ultralytics'
  ls: cannot access 'runs': No such file or directory
  ```
- **Description**: Three broken links:
  1. The test expects `runs/detect/smartgate-colab-v6-*/weights/best.pt`, but the repo only ships `smartgate-artifacts-*/` and a root `best.pt` — no `runs/` → `python tests/test_pipeline.py` **always fails and aborts** on a new clone (README claims "80+ checks"; in reality it stops at check 47);
  2. `requirements.txt` **lacks `ultralytics`** — `detect_yolo._model()` always hits ImportError, the YOLO path never activates, silently falling back to classic OpenCV (the README's headline 3-model comparison / training page all idles);
  3. `detect_yolo.VARIANTS` paths don't match the actual repo layout (`smartgate-artifacts-Y8N/best.pt`).
- **Recommendation**: Git LFS or a download script for weights; add `ultralytics` and `requests` (used by tools) to `requirements.txt`; tests should skip (not fail) when weights are absent.
- **Suggested command**: `/normalize`

#### H4. Docs-vs-implementation security gap
- **Location**: `docs/API.md` (401 semantics, `Authorization: Bearer`, `X-Internal-Key`, `WS /ws/alerts?token=<JWT>`, login endpoints) vs `app/web.py`
- **Description**: The docs describe a production API with authentication; the implementation has none of it. Integrators/auditors will wrongly assume 401 protection exists. `docs/DATABASE.md`'s `password_hash` and `docs/TECHNICAL.md`'s `DB_PASSWORD` are likewise dangling.
- **Recommendation**: either implement a minimal auth layer, or state explicitly in the README: "prototype has no authentication, localhost demo only".

#### H5. No CSRF protection on any state-changing endpoint
- **Location**: `/vehicles/save`, `/vehicles/delete` (form POSTs), `/api/logs/<id>/action`, `/api/settings` (JSON fetch)
- **Description**: No CSRF token, no `SameSite` cookie policy (because there are no sessions at all). Combined with C1, a malicious page on the LAN can silently edit the vehicle registry / forge approvals from a visitor's browser. The JSON endpoints get a little natural protection from the `Content-Type: application/json` requirement, but the form endpoints are wide open.
- **Recommendation**: after introducing sessions, add CSRF tokens (Flask-WTF).

### 🟡 Medium

#### M1. Unbounded snapshot storage growth
- **Location**: `app/service.py::_save` (`data/snapshots/<session>/...`)
- **Description**: The diagnostics directory has a ring buffer (`MAX_DIAGNOSTIC_BUNDLES = 10`) and dedup cooldown, but **the main snapshots/stage images have no cleanup policy at all**. Each persist session writes 1 annotated image + up to 8 stage PNGs per frame; a single "Scan & Save Log" (3 frames) ≈ 27 files. Long-running operation fills the disk → eventually takes down the gate host itself.
- **Recommendation**: reuse the ring-buffer approach from diagnostics, or rotate by day/capacity.

#### M2. No rate limiting / resource caps
- **Location**: `/api/evaluate` (16MB × N files × 3 frames of heavy OCR), `camera.html` auto-scan at 0.75s intervals
- **Description**: A single request synchronously runs YOLO + PaddleOCR (seconds); under `threaded=True`, a few concurrent requests exhaust CPU/RAM. `MAX_CONTENT_LENGTH` only caps a single file. `_ROBUST_CACHE` (32 crop-bytes entries) has noticeable CPU hashing overhead at high frame rates.
- **Recommendation**: global semaphore limiting concurrent inference; reduce auto-scan snapshots to 1 frame + client-side backoff.

#### M3. Flask dev server exposed directly + no security headers
- **Location**: `run.py` (`app.run(threaded=True)`)
- **Description**: dev server with no production hardening; no `Content-Security-Policy` (which would mitigate C3), `X-Frame-Options`, or `X-Content-Type-Options`. Binding `0.0.0.0` exposes it to the LAN immediately.
- **Recommendation**: deploy with waitress/gunicorn; add security headers in an `after_request` hook (CSP also backstops XSS).

#### M4. Dependency manifest inconsistent with actual imports
- **Location**: `requirements.txt`
- **Description**: missing `ultralytics` (H3), `requests` (`tools/fetch_samples.py`); meanwhile `easyocr` + `paddleocr` + `paddlepaddle` are listed side by side — multiple GB installed while only one is used. `opencv-contrib-python` (AprilTag branch) is also undeclared.
- **Recommendation**: split into `requirements.txt` / `requirements-ocr.txt` / `requirements-dev.txt`.

#### M5. Crude dashboard polling
- **Location**: `app/static/app.js` (`/api/alerts` every 3s; `latest_id` change → **full page reload**)
- **Description**: during busy periods every new log reloads the entire page (all thumbnails/tables), and `setInterval` has no `document.hidden` check — background tabs keep hammering the API.
- **Recommendation**: partial DOM updates + pause polling on `visibilitychange` (given the "no WebSocket to reduce dependencies" rationale, partial updates should be done properly).

#### M6. Mobile table/nav horizontal overflow
- **Location**: `app/static/style.css` (`table.data` has no scroll container; `.grid { minmax(320px, 1fr) }`; `.topbar nav` 7 links, no wrap)
- **Description**: at 320–375px viewports, `main` has 20px padding so a 320px minimum column exceeds the ~280px available → horizontal scroll; the 10-column log table inevitably overflows. Checking logs on a phone is painful.
- **Recommendation**: `minmax(min(320px, 100%), 1fr)`; wrap tables in `overflow-x:auto` containers; collapse the nav.

#### M7. Repository size out of control (.git 558MB)
- **Location**: `best.pt` (6.3MB) + `smartgate-artifacts-Y8N/Y11N` (best.pt + best.onnx each) + training data uploaded repeatedly in history (commit `943d4e9 "Upload data train"`)
- **Description**: `.git` measures 558MB. Cloning is very slow, and repeatedly rewriting big binaries into history is the classic "weights in git" anti-pattern.
- **Recommendation**: Git LFS, or publish to Releases/cloud storage and keep only a download script + `evaluation_summary.json` in the repo.

### 🟢 Low

- **L1** `web.py::_latest_train_run` annotates `-> Path` but the module never imports `from pathlib import Path` (`from __future__ import annotations` keeps it from raising at runtime, but flake8 F821 will flag it and anything evaluating annotations at runtime will break).
- **L2** `web.py::ROLE_CHOICES = ("satpam1", "admin")` is defined and never used — and it's inconsistent with the DB's `role IN ('admin','satpam')` enum — evidence that an auth layer was planned but never built (ties into C1).
- **L3** Touch targets are small: buttons ~33px tall < the 44px WCAG 2.5.5 recommendation; `.btn.small` is even smaller.
- **L4** `training.html` puts `<meta http-equiv="refresh" content="15">` inside `<body>` (invalid HTML, works only via browser error recovery); several inline `style=` attributes decouple from the CSS variable system. `|float` filters will throw if epoch CSV columns change.
- **L5** Static assets have no cache busting/versioning (`app.js`/`style.css` updates can hit stale browser caches).
- **L6** `ocr._ROBUST_CACHE` keys on the full crop `tobytes()` with no TTL; bounded to 32 entries but hashing large arrays costs CPU (a digest would be cheaper).

---

## 3. Patterns & Systemic Issues

1. **"Half-finished security features" pattern**: signed QR (H2), users table + role enum (C1/L2), API.md security spec (H4) — the security primitives are written or designed, but every one has a bypass or is simply not wired up. This is the most alarming systemic issue in the repo.
2. **Frontend renders everything via innerHTML string concatenation**: one dangerous pattern across all dynamic rendering (C3), with no escaping helper anywhere.
3. **Resource lifecycle done by halves**: diagnostics has a ring buffer, snapshots don't (M1); model caches use `lru_cache`, settings cache invalidates correctly, but `active_backend` is `lru_cache`-cached so `SGS_OCR_BACKEND` env changes need a restart (acceptable, but should be documented).
4. **Test fragility**: assert-style harness stops at the first failure and depends on artifacts absent from the repo (H3) → CI cannot run.

## 4. Positive Findings (keep these)

- ✅ **Fail-safe decision chain is correct**: DB error → `db_available=False` → never `AUTO_OPEN`; `fusion.decide` documents "the caller must ensure `match` is None when DB is unavailable", and `service.evaluate`'s `except sqlite3.Error` honors it.
- ✅ **All SQL parameterized**; dynamic table/column names come only from internal constants — no injection surface.
- ✅ **Path traversal protection is solid**: `service.snapshot_path` (resolve + parents check) and `diagnostic_path` (relative_to) are both implemented correctly; `training_plot` uses the `TRAIN_PLOTS` whitelist.
- ✅ **Evidence cross-checking**: `fusion.evidence_matches_vehicle` rejects OR-matched plate+sticker mixes from different vehicles.
- ✅ **DB audit constraints**: `gate_logs` CHECK forces `override_by/override_note` on MANUAL_OVERRIDE; vehicle deletion degrades to deactivation on FK conflict, preserving the audit chain.
- ✅ **Structured NRKB correction** (`ocr.normalize_plate`): uses Indonesian plate grammar (region code / number-group rules) to arbitrate B/8, 6/G, 1/I — genuine domain knowledge, with a `VALID_PREFIXES` whitelist.
- ✅ **OCR cost control**: candidates ranked then capped at 3 for OCR, `_ROBUST_CACHE`, early-exit (valid + conf ≥ 0.80), fast/full tiers.
- ✅ **Jinja templates autoescape everywhere** (server-rendered parts are safe; the problem is only in app.js).
- ✅ **Framework-free tests** (46 verified passing, covering NRKB, voting, moiré, distractors — the real hard cases), and high-quality comments that explain trade-offs.

---

## 5. Remediation Roadmap

### Immediate (before connecting to any real device)
1. **Authentication + authorization** (C1): login, session, restrict `/api/settings` and `/vehicles/*` to admin — `/harden`
2. **Server-side audit identity** (C2): username from session — `/harden`
3. **XSS escaping** (C3, H1): escape all fields in `renderResult` + replace `onsubmit` with data attributes — `/harden`

### Short-term (this iteration)
4. Tighten legacy QR (H2); CSRF (H5) — `/harden`
5. Fix tests + weight placement + `requirements.txt` (H3, M4) — `/normalize`
6. Align docs with implementation (H4) — `/polish`

### Medium-term
7. Snapshot rotation (M1), concurrency/rate caps (M2), production server + security headers (M3) — `/optimize`, `/harden`
8. Frontend partial updates + mobile layout (M5, M6) — `/adapt`, `/optimize`

### Long-term
9. Git LFS / binary offloading (M7); sweep up L1–L6 — `/quieter`, `/polish`

---

## Appendix: Measured Evidence

| Check | Result |
|---|---|
| `python3 tests/test_pipeline.py` | 46 ok → **FAIL** (`varian yolov8n -> bobot v6-n (dapat None)`, exit 2) |
| `import ultralytics` | **ModuleNotFoundError** (and not in requirements.txt) |
| `runs/` directory | **absent** (tests / README / `VARIANTS` all assume it exists) |
| `.git` size | **558MB** |
| Secret scan | no hardcoded keys (tokens/keys come from env, ✅); `SGS_STICKER_SIGNING_KEY` design is correct |
| Dangerous-sink scan | no `eval/exec/pickle/subprocess`; only dangerous sink is `innerHTML` (C3) |
