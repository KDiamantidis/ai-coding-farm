# =============================================================================
# FILE:    farm/router.py
# PURPOSE: Send a prompt to the right model for a role, with API fallback, and
#          log every call.
#
# EXPORTS:
#   Reply          dataclass: text, model, tokens_in, tokens_out, latency_s
#   Router         Router(cfg, conn).call(role, messages, level=0, ...)
#
# TWO DIFFERENT KINDS OF "FALLBACK" (do not mix them up):
#   1. API fallback (here): the model call itself failed (outage, rate limit,
#      timeout). Rate limits and overload are retried on the same model first
#      (up to 3 tries, waiting as long as the provider asks). Then we move on to
#      the next model in the chain.
#   2. Escalation (orchestrator.py): the call worked but the patch was rejected
#      by the gatekeeper. The next ATTEMPT starts one level higher in the chain.
#   `level` is the starting position in the chain. This file only handles (1).
#
# TOKEN BUDGET (settings: `rate_limits` in models.yaml, tokens per minute per model):
#   Free tiers allow a number of tokens per minute (Groq: 8000). All workers share that
#   budget. TokenLimiter keeps a 60-second window of tokens used and makes a call WAIT
#   until it fits, instead of sending it, getting a 429, and retrying. A model with no
#   entry in `rate_limits` is not limited.
#
# DESIGN NOTES:
#   - Routing is rules from models.yaml. No classifier model: with a few roles,
#     a YAML lookup is simpler, faster, and cannot be "wrong" in a surprising
#     way. A learned router is on the roadmap, only if it beats this on data.
#   - litellm is imported lazily, so the mock demo and the tests need no
#     network libraries at all.
# =============================================================================

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

from . import db, mockmodel
from .config import ConfigError, chain_for
from .mockmodel import ModelError


@dataclass
class Reply:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_s: float
    finish_reason: str = ""   # why the model stopped ("stop", "length", ...)


# Errors that usually go away if we wait a few seconds (busy server, rate limit).
TRANSIENT_HINTS = ("503", "429", "high demand", "overloaded", "rate limit")


# Providers often say how long to wait: "try again in 4.8s", "retry in11.09s", "630ms".
RETRY_HINT_RE = re.compile(r"(?:try again|retry) in\s*([\d.]+)\s*(ms|s)", re.IGNORECASE)


def _retry_wait(message: str, default: float) -> float:
    """Seconds to wait before the next try. Use the provider's hint when there is one."""
    m = RETRY_HINT_RE.search(message)
    if not m:
        return default
    seconds = float(m.group(1)) / (1000 if m.group(2).lower() == "ms" else 1)
    return min(max(seconds + 0.5, 1.0), 60.0)


def _is_transient(message: str) -> bool:
    low = message.lower()
    return any(hint in low for hint in TRANSIENT_HINTS)


class TokenLimiter:
    """Sliding 60-second window of tokens. Thread safe. Used by every worker."""

    SAFETY = 0.9   # stay a little under the provider's limit

    def __init__(self, tokens_per_minute: int, window_s: float = 60.0,
                 clock=time.monotonic, sleep=time.sleep):
        self.limit = tokens_per_minute * self.SAFETY
        self.window = window_s
        self.clock, self.sleep = clock, sleep
        self.entries: list[list[float]] = []   # [time, tokens]
        self.lock = threading.Lock()
        self.avg_out = 1000.0                   # learned from real answers

    def estimate(self, messages: list[dict]) -> int:
        chars = sum(len(m.get("content", "")) for m in messages)
        return int(chars / 3.5 + self.avg_out)

    def acquire(self, estimate: int) -> list[float]:
        """Wait until `estimate` tokens fit in the window, then reserve them."""
        while True:
            with self.lock:
                now = self.clock()
                self.entries = [e for e in self.entries if now - e[0] < self.window]
                used = sum(e[1] for e in self.entries)
                # an empty window always lets one call through, even a very big one
                if not self.entries or used + estimate <= self.limit:
                    entry = [now, float(estimate)]
                    self.entries.append(entry)
                    return entry
                wait = self.entries[0][0] + self.window - now
            self.sleep(min(max(wait, 0.05), 5.0))

    def settle(self, entry: list[float], tokens_in: int, tokens_out: int) -> None:
        """Replace the reservation with what the provider really counted."""
        with self.lock:
            entry[1] = float(tokens_in + tokens_out)
            self.avg_out = 0.7 * self.avg_out + 0.3 * tokens_out


