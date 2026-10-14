"""Fenêtre de base : en-tête officiel, identité de l'utilisateur, déconnexion, bannières temporisées, fermeture protégée par le PIN admin."""
import functools, os, sys
from datetime import datetime

from PyQt6.QtCore import QProcess, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QSizePolicy,
                             QPushButton, QVBoxLayout, QWidget)

from branding import HeaderBar
from config_manager import data_dir
from data_structures import SERVICE_BY_CODE
import userdata
from database import FMT
from functions import honorific
from ui_layout import FlowLayout, profile

ROLE_LABELS = {"accueil": "Accueil Général", "dedie": "Accueil dédié"}
USER_ROLE_LABELS = {"accueil": "Accueil", "medecin": "Consultation", "radio": "Radiologie", "pharmacie": "Pharmacie", "labo": "Laboratoire",
                    "soins": "Soins & Triage", "coord_med": "Coordination des médecins", "coord_para": "Coordination paramédicale"}
BANNER_MS = {"info": 4000, "error": 6000, "revisit": 10000}      # les bannières se masquent seules (3 à 10 s)


def user_label(u):
    return f"{honorific(u.get('function'))}{u['last_name']} {u['first_name']}"


def guard(fn):
    """Une panne du Hub (ConnectionError) ou un refus d'accès s'affichent en bannière au lieu de faire planter l'application.
    Les méthodes protégées acceptent *_ car Qt leur passe des arguments de signal."""
    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except ConnectionError as e:
            self.show_banner(f"⚠️ {e}", "error")
        except PermissionError as e:
            self.show_banner(f"⛔ {e}", "error")
    return wrapper


def restart_app():
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    QProcess.startDetached(sys.executable, args)
    QApplication.quit()


def quit_now():
    """Ferme l'application pour de bon (la mise à jour attend la fin du processus) : quit() puis arrêt forcé de secours."""
    QApplication.quit()
    QTimer.singleShot(2500, lambda: os._exit(0))


def tv_url(cfg, screen=""):
    host = "127.0.0.1" if cfg.get("net_mode") != "client" else cfg.get("hub_host", "127.0.0.1")
    return f"http://{host}:{cfg.get('hub_port', 5000)}/tv" + (f"?screen={screen}" if screen else "")


def open_tv(cfg):
    QDesktopServices.openUrl(QUrl(tv_url(cfg, cfg.get("tv_screen", ""))))


def revisit_text(row):
    dt = datetime.strptime(row["created_at"], FMT)
    svc = SERVICE_BY_CODE.get(row["service_code"], {}).get("name", row["service_code"])
    return f"⚠️ Information : Ce patient a déjà été enregistré le {dt:%d/%m/%Y} à {dt:%H:%M} (Service : {svc})."


