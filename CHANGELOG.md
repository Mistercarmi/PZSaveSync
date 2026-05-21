# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
sémantique ([SemVer](https://semver.org/lang/fr/)).

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
  Les bundles v1 sont toujours lus correctement (rétrocompat).
- `config.Config` : nouveaux champs `auto_release_lock`, `discord_webhook`,
  `keep_last_n_versions`, `watch_pz_process`, `onboarding_done`. Le chargement
  filtre les champs inconnus → migration silencieuse depuis v0.1.0.
- Onglet Réglages enrichi : sections PRÉFÉRENCES + Webhook Discord, bouton
  "🔍 Détecter" à côté du dossier partagé, boutons "🧹 Nettoyer historique"
  et "🎯 Relancer le wizard" dans Outils.
- Footer affiche maintenant "🎮 PZ détecté" en vert quand PZ tourne.

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
