import os
import json
import smtplib
import threading
import time
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
CORS(app)

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), '.credentials.json')
ALERTS_FILE = os.path.join(os.path.dirname(__file__), 'alerts.json')
alerts_lock = threading.Lock()

def load_credentials():
    """Load credentials from gitignored .credentials.json or environment"""
    email_addr = os.environ.get("BOT_EMAIL_ADDRESS") or os.environ.get("SENDER_EMAIL")
    email_pass = os.environ.get("BOT_EMAIL_PASSWORD") or os.environ.get("SENDER_PASSWORD")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                email_addr = data.get("email_address") or email_addr
                email_pass = data.get("email_password") or email_pass
                gemini_key = data.get("gemini_api_key") or gemini_key
        except Exception as e:
            print(f"[Error] Failed to load {CREDENTIALS_FILE}: {e}")
            
    return email_addr, email_pass, gemini_key

def save_credentials(email_addr, email_pass):
    """Save credentials to gitignored .credentials.json and environment"""
    os.environ["BOT_EMAIL_ADDRESS"] = email_addr
    os.environ["BOT_EMAIL_PASSWORD"] = email_pass
    
    _, _, existing_key = load_credentials()
    data = {"email_address": email_addr, "email_password": email_pass}
    if existing_key:
        data["gemini_api_key"] = existing_key
        
    try:
        with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Error] Failed to save {CREDENTIALS_FILE}: {e}")

def get_sender_email():
    email_addr, _, _ = load_credentials()
    if email_addr and "your_email" not in email_addr.lower():
        return email_addr.strip()
    return None

def get_sender_password():
    _, email_pass, _ = load_credentials()
    if email_pass and "your_gmail" not in email_pass.lower():
        return email_pass.strip()
    return None

def get_gemini_key():
    _, _, gemini_key = load_credentials()
    if gemini_key and gemini_key.strip() and not gemini_key.startswith("AIzaSyAntigravityNovaDemoKey"):
        return gemini_key.strip()
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key and env_key.strip() and not env_key.startswith("AIzaSyAntigravityNovaDemoKey"):
        return env_key.strip()
    return None

def is_email_configured():
    return bool(get_sender_email() and get_sender_password())

def load_alerts_from_file():
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Error] Failed to load {ALERTS_FILE}: {e}")
    return []

def save_alerts_to_file(alerts):
    try:
        with open(ALERTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, indent=2)
    except Exception as e:
        print(f"[Error] Failed to save {ALERTS_FILE}: {e}")

active_alerts = load_alerts_from_file()

