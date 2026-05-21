# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
sémantique ([SemVer](https://semver.org/lang/fr/)).

## [Unreleased]

### Changed
- Refonte du GUI : 4 onglets réduits à 3 (« 🔄 Partager », « 🎮 Mes parties »,
  « ⚙ Réglages »). L'onglet Partager fusionne les flux cloud et `.zip` manuel
  et devient le hub principal.
- Boutons d'action principaux agrandis (112px, icône 34pt, hover par éclairage
  doux de la couleur de fond plutôt que bordure agressive).
- Textes explicatifs raccourcis ; détails déplacés dans les tooltips.
- Passe esthétique : palette unifiée (PZ-themed dark), bordures discrètes sur
  cartes, étoile dorée (#f5c842) pour la partie active, hover effects sur les
  cartes de saves, footer avec version et statut de connexion au dossier
  partagé.
- Popups (VersionPicker, BuildWindow) alignés sur la palette principale.

## [0.1.0] — initial

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
