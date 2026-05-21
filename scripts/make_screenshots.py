"""Génère les screenshots du README avec des données 100% factices.

Aucun fichier perso (config.json, dossier Zomboid réel) n'est touché.
Tout est isolé dans un dossier temporaire qui est nettoyé à la fin.

Usage:
    python scripts/make_screenshots.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# --- Données factices ---
FAKE_PLAYER = "Survivor42"
FAKE_SHARED_FOLDER = r"D:\PZ_avec_potes"
FAKE_SAVES = [
    ("Muldraugh_Coop", ["Survivor42", "JimBob"], True, 240, 18),       # active, server
    ("Riverside_HardMode", ["Survivor42", "JimBob", "AlexZ"], False, 380, 42),
    ("Westpoint_Vanilla", ["Survivor42"], False, 120, 7),
]


def build_fake_zomboid(root: Path) -> None:
    """Construit une arbo Zomboid factice avec saves serveur + persos en DB."""
    for save_name, players, _active, chunks, structures in FAKE_SAVES:
        save_dir = root / "Saves" / "Multiplayer" / save_name
        save_dir.mkdir(parents=True, exist_ok=True)
        # Map chunks (fake content)
        for i in range(min(chunks, 250)):
            (save_dir / f"map_{825 + i // 16}_{1155 + i % 16}.bin").write_bytes(
                b"chunk" * 1024
            )
        # Chunkdata
        for i in range(min(chunks // 5, 50)):
            (save_dir / f"chunkdata_{27 + i}_{38 + i}.bin").write_bytes(b"cd" * 512)
        # Structures
        names = ["campfire", "wall", "door", "barricade", "trap"]
        for i in range(min(structures, 50)):
            (save_dir / f"gos_{names[i % len(names)]}_{i}.bin").write_bytes(b"struct")
        (save_dir / "WorldDictionary.bin").write_bytes(b"mods-bin")

        # DB SQLite avec joueurs
        db_dir = root / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        db = db_dir / f"{save_name}.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE whitelist(username TEXT)")
        con.executemany(
            "INSERT INTO whitelist(username) VALUES (?)",
            [(p,) for p in players],
        )
        con.commit()
        con.close()

        # Server config
        srv = root / "Server"
        srv.mkdir(parents=True, exist_ok=True)
        ini_content = (
            f"Public=false\n"
            f"PVP=false\n"
            f"Mods=BetterSorting;ProperZeds;MoreTraits\n"
            f"WorkshopItems=2169435993;2200148440;1234567890\n"
            f"AdminPassword=demo_admin_pwd\n"
        )
        (srv / f"{save_name}.ini").write_text(ini_content, encoding="utf-8")
        (srv / f"{save_name}_SandboxVars.lua").write_text(
            "SandboxVars = { Zombies = 3, DayLength = 2, }", encoding="utf-8"
        )
        (srv / f"{save_name}_spawnregions.lua").write_text(
            "function SpawnRegions() return {} end", encoding="utf-8"
        )


def build_fake_shared_repo(root: Path) -> None:
    """Construit un faux dépôt partagé avec quelques versions historiques."""
    from pzsavesync.sync import SharedRepo, Version
    import datetime as dt
    import json
    repo = SharedRepo(root)
    repo.init_if_needed()
    # On injecte directement des versions fictives dans le manifest
    manifest_versions = []
    base = dt.datetime(2026, 5, 18, 21, 30, 0)
    sessions = [
        ("Muldraugh_Coop", "JimBob", 145, "Soir 1 — on a fini d'explorer la mairie"),
        ("Muldraugh_Coop", "Survivor42", 152, "Soir 2 — base posée au resto"),
        ("Muldraugh_Coop", "AlexZ", 168, "Soir 3 — Alex prend la main"),
        ("Muldraugh_Coop", "Survivor42", 174, ""),
    ]
    for i, (save, who, mb, note) in enumerate(sessions):
        ts = (base + dt.timedelta(days=i)).isoformat(timespec="seconds")
        manifest_versions.append({
            "filename": f"bundle_{save}_{ts.replace(':', '').replace('-', '')}_{who}.zip",
            "save_name": save,
            "uploaded_by": who,
            "uploaded_at": ts,
            "size_bytes": mb * 1024 * 1024,
            "has_db": True,
            "server_files": [f"{save}.ini", f"{save}_SandboxVars.lua", f"{save}_spawnregions.lua"],
            "note": note,
        })
    (root / "manifest.json").write_text(
        json.dumps({"versions": manifest_versions}, indent=2),
        encoding="utf-8",
    )


def main():
    """Patch les chemins, configure des données factices, lance l'app, capture."""
    tmp = Path(tempfile.mkdtemp(prefix="pzsavesync_screenshots_"))
    print(f"[setup] temp = {tmp}")
    fake_zomboid = tmp / "Zomboid"
    fake_zomboid.mkdir()
    fake_shared = tmp / "PZ_avec_potes"
    fake_shared.mkdir()
    fake_appdata = tmp / "appdata"
    fake_appdata.mkdir()

    print("[setup] arbo Zomboid factice...")
    build_fake_zomboid(fake_zomboid)

    print("[setup] dépôt partagé factice...")
    build_fake_shared_repo(fake_shared)

    # === MONKEY PATCHES ===
    # 1. Forcer zomboid_root() à pointer sur notre faux
    from pzsavesync import saves, bundle, config, inspector
    saves.zomboid_root = lambda: fake_zomboid
    bundle.zomboid_root = lambda: fake_zomboid

    # 2. Forcer config.load/save à utiliser un faux config.json
    fake_config_path = fake_appdata / "config.json"
    config.CONFIG_PATH = fake_config_path
    config.APP_DIR = fake_appdata

    # 3. Préparer la config factice (v0.3+ : profils)
    cfg = config.Config()
    # Profil "default" déjà créé par défaut, on remplit ses champs via les properties
    cfg.player_name = FAKE_PLAYER
    cfg.shared_folder = FAKE_SHARED_FOLDER  # AFFICHÉ, mais le vrai SharedRepo pointera sur fake_shared
    cfg.save_name = "Muldraugh_Coop"
    cfg.save_type = "Multiplayer"
    # Ajouter un second profil pour montrer le sélecteur multi-groupes
    cfg.add_profile("groupe_b", "Apocalypse_Marathon")
    cfg.onboarding_done = True
    cfg.auto_check_updates = False  # pas de check réseau dans les screenshots
    config.save(cfg)

    # 4. Pour que SharedRepo fonctionne avec notre fake_shared, on remplace temporairement
    #    le shared_folder de la config (l'app utilise cfg.shared_folder pour construire le SharedRepo)
    cfg.shared_folder = str(fake_shared)
    config.save(cfg)

    # === CAPTURE ===
    try:
        from PIL import ImageGrab
    except ImportError:
        print("[err] Pillow requis pour les screenshots : pip install Pillow")
        sys.exit(1)

    import customtkinter as ctk
    from pzsavesync import gui

    # On va lancer l'app, switcher d'onglet, capturer la fenêtre.
    shots_dir = ROOT / "docs" / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    app = gui.App()
    # Pour l'affichage des screenshots, on patche le chemin affiché en header
    # pour ne pas montrer le vrai chemin temporaire (qui contient ton username Windows).
    # On remplace fake_shared → FAKE_SHARED_FOLDER dans l'affichage uniquement.
    original_refresh = app.refresh_all

    def patched_refresh():
        original_refresh()
        # Forcer l'affichage du faux chemin propre dans le header
        app.header_cloud.configure(text=f"☁  {FAKE_SHARED_FOLDER}", text_color="#e6e8ec")

    app.refresh_all = patched_refresh
    app.refresh_all()
    app.update()
    app.update_idletasks()

    # Switcher manuellement sur chaque onglet et capturer.
    # Le CTkTabview a un .set(name) pour activer un onglet.
    tabs_widget = None
    for child in app.winfo_children():
        if isinstance(child, ctk.CTkTabview):
            tabs_widget = child
            break
    if tabs_widget is None:
        # Le tabview n'est pas un enfant direct ; on le retrouve via la sortie
        for child in app.winfo_children():
            for sub in child.winfo_children():
                if isinstance(sub, ctk.CTkTabview):
                    tabs_widget = sub
                    break

    tab_order = [
        ("🔄  Partager", "01_partager.png"),
        ("🎮  Mes parties", "02_mes_parties.png"),
        ("⚙  Réglages", "03_reglages.png"),
    ]

    for tab_name, filename in tab_order:
        if tabs_widget is not None:
            try:
                tabs_widget.set(tab_name)
            except Exception as e:
                print(f"[warn] set('{tab_name}') a échoué : {e}")
        # IMPORTANT : avant de capturer, on force l'affichage des chemins propres
        # (le vrai SharedRepo utilise un chemin temporaire qui contient le username
        # Windows ; on ne veut PAS qu'il apparaisse dans les screenshots).
        try:
            app.folder_var.set(FAKE_SHARED_FOLDER)
        except Exception:
            pass
        app.header_cloud.configure(text=f"☁  {FAKE_SHARED_FOLDER}", text_color="#e6e8ec")
        app.update()
        app.update_idletasks()
        # Laisser un petit délai pour le rendu
        time.sleep(0.5)
        app.update()
        # Géométrie de la fenêtre
        x = app.winfo_rootx()
        y = app.winfo_rooty()
        w = app.winfo_width()
        h = app.winfo_height()
        bbox = (x, y, x + w, y + h)
        print(f"[shot] {filename}  bbox={bbox}")
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        img.save(shots_dir / filename, "PNG")

    app.destroy()
    print(f"[done] Screenshots dans {shots_dir}/")


if __name__ == "__main__":
    main()
