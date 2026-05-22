## 🛡 PZ SaveSync v0.3.5 — Ceinture et bretelles

Cette release ferme **tous** les angles morts identifiés lors de l'audit complet du pipeline push → pull → import. Si tu utilises l'app pour partager une partie avec tes potes, mets à jour : 4 catégories de cas de perte de données silencieuse sont désormais bloquées.

### 📥 Installation rapide

Télécharge **`PZSaveSync.exe`** ci-dessous, double-clique pour remplacer ton ancienne version. Ta config, tes profils et ton historique cloud sont conservés.

> ℹ️ Windows SmartScreen affichera un avertissement « éditeur inconnu » au premier lancement (exe non signé). Clique sur **« Informations complémentaires » → « Exécuter quand même »**.

### 🐛 Corrigé — ne rien perdre, des deux côtés

**Côté hôte (push) :**
- **`_spawnpoints.lua` jamais embarqué** : les points de respawn custom étaient oubliés. Désormais inclus si présents.
- **Push d'une save vide possible** : `build_bundle` refuse maintenant si la save_dir contient 0 fichier.
- **L'auto-prune pouvait supprimer la seule version d'une autre save** : maintenant scoped à la save qu'on push.
- **`keep_last_n=1` autorisé** : 1 push corrompu = plus aucun rollback. Clamp automatique à **min 2 versions** par save.

**Côté pote (pull / import) :**
- **Fichiers SQLite WAL/SHM/journal perdus** : si PZ a été tué avant un checkpoint, les dernières transactions joueurs/véhicules disparaissaient. Désormais embarqués avec la `.db`.
- **Anti-corruption SQLite** : les compagnons SQLite résiduels du destinataire sont nettoyés (et backupés) avant extract — sinon SQLite tenterait d'appliquer un mauvais WAL sur la nouvelle `.db`.
- **`extract_bundle(backup_dir=None)` faisait un `rmtree` sans backup** : porte d'entrée fermée. `backup_dir` est désormais obligatoire par défaut.

### ✨ Ajouté

- **Bouton « ↩ Restaurer un backup »** : liste les backups locaux, restaure la save + DB + compagnons SQLite + fichiers serveur. Un backup pré-restauration est créé automatiquement.
- **Bouton « 🩺 Vérifier le repo cloud »** : détecte les `.zip` orphelins (présents mais invisibles dans le manifest), les entrées fantômes (manifest sans `.zip` physique) et les résidus `.tmp`. Réparation 1-clic.
- **Bannière d'aide en haut de l'onglet Partager** : explique en 1 ligne les 2 cas d'usage (Récupérer / Envoyer). Fermable, réaffichable depuis les Réglages.
- **Saves non-exportables grisées** dans Mes parties : plus de confusion entre saves client et serveur.
- **Version dans le header + bouton 🆕** : la version est toujours visible, et un clic vérifie les MAJ depuis n'importe quel onglet. Devient orange si une MAJ existe.
- **Actions secondaires regroupées** sous « ⋯ Plus d'options ».

### 🔧 Migration depuis v0.3.x

- **Aucune action requise.** Drop-in replacement du `.exe`. Tes versions cloud existantes restent lisibles (rétro-compat bundle v1/v2/v3).
- Au premier lancement, la bannière d'aide apparaît une fois ; ferme-la avec ✕ si tu connais déjà.

### 🧪 Tests

- **82 tests unitaires + intégration** (60 existants + 14 recovery completeness + 12 safety belt).
- Round-trip live validé sur une vraie save (52 730 fichiers, 168 MB) : aucun octet ne diverge entre source et destination.
- Bundle v3 (rétro-compat lecture des v1/v2).

### 📜 Licence

Source Available — Tous droits réservés. Voir [LICENSE](https://github.com/Mistercarmi/PZSaveSync/blob/main/LICENSE).
