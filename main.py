"""Smart DEM — point d'entrée : connexion par PIN, routage automatique vers l'espace du rôle, sauvegardes, résilience."""
import faulthandler, os, shutil, sys, threading, traceback
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from config_manager import Config, data_dir, resource_path
from database import Database, now
from styles import stylesheet

# Routage par rôle : un utilisateur n'ouvre QUE l'espace de son rôle (aucune navigation vers les autres espaces).
ROLES = ("accueil", "medecin", "radio", "pharmacie", "labo")


def window_class(role):
    """Classe de l'espace d'un rôle. IMPORTS STATIQUES OBLIGATOIRES : PyInstaller ne suit pas les imports dynamiques (importlib),
    un import par nom de module laisserait ces fenêtres hors de l'exécutable (« No module named 'ui_reception' » à la connexion)."""
    if role == "accueil":
        from ui_reception import ReceptionWindow as W
    elif role == "medecin":
        from ui_doctor import DoctorWindow as W
    elif role == "radio":
        from ui_radio import RadioWindow as W
    elif role == "pharmacie":
        from ui_pharmacy import PharmacyWindow as W
    elif role == "labo":
        from ui_lab import LabWindow as W
    else:
        raise ValueError(f"Rôle inconnu : {role}")
    return W


def log_error(cfg, exc_type, exc, tb):
    try:
        with open(os.path.join(cfg.dir, "error.log"), "a", encoding="utf-8") as f:
            f.write(f"[{now()}]\n{''.join(traceback.format_exception(exc_type, exc, tb))}\n")
    except OSError:
        pass


