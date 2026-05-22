"""Test que ProgressDialog.run_in_thread appelle on_done même si la dialog
est fermée pendant l'opération.

Avant v0.3.6 : si l'user fermait la dialog (Alt+F4) pendant un push, le
`self.after(0, finalize)` levait TclError, le `try/except` swallowait, et
on_done n'était jamais appelée → user sans aucun feedback.

Ces tests utilisent un mock minimal de Tk pour éviter une vraie boucle UI.
"""
from __future__ import annotations

import threading
import time

import pytest


class _FakeDialog:
    """Mock minimal d'un ProgressDialog déjà détruit (after() lève TclError)."""

    def __init__(self, master=None):
        self.master = master
        self.destroyed = False
        self.set_progress_calls = []

    def destroy(self):
        self.destroyed = True

    def after(self, ms, fn=None, *args):
        # Si la dialog est "détruite", simuler le comportement Tk : TclError
        if self.destroyed:
            raise RuntimeError("Tk widget destroyed")
        # Sinon, on exécute immédiatement (pas de boucle Tk pour les tests)
        if fn is not None:
            try:
                fn(*args)
            except Exception:
                pass


class _FakeMaster:
    """Master qui reste vivant et exécute after() immédiatement."""
    def __init__(self):
        self.alive = True

    def after(self, ms, fn=None, *args):
        if not self.alive:
            raise RuntimeError("master destroyed")
        if fn is not None:
            fn(*args)


def _patch_dialog_to_use_run_in_thread(dialog):
    """Bind run_in_thread du vrai ProgressDialog au mock pour le tester."""
    from pzsavesync.progress_dialog import ProgressDialog
    return ProgressDialog.run_in_thread.__get__(dialog)


def test_on_done_called_when_dialog_alive():
    """Cas nominal : dialog vivante, on_done appelée."""
    master = _FakeMaster()
    dlg = _FakeDialog(master=master)
    # Stub _set_progress_safe (pas utilisé par le worker simple)
    dlg._set_progress_safe = lambda *a, **kw: None
    run_in_thread = _patch_dialog_to_use_run_in_thread(dlg)

    done = threading.Event()
    captured = {}

    def worker(progress_cb):
        return "RESULT-OK"

    def on_done(result, err):
        captured["result"] = result
        captured["err"] = err
        done.set()

    run_in_thread(worker, on_done=on_done)
    done.wait(timeout=2)
    assert done.is_set(), "on_done jamais appelée"
    assert captured["result"] == "RESULT-OK"
    assert captured["err"] is None
    assert dlg.destroyed is True


def test_on_done_called_when_dialog_destroyed_mid_op():
    """Cas régression : dialog détruite avant la fin → on_done quand même appelée
    via le fallback master.after().
    """
    master = _FakeMaster()
    dlg = _FakeDialog(master=master)
    dlg._set_progress_safe = lambda *a, **kw: None
    run_in_thread = _patch_dialog_to_use_run_in_thread(dlg)

    done = threading.Event()
    captured = {}

    def worker(progress_cb):
        # Simule l'user qui ferme la dialog pendant l'opération
        dlg.destroyed = True
        return "RESULT-AFTER-CLOSE"

    def on_done(result, err):
        captured["result"] = result
        captured["err"] = err
        done.set()

    run_in_thread(worker, on_done=on_done)
    done.wait(timeout=2)
    assert done.is_set(), (
        "on_done jamais appelée alors que la dialog était détruite — "
        "régression du fix v0.3.6 : on_done DOIT être appelée pour que "
        "l'user voie le messagebox de succès/erreur."
    )
    assert captured["result"] == "RESULT-AFTER-CLOSE"


def test_on_done_called_with_error_when_worker_raises():
    """Si le worker lève, on_done reçoit l'exception en 2e argument."""
    master = _FakeMaster()
    dlg = _FakeDialog(master=master)
    dlg._set_progress_safe = lambda *a, **kw: None
    run_in_thread = _patch_dialog_to_use_run_in_thread(dlg)

    done = threading.Event()
    captured = {}

    def worker(progress_cb):
        raise ValueError("boom")

    def on_done(result, err):
        captured["result"] = result
        captured["err"] = err
        done.set()

    run_in_thread(worker, on_done=on_done)
    done.wait(timeout=2)
    assert done.is_set()
    assert captured["result"] is None
    assert isinstance(captured["err"], ValueError)
    assert str(captured["err"]) == "boom"


def test_on_done_last_resort_when_dialog_and_master_both_dead():
    """Dialog ET master détruits → on_done est quand même appelée en synchrone
    (dernier recours). User a son feedback même si pas thread-safe Tk."""
    master = _FakeMaster()
    master.alive = False  # Master "mort" → after() lève
    dlg = _FakeDialog(master=master)
    dlg._set_progress_safe = lambda *a, **kw: None
    run_in_thread = _patch_dialog_to_use_run_in_thread(dlg)

    done = threading.Event()
    captured = {}

    def worker(progress_cb):
        dlg.destroyed = True
        return "LAST-RESORT"

    def on_done(result, err):
        captured["result"] = result
        done.set()

    run_in_thread(worker, on_done=on_done)
    done.wait(timeout=2)
    assert done.is_set()
    assert captured["result"] == "LAST-RESORT"
