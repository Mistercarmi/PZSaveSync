## 🩹 PZ SaveSync v0.3.1 — Hotfix anti-freeze

Patch ciblé sur un bug remonté en early testing : sur certains PC, l'interface freezait plusieurs secondes à chaque interaction.

### 📥 Installation rapide

Télécharge **`PZSaveSync.exe`** ci-dessous, double-clique pour remplacer ton ancienne version. Ta config et tes profils sont conservés.

> ℹ️ Windows SmartScreen affichera un avertissement « éditeur inconnu » au premier lancement (exe non signé). Clique sur **« Informations complémentaires » → « Exécuter quand même »**.

### 🐛 Corrigé

- **Freeze UI à chaque clic** sur certains setups. Le polling du process Project Zomboid (toutes les 15 s pour détecter quand tu fermes le jeu) appelait `tasklist` de manière synchrone sur le thread UI. Sur les PC où `tasklist` est lent à répondre (antivirus actif inspectant le call, beaucoup de process ouverts), ça bloquait l'interface plusieurs secondes à chaque tick — et la sensation était « ça freeze à chaque clic ».

  Le poll s'exécute maintenant dans un **thread daemon séparé**, et le résultat est marshalé sur le main thread via `self.after(0, ...)`. Plus aucun blocage UI dû au polling.

### 🔧 Migration depuis v0.3.0

- **Aucune action requise.** Drop-in replacement du `.exe`. Config, profils et historique des versions préservés.

### 🧪 Tests

- Tous les tests existants (45 unitaires + 2 intégration) passent.
- Build PyInstaller : `.exe` final ~21 MB.

### 📜 Licence

Source Available — Tous droits réservés. Voir [LICENSE](https://github.com/Mistercarmi/PZSaveSync/blob/main/LICENSE).
