"""Exercise the skill as a CLI against a local fake Mochi, never a GPU."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL
ENGINE_ROOT = Path(os.environ.get("DTR_ROOT", str(SKILL.parents[1])))
CLI = SKILL / "scripts" / "mochi.py"
DRAW = SKILL / "scripts" / "draw.mjs"
PNG = bytes.fromhex("89504e470d0a1a0a") + b"fake image for transport test"


class Server(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def events(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for event, value in events:
            self.wfile.write(f"event: {event}\ndata: {json.dumps(value)}\n\n".encode())
        self.wfile.flush()

    def done(self):
        payload = self.server.posts[-1]
        return {"ok": True, "positive": payload["positive"], "seed": payload["seed"],
                "image": "/api/image?filename=test.png&subfolder=danbooru_case&type=output&h=abc",
                "width": payload["width"], "height": payload["height"], "ckpt": "test.safetensors"}

    def do_GET(self):
        self.server.gets.append(self.path)
        if self.path == "/api/ping":
            self.reply({"ok": self.server.mode != "offline", "error": "ComfyUI offline"})
        elif self.path.startswith("/api/gen/attach?"):
            if self.server.mode == "gone":
                self.reply({"ok": False, "error": "missing"}, 404)
            else:
                self.events([("done", self.done())])
        elif self.path.startswith("/api/gen/recover?"):
            self.reply({"ok": True, "state": "gone"})
        elif self.path.startswith("/api/image?"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(PNG)
        else:
            self.reply({"ok": True, "items": []})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/gen/cancel":
            self.server.cancelled.append(payload)
            self.reply({"ok": True})
            return
        self.server.posts.append(payload)
        self.server.headers_seen.append(dict(self.headers))
        if self.server.mode == "lost-response":
            self.close_connection = True
            return
        if self.server.mode == "error":
            self.events([("error", {"error": "model failed"})])
            return
        events = [("queued", {"seed": payload["seed"]}),
                  ("submitted", {"prompt_id": "prompt-123456"}),
                  ("progress", {"value": 1, "max": 2})]
        if self.server.mode not in ("disconnect", "gone"):
            done = self.done()
            if self.server.mode == "foreign-image":
                done["image"] = "https://example.invalid/image.png"
            events.append(("done", done))
        self.events(events)


class SkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".skill-test-", dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.http.mode = "normal"
        self.http.posts = []
        self.http.gets = []
        self.http.cancelled = []
        self.http.headers_seen = []

    def cli(self, spec=None, *args, command="generate"):
        argv = [sys.executable, str(CLI), command, "--url", self.url,
                "--output", self.tmp.name, *args]
        if spec is not None:
            argv += ["--spec", "-"]
        p = subprocess.run(argv, input=json.dumps(spec) if spec is not None else "",
                           text=True, encoding="utf-8", capture_output=True, timeout=30)
        self.assertTrue(p.stdout.strip(), p.stderr)
        return p, json.loads(p.stdout)

    def test_dry_run_direct_needs_no_project_or_server(self):
        p, out = self.cli({"positive": "1girl, adult, beach", "n": 2}, "--dry-run", "--root", self.tmp.name)
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(out["results"][0]["positive"], "1girl, adult, beach")
        self.assertEqual(self.http.gets, [])
        self.assertEqual(self.http.posts, [])

    def test_sse_download_manifest_and_seed_precision(self):
        seed = 18446744073709551600
        p, out = self.cli({"positive": "1girl, adult, beach", "genSeed": str(seed), "n": 2})
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual([p["seed"] for p in self.http.posts], [seed, seed + 1])
        self.assertEqual(len(out["images"]), 2)
        self.assertEqual(Path(out["images"][0]["path"]).read_bytes(), PNG)
        self.assertTrue(Path(out["manifest"]).is_absolute())
        manifest = json.loads(Path(out["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["jobs"][0]["status"], "saved")
        self.assertEqual(self.http.headers_seen[0]["X-Gen-Resume"], "1")
        self.assertIn("progress", p.stderr)

    def test_disconnect_attaches_without_resubmitting(self):
        self.http.mode = "disconnect"
        p, out = self.cli({"positive": "beach"})
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual(len(self.http.posts), 1)
        self.assertTrue(any(p.startswith("/api/gen/attach?") for p in self.http.gets))

    def test_lost_response_attaches_using_persisted_client_job(self):
        self.http.mode = "lost-response"
        p, out = self.cli({"positive": "beach"})
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual(len(self.http.posts), 1)

    def test_error_event_stops_batch_and_keeps_manifest(self):
        self.http.mode = "error"
        p, out = self.cli({"positive": "beach", "n": 2})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("model failed", out["error"])
        self.assertTrue(Path(out["manifest"]).exists())
        self.assertEqual(len(self.http.posts), 1)

    def test_missing_job_recovery_never_regenerates(self):
        self.http.mode = "gone"
        p, out = self.cli({"positive": "beach"})
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(len(self.http.posts), 1)
        self.assertTrue(any(p.startswith("/api/gen/recover?") for p in self.http.gets))
        self.assertTrue(out["job"])

    def test_rejects_foreign_image_url(self):
        self.http.mode = "foreign-image"
        p, out = self.cli({"positive": "beach"})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("/api/image", out["error"])

    def test_doctor_distinguishes_comfy_offline(self):
        self.http.mode = "offline"
        p, out = self.cli(command="doctor")
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(out["serverReachable"])
        self.assertFalse(out["comfyReady"])

    def test_cancel_uses_specific_job(self):
        p, out = self.cli(None, "--job", "codex-12345678", command="cancel")
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual(self.http.cancelled, [{"job": "codex-12345678"}])

    def test_unknown_spec_field_fails_before_post(self):
        p, out = self.cli({"positive": "beach", "negative": "ignored?"})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("negative", out["error"])
        self.assertEqual(self.http.posts, [])

    def test_attach_saved_result_downloads_without_resubmission(self):
        p, first = self.cli({"positive": "beach"})
        self.assertEqual(p.returncode, 0, first)
        original_posts = len(self.http.posts)
        Path(first["images"][0]["path"]).unlink()
        p, out = self.cli(None, "--manifest", first["manifest"], command="attach")
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual(Path(out["images"][0]["path"]).read_bytes(), PNG)
        self.assertEqual(len(self.http.posts), original_posts)

    def test_invalid_heat_rejected_before_http(self):
        p, out = self.cli({"heats": ["activty"]})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("heats", out["error"])
        self.assertEqual(self.http.posts, [])

    def test_generation_returns_draw_warnings(self):
        if not (ENGINE_ROOT / "web" / "engine.js").exists():
            self.skipTest("Set DTR_ROOT to run the real-engine integration test")
        p, out = self.cli({"pins": ["unknown-custom-scene"], "bans": ["unknown-custom-ban"]}, "--root", str(ENGINE_ROOT))
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual(out["notInLexicon"], ["unknown-custom-scene"])
        self.assertEqual(out["unknownBans"], ["unknown-custom-ban"])

    def draw(self, spec):
        return subprocess.run(["node", str(DRAW), "draw", "--spec", "-"],
                              input=json.dumps(spec), text=True, encoding="utf-8", capture_output=True,
                              env={**os.environ, "DTR_ROOT": str(ENGINE_ROOT)}, timeout=30)

    def test_real_engine_reproducible_and_extras_deduplicated(self):
        if not (ENGINE_ROOT / "web" / "engine.js").exists():
            self.skipTest("Set DTR_ROOT to run the real-engine integration test")
        spec = {"pins": ["1girl", "beach", "white_hair"], "extra": ["adult", "adult"], "drawSeed": 42}
        a, b = self.draw(spec), self.draw(spec)
        self.assertEqual(a.returncode, 0, a.stdout + a.stderr)
        self.assertEqual(a.stdout, b.stdout)
        out = json.loads(a.stdout)
        tags = out["results"][0]["positive"].split(", ")
        self.assertEqual(tags.count("adult"), 1)
        self.assertIn("white hair", tags)
        self.assertEqual(out["settings"]["rating"], "general")

    def test_invalid_draw_spec_returns_json(self):
        p = self.draw({"pins": "beach"})
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(json.loads(p.stdout)["ok"])

    def test_mixed_eras_keeps_requested_pins(self):
        if not (ENGINE_ROOT / "web" / "engine.js").exists():
            self.skipTest("Set DTR_ROOT to run the real-engine integration test")
        p = self.draw({"pins": ["hanfu", "skyscraper"], "eraMix": True,
                       "eras": ["modern", "ancient_china"], "heats": ["tease"],
                       "rating": "sensitive", "drawSeed": 42})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout)
        self.assertIn("hanfu", out["pinned"])
        self.assertIn("skyscraper", out["pinned"])


if __name__ == "__main__":
    unittest.main()
