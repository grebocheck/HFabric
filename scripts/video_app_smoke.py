#!/usr/bin/env python3
"""Live app-path smoke for the P27 video workspace.

The check talks to a running HFabric backend rather than importing test
fixtures. It validates the browser-critical video path: queue -> worker ->
Video DB row -> mp4 HTTP range replay, plus cancellation of a running denoise
and a Video -> LLM -> Video resident swap.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"done", "error", "cancelled"}


class Client:
    def __init__(self, base_url: str, api_token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = (api_token or "").strip()

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def json(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        timeout: float = 30.0,
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers=self._headers(headers),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    def raw(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            method="GET",
            headers=self._headers(headers),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return {
                    "status": resp.status,
                    "headers": resp.headers,
                    "body": resp.read(),
                }
        except urllib.error.HTTPError as exc:
            return {
                "status": exc.code,
                "headers": exc.headers,
                "body": exc.read(),
            }


def websocket_url(base_url: str, api_token: str | None = None) -> str:
    parsed = urllib.parse.urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc or parsed.path
    token = (api_token or "").strip()
    query = f"?token={urllib.parse.quote(token)}" if token else ""
    return f"{scheme}://{netloc}/ws{query}"


async def collect_events(
    base_url: str,
    api_token: str | None,
    sink: list[dict[str, Any]],
    stop: asyncio.Event,
) -> None:
    try:
        import websockets
    except ImportError:
        print(
            "Python package 'websockets' is required. It is installed by "
            "backend/requirements.txt via uvicorn[standard].",
            file=sys.stderr,
        )
        raise

    async with websockets.connect(websocket_url(base_url, api_token)) as ws:
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except TimeoutError:
                continue
            sink.append(json.loads(raw))


def choose_model(
    models: list[dict[str, Any]],
    job_type: str,
    *,
    model_id: str | None = None,
    preferred_family: str | None = None,
) -> dict[str, Any]:
    if model_id:
        for model in models:
            if model.get("id") == model_id:
                return model
        raise RuntimeError(f"Model {model_id!r} was not returned by /api/models")

    candidates = [
        model
        for model in models
        if model.get("job_type") == job_type and model.get("available") is not False
    ]
    if preferred_family:
        preferred = [model for model in candidates if model.get("family") == preferred_family]
        if preferred:
            candidates = preferred
    elif job_type == "video":
        preferred = [model for model in candidates if model.get("family") == "ltx-video"]
        if preferred:
            candidates = preferred

    if not candidates:
        raise RuntimeError(f"No available {job_type} model was returned by /api/models")
    return sorted(
        candidates,
        key=lambda m: (int(m.get("size_bytes") or 0), str(m.get("name") or "")),
    )[0]


def ensure_queue_idle(client: Client) -> None:
    jobs = client.json("GET", "/api/jobs?limit=1000")
    active = [job for job in jobs if job.get("status") in ACTIVE_STATUSES]
    if active:
        sample = ", ".join(f"{job['id']}:{job['status']}" for job in active[:5])
        raise RuntimeError(
            f"Queue is not idle ({len(active)} active job(s): {sample}). "
            "Wait/cancel them first, or pass --allow-existing-jobs."
        )


def video_payload(
    model_id: str,
    args: argparse.Namespace,
    *,
    prompt: str,
    steps: int | None = None,
) -> dict[str, Any]:
    return {
        "type": "video",
        "model_id": model_id,
        "params": {
            "prompt": prompt,
            "negative": "",
            "mode": "t2v",
            "width": args.width,
            "height": args.height,
            "frames": args.frames,
            "fps": args.fps,
            "steps": steps if steps is not None else args.steps,
            "guidance": args.guidance,
            "seed": args.seed,
        },
    }


def llm_payload(model_id: str) -> dict[str, Any]:
    return {
        "type": "llm",
        "model_id": model_id,
        "params": {
            "prompt": "Return exactly: video swap smoke",
            "max_tokens": 12,
            "temperature": 0.1,
        },
    }


async def wait_job(client: Client, job_id: str, *, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = await asyncio.to_thread(client.json, "GET", f"/api/jobs/{job_id}")
        if latest.get("status") in TERMINAL_STATUSES:
            return latest
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout:.0f}s: {latest}")


async def wait_status(
    client: Client,
    job_id: str,
    status: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = await asyncio.to_thread(client.json, "GET", f"/api/jobs/{job_id}")
        if latest.get("status") == status:
            return latest
        if latest.get("status") in TERMINAL_STATUSES:
            raise RuntimeError(
                f"Job {job_id} reached {latest.get('status')} before {status}: {latest}"
            )
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Job {job_id} did not reach {status} within {timeout:.0f}s: {latest}")


async def queue_one(client: Client, payload: dict[str, Any]) -> dict[str, Any]:
    jobs = await asyncio.to_thread(client.json, "POST", "/api/jobs", [payload])
    if not isinstance(jobs, list) or not jobs:
        raise RuntimeError(f"Unexpected queue response: {jobs!r}")
    return jobs[0]


def assert_events(events: list[dict[str, Any]], job_id: str, required: set[str]) -> None:
    seen = {event.get("type") for event in events if event.get("job_id") == job_id}
    missing = sorted(required - seen)
    if missing:
        raise AssertionError(f"Missing websocket events for {job_id}: {', '.join(missing)}")


def assert_video_ranges(client: Client, video_id: str) -> None:
    whole = client.raw(f"/api/videos/{video_id}/file")
    if whole["status"] != 200:
        raise AssertionError(f"Whole mp4 request returned HTTP {whole['status']}")
    if whole["headers"].get("Accept-Ranges", "").lower() != "bytes":
        raise AssertionError("Whole mp4 response did not advertise Accept-Ranges: bytes")
    if not whole["headers"].get("Content-Type", "").startswith("video/mp4"):
        raise AssertionError(
            f"Unexpected video content type: {whole['headers'].get('Content-Type')}"
        )

    partial = client.raw(f"/api/videos/{video_id}/file", headers={"Range": "bytes=0-127"})
    if partial["status"] != 206:
        raise AssertionError(f"Range mp4 request returned HTTP {partial['status']}")
    if len(partial["body"]) != 128:
        raise AssertionError(
            f"Range mp4 response returned {len(partial['body'])} bytes, expected 128"
        )
    content_range = partial["headers"].get("Content-Range", "")
    if not content_range.startswith("bytes 0-127/"):
        raise AssertionError(f"Unexpected Content-Range: {content_range!r}")

    for suffix in ("poster", "thumb"):
        asset = client.raw(f"/api/videos/{video_id}/{suffix}")
        if asset["status"] != 200:
            raise AssertionError(f"{suffix} request returned HTTP {asset['status']}")


async def run_completed_video(
    client: Client,
    model_id: str,
    args: argparse.Namespace,
    *,
    prompt: str,
) -> dict[str, Any]:
    job = await queue_one(client, video_payload(model_id, args, prompt=prompt))
    finished = await wait_job(client, job["id"], timeout=args.timeout)
    if finished.get("status") != "done":
        raise RuntimeError(f"Video job failed: {finished}")
    video_id = (finished.get("result") or {}).get("video_id")
    if not isinstance(video_id, str) or not video_id:
        raise RuntimeError(f"Video job completed without result.video_id: {finished}")
    return {**finished, "video_id": video_id}


async def run_check(args: argparse.Namespace) -> int:
    client = Client(args.base_url, args.api_token or os.environ.get("HFAB_API_TOKEN"))
    health = await asyncio.to_thread(client.json, "GET", "/api/health")
    print(f"Backend: {health.get('version')} stub_mode={health.get('stub_mode')}")
    if not args.allow_existing_jobs:
        await asyncio.to_thread(ensure_queue_idle, client)

    models = await asyncio.to_thread(client.json, "GET", "/api/models")
    video = choose_model(
        models,
        "video",
        model_id=args.video_model,
        preferred_family=args.video_family,
    )
    llm = None if args.skip_swap else choose_model(models, "llm", model_id=args.llm_model)
    print(f"Using video: {video['id']} ({video.get('family')})")
    if llm:
        print(f"Using LLM  : {llm['id']}")

    events: list[dict[str, Any]] = []
    stop = asyncio.Event()
    collector = asyncio.create_task(
        collect_events(args.base_url, client.api_token, events, stop)
    )
    await asyncio.sleep(0.1)
    try:
        await asyncio.to_thread(client.json, "POST", "/api/gpu/free")

        done_video = await run_completed_video(
            client,
            video["id"],
            args,
            prompt="P27 app smoke range replay",
        )
        assert_video_ranges(client, done_video["video_id"])
        assert_events(
            events,
            done_video["id"],
            {"job.started", "job.progress", "video.ready", "job.done"},
        )
        print(f"Range replay: PASS video_id={done_video['video_id']}")

        cancel_job = await queue_one(
            client,
            video_payload(
                video["id"],
                args,
                prompt="P27 app smoke cancel during denoise",
                steps=args.cancel_steps,
            ),
        )
        await wait_status(client, cancel_job["id"], "running", timeout=args.timeout)
        await asyncio.to_thread(client.json, "DELETE", f"/api/jobs/{cancel_job['id']}")
        cancelled = await wait_job(client, cancel_job["id"], timeout=args.timeout)
        if cancelled.get("status") != "cancelled":
            raise RuntimeError(f"Cancel smoke did not end cancelled: {cancelled}")
        assert_events(
            events,
            cancel_job["id"],
            {"job.started", "job.progress", "job.cancelled"},
        )
        print(f"Cancel running: PASS job_id={cancel_job['id']}")

        if llm:
            await asyncio.to_thread(client.json, "POST", "/api/gpu/free")
            first = await run_completed_video(
                client,
                video["id"],
                args,
                prompt="P27 app smoke swap video first",
            )
            gpu = await asyncio.to_thread(client.json, "GET", "/api/gpu")
            if gpu.get("model_id") != video["id"]:
                raise AssertionError(
                    f"Expected video resident after first video job, got {gpu}"
                )

            llm_job = await queue_one(client, llm_payload(llm["id"]))
            llm_finished = await wait_job(client, llm_job["id"], timeout=args.timeout)
            if llm_finished.get("status") != "done":
                raise RuntimeError(f"LLM swap job failed: {llm_finished}")
            gpu = await asyncio.to_thread(client.json, "GET", "/api/gpu")
            if gpu.get("model_id") != llm["id"]:
                raise AssertionError(f"Expected LLM resident after LLM job, got {gpu}")

            second = await run_completed_video(
                client,
                video["id"],
                args,
                prompt="P27 app smoke swap video second",
            )
            gpu = await asyncio.to_thread(client.json, "GET", "/api/gpu")
            if gpu.get("model_id") != video["id"]:
                raise AssertionError(
                    f"Expected video resident after second video job, got {gpu}"
                )
            assert_events(events, first["id"], {"job.done", "video.ready"})
            assert_events(events, llm_job["id"], {"job.done"})
            assert_events(events, second["id"], {"job.done", "video.ready"})
            print("Video -> LLM -> Video swap: PASS")

        print("video app smoke passed")
        return 0
    finally:
        stop.set()
        try:
            await asyncio.wait_for(collector, timeout=2.0)
        except TimeoutError:
            collector.cancel()
        await asyncio.to_thread(client.json, "POST", "/api/gpu/free")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8260")
    parser.add_argument("--api-token")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--allow-existing-jobs", action="store_true")
    parser.add_argument("--video-model")
    parser.add_argument("--video-family", choices=("ltx-video", "wan-video"))
    parser.add_argument("--llm-model")
    parser.add_argument("--skip-swap", action="store_true")
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--frames", type=int, default=9)
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--cancel-steps", type=int, default=80)
    parser.add_argument("--guidance", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=4242)
    return parser.parse_args()


def main() -> int:
    return asyncio.run(run_check(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
