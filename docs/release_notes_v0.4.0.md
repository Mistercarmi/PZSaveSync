## ⚡ PZ SaveSync v0.4.0 — Push 60× plus léger + 2 fixes critiques

Cette release introduit le **bundle différentiel** : au lieu de renvoyer toute ta save (~64 MB sur Gitano_Z) à chaque push retour, l'app ne renvoie que les fichiers que tu as réellement modifiés depuis ton dernier import. Mesure réelle sur 2 zips de partie multi : **64 MB → 1.1 MB (-98%)**.

**Inclut aussi 2 fixes critiques signalés en v0.3.7** :
- 🗺  **Plus de perte de la mini-map M** après un push/pull (le Server name était écrasé, le fog of war devenait orphelin).
- ⏳ **Plus de barre "bloquée" pendant la vérification SHA256** (la prog bar update maintenant toutes les 50 entrées).

**+ 8 fixes pré-prod identifiés par audit complet du code** :
- ✅ `DiffTooBigError` → fallback FULL silencieux (plus de crash si > 85% chunks modifiés)
- ✅ Dialog `_pull` adapté au mode du bundle (plus de mensonge "va écraser ta config")
- ✅ Refus explicite des pull DIFF orphelins (plus de save corrompue silencieuse)
- ✅ `prune_versions` protège les seed FULL parents de DIFFs gardés
- ✅ **Backup pré-import préserve le Server name avec espaces** (frère caché du bug v0.3.7 — sans ça, rollback impossible)
- ✅ `sys.excepthook` global → exceptions tracées dans le log même en mode --windowed
- ✅ Progress callback dans la validation overlay (plus de freeze 5-15s sur grosse save)
- ✅ Double SHA256 supprimé au pull (gain 5-30s sur 64 MB)

### 📥 Installation rapide

Télécharge **`PZSaveSync.exe`** ci-dessous, double-clique pour remplacer ton ancienne version. Ta config, tes profils et ton historique cloud sont conservés.

> ℹ️ Windows SmartScreen affichera un avertissement « éditeur inconnu » au premier lancement (exe non signé). Clique sur **« Informations complémentaires » → « Exécuter quand même »**.

### ⚡ Nouveauté principale — Envoi optimisé

Quand tu cliques sur **⬆  Push** depuis ton onglet Partager, un nouveau dialog te propose :

```
⚡  Envoi optimisé  (recommandé)
   N'envoie que les fichiers modifiés depuis ton dernier import.
   Décoche pour un envoi COMPLET (failsafe — plus gros, plus sûr).
```

Coché par défaut. À chaque push, tu vois maintenant :

```
⚡  Push optimisé envoyé !

1.2 MB au lieu de 64 MB  (-98%)

328 fichier(s) modifié(s) envoyé(s).
```

L'icône **⚡** apparaît à côté des versions différentielles dans la liste cloud (📦 = bundle complet).

### 🛡 Failsafe garanti

- **Toggle décoché** = bundle complet comme avant (v0.3.x), aucun changement de comportement.
- **Hôte (seed initial)** = toujours en mode complet, pour qu'un nouveau pote puisse partir d'un seed propre.
- **Pas de snapshot** (1er push après upgrade) = fallback automatique en mode complet, sans erreur.
- **Conflit "un autre joueur a poussé entre temps"** = l'app détecte et te propose un pull avant de re-push.

### 🔒 Ce qui ne change PAS côté hôte

Quand tu pulles un bundle diff envoyé par un pote :
- Ta **config serveur** (`Server/<save>.ini`, `_SandboxVars.lua`, `_spawnregions.lua`) reste **intacte** — le client n'a pas le droit de l'écraser.
- Ta **.db locale** (cache SQLite) reste intacte.
- Tes **fichiers locaux non touchés** par le client sont préservés (overlay, pas wipe + extract).
- Les fichiers de cache régénérables (`WorldDictionaryReadable.lua`, `WorldDictionaryLog.lua`) ne sont **pas renvoyés** par les clients (826 KB économisés/push).

### 🔧 Comment ça marche

1. À chaque **pull / import**, l'app calcule un snapshot SHA256 de chaque fichier de la save extraite, et le persiste dans `~/PZSaveSync/snapshots/`.
2. À chaque **push**, elle compare l'état courant à ce snapshot, et n'envoie que les fichiers modifiés ou nouveaux.
3. Côté pote au pull, le diff est appliqué en **overlay** sur sa save existante (les fichiers locaux non listés sont préservés).
4. **Vérification de cohérence** : si quelqu'un a poussé entre temps, le push diff refuse et propose de pull d'abord.

### 🧪 Tests

- **+70 tests unitaires + intégration** sur 5 nouveaux fichiers de test.
- **Compat ascendante** : les 173 tests v0.3.7 passent toujours (zero régression).
- **Roundtrip complet validé** : seed full → pull → snapshot → modifs → push diff → overlay hôte → état final identique à l'attendu.
- **Bundles v3 (anciens)** : toujours lisibles, extraits automatiquement en mode FULL.

### 🗺  Fix critique : perte de la mini-map M

**Avant ce fix** (toutes versions ≤ v0.3.7) : si ton Server name avait des espaces (ex: "Gitano Z"), un seul round-trip push/pull suffisait à les remplacer par des underscores. PZ relisait alors le `.ini` avec le nouveau Server name "Gitano_Z" et ne retrouvait plus le dossier `<ton_steamid>_Gitano Z_player/` où était stockée ta mini-map M révélée. **Map perdue, des deux côtés après le round-trip.**

**Après ce fix** :
- Le Server name d'origine est **préservé** dans le bundle (plus de renommage sous save_name).
- À l'import, si l'app détecte que tu as déjà un dossier de map sous l'ancien Server name (typiquement avec des underscores), elle te propose un **renommage 1-clic** :
  > 🗺  Maps révélées à mettre à jour
  > Le Server name de cette save a changé. Sans renommage, PZ ne retrouvera pas la mini-map M révélée. Renommer maintenant ? **[Oui]** [Non]

Si tu avais déjà perdu ta map en v0.3.7, **elle ne reviendra pas magiquement** (PZ ne sait pas recréer ce que tu avais exploré). Mais le bug ne se reproduira plus, et les sauves futures préserveront ta carte.

### ⏳ Fix : barre de progression bloquée pendant la vérification SHA256

Sur les gros bundles (52k+ fichiers, 64 MB), la barre restait figée à 0/1 pendant 5-15 sec pendant le hash. Maintenant tu vois progresser "verify 5000/52000... 12000/52000...". Pas plus rapide, juste pas trompeur.

### 🔄 Migration depuis v0.3.x

**Aucune action requise.** Drop-in replacement du `.exe`. Au prochain lancement :
1. Ton `config.json` existant est étendu avec les 2 nouveaux toggles (defaults safe).
2. Ton manifest cloud existant est lu sans erreur (champs v4 défaultés à "full").
3. **Tes premiers push depuis v0.4.0 seront FULL** (pas encore de snapshot créé).
4. À partir du premier pull/import sous v0.4.0, les snapshots sont créés → **les push suivants seront automatiquement DIFF**.

### 📜 Licence

Source Available — Tous droits réservés. Voir [LICENSE](https://github.com/Mistercarmi/PZSaveSync/blob/main/LICENSE).
