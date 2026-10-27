# Spec and HTTP reference

## Environment

| Setting | Meaning |
|---|---|
| `MOCHI_URL` / `--url` | Mochi **server** URL, default `http://127.0.0.1:8796`; not ComfyUI's 8188/8000 |
| `DTR_ROOT` / generate `--root` | Local repo containing `web/engine.js` and `web/lexicon.json` |
| `MOCHI_ROOT` | Alternate engine location if `DTR_ROOT` is unset |
| `DTR_RUNS` / `--output` | Output parent, default `mochi-runs` in current working directory |
| `--timeout` | HTTP idle timeout in seconds, default 30; server SSE keepalive arrives every 10 seconds |

Explicit `--url` overrides `MOCHI_URL`. With `attach --manifest`, an explicit `--url` overrides the saved URL; otherwise the saved URL is used.
Root discovery walks upward from cwd and helper location. No hardcoded drive or user profile is required.
HTTP calls bypass environment proxy settings so local/Tailscale traffic stays direct.

## Spec

| Field | Values / default |
|---|---|
| `positive` | Finished prompt; bypasses drawing, pins, extras and draw settings. Preserves the text apart from surrounding whitespace. |
| `pins`, `bans`, `extra` | Arrays of strings, default empty; underscores normalize to spaces in drawing mode |
| `counts` | Per-section quotas, default `{subject:2,feature:5,pose:4,clothing:3,env:4}` |
| `focus` | `{section: [group, ...]}`; prioritizes skeleton slots when quota is below the section cap |
| `rating` | `general` (default), `sensitive`, `explicit`; controls server negative and engine filtering |
| `heats` | Available values from `groups`; default `["activity"]`. Independent from Rating. |
| `eras` | Default `["modern"]`; available values from `groups` |
| `girl`, `boy` | Engine gender switches; current engine defaults apply |
| `sceneMode` | `normal` (default), `diverse`, `weird` |
| `width`, `height` | Integer 256–2048, default 1024; portrait example 832×1216, landscape 1216×832 |
| `n` | Integer 1–10; each request generates one image, sequentially |
| `drawSeed` | Unsigned 32-bit integer for engine RNG; drawing row i uses `(drawSeed+i) mod 2^32` |
| `seed` | Legacy alias for `drawSeed`; prefer the unambiguous name |
| `genSeed` | Unsigned 64-bit integer or decimal string; image i uses `(genSeed+i) mod 2^64`; omit for random seeds |
| `ckpt` | Exact checkpoint filename from `/api/checkpoints`; omitted = server default |
| `steps`, `cfg` | Optional server sampling overrides; omitted = server defaults |
| `loras` | Up to two `[{"folder":"", "file":"exact-file.safetensors","strength":0.8}]`; copy folder/file from `/api/loras` |
| `workflowId` | Saved workflow profile ID from `/api/workflows` |
| `pose` | Server pose-reference object; use current server schema if requested |

Advanced engine settings are passed through: `samePerson`, `drawJob`, `drawCharacter`,
`characterSeries`, `characterSameSeries`, `characterFavOnly`, `characterFavorites`,
`mustDraw`, `offGroups`, `eraMix`, `pinCompanions`, `pinMutex`.
Their meanings and compatibility follow the installed engine, which this skill does not vendor.

Direct prompting needs only Python and the HTTP server. Drawing additionally needs Node and the local project.
No custom `negative` field is accepted: the server selects its negative prompt from Rating and configuration.
Unknown spec fields fail instead of silently disappearing. Engine-specific values are sanitized by the installed engine.

### Draw, repeat, edit

- Draw n variations: omit `positive`, set `pins` and `n`.
- Render one prompt n times: set `positive` and `n`; do not reuse the original drawing spec.
- Repeat exactly: use the saved `positive`, width, height, Rating, checkpoint, LoRAs, workflow and `genSeed`, with `n:1`. Hardware/model changes can still affect pixels.
- Edit one detail: patch that prompt, keep generation parameters and `genSeed`; same seed does not guarantee identical composition.

Generation seeds are handled in Python, never round-tripped through Node. Keep 64-bit seeds as strings when transferring through JavaScript tools.
`genSeed:0` is valid. Batches increment an explicit seed rather than silently rendering the same seed n times.

