@echo off
REM Launch the AWS cost dashboard locally.
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
if not exist .env (
  echo No .env found. Copy .env.example to .env and add your read-only IAM creds.
  exit /b 1
)
python app.py