def send_email_smtp(recipient_email, subject, html_content, text_content=""):
    sender_email = get_sender_email()
    sender_password = get_sender_password()
    
    if not sender_email or not sender_password:
        return False, "Gmail credentials are not configured. Call /api/config/email or set BOT_EMAIL_ADDRESS and BOT_EMAIL_PASSWORD."

    if not recipient_email or not recipient_email.strip():
        recipient_email = sender_email
        
    recipient_email = recipient_email.strip()

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = recipient_email

    if text_content:
        msg.attach(MIMEText(text_content, 'plain'))
    if html_content:
        msg.attach(MIMEText(html_content, 'html'))
    elif not text_content:
        msg.attach(MIMEText("Notification from ANTIGRAVITY Market AI", 'plain'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=15) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        print(f"[Email Success] Sent to {recipient_email} via SMTP_SSL:465 (Subject: '{subject}')")
        return True, f"Email sent successfully to {recipient_email}"
    except smtplib.SMTPAuthenticationError:
        err_msg = "Gmail Authentication Failed! Ensure 2-Step Verification is enabled on your Google Account and generate a 16-character App Password at myaccount.google.com/apppasswords."
        print(f"[Email Error] {err_msg}")
        return False, err_msg
    except Exception as ssl_err:
        print(f"[SMTP_SSL Warning] Port 465 failed ({ssl_err}). Retrying via STARTTLS on port 587...")
        try:
            with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
            print(f"[Email Success] Sent to {recipient_email} via STARTTLS:587 (Subject: '{subject}')")
            return True, f"Email sent successfully to {recipient_email}"
        except smtplib.SMTPAuthenticationError:
            err_msg = "Gmail Authentication Failed! Ensure 2-Step Verification is enabled on your Google Account and generate a 16-character App Password at myaccount.google.com/apppasswords."
            print(f"[Email Error] {err_msg}")
            return False, err_msg
        except Exception as starttls_err:
            err_msg = f"Failed to send email via SMTP: {str(starttls_err)}"
            print(f"[Email Error] {err_msg}")
            return False, err_msg

# ======================================================================
# LLM SYSTEM PROMPT & BACKEND CHAT PROXY
# ======================================================================

NOVA_SYSTEM_PROMPT = """You are NOVA, an intelligent, versatile AI assistant built into the ANTIGRAVITY platform. While you possess deep expertise in cryptocurrency, blockchain, financial markets, and data analysis (with access to real-time live market data from CoinGecko provided with each prompt), you function as a full general-purpose assistant capable of answering ANY type of question — coding, science, general knowledge, writing, casual conversation, logic, and beyond.

CORE GUIDELINES:
- Answer questions naturally, conversationally, accurately, and directly, just like ChatGPT or Claude.
- Tailor your response length, structure, and style appropriately to fit each specific question.
- Do NOT force every answer into a fixed market analysis template or multi-section report framework unless explicitly asked for market analysis.
- Use formatting (headers, lists, bold text, code blocks) naturally where it improves clarity.
- Use emojis only when they feel natural and appropriate — do not enforce an artificial emoji quota.

GENERAL & NON-FINANCIAL QUESTIONS (Coding, Explanations, Science, General Knowledge, Casual Chat):
- Respond in clear, engaging, and well-reasoned prose or standard markdown.
- Do NOT attach financial risk disclaimers to non-financial queries (e.g. coding, math, general advice, explanations).

CRYPTO & INVESTMENT ANALYSIS REQUESTS:
- Ground all crypto price data and market stats in the real-time live CoinGecko data provided. Always cite exact prices, 24h/7d changes, and market cap ranks when relevant.
- When evaluating coins or portfolios, look at price momentum, market breadth, and top gainers/losers provided in the context.
- Only when the user is specifically asking for a coin analysis, portfolio audit, or trade verdict, provide a clear BUY / HOLD / SELL verdict with supporting technical and fundamental reasoning.
- Include a brief risk disclaimer ONLY at the end of specific financial/coin investment analyses:
  ⚡ *Risk Disclaimer: This analysis is for educational purposes only. Cryptocurrency investments carry risk. Always do your own research (DYOR).*"""

def build_server_market_context(coins):
    if not coins or not isinstance(coins, list) or len(coins) == 0:
        return "Live market data is currently loading."
    top20 = coins[:20]
    total_gainers = len([c for c in coins if (c.get('price_change_percentage_24h') or 0) > 0])
    breadth = f"{((total_gainers / len(coins)) * 100):.1f}"
    
    # Sort for gainers & losers summary
    valid_coins = [c for c in coins if c.get('price_change_percentage_24h') is not None]
    sorted_coins = sorted(valid_coins, key=lambda x: x.get('price_change_percentage_24h', 0), reverse=True)
    top_gainers = sorted_coins[:3]
    top_losers = sorted_coins[-3:] if len(sorted_coins) >= 3 else []
    
    gainers_str = ", ".join([f"{c.get('symbol', '').upper()}: +{c.get('price_change_percentage_24h', 0):.1f}%" for c in top_gainers])
    losers_str = ", ".join([f"{c.get('symbol', '').upper()}: {c.get('price_change_percentage_24h', 0):.1f}%" for c in top_losers])

    top_table = "\n".join([
        f"  {c.get('market_cap_rank', 'N/A')}. {c.get('name')} ({c.get('symbol', '').upper()}): ${c.get('current_price', 0):,} | 24h: {c.get('price_change_percentage_24h', 0):.2f}%"
        for c in top20
    ])
    
    return f"""=== LIVE MARKET DATA (from CoinGecko) ===
Date/Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
Market Breadth: {breadth}% of tracked coins positive (24h)
Top 24h Gainers: {gainers_str if gainers_str else 'N/A'}
Top 24h Losers: {losers_str if losers_str else 'N/A'}

Top Cryptocurrencies:
{top_table}
=== END MARKET DATA ==="""

def get_generation_config(user_msg):
    """Determine optimal temperature based on prompt intent (coding/math vs analysis/creative)."""
    msg_lower = user_msg.lower()
    is_code_or_math = any(kw in msg_lower for kw in ['code', 'python', 'javascript', 'html', 'css', 'func', 'bug', 'fix', 'error', 'math', 'calculate', 'json'])
    return {
        "temperature": 0.2 if is_code_or_math else 0.7,
        "topK": 40,
        "topP": 0.95,
        "maxOutputTokens": 8192
    }


@app.route('/api/chat', methods=['POST'])
def proxy_chat_llm():
    """Requirement 1 & 5: POST /api/chat -> accepts { message, conversationHistory, coins, model }"""
    data = request.json or {}
    user_message = (data.get('message') or '').strip()
    history = data.get('conversationHistory') or []
    coins = data.get('coins') or []
    requested_model = data.get('model') or 'gemini-2.0-flash'

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    api_key = get_gemini_key()
    if not api_key:
        return jsonify({
            "error": "Server LLM API key not configured. Add GEMINI_API_KEY to your .env or .credentials.json file."
        }), 503

    market_context = build_server_market_context(coins)
    
    contents = []
    for msg in history:
        role = 'user' if msg.get('role') == 'user' else 'model'
        contents.append({
            'role': role,
            'parts': [{'text': msg.get('text', '')}]
        })

    enriched_user_msg = f"{market_context}\n\nUser Question: {user_message}" if len(contents) == 0 else f"[Live market data refreshed]\n{market_context}\n\nUser Question: {user_message}"
    contents.append({'role': 'user', 'parts': [{'text': enriched_user_msg}]})

    payload = {
        "system_instruction": {"parts": [{"text": NOVA_SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": get_generation_config(user_message)
    }

    models_to_try = [requested_model, "gemini-2.0-flash", "gemini-flash-latest", "gemini-1.5-flash", "gemini-1.5-pro"]
    models_to_try = list(dict.fromkeys(models_to_try))
    last_error = ""

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": api_key
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=30)
            if res.status_code == 200:
                res_data = res.json()
                candidate = res_data.get('candidates', [{}])[0]
                reply_text = candidate.get('content', {}).get('parts', [{}])[0].get('text', '')
                finish_reason = candidate.get('finishReason', 'STOP')
                if reply_text:
                    return jsonify({
                        "reply": reply_text.strip(),
                        "finishReason": finish_reason,
                        "model": model
                    }), 200

            res_json = res.json() if 'json' in res.headers.get('content-type', '').lower() else {}
            err_msg = res_json.get('error', {}).get('message', res.text)
            print(f"[LLM Warning] Model {model} returned HTTP {res.status_code}: {err_msg}")
            
            if res.status_code == 429 or "RESOURCE_EXHAUSTED" in str(res_json) or "quota" in str(err_msg).lower():
                last_error = err_msg
                continue
            else:
                last_error = err_msg
                break
        except Exception as e:
            last_error = str(e)
            continue

    if "quota" in str(last_error).lower() or "429" in str(last_error) or "RESOURCE_EXHAUSTED" in str(last_error):
        user_err = (
            "⏳ **Gemini API Quota Exceeded (HTTP 429)**\n\n"
            "Your configured Gemini API key has 0 quota or has hit Google's free tier request limit.\n\n"
            "**Quick Fix:**\n"
            "1. Generate a free API key at **[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)**\n"
            "2. Click ⚙️ in NOVA chat settings and paste your key."
        )
        return jsonify({"error": user_err}), 429

    return jsonify({"error": f"Gemini API Error: {last_error}"}), 502

@app.route('/api/chat/stream', methods=['POST'])
def proxy_chat_stream():
    """Requirement 3: Stream tokens in real time via Server-Sent Events (SSE)"""
    data = request.json or {}
    user_message = (data.get('message') or '').strip()
    history = data.get('conversationHistory') or []
    coins = data.get('coins') or []
    requested_model = data.get('model') or 'gemini-2.0-flash'

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    api_key = get_gemini_key()
    if not api_key:
        return jsonify({
            "error": "Server LLM API key not configured. Add GEMINI_API_KEY to your .env or .credentials.json file."
        }), 503

    market_context = build_server_market_context(coins)
    
    contents = []
    for msg in history:
        role = 'user' if msg.get('role') == 'user' else 'model'
        contents.append({
            'role': role,
            'parts': [{'text': msg.get('text', '')}]
        })

    enriched_user_msg = f"{market_context}\n\nUser Question: {user_message}" if len(contents) == 0 else f"[Live market data refreshed]\n{market_context}\n\nUser Question: {user_message}"
    contents.append({'role': 'user', 'parts': [{'text': enriched_user_msg}]})

    payload = {
        "system_instruction": {"parts": [{"text": NOVA_SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": get_generation_config(user_message)
    }

    models_to_try = [requested_model, "gemini-2.0-flash", "gemini-flash-latest", "gemini-1.5-flash", "gemini-1.5-pro"]
    models_to_try = list(dict.fromkeys(models_to_try))

    def generate_sse():
        success = False
        last_error = ""
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}&alt=sse"
            headers = {
                "Content-Type": "application/json",
                "X-goog-api-key": api_key
            }
            try:
                res = requests.post(url, json=payload, headers=headers, stream=True, timeout=30)
                if res.status_code == 200:
                    success = True
                    finish_reason = "STOP"
                    for line in res.iter_lines():
                        if line:
                            line_str = line.decode('utf-8')
                            if line_str.startswith('data: '):
                                chunk_json_str = line_str[6:].strip()
                                try:
                                    chunk_data = json.loads(chunk_json_str)
                                    candidate = chunk_data.get('candidates', [{}])[0]
                                    chunk_text = candidate.get('content', {}).get('parts', [{}])[0].get('text', '')
                                    if candidate.get('finishReason'):
                                        finish_reason = candidate.get('finishReason')
                                    if chunk_text:
                                        yield f"data: {json.dumps({'chunk': chunk_text, 'model': model})}\n\n"
                                except Exception:
                                    pass
                    yield f"data: {json.dumps({'done': True, 'finishReason': finish_reason, 'model': model})}\n\n"
                    break
                else:
                    err_text = res.text
                    print(f"[LLM Stream Warning] Model {model} returned HTTP {res.status_code}: {err_text}")
                    last_error = err_text
                    if res.status_code == 429 or "quota" in err_text.lower():
                        continue
                    else:
                        break
            except Exception as e:
                last_error = str(e)
                continue

        if not success:
            user_err = f"Failed to stream from Gemini API: {last_error}"
            if "quota" in last_error.lower() or "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
                user_err = (
                    "⏳ **Gemini API Quota Exceeded (HTTP 429)**\n\n"
                    "Your configured Gemini API key has 0 quota or has hit Google's free tier request limit.\n\n"
                    "**Quick Fix:**\n"
                    "1. Generate a free API key at **[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)**\n"
                    "2. Click ⚙️ in NOVA chat settings and paste your key."
                )
            yield f"data: {json.dumps({'error': user_err})}\n\n"

    return Response(generate_sse(), mimetype='text/event-stream')

# ======================================================================
# ENDPOINTS
# ======================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """GET /api/health"""
    with alerts_lock:
        count = len(active_alerts)
    return jsonify({
        "online": True,
        "email_configured": is_email_configured(),
        "chat_llm_configured": bool(get_gemini_key()),
        "sender_email": get_sender_email(),
        "active_alerts_count": count
    }), 200

@app.route('/api/config/email', methods=['POST'])
def configure_email():
    """POST /api/config/email"""
    data = request.json or {}
    email_addr = (data.get('email_address') or data.get('email') or '').strip()
    email_pass = (data.get('email_password') or data.get('password') or '').strip()

    if not email_addr or not email_pass:
        return jsonify({"error": "Both email_address and email_password (16-character App Password) are required"}), 400

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10) as server:
            server.login(email_addr, email_pass)
    except smtplib.SMTPAuthenticationError:
        return jsonify({
            "error": "Invalid Gmail address or App Password. Ensure 2-Step Verification is enabled on your Google Account and generate a 16-character App Password at myaccount.google.com/apppasswords."
        }), 400
    except Exception:
        try:
            with smtplib.SMTP('smtp.gmail.com', 587, timeout=10) as server:
                server.starttls()
                server.login(email_addr, email_pass)
        except smtplib.SMTPAuthenticationError:
            return jsonify({
                "error": "Invalid Gmail address or App Password. Ensure 2-Step Verification is enabled on your Google Account and generate a 16-character App Password at myaccount.google.com/apppasswords."
            }), 400
        except Exception as e2:
            return jsonify({"error": f"Failed to authenticate with Gmail SMTP: {str(e2)}"}), 400

    save_credentials(email_addr, email_pass)

    subject = "🧪 ANTIGRAVITY Alert Bot Credentials Verified"
    text_content = (
        "Congratulations!\n\n"
        "Your ANTIGRAVITY Market Alert Bot credentials have been verified successfully.\n"
        "Real-time crypto price alerts and AI market recommendations will now be delivered to this email address.\n\n"
        "Powered by ANTIGRAVITY Market AI"
    )
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: sans-serif; background: #050508; color: #f3f4f6; padding: 20px;">
      <div style="max-width: 480px; margin: auto; background: #0b0b10; border: 1px solid #1f2937; border-top: 4px solid #10b981; border-radius: 12px; padding: 24px; text-align: center;">
        <h2 style="color: #ffffff; text-transform: uppercase; font-size: 18px; margin-top: 0;">🧪 Credentials Verified</h2>
        <p style="color: #9ca3af; font-size: 14px; line-height: 1.6;">
          Your ANTIGRAVITY Alert Bot credentials for <strong>{email_addr}</strong> have been verified and saved successfully!
        </p>
        <div style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.25); color: #34d399; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: bold; margin: 16px 0;">
          ✅ Real-Time Email Alerts Active
        </div>
      </div>
    </body>
    </html>
    """
    send_email_smtp(email_addr, subject, html_content, text_content)

    return jsonify({"message": f"Gmail SMTP credentials verified & saved! Confirmation email sent to {email_addr}"}), 200

@app.route('/api/send-test-email', methods=['POST'])
def send_test_email():
    """POST /api/send-test-email"""
    data = request.json or {}
    recipient_email = data.get('email') or get_sender_email()

    if not is_email_configured():
        return jsonify({"error": "Sender email not configured. Please call /api/config/email or set credentials first."}), 400

    subject = "🧪 ANTIGRAVITY Alert Bot Test Email"
    text_content = (
        "Congratulations! Your ANTIGRAVITY Crypto Market Alert Bot is configured correctly.\n\n"
        "Real-time email price alerts and AI market recommendations will be delivered to this address automatically.\n\n"
        "Powered by ANTIGRAVITY Market AI"
    )
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: sans-serif; background: #050508; color: #f3f4f6; padding: 20px;">
      <div style="max-width: 480px; margin: auto; background: #0b0b10; border: 1px solid #1f2937; border-top: 4px solid #3b82f6; border-radius: 12px; padding: 24px; text-align: center;">
        <h2 style="color: #ffffff; text-transform: uppercase; font-size: 18px; margin-top: 0;">🧪 Real-Time Test Email</h2>
        <p style="color: #9ca3af; font-size: 14px; line-height: 1.6;">
          Your ANTIGRAVITY Crypto Market Alert Bot is online and working correctly!
        </p>
      </div>
    </body>
    </html>
    """

    success, message = send_email_smtp(recipient_email, subject, html_content, text_content)
    if success:
        return jsonify({"message": f"Test email sent successfully to {recipient_email}!"}), 200
    else:
        return jsonify({"error": message}), 500

@app.route('/api/alerts/trigger', methods=['POST'])
@app.route('/api/alerts/digest', methods=['POST'])
def trigger_alert_email():
    """POST /api/alerts/trigger or /api/alerts/digest"""
    data = request.json or {}
    recipient_email = data.get('email') or get_sender_email()
    digest_type = data.get('digestType', 'realtime-alert')
    coin_name = data.get('coinName') or data.get('coin') or 'Market'
    html_content = data.get('htmlContent') or data.get('aiMarketSummary')

    if not is_email_configured():
        return jsonify({"error": "Sender email not configured. Please set credentials via /api/config/email."}), 400

    if digest_type == 'ai-auto-alert':
        subject = f"🤖 AI BUY RECOMMENDATION ALERT: {coin_name}"
    elif digest_type == 'live-report':
        subject = f"🛸 ANTIGRAVITY: Live Market & News AI Digest"
    else:
        subject = f"🛸 Real-Time Crypto Alert: {coin_name}"

    text_fallback = f"ANTIGRAVITY Alert triggered for {coin_name}."

    success, message = send_email_smtp(recipient_email, subject, html_content, text_fallback)

    if success:
        return jsonify({"success": True, "message": f"Email delivered to {recipient_email}"}), 200
    else:
        return jsonify({"error": message}), 500

# ======================================================================
# PRICE ALERT CRUD & BACKGROUND POLLER
# ======================================================================

@app.route('/api/alerts', methods=['POST'])
def create_alert():
    data = request.json or {}
    if not all(k in data for k in ('coin', 'target_price', 'condition')):
        return jsonify({"error": "Missing required fields (coin, target_price, condition)"}), 400

    try:
        target_price = float(data['target_price'])
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid target_price. Must be a valid numeric value."}), 400

    recipient_email = data.get('email') or get_sender_email() or "user@localhost"
    alert_id = data.get('id', "alert_" + str(int(time.time() * 1000)))
    alert = {
        'id': alert_id,
        'email': recipient_email,
        'coin': data['coin'].lower().strip().replace(' ', '-'),
        'target_price': target_price,
        'condition': data['condition'],
        'created_at': data.get('created_at', time.strftime("%Y-%m-%dT%H:%M:%SZ"))
    }

    with alerts_lock:
        existing = [a for a in active_alerts if a.get('id') == alert_id]
        if not existing:
            active_alerts.append(alert)
            save_alerts_to_file(active_alerts)

    return jsonify({"message": "Alert created successfully", "alert": alert, "active_alerts": len(active_alerts)}), 201

@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    with alerts_lock:
        return jsonify({"active_alerts": list(active_alerts)})

@app.route('/api/alerts/<alert_id>', methods=['DELETE'])
def delete_alert(alert_id):
    with alerts_lock:
        initial_len = len(active_alerts)
        active_alerts[:] = [a for a in active_alerts if a.get('id') != alert_id]
        removed = initial_len > len(active_alerts)
        if removed:
            save_alerts_to_file(active_alerts)

    if removed:
        return jsonify({"message": "Alert deleted successfully", "id": alert_id}), 200
    else:
        return jsonify({"error": "Alert not found"}), 404

def get_crypto_prices():
    try:
        with alerts_lock:
            coins = list(set([a['coin'].lower().strip().replace(' ', '-') for a in active_alerts if 'coin' in a]))
        if not coins:
            return {}
        ids = ",".join(coins)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[Price Monitor Error] {e}")
    return {}

def background_price_monitor():
    print("[Price Monitor] Daemon thread started (Polling CoinGecko every 30s)...")
    while True:
        try:
            with alerts_lock:
                alerts_snapshot = list(active_alerts)
            if alerts_snapshot:
                prices = get_crypto_prices()
                alerts_to_remove = []
                for alert in alerts_snapshot:
                    coin = alert.get('coin', '').lower().strip().replace(' ', '-')
                    if coin in prices and 'usd' in prices[coin]:
                        current_price = prices[coin]['usd']
                        target_price = alert.get('target_price', 0)
                        condition = alert.get('condition', 'above')
                        triggered = False
                        if condition == 'above' and current_price >= target_price:
                            triggered = True
                        elif condition == 'below' and current_price <= target_price:
                            triggered = True
                        if triggered:
                            print(f"[Alert Triggered] {coin} at ${current_price:,.2f} ({condition} target ${target_price:,.2f})")
                            recipient = alert.get('email') or get_sender_email()
                            subject = f"🛸 Crypto Alert: {coin.capitalize()} is now ${current_price:,.2f}"
                            text_body = f"Alert triggered! {coin.capitalize()} reached ${current_price:,.2f} ({condition} ${target_price:,.2f})."
                            send_email_smtp(recipient, subject, None, text_body)
                            alerts_to_remove.append(alert)
                if alerts_to_remove:
                    with alerts_lock:
                        for alert in alerts_to_remove:
                            if alert in active_alerts:
                                active_alerts.remove(alert)
                        save_alerts_to_file(active_alerts)
        except Exception as e:
            print(f"[Monitor Error] {e}")
        time.sleep(30)

if __name__ == '__main__':
    sender = get_sender_email()
    configured = is_email_configured()
    gemini_key = get_gemini_key()

    print("======================================================================")
    print("🛸 ANTIGRAVITY Alert Bot & Advanced LLM Server running at http://localhost:5000")
    print("======================================================================")
    print("Status:")
    print("  - Server Health:       GET  http://localhost:5000/api/health")
    print("  - Chat LLM Proxy:      POST http://localhost:5000/api/chat")
    print("  - Real-Time SSE Stream:POST http://localhost:5000/api/chat/stream")
    print("  - Configure Email:     POST http://localhost:5000/api/config/email")
    print("  - Send Test Email:     POST http://localhost:5000/api/send-test-email")
    print("  - Trigger Email:       POST http://localhost:5000/api/alerts/trigger")
    print(f"  - Email Configured:    {'YES (' + sender + ')' if configured else 'NO'}")
    print(f"  - Chat LLM Key:        {'YES (Gemini Key Loaded)' if gemini_key else 'NO (Set GEMINI_API_KEY in .env or .credentials.json)'}")
    print("======================================================================")

    monitor_thread = threading.Thread(target=background_price_monitor, daemon=True)
    monitor_thread.start()

    app.run(host='0.0.0.0', port=5000)
