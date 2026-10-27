# Danbooru Draw Skill

[English](#english) · [繁體中文](#繁體中文)

An agent skill for **Mochi (墨池)**: search the Danbooru lexicon, draw coherent tag prompts with the real draw engine, and generate images through Mochi's HTTP API.

Built for Codex and usable with Claude Code. No cloud image API, browser automation, or third-party Python dependencies.

## English

### What it does

- Searches tags in English or Chinese, with categories and metadata.
- Draws prompts using your installed `web/engine.js`, including pinning, bans, quotas and compatibility rules.
- Supports prompt-only previews, draw-and-generate, and direct rendering of a finished prompt.
- Streams generation progress and downloads the completed image.
- Saves prompts, draw seeds, generation seeds, model settings and job IDs for repeatable follow-ups.
- Reattaches after connection loss without automatically submitting another generation.
- Lists checkpoints, LoRAs, sampling settings, workflows, history and active jobs through read-only API requests.
- Cancels a specific job when asked.

**Drawing happens in Node; rendering happens on the server.** Mochi's `/api/gen` accepts a finished positive prompt. It does not draw tags for you. This skill connects the two.

### Requirements

| Component | Required for |
|---|---|
| Python 3.10+ | All HTTP helper commands; standard library only |
| Node.js 22.7+ | Lexicon search and drawing |
| [Mochi](https://github.com/bosen12/danbooru_tag_mochi) or [danbooru_tag_random](https://github.com/bosen12/danbooru_tag_random) checkout | Local `web/engine.js` and `web/lexicon.json` for drawing |
| Running Mochi HTTP server | Rendering, model/history queries and job control |
| Running ComfyUI, configured in Mochi | Actual image generation |

The normal Mochi launcher uses **port 8796**. Set `MOCHI_URL` if yours differs. Do not point the helper at ComfyUI's port 8188/8000.
Direct rendering with `positive` does not require Node or a local engine checkout.

### Install for Codex

Clone this repository into a folder named `danbooru-draw` inside your personal skills directory:

```powershell
git clone https://github.com/bosen12/danbooru_tag_draw_skill.git "$env:USERPROFILE/.codex/skills/danbooru-draw"
```

macOS / Linux:

```sh
git clone https://github.com/bosen12/danbooru_tag_draw_skill.git ~/.codex/skills/danbooru-draw
```

If you use a custom `CODEX_HOME`, install into its `skills/danbooru-draw` folder instead.
Start a new chat after installation and invoke `$danbooru-draw` explicitly if needed.
The `SKILL.md` entrypoint and optional UI metadata follow the [OpenAI skills format](https://developers.openai.com/codex/skills).

For **Claude Code**, use `~/.claude/skills/danbooru-draw` instead. The helper scripts are the same; the agent uses its own shell and image display tools.

For updates, run `git -C PATH_TO_SKILL pull --ff-only`. Keep images outside the installation folder.

### Configure

```powershell
$env:DTR_ROOT = 'C:/projects/danbooru_tag_random'
# Or point to a local danbooru_tag_mochi checkout.
$env:MOCHI_URL = 'http://127.0.0.1:8796'
$S = Join-Path $env:USERPROFILE '.codex/skills/danbooru-draw/scripts'
python "$S/mochi.py" doctor
```

macOS / Linux:

```sh
export DTR_ROOT="$HOME/projects/danbooru_tag_mochi"
export MOCHI_URL=http://127.0.0.1:8796
S="$HOME/.codex/skills/danbooru-draw/scripts"
python3 "$S/mochi.py" doctor
```

These settings apply to the current shell. Persist them in your usual shell profile if desired.
Inside an engine checkout, root discovery also works by walking upward from the current directory.

| Option | Default |
|---|---|
| `DTR_ROOT` / `generate --root` | Discover `web/engine.js` from cwd/helper ancestors; `MOCHI_ROOT` is an alternate environment variable |
| `MOCHI_URL` / `--url` | `http://127.0.0.1:8796` |
| `DTR_RUNS` / `--output` | `mochi-runs` under current working directory |
| `--timeout` | 30 seconds of HTTP inactivity; generation uses an SSE stream with keepalives |

The server and ComfyUI must already be running. The skill does not start or reconfigure them.
Localhost and Tailscale access restrictions are still enforced by Mochi.

### Ask your agent

```text
Use $danbooru-draw to draw a SFW prompt for an adult woman with white hair at the beach. Show the tags first, without generating.

Generate two images with this exact prompt, using different generation seeds.

Keep the previous seed and model, but change the hair color to blue.

Show the available checkpoints and the last ten generation records.

Resume the job from this run.json. Do not generate another image.
```

The default is **General Rating**, activity-only drawing, **1024×1024**, **one image**.
User-specified settings take priority. The skill does not import body, clothing or camera defaults from another image skill.

### Command-line quick start

Search once for the elements you want:

```powershell
node "$S/draw.mjs" search beach 'white hair' smile
node "$S/draw.mjs" groups
```

Save this UTF-8 file as `spec.json`:

```json
{
  "pins": ["1girl", "beach", "white hair", "smile"],
  "bans": ["glasses"],
  "counts": {"feature": 5, "pose": 4, "clothing": 3, "env": 4},
  "rating": "general",
  "heats": ["activity"],
  "drawSeed": 42,
  "width": 1024,
  "height": 1024,
  "n": 1
}
```

Preview without any HTTP request, then generate:

```powershell
python "$S/mochi.py" generate --spec spec.json --dry-run
python "$S/mochi.py" generate --spec spec.json --output C:/images/mochi
```

On macOS/Linux use `python3` and a suitable output path. All options follow the command, for example `mochi.py generate --url URL --spec spec.json`.
`--spec -` accepts stdin; a UTF-8 file avoids PowerShell encoding and quoting surprises.

### Reuse a prompt

To render the **same tags twice**, use the returned `positive` in a new spec:

```json
{
  "positive": "1girl, adult, white hair, smile, sundress, beach, outdoors",
  "rating": "general",
  "width": 1024,
  "height": 1024,
  "genSeed": "12345678901234567890",
  "n": 2
}
```

- `drawSeed` controls the random tag draw; `genSeed` controls image generation.
- An explicit `genSeed` increments by one for each batch image; omit it for random generation seeds.
- A drawing spec with `n:2` draws **two prompts**. A direct `positive` spec with `n:2` renders **one prompt twice**.
- Keep large generation seeds as decimal strings when moving them through JavaScript tools.
- To edit one detail, patch the previous prompt and keep its generation seed, checkpoint, LoRAs, Rating and dimensions. Identical composition is not guaranteed.
- Finished prompts bypass engine drawing and its pin/ban rules. Preserve only intentional tags in the prompt itself.

### Models, progress, history and cancellation

```powershell
python "$S/mochi.py" get /api/checkpoints
python "$S/mochi.py" get /api/loras
python "$S/mochi.py" get /api/sampling
python "$S/mochi.py" get /api/workflows
python "$S/mochi.py" get '/api/genlog?limit=10'
python "$S/mochi.py" get /api/gen/active
python "$S/mochi.py" attach --manifest C:/images/mochi/RUN/run.json
python "$S/mochi.py" cancel --job codex-YOUR_JOB_ID
```

Generation uses resumable SSE and saves a client job ID **before** POSTing.
Connection loss triggers up to three attach attempts. The client never automatically re-POSTs generation.
If the server no longer has the job, it checks recovery once and reports its state.

`attach --manifest` retries the latest submitted job or downloads an already completed result. Add `--job ID` to select an earlier job.
It recovers one submitted image; it does not submit the unstarted remainder of a failed batch.
If the server reports `pending`, try attach again later. Cancelling targets only the specified job.

### Output and troubleshooting

stdout is one JSON object; progress is JSON lines on stderr. Images and adjacent metadata use absolute local paths.
Each generation run has a `run.json` containing the spec, submitted payloads, job IDs and results.
Failures preserve completed images and recovery information. The agent can display `images[].path` directly.

| Symptom | Check |
|---|---|
| Connection refused / server unreachable | Start Mochi and verify `MOCHI_URL` and its port |
| `doctor`: server reachable, ComfyUI unavailable | Start ComfyUI or fix its connection in Mochi |
| Engine or lexicon not found | Set `DTR_ROOT` to the repo containing `web/engine.js` and `web/lexicon.json` |
| Requested pin missing | Inspect `droppedPins`; quota, Rating and engine compatibility can affect it |
| Unknown tag or ban | Check `notInLexicon` / `unknownBans`; free extras bypass engine checks |
| Image generated but download failed | Run `attach --manifest` to retry the saved result |
| Server restarted / job gone | Inspect the reported recovery state; a new generation requires an explicit new request |

The helper leaves checkpoint, workflow and sampling defaults to Mochi unless you override supported fields.
Custom negative prompts are not accepted by this client. No notification, deck or preference changes are performed.
For all spec fields and recovery details, see [the usage reference](references/usage.md).

### Development and tests

```powershell
python -m unittest discover -s tests -v
```

HTTP integration tests use a temporary loopback-only fake server; they do not call ComfyUI or use a GPU.
Set `DTR_ROOT` to enable the real-engine test. Without an engine checkout that test is skipped.
CI checks both Windows and Linux, Python 3.10/3.12, with a public Mochi checkout for the engine test.

### License and credits

**GPL-3.0-only**, by [bosen12](https://github.com/bosen12). See [LICENSE](LICENSE) and [NOTICE](NOTICE).
The draw helper builds on the existing `danbooru-draw` workflow and uses the installed engine from Mochi / danbooru_tag_random.
The engine, lexicon, models, LoRAs and generated images are not bundled here. Their applicable terms remain separate.

---

## 繁體中文

### 這是什麼

讓 Codex 或 Claude Code 使用**墨池**查詞、抽牌、組提示詞，再透過墨池 HTTP API 生圖的 skill。
它直接使用你本機現有的 `web/engine.js`，不另外複製一套抽牌邏輯。

- 中文／英文查詞，查看分類與 metadata。
- 釘選、禁用、分配各段張數，交給引擎處理相依與互斥。
- 只抽不生、抽完生圖，或直接使用現成提示詞。
- 顯示生成進度，下載成品，保存參數與工作編號。
- 斷線接回原工作，不會自動重送另一張。
- 查模型、LoRA、取樣參數、工作流程、出圖紀錄及進行中的工作。
- 指定工作取消，不中斷其他人的生圖。

**抽牌在 Node 裡，生圖在伺服器上。** `/api/gen` 只接收寫好的正向提示詞；這個 skill 負責把兩邊串起來。

### 需要什麼

| 項目 | 用途 |
|---|---|
| Python 3.10+ | HTTP helper；只用標準函式庫，不必 pip install |
| Node.js 22.7+ | 查詞與抽牌 |
| [墨池](https://github.com/bosen12/danbooru_tag_mochi)或[排字匣](https://github.com/bosen12/danbooru_tag_random)的本機 repo | 提供 `web/engine.js` 與 `web/lexicon.json` |
| 已啟動的墨池伺服器 | 生圖 API、模型與紀錄查詢、工作控制 |
| 已在墨池設定好的 ComfyUI | 真正執行生圖 |

墨池一般啟動埠是 **8796**；不同的話設 `MOCHI_URL`。
這裡要填墨池的埠，不是 ComfyUI 的 8188／8000。
直接給完整 `positive` 生圖時，不需要 Node 或本機詞庫。

### 安裝

Codex，Windows PowerShell：

```powershell
git clone https://github.com/bosen12/danbooru_tag_draw_skill.git "$env:USERPROFILE/.codex/skills/danbooru-draw"
```

macOS／Linux：

```sh
git clone https://github.com/bosen12/danbooru_tag_draw_skill.git ~/.codex/skills/danbooru-draw
```

如果有自訂 `CODEX_HOME`，改放到其 `skills/danbooru-draw`。
安裝後開一個新對話，需要時明確呼叫 `$danbooru-draw`。
Claude Code 改放 `~/.claude/skills/danbooru-draw`；同一套 helper 可以使用。

更新用 `git -C skill安裝路徑 pull --ff-only`；圖片建議存到 skill 資料夾之外。

### 設定與開始使用

```powershell
$env:DTR_ROOT = 'C:/projects/danbooru_tag_random'
# 也可以指向本機的 danbooru_tag_mochi。
$env:MOCHI_URL = 'http://127.0.0.1:8796'
$S = Join-Path $env:USERPROFILE '.codex/skills/danbooru-draw/scripts'
python "$S/mochi.py" doctor
```

macOS／Linux：

```sh
export DTR_ROOT="$HOME/projects/danbooru_tag_mochi"
export MOCHI_URL=http://127.0.0.1:8796
S="$HOME/.codex/skills/danbooru-draw/scripts"
python3 "$S/mochi.py" doctor
```

環境變數只影響目前 shell，需要永久使用可放進自己的 shell 設定。
在專案內執行時，也會往上找引擎；`--root` 可覆寫引擎位置，`--url` 可覆寫伺服器網址。
`DTR_RUNS`／`--output` 指定輸出資料夾，預設是目前目錄下的 `mochi-runs`。
`--timeout` 預設為 30 秒 HTTP 閒置時間，生圖串流會持續收到 keepalive。
伺服器與 ComfyUI 請先開好；skill 不會自行啟動服務或修改設定，原本的本機／Tailscale 連線限制仍然有效。

可以直接對 agent 說：

```text
用 $danbooru-draw 抽一組健全的海邊白髮成年女性提示詞，先不要生圖。
照這組提示詞生兩張，生圖 seed 要不同。
保留上一張的 seed 和模型，只把頭髮換成藍色。
列出底模和最近十筆出圖紀錄。
從這個 run.json 接回原工作，不要重生。
```

預設是**全年齡 General**、`activity` 尺度、**1024×1024、1 張**；使用者指定的優先。
不會從其他生圖 skill 帶入身材、衣著或鏡頭預設。

### 查詞、抽牌、生圖

```powershell
node "$S/draw.mjs" search 海邊 白髮 微笑
node "$S/draw.mjs" groups
```

把查到的 tag 放進 UTF-8 的 `spec.json`，例如：

```json
{
  "pins": ["1girl", "beach", "white hair", "smile"],
  "bans": ["glasses"],
  "counts": {"feature": 5, "pose": 4, "clothing": 3, "env": 4},
  "rating": "general",
  "heats": ["activity"],
  "drawSeed": 42,
  "width": 1024,
  "height": 1024,
  "n": 1
}
```

```powershell
python "$S/mochi.py" generate --spec spec.json --dry-run
python "$S/mochi.py" generate --spec spec.json --output C:/images/mochi
```

`--dry-run` 完全不連線、不生圖；拿掉後才送印。選項寫在子指令後面。
`--spec -` 可讀 stdin；使用 UTF-8 檔案可避免 PowerShell 管線的中文編碼與跳脫問題。
macOS／Linux 改用 `python3` 及適合的輸出路徑。

### 同一組再生、改一個細節

把上一組完整 `positive` 放進新規格，就不會重新抽牌：

```json
{
  "positive": "1girl, adult, white hair, smile, sundress, beach, outdoors",
  "rating": "general",
  "width": 1024,
  "height": 1024,
  "genSeed": "12345678901234567890",
  "n": 2
}
```

- `drawSeed` 是抽牌種子；`genSeed` 是生圖種子，彼此獨立。
- 指定 `genSeed` 時，批次每張加 1；省略則隨機。大數建議用十進位字串保存。
- 抽牌規格的 `n:2` 會抽兩組；完整 `positive` 的 `n:2` 才是同一組生兩張。
- 改細節只改相關 tag，沿用上一張生圖種子、尺寸、分級、模型與 LoRA；同種子仍不保證構圖完全不變。
- 完整 `positive` 會跳過引擎抽牌及 pins／bans 規則，請直接修改提示詞裡的內容。

### 查模型、紀錄、接回與取消

```powershell
python "$S/mochi.py" get /api/checkpoints
python "$S/mochi.py" get /api/loras
python "$S/mochi.py" get /api/sampling
python "$S/mochi.py" get /api/workflows
python "$S/mochi.py" get '/api/genlog?limit=10'
python "$S/mochi.py" get /api/gen/active
python "$S/mochi.py" attach --manifest C:/images/mochi/RUN/run.json
python "$S/mochi.py" cancel --job codex-YOUR_JOB_ID
```

送印前先保存工作編號與參數。串流斷線最多接回三次，不會自動重新 POST 生圖。
工作消失時會查一次 recovery 並回報狀態；`pending` 可稍後再 attach。
`attach --manifest` 預設接最後提交的工作，加 `--job ID` 可選別張；已完成但下載失敗也能重試下載。
它只接回一張已提交的圖，不會自動補送失敗批次中尚未提交的其他張。
取消只影響指定工作。

### 輸出、故障排除與限制

stdout 是一份 JSON，stderr 是逐行 JSON 進度。`images[].path` 是圖片絕對路徑。
每次生圖建立獨立資料夾，包含 `run.json`、圖片、同名 JSON 參數；失敗時保留已完成圖片與接回資訊。

| 問題 | 檢查方式 |
|---|---|
| 連不到伺服器 | 啟動墨池，確認 `MOCHI_URL` 與埠 |
| 墨池可連、ComfyUI 離線 | 開啟 ComfyUI 或在墨池修正連線 |
| 找不到詞庫／引擎 | `DTR_ROOT` 要指向含 `web/engine.js`、`web/lexicon.json` 的 repo |
| 釘選沒留下 | 看 `droppedPins`；可能受名額、分級、互斥影響，不只看 heat 註記 |
| 不認得 tag 或禁用字 | 看 `notInLexicon`／`unknownBans`；自由字不經引擎相容檢查 |
| 生完但下載失敗 | 用 `attach --manifest` 重試已保存的結果 |
| 伺服器重開／工作消失 | 看 recovery 狀態；不會自行重送新圖 |

未指定的模型、步數、CFG、workflow 與負向提示交給墨池設定。
helper 不接受自訂 `negative`，不會修改通知、牌組或偏好設定。
完整欄位與接回規則見 [usage reference](references/usage.md)。

### 測試與授權

```powershell
python -m unittest discover -s tests -v
```

HTTP 測試使用臨時本機模擬伺服器，不呼叫 ComfyUI、不用 GPU。
設 `DTR_ROOT` 可加跑真實引擎測試；沒有引擎時會跳過該項。
CI 在 Windows／Linux、Python 3.10／3.12 執行，並使用公開墨池 repo 測試引擎。

作者 [bosen12](https://github.com/bosen12)，採 **GPL-3.0-only**，見 [LICENSE](LICENSE) 與 [NOTICE](NOTICE)。
抽牌 helper 延續既有 `danbooru-draw` 工作流程；引擎、詞庫、模型、LoRA 與生成圖片不隨本 repo 提供，各自的適用授權維持不變。
