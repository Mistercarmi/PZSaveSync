# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
sémantique ([SemVer](https://semver.org/lang/fr/)).

## [0.3.5] — 2026-05-22

### Added — Garde-fous « ceinture et bretelles »
- **Refus de pousser une save vide** : `build_bundle` vérifie maintenant que
  la save_dir contient au moins 1 fichier avant de zipper. Avant, on pouvait
  pousser un bundle de 0 octet de contenu monde si la save était corrompue ou
  vidée — le pote aurait pull du vide.
- **Clamp `keep_last_n >= 2`** : `prune_versions` garde toujours au minimum 2
  versions par save. Sécurité contre un scénario où on push une save corrompue
  avec `keep_last_n=1` : sans le clamp, l'ancienne version saine était
  supprimée immédiatement → plus aucun rollback. Maintenant garanti.
- **Health check du repo cloud** : `SharedRepo.health_check()` + bouton
  Outils → **🩺 Vérifier le repo cloud**. Détecte les `.zip` orphelins
  (présents mais absents du manifest, donc invisibles au pull), les entrées
  fantômes du manifest (sans `.zip` physique), et les résidus `.tmp`. Propose
  une réparation 1-clic : réintégration des bundles orphelins lisibles dans
  le manifest, suppression des fantômes, nettoyage des `.tmp`.

### Added — UX
- **Bannière d'aide « 🎯 Comment ça marche en 2 clics »** en haut de l'onglet
  Partager. Explique les 2 use cases (Récupérer / Envoyer) en 1 ligne.
  Fermable avec ✕ (préférence persistée). Réaffichable via
  Outils → **❓ Réafficher l'aide**.
- **Saves non-exportables grisées** dans l'onglet Mes parties : fond plus
  sombre, texte gris, tag `🚫 non exportable`. Plus de confusion avec les
  saves serveur hébergées localement.
- **Header avec version + bouton MAJ** : badge `v0.3.5` à côté du titre,
  bouton **🆕** qui interroge GitHub Releases en 1 clic depuis n'importe quel
  onglet. Le badge devient orange si une MAJ est disponible.
- **Actions secondaires regroupées** sous **« ⋯ Plus d'options »** (Inspecter,
  Diff, Inspecter version) — moins de bruit visuel dans le flux principal.

### Tests
- **+12 tests** dans `test_safety_belt_v035.py` (refus push vide, clamp
  keep_last_n, health check repo + adopt_orphans + remove_missing_from_manifest).
- Total : **82 tests** verts.

## [0.3.4] — 2026-05-22

### Fixed — Ne rien perdre, tout récupérer côté pote
- **`_spawnpoints.lua` jamais embarqué** : si l'hôte avait configuré des
  points de respawn custom (`<prefix>_spawnpoints.lua`), le fichier n'était
  jamais inclus dans le bundle. Côté pote, le respawn divergait. Ajouté à la
  découverte, au build et au backup.
- **Fichiers SQLite WAL/SHM/journal perdus** : `db/<prefix>.db-wal`,
  `.db-shm`, `.db-journal` ne suivaient pas la `.db` principale. Si PZ était
  tué avant un checkpoint propre, les dernières transactions joueurs et
  véhicules disparaissaient. Maintenant embarqués avec la `.db`, restaurés
  ensemble, et le destinataire voit ses propres compagnons résiduels nettoyés
  AVANT extract (sinon SQLite tenterait d'appliquer un vieux wal sur la
  nouvelle .db → corruption).
- **`prune_versions` global pouvait supprimer la seule version d'une autre
  save** : l'auto-prune après push appelait `prune_versions(keep_last_n=N)`
  sans `save_name`. Si le repo cloud contenait plusieurs saves, garder les N
  globales pouvait sacrifier l'unique version d'une save peu utilisée. Le
  prune est maintenant scopé à la save qu'on vient de pousser ; le prune
  manuel itère par save (« garder N par save »).
- **`extract_bundle(backup_dir=None)` faisait un `rmtree` sans backup** :
  porte d'entrée pour perdre la save_dir si appelée hors GUI. Désormais
  `backup_dir` est requis par défaut. Bypass explicite via `allow_no_backup=True`
  (réservé aux tests).

### Added
- **Bouton « ↩ Restaurer un backup »** dans Outils. Liste les backups locaux
  (`~/PZSaveSync_LocalBackups/pre_import_*`), affiche save/date/contenu, et
  restaure le monde + DB + compagnons SQLite + fichiers serveur. Un backup
  pré-restauration est créé automatiquement avant (au cas où on se trompe).
- **Module `restore.py`** : `list_backups()`, `restore_backup()` ; idem côté
  CLI/scripts.
- **Bundle v3** : champs implicites (spawnpoints, db-wal/shm/journal). Rétro-
  compatible à la lecture (les bundles v1/v2 s'ouvrent toujours).

### Tests
- **+14 tests** dans `test_recovery_completeness.py` (round-trip spawnpoints,
  embarquage WAL/SHM, nettoyage des compagnons SQLite résiduels, refus
  d'extract sans backup, prune scoped, restore round-trip).
- `scripts/live_roundtrip_check.py` : script de validation à lancer en local
  qui crée un bundle de ta vraie save, l'extrait dans un dossier fantôme,
  et hash chaque fichier pour vérifier qu'aucune octet n'a bougé. Sans
  toucher à la save originale.

## [0.3.3] — 2026-05-21

### Fixed
- **Bundle vide de config serveur quand Server name ≠ World name** : si l'hôte
  hébergeait en laissant le nom de serveur par défaut (`servertest`) tout en
  nommant son monde autrement, le builder cherchait uniquement
  `Server/<world>.ini` et `db/<world>.db` et n'embarquait rien. Le destinataire
  recevait alors une save sans DB joueurs ni config, et ne voyait pas la
  partie dans le menu Multijoueur → Héberger. Le builder utilise maintenant
  une **stratégie en cascade** pour retrouver les bons fichiers même quand les
  noms diffèrent :
  1. *Set Server complet préféré* : un `.ini` accompagné de son `_SandboxVars`
     et `_spawnregions` du même prefix bat un `.ini` orphelin.
  2. *Corrélation mtime* entre `Saves/Multiplayer/<world>/` et les fichiers
     de `Server/` + `db/` (PZ écrit ces trois choses simultanément à chaque
     sauvegarde, donc les dates sont alignées à la minute près).
  3. *Cross-vérification db ↔ server* : si on infère `prefix=X` côté Server,
     on prend `db/X.db` directement s'il existe.
  4. *Seuil de sécurité* : rejet de l'inférence si écart mtime > 90 jours
     (mieux vaut un bundle sans config qu'un mauvais `.ini` embarqué).
  Les fichiers sont embarqués dans le bundle sous `{save_name}.<ext>` pour
  rester cohérents côté destinataire. Tracé dans le manifest via
  `inferred_server_prefix`.

## [0.3.2] — 2026-05-21

### Fixed
- **Import refusé "Bundle suspect" sur grosses saves multi** : la limite
  `MAX_FILES_IN_BUNDLE` était à 50 000 fichiers, ce qui est dépassé par une
  save PZ où la map a été beaucoup explorée (chaque chunk = 1 fichier
  `chunkdata_X_Y.bin` + `map_X_Y.bin` + `zpop_X_Y.bin`). Passée à 500 000.
  Le vrai garde-fou anti-zip-bomb reste la taille décompressée (20 GB max).

## [0.3.1] — 2026-05-21

### Fixed
- **Freeze UI à chaque clic sur certains PC** : le polling de Project Zomboid
  (toutes les 15 s) appelait `tasklist` de manière synchrone sur le thread UI.
  Sur les PC où `tasklist` est lent (antivirus actif, beaucoup de process), ça
  bloquait l'interface plusieurs secondes à chaque tick. Le poll s'exécute
  maintenant dans un thread daemon, et le résultat est marshalé sur le main
  thread via `self.after(0, ...)`.

## [0.3.0] — 2026-05-21

### Added — Distribution & dev experience
- **CI/CD GitHub Actions** : `.github/workflows/tests.yml` lance les tests
  + py_compile sur Windows × Python 3.11/3.12/3.13 à chaque push/PR.
  `release.yml` build le `.exe` via PyInstaller et publie une release
  automatiquement à chaque tag `v*` (avec notes depuis `docs/release_notes_*.md`).
- **Auto-update check** : module `updater.py` interroge l'API GitHub Releases
  au démarrage et affiche une bannière bleue cliquable si une nouvelle version
  est disponible. Bouton "🆕 Vérifier les MAJ" dans Réglages aussi.
- **Drag-and-drop d'un `.zip`** sur la fenêtre déclenche l'import (validation
  + progress + check mods comme un import normal). Dépendance : `tkinterdnd2`.
- **Image sociale** générée par `scripts/make_social_image.py` (1280×640)
  pour les previews Discord/Twitter du repo.
- **Templates GitHub** : bug report + feature request (`.github/ISSUE_TEMPLATE/`)
  avec champs structurés (version, PZ build, OS, logs).
- **README en anglais** (`README.en.md`) avec switcher de langue en haut.

### Added — UX & fiabilité
- **Profils multi-groupes** : tu peux maintenant avoir plusieurs profils
  (un par groupe d'amis), chacun avec son propre pseudo, dossier partagé,
  save active et webhook Discord. Sélecteur en haut du header, bouton `＋`
  pour ajouter un profil. Migration silencieuse depuis v0.2 → v0.3 (le config
  v0.2 flat devient un profil "default").
- **Logger persistant** : module `logger.py` écrit dans
  `%APPDATA%/PZSaveSync/logs/pzsavesync-YYYY-MM-DD.log`. Rétention 14 jours,
  bouton "📝 Voir logs" dans Réglages. Stack traces complètes des erreurs
  pour faciliter les bug reports.
- **Notifications natives OS** : module `notifications.py` (Toast Windows
  via PowerShell + WinRT, `notify-send` sous Linux, `osascript` sous macOS).
  Toast affiché après chaque push/pull/import réussi.
- **Recovery `.tmp` au démarrage** : nettoyage automatique des fichiers
  `bundle_xxx.zip.tmp` orphelins (résidus d'opérations interrompues).
- **Support Linux/macOS** : `Path.home() / "Zomboid"` au lieu de
  `%USERPROFILE%`. Variable d'environnement `PZ_ZOMBOID_ROOT` pour override
  manuel. Le badge platform du README est mis à jour.

### Security
- **Limites anti zip-bomb** à l'extraction : 5 GB compressé max, 20 GB
  décompressé max, 50 000 fichiers max. Refus explicite avec message clair.
- **Validation numérique des Workshop IDs** : un Workshop ID Steam doit être
  uniquement composé de chiffres ; toute valeur non-numérique est filtrée
  silencieusement par `parse_ini_mods`. Idem pour les noms de mods : refus
  des séparateurs de chemin et `..`.

### Tests
- **Suite pytest** ajoutée : 45 tests unitaires répartis sur 10 modules
  (`test_bundle_security`, `test_config_migration`, `test_sync_prune`,
  `test_pz_detector`, `test_updater`, `test_logger`, `test_cloud_detect`,
  `test_discord_webhook` en plus des 2 fichiers d'intégration existants).
- `conftest.py` avec une fixture `fake_zomboid` réutilisable.

### Changed
- `config.py` schéma v0.3 : `{active_profile, profiles, ...globals}` au lieu
  du schéma flat v0.2. Migration auto au chargement.
- `requirements.txt` ajoute `tkinterdnd2>=0.4.0`.

## [0.2.0] — 2026-05-21

### Added
- **Détection automatique de PZ en cours d'exécution** : bloque push / pull /
  import / export tant que PZ tourne (évite la corruption de save). Module
  `pz_detector.py` (cross-platform Windows / Linux / Mac).
- **Bannière "save locale en retard"** dans l'onglet Partager : compare la
  date du dernier push cloud avec le mtime de la save locale ; affiche un
  warning jaune si le cloud est plus récent.
- **Vérification des mods installés** après un import / pull : scan
  `Zomboid/mods/` + Steam Workshop (AppID 108600), liste les mods et IDs
  Workshop manquants avec lien direct. Module `mods_check.py`.
- **Auto-détection des dossiers cloud** : bouton "🔍 Détecter" dans Réglages
  qui scanne Dropbox / Drive / OneDrive / iCloud / MEGA / pCloud et propose
  les chemins trouvés. Module `cloud_detect.py`.
- **Hash SHA256 dans le manifest** (bundle v2) : calculé au push, vérifié au
  pull / import. Détecte la corruption de bundle pendant la synchro cloud.
  Rétro-compat pour les bundles v1 (vérification ignorée).
- **Nettoyage de l'historique** : méthode `SharedRepo.prune_versions()` +
  bouton "🧹 Nettoyer historique" dans Outils. Garde les N plus récentes.
- **Détection de fermeture de PZ → propose un push** : polling toutes les
  15 s ; popup automatique quand on passe de "PZ tourne" à "PZ fermé".
- **Wizard d'onboarding 3 étapes** au premier lancement : pseudo →
  dossier partagé (avec suggestions cloud) → récap. Module `onboarding.py`.
- **Barre de progression** pour push / pull / export / import : threading
  + callback `progress(step, current, total)`. Module `progress_dialog.py`.
- **Auto-release du tour après push** : checkbox dans le dialog de push,
  préférence persistée dans la config.
- **Webhook Discord** (optionnel) : URL configurable dans Réglages, bouton
  "🧪 Tester", notification automatique à chaque push réussi. Module
  `discord_webhook.py` (stdlib pure, aucune nouvelle dépendance).

### Changed
- `bundle.BUNDLE_VERSION` passe à 2 (champ `sha256` ajouté au manifest).
- `config.Config` : nouveaux champs `auto_release_lock`, `discord_webhook`,
  `keep_last_n_versions`, `watch_pz_process`, `onboarding_done`.

## [0.1.0] — 2026-05-21

### Added
- Détection auto des saves multi locales (`%USERPROFILE%\Zomboid\Saves\Multiplayer\`)
- Inspection : chunks explorés, structures construites, joueurs (DB SQLite)
- Bundle `.zip` auto-suffisant : monde + DB persos + config serveur (.ini,
  SandboxVars, spawnregions)
- Mode **cloud** via dossier partagé Dropbox/Drive/OneDrive : push, pull,
  historique des versions
- Mode **manuel** : export / import / inspect `.zip` (Gmail, WeTransfer,
  Discord, USB)
- Verrou de tour (`lock.json`) pour éviter les push concurrents
- Backup auto avant chaque pull/import (`~/PZSaveSync_LocalBackups/`)
- Build `.exe` autonome intégré (PyInstaller)
- Diff entre save locale et dernière version remote
- GUI customtkinter dark mode, 3 onglets (Partager / Mes parties / Réglages)
- Palette PZ-themed, étoile dorée pour la partie active, hover effects sur
  les cartes, footer avec version et statut du dossier partagé
