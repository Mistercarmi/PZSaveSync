<div align="center">

# 🎮 PZ SaveSync

### Partage ta save Project Zomboid avec tes potes en 2 clics.

**🇫🇷 Français** · [🇬🇧 English](README.en.md)

![Free](https://img.shields.io/badge/100%25-Gratuit-2ecc71?style=for-the-badge)
![Source Visible](https://img.shields.io/badge/Code-Source%20visible-3498db?style=for-the-badge)
![No Account](https://img.shields.io/badge/Compte-Aucun%20requis-9b59b6?style=for-the-badge)

![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078d4)
![Build PZ](https://img.shields.io/badge/Project%20Zomboid-B41%20%2F%20B42-d65a5a)
![License](https://img.shields.io/badge/License-Source%20Available-orange)

</div>

---

## 🎯 Le problème, en 1 phrase

Tu joues à PZ en multi avec tes potes. À chaque fois qu'un autre veut héberger la prochaine session, **quelqu'un doit zipper à la main 5 fichiers / dossiers**, les envoyer par WeTransfer, et croiser les doigts pour que personne n'écrase la save de l'autre.

**PZ SaveSync fait ça pour toi avec 2 boutons.**

![Aperçu de l'onglet Partager](docs/screenshots/01_partager.png)

---

## 🚀 Comment ça marche

<table width="100%">
<tr>
<td width="50%" valign="top">

### 📥 Récupérer la save de ton pote

> *« Mon pote a fini sa session, c'est à moi d'héberger. »*

Clique **⬇ Récupérer la save**.
L'app télécharge la dernière version depuis le dossier partagé, sauvegarde ton état actuel au cas où, et te dit **« lance PZ → Multijoueur → Héberger »**.

</td>
<td width="50%" valign="top">

### 📤 Envoyer ta save à tes potes

> *« J'ai joué, je veux que mon pote prenne la suite. »*

Clique **⬆ Envoyer ma session**.
L'app emballe ton monde, la DB des persos et la config serveur, le dépose dans le dossier partagé. Ton pote n'a plus qu'à cliquer **Récupérer**.

</td>
</tr>
</table>

> 🔒 **Personne n'écrase la save de l'autre** : un verrou de tour empêche les push concurrents.
> 💾 **Tu peux toujours revenir en arrière** : un backup auto est créé avant chaque récupération, restaurable en 1 clic.
> ✅ **Aucun octet n'est perdu** : transfert bit-pour-bit, hash SHA256, audit de bout en bout.

---

## 📥 Installation (Windows, 30 secondes)

1. Va dans la section [Releases](https://github.com/Mistercarmi/PZSaveSync/releases/latest)
2. Télécharge **`PZSaveSync.exe`**
3. Double-clique

C'est tout. Pas de Python à installer, pas de compte à créer. Au premier lancement, un wizard te demande ton pseudo et le chemin de ton dossier Dropbox/Drive/OneDrive partagé.

> ℹ️ Windows SmartScreen va t'avertir « éditeur inconnu » (exe non signé). Clique sur **« Informations complémentaires » → « Exécuter quand même »**.

### Tu joues sous Linux / macOS

```bash
git clone https://github.com/Mistercarmi/PZSaveSync
cd PZSaveSync
pip install -r requirements.txt
python -m pzsavesync
```

---

## 🖥 Aperçu de l'app

| Mes parties | Réglages |
|:---:|:---:|
| ![Mes parties](docs/screenshots/02_mes_parties.png) | ![Réglages](docs/screenshots/03_reglages.png) |
| Toutes tes saves détectées automatiquement. Les non-exportables sont grisées. | Pseudo + dossier partagé, ça tient en 2 champs. |

---

## ❓ Questions fréquentes

**Et si mon pote n'a pas les mêmes mods que moi ?**
L'app extrait la liste des mods de ta save et **affiche les liens Steam Workshop directement à l'import**. Ton pote n'a qu'à cliquer pour s'abonner.

**Mon pote perd-il son perso quand il devient hôte ?**
**Non.** PZ stocke les persos dans la DB par SteamID. Quand ton pote héberge, son perso reste le sien, et toi tu retrouves le tien quand tu le rejoins.

**Et si on push tous les deux en même temps ?**
L'app pose un **verrou** quand quelqu'un prend le tour. Si tu tentes de push pendant que le verrou est pris, l'app te prévient.

**Si je fais une erreur de manip ?**
Avant chaque récupération, un **backup horodaté** de ton état actuel est créé dans `~/PZSaveSync_LocalBackups/`. Le bouton **↩ Restaurer un backup** te ramène à n'importe quel état précédent en 2 clics.

**C'est vraiment gratuit ?**
Oui. Aucune limite, aucun compte, aucune pub, aucun achat in-app. Le code est public, tu peux le vérifier et le builder toi-même.

---

## 📜 Licence

**Source Available — Tous droits réservés.** Tu peux lire le code et l'utiliser pour ton usage perso. Voir [LICENSE](LICENSE).

---

<div align="center">

*Made for the long nights of looting Muldraugh with your friends. 🌙*

</div>
