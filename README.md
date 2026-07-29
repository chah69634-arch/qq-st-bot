[English](README.md) | [简体中文](README.zh-CN.md)

# PresenceKit

An AI companion backend with long-term memory, emotional state, and the ability to reach out to you first. A QQ bot is just one of several optional channels — the core is a persona/memory/scheduling engine you can talk to over HTTP/WebSocket from any client.

---

## Repo relationship

```
PresenceKit (this repo, backend)
  ├── PresenceKit-desktop  Tauri desktop pet + admin panel client
  └── PresenceKit-mobile   Flutter mobile client
```

The backend is the single source of truth: long-term memory, emotional state, the proactive scheduler, the tool system, and the persona all live here. Desktop and mobile are **thin clients** — they render UI and forward user input, they don't own any business data. All three talk over HTTP/WebSocket; you can run the backend with only one client connected, both, or neither (pure QQ-bot mode).

---

## Features

### Memory system (five layers, running in parallel)

- **Short-term history**: sliding window of the last 20 turns, sanitized on read to avoid style self-feedback collapse
- **Mid-term summary**: compressed view of the last 12 hours, rendered into three time buckets (just now / a few hours ago / earlier), LLM-compressed with a rule-based fallback
- **Episodic memory**: structured fragments promoted from mid-term via eager/sweep, with strength decay, MMR diversity recall, and emotion-texture dedup
- **Stable behavior patterns** (user_identity): the character's long-term read on you, driven by a four-stage consolidation pipeline (capture → midterm → episodic → identity); survives restarts
- **Event log**: daily-sharded, keyword-searchable, with intensity decay scoring — low-intensity entries older than 7 days are skipped automatically

`character_growth` is kept as legacy-compatible data but is no longer the primary long-term context source for the live prompt.

### Emotional state system

- After every turn, an LLM detects the character's reply emotion and writes it to `mood_state`
- Drift formula: `new_intensity = old_intensity × 0.7 + new_emotion_intensity × 0.3`; a state switch needs two consecutive confirming turns
- The current emotional undertone is injected into the prompt as a soft hint, described at three intensity tiers
- Emotion feeds back into episodic recall scoring — memories that get recalled more often become more durable

### Prompt architecture (12+ layers)

