import os
import time
import json
import base64
import sqlite3
import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests
import streamlit as st
from PIL import Image

# ==========================================
# CONSTANTS & CONFIGURATION
# ==========================================
BASE_URL = "https://imaginer.mirava.studio"
DB_PATH = Path("history.db")
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STOP_FLAG_FILE = Path("stop_batch.flag")

MODEL_MATRIX = {
    "nano-banana-2": {
        "name": "NANO BANANA 2",
        "qualities": ["1K", "2K", "4K"],
        "max_refs": 6,
        "support_style": True,
        "max_prompt_chars": None,
        "description": "High-fidelity generation dengan resolusi 1K/2K/4K dan hingga 6 gambar referensi."
    },
    "gpt-image-2": {
        "name": "GPT IMAGE 2",
        "qualities": ["low", "medium"],
        "max_refs": 6,
        "support_style": True,
        "max_prompt_chars": None,
        "description": "Model visi AI seimbang dengan opsi kualitas low/medium dan hingga 6 gambar referensi."
    },
    "flux-pro-2.0": {
        "name": "FLUX 2.0 PRO",
        "qualities": [],
        "max_refs": 4,
        "support_style": True,
        "max_prompt_chars": None,
        "description": "Model fotorealistik tingkat tinggi dengan dukungan hingga 4 gambar referensi."
    },
    "ideogram-v3.0": {
        "name": "IDEOGRAM 3.0",
        "qualities": [],
        "max_refs": 0,
        "support_style": True,
        "max_prompt_chars": None,
        "description": "Model grafis dan tipografi teks presisi (mode teks murni tanpa referensi)."
    },
    "lucid-origin": {
        "name": "LUCID ORIGIN",
        "qualities": [],
        "max_refs": 2,
        "support_style": True,
        "max_prompt_chars": None,
        "description": "Model estetika artistik dengan dukungan hingga 2 gambar referensi."
    },
    "seedream-4.5": {
        "name": "SEEDREAM 4.5",
        "qualities": [],
        "max_refs": 6,
        "support_style": True,
        "max_prompt_chars": None,
        "description": "Model pemahaman estetika mendalam dengan dukungan hingga 6 gambar referensi."
    },
    "recraft-v4": {
        "name": "RECRAFT V4",
        "qualities": [],
        "max_refs": 0,
        "support_style": False,
        "max_prompt_chars": 1200,
        "description": "Model desain vektor dan raster. Maksimal 1200 karakter prompt, mode teks murni."
    }
}

RATIO_OPTIONS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]

STYLE_OPTIONS = [
    "TANPA GAYA",
    "DINAMIS",
    "POTRET SINEMATIK",
    "ILUSTRASI",
    "RENDER 3D",
    "FOTO WARNA",
    "KREATIF",
    "FASHION",
    "POTRET",
    "POTRET FASHION",
    "AKRILIK",
    "KONSEP GAME",
    "DESAIN GRAFIS 2D",
    "DESAIN GRAFIS 3D",
    "FOTO HITAM PUTIH",
    "FOTO FILM",
    "RAY TRACED",
    "FOTO 35MM",
    "CAT AIR"
]

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

