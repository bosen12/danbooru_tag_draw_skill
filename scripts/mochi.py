#!/usr/bin/env python3
# Copyright (c) 2026 bosen12. SPDX-License-Identifier: GPL-3.0-only
"""Standard-library Mochi HTTP client. JSON stdout; progress stderr."""
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
SEED_MAX = (1 << 64) - 1
DRAW_FIELDS = {
    "pins", "bans", "extra", "counts", "focus", "heats", "rating", "eras", "girl", "boy",
    "sceneMode", "width", "height", "n", "positive", "drawSeed", "seed", "samePerson",
    "drawJob", "drawCharacter", "characterSeries", "characterSameSeries", "characterFavOnly",
    "characterFavorites", "mustDraw", "offGroups", "eraMix", "pinCompanions", "pinMutex",
}
GEN_FIELDS = {"genSeed", "ckpt", "steps", "cfg", "loras", "workflowId", "pose"}


class ClientError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def log(event, **value):
    print(json.dumps({"event": event, **value}, ensure_ascii=False), file=sys.stderr, flush=True)


def read_spec(source):
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8-sig")
    spec = json.loads(raw.lstrip("\ufeff"))
    if not isinstance(spec, dict):
        raise ClientError("規格必須是 JSON object")
    unknown = set(spec) - DRAW_FIELDS - GEN_FIELDS
    if unknown:
        raise ClientError("不支援的規格欄位：" + ", ".join(sorted(unknown)))
    for field in ("pins", "bans", "extra", "heats", "eras", "offGroups", "characterFavorites"):
        if field in spec and (not isinstance(spec[field], list) or
                              not all(isinstance(v, str) for v in spec[field])):
            raise ClientError(field + " 必須是字串陣列")
    for field in ("counts", "focus", "mustDraw"):
        if field in spec and not isinstance(spec[field], dict):
            raise ClientError(field + " 必須是 object")
    n = spec.get("n", 1)
    if type(n) is not int or not 1 <= n <= 10:
        raise ClientError("n 必須是 1–10 的整數")
    for field in ("width", "height"):
        value = spec.get(field, 1024)
        if type(value) is not int or not 256 <= value <= 2048:
            raise ClientError(field + " 必須是 256–2048 的整數")
    if spec.get("rating", "general") not in ("general", "sensitive", "explicit"):
        raise ClientError("rating 必須是 general / sensitive / explicit")
    for field, allowed in (("heats", {"activity", "tease", "flash", "sex"}),
                           ("eras", {"modern", "ancient_china", "ancient_greece", "medieval", "edo", "victorian"})):
        if field in spec and (not spec[field] or set(spec[field]) - allowed):
            raise ClientError(field + " 含未知值或空清單；請用 draw.mjs groups 查詢")
    if spec.get("sceneMode", "normal") not in ("normal", "diverse", "weird"):
        raise ClientError("sceneMode 必須是 normal / diverse / weird")
    if "positive" in spec and (not isinstance(spec["positive"], str) or not spec["positive"].strip()):
        raise ClientError("positive 必須是非空字串")
    if "genSeed" in spec:
        value = spec["genSeed"]
        if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)) or not 0 <= int(value) <= SEED_MAX:
            raise ClientError("genSeed 必須是 0–2^64-1；大數請用十進位字串")
    if "loras" in spec:
        loras = spec["loras"]
        if not isinstance(loras, list) or len(loras) > 2 or any(
            not isinstance(lo, dict) or not isinstance(lo.get("file"), str) or not lo["file"].strip()
            for lo in loras
        ):
            raise ClientError('loras 最多兩筆，每筆需要 {"folder":"", "file":"模型.safetensors", "strength":0.8}')
    return spec


def draw(spec, root=None):
    if "positive" in spec:
        positive = spec["positive"].strip()
        return {"ok": True, "settings": {"width": spec.get("width", 1024),
                "height": spec.get("height", 1024), "rating": spec.get("rating", "general")},
                "results": [{"seed": None, "positive": positive,
                             "tagCount": len([t for t in positive.split(",") if t.strip()]),
                             "droppedPins": [], "conflicts": []} for _ in range(spec.get("n", 1))]}
    env = dict(os.environ)
    if root:
        env["DTR_ROOT"] = str(Path(root).resolve())
    proc = subprocess.run(["node", str(HERE / "draw.mjs"), "draw", "--spec", "-"],
                          input=json.dumps({k: v for k, v in spec.items() if k in DRAW_FIELDS}, ensure_ascii=False),
                          encoding="utf-8", capture_output=True, env=env, timeout=120)
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        raise ClientError("抽牌沒有回 JSON：" + (proc.stderr or proc.stdout)[-1000:])
    if proc.returncode or not out.get("ok"):
        raise ClientError(out.get("error", "抽牌失敗"))
    return out


