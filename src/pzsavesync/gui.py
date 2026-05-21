from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from pzsavesync import builder, bundle as bundle_mod, config, inspector, saves
from pzsavesync.sync import SharedRepo, Version
from pzsavesync.tooltip import attach as tip

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

APP_VERSION = "0.1.0"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("PZ SaveSync")
        self.geometry("1100x800")
        self.minsize(980, 700)
        self.configure(fg_color=COLOR_BG)
        self.cfg = config.load()
        self._save_entries: list[saves.SaveEntry] = []
        self._selected_save: str | None = self.cfg.save_name or None

        self._build_header()
        self._build_tabs()
        self._build_footer()
        self.refresh_all()

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
        ctk.CTkLabel(
            title_block, text="PZ SaveSync",
            font=("Segoe UI", 19, "bold"), anchor="w",
        ).pack(anchor="w")
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
        self.footer_status = ctk.CTkLabel(
            foot, text="prêt",
            font=("Segoe UI", 9), text_color=COLOR_TEXT_DIM,
        )
        self.footer_status.pack(side="right", padx=12)

    # ------------------------------------------------------------------ tabs
    def _build_tabs(self):
        tabs = ctk.CTkTabview(self, anchor="nw")
        tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_share = tabs.add("🔄  Partager")
        self.tab_parties = tabs.add("🎮  Mes parties")
        self.tab_settings = tabs.add("⚙  Réglages")

        self._build_tab_share()
        self._build_tab_parties()
        self._build_tab_settings()

    # ============================================================== TAB PARTAGER
    def _build_tab_share(self):
        wrap = self.tab_share

        # --- Bandeau "Partie active" ---
        active_bar = ctk.CTkFrame(wrap, fg_color=COLOR_CARD, corner_radius=10,
                                  border_width=1, border_color=COLOR_BORDER)
        active_bar.pack(fill="x", padx=16, pady=(16, 8))
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

        # --- Petite barre d'actions secondaires (en ligne, discrètes) ---
        more = ctk.CTkFrame(wrap, fg_color="transparent")
        more.pack(fill="x", padx=16, pady=(10, 4))
        b_inspect = ctk.CTkButton(
            more, text="🔍  Inspecter un .zip", height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10), command=self._inspect_file,
        )
        b_inspect.pack(side="left", padx=3)
        tip(b_inspect, "Affiche le manifeste et le contenu d'un .zip sans rien installer.")

        b_diff = ctk.CTkButton(
            more, text="↔  Diff local / remote", height=30,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10), command=self._preview_diff,
        )
        b_diff.pack(side="left", padx=3)
        tip(b_diff, "Compare ta save locale active à la dernière version partagée.")

        b_pick = ctk.CTkButton(
            more, text="🕓  Inspecter une version...", height=30,
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
            grid, textvariable=self.folder_var, width=500, height=34,
            border_width=1, border_color=COLOR_BORDER,
        )
        e_folder.grid(row=3, column=0, sticky="w", padx=14, pady=(0, 14))
        tip(e_folder, "Un dossier déjà synchronisé entre toi et ton pote (Dropbox, "
                      "Google Drive Desktop, OneDrive). Toi et lui devez pointer vers le MÊME contenu.")
        b_browse = ctk.CTkButton(
            grid, text="📁  Parcourir...", width=120, height=34,
            command=self._browse,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            font=("Segoe UI", 10),
        )
        b_browse.grid(row=3, column=1, padx=6, pady=(0, 14))

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

    # =============================================================== refresh
    def refresh_all(self):
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

    def _make_card(self, entry: saves.SaveEntry) -> ctk.CTkFrame:
        is_selected = entry.name == self._selected_save
        is_active = entry.name == self.cfg.save_name
        bg = COLOR_CARD_SEL if is_selected else COLOR_CARD
        border_color = COLOR_STAR if is_active else (
            "#4d7eb8" if is_selected else COLOR_BORDER
        )
        card = ctk.CTkFrame(
            self.saves_list_scroll, fg_color=bg, corner_radius=8,
            border_width=1, border_color=border_color,
        )
        card.pack(fill="x", padx=4, pady=4)

        icon = "🌍" if entry.is_server_save else ("👤" if entry.is_client_save else "❓")
        line1 = ctk.CTkFrame(card, fg_color="transparent")
        line1.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            line1, text=f"{icon}  {entry.name}",
            font=("Segoe UI", 12, "bold"), anchor="w",
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
            text_color=COLOR_TEXT if is_selected else "#bcbfc6",
            anchor="w", justify="left",
        ).pack(fill="x", padx=12, pady=(2, 4))

        # Tag transférable (compact)
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.pack(fill="x", padx=12, pady=(0, 10))
        if entry.transferable:
            t = ctk.CTkLabel(
                bar, text="✓  transférable",
                text_color=COLOR_OK, font=("Segoe UI", 9, "bold"),
            )
            t.pack(side="left")
            tip(t, "Cette partie est un serveur multi hébergé localement : on peut bundler "
                   "save + DB + config et la transférer à ton pote.")
        else:
            t = ctk.CTkLabel(
                bar, text="∅  non transférable",
                text_color=COLOR_TEXT_DIM, font=("Segoe UI", 9),
            )
            t.pack(side="left")
            tip(t, "Ce dossier est probablement une save client (toi qui rejoins un serveur), "
                   "pas un serveur que tu héberges.")

        def on_click(_e=None, n=entry.name):
            self._select_save(n)

        # Hover doux pour les cartes non-sélectionnées
        hover_bg = COLOR_CARD_HOVER if not is_selected else bg

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
            card.configure(fg_color=COLOR_CARD_SEL if n == name else COLOR_CARD)
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
        try:
            m = bundle_mod.build_bundle(
                save_name=save_name, out_zip=Path(path),
                created_by=name, note=note,
            )
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
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def _do_push(self, save_name: str):
        name = self._require_name()
        repo = self._repo()
        if not name or not repo:
            return
        lock = repo.get_lock()
        if lock and lock.holder != name:
            if not messagebox.askyesno("Verrou",
                                       f"Le tour est à {lock.holder}. Pousser quand même ?"):
                return
        note = ctk.CTkInputDialog(text="Note (optionnel) :", title="Push").get_input() or ""
        try:
            v = repo.push_bundle(save_name, uploaded_by=name, note=note)
            messagebox.showinfo(
                "Push réussi",
                f"Bundle envoyé : {v.filename}\n"
                f"Taille : {v.size_bytes/1024/1024:.1f} MB\n"
                f"DB joueurs : {'oui' if v.has_db else 'NON'}\n"
                f"Config serveur : {len(v.server_files or [])} fichier(s)"
            )
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Push", str(e))

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
        repo.release_lock(holder="*", force=True); self.refresh_all()

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
        try:
            report = repo.pull_bundle(latest, backup_dir=LOCAL_BACKUPS)
            self._show_extract_report(report, box=self.preview_box)
            self.cfg.save_name = report.save_name
            config.save(self.cfg)
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Pull", str(e))

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
            save_path = Path.home() / "Zomboid" / "Saves" / "Multiplayer" / latest.save_name
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
        try:
            report = bundle_mod.extract_bundle(Path(path), backup_dir=LOCAL_BACKUPS)
            self._show_extract_report(report, box=self.preview_box)
            self.cfg.save_name = report.save_name
            config.save(self.cfg)
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Import", str(e))

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


def run():
    App().mainloop()


if __name__ == "__main__":
    run()
