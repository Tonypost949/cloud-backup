# ☁️ Cloud Backup — Directions (Space & Backup & Recording, for global use)

_Stack: amd949609@gmail.com / Tonypost949 · Created 2026-10-19 by OpenCode agent (DeepSeek V4.1 Flash Free) · Law 15 dynamic tiering + Law 14 backup discipline_

## What this is

The command-and-control folder for backing up everything on this VM — and by copy, on any machine — to the user's cloud spaces:

| Node | Real address | Status |
|------|--------------|--------|
| **Google (GCS)** | `gs://backup-project-743aab84-f9a5-4ec7-954` (+ `gs://osintneoxl`, `gs://adc-d759a403-9030-45ab-9c81-cd5f822fe3bc`) | ✅ ACTIVE |
| **Microsoft (OneDrive 1 TB)** | account `amd949609@gmail.com` via rclone remote `onedrive` | 🚫 blocked from VM (MSA rate-limit wall) — fallback: Windows-side token import (queued) |
| **GitHub** | `https://github.com/Tonypost949/OsintNeoAi.git`, `https://github.com/Tonypost949/ailaws`, this repo: `https://github.com/Tonypost949/cloud-backup` | ✅ ACTIVE |
| **Azure DevOps** | `https://dev.azure.com/anthonydimarcello/osintneoai/_git/osintneoai` | ⏳ queued (no PAT on VM) |
| **Windows user folder** | `C:\Amd949609_Antigravity_v1\` (+ `cloud_storage\gdrive_backup`, OneDrive sync) | user machine |

Full node registry: `storage_nodes.csv` (Label is primary column). Credential locations: `~/Amd949609_keys/CREDENTIALS_INDEX.md`.

## Files here

| File | Purpose |
|------|---------|
| `cloud_backup.sh` | Executor — pushes sets to ALL configured targets; appends backup ledger |
| `storage_nodes.csv` | Registry of every storage node |
| `onedrive_auth.py` … `onedrive_auth6.py` | OneDrive OAuth onboarding automation lineage (v1 → v6, see below; account creds in `~/.config/onedrive`) |
| `README.md` | This directions file |
| `manifests/`, `onedrive_auth_shots/` (34 MB), `onedrive_auth*.log` | Evidence + logs (per-step screenshots + HTML dumps) |

## Commands

```bash
~/tools/cloud_backup/cloud_backup.sh push critical   # laws, task system, keys, auth configs
~/tools/cloud_backup/cloud_backup.sh push daily      # lightweight daily set
~/tools/cloud_backup/cloud_backup.sh push tools      # all tool packages
~/tools/cloud_backup/cloud_backup.sh push mirrors    # GitHub mirror tree (~5.6 GB)
~/tools/cloud_backup/cloud_backup.sh push all
~/tools/cloud_backup/cloud_backup.sh verify critical
~/tools/cloud_backup/cloud_backup.sh targets
```

Every push lands under `<remote>:<root>/<machine>/<UTC-stamp>/<label>/` — fully versioned by timestamp; nothing is ever overwritten. A daily cron runs `push daily` at 08:17 UTC.

## OneDrive onboarding — chain & blocker (2026-10-19)

Lineage: `onedrive_auth.py` (v1) → `onedrive_auth4.py` (menu-path probe + WebAuthn stub) → `onedrive_auth5.py` (regression, fixed in v6) → `onedrive_auth6.py` (final).

**Validated chain (v6)** — this is the recipe that reaches password sign-in on a passkey-default account:

1. Email entry on `login.microsoftonline.com`.
2. Account hard-routes to the FIDO/passkey wall (`login.microsoft.com/consumers/fido/get`).
3. WebAuthn stubbed in the browser context (`navigator.credentials` rejects) so the passkey attempt fails fast.
4. Click `#moreOptions` (“…”) → **“Sign in another way”**.
5. Classic options page → **“Use your password”** (`div[aria-label="Use your password"]` → `span[role=button]`).
6. Password entry page (`#passwordEntry`, Fluent UI).

**Result from this VM:** the password submission was rejected with the MSA wall —
> “You've tried to sign in too many times with an incorrect account or password.”

**Decision:** zero further password attempts from this VM (datacenter IPs are rate-limited by MSA; repeated attempts risk the account).

**Fallback (only remaining path here)** — one-time, on the Windows machine:

```bash
rclone authorize "onedrive"        # opens browser; sign in once
# copy the pasted {token JSON} block to this machine, then:
rclone config create onedrive onedrive token '<json>'
rclone about onedrive:
```

Once the remote exists, `cloud_backup.sh` automatically includes OneDrive in every target list (see `targets()`).

Evidence: `onedrive_auth_shots/` — per-step screenshots + HTML dumps for v1→v6, including the final rate-limit wall (`*_v6_wall_5.png`).

## Recording (audit trail — "recording it for global use")

- **Backup ledger:** `~/tools/task_system/backup_ledger.jsonl` — one JSON line per artifact per run (ts, machine, label, src, targets, status)
- **Storage registry:** `storage_nodes.csv` (this folder)
- **Onboarding evidence:** `onedrive_auth_shots/*.png|*.html`, `onedrive_auth*.log`
- **Task ledgers:** `~/tools/task_system/completed_tasks.jsonl`, `queued_tasks.jsonl`
- All of the above ride in the `critical`/`daily` backup sets → they exist locally, in GCS, in OneDrive (once configured), and in the Windows user folder (queued mirror)

## Security rules

- Credentials live ONLY in: `~/.env`, `~/.config/onedrive/credentials.json`, `~/.config/onedrive/rclone_token.json` (when minted), `~/.config/gcloud/application_default_credentials.json`, `~/.config/rclone/rclone.conf` (all 600) — snapshots in `~/Amd949609_keys/` (600).
- **Never** commit credential files to GitHub — tools and docs only.
- Private cloud spaces only (own buckets / own OneDrive).

## Restore

```bash
rclone copy gcs:backup-project-743aab84-f9a5-4ec7-954/osintneoai_azure_vm/<machine>/<stamp>/<label> <destination> --progress
```

## Troubleshooting

- **`401 Invalid Credentials` on `gcs`** — the stored OAuth access token is stale while its stored expiry is in the future (rclone then skips auto-refresh). `cloud_backup.sh` now self-heals: it normalizes the token expiry to the past, which forces rclone to exchange the stored `refresh_token` for a fresh access token and persist a correct expiry. Manual equivalent:
  ```bash
  rclone lsd gcs: --max-depth 1     # after setting expiry to the past, this triggers + persists the refresh
  ```
- **rclone `config update` hangs** — pass `--non-interactive` (it can otherwise wait on stdin).

## Global use

1. Copy `cloud_backup.sh` + `storage_nodes.csv` + this README to any machine.
2. Provide that machine's own credentials: rclone remote `gcs` (Google ADC OAuth) and/or `onedrive`.
3. To add **OneDrive** on any machine — run `rclone authorize "onedrive"` locally (real browser + real network), then `rclone config create onedrive onedrive token '<json>'`. `cloud_backup.sh targets` will pick it up automatically.
4. Run the same commands — every run is ledger-recorded; every stamp is immutable.