### Warnings

Pins consume quotas. Dependencies, count tags, adult and quality tags affect the final number of tags, so approximately 25 is a target, not an exact promise.

- `droppedPins`: requested tags absent from the final prompt; inspect actual output, not heat annotations alone.
- `notInLexicon`: unknown pins are emitted as free extras. They bypass engine compatibility checks.
- `unknownBans`: tags not known to the engine; they cannot reliably be excluded from random draws.
- `conflicts`, `eraClash`, `heatClash`: engine diagnostics; report material conflicts rather than hiding them.
- Extras are deduplicated but are not validated by the engine's Rating or mutex rules. Check them before generation.

## Commands

Use `python scripts/mochi.py COMMAND --help` for flags.
All flags shown below follow the subcommand.

```powershell
python scripts/mochi.py doctor
node scripts/draw.mjs search 海邊 白髮 smile --section env
node scripts/draw.mjs groups
python scripts/mochi.py generate --spec spec.json --dry-run
python scripts/mochi.py generate --spec spec.json --output C:/images/mochi
python scripts/mochi.py get /api/checkpoints
python scripts/mochi.py get /api/loras
python scripts/mochi.py get /api/sampling
python scripts/mochi.py get /api/workflows
python scripts/mochi.py get '/api/genlog?limit=10'
python scripts/mochi.py get /api/gen/active
python scripts/mochi.py attach --manifest C:/images/mochi/RUN/run.json
python scripts/mochi.py attach --manifest C:/images/mochi/RUN/run.json --job codex-JOBID
python scripts/mochi.py cancel --job codex-JOBID
```

`get` only makes GET requests and expects JSON. For images, use the generation/attach download path.
The helper does not expose generic mutation endpoints for decks, preferences, messaging or configuration.

## Streaming and recovery

Generation POSTs `/api/gen` with `Accept: text/event-stream`, `X-Gen-Resume: 1`,
and a client-generated `job`. It saves that ID and payload before sending. Only a `done` event or a confirmed recovered result is success.

On transport failure or EOF, it reconnects to `GET /api/gen/attach?job=ID` up to three times.
It never automatically re-POSTs generation. HTTP errors and SSE `error` events stop the batch.
If attach returns 404, it asks `/api/gen/recover?job=ID&prompt_id=ID` once:

- `done`: download the recovered image.
- `pending` / `unknown` / `gone` / `failed`: return the state and manifest. No fresh image is submitted.

Use `attach --manifest` later to retry a pending job or failed download. By default it selects the most recently submitted job;
add `--job` to select another. Attaching without a manifest also works with `--job`, but the original manifest preserves more metadata.
Attach recovers one submitted job; it does not automatically submit the remainder of a failed batch.

The server normally allows around 30 seconds to reconnect and retains completed jobs around 30 minutes;
these are server policies, not guarantees made by the skill. A server restart can clear in-memory jobs.
`cancel --job` stops only that job. Interrupting the CLI does not send a global ComfyUI interrupt.

## Output contract

stdout contains one JSON object; progress is JSON lines on stderr. Exit 0 means success, 1 means failure, 130 means interrupted.
A dry run does not connect to HTTP or create output directories.
`plannedGenSeeds` lists the exact sequence for an explicit `genSeed`; it is null when seeds will be randomized at submission.

Actual generation creates:

```text
mochi-runs/YYYYMMDD-HHMMSS-random/
  run.json                   spec, settings, requests, job IDs, last-event markers and results
  codex-ID.png               downloaded image (extension follows response MIME)
  codex-ID.json              image metadata and exact submitted payload
```

Success includes `images[].path` as an absolute local path and `manifest`.
Failure preserves completed `images`, the current `job`, and `manifest` when one has been created.
The server's output retention may eventually remove an undownloaded image; local downloads remain independent.

## API boundaries

This client does not start services, change firewall rules, configure notifications, or send images to other people.
Default server access restrictions still apply: localhost and permitted Tailscale peers.
Use the current server's validation and do not bypass prompt checks via direct ComfyUI calls.

The engine and HTTP server evolve independently of this skill. For an unsupported optional feature such as a new pose schema,
inspect the installed `server.py` implementation or matching web client rather than inventing request fields.
