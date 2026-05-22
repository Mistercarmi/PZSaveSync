"""Dialog modal de progression pour les opérations longues (push/pull/export/import)."""
from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk


COLOR_BG = "#15171b"
COLOR_CARD = "#22262e"
COLOR_BORDER = "#33373f"
COLOR_TEXT = "#e6e8ec"
COLOR_TEXT_MUTED = "#8a8e97"
COLOR_OK = "#4caf6d"
COLOR_BAD = "#d65a5a"
ACTION_PRIMARY = "#2c7fb8"


class ProgressDialog(ctk.CTkToplevel):
    """Petit dialog avec une barre de progression + texte de statut.

    Usage :
        dlg = ProgressDialog(parent, "Création du bundle...")
        def worker(progress_cb):
            # ... ton boulot, en appelant progress_cb("zip", current, total)
        dlg.run_in_thread(worker, on_done=lambda result, err: ...)
    """

    def __init__(self, parent, title: str = "Opération en cours"):
        super().__init__(parent)
        self.title(title)
        self.geometry("520x180")
        self.configure(fg_color=COLOR_BG)
        self.resizable(False, False)
        self._build_ui(title)
        try:
            self.grab_set()
        except Exception:
            pass

    def _build_ui(self, title: str):
        card = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=10,
                            border_width=1, border_color=COLOR_BORDER)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        self.title_label = ctk.CTkLabel(
            card, text=title,
            font=("Segoe UI", 13, "bold"), anchor="w",
        )
        self.title_label.pack(fill="x", padx=16, pady=(14, 4))

        self.status_label = ctk.CTkLabel(
            card, text="Démarrage…",
            font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED, anchor="w",
        )
        self.status_label.pack(fill="x", padx=16, pady=(0, 8))

        self.bar = ctk.CTkProgressBar(card, height=14, corner_radius=4,
                                      progress_color=ACTION_PRIMARY)
        self.bar.pack(fill="x", padx=16, pady=(0, 10))
        self.bar.set(0)

        self.pct_label = ctk.CTkLabel(
            card, text="0 %",
            font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED,
        )
        self.pct_label.pack(padx=16, pady=(0, 12))

    # -------- API --------
    def set_progress(self, step: str, current: int, total: int):
        """À appeler depuis le thread principal."""
        if total <= 0:
            self.bar.set(0)
            pct = 0.0
        else:
            pct = min(1.0, current / total)
            self.bar.set(pct)
        labels = {
            "scan": "Scan des fichiers",
            "zip": "Compression",
            "hash": "Vérification d'intégrité",
            "extract": "Extraction",
            "verify": "Vérification SHA256",
            "backup": "Backup local",
        }
        step_label = labels.get(step, step)
        if total > 0 and step != "hash":
            self.status_label.configure(text=f"{step_label} — {current} / {total}")
        else:
            self.status_label.configure(text=f"{step_label}…")
        self.pct_label.configure(text=f"{int(pct * 100)} %")

    def _set_progress_safe(self, step: str, current: int, total: int):
        """Version thread-safe (appelée depuis le worker thread)."""
        try:
            self.after(0, lambda: self.set_progress(step, current, total))
        except Exception:
            pass

    def run_in_thread(
        self,
        worker: Callable,
        on_done: Callable | None = None,
    ):
        """Lance `worker(progress_cb)` dans un thread. À la fin, appelle on_done(result, err).

        on_done est appelée MÊME si la dialog a été fermée pendant l'opération
        (Alt+F4, croix). Sans ça, un user qui ferme la dialog pendant un push
        long ne savait jamais si ça a marché — le bundle pouvait être sur le
        cloud sans aucune confirmation visible.
        """
        def thread_target():
            err = None
            result = None
            try:
                result = worker(self._set_progress_safe)
            except Exception as e:
                err = e

            def finalize():
                # destroy() peut throw si déjà détruite par l'user → on swallow
                try:
                    self.destroy()
                except Exception:
                    pass
                if on_done:
                    on_done(result, err)

            # On essaie d'abord de marshaler sur le main thread via after(0, ...)
            # — chemin nominal quand la dialog est encore vivante.
            try:
                self.after(0, finalize)
                return
            except Exception:
                pass

            # Fallback : dialog détruite → on cherche un autre widget pour
            # appeler on_done sur le main thread. self.master pointe sur la
            # fenêtre principale (App) qui devrait être vivante.
            master = getattr(self, "master", None)
            if master is not None and on_done is not None:
                try:
                    master.after(0, lambda: on_done(result, err))
                    return
                except Exception:
                    pass

            # Dernier recours : appeler on_done depuis ce thread. Pas idéal
            # (callbacks UI Tk doivent vivre sur le main thread), mais mieux
            # que de laisser l'user sans feedback. Les implémentations
            # actuelles d'on_done lancent un messagebox qui sait gérer ça.
            if on_done is not None:
                try:
                    on_done(result, err)
                except Exception:
                    pass

        threading.Thread(target=thread_target, daemon=True).start()
