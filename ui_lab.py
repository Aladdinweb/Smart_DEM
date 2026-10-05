"""Poste Laboratoire (accueil / secrétariat + technicien) : tickets, file d'appel, demandes des médecins, résultats, rendez-vous (calendrier)."""
from datetime import datetime

from PyQt6.QtCore import QDate, QTime, Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut, QTextCharFormat
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCalendarWidget, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
                             QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget, QTableWidget,
                             QTableWidgetItem, QTextEdit, QTimeEdit, QVBoxLayout, QWidget)

from archive import archive_reception
from database import FMT, age_from_row, display_name, parse_age_or_birth
from printer import print_ticket
from ui_common import BaseWindow, guard, open_tv
from ui_radio import SendResultDialog, _table

STATUS = {"PLANNED": "📅 Prévu", "ARRIVED": "🚶 Arrivé", "DONE": "✅ Fait", "CANCELLED": "✖ Annulé"}


class ApptDialog(QDialog):
    def __init__(self, a=None, day=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rendez-vous d'analyses")
        f = QFormLayout(self)
        self.last, self.first = QLineEdit(a["last_name"] if a else ""), QLineEdit(a["first_name"] if a else "")
        self.year = QLineEdit(str(a["birth_year"] or "") if a else ""); self.year.setPlaceholderText("année de naissance (facultatif)")
        self.phone, self.ident = QLineEdit(a["phone"] if a else ""), QLineEdit(a["ident"] if a else "")
        self.date = QDateEdit(QDate.fromString(a["date"], "yyyy-MM-dd") if a else (day or QDate.currentDate())); self.date.setCalendarPopup(True)
        self.time = QTimeEdit(QTime.fromString(a["time"], "HH:mm") if a else QTime(8, 0)); self.time.setDisplayFormat("HH:mm")
        self.exam, self.notes = QLineEdit(a["exam"] if a else ""), QLineEdit(a["notes"] if a else "")
        self.status = QComboBox()
        for k, v in STATUS.items():
            self.status.addItem(v, k)
        if a:
            self.status.setCurrentIndex(max(0, self.status.findData(a["status"])))
        for lab, w in (("Nom", self.last), ("Prénom", self.first), ("Naissance", self.year), ("Téléphone", self.phone), ("N° d'identification", self.ident),
                       ("Date", self.date), ("Heure", self.time), ("Analyses", self.exam), ("Notes", self.notes)):
            f.addRow(lab + " :", w)
        if a:
            f.addRow("Statut :", self.status)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); f.addRow(bb)

    def _ok(self):
        if len(self.last.text().strip()) < 2 or not self.first.text().strip():
            QMessageBox.warning(self, "Rendez-vous", "Nom et prénom obligatoires."); return
        self.accept()

    def values(self):
        y = self.year.text().strip()
        return {"last_name": self.last.text(), "first_name": self.first.text(), "birth_year": int(y) if y.isdigit() else None,
                "phone": self.phone.text(), "ident": self.ident.text(), "date": self.date.date().toString("yyyy-MM-dd"),
                "time": self.time.time().toString("HH:mm"), "exam": self.exam.text(), "notes": self.notes.text(), "status": self.status.currentData()}