# ==========================================
# DATABASE HELPER (SQLite & Config Persistence)
# ==========================================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generation_id TEXT UNIQUE,
                model_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                ratio TEXT,
                quality TEXT,
                style TEXT,
                parameters TEXT,
                status TEXT NOT NULL,
                remote_urls TEXT,
                local_paths TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gen_id ON generations(generation_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON generations(status)")
        conn.commit()

def get_config(key: str, default: str = "") -> str:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_config WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return str(row[0])
    except Exception:
        pass
    return default

def set_config(key: str, value: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO app_config (key, value, updated_at)
                VALUES (?, ?, datetime('now', 'localtime'))
            """, (key, str(value)))
            conn.commit()
    except Exception:
        pass

def record_generation_start(generation_id: str, model_id: str, prompt: str, ratio: str,
                            quality: Optional[str], style: Optional[str],
                            parameters: Dict[str, Any]):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO generations 
            (generation_id, model_id, prompt, ratio, quality, style, parameters, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        """, (
            generation_id,
            model_id,
            prompt,
            ratio,
            quality or "",
            style or "",
            json.dumps(parameters),
            "processing"
        ))
        conn.commit()

def update_generation_complete(generation_id: str, status: str,
                               remote_urls: List[str] = None,
                               local_paths: List[str] = None,
                               error_message: str = None):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE generations
            SET status = ?,
                remote_urls = ?,
                local_paths = ?,
                error_message = ?
            WHERE generation_id = ?
        """, (
            status,
            json.dumps(remote_urls or []),
            json.dumps(local_paths or []),
            error_message or "",
            generation_id
        ))
        conn.commit()

def fetch_history(search_query: str = "", model_filter: str = "All"):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = "SELECT * FROM generations WHERE 1=1"
        params = []

        if model_filter and model_filter != "All":
            query += " AND model_id = ?"
            params.append(model_filter)

        if search_query.strip():
            query += " AND prompt LIKE ?"
            params.append(f"%{search_query.strip()}%")

        query += " ORDER BY id DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def delete_generation(record_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT local_paths FROM generations WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if row and row["local_paths"]:
            try:
                paths = json.loads(row["local_paths"])
                for p in paths:
                    file_path = Path(p)
                    if file_path.exists():
                        file_path.unlink()
            except Exception:
                pass
        cursor.execute("DELETE FROM generations WHERE id = ?", (record_id,))
        conn.commit()

# ==========================================
# GOOGLE DRIVE SYNC HELPER
# ==========================================
def is_gdrive_sync_enabled() -> bool:
    return get_config("gdrive_enabled", "false").lower() == "true"

def upload_to_gdrive(file_path: str, log_callback=None) -> bool:
    """Uploads a local image file to Google Drive via configured method."""
    mode = get_config("gdrive_mode", "webhook")

    if mode == "webhook":
        webhook_url = get_config("gdrive_webhook_url", "").strip()
        if not webhook_url:
            raise ValueError("Google Apps Script Webhook URL belum dikonfigurasi.")
        
        p = Path(file_path)
        with open(p, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
        
        payload = {
            "filename": p.name,
            "mimeType": "image/png" if p.suffix.lower() == ".png" else "image/jpeg",
            "base64": b64_data
        }
        resp = requests.post(webhook_url, json=payload, timeout=60)
        
        # Check if Google returned a script error
        if "Fungsi skrip tidak ditemukan" in resp.text or "Script function not found" in resp.text:
            raise RuntimeError("Fungsi 'doPost' belum aktif pada URL ini. Kemungkinan besar Google telah membuatkan URL WEB APP BARU saat Anda klik Deploy. Silakan salin URL Web App yang baru dari Google Apps Script dan tempelkan ke kolom di atas.")
        
        if "Google Accounts" in resp.text or "Sign in" in resp.text:
            raise RuntimeError("Akses ditolak oleh Google. Pastikan setelan 'Who has access' pada Web app diatur ke 'Anyone'.")
            
        try:
            data = resp.json()
            if isinstance(data, dict):
                if data.get("status") == "success" or "id" in data:
                    return True
                elif data.get("error"):
                    raise RuntimeError(f"Apps Script Error: {data.get('error')}")
        except Exception:
            pass

        if resp.status_code in (200, 201, 302):
            if "<!DOCTYPE html>" in resp.text or "<html" in resp.text:
                raise RuntimeError("Google Apps Script mengembalikan halaman web error, bukan data file. Periksa deployment Google Apps Script Anda.")
            return True
        else:
            raise RuntimeError(f"Webhook HTTP {resp.status_code}: {resp.text[:120]}")

    elif mode == "service_account":
        creds_json = get_config("gdrive_service_account_json", "").strip()
        if not creds_json:
            raise ValueError("Service Account credentials JSON belum diisi.")
        try:
            creds_dict = json.loads(creds_json)
        except Exception:
            raise ValueError("Format Service Account JSON tidak valid.")
        
        folder_id = get_config("gdrive_folder_id", "").strip()

        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        SCOPES = ['https://www.googleapis.com/auth/drive.file']
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)

        p = Path(file_path)
        file_metadata = {'name': p.name}
        if folder_id:
            file_metadata['parents'] = [folder_id]

        media = MediaFileUpload(
            file_path,
            mimetype='image/png' if p.suffix.lower() == ".png" else 'image/jpeg',
            resumable=True
        )
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return bool(file.get('id'))

    return False

# ==========================================
# RPM RATE LIMITER (SLIDING WINDOW)
# ==========================================
class RPMRateLimiter:
    def __init__(self, max_rpm: int = 5):
        self.max_rpm = max_rpm
        self.request_timestamps: List[float] = []

    def wait_for_slot(self, log_callback=None, stop_check_callback=None):
        now = time.time()
        self.request_timestamps = [t for t in self.request_timestamps if now - t < 60.0]

        if len(self.request_timestamps) >= self.max_rpm:
            oldest_ts = self.request_timestamps[0]
            elapsed_since_oldest = now - oldest_ts
            sleep_needed = max(1.0, 60.0 - elapsed_since_oldest + 1.0)
            
            if log_callback:
                log_callback(f"⏱️ Limit {self.max_rpm} RPM aktif ({len(self.request_timestamps)}/{self.max_rpm} request). Menunggu {int(sleep_needed)}s...", "active")
            
            step = 0.5
            total_slept = 0.0
            while total_slept < sleep_needed:
                if stop_check_callback and stop_check_callback():
                    return False
                time.sleep(min(step, sleep_needed - total_slept))
                total_slept += step
            
            now = time.time()
            self.request_timestamps = [t for t in self.request_timestamps if now - t < 60.0]

        self.request_timestamps.append(time.time())
        return True

# ==========================================
# MIRAVA API CLIENT & IMAGE DOWNLOADER
# ==========================================
class MiravaAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()
        self.base_url = BASE_URL.rstrip('/')
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "MiravaStudioClient/2.5"
        }

    def upload_reference_image(self, uploaded_file) -> str:
        url = f"{self.base_url}/api/public/v1/upload"
        files = {
            "image": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type or "image/png")
        }
        resp = requests.post(url, headers={"Authorization": f"Bearer {self.api_key}"}, files=files, timeout=60)
        
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Gagal mengunggah gambar referensi ({resp.status_code}): {resp.text}")
        
        data = resp.json()
        image_id = None
        if isinstance(data, dict):
            image_id = data.get("image_id") or data.get("id")
            if not image_id and "data" in data and isinstance(data["data"], dict):
                image_id = data["data"].get("image_id") or data["data"].get("id")
        
        if not image_id:
            raise RuntimeError(f"Respon upload tidak memiliki field image_id: {data}")
        return str(image_id)

    def get_models(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/public/v1/models"
        try:
            resp = requests.get(url, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return data.get("data") or data.get("models") or []
                elif isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    def create_generation_task(self, model_id: str, prompt: str, ratio: str,
                               quality: Optional[str] = None,
                               style: Optional[str] = None,
                               ref_image_ids: Optional[List[str]] = None,
                               log_callback = None,
                               stop_check_callback = None) -> str:
        url = f"{self.base_url}/api/public/v1/generate"
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
            **self.headers,
            "Content-Type": "application/json"
        }

        max_retries = 6
        base_delay = 12

        for attempt in range(max_retries):
            if stop_check_callback and stop_check_callback():
                raise InterruptedError("Batch dihentikan pengguna.")

            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
            except Exception as conn_err:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                raise conn_err

            if resp.status_code == 429:
                retry_header = resp.headers.get("Retry-After")
                try:
                    wait_s = int(retry_header) if retry_header else (base_delay * (attempt + 1))
                except Exception:
                    wait_s = base_delay * (attempt + 1)
                
                if log_callback:
                    log_callback(f"⏳ Rate Limit (429) tercapai. Menunggu {wait_s}s sebelum auto-retry ({attempt+1}/{max_retries})...", "active")
                
                total_w = 0.0
                while total_w < wait_s:
                    if stop_check_callback and stop_check_callback():
                        raise InterruptedError("Batch dihentikan pengguna.")
                    time.sleep(0.5)
                    total_w += 0.5
                continue

            if resp.status_code not in (200, 201, 202):
                raise RuntimeError(f"Gagal membuat tugas generasi ({resp.status_code}): {resp.text}")

            data = resp.json()
            generation_id = None
            if isinstance(data, dict):
                generation_id = data.get("generation_id") or data.get("id")
                if not generation_id and "data" in data and isinstance(data["data"], dict):
                    generation_id = data["data"].get("generation_id") or data["data"].get("id")

            if not generation_id:
                raise RuntimeError(f"Respon generate tidak menyertakan generation_id: {data}")
            return str(generation_id)

        raise RuntimeError(f"Gagal membuat tugas generasi (429): Batas RPM limit terlampaui setelah {max_retries} kali percobaan.")

    def check_task_status(self, generation_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/public/v1/generate/{generation_id}"
        resp = None
        for _ in range(3):
            try:
                resp = requests.get(url, headers=self.headers, timeout=30)
                if resp.status_code == 429:
                    time.sleep(5)
                    continue
                if resp.status_code != 200:
                    return {
                        "status": "error",
                        "error": f"HTTP {resp.status_code}: {resp.text}",
                        "urls": []
                    }
                break
            except Exception:
                time.sleep(2)
        
        if not resp or resp.status_code != 200:
            return {
                "status": "error",
                "error": "Gagal menghubungi server status render.",
                "urls": []
            }

        data = resp.json()
        status_val = "processing"
        urls = []
        error_msg = None

        if isinstance(data, dict):
            content = data.get("data", data)
            raw_status = str(content.get("status", "")).lower()

            if raw_status in ("success", "completed", "done", "succeeded"):
                status_val = "success"
                raw_urls = content.get("urls") or content.get("url") or []
                if isinstance(raw_urls, str):
                    urls = [raw_urls]
                elif isinstance(raw_urls, list):
                    urls = raw_urls
            elif raw_status in ("failed", "error", "rejected"):
                status_val = "failed"
                error_msg = content.get("error") or content.get("message") or "Unknown API generation error."
            else:
                status_val = "processing"
        
        return {
            "status": status_val,
            "urls": urls,
            "error": error_msg,
            "raw": data
        }

def download_remote_image(url: str, generation_id: str, index: int) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "")
            if "png" in content_type:
                ext = ".png"
            elif "webp" in content_type:
                ext = ".webp"
            else:
                ext = ".jpg"
            
            clean_gen_id = "".join(c for c in generation_id if c.isalnum() or c in "-_")
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{clean_gen_id}_{timestamp_str}_{index}{ext}"
            file_path = OUTPUT_DIR / filename

            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return str(file_path)
    except Exception as e:
        st.warning(f"Gagal mengunduh gambar ke penyimpanan lokal: {e}")
    return None

# ==========================================
# UI HELPER: PROMPT STATUS LIST IN MONITOR
# ==========================================
def render_monitor_prompt_status(items: List[Dict[str, Any]], container):
    """Renders clean prompt rows with live status badges right inside MONITOR & METRICS."""
    with container:
        if not items:
            return
        
        st.markdown('<div class="section-label"><span>STATUS TIAP PROMPT (LIVE MONITOR)</span></div>', unsafe_allow_html=True)
        
        rows_html = []
        for it in items:
            st_type = it.get("status", "MENUNGGU")
            badge_color = "#94a3b8"
            badge_bg = "rgba(148, 163, 184, 0.1)"
            badge_border = "#334155"
            status_text = "⏳ Menunggu"

            if st_type == "SELESAI":
                badge_color = "#34d399"
                badge_bg = "rgba(16, 185, 129, 0.15)"
                badge_border = "#10b981"
                dur = f" • {it.get('time', '')}" if it.get("time") else ""
                status_text = f"✅ Selesai{dur}"
            elif st_type in ("RENDERING", "SUBMIT"):
                badge_color = "#67e8f9"
                badge_bg = "rgba(6, 182, 212, 0.15)"
                badge_border = "#06b6d4"
                dur = f" ({it.get('time', '')})" if it.get("time") else ""
                status_text = f"🎨 Render{dur}"
            elif st_type == "LIMIT_RPM":
                badge_color = "#e5fe00"
                badge_bg = "rgba(229, 254, 0, 0.12)"
                badge_border = "#e5fe00"
                status_text = "⏱️ Limit 5 RPM"
            elif st_type == "GAGAL":
                badge_color = "#f87171"
                badge_bg = "rgba(239, 68, 68, 0.15)"
                badge_border = "#ef4444"
                status_text = "❌ Gagal"
            elif st_type == "DIBATALKAN":
                badge_color = "#fb923c"
                badge_bg = "rgba(251, 146, 60, 0.15)"
                badge_border = "#f97316"
                status_text = "🛑 Dibatalkan"

            p_text = it.get("prompt", "")
            p_short = (p_text[:50] + "...") if len(p_text) > 50 else p_text

            row = f'<div style="background:#0b0f19; border:1px solid #1e293b; border-left:3px solid {badge_border}; padding:0.42rem 0.65rem; border-radius:3px; margin-bottom:0.35rem; display:flex; justify-content:space-between; align-items:center; font-family:\'JetBrains Mono\',monospace;"><div style="font-size:0.78rem; color:#f1f5f9; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:65%;"><b>[#{it.get("index")}]</b> {p_short}</div><div style="font-size:0.72rem; font-weight:700; color:{badge_color}; background:{badge_bg}; border:1px solid {badge_border}; padding:0.18rem 0.5rem; border-radius:3px; white-space:nowrap;">{status_text}</div></div>'
            if it.get("error"):
                row += f'<div style="color:#f87171; font-size:0.72rem; font-family:\'JetBrains Mono\',monospace; padding-left:0.5rem; margin-bottom:0.35rem;">❌ {it.get("error")}</div>'
            rows_html.append(row)

        full_html = f'<div style="max-height:220px; overflow-y:auto; margin-bottom:0.75rem;">' + "".join(rows_html) + '</div>'
        st.markdown(full_html, unsafe_allow_html=True)

# ==========================================
# STREAMLIT UI APPLICATION
# ==========================================
def main():
    st.set_page_config(
        page_title="BATCH GENERATE • MIRAVA STUDIO",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

    init_db()

    saved_key = get_config("api_key", os.getenv("MIRAVA_API_KEY", ""))
    saved_rpm = int(get_config("max_rpm", "5"))

    if "api_key" not in st.session_state:
        st.session_state["api_key"] = saved_key
    if "max_rpm" not in st.session_state:
        st.session_state["max_rpm"] = saved_rpm
    if "rate_limiter" not in st.session_state:
        st.session_state["rate_limiter"] = RPMRateLimiter(max_rpm=st.session_state["max_rpm"])
    if "selected_model" not in st.session_state:
        st.session_state["selected_model"] = "nano-banana-2"
    if "selected_ratio" not in st.session_state:
        st.session_state["selected_ratio"] = "1:1"
    if "selected_style" not in st.session_state:
        st.session_state["selected_style"] = "TANPA GAYA"
    if "batch_logs" not in st.session_state:
        st.session_state["batch_logs"] = []
    if "prompt_tracker_items" not in st.session_state:
        st.session_state["prompt_tracker_items"] = []
    if "batch_stats" not in st.session_state:
        st.session_state["batch_stats"] = {
            "total": 0, "success": 0, "failed": 0, "cancelled": 0, "active": 0, "remaining": 0
        }
    if "latest_images" not in st.session_state:
        st.session_state["latest_images"] = []
    if "nav_view" not in st.session_state:
        st.session_state["nav_view"] = "BATCH"

    # Clean Dark Cyberpunk CSS
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Rajdhani:wght@500;600;700&display=swap');

        html, body, [class*="css"] {
            font-family: 'Rajdhani', -apple-system, sans-serif;
            background-color: #07080a !important;
            color: #d1d5db;
        }

        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
            max-width: 98% !important;
        }

        .top-meta-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.78rem;
            color: #94a3b8;
            letter-spacing: 0.1em;
            margin-bottom: 0.25rem;
            padding-bottom: 0.25rem;
            border-bottom: 1px solid #1e2430;
        }

        .main-brand-title {
            font-family: 'Chakra Petch', sans-serif;
            font-size: 2.5rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            line-height: 1.1;
            margin-top: 0.4rem;
            margin-bottom: 1rem;
            text-transform: uppercase;
        }
        .main-brand-title .white-text { color: #ffffff; }
        .main-brand-title .yellow-text { color: #e5fe00; }

        .section-label {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.76rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            color: #94a3b8;
            text-transform: uppercase;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .metric-row {
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            border: 1px solid #1e293b;
            background: #0c0f17;
            margin-bottom: 1rem;
            border-radius: 4px;
        }
        .metric-box {
            padding: 0.75rem 0.3rem;
            text-align: center;
            border-right: 1px solid #1e293b;
        }
        .metric-box:last-child {
            border-right: none;
        }
        .metric-val {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.4rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 0.2rem;
        }
        .metric-lbl {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.65rem;
            color: #64748b;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        .terminal-panel {
            background-color: #090c12;
            border: 1px solid #1e2430;
            border-radius: 4px;
            padding: 1rem;
            min-height: 300px;
        }

        .yellow-badge {
            background: #e5fe00;
            color: #000000;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem;
            font-weight: 700;
            padding: 0.25rem 0.55rem;
            border-radius: 3px;
            display: inline-block;
        }

        div[data-baseweb="select"] > div {
            background-color: #0f141f !important;
            border: 1px solid #232d3f !important;
            border-radius: 4px !important;
            color: #ffffff !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-size: 0.88rem !important;
        }
        .stTextArea textarea {
            background-color: #0a0d14 !important;
            border: 1px solid #1e2638 !important;
            border-radius: 4px !important;
            color: #f8fafc !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-size: 0.88rem !important;
            line-height: 1.6 !important;
            padding: 0.75rem !important;
        }
        .stTextArea textarea:focus {
            border-color: #e5fe00 !important;
            box-shadow: 0 0 0 1px #e5fe00 !important;
        }

        .stButton button {
            border-radius: 3px !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-weight: 700 !important;
            font-size: 0.82rem !important;
            letter-spacing: 0.05em !important;
            text-transform: uppercase !important;
            padding: 0.45rem 0.75rem !important;
            line-height: 1.3 !important;
            white-space: normal !important;
            word-break: break-word !important;
            min-height: 42px !important;
        }
        button[kind="primary"] {
            background-color: #e5fe00 !important;
            color: #000000 !important;
            border: 1px solid #e5fe00 !important;
        }
        button[kind="primary"]:hover {
            background-color: #f2ff4f !important;
            box-shadow: 0 0 12px rgba(229, 254, 0, 0.4) !important;
        }

        .stop-btn button {
            background-color: #dc2626 !important;
            color: #ffffff !important;
            border: 1px solid #ef4444 !important;
        }
        .stop-btn button:hover {
            background-color: #ef4444 !important;
            box-shadow: 0 0 12px rgba(239, 68, 68, 0.5) !important;
        }

        .logs-empty {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 240px;
            color: #1e293b;
            font-family: 'JetBrains Mono', monospace;
        }
        .logs-empty-number {
            font-size: 4rem;
            font-weight: 700;
            line-height: 1;
            margin-bottom: 0.5rem;
            color: #172033;
        }
        .logs-empty-text {
            font-size: 0.78rem;
            letter-spacing: 0.15em;
            color: #334155;
            text-transform: uppercase;
        }

        .log-entry {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            padding: 0.35rem 0.55rem;
            margin-bottom: 0.25rem;
            border-left: 3px solid #334155;
            background: rgba(255,255,255,0.02);
            color: #cbd5e1;
            line-height: 1.4;
        }
        .log-entry.success { border-left-color: #10b981; color: #34d399; }
        .log-entry.failed { border-left-color: #ef4444; color: #f87171; }
        .log-entry.active { border-left-color: #e5fe00; color: #e5fe00; }
        </style>
    """, unsafe_allow_html=True)

    # ------------------------------------------
    # TOP NAVIGATION BAR
    # ------------------------------------------
    nav_col1, nav_col2, nav_info = st.columns([1.6, 2.0, 3.2])
    
    with nav_col1:
        is_b = (st.session_state["nav_view"] == "BATCH")
        if st.button("⚡ BATCH GENERATE", key="top_nav_b", type="primary" if is_b else "secondary", use_container_width=True):
            st.session_state["nav_view"] = "BATCH"
            st.rerun()
            
    with nav_col2:
        is_s = (st.session_state["nav_view"] == "SETTINGS")
        if st.button("⚙️ PENGATURAN", key="top_nav_s", type="primary" if is_s else "secondary", use_container_width=True):
            st.session_state["nav_view"] = "SETTINGS"
            st.rerun()

    with nav_info:
        api_status_icon = "🟢" if st.session_state["api_key"] else "🔴"
        api_status_txt = "Tersimpan" if st.session_state["api_key"] else "Belum Diisi"
        gdrive_status = "🟢 ON" if is_gdrive_sync_enabled() else "⚪ OFF"
        st.markdown(f"""
            <div style="text-align:right; font-family:'JetBrains Mono',monospace; font-size:0.75rem; padding-top:0.6rem; color:#94a3b8;">
                <span>API: <b>{api_status_icon} {api_status_txt}</b></span> &nbsp;•&nbsp; 
                <span>LIMIT: <b style="color:#e5fe00;">{st.session_state['max_rpm']} RPM</b></span> &nbsp;•&nbsp;
                <span>G-DRIVE: <b>{gdrive_status}</b></span>
            </div>
        """, unsafe_allow_html=True)

    # ---------------------------------------------------------
    # VIEW 1: BATCH GENERATE
    # ---------------------------------------------------------
    if st.session_state["nav_view"] == "BATCH":
        left_col, right_col = st.columns([1.18, 0.82], gap="large")

        # ==========================================
        # LEFT PANEL: FORM CONTROLS
        # ==========================================
        with left_col:
            active_model_spec = MODEL_MATRIX[st.session_state["selected_model"]]
            quality_info = st.session_state.get("selected_quality", active_model_spec['qualities'][0] if active_model_spec['qualities'] else 'AUTO')
            meta_str = f"{active_model_spec['name']} • {st.session_state['selected_ratio']} • {st.session_state['selected_style']} • {quality_info}"

            st.markdown(f"""
                <div class="top-meta-bar">
                    <span>MODE 01 — BATCH RUNNER</span>
                    <span>{meta_str}</span>
                </div>
                <div class="main-brand-title">
                    <span class="white-text">BATCH</span> <span class="yellow-text">GENERATE</span>
                </div>
            """, unsafe_allow_html=True)

            # MODEL SELECTION
            st.markdown('<div class="section-label"><span>PILIH MODEL</span></div>', unsafe_allow_html=True)
            model_keys = list(MODEL_MATRIX.keys())
            
            m_cols_r1 = st.columns(4)
            m_cols_r2 = st.columns(3)
            
            for idx, m_key in enumerate(model_keys[:4]):
                is_sel = (st.session_state["selected_model"] == m_key)
                with m_cols_r1[idx]:
                    if st.button(
                        f"● {MODEL_MATRIX[m_key]['name']}" if is_sel else MODEL_MATRIX[m_key]['name'],
                        key=f"m_btn_{m_key}",
                        type="primary" if is_sel else "secondary",
                        use_container_width=True
                    ):
                        st.session_state["selected_model"] = m_key
                        if not MODEL_MATRIX[m_key]["qualities"]:
                            st.session_state["selected_quality"] = None
                        else:
                            st.session_state["selected_quality"] = MODEL_MATRIX[m_key]["qualities"][0]
                        st.rerun()

            for idx, m_key in enumerate(model_keys[4:]):
                is_sel = (st.session_state["selected_model"] == m_key)
                with m_cols_r2[idx]:
                    if st.button(
                        f"● {MODEL_MATRIX[m_key]['name']}" if is_sel else MODEL_MATRIX[m_key]['name'],
                        key=f"m_btn_{m_key}",
                        type="primary" if is_sel else "secondary",
                        use_container_width=True
                    ):
                        st.session_state["selected_model"] = m_key
                        if not MODEL_MATRIX[m_key]["qualities"]:
                            st.session_state["selected_quality"] = None
                        else:
                            st.session_state["selected_quality"] = MODEL_MATRIX[m_key]["qualities"][0]
                        st.rerun()

            # QUALITY / RESOLUTION
            if active_model_spec["qualities"]:
                st.markdown('<div class="section-label"><span>KUALITAS / RESOLUSI</span></div>', unsafe_allow_html=True)
                q_cols = st.columns(len(active_model_spec["qualities"]))
                for q_idx, q_val in enumerate(active_model_spec["qualities"]):
                    curr_q = st.session_state.get("selected_quality", active_model_spec["qualities"][0])
                    is_q_sel = (curr_q == q_val)
                    with q_cols[q_idx]:
                        if st.button(
                            f"● {q_val}" if is_q_sel else q_val,
                            key=f"q_btn_{q_val}",
                            type="primary" if is_q_sel else "secondary",
                            use_container_width=True
                        ):
                            st.session_state["selected_quality"] = q_val
                            st.rerun()

            # ASPECT RATIO SELECTION
            st.markdown('<div class="section-label"><span>ASPECT RATIO</span></div>', unsafe_allow_html=True)
            r_cols1 = st.columns(4)
            r_cols2 = st.columns(4)
            
            for idx, r_val in enumerate(RATIO_OPTIONS[:4]):
                is_r_sel = (st.session_state["selected_ratio"] == r_val)
                with r_cols1[idx]:
                    if st.button(r_val, key=f"r_btn_{r_val}", type="primary" if is_r_sel else "secondary", use_container_width=True):
                        st.session_state["selected_ratio"] = r_val
                        st.rerun()

            for idx, r_val in enumerate(RATIO_OPTIONS[4:]):
                is_r_sel = (st.session_state["selected_ratio"] == r_val)
                with r_cols2[idx]:
                    if st.button(r_val, key=f"r_btn_{r_val}", type="primary" if is_r_sel else "secondary", use_container_width=True):
                        st.session_state["selected_ratio"] = r_val
                        st.rerun()

            # GAYA GAMBAR (STYLE) - Default: TANPA GAYA
            if active_model_spec["support_style"]:
                st.markdown('<div class="section-label"><span>GAYA GAMBAR (DEFAULT: TANPA GAYA)</span></div>', unsafe_allow_html=True)
                
                quick_styles = ["TANPA GAYA", "DINAMIS", "POTRET SINEMATIK", "ILUSTRASI", "RENDER 3D", "FOTO WARNA"]
                q_s_cols = st.columns(len(quick_styles))
                for qs_idx, qs_val in enumerate(quick_styles):
                    is_qs_sel = (st.session_state["selected_style"] == qs_val)
                    with q_s_cols[qs_idx]:
                        if st.button(qs_val, key=f"qs_btn_{qs_val}", type="primary" if is_qs_sel else "secondary", use_container_width=True):
                            st.session_state["selected_style"] = qs_val
                            st.rerun()

                sel_style_idx = STYLE_OPTIONS.index(st.session_state["selected_style"]) if st.session_state["selected_style"] in STYLE_OPTIONS else 0
                chosen_style = st.selectbox(
                    "Pilihan Style Lengkap:",
                    options=STYLE_OPTIONS,
                    index=sel_style_idx,
                    label_visibility="collapsed",
                    key="style_selectbox"
                )
                if chosen_style != st.session_state["selected_style"]:
                    st.session_state["selected_style"] = chosen_style
                    st.rerun()
            else:
                st.caption("🔒 *Model ini beroperasi tanpa filter gaya (Mode Teks Murni).*")

            # REFERENCE IMAGE UPLOADER
            max_r = active_model_spec["max_refs"]
            st.markdown(f'<div class="section-label"><span>GAMBAR REFERENSI — (MAKS {max_r})</span></div>', unsafe_allow_html=True)
            
            uploaded_refs = []
            if max_r > 0:
                uploaded_refs = st.file_uploader(
                    "Pilih file gambar referensi",
                    type=["png", "jpg", "jpeg", "webp"],
                    accept_multiple_files=True,
                    label_visibility="collapsed",
                    key="clean_ref_uploader"
                )
                if uploaded_refs and len(uploaded_refs) > max_r:
                    st.warning(f"Maksimal {max_r} gambar referensi untuk {active_model_spec['name']}. Hanya {max_r} pertama yang akan diproses.")
                    uploaded_refs = uploaded_refs[:max_r]
            else:
                st.caption("🔒 *Model ini adalah text-to-image murni (tanpa gambar referensi).*")

            # PROMPTS SECTION (BATCH RUNNER)
            st.markdown("""
                <div class="section-label">
                    <span>DAFTAR PROMPT (SATU PROMPT PER BARIS)</span>
                </div>
            """, unsafe_allow_html=True)

            txt_col1, _ = st.columns([0.45, 0.55])
            with txt_col1:
                uploaded_txt = st.file_uploader("Upload .txt file", type=["txt"], key="clean_txt_prompt_uploader", label_visibility="collapsed")
            
            default_prompts = (
                "KOTA CYBERPUNK DI TENGAH MALAM\n"
                "DANAU PEGUNUNGAN YANG TENANG SAAT FAJAR\n"
                "POLA GEOMETRIS ABSTRAK BERWARNA EMAS"
            )

            if uploaded_txt is not None:
                try:
                    default_prompts = uploaded_txt.read().decode("utf-8")
                except Exception:
                    pass

            prompts_raw = st.text_area(
                "Batch Prompts Input",
                value=default_prompts,
                height=140,
                label_visibility="collapsed",
                placeholder="Tuliskan satu baris prompt untuk setiap gambar yang ingin digenerate...",
                key="clean_batch_prompts_input"
            )

            prompt_lines = [p.strip() for p in prompts_raw.strip().split("\n") if p.strip()]
            longest_char = max([len(p) for p in prompt_lines]) if prompt_lines else 0
            max_allowed = active_model_spec["max_prompt_chars"] or 1200

            st.markdown(f"""
                <div style="display:flex; justify-content:space-between; font-family:'JetBrains Mono',monospace; font-size:0.75rem; color:#94a3b8; margin-top:0.3rem; margin-bottom:0.75rem;">
                    <span>📊 <b>{len(prompt_lines)}</b> PROMPT TERDETEKSI</span>
                    <span>📏 TERPANJANG: <b>{longest_char} / {max_allowed}</b> KARAKTER</span>
                </div>
            """, unsafe_allow_html=True)

            # Ensure prompt tracker items are synchronized
            if not st.session_state["prompt_tracker_items"] or len(st.session_state["prompt_tracker_items"]) != len(prompt_lines):
                st.session_state["prompt_tracker_items"] = [
                    {
                        "index": idx + 1,
                        "prompt": p_text,
                        "status": "MENUNGGU",
                        "badge": "⏳ MENUNGGU",
                        "time": "",
                        "error": None,
                        "file": None
                    }
                    for idx, p_text in enumerate(prompt_lines)
                ]

            # Storage & Cloud Status Indicator
            st_col1, st_col2 = st.columns([3.8, 1.0])
            with st_col1:
                gdrive_note = " + ☁️ Google Drive" if is_gdrive_sync_enabled() else ""
                st.markdown(f"""
                    <div style="font-family:'JetBrains Mono',monospace; font-size:0.76rem; color:#94a3b8; padding-top:0.4rem;">
                        <span style="color:#e5fe00;">■</span> <b>PENYIMPANAN:</b> <code>outputs/*.png</code>{gdrive_note}
                    </div>
                """, unsafe_allow_html=True)
            with st_col2:
                if st.button("⚙️ ATUR", key="btn_open_atur_main", use_container_width=True):
                    st.session_state["nav_view"] = "SETTINGS"
                    st.rerun()

            # Direct API Key Input if not yet set
            has_api_key = bool(st.session_state["api_key"])
            if not has_api_key:
                st.markdown("""
                    <div style="border: 1px solid #f59e0b; background: rgba(245, 158, 11, 0.08); padding: 0.6rem; border-radius: 4px; margin-bottom: 0.75rem;">
                        <span style="color:#fbbf24; font-family:'JetBrains Mono',monospace; font-size:0.78rem; font-weight:700;">⚠️ API KEY BELUM TERSIMPAN</span>
                    </div>
                """, unsafe_allow_html=True)
                entered_key = st.text_input(
                    "Masukkan Mirava API Key (Otomatis Disimpan Permanen):",
                    type="password",
                    placeholder="mirava_sk_...",
                    key="input_direct_api_key"
                )
                if entered_key:
                    st.session_state["api_key"] = entered_key
                    set_config("api_key", entered_key)
                    st.success("✅ API Key berhasil disimpan permanen ke database!")
                    st.rerun()

            can_run = has_api_key and len(prompt_lines) > 0
            if active_model_spec["max_prompt_chars"] and longest_char > active_model_spec["max_prompt_chars"]:
                can_run = False
                st.error(f"Salah satu prompt melebihi batas maksimum {active_model_spec['max_prompt_chars']} karakter.")

            # ACTION BUTTONS: RUN BATCH & STOP BATCH
            action_btn_col1, action_btn_col2, rate_info_col = st.columns([0.38, 0.32, 0.30])
            
            with action_btn_col1:
                run_batch_btn = st.button(
                    "⚡ RUN BATCH",
                    type="primary",
                    use_container_width=True,
                    disabled=not can_run
                )

            with action_btn_col2:
                st.markdown('<div class="stop-btn">', unsafe_allow_html=True)
                stop_batch_btn = st.button(
                    "🛑 STOP BATCH",
                    key="btn_trigger_stop",
                    use_container_width=True
                )
                st.markdown('</div>', unsafe_allow_html=True)
                if stop_batch_btn:
                    STOP_FLAG_FILE.touch()
                    st.warning("🛑 Sinyal berhenti dikirim ke proses batch...")

            with rate_info_col:
                if has_api_key:
                    st.markdown(f"""
                        <div style="font-family:'JetBrains Mono',monospace; font-size:0.74rem; color:#94a3b8; padding-top:0.45rem;">
                            🛡️ <b>Rate Limiter:</b> {st.session_state['max_rpm']} RPM (Auto-Wait)
                        </div>
                    """, unsafe_allow_html=True)

        # ==========================================
        # RIGHT PANEL: MONITOR & METRICS
        # ==========================================
        with right_col:
            st.markdown('<div class="section-label"><span>MONITOR & METRICS</span></div>', unsafe_allow_html=True)
            
            stats = st.session_state["batch_stats"]
            st.markdown(f"""
                <div class="metric-row">
                    <div class="metric-box">
                        <div class="metric-val">{stats['total']}</div>
                        <div class="metric-lbl">TOTAL</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-val" style="color:#34d399;">{stats['success']}</div>
                        <div class="metric-lbl">SUCCESS</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-val" style="color:#f87171;">{stats['failed']}</div>
                        <div class="metric-lbl">FAILED</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-val" style="color:#fb923c;">{stats['cancelled']}</div>
                        <div class="metric-lbl">CANCELLED</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-val" style="color:#e5fe00;">{stats['active']}</div>
                        <div class="metric-lbl">ACTIVE</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-val">{stats['remaining']}</div>
                        <div class="metric-lbl">REMAINING</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            # STATUS TIAP PROMPT INSIDE MONITOR & METRICS
            prompt_status_container = st.empty()
            render_monitor_prompt_status(st.session_state["prompt_tracker_items"], prompt_status_container)

            # LIVE TERMINAL LOGS
            st.markdown('<div class="section-label"><span>LIVE TERMINAL LOGS</span></div>', unsafe_allow_html=True)
            logs_container = st.empty()

            def render_logs_ui():
                if not st.session_state["batch_logs"]:
                    logs_container.markdown("""
                        <div class="terminal-panel logs-empty">
                            <div class="logs-empty-number">0</div>
                            <div class="logs-empty-text">LOGS WILL APPEAR HERE</div>
                        </div>
                    """, unsafe_allow_html=True)
                else:
                    log_html = '<div class="terminal-panel" style="max-height: 300px; overflow-y: auto;">'
                    for l in st.session_state["batch_logs"]:
                        log_html += f'<div class="log-entry {l.get("type", "")}">[{l["time"]}] {l["text"]}</div>'
                    log_html += '</div>'
                    logs_container.markdown(log_html, unsafe_allow_html=True)

            render_logs_ui()

            # Completed Image Output Preview
            if st.session_state["latest_images"]:
                st.markdown('<div class="section-label"><span>HASIL GAMBAR GENERASI TERAKHIR</span></div>', unsafe_allow_html=True)
                img_cols = st.columns(min(len(st.session_state["latest_images"]), 2))
                for idx, img_path in enumerate(st.session_state["latest_images"]):
                    with img_cols[idx % 2]:
                        if Path(img_path).exists():
                            st.image(img_path, use_container_width=True)
                            with open(img_path, "rb") as f:
                                st.download_button(
                                    label=f"Unduh {Path(img_path).name}",
                                    data=f.read(),
                                    file_name=Path(img_path).name,
                                    mime="image/png",
                                    key=f"dl_latest_{idx}",
                                    use_container_width=True
                                )

        # ==========================================
        # EXECUTION ENGINE: BATCH PROCESSOR WITH STOP & TRACKER
        # ==========================================
        if run_batch_btn:
            if STOP_FLAG_FILE.exists():
                STOP_FLAG_FILE.unlink()

            client = MiravaAPIClient(st.session_state["api_key"])
            limiter = st.session_state["rate_limiter"]
            limiter.max_rpm = st.session_state["max_rpm"]
            total_items = len(prompt_lines)
            
            st.session_state["batch_stats"] = {
                "total": total_items,
                "success": 0,
                "failed": 0,
                "cancelled": 0,
                "active": 0,
                "remaining": total_items
            }
            st.session_state["batch_logs"] = []
            st.session_state["latest_images"] = []

            st.session_state["prompt_tracker_items"] = [
                {
                    "index": idx + 1,
                    "prompt": p_text,
                    "status": "MENUNGGU",
                    "badge": "⏳ MENUNGGU",
                    "time": "",
                    "error": None,
                    "file": None
                }
                for idx, p_text in enumerate(prompt_lines)
            ]

            def is_stop_requested() -> bool:
                return STOP_FLAG_FILE.exists()

            def append_log(text: str, log_type: str = ""):
                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                st.session_state["batch_logs"].append({"time": timestamp, "text": text, "type": log_type})
                render_logs_ui()

            def update_item_status(idx: int, status: str, badge: str, time_str: str = "", err: str = None, file_p: str = None):
                if 0 <= idx < len(st.session_state["prompt_tracker_items"]):
                    st.session_state["prompt_tracker_items"][idx]["status"] = status
                    st.session_state["prompt_tracker_items"][idx]["badge"] = badge
                    if time_str:
                        st.session_state["prompt_tracker_items"][idx]["time"] = time_str
                    if err:
                        st.session_state["prompt_tracker_items"][idx]["error"] = err
                    if file_p:
                        st.session_state["prompt_tracker_items"][idx]["file"] = file_p
                    render_monitor_prompt_status(st.session_state["prompt_tracker_items"], prompt_status_container)

            append_log(f"Memulai tugas Batch Generate ({total_items} prompt) • Limit {limiter.max_rpm} RPM.", "active")
            render_monitor_prompt_status(st.session_state["prompt_tracker_items"], prompt_status_container)

            # Upload Reference Images if present
            ref_image_ids = []
            if uploaded_refs:
                append_log(f"Mengunggah {len(uploaded_refs)} gambar referensi...")
                for r_idx, ref_f in enumerate(uploaded_refs):
                    if is_stop_requested():
                        break
                    try:
                        rid = client.upload_reference_image(ref_f)
                        ref_image_ids.append(rid)
                        append_log(f"Referensi #{r_idx+1} terunggah (ID: {rid})", "active")
                    except Exception as e:
                        append_log(f"Gagal upload referensi #{r_idx+1}: {e}", "failed")

            # Sequential Batch Loop
            cancelled_by_user = False
            for i, p_text in enumerate(prompt_lines):
                if is_stop_requested():
                    cancelled_by_user = True
                    break

                st.session_state["batch_stats"]["active"] = 1
                st.session_state["batch_stats"]["remaining"] = total_items - i
                
                selected_model = st.session_state["selected_model"]
                selected_ratio = st.session_state["selected_ratio"]
                selected_quality = st.session_state.get("selected_quality", None)
                if selected_quality and not MODEL_MATRIX[selected_model]["qualities"]:
                    selected_quality = None
                selected_style = st.session_state["selected_style"]
                if not MODEL_MATRIX[selected_model]["support_style"]:
                    selected_style = None

                # Enforce Rate Limiter Slot Delay
                update_item_status(i, "LIMIT_RPM", "⏱️ CEK SLOT RPM")
                slot_ok = limiter.wait_for_slot(log_callback=append_log, stop_check_callback=is_stop_requested)
                
                if not slot_ok or is_stop_requested():
                    cancelled_by_user = True
                    break

                prompt_start_time = time.time()
                update_item_status(i, "SUBMIT", "🚀 MENGIRIM TUGAS")
                append_log(f"[{i+1}/{total_items}] Mengirim prompt: \"{p_text[:45]}...\"", "active")

                try:
                    # Submit generate task
                    gen_id = client.create_generation_task(
                        model_id=selected_model,
                        prompt=p_text,
                        ratio=selected_ratio,
                        quality=selected_quality,
                        style=selected_style,
                        ref_image_ids=ref_image_ids if ref_image_ids else None,
                        log_callback=append_log,
                        stop_check_callback=is_stop_requested
                    )
                    append_log(f"Tugas diterima: ID `{gen_id}`. Memulai polling...", "active")
                    update_item_status(i, "RENDERING", "🎨 RENDERING", time_str="0s")

                    # Record initial state in SQLite
                    record_generation_start(
                        generation_id=gen_id,
                        model_id=selected_model,
                        prompt=p_text,
                        ratio=selected_ratio,
                        quality=selected_quality,
                        style=selected_style,
                        parameters={"ratio": selected_ratio, "quality": selected_quality, "style": selected_style}
                    )

                    # Polling Loop (Safe 8s interval)
                    start_t = time.time()
                    success_urls = []
                    while time.time() - start_t < 300:
                        if is_stop_requested():
                            cancelled_by_user = True
                            break

                        status_res = client.check_task_status(gen_id)
                        c_status = status_res.get("status")
                        elapsed_s = int(time.time() - prompt_start_time)
                        update_item_status(i, "RENDERING", "🎨 RENDERING", time_str=f"{elapsed_s}s")

                        if c_status == "success":
                            success_urls = status_res.get("urls", [])
                            break
                        elif c_status in ("failed", "error"):
                            err_str = str(status_res.get("error", ""))
                            if "429" in err_str or "rate" in err_str.lower():
                                append_log("⏳ Polling rate limit, menunggu 10s...", "active")
                                time.sleep(10)
                                continue
                            raise RuntimeError(err_str or "Generation failed on server.")
                        
                        # Wait 8s with periodic stop check
                        for _ in range(16):
                            if is_stop_requested():
                                cancelled_by_user = True
                                break
                            time.sleep(0.5)

                    if cancelled_by_user:
                        break

                    if not success_urls:
                        raise TimeoutError("Render timeout (melebihi 5 menit).")

                    # Download locally
                    saved_files = []
                    for u_idx, u in enumerate(success_urls):
                        loc_p = download_remote_image(u, gen_id, u_idx)
                        if loc_p:
                            saved_files.append(loc_p)
                            st.session_state["latest_images"].append(loc_p)

                            # Upload to Google Drive if enabled
                            if is_gdrive_sync_enabled():
                                try:
                                    append_log(f"[{i+1}/{total_items}] ☁️ Mengunggah ke Google Drive...", "active")
                                    if upload_to_gdrive(loc_p, log_callback=append_log):
                                        append_log(f"[{i+1}/{total_items}] ☁️ Berhasil tersimpan di Google Drive!", "success")
                                except Exception as gd_err:
                                    append_log(f"[{i+1}/{total_items}] ⚠️ Gagal simpan ke G-Drive: {gd_err}", "failed")

                    update_generation_complete(
                        generation_id=gen_id,
                        status="success",
                        remote_urls=success_urls,
                        local_paths=saved_files
                    )
                    
                    total_dur = int(time.time() - prompt_start_time)
                    st.session_state["batch_stats"]["success"] += 1
                    update_item_status(i, "SELESAI", "✅ SELESAI", time_str=f"{total_dur}s", file_p=saved_files[0] if saved_files else None)
                    append_log(f"[{i+1}/{total_items}] Berhasil ({total_dur}s)! File tersimpan di outputs/", "success")

                except InterruptedError:
                    cancelled_by_user = True
                    break
                except Exception as ex:
                    total_dur = int(time.time() - prompt_start_time)
                    st.session_state["batch_stats"]["failed"] += 1
                    update_item_status(i, "GAGAL", "❌ GAGAL", time_str=f"{total_dur}s", err=str(ex))
                    append_log(f"[{i+1}/{total_items}] Gagal: {str(ex)}", "failed")

            # Handle cancellation if requested
            if cancelled_by_user:
                remaining_count = 0
                for rem_idx in range(len(st.session_state["prompt_tracker_items"])):
                    item = st.session_state["prompt_tracker_items"][rem_idx]
                    if item["status"] in ("MENUNGGU", "LIMIT_RPM", "SUBMIT"):
                        item["status"] = "DIBATALKAN"
                        item["badge"] = "🛑 DIBATALKAN"
                        remaining_count += 1
                st.session_state["batch_stats"]["cancelled"] += remaining_count
                append_log(f"🛑 Batch dihentikan oleh pengguna. {remaining_count} prompt dibatalkan.", "failed")
                render_monitor_prompt_status(st.session_state["prompt_tracker_items"], prompt_status_container)

            if STOP_FLAG_FILE.exists():
                STOP_FLAG_FILE.unlink()

            st.session_state["batch_stats"]["active"] = 0
            st.session_state["batch_stats"]["remaining"] = 0
            append_log("Pemrosesan antrean Batch Generate selesai.", "active")
            st.rerun()

    # ---------------------------------------------------------
    # VIEW 2: PENGATURAN
    # ---------------------------------------------------------
    elif st.session_state["nav_view"] == "SETTINGS":
        s_head_col, s_close_col = st.columns([3.5, 1.4])
        with s_head_col:
            st.markdown('<div class="main-brand-title"><span class="white-text">PENGATURAN</span> <span class="yellow-text">APLIKASI</span></div>', unsafe_allow_html=True)
        with s_close_col:
            st.write("")
            if st.button("✕ TUTUP / KEMBALI KE BATCH", type="primary", use_container_width=True, key="btn_close_settings_top_view"):
                st.session_state["nav_view"] = "BATCH"
                st.rerun()
        
        # 1. API Key Config
        st.markdown('<div class="section-label"><span>1. KUNCI AUTENTIKASI (API KEY) — DISIMPAN PERMANEN</span></div>', unsafe_allow_html=True)
        current_saved_key = get_config("api_key", "")
        new_api_key = st.text_input(
            "Mirava Bearer API Key",
            value=current_saved_key,
            type="password",
            placeholder="mirava_sk_...",
            help="Kunci API Anda akan otomatis tersimpan secara permanen di SQLite database dan tidak perlu diisi ulang setiap restart.",
            key="settings_api_key_input"
        )
        if new_api_key != current_saved_key:
            set_config("api_key", new_api_key)
            st.session_state["api_key"] = new_api_key
            st.success("✅ API Key berhasil diperbarui dan disimpan secara permanen!")

        # 2. Rate Limit (Max RPM) Setting
        st.markdown('<div class="section-label"><span>2. BATAS KECEPATAN (MAX RPM GENERATE)</span></div>', unsafe_allow_html=True)
        current_saved_rpm = int(get_config("max_rpm", "5"))
        selected_rpm = st.slider(
            "Batas Maksimum Request Per Menit (RPM):",
            min_value=1,
            max_value=20,
            value=current_saved_rpm,
            step=1,
            help="Batas RPM akun Mirava Anda. Standar: 5 generate per menit."
        )
        if selected_rpm != current_saved_rpm:
            set_config("max_rpm", str(selected_rpm))
            st.session_state["max_rpm"] = selected_rpm
            st.session_state["rate_limiter"].max_rpm = selected_rpm
            st.success(f"✅ Batas RPM diperbarui ke {selected_rpm} generate per menit.")

        # 3. Google Drive Storage Integration
        st.markdown("---")
        st.markdown('<div class="section-label"><span>3. INTEGRASI PENYIMPANAN GOOGLE DRIVE (OPSIONAL)</span></div>', unsafe_allow_html=True)
        
        current_gdrive_enabled = is_gdrive_sync_enabled()
        enable_gdrive = st.checkbox(
            "Aktifkan Simpan Otomatis Gambar ke Google Drive",
            value=current_gdrive_enabled,
            help="Setiap gambar yang selesai digenerate akan otomatis diunggah langsung ke akun Google Drive Anda."
        )
        if enable_gdrive != current_gdrive_enabled:
            set_config("gdrive_enabled", "true" if enable_gdrive else "false")
            st.rerun()

        if enable_gdrive:
            st.info("Pilih metode integrasi Google Drive yang paling mudah bagi Anda:")
            current_mode = get_config("gdrive_mode", "webhook")
            selected_mode = st.radio(
                "Pilihan Metode Koneksi Google Drive:",
                options=["webhook", "service_account"],
                format_func=lambda m: "Metode 1: Google Apps Script Webhook (Paling Praktis, Tanpa Cloud Console)" if m == "webhook" else "Metode 2: Google Cloud Service Account (credentials.json)",
                index=0 if current_mode == "webhook" else 1
            )
            if selected_mode != current_mode:
                set_config("gdrive_mode", selected_mode)
                st.rerun()

            if selected_mode == "webhook":
                saved_webhook = get_config("gdrive_webhook_url", "")
                webhook_input = st.text_input(
                    "Google Apps Script Web App URL:",
                    value=saved_webhook,
                    placeholder="https://script.google.com/macros/s/.../exec",
                    help="URL Web App dari Google Apps Script yang memiliki izin menulis ke Google Drive Anda."
                )
                if webhook_input != saved_webhook:
                    set_config("gdrive_webhook_url", webhook_input)
                    st.success("✅ Webhook URL berhasil disimpan!")

                with st.expander("📖 Panduan Setup & Perbaikan Google Apps Script (Gratis & Mudah)", expanded=True):
                    st.markdown("""
                    **Kode Google Apps Script Lengkap (Otomatis simpan ke folder `Mirava Studio`):**
                    ```javascript
                    function doGet(e) {
                      return ContentService.createTextOutput(JSON.stringify({
                        status: 'online',
                        message: 'Google Apps Script Mirava Uploader Siap!'
                      })).setMimeType(ContentService.MimeType.JSON);
                    }

                    function doPost(e) {
                      try {
                        var data = JSON.parse(e.postData.contents);
                        var bytes = Utilities.base64Decode(data.base64);
                        var filename = data.filename || ('mirava_' + new Date().getTime() + '.png');
                        var mimeType = data.mimeType || 'image/png';
                        var blob = Utilities.newBlob(bytes, mimeType, filename);
                        
                        // Otomatis simpan ke folder 'Mirava Studio' di Google Drive Anda
                        var folders = DriveApp.getFoldersByName('Mirava Studio');
                        var targetFolder = folders.hasNext() ? folders.next() : DriveApp.createFolder('Mirava Studio');
                        var file = targetFolder.createFile(blob);
                        
                        return ContentService.createTextOutput(JSON.stringify({
                          status: 'success',
                          id: file.getId(),
                          name: file.getName(),
                          url: file.getUrl()
                        })).setMimeType(ContentService.MimeType.JSON);
                      } catch (err) {
                        return ContentService.createTextOutput(JSON.stringify({
                          status: 'error',
                          error: err.toString()
                        })).setMimeType(ContentService.MimeType.JSON);
                      }
                    }
                    ```

                    **⚠️ Cara Deploy / Update Kode (PENTING):**
                    1. Buka project Anda di [script.google.com](https://script.google.com).
                    2. Hapus seluruh isi kode lama, tempelkan kode di atas, lalu tekan **Simpan (Ctrl+S)**.
                    3. Klik menu **Deploy (Terapkan)** di pojok kanan atas:
                       - Jika **pertama kali**: Pilih **New deployment** > jenis **Web app** > Execute as: **Me** > Who has access: **Anyone** > Klik **Deploy**.
                       - Jika **sudah pernah deploy**: Pilih **Manage deployments** > Klik ikon **✏️ Pensil (Edit)** > Pada baris **Version**, pilih **New version (Versi baru)** > Klik **Deploy**.
                    4. Salin **Web app URL** yang berakhiran `/exec` dan tempelkan ke kolom input di atas.
                    5. Klik tombol **🧪 Uji Koneksi Google Drive** di bawah untuk memverifikasi!
                    """)

            elif selected_mode == "service_account":
                st.caption("Gunakan Google Cloud Service Account JSON key untuk akun korporat atau pengembang.")
                uploaded_json = st.file_uploader("Unggah File credentials.json:", type=["json"])
                current_json_str = get_config("gdrive_service_account_json", "")
                
                if uploaded_json is not None:
                    try:
                        content_str = uploaded_json.read().decode("utf-8")
                        json.loads(content_str)  # validate JSON
                        set_config("gdrive_service_account_json", content_str)
                        st.success("✅ File credentials.json berhasil diunggah dan disimpan.")
                    except Exception as err:
                        st.error(f"Format JSON tidak valid: {err}")
                
                folder_id_input = st.text_input(
                    "Target Google Drive Folder ID (Opsional, biarkan kosong untuk Root):",
                    value=get_config("gdrive_folder_id", ""),
                    placeholder="1A2B3C4D5E...",
                    help="ID folder Google Drive tempat gambar akan disimpan. Pastikan folder tersebut sudah di-share (Editor) ke email Service Account."
                )
                if folder_id_input != get_config("gdrive_folder_id", ""):
                    set_config("gdrive_folder_id", folder_id_input)
                    st.success("✅ Folder ID diperbarui!")

            # Test connection button
            if st.button("🧪 Uji Koneksi Google Drive"):
                test_file = OUTPUT_DIR / "test_gdrive_sync.png"
                try:
                    img = Image.new("RGB", (100, 100), color=(229, 254, 0))
                    img.save(test_file)
                    ok = upload_to_gdrive(str(test_file))
                    if ok:
                        st.success("🎉 Berhasil terhubung! File tes berhasil diunggah ke akun Google Drive Anda.")
                    else:
                        st.warning("⚠️ Upload selesai namun server tidak mengembalikan status sukses.")
                except Exception as test_err:
                    st.error(f"❌ Gagal terhubung ke Google Drive: {test_err}")
                finally:
                    if test_file.exists():
                        test_file.unlink()

        # 4. Storage and DB Status
        st.markdown("---")
        st.markdown('<div class="section-label"><span>4. STATUS PENYIMPANAN SISTEM & DATABASE</span></div>', unsafe_allow_html=True)
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            tot_h = len(fetch_history(search_query="", model_filter="All"))
            st.metric("Total Riwayat Database", f"{tot_h} entri")
        with sc2:
            out_files = list(OUTPUT_DIR.glob("*.*"))
            st.metric("Total File Gambar Lokal", f"{len(out_files)} file")
        with sc3:
            tot_mb = sum(f.stat().st_size for f in out_files) / (1024 * 1024) if out_files else 0
            st.metric("Ukuran Folder outputs/", f"{tot_mb:.2f} MB")

        st.markdown("---")
        if st.button("✕ TUTUP PENGATURAN & KEMBALI KE BATCH GENERATE", type="primary", use_container_width=True, key="btn_close_settings_bottom_view"):
            st.session_state["nav_view"] = "BATCH"
            st.rerun()

if __name__ == "__main__":
    main()
