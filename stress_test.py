"""
Stress test — simulates N concurrent players joining and playing the quiz.

Usage:
    ./venv/bin/python stress_test.py                     # 500 players, localhost
    ./venv/bin/python stress_test.py --players 100       # custom count
    ./venv/bin/python stress_test.py --base http://localhost:8000 --players 200

The test:
  1. Resolves the quiz code from the server.
  2. Registers N players concurrently via HTTP POST /api/join/.
  3. Connects each player to the WebSocket.
  4. Waits for the host to start the quiz (or auto-starts after --wait seconds).
  5. Each player sends a random answer when the 'answering' phase begins.
  6. Prints a timing summary.
"""

import argparse
import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import websockets
import websockets.exceptions


# ── Configuration ────────────────────────────────────────────────────────────

DEFAULT_BASE   = "http://localhost:8000"
DEFAULT_PLAYERS = 500
COLORS = ["red", "blue", "green", "yellow"]
BATCH_SIZE = 50          # players registered per batch (avoids hammering DB)
BATCH_DELAY = 0.05       # seconds between batches
WS_TIMEOUT  = 30         # seconds to wait for 'answering' phase


# ── Result tracking ──────────────────────────────────────────────────────────

@dataclass
class PlayerResult:
    name: str
    registered: bool = False
    ws_connected: bool = False
    answered: bool = False
    register_ms: float = 0.0
    ws_connect_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class Summary:
    results: list = field(default_factory=list)
    start: float = field(default_factory=time.time)

    def add(self, r: PlayerResult):
        self.results.append(r)

    def print(self):
        total      = len(self.results)
        registered = sum(1 for r in self.results if r.registered)
        connected  = sum(1 for r in self.results if r.ws_connected)
        answered   = sum(1 for r in self.results if r.answered)
        errors     = [r for r in self.results if r.error]

        reg_times  = [r.register_ms for r in self.results if r.registered]
        ws_times   = [r.ws_connect_ms for r in self.results if r.ws_connected]
        elapsed    = time.time() - self.start

        print("\n" + "═" * 56)
        print(f"  STRESS TEST RESULTS  ({total} players, {elapsed:.1f}s total)")
        print("═" * 56)
        print(f"  Registered      : {registered:>5} / {total}")
        print(f"  WS connected    : {connected:>5} / {total}")
        print(f"  Answered        : {answered:>5} / {total}")
        if reg_times:
            print(f"\n  HTTP register  avg {avg(reg_times):.0f}ms  "
                  f"p95 {percentile(reg_times, 95):.0f}ms  "
                  f"max {max(reg_times):.0f}ms")
        if ws_times:
            print(f"  WS connect     avg {avg(ws_times):.0f}ms  "
                  f"p95 {percentile(ws_times, 95):.0f}ms  "
                  f"max {max(ws_times):.0f}ms")
        if errors:
            unique = {}
            for r in errors:
                unique[r.error] = unique.get(r.error, 0) + 1
            print(f"\n  Errors ({len(errors)}):")
            for msg, count in sorted(unique.items(), key=lambda x: -x[1]):
                print(f"    [{count:>3}x] {msg}")
        print("═" * 56)


def avg(lst):
    return sum(lst) / len(lst) if lst else 0

def percentile(lst, p):
    if not lst:
        return 0
    s = sorted(lst)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s) - 1)]


# ── HTTP — register a player ─────────────────────────────────────────────────

async def register_player(session: aiohttp.ClientSession, base: str,
                           code: str, name: str) -> tuple[Optional[int], float, str]:
    """POST /api/join/ and return (player_id, elapsed_ms, error_detail)."""
    t0 = time.monotonic()
    try:
        async with session.post(
            f"{base}/api/join/",
            data={"code": code, "name": name, "language": "fr"},
            allow_redirects=False,
        ) as resp:
            elapsed = (time.monotonic() - t0) * 1000
            location = resp.headers.get("Location", "")
            if resp.status in (301, 302):
                # Success → /player/123/ ; failure → /play/?code=TEST
                parts = [p for p in location.strip("/").split("/") if p.isdigit()]
                if parts:
                    return int(parts[-1]), elapsed, ""
                return None, elapsed, f"HTTP {resp.status} → {location}"
            return None, elapsed, f"HTTP {resp.status} (expected redirect)"
    except Exception as e:
        return None, (time.monotonic() - t0) * 1000, str(e)


# ── WebSocket — connect and play ─────────────────────────────────────────────

