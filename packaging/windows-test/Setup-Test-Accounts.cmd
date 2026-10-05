@echo off
rem Wese Trade - PERSONAL TEST PACKAGE ONLY.
rem Copies the prepared test database (3 local test accounts, no forward-test data) into
rem %LOCALAPPDATA%\WeseTrade\data. Existing data is never deleted: it is MOVED to a
rem WeseTrade-backup-<time> folder first. Production behaviour of the app is unchanged.
setlocal EnableExtensions
chcp 65001 >nul
set "QUIET="
if /I "%~1"=="/quiet" set "QUIET=1"
set "SRC=%~dp0TestData\wese_trade.db"
set "ROOT=%LOCALAPPDATA%\WeseTrade"
set "DATA=%ROOT%\data"

echo.
echo  Wese Trade - test accounts setup / تجهيز حسابات الاختبار
echo  ---------------------------------------------------------
if not exist "%SRC%" (
  echo  [ERROR] TestData\wese_trade.db not found next to this file.
  echo  [خطأ] لم يتم العثور على ملف قاعدة بيانات الاختبار بجانب هذا الملف.
  goto :fail
)

for %%P in ("wese-trade.exe" "Wese Trade.exe" "wese-trade-backend.exe") do (
  tasklist /FI "IMAGENAME eq %%~P" /NH 2>nul | "%SystemRoot%\System32\find.exe" /I "%%~P" >nul && (
    echo  [STOP] Wese Trade is running. Close it first, then run this file again.
    echo  [توقف] برنامج Wese Trade يعمل حالياً. أغلقه أولاً ثم شغّل هذا الملف مرة أخرى.
    goto :fail
  )
)

if exist "%ROOT%" (
  if defined QUIET (
    echo  [STOP] %ROOT% already exists.
    goto :fail
  )
  echo  Existing Wese Trade data was found at:
  echo  توجد بيانات سابقة لبرنامج Wese Trade في:
  echo     %ROOT%
  echo  It will be MOVED to a backup folder - nothing is deleted.
  echo  سيتم نقلها إلى مجلد نسخة احتياطية ولن تُحذف.
  choice /C YN /M " Continue? / متابعة؟"
  if errorlevel 2 goto :cancel
  for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%T"
  move "%ROOT%" "%ROOT%-backup-%STAMP%" >nul || (
    echo  [ERROR] Could not move the existing data folder.
    echo  [خطأ] تعذر نقل مجلد البيانات الحالي.
    goto :fail
  )
  echo  Backup: %ROOT%-backup-%STAMP%
)

mkdir "%DATA%" >nul 2>&1
copy /Y "%SRC%" "%DATA%\wese_trade.db" >nul || (
  echo  [ERROR] Copy failed. / [خطأ] فشل النسخ.
  goto :fail
)
echo.
echo  [OK] Test accounts are ready. Now open Wese Trade and sign in.
echo  [تم] حسابات الاختبار جاهزة. افتح Wese Trade الآن وسجّل الدخول.
echo  Accounts: see TEST-ACCOUNTS-AR.txt / الحسابات: راجع الملف TEST-ACCOUNTS-AR.txt
if not defined QUIET pause
exit /b 0

:cancel
echo  Cancelled. Nothing was changed. / تم الإلغاء ولم يتغير شيء.
if not defined QUIET pause
exit /b 3

:fail
if not defined QUIET pause
exit /b 1
