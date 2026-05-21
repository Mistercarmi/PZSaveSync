"""Wizard d'onboarding au premier lancement.

3 étapes : pseudo, dossier partagé (avec auto-détection), confirmation + scan.
Apparaît si la config est vierge (player_name vide OU onboarding_done=False).
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from pzsavesync import cloud_detect, config


# Palette synchronisée avec gui.py — on duplique les 3-4 constantes nécessaires
# plutôt que d'importer gui (circular import).
COLOR_BG = "#15171b"
COLOR_CARD = "#22262e"
COLOR_BORDER = "#33373f"
COLOR_TEXT = "#e6e8ec"
COLOR_TEXT_MUTED = "#8a8e97"
COLOR_TEXT_DIM = "#5a5e66"
COLOR_OK = "#4caf6d"
COLOR_STAR = "#f5c842"
ACTION_PRIMARY = "#2c7fb8"
ACTION_SUCCESS = "#2e8b57"
ACTION_NEUTRAL = "#3a3d44"
ACTION_NEUTRAL_HOVER = "#484c54"


class OnboardingWizard(ctk.CTkToplevel):
    """Fenêtre modale 3 étapes ; appelle on_finish(cfg) à la fin."""

    def __init__(self, parent, cfg: config.Config, on_finish):
        super().__init__(parent)
        self.title("Bienvenue dans PZ SaveSync")
        self.geometry("680x520")
        self.minsize(680, 520)
        self.configure(fg_color=COLOR_BG)
        self.cfg = cfg
        self.on_finish = on_finish
        self.step = 0
        self._build_ui()
        self._render_step()
        # Rendre la fenêtre modale et centrée
        self.grab_set()
        self.after(100, self._center_on_parent)

    def _center_on_parent(self):
        try:
            p = self.master
            px, py = p.winfo_rootx(), p.winfo_rooty()
            pw, ph = p.winfo_width(), p.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
        except Exception:
            pass

    # -------------- layout --------------
    def _build_ui(self):
        # Header
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 4))
        ctk.CTkLabel(
            head, text="🎮  PZ SaveSync",
            font=("Segoe UI", 22, "bold"), anchor="w",
        ).pack(anchor="w")
        self.step_label = ctk.CTkLabel(
            head, text="", anchor="w",
            font=("Segoe UI", 11), text_color=COLOR_TEXT_MUTED,
        )
        self.step_label.pack(anchor="w", pady=(2, 0))

        # Indicateur de progression (3 dots)
        self.progress_frame = ctk.CTkFrame(head, fg_color="transparent")
        self.progress_frame.pack(anchor="w", pady=(8, 0))
        self.dots: list[ctk.CTkFrame] = []
        for i in range(3):
            d = ctk.CTkFrame(
                self.progress_frame, width=24, height=4,
                fg_color=COLOR_BORDER, corner_radius=2,
            )
            d.grid(row=0, column=i, padx=(0, 4))
            self.dots.append(d)

        # Body (container que chaque step rend différemment)
        self.body = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=10,
                                 border_width=1, border_color=COLOR_BORDER)
        self.body.pack(fill="both", expand=True, padx=24, pady=14)

        # Footer (boutons Suivant/Précédent)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=24, pady=(0, 20))
        self.btn_prev = ctk.CTkButton(
            foot, text="◀  Précédent", width=130, height=38,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            command=self._prev,
        )
        self.btn_prev.pack(side="left")
        self.btn_next = ctk.CTkButton(
            foot, text="Suivant  ▶", width=130, height=38,
            font=("Segoe UI", 11, "bold"),
            fg_color=ACTION_PRIMARY, hover_color="#3690c5",
            command=self._next,
        )
        self.btn_next.pack(side="right")
        self.btn_skip = ctk.CTkButton(
            foot, text="Passer", width=80, height=38,
            fg_color="transparent", hover_color=ACTION_NEUTRAL,
            text_color=COLOR_TEXT_MUTED,
            command=self._skip,
        )
        self.btn_skip.pack(side="right", padx=(0, 8))

    def _render_step(self):
        # Reset body
        for c in self.body.winfo_children():
            c.destroy()
        # Reset dots
        for i, d in enumerate(self.dots):
            d.configure(fg_color=ACTION_PRIMARY if i <= self.step else COLOR_BORDER)
        self.step_label.configure(text=f"Étape {self.step + 1} / 3")

        if self.step == 0:
            self._render_step_name()
            self.btn_prev.configure(state="disabled")
            self.btn_next.configure(text="Suivant  ▶")
        elif self.step == 1:
            self._render_step_folder()
            self.btn_prev.configure(state="normal")
            self.btn_next.configure(text="Suivant  ▶")
        elif self.step == 2:
            self._render_step_summary()
            self.btn_prev.configure(state="normal")
            self.btn_next.configure(text="Terminer  ✓",
                                   fg_color=ACTION_SUCCESS, hover_color="#3da76b")

    # -------------- step 1 : pseudo --------------
    def _render_step_name(self):
        ctk.CTkLabel(
            self.body, text="👤   Quel est ton pseudo ?",
            font=("Segoe UI", 16, "bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkLabel(
            self.body,
            text=(
                "Il sera utilisé pour :\n"
                "  • signer les bundles que tu envoies (ton pote saura d'où ça vient)\n"
                "  • marquer le verrou de tour quand c'est ta session"
            ),
            anchor="w", justify="left",
            font=("Segoe UI", 11), text_color=COLOR_TEXT_MUTED,
        ).pack(fill="x", padx=20, pady=(0, 12))

        self.name_var = ctk.StringVar(value=self.cfg.player_name)
        entry = ctk.CTkEntry(
            self.body, textvariable=self.name_var, height=40,
            font=("Segoe UI", 13),
            placeholder_text="Ex. Survivor42, JimBob, ...",
        )
        entry.pack(fill="x", padx=20, pady=4)
        entry.focus_set()

    # -------------- step 2 : dossier --------------
    def _render_step_folder(self):
        ctk.CTkLabel(
            self.body, text="☁   Dossier partagé (Dropbox / Drive / OneDrive)",
            font=("Segoe UI", 16, "bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkLabel(
            self.body,
            text=(
                "Le chemin local d'un dossier synchronisé avec ton pote.\n"
                "On a détecté quelques services cloud sur ton PC :"
            ),
            anchor="w", justify="left",
            font=("Segoe UI", 11), text_color=COLOR_TEXT_MUTED,
        ).pack(fill="x", padx=20, pady=(0, 8))

        # Liste des candidats
        candidates_frame = ctk.CTkFrame(self.body, fg_color="transparent")
        candidates_frame.pack(fill="x", padx=20, pady=4)
        self.folder_var = ctk.StringVar(value=self.cfg.shared_folder)

        found = cloud_detect.detect()
        if not found:
            ctk.CTkLabel(
                candidates_frame,
                text="(aucun dossier cloud standard détecté — pointe à la main)",
                anchor="w", text_color=COLOR_TEXT_DIM,
                font=("Segoe UI", 10),
            ).pack(fill="x", pady=4)
        else:
            for c in found[:5]:  # max 5 suggestions
                suggested = cloud_detect.suggest_subfolder(c.path)
                btn = ctk.CTkButton(
                    candidates_frame,
                    text=f"{c.icon}  {c.label}   →   {suggested}",
                    height=36, anchor="w",
                    font=("Segoe UI", 10),
                    fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
                    command=lambda p=suggested: self.folder_var.set(str(p)),
                )
                btn.pack(fill="x", pady=2)

        # Champ libre + browse
        custom_frame = ctk.CTkFrame(self.body, fg_color="transparent")
        custom_frame.pack(fill="x", padx=20, pady=(12, 4))
        ctk.CTkLabel(
            custom_frame, text="Chemin sélectionné :",
            font=("Segoe UI", 10, "bold"), anchor="w",
            text_color=COLOR_TEXT_MUTED,
        ).pack(anchor="w")
        row = ctk.CTkFrame(custom_frame, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))
        e = ctk.CTkEntry(row, textvariable=self.folder_var, height=36, font=("Segoe UI", 11))
        e.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            row, text="📁", width=44, height=36,
            fg_color=ACTION_NEUTRAL, hover_color=ACTION_NEUTRAL_HOVER,
            command=self._browse,
        ).pack(side="left", padx=(6, 0))

    def _browse(self):
        path = filedialog.askdirectory(title="Choisir le dossier partagé")
        if path:
            self.folder_var.set(path)

    # -------------- step 3 : récap --------------
    def _render_step_summary(self):
        ctk.CTkLabel(
            self.body, text="✓   Récap",
            font=("Segoe UI", 16, "bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 8))

        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=4)
        rows = [
            ("Pseudo", self.cfg.player_name or "(non défini)"),
            ("Dossier partagé", self.cfg.shared_folder or "(non défini — tu pourras le faire plus tard)"),
        ]
        for label, value in rows:
            r = ctk.CTkFrame(grid, fg_color="transparent")
            r.pack(fill="x", pady=4)
            ctk.CTkLabel(
                r, text=label, width=140, anchor="w",
                font=("Segoe UI", 11), text_color=COLOR_TEXT_MUTED,
            ).pack(side="left")
            ctk.CTkLabel(
                r, text=value, anchor="w",
                font=("Segoe UI", 12, "bold"),
            ).pack(side="left")

        ctk.CTkLabel(
            self.body,
            text=(
                "🎯  Prochaines étapes après ce wizard :\n"
                "  • Sélectionne ta save dans l'onglet « Mes parties »\n"
                "  • Clique « ⭐ Définir comme partie active »\n"
                "  • Direction l'onglet « Partager » pour push / pull"
            ),
            anchor="w", justify="left",
            font=("Segoe UI", 11), text_color=COLOR_TEXT_MUTED,
        ).pack(fill="x", padx=20, pady=(16, 0))

    # -------------- navigation --------------
    def _next(self):
        # Sauvegarde de l'étape courante avant d'avancer
        if self.step == 0:
            name = self.name_var.get().strip()
            if not name:
                return  # ne pas avancer si vide
            self.cfg.player_name = name
        elif self.step == 1:
            self.cfg.shared_folder = self.folder_var.get().strip()
            # On accepte d'avancer même si vide (l'utilisateur peut le faire plus tard)
        elif self.step == 2:
            self._finish()
            return
        self.step += 1
        self._render_step()

    def _prev(self):
        if self.step > 0:
            self.step -= 1
            self._render_step()

    def _skip(self):
        # Passer le wizard sans valider — on le rappellera la prochaine fois si rien n'est rempli
        self.destroy()

    def _finish(self):
        self.cfg.onboarding_done = True
        config.save(self.cfg)
        self.destroy()
        if self.on_finish:
            self.on_finish(self.cfg)
