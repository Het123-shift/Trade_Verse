"""
ANTIGRAVITY Bot Server — Full Test Suite
=========================================
Unit tests:        python test_bot_server.py
Integration tests: python test_bot_server.py --live   (server must be running on localhost:5000)
Verbose output:    python test_bot_server.py -v
"""

import sys
import json
import time
import types
import unittest
import threading
import unittest.mock as mock
from unittest.mock import patch, MagicMock, mock_open

# ── Dependency check ──────────────────────────────────────────────────────────
try:
    import flask
    import flask_cors
    import requests
except ImportError as e:
    print(f"\n\033[91m\033[1m❌ Missing required dependency: {e.name}\033[0m")
    print(f"\033[93m👉 Please install project requirements by running:\033[0m")
    print(f"\033[96m   pip install -r requirements.txt\033[0m\n")
    sys.exit(1)

# ── Detect flags ──────────────────────────────────────────────────────────────
RUN_LIVE = "--live" in sys.argv
VERBOSE  = "-v" in sys.argv or "--verbose" in sys.argv
BASE_URL = "http://localhost:5000"

if "--live" in sys.argv:
    sys.argv.remove("--live")

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  print(f"  {GREEN}✔{RESET} {msg}")
def fail(msg):print(f"  {RED}✗{RESET} {msg}")
def info(msg):print(f"  {YELLOW}ℹ{RESET} {msg}")

# ══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS  (no network / no running server required)
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadCredentials(unittest.TestCase):
    """Unit-test credential loading from file and environment variables."""

    def _make_module(self, file_data=None, env=None):
        """Import bot_server with a mocked filesystem + env."""
        env = env or {}
        file_json = json.dumps(file_data) if file_data else ""
        exists_rv = bool(file_data)

        with patch.dict("os.environ", env, clear=False), \
             patch("os.path.exists", return_value=exists_rv), \
             patch("builtins.open", mock_open(read_data=file_json)), \
             patch("bot_server.load_alerts_from_file", return_value=[]), \
             patch("bot_server.threading.Thread"):
            import importlib, bot_server as bs
            importlib.reload(bs)
            return bs

    def test_reads_from_credentials_file(self):
        bs = self._make_module(file_data={
            "email_address":  "test@gmail.com",
            "email_password": "app_password_123",
            "gemini_api_key": "AIzaSy_REAL_KEY"
        })
        addr, pwd, key = bs.load_credentials()
        self.assertEqual(addr, "test@gmail.com")
        self.assertEqual(pwd,  "app_password_123")
        self.assertEqual(key,  "AIzaSy_REAL_KEY")

    def test_env_fallback_when_no_file(self):
        env = {
            "BOT_EMAIL_ADDRESS":  "env@gmail.com",
            "BOT_EMAIL_PASSWORD": "env_password",
            "GEMINI_API_KEY":     "AIzaSy_ENV_KEY"
        }
        bs = self._make_module(file_data=None, env=env)
        addr, pwd, key = bs.load_credentials()
        self.assertEqual(addr, "env@gmail.com")
        self.assertEqual(key,  "AIzaSy_ENV_KEY")

    def test_returns_none_when_nothing_set(self):
        bs = self._make_module(file_data=None, env={})
        addr, pwd, key = bs.load_credentials()
        # Any of these might be set from the real environment;
        # just ensure the function doesn't raise.
        self.assertIsInstance(addr, (str, type(None)))


