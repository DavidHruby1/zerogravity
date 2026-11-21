#!/usr/bin/env python3
"""Check a loopback ZeroGravity API with a bounded, synthetic probe."""

import argparse
import http.client
import json
import math
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TRAILER_LINE_BYTES = 64 * 1024
TOOLS = ("probe_seed", "probe_check")
INPUTS = ({"value": "start"}, {"value": "zg-probe-second-value"})
RESULTS = ("zg-probe-second-value", "zg-probe-complete")
STOP_REASONS = {
    "end_turn", "max_tokens", "stop_sequence", "tool_use", "pause_turn",
    "refusal", "model_context_window_exceeded",
}
HTTP_FAILURES = {
    401: "unauthorized",
    403: "forbidden",
    408: "request_timeout",
    429: "rate_limited",
    503: "unavailable",
    504: "gateway_timeout",
    529: "overloaded",
}


class ProbeError(Exception):
    """A fixed diagnostic identifier safe to print."""


class ProbeResponse(http.client.HTTPResponse):
    def _read_and_discard_trailer(self):
        # The standard parser tolerates EOF here, but a probe needs to detect truncation.
        while True:
            line = self.fp.readline(MAX_TRAILER_LINE_BYTES + 1)
            if len(line) > MAX_TRAILER_LINE_BYTES:
                raise http.client.LineTooLong("chunk trailer")
            if not line.endswith(b"\r\n"):
                raise http.client.IncompleteRead(b"")
            if line == b"\r\n":
                return


def failure_kind(status, body):
    detail = body.lower()
    if b"terms_of_service_violation" in detail or (
        b"terms of service" in detail and
        (b"service has been disabled" in detail or b"account has been disabled" in detail)
    ):
        return "provider_terms_restriction"
    if status in (200, 401) and b"no oauth token" in detail:
        return "missing_oauth_token"
    if status in (200, 408, 429, 503, 504, 529):
        if b"model_capacity_exhausted" in detail or b"exhausted your capacity on this model" in detail:
            return "model_capacity_exhausted"
        if b"queue is full" in detail or b"queue full" in detail:
            return "queue_full"
        if b"queue timeout" in detail or b"timed out waiting in the queue" in detail:
            return "queue_timeout"
        if b"recovery mode" in detail or b"backend restarting" in detail:
            return "backend_recovering"
    if status == 200:
        return "stream_overloaded" if b'"overloaded_error"' in detail else "stream_error"
    return HTTP_FAILURES.get(status, "http_error")


def read_body(response):
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ProbeError("response_too_large")
    if response.length not in (None, 0):
        raise ProbeError("incomplete_response")
    return body


def decode_json(data, error):
    try:
        return json.loads(data)
    except (UnicodeError, ValueError, RecursionError):
        raise ProbeError(error) from None


def read_json(response, _report, _elapsed_ms):
    return decode_json(read_body(response), "invalid_json")


def read_health(response, _report, _elapsed_ms):
    read_body(response)


def response_metadata(response, report):
    queue = re.search(
        r"(?:^|,)\s*queue\s*;\s*dur\s*=\s*([0-9]+(?:\.[0-9]+)?)(?=\s*(?:[,;]|$))",
        response.getheader("Server-Timing", ""),
        re.IGNORECASE,
    )
    if queue:
        duration = float(queue[1])
        if math.isfinite(duration):
            report["server_queue_ms"] = duration
    retry_after = response.getheader("Retry-After", "")
    if re.fullmatch(r"[0-9]{1,10}", retry_after):
        report["retry_after_seconds"] = int(retry_after)
    elif retry_after:
        try:
            date = parsedate_to_datetime(retry_after)
            if date and date.tzinfo:
                seconds = (date - datetime.now(timezone.utc)).total_seconds()
                report["retry_after_seconds"] = max(0, math.ceil(seconds))
        except (ValueError, OverflowError):
            pass


