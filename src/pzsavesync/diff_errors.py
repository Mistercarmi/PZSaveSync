"""Exceptions typées du mode bundle différentiel (v0.4.0).

Permet aux appelants (sync.py, gui.py) de discriminer les cas d'échec spécifiques
au mode diff sans matcher sur des strings d'erreur génériques.
"""
from __future__ import annotations


class DiffBundleError(Exception):
    """Base pour toutes les erreurs spécifiques au mode bundle différentiel."""


class NoSnapshotAvailableError(DiffBundleError):
    """Mode DIFF demandé mais aucun snapshot trouvé pour cette save.

    Le client n'a jamais importé ce bundle (ou son snapshot a été perdu).
    L'appelant doit fallback en FULL.
    """


class ParentBundleSHAmismatchError(DiffBundleError):
    """Le snapshot référence un bundle qui n'est plus le dernier sur le cloud.

    Quelqu'un d'autre a poussé entre temps. Le client doit pull la dernière
    version avant de re-push un diff cohérent.
    """


class DiffTooBigError(DiffBundleError):
    """Trop de fichiers ont changé — le diff ne vaut plus le coup vs un full.

    Au-delà d'un certain ratio (par défaut 85%), envoyer un diff génère
    presque autant de bytes qu'un full, avec un risque de divergence plus
    grand. Mieux vaut basculer en FULL.
    """


class SnapshotCorruptError(DiffBundleError):
    """Fichier snapshot illisible ou format invalide.

    Définie ici (pas dans snapshot.py) pour que les appelants puissent
    catch via la hiérarchie DiffBundleError. snapshot.py re-exporte.
    """


class InvalidDiffManifestError(DiffBundleError):
    """Manifest d'un bundle déclare bundle_mode='diff' mais champs requis manquants
    (parent_bundle_sha256 vide ou expected_save_files vide)."""


class OrphanDiffError(DiffBundleError):
    """Bundle diff dont le seed FULL parent n'est plus accessible localement.

    Si on extrait un diff sans avoir le seed FULL au préalable, on écrirait
    les fichiers du diff sur une save_dir vide ou partielle → save corrompue
    silencieusement. On refuse explicitement avec un message UX clair.
    """