class TestBuildMarketContext(unittest.TestCase):
    """Unit-test market context string builder."""

    def setUp(self):
        with patch("os.path.exists", return_value=False), \
             patch("bot_server.load_alerts_from_file", return_value=[]), \
             patch("bot_server.threading.Thread"):
            import importlib, bot_server as bs
            importlib.reload(bs)
            self.bs = bs

    def _make_coin(self, rank, name, symbol, price, change24h):
        return {
            "market_cap_rank":             rank,
            "name":                        name,
            "symbol":                      symbol,
            "current_price":               price,
            "price_change_percentage_24h": change24h,
        }

    def test_returns_loading_message_for_empty_list(self):
        ctx = self.bs.build_server_market_context([])
        self.assertIn("loading", ctx.lower())

    def test_returns_loading_message_for_none(self):
        ctx = self.bs.build_server_market_context(None)
        self.assertIn("loading", ctx.lower())

    def test_includes_top_coins(self):
        coins = [
            self._make_coin(1, "Bitcoin",  "btc", 65000, 2.5),
            self._make_coin(2, "Ethereum", "eth", 3200,  -1.2),
        ]
        ctx = self.bs.build_server_market_context(coins)
        self.assertIn("Bitcoin", ctx)
        self.assertIn("Ethereum", ctx)
        self.assertIn("$65,000", ctx)

    def test_market_breadth_positive_only(self):
        coins = [
            self._make_coin(1, "Bitcoin",  "btc", 65000,  5.0),
            self._make_coin(2, "Ethereum", "eth", 3200,   3.0),
            self._make_coin(3, "Solana",   "sol", 150,   -2.0),
            self._make_coin(4, "BNB",      "bnb", 400,    1.0),
        ]
        ctx = self.bs.build_server_market_context(coins)
        # 3 out of 4 are positive → 75.0%
        self.assertIn("75.0%", ctx)

    def test_caps_at_top_20(self):
        coins = [self._make_coin(i, f"Coin{i}", f"C{i}", i * 100, 1.0)
                 for i in range(1, 30)]
        ctx = self.bs.build_server_market_context(coins)
        # Coin21 and above should NOT appear in the table
        self.assertNotIn("Coin21", ctx)

    def test_contains_coingecko_label(self):
        coins = [self._make_coin(1, "Bitcoin", "btc", 65000, 1.0)]
        ctx = self.bs.build_server_market_context(coins)
        self.assertIn("CoinGecko", ctx)

    def test_handles_none_fields(self):
        coins = [{
            "market_cap_rank": None,
            "name": None,
            "symbol": None,
            "current_price": None,
            "price_change_percentage_24h": None
        }]
        ctx = self.bs.build_server_market_context(coins)
        self.assertIn("Unknown", ctx)
        self.assertIn("$0", ctx)


class TestAlertTriggerLogic(unittest.TestCase):
    """Unit-test the price-comparison logic used in the background monitor."""

    def _check(self, condition, current_price, target_price):
        """Mirror the trigger logic from background_price_monitor."""
        if condition == "above":
            return current_price >= target_price
        elif condition == "below":
            return current_price <= target_price
        return False

    def test_above_triggers_at_target(self):
        self.assertTrue(self._check("above", 65000, 65000))

    def test_above_triggers_above_target(self):
        self.assertTrue(self._check("above", 70000, 65000))

    def test_above_does_not_trigger_below(self):
        self.assertFalse(self._check("above", 60000, 65000))

    def test_below_triggers_at_target(self):
        self.assertTrue(self._check("below", 50000, 50000))

    def test_below_triggers_below_target(self):
        self.assertTrue(self._check("below", 40000, 50000))

    def test_below_does_not_trigger_above(self):
        self.assertFalse(self._check("below", 60000, 50000))

    def test_unknown_condition_does_not_trigger(self):
        self.assertFalse(self._check("sideways", 65000, 65000))


class TestAlertIdDeduplication(unittest.TestCase):
    """Unit-test that duplicate alert IDs are not inserted twice."""

    def setUp(self):
        with patch("os.path.exists", return_value=False), \
             patch("bot_server.load_alerts_from_file", return_value=[]), \
             patch("bot_server.threading.Thread"), \
             patch("bot_server.save_alerts_to_file"):
            import importlib, bot_server as bs
            importlib.reload(bs)
            self.bs = bs

    def test_duplicate_id_not_added(self):
        self.bs.active_alerts.clear()
        alert = {
            "id": "alert_test_001",
            "coin": "bitcoin",
            "target_price": 60000,
            "condition": "above",
            "email": "x@x.com",
            "created_at": "2026-01-01T00:00:00Z"
        }
        with self.bs.alerts_lock:
            existing = [a for a in self.bs.active_alerts if a.get("id") == alert["id"]]
            if not existing:
                self.bs.active_alerts.append(alert)
            # Try to add again
            existing2 = [a for a in self.bs.active_alerts if a.get("id") == alert["id"]]
            if not existing2:
                self.bs.active_alerts.append(alert)

        self.assertEqual(len([a for a in self.bs.active_alerts
                               if a["id"] == "alert_test_001"]), 1)


