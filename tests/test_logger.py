"""Tests du module logger."""
from pzsavesync import logger as log_mod


def test_setup_idempotent():
    """setup() peut être appelé plusieurs fois sans dupliquer les handlers."""
    log = log_mod.setup()
    n_handlers = len(log.handlers)
    log_mod.setup()  # 2e appel
    assert len(log.handlers) == n_handlers, "setup() doit être idempotent"


def test_get_returns_child_logger():
    parent = log_mod.get("pzsavesync")
    child = log_mod.get("gui")
    assert child.name == "pzsavesync.gui"
    assert child.parent is parent or child.parent.name.startswith("pzsavesync")


def test_log_file_path_is_absolute():
    """LOG_FILE doit être un chemin absolu."""
    assert log_mod.LOG_FILE.is_absolute()


def test_purge_old_returns_int():
    n = log_mod.purge_old(days=99999)  # rien ne doit être > 99999 jours
    assert n == 0
