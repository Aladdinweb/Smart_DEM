"""Rendez-vous de TOUS les services (v1.4.0) : calendrier, n° de passage, ticket imprimé avec QR code, et arrivée du patient le jour J
(scan du QR ou bouton) qui l'insère automatiquement dans la file du service à la place correspondant à l'heure du rendez-vous."""
from PyQt6.QtCore import QDate, QTime, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat
from PyQt6.QtWidgets import (QAbstractItemView, QCalendarWidget, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                             QTimeEdit, QVBoxLayout, QWidget)

from archive import archive_reception
from data_structures import SERVICE_BY_CODE, SERVICES
from printer import print_appt_ticket, print_ticket

STATUS = {"PLANNED": "📅 Prévu", "ARRIVED": "🚶 Arrivé", "DONE": "✅ Fait", "CANCELLED": "✖ Annulé"}
NO_APPT = ("URG", "SOINS")                      # mêmes exclusions que Database._APPT_NOT


def allowed_services(user):
    """Codes de service pour lesquels cet utilisateur peut gérer des rendez-vous."""
    role = user["role"]
    every = [s["code"] for s in SERVICES if s["code"] not in NO_APPT]
    if role == "accueil":
        return every
    if role == "labo":
        return ["LAB", "LABP"]
    if role == "radio":
        return ["RAD"]
    mine = [c for c in (user.get("services") or []) if c in every]
    return mine or ["MG"]


def _svc_label(code):
    s = SERVICE_BY_CODE.get(code or "LAB", {"icon": "", "name": code or ""})
    return f"{s['icon']} {s['name']}".strip()


class ApptEditDialog(QDialog):
    def __init__(self, services, a=None, day=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rendez-vous")
        a = a or {}
        f = QFormLayout(self)
        self.svc = QComboBox()
        for c in services:
            self.svc.addItem(_svc_label(c).replace("&", "&&"), c)
        if a.get("service_code"):
            self.svc.setCurrentIndex(max(0, self.svc.findData(a["service_code"])))
        self.svc.setEnabled(len(services) > 1)
        self.last, self.first = QLineEdit(a.get("last_name", "")), QLineEdit(a.get("first_name", ""))
        self.year = QLineEdit(str(a.get("birth_year") or "")); self.year.setPlaceholderText("année de naissance (ex : 1985)")
        self.gender = QComboBox(); self.gender.addItem("— Sexe —", ""); self.gender.addItem("Homme", "H"); self.gender.addItem("Femme", "F")
        self.gender.setCurrentIndex(max(0, self.gender.findData(a.get("gender") or "")))
        self.phone, self.ident = QLineEdit(a.get("phone", "")), QLineEdit(a.get("ident", ""))
        self.date = QDateEdit(QDate.fromString(a["date"], "yyyy-MM-dd") if a.get("date") else (day or QDate.currentDate())); self.date.setCalendarPopup(True)
        self.date.setMinimumDate(QDate.currentDate().addYears(-1) if a.get("date") else QDate.currentDate())
        self.time = QTimeEdit(QTime.fromString(a["time"], "HH:mm") if a.get("time") else QTime(8, 0)); self.time.setDisplayFormat("HH:mm")
        self.exam, self.notes = QLineEdit(a.get("exam", "")), QLineEdit(a.get("notes", ""))
        self.exam.setPlaceholderText("motif / examen / analyses")
        self.status = QComboBox()
        for k, v in STATUS.items():
            self.status.addItem(v, k)
        if a.get("status"):
            self.status.setCurrentIndex(max(0, self.status.findData(a["status"])))
        self._edit = bool(a.get("id"))
        for lab, w in (("Service", self.svc), ("Nom", self.last), ("Prénom", self.first), ("Naissance", self.year), ("Sexe", self.gender),
                       ("Téléphone", self.phone), ("N° d'identification", self.ident), ("Date", self.date), ("Heure", self.time),
                       ("Motif / examen", self.exam), ("Notes", self.notes)):
            f.addRow(lab + " :", w)
        if self._edit:
            f.addRow("Statut :", self.status)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); f.addRow(bb)

    def _ok(self):
        y = self.year.text().strip()
        if len(self.last.text().strip()) < 2 or not self.first.text().strip():
            return QMessageBox.warning(self, "Rendez-vous", "Nom et prénom obligatoires.")
        if y and not (y.isdigit() and 1890 <= int(y)):
            return QMessageBox.warning(self, "Rendez-vous", "Année de naissance invalide.")
        self.accept()

    def values(self):
        y = self.year.text().strip()
        v = {"service_code": self.svc.currentData(), "last_name": self.last.text(), "first_name": self.first.text(), "birth_year": int(y) if y.isdigit() else None,
             "gender": self.gender.currentData() or None, "phone": self.phone.text(), "ident": self.ident.text(), "date": self.date.date().toString("yyyy-MM-dd"),
             "time": self.time.time().toString("HH:mm"), "exam": self.exam.text(), "notes": self.notes.text()}
        if self._edit:
            v["status"] = self.status.currentData()
        return v


