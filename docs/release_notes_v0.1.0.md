## 🎮 PZ SaveSync v0.1.0 — Initial release

Premier release public de **PZ SaveSync**, l'outil pour partager les sauvegardes Project Zomboid entre potes via Dropbox/Drive/OneDrive — sans serveur dédié, sans abonnement.

### 📥 Installation rapide (non-devs)

Télécharge **`PZSaveSync.exe`** ci-dessous, double-clique, et c'est parti.
Aucune installation Python requise, aucune dépendance externe.

> ℹ️ Windows SmartScreen peut afficher un avertissement « éditeur inconnu » au premier lancement (l'exe n'est pas signé). Clique sur **« Informations complémentaires » → « Exécuter quand même »**.

### ✨ Features

- 🔍 **Détection auto** des saves multi locales (`Zomboid\Saves\Multiplayer\`)
- 📊 **Inspection** : chunks explorés, structures construites, joueurs présents en DB
- 📦 **Bundle `.zip`** auto-suffisant : monde + DB persos + config serveur (`.ini`, sandbox, spawnregions)
- ☁ **Mode cloud** : push/pull versionné via un dossier partagé Dropbox/Drive/OneDrive
- ✉ **Mode manuel** : export/import `.zip` pour Gmail / WeTransfer / Discord / USB
- 🔒 **Verrou de tour** (`lock.json`) pour éviter les push concurrents
- 💾 **Backup auto** avant chaque pull/import dans `~/PZSaveSync_LocalBackups/`
- 🛠 **Build `.exe` autonome** intégré (PyInstaller)
- ↔ **Diff** entre save locale et dernière version remote

### 🏠 Gestion du changement d'hôte

L'app fait un **transfert bit-perfect** des fichiers nécessaires. Les persos sont indexés par SteamID dans la DB SQLite, donc personne ne perd son perso quand un pote prend le relais comme hôte. Détails dans le [README](https://github.com/Mistercarmi/PZSaveSync#-comment-ça-gère-le-changement-dhôte).

### 🔐 Sécurité

- Validation stricte des bundles à l'import (champs obligatoires, nom de save sain)
- Protection anti zip-slip / path-traversal
- Écriture atomique (`tmp` + `rename`) — pas de bundle corrompu en cas de crash
- Tests : voir `tests/test_security.py`

### 🧪 Build & tests

- GUI : customtkinter 5.2 (dark mode)
- Stdlib : `zipfile`, `pathlib`, `json`, `sqlite3`
- Tests round-trip + sécurité : ✅
- Python 3.11+, Windows 10/11 (Linux/Mac non testé)

### 📜 Licence

Source Available — Tous droits réservés. Voir [LICENSE](https://github.com/Mistercarmi/PZSaveSync/blob/main/LICENSE).
