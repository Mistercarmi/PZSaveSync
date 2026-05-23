# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
sémantique ([SemVer](https://semver.org/lang/fr/)).

## [0.3.7] — 2026-05-23

### Fixed — inférence de companions piégée par plusieurs serveurs concurrents

- **`discover_companion_files` choisissait le mauvais `.ini`/`.db` quand un
  hôte avait 3+ serveurs et que les `save_dir` partageaient des mtimes proches**
  (typique après une extraction zip qui touche toutes les save_dir à la même
  seconde). L'inférence mtime, faute de variant exact, sélectionnait
  silencieusement le set Server le plus récent — y compris d'un AUTRE serveur.
  Un push embarquait alors la DB + config d'un serveur dans un bundle d'un
  autre serveur → corruption garantie chez le destinataire à l'extraction.
- **Cause racine** : PZ remplace systématiquement les espaces du *Server name*
  par des underscores quand il crée le dossier `Saves/Multiplayer/<save>/`.
  Donc un World name `My_Save` provient typiquement d'un Server name `My Save`
  avec `.ini`/`.db` nommés à l'identique (espaces). Le code ne testait pas
  cette transformation canonique et tombait direct dans l'inférence mtime.
- **Fix** : nouveau niveau « variant `_` → ` ` » inséré entre le match exact
  et l'inférence mtime. Si le match exact échoue, on tente d'abord
  `save_name.replace("_", " ")` comme prefix Server/db. Match déterministe
  basé sur la convention PZ, donc forte confiance (`exact_match=False`
  conservé pour transparence dans le manifest).

### Tests
- **+2 tests** dans `test_bundle_discovery.py` :
  - reproduit le cas avec 2 serveurs (cible « espace » + distracteur « espace »
    de mtime plus récente) → vérifie qu'on choisit le bon
  - garantit qu'un match exact (`My_Save.ini` existant réellement) reste
    prioritaire sur le variant (`My Save.ini`), pour ne pas casser les
    setups où le World name a volontairement des underscores

## [0.3.6] — 2026-05-22

### Fixed — parsing INI cassé sur BOM UTF-8 (audit phase 3)

- **`parse_ini_mods` ratait les mods quand le `.ini` avait un BOM UTF-8** :
  un user qui éditait son server.ini avec Notepad Windows (et le sauvegardait
  en « UTF-8 with BOM ») finissait avec un `\\ufeff` en début de fichier.
  La 1re ligne devenait `\\ufeffMods=...` et `startswith("Mods=")` ratait
  → 0 mod détecté dans le bundle, **le pote recevait une save sans mods**.
  Fix : `encoding="utf-8-sig"` qui consomme le BOM automatiquement.

### Improved — perf refresh_all (audit phase 3)

- **`_check_save_late` ne re-rglob plus la save** : avant, `refresh_all`
  appelait `list_all_with_info()` qui scanne chaque save_dir, PUIS
  `_check_save_late` rglobait la save active une 2e fois pour calculer
  son mtime. Sur une save de 50k chunks, ça doublait le freeze UI à
  chaque refresh. Maintenant on ré-utilise `info.last_played` du scan
  initial.

### Fixed — CI cassée silencieusement (audit phase 2)

- **`tests.yml` ne masquait plus les échecs pytest** : la step pytest avait
  `pytest tests/ -v --tb=short || echo "pytest a renvoyé un code différent de 0"`
  → un test qui plante laissait la CI **verte**. La suite pouvait être
  intégralement rouge depuis des semaines sans qu'on le voie. Fix : retiré
  le `|| echo`, commentaire explicite pour ne plus le rajouter par réflexe.
- **`release.yml` ne lançait que 2 tests sur la suite complète** : on faisait
  `python tests/test_roundtrip.py` + `python tests/test_security.py` en
  standalone. Tous les tests ajoutés à pytest (`test_resilience_v036`,
  `test_safety_belt_v035`, `test_recovery_completeness`, etc.) **n'étaient
  pas exécutés avant la build du `.exe`**. Une release pouvait donc shipper
  alors que ~70% de la suite était rouge. Fix : `pytest tests/ -v` en pré-build.

### Fixed — UX silencieuse (audit phase 2)

- **`ProgressDialog.run_in_thread` n'appelait plus `on_done` si l'user fermait
  la dialog en cours d'opération** : `self.after(0, finalize)` levait
  `TclError` (widget destroyed), le `try/except` swallowait, et le messagebox
  de succès/échec ne s'affichait jamais. Sur un push long, l'user fermait la
  fenêtre par accident et n'avait plus aucune confirmation. Fix : cascade de
  fallbacks (`self.after` → `master.after` → appel synchrone) pour garantir
  que `on_done` s'exécute toujours.
- **Notifications PowerShell : XML escape des caractères spéciaux** :
  `&`, `<`, `>`, `"`, `'` dans le title ou message brisaient le `LoadXml()`
  du toast → notification silencieusement absente. En pratique limité (les
  noms de saves sont validés), mais defense en profondeur pour les notes
  utilisateur et messages futurs. Fix via `xml.sax.saxutils.escape` étendu
  aux quotes.

### Tests
- **+17 tests** dans `test_notifications.py` (échappement XML) et
  `test_progress_dialog_resilience.py` (cascade de fallbacks on_done).
- **+25 tests** dans `test_coverage_gaps.py` :
  - `parse_ini_mods` avec BOM UTF-8, CRLF, CR-only, edge cases
  - `SharedRepo.push_bundle` complet (jamais testé jusqu'ici malgré son
    rôle central — gui.py dupliquait sa logique inline avant v0.3.6)
  - `SharedRepo.pull_bundle` (jamais testé)
  - **Verrou de tour** (`take_lock` / `release_lock` / `get_lock`) — feature
    centrale du workflow cloud qui n'avait AUCUN test : prise normale,
    refus si autre holder, force=True, libération, résilience à un
    lock.json corrompu / incomplet / array
- Couverture sync.py : **73% → 89%**
- Couverture totale : **71% → 74%**
- Total : **140 tests** verts (115 → 140).

### Fixed — résilience et défense en profondeur (audit complet)

- **`config.save()` désormais ATOMIQUE** : avant, un crash ou coupure de
  courant pendant l'écriture pouvait tronquer `config.json` → `load()`
  retombait sur une `Config()` vide → l'user **perdait ses profils, pseudo,
  dossier partagé et webhook**. Maintenant écriture via `.tmp` + `os.replace`,
  comme partout ailleurs dans le code.
- **`SharedRepo._read_manifest()` tolère un manifest corrompu** : si
  `versions/manifest.json` est tronqué (sync cloud foireuse, édit manuel),
  on log et on renvoie un manifest vide au lieu de crasher l'UI au
  `_refresh_cloud`. Les `.zip` physiques restent sur disque et
  `health_check()` les redétecte comme orphelins → réintégration 1-clic.
- **`inspector.inspect_zip()` n'extrait plus l'archive entière** : avant,
  cliquer « Inspecter un .zip » sur un bundle de 500 MB extrayait tout
  dans `/tmp` (lent + risque zip-bomb / zip-slip sur Python < 3.12).
  Maintenant on lit uniquement le manifest et la DB (si présente) via
  `zf.open()` ciblé, avec garde-fous anti zip-bomb (500 000 fichiers,
  20 GB décompressé, 200 MB max pour la DB embarquée).
- **PyInstaller `.exe` embarque tkinterdnd2** : avant, le `.spec` et le
  builder ne faisaient `collect_all` que sur `customtkinter`. Résultat :
  le drag-and-drop documenté dans le CHANGELOG v0.3.0 était silencieusement
  absent du `.exe` distribué (fallback `_DND_AVAILABLE=False` invisible
  pour l'utilisateur). Fix : ajouté à `PZSaveSync.spec` et `builder.py`.

### Fixed — bugs mineurs déterrés par l'audit

- **`cleanup_orphan_tmp_files` ne clobber plus un push concurrent** :
  ajoute un délai minimal de 5 minutes avant de considérer un `.tmp` comme
  orphelin. Sans ça, lancer une 2ᵉ instance pendant qu'une 1ʳᵉ pushe
  pouvait supprimer son `.tmp` actif → `os.replace` échouait.
- **GUI : Diff et bannière "save en retard" honorent `$PZ_ZOMBOID_ROOT`** :
  deux endroits utilisaient `Path.home() / "Zomboid"` en dur, ignorant
  l'override d'environnement (`bundle.py`, `saves.py`, etc. le respectent
  déjà). Sur Linux/Mac, ces fonctionnalités pointaient au mauvais endroit.
- **Logger : rotation par date via `TimedRotatingFileHandler`** : avant,
  `LOG_FILE` était figé à l'import → une session ouverte sur 2 jours
  écrivait toute la nuit dans le fichier de la veille. `purge_old` couvre
  désormais les deux formats (ancien `pzsavesync-DATE.log` et nouveau
  `pzsavesync.log.DATE`).
- **`_force_release` du verrou trace le pseudo** : avant `holder="*"` en
  dur, maintenant `holder=cfg.player_name` + log INFO.
- **`restore.list_backups()` voit les `pre_restore_*`** : un user qui se
  trompe de backup à restaurer voit maintenant le filet de secours créé
  juste avant. Tag visuel 📥 vs ↩ dans le picker.
- **`onboarding` : feedback explicite sur pseudo vide** : avant, le bouton
  "Suivant" ne faisait rien silencieusement. Maintenant un message rouge
  guide l'utilisateur.
- **`_do_push` ne duplique plus la logique de `push_bundle`** : le worker
  inline réimplémentait `SharedRepo.push_bundle` pour passer un
  `progress_cb`. `push_bundle` accepte maintenant `progress=...`.

### Tests
- **+16 tests** dans `test_resilience_v036.py` couvrant : atomicité de
  `config.save`, tolérance de `_read_manifest`, sécurité d'`inspect_zip`
  (no extractall, anti zip-bomb, bad zip), délai anti-concurrence de
  `cleanup_orphan_tmp_files`, visibilité des `pre_restore_*`.
- Total : **98 tests** verts.

### Cleanup
- Imports inutilisés retirés : `tempfile` dans `bundle.py`, `sys` dans
  `discord_webhook.py`, `Path` dans `onboarding.py`.
- User-Agent webhook Discord aligné sur la version courante (`PZSaveSync/0.3.6`).

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
