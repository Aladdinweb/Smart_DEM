"""Fenêtre de base : en-tête officiel, session utilisateur (PIN), bannière, fermeture protégée par le PIN admin."""
import functools, sys
from datetime import datetime

from PyQt6.QtCore import QProcess, QTimer
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QPushButton, QVBoxLayout, QWidget)

from branding import HeaderBar
from data_structures import SERVICE_BY_CODE
from database import FMT

ROLE_LABELS = {"accueil": "Accueil Général", "dedie": "Poste Dédié", "medecin": "Poste Médecin",
               "radio": "Poste Radiologie", "pharmacie": "Poste Pharmacie"}
USER_ROLE_LABELS = {"accueil": "Accueil", "medecin": "Médecin", "radio": "Manipulateur radio", "pharmacie": "Pharmacien"}


def user_label(u):
    name = f"{u['last_name']} {u['first_name']}"
    return ("Dr " + name) if u["role"] == "medecin" else name


def guard(fn):
    """Une panne du Hub (ConnectionError) s'affiche en bannière au lieu de faire planter l'application.
    Les méthodes protégées acceptent *_ car Qt leur passe des arguments de signal."""
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
    USER_ROLES = ()          # rôles utilisateurs autorisés à ouvrir une session sur ce poste

    def __init__(self, cfg, db):
        super().__init__()
        self.cfg, self.db = cfg, db
        self.station = cfg.get("station_name", "")
        self.user = None
        self._allow_close = False
        self._banner_kind = None
        self.setWindowTitle("Smart DEM")
        central = QWidget()
        self.setCentralWidget(central)
        self.root = QVBoxLayout(central)
        self.root.setContentsMargins(14, 10, 14, 10)
        self.root.setSpacing(10)
        self.root.addWidget(HeaderBar(cfg))
        self.root.addWidget(self._build_header())
        self.content_widget = QWidget()
        self.content = QVBoxLayout(self.content_widget)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.root.addWidget(self.content_widget, 1)
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
        t = QLabel(self.cfg.get("parent", "")); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.sub = QLabel(f"{self.cfg.get('structure', '')}  •  {ROLE_LABELS.get(self.cfg.get('role'), '')}  •  {self.station}")
        self.sub.setStyleSheet("color:#8b97a7;")
        self.user_chip = QLabel("🔒 Session verrouillée"); self.user_chip.setStyleSheet("font-weight:700;color:#4f9dff;")
        box.addWidget(t); box.addWidget(self.sub); box.addWidget(self.user_chip)
        h.addLayout(box, 1)
        self.header_extra = QHBoxLayout()
        h.addLayout(self.header_extra)
        b_out = QPushButton("🔒 Déconnexion"); b_out.clicked.connect(self.logout)
        b_set = QPushButton("⚙ Paramètres"); b_set.clicked.connect(self.open_settings)
        b_quit = QPushButton("⏻ Quitter"); b_quit.setObjectName("danger"); b_quit.clicked.connect(self.request_quit)
        for b in (b_out, b_set, b_quit):
            h.addWidget(b)
        return f

    # ---------- session (PIN) ----------
    def start_session(self):
        if not self.login():
            self._allow_close = True
            self.close()

    def _update_chip(self):
        if self.user:
            extra = f" — {self.user['specialty']}" if self.user.get("specialty") else ""
            self.user_chip.setText(f"👤 {user_label(self.user)}  •  {USER_ROLE_LABELS.get(self.user['role'], '')}{extra}")
        else:
            self.user_chip.setText("🔒 Session verrouillée")

    def login(self):
        """Verrouille l'écran puis demande le PIN. Retourne False si l'application doit se fermer."""
        from ui_login import LoginDialog
        self.user = None
        self._update_chip()
        self.content_widget.setVisible(False)
        while True:
            dlg = LoginDialog(self.cfg, self.db, self.USER_ROLES, self)
            res = dlg.exec()
            if dlg.quit_requested:
                return False
            if res == QDialog.DialogCode.Accepted and dlg.user:
                break
        self.user = dlg.user
        self._update_chip()
        self.content_widget.setVisible(True)
        self.on_login()
        return True

    def logout(self, *_):
        if not self.login():
            self._allow_close = True
            self.close()

    def on_login(self):
        """À surcharger : rafraîchir le poste pour l'utilisateur qui vient de se connecter."""

    # ---------- mises à jour GitHub (vérification discrète) ----------
    def _auto_update_check(self):
        from ui_update import CheckThread
        from version import GITHUB_REPO
        self._upd_thread = CheckThread(self.cfg.get("github_repo") or GITHUB_REPO)
        self._upd_thread.done.connect(self._on_auto_update)
        self._upd_thread.start()

    def _on_auto_update(self, info, err):
        if info and info.get("available") and not self.banner.isVisible():
            self.show_banner(f"🔔 Nouvelle version v{info['version']} disponible — Paramètres › Sécurité & Mises à Jour.")

    # ---------- bannière non bloquante ----------
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

    # ---------- sécurité administrateur ----------
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

    def request_quit(self, *_):
        if self.ask_pin("Fermeture de l'application"):
            self._allow_close = True
            self.close()

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
        else:
            event.ignore()
            self.request_quit()

    def open_settings(self, *_):
        if not self.ask_pin("Paramètres"):
            return
        from ui_settings import SettingsDialog
        SettingsDialog(self.cfg, self.db, self).exec()