- Layered prompt construction with tag gating, token estimation, and quality-graded trimming
- Lorebook / character card / user profile / realtime state / emotional undertone / episodic memory / mid-term summary / activity state / character diary / rotating Author's Note
- Probe mechanism: a keyword fast-path plus a minimal LLM probe runs ahead of the main turn to pre-判断 info/desktop tool calls
- Layer 11 (Author's Note): rotating personality traits plus corrective injection appended when `consistency_check` flags an issue
- When the token budget is exceeded, layers are trimmed lowest-quality-first

### Dream system

- An isolated Dream Session pipeline: doesn't enter the waking-conversation post-process, doesn't write to waking history/memory, doesn't trigger the scheduler
- A snapshot of the waking context is frozen on dream entry; dreams run their own D0–D10 prompt layer stack, world pack, and lorebook
- Three dream modes: sandbox (free-form world lore + jailbreak preset authoring) / scenario
  (scripted stage progression) / mirror (read-only figurative dreams, tendency material
  auto-derived from the user's hidden state); the admin panel's "Dream Settings" page
  authors each mode in its own tab, including create/rename/delete for world folders and scripts
- Supports a soft exit and an unstoppable hard exit; on exit the raw dream text is archived and a low-weight dream impression is distilled
- The waking prompt only ever receives the scene-stripped `6g_dream_impression`, so dream content can't be misremembered as reality

### Proactive trigger scheduler

- Good morning / good night / random daytime small talk (drawn from past messages carrying emotional words)
- Weather-linked messages, a daily diary entry the character writes itself, natural memory decay
- Multi-stage birthday triggers: night-before warmup, midnight greeting, afternoon check-in, evening wind-down
- Follow-ups on unfinished topics, proactive-recall triggers
- Holiday awareness, calendar-moment awareness, faster cadence over long holidays
- Periodic episodic-memory sweep/promotion (30-minute cooldown)
- Do-not-disturb module (implemented, pluggable)
- High-priority triggers (birthday / period / heart-rate alert) force-send even while the do-not-disturb window is active
- Cooldown state is persisted and survives restarts

### Emotional garden

- The character has its own flower plot: auto-watering, user-prompted watering, blooming, and post-harvest handling
- Garden state is exposed to the admin panel; key events can feed into the proactive scheduler

### Real-world data awareness

- **Apple Watch**: abnormal heart-rate alerts (low priority above 100bpm, high priority above 120bpm), sleep awareness and reports (pushed via an iPhone Shortcut)
- **Obsidian journal**: read by date, keyword-searchable over the last 30 days, marked as shared once read
- **Menstrual cycle awareness**: tag-gated during and near the cycle, auto-injects a care layer
- **Phone sensors**: steps / battery / location / screen-on count, injected whenever same-day data exists
- **Desktop pet screen-activity snapshot**: 5-minute TTL, injected on tag match

### Conversation capabilities

- Image recognition (GLM / Gemini / OpenAI Vision)
- TTS speech synthesis (GPT-SoVITS, reference audio switches with emotion)
- Sticker sending (emotion-linked, mutually exclusive with TTS)
- Tool calls: weather lookup, reminders, web search (DuckDuckGo), desktop control, and memory tools. When the per-character/global tool-loop switch is enabled, the function-calling main loop exposes the allowed registry categories (including memory); when it is off, the legacy probe/Path B paths remain in use.
- Desktop intent parsing: the character saying "let me close that game for you" actually minimizes the window
- Three channels — QQ, desktop pet, mobile polling — with WebSocket preferred for proactive desktop pushes and a file-queue fallback
- The desktop WebSocket supports a segmented `message_segments` narrative view; the raw reply remains the source of truth for memory
- Cross-channel continuity awareness — switching channels injects a pick-up-where-we-left-off hint

### Engineering quality

- Data paths are unified through `core/data_paths.py`, governance metadata is registered via `core/data_registry.py`, `core/sandbox.py` provides the singleton glue, and `core/migration.py` handles compatibility reads during migrations
- Test mode redirects all data writes to `data/test_sandbox/{session_id}/`, keeping production data untouched
- Atomic writes (`safe_write`, cross-platform `os.replace`)
- LLM output validation with up to 3 retries; on failure, old data is preserved
- Post-process is split into a critical path (lock-holding) and a slow queue (single worker, backoff retry), avoiding lock starvation
- Failed slow tasks go to a dead-letter queue (DLQ), monitored periodically by the scheduler
- Concurrency protection: per-uid locks plus a global emotional-state lock

---

## Tech stack

Python · FastAPI · NapCat (OneBot 11, optional) · DeepSeek / any OpenAI-compatible LLM API · GPT-SoVITS (optional)

---

## Quickstart

### 10-minute path (minimal playable config, no QQ/NapCat needed)

For new users who just want to get something running before reading further. Everything below goes through the desktop pet / admin panel; the QQ bot is optional (see "Optional integrations"). On Windows you can skip the manual commands and use the bundled `AA*.bat` scripts instead.

1. **Install dependencies**: double-click `AA1安装并启动.bat` (or manually run `pip install -r requirements.txt` + `cp config.example.yaml config.yaml`).
   **Expected output**: the terminal ends with `Successfully installed ...`, and a `config.yaml` now exists at the repo root.

2. **Initialize auth** (required before the first run): double-click `AA2鉴权初始化.bat` (or `python scripts/setup_auth.py`).
   **Expected output**:
   ```
   ✅ 鉴权初始化完成，凭据已写入 secrets.local.yaml（已 gitignore，勿提交）
   📖 已用系统默认程序打开 secrets.local.yaml
   ```
   This auto-opens the secrets file `secrets.local.yaml` — **don't close that window yet**. The admin-panel login secret (`admin_secret`) and every per-device token live in there; you'll come back to copy the login secret in the next step, and again later when connecting the desktop/mobile client.

3. **Start the backend**: double-click `AA3启动.bat` (or `python main.py`). If you're not connecting QQ, set `standalone_mode: true` in `config.yaml` first — that's the "minimal playable config" this section is about: it skips the NapCat connection while the desktop pet / admin panel keep working normally.
   **Expected output**: the terminal keeps printing `INFO`-level logs; once you see `Uvicorn running on http://127.0.0.1:8080` the backend is ready and the process should stay running (not exit).

4. **First panel login**: open `http://127.0.0.1:8080` in a browser and log in with the `admin_secret` from the secrets file.
   **Expected output**: you land on the "配置" (Setup) page automatically, with a red banner at the top: `⚠ 未配置将无法聊天/主动触发失效：请先填写下方「基础聊天模型」「owner_id」必填项` (chat and proactive triggers won't work until the required fields below are filled in).

5. **Configure the LLM API**: fill in `base_url` / `model` / `api_key` (e.g. DeepSeek) in the "基础聊天模型" (Primary Chat Model) card, save, then click the "测试连接" (Test connection) button next to it. Fill in `owner_id` on the same page too (your QQ number is recommended, even if you're not connecting QQ yet).
   **Expected output**: a green `✓ xxx ms · deepseek-chat` means the connection works; red text is the raw error — fix `base_url`/`api_key` accordingly. This save is hot-reloaded, **no backend restart needed**.

6. **Create a character card** (strongly recommended): the bundled `default` card is just a placeholder template (its name is literally "角色名" / "character name"). The panel shows a reminder card at this point — go to the "角色卡" (Character Card) page and create/edit your own character.
   **Expected output**: your new character card appears and saves in the editor; the reminder card on the Setup page disappears once you're no longer on the placeholder.

7. **Send your first message**: through the desktop client, or the admin panel's "聊天日志" (Chat Log) page.
   **Expected output**: a reply from the character within a few seconds, and a pipeline-related log line printed in the backend terminal.

At that point you have the minimal working loop: LLM configured, character card no longer a placeholder, and a real reply received.

**Requirements**

- Python 3.10–3.12 (3.12 recommended; 3.13+ not yet supported — `rapidocr-onnxruntime`
  caps at `<3.13`)

**Install**

```bash
git clone https://github.com/cicikat/PresenceKit.git
cd PresenceKit
pip install -r requirements.txt
```

**Windows shortcut**: instead of the manual steps below, double-click
`AA1安装并启动.bat` (installs deps, generates `config.yaml`), fill in
`config.yaml`, then `AA2鉴权初始化.bat` (auth init, required before the
first run) and `AA3启动.bat` (start). `AA2` finishes by auto-opening the
secrets file and the admin panel — the panel lands on the "配置"
(Setup) page on first launch; fill in the two red required fields
(① base chat model, ② `owner_id`) and you're ready to chat.
`AA更新.bat` does `git pull` + reinstall deps for later updates.

> **PresenceKit v1.0.0 is the first supported update baseline. Preview v0.x
> installations must migrate through backup and fresh installation.** Back up
> `data/`, `userdata/`, `config.yaml`, optional `config.local.yaml`, and
> optional `secrets.local.yaml`; install v1 into a new directory and copy only
> those protected items. Do not copy preview program trees such as
> `characters/`, `content/`, `defaults/`, `examples/`, `core/`, `scripts/`, or
> `.venv/`. See [Backend Upgrade and Recovery](docs/backend-upgrade-recovery.md).

**Configure**

```bash
cp config.example.yaml config.yaml
```

Fill in the required fields per the comments in `config.example.yaml`: your LLM API key, an admin-panel secret, and `scheduler.owner_id`; add a QQ number only if you're using the QQ bot. You can also skip editing the yaml directly and fill both required fields from the admin panel's "配置" (Setup) page.

`config.yaml` is the only file the app actually reads and writes — the admin panel's Setup/Settings pages persist directly to it. `config.example.yaml` is only a first-install template; it stays comment-annotated and is what you should check for field meanings. The two files' key sets are kept in sync by `scripts/gen_config_example.py`, so `config.yaml` growing longer and losing comments over time (from panel writes expanding defaults and YAML re-dumping) is expected, not a sign of corruption.

For `owner_id`, use your QQ number if you have one — using a different id here means connecting QQ later will start a separate memory thread that won't merge with the desktop-pet memories. Leaving it empty makes the proactive-message scheduler silently skip all triggers.

Create character cards in `userdata/characters/cards/`; the loader supports `.json`, `.txt`, and `.md` and retains a read-only fallback for legacy `characters/` installations. Other private authored assets belong below `userdata/characters/` (for example `authored/{char_id}/`, `reality/`, and `dream/`); see `docs/data-taxonomy.md`. Release-owned read-only seeds, templates, and examples live under `bundled/`, including `bundled/templates/character_template.json` and the neutral first-run `default` card.

**Initialize auth** (before the first run)

```bash
python scripts/setup_auth.py
```

This generates the admin-panel secret and per-device tokens, and writes them to a local secrets file `secrets.local.yaml` (already gitignored). See [docs/token-rotation.md](docs/token-rotation.md).

**Run**

```bash
# Using only the desktop pet or mobile client? Set standalone_mode: true in config.yaml to skip NapCat.
python main.py
```

To use the QQ bot: start NapCat first, make sure QQ is logged in and its WebSocket server is listening on port 3001, then run `python main.py`.

Test mode redirects all writes to an isolated sandbox, leaving production data untouched:

```bash
python run_test.py
```

Admin panel: `http://127.0.0.1:8080`

---

## Optional integrations

- **QQ / NapCat**: see "Run" above; skip it entirely with `standalone_mode: true` if you don't need the QQ bot.
- **Desktop client**: [PresenceKit-desktop](https://github.com/cicikat/PresenceKit-desktop) — requires the backend to be running. Before grabbing a release build, check its [Download section](https://github.com/cicikat/PresenceKit-desktop#download) for installer caveats (unsigned installer → SmartScreen prompt, Edge sometimes blocks the download outright, install to a non-system drive if you have one).
- **Mobile client**: [PresenceKit-mobile](https://github.com/cicikat/PresenceKit-mobile) — connects over a LAN IP or `adb reverse`.
- **TTS**: GPT-SoVITS; see the TTS-related fields in `config.example.yaml`.
- **Apple Watch**: push heart-rate/sleep data to the backend via an iPhone Shortcut; see the relevant fields in `config.example.yaml` and [docs/known-issues.md](docs/known-issues.md).

---

## Testing

```bash
pytest
python run_test.py
```

If you touch `tag_rules`-related logic, also run the eval suite:

```bash
python tests/run_eval.py
```

---

## Docs

| Doc | Content |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview, the four-stage pipeline, data directory layout |
| [docs/memory.md](docs/memory.md) | The five-layer memory subsystem design and concurrency protection |
| [docs/prompt-layers.md](docs/prompt-layers.md) | Prompt layer structure, tag gating, token trimming |
| [docs/tools.md](docs/tools.md) | Tool system, probe mechanism, desktop action execution |
| [docs/scheduler.md](docs/scheduler.md) | Full list of scheduler triggers and their cooldown design |
| [docs/channels.md](docs/channels.md) | QQ / desktop-pet channels, WebSocket, file fallback, cross-channel continuity |
| [docs/garden.md](docs/garden.md) | Emotional garden, auto/manual watering, post-harvest handling, admin panel state API |
| [docs/dream.md](docs/dream.md) | Dream Session isolation boundary, independent prompt stack, world pack and impression writeback |
| [docs/data-taxonomy.md](docs/data-taxonomy.md) | Current datapath layout, governance metadata, migration-era compatibility reads |
| [docs/assistant-turn-sink.md](docs/assistant-turn-sink.md) | Unified assistant-turn writes, broadcast, and the narrative-segment protocol |
| [docs/security_model.md](docs/security_model.md) | Admin panel, desktop-pet WebSocket, and client-secret boundaries |
| [docs/security.md](docs/security.md) | Auth model (scoped tokens): scope/profile tables, token management API |
| [docs/token-rotation.md](docs/token-rotation.md) | First-time setup, per-device token rotation commands, 401/403/429 troubleshooting |
| [docs/fresh-clone-testing.md](docs/fresh-clone-testing.md) | How to correctly test a fresh clone (avoid connecting to a stale backend process/data) |
| [docs/known-issues.md](docs/known-issues.md) | Current tech debt and verified fixes |
| [docs/v1-release-contract.md](docs/v1-release-contract.md) | v1 product contract: supported surfaces, exclusions, ownership, and fallbacks |
| [docs/v1-release-readiness.md](docs/v1-release-readiness.md) | Evidence-based v1 release blockers, compatibility matrix, and validation plan |

---

## Notes

- Personal/learning use only.
- Bring your own LLM API key (DeepSeek is recommended if you're in mainland China — direct connect, no proxy needed).
- Bring your own character card; see `userdata/characters/cards/` for the live location and `bundled/templates/character_template.json` for the format. This project ships no copyrighted character material.
- The project uses "他" (a male original character) as its example persona. The display name is configurable via `character.name` in `config.yaml`; some defaults, compatibility paths, and older docs still say `yexuan` internally — this doesn't affect functionality, and will be unified in a later version.

---

## License

This project is licensed under the PolyForm Noncommercial License 1.0.0.

Noncommercial use is permitted. Commercial use is not permitted without separate permission from the author.
