@echo off

cls

title UPSTOX_APP

echo ========================================
echo Starting UPSTOX_APP...
echo ========================================

uvicorn main:app --host 0.0.0.0 --port 8000

@REM  --reload

pause