class BaseWindow(QMainWindow):
    def __init__(self, cfg, db):
        super().__init__()
        self.cfg, self.db = cfg, db
        self.station = cfg.get("station_name", "")
        self.room = cfg.get("room_label", "") or self.station          # libellé du bureau affiché sur l'écran TV
        self.user = None
        self.logout_cb = None
        self._allow_close = False
        self._banner_kind = None
        self.setWindowTitle("Smart DEM")
        central = QWidget()
        self.setCentralWidget(central)
        self.root = QVBoxLayout(central)
        compact = profile(cfg)["compact"]
        self.root.setContentsMargins(8, 6, 8, 6) if compact else self.root.setContentsMargins(14, 10, 14, 10)
        self.root.setSpacing(6 if compact else 10)
        self._msg_after, self._msg_first, self._popups = 0, True, []
        self.prof = profile(cfg)
        self.root.addWidget(HeaderBar(cfg, 44 if self.prof["compact"] else 64))
        self.root.addWidget(self._build_header())
        self.content_widget = QWidget()
        self.content = QVBoxLayout(self.content_widget)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.root.addWidget(self.content_widget, 1)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt_PlainText())
        self.banner.hide()
        self.root.addWidget(self.banner)
        self._banner_timer = QTimer(self); self._banner_timer.setSingleShot(True); self._banner_timer.timeout.connect(self.hide_banner)
        if cfg.get("auto_update_check", True):
            QTimer.singleShot(6000, self._auto_update_check)
        QTimer.singleShot(2500, self._check_update_result)
        self._msg_timer = QTimer(self); self._msg_timer.timeout.connect(self._poll_messages); self._msg_timer.start(5000)
        self._set_badge(0)

    def _build_header(self):
        f = QFrame(); f.setObjectName("card")
        f.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)        # l'en-tête ne force jamais la largeur de la fenêtre (retour à la ligne)
        outer = QVBoxLayout(f); outer.setContentsMargins(8, 6, 8, 6); outer.setSpacing(4)
        self.hdr1, self.hdr2 = QHBoxLayout(), QHBoxLayout()
        outer.addLayout(self.hdr1); outer.addLayout(self.hdr2)
        self.user_chip = QLabel("")
        self.user_chip.setStyleSheet("font-size:16px;font-weight:700;color:#4f9dff;"); self.user_chip.setTextFormat(Qt_PlainText())
        self.sub = QLabel(f"{ROLE_LABELS.get(self.cfg.get('role'), '')}  •  {self.station}")
        self.sub.setStyleSheet("color:#8b97a7;")
        box = QVBoxLayout(); box.addWidget(self.user_chip); box.addWidget(self.sub)
        self.hdr1.addLayout(box, 1)
        self.extra_box = QWidget(); self.extra_box.setStyleSheet("background:transparent;")
        self.header_extra = FlowLayout(self.extra_box, 6)
        self.btn_msg = QPushButton("✉ Messages"); self.btn_msg.clicked.connect(self.open_messages)
        self.btn_docs = QPushButton("📄 Modèles"); self.btn_docs.clicked.connect(self.open_templates); self.btn_docs.setVisible(False)
        self.b_out = QPushButton("🔒 Déconnexion"); self.b_out.clicked.connect(self.logout)
        self.b_set = QPushButton("⚙ Paramètres"); self.b_set.clicked.connect(self.open_settings)
        self.b_quit = QPushButton("⏻ Quitter"); self.b_quit.setObjectName("danger"); self.b_quit.clicked.connect(self.request_quit)
        self.std_buttons = (self.btn_msg, self.btn_docs, self.b_out, self.b_set, self.b_quit)
        self._two = None
        self._place_header(bool(self.prof["two_rows"]))
        return f

    _FULL = {"b_out": "🔒 Déconnexion", "b_set": "⚙ Paramètres", "b_quit": "⏻ Quitter", "btn_msg": "✉ Messages", "btn_docs": "📄 Modèles"}
    _SHORT = {"b_out": "🔒", "b_set": "⚙", "b_quit": "⏻", "btn_msg": "✉", "btn_docs": "📄"}

    def _place_header(self, two):
        """16:9 large : tous les boutons sur une ligne ; 4:3 / largeur insuffisante : boutons du poste sur une 2e ligne, boutons standard raccourcis."""
        self._two = two
        for lay in (self.hdr1, self.hdr2):
            lay.removeWidget(self.extra_box)
            for b in self.std_buttons:
                lay.removeWidget(b)
        while self.hdr2.count():
            self.hdr2.takeAt(0)                              # retire le stretch éventuel
        if two:
            self.hdr2.addWidget(self.extra_box); self.hdr2.addStretch(1)
        else:
            self.hdr1.addWidget(self.extra_box)
        for b in self.std_buttons:
            self.hdr1.addWidget(b)
        for name, full in self._FULL.items():
            b = getattr(self, name)
            if name == "btn_msg":
                continue                                     # libellé géré par _set_badge
            b.setText(self._SHORT[name] if two else full); b.setToolTip(full[2:] if two else "")
        self.extra_box.setVisible(self.header_extra.count() > 0 or not two)
        self._set_badge(getattr(self, "_unread", 0))

    def _auto_header(self):
        fm = self.fontMetrics()
        need = 300 + sum(self.header_extra.itemAt(i).sizeHint().width() + 6 for i in range(self.header_extra.count())
                         if not self.header_extra.itemAt(i).isEmpty()) + sum(fm.horizontalAdvance(t) + 40 for t in self._FULL.values()) + 60
        want = bool(self.prof["two_rows"]) or need > self.width()
        if want != getattr(self, "_two", None):
            self._place_header(want)
        self.extra_box.setVisible(self.header_extra.count() > 0)     # les boutons du poste sont ajoutés par la sous-classe, après la construction

    def showEvent(self, e):
        super().showEvent(e)
        self._auto_header()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._auto_header()

    # ---------- messagerie interne & modèles de documents ----------
    def _set_badge(self, n):
        self._unread = n
        self.btn_msg.setText(("✉ Messages" if not getattr(self, "_two", False) else "✉") + (f" ({n})" if n else ""))
        self.btn_msg.setToolTip("Messagerie interne : signalements et convocations")
        self.btn_msg.setStyleSheet("background:#f39c12;color:white;font-weight:700;" if n else "")

    def _poll_messages(self):
        if not self.user:
            return
        try:
            p = self.db.messages_poll(self.user["id"], self._msg_after)
        except (ConnectionError, PermissionError, OSError):
            return
        self._set_badge(p["unread"])
        new = p["new"]
        if not new:
            return
        self._msg_after = max(m["id"] for m in new)
        urgent = [m for m in new if m["kind"] == "CONVOCATION" or m["priority"] == "URGENT"]
        if self._msg_first:
            self.show_banner(f"✉ {p['unread']} message(s) non lu(s)", "info", 8000)
        else:
            m = new[-1]
            self.show_banner(f"✉ {m['from_name']} : {m['reason']}", "info", 8000)
        self._msg_first = False
        QApplication.beep()
        from ui_messages import MessagePopup
        self._popups = [x for x in self._popups if x.isVisible()]
        for m in urgent[:3]:
            pop = MessagePopup(self.db, self.user, m, self.open_messages, self)
            pop.show(); self._popups.append(pop)

    def open_messages(self, *_):
        if not self.user:
            return
        from ui_messages import MessagesDialog
        try:
            MessagesDialog(self.db, self.user, self.station, self).exec()
        except (ConnectionError, PermissionError) as e:
            self.show_banner(f"⚠️ {e}", "error")
        self._poll_messages()

    def open_appointments(self, prefill=None, *_):
        """Rendez-vous de tous les services (calendrier, ticket QR, arrivée du patient)."""
        if not self.user:
            return
        from ui_appointments import AppointmentsDialog
        dlg = AppointmentsDialog(self.db, self.cfg, self.user, self, prefill if isinstance(prefill, dict) else None)
        if hasattr(self, "refresh"):
            dlg.panel.changed.connect(self.refresh)
        dlg.exec()

    def open_documents(self, adm=None, service="", *_):
        """Certificats, fiches et formulaires du rôle (modèles importés ou standard)."""
        if not self.user:
            return
        from ui_templates import DocumentDialog
        try:
            DocumentDialog(self.db, self.cfg, self.user, adm if isinstance(adm, dict) else None, service, self).exec()
        except (ConnectionError, PermissionError) as e:
            self.show_banner(f"⚠️ {e}", "error")

    def open_templates(self, *_):
        if not self.user:
            return
        from ui_templates import TemplatesDialog
        try:
            TemplatesDialog(self.db, self.user, self).exec()
        except (ConnectionError, PermissionError) as e:
            self.show_banner(f"⚠️ {e}", "error")

    # ---------- session ----------
    def set_user(self, user):
        self.user = user
        self._msg_after, self._msg_first = 0, True
        for p in self._popups:
            p.close()
        self._popups = []
        try:
            from doc_models import kinds_for
            self.btn_docs.setVisible(bool(kinds_for(user["role"], user.get("function"))))
        except Exception:
            pass
        QTimer.singleShot(400, self._poll_messages)
        extra = f" — {user['specialty']}" if user.get("specialty") else ""
        self.user_chip.setText(f"👤 {user_label(user)}  •  {user.get('function') or USER_ROLE_LABELS.get(user['role'], '')}{extra}")
        try:
            userdata.write_profile(user, self.station)            # dossier local data/users/[SLUG]/ : profil + journal d'activité
            self.log("connexion")
        except OSError:
            pass

    def log(self, action, detail=""):
        """Journal d'activité de l'agent sur ce poste (data/users/[SLUG]/activity.log) — jamais d'identité de patient."""
        if self.user:
            userdata.log_activity(self.user, action, detail, self.station)

    def before_logout(self):
        """À surcharger : retourne False pour annuler la déconnexion (ex. consultation en cours)."""
        return True

    def logout(self, *_):
        if self.before_logout() and self.logout_cb:
            self.log("déconnexion")
            self.logout_cb()

    def on_login(self):
        """À surcharger : rafraîchir le poste pour l'utilisateur qui vient de se connecter."""

    # ---------- mises à jour ----------
    def _auto_update_check(self):
        from ui_update import CheckThread
        from version import GITHUB_REPO
        self._upd_thread = CheckThread(self.cfg.get("github_repo") or GITHUB_REPO)
        self._upd_thread.done.connect(self._on_auto_update)
        self._upd_thread.start()

    def _on_auto_update(self, info, err):
        if info and info.get("available") and not self.banner.isVisible():
            self.show_banner(f"🔔 Nouvelle version v{info['version']} disponible — Paramètres › Sécurité & Mises à Jour.", ms=10000)

    def _check_update_result(self):
        """Résultat de la dernière mise à jour (écrit par le script de mise à jour après la fermeture)."""
        p = os.path.join(data_dir(), "update_result.txt")
        if not os.path.isfile(p):
            return
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                txt = f.read().strip()
            os.remove(p)
        except OSError:
            return
        from version import __version__
        if txt.startswith("OK"):
            self.show_banner(f"✅ Mise à jour appliquée — version installée : v{__version__}.", ms=8000)
        else:
            self.show_banner(f"⚠️ La dernière mise à jour n'a pas pu être appliquée ({txt}). Réinstallez avec Smart_DEM_Setup.exe "
                             "(GitHub Releases) : vos données sont conservées.", "error", ms=20000)

    # ---------- bannière temporisée ----------
    def show_banner(self, text, kind="info", ms=None):
        style = {"info": "background:#f5b041;color:#1b1b1b;", "error": "background:#c0392b;color:white;"}[kind]
        self.banner.setStyleSheet(style + "font-weight:600;padding:10px 14px;border-radius:8px;")
        self.banner.setText(text)
        self.banner.show()
        self._banner_kind = kind if kind == "error" else "info"
        self._banner_timer.start(ms or BANNER_MS[kind])             # masquage automatique (QTimer)

    def show_revisit(self, row):
        self.show_banner(revisit_text(row), ms=BANNER_MS["revisit"])
        self._banner_kind = "revisit"

    def clear_revisit_banner(self):
        if self._banner_kind == "revisit":
            self.hide_banner()

    def hide_banner(self):
        self._banner_timer.stop(); self.banner.hide(); self._banner_kind = None

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
            QApplication.quit()

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


