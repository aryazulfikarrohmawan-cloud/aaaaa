import os
import sys
import time
import json
import base64
import sqlite3
import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "history.db"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STOP_FLAG_FILE = BASE_DIR / "stop_batch.flag"
PID_FILE = BASE_DIR / "worker.pid"
LOG_FILE = BASE_DIR / "worker.log"

BASE_URL = "https://imaginer.mirava.studio"

STYLE_MAP = {
    "KREATIF": "creative",
    "FASHION": "fashion",
    "POTRET": "portrait",
    "POTRET SINEMATIK": "cinematic",
    "POTRET FASHION": "fashion",
    "ILUSTRASI": "illustration",
    "RENDER 3D": "3d",
    "AKRILIK": "acrylic",
    "KONSEP GAME": "concept-art",
    "DESAIN GRAFIS 2D": "vector",
    "DESAIN GRAFIS 3D": "3d",
    "FOTO HITAM PUTIH": "monochrome",
    "FOTO WARNA": "photorealistic",
    "FOTO FILM": "film",
    "RAY TRACED": "ray-traced",
    "FOTO 35MM": "35mm",
    "CAT AIR": "watercolor"
}

def log_worker(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_worker_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS batch_jobs (
                batch_id TEXT PRIMARY KEY,
                total INTEGER NOT NULL,
                model_id TEXT NOT NULL,
                ratio TEXT NOT NULL,
                quality TEXT,
                style TEXT,
                ref_image_ids TEXT,
                status TEXT NOT NULL, -- 'active', 'completed', 'stopped'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS batch_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                item_index INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL, -- 'PENDING', 'LIMIT_RPM', 'SUBMITTED', 'RENDERING', 'SELESAI', 'GAGAL', 'DIBATALKAN'
                duration_seconds INTEGER DEFAULT 0,
                generation_id TEXT,
                remote_urls TEXT,
                local_paths TEXT,
                gdrive_synced INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS batch_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                time_str TEXT NOT NULL,
                log_type TEXT,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_batch_items ON batch_items(batch_id, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_jobs(status)")
        conn.commit()

def add_batch_log(batch_id: str, message: str, log_type: str = ""):
    time_str = datetime.datetime.now().strftime("%H:%M:%S")
    log_worker(f"[{batch_id}] {message}")
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO batch_logs (batch_id, time_str, log_type, message)
                VALUES (?, ?, ?, ?)
            """, (batch_id, time_str, log_type, message))
            conn.commit()
    except Exception as e:
        log_worker(f"Error adding batch log: {e}")

def get_config_val(key: str, default: str = "") -> str:
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT value FROM app_config WHERE key = ?", (key,))
            row = c.fetchone()
            if row and row[0] is not None:
                return str(row[0])
    except Exception:
        pass
    return default

def is_gdrive_enabled() -> bool:
    return get_config_val("gdrive_enabled", "false").lower() == "true"

def upload_to_gdrive(file_path: str) -> bool:
    mode = get_config_val("gdrive_mode", "webhook")
    if mode == "webhook":
        webhook_url = get_config_val("gdrive_webhook_url", "").strip()
        if not webhook_url:
            raise ValueError("Google Apps Script Webhook URL belum diatur.")
        
        p = Path(file_path)
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {
            "filename": p.name,
            "mimeType": "image/png" if p.suffix.lower() == ".png" else "image/jpeg",
            "base64": b64
        }
        resp = requests.post(webhook_url, json=payload, timeout=60)
        
        if "Fungsi skrip tidak ditemukan" in resp.text or "Script function not found" in resp.text:
            raise RuntimeError("Fungsi 'doPost' belum aktif pada URL ini.")
        if "Google Accounts" in resp.text or "Sign in" in resp.text:
            raise RuntimeError("Akses ditolak oleh Google. Setelan 'Who has access' harus 'Anyone'.")
        
        try:
            d = resp.json()
            if isinstance(d, dict) and (d.get("status") == "success" or "id" in d):
                return True
        except Exception:
            pass

        if resp.status_code in (200, 201, 302):
            if "<!DOCTYPE html>" in resp.text:
                raise RuntimeError("Apps Script mengembalikan halaman HTML alih-alih data.")
            return True
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:100]}")

    elif mode == "service_account":
        creds_json = get_config_val("gdrive_service_account_json", "").strip()
        if not creds_json:
            raise ValueError("Credentials JSON belum diatur.")
        creds_dict = json.loads(creds_json)
        folder_id = get_config_val("gdrive_folder_id", "").strip()

        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        SCOPES = ['https://www.googleapis.com/auth/drive.file']
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)

        p = Path(file_path)
        metadata = {'name': p.name}
        if folder_id:
            metadata['parents'] = [folder_id]
        media = MediaFileUpload(file_path, mimetype='image/png' if p.suffix.lower() == ".png" else 'image/jpeg', resumable=True)
        f = service.files().create(body=metadata, media_body=media, fields='id').execute()
        return bool(f.get('id'))

    return False

class RPMRateLimiter:
    def __init__(self, max_rpm: int = 5):
        self.max_rpm = max_rpm
        self.request_timestamps: List[float] = []

    def wait_for_slot(self, stop_callback=None):
        now = time.time()
        self.request_timestamps = [t for t in self.request_timestamps if now - t < 60.0]

        if len(self.request_timestamps) >= self.max_rpm:
            oldest_ts = self.request_timestamps[0]
            elapsed = now - oldest_ts
            sleep_needed = max(1.0, 60.0 - elapsed + 1.0)
            
            step = 0.5
            total = 0.0
            while total < sleep_needed:
                if stop_callback and stop_callback():
                    return False
                time.sleep(min(step, sleep_needed - total))
                total += step
            now = time.time()
            self.request_timestamps = [t for t in self.request_timestamps if now - t < 60.0]

        self.request_timestamps.append(time.time())
        return True

def check_stop_requested() -> bool:
    return STOP_FLAG_FILE.exists()

def create_mirava_task(api_key: str, model_id: str, prompt: str, ratio: str,
                       quality: Optional[str], style: Optional[str],
                       ref_image_ids: Optional[List[str]]) -> str:
    url = f"{BASE_URL}/api/public/v1/generate"
    payload = {
        "model_id": model_id,
        "prompt": prompt,
        "ratio": ratio
    }
    if quality:
        payload["quality"] = quality
    if style:
        s_clean = str(style).strip().upper()
        if s_clean not in ("TANPA GAYA", "TANPA GAYA (DEFAULT)", "DINAMIS", "NONE", "DEFAULT", "AUTO", "TANPA STYLE", ""):
            api_style = STYLE_MAP.get(s_clean, style.lower().replace(" ", "-"))
            if api_style:
                payload["style"] = api_style
    if ref_image_ids:
        payload["ref_image_ids"] = ref_image_ids

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "User-Agent": "MiravaStudioWorker/2.5"
    }

    max_retries = 6
    for attempt in range(max_retries):
        if check_stop_requested():
            raise InterruptedError("Batch dihentikan pengguna.")
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise e

        if resp.status_code == 429:
            retry_header = resp.headers.get("Retry-After")
            try:
                wait_s = int(retry_header) if retry_header else (12 * (attempt + 1))
            except Exception:
                wait_s = 12 * (attempt + 1)
            time.sleep(wait_s)
            continue

        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(f"Gagal generate ({resp.status_code}): {resp.text}")

        data = resp.json()
        gen_id = None
        if isinstance(data, dict):
            gen_id = data.get("generation_id") or data.get("id")
            if not gen_id and "data" in data and isinstance(data["data"], dict):
                gen_id = data["data"].get("generation_id") or data["data"].get("id")
        if not gen_id:
            raise RuntimeError(f"Respon tidak memiliki generation_id: {data}")
        return str(gen_id)

    raise RuntimeError("Batas RPM limit terlampaui.")

def check_mirava_status(api_key: str, generation_id: str) -> Dict[str, Any]:
    url = f"{BASE_URL}/api/public/v1/generate/{generation_id}"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "User-Agent": "MiravaStudioWorker/2.5"
    }
    for _ in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 429:
                time.sleep(5)
                continue
            if resp.status_code != 200:
                return {"status": "error", "error": f"HTTP {resp.status_code}: {resp.text}", "urls": []}
            data = resp.json()
            content = data.get("data", data) if isinstance(data, dict) else {}
            raw_s = str(content.get("status", "")).lower()
            if raw_s in ("success", "completed", "done", "succeeded"):
                raw_urls = content.get("urls") or content.get("url") or []
                urls = [raw_urls] if isinstance(raw_urls, str) else raw_urls
                return {"status": "success", "urls": urls, "error": None}
            elif raw_s in ("failed", "error", "rejected"):
                return {"status": "failed", "urls": [], "error": content.get("error") or "Gagal render."}
            return {"status": "processing", "urls": [], "error": None}
        except Exception:
            time.sleep(2)
    return {"status": "error", "urls": [], "error": "Koneksi terputus saat polling status."}

def download_image(url: str, generation_id: str, index: int) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 200:
            c_type = resp.headers.get("Content-Type", "")
            ext = ".png" if "png" in c_type else (".webp" if "webp" in c_type else ".jpg")
            clean_id = "".join(c for c in generation_id if c.isalnum() or c in "-_")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"{clean_id}_{ts}_{index}{ext}"
            fpath = OUTPUT_DIR / fname
            with open(fpath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return str(fpath)
    except Exception as e:
        log_worker(f"Download error: {e}")
    return None

def process_batch_queue():
    """Main worker loop that processes active batches in the background."""
    init_worker_db()
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    
    log_worker(f"Background worker started with PID {os.getpid()}")
    limiter = RPMRateLimiter(max_rpm=int(get_config_val("max_rpm", "5")))

    while True:
        try:
            # Update RPM rate if changed
            curr_rpm = int(get_config_val("max_rpm", "5"))
            limiter.max_rpm = curr_rpm

            # Check if stop was requested
            if check_stop_requested():
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("SELECT batch_id FROM batch_jobs WHERE status = 'active'")
                    active_jobs = [r["batch_id"] for r in c.fetchall()]
                    for b_id in active_jobs:
                        c.execute("UPDATE batch_items SET status = 'DIBATALKAN' WHERE batch_id = ? AND status IN ('PENDING', 'LIMIT_RPM', 'SUBMITTED')", (b_id,))
                        c.execute("UPDATE batch_jobs SET status = 'stopped', updated_at = datetime('now','localtime') WHERE batch_id = ?", (b_id,))
                        add_batch_log(b_id, "🛑 Batch dihentikan oleh pengguna.", "failed")
                    conn.commit()
                if STOP_FLAG_FILE.exists():
                    STOP_FLAG_FILE.unlink()

            # Find active batch
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM batch_jobs WHERE status = 'active' ORDER BY created_at ASC LIMIT 1")
                job = c.fetchone()

            if not job:
                time.sleep(2)
                continue

            batch_id = job["batch_id"]
            api_key = get_config_val("api_key", "")
            if not api_key:
                add_batch_log(batch_id, "❌ API Key belum tersimpan di database!", "failed")
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE batch_jobs SET status = 'stopped' WHERE batch_id = ?", (batch_id,))
                    conn.commit()
                time.sleep(2)
                continue

            # Find next unfinished item in this batch
            with get_db() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT * FROM batch_items 
                    WHERE batch_id = ? AND status IN ('PENDING', 'LIMIT_RPM', 'SUBMITTED', 'RENDERING')
                    ORDER BY item_index ASC LIMIT 1
                """, (batch_id,))
                item = c.fetchone()

            if not item:
                # All items in this batch completed!
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE batch_jobs SET status = 'completed', updated_at = datetime('now','localtime') WHERE batch_id = ?", (batch_id,))
                    conn.commit()
                add_batch_log(batch_id, "✅ Semua prompt dalam batch ini selesai diproses.", "success")
                time.sleep(1)
                continue

            item_id = item["id"]
            item_idx = item["item_index"]
            prompt_text = item["prompt"]
            total_items = job["total"]

            # 1. Enforce Rate Limiter Slot
            with get_db() as conn:
                c = conn.cursor()
                c.execute("UPDATE batch_items SET status = 'LIMIT_RPM', updated_at = datetime('now','localtime') WHERE id = ?", (item_id,))
                conn.commit()

            slot_ok = limiter.wait_for_slot(stop_callback=check_stop_requested)
            if not slot_ok or check_stop_requested():
                continue

            # 2. Submit task to Mirava API
            item_start_t = time.time()
            with get_db() as conn:
                c = conn.cursor()
                c.execute("UPDATE batch_items SET status = 'SUBMITTED', updated_at = datetime('now','localtime') WHERE id = ?", (item_id,))
                conn.commit()

            add_batch_log(batch_id, f"[{item_idx}/{total_items}] Mengirim: \"{prompt_text[:40]}...\"", "active")

            try:
                ref_ids = json.loads(job["ref_image_ids"]) if job["ref_image_ids"] else None
                gen_id = create_mirava_task(
                    api_key=api_key,
                    model_id=job["model_id"],
                    prompt=prompt_text,
                    ratio=job["ratio"],
                    quality=job["quality"],
                    style=job["style"],
                    ref_image_ids=ref_ids
                )
                
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("""
                        UPDATE batch_items 
                        SET status = 'RENDERING', generation_id = ?, updated_at = datetime('now','localtime')
                        WHERE id = ?
                    """, (gen_id, item_id))
                    conn.commit()

                add_batch_log(batch_id, f"[{item_idx}/{total_items}] Tugas diterima: ID `{gen_id}`. Polling...", "active")

                # 3. Polling loop (8s safe interval)
                start_poll = time.time()
                success_urls = []
                while time.time() - start_poll < 360:
                    if check_stop_requested():
                        break
                    st_res = check_mirava_status(api_key, gen_id)
                    curr_s = st_res.get("status")
                    elapsed = int(time.time() - item_start_t)
                    
                    with get_db() as conn:
                        c = conn.cursor()
                        c.execute("UPDATE batch_items SET duration_seconds = ? WHERE id = ?", (elapsed, item_id))
                        conn.commit()

                    if curr_s == "success":
                        success_urls = st_res.get("urls", [])
                        break
                    elif curr_s in ("failed", "error"):
                        err_msg = st_res.get("error", "Generation failed.")
                        if "429" in err_msg:
                            time.sleep(10)
                            continue
                        raise RuntimeError(err_msg)

                    for _ in range(16):
                        if check_stop_requested():
                            break
                        time.sleep(0.5)

                if check_stop_requested():
                    continue

                if not success_urls:
                    raise TimeoutError("Render timeout melebihi 6 menit.")

                # 4. Download locally
                saved_paths = []
                for u_idx, u in enumerate(success_urls):
                    loc_p = download_image(u, gen_id, u_idx)
                    if loc_p:
                        saved_paths.append(loc_p)

                # 5. Upload to Google Drive if enabled
                gdrive_ok = 0
                if is_gdrive_enabled() and saved_paths:
                    for p in saved_paths:
                        try:
                            add_batch_log(batch_id, f"[{item_idx}/{total_items}] ☁️ Mengunggah ke Google Drive...", "active")
                            if upload_to_gdrive(p):
                                gdrive_ok = 1
                                add_batch_log(batch_id, f"[{item_idx}/{total_items}] ☁️ Tersimpan di Google Drive!", "success")
                        except Exception as gd_err:
                            add_batch_log(batch_id, f"[{item_idx}/{total_items}] ⚠️ Gagal simpan ke G-Drive: {gd_err}", "failed")

                dur = int(time.time() - item_start_t)
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("""
                        UPDATE batch_items 
                        SET status = 'SELESAI', duration_seconds = ?, remote_urls = ?, local_paths = ?, gdrive_synced = ?, updated_at = datetime('now','localtime')
                        WHERE id = ?
                    """, (dur, json.dumps(success_urls), json.dumps(saved_paths), gdrive_ok, item_id))
                    # Also record into unified generations table
                    c.execute("""
                        INSERT OR REPLACE INTO generations
                        (generation_id, model_id, prompt, ratio, quality, style, status, remote_urls, local_paths, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'success', ?, ?, datetime('now','localtime'))
                    """, (gen_id, job["model_id"], prompt_text, job["ratio"], job["quality"] or "", job["style"] or "", json.dumps(success_urls), json.dumps(saved_paths)))
                    conn.commit()

                add_batch_log(batch_id, f"[{item_idx}/{total_items}] Berhasil ({dur}s)! Tersimpan di outputs/", "success")

            except InterruptedError:
                continue
            except Exception as item_err:
                dur = int(time.time() - item_start_t)
                err_str = str(item_err)
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("""
                        UPDATE batch_items 
                        SET status = 'GAGAL', duration_seconds = ?, error_message = ?, updated_at = datetime('now','localtime')
                        WHERE id = ?
                    """, (dur, err_str, item_id))
                    conn.commit()
                add_batch_log(batch_id, f"[{item_idx}/{total_items}] Gagal ({dur}s): {err_str}", "failed")

        except Exception as loop_err:
            log_worker(f"Unexpected worker error: {loop_err}")
            time.sleep(3)

if __name__ == "__main__":
    process_batch_queue()
