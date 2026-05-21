# 🎮 PZ SaveSync

> Partage tes sauvegardes **Project Zomboid** entre potes sans serveur dédié,
> sans abonnement, sans Steam Workshop. Juste un dossier Dropbox/Drive/OneDrive
> que vous avez déjà.

**N'importe qui du groupe peut héberger la prochaine session, même si l'hôte
habituel n'est pas là.** Un système de "tour" évite que vous écrasiez la save
l'un de l'autre.

---

## Pourquoi cet outil existe

Tu joues à PZ en multi avec des potes. L'hôte habituel est en vacances. Ta
session se termine, tu veux que ton pote prenne le relais demain. Aujourd'hui
tu dois :

- Zipper à la main `Zomboid\Saves\Multiplayer\<server>\` + `Zomboid\db\<server>.db`
  + `Zomboid\Server\<server>.ini` + `_SandboxVars.lua` + `_spawnregions.lua`
- L'envoyer par WeTransfer ou Drive
- Espérer que ton pote ne se trompe pas en le rangeant chez lui
- Croiser les doigts pour qu'aucun de vous deux n'écrase l'autre

PZ SaveSync automatise tout ça :

1. **Inspecte** ta save (chunks explorés, structures, joueurs en DB)
2. **Bundle** TOUT ce qu'il faut dans un seul `.zip` (avec un manifest)
3. **Pousse** dans un dossier partagé Dropbox/Drive/OneDrive — ou exporte en `.zip`
   à envoyer manuellement (Gmail, WeTransfer, Discord, USB)
4. Pose un **verrou** ("c'est mon tour") pour empêcher les conflits
5. **Backup auto** avant chaque restore, au cas où

---

## Comparé aux alternatives

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

**Quand utiliser SaveSync (commercial) plutôt :** si tu joues aussi à Stardew /
Valheim / Satisfactory et que tu veux un seul outil polyvalent payant.

**Quand utiliser PZ SaveSync :** si tu veux gratuit + open-source + ton propre
cloud + le mécanisme de tour pour ton groupe PZ.

---

## Fonctionnement

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

Un fichier `lock.json` dans le dossier partagé indique qui détient le tour. Tant
qu'il n'est pas libéré, l'app prévient les autres joueurs s'ils tentent de push.
(Override manuel possible si quelqu'un a oublié de libérer.)

---

## Fichiers gérés

Tout ce que PZ SaveSync packe pour une partie nommée `MaPartie` :

| Fichier / dossier | Rôle | Si manquant... |
|---|---|---|
| `Zomboid\Saves\Multiplayer\MaPartie\` | Le monde (map, chunks, structures, véhicules) | Pas de transfert possible |
| `Zomboid\db\MaPartie.db` | DB SQLite des **persos** | Vous repartez à poil |
| `Zomboid\Server\MaPartie.ini` | Config serveur + **liste des mods** | Ton pote ne pourra pas rejoindre avec les mêmes mods |
| `Zomboid\Server\MaPartie_SandboxVars.lua` | Réglages (zombies, vitesse...) | Réglages par défaut |
| `Zomboid\Server\MaPartie_spawnregions.lua` | Zones de spawn perso | Zones par défaut |

Les 3 fichiers du dossier `Server\` doivent **avoir exactement le même nom de
base** que le dossier de save — c'est le contrat PZ. PZ SaveSync renomme
automatiquement si besoin à l'import.

---

## Installation

### Depuis les sources (Python)

```powershell
git clone https://github.com/<ton-user>/pz-savesync
cd pz-savesync
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pzsavesync
```

### Depuis un `.exe` (recommandé pour tes potes non-devs)

Lance l'app, va dans **Réglages → 🛠 Build .exe**. Un `.exe` autonome est
généré dans `dist/PZSaveSync.exe` que tu peux filer à tes potes — pas besoin
d'installer Python chez eux.

---

## Configuration

1. **Lance l'app** (`python -m pzsavesync` ou le `.exe`)
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

## Stack technique

- **Python 3.11+**
- **customtkinter** ≥ 5.2 (GUI dark mode)
- `zipfile` / `pathlib` / `json` / `sqlite3` (stdlib uniquement)
- **PyInstaller** (optionnel, pour le build `.exe`)

Tout le reste est en stdlib pour minimiser les dépendances.

---

## FAQ

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
garantit qu'il joue avec la même liste que toi.

**Ça fonctionne sur Linux/Mac ?**
Pas testé. Le code utilise `%USERPROFILE%\Zomboid` (chemin Windows). Une PR
pour gérer `~/Zomboid` est la bienvenue.

**Si je perds le dossier partagé, je perds tout ?**
Non. À chaque import / pull, un backup auto est créé dans
`~/PZSaveSync_LocalBackups/`. Et ton Drive/Dropbox a ses propres versions
historiques.

---

## Structure du code

```
src/pzsavesync/
  __main__.py      # entry point (python -m pzsavesync)
  gui.py           # interface customtkinter (3 onglets)
  saves.py         # détection des saves locales
  inspector.py     # lecture des chunks / DB / structures
  bundle.py        # création / extraction des .zip + manifest
  sync.py          # SharedRepo : lock + versions dans le dossier partagé
  config.py        # %APPDATA%\PZSaveSync\config.json
  builder.py       # build .exe via PyInstaller
  tooltip.py       # info-bulles
```

---

## Roadmap

- [ ] Support Linux/Mac (chemin `~/Zomboid`)
- [ ] Notifications quand le tour est libéré côté pote (polling Drive)
- [ ] Mode "diff visuel" : voir sur la map ce qui a changé entre 2 versions
- [ ] Compression delta entre versions (au lieu de re-zipper tout le monde)
- [ ] Détection des conflits de mods entre deux PCs

---

## Contribuer

Les PRs sont les bienvenues. Pour les changements importants, ouvre une issue
d'abord pour qu'on en discute.

```powershell
# Setup dev
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Test rapide du round-trip bundle/extract
python tests/test_roundtrip.py
```

---

## Licence

**Source Available — Tous droits réservés.** Voir [LICENSE](LICENSE).

Le code source est rendu public à titre de lecture et d'apprentissage uniquement.
Tu peux le faire tourner en local pour ton usage personnel, mais tu ne peux pas
le copier, le modifier, le redistribuer ni l'intégrer dans un autre projet.

---

## Crédits

- Outil basé sur l'observation de la structure de save documentée par la
  communauté PZ ([PZwiki Multiplayer FAQ](https://pzwiki.net/wiki/Multiplayer_FAQ),
  [Indifferent Broccoli — Upload a Save](https://wiki.indifferentbroccoli.com/ProjectZomboid/UploadASave))
- Inspiré par [PZ-Server-Save-Manager](https://github.com/pabloherresp/PZ-Server-Save-Manager)
  (script Batch, sans GUI ni lock)
