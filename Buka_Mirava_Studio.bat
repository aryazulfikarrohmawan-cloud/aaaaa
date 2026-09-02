@echo off
title Mirava Imaginer Studio
cd /d "%~dp0"

echo ========================================================
echo        MEMBUKA MIRAVA IMAGINER STUDIO...
echo ========================================================

:: Cek apakah server di port 8501 sudah aktif
netstat -ano | findstr :8501 | findstr LISTENING >nul
if %errorlevel% equ 0 (
    echo.
    echo [INFO] Aplikasi sudah aktif berjalan!
    echo [INFO] Membuka antarmuka di browser Anda...
    echo.
    start http://localhost:8501
    timeout /t 3 >nul
    exit /b
)

:: Jika belum aktif, jalankan Streamlit dan buka browser
echo.
echo [INFO] Menjalankan server aplikasi...
echo [INFO] Browser akan terbuka otomatis.
echo.
echo [PENTING] Biarkan jendela ini tetap terbuka selama menggunakan aplikasi.
echo.

start "" "http://localhost:8501"
"C:\Users\DESIGN2-SPJ112024\AppData\Local\Programs\Python\Python313\python.exe" -m streamlit run app.py --server.headless=true --server.port=8501
pause
