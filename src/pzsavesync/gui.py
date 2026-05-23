from __future__ import annotations

import datetime as dt
import os
import platform
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from pzsavesync import (
    builder,
    bundle as bundle_mod,
    cloud_detect,
    config,
    discord_webhook,
    inspector,
    logger as log_mod,
    mods_check,
    notifications,
    onboarding,
    pz_detector,
    restore as restore_mod,
    saves,
    updater,
)
from pzsavesync.progress_dialog import ProgressDialog
from pzsavesync.sync import SharedRepo, Version
from pzsavesync.tooltip import attach as tip

# Drag-and-drop optionnel : si tkinterdnd2 n'est pas dispo, on dégrade proprement
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False
    DND_FILES = None  # type: ignore
    TkinterDnD = None  # type: ignore

_log = log_mod.get("gui")

LOCAL_BACKUPS = Path.home() / "PZSaveSync_LocalBackups"


def _open_path(path: Path | str) -> None:
    """Ouvre un dossier ou un fichier dans l'explorateur de l'OS, cross-platform."""
    p = str(path)
    sysname = platform.system()
    if sysname == "Windows":
        os.startfile(p)
    elif sysname == "Darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])

# --- Palette unifiée (PZ-themed, dark mode) ---
# Surfaces
COLOR_BG = "#15171b"          # fond principal (presque noir)
COLOR_HEADER = "#101216"      # bandeau header (plus sombre que BG)
COLOR_CARD = "#22262e"        # cartes / panneaux niveau 1
COLOR_CARD_HOVER = "#2a2f38"  # hover sur cartes
COLOR_CARD_SEL = "#2d557e"    # sélection (bleu plus chaud, distinct des actions)
COLOR_BORDER = "#33373f"      # bordures discrètes

# Texte
COLOR_TEXT = "#e6e8ec"
COLOR_TEXT_MUTED = "#8a8e97"
COLOR_TEXT_DIM = "#5a5e66"

# Sémantique
COLOR_OK = "#4caf6d"          # vert succès (un poil plus vif)
COLOR_WARN = "#e0a236"        # orange warning
COLOR_BAD = "#d65a5a"         # rouge erreur
COLOR_STAR = "#f5c842"        # doré pour la partie active (★)
COLOR_MUTED = COLOR_TEXT_MUTED  # alias rétro-compat

# Actions (boutons)
ACTION_PULL = "#2c7fb8"       # bleu PZ — récupérer
ACTION_PUSH = "#2e8b57"       # vert — partager
ACTION_IMPORT = "#3a6fa8"     # bleu un poil plus clair que la sélection
ACTION_EXPORT = "#3a9a5c"     # vert légèrement plus clair que push
ACTION_NEUTRAL = "#3a3d44"    # gris, secondaire
ACTION_NEUTRAL_HOVER = "#484c54"
ACTION_DANGER = "#b24545"     # rouge, attention
ACTION_RELEASE = "#7a5a3a"    # brun chaud (libérer un verrou — sobre, pas dangereux)

APP_VERSION = "0.3.7"


_AppBase = (ctk.CTk, TkinterDnD.DnDWrapper) if _DND_AVAILABLE else (ctk.CTk,)