class Client:
    def __init__(self, url, timeout=30):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ClientError("--url 請填墨池伺服器的 http(s)://主機:埠，不含 /api 路徑")
        self.url = url.rstrip("/")
        self.timeout = timeout
        # Loopback / Tailscale API calls should not be sent through HTTP_PROXY.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def open(self, path, payload=None, stream=False):
        if not path.startswith("/api/") or urllib.parse.urlsplit(path).netloc:
            raise ClientError("只接受同一台墨池的 /api/ 路徑")
        headers = {"Accept": "text/event-stream" if stream else "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers.update({"Content-Type": "application/json", "X-Gen-Resume": "1"})
        request = urllib.request.Request(self.url + path, data=body, headers=headers)
        try:
            return self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", str(exc))
            except (ValueError, UnicodeError):
                detail = str(exc)
            raise ClientError(f"HTTP {exc.code}: {detail}", exc.code) from exc

    def get(self, path, payload=None):
        with self.open(path, payload) as response:
            result = json.load(response)
        if isinstance(result, dict) and result.get("ok") is False:
            raise ClientError(result.get("error", "API 回報失敗"))
        return result

    def stream(self, path, job, persist, payload=None):
        with self.open(path, payload, stream=True) as response:
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                raise ClientError("預期 SSE，但伺服器沒有回傳 text/event-stream")
            event, data = "message", []
            for raw in response:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data:
                        value = json.loads("\n".join(data))
                        if event != "preview":
                            if value.get("prompt_id"):
                                job["promptId"] = value["prompt_id"]
                            if "seed" in value:
                                job["seed"] = value["seed"]
                            job["lastEvent"] = event
                            persist()
                            log(event, job=job["id"], **{k: v for k, v in value.items() if k in ("value", "max", "seed", "error")})
                        if event == "error":
                            raise ClientError(value.get("error", "生圖失敗"))
                        if event == "done":
                            return value
                    event, data = "message", []
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
        raise ConnectionError("SSE 在 done 前結束")

    def follow(self, job, persist, submit=False, reconnects=3):
        path = "/api/gen" if submit else "/api/gen/attach?" + urllib.parse.urlencode({"job": job["id"]})
        for attempt in range(reconnects + 1):
            try:
                return self.stream(path, job, persist, job["payload"] if submit and attempt == 0 else None)
            except ClientError as exc:
                if exc.status != 404 or path == "/api/gen":
                    raise
                recovered = self.get("/api/gen/recover?" + urllib.parse.urlencode({
                    "job": job["id"], "prompt_id": job.get("promptId", "")}))
                if recovered.get("state") == "done":
                    return {**job["payload"], **recovered}
                raise ClientError("接回工作失敗，recover 狀態：" + str(recovered.get("state")) +
                                  ("：" + str(recovered["error"]) if recovered.get("error") else "") + "；沒有重新送圖")
            except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
                if attempt == reconnects:
                    raise ClientError("連線中斷，已停止接回；沒有重新送圖：" + str(exc)) from exc
                log("reconnect", job=job["id"], attempt=attempt + 1)
                path = "/api/gen/attach?" + urllib.parse.urlencode({"job": job["id"]})
                time.sleep(min(attempt, 2))

    def image(self, src, destination):
        if not isinstance(src, str) or not src.startswith("/api/image?"):
            raise ClientError("圖片必須是同一台墨池的 /api/image? 網址")
        with self.open(src) as response:
            mime = response.headers.get_content_type()
            if not mime.startswith("image/"):
                raise ClientError("圖片 API 沒有回傳 image/*")
            raw = response.read()
        if not raw:
            raise ClientError("圖片是空的")
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, ".img")
        path = Path(destination).with_suffix(extension)
        path.write_bytes(raw)
        return str(path.resolve())


def save_image(client, job, result, directory):
    # Save the done event before downloading, so a failed download can be resumed.
    path = client.image(result["image"], directory / job["id"])
    meta = {**job.get("draw", {}), **result, "drawSeed": job.get("draw", {}).get("seed"),
            "seed": result.get("seed", job.get("seed")), "path": path, "job": job["id"],
            "payload": job.get("payload", {})}
    write_json(Path(path).with_suffix(".json"), meta)
    return meta


