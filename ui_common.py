"""Fenêtre de base : en-tête, bannière d'information, fermeture protégée par PIN."""
import functools, sys
from datetime import datetime

from PyQt6.QtCore import QProcess, QTimer
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from data_structures import SERVICE_BY_CODE
from database import FMT

ROLE_LABELS = {"accueil": "Accueil Général", "dedie": "Poste Dédié", "medecin": "Poste Médecin"}


def guard(fn):
    """Une panne du Hub (ConnectionError) s'affiche en bannière au lieu de faire planter l'application."""
    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except ConnectionError as e:
            self.show_banner(f"⚠️ {e}", "error")
    return wrapper


def restart_app():
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    QProcess.startDetached(sys.executable, args)
    QApplication.quit()


def revisit_text(row):
    dt = datetime.strptime(row["created_at"], FMT)
    svc = SERVICE_BY_CODE.get(row["service_code"], {}).get("name", row["service_code"])
    return f"⚠️ Information : Ce patient a déjà été enregistré le {dt:%d/%m/%Y} à {dt:%H:%M} (Service : {svc})."


class BaseWindow(QMainWindow):
    def __init__(self, cfg, db):
        super().__init__()
        self.cfg, self.db = cfg, db
        self.station = cfg.get("station_name", "")
        self._allow_close = False
        self._banner_kind = None
        self.setWindowTitle("Smart DEM")
        central = QWidget()
        self.setCentralWidget(central)
        self.root = QVBoxLayout(central)
        self.root.setContentsMargins(14, 10, 14, 10)
        self.root.setSpacing(10)
        self.root.addWidget(self._build_header())
        self.content = QVBoxLayout()
        self.root.addLayout(self.content, 1)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.hide()
        self.root.addWidget(self.banner)
        if cfg.get("auto_update_check", True):
            QTimer.singleShot(6000, self._auto_update_check)

    def _build_header(self):
        f = QFrame(); f.setObjectName("card")
        h = QHBoxLayout(f)
        box = QVBoxLayout()
        t = QLabel(self.cfg.get("parent", "")); t.setStyleSheet("font-size:20px;font-weight:700;")
        s = QLabel(f"{self.cfg.get('structure', '')}  •  {ROLE_LABELS.get(self.cfg.get('role'), '')}  •  {self.station}")
        s.setStyleSheet("color:#8b97a7;")
        box.addWidget(t); box.addWidget(s)
        h.addLayout(box, 1)
        self.header_extra = QHBoxLayout()
        h.addLayout(self.header_extra)
        b_set = QPushButton("⚙ Paramètres"); b_set.clicked.connect(self.open_settings)
        b_quit = QPushButton("⏻ Quitter"); b_quit.setObjectName("danger"); b_quit.clicked.connect(self.request_quit)
        h.addWidget(b_set); h.addWidget(b_quit)
        return f

    def _auto_update_check(self):
        from ui_update import CheckThread
        from version import GITHUB_REPO
        self._upd_thread = CheckThread(self.cfg.get("github_repo") or GITHUB_REPO)
        self._upd_thread.done.connect(self._on_auto_update)
        self._upd_thread.start()

    def _on_auto_update(self, info, err):
        if info and info.get("available") and not self.banner.isVisible():
            self.show_banner(f"🔔 Nouvelle version v{info['version']} disponible — Paramètres › Sécurité & Mises à Jour.")

    # --- bannière non bloquante ---
    def show_banner(self, text, kind="info"):
        style = {"info": "background:#f5b041;color:#1b1b1b;", "error": "background:#c0392b;color:white;"}[kind]
        self.banner.setStyleSheet(style + "font-weight:600;padding:10px 14px;border-radius:8px;")
        self.banner.setText(text)
        self.banner.show()
        self._banner_kind = kind if kind == "error" else "info"

    def show_revisit(self, row):
        self.show_banner(revisit_text(row))
        self._banner_kind = "revisit"

    def clear_revisit_banner(self):
        if self._banner_kind == "revisit":
            self.banner.hide(); self._banner_kind = None

    def hide_banner(self):
        self.banner.hide(); self._banner_kind = None

    # --- sécurité ---
    def ask_pin(self, title):
        if not self.cfg.has_pin():
            return True
        pin, ok = QInputDialog.getText(self, title, "Code PIN administrateur :", QLineEdit.EchoMode.Password)
        if not ok:
            return False
        if self.cfg.check_pin(pin):
            return True
        QMessageBox.warning(self, title, "Code PIN incorrect.")
        return False

    def request_quit(self):
        if self.ask_pin("Fermeture de l'application"):
            self._allow_close = True
            self.close()

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
        else:
            event.ignore()
            self.request_quit()

    def open_settings(self):
        if not self.ask_pin("Paramètres"):
            return
        from ui_settings import SettingsDialog
        SettingsDialog(self.cfg, self.db, self).exec()
