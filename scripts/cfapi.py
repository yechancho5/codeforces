"""Minimal Codeforces API client (stdlib only).

Codeforces asks for at most one request every 2 seconds; this client throttles
to that, retries transient failures with exponential backoff, and raises
CFError with a readable message otherwise.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://codeforces.com/api/"
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class CFError(Exception):
    pass


class Client:
    def __init__(self, min_interval=2.1, retries=4, timeout=30):
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self.calls = 0
        self._last = 0.0

    def _get(self, url):
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.calls += 1
        req = urllib.request.Request(url, headers={"User-Agent": "cf-coach/1.0 (personal training tool)"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    def call(self, method, **params):
        url = API_URL + method
        if params:
            url += "?" + urllib.parse.urlencode(params)
        backoff = 4.0
        last_error = "unknown error"
        for attempt in range(self.retries + 1):
            retryable = False
            try:
                body = self._get(url)
            except urllib.error.HTTPError as e:
                # CF answers bad requests (e.g. unknown handle) with a JSON body.
                try:
                    body = json.load(e)
                except Exception:
                    body = None
                if body is None:
                    last_error = f"HTTP {e.code}"
                    retryable = e.code in RETRYABLE_HTTP
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                body, last_error, retryable = None, f"network error: {e}", True

            if body is not None:
                if body.get("status") == "OK":
                    return body["result"]
                last_error = body.get("comment", "API returned FAILED")
                retryable = "limit exceeded" in last_error.lower()

            if not retryable or attempt == self.retries:
                break
            time.sleep(backoff)
            backoff *= 2
        raise CFError(f"{method}: {last_error}")