class App(*_AppBase):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("PZ SaveSync")
        self.geometry("1100x800")
        self.minsize(980, 700)
        self.configure(fg_color=COLOR_BG)

        # Activer le drag-and-drop si dispo
        if _DND_AVAILABLE:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
                _log.info("Drag-and-drop activé.")
            except Exception as e:
                _log.warning("Drag-and-drop indisponible : %s", e)

        self.cfg = config.load()
        self._save_entries: list[saves.SaveEntry] = []
        self._selected_save: str | None = self.cfg.save_name or None
        # État du polling de PZ : True quand on a vu PZ tourner au moins une fois
        self._pz_was_running = False
        # Update info (rempli au démarrage par le check async)
        self._update_info: updater.UpdateInfo | None = None

        # Nettoyage des résidus de la session précédente
        self._cleanup_orphan_tmp()

        self._build_header()
        self._build_tabs()
        self._build_footer()
        self.refresh_all()

        # Pop-up onboarding si premier lancement (pseudo vide ET pas marqué done)
        if not self.cfg.player_name and not self.cfg.onboarding_done:
            self.after(300, self._show_onboarding)

        # Polling du process PZ (toutes les 15 s)
        self._schedule_pz_poll()

        # Check des mises à jour en async (1.5s après démarrage)
        if self.cfg.auto_check_updates:
            self.after(1500, self._check_updates_async)

        _log.info("App démarrée — v%s", APP_VERSION)

    # ---------------------------------------------------------------- header
    def _build_header(self):
        bar = ctk.CTkFrame(self, height=62, corner_radius=0, fg_color=COLOR_HEADER)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # Logo + nom
        logo = ctk.CTkFrame(bar, fg_color="transparent")
        logo.pack(side="left", padx=16)
        ctk.CTkLabel(
            logo, text="🎮",
            font=("Segoe UI Emoji", 22),
        ).pack(side="left", padx=(0, 8))
        title_block = ctk.CTkFrame(logo, fg_color="transparent")
        title_block.pack(side="left")
        title_row = ctk.CTkFrame(title_block, fg_color="transparent")
        title_row.pack(anchor="w")
        ctk.CTkLabel(
            title_row, text="PZ SaveSync",
            font=("Segoe UI", 19, "bold"), anchor="w",
        ).pack(side="left")
        self.header_version = ctk.CTkLabel(
            title_row, text=f"v{APP_VERSION}",
            font=("Segoe UI", 11, "bold"), text_color=COLOR_TEXT_DIM, anchor="w",
        )
        self.header_version.pack(side="left", padx=(8, 0), pady=(4, 0))
        tip(self.header_version, "Version installée. Clique sur 🆕 pour vérifier les MAJ.")
        ctk.CTkLabel(
            title_block, text="Co-op save sharing for Project Zomboid",
            font=("Segoe UI", 9), anchor="w", text_color=COLOR_TEXT_DIM,
        ).pack(anchor="w")

        # Trait fin sous le header (séparation)
        sep = ctk.CTkFrame(self, height=1, corner_radius=0, fg_color=COLOR_BORDER)
        sep.pack(fill="x")

        # Statut à droite
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right", padx=12)

        # Profil actif — dropdown (uniquement si > 1 profil ou si on veut le proposer)
        self.profile_var = ctk.StringVar(value=self.cfg.current.name or "Default")
        self.profile_menu = ctk.CTkOptionMenu(
            right, variable=self.profile_var,
            values=self.cfg.profile_labels(),
            width=140, height=30,
            font=("Segoe UI", 11),
            fg_color=ACTION_NEUTRAL, button_color=ACTION_NEUTRAL_HOVER,
            command=self._switch_profile,
        )
        self.profile_menu.pack(side="left", padx=6)
        tip(self.profile_menu, "Profil actif (groupe d'amis). Tu peux en avoir plusieurs.")

        b_add_profile = ctk.CTkButton(
            right, text="＋", width=30, height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 14, "bold"),
            command=self._add_profile_prompt,
        )
        b_add_profile.pack(side="left", padx=2)
        tip(b_add_profile, "Ajouter un nouveau profil (nouveau groupe d'amis).")

        # Séparateur visuel
        ctk.CTkFrame(right, width=1, height=24, fg_color=COLOR_BORDER).pack(
            side="left", padx=8, pady=4
        )

        self.header_user = ctk.CTkLabel(
            right, text="👤 —",
            font=("Segoe UI", 12), text_color=COLOR_TEXT_MUTED,
        )
        self.header_user.pack(side="left", padx=10)
        tip(self.header_user, "Ton pseudo (modifiable dans Réglages).")

        self.header_cloud = ctk.CTkLabel(
            right, text="☁ —",
            font=("Segoe UI", 12), text_color=COLOR_TEXT_MUTED,
        )
        self.header_cloud.pack(side="left", padx=10)
        tip(self.header_cloud, "Dossier partagé (Dropbox / GDrive / OneDrive) utilisé pour le mode cloud.")

        self.header_update_btn = ctk.CTkButton(
            right, text="🆕", width=36, height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 14, "bold"),
            command=self._manual_update_check,
        )
        self.header_update_btn.pack(side="left", padx=2)
        tip(self.header_update_btn, "Vérifier si une nouvelle version est disponible "
                                    "(interroge GitHub Releases).")

        b_refresh = ctk.CTkButton(
            right, text="↻", width=36, height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 14, "bold"),
            command=self.refresh_all,
        )
        b_refresh.pack(side="left", padx=6)
        tip(b_refresh, "Rafraîchir : re-scanne tes saves locales et l'état du dossier partagé.")

    # ---------------------------------------------------------------- footer
    def _build_footer(self):
        sep = ctk.CTkFrame(self, height=1, corner_radius=0, fg_color=COLOR_BORDER)
        sep.pack(fill="x", side="bottom")
        foot = ctk.CTkFrame(self, height=26, corner_radius=0, fg_color=COLOR_HEADER)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        ctk.CTkLabel(
            foot, text=f"PZ SaveSync v{APP_VERSION}",
            font=("Segoe UI", 9), text_color=COLOR_TEXT_DIM,
        ).pack(side="left", padx=12)
        # Indicateur "PZ détecté" (vide la plupart du temps)
        self.footer_pz_status = ctk.CTkLabel(
            foot, text="",
            font=("Segoe UI", 9), text_color=COLOR_TEXT_DIM,
        )
        self.footer_pz_status.pack(side="left", padx=12)
        self.footer_status = ctk.CTkLabel(
            foot, text="prêt",
            font=("Segoe UI", 9), text_color=COLOR_TEXT_DIM,
        )
        self.footer_status.pack(side="right", padx=12)

    # ------------------------------------------------------------------ tabs
    def _build_tabs(self):
        tabs = ctk.CTkTabview(self, anchor="nw")
        tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self.tabs_widget = tabs
        self.tab_share = tabs.add("🔄  Partager")
        self.tab_parties = tabs.add("🎮  Mes parties")
        self.tab_settings = tabs.add("⚙  Réglages")

        self._build_tab_share()
        self._build_tab_parties()
        self._build_tab_settings()

    # ============================================================== TAB PARTAGER
    def _build_tab_share(self):
        wrap = self.tab_share

        # --- Bannière d'aide "Comment utiliser l'app" (fermable) ---
        self.help_banner = ctk.CTkFrame(
            wrap, fg_color="#1a2e2a", corner_radius=10,
            border_width=1, border_color=ACTION_PUSH,
        )
        # On la pack seulement si l'user ne l'a pas masquée
        if not self.cfg.hide_help_banner:
            self.help_banner.pack(fill="x", padx=16, pady=(16, 4))

        help_inner = ctk.CTkFrame(self.help_banner, fg_color="transparent")
        help_inner.pack(fill="x", padx=14, pady=10)

        help_text_block = ctk.CTkFrame(help_inner, fg_color="transparent")
        help_text_block.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            help_text_block, text="🎯  Comment ça marche en 2 clics",
            font=("Segoe UI", 12, "bold"), text_color="#9bd9bf",
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            help_text_block,
            text="⬇  Récupérer la save  →  ton pote vient de jouer, tu prends le relais.    "
                 "⬆  Envoyer ma session  →  toi tu viens de jouer, c'est au tour de ton pote.",
            font=("Segoe UI", 11), text_color=COLOR_TEXT,
            anchor="w", justify="left", wraplength=900,
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkButton(
            help_inner, text="✕", width=28, height=28,
            fg_color="transparent", hover_color=COLOR_CARD,
            font=("Segoe UI", 13, "bold"), text_color=COLOR_TEXT_MUTED,
            command=self._dismiss_help_banner,
        ).pack(side="right", padx=(8, 0), anchor="n")

        # --- Bannière "update disponible" (cachée par défaut) ---
        self.update_banner = ctk.CTkFrame(
            wrap, fg_color="#1e3a5f", corner_radius=10,
            border_width=1, border_color=ACTION_PULL,
        )
        self.update_banner_label = ctk.CTkLabel(
            self.update_banner, text="",
            text_color="#9bc1ed", font=("Segoe UI", 12, "bold"),
            anchor="w", justify="left", cursor="hand2",
        )
        self.update_banner_label.pack(fill="x", padx=14, pady=10)
        self.update_banner_label.bind("<Button-1>", self._open_update_url)
        self.update_banner.bind("<Button-1>", self._open_update_url)

        # --- Bannière "save locale en retard" (cachée par défaut) ---
        self.late_banner = ctk.CTkFrame(
            wrap, fg_color="#3a2b14", corner_radius=10,
            border_width=1, border_color=COLOR_WARN,
        )
        # On la pack/unpack dynamiquement dans _refresh_late_banner
        self.late_banner_label = ctk.CTkLabel(
            self.late_banner, text="",
            text_color=COLOR_WARN, font=("Segoe UI", 12, "bold"),
            anchor="w", justify="left",
        )
        self.late_banner_label.pack(fill="x", padx=14, pady=10)
        # Pas de pack ici — c'est _refresh_late_banner qui décide

        # --- Bandeau "Partie active" ---
        active_bar = ctk.CTkFrame(wrap, fg_color=COLOR_CARD, corner_radius=10,
                                  border_width=1, border_color=COLOR_BORDER)
        active_bar.pack(fill="x", padx=16, pady=(16, 8))
        self.active_bar_ref = active_bar  # pour pack avant cette barre la bannière retard
        self.active_label = ctk.CTkLabel(
            active_bar, text="⭐  Aucune partie active",
            font=("Segoe UI", 14, "bold"), anchor="w",
        )
        self.active_label.pack(side="left", padx=16, pady=12)
        self.active_sub = ctk.CTkLabel(
            active_bar, text="", text_color=COLOR_TEXT_MUTED,
            font=("Segoe UI", 11), anchor="w",
        )
        self.active_sub.pack(side="left", padx=4, pady=12)
        tip(active_bar, "La 'partie active' est celle utilisée par défaut pour les Push/Export. "
                        "Change-la dans l'onglet 'Mes parties'.")

        # --- Bandeau "Tour" (verrou) ---
        lock_bar = ctk.CTkFrame(wrap, fg_color=COLOR_CARD, corner_radius=10,
                                border_width=1, border_color=COLOR_BORDER)
        lock_bar.pack(fill="x", padx=16, pady=4)
        left_lock = ctk.CTkFrame(lock_bar, fg_color="transparent")
        left_lock.pack(side="left", fill="x", expand=True)
        self.cloud_lock_big = ctk.CTkLabel(
            left_lock, text="🔓  Tour : libre",
            font=("Segoe UI", 14, "bold"), anchor="w",
        )
        self.cloud_lock_big.pack(anchor="w", padx=16, pady=(10, 0))
        self.cloud_lock_sub = ctk.CTkLabel(
            left_lock, text="", text_color=COLOR_TEXT_MUTED,
            font=("Segoe UI", 11), anchor="w",
        )
        self.cloud_lock_sub.pack(anchor="w", padx=16, pady=(0, 10))

        lock_btns = ctk.CTkFrame(lock_bar, fg_color="transparent")
        lock_btns.pack(side="right", padx=10, pady=8)
        b_take = ctk.CTkButton(
            lock_btns, text="🔒  Prendre", width=120, height=34,
            font=("Segoe UI", 11, "bold"),
            command=self._take, fg_color=ACTION_PUSH, hover_color="#3da76b",
        )
        b_take.pack(side="left", padx=3)
        tip(b_take, "Pose un verrou dans le dossier partagé avec ton pseudo. "
                    "Tant qu'il est en place, l'autre joueur sera averti s'il essaie de push.")
        b_rel = ctk.CTkButton(
            lock_btns, text="🔓  Libérer", width=120, height=34,
            font=("Segoe UI", 11, "bold"),
            command=self._release, fg_color=ACTION_RELEASE, hover_color="#946b45",
        )
        b_rel.pack(side="left", padx=3)
        tip(b_rel, "Retire le verrou pour que ton pote puisse héberger à son tour.")
        b_force = ctk.CTkButton(
            lock_btns, text="⚠", width=36, height=34,
            font=("Segoe UI", 14, "bold"),
            command=self._force_release, fg_color=ACTION_DANGER, hover_color="#cc5555",
        )
        b_force.pack(side="left", padx=3)
        tip(b_force, "Forcer la libération : à utiliser SEULEMENT si ton pote a oublié de libérer "
                     "le tour et qu'il est OK pour que tu prennes la main de force.")

        # --- Section CLOUD : 2 gros boutons côte à côte ---
        cloud_title = ctk.CTkLabel(
            wrap, text="☁   VIA LE DOSSIER PARTAGÉ",
            font=("Segoe UI", 11, "bold"), anchor="w", text_color=COLOR_TEXT_MUTED,
        )
        cloud_title.pack(fill="x", padx=20, pady=(14, 4))

        cloud_actions = ctk.CTkFrame(wrap, fg_color="transparent")
        cloud_actions.pack(fill="x", padx=16, pady=(0, 4))
        cloud_actions.grid_columnconfigure((0, 1), weight=1, uniform="cloud")

        b_pull = self._huge_btn(
            cloud_actions, "⬇", "Récupérer la save",
            "Pull la dernière version déposée par ton pote",
            self._pull, color=ACTION_PULL,
        )
        b_pull.grid(row=0, column=0, padx=6, pady=4, sticky="ew")

        b_push = self._huge_btn(
            cloud_actions, "⬆", "Envoyer ma session",
            "Push ta partie active dans le dossier partagé",
            self._push, color=ACTION_PUSH,
        )
        b_push.grid(row=0, column=1, padx=6, pady=4, sticky="ew")

        # --- Section ZIP : 2 gros boutons côte à côte ---
        zip_title = ctk.CTkLabel(
            wrap, text="✉   VIA FICHIER .ZIP  (mail, Drive, Discord, USB...)",
            font=("Segoe UI", 11, "bold"), anchor="w", text_color=COLOR_TEXT_MUTED,
        )
        zip_title.pack(fill="x", padx=20, pady=(14, 4))

        zip_actions = ctk.CTkFrame(wrap, fg_color="transparent")
        zip_actions.pack(fill="x", padx=16, pady=(0, 4))
        zip_actions.grid_columnconfigure((0, 1), weight=1, uniform="zip")

        b_import = self._huge_btn(
            zip_actions, "📥", "Importer un .zip",
            "Restaure une partie reçue de ton pote",
            self._import_file, color=ACTION_IMPORT,
        )
        b_import.grid(row=0, column=0, padx=6, pady=4, sticky="ew")

        b_export = self._huge_btn(
            zip_actions, "📤", "Exporter en .zip",
            "Crée un .zip de ta partie pour l'envoyer",
            self._export_active, color=ACTION_EXPORT,
        )
        b_export.grid(row=0, column=1, padx=6, pady=4, sticky="ew")

        # Dropdown caché pour compatibilité (sélection partie à exporter via menu)
        # On garde la variable mais elle n'est plus visible — l'export se base sur la partie active
        self.manual_save_var = ctk.StringVar()
        self.manual_save_menu = ctk.CTkOptionMenu(
            wrap, variable=self.manual_save_var, values=["(rescan...)"], width=1)
        # Pas pack — invisible

        # --- Actions avancées (repliables sous un seul bouton) ---
        more = ctk.CTkFrame(wrap, fg_color="transparent")
        more.pack(fill="x", padx=16, pady=(10, 4))
        # Frame qui contient les boutons avancés (toggle pack/unpack)
        self.advanced_actions_frame = ctk.CTkFrame(more, fg_color="transparent")
        # Pas pack par défaut : ces actions ne sont pas indispensables pour le quotidien
        self._advanced_actions_visible = False

        b_toggle_more = ctk.CTkButton(
            more, text="⋯  Plus d'options", height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
            command=self._toggle_advanced_actions,
        )
        b_toggle_more.pack(side="left", padx=3)
        self._b_toggle_more = b_toggle_more
        tip(b_toggle_more, "Affiche/cache : inspection d'un .zip, diff local/remote, "
                           "inspection d'une version précise. Utile en mode debug.")

        b_inspect = ctk.CTkButton(
            self.advanced_actions_frame, text="🔍  Inspecter un .zip", height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10), command=self._inspect_file,
        )
        b_inspect.pack(side="left", padx=3)
        tip(b_inspect, "Affiche le manifeste et le contenu d'un .zip sans rien installer.")

        b_diff = ctk.CTkButton(
            self.advanced_actions_frame, text="↔  Diff local / remote", height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10), command=self._preview_diff,
        )
        b_diff.pack(side="left", padx=3)
        tip(b_diff, "Compare ta save locale active à la dernière version partagée.")

        b_pick = ctk.CTkButton(
            self.advanced_actions_frame, text="🕓  Inspecter une version...", height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10), command=self._preview_pick,
        )
        b_pick.pack(side="left", padx=3)
        tip(b_pick, "Voir le contenu d'une version précise de l'historique avant de la pull.")

        # --- Historique + Détails (combinés en bas) ---
        bottom = ctk.CTkFrame(wrap, fg_color="transparent")
        bottom.pack(fill="both", expand=True, padx=16, pady=(8, 12))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)
        bottom.grid_rowconfigure(0, weight=1)

        # Historique à gauche
        hist_frame = ctk.CTkFrame(bottom, fg_color=COLOR_CARD, corner_radius=10,
                                  border_width=1, border_color=COLOR_BORDER)
        hist_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(
            hist_frame, text="📜   HISTORIQUE DES VERSIONS",
            font=("Segoe UI", 11, "bold"), anchor="w", text_color=COLOR_TEXT_MUTED,
        ).pack(fill="x", padx=12, pady=(10, 4))
        self.history_box = ctk.CTkTextbox(
            hist_frame, font=("Consolas", 10),
            fg_color=COLOR_BG, border_width=0,
        )
        self.history_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Détails / journal à droite (unifié cloud + manuel)
        det_frame = ctk.CTkFrame(bottom, fg_color=COLOR_CARD, corner_radius=10,
                                 border_width=1, border_color=COLOR_BORDER)
        det_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(
            det_frame, text="📋   DÉTAILS / JOURNAL",
            font=("Segoe UI", 11, "bold"), anchor="w", text_color=COLOR_TEXT_MUTED,
        ).pack(fill="x", padx=12, pady=(10, 4))
        self.preview_box = ctk.CTkTextbox(
            det_frame, font=("Consolas", 10),
            fg_color=COLOR_BG, border_width=0,
        )
        self.preview_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        # Alias pour les méthodes existantes
        self.cloud_preview = self.preview_box
        self.manual_preview = self.preview_box

    # =========================================================== TAB MES PARTIES
    def _build_tab_parties(self):
        wrap = self.tab_parties
        wrap.grid_columnconfigure(0, weight=1, minsize=360)
        wrap.grid_columnconfigure(1, weight=2)
        wrap.grid_rowconfigure(0, weight=1)

        # --- gauche : liste des saves ---
        left = ctk.CTkFrame(wrap, fg_color=COLOR_CARD, corner_radius=10,
                            border_width=1, border_color=COLOR_BORDER)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=4)

        header = ctk.CTkFrame(left, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 8))
        ctk.CTkLabel(
            header, text="🎮  TES PARTIES",
            font=("Segoe UI", 11, "bold"), text_color=COLOR_TEXT_MUTED,
        ).pack(side="left")
        b_rescan = ctk.CTkButton(
            header, text="↻ Rescan", width=86, height=26,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
            command=self.refresh_all,
        )
        b_rescan.pack(side="right")
        tip(b_rescan, "Relit le dossier Zomboid\\Saves\\Multiplayer\\ pour redétecter les saves.")

        self.saves_list_scroll = ctk.CTkScrollableFrame(left, fg_color=COLOR_BG, corner_radius=6)
        self.saves_list_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        self._save_cards: dict[str, ctk.CTkFrame] = {}

        # --- droite : détails ---
        right = ctk.CTkFrame(wrap, fg_color=COLOR_CARD, corner_radius=10,
                             border_width=1, border_color=COLOR_BORDER)
        right.grid(row=0, column=1, sticky="nsew", pady=4)

        self.detail_title = ctk.CTkLabel(
            right, text="Aucune partie sélectionnée",
            font=("Segoe UI", 18, "bold"), anchor="w",
        )
        self.detail_title.pack(fill="x", padx=16, pady=(14, 2))
        self.detail_subtitle = ctk.CTkLabel(
            right, text="", text_color=COLOR_TEXT_MUTED,
            font=("Segoe UI", 11), anchor="w",
        )
        self.detail_subtitle.pack(fill="x", padx=16, pady=(0, 10))

        # Boutons d'action — DEPLACES EN HAUT pour qu'ils sautent aux yeux
        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 10))
        self.btn_set_active = ctk.CTkButton(
            actions, text="⭐  Définir comme partie active",
            command=self._set_active, height=38,
            font=("Segoe UI", 11, "bold"),
            fg_color=ACTION_PULL, hover_color="#3690c5",
        )
        self.btn_set_active.pack(side="left", padx=3)
        tip(self.btn_set_active,
            "Sera utilisée par défaut pour les Push vers le dossier partagé et les Export .zip.")

        self.btn_export_this = ctk.CTkButton(
            actions, text="📤  Exporter en .zip",
            command=self._export_selected, height=38,
            font=("Segoe UI", 11, "bold"),
            fg_color=ACTION_EXPORT, hover_color="#48ad6d",
        )
        self.btn_export_this.pack(side="left", padx=3)
        tip(self.btn_export_this,
            "Crée un .zip auto-suffisant : monde + persos + config serveur. "
            "Tu pourras l'envoyer par mail, Drive, Discord, USB...")

        self.btn_push_this = ctk.CTkButton(
            actions, text="☁  Push cloud",
            command=self._push_selected, height=38,
            font=("Segoe UI", 11, "bold"),
            fg_color=ACTION_PUSH, hover_color="#3da76b",
        )
        self.btn_push_this.pack(side="left", padx=3)
        tip(self.btn_push_this,
            "Pousse un bundle complet de cette partie dans le dossier partagé.")

        # Bloc d'infos en grille (KV) — compact
        kv = ctk.CTkFrame(right, fg_color=COLOR_BG, corner_radius=8)
        kv.pack(fill="x", padx=16, pady=(4, 8))
        self.kv_labels: dict[str, ctk.CTkLabel] = {}
        rows = [
            ("type", "Type"),
            ("last_played", "Dernière session"),
            ("size", "Taille"),
            ("chunks", "Chunks"),
            ("structures", "Structures"),
            ("players", "Joueurs"),
            ("mods", "Mods"),
        ]
        for i, (key, label) in enumerate(rows):
            ctk.CTkLabel(
                kv, text=label, text_color=COLOR_TEXT_MUTED,
                anchor="w", font=("Segoe UI", 10),
            ).grid(row=i, column=0, sticky="w", padx=14, pady=4)
            v = ctk.CTkLabel(
                kv, text="—", anchor="w",
                font=("Segoe UI", 11, "bold"),
            )
            v.grid(row=i, column=1, sticky="w", padx=4, pady=4)
            self.kv_labels[key] = v
        kv.grid_columnconfigure(1, weight=1)

        # Compagnons — petites pilules en ligne
        comp = ctk.CTkFrame(right, fg_color=COLOR_BG, corner_radius=8)
        comp.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(
            comp, text="CONTENU DÉTECTÉ",
            anchor="w", font=("Segoe UI", 10, "bold"),
            text_color=COLOR_TEXT_MUTED,
        ).pack(anchor="w", padx=14, pady=(8, 4))
        comp_grid = ctk.CTkFrame(comp, fg_color="transparent")
        comp_grid.pack(fill="x", padx=12, pady=(0, 10))
        self.comp_pills: dict[str, ctk.CTkLabel] = {}
        labels = [
            ("save_dir", "Save", "Le monde joué : map, structures, items. Indispensable."),
            ("db", "DB persos", "Contient TES persos. Sans elle, vous repartez nus à zéro à la prochaine session."),
            ("server_ini", ".ini", "Mods, options serveur, mot de passe. Sans elle ton pote ne pourra pas rejoindre avec les mêmes mods."),
            ("server_sandbox", "Sandbox", "Réglages du jeu : nb de zombies, vitesse, etc."),
            ("server_spawn", "Spawn", "Zones de spawn personnalisées."),
        ]
        for i, (key, text, tooltip_text) in enumerate(labels):
            pill = ctk.CTkLabel(
                comp_grid, text=f"○  {text}",
                fg_color=COLOR_CARD, corner_radius=12,
                padx=12, pady=4, font=("Segoe UI", 10),
            )
            pill.grid(row=0, column=i, padx=3, pady=2, sticky="w")
            tip(pill, tooltip_text)
            self.comp_pills[key] = pill

        # Aide contextuelle
        self.detail_help = ctk.CTkLabel(
            right, text="", text_color=COLOR_TEXT_MUTED, anchor="w",
            font=("Segoe UI", 10), justify="left", wraplength=560,
        )
        self.detail_help.pack(fill="x", padx=16, pady=(4, 14))

    # ============================================================== TAB RÉGLAGES
    def _build_tab_settings(self):
        wrap = self.tab_settings

        # Form principal
        grid = ctk.CTkFrame(wrap, fg_color=COLOR_CARD, corner_radius=10,
                            border_width=1, border_color=COLOR_BORDER)
        grid.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(
            grid, text="👤   TON PSEUDO",
            font=("Segoe UI", 11, "bold"), anchor="w",
            text_color=COLOR_TEXT_MUTED,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 4))
        self.name_var = ctk.StringVar(value=self.cfg.player_name)
        e_name = ctk.CTkEntry(
            grid, textvariable=self.name_var, width=300, height=34,
            border_width=1, border_color=COLOR_BORDER,
        )
        e_name.grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 14))
        tip(e_name, "Affiché dans le verrou de tour et le nom des bundles, "
                    "pour que ton pote sache d'où vient le fichier.")

        ctk.CTkLabel(
            grid, text="☁   DOSSIER PARTAGÉ",
            font=("Segoe UI", 11, "bold"), anchor="w",
            text_color=COLOR_TEXT_MUTED,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=14, pady=(4, 4))
        self.folder_var = ctk.StringVar(value=self.cfg.shared_folder)
        e_folder = ctk.CTkEntry(
            grid, textvariable=self.folder_var, width=420, height=34,
            border_width=1, border_color=COLOR_BORDER,
        )
        e_folder.grid(row=3, column=0, sticky="w", padx=14, pady=(0, 14))
        tip(e_folder, "Un dossier déjà synchronisé entre toi et ton pote (Dropbox, "
                      "Google Drive Desktop, OneDrive). Toi et lui devez pointer vers le MÊME contenu.")
        b_detect = ctk.CTkButton(
            grid, text="🔍  Détecter", width=110, height=34,
            command=self._detect_cloud_folder,
            fg_color=ACTION_PULL, hover_color="#3690c5",
            font=("Segoe UI", 10),
        )
        b_detect.grid(row=3, column=1, padx=6, pady=(0, 14))
        tip(b_detect, "Cherche Dropbox / Google Drive / OneDrive sur ton PC et propose des suggestions.")
        b_browse = ctk.CTkButton(
            grid, text="📁  Parcourir...", width=120, height=34,
            command=self._browse,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_browse.grid(row=3, column=2, padx=6, pady=(0, 14))

        # --- Préférences avancées ---
        ctk.CTkLabel(
            grid, text="⚡   PRÉFÉRENCES",
            font=("Segoe UI", 11, "bold"), anchor="w",
            text_color=COLOR_TEXT_MUTED,
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=14, pady=(4, 4))
        self.auto_release_var = ctk.BooleanVar(value=self.cfg.auto_release_lock)
        cb_release = ctk.CTkCheckBox(
            grid, text="Libérer automatiquement le tour après un push",
            variable=self.auto_release_var, font=("Segoe UI", 11),
        )
        cb_release.grid(row=5, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 6))
        tip(cb_release, "Décoché : tu gardes le tour après ton push (rare).")

        self.watch_pz_var = ctk.BooleanVar(value=self.cfg.watch_pz_process)
        cb_watch = ctk.CTkCheckBox(
            grid, text="Détecter quand PZ se ferme et proposer un push automatique",
            variable=self.watch_pz_var, font=("Segoe UI", 11),
        )
        cb_watch.grid(row=6, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 6))
        tip(cb_watch, "Polling toutes les 15s. Affiche une popup quand tu fermes Project Zomboid.")

        # Webhook Discord
        ctk.CTkLabel(
            grid, text="💬  Webhook Discord (optionnel)",
            font=("Segoe UI", 10, "bold"), anchor="w",
            text_color=COLOR_TEXT_MUTED,
        ).grid(row=7, column=0, columnspan=3, sticky="w", padx=14, pady=(8, 2))
        self.webhook_var = ctk.StringVar(value=self.cfg.discord_webhook)
        e_webhook = ctk.CTkEntry(
            grid, textvariable=self.webhook_var, width=420, height=32,
            placeholder_text="https://discord.com/api/webhooks/...",
            border_width=1, border_color=COLOR_BORDER,
        )
        e_webhook.grid(row=8, column=0, sticky="w", padx=14, pady=(0, 12))
        tip(e_webhook,
            "Crée un webhook dans Server Settings → Integrations → Webhooks "
            "et colle l'URL ici. Une notif sera envoyée à chaque push.")
        b_test_wh = ctk.CTkButton(
            grid, text="🧪  Tester", width=110, height=32,
            command=self._test_webhook,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_test_wh.grid(row=8, column=1, padx=6, pady=(0, 12))

        # Boutons principaux — gros et visibles
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=8)
        b_save = ctk.CTkButton(
            btns, text="💾   Enregistrer les réglages",
            command=self._save_cfg, height=42,
            font=("Segoe UI", 12, "bold"),
            fg_color=ACTION_PUSH, hover_color="#3da76b",
        )
        b_save.pack(side="left", padx=4)
        tip(b_save, "Sauvegarde tes paramètres dans %APPDATA%\\PZSaveSync\\config.json")

        # Aide repliable
        help_box = ctk.CTkFrame(wrap, fg_color=COLOR_CARD, corner_radius=10,
                                border_width=1, border_color=COLOR_BORDER)
        help_box.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(
            help_box, text="ℹ   COMMENT METTRE EN PLACE LE DOSSIER PARTAGÉ ?",
            font=("Segoe UI", 11, "bold"), anchor="w",
            text_color=COLOR_TEXT_MUTED,
        ).pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(
            help_box,
            text=(
                "1.  Crée un dossier sur Google Drive / Dropbox / OneDrive (ex. PZ_avec_pote).\n"
                "2.  Partage-le avec ton pote (droits d'écriture).\n"
                "3.  Active la synchro \"miroir\" / \"disponible hors ligne\".\n"
                "4.  Vous pointez chacun ce chemin local ci-dessus."
            ),
            justify="left", anchor="w",
            font=("Segoe UI", 11), text_color=COLOR_TEXT,
        ).pack(fill="x", padx=14, pady=(0, 14))

        # Actions secondaires
        adv = ctk.CTkFrame(wrap, fg_color="transparent")
        adv.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(
            adv, text="OUTILS",
            font=("Segoe UI", 10, "bold"),
            text_color=COLOR_TEXT_MUTED, anchor="w",
        ).pack(fill="x", padx=4, pady=(0, 6))

        adv_btns = ctk.CTkFrame(adv, fg_color="transparent")
        adv_btns.pack(fill="x")
        b_build = ctk.CTkButton(
            adv_btns, text="🛠  Build .exe",
            command=self._build_exe, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_build.pack(side="left", padx=3)
        tip(b_build, "Génère un exécutable Windows autonome (PyInstaller) pour le filer "
                     "à ton pote sans qu'il ait à installer Python. Prend 1-3 minutes.")
        b_backups = ctk.CTkButton(
            adv_btns, text="📁  Ouvrir backups",
            command=self._open_backups, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_backups.pack(side="left", padx=3)
        tip(b_backups, f"Ouvre {LOCAL_BACKUPS} dans l'Explorateur Windows. "
                       "C'est là que vont les sauvegardes auto avant chaque import.")
        b_restore = ctk.CTkButton(
            adv_btns, text="↩  Restaurer un backup",
            command=self._restore_backup_prompt, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_restore.pack(side="left", padx=3)
        tip(b_restore, "Restaure une save (monde + DB + config) depuis un backup local. "
                       "Idéal si tu viens de pull/import par erreur. Un backup de l'état "
                       "actuel est fait avant la restauration.")
        b_prune = ctk.CTkButton(
            adv_btns, text="🧹  Nettoyer historique",
            command=self._prune_versions_prompt, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_prune.pack(side="left", padx=3)
        tip(b_prune, "Supprime les anciennes versions du dossier partagé "
                     "pour économiser de l'espace cloud.")
        b_wizard = ctk.CTkButton(
            adv_btns, text="🎯  Relancer le wizard",
            command=self._show_onboarding, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_wizard.pack(side="left", padx=3)
        tip(b_wizard, "Relance le wizard d'onboarding pour reconfigurer.")

        b_show_help = ctk.CTkButton(
            adv_btns, text="❓  Réafficher l'aide",
            command=self._show_help_banner, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_show_help.pack(side="left", padx=3)
        tip(b_show_help, "Réaffiche la bannière 'Comment ça marche' en haut de l'onglet Partager.")

        b_repo_check = ctk.CTkButton(
            adv_btns, text="🩺  Vérifier le repo cloud",
            command=self._repo_health_check, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_repo_check.pack(side="left", padx=3)
        tip(b_repo_check, "Vérifie l'intégrité du dossier partagé : détecte les .zip "
                          "orphelins (présents mais invisibles), les entrées sans "
                          ".zip physique, et les .tmp résiduels. Propose de réparer.")

        # Deuxième rangée d'outils
        adv_btns2 = ctk.CTkFrame(adv, fg_color="transparent")
        adv_btns2.pack(fill="x", pady=(4, 0))
        b_update = ctk.CTkButton(
            adv_btns2, text="🆕  Vérifier les MAJ",
            command=self._manual_update_check, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_update.pack(side="left", padx=3)
        tip(b_update, "Interroge GitHub Releases pour savoir s'il y a une nouvelle version.")
        b_logs = ctk.CTkButton(
            adv_btns2, text="📝  Voir logs",
            command=log_mod.open_logs_folder, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_logs.pack(side="left", padx=3)
        tip(b_logs, f"Ouvre le dossier de logs ({log_mod.LOGS_DIR}). "
                    "Joins le dernier fichier à ton bug report.")
        b_remove_profile = ctk.CTkButton(
            adv_btns2, text="🗑  Supprimer ce profil",
            command=self._remove_profile_prompt, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_remove_profile.pack(side="left", padx=3)
        tip(b_remove_profile, "Supprime le profil actif (un autre devra être actif).")

    # =================================================================== util
    def _huge_btn(self, parent, icon, title, sub, cmd, color="#1f4a7a"):
        """Bouton 'mega' avec icône énorme, titre et sous-titre. Tout est cliquable."""
        hover_color = self._lighten(color, 0.10)
        f = ctk.CTkFrame(
            parent, fg_color=color, corner_radius=12, height=112,
            border_width=1, border_color=self._lighten(color, 0.15),
        )
        f.pack_propagate(False)

        inner = ctk.CTkFrame(f, fg_color="transparent")
        inner.pack(expand=True, fill="both", padx=16, pady=12)

        # Icône énorme
        l_icon = ctk.CTkLabel(
            inner, text=icon, font=("Segoe UI Emoji", 34, "bold"),
            fg_color="transparent",
        )
        l_icon.pack(side="left", padx=(4, 14))

        # Titre + sous-titre
        text_block = ctk.CTkFrame(inner, fg_color="transparent")
        text_block.pack(side="left", fill="both", expand=True)
        l_title = ctk.CTkLabel(
            text_block, text=title,
            font=("Segoe UI", 15, "bold"),
            anchor="w", fg_color="transparent",
        )
        l_title.pack(anchor="w", fill="x")
        l_sub = ctk.CTkLabel(
            text_block, text=sub,
            font=("Segoe UI", 10),
            text_color="#e6ecf2", anchor="w",
            fg_color="transparent", justify="left",
        )
        l_sub.pack(anchor="w", fill="x", pady=(3, 0))

        # Tout cliquable + hover doux (changement de couleur de fond, pas de border)
        def _enter(_e, fr=f):
            fr.configure(fg_color=hover_color)

        def _leave(_e, fr=f, c=color):
            fr.configure(fg_color=c)

        for w in [f, inner, l_icon, text_block, l_title, l_sub]:
            w.bind("<Button-1>", lambda _e: cmd())
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
        return f

    @staticmethod
    def _lighten(hex_color: str, factor: float = 0.1) -> str:
        """Éclaircit une couleur hex (#rrggbb) d'un facteur (0..1)."""
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = min(255, int(r + (255 - r) * factor))
            g = min(255, int(g + (255 - g) * factor))
            b = min(255, int(b + (255 - b) * factor))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    @staticmethod
    def _tint(base_hex: str, tint_hex: str, factor: float = 0.2) -> str:
        """Mélange base_hex avec tint_hex selon factor (0=base, 1=tint)."""
        try:
            b = base_hex.lstrip("#")
            t = tint_hex.lstrip("#")
            br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
            tr, tg, tb = int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
            r = int(br + (tr - br) * factor)
            g = int(bg + (tg - bg) * factor)
            bl = int(bb + (tb - bb) * factor)
            return f"#{r:02x}{g:02x}{bl:02x}"
        except Exception:
            return base_hex

    def _export_active(self):
        """Bouton 'Exporter en .zip' du tab Partager — exporte la partie active."""
        name = self.cfg.save_name
        if not name:
            # Pas de partie active : on prend une transférable au pif si possible
            options = [e.name for e in self._save_entries if e.transferable]
            if not options:
                messagebox.showerror(
                    "Aucune partie à exporter",
                    "Aucune partie hébergée localement n'a été trouvée. "
                    "Va dans l'onglet 'Mes parties' pour vérifier.")
                return
            if len(options) == 1:
                name = options[0]
            else:
                messagebox.showinfo(
                    "Partie active manquante",
                    "Sélectionne d'abord une partie active dans l'onglet 'Mes parties'.")
                return
        self._do_export(name)

    def _browse(self):
        path = filedialog.askdirectory(title="Choisir le dossier partagé")
        if path:
            self.folder_var.set(path)

    def _save_cfg(self):
        self.cfg.player_name = self.name_var.get().strip()
        self.cfg.shared_folder = self.folder_var.get().strip()
        self.cfg.save_type = "Multiplayer"
        # Préférences avancées (si les widgets existent)
        if hasattr(self, "auto_release_var"):
            self.cfg.auto_release_lock = bool(self.auto_release_var.get())
        if hasattr(self, "watch_pz_var"):
            self.cfg.watch_pz_process = bool(self.watch_pz_var.get())
        if hasattr(self, "webhook_var"):
            self.cfg.discord_webhook = self.webhook_var.get().strip()
        config.save(self.cfg)
        self.refresh_all()
        messagebox.showinfo("OK", "Configuration enregistrée.")

    def _repo(self) -> SharedRepo | None:
        if not self.cfg.shared_folder:
            messagebox.showerror("Erreur",
                                 "Configure d'abord un dossier partagé (onglet Réglages) "
                                 "ou utilise le mode .zip.")
            return None
        try:
            repo = SharedRepo(Path(self.cfg.shared_folder))
            repo.init_if_needed()
            return repo
        except Exception as e:
            messagebox.showerror("Erreur", f"Dossier partagé inaccessible : {e}")
            return None

    def _require_name(self) -> str | None:
        if not self.cfg.player_name:
            messagebox.showerror("Erreur",
                                 "Renseigne ton pseudo dans l'onglet Réglages.")
            return None
        return self.cfg.player_name

    def _open_backups(self):
        LOCAL_BACKUPS.mkdir(parents=True, exist_ok=True)
        _open_path(LOCAL_BACKUPS)

    def _dismiss_help_banner(self):
        """Ferme la bannière d'aide et persiste la préférence."""
        try:
            self.help_banner.pack_forget()
        except Exception:
            pass
        self.cfg.hide_help_banner = True
        config.save(self.cfg)

    def _repo_health_check(self):
        """Vérifie l'intégrité du dossier partagé et propose des corrections."""
        repo = self._repo()
        if not repo:
            return
        try:
            health = repo.health_check()
        except Exception as e:
            messagebox.showerror("Health check", f"Erreur : {e}")
            return
        if health.is_healthy:
            messagebox.showinfo(
                "Repo cloud OK",
                "✅ Aucun problème détecté.\n\n"
                "Toutes les versions du manifest ont leur .zip physique, "
                "aucun .zip orphelin, aucun fichier .tmp résiduel.",
            )
            return

        # Construire le résumé + propositions
        lines = [
            "⚠ Problèmes détectés dans le dossier partagé :",
            "",
        ]
        if health.orphan_files:
            lines.append(f"🔸 {len(health.orphan_files)} .zip orphelin(s) — présents "
                         f"mais invisibles via Pull :")
            for n in health.orphan_files[:6]:
                lines.append(f"   • {n}")
            if len(health.orphan_files) > 6:
                lines.append(f"   … et {len(health.orphan_files) - 6} autre(s)")
            lines.append(
                f"   → {len(health.readable_orphans)} réintégrable(s) "
                f"automatiquement (lisible(s))."
            )
            lines.append("")
        if health.missing_files:
            lines.append(f"🔸 {len(health.missing_files)} entrée(s) sans .zip physique "
                         f"(synchro cloud échouée ou .zip supprimé manuellement) :")
            for n in health.missing_files[:6]:
                lines.append(f"   • {n}")
            if len(health.missing_files) > 6:
                lines.append(f"   … et {len(health.missing_files) - 6} autre(s)")
            lines.append("")
        if health.tmp_residues:
            lines.append(f"🔸 {len(health.tmp_residues)} fichier(s) .tmp résiduel(s).")
            lines.append("")
        lines.append("Réparer maintenant ?")
        lines.append("  • Réintégrer les orphelins lisibles dans le manifest")
        lines.append("  • Supprimer les entrées fantômes du manifest")
        lines.append("  • Nettoyer les .tmp")

        if not messagebox.askyesno("Repo cloud — anomalies", "\n".join(lines)):
            return

        # Réparation
        try:
            adopted = repo.adopt_orphans(health.readable_orphans)
            removed = repo.remove_missing_from_manifest(health.missing_files)
            tmp_cleaned = repo.cleanup_orphan_tmp_files()
            messagebox.showinfo(
                "Réparation effectuée",
                f"✅ {adopted} bundle(s) orphelin(s) réintégré(s).\n"
                f"✅ {removed} entrée(s) fantôme(s) retirée(s) du manifest.\n"
                f"✅ {len(tmp_cleaned)} fichier(s) .tmp nettoyé(s).",
            )
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Réparation", f"Erreur : {e}")

    def _toggle_advanced_actions(self):
        """Affiche/cache les boutons avancés (inspecter, diff, etc.)."""
        if self._advanced_actions_visible:
            self.advanced_actions_frame.pack_forget()
            self._b_toggle_more.configure(text="⋯  Plus d'options")
            self._advanced_actions_visible = False
        else:
            self.advanced_actions_frame.pack(side="left", padx=(8, 0))
            self._b_toggle_more.configure(text="✕  Moins d'options")
            self._advanced_actions_visible = True

    def _show_help_banner(self):
        """Réaffiche la bannière (depuis Réglages)."""
        self.cfg.hide_help_banner = False
        config.save(self.cfg)
        try:
            # Re-pack en haut de l'onglet, avant tout le reste
            self.help_banner.pack(
                fill="x", padx=16, pady=(16, 4), before=self.update_banner,
            )
        except Exception:
            try:
                self.help_banner.pack(fill="x", padx=16, pady=(16, 4))
            except Exception:
                pass
        # Bascule sur l'onglet Partager pour qu'on la voie
        try:
            self.tabs_widget.set("🔄  Partager")
        except Exception:
            pass

    def _restore_backup_prompt(self):
        """Affiche la liste des backups locaux et permet d'en restaurer un."""
        if self._block_if_pz_running("Restauration de backup"):
            return
        LOCAL_BACKUPS.mkdir(parents=True, exist_ok=True)
        backups = restore_mod.list_backups(LOCAL_BACKUPS)
        if not backups:
            messagebox.showinfo(
                "Restauration",
                f"Aucun backup local trouvé dans :\n{LOCAL_BACKUPS}\n\n"
                "Les backups sont créés automatiquement avant chaque pull/import.",
            )
            return
        BackupPicker(self, backups, on_pick=self._do_restore_backup)

    def _do_restore_backup(self, backup: "restore_mod.BackupEntry"):
        # Confirmation explicite — c'est une opération destructive de l'état courant
        details = []
        if backup.has_save_zip:
            details.append("• Monde (save.zip)")
        if backup.has_db:
            details.append(f"• DB joueurs ({backup.save_name}.db)")
        if backup.db_companions:
            details.append(f"• Compagnons SQLite : {', '.join(backup.db_companions)}")
        if backup.server_files:
            details.append(f"• Config serveur : {len(backup.server_files)} fichier(s)")
        msg = (
            f"Restaurer le backup :\n"
            f"   Save : {backup.save_name}\n"
            f"   Date : {backup.display_timestamp}\n"
            f"   Taille : {backup.size_bytes / 1024 / 1024:.1f} MB\n\n"
            f"Contenu :\n" + "\n".join(details) + "\n\n"
            f"⚠ Ton état actuel pour '{backup.save_name}' sera ÉCRASÉ.\n"
            f"Un backup pré-restauration est créé avant — récupérable.\n\nContinuer ?"
        )
        if not messagebox.askyesno("Restaurer", msg):
            return

        dlg = ProgressDialog(self, "Restauration en cours…")

        def worker(progress_cb):
            progress_cb("restore", 0, 1)
            r = restore_mod.restore_backup(
                backup, safety_backup_dir=LOCAL_BACKUPS,
            )
            progress_cb("restore", 1, 1)
            return r

        def on_done(report, err):
            if err:
                _log.error("Restauration échouée : %s", err)
                messagebox.showerror("Restauration", str(err))
                return
            lines = [
                "✅ Backup restauré avec succès",
                "",
                f"Save     : {report.save_name}",
                f"Dossier  : {report.save_dir}",
                f"DB       : {report.db_path or '(non incluse dans le backup)'}",
            ]
            if report.db_companions_restored:
                lines.append(
                    f"DB WAL   : {', '.join(p.name for p in report.db_companions_restored)}"
                )
            lines.append(f"Config   : {len(report.server_files)} fichier(s) serveur")
            for f in report.server_files:
                lines.append(f"   • {f.name}")
            if report.pre_restore_backup:
                lines.append("")
                lines.append(f"💾 Backup pré-restauration : {report.pre_restore_backup}")
            lines.append("")
            lines.append("→ Lance Project Zomboid → Multijoueur → Héberger.")
            text = "\n".join(lines)
            self.preview_box.delete("1.0", "end")
            self.preview_box.insert("end", text)
            self.cfg.save_name = report.save_name
            config.save(self.cfg)
            self.refresh_all()
            notifications.notify(
                "PZ SaveSync — Restauration OK",
                f"Save '{report.save_name}' restaurée depuis le backup.",
            )
            _log.info("Restore OK : %s depuis %s", report.save_name, backup.path)

        dlg.run_in_thread(worker, on_done=on_done)

    # =============================================================== refresh
    def refresh_all(self):
        # Profil dropdown
        if hasattr(self, "profile_menu"):
            labels = self.cfg.profile_labels()
            self.profile_menu.configure(values=labels)
            self.profile_var.set(self.cfg.current.name or self.cfg.active_profile)

        # Header
        if self.cfg.player_name:
            self.header_user.configure(
                text=f"👤  {self.cfg.player_name}", text_color=COLOR_TEXT,
            )
        else:
            self.header_user.configure(
                text="👤  (pseudo non défini)", text_color=COLOR_TEXT_MUTED,
            )
        if self.cfg.shared_folder:
            shown = self.cfg.shared_folder
            if len(shown) > 42:
                shown = "…" + shown[-39:]
            self.header_cloud.configure(text=f"☁  {shown}", text_color=COLOR_TEXT)
        else:
            self.header_cloud.configure(
                text="☁  (non configuré)", text_color=COLOR_TEXT_MUTED,
            )

        # Saves
        self._save_entries = saves.list_all_with_info()

        # Bandeau "Partie active"
        if self.cfg.save_name:
            active_entry = next((e for e in self._save_entries if e.name == self.cfg.save_name), None)
            self.active_label.configure(
                text=f"⭐  Partie active : {self.cfg.save_name}",
                text_color=COLOR_STAR,
            )
            if active_entry:
                size_mb = active_entry.info.size_mb
                self.active_sub.configure(
                    text=f"  {size_mb:.1f} MB  •  dernière session : "
                         f"{(active_entry.info.last_played or '—').replace('T', ' ')}")
            else:
                self.active_sub.configure(text="  (introuvable localement)")
        else:
            self.active_label.configure(
                text="⭐  Aucune partie active", text_color=COLOR_TEXT,
            )
            self.active_sub.configure(text="  → Onglet 'Mes parties' pour en choisir une")

        # Liste cartes
        for c in self._save_cards.values():
            c.destroy()
        self._save_cards.clear()
        if not self._save_entries:
            empty = ctk.CTkFrame(self.saves_list_scroll, fg_color="transparent")
            empty.pack(pady=24, padx=10, fill="x")
            ctk.CTkLabel(
                empty, text="🔭", font=("Segoe UI Emoji", 32),
                text_color=COLOR_TEXT_DIM,
            ).pack()
            ctk.CTkLabel(
                empty,
                text="Aucune save trouvée.\nHéberge une partie dans Project Zomboid d'abord.",
                text_color=COLOR_TEXT_MUTED, font=("Segoe UI", 11),
                justify="center",
            ).pack(pady=(8, 0))
        else:
            for entry in self._save_entries:
                self._save_cards[entry.name] = self._make_card(entry)

        # Dropdown caché (compatibilité)
        manual_options = [e.name for e in self._save_entries if e.transferable]
        if not manual_options:
            manual_options = ["(aucune partie hébergée à exporter)"]
        self.manual_save_menu.configure(values=manual_options)
        if self.manual_save_var.get() not in manual_options:
            self.manual_save_var.set(manual_options[0])

        # Sélection auto
        if self._selected_save and self._selected_save in self._save_cards:
            self._select_save(self._selected_save)
        elif self._save_entries:
            self._select_save(self._save_entries[0].name)
        else:
            self._update_detail(None)

        # Cloud
        self._refresh_cloud()

        # Bannière "save en retard"
        self._refresh_late_banner()

    def _make_card(self, entry: saves.SaveEntry) -> ctk.CTkFrame:
        is_selected = entry.name == self._selected_save
        is_active = entry.name == self.cfg.save_name
        is_transferable = entry.transferable
        # Couleurs grisées pour les saves non-transférables
        if is_selected:
            bg = COLOR_CARD_SEL
        elif is_transferable:
            bg = COLOR_CARD
        else:
            # Fond plus sombre que COLOR_CARD pour signaler "désactivé"
            bg = "#1c1e23"
        border_color = COLOR_STAR if is_active else (
            "#4d7eb8" if is_selected else COLOR_BORDER
        )
        card = ctk.CTkFrame(
            self.saves_list_scroll, fg_color=bg, corner_radius=8,
            border_width=1, border_color=border_color,
        )
        card.pack(fill="x", padx=4, pady=4)

        # Couleurs du texte selon transférabilité
        title_color = COLOR_TEXT if is_transferable or is_selected else COLOR_TEXT_DIM
        sub_color = (
            COLOR_TEXT if is_selected
            else ("#bcbfc6" if is_transferable else COLOR_TEXT_DIM)
        )

        icon = "🌍" if entry.is_server_save else ("👤" if entry.is_client_save else "❓")
        line1 = ctk.CTkFrame(card, fg_color="transparent")
        line1.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            line1, text=f"{icon}  {entry.name}",
            font=("Segoe UI", 12, "bold"), anchor="w",
            text_color=title_color,
        ).pack(side="left")

        if is_active:
            star = ctk.CTkLabel(
                line1, text="★ ACTIVE",
                fg_color=COLOR_STAR, text_color="#2b1f00",
                corner_radius=8, padx=8, pady=1,
                font=("Segoe UI", 9, "bold"),
            )
            star.pack(side="right")
            tip(star, "C'est ta partie active : utilisée par défaut pour les Push/Export.")

        # Sous-ligne infos compacte
        size_mb = entry.info.size_mb
        last = (entry.info.last_played or "—").replace("T", " ")
        players = ", ".join(entry.info.players) if entry.info.players else "—"
        sub = f"{size_mb:.1f} MB  •  {entry.info.map_chunks} chunks  •  {players}\n{last}"
        ctk.CTkLabel(
            card, text=sub, font=("Segoe UI", 10),
            text_color=sub_color,
            anchor="w", justify="left",
        ).pack(fill="x", padx=12, pady=(2, 4))

        # Tag transférable (compact)
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.pack(fill="x", padx=12, pady=(0, 10))
        if is_transferable:
            t = ctk.CTkLabel(
                bar, text="✓  transférable",
                text_color=COLOR_OK, font=("Segoe UI", 9, "bold"),
            )
            t.pack(side="left")
            tip(t, "Cette partie est un serveur multi hébergé localement : on peut bundler "
                   "save + DB + config et la transférer à ton pote.")
        else:
            t = ctk.CTkLabel(
                bar, text="🚫  non exportable",
                text_color=COLOR_TEXT_DIM, font=("Segoe UI", 9, "bold"),
            )
            t.pack(side="left")
            tip(t, "Ce dossier est probablement une save client (toi qui rejoins un serveur), "
                   "pas un serveur que tu héberges. Tu peux la consulter mais pas l'envoyer "
                   "à un pote — il faut être l'hôte.")

        def on_click(_e=None, n=entry.name):
            self._select_save(n)

        # Hover doux pour les cartes non-sélectionnées (encore plus discret pour les grisées)
        if is_selected:
            hover_bg = bg
        elif is_transferable:
            hover_bg = COLOR_CARD_HOVER
        else:
            hover_bg = "#23262c"  # à peine plus clair que #1c1e23

        def _enter(_e, c=card, b=hover_bg):
            c.configure(fg_color=b)

        def _leave(_e, c=card, b=bg):
            c.configure(fg_color=b)

        for w in [card] + self._all_descendants(card):
            w.bind("<Button-1>", on_click)
            if not is_selected:
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
        return card

    def _all_descendants(self, w) -> list:
        res = []
        for c in w.winfo_children():
            res.append(c)
            res.extend(self._all_descendants(c))
        return res

    def _select_save(self, name: str):
        self._selected_save = name
        for n, card in self._save_cards.items():
            if n == name:
                card.configure(fg_color=COLOR_CARD_SEL)
            else:
                # Couleur de fond selon transférabilité (cohérent avec _make_card)
                entry = next((e for e in self._save_entries if e.name == n), None)
                is_transferable = entry.transferable if entry else True
                card.configure(
                    fg_color=COLOR_CARD if is_transferable else "#1c1e23"
                )
        entry = next((e for e in self._save_entries if e.name == name), None)
        self._update_detail(entry)

    def _update_detail(self, entry: saves.SaveEntry | None):
        if entry is None:
            self.detail_title.configure(text="Aucune partie sélectionnée")
            self.detail_subtitle.configure(text="")
            for v in self.kv_labels.values():
                v.configure(text="—")
            for p in self.comp_pills.values():
                t = p.cget("text")
                t = t.replace("✓  ", "○  ").replace("✗  ", "○  ")
                p.configure(text=t, text_color=COLOR_TEXT_MUTED, fg_color=COLOR_CARD)
            self.detail_help.configure(text="")
            self.btn_set_active.configure(state="disabled")
            self.btn_export_this.configure(state="disabled")
            self.btn_push_this.configure(state="disabled")
            return

        i = entry.info
        title = f"{'🌍' if entry.is_server_save else '👤' if entry.is_client_save else '❓'}  {entry.name}"
        self.detail_title.configure(text=title)
        if entry.is_server_save:
            subt = "Save de serveur hébergée localement — partageable"
        elif entry.is_client_save:
            subt = "Save client (toi en tant que joueur connecté) — pas partageable"
        else:
            subt = "Type indéterminé"
        self.detail_subtitle.configure(text=subt)

        self.kv_labels["type"].configure(text=i.kind)
        self.kv_labels["last_played"].configure(text=(i.last_played or "—").replace("T", " "))
        self.kv_labels["size"].configure(text=f"{i.size_mb:.1f} MB  •  {i.file_count} fichiers")
        self.kv_labels["chunks"].configure(text=f"{i.map_chunks} (carte) + {i.chunkdata_files} (chunkdata)")
        self.kv_labels["structures"].configure(text=f"{i.structures}")
        plist = ", ".join(i.players) if i.players else "—"
        src = f"  (source: {i.players_source})" if i.players_source else ""
        self.kv_labels["players"].configure(text=plist + src)

        # Mods : lus depuis le .ini compagnon si présent
        ini_path = entry.companions.get("server_ini")
        if ini_path:
            mods, workshop = bundle_mod.parse_ini_mods(ini_path)
            if mods or workshop:
                parts = []
                if mods:
                    parts.append(f"{len(mods)} mod(s)")
                if workshop:
                    parts.append(f"{len(workshop)} Workshop ID(s)")
                self.kv_labels["mods"].configure(text=" + ".join(parts))
            else:
                self.kv_labels["mods"].configure(text="aucun")
        else:
            self.kv_labels["mods"].configure(text="(pas de .ini)")

        status = entry.companions_status
        labels = {
            "save_dir": "Save",
            "db": "DB persos",
            "server_ini": ".ini",
            "server_sandbox": "Sandbox",
            "server_spawn": "Spawn",
        }
        for key, label in labels.items():
            ok = status.get(key, False)
            mark = "✓" if ok else "✗"
            color_fg = COLOR_OK if ok else COLOR_BAD
            bg = self._tint(COLOR_CARD, color_fg, 0.20) if ok else COLOR_CARD
            pill = self.comp_pills[key]
            pill.configure(text=f"{mark}  {label}", text_color=color_fg, fg_color=bg)

        if entry.transferable:
            missing = [labels[k] for k, v in status.items() if not v and k != "save_dir"]
            if missing:
                self.detail_help.configure(
                    text="⚠ Compagnons manquants : " + ", ".join(missing) +
                         ". La partie peut être transférée, mais ton pote risque "
                         "d'avoir une config serveur incomplète."
                )
            else:
                self.detail_help.configure(
                    text="✓ Tout est prêt. Tu peux exporter en .zip ou pousser sur le cloud."
                )
        else:
            self.detail_help.configure(
                text="ℹ Cette partie n'est pas hébergée localement (sans doute un cache "
                     "de connexion à un serveur). Seules les parties hébergées peuvent être transférées."
            )

        self.btn_set_active.configure(state="normal")
        self.btn_export_this.configure(state="normal" if entry.transferable else "disabled")
        self.btn_push_this.configure(state="normal" if entry.transferable else "disabled")

    # ----- actions sur la save sélectionnée -----
    def _set_active(self):
        if not self._selected_save:
            return
        self.cfg.save_name = self._selected_save
        config.save(self.cfg)
        self.refresh_all()
        messagebox.showinfo("Partie active",
                            f"« {self._selected_save} » est maintenant ta partie active.")

    def _export_selected(self):
        if not self._selected_save:
            return
        self._do_export(self._selected_save)

    def _push_selected(self):
        if not self._selected_save:
            return
        self._do_push(self._selected_save)

    def _export_from_dropdown(self):
        name = self.manual_save_var.get()
        if not name or name.startswith("("):
            messagebox.showerror("Erreur", "Sélectionne une partie à exporter.")
            return
        self._do_export(name)

    def _do_export(self, save_name: str, target_box=None):
        name = self._require_name()
        if not name:
            return
        if self._block_if_pz_running("Export"):
            return
        default = f"PZ_{save_name}_{name}.zip"
        path = filedialog.asksaveasfilename(
            title=f"Exporter la partie '{save_name}' vers...",
            defaultextension=".zip",
            initialfile=default,
            filetypes=[("Bundle PZSaveSync", "*.zip")],
        )
        if not path:
            return
        note = ctk.CTkInputDialog(text="Note pour ton pote (optionnel) :",
                                  title="Exporter").get_input() or ""

        dlg = ProgressDialog(self, "Export en cours…")

        def worker(progress_cb):
            return bundle_mod.build_bundle(
                save_name=save_name, out_zip=Path(path),
                created_by=name, note=note, progress=progress_cb,
            )

        def on_done(m, err):
            if err:
                messagebox.showerror("Export", str(err))
                return
            size_mb = Path(path).stat().st_size / 1024 / 1024
            text = (
                "✅  Bundle exporté avec succès !\n\n"
                + bundle_mod.summarize_manifest(m)
                + f"\n\nFichier : {path}\nTaille  : {size_mb:.1f} MB\n\n"
                "→ Tu peux maintenant l'envoyer :\n"
                "   • Gmail (Drive auto si > 25 MB)\n"
                "   • WeTransfer / Smash\n"
                "   • Google Drive partagé\n"
                "   • Discord (≤ 25 MB sans Nitro)\n"
                "   • Clé USB"
            )
            box = target_box or self.preview_box
            box.delete("1.0", "end")
            box.insert("end", text)
            if messagebox.askyesno("Exporté", f"Ouvrir le dossier contenant le fichier ?\n\n{path}"):
                _open_path(Path(path).parent)

        dlg.run_in_thread(worker, on_done=on_done)

    def _do_push(self, save_name: str):
        name = self._require_name()
        repo = self._repo()
        if not name or not repo:
            return
        if self._block_if_pz_running("Push"):
            return
        lock = repo.get_lock()
        if lock and lock.holder != name:
            if not messagebox.askyesno("Verrou",
                                       f"Le tour est à {lock.holder}. Pousser quand même ?"):
                return
        # Dialog enrichi : note + checkbox "libérer le tour après"
        opts = PushOptionsDialog(self, default_release=self.cfg.auto_release_lock)
        self.wait_window(opts)
        if not opts.ok:
            return
        note = opts.note
        release_after = opts.release_after

        # Push en thread avec progress dialog
        dlg = ProgressDialog(self, "Push en cours…")

        def worker(progress_cb):
            return repo.push_bundle(
                save_name=save_name,
                uploaded_by=name,
                note=note,
                progress=progress_cb,
            )

        def on_done(v, err):
            if err:
                messagebox.showerror("Push", str(err))
                return
            # Auto-release du tour
            if release_after:
                try:
                    repo.release_lock(name)
                except Exception:
                    pass
            # Auto-purge si configurée — IMPORTANT : scoped à save_name pour ne
            # pas supprimer les versions des AUTRES saves du repo (un repo
            # partagé peut contenir plusieurs mondes, ex: 'Gitano_Z' + 'Test').
            if self.cfg.keep_last_n_versions and self.cfg.keep_last_n_versions > 0:
                try:
                    repo.prune_versions(
                        keep_last_n=self.cfg.keep_last_n_versions,
                        save_name=save_name,
                    )
                except Exception:
                    pass
            # Webhook Discord
            if self.cfg.discord_webhook:
                try:
                    discord_webhook.notify_push(
                        self.cfg.discord_webhook,
                        player=name,
                        save_name=save_name,
                        size_mb=v.size_bytes / 1024 / 1024,
                        note=note,
                        versions_count=len(repo.list_versions()),
                    )
                except Exception:
                    pass
            messagebox.showinfo(
                "Push réussi",
                f"Bundle envoyé : {v.filename}\n"
                f"Taille : {v.size_bytes/1024/1024:.1f} MB\n"
                f"DB joueurs : {'oui' if v.has_db else 'NON'}\n"
                f"Config serveur : {len(v.server_files or [])} fichier(s)"
                + ("\n🔓 Tour libéré." if release_after else "")
            )
            notifications.notify(
                "PZ SaveSync — Push OK",
                f"Bundle {save_name} ({v.size_bytes/1024/1024:.0f} MB) envoyé.",
            )
            _log.info("Push OK : %s", v.filename)
            self.refresh_all()

        dlg.run_in_thread(worker, on_done=on_done)

    # ====================================================== cloud / history
    def _refresh_cloud(self):
        if not self.cfg.shared_folder:
            self.cloud_lock_big.configure(
                text="🔓  Dossier partagé non configuré",
                text_color=COLOR_TEXT_MUTED,
            )
            self.cloud_lock_sub.configure(text="Onglet Réglages pour le définir.")
            self.history_box.delete("1.0", "end")
            if hasattr(self, "footer_status"):
                self.footer_status.configure(
                    text="dossier partagé non configuré",
                    text_color=COLOR_TEXT_DIM,
                )
            return
        try:
            repo = SharedRepo(Path(self.cfg.shared_folder))
            repo.init_if_needed()
        except Exception as e:
            self.cloud_lock_big.configure(text=f"⚠  {e}", text_color=COLOR_BAD)
            self.cloud_lock_sub.configure(text="")
            if hasattr(self, "footer_status"):
                self.footer_status.configure(
                    text="dossier partagé inaccessible", text_color=COLOR_BAD,
                )
            return

        lock = repo.get_lock()
        if lock:
            self.cloud_lock_big.configure(
                text=f"🔒  Tour pris par {lock.holder}", text_color=COLOR_WARN,
            )
            self.cloud_lock_sub.configure(
                text=f"Depuis {lock.taken_at}" + (f" — {lock.note}" if lock.note else ""))
        else:
            self.cloud_lock_big.configure(text="🔓  Tour libre", text_color=COLOR_OK)
            self.cloud_lock_sub.configure(text="N'importe qui peut prendre la main.")

        self.history_box.delete("1.0", "end")
        versions = list(reversed(repo.list_versions()))
        for v in versions:
            size_mb = v.size_bytes / (1024 * 1024)
            line = (f"{v.uploaded_at}  {v.uploaded_by:>10}  "
                    f"[{v.save_name:<14}] {size_mb:6.1f} MB  "
                    f"db={'Y' if v.has_db else 'N'}  srv={len(v.server_files or [])}  "
                    f"{v.filename}")
            if v.note:
                line += f"  — {v.note}"
            self.history_box.insert("end", line + "\n")

        if hasattr(self, "footer_status"):
            count = len(versions)
            if count == 0:
                self.footer_status.configure(
                    text="dossier partagé prêt — 0 version",
                    text_color=COLOR_TEXT_DIM,
                )
            else:
                self.footer_status.configure(
                    text=f"dossier partagé OK — {count} version(s)",
                    text_color=COLOR_OK,
                )

    # ----- cloud actions -----
    def _take(self):
        name = self._require_name(); repo = self._repo()
        if not name or not repo: return
        try: repo.take_lock(name); self.refresh_all()
        except Exception as e: messagebox.showerror("Verrou", str(e))

    def _release(self):
        name = self._require_name(); repo = self._repo()
        if not name or not repo: return
        try: repo.release_lock(name); self.refresh_all()
        except Exception as e: messagebox.showerror("Verrou", str(e))

    def _force_release(self):
        repo = self._repo()
        if not repo: return
        if not messagebox.askyesno("Forcer", "Forcer la libération du verrou ?"):
            return
        # On utilise le pseudo de l'user pour tracer qui a forcé (utile dans
        # les logs / un futur webhook). Le `force=True` bypasse la vérif holder.
        holder = self.cfg.player_name or "*"
        repo.release_lock(holder=holder, force=True)
        _log.info("Force-release du verrou par %s", holder)
        self.refresh_all()

    def _push(self):
        save = self.cfg.save_name
        if not save:
            messagebox.showerror("Erreur",
                                 "Aucune partie active. Va dans l'onglet 'Mes parties', "
                                 "sélectionne une partie et clique 'Définir comme partie active'.")
            return
        self._do_push(save)

    def _pull(self):
        repo = self._repo()
        if not repo: return
        if self._block_if_pz_running("Pull"):
            return
        latest = repo.latest_version()
        if not latest:
            messagebox.showinfo("Pull", "Aucune version disponible dans le dossier partagé.")
            return
        msg = (
            f"Restaurer le bundle [{latest.save_name}]\n"
            f"Fichier : {latest.filename}\n"
            f"Uploadé par {latest.uploaded_by} le {latest.uploaded_at}\n\n"
            f"⚠ Va écraser ces fichiers locaux (backup auto avant) :\n"
            f"   • Zomboid\\Saves\\Multiplayer\\{latest.save_name}\\\n"
            f"   • Zomboid\\db\\{latest.save_name}.db\n"
            f"   • Zomboid\\Server\\{latest.save_name}.* (config serveur)\n\n"
            f"Backups dans : {LOCAL_BACKUPS}\n\nContinuer ?"
        )
        if not messagebox.askyesno("Pull", msg):
            return

        dlg = ProgressDialog(self, "Pull en cours…")

        def worker(progress_cb):
            progress_cb("verify", 0, 1)
            archive = repo.versions_dir / latest.filename
            ok, vmsg = bundle_mod.verify_bundle_integrity(archive)
            if not ok:
                raise ValueError(f"Vérification d'intégrité échouée : {vmsg}")
            progress_cb("verify", 1, 1)
            return repo.pull_bundle(latest, backup_dir=LOCAL_BACKUPS)

        def on_done(report, err):
            if err:
                _log.error("Pull échoué : %s", err)
                messagebox.showerror("Pull", str(err))
                return
            self._show_extract_report(report, box=self.preview_box)
            self._check_mods_for_report(report)
            self.cfg.save_name = report.save_name
            config.save(self.cfg)
            self.refresh_all()
            notifications.notify(
                "PZ SaveSync — Pull OK",
                f"Save '{report.save_name}' restaurée localement.",
            )
            _log.info("Pull OK : %s", report.save_name)

        dlg.run_in_thread(worker, on_done=on_done)

    def _preview_diff(self):
        repo = self._repo()
        if not repo: return
        latest = repo.latest_version()
        if not latest:
            self.preview_box.delete("1.0", "end")
            self.preview_box.insert("end", "Aucune version remote.")
            return
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("end", "Calcul du diff...\n")
        self.update_idletasks()
        try:
            save_path = bundle_mod.zomboid_root() / "Saves" / "Multiplayer" / latest.save_name
            local = inspector.inspect_save(save_path)
            remote = inspector.inspect_zip(repo.versions_dir / latest.filename)
            text = inspector.format_info(local, "── Local ──") + "\n\n"
            text += inspector.format_info(remote, f"── Remote ({latest.filename}) ──") + "\n\n"
            text += inspector.diff(local, remote)
            self.preview_box.delete("1.0", "end")
            self.preview_box.insert("end", text)
        except Exception as e:
            messagebox.showerror("Diff", str(e))

    def _preview_pick(self):
        repo = self._repo()
        if not repo: return
        versions = list(reversed(repo.list_versions()))
        if not versions:
            messagebox.showinfo("Aperçu version", "Aucune version disponible.")
            return
        VersionPicker(self, versions, on_pick=lambda v: self._preview_version(repo, v))

    def _preview_version(self, repo: SharedRepo, v: Version):
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("end", f"Inspection de {v.filename}...\n")
        self.update_idletasks()
        try:
            archive = repo.versions_dir / v.filename
            manifest = bundle_mod.read_manifest(archive)
            info = inspector.inspect_zip(archive)
            header = (
                f"── Version : {v.filename} ──\n"
                f"  Save d'origine : {manifest.save_name}\n"
                f"  Uploadé par    : {v.uploaded_by} le {v.uploaded_at}\n"
                f"  DB joueurs     : {'oui' if manifest.has_db else 'NON (risque de perdre les persos)'}\n"
                f"  Config serveur : {', '.join(manifest.server_files) if manifest.server_files else 'aucune'}\n"
                f"  Note           : {v.note or '-'}\n\n"
            )
            self.preview_box.delete("1.0", "end")
            self.preview_box.insert("end", header + inspector.format_info(info))
        except Exception as e:
            messagebox.showerror("Aperçu", str(e))

    # ================================================== manuel : inspect/import
    def _inspect_file(self):
        path = filedialog.askopenfilename(
            title="Inspecter un bundle...",
            filetypes=[("Bundle PZSaveSync", "*.zip"), ("Tous", "*.*")],
        )
        if not path: return
        try:
            m = bundle_mod.read_manifest(Path(path))
            info = inspector.inspect_zip(Path(path))
            self.preview_box.delete("1.0", "end")
            self.preview_box.insert(
                "end",
                "── Manifest ──\n"
                + bundle_mod.summarize_manifest(m)
                + "\n\n"
                + inspector.format_info(info, "── Contenu inspecté ──")
            )
        except Exception as e:
            messagebox.showerror("Inspecter", str(e))

    def _import_file(self):
        if self._block_if_pz_running("Import"):
            return
        path = filedialog.askopenfilename(
            title="Importer un bundle reçu...",
            filetypes=[("Bundle PZSaveSync", "*.zip"), ("Tous", "*.*")],
        )
        if not path: return
        try:
            m = bundle_mod.read_manifest(Path(path))
        except Exception as e:
            messagebox.showerror("Import", f"Bundle invalide : {e}")
            return
        msg = (
            "Tu vas importer ce bundle :\n\n"
            + bundle_mod.summarize_manifest(m)
            + f"\n\n⚠ Écrasera sur TON PC :\n"
            f"   • Zomboid\\Saves\\Multiplayer\\{m.save_name}\\\n"
            f"   • Zomboid\\db\\{m.save_name}.db\n"
            f"   • Zomboid\\Server\\{m.save_name}.* (config serveur)\n\n"
            f"Backup avant écrasement : {LOCAL_BACKUPS}\n\nContinuer ?"
        )
        if not messagebox.askyesno("Importer", msg): return

        dlg = ProgressDialog(self, "Import en cours…")

        def worker(progress_cb):
            progress_cb("verify", 0, 1)
            ok, vmsg = bundle_mod.verify_bundle_integrity(Path(path))
            if not ok:
                raise ValueError(f"Vérification d'intégrité échouée : {vmsg}")
            progress_cb("verify", 1, 1)
            return bundle_mod.extract_bundle(Path(path), backup_dir=LOCAL_BACKUPS)

        def on_done(report, err):
            if err:
                messagebox.showerror("Import", str(err))
                return
            self._show_extract_report(report, box=self.preview_box)
            # Vérif mods installés
            self._check_mods_for_report(report)
            self.cfg.save_name = report.save_name
            config.save(self.cfg)
            self.refresh_all()

        dlg.run_in_thread(worker, on_done=on_done)

    def _check_mods_for_report(self, report):
        """Après un import/pull, vérifie que les mods sont installés et alerte sinon."""
        mods = getattr(report, "mods", []) or []
        workshop = getattr(report, "workshop_items", []) or []
        if not mods and not workshop:
            return
        result = mods_check.check_mods(mods, workshop)
        if result.all_ok:
            return
        lines = [
            "⚠ Certains mods requis ne sont PAS installés sur ton PC :",
            "",
        ]
        if result.missing_mods:
            lines.append(f"Mods manquants ({len(result.missing_mods)}) :")
            for m in result.missing_mods[:10]:
                lines.append(f"   • {m}")
            if len(result.missing_mods) > 10:
                lines.append(f"   … et {len(result.missing_mods) - 10} autres")
            lines.append("")
        if result.missing_workshop:
            lines.append(f"Workshop IDs manquants ({len(result.missing_workshop)}) :")
            for w in result.missing_workshop[:10]:
                lines.append(f"   • https://steamcommunity.com/sharedfiles/filedetails/?id={w}")
            if len(result.missing_workshop) > 10:
                lines.append(f"   … et {len(result.missing_workshop) - 10} autres")
            lines.append("")
        lines.append(
            "→ Abonne-toi à ces mods sur Steam Workshop AVANT de lancer la partie, "
            "sinon le serveur ne démarrera pas."
        )
        messagebox.showwarning("Mods manquants", "\n".join(lines))

    def _show_extract_report(self, report, box):
        lines = [
            "✅ Bundle restauré avec succès",
            "",
            f"Save     : {report.save_name}",
            f"Dossier  : {report.save_dir}",
            f"DB       : {report.db_path or '(non incluse)'}",
            f"Config   : {len(report.server_files)} fichier(s) serveur",
        ]
        for f in report.server_files:
            lines.append(f"   • {f.name}")

        mods = getattr(report, "mods", []) or []
        workshop = getattr(report, "workshop_items", []) or []
        if mods or workshop:
            lines.append("")
            lines.append(f"🧩 Mods requis ({len(mods)}) :")
            if mods:
                for m in mods:
                    lines.append(f"   • {m}")
            else:
                lines.append("   (aucun nom de mod listé)")
            if workshop:
                lines.append("")
                lines.append(f"Steam Workshop IDs ({len(workshop)}) :")
                for w in workshop:
                    lines.append(f"   • https://steamcommunity.com/sharedfiles/filedetails/?id={w}")
                lines.append("")
                lines.append("→ Abonne-toi à ces IDs depuis ton Steam Workshop "
                             "avant de lancer la partie, sinon le serveur ne démarrera pas.")

        if report.backed_up_to:
            lines.append("")
            lines.append(f"💾 Backup pré-import : {report.backed_up_to}")
        lines.append("")
        lines.append("→ Lance Project Zomboid → menu Host → sélectionne la save.")
        lines.append("   Ton pote rejoindra via ton IP comme d'habitude.")
        text = "\n".join(lines)
        box.delete("1.0", "end")
        box.insert("end", text)
        messagebox.showinfo("Import réussi", f"Save '{report.save_name}' prête à jouer !")

    # =================================================================== build
    def _build_exe(self):
        BuildWindow(self)

    # ============================================================== drag-and-drop
    def _on_drop(self, event):
        """Un fichier a été déposé sur la fenêtre."""
        if self._block_if_pz_running("Import (drag-and-drop)"):
            return
        # event.data est une string avec les chemins (entre {} si espaces)
        raw = (event.data or "").strip()
        # Parse simple : tkinterdnd2 wrap les paths avec {} si espaces
        paths: list[str] = []
        if raw.startswith("{") and raw.endswith("}"):
            # Format "{path1} {path2}"
            import re
            paths = re.findall(r"\{([^}]+)\}", raw)
        else:
            # Pas d'espaces, paths séparés par espaces
            paths = raw.split() if " " not in raw else [raw]
        # Filtrer aux .zip
        zips = [p for p in paths if p.lower().endswith(".zip")]
        if not zips:
            messagebox.showinfo(
                "Drop", "Glisse un fichier .zip pour l'importer."
            )
            return
        if len(zips) > 1:
            messagebox.showinfo(
                "Drop", f"{len(zips)} fichiers détectés — importe-les un par un."
            )
            zips = zips[:1]
        # Importe le premier .zip directement
        self._import_path(Path(zips[0]))

    def _import_path(self, path: Path):
        """Variante de _import_file qui prend un chemin déjà connu."""
        try:
            m = bundle_mod.read_manifest(path)
        except Exception as e:
            messagebox.showerror("Import", f"Bundle invalide : {e}")
            return
        msg = (
            f"Tu vas importer ce bundle (glissé-déposé) :\n\n"
            + bundle_mod.summarize_manifest(m)
            + f"\n\n⚠ Écrasera sur TON PC :\n"
            f"   • Zomboid\\Saves\\Multiplayer\\{m.save_name}\\\n"
            f"   • Zomboid\\db\\{m.save_name}.db\n"
            f"   • Zomboid\\Server\\{m.save_name}.*\n\n"
            f"Backup avant écrasement : {LOCAL_BACKUPS}\n\nContinuer ?"
        )
        if not messagebox.askyesno("Importer", msg):
            return

        dlg = ProgressDialog(self, "Import en cours…")

        def worker(progress_cb):
            progress_cb("verify", 0, 1)
            ok, vmsg = bundle_mod.verify_bundle_integrity(path)
            if not ok:
                raise ValueError(f"Vérification d'intégrité échouée : {vmsg}")
            progress_cb("verify", 1, 1)
            return bundle_mod.extract_bundle(path, backup_dir=LOCAL_BACKUPS)

        def on_done(report, err):
            if err:
                _log.error("Import drop échoué : %s", err)
                messagebox.showerror("Import", str(err))
                return
            self._show_extract_report(report, box=self.preview_box)
            self._check_mods_for_report(report)
            self.cfg.save_name = report.save_name
            config.save(self.cfg)
            self.refresh_all()
            notifications.notify("PZ SaveSync", f"Save '{report.save_name}' importée.")

        dlg.run_in_thread(worker, on_done=on_done)

    # ============================================================== updates
    def _check_updates_async(self):
        def on_done(info: updater.UpdateInfo):
            self._update_info = info
            self.cfg.touch_update_check()
            config.save(self.cfg)
            # On programme le rendu dans le main thread
            try:
                self.after(0, self._render_update_banner)
            except Exception:
                pass

        updater.check_latest_async(APP_VERSION, on_done)

    def _render_update_banner(self):
        if not self._update_info:
            return
        if self._update_info.available:
            _log.info("Mise à jour disponible : %s", self._update_info.latest)
            if hasattr(self, "update_banner"):
                self.update_banner_label.configure(
                    text=f"🆕  Une nouvelle version {self._update_info.latest} est disponible "
                         f"(tu as v{APP_VERSION})  ·  clique pour télécharger"
                )
                try:
                    self.update_banner.pack(fill="x", padx=16, pady=(8, 0), before=self.active_bar_ref)
                except Exception:
                    self.update_banner.pack(fill="x", padx=16, pady=(8, 0))
            # Highlight le bouton MAJ du header
            if hasattr(self, "header_update_btn"):
                self.header_update_btn.configure(
                    fg_color=COLOR_WARN, hover_color="#d4a017",
                )
            if hasattr(self, "header_version"):
                self.header_version.configure(
                    text=f"v{APP_VERSION} → v{self._update_info.latest}",
                    text_color=COLOR_WARN,
                )

    def _open_update_url(self, _event=None):
        if self._update_info and self._update_info.download_url:
            import webbrowser
            webbrowser.open(self._update_info.download_url)

    def _manual_update_check(self):
        """Bouton 'Vérifier les MAJ' dans Réglages — version synchrone bloquante (4s max)."""
        try:
            info = updater.check_latest(APP_VERSION, timeout=5)
        except Exception as e:
            messagebox.showerror("Mise à jour", f"Erreur : {e}")
            return
        if info.error:
            messagebox.showerror("Mise à jour", f"Échec : {info.error}")
            return
        if info.available:
            if messagebox.askyesno(
                "Mise à jour disponible",
                f"Tu as v{info.current}.\nUne version {info.latest} est disponible.\n\n"
                f"Ouvrir la page de téléchargement ?"
            ):
                import webbrowser
                webbrowser.open(info.download_url)
        else:
            messagebox.showinfo(
                "À jour", f"Tu es bien sur la dernière version (v{info.current})."
            )

    # ============================================================== profils
    def _switch_profile(self, choice: str):
        """Callback du dropdown profils dans le header."""
        # choice est le 'name' du profil — il faut retrouver la clé
        for key, p in self.cfg.profiles.items():
            if (p.name or key) == choice:
                self.cfg.set_active(key)
                config.save(self.cfg)
                self._selected_save = self.cfg.save_name or None
                self.refresh_all()
                _log.info("Profil actif → %s", key)
                return

    def _add_profile_prompt(self):
        dlg = ctk.CTkInputDialog(
            text="Nom du nouveau profil (ex. 'Groupe Muldraugh', 'Marathon B42') :",
            title="Nouveau profil",
        )
        name = dlg.get_input()
        if not name:
            return
        name = name.strip()
        if not name:
            return
        key = "".join(c.lower() for c in name if c.isalnum() or c in "-_") or f"p{len(self.cfg.profiles)}"
        # Garantir l'unicité
        base = key
        i = 1
        while key in self.cfg.profiles:
            i += 1
            key = f"{base}{i}"
        try:
            self.cfg.add_profile(key, name)
        except ValueError as e:
            messagebox.showerror("Profil", str(e))
            return
        self.cfg.set_active(key)
        config.save(self.cfg)
        self.refresh_all()
        _log.info("Profil ajouté : %s (%s)", key, name)

    def _remove_profile_prompt(self):
        if len(self.cfg.profiles) <= 1:
            messagebox.showinfo("Profil", "Impossible de supprimer le dernier profil.")
            return
        current_key = self.cfg.active_profile
        current_name = self.cfg.current.name or current_key
        if not messagebox.askyesno(
            "Supprimer le profil",
            f"Supprimer le profil « {current_name} » ?\n\n"
            "Les bundles dans le dossier partagé ne sont PAS touchés — "
            "tu pourras les retrouver en recréant le profil."
        ):
            return
        try:
            self.cfg.remove_profile(current_key)
        except ValueError as e:
            messagebox.showerror("Profil", str(e))
            return
        config.save(self.cfg)
        self.refresh_all()
        _log.info("Profil supprimé : %s", current_key)

    # ============================================================== tmp cleanup
    def _cleanup_orphan_tmp(self):
        """Au démarrage, nettoie les .tmp orphelins (résidus d'opérations crashées)."""
        try:
            if not self.cfg.shared_folder:
                return
            repo = SharedRepo(Path(self.cfg.shared_folder))
            if not repo.versions_dir.exists():
                return
            deleted = repo.cleanup_orphan_tmp_files()
            if deleted:
                _log.info("Recovery : %d fichier(s) .tmp orphelin(s) supprimé(s)", len(deleted))
        except Exception as e:
            _log.warning("Cleanup .tmp : %s", e)

    # =========================================================== onboarding
    def _show_onboarding(self):
        try:
            onboarding.OnboardingWizard(self, self.cfg, on_finish=self._on_onboarding_done)
        except Exception as e:
            print(f"[onboarding] erreur : {e}")

    def _on_onboarding_done(self, cfg):
        self.cfg = cfg
        self.refresh_all()

    # =========================================================== polling PZ
    def _schedule_pz_poll(self):
        if not self.cfg.watch_pz_process:
            return
        self.after(15000, self._poll_pz)

    def _poll_pz(self):
        # On exécute is_pz_running() dans un thread daemon : sur certains PC
        # (antivirus actif, beaucoup de process) tasklist peut prendre plusieurs
        # secondes et bloquerait sinon le main thread → freeze UI à chaque poll.
        def worker():
            try:
                running, _ = pz_detector.is_pz_running()
            except Exception:
                running = False
            try:
                self.after(0, self._handle_pz_poll_result, running)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
        # Re-scheduler indépendamment du résultat
        self.after(15000, self._poll_pz)

    def _handle_pz_poll_result(self, running: bool):
        if running:
            self._pz_was_running = True
            if hasattr(self, "footer_pz_status"):
                self.footer_pz_status.configure(
                    text="🎮 PZ détecté", text_color=COLOR_OK,
                )
        else:
            if self._pz_was_running and self.cfg.save_name:
                self._pz_was_running = False
                if hasattr(self, "footer_pz_status"):
                    self.footer_pz_status.configure(text="", text_color=COLOR_TEXT_DIM)
                self.after(0, self._prompt_push_after_pz_close)
            elif hasattr(self, "footer_pz_status"):
                self.footer_pz_status.configure(text="", text_color=COLOR_TEXT_DIM)

    def _prompt_push_after_pz_close(self):
        if not self.cfg.save_name:
            return
        msg = (
            f"Tu viens de fermer Project Zomboid.\n\n"
            f"Veux-tu push ta partie active « {self.cfg.save_name} » "
            f"vers le dossier partagé maintenant ?"
        )
        if messagebox.askyesno("Push après session", msg):
            self._do_push(self.cfg.save_name)

    # ======================================================== check PZ running
    def _block_if_pz_running(self, action_label: str = "Cette opération") -> bool:
        """Si PZ tourne, prévient et bloque (renvoie True si on doit annuler)."""
        running, names = pz_detector.is_pz_running()
        if not running:
            return False
        messagebox.showwarning(
            "Project Zomboid est en cours d'exécution",
            f"{action_label} ne peut pas être lancée pendant que PZ tourne "
            f"(risque de corruption de la save).\n\n"
            f"Process détecté(s) : {', '.join(names)}\n\n"
            f"Ferme PZ d'abord, puis réessaie."
        )
        return True

    # ============================================================ save retard
    def _check_save_late(self) -> str | None:
        """Renvoie un message si la save locale active est plus vieille que le latest cloud.

        Renvoie None sinon.

        Perf : on ré-utilise `info.last_played` calculé par `inspect_save`
        pendant le `list_all_with_info()` du refresh courant — avant
        v0.3.6, on rglobait la save_dir une 2e fois (~secondes de freeze UI
        sur les saves de 50k+ chunks).
        """
        if not self.cfg.save_name or not self.cfg.shared_folder:
            return None
        try:
            repo = SharedRepo(Path(self.cfg.shared_folder))
            latest = repo.latest_version()
        except Exception:
            return None
        if not latest or latest.save_name != self.cfg.save_name:
            return None
        # Cherche la save active dans le scan déjà fait par refresh_all
        active_entry = next(
            (e for e in self._save_entries if e.name == self.cfg.save_name), None,
        )
        if active_entry is None or not active_entry.info.last_played:
            return None
        try:
            local_dt = dt.datetime.fromisoformat(active_entry.info.last_played)
        except (ValueError, TypeError):
            return None
        try:
            remote_dt = dt.datetime.fromisoformat(latest.uploaded_at)
        except (ValueError, TypeError):
            return None
        # Tolérance de 60s (clock skew, latence Drive)
        if remote_dt > local_dt + dt.timedelta(seconds=60):
            delta = remote_dt - local_dt
            hours = delta.total_seconds() / 3600
            if hours < 1:
                ago = f"{int(delta.total_seconds() / 60)} min"
            elif hours < 24:
                ago = f"{hours:.1f} h"
            else:
                ago = f"{int(hours / 24)} j"
            return (
                f"⚠  Ta save locale est en retard sur le cloud  ·  "
                f"dernière version par {latest.uploaded_by} il y a {ago}  ·  "
                f"pull avant de jouer !"
            )
        return None

    def _refresh_late_banner(self):
        if not hasattr(self, "late_banner"):
            return
        msg = self._check_save_late()
        if msg:
            self.late_banner.pack(fill="x", padx=16, pady=(8, 0), before=self.active_bar_ref)
            self.late_banner_label.configure(text=msg)
        else:
            try:
                self.late_banner.pack_forget()
            except Exception:
                pass

    # ============================================================ detect cloud
    def _detect_cloud_folder(self):
        """Bouton 'Détecter' dans Réglages : propose les dossiers cloud trouvés."""
        found = cloud_detect.detect()
        if not found:
            messagebox.showinfo(
                "Auto-détection",
                "Aucun dossier cloud standard détecté (Dropbox, Drive, OneDrive). "
                "Saisis le chemin à la main."
            )
            return
        dlg = CloudPicker(self, found, on_pick=lambda p: self.folder_var.set(str(p)))
        try:
            dlg.grab_set()
        except Exception:
            pass

    # ============================================================ nettoyage versions
    def _prune_versions_prompt(self):
        repo = self._repo()
        if not repo:
            return
        versions = repo.list_versions()
        if not versions:
            messagebox.showinfo("Nettoyage", "Aucune version à nettoyer.")
            return
        total_mb = sum(v.size_bytes for v in versions) / 1024 / 1024
        # Regroupe par save_name : on prune INDÉPENDAMMENT chaque save pour
        # éviter de supprimer la dernière version d'une save peu utilisée.
        saves_in_repo = sorted({v.save_name for v in versions if v.save_name})
        save_counts = {
            s: sum(1 for v in versions if v.save_name == s) for s in saves_in_repo
        }
        counts_txt = " · ".join(f"{s} ({n})" for s, n in save_counts.items())
        keep = ctk.CTkInputDialog(
            text=f"Tu as {len(versions)} versions ({total_mb:.0f} MB total).\n"
                 f"Réparties par save : {counts_txt or '(aucune nommée)'}\n\n"
                 f"Combien en garder PAR SAVE (les plus récentes) ?",
            title="Nettoyer l'historique",
        ).get_input()
        if keep is None:
            return
        try:
            n = int(keep)
        except ValueError:
            messagebox.showerror("Erreur", "Saisis un nombre entier.")
            return
        if n < 1:
            messagebox.showerror("Erreur", "Garde au moins 1 version.")
            return
        try:
            all_deleted: list[str] = []
            # Prune indépendamment chaque save → on ne touche pas la dernière
            # version d'une save peu utilisée.
            for s in saves_in_repo:
                all_deleted.extend(repo.prune_versions(keep_last_n=n, save_name=s))
            # Versions sans save_name (anciens manifestes) : pruned globalement
            anonymes = [v for v in versions if not v.save_name]
            if anonymes:
                all_deleted.extend(repo.prune_versions(keep_last_n=n))
            new_total_mb = sum(v.size_bytes for v in repo.list_versions()) / 1024 / 1024
            messagebox.showinfo(
                "Nettoyage",
                f"{len(all_deleted)} version(s) supprimée(s).\n"
                f"Espace libéré : ~{total_mb - new_total_mb:.0f} MB\n"
                f"Sauvé : au moins {n} version(s) de chaque save."
            )
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Nettoyage", str(e))

    # ============================================================ webhook test
    def _test_webhook(self):
        url = self.webhook_var.get().strip()
        if not url:
            messagebox.showerror("Webhook", "URL vide.")
            return
        ok, msg = discord_webhook.notify_test(
            url, player=self.name_var.get().strip() or "(test)",
        )
        if ok:
            messagebox.showinfo("Webhook", f"✓ Test envoyé : {msg}")
        else:
            messagebox.showerror("Webhook", f"✗ Échec : {msg}")


# --------------------------------------------------------------- popups
class VersionPicker(ctk.CTkToplevel):
    def __init__(self, parent, versions: list[Version], on_pick):
        super().__init__(parent)
        self.title("Choisir une version")
        self.geometry("820x480")
        self.configure(fg_color=COLOR_BG)
        self.on_pick = on_pick
        self.versions = versions
        ctk.CTkLabel(
            self, text="🕓  Choisir une version à inspecter",
            font=("Segoe UI", 13, "bold"), anchor="w",
        ).pack(padx=14, pady=(14, 4), anchor="w")
        ctk.CTkLabel(
            self, text="Saisis l'index et clique Inspecter.",
            font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED, anchor="w",
        ).pack(padx=14, pady=(0, 8), anchor="w")
        self.listbox = ctk.CTkTextbox(
            self, font=("Consolas", 10),
            fg_color=COLOR_CARD, border_width=1, border_color=COLOR_BORDER,
        )
        self.listbox.pack(fill="both", expand=True, padx=14, pady=4)
        for i, v in enumerate(versions):
            size_mb = v.size_bytes / (1024 * 1024)
            self.listbox.insert(
                "end",
                f"[{i}] {v.uploaded_at}  {v.uploaded_by:>10}  "
                f"[{v.save_name:<14}] {size_mb:6.1f} MB  {v.filename}"
                + (f"  — {v.note}" if v.note else "") + "\n"
            )
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(
            bar, text="Index :", font=("Segoe UI", 11),
        ).pack(side="left")
        self.idx_var = ctk.StringVar(value="0")
        ctk.CTkEntry(
            bar, textvariable=self.idx_var, width=80, height=32,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            bar, text="🔍  Inspecter", command=self._go, height=32,
            fg_color=ACTION_PULL, hover_color="#3690c5",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")

    def _go(self):
        try:
            i = int(self.idx_var.get()); v = self.versions[i]
        except (ValueError, IndexError):
            messagebox.showerror("Erreur", "Index invalide.")
            return
        self.destroy(); self.on_pick(v)


class BackupPicker(ctk.CTkToplevel):
    """Liste les backups locaux et permet d'en sélectionner un à restaurer."""
    def __init__(self, parent, backups: "list[restore_mod.BackupEntry]", on_pick):
        super().__init__(parent)
        self.title("Restaurer un backup")
        self.geometry("860x500")
        self.configure(fg_color=COLOR_BG)
        self.on_pick = on_pick
        self.backups = backups
        ctk.CTkLabel(
            self, text="↩  Choisir un backup à restaurer",
            font=("Segoe UI", 13, "bold"), anchor="w",
        ).pack(padx=14, pady=(14, 4), anchor="w")
        ctk.CTkLabel(
            self, text="Les plus récents en haut. Saisis l'index et clique Restaurer.",
            font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED, anchor="w",
        ).pack(padx=14, pady=(0, 8), anchor="w")
        self.listbox = ctk.CTkTextbox(
            self, font=("Consolas", 10),
            fg_color=COLOR_CARD, border_width=1, border_color=COLOR_BORDER,
        )
        self.listbox.pack(fill="both", expand=True, padx=14, pady=4)
        for i, b in enumerate(backups):
            size_mb = b.size_bytes / (1024 * 1024)
            db_tag = "DB+" + ",".join(b.db_companions) if b.db_companions else (
                "DB" if b.has_db else "—"
            )
            srv_tag = f"srv={len(b.server_files)}"
            ok_tag = "✓" if b.restorable else "✗"
            # tag visuel du type de backup pour distinguer pre_import vs pre_restore
            kind_tag = "📥" if b.kind == "import" else "↩"
            self.listbox.insert(
                "end",
                f"[{i}] {ok_tag} {kind_tag} {b.display_timestamp}  "
                f"[{b.save_name:<14}] {size_mb:6.1f} MB  {db_tag}  {srv_tag}\n"
            )
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(bar, text="Index :", font=("Segoe UI", 11)).pack(side="left")
        self.idx_var = ctk.StringVar(value="0")
        ctk.CTkEntry(
            bar, textvariable=self.idx_var, width=80, height=32,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            bar, text="↩  Restaurer", command=self._go, height=32,
            fg_color=ACTION_PULL, hover_color="#3690c5",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")

    def _go(self):
        try:
            i = int(self.idx_var.get())
            b = self.backups[i]
        except (ValueError, IndexError):
            messagebox.showerror("Erreur", "Index invalide.")
            return
        if not b.restorable:
            messagebox.showerror(
                "Erreur",
                "Ce backup est incomplet (pas de save.zip), impossible de restaurer.",
            )
            return
        self.destroy()
        self.on_pick(b)


class BuildWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Build .exe (PyInstaller)")
        self.geometry("820x560")
        self.configure(fg_color=COLOR_BG)
        ctk.CTkLabel(
            self,
            text="🛠  Build du .exe en cours...",
            anchor="w", font=("Segoe UI", 13, "bold"),
        ).pack(fill="x", padx=14, pady=(14, 2))
        ctk.CTkLabel(
            self, text="Patiente 1 à 3 minutes — PyInstaller fait le café.",
            anchor="w", font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED,
        ).pack(fill="x", padx=14, pady=(0, 10))
        self.log_box = ctk.CTkTextbox(
            self, font=("Consolas", 10),
            fg_color=COLOR_CARD, border_width=1, border_color=COLOR_BORDER,
        )
        self.log_box.pack(fill="both", expand=True, padx=14, pady=4)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=12)
        self.status = ctk.CTkLabel(
            bar, text="⏳  démarrage...", anchor="w",
            font=("Segoe UI", 11, "bold"),
        )
        self.status.pack(side="left")
        ctk.CTkButton(
            bar, text="📁  Ouvrir dist/", command=self._open_dist, height=32,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        ).pack(side="right", padx=4)
        builder.build(self._log, self._done)

    def _log(self, msg: str):
        def append():
            self.log_box.insert("end", msg + "\n"); self.log_box.see("end")
        try: self.after(0, append)
        except Exception: pass

    def _done(self, ok: bool, exe_path):
        def update():
            if ok and exe_path:
                self.status.configure(text=f"✅  OK : {exe_path}", text_color=COLOR_OK)
            else:
                self.status.configure(text="❌  Échec — voir logs.", text_color=COLOR_BAD)
        try: self.after(0, update)
        except Exception: pass

    def _open_dist(self):
        dist = builder.DIST; dist.mkdir(parents=True, exist_ok=True)
        _open_path(dist)


class PushOptionsDialog(ctk.CTkToplevel):
    """Dialog modal pour les options du push : note + libérer le tour."""

    def __init__(self, parent, default_release: bool = True):
        super().__init__(parent)
        self.title("Options du push")
        self.geometry("480x260")
        self.configure(fg_color=COLOR_BG)
        self.resizable(False, False)
        self.ok = False
        self.note = ""
        self.release_after = default_release
        self._build_ui(default_release)
        try:
            self.grab_set()
        except Exception:
            pass

    def _build_ui(self, default_release: bool):
        card = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=10,
                            border_width=1, border_color=COLOR_BORDER)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            card, text="⬆  Push vers le dossier partagé",
            font=("Segoe UI", 13, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 10))

        ctk.CTkLabel(
            card, text="Note pour ton pote (optionnel) :",
            font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED, anchor="w",
        ).pack(fill="x", padx=14)
        self.note_var = ctk.StringVar()
        ctk.CTkEntry(
            card, textvariable=self.note_var, height=34,
            placeholder_text="ex. Fini d'explorer la mairie de Muldraugh",
        ).pack(fill="x", padx=14, pady=(4, 12))

        self.release_var = ctk.BooleanVar(value=default_release)
        ctk.CTkCheckBox(
            card, text="🔓  Libérer le tour après le push",
            variable=self.release_var, font=("Segoe UI", 11),
        ).pack(anchor="w", padx=14, pady=(0, 14))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(
            btns, text="Annuler", width=100, height=34,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            command=self._cancel,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            btns, text="⬆  Push", width=120, height=34,
            font=("Segoe UI", 11, "bold"),
            fg_color=ACTION_PUSH, hover_color="#3da76b",
            command=self._confirm,
        ).pack(side="right")

    def _confirm(self):
        self.note = self.note_var.get().strip()
        self.release_after = bool(self.release_var.get())
        self.ok = True
        self.destroy()

    def _cancel(self):
        self.ok = False
        self.destroy()


class CloudPicker(ctk.CTkToplevel):
    """Liste les dossiers cloud détectés et permet d'en choisir un."""

    def __init__(self, parent, candidates: list, on_pick):
        super().__init__(parent)
        self.title("Dossiers cloud détectés")
        self.geometry("560x420")
        self.configure(fg_color=COLOR_BG)
        self.on_pick = on_pick

        ctk.CTkLabel(
            self, text="☁  Dossiers cloud détectés sur ton PC",
            font=("Segoe UI", 13, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 4))
        ctk.CTkLabel(
            self, text="Clique sur un dossier pour le pré-remplir dans Réglages.",
            font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED, anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_CARD, corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        for c in candidates:
            suggested = cloud_detect.suggest_subfolder(c.path)
            row = ctk.CTkFrame(scroll, fg_color=COLOR_BG, corner_radius=6)
            row.pack(fill="x", padx=4, pady=4)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(
                inner, text=f"{c.icon}  {c.label}",
                font=("Segoe UI", 12, "bold"), anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                inner, text=f"   {suggested}",
                font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED,
                anchor="w", justify="left",
            ).pack(anchor="w", pady=(2, 0))
            ctk.CTkButton(
                inner, text=f"Utiliser ce chemin",
                height=28, width=160,
                fg_color=ACTION_PULL, hover_color="#3690c5",
                font=("Segoe UI", 10),
                command=lambda p=suggested: self._pick(p),
            ).pack(anchor="w", pady=(6, 0))

    def _pick(self, path):
        try:
            self.on_pick(path)
        finally:
            self.destroy()


def run():
    App().mainloop()


if __name__ == "__main__":
    run()
