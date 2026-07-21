@echo off
cls


echo Starting FastAPI Application...


uvicorn main:app --host 0.0.0.0 --port 8000


pause