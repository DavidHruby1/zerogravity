import json
import os
import subprocess
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts import check_proxy


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_proxy.py"
EMAIL = "fixture@example.invalid"
API_KEY = "local-key"
REFRESH_TOKEN = "fixture-refresh-token"
FIXTURE_STATUS = {
    "/health": {"status": "ok"},
    "/v1/models": {"data": [{"id": "test-model"}]},
    "/v1/accounts": {"accounts": [{
        "email": EMAIL, "refresh_token": REFRESH_TOKEN, "active": True, "disabled": False,
    }]},
    "/v1/accounts/status": {"accounts": [{
        "index": 0, "email": EMAIL, "state": "active",
    }], "active_index": 0},
}


def sse_event(event_type, **fields):
    body = json.dumps({"type": event_type, **fields})
    return f"event: {event_type}\r\ndata: {body}\r\n\r\n".encode()


def message_start():
    return sse_event("message_start", message={"role": "assistant", "content": []})


def message_end(reason):
    return sse_event("message_delta", delta={"stop_reason": reason}) + sse_event("message_stop")


def tool_response(turn, name=None, arguments=None):
    expected_names = ("probe_seed", "probe_check")
    expected_values = ("start", "zg-probe-second-value")
    payload = json.dumps({"value": expected_values[turn]} if arguments is None else arguments)
    return b"".join([
        sse_event("ping"),
        message_start(),
        sse_event("content_block_start", index=0, content_block={
            "type": "tool_use", "id": f"toolu_{turn}", "name": name or expected_names[turn], "input": {},
        }),
        sse_event("content_block_delta", index=0,
                  delta={"type": "input_json_delta", "partial_json": payload[:8]}),
        sse_event("content_block_delta", index=0,
                  delta={"type": "input_json_delta", "partial_json": payload[8:]}),
        sse_event("content_block_stop", index=0),
        message_end("tool_use"),
    ])


def text_response(text="zg-probe-complete"):
    return b"".join([
        message_start(),
        sse_event("content_block_start", index=0, content_block={"type": "text", "text": ""}),
        sse_event("content_block_delta", index=0, delta={"type": "text_delta", "text": text}),
        sse_event("content_block_stop", index=0),
        message_end("end_turn"),
    ])


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("x-api-key"), None))
        self.server.respond(self, None)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, self.headers.get("x-api-key"), payload))
        self.server.respond(self, payload)

    def reply(self, status, body, **headers):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def json_reply(self, status, payload, **headers):
        self.reply(status, json.dumps(payload).encode(), **{"Content-Type": "application/json", **headers})

    def sse_reply(self, body, terminate=True):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Server-Timing", "other;dur=72, queue;dur=12.5")
        self.end_headers()
        for segment in (body[:17], body[17:]):
            if segment:
                self.wfile.write(f"{len(segment):x}\r\n".encode() + segment + b"\r\n")
        if terminate:
            self.wfile.write(b"0\r\n\r\n")


@contextmanager
def fixture(respond):
    with ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler) as server:
        server.respond = respond
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


def probe_for(server, timeout=2):
    return check_proxy.Probe("127.0.0.1", server.server_port, API_KEY, timeout)


