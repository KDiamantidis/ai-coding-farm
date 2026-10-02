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


class Router:
    def __init__(self, cfg: dict, conn):
        self.cfg = cfg
        self.conn = conn
        self.settings = cfg["settings"]
        # Mock answers live next to models.yaml unless the file says otherwise.
        self.mock_dir = cfg.get("mock_dir", "examples/demo_target/mock")
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
        resp = litellm.completion(
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
        return text, tin, tout
