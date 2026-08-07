# v1 Cold Start and Single-User Deployment

This is the operator runbook for a new v1 installation. It describes the
supported single-user shape: one owner, one backend process, and local or
explicitly protected remote clients. Authentication remains mandatory even
when every client belongs to the same person.

## Clean install

1. Use Python 3.10-3.12 (3.12 is the supported recommendation), install the
   dependencies, and copy `config.example.yaml` to `config.yaml`.
2. Run `python scripts/setup_auth.py`. Keep `secrets.local.yaml` outside source
   control. The command creates the break-glass admin secret and scoped device
   tokens; it does not print existing token values on a later run.
3. For a desktop-only install set `standalone_mode: true`. Leave `qq.enabled`
   false unless NapCat is deliberately part of this deployment.
4. Start `python main.py`. A valid auth secret/token, a loadable default
   character, and a valid data root are required before services start.
5. Open the admin panel on the configured loopback address. The Setup page
   requires a working chat model and `scheduler.owner_id`; Embedding is
   optional and falls back to keyword recall when not configured.
6. Select or create the active character card, test the model connection, then
   send one owner chat through the desktop client or `/desktop/chat`.

The clean-start success condition is a real assistant reply, not merely a
running HTTP process. Do not copy a developer `data/`, `config.yaml`, or
`secrets.local.yaml` into a clean-start test.

## Conservative defaults

The public template is intentionally dormant until the owner opts in:

| Surface | First-run expectation | How to verify |
|---|---|---|
| Unsolicited speech | `scheduler.enabled: false`; no owner means no proactive run | `GET /scheduler/status` |
| Autonomy | Durable autonomy config starts disabled | `GET /admin/autonomy/effective-state` |
| MCP | Global and per-server switches are disabled; startup makes no external MCP connection | `GET /settings/mcp` |
| Hardware | Hardware and Intiface are disabled; no job is started at boot | `GET /hardware/status` (when available) |
| High-risk tools | Shutdown, sleep, toy actuation, and similar tools are disabled or confirmation-gated | Admin tool policy page and `GET /status` |
| QQ/NapCat | Disabled by default; standalone mode does not create a QQ connection | startup log and `GET /status` |
| Embedding | Placeholder credentials are treated as not configured; chat remains usable | `GET /settings/setup-status` |

`coplay.enabled` is only a deployment capability switch. It does not arm a
game session. Never treat it as permission to start a game automatically.

## Readiness checklist

Run these checks after first setup and after every restore or upgrade. Record
the result with the release candidate commit.

- [ ] **Model:** Setup reports the base chat model configured and its connection
  test succeeds. Provider errors are actionable and do not silently select a
  different provider.
- [ ] **Data paths:** `/status` reports the intended production data root;
  `mode` is not a test sandbox. `data/layout_version.json` is present after a
  successful v1 initialization.
- [ ] **Permissions:** the service account can read bundled assets and write
  the declared `data/` and `userdata/` roots, but the backup destination is
  outside the installation. Secrets are not world-readable.
- [ ] **Authentication:** the panel accepts the scoped panel token; an absent
  secret/token blocks startup; a device token cannot call admin-only routes.
- [ ] **Character:** the active card loads and a chat reply is delivered. A
  placeholder card is a product-quality warning, not a runtime fallback.
- [ ] **Scheduler/autonomy:** `/scheduler/status` and
  `/admin/autonomy/effective-state` show the intended enabled state, owner,
  cooldown, and channel. A disabled scheduler must not emit a turn.
- [ ] **MCP:** `/settings/mcp` shows disabled when not explicitly required.
  If enabled, every server has a local allowlist/policy and a failed server is
  reported as unavailable without preventing local chat.
- [ ] **Channels:** test one intended channel only. Verify desktop WS or
  mobile poll/ack as applicable; leave QQ disconnected when `standalone_mode`
  is used.
- [ ] **Health and logs:** `/system/health` is reachable with `state.read`,
  silent-failure counters are understood, and logs contain no credential URLs.