class HandoverDialog(QDialog):
    """Patients réservés par un confrère lors d'une relève de garde : reprise en un clic (consultation et brouillon repris)."""
    def __init__(self, db, user, services, parent=None):
        super().__init__(parent)
        self.db, self.user, self.taken = db, user, None
        self.setWindowTitle("Relève de garde — reprises en attente"); self.resize(720, 360)
        v = QVBoxLayout(self)
        from PyQt6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem
        self.rows = db.handover_list(services, user["id"])
        self.t = QTableWidget(len(self.rows), 5)
        self.t.setHorizontalHeaderLabels(["Ticket", "Patient", "De la part de", "Depuis", "Consigne"])
        self.t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t.verticalHeader().hide(); self.t.horizontalHeader().setStretchLastSection(True)
        from database import display_name
        for i, r in enumerate(self.rows):
            for j, txt in enumerate((r["ticket_label"], display_name(r), f"{honorific(r.get('from_function'))}{r['from_last']} {r['from_first']}", (r["handover_at"] or "")[11:16], r["handover_note"] or "")):
                self.t.setItem(i, j, QTableWidgetItem(txt))
        v.addWidget(self.t)
        b = QPushButton("📥 Reprendre ce patient"); b.setObjectName("primary"); b.clicked.connect(self.take); v.addWidget(b)

    def take(self, *_):
        r = self.t.currentRow()
        if not 0 <= r < len(self.rows):
            return QMessageBox.information(self, "Reprise", "Sélectionnez un patient.")
        try:
            self.taken = self.db.take_over(self.rows[r]["id"], self.user["id"])
        except (ConnectionError, PermissionError, ValueError) as e:
            return QMessageBox.warning(self, "Reprise", str(e))
        self.accept()


def Qt_PlainText():
    from PyQt6.QtCore import Qt
    return Qt.TextFormat.PlainText
