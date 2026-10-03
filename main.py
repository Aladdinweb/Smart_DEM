"""Smart DEM — point d'entrée."""
import os, sys, traceback

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from config_manager import Config
from database import Database, now
from styles import stylesheet


def build_db(cfg):
    """Autonome / Hub (héberge le serveur LAN + écran TV) / Client (base distante via le Hub)."""
    mode = cfg.get("net_mode", "local")
    if mode == "client":
        from remote_db import RemoteDatabase
        db = RemoteDatabase(cfg.get("hub_host"), cfg.get("hub_port", 5000), cfg.get("lan_token", ""))
        db.ping()
        return db
    db = Database(cfg.db_path)
    if mode == "hub":
        from hub_server import Hub
        Hub(db, cfg).start()
    return db


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Smart DEM")
    cfg = Config()

    def excepthook(t, v, tb):   # une exception dans un slot Qt ne doit jamais fermer l'application
        try:
            with open(os.path.join(cfg.dir, "error.log"), "a", encoding="utf-8") as f:
                f.write(f"[{now()}]\n{''.join(traceback.format_exception(t, v, tb))}\n")
        except OSError:
            pass
    sys.excepthook = excepthook
    app.setStyleSheet(stylesheet(cfg.get("theme")))

    if not cfg.get("configured"):
        from ui_setup import SetupDialog
        if SetupDialog(cfg).exec() != QDialog.DialogCode.Accepted:
            return 0
        app.setStyleSheet(stylesheet(cfg.get("theme")))

    while True:
        try:
            db = build_db(cfg)
            break
        except Exception as e:
            box = QMessageBox(QMessageBox.Icon.Critical, "Smart DEM", f"Démarrage impossible :\n{e}")
            retry = box.addButton("Réessayer", QMessageBox.ButtonRole.AcceptRole)
            local = box.addButton("Passer en mode autonome", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Quitter", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == retry:
                continue
            if box.clickedButton() == local:
                cfg.set("net_mode", "local"); cfg.save(); continue
            return 1

    role = cfg.get("role")
    if role == "medecin":
        from ui_doctor import DoctorWindow as Win
    elif role == "radio":
        from ui_radio import RadioWindow as Win
    elif role == "pharmacie":
        from ui_pharmacy import PharmacyWindow as Win
    else:
        from ui_reception import ReceptionWindow as Win
    win = Win(cfg, db)
    win.showMaximized()
    QTimer.singleShot(0, win.start_session)      # écran de connexion par PIN dès le démarrage
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