async def play(ws_base: str, player_id: int, result: PlayerResult):
    """Connect player WebSocket, wait for answering phase, send answer."""
    url = f"{ws_base}/ws/player/{player_id}/"
    t0 = time.monotonic()
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            result.ws_connect_ms = (time.monotonic() - t0) * 1000
            result.ws_connected = True

            deadline = time.monotonic() + WS_TIMEOUT
            async for raw in ws:
                if time.monotonic() > deadline:
                    break
                try:
                    import json
                    msg = json.loads(raw)
                except Exception:
                    continue

                if msg.get("type") != "state":
                    continue
                state = msg["state"]
                phase = state.get("phase")

                if phase == "answering" and not result.answered:
                    color = random.choice(COLORS)
                    await ws.send(json.dumps({"action": "answer", "color": color}))
                    result.answered = True

                if state.get("quiz", {}).get("status") == "finished":
                    break

    except websockets.exceptions.WebSocketException as e:
        result.error = f"WS: {type(e).__name__}"
    except OSError as e:
        result.error = f"OS: {e.strerror}"
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"


# ── Quiz code lookup ──────────────────────────────────────────────────────────

async def get_quiz_status(session: aiohttp.ClientSession, base: str, code: str) -> str:
    """Return 'waiting', 'running', 'finished', or 'unknown'."""
    try:
        async with session.get(f"{base}/play/?code={code}",
                               allow_redirects=True) as resp:
            text = await resp.text()
            # The join page renders the quiz title only when quiz exists + waiting
            if "quiz-name" in text or "card-form" in text or "join-form" in text:
                return "waiting"
            if "déjà commencé" in text or "đã bắt đầu" in text:
                return "running_or_finished"
            return "unknown"
    except Exception:
        return "unknown"


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(base: str, code: str, n: int):
    summary = Summary()
    ws_base = base.replace("http://", "ws://").replace("https://", "wss://")

    connector = aiohttp.TCPConnector(limit=200, limit_per_host=200)
    timeout   = aiohttp.ClientTimeout(total=15)

    print(f"  Target   : {base}")
    print(f"  Quiz code: {code}")
    print(f"  Players  : {n}  (batches of {BATCH_SIZE})")

    # ── Preflight: check quiz is in 'waiting' status ──────────────────────────
    async with aiohttp.ClientSession() as probe:
        status = await get_quiz_status(probe, base, code)
    if status != "waiting":
        print(f"\n  ✗ Quiz '{code}' is not in 'waiting' status (detected: {status})")
        print("  → Reset it from the host page or Django admin, then re-run.")
        print("  → Host page: click 'Restart' button, or run:")
        print(f"     DJANGO_SETTINGS_MODULE=color_quiz_show.settings "
              f"./venv/bin/python manage.py shell -c \""
              f"from quiz.models import Quiz,Answer; q=Quiz.objects.get(code='{code}'); "
              f"Answer.objects.filter(player__quiz=q).delete(); "
              f"q.status='waiting'; q.current_phase='waiting_players'; "
              f"q.current_question=None; q.save()\"")
        return

    player_ids: list[tuple[int, PlayerResult]] = []

    # ── Phase 1: register all players ────────────────────────────────────────
    print("\n[1/2] Registering players …")
    p1 = time.monotonic()

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        names = [f"Bot{i:04d}" for i in range(n)]

        for batch_start in range(0, n, BATCH_SIZE):
            batch = names[batch_start:batch_start + BATCH_SIZE]
            tasks = [register_player(session, base, code, name) for name in batch]
            results_batch = await asyncio.gather(*tasks)

            for name, (pid, ms, err) in zip(batch, results_batch):
                r = PlayerResult(name=name, register_ms=ms)
                if pid:
                    r.registered = True
                    player_ids.append((pid, r))
                else:
                    r.error = err or "Registration failed"
                summary.add(r)

            done = min(batch_start + BATCH_SIZE, n)
            print(f"  {done}/{n} registered …", end="\r")
            await asyncio.sleep(BATCH_DELAY)

    reg_ok = sum(1 for r in summary.results if r.registered)
    print(f"  {reg_ok}/{n} registered in {time.monotonic()-p1:.1f}s          ")

    if not player_ids:
        print("  ✗ No players registered — is the quiz in 'waiting' status?")
        summary.print()
        return

    # ── Phase 2: connect WebSockets and play ─────────────────────────────────
    print(f"\n[2/2] Connecting {len(player_ids)} WebSockets …")
    p2 = time.monotonic()

    ws_tasks = [play(ws_base, pid, r) for pid, r in player_ids]
    await asyncio.gather(*ws_tasks)

    ws_ok = sum(1 for _, r in player_ids if r.ws_connected)
    print(f"  {ws_ok}/{len(player_ids)} WS connected in {time.monotonic()-p2:.1f}s")

    summary.print()


def main():
    parser = argparse.ArgumentParser(description="Quiz server stress test")
    parser.add_argument("--base",    default=DEFAULT_BASE,    help="Base HTTP URL")
    parser.add_argument("--code",    default=None,            help="Quiz code (e.g. TEST)")
    parser.add_argument("--players", default=DEFAULT_PLAYERS, type=int)
    args = parser.parse_args()

    if not args.code:
        # Try to guess: ask user
        args.code = input("Quiz code (e.g. TEST): ").strip().upper()
    if not args.code:
        print("Error: --code is required")
        return

    asyncio.run(run(args.base, args.code, args.players))


if __name__ == "__main__":
    main()