class Router:
    def __init__(self, cfg: dict, conn):
        self.cfg = cfg
        self.conn = conn
        self.settings = cfg["settings"]
        # Mock answers live next to models.yaml unless the file says otherwise.
        self.mock_dir = cfg.get("mock_dir", "examples/demo_target/mock")
        self.limiters = {m: TokenLimiter(int(tpm))
                         for m, tpm in (cfg.get("rate_limits") or {}).items()}
        self._local = threading.local()  # finish reason of the last call, per thread

    def call(self, role: str, messages: list[dict], level: int = 0,
             task_id: str | None = None, attempt_no: int | None = None) -> Reply:
        """Try chain[level], then the models after it, until one answers."""
        chain = chain_for(self.cfg, role)
        level = max(0, min(level, len(chain) - 1))
        last_error = "no models tried"

        for model in chain[level:]:
            # Up to 3 tries with a growing wait, but only for errors that pass by themselves.
            for try_no in (1, 2, 3):
                started = time.monotonic()
                try:
                    text, tin, tout = self._complete(model, messages)
                except ConfigError:
                    raise  # a setup problem is not an outage: stop and tell the user
                except Exception as exc:  # any provider error counts as an outage
                    elapsed = time.monotonic() - started
                    last_error = f"{type(exc).__name__}: {exc}"
                    db.log_call(self.conn, task_id=task_id, attempt_no=attempt_no,
                                role=role, model=model, ok=False, error=last_error,
                                latency_s=elapsed)
                    if try_no < 3 and _is_transient(last_error):
                        default_wait = self.settings.get("retry_wait_s", 5) * try_no
                        time.sleep(_retry_wait(last_error, default_wait))
                        continue
                    break  # next model in the chain

                elapsed = time.monotonic() - started
                db.log_call(self.conn, task_id=task_id, attempt_no=attempt_no,
                            role=role, model=model, ok=True, tokens_in=tin,
                            tokens_out=tout, latency_s=elapsed)
                return Reply(text, model, tin, tout, elapsed, getattr(self._local, "finish", ""))

        raise ModelError(f"all models failed for role '{role}': {last_error}")

    # ------------------------------------------------------------------
    def _complete(self, model: str, messages: list[dict]) -> tuple[str, int, int]:
        self._local.finish = ""
        if model.startswith("mock/"):
            return mockmodel.complete(model, messages, self.mock_dir)

        try:
            import litellm  # imported here on purpose, see header
        except ImportError as exc:
            raise ConfigError("litellm is not installed. Run: pip install -r requirements.txt") from exc

        # Extra settings for one model, from the "model_params" section of models.yaml
        # (for example reasoning_effort for the gpt-oss models).
        extra = (self.cfg.get("model_params") or {}).get(model, {})
        limiter = self.limiters.get(model)
        entry = limiter.acquire(limiter.estimate(messages)) if limiter else None
        resp = litellm.completion(          # on an error the reservation stays (counted as used)
            model=model,
            messages=messages,
            timeout=self.settings["call_timeout_s"],
            temperature=0.2,
            **extra,
        )
        text = resp.choices[0].message.content or ""
        self._local.finish = str(getattr(resp.choices[0], "finish_reason", "") or "")
        usage = getattr(resp, "usage", None)
        tin = getattr(usage, "prompt_tokens", 0) or 0
        tout = getattr(usage, "completion_tokens", 0) or 0
        if limiter:
            limiter.settle(entry, tin, tout)
        return text, tin, tout
