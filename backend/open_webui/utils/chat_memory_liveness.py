from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

# Scheduling-only module. It owns single-flight, a bounded probe budget, capped
# backoff for both errors and no-progress cycles, an error budget that can stop
# the loop, and clean cancellation. It never inspects memory content.
#
# STEADY-STATE COST (stated deliberately). The service's authoritative-source
# inventory is a per-scope route: `POST /v1/memory/source/inventory` answers for
# exactly one instance/owner/chat and there is no aggregate scope-inventory route
# in the client API. One call per interval therefore cannot answer availability
# for all 64 chats in the reconciliation window, and this module does not pretend
# otherwise. Instead every cycle probes at most `probe_limit` chats (default 8,
# maximum 16) taken from a rotating offset over the same bounded 64-chat window,
# so steady-state cost is at most `probe_limit` small inventory calls per cycle
# and every eligible scope is still examined within
# `ceil(window_size / probe_limit)` cycles. The expensive repair (up to 64
# pushes) only runs when at least one probe reports an unavailable eligible scope.
LOOP_DISABLED = "DISABLED"
LOOP_IDLE = "IDLE"
LOOP_POLLING = "POLLING"
LOOP_RECONCILING = "RECONCILING"
LOOP_WAITING = "WAITING"
LOOP_STOPPED = "STOPPED"

CYCLE_NONE = "NONE"
CYCLE_CURRENT = "CURRENT"
CYCLE_REPAIRED = "REPAIRED"
CYCLE_NO_PROGRESS = "NO_PROGRESS"
CYCLE_FAILED = "FAILED"

STOPPED_AFTER_FAILURES = "STOPPED_AFTER_FAILURES"

# A no-progress repair is not an error, so it never consumes the error budget and
# never stops the loop; it only lengthens the delay, up to the configured cap.
MAXIMUM_PROBE_LIMIT = 16


def error_class(value: BaseException | None) -> str | None:
    """Return a stable, content-free error class for one failure.

    Only a machine-shaped `code` attribute or the exception type name is
    reported: never an exception message, a credential, a scope, or chat text.
    """
    if value is None:
        return None
    code = getattr(value, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip().upper()
    return type(value).__name__


@dataclass(frozen=True)
class CycleRecord:
    """The content-free outcome of one poll/repair cycle."""

    cycle: int
    result: str
    probed: int
    skipped: int
    unavailable_before: int
    unavailable_after: int
    selected: int
    synchronized: int
    failed: int
    error_class: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "result": self.result,
            "probed": self.probed,
            "skipped": self.skipped,
            "unavailable_before": self.unavailable_before,
            "unavailable_after": self.unavailable_after,
            "selected": self.selected,
            "synchronized": self.synchronized,
            "failed": self.failed,
            "error_class": self.error_class,
        }


