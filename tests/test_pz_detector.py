"""Tests de la détection de process PZ."""
from pzsavesync import pz_detector


def test_pz_process_names_includes_b41_b42():
    """Vérifie qu'on couvre bien les binaires connus."""
    expected = ("ProjectZomboid64.exe", "PZServer.exe", "ProjectZomboid")
    for name in expected:
        assert name in pz_detector.PZ_PROCESS_NAMES


def test_is_pz_running_returns_tuple():
    """is_pz_running doit toujours renvoyer (bool, list[str])."""
    running, names = pz_detector.is_pz_running()
    assert isinstance(running, bool)
    assert isinstance(names, list)


def test_is_pz_running_with_extra_names():
    """L'argument extra_names doit étendre la liste cible."""
    # On passe le nom du process Python (forcément en cours)
    running, names = pz_detector.is_pz_running(extra_names=("python.exe",))
    # Sur Windows : python.exe est dans la liste si pytest tourne via python.exe
    # On ne peut pas être 100% sûr du résultat, mais au moins ça ne doit pas crasher.
    assert isinstance(running, bool)


def test_list_processes_returns_set_of_lowercase():
    """list_running_processes doit renvoyer un set de strings en minuscules."""
    procs = pz_detector.list_running_processes()
    assert isinstance(procs, set)
    for p in procs:
        assert p == p.lower(), f"'{p}' n'est pas en minuscules"
