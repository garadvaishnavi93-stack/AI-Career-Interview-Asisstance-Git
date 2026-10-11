# AI Career & Interview Assistant

## Run on Windows

1. Install Python 3.10+ and select **Add Python to PATH** during installation.
2. Open PowerShell in this folder.
3. Run:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

4. Open `.env` and replace `your_gemini_api_key_here` with your own Gemini API key.
5. Start the app:

```powershell
python app.py
```

6. Open http://127.0.0.1:5000 in a browser.

Never upload `.env` or your API key to GitHub. If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again.
