## 🎮 PZ SaveSync v0.2.0 — Smart sync release

Cette release ajoute 11 features qui rendent l'app **vraiment utilisable au quotidien**, en évitant les scénarios où on perd 2 h de jeu par erreur d'enchaînement.

### 📥 Installation rapide

Télécharge **`PZSaveSync.exe`** ci-dessous, double-clique.

> ℹ️ Windows SmartScreen affichera un avertissement « éditeur inconnu » au premier lancement (exe non signé). Clique sur **« Informations complémentaires » → « Exécuter quand même »**.

### 🆕 Nouveautés v0.2

#### 🔴 Anti-perte de progression

- **🛡 Détection PZ en cours d'exécution** — Pull / Push / Import / Export sont bloqués tant que Project Zomboid tourne (risque de corruption). Cross-platform via `tasklist` (Windows) / `ps` (Linux/Mac).
- **⚠ Bannière "save en retard"** dans l'onglet Partager — Si le cloud a une version plus récente que ta save locale, l'app te le dit en jaune pour que tu pulles avant de jouer. Évite d'écraser la session de ton pote par accident.
- **🧩 Vérification des mods installés** après pull/import — L'app scanne `Zomboid/mods/` et `steamapps/workshop/content/108600/` et te liste les mods et IDs Workshop manquants, avec lien direct vers Steam pour t'abonner.

#### 🟡 Confort d'utilisation

- **🔍 Auto-détection des dossiers cloud** — Bouton "Détecter" qui propose les Dropbox / Drive / OneDrive / iCloud / MEGA / pCloud trouvés sur ton PC.
- **🔐 Hash SHA256 dans le manifest** — Vérification d'intégrité à l'import : si Dropbox a foiré la synchro, le bundle est marqué corrompu plutôt que de planter PZ. Rétrocompat v1.
- **🧹 Nettoyage de l'historique** — Bouton "Nettoyer historique" qui supprime les vieilles versions (garde les N dernières). Tu peux aussi activer une purge automatique après chaque push.
- **🎬 Push auto à la fermeture de PZ** — Polling toutes les 15 s ; quand tu fermes PZ, l'app te propose un push pour ne pas oublier.

#### 🟢 UX

- **🎯 Wizard 3 étapes** au premier lancement (pseudo → dossier → récap), avec suggestions cloud auto.
- **📊 Barre de progression** pour push / pull / export / import des gros mondes (PZ B42 peut faire 500 MB+).
- **🔓 Auto-release du tour** après push — Checkbox cochée par défaut, préférence persistée.
- **💬 Webhook Discord** — Optionnel : notification "⬆ Nouvelle session disponible" dans votre canal à chaque push. Stdlib pure (aucune nouvelle dépendance).

### 🔧 Migration depuis v0.1

- Aucune action requise. La config v0.1 (`%APPDATA%\PZSaveSync\config.json`) est lue normalement ; les nouveaux champs prennent leurs valeurs par défaut.
- Les bundles v1 (sans champ `sha256`) restent importables — la vérification d'intégrité est juste skip pour eux.

### 🧪 Build & tests

- Stack : Python 3.11+, customtkinter 5.2, **stdlib only** pour les modules réseau et système (urllib, subprocess, hashlib).
- Tests round-trip + sécurité : ✅
- Smoke test post-build du `.exe` : ✅

### 📜 Licence

Source Available — Tous droits réservés. Voir [LICENSE](https://github.com/Mistercarmi/PZSaveSync/blob/main/LICENSE).