class Probe:
    def __init__(self, host, port, api_key, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.headers = {"Connection": "close"}
        if api_key:
            self.headers["x-api-key"] = api_key

    def request(self, path, payload=None, read=read_json, deadline=None):
        started = time.monotonic()
        request_deadline = started + self.timeout
        if deadline is not None:
            request_deadline = min(request_deadline, deadline)

        def elapsed_ms():
            return round((time.monotonic() - started) * 1000, 1)

        report = {"path": path, "http_status": None}
        if request_deadline <= started:
            return {**report, "outcome": "deadline_exceeded", "duration_ms": 0}, None
        result = None
        timer = None
        timed_out = threading.Event()
        connection = http.client.HTTPConnection(self.host, self.port, timeout=request_deadline - started)
        connection.response_class = ProbeResponse
        try:
            connection.connect()
            connected_socket = connection.sock

            def expire():
                timed_out.set()
                try:
                    connected_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            # Apply one deadline across headers and body, including a slow drip of data.
            timer = threading.Timer(max(0, request_deadline - time.monotonic()), expire)
            timer.daemon = True
            timer.start()
            if payload is None:
                connection.request("GET", path, headers=self.headers)
            else:
                headers = {
                    **self.headers,
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "anthropic-version": "2023-06-01",
                }
                connection.request("POST", path, body=json.dumps(payload), headers=headers)
            with connection.getresponse() as response:
                report["http_status"] = response.status
                report["headers_ms"] = elapsed_ms()
                response_metadata(response, report)
                if response.status == 200:
                    result = read(response, report, elapsed_ms)
                    report["outcome"] = "ok"
                else:
                    report["outcome"] = failure_kind(response.status, read_body(response))
        except ProbeError as error:
            report["outcome"] = str(error)
        except TimeoutError:
            report["outcome"] = "deadline_exceeded"
        except http.client.IncompleteRead:
            report["outcome"] = "incomplete_response"
        except (OSError, http.client.HTTPException):
            report["outcome"] = "connection_error"
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()

        if timed_out.is_set() or time.monotonic() >= request_deadline:
            report["outcome"] = "deadline_exceeded"
            if "response_complete" in report:
                report["response_complete"] = False
        report["duration_ms"] = elapsed_ms()
        return report, result


def account_rows(report, payload):
    if report["outcome"] != "ok":
        return None
    rows = payload.get("accounts") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) and isinstance(row.get("email"), str) and row["email"]
        for row in rows
    ):
        report["outcome"] = "invalid_accounts_response"
        return None
    report["account_count"] = len(rows)
    report["blocked_account_count"] = sum(account_blocked(row) for row in rows)
    return rows


def account_blocked(row):
    return row.get("state") in ("banned", "restricted", "disabled") or any(
        row.get(flag) is True for flag in ("banned", "restricted", "disabled")
    )


def active_accounts(report, payload, rows):
    if rows is None:
        return []
    if isinstance(payload, dict) and "active_index" in payload:
        index = payload["active_index"]
        if index is None:
            selected = []
        else:
            selected = [
                row for position, row in enumerate(rows)
                if type(row.get("index", position)) is int and row.get("index", position) == index
            ]
            if type(index) is not int or index < 0 or len(selected) != 1:
                report["outcome"] = "invalid_active_account_index"
                return []
    elif all("state" in row or isinstance(row.get("active"), bool) for row in rows):
        selected = [row for row in rows if row.get("state") == "active" or row.get("active") is True]
    else:
        report["outcome"] = "active_account_status_unavailable"
        return []
    active = [
        row for row in selected
        if row.get("state", "active") == "active" and row.get("active", True) is True
    ]
    report["active_count"] = len(active)
    report["active_account_blocked"] = any(account_blocked(row) for row in selected)
    return active


def check_status(probe, deadline=None):
    health, _ = probe.request("/health", read=read_health, deadline=deadline)
    models, model_list = probe.request("/v1/models", deadline=deadline)
    accounts, account_list = probe.request("/v1/accounts", deadline=deadline)
    status, account_status = probe.request("/v1/accounts/status", deadline=deadline)
    if models["outcome"] == "ok":
        if isinstance(model_list, dict) and isinstance(model_list.get("data"), list):
            models["model_count"] = len(model_list["data"])
        else:
            models["outcome"] = "invalid_models_response"
    listed = account_rows(accounts, account_list)
    reported = account_rows(status, account_status)
    active = active_accounts(status, account_status, reported)
    if listed is not None and len(listed) == len(active) == 1:
        status["matches_listed_account"] = listed[0]["email"] == active[0]["email"]
    single_managed_account = (
        status.get("matches_listed_account") is True
        and status.get("account_count") == 1
        and listed[0].get("active", True) is True
        and accounts["blocked_account_count"] == 0
        and status.get("active_account_blocked") is False
    )
    process_healthy = health["outcome"] == "ok"
    api_healthy = process_healthy and models["outcome"] == "ok"
    return {
        "ok": api_healthy and single_managed_account,
        "process_healthy": process_healthy,
        "api_healthy": api_healthy,
        "single_managed_account_active": single_managed_account,
        "checks": [health, models, accounts, status],
    }


def wait_ready(probe, seconds):
    started = time.monotonic()
    deadline = started + seconds
    samples = []
    while True:
        report = check_status(probe, deadline)
        now = time.monotonic()
        samples.append({**report, "elapsed_ms": round((now - started) * 1000, 1)})
        if report["ok"] or now >= deadline:
            break
        time.sleep(min(1, deadline - now))
        if time.monotonic() >= deadline:
            break
    return {
        "ok": report["ok"],
        "observed_api_recovery": len(samples) > 1 and report["ok"],
        "samples": samples,
    }


