<div align="center">

# 🎮 PZ SaveSync

# 💯 100% FREE · 🔍 SOURCE VISIBLE · 🚫 NO SUBSCRIPTION

**Share your Project Zomboid saves with friends — no dedicated server, no hidden fees, no sign-up.**

Just a Dropbox/Drive/OneDrive folder you already have.

[🇫🇷 Français](README.md) · **🇬🇧 English**

![Free](https://img.shields.io/badge/Price-Free-2ecc71?style=for-the-badge)
![Source Visible](https://img.shields.io/badge/Source-Visible-3498db?style=for-the-badge)
![No Account](https://img.shields.io/badge/Account-None%20required-9b59b6?style=for-the-badge)

![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078d4)
![GUI](https://img.shields.io/badge/GUI-customtkinter-1f6f43)
![License](https://img.shields.io/badge/License-Source%20Available-orange)
![PZ Build](https://img.shields.io/badge/Project%20Zomboid-B41%20%2F%20B42-d65a5a)
![CI](https://github.com/Mistercarmi/PZSaveSync/actions/workflows/tests.yml/badge.svg)

</div>

> 💸 **No paywall, no in-app purchase, no ads.** Source code is public on GitHub
> and auditable — you can read it, build it yourself, and use it indefinitely.
> See [License](#-license) for details (personal use allowed, redistribution reserved to the author).

---

## 🎯 In 30 seconds: what does this tool actually do?

You're playing PZ co-op with friends. Only one person hosts at a time, and you need to pass the save around when the host changes. This tool does **exactly two things**:

<table width="100%">
<tr>
<td width="50%" valign="top">

### 📥 « I want to **grab** my friend's save to play »

Your friend ended their session and uploaded the save. You want to grab it and host next.

→ Tab **🔄 Share** → button **⬇ Pull save**

The app downloads the latest version, backs up your current state just in case, and tells you "launch PZ → Multiplayer → Host". **That's it.**

</td>
<td width="50%" valign="top">

### 📤 « I want to **hand off** my save to my friends »

You're done playing. You want your friends to be able to keep the game running with the up-to-date save.

→ Tab **🔄 Share** → button **⬆ Push my session**

The app bundles your world + player DB + server config, drops it in the shared folder, and your friend just clicks **Pull save** on their end. **That's it.**

</td>
</tr>
</table>

> 🆕 **First time?** [3-step setup ↓](#-installation) (nickname, shared Dropbox/Drive/OneDrive folder, active save)

> 🔒 **What if both of us push at the same time?** The app sets a **turn lock**: only one person can push at a time. Nobody overwrites the other's save by accident. ([details](#-how-it-works))

> 💾 **What if I mess up?** Before every pull, an **auto-backup** of your current state is created. You can restore it in 1 click via **Tools → ↩ Restore a backup**. ([new in v0.3.4](CHANGELOG.md))

---

## 🧠 What does "send the save" actually mean technically?

PZ needs 5 things for one of your friends to be able to play as if they were the host:

1. **The world** — explored chunks, built structures, dropped items (`Zomboid\Saves\Multiplayer\<save>\`)
2. **The player DB** — each player is linked by SteamID, so your friend finds THEIR character and you find YOURS, even when the host changes (`Zomboid\db\<save>.db`)
3. **Server config** — mods, admin password, PVP on/off, port (`Zomboid\Server\<save>.ini`)
4. **Sandbox settings** — zombie density, speed, loot... (`<save>_SandboxVars.lua`)
5. **Spawn regions** — where new players appear (`<save>_spawnregions.lua`, + `_spawnpoints.lua` if custom)

PZ SaveSync collects **all 5 together**, packs them into a signed `.zip` (SHA256), and guarantees your friend gets them **bit-for-bit identical** on their end. You don't have to zip, copy, or rename **anything** by hand.

---

## 📑 Table of contents

- [Why this tool exists](#-why-this-tool-exists)
- [Screenshots](#-screenshots)
- [Compared to alternatives](#-compared-to-alternatives)
- [How it works](#-how-it-works)
- [How it handles the host change](#-how-it-handles-the-host-change)
- [Files managed](#-files-managed)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Tech stack](#-tech-stack)
- [FAQ](#-faq)
- [Code structure](#-code-structure)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🧟 Why this tool exists

Without this tool, to pass the save between friends you have to:

- Zip by hand all 5 files/folders, without forgetting any
- Send via WeTransfer / Drive
- Hope your friend doesn't misplace it
- Cross your fingers that neither of you overwrites the other
- Repeat this dance every time the host changes

**PZ SaveSync replaces all that with 2 buttons**: `⬆ Push` on your end, `⬇ Pull` on your friend's end. The rest (lock, backup, SHA256 integrity check, server-file renaming if needed) is automatic.

### ✨ What's new in v0.3

- 🤖 **CI/CD on GitHub Actions** — tests on every push, auto-build the .exe on every tag
- 🆕 **Auto-update check** at startup — banner when a new release is available
- 🪟 **Drag-and-drop a .zip** onto the window to import it
- 👥 **Multi-group profiles** — switch between groups of friends from the header
- 📝 **Persistent logs** in `%APPDATA%/PZSaveSync/logs/` for easy bug reports
- 🔔 **Native OS notifications** (Toast Windows / notify-send / osascript)
- 🛡 **Zip-bomb protection** at extraction (size + file count limits)
- ✅ **Numeric validation of Workshop IDs** (anti-injection)
- 🧹 **Auto-recovery** of orphan `.tmp` files at startup
- 🐧 **Linux/macOS support** (with `$PZ_ZOMBOID_ROOT` override)

### Earlier versions ([CHANGELOG](CHANGELOG.md))

**v0.2** — process detection (blocks operations when PZ is running), "save is
behind" banner, mod verification vs installed, cloud folder auto-detection,
SHA256 hash, history cleanup, Discord webhook, onboarding wizard, progress bar.

**v0.1** — initial release with cloud + manual `.zip` modes, turn lock,
auto-backup, integrated PyInstaller build.

---

## 🖥 Screenshots

### "Share" tab — the main hub

![Share tab](docs/screenshots/01_partager.png)

Everything you do 90% of the time is here: take the turn, pull your friend's
save, push yours. The 4 big action buttons handle both modes (shared cloud or
`.zip` sent manually).

### "My saves" tab — all your local saves

![My saves tab](docs/screenshots/02_mes_parties.png)

The app scans `%USERPROFILE%\Zomboid\Saves\Multiplayer\` and shows everything
transferable: explored chunks, players in DB, detected mods, companion files
(DB, .ini, sandbox, spawn).

### "Settings" tab — minimalist

![Settings tab](docs/screenshots/03_reglages.png)

Two fields to fill once: your username and the shared folder path. Plus a
"Build .exe" button to generate a standalone executable to give to your
non-dev friends.

---

## ⚔ Compared to alternatives

| | **PZ SaveSync** | [PZ-Server-Save-Manager](https://github.com/pabloherresp/PZ-Server-Save-Manager) | [SaveSync (Steam)](https://store.steampowered.com/app/3832010/SaveSync_Coop_Save_Sharing_Made_Easy/) |
|---|---|---|---|
| Price | **Free (source visible)** | Free (GPL-3, open-source) | $6 |
| Backend | Your Dropbox/Drive/OneDrive | Local only | Steam Workshop (proprietary) |
| Modern GUI | ✅ (customtkinter) | ❌ (Batch script) | ✅ |
| Anti-conflict (lock/turn) | ✅ | ❌ | not documented |
| Manual `.zip` mode | ✅ (mail / Discord / USB) | ✅ | ❌ |
| Bundle inspection (chunks, players, diff) | ✅ | ❌ | ❌ |
| Generates standalone `.exe` | ✅ (PyInstaller integrated) | n/a | n/a |
| Multi-game | ❌ (PZ only) | ❌ (PZ) | ✅ (30+ games) |

---

## 🔄 How it works

### Cloud workflow

```
Friend A finishes session  →  🔒 Take the turn
                           →  ⬆ Push (drop the bundle in the shared Drive)
                           →  🔓 Release the turn
                                ↓
                           (Drive syncs by itself)
                                ↓
Friend B wants to host      →  ⬇ Pull (fetch the latest bundle)
                           →  Play
                           →  🔒 Take, ⬆ Push, 🔓 Release
```

### Manual `.zip` workflow

```
Friend A  →  📤 Export my game → .zip → send via Gmail / WeTransfer / Discord
Friend B  →  📥 Import the received .zip → everything stored at the right place
```

### Anti-conflict

A `lock.json` file in the shared folder indicates who holds the turn. As long
as it's not released, the app warns the other player if they try to push.
(Manual override available if someone forgot to release.)

---

## 🏠 How it handles the host change

That's THE critical question in PZ multi-coop. The short answer: **the app
doesn't "change" the host explicitly — it does a bit-perfect transfer**,
which is exactly the right thing, because PZ was designed for portable saves.

### What the app does

It zips **exactly 4 categories of files**, without modifying anything:

| File | Role when transferring |
|---|---|
| `Saves/Multiplayer/<save>/` | The world: map, chunks, structures, items |
| `db/<save>.db` | SQLite DB with **all characters of all players** |
| `Server/<save>.ini` | Mods + admin password + port |
| `Server/<save>_SandboxVars.lua` + `_spawnregions.lua` | World settings |

On import, everything is extracted **at the same path** with **the same save
name** on your friend's machine. No byte is modified — it's just a safe
`extractall` (anti zip-slip, atomic writes, manifest validation, SHA256
integrity check).

### Why nothing breaks (the important part)

PZ stores characters in `<save>.db` **indexed by player SteamID**, not by
"who hosts". As a result:

- When friend B imports A's save and launches **Host** → PZ starts the
  server, B connects (their SteamID finds their character in the DB), A also
  connects (their SteamID finds theirs). **Nobody loses their character.**
- The server IP changes (it's B now) → players connect via B's IP instead of
  A's. Handled by the **Join** menu on the player side, not the save.
- The port is in the `.ini` → stays the same.

### The real things to watch out for

| Issue | How PZ SaveSync handles it |
|---|---|
| **Mods** — if A had mod X and B doesn't, the server won't start. | The app **shows the mod list + Steam Workshop links on import**, so B can subscribe before launching. |
| **Admin password** — who is admin on the new host? | Stays in the shared `.ini` — so B inherits A's admin password. Consistent: we're sharing among trusted friends. |
| **Whitelist** — is B allowed to join? | Already in the DB. B is always accepted because they're the host. |
| **Conflict if B already had a save with the same name** | **Auto-backup** before overwrite in `~/PZSaveSync_LocalBackups/` (timestamped zip). |

### What the app does NOT do (and doesn't need to)

- ❌ Rewrite the SteamID in the save → useless, PZ uses multiple SteamIDs
- ❌ Modify the IP or port → IP isn't in the files, port works as-is
- ❌ "Transfer ownership" → this concept doesn't exist in PZ multi-coop

---

## 📥 Installation

### Easy mode (recommended for non-devs)

Download `PZSaveSync.exe` from the [latest release](https://github.com/Mistercarmi/PZSaveSync/releases/latest). Double-click. Done.

### From source (Python)

```powershell
git clone https://github.com/Mistercarmi/PZSaveSync
cd PZSaveSync
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pzsavesync
```

Or under Windows: just run `run.bat` (the script installs Python 3.11+ if
absent, creates the venv, installs deps, launches the app).

### Build your own `.exe`

Inside the app, go to **Settings → 🛠 Build .exe**. A standalone `.exe`
is generated in `dist/PZSaveSync.exe`.

---

## ⚙ Configuration

1. **Launch the app** — at first launch, the onboarding wizard guides you in
   3 steps (username, shared folder, recap).
2. The app auto-detects standard cloud folders (Dropbox, Drive, OneDrive).
3. Pick your save in the **🎮 My saves** tab and click **⭐ Set as active**.
4. Head to **🔄 Share** for Pull / Push / Import / Export.

### Multi-group profiles

The header has a profile selector. Click `＋` to create a new profile
(another group of friends, with their own shared folder). Each profile keeps
its own username, shared folder, active save, and Discord webhook.

---

## 🧩 Tech stack

- **Python 3.11+**
- **customtkinter** ≥ 5.2 (dark mode GUI)
- **tkinterdnd2** ≥ 0.4 (drag-and-drop)
- `zipfile` / `pathlib` / `json` / `sqlite3` / `urllib` / `hashlib` (stdlib only)
- **PyInstaller** (optional, for `.exe` build)
- **Pillow** (optional, for `scripts/make_screenshots.py`)
- **pytest** (optional, for the test suite)

---

## ❓ FAQ

**Does it work with Build 41 AND Build 42?**
Yes, the `Zomboid\Saves\Multiplayer\` and `Zomboid\Server\` paths haven't
changed. If you're on B42 unstable and hit an edge case, open an issue.

**What if we push at the same time?**
The lock (`lock.json`) exists exactly for this. Before pushing, take the
turn. If the other player has the turn and tries to push, the app warns
them. (You can force-release if the other forgot.)

**Are mods included?**
The `.ini` contains the **list** of mods (`Mods=` and `WorkshopItems=`).
Your friend still needs to install them via Steam Workshop, but the app
guarantees they play with the same list — and shows them Workshop links on
import to subscribe quickly.

**Does my friend lose their character when they become host?**
No. PZ stores characters in the SQLite DB, indexed by SteamID. See the
[dedicated section](#-how-it-handles-the-host-change).

**Linux/macOS support?**
PZ SaveSync runs on Linux/macOS, but Project Zomboid stores saves at
`~/Zomboid` instead of `%USERPROFILE%\Zomboid`. The app uses `~/Zomboid`
by default; you can override with the `PZ_ZOMBOID_ROOT` environment variable.

**Is it secure?** The app validates every bundle before extraction (required
fields, sanitized save name, anti zip-slip / path-traversal, SHA256 hash,
file count and size limits). See [`tests/test_security.py`](tests/test_security.py)
and [`tests/test_bundle_security.py`](tests/test_bundle_security.py).

---

## 🗂 Code structure

```
src/pzsavesync/
  __main__.py          # entry point
  gui.py               # customtkinter interface (3 tabs)
  onboarding.py        # 3-step wizard on first launch
  progress_dialog.py   # progress dialog for long operations
  saves.py             # detection of local saves
  inspector.py         # reading chunks / DB / structures
  bundle.py            # zip create/extract + manifest + SHA256
  sync.py              # SharedRepo: lock + versions + prune
  config.py            # multi-group profiles + global preferences
  builder.py           # .exe build via PyInstaller
  pz_detector.py       # detects if Project Zomboid is running
  mods_check.py        # checks installed vs required mods
  cloud_detect.py      # auto-detects Dropbox/Drive/OneDrive/...
  discord_webhook.py   # Discord notifications (stdlib only)
  notifications.py     # OS native toasts (Win/Mac/Linux)
  updater.py           # GitHub Releases update check
  logger.py            # persistent logs (rotated daily)
  tooltip.py           # tooltips

tests/
  conftest.py          # pytest fixtures
  test_roundtrip.py    # bundle → import → re-bundle cycle (integration)
  test_security.py     # zip-slip, validation manifest, parsing mods
  test_bundle_security.py  # size limits, hash, Workshop IDs validation
  test_config_migration.py # v0.2 → v0.3 migration
  test_sync_prune.py   # history cleanup + tmp recovery
  test_pz_detector.py  # process detection
  test_updater.py      # version parsing
  test_logger.py       # logger
  test_cloud_detect.py # cloud auto-detection
  test_discord_webhook.py # URL validation

.github/
  workflows/
    tests.yml          # CI: tests on every push/PR
    release.yml        # CI: auto-build the .exe + GitHub release on every v* tag
  ISSUE_TEMPLATE/
    bug_report.yml
    feature_request.yml
    config.yml

scripts/
  make_screenshots.py  # screenshot generation with 100% fake data
```

---

## 🛣 Roadmap

- [x] Linux/macOS support (paths)
- [x] CI/CD GitHub Actions
- [x] Auto-update check
- [x] Drag-and-drop import
- [x] Multi-group profiles
- [ ] Notifications when the turn is released (Drive polling)
- [ ] Visual "diff" mode: see on the map what changed between 2 versions
- [ ] Delta compression between versions (instead of re-zipping the whole world)
- [ ] Mod conflict detection between two PCs
- [ ] Windows tray icon (app lives in background)
- [ ] Demo GIF in README

---

## 🤝 Contributing

PRs are welcome. For major changes, open an issue first to discuss.

```powershell
# Dev setup
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pytest

# Tests
python tests/test_roundtrip.py
python tests/test_security.py
pytest tests/ -v

# Regenerate screenshots (100% fake data)
pip install Pillow
python scripts/make_screenshots.py
```

---

## 📜 License

**Source Available — All rights reserved.** See [LICENSE](LICENSE).

The source code is made public for reading and learning purposes only. You
can run it locally for personal use, but you cannot copy, modify,
redistribute, or integrate it into another project.

---

## 🙏 Credits

- Tool based on the save structure documented by the PZ community
  ([PZwiki Multiplayer FAQ](https://pzwiki.net/wiki/Multiplayer_FAQ),
  [Indifferent Broccoli — Upload a Save](https://wiki.indifferentbroccoli.com/ProjectZomboid/UploadASave))
- Inspired by [PZ-Server-Save-Manager](https://github.com/pabloherresp/PZ-Server-Save-Manager)
  (Batch script, no GUI nor lock)

---

<div align="center">

*Made for the long nights of looting Muldraugh with your friends. 🌙*

</div>
