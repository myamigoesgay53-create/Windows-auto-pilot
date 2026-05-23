# Windows AI Autopilot (Python + OpenAI)

Windows desktop app that receives a text task and uses OpenAI to perform real actions on your PC:

- mouse and keyboard control through Computer Use
- web browsing
- local tools to read/search/write files

## Important

- Use this app only in an environment you control.
- Start with low-risk tasks.
- UI automation can make mistakes.
- In **safe mode** (enabled by default), writing outside the project folder is blocked and execution pauses when the API requests safety checks.

## Requirements

- Windows 10/11
- Python 3.10 or newer (3.10-3.13 recommended; 3.14 may require dependencies still catching up)

## Installation

1. Open PowerShell in this folder.
2. Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

3. Install dependencies:

```powershell
pip install -r requirements.txt
```

4. Set up your API key (optional via `.env`):

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and paste your key into `OPENAI_API_KEY`.

## Run

```powershell
python main.py
```

Or with double-click/terminal:

```powershell
run_app.bat
```

## Quick Start

1. Enter your API key (or use `.env`).
2. Write the task in plain text.
3. Click **Start Autopilot**.
4. If you need to stop, click **Stop**.
5. Extra emergency stop: move the mouse to the top-left corner (PyAutoGUI FailSafe).

If you already had a previous install, update dependencies:

```powershell
pip install -U -r requirements.txt
```

## Example Tasks

- "Open the browser, find three coworking options in central Madrid, compare prices, and save a summary in `resultado.txt`."
- "Search my `Documents` folder for files containing `factura` in the name and list them."

## Structure

- `main.py`: UI and agent runtime.
- `requirements.txt`: dependencies.
- `.env.example`: environment variable template.