def sse_lines(response):
    remaining = MAX_RESPONSE_BYTES
    pending = b""
    # HTTPResponse.readline uses a best-effort peek on chunked bodies, where
    # a missing terminating chunk can be mistaken for a clean EOF.
    while chunk := response.read1(min(8192, remaining + 1)):
        remaining -= len(chunk)
        if remaining < 0:
            raise ProbeError("response_too_large")
        *lines, pending = (pending + chunk).split(b"\n")
        for line in lines:
            yield line.removesuffix(b"\r")
    if response.length not in (None, 0) or pending:
        raise ProbeError("incomplete_response")


def sse_events(response):
    name = None
    data = []
    for line in sse_lines(response):
        if not line:
            if data:
                body = b"\n".join(data)
                event = decode_json(body, "invalid_event_json")
                if not isinstance(event, dict) or not name or event.get("type") != name:
                    raise ProbeError("invalid_sse_event")
                yield name, event, body
            name, data = None, []
        else:
            field, _, value = line.partition(b":")
            value = value.removeprefix(b" ")
            if field == b"event":
                try:
                    name = value.decode("ascii")
                except UnicodeError:
                    raise ProbeError("invalid_sse_event") from None
            elif field == b"data":
                data.append(value)
    if data or name:
        raise ProbeError("incomplete_response")


def append_delta(block, delta, tool_input):
    if not isinstance(delta, dict):
        raise ProbeError("invalid_content_delta")
    delta_type = delta.get("type")
    if delta_type == "input_json_delta":
        fragment = delta.get("partial_json")
        if block["type"] != "tool_use" or not isinstance(fragment, str):
            raise ProbeError("invalid_tool_arguments")
        tool_input.append(fragment)
        return
    fields = {
        ("text", "text_delta"): "text",
        ("thinking", "thinking_delta"): "thinking",
        ("thinking", "signature_delta"): "signature",
    }
    if not isinstance(delta_type, str):
        raise ProbeError("invalid_content_delta")
    field = fields.get((block["type"], delta_type))
    if field:
        if not isinstance(delta.get(field), str) or not isinstance(block.get(field, ""), str):
            raise ProbeError("invalid_content_delta")
        block[field] = block.get(field, "") + delta[field]
    elif delta_type in ("text_delta", "thinking_delta", "signature_delta"):
        raise ProbeError("invalid_content_delta")


def read_stream(response, report, elapsed_ms):
    report["response_complete"] = False
    media_type = response.getheader("Content-Type", "").split(";")[0].strip().lower()
    if media_type != "text/event-stream":
        raise ProbeError("expected_sse_content_type")
    started = False
    stopped = False
    stop_reason = None
    content = []
    open_blocks = {}
    for kind, event, raw in sse_events(response):
        if "first_event_ms" not in report:
            report["first_event_ms"] = elapsed_ms()
        if kind == "ping":
            continue
        if kind == "error":
            raise ProbeError(failure_kind(200, raw))
        if stopped:
            raise ProbeError("event_after_message_stop")
        if kind == "message_start":
            message = event.get("message")
            if started or not isinstance(message, dict) or message.get("content") != []:
                raise ProbeError("invalid_message_start")
            started = True
            report["message_start_ms"] = elapsed_ms()
        elif kind == "message_delta":
            delta = event.get("delta")
            if not started or open_blocks or not isinstance(delta, dict):
                raise ProbeError("invalid_message_delta")
            reason = delta.get("stop_reason")
            if reason is not None:
                if not isinstance(reason, str) or stop_reason is not None:
                    raise ProbeError("invalid_stop_reason")
                stop_reason = reason
                report["stop_reason"] = reason if reason in STOP_REASONS else "unknown"
        elif kind == "message_stop":
            report["message_stop_ms"] = elapsed_ms()
            if not started or open_blocks or stop_reason is None:
                raise ProbeError("invalid_message_stop")
            stopped = True
        elif kind in ("content_block_start", "content_block_delta", "content_block_stop"):
            index = event.get("index")
            if not started or stop_reason is not None or type(index) is not int:
                raise ProbeError("invalid_content_block")
            if kind == "content_block_start":
                block = event.get("content_block")
                if (index != len(content) or not isinstance(block, dict)
                        or not isinstance(block.get("type"), str)):
                    raise ProbeError("invalid_content_block")
                content.append(block)
                open_blocks[index] = []
            elif index not in open_blocks:
                raise ProbeError("content_block_not_open")
            elif kind == "content_block_delta":
                append_delta(content[index], event.get("delta"), open_blocks[index])
            else:
                fragments = open_blocks.pop(index)
                if fragments:
                    content[index]["input"] = decode_json("".join(fragments), "invalid_tool_arguments")
    report["response_complete"] = True
    if not stopped:
        raise ProbeError("missing_message_stop")
    return content, stop_reason


