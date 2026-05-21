<div align="center">

# 🎮 PZ SaveSync

**Partage tes sauvegardes Project Zomboid entre potes — sans serveur dédié, sans abonnement.**

Juste un dossier Dropbox/Drive/OneDrive que vous avez déjà.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078d4?logo=windows&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-customtkinter-1f6f43)
![License](https://img.shields.io/badge/License-Source%20Available-orange)
![Build PZ](https://img.shields.io/badge/Project%20Zomboid-B41%20%2F%20B42-d65a5a)

</div>

> **N'importe qui du groupe peut héberger la prochaine session, même si l'hôte
> habituel n'est pas là.** Un système de "tour" évite que vous écrasiez la
> save l'un de l'autre.

---

## 📑 Sommaire

- [Pourquoi cet outil existe](#-pourquoi-cet-outil-existe)
- [Aperçu](#-aperçu)
- [Comparé aux alternatives](#-comparé-aux-alternatives)
- [Fonctionnement](#-fonctionnement)
- [Comment ça gère le changement d'hôte](#-comment-ça-gère-le-changement-dhôte)
- [Fichiers gérés](#-fichiers-gérés)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Stack technique](#-stack-technique)
- [FAQ](#-faq)
- [Structure du code](#-structure-du-code)
- [Roadmap](#-roadmap)
- [Contribuer](#-contribuer)
- [Licence](#-licence)

---

## 🧟 Pourquoi cet outil existe

Tu joues à PZ en multi avec des potes. L'hôte habituel est en vacances. Ta
session se termine, tu veux que ton pote prenne le relais demain. Aujourd'hui
tu dois :

- Zipper à la main `Zomboid\Saves\Multiplayer\<server>\` + `Zomboid\db\<server>.db`
  + `Zomboid\Server\<server>.ini` + `_SandboxVars.lua` + `_spawnregions.lua`
- L'envoyer par WeTransfer ou Drive
- Espérer que ton pote ne se trompe pas en le rangeant chez lui
- Croiser les doigts pour qu'aucun de vous deux n'écrase l'autre

**PZ SaveSync automatise tout ça :**

1. 🔍 **Inspecte** ta save (chunks explorés, structures, joueurs en DB)
2. 📦 **Bundle** TOUT ce qu'il faut dans un seul `.zip` (avec un manifest)
3. ☁ **Pousse** dans un dossier partagé Dropbox/Drive/OneDrive — ou exporte en
   `.zip` à envoyer manuellement (Gmail, WeTransfer, Discord, USB)
4. 🔒 Pose un **verrou** ("c'est mon tour") pour empêcher les conflits
5. 💾 **Backup auto** avant chaque restore, au cas où

### ✨ Nouveautés v0.2

- 🛡 **Détecte que PZ tourne** et bloque les opérations destructives
- ⚠ **Te prévient si ta save est en retard** sur le cloud (évite d'écraser la session d'un pote)
- 🧩 **Vérifie les mods installés** vs requis après import — liste les manquants avec lien Workshop
- 🔍 **Auto-détection** des dossiers Dropbox / Drive / OneDrive sur ton PC
- 🔐 **Hash SHA256** dans le manifest — corruption de bundle détectée
- 📊 **Barre de progression** pour les gros bundles
- 🎯 **Wizard 3 étapes** au premier lancement
- 💬 **Webhook Discord** pour notifier le canal à chaque push
- 🧹 **Nettoyage de l'historique** (garde N dernières versions)
- 🔓 **Auto-release du tour** après push (option)
- 🎬 **Push auto à la fermeture de PZ** (option)

---

## 🖥 Aperçu

### Onglet « Partager » — le hub principal

![Onglet Partager](docs/screenshots/01_partager.png)

Tout ce que tu fais 90 % du temps est ici : prendre le tour, récupérer la save
de ton pote, envoyer la tienne. Les 4 gros boutons d'action gèrent les deux
modes (cloud partagé ou fichier `.zip` envoyé à la main).

### Onglet « Mes parties » — toutes tes saves locales

![Onglet Mes parties](docs/screenshots/02_mes_parties.png)

L'app scanne `%USERPROFILE%\Zomboid\Saves\Multiplayer\` et te montre tout ce
qui est transférable : chunks explorés, joueurs présents en DB, mods détectés,
fichiers compagnons (DB, .ini, sandbox, spawn).

### Onglet « Réglages » — minimaliste

![Onglet Réglages](docs/screenshots/03_reglages.png)

Deux champs à remplir une seule fois : ton pseudo, et le chemin du dossier
partagé. Plus un bouton « Build .exe » pour générer un exécutable autonome à
filer à tes potes non-devs.

---

## ⚔ Comparé aux alternatives

| | **PZ SaveSync** | [PZ-Server-Save-Manager](https://github.com/pabloherresp/PZ-Server-Save-Manager) | [SaveSync (Steam)](https://store.steampowered.com/app/3832010/SaveSync_Coop_Save_Sharing_Made_Easy/) |
|---|---|---|---|
| Prix | **Gratuit, open-source** | Gratuit (GPL-3) | 5,89 € |
| Backend | Ton Dropbox/Drive/OneDrive (déjà payé) | Local seulement | Steam Workshop (propriétaire) |
| GUI moderne | ✅ (customtkinter) | ❌ (script Batch) | ✅ |
| Anti-conflit (tour/lock) | ✅ | ❌ | non documenté |
| Mode `.zip` manuel | ✅ (mail / Discord / USB) | ✅ | ❌ |
| Inspection bundle (chunks, joueurs, diff) | ✅ | ❌ | ❌ |
| Génère un `.exe` autonome | ✅ (PyInstaller intégré) | n/a | n/a |
| Multi-jeux | ❌ (PZ uniquement) | ❌ (PZ) | ✅ (30+ jeux) |

> 💡 **Quand utiliser SaveSync (commercial) plutôt :** si tu joues aussi à
> Stardew / Valheim / Satisfactory et que tu veux un seul outil polyvalent payant.
>
> 💡 **Quand utiliser PZ SaveSync :** si tu veux gratuit + open-source + ton
> propre cloud + le mécanisme de tour pour ton groupe PZ.

---

## 🔄 Fonctionnement

### Workflow type (cloud)

```
Pote A finit sa session  →  🔒 Prend le tour
                         →  ⬆ Push (dépose le bundle dans le Drive partagé)
                         →  🔓 Libère le tour
                              ↓
                         (le Drive synchronise tout seul)
                              ↓
Pote B veut héberger     →  ⬇ Pull (récupère le dernier bundle)
                         →  Joue
                         →  🔒 Prend le tour, ⬆ Push, 🔓 Libère
```

### Workflow type (manuel `.zip`)

```
Pote A  →  📤 Exporte ma partie → .zip → envoie par Gmail / WeTransfer / Discord
Pote B  →  📥 Importe le .zip reçu → tout est rangé au bon endroit
```

### Anti-conflit

Un fichier `lock.json` dans le dossier partagé indique qui détient le tour.
Tant qu'il n'est pas libéré, l'app prévient les autres joueurs s'ils tentent
de push. (Override manuel possible si quelqu'un a oublié de libérer.)

---

## 🏠 Comment ça gère le changement d'hôte

C'est LA question critique en multi-coop PZ. La réponse courte :
**l'app ne "change" pas l'hôte explicitement, elle fait un transfert
bit-perfect — et c'est exactement ce qu'il faut**, parce que PZ a été conçu
pour que la save soit portable.

### Ce que l'app fait

Elle zippe **exactement 4 catégories de fichiers**, sans rien modifier :

| Fichier | Rôle au moment du transfert |
|---|---|
| `Saves/Multiplayer/<save>/` | Le monde : map, chunks, structures, items |
| `db/<save>.db` | DB SQLite avec **tous les persos de tous les joueurs** |
| `Server/<save>.ini` | Mods + admin password + port |
| `Server/<save>_SandboxVars.lua` + `_spawnregions.lua` | Réglages monde |

À l'import, tout est extrait **au même chemin** et **avec le même nom de
save** chez ton pote. Aucun byte n'est modifié — juste un `extractall`
sécurisé (anti zip-slip, écriture atomique, validation du manifest).

### Pourquoi ça ne casse rien (le truc important)

PZ stocke les persos dans `<save>.db` **indexés par SteamID du joueur**, pas
par "qui héberge". Conséquence :

- Quand ton pote B importe la save de A et lance **Host** → PZ démarre le
  serveur, B se connecte (son SteamID retrouve son perso dans la DB), A se
  connecte aussi (son SteamID retrouve le sien). **Personne ne perd son perso.**
- L'IP du serveur change forcément (c'est B maintenant) → les joueurs joignent
  via l'IP de B au lieu de celle de A. Géré par le menu **Join** côté
  joueurs, pas par la save.
- Le port est dans le `.ini` → reste le même.

### Les vrais points d'attention

| Point | Solution PZ SaveSync |
|---|---|
| **Les mods** — si A avait mod X et que B ne l'a pas, le serveur ne démarre pas. | L'app **affiche la liste des mods + les liens Steam Workshop à l'import**, pour que B s'abonne avant de lancer. |
| **Admin password** — qui est admin chez le nouvel hôte ? | Reste dans le `.ini` partagé — donc B hérite du admin pwd de A. Cohérent : on partage entre potes de confiance. |
| **Whitelist** — B est-il autorisé à rejoindre ? | Déjà dans la DB. B est forcément accepté car il est l'hôte. |
| **Conflits si B avait déjà une save du même nom** | **Backup auto** avant écrasement dans `~/PZSaveSync_LocalBackups/` (un zip horodaté). |

### Ce que l'app NE fait PAS (et n'a pas besoin de faire)

- ❌ Réécrire le SteamID dans la save → inutile, PZ utilise des SteamID multiples
- ❌ Modifier l'IP ou le port → l'IP n'est pas dans les fichiers, le port est OK tel quel
- ❌ "Transférer la propriété" → ce concept n'existe pas dans PZ multi-coop

### Limite honnête

Le seul cas où ça pourrait casser : un mod qui stocke des chemins **absolus**
spécifiques au PC d'origine (genre `C:\Users\Alice\...`). Rare, mais
théoriquement possible. PZ vanilla n'a pas ce problème.

---

## 📁 Fichiers gérés

Tout ce que PZ SaveSync packe pour une partie nommée `MaPartie` :

| Fichier / dossier | Rôle | Si manquant... |
|---|---|---|
| `Zomboid\Saves\Multiplayer\MaPartie\` | Le monde (map, chunks, structures, véhicules) | Pas de transfert possible |
| `Zomboid\db\MaPartie.db` | DB SQLite des **persos** | Vous repartez à poil |
| `Zomboid\Server\MaPartie.ini` | Config serveur + **liste des mods** | Ton pote ne pourra pas rejoindre avec les mêmes mods |
| `Zomboid\Server\MaPartie_SandboxVars.lua` | Réglages (zombies, vitesse...) | Réglages par défaut |
| `Zomboid\Server\MaPartie_spawnregions.lua` | Zones de spawn perso | Zones par défaut |

Les 3 fichiers du dossier `Server\` doivent **avoir exactement le même nom
de base** que le dossier de save — c'est le contrat PZ. PZ SaveSync renomme
automatiquement si besoin à l'import.

---

## 📥 Installation

### Depuis les sources (Python)

```powershell
git clone https://github.com/Mistercarmi/PZSaveSync
cd PZSaveSync
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pzsavesync
```

Ou plus simple sous Windows : lance `run.bat` (le script installe Python
3.11+ tout seul si absent, crée le venv, installe les deps, lance l'app).

### Depuis un `.exe` (recommandé pour tes potes non-devs)

Lance l'app, va dans **Réglages → 🛠 Build .exe**. Un `.exe` autonome est
généré dans `dist/PZSaveSync.exe` que tu peux filer à tes potes — pas
besoin d'installer Python chez eux.

---

## ⚙ Configuration

1. **Lance l'app** (`python -m pzsavesync`, `run.bat`, ou le `.exe`)
2. Onglet **⚙ Réglages** :
   - Renseigne ton **pseudo** (sert à signer les bundles et le verrou)
   - Renseigne le **dossier partagé** (chemin local synchronisé par Dropbox/Drive/OneDrive)
3. Onglet **🎮 Mes parties** : sélectionne ta save et clique **⭐ Définir
   comme partie active**
4. Onglet **🔄 Partager** : tout est là — Pull, Push, Import, Export

### Mettre en place un dossier partagé

1. Crée un dossier sur Drive / Dropbox / OneDrive, ex. `PZ_avec_pote`
2. Partage-le avec ton pote (droits **écriture**)
3. Active la synchro **« miroir » / « disponible hors ligne »** pour avoir
   un chemin local sur ton disque
4. Toi et ton pote pointez chacun ce chemin local dans Réglages

---

## 🧩 Stack technique

- **Python 3.11+**
- **customtkinter** ≥ 5.2 (GUI dark mode)
- `zipfile` / `pathlib` / `json` / `sqlite3` (stdlib uniquement)
- **PyInstaller** (optionnel, pour le build `.exe`)
- **Pillow** (optionnel, pour `scripts/make_screenshots.py`)

Tout le reste est en stdlib pour minimiser les dépendances.

---

## ❓ FAQ

**Est-ce que ça marche avec Build 41 ET Build 42 ?**
Oui, les chemins `Zomboid\Saves\Multiplayer\` et `Zomboid\Server\` n'ont pas
changé. Si tu joues en B42 unstable et que tu rencontres un cas non géré,
ouvre une issue.

**Et si on push tous les deux en même temps ?**
Le verrou (`lock.json`) sert exactement à ça. Avant de push, prends le tour.
Si l'autre joueur a le tour et tente de push, l'app le prévient. (Tu peux
forcer une libération si l'autre a oublié.)

**Les mods sont-ils inclus ?**
Le `.ini` contient la **liste** des mods (`Mods=` et `WorkshopItems=`). Ton
pote doit toujours les avoir installés via Steam Workshop, mais l'app
garantit qu'il joue avec la même liste que toi — et lui affiche les liens
Workshop à l'import pour qu'il s'abonne rapidement.

**Mon pote perd-il son perso quand il devient hôte ?**
Non. PZ stocke les persos dans la DB SQLite, indexés par SteamID. Voir la
[section dédiée](#-comment-ça-gère-le-changement-dhôte).

**Ça fonctionne sur Linux/Mac ?**
Pas testé. Le code utilise `%USERPROFILE%\Zomboid` (chemin Windows). Une PR
pour gérer `~/Zomboid` est la bienvenue.

**Si je perds le dossier partagé, je perds tout ?**
Non. À chaque import / pull, un backup auto est créé dans
`~/PZSaveSync_LocalBackups/`. Et ton Drive/Dropbox a ses propres versions
historiques.

**Est-ce sécurisé ?** L'app valide chaque bundle avant extraction (champs
obligatoires, nom de save sain, protection contre zip-slip / path traversal).
Voir [`tests/test_security.py`](tests/test_security.py).

---

## 🗂 Structure du code

```
src/pzsavesync/
  __main__.py          # entry point (python -m pzsavesync)
  gui.py               # interface customtkinter (3 onglets)
  onboarding.py        # wizard 3 étapes au premier lancement
  progress_dialog.py   # dialog modal de progression
  saves.py             # détection des saves locales
  inspector.py         # lecture des chunks / DB / structures
  bundle.py            # création / extraction des .zip + manifest + SHA256
  sync.py              # SharedRepo : lock + versions + prune
  config.py            # %APPDATA%\PZSaveSync\config.json
  builder.py           # build .exe via PyInstaller
  pz_detector.py       # détecte si Project Zomboid tourne
  mods_check.py        # vérifie les mods installés vs requis
  cloud_detect.py      # auto-détection Dropbox/Drive/OneDrive/...
  discord_webhook.py   # notifications Discord (stdlib pure)
  tooltip.py           # info-bulles

tests/
  test_roundtrip.py   # cycle bundle → import → re-bundle bit-perfect
  test_security.py    # zip-slip, validation manifest, parsing mods

scripts/
  make_screenshots.py # génération des screenshots avec données factices
```

---

## 🛣 Roadmap

- [ ] Support Linux/Mac (chemin `~/Zomboid`)
- [ ] Notifications quand le tour est libéré côté pote (polling Drive)
- [ ] Mode "diff visuel" : voir sur la map ce qui a changé entre 2 versions
- [ ] Compression delta entre versions (au lieu de re-zipper tout le monde)
- [ ] Détection des conflits de mods entre deux PCs

---

## 🤝 Contribuer

Les PRs sont les bienvenues. Pour les changements importants, ouvre une
issue d'abord pour qu'on en discute.

```powershell
# Setup dev
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Tests
python tests/test_roundtrip.py
python tests/test_security.py

# Regénérer les screenshots (données 100% factices)
pip install Pillow
python scripts/make_screenshots.py
```

---

## 📜 Licence

**Source Available — Tous droits réservés.** Voir [LICENSE](LICENSE).

Le code source est rendu public à titre de lecture et d'apprentissage
uniquement. Tu peux le faire tourner en local pour ton usage personnel,
mais tu ne peux pas le copier, le modifier, le redistribuer ni l'intégrer
dans un autre projet.

---

## 🙏 Crédits

- Outil basé sur l'observation de la structure de save documentée par la
  communauté PZ ([PZwiki Multiplayer FAQ](https://pzwiki.net/wiki/Multiplayer_FAQ),
  [Indifferent Broccoli — Upload a Save](https://wiki.indifferentbroccoli.com/ProjectZomboid/UploadASave))
- Inspiré par [PZ-Server-Save-Manager](https://github.com/pabloherresp/PZ-Server-Save-Manager)
  (script Batch, sans GUI ni lock)

---

<div align="center">

*Made for the long nights of looting Muldraugh with your friends. 🌙*

</div>