The checks above are operational evidence. A green HTTP health response alone
does not prove model, channel, or scheduler readiness.

## v0.2.2 migration

v0.2.2 is a preview source and is not an automatic-update source. The supported
path is deliberately explicit:

1. Stop the old process and create/verify an offline private-state snapshot.
2. Install v1 in a new empty directory.
3. Copy only the protected state listed by
   [Offline Private-State Backup](offline-state-backup.md): `data/`,
   `userdata/`, local configuration/secrets, and reviewed legacy private
   authored assets. Do not overlay `core/`, `scripts/`, `defaults/`,
   `examples/`, `.venv/`, or other program files.
4. Run the authored-root dry run with `--fail-on-diverged --fail-on-invalid`.
   `legacy-only`, `diverged`, `invalid`, `incomplete`, or `unresolved` results
   are actionable blockers requiring manual review; they are never silently
   overwritten.
5. Start v1 and complete the clean-start and readiness checks. The first viable
   startup writes the v1 layout marker; it does not claim to have migrated
   arbitrary preview state.

For v1 and later, the updater accepts only a supported v1 marker and a
non-downgrade target. Preview sources, future schemas, missing markers, and
downgrades fail before program replacement. Restore the updater snapshot or an
offline private-state snapshot in a new target and cut over manually.

## Backup, restore, and retention

Stop the service before taking a snapshot. The command refuses a running or
unknown service and never uploads data:

```powershell
python main.py backup-state create --output <protected-volume>\presencekit-snapshot --protection-mode protected_volume
python main.py backup-state verify <protected-volume>\presencekit-snapshot
```

Keep at least one recent snapshot on a separate protected volume. Retention and
off-site encryption are operator responsibilities; `protected_volume` is not an
encrypted archive. Test a restore before relying on a backup:

```powershell
python main.py backup-state restore <snapshot> --target <new-empty-directory>
```

Restore verifies hashes and performs a read-only startup check with outbound
calls disabled. It does not replace the live installation, delete the source,
or perform an implicit version migration. Review the recovery report, then
perform a manual cutover.

## Single-user server shape

- Bind the admin service to `127.0.0.1` for local clients. For LAN or remote
  access, put an HTTPS reverse proxy in front of it, restrict the proxy to the
  required paths, and keep the backend bind private. Do not expose plain HTTP
  or the break-glass secret to the public network.
- Store `secrets.local.yaml` and any proxy credentials with the service account
  permissions only. Use scoped `panel`, `desktop`, `mobile`, `watch`, and
  `device` tokens; do not reuse the admin secret on edge devices.
- Back up while stopped, verify the manifest, and keep the backup destination
  outside the install. Rotate tokens after a device is lost and after a backup
  leaves the protected host.
- Rotate `data/logs` and forensic logs according to the configured size/keep
  limits. Do not place secrets in debug prompts or enable LLM request logging
  outside a short diagnostic window.
- Restart with the same service account and data root. Hardware jobs left
  active by a prior process are marked expired and an explicit stop is
  attempted; they are never resumed automatically.
- Scheduler schedule entries default to `restart_miss_policy: skip`. Expired
  wake/autonomy signals are terminal, and one-shot desktop wake signals are
  discarded when autonomy is disabled. A restart therefore does not replay a
  stale proactive event.

## External MCP failure behavior

MCP is optional. With `mcp_servers.enabled: false`, startup must not attempt a
network connection. When an explicitly enabled server is unreachable, its
connection is recorded as unavailable, its tools are not exposed, and local
chat continues. Do not respond to an `outcome_unknown` hardware action by
automatically retrying it; inspect device state or use the emergency stop path.

## Residual release risks

The following are not proven by this runbook and must remain visible in the
release decision: Android production signing and Keystore migration, real-device
relay/Doze recovery, cross-repository protocol compatibility, optional hardware
and MCP integrations, and any authored-root entries reported by the migration
dry run. These are release evidence gaps, not reasons to weaken authentication
or enable integrations by default.