def stream_payload(model, messages, turn):
    tools = [
        {
            "name": name,
            "description": "Accept one string for a synthetic transport probe.",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        }
        for name in TOOLS
    ]
    choice = {"type": "none"}
    if turn < len(TOOLS):
        choice = {"type": "tool", "name": TOOLS[turn], "disable_parallel_tool_use": True}
    return {
        "model": model, "max_tokens": 256, "stream": True,
        "messages": messages, "tools": tools, "tool_choice": choice,
    }


def validate_turn(content, stop_reason, turn, prior_ids):
    calls = [block for block in content if block["type"] == "tool_use"]
    if turn == len(TOOLS):
        if calls or stop_reason != "end_turn":
            raise ProbeError("expected_final_text")
        parts = [block.get("text") for block in content if block["type"] == "text"]
        if not all(isinstance(part, str) for part in parts) or "".join(parts).strip() != RESULTS[-1]:
            raise ProbeError("final_result_mismatch")
        return None

    if len(calls) != 1 or stop_reason != "tool_use":
        raise ProbeError("expected_single_tool_use")
    call = calls[0]
    if call.get("name") != TOOLS[turn]:
        raise ProbeError("tool_name_mismatch")
    if call.get("input") != INPUTS[turn]:
        raise ProbeError("tool_arguments_mismatch")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id or call_id in prior_ids:
        raise ProbeError("invalid_tool_use_id")
    return call_id


def check_stream(probe, model):
    messages = [{
        "role": "user",
        "content": (
            'Call probe_seed with value "start". After its result, call probe_check with '
            "value equal to that result. After the second tool result, reply with only "
            "its exact text."
        ),
    }]
    checks = []
    prior_ids = set()
    for turn in range(len(TOOLS) + 1):
        report, result = probe.request("/v1/messages", stream_payload(model, messages, turn), read_stream)
        report["turn"] = turn + 1
        checks.append(report)
        if report["outcome"] != "ok":
            break
        content, stop_reason = result
        try:
            call_id = validate_turn(content, stop_reason, turn, prior_ids)
        except ProbeError as error:
            report["outcome"] = str(error)
            break
        if call_id:
            prior_ids.add(call_id)
            messages.extend([
                {"role": "assistant", "content": content},
                {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": call_id, "content": RESULTS[turn],
                }]},
            ])
    return {"ok": len(checks) == len(TOOLS) + 1 and checks[-1]["outcome"] == "ok", "checks": checks}


def loopback_url(value):
    match = re.fullmatch(r"http://(127\.0\.0\.1|localhost|\[::1\])(?::([0-9]{1,5}))?/?", value)
    if not match:
        raise argparse.ArgumentTypeError("use an HTTP loopback URL with an optional port")
    host = "127.0.0.1" if match[1] == "localhost" else match[1].strip("[]")
    port = int(match[2] or 80)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return host, port


def timeout_seconds(value):
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a positive number of seconds") from None
    if not math.isfinite(seconds) or not 0 < seconds <= 3600:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 3600 seconds")
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=loopback_url, default="http://127.0.0.1:8741")
    parser.add_argument("--timeout", type=timeout_seconds, default=30, help="deadline in seconds per request")
    checks = parser.add_subparsers(dest="check", required=True)
    status = checks.add_parser("status", help="check process/API health and managed account state")
    status.add_argument("--wait-ready", type=timeout_seconds, metavar="SECONDS",
                        help="repeat read-only status checks within this deadline")
    stream = checks.add_parser("stream", help="check two synthetic tool calls and the final response")
    stream.add_argument("--model", required=True, help="configured model for the authorized test backend")
    args = parser.parse_args()
    keys = os.environ.get("ZEROGRAVITY_API_KEY", "").split(",")
    api_key = next((key.strip() for key in keys if key.strip()), "")
    if any(not 0x21 <= ord(char) <= 0x7E for char in api_key):
        parser.error("ZEROGRAVITY_API_KEY must contain printable ASCII keys without spaces")
    probe = Probe(*args.base_url, api_key, args.timeout)
    if args.check == "stream":
        report = check_stream(probe, args.model)
    elif args.wait_ready is not None:
        report = wait_ready(probe, args.wait_ready)
    else:
        report = check_status(probe)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