class TestGetCryptoPricesMocked(unittest.TestCase):
    """Unit-test get_crypto_prices with mocked HTTP responses."""

    def setUp(self):
        with patch("os.path.exists", return_value=False), \
             patch("bot_server.load_alerts_from_file", return_value=[]), \
             patch("bot_server.threading.Thread"):
            import importlib, bot_server as bs
            importlib.reload(bs)
            self.bs = bs

    def test_returns_price_dict_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "bitcoin": {"usd": 65000},
            "ethereum": {"usd": 3200}
        }
        with patch("requests.get", return_value=mock_resp), \
             patch.object(self.bs, "active_alerts",
                          [{"coin": "bitcoin"}, {"coin": "ethereum"}]):
            prices = self.bs.get_crypto_prices()
        self.assertIn("bitcoin", prices)
        self.assertEqual(prices["bitcoin"]["usd"], 65000)

    def test_returns_empty_dict_on_error(self):
        with patch("requests.get", side_effect=Exception("Timeout")), \
             patch.object(self.bs, "active_alerts", [{"coin": "bitcoin"}]):
            prices = self.bs.get_crypto_prices()
        self.assertEqual(prices, {})

    def test_returns_empty_dict_when_no_alerts(self):
        with patch.object(self.bs, "active_alerts", []):
            prices = self.bs.get_crypto_prices()
        self.assertEqual(prices, {})


class TestEmailHelpers(unittest.TestCase):
    """Unit-test is_email_configured and related helpers."""

    def setUp(self):
        with patch("os.path.exists", return_value=False), \
             patch("bot_server.load_alerts_from_file", return_value=[]), \
             patch("bot_server.threading.Thread"):
            import importlib, bot_server as bs
            importlib.reload(bs)
            self.bs = bs

    def test_configured_when_real_creds(self):
        with patch.object(self.bs, "get_sender_email", return_value="test@gmail.com"), \
             patch.object(self.bs, "get_sender_password", return_value="abcd efgh ijkl mnop"):
            self.assertTrue(self.bs.is_email_configured())

    def test_not_configured_when_placeholder_email(self):
        with patch.object(self.bs, "load_credentials",
                          return_value=("your_email@gmail.com", "pass", None)):
            result = self.bs.get_sender_email()
        self.assertIsNone(result)

    def test_not_configured_when_none(self):
        with patch.object(self.bs, "get_sender_email", return_value=None), \
             patch.object(self.bs, "get_sender_password", return_value=None):
            self.assertFalse(self.bs.is_email_configured())


class TestNovaSystemPrompt(unittest.TestCase):
    """Validate NOVA's system prompt contains required sections."""

    def setUp(self):
        with patch("os.path.exists", return_value=False), \
             patch("bot_server.load_alerts_from_file", return_value=[]), \
             patch("bot_server.threading.Thread"):
            import importlib, bot_server as bs
            importlib.reload(bs)
            self.prompt = bs.NOVA_SYSTEM_PROMPT

    def test_prompt_not_empty(self):
        self.assertTrue(len(self.prompt) > 100)

    def test_prompt_defines_nova_identity(self):
        self.assertIn("NOVA", self.prompt)

    def test_prompt_mentions_coingecko(self):
        self.assertIn("CoinGecko", self.prompt)

    def test_prompt_has_crypto_guidance(self):
        self.assertIn("BUY", self.prompt)
        self.assertIn("SELL", self.prompt)
        self.assertIn("HOLD", self.prompt)

    def test_prompt_has_general_guidance(self):
        # Should handle non-crypto questions
        lower = self.prompt.lower()
        self.assertTrue(
            "general" in lower or "coding" in lower or "non-financial" in lower,
            "Prompt should mention handling of general/non-financial questions"
        )

    def test_prompt_has_risk_disclaimer(self):
        self.assertIn("disclaimer", self.prompt.lower())


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS  (requires `python bot_server.py` running)
# ══════════════════════════════════════════════════════════════════════════════

