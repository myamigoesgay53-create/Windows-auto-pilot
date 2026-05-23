@echo off
setlocal

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creando entorno virtual...
  py -3 -m venv .venv 2>nul
  if errorlevel 1 (
    python -m venv .venv
  )
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
python main.py

endlocal
