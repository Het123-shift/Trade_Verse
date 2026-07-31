# 🛸 ANTIGRAVITY Crypto Dashboard & NOVA AI Assistant

A modern, high-performance Cryptocurrency Market Dashboard powered by real-time CoinGecko market data, custom price alerts via Gmail SMTP, and an advanced streaming AI assistant (**NOVA**) using Google Gemini models.

---

## 🌟 Key Features

* **📈 Real-Time Crypto Dashboard**: Interactive charts, market cap ranks, 24h volume, and fear & greed sentiment metrics.
* **🤖 NOVA AI Assistant**:
  * **Real-Time Token Streaming (SSE)**: Streaming responses token-by-token like ChatGPT.
  * **Multi-Model Selector**: Switch live between `Gemini 2.0 Flash`, `Gemini Flash Latest`, and `Gemini 1.5 Pro`.
  * **Truncation Auto-Continue**: `▶ Click to Continue` button for long answers.
  * **1-Click Copy & Regenerate**: Easy clipboard copying and response regeneration.
* **📧 Automated Price Alerts**: Set target price conditions (`above`/`below`) with automated background polling and email delivery via Gmail SMTP.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install flask flask-cors requests python-dotenv
```

### 2. Configure Environment Credentials
Copy `.env.example` to `.env` or create `.credentials.json`:
```env
BOT_EMAIL_ADDRESS=your_email@gmail.com
BOT_EMAIL_PASSWORD=your_16_character_app_password
GEMINI_API_KEY=your_gemini_api_key
```

### 3. Start the Backend Server
```bash
python bot_server.py
```

### 4. Launch the Web Application
Open [`index.html`](file:///c:/Users/patel/OneDrive/Desktop/programming/crypto/index.html) in your browser!

---

## 🔒 Security Notice
Sensitive configuration files (`.credentials.json`, `.env`, `alerts.json`) are automatically included in `.gitignore` and ignored from version control.
