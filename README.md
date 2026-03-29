# 🚀 How to Deploy PCAS to Render (Free Tier)

This folder contains the modified version of PCAS optimized for Render.com.

## 1. Environment Variables (.env) on Render
Set the following variables in the Render Dashboard (Settings > Environment Variables):

| Key | Value (Example) |
| :--- | :--- |
| `VIDEOSDK_TOKEN` | your_token |
| `GOOGLE_API_KEY` | your_gemini_key |
| `TWILIO_ACCOUNT_SID` | your_sid |
| `TWILIO_AUTH_TOKEN` | your_token |
| `TWILIO_PHONE_NUMBER` | +123456789 |
| `TRANSFER_NUMBER` | +66... |
| `USER_NAME` | Your Name |
| `EMAIL_SENDER` | gmail address |
| `EMAIL_PASSWORD` | app password |
| `EMAIL_RECEIVER` | receiver email |
| `GOOGLE_TOKEN_DATA` | **(Copy content of `token.json` here)** 👈 Crucial |
| `RENDER_EXTERNAL_URL` | `https://your-app-name.onrender.com` |

## 2. Setting up Google Login (Pre-deployment)
1.  Run the app locally first to generate `token.json`.
2.  Open `token.json`, select all text, and copy it.
3.  Paste it into the `GOOGLE_TOKEN_DATA` environment variable on Render.
    *   *This trick bypasses Render's temporary file system behavior.*

## 3. Render Settings
- **Runtime:** Python
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python combined_app.py`
- **Memory Optimization:** Added `combined_app.py` to run both Web and AI in a single process.
- **Python Version:** Set `PYTHON_VERSION` = `3.11.10` in Render Settings.

## 4. Keep-Alive (Prevent Sleeping)
To prevent Render Free Tier from spinning down, use an external uptime monitor like **[cron-job.org](https://cron-job.org/)**:
1.  Target: `https://your-app-name.onrender.com/`
2.  Interval: Every **5 minutes**.

---
**Note:** If you run into RAM issues, ensure only one call is active at a time. The Free Tier has limited resources.