def selftest(outfile):
    """Auto-test de l'EXÉCUTABLE COMPILÉ (exécuté par la CI après PyInstaller) : chaque espace se construit et se connecte."""
    import tempfile
    tmp = tempfile.mkdtemp()
    os.environ.update({"QT_QPA_PLATFORM": "offscreen", "LOCALAPPDATA": tmp, "HOME": tmp})
    lines, ok = [], True
    try:
        app = QApplication(sys.argv)
        cfg = Config(); cfg.set("auto_update_check", False)
        db = Database(cfg.db_path)
        for role in ROLES:
            db.create_user(role.upper(), "Test", role, "", "1234", ["MG"] if role == "medecin" else [])
            user = db.list_users(roles=[role])[0]
            w = window_class(role)(cfg, db)
            w.set_user(user); w.on_login(); w._allow_close = True; w.close()
            lines.append(f"OK espace {role}")
        import ui_settings, ui_dpi, ui_sigeditor, ui_login, hub_server, remote_db, github_updater, sync, reports, documents  # noqa
        import printer, templates, barcode, qr, imgproc, fhir, tls, crypto  # noqa
        lines.append("OK modules")
    except Exception:
        ok = False
        lines.append("ECHEC\n" + traceback.format_exc())
    with open(outfile, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0 if ok else 1


def make_db(cfg):
    """Autonome / Hub (héberge le serveur LAN + écran TV) / Client (base distante via le Hub)."""
    mode = cfg.get("net_mode", "local")
    if mode == "client":
        from remote_db import RemoteDatabase
        db = RemoteDatabase(cfg.get("hub_host"), cfg.get("hub_port", 5000), cfg.get("lan_token", ""), use_tls=bool(cfg.get("hub_tls")),
                            tls_port=int(cfg.get("hub_tls_port", 5443)), cert_pem=cfg.get("hub_cert_pem", ""))
        db.ping()
        return db
    db = Database(cfg.db_path)
    db.backup_dir = os.path.join(cfg.dir, "backups")
    db.sync_enabled = bool(cfg.get("sync_enabled"))
    if not db.integrity_ok():
        raise RuntimeError("corrupt")
    if mode == "hub":
        from hub_server import Hub
        Hub(db, cfg).start()
    return db


def restore_latest(cfg):
    """Base endommagée : on met de côté le fichier corrompu et on restaure la dernière sauvegarde automatique."""
    folder = os.path.join(cfg.dir, "backups")
    files = sorted(f for f in os.listdir(folder) if f.startswith("dem_database_") and f.endswith(".db")) if os.path.isdir(folder) else []
    if not files:
        return None
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(cfg.db_path + suffix):
            os.replace(cfg.db_path + suffix, f"{cfg.db_path}{suffix}.corrompu_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copyfile(os.path.join(folder, files[-1]), cfg.db_path)
    return files[-1]


class Controller(QObject):
    """Connexion -> ouverture de la fenêtre du rôle -> déconnexion -> nouvelle connexion (changement de médecin / d'agent sans fermer l'application)."""
    def __init__(self, app, cfg, db):
        super().__init__()
        self.app, self.cfg, self.db, self.win = app, cfg, db, None

    def next_login(self):
        from ui_login import LoginDialog
        dlg = LoginDialog(self.cfg, self.db, None)           # tous les rôles : l'espace est choisi d'après le compte
        dlg.exec()
        if dlg.quit_requested or not dlg.user:
            self.app.quit(); return
        self.open_window(dlg.user)

    def open_window(self, user):
        win = None
        try:
            win = window_class(user["role"])(self.cfg, self.db)
            win.logout_cb = self.on_logout
            win.set_user(user)
            win.showMaximized()
            win.on_login()
            self.win = win
        except Exception as e:           # jamais d'application « fantôme » sans fenêtre : on le dit, on journalise, on revient à la connexion
            log_error(self.cfg, type(e), e, e.__traceback__)
            if win is not None:
                win._allow_close = True; win.close(); win.deleteLater()
            QMessageBox.critical(None, "Smart DEM", f"L'espace « {user['role']} » n'a pas pu s'ouvrir.\n\n{type(e).__name__} : {e}\n\n"
                                 "Détail enregistré dans error.log (dossier %LOCALAPPDATA%\\Smart_DEM).")
            QTimer.singleShot(0, self.next_login)

    def on_logout(self):
        w, self.win = self.win, None
        if hasattr(self.db, "logout"):
            self.db.logout()                                 # le jeton de session est abandonné
        w._allow_close = True
        w.close(); w.deleteLater()
        QTimer.singleShot(0, self.next_login)


def housekeeping(cfg, db, app):
    """Sauvegarde quotidienne, rapport mensuel DSP, synchronisation en arrière-plan (hub / autonome seulement)."""
    if not isinstance(db, Database):
        return
    if db.last_backup_age_hours() >= 24:
        db.auto_backup("quotidienne")
    timer = QTimer(app); timer.timeout.connect(lambda: db.last_backup_age_hours() >= 24 and db.auto_backup("quotidienne")); timer.start(3_600_000)
    app._housekeeping_timer = timer
    first = date.today().replace(day=1)
    prev_end, prev_start = first - timedelta(days=1), (first - timedelta(days=1)).replace(day=1)
    out = os.path.join(data_dir(), "reports", f"DSP_{prev_start:%Y-%m}.pdf")
    if not os.path.exists(out):                               # rapport statistique mensuel automatique pour la DSP
        try:
            from documents import header_html
            from printer import print_document
            from reports import report_html
            st = db.stats_report(prev_start.isoformat(), prev_end.isoformat())
            if st["admissions"]:
                ok, msg = print_document(cfg, report_html(cfg, st, header_html(cfg)), {}, "a4", f"rapport_DSP_{prev_start:%Y-%m}")
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "w") as f:
                    f.write(msg)                              # marqueur : rapport du mois déjà généré (le PDF est dans documents\\rapport\\)
        except Exception:
            pass
    if cfg.get("sync_enabled") and cfg.get("sync_endpoint"):
        from sync import SyncWorker
        SyncWorker(db, cfg).start()


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2])
    faulthandler.enable(open(os.path.join(Config().dir, "crash.log"), "a"))     # trace des plantages natifs
    app = QApplication(sys.argv)
    app.setApplicationName("Smart DEM")
    app.setQuitOnLastWindowClosed(False)                       # la fermeture d'une session ne ferme pas l'application
    cfg = Config()
    icon = resource_path(os.path.join("assets", "smart_dem.ico"))
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    shown = {"t": 0}

    def report(t, v, tb):   # exception globale : jamais de fermeture inattendue ; trace dans error.log, message discret
        log_error(cfg, t, v, tb)
        if datetime.now().timestamp() - shown["t"] > 30:
            shown["t"] = datetime.now().timestamp()
            QTimer.singleShot(0, lambda: QMessageBox.warning(None, "Smart DEM", "Une erreur inattendue est survenue.\nL'application continue de fonctionner ; "
                                                             "le détail est enregistré dans error.log."))
    sys.excepthook = report
    threading.excepthook = lambda a: report(a.exc_type, a.exc_value, a.exc_traceback)
    app.setStyleSheet(stylesheet(cfg.get("theme")))

    if not cfg.get("configured"):
        from ui_setup import SetupDialog
        if SetupDialog(cfg).exec() != QDialog.DialogCode.Accepted:
            return 0
        app.setStyleSheet(stylesheet(cfg.get("theme")))

    while True:
        try:
            db = make_db(cfg)
            break
        except Exception as e:
            corrupt = str(e) == "corrupt" or "malformed" in str(e).lower() or "not a database" in str(e).lower()
            box = QMessageBox(QMessageBox.Icon.Critical, "Smart DEM", "La base de données est endommagée." if corrupt else f"Démarrage impossible :\n{e}")
            retry = box.addButton("Restaurer la dernière sauvegarde" if corrupt else "Réessayer", QMessageBox.ButtonRole.AcceptRole)
            local = box.addButton("Passer en mode autonome", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Quitter", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == retry:
                if corrupt and not restore_latest(cfg):
                    QMessageBox.critical(None, "Smart DEM", "Aucune sauvegarde disponible.")
                    return 1
                continue
            if box.clickedButton() == local:
                cfg.set("net_mode", "local"); cfg.save(); continue
            return 1

    housekeeping(cfg, db, app)
    if cfg.get("tv_autostart") and cfg.get("tv_screen"):
        from ui_common import open_tv
        QTimer.singleShot(1500, lambda: open_tv(cfg))
    ctl = Controller(app, cfg, db)
    app._controller = ctl
    QTimer.singleShot(0, ctl.next_login)                       # écran de connexion par PIN dès le démarrage
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
