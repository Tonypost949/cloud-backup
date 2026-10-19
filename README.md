# ☁️ Cloud Backup — Directions (Space & Backup & Recording, for global use)

_Stack: amd949609@gmail.com / Tonypost949 · Created 2026-10-19 by OpenCode agent (DeepSeek V4.1 Flash Free) · Law 15 dynamic tiering + Law 14 backup discipline_

## What this is

The command-and-control folder for backing up everything on this VM — and by copy, on any machine — to the user's cloud spaces:

| Node | Real address | Status |
|------|--------------|--------|
| **Google (GCS)** | `gs://backup-project-743aab84-f9a5-4ec7-954` (bucket established 2026-06-16, already holds `bq_backup/`) | ✅ ACTIVE |
| **Microsoft (OneDrive 1 TB)** | account `amd949609@gmail.com` via rclone remote `onedrive` | ⏳ onboarding |
| **GitHub** | `https://github.com/Tonypost949/OsintNeoAi.git`, `https://github.com/Tonypost949/ailaws` | ✅ ACTIVE |
| **Azure DevOps** | `https://dev.azure.com/anthonydimarcello/osintneoai/_git/osintneoai` | ⏳ queued |
| **Windows user folder** | `C:\Amd949609_Antigravity_v1\` (+ `cloud_storage\gdrive_backup`, OneDrive sync) | user machine |

Full node registry: `storage_nodes.csv` (Label is primary column). Credential locations: `~/Amd949609_keys/CREDENTIALS_INDEX.md`.

## Files here

| File | Purpose |
|------|---------|
| `cloud_backup.sh` | Executor — pushes sets to ALL configured targets; appends backup ledger |
| `storage_nodes.csv` | Registry of every storage node |
| `onedrive_auth.py` | Automated OneDrive OAuth onboarding (Playwright browser automation; account creds in `~/.config/onedrive`) |
| `README.md` | This directions file |
| `manifests/`, `onedrive_auth_shots/`, `onedrive_auth.log` | Evidence + logs |

## Commands

```bash
~/tools/cloud_backup/cloud_backup.sh push critical   # laws, task system, keys, auth configs
~/tools/cloud_backup/cloud_backup.sh push daily      # lightweight daily set
~/tools/cloud_backup/cloud_backup.sh push tools      # all tool packages
~/tools/cloud_backup/cloud_backup.sh push mirrors    # GitHub mirror tree (~5.7 GB)
~/tools/cloud_backup/cloud_backup.sh push all
~/tools/cloud_backup/cloud_backup.sh verify critical
~/tools/cloud_backup/cloud_backup.sh targets
```

Every push lands under `<remote>:<root>/<machine>/<UTC-stamp>/<label>/` — fully versioned by timestamp; nothing is ever overwritten.

## Recording (audit trail — "recording it for global use")

- **Backup ledger:** `~/tools/task_system/backup_ledger.jsonl` — one JSON line per artifact per run (ts, machine, label, src, targets, status)
- **Storage registry:** `storage_nodes.csv` (this folder)
- **Onboarding evidence:** `onedrive_auth_shots/*.png`, `onedrive_auth.log`
- All of the above ride in the `critical`/`daily` backup sets → they exist locally, in GCS, in OneDrive, and in the Windows user folder (queued mirror)

## Security rules

- Credentials live ONLY in: `~/.env`, `~/.config/onedrive/credentials.json`, `~/.config/onedrive/rclone_token.json`, `~/.config/gcloud/application_default_credentials.json`, `~/.config/rclone/rclone.conf` (all 600) — snapshots in `~/Amd949609_keys/` (600).
- **Never** commit credential files to GitHub — tools and docs only.
- Private cloud spaces only (own buckets / own OneDrive).

## Restore

```bash
rclone copy gcs:backup-project-743aab84-f9a5-4ec7-954/osintneoai_azure_vm/<machine>/<stamp>/<label> <destination> --progress
```

## Global use

1. Copy `cloud_backup.sh` + `storage_nodes.csv` + this README to any machine.
2. Provide that machine's own credentials: rclone remote `gcs` (Google ADC OAuth) and/or `onedrive` (device/account OAuth).
3. Run the same commands — every run is ledger-recorded; every stamp is immutable.