def generate(args, client, context):
    spec = read_spec(args.spec)
    drawn = draw(spec, args.root)
    if args.dry_run:
        planned = [(int(spec["genSeed"]) + i) & SEED_MAX for i in range(len(drawn["results"]))] if "genSeed" in spec else None
        return {**drawn, "dryRun": True, "plannedGenSeeds": planned}
    directory = (Path(args.output) / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    manifest_path = directory / "run.json"
    manifest = {"version": 1, "url": client.url, "spec": spec, "drawn": drawn, "jobs": []}
    context.update(manifest=str(manifest_path), images=[], **{
        key: drawn.get(key, []) for key in ("notInLexicon", "unknownBans", "pinned", "banned")})
    persist = lambda: write_json(manifest_path, manifest)
    persist()
    for index, row in enumerate(drawn["results"]):
        seed = (int(spec["genSeed"]) + index) & SEED_MAX if "genSeed" in spec else secrets.randbits(64)
        payload = {"positive": row["positive"], "width": drawn["settings"]["width"],
                   "height": drawn["settings"]["height"], "rating": drawn["settings"]["rating"],
                   "seed": seed, "origin": "mochi"}
        payload.update({k: spec[k] for k in GEN_FIELDS - {"genSeed"} if k in spec})
        job = {"id": "codex-" + uuid.uuid4().hex, "payload": payload, "draw": row, "status": "submitted"}
        payload["job"] = job["id"]
        manifest["jobs"].append(job)
        context["job"] = job["id"]
        persist()  # durable before the POST, even if its response is lost
        log("submit", job=job["id"], manifest=str(manifest_path))
        try:
            result = client.follow(job, persist, submit=True)
            job.update(status="done", result=result)
            persist()
            meta = save_image(client, job, result, directory)
            job.update(status="saved", path=meta["path"])
            context["images"].append(meta)
            persist()
        except Exception as exc:
            job["error"] = str(exc)
            persist()
            raise
    return {"ok": True, **context, "settings": drawn["settings"]}


def attach(args, client, context):
    manifest = None
    if args.manifest:
        manifest_path = Path(args.manifest).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if args.url is None:
            client = Client(manifest["url"], args.timeout)
        candidates = [j for j in manifest["jobs"] if not args.job or j["id"] == args.job]
        if not candidates:
            raise ClientError("manifest 找不到這個工作")
        job = candidates[-1]
        directory = manifest_path.parent
        context["manifest"] = str(manifest_path)
        persist = lambda: write_json(manifest_path, manifest)
    else:
        if not args.job:
            raise ClientError("attach 需要 --job 或 --manifest")
        job = {"id": args.job, "payload": {}}
        directory = Path(args.output).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        manifest_path = directory / ("attach-" + uuid.uuid4().hex + ".json")
        manifest = {"version": 1, "url": client.url, "jobs": [job]}
        persist = lambda: write_json(manifest_path, manifest)
        context["manifest"] = str(manifest_path)
    context["job"] = job["id"]
    persist()
    result = job.get("result") or client.follow(job, persist)
    job.update(status="done", result=result)
    persist()
    meta = save_image(client, job, result, directory)
    job.update(status="saved", path=meta["path"])
    persist()
    return {"ok": True, **context, "images": [meta]}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "get", "generate", "attach", "cancel"):
        p = commands.add_parser(name)
        p.add_argument("--url", default=None, help="墨池 URL；預設 MOCHI_URL 或 http://127.0.0.1:8796")
        p.add_argument("--output", default=os.environ.get("DTR_RUNS", str(Path.cwd() / "mochi-runs")))
        p.add_argument("--timeout", type=float, default=30, help="HTTP 閒置秒數；SSE 每 10 秒有 keepalive")
        if name == "get":
            p.add_argument("path", help="例如 /api/checkpoints 或 /api/genlog?limit=10")
        if name == "generate":
            p.add_argument("--spec", required=True, help="JSON 檔案；- 代表 stdin")
            p.add_argument("--root", help="抽牌專案路徑，也可設 DTR_ROOT")
            p.add_argument("--dry-run", action="store_true", help="只抽牌，完全不呼叫 HTTP")
        if name in ("attach", "cancel"):
            p.add_argument("--job", required=name == "cancel")
        if name == "attach":
            p.add_argument("--manifest", help="generate 回傳的 run.json；可接回並重試下載")
    args = parser.parse_args()
    context = {}
    try:
        if args.timeout <= 0:
            raise ClientError("timeout 必須大於 0")
        if getattr(args, "job", None) and not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", args.job):
            raise ClientError("job 格式錯誤")
        client = Client(args.url or os.environ.get("MOCHI_URL") or "http://127.0.0.1:8796", args.timeout)
        if args.command == "doctor":
            with client.open("/api/ping") as response:
                ping = json.load(response)
            result = {"ok": bool(ping.get("ok")), "url": client.url, "serverReachable": True,
                      "comfyReady": bool(ping.get("ok")), "ping": ping}
        elif args.command == "get":
            result = client.get(args.path)
        elif args.command == "cancel":
            result = client.get("/api/gen/cancel", {"job": args.job})
        elif args.command == "attach":
            result = attach(args, client, context)
        else:
            result = generate(args, client, context)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not isinstance(result, dict) or result.get("ok", True) else 1
    except (Exception, KeyboardInterrupt) as exc:
        error = "使用者中斷；可用 attach 接回或 cancel 停止" if isinstance(exc, KeyboardInterrupt) else str(exc)
        print(json.dumps({"ok": False, "error": error, **context}, ensure_ascii=False, indent=2))
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