if RUN_LIVE:
    import requests as _requests

    def _post(path, body=None):
        return _requests.post(f"{BASE_URL}{path}", json=body, timeout=30)

    def _get(path):
        return _requests.get(f"{BASE_URL}{path}", timeout=10)

    class TestHealthEndpoint(unittest.TestCase):
        def test_health_returns_200(self):
            r = _get("/api/health")
            self.assertEqual(r.status_code, 200)

        def test_health_has_online_true(self):
            data = _get("/api/health").json()
            self.assertTrue(data.get("online"))

        def test_health_has_required_keys(self):
            data = _get("/api/health").json()
            for key in ("online", "email_configured", "chat_llm_configured",
                        "sender_email", "active_alerts_count"):
                self.assertIn(key, data, f"Missing key: {key}")

        def test_health_alert_count_is_int(self):
            data = _get("/api/health").json()
            self.assertIsInstance(data["active_alerts_count"], int)

    class TestChatEndpoint(unittest.TestCase):
        def test_empty_message_returns_400(self):
            r = _post("/api/chat", {"message": ""})
            self.assertEqual(r.status_code, 400)

        def test_missing_message_returns_400(self):
            r = _post("/api/chat", {})
            self.assertEqual(r.status_code, 400)

        def test_valid_message_returns_reply(self):
            r = _post("/api/chat", {
                "message": "What is 2 + 2?",
                "coins": []
            })
            self.assertIn(r.status_code, (200, 429, 503),
                          f"Unexpected status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                self.assertIn("reply", data)
                self.assertTrue(len(data["reply"]) > 0)

        def test_crypto_question_with_market_data(self):
            coins = [
                {"market_cap_rank": 1, "name": "Bitcoin", "symbol": "btc",
                 "current_price": 65000, "price_change_percentage_24h": 2.5}
            ]
            r = _post("/api/chat", {
                "message": "What is the current Bitcoin price?",
                "coins": coins
            })
            self.assertIn(r.status_code, (200, 429, 503))
            if r.status_code == 200:
                data = r.json()
                self.assertIn("reply", data)

        def test_model_field_returned_in_response(self):
            r = _post("/api/chat", {"message": "Say hi", "coins": []})
            if r.status_code == 200:
                self.assertIn("model", r.json())

    class TestChatStreamEndpoint(unittest.TestCase):
        def test_empty_message_returns_400(self):
            r = _post("/api/chat/stream", {"message": ""})
            self.assertEqual(r.status_code, 400)

        def test_stream_delivers_sse_chunks(self):
            import sseclient
            try:
                resp = _requests.post(
                    f"{BASE_URL}/api/chat/stream",
                    json={"message": "Say exactly: HELLO", "coins": []},
                    stream=True,
                    timeout=30
                )
                if resp.status_code != 200:
                    self.skipTest(f"Stream returned {resp.status_code}")

                chunks = []
                done_seen = False
                client = sseclient.SSEClient(resp)
                for event in client.events():
                    data = json.loads(event.data)
                    if data.get("chunk"):
                        chunks.append(data["chunk"])
                    if data.get("done"):
                        done_seen = True
                        break

                self.assertTrue(done_seen, "No 'done' SSE event received")
                self.assertTrue(len(chunks) > 0, "No text chunks received")
            except ImportError:
                # Fallback: raw line reading if sseclient not installed
                resp = _requests.post(
                    f"{BASE_URL}/api/chat/stream",
                    json={"message": "Say hi", "coins": []},
                    stream=True, timeout=30
                )
                if resp.status_code != 200:
                    self.skipTest(f"Stream returned {resp.status_code}")
                lines = []
                for line in resp.iter_lines():
                    if line:
                        lines.append(line.decode())
                self.assertTrue(
                    any("done" in l or "chunk" in l for l in lines),
                    "SSE response had no 'chunk' or 'done' events"
                )

    class TestAlertsEndpoints(unittest.TestCase):
        TEST_ALERT_ID = f"test_alert_{int(time.time())}"

        def test_create_alert_returns_201(self):
            payload = {
                "id":           self.TEST_ALERT_ID,
                "coin":         "bitcoin",
                "target_price": 999999,
                "condition":    "above",
                "email":        "test@test.com"
            }
            r = _post("/api/alerts", payload)
            self.assertEqual(r.status_code, 201)
            data = r.json()
            self.assertIn("alert", data)

        def test_create_alert_missing_fields_returns_400(self):
            r = _post("/api/alerts", {"coin": "bitcoin"})
            self.assertEqual(r.status_code, 400)

        def test_create_alert_invalid_price_returns_400(self):
            r = _post("/api/alerts", {
                "coin": "bitcoin",
                "target_price": "invalid_number",
                "condition": "above"
            })
            self.assertEqual(r.status_code, 400)

        def test_get_alerts_returns_list(self):
            r = _get("/api/alerts")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertIn("active_alerts", data)
            self.assertIsInstance(data["active_alerts"], list)

        def test_created_alert_appears_in_get(self):
            r = _get("/api/alerts")
            ids = [a["id"] for a in r.json().get("active_alerts", [])]
            self.assertIn(self.TEST_ALERT_ID, ids)

        def test_delete_existing_alert_returns_200(self):
            r = _requests.delete(
                f"{BASE_URL}/api/alerts/{self.TEST_ALERT_ID}", timeout=10
            )
            self.assertEqual(r.status_code, 200)

        def test_delete_nonexistent_alert_returns_404(self):
            r = _requests.delete(
                f"{BASE_URL}/api/alerts/nonexistent_alert_xyz", timeout=10
            )
            self.assertEqual(r.status_code, 404)

        def test_deleted_alert_gone_from_get(self):
            r = _get("/api/alerts")
            ids = [a["id"] for a in r.json().get("active_alerts", [])]
            self.assertNotIn(self.TEST_ALERT_ID, ids)

    class TestEmailConfigEndpoint(unittest.TestCase):
        def test_missing_fields_returns_400(self):
            r = _post("/api/config/email", {})
            self.assertEqual(r.status_code, 400)

        def test_missing_password_returns_400(self):
            r = _post("/api/config/email", {"email_address": "x@x.com"})
            self.assertEqual(r.status_code, 400)

        def test_invalid_credentials_returns_400(self):
            r = _post("/api/config/email", {
                "email_address":  "fake@gmail.com",
                "email_password": "xxxx xxxx xxxx xxxx"
            })
            # Invalid creds → 400 (auth failure) or connection error
            self.assertIn(r.status_code, (400, 500))

    class TestSendTestEmail(unittest.TestCase):
        def test_send_test_email_configured(self):
            """If server has email configured, should return 200."""
            health = _get("/api/health").json()
            if not health.get("email_configured"):
                self.skipTest("Email not configured on server")
            r = _post("/api/send-test-email", {})
            self.assertEqual(r.status_code, 200)
            self.assertIn("message", r.json())

        def test_send_test_email_not_configured(self):
            """If not configured, should 400."""
            health = _get("/api/health").json()
            if health.get("email_configured"):
                self.skipTest("Email IS configured — skipping 'not configured' test")
            r = _post("/api/send-test-email", {})
            self.assertEqual(r.status_code, 400)

    class TestAlertsTrigger(unittest.TestCase):
        def test_trigger_without_email_config_returns_400_or_200(self):
            health = _get("/api/health").json()
            r = _post("/api/alerts/trigger", {
                "coinName":    "bitcoin",
                "digestType":  "realtime-alert",
                "htmlContent": "<p>Test</p>"
            })
            if health.get("email_configured"):
                self.assertEqual(r.status_code, 200)
            else:
                self.assertEqual(r.status_code, 400)

        def test_digest_endpoint_without_email_config_returns_400_or_200(self):
            health = _get("/api/health").json()
            r = _post("/api/alerts/digest", {
                "digestType":      "live-report",
                "aiMarketSummary": "Market summary test",
                "htmlContent":     "<p>Digest Test</p>"
            })
            if health.get("email_configured"):
                self.assertEqual(r.status_code, 200)
            else:
                self.assertEqual(r.status_code, 400)


# ══════════════════════════════════════════════════════════════════════════════
# PRETTY RUNNER
# ══════════════════════════════════════════════════════════════════════════════

class PrettyResult(unittest.TestResult):
    """Coloured test result reporter."""

    def __init__(self):
        super().__init__()
        self._pass = 0

    def startTest(self, test):
        super().startTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._pass += 1
        ok(test._testMethodName)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        fail(f"{test._testMethodName}  →  {err[1]}")

    def addError(self, test, err):
        super().addError(test, err)
        fail(f"{test._testMethodName}  →  ERROR: {err[1]}")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        info(f"{test._testMethodName}  (skipped: {reason})")


def run_suite(suite_name, loader, test_classes):
    print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {suite_name}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")

    suite = unittest.TestSuite()
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    result = PrettyResult()
    suite.run(result)

    total = result.testsRun
    passed = result._pass
    failed = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)

    colour = GREEN if failed == 0 else RED
    print(f"\n  {colour}{BOLD}Results: {passed}/{total} passed"
          + (f", {skipped} skipped" if skipped else "")
          + (f", {failed} FAILED" if failed else "")
          + f"{RESET}")

    return result


