---
name: danbooru-draw
description: >
  Use when the user wants Mochi / 墨池 / 排字匣 to search Danbooru tags,
  抽牌、抽籤、抽 tag、隨機提示詞, generate images through Mochi's local HTTP
  API, reuse or edit a previous prompt, inspect generation history, or resume
  a Mochi job. Does not apply to unrelated image tools or cloud generation.
license: GPL-3.0-only
---

# 墨池抽牌與生圖

使用本 skill 旁的 `scripts/draw.mjs` 與 `scripts/mochi.py`。不依賴 Claude 專用工具、Bash 或第三方 Python 套件。
抽牌直接載入現有 `web/engine.js`；生圖走墨池 HTTP API，伺服器負責 workflow、模型預設與負向提示。

## 選擇工作

| 使用者要的 | 做法 |
|---|---|
| 查詞／抽牌，不生圖 | `draw.mjs search`／`mochi.py generate --dry-run` |
| 抽完生圖 | 把描述轉成 spec，再 `mochi.py generate --spec spec.json` |
| 已有完整提示詞／修改上一張 | spec 填 `positive`，直接生圖，不再抽牌 |
| 模型、紀錄、工作狀態 | `mochi.py get /api/checkpoints` 等唯讀 API |
| 接回／停止 | `mochi.py attach --manifest run.json`／`cancel --job ID` |

## 設定與執行

`S` 代表本 skill 的 `scripts` 絕對路徑，從這份 SKILL.md 的位置取得。
墨池預設 `http://127.0.0.1:8796`；其他位置設 `MOCHI_URL` 或 `--url`。
抽牌需要本機排字匣或 Mochi repo，設 `DTR_ROOT` 指向含 `web/engine.js` 的資料夾；在 repo 內可自動找到。
直接給 `positive` 的生圖只需 Python 與運行中的墨池，無需 Node 或本機詞庫。

```powershell
$S = Join-Path $env:USERPROFILE '.codex/skills/danbooru-draw/scripts'
$env:DTR_ROOT = 'C:/projects/danbooru_tag_random'
node "$S/draw.mjs" search 海邊 白髮 微笑
python "$S/mochi.py" generate --spec spec.json --dry-run
python "$S/mochi.py" generate --spec spec.json
```

用檔案工具寫 UTF-8 spec，避免 PowerShell 管線的編碼或命令跳脫問題。
`--spec -` 也支援 stdin。長工作讓工具回傳 session，再持續讀取；不要因為工具先返回就重送。

## 描述轉 spec

一次搜尋重要元素，搜尋結果的 `tag` 原樣放 `pins`；不要的放 `bans`。
查不到才放 `extra`；這些自由字不經引擎互斥／分級檢查，需自己檢查是否符合使用者要求。
預設全年齡 `rating: general`、`heats: [activity]`、1024×1024、1 張；使用者指定優先。
不要帶入其他 skill 的身材、服裝或鏡頭預設。

```json
{
  "pins": ["1girl", "beach", "white hair", "smile"],
  "counts": {"feature": 5, "pose": 4, "clothing": 3, "env": 4},
  "rating": "general",
  "heats": ["activity"],
  "width": 1024,
  "height": 1024,
  "n": 1
}
```

四段總數 15–17 通常接近 25 tags，實際數量受相依字影響。釘選佔段落名額。
`drawSeed` 控制抽牌；`genSeed` 控制生圖，兩者分開。大量種子用十進位字串保存，避免 JavaScript 精度流失。
完整欄位、批次 seed 規則與進階 API 見 [references/usage.md](references/usage.md)，需要時才讀。

## 接續與失敗處理

- 「再抽」保留 spec 重抽；「同一組再生」沿用完整 `positive`、尺寸、分級等參數，換 `genSeed`。
- 改一處細節時只改相關 tag，保留上一張 `genSeed`、模型及尺寸；不保證構圖完全相同。
- helper 自動保存 `run.json`，遇到斷線只接回原工作，最多三次；沒有自動重生。
- 接回用 `attach --manifest`；批次指定 `--job` 可選先前那張。它只處理一張，不自動續跑未提交的批次。
- API 明確報錯就停止，回報已完成的圖片、manifest、job；不取消別人的工作。
- 墨池或 ComfyUI 沒開時回報哪一層離線；連線不明可跑 `doctor`。不自動改防火牆、模型或服務設定。

## 交付

stdout 是 JSON；進度在 stderr。圖片位於 `images[].path`，用絕對路徑 Markdown `![圖片](/absolute/path.png)` 顯示。
附一行提示詞、seed、必要的 `droppedPins`／`notInLexicon`／`unknownBans` 警告；保留可接續的 manifest。
以抽出結果判斷釘選是否保留，不單看詞庫 heat 註記。不要自行評分或無限重抽，也不要繞過伺服器的內容檢查。