class SourceLivenessSupervisor:
    """Supervise one bounded source-liveness loop for the Open WebUI adapter.

    The injected callables are the whole seam: `chat_records` returns the bounded
    eligible, non-internal recent chats, `available` performs the cheap
    content-free inventory probe for one chat, and `repair` runs the existing
    bounded reconciliation.

    Delay semantics: `supervise()` sleeps exactly the delay returned by
    `run_cycle()` and never adds the interval on top, so a failing or
    no-progress cycle sleeps its backoff and a healthy cycle sleeps the
    configured interval. The effective delay is therefore
    `interval_seconds * 2 ** max(0, streak - 1)` capped at
    `maximum_backoff_seconds`, where `streak` is consecutive hard failures or
    consecutive no-progress repairs, whichever is larger.
    """

    def __init__(
        self,
        *,
        chat_records: Callable[[], Awaitable[list[Any]]],
        chat_identity: Callable[[Any], tuple[str, str]],
        available: Callable[[Any], Awaitable[bool]],
        repair: Callable[[], Awaitable[dict[str, Any] | None]],
        enabled: bool = True,
        interval_seconds: float = 300.0,
        maximum_backoff_seconds: float = 3600.0,
        maximum_consecutive_failures: int = 5,
        probe_limit: int = 8,
    ) -> None:
        if not isinstance(interval_seconds, (int, float)) or isinstance(interval_seconds, bool) or interval_seconds <= 0:
            raise ValueError("liveness interval must be a positive number of seconds")
        if not isinstance(maximum_backoff_seconds, (int, float)) or isinstance(maximum_backoff_seconds, bool) or maximum_backoff_seconds < interval_seconds:
            raise ValueError("liveness backoff cap must be at least the interval")
        if not isinstance(maximum_consecutive_failures, int) or isinstance(maximum_consecutive_failures, bool) or maximum_consecutive_failures < 1:
            raise ValueError("liveness failure budget must be a positive integer")
        if not isinstance(probe_limit, int) or isinstance(probe_limit, bool) or not 1 <= probe_limit <= MAXIMUM_PROBE_LIMIT:
            raise ValueError(f"liveness probe budget must be an integer from 1 through {MAXIMUM_PROBE_LIMIT}")
        self._chat_records = chat_records
        self._chat_identity = chat_identity
        self._available = available
        self._repair = repair
        self.enabled = bool(enabled)
        self.interval_seconds = float(interval_seconds)
        self.maximum_backoff_seconds = float(maximum_backoff_seconds)
        self.maximum_consecutive_failures = maximum_consecutive_failures
        self.probe_limit = probe_limit
        self._task: asyncio.Task | None = None
        self._in_flight = False
        self._state = LOOP_DISABLED if not self.enabled else LOOP_IDLE
        self._stop_reason: str | None = None
        self._cycles = 0
        self._reconciliations = 0
        self._examinations = 0
        self._unavailable_seen = 0
        self._consecutive_failures = 0
        self._no_progress = 0
        self._last_error_class: str | None = None
        self._last_cycle: CycleRecord | None = None
        self._rotation = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    @property
    def last_cycle(self) -> CycleRecord | None:
        return self._last_cycle

    def backoff_seconds(self, streak: int) -> float:
        """Capped exponential backoff for the given consecutive-problem count.

        The exponent is clamped before the shift so a pathological streak cannot
        raise OverflowError: the configured cap is always reached far below this
        bound, so clamping changes no reachable delay.
        """
        exponent = min(max(0, int(streak) - 1), 16)
        delay = self.interval_seconds * (2 ** exponent)
        return float(min(delay, self.maximum_backoff_seconds))

    def settle_seconds(self) -> float:
        """The delay the next cycle must wait, driven by the worse streak."""
        return self.backoff_seconds(max(self._consecutive_failures, self._no_progress))

    def status(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "enabled": self.enabled,
            "stop_reason": self._stop_reason,
            "cycles": self._cycles,
            "reconciliations": self._reconciliations,
            "examinations": self._examinations,
            "unavailable_seen": self._unavailable_seen,
            "consecutive_failures": self._consecutive_failures,
            "no_progress_cycles": self._no_progress,
            "failure_budget": self.maximum_consecutive_failures,
            "interval_seconds": self.interval_seconds,
            "maximum_backoff_seconds": self.maximum_backoff_seconds,
            "probe_limit": self.probe_limit,
            "probe_offset": self._rotation,
            "last_cycle": self._last_cycle.as_dict() if self._last_cycle is not None else None,
            "last_error_class": self._last_error_class,
        }

    def start(self) -> asyncio.Task | None:
        """Start the supervised loop once; repeated calls are inert."""
        if not self.enabled or self._state == LOOP_STOPPED:
            return None
        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self.supervise(), name="chat-memory-source-liveness")
        return self._task

    async def stop(self) -> None:
        """Cancel the loop and await it so no pending task or warning survives."""
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
        if task is not None and task is not asyncio.current_task():
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self.enabled and self._state != LOOP_STOPPED:
            self._state = LOOP_STOPPED
            self._stop_reason = self._stop_reason or "SHUTDOWN"

    async def supervise(self) -> None:
        """Sleep the delay the last cycle earned, then run the next cycle."""
        delay = self.interval_seconds
        while True:
            await asyncio.sleep(delay)
            record, delay = await self.run_cycle()

    async def _probe(self, chats: list[Any]) -> tuple[int, int, int, set[tuple[str, str]]]:
        """Probe one rotating slice; return (probed, skipped, unavailable, ids)."""
        total = len(chats)
        if total == 0:
            self._rotation = 0
            return 0, 0, 0, set()
        start = self._rotation % total
        ordered = list(chats[start:]) + list(chats[:start])
        slice_ = ordered[:self.probe_limit]
        unavailable: set[tuple[str, str]] = set()
        for chat in slice_:
            self._examinations += 1
            if not await self._available(chat):
                unavailable.add(self._chat_identity(chat))
        self._rotation = (start + len(slice_)) % total
        return len(slice_), total - len(slice_), len(unavailable), unavailable

    async def _count_unavailable(self, chats: list[Any], identities: set[tuple[str, str]]) -> int:
        """Re-probe only the scopes that were unavailable before the repair."""
        remaining = 0
        for chat in chats:
            if self._chat_identity(chat) not in identities:
                continue
            self._examinations += 1
            if not await self._available(chat):
                remaining += 1
        return remaining

    async def _cycle(self) -> CycleRecord:
        self._state = LOOP_POLLING
        chats = await self._chat_records()
        probed, skipped, before, unavailable = await self._probe(chats)
        if before == 0:
            return CycleRecord(
                cycle=self._cycles + 1, result=CYCLE_CURRENT, probed=probed, skipped=skipped,
                unavailable_before=0, unavailable_after=0, selected=len(chats),
                synchronized=0, failed=0, error_class=None,
            )
        self._state = LOOP_RECONCILING
        outcome = await self._repair()
        outcome = outcome if isinstance(outcome, dict) else {}
        self._unavailable_seen += before
        after = await self._count_unavailable(chats, unavailable)
        selected = int(outcome.get("selected") or len(chats))
        synchronized = int(outcome.get("synchronized") or 0)
        failed = int(outcome.get("failed") or 0)
        if after < before:
            return CycleRecord(
                cycle=self._cycles + 1, result=CYCLE_REPAIRED, probed=probed, skipped=skipped,
                unavailable_before=before, unavailable_after=after, selected=selected,
                synchronized=synchronized, failed=failed, error_class=None,
            )
        return CycleRecord(
            cycle=self._cycles + 1, result=CYCLE_NO_PROGRESS, probed=probed, skipped=skipped,
            unavailable_before=before, unavailable_after=after, selected=selected,
            synchronized=synchronized, failed=failed,
            error_class="RECONCILIATION_INCOMPLETE" if failed else None,
        )

    async def run_cycle(self) -> tuple[CycleRecord, float]:
        """Run one poll/repair cycle unless another cycle is already in flight.

        A hard failure consumes the error budget and can stop the loop. A repair
        that changes nothing is recorded as no-progress: it lengthens the delay
        up to the cap but never consumes the error budget and never stops the
        loop, so a permanently inaccessible scope settles into a slow retry
        instead of a reconciliation every interval. Once the error budget has
        stopped the loop, further cycles are a bounded no-op.

        Single-flight is enforced here rather than left to callers: a second
        concurrent cycle raises instead of joining the in-flight one, so a
        reconciliation can never run twice at once and a caller can never block
        behind work it did not start.
        """
        if self._state == LOOP_STOPPED:
            return self._last_cycle, self.maximum_backoff_seconds
        if self._in_flight:
            raise RuntimeError("reconciliation is already in flight")
        self._in_flight = True
        try:
            return await self._cycle_locked()
        finally:
            self._in_flight = False

    async def _cycle_locked(self) -> tuple[CycleRecord, float]:
        try:
            record = await self._cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the loop must survive any single cycle failure
            self._consecutive_failures += 1
            self._no_progress = 0
            self._last_error_class = error_class(exc)
            self._cycles += 1
            self._last_cycle = CycleRecord(
                cycle=self._cycles, result=CYCLE_FAILED, probed=0, skipped=0,
                unavailable_before=0, unavailable_after=0, selected=0,
                synchronized=0, failed=0, error_class=self._last_error_class,
            )
            if self._consecutive_failures >= self.maximum_consecutive_failures:
                self._state = LOOP_STOPPED
                self._stop_reason = STOPPED_AFTER_FAILURES
                log.warning(
                    "Chat Memory source liveness stopped after %s consecutive failed cycles: error_class=%s",
                    self._consecutive_failures, self._last_error_class,
                )
                return self._last_cycle, self.maximum_backoff_seconds
            delay = self.settle_seconds()
            if self._consecutive_failures == 1 or self._consecutive_failures & (self._consecutive_failures - 1) == 0:
                log.warning(
                    "Chat Memory source liveness cycle failed: consecutive_failures=%s error_class=%s next_delay_seconds=%s",
                    self._consecutive_failures, self._last_error_class, delay,
                )
            self._state = LOOP_WAITING
            return self._last_cycle, delay

        self._cycles += 1
        self._last_cycle = record
        if record.result == CYCLE_NO_PROGRESS:
            self._consecutive_failures = 0
            self._no_progress += 1
            self._last_error_class = record.error_class
            delay = self.settle_seconds()
            if self._no_progress == 1 or self._no_progress & (self._no_progress - 1) == 0:
                log.warning(
                    "Chat Memory source liveness repair made no progress: no_progress_cycles=%s unavailable=%s next_delay_seconds=%s",
                    self._no_progress, record.unavailable_after, delay,
                )
            self._state = LOOP_WAITING
            return record, delay
        self._consecutive_failures = 0
        self._no_progress = 0
        self._last_error_class = None
        if record.result == CYCLE_REPAIRED:
            self._reconciliations += 1
        self._state = LOOP_IDLE
        return record, self.interval_seconds