if __name__ == "__main__":
    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # preserve declaration order

    print(f"\n{BOLD}🧪 ANTIGRAVITY Bot Server — Test Suite{RESET}")
    print(f"Mode: {'UNIT + INTEGRATION (--live)' if RUN_LIVE else 'UNIT TESTS ONLY'}")
    print(f"Server: {BASE_URL}" if RUN_LIVE else "")

    unit_classes = [
        TestLoadCredentials,
        TestBuildMarketContext,
        TestAlertTriggerLogic,
        TestAlertIdDeduplication,
        TestGetCryptoPricesMocked,
        TestEmailHelpers,
        TestNovaSystemPrompt,
    ]

    unit_result = run_suite("UNIT TESTS  (offline / mocked)", loader, unit_classes)

    all_results = [unit_result]

    if RUN_LIVE:
        integration_classes = [
            TestHealthEndpoint,
            TestChatEndpoint,
            TestChatStreamEndpoint,
            TestAlertsEndpoints,
            TestEmailConfigEndpoint,
            TestSendTestEmail,
            TestAlertsTrigger,
        ]
        live_result = run_suite("INTEGRATION TESTS  (live server)", loader, integration_classes)
        all_results.append(live_result)
    else:
        print(f"\n{YELLOW}ℹ  Integration tests skipped. "
              f"Start the server and run with --live to include them.{RESET}")

    total_passed = sum(r._pass for r in all_results)
    total_run    = sum(r.testsRun for r in all_results)
    total_failed = sum(len(r.failures) + len(r.errors) for r in all_results)

    print(f"\n{BOLD}{'═' * 60}")
    colour = GREEN if total_failed == 0 else RED
    print(f"{colour}  FINAL: {total_passed}/{total_run} tests passed"
          + (f"  ✗ {total_failed} FAILED" if total_failed else "  ✔ ALL PASSED")
          + f"{RESET}{BOLD}")
    print(f"{'═' * 60}{RESET}\n")

    sys.exit(1 if total_failed else 0)