class StatusTests(unittest.TestCase):
    def test_healthy_api_does_not_hide_empty_managed_accounts(self):
        payloads = {
            **FIXTURE_STATUS,
            "/v1/accounts": {"accounts": []},
            "/v1/accounts/status": {"accounts": [], "active_index": None},
        }
        with fixture(lambda handler, _: handler.json_reply(200, payloads[handler.path])) as server:
            report = check_proxy.check_status(probe_for(server))
        self.assertTrue(report["api_healthy"])
        self.assertFalse(report["single_managed_account_active"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"][-1]["active_count"], 0)

    def test_process_health_is_independent_of_protected_api_access(self):
        def respond(handler, _):
            if handler.path == "/health":
                handler.json_reply(200, FIXTURE_STATUS[handler.path])
            else:
                handler.json_reply(401, {"error": "Invalid API key"})

        with fixture(respond) as server:
            report = check_proxy.check_status(probe_for(server))
        self.assertTrue(report["process_healthy"])
        self.assertFalse(report["api_healthy"])
        self.assertFalse(report["single_managed_account_active"])
        self.assertEqual([check["http_status"] for check in report["checks"]], [200, 401, 401, 401])

    def test_cli_checks_authenticated_api_without_printing_individual_credentials(self):
        with fixture(lambda handler, _: handler.json_reply(200, FIXTURE_STATUS[handler.path])) as server:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--base-url", f"http://localhost:{server.server_port}", "status"],
                env={**os.environ, "ZEROGRAVITY_API_KEY": f",{API_KEY},second-key"},
                capture_output=True, text=True, check=True, timeout=4,
            )
        self.assertTrue(json.loads(result.stdout)["single_managed_account_active"])
        for item in (API_KEY, "second-key", EMAIL, REFRESH_TOKEN):
            self.assertNotIn(item, result.stdout + result.stderr)
        self.assertEqual([path for path, _, _ in server.requests], list(FIXTURE_STATUS))
        self.assertTrue(all(key == API_KEY and payload is None for _, key, payload in server.requests))

    def test_bounded_status_observes_api_recovery_without_completion_requests(self):
        def respond(handler, _):
            if len(handler.server.requests) == 1:
                handler.json_reply(503, {"error": "backend restarting"})
            else:
                handler.json_reply(200, FIXTURE_STATUS[handler.path])

        with fixture(respond) as server:
            report = check_proxy.wait_ready(probe_for(server), 2)
        self.assertTrue(report["observed_api_recovery"])
        self.assertEqual(len(report["samples"]), 2)
        self.assertEqual(report["samples"][0]["checks"][0]["outcome"], "backend_recovering")
        self.assertTrue(all(payload is None for _, _, payload in server.requests))

    def test_single_managed_account_requires_matching_active_records(self):
        cases = (
            (
                {"email": EMAIL, "active": True, "disabled": True},
                {"index": 0, "email": EMAIL, "state": "active"},
            ),
            (
                {"email": EMAIL, "active": True, "disabled": False},
                {"index": 0, "email": "different@example.invalid", "state": "active"},
            ),
            (
                {"email": EMAIL, "active": True, "disabled": False},
                {"index": 0, "email": EMAIL, "state": "restricted"},
            ),
        )
        for listed, status in cases:
            with self.subTest(listed=listed, status=status):
                payloads = {
                    **FIXTURE_STATUS,
                    "/v1/accounts": {"accounts": [listed]},
                    "/v1/accounts/status": {"accounts": [status], "active_index": 0},
                }
                with fixture(lambda handler, _: handler.json_reply(200, payloads[handler.path])) as server:
                    report = check_proxy.check_status(probe_for(server))
                self.assertTrue(report["api_healthy"])
                self.assertFalse(report["single_managed_account_active"])


class StreamTests(unittest.TestCase):
    def test_two_tool_turns_and_final_message_round_trip(self):
        def respond(handler, payload):
            turn = len(payload["messages"]) // 2
            body = tool_response(turn) if turn < 2 else text_response()
            handler.sse_reply(body)

        with fixture(respond) as server:
            report = check_proxy.check_stream(probe_for(server), "test-model")
        self.assertTrue(report["ok"], report)
        self.assertEqual([item["stop_reason"] for item in report["checks"]], ["tool_use", "tool_use", "end_turn"])
        for item in report["checks"]:
            self.assertLessEqual(item["headers_ms"], item["first_event_ms"])
            self.assertLessEqual(item["first_event_ms"], item["message_stop_ms"])
            self.assertLessEqual(item["message_stop_ms"], item["duration_ms"])
            self.assertEqual(item["server_queue_ms"], 12.5)
            self.assertTrue(item["response_complete"])
        payloads = [payload for _, _, payload in server.requests]
        self.assertEqual([p["tool_choice"].get("name") for p in payloads], ["probe_seed", "probe_check", None])
        self.assertEqual(payloads[2]["tool_choice"], {"type": "none"})
        for i, expected_value in enumerate(("start", "zg-probe-second-value")):
            assistant = payloads[i + 1]["messages"][-2]
            user = payloads[i + 1]["messages"][-1]
            call = assistant["content"][0]
            self.assertEqual(call["input"], {"value": expected_value})
            self.assertEqual(user["content"][0], {
                "type": "tool_result", "tool_use_id": call["id"],
                "content": ("zg-probe-second-value", "zg-probe-complete")[i],
            })

    def test_second_turn_tool_mismatch_aborts_after_two_requests(self):
        variants = (
            ("tool_name_mismatch", tool_response(1, name="probe_seed")),
            ("tool_arguments_mismatch", tool_response(1, arguments={})),
            ("expected_single_tool_use", text_response('{"name":"probe_check","input":{}}')),
        )
        for outcome, body in variants:
            with self.subTest(outcome=outcome):
                def respond(handler, _):
                    handler.sse_reply(tool_response(0) if len(handler.server.requests) == 1 else body)

                with fixture(respond) as server:
                    report = check_proxy.check_stream(probe_for(server), "test-model")
                self.assertFalse(report["ok"])
                self.assertEqual(len(server.requests), 2)
                self.assertEqual(report["checks"][-1]["outcome"], outcome)

    def test_terminal_event_and_transport_completion_are_independent(self):
        missing_stop = tool_response(0).split(b"event: message_stop")[0]
        with fixture(lambda handler, _: handler.sse_reply(missing_stop)) as server:
            report = check_proxy.check_stream(probe_for(server), "test-model")
        self.assertEqual(report["checks"][0]["outcome"], "missing_message_stop")
        self.assertTrue(report["checks"][0]["response_complete"])

        with fixture(lambda handler, _: handler.sse_reply(tool_response(0), terminate=False)) as server:
            report = check_proxy.check_stream(probe_for(server), "test-model")
        self.assertEqual(report["checks"][0]["outcome"], "incomplete_response")
        self.assertIn("message_stop_ms", report["checks"][0])
        self.assertFalse(report["checks"][0]["response_complete"])

    def test_truncated_chunk_trailers_prevent_follow_up(self):
        for trailer in (b"0\r\n", b"0\r\nX-Trailer: value\r\n"):
            with self.subTest(trailer=trailer):
                def respond(handler, _):
                    handler.sse_reply(tool_response(0), terminate=False)
                    handler.wfile.write(trailer)

                with fixture(respond) as server:
                    report = check_proxy.check_stream(probe_for(server), "test-model")
                self.assertEqual(len(server.requests), 1)
                self.assertEqual(report["checks"][0]["outcome"], "incomplete_response")
                self.assertIn("message_stop_ms", report["checks"][0])
                self.assertFalse(report["checks"][0]["response_complete"])

    def test_deadline_after_message_stop_prevents_follow_up(self):
        release = threading.Event()

        def respond(handler, _):
            handler.sse_reply(tool_response(0), terminate=False)
            release.wait(1)

        with fixture(respond) as server:
            started = time.monotonic()
            report = check_proxy.check_stream(probe_for(server, timeout=0.15), "test-model")
            release.set()
        self.assertLess(time.monotonic() - started, 0.75)
        self.assertEqual(report["checks"][0]["outcome"], "deadline_exceeded")
        self.assertIn("message_stop_ms", report["checks"][0])
        self.assertFalse(report["checks"][0]["response_complete"])
        self.assertEqual(len(server.requests), 1)

    def test_http_errors_preserve_status_and_reason_without_retries_or_raw_details(self):
        cases = (
            (401, "No OAuth token", "missing_oauth_token"),
            (401, "Invalid API key", "unauthorized"),
            (403, "PERMISSION_DENIED", "forbidden"),
            (403, "Possible violation of Terms of Service", "forbidden"),
            (403, "TERMS_OF_SERVICE_VIOLATION", "provider_terms_restriction"),
            (403, "This service has been disabled in this account for violation of Terms of Service.",
             "provider_terms_restriction"),
            (503, "Request queue is full", "queue_full"),
            (503, "MODEL_CAPACITY_EXHAUSTED", "model_capacity_exhausted"),
            (503, "Temporarily unavailable", "unavailable"),
            (504, "Gateway Timeout", "gateway_timeout"),
        )
        for status, detail, expected in cases:
            with self.subTest(status=status, expected=expected):
                def respond(handler, _):
                    handler.json_reply(status, {"error": {"message": f"{detail} {EMAIL}"}}, **{"Retry-After": "3"})

                with fixture(respond) as server:
                    report = check_proxy.check_stream(probe_for(server), "test-model")
                self.assertFalse(report["ok"])
                self.assertEqual(len(server.requests), 1)
                self.assertEqual(report["checks"][0]["http_status"], status)
                self.assertEqual(report["checks"][0]["outcome"], expected)
                self.assertEqual(report["checks"][0]["retry_after_seconds"], 3)
                self.assertNotIn(EMAIL, json.dumps(report))

    def test_redirect_is_a_failure_and_is_not_followed(self):
        with fixture(lambda handler, _: handler.reply(302, b"", Location="/unexpected")) as server:
            report = check_proxy.check_stream(probe_for(server), "test-model")
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"][0]["http_status"], 302)
        self.assertEqual([path for path, _, _ in server.requests], ["/v1/messages"])

    def test_error_after_output_does_not_trigger_another_request(self):
        error = sse_event("error", error={"type": "overloaded_error", "message": "too busy"})
        partial = message_start() + sse_event(
            "content_block_start", index=0, content_block={"type": "text", "text": "partial output"},
        )
        with fixture(lambda handler, _: handler.sse_reply(partial + error)) as server:
            report = check_proxy.check_stream(probe_for(server), "test-model")
        self.assertEqual(report["checks"][0]["http_status"], 200)
        self.assertEqual(report["checks"][0]["outcome"], "stream_overloaded")
        self.assertIn("message_start_ms", report["checks"][0])
        self.assertEqual(len(server.requests), 1)


if __name__ == "__main__":
    unittest.main()
