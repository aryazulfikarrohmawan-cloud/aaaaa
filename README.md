# Mirava Imaginer Studio Web Application

Aplikasi web modern end-to-end berbasis Streamlit untuk berinteraksi dengan Imaginer RESTful API (Mirava Studio) dengan dukungan database lokal SQLite (`history.db`) dan penyimpanan gambar lokal (`outputs/`).

## 🚀 Fitur Utama
1. **Model Matrix Support Lengkap**:
   - `nano-banana-2`: Resolusi 1K / 2K / 4K, hingga 6 referensi gambar.
   - `gpt-image-2`: Kualitas low / medium, hingga 6 referensi gambar.
   - `flux-pro-2.0`: Photorealistic, tanpa konfigurasi kualitas, hingga 4 referensi gambar.
   - `ideogram-v3.0`: Spesialis tipografi & desain grafis, mode teks murni (tanpa referensi gambar).
   - `lucid-origin`: Model artistik, hingga 2 referensi gambar.
   - `seedream-4.5`: Model estetika tinggi, hingga 6 referensi gambar.
   - `recraft-v4`: Model desain vektor & raster, batasan prompt 1200 karakter, mode teks murni tanpa style/quality.

2. **Dukungan RESTful API Mirava**:
   - Upload gambar referensi (`POST /api/public/v1/upload`, `multipart/form-data`, key: `image`).
   - Buat tugas generasi gambar (`POST /api/public/v1/generate`, HTTP 202 Accepted).
   - Polling status background rendering (`GET /api/public/v1/generate/<generation_id>`) hingga status `success` atau `failed`.

3. **Penyimpanan Lokal & Keamanan Link**:
   - Otomatis mengunduh berkas gambar langsung dari URL CDN/Tencent COS ke folder `outputs/` agar aset gambar tidak hilang saat tautan kedaluwarsa.
   - Database SQLite (`history.db`) menyimpan riwayat prompt, model, parameter teknis, status, timestamp, dan path lokal.

4. **UI Streamlit Interaktif & Modern**:
   - Sidebar dengan input API key, dropdown model dinamis, rasio aspek, kualitas, dan style.
   - Validasi karakter prompt khusus untuk `recraft-v4` (maks 1200 karakter).
   - Tab Galeri dengan filter model, pencarian prompt, preview gambar lokal, unduh berkas, dan hapus riwayat.
   - Tab Model Matrix dan metrik kapasitas penyimpanan lokal.

## 🛠️ Cara Menjalankan Aplikasi

1. Masuk ke folder proyek:
   ```bash
   cd C:\Users\DESIGN2-SPJ112024\.gemini\antigravity-ide\scratch\imaginer_studio
   ```

2. Instal dependensi:
   ```bash
   pip install -r requirements.txt
   ```

3. Jalankan aplikasi Streamlit:
   ```bash
   streamlit run app.py
   ```