def _tbl(headers):
    t = QTableWidget(0, len(headers)); t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); t.verticalHeader().hide()
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); t.horizontalHeader().setStretchLastSection(True)
    return t


class AppointmentsPanel(QWidget):
    changed = pyqtSignal()                      # un patient a été mis en file : la fenêtre hôte rafraîchit sa file

    def __init__(self, db, cfg, parent=None):
        super().__init__(parent)
        self.db, self.cfg, self.user, self.station = db, cfg, None, cfg.get("station_name", "")
        self._appts, self._day, self.services = [], [], []
        v = QVBoxLayout(self)
        scan = QHBoxLayout()
        self.scan = QLineEdit(); self.scan.setPlaceholderText("📷 Arrivée : scannez le QR du ticket de rendez-vous ici (lecteur USB) puis Entrée")
        self.scan.returnPressed.connect(self._scan)
        self.svc_filter = QComboBox(); self.svc_filter.currentIndexChanged.connect(self.refresh)
        scan.addWidget(self.scan, 1); scan.addWidget(self.svc_filter)
        self.msg = QLabel(""); self.msg.setWordWrap(True); self.msg.setTextFormat(Qt.TextFormat.PlainText)
        v.addLayout(scan); v.addWidget(self.msg)
        sp = QSplitter(Qt.Orientation.Horizontal); v.addWidget(sp, 1)
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        self.cal = QCalendarWidget(); self.cal.setGridVisible(True)
        self.cal.selectionChanged.connect(self.refresh); self.cal.currentPageChanged.connect(lambda *_: self._mark_days())
        self.day_table = _tbl(["Heure", "N°", "Patient", "Service", "Statut"])
        lv.addWidget(self.cal); lv.addWidget(QLabel("Rendez-vous du jour sélectionné :")); lv.addWidget(self.day_table, 1)
        sp.addWidget(left)
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Rechercher (nom, prénom, N° d'identification, téléphone)…"); self.search.textChanged.connect(self.refresh)
        self.range = QComboBox(); self.range.addItems(["Ce mois", "30 prochains jours", "Tous (±1 an)"]); self.range.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.search, 1); top.addWidget(self.range)
        self.all_table = _tbl(["Date", "Heure", "N°", "Patient", "Service", "Motif", "Statut", "Tél."])
        rv.addLayout(top); rv.addWidget(QLabel("Liste globale des rendez-vous :")); rv.addWidget(self.all_table, 1)
        row = QHBoxLayout()
        self.btn_checkin = QPushButton("🎟 Arrivé → mettre en file"); self.btn_checkin.setObjectName("primary"); self.btn_checkin.clicked.connect(self.checkin_selected)
        for label, fn in (("➕ Nouveau", self.new_appt), ("✏️ Modifier", self.edit_appt), ("🖨 Ticket RDV (QR)", self.print_selected), ("🗑 Supprimer", self.del_appt)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        row.addWidget(self.btn_checkin); rv.addLayout(row)
        sp.addWidget(right); sp.setSizes([420, 700])

    # ---------- session ----------
    def set_user(self, user):
        self.user, self.services = user, allowed_services(user)
        self.svc_filter.blockSignals(True); self.svc_filter.clear()
        self.svc_filter.addItem("Tous mes services", "")
        for c in self.services:
            self.svc_filter.addItem(_svc_label(c).replace("&", "&&"), c)
        self.svc_filter.setVisible(len(self.services) > 1); self.svc_filter.blockSignals(False)
        self.btn_checkin.setVisible(user["role"] in ("accueil", "labo", "radio"))
        self.scan.setVisible(user["role"] in ("accueil", "labo", "radio"))
        self.refresh()

    def _sel(self):
        for table, rows in ((self.all_table, self._appts), (self.day_table, self._day)):
            r = table.currentRow()
            if 0 <= r < len(rows):
                return rows[r]
        return None

    def _err(self, text):
        self.msg.setStyleSheet("color:#e74c3c;font-weight:700;"); self.msg.setText(text)

    def _ok(self, text):
        self.msg.setStyleSheet("color:#2ecc71;font-weight:700;"); self.msg.setText(text)

    def _safe(self, fn, *a, **k):
        try:
            return fn(*a, **k)
        except (ConnectionError, PermissionError, ValueError) as e:
            self._err(str(e)); return None

    # ---------- affichage ----------
    def refresh(self, *_):
        if not self.user:
            return
        d = self.cal.selectedDate()
        first = QDate(d.year(), d.month(), 1)
        lo, hi = {0: (first, first.addMonths(1).addDays(-1)), 1: (QDate.currentDate(), QDate.currentDate().addDays(30)),
                  2: (QDate.currentDate().addYears(-1), QDate.currentDate().addYears(1))}[self.range.currentIndex()]
        f = lambda q: q.toString("yyyy-MM-dd")
        svc = self.svc_filter.currentData() or None
        try:
            self._appts = self.db.list_appointments(f(lo), f(hi), self.search.text(), self.user["id"], svc)
            self._day = self.db.list_appointments(f(d), f(d), "", self.user["id"], svc)
        except (ConnectionError, PermissionError) as e:
            return self._err(str(e))
        name = lambda a: f"{a['last_name']} {a['first_name']}"
        for table, rows, cols in ((self.all_table, self._appts, lambda a: (a["date"], a["time"], str(a.get("number") or ""), name(a), _svc_label(a.get("service_code")), a["exam"], STATUS[a["status"]], a["phone"])),
                                  (self.day_table, self._day, lambda a: (a["time"], str(a.get("number") or ""), name(a), _svc_label(a.get("service_code")), STATUS[a["status"]]))):
            table.setRowCount(len(rows))
            for i, a in enumerate(rows):
                for j, t in enumerate(cols(a)):
                    table.setItem(i, j, QTableWidgetItem(t or ""))
        self._mark_days()

    def _mark_days(self):
        self.cal.setDateTextFormat(QDate(), QTextCharFormat())
        fmt = QTextCharFormat(); fmt.setBackground(QColor("#2f80ed")); fmt.setForeground(QColor("white"))
        month = f"{self.cal.yearShown()}-{self.cal.monthShown():02d}"
        try:
            for day in self.db.appointment_days(month, self.user["id"], self.svc_filter.currentData() or None):
                self.cal.setDateTextFormat(QDate.fromString(day, "yyyy-MM-dd"), fmt)
        except (ConnectionError, PermissionError):
            pass

    # ---------- actions ----------
    def new_appt(self, *_, prefill=None):
        if not self.user:
            return
        pre = dict(prefill or {})
        d = ApptEditDialog(self.services, pre, self.cal.selectedDate(), self)
        if d.exec():
            a = self._safe(self.db.create_appointment, d.values(), self.user["id"])
            if a:
                self.refresh()
                self._ok(f"✅ Rendez-vous enregistré : {a['date']} à {a['time']} — n° de passage {a['number']}.")
                if QMessageBox.question(self, "Ticket de rendez-vous", "Imprimer le ticket avec QR code maintenant ?") == QMessageBox.StandardButton.Yes:
                    ok, m = print_appt_ticket(self.cfg, a)
                    if not ok:
                        self._err(f"Impression impossible : {m}")

    def edit_appt(self, *_):
        a = self._sel()
        if not a:
            return self._err("Sélectionnez un rendez-vous.")
        d = ApptEditDialog(self.services, a, None, self)
        if d.exec() and self._safe(self.db.update_appointment, a["id"], d.values(), self.user["id"]):
            self.refresh()

    def del_appt(self, *_):
        a = self._sel()
        if not a:
            return self._err("Sélectionnez un rendez-vous.")
        if QMessageBox.question(self, "Supprimer", f"Supprimer le rendez-vous de {a['last_name']} {a['first_name']} ?") == QMessageBox.StandardButton.Yes:
            self._safe(self.db.delete_appointment, a["id"], self.user["id"]); self.refresh()

    def print_selected(self, *_):
        a = self._sel()
        if not a:
            return self._err("Sélectionnez un rendez-vous.")
        ok, m = print_appt_ticket(self.cfg, a)
        (self._ok if ok else self._err)(("🖨 " + m) if ok else f"Impression impossible : {m}")

    def _scan(self):
        ref = self.scan.text().strip(); self.scan.clear()
        if ref:
            self._checkin(ref)

    def checkin_selected(self, *_):
        a = self._sel()
        if not a:
            return self._err("Sélectionnez un rendez-vous.")
        self._checkin(a["id"])

    def _checkin(self, ref):
        if not self.user:
            return
        extra = None
        for _try in range(2):
            try:
                r = self.db.appointment_checkin(ref, self.user["id"], self.station, extra)
                break
            except ValueError as e:
                if str(e).startswith("INCOMPLET:") and extra is None:
                    extra = self._ask_missing()
                    if extra:
                        continue
                    return self._err("Arrivée annulée : sexe et année de naissance sont nécessaires.")
                return self._err(str(e))
            except (ConnectionError, PermissionError) as e:
                return self._err(str(e))
        else:
            return
        adm = r["admission"]
        ok, m = print_ticket(self.cfg, adm)
        if self.user["role"] == "accueil":
            try:
                archive_reception(adm)
            except OSError:
                pass
        self.refresh(); self.changed.emit()
        self._ok(f"✅ {adm['ticket_label']} — {adm['last_name']} {adm['first_name']} inséré dans la file selon son heure de rendez-vous ({r['appointment']['time']})." + ("" if ok else f"  ⚠ ticket : {m}"))

    def _ask_missing(self):
        box = QMessageBox(QMessageBox.Icon.Question, "Rendez-vous incomplet", "Ce rendez-vous (ancien) n'a pas de sexe / année de naissance.\nSexe du patient ?", parent=self)
        h = box.addButton("Homme", QMessageBox.ButtonRole.AcceptRole); f = box.addButton("Femme", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole); box.exec()
        g = "H" if box.clickedButton() is h else ("F" if box.clickedButton() is f else None)
        if not g:
            return None
        y, ok = QInputDialog.getInt(self, "Année de naissance", "Année de naissance :", 1985, 1890, QDate.currentDate().year())
        return {"gender": g, "birth_year": y} if ok else None


class AppointmentsDialog(QDialog):
    def __init__(self, db, cfg, user, parent=None, prefill=None):
        super().__init__(parent)
        self.setWindowTitle("Rendez-vous"); self.resize(1100, 700)
        v = QVBoxLayout(self)
        self.panel = AppointmentsPanel(db, cfg, self); self.panel.set_user(user); v.addWidget(self.panel)
        if prefill:
            QTimer.singleShot(0, lambda: self.panel.new_appt(prefill=prefill))
