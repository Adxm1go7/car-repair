"""A small load test of the public availability lookup, run by hand against a running stack.

    uv run python scripts/load_availability.py [--base-url URL] [--users N] [--seconds S]

Each of N simulated users asks `GET /api/availability?services=<first service>&date=<next
open day>` again and again for S seconds. It prints the request count, requests per second,
errors (anything that isn't a 2xx, or no answer) and the p50, p95 and p99 response times.
"""

import argparse
import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx2


@dataclass
class Result:
    requests: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    elapsed: float = 0.0


def percentile(sorted_ms: list[float], p: float) -> float:
    """Nearest-rank percentile of an already sorted list; 0 for an empty one."""
    if not sorted_ms:
        return 0
    rank = max(1, math.ceil(p / 100 * len(sorted_ms)))
    return sorted_ms[rank - 1]


def next_open_day(timetables: list[dict[str, Any]], today: date) -> date:
    """The first day after `today` that the timetable in force on it opens (0 = Monday)."""
    for offset in range(1, 60):
        day = today + timedelta(days=offset)
        in_force = [t for t in timetables if date.fromisoformat(t["starts_on"]) <= day]
        if not in_force:
            continue
        latest = max(in_force, key=lambda t: t["starts_on"])
        if any(d["weekday"] == day.weekday() for d in latest["days"]):
            return day
    raise RuntimeError("no open day in the next 60 days")


async def _user(
    client: httpx2.AsyncClient, url: str, params: dict[str, str], deadline: float, result: Result
) -> None:
    while time.perf_counter() < deadline:
        started = time.perf_counter()
        try:
            response = await client.get(url, params=params)
            ok = response.is_success
        except httpx2.HTTPError:
            ok = False
        result.latencies_ms.append((time.perf_counter() - started) * 1000)
        result.requests += 1
        if not ok:
            result.errors += 1


async def run(base_url: str, users: int, seconds: float) -> Result:
    async with httpx2.AsyncClient(
        base_url=base_url, timeout=10, limits=httpx2.Limits(max_connections=users)
    ) as client:
        service = (await client.get("/api/services")).raise_for_status().json()[0]["slug"]
        hours = (await client.get("/api/opening-hours")).raise_for_status().json()
        day = next_open_day(hours["timetables"], date.today())
        params = {"services": service, "date": day.isoformat()}
        print(f"GET /api/availability?services={service}&date={day} - {users} users, {seconds:g}s")

        result = Result()
        started = time.perf_counter()
        deadline = started + seconds
        await asyncio.gather(
            *(_user(client, "/api/availability", params, deadline, result) for _ in range(users))
        )
        result.elapsed = time.perf_counter() - started
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()

    result = asyncio.run(run(args.base_url, args.users, args.seconds))
    ordered = sorted(result.latencies_ms)
    print(f"requests: {result.requests}")
    print(f"requests per second: {result.requests / result.elapsed:.0f}")
    print(f"errors: {result.errors}")
    for p in (50, 95, 99):
        print(f"p{p}: {percentile(ordered, p):.0f} ms")


if __name__ == "__main__":
    main()
