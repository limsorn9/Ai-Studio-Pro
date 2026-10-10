@echo off
chcp 65001 > nul
echo ========================================================
echo       AI STUDIO PRO - AUTO PATCH UPDATE v2.7.1
echo ========================================================
echo.
echo [1/3] បិទដំណើរការ AiStudioPro.exe ចាស់...
taskkill /f /im AiStudioPro.exe > nul 2>&1
taskkill /f /im whisper-cli.exe > nul 2>&1
timeout /t 2 /nobreak > nul

echo [2/3] កំពុងដំឡើង Patch v2.7.1 ចូលក្នុង app.asar...
copy /y "D:\Ai Studio Pro\app_patched.asar" "D:\Ai Studio Pro\app\resources\app.asar" > nul
if %errorlevel% neq 0 (
    echo [ERROR] មិនអាចចម្លង file បានទេ សូមបិទ AiStudioPro.exe ដោយដៃ រួចសាកល្បងម្តងទៀត!
    pause
    exit /b 1
)

echo [3/3] បើកដំណើរការ Ai Studio Pro v2.7.1 ឡើងវិញ...
start "" "D:\Ai Studio Pro\app\AiStudioPro.exe"
echo.
echo ========================================================
echo  ✅ ជោគជ័យ ១០០%! Ai Studio Pro v2.7.1 ដំណើរការហើយ!
echo ========================================================
timeout /t 3 /nobreak > nul
exit