class LabWindow(BaseWindow):
    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.current = None
        self._reqs, self._appts, self._calls = [], [], []
        if cfg.get("tv_screen"):
            b = QPushButton("📺 Ouvrir l'écran TV"); b.clicked.connect(lambda *_: open_tv(self.cfg)); self.header_extra.addWidget(b)
        tabs = QTabWidget(); self.content.addWidget(tabs, 1)
        tabs.addTab(self._tab_queue(), "🧪 File & demandes")
        tabs.addTab(self._tab_tickets(), "🎟 Tickets")
        tabs.addTab(self._tab_appts(), "📅 Rendez-vous")
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.call_next)
        self.t = QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(3000)

    def on_login(self):
        self._seen = None
        self.refresh(); self.refresh_appts()

    # ---------------- file d'attente & demandes électroniques ----------------
    def _tab_queue(self):
        w = QWidget(); h = QHBoxLayout(w)
        a = QFrame(); a.setObjectName("card"); av = QVBoxLayout(a)
        t = QLabel("Patients du laboratoire (tickets)"); t.setStyleSheet("font-size:17px;font-weight:700;")
        self.q_calls = _table(["Ticket", "Patient", "Âge", "Attente"])
        self.cur = QLabel("Aucun patient appelé"); self.cur.setStyleSheet("font-size:20px;font-weight:700;"); self.cur.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur.setTextFormat(Qt.TextFormat.PlainText)
        row = QHBoxLayout()
        for label, fn in (("📣 Appeler le suivant (Espace)", self.call_next), ("🔁 Rappeler", self.recall), ("✔ Terminé", self.finish)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        for x in (t, self.q_calls, self.cur):
            av.addWidget(x)
        av.addLayout(row); h.addWidget(a, 1)
        b_ = QFrame(); b_.setObjectName("card"); bv = QVBoxLayout(b_)
        t2 = QLabel("Demandes des médecins"); t2.setStyleSheet("font-size:17px;font-weight:700;")
        self.q_req = _table(["N°", "Patient", "Médecin", "Statut"])
        self.q_req.itemSelectionChanged.connect(self._show_req)
        self.req_info = QLabel(""); self.req_info.setWordWrap(True); self.req_info.setTextFormat(Qt.TextFormat.PlainText)
        self.req_info.setStyleSheet("background:#0e141b;border:1px solid #2c3644;border-radius:8px;padding:8px;")
        row2 = QHBoxLayout()
        for label, fn in (("▶ Démarrer", self.start_req), ("📎 Envoyer le résultat au médecin", self.send_result), ("✅ Terminé", self.done_req)):
            b = QPushButton(label); b.clicked.connect(fn); row2.addWidget(b)
        for x in (t2, self.q_req, self.req_info):
            bv.addWidget(x)
        bv.addLayout(row2); h.addWidget(b_, 1)
        return w

    def _sel_req(self):
        r = self.q_req.currentRow()
        return self._reqs[r] if 0 <= r < len(self._reqs) else None

    def _show_req(self, *_):
        r = self._sel_req()
        self.req_info.setText(f"{display_name(r)} — {age_from_row(r)} ans\nAnalyses : " + ", ".join(r["items"]) +
                              f"\nIndications : {r['clinical_info'] or '—'}" + ("\n🚨 URGENT" if r["urgent"] else "") if r else "")

    @guard
    def refresh(self, *_):
        if not self.user:
            return
        sel = self.q_req.currentRow()
        rows = self.db.queue(["LAB", "LABP"], 72)
        if self._banner_kind == "error":
            self.hide_banner()
        self._calls = rows
        self.q_calls.setRowCount(len(rows))
        for i, r in enumerate(rows):
            wait = int((datetime.now() - datetime.strptime(r["created_at"], FMT)).total_seconds() // 60)
            for j, txt in enumerate((r["ticket_label"], display_name(r), f"{age_from_row(r)} ans", f"{wait} min")):
                self.q_calls.setItem(i, j, QTableWidgetItem(txt))
        cur = self.db.current_called(self.station, self.user["id"])
        self.current = cur
        self.cur.setText(f"{cur['ticket_label']} — {display_name(cur)}" if cur else "Aucun patient appelé")
        self._reqs = self.db.lab_queue(self.user["id"])
        ids = {r["id"] for r in self._reqs}
        if getattr(self, "_seen", None) is not None and ids - self._seen:
            n = [r for r in self._reqs if r["id"] in ids - self._seen][0]
            self.show_banner(f"📨 Nouvelle demande d'analyses : {n['ticket_label']} — {display_name(n)}" + (" 🚨 URGENT" if n["urgent"] else ""), ms=8000)
            QApplication.beep()
        self._seen = (getattr(self, "_seen", None) or set()) | ids
        self.q_req.setRowCount(len(self._reqs))
        for i, r in enumerate(self._reqs):
            for j, txt in enumerate((("🚨 " if r["urgent"] else "") + (r["ticket_label"] or ""), display_name(r), f"Dr {r['doc_last'] or ''}",
                                     "🧪 En cours" if r["status"] == "IN_PROGRESS" else "⏳ En attente")):
                it = QTableWidgetItem(txt)
                if r["urgent"]:
                    it.setBackground(QColor(231, 76, 60, 90))
                self.q_req.setItem(i, j, it)
        if 0 <= sel < len(self._reqs):
            self.q_req.selectRow(sel)

    @guard
    def call_next(self, *_):
        if not self.user:
            return
        row = self.db.call_next(["LAB", "LABP"], self.station, self.user["id"], self.room)
        self.show_banner("Aucun patient en attente.") if not row else (self.hide_banner(), QApplication.beep())
        self.refresh()

    @guard
    def recall(self, *_):
        if self.current:
            self.db.recall(self.current["id"], self.station, self.user["id"], self.room)

    @guard
    def finish(self, *_):
        if self.current:
            self.db.finish(self.current["id"], self.user["id"]); self.refresh()

    @guard
    def start_req(self, *_):
        r = self._sel_req()
        if r:
            self.db.lab_start(r["id"], self.station, self.user["id"]); self.refresh()

    @guard
    def send_result(self, *_):
        r = self._sel_req()
        if not r:
            return self.show_banner("Sélectionnez une demande.", "error")
        d = SendResultDialog(f"Résultat — {r['ticket_label']}", self)
        if d.exec():
            self.db.add_result("lab", r["id"], d.filename, d.mime, d.data_b64, d.text.toPlainText(), self.user["id"])
            self.show_banner("📤 Résultat envoyé à la session du médecin demandeur.")

    @guard
    def done_req(self, *_):
        r = self._sel_req()
        if r:
            self.db.lab_validate(r["id"], "", self.user["id"]); self.show_banner("✅ Demande terminée (statut renvoyé au médecin)."); self.refresh()

    # ---------------- émission de tickets du laboratoire ----------------
    def _tab_tickets(self):
        w = QWidget(); f = QFormLayout(w)
        self.t_last, self.t_first, self.t_age, self.t_ident = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.t_age.setPlaceholderText("Âge ou jj/mm/aaaa"); self.t_ident.setPlaceholderText("facultatif")
        self.t_gender = QComboBox(); self.t_gender.addItem("Homme", "H"); self.t_gender.addItem("Femme", "F")
        self.t_type = QComboBox(); self.t_type.addItem("🧪 Analyses rapides", "LAB"); self.t_type.addItem("🧬 Bilans prédictifs", "LABP")
        for lab, x in (("Nom", self.t_last), ("Prénom", self.t_first), ("Âge / naissance", self.t_age), ("N° d'identification", self.t_ident),
                       ("Genre", self.t_gender), ("Type de ticket", self.t_type)):
            f.addRow(lab + " :", x)
        b = QPushButton("🖨 Émettre et imprimer le ticket"); b.setObjectName("primary"); b.clicked.connect(self.issue)
        f.addRow(b)
        for x in (self.t_last, self.t_first, self.t_age, self.t_ident):
            x.returnPressed.connect(self.issue)
        return w

    @guard
    def issue(self, *_):
        parsed = parse_age_or_birth(self.t_age.text())
        if len(self.t_last.text().strip()) < 2 or not self.t_first.text().strip() or not parsed:
            return self.show_banner("Nom, prénom ou âge invalide.", "error")
        row = self.db.add_admission({"last_name": self.t_last.text(), "first_name": self.t_first.text(), "parsed": parsed,
                                     "gender": self.t_gender.currentData(), "service_code": self.t_type.currentData(),
                                     "ident": self.t_ident.text().strip(), "user_id": self.user["id"]}, self.station)
        ok, msg = print_ticket(self.cfg, row)
        try:
            archive_reception(row)
        except OSError:
            pass
        for x in (self.t_last, self.t_first, self.t_age, self.t_ident):
            x.clear()
        self.t_last.setFocus(); self.refresh()
        self.show_banner(f"Ticket {row['ticket_label']} émis." + ("" if ok else f" (impression : {msg})"), "info" if ok else "error")
        return row

    # ---------------- rendez-vous : calendrier + liste globale ----------------
    def _tab_appts(self):
        w = QWidget(); h = QHBoxLayout(w)
        left = QVBoxLayout()
        self.cal = QCalendarWidget(); self.cal.setGridVisible(True)
        self.cal.selectionChanged.connect(self.refresh_appts); self.cal.currentPageChanged.connect(lambda *_: self._mark_days())
        self.day_table = _table(["Heure", "Patient", "Analyses", "Statut"])
        left.addWidget(self.cal); left.addWidget(QLabel("Rendez-vous du jour sélectionné :")); left.addWidget(self.day_table, 1)
        h.addLayout(left, 1)
        right = QVBoxLayout()
        top = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Rechercher (nom, prénom, N° d'identification, téléphone)…")
        self.search.textChanged.connect(self.refresh_appts)
        self.range = QComboBox(); self.range.addItems(["Ce mois", "30 prochains jours", "Tous (±1 an)"]); self.range.currentIndexChanged.connect(self.refresh_appts)
        top.addWidget(self.search, 1); top.addWidget(self.range)
        self.all_table = _table(["Date", "Heure", "Patient", "Analyses", "Statut", "Tél."])
        right.addLayout(top); right.addWidget(QLabel("Liste globale des rendez-vous :")); right.addWidget(self.all_table, 1)
        row = QHBoxLayout()
        for label, fn in (("➕ Nouveau", self.new_appt), ("✏️ Modifier", self.edit_appt), ("🗑 Supprimer", self.del_appt), ("🎟 Arrivé → ticket", self.appt_to_ticket)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        right.addLayout(row); h.addLayout(right, 2)
        return w

    def _sel_appt(self):
        for table in (self.all_table, self.day_table):
            r = table.currentRow()
            rows = self._appts if table is self.all_table else self._day
            if 0 <= r < len(rows):
                return rows[r]
        return None

    @guard
    def refresh_appts(self, *_):
        if not self.user:
            return
        d = self.cal.selectedDate()
        first = QDate(d.year(), d.month(), 1)
        lo, hi = {0: (first, first.addMonths(1).addDays(-1)), 1: (QDate.currentDate(), QDate.currentDate().addDays(30)),
                  2: (QDate.currentDate().addYears(-1), QDate.currentDate().addYears(1))}[self.range.currentIndex()]
        f = lambda q: q.toString("yyyy-MM-dd")
        self._appts = self.db.list_appointments(f(lo), f(hi), self.search.text(), self.user["id"])
        self._day = self.db.list_appointments(f(d), f(d), "", self.user["id"])
        for table, rows, cols in ((self.all_table, self._appts, lambda a: (a["date"], a["time"], f"{a['last_name']} {a['first_name']}", a["exam"], STATUS[a["status"]], a["phone"])),
                                  (self.day_table, self._day, lambda a: (a["time"], f"{a['last_name']} {a['first_name']}", a["exam"], STATUS[a["status"]]))):
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
            for day in self.db.appointment_days(month, self.user["id"]):
                self.cal.setDateTextFormat(QDate.fromString(day, "yyyy-MM-dd"), fmt)
        except (ConnectionError, PermissionError):
            pass

    @guard
    def new_appt(self, *_):
        d = ApptDialog(None, self.cal.selectedDate(), self)
        if d.exec():
            self.db.create_appointment(d.values(), self.user["id"]); self.refresh_appts()

    @guard
    def edit_appt(self, *_):
        a = self._sel_appt()
        if not a:
            return self.show_banner("Sélectionnez un rendez-vous.", "error")
        d = ApptDialog(a, None, self)
        if d.exec():
            self.db.update_appointment(a["id"], d.values(), self.user["id"]); self.refresh_appts()

    @guard
    def del_appt(self, *_):
        a = self._sel_appt()
        if a and QMessageBox.question(self, "Supprimer", f"Supprimer le rendez-vous de {a['last_name']} {a['first_name']} ?") == QMessageBox.StandardButton.Yes:
            self.db.delete_appointment(a["id"], self.user["id"]); self.refresh_appts()

    @guard
    def appt_to_ticket(self, *_):
        a = self._sel_appt()
        if not a:
            return self.show_banner("Sélectionnez un rendez-vous.", "error")
        year = a["birth_year"] or datetime.now().year - 30
        row = self.db.add_admission({"last_name": a["last_name"], "first_name": a["first_name"], "parsed": {"birth_date": None, "birth_year": year},
                                     "gender": "H", "service_code": "LAB", "ident": a["ident"], "user_id": self.user["id"]}, self.station)
        self.db.update_appointment(a["id"], {**a, "status": "ARRIVED"}, self.user["id"])
        print_ticket(self.cfg, row)
        self.show_banner(f"Patient arrivé — ticket {row['ticket_label']} (vérifiez le genre sur la fiche si besoin).")
        self.refresh(); self.refresh_appts()
