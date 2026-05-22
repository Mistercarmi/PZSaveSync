## 🛡 PZ SaveSync v0.3.4 — « Ne rien perdre »

Audit complet du pipeline push → pull → import. Quatre trous identifiés qui pouvaient faire perdre de la progression ou laisser ton pote sans pouvoir relancer la partie. Tous patchés.

### 📥 Installation rapide

Télécharge **`PZSaveSync.exe`** ci-dessous, double-clique pour remplacer ton ancienne version. Ta config, tes profils et ton historique cloud sont conservés.

> ℹ️ Windows SmartScreen affichera un avertissement « éditeur inconnu » au premier lancement (exe non signé). Clique sur **« Informations complémentaires » → « Exécuter quand même »**.

### 🐛 Corrigé — quatre fuites silencieuses

- **`_spawnpoints.lua` jamais embarqué** : si l'hôte avait configuré des points de respawn custom, le fichier ne suivait pas le bundle. Ton pote spawnait au mauvais endroit après import. **Désormais inclus** dans la découverte, le build et le backup.

- **Fichiers SQLite WAL/SHM/journal perdus** : `db/<save>.db-wal` contient les dernières transactions joueurs/véhicules quand PZ a été tué avant un checkpoint. Sans lui = perte de progression DB. **Désormais embarqués** avec la `.db` principale. Et **anti-corruption** : le destinataire voit ses vieux compagnons SQLite résiduels nettoyés avant l'extract (sinon SQLite tenterait d'appliquer un mauvais wal sur la nouvelle .db).

- **L'auto-prune pouvait supprimer la seule version d'une autre save** : après chaque push, le nettoyage gardait les N versions globales — donc si tu avais plusieurs saves dans le même repo cloud, la save peu utilisée disparaissait. **Le prune est maintenant scopé à la save** qu'on vient de pousser. Le prune manuel itère par save (« garder N par save »).

- **`extract_bundle(backup_dir=None)` faisait un `rmtree` sans backup** : porte d'entrée pour perdre la save_dir si appelée hors GUI. **Désormais backup obligatoire** par défaut.

### ✨ Ajouté

- **Bouton « ↩ Restaurer un backup »** dans Outils. Liste tes backups locaux (`~/PZSaveSync_LocalBackups/pre_import_*`), affiche save/date/contenu, et restaure le monde + DB + compagnons SQLite + fichiers serveur. Un backup pré-restauration est créé automatiquement avant (au cas où tu te trompes de backup).
- **Bundle v3** : champs implicites (spawnpoints, db-wal/shm/journal). Rétro-compatible : les bundles v1/v2 s'ouvrent toujours sans erreur.

### 🔧 Migration depuis v0.3.3

- **Aucune action requise.** Drop-in replacement du `.exe`. Tes versions cloud existantes restent lisibles. Au premier push après mise à jour, le nouveau format v3 sera utilisé.

### 🧪 Tests

- **70 tests unitaires + intégration** (60 existants + 14 nouveaux dans `test_recovery_completeness.py`).
- Round-trip live validé sur une vraie save (52k fichiers, 168 MB) : aucun octet ne diverge entre source et destination.

### 📜 Licence

Source Available — Tous droits réservés. Voir [LICENSE](https://github.com/Mistercarmi/PZSaveSync/blob/main/LICENSE).
