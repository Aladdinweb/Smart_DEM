"""Poste Laboratoire (accueil / secrétariat + technicien) : tickets, file d'appel, demandes des médecins, résultats, rendez-vous (calendrier)."""
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from archive import archive_reception
from database import FMT, age_from_row, display_name, parse_age_or_birth
from printer import print_ticket
from ui_appointments import AppointmentsPanel
from ui_common import BaseWindow, guard, open_tv
from ui_radio import SendResultDialog, _table

STATUS = {"PLANNED": "📅 Prévu", "ARRIVED": "🚶 Arrivé", "DONE": "✅ Fait", "CANCELLED": "✖ Annulé"}


class LabWindow(BaseWindow):
    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.current = None
        self._reqs, self._appts, self._calls = [], [], []
        if cfg.get("tv_screen"):
            b = QPushButton("📺 Ouvrir l'écran TV"); b.clicked.connect(lambda *_: open_tv(self.cfg)); self.header_extra.addWidget(b)
        f = QPushButton("📝 Fiches et formulaires"); f.clicked.connect(self.fiches); self.header_extra.addWidget(f)
        tabs = QTabWidget(); self.content.addWidget(tabs, 1)
        tabs.addTab(self._tab_queue(), "🧪 File & demandes")
        tabs.addTab(self._tab_tickets(), "🎟 Tickets")
        tabs.addTab(self._tab_appts(), "📅 Rendez-vous")
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.call_next)
        self.t = QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(3000)

    def on_login(self):
        self._seen = None
        self.appts_panel.set_user(self.user)
        self.refresh()

    # ---------------- file d'attente & demandes électroniques ----------------
    def _tab_queue(self):
        w = QWidget(); h = QHBoxLayout(w)
        a = QFrame(); a.setObjectName("card"); av = QVBoxLayout(a)
        t = QLabel("Patients du laboratoire (tickets)"); t.setStyleSheet("font-size:17px;font-weight:700;")
        self.q_calls = _table(["Ticket", "Patient", "Âge", "Attente"])
        self.cur = QLabel("Aucun patient appelé"); self.cur.setStyleSheet("font-size:20px;font-weight:700;"); self.cur.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur.setTextFormat(Qt.TextFormat.PlainText)
        row = QHBoxLayout()
        for label, fn in (("📣 Appeler le suivant (Espace)", self.call_next), ("📢 Rappeler / répéter l'appel", self.recall), ("✔ Terminé", self.finish)):
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
        self.log("ticket", row["ticket_label"]); self.t_last.setFocus(); self.refresh()
        self.show_banner(f"Ticket {row['ticket_label']} émis." + ("" if ok else f" (impression : {msg})"), "info" if ok else "error")
        return row

    # ---------------- rendez-vous : calendrier + liste globale ----------------
    def _tab_appts(self):
        self.appts_panel = AppointmentsPanel(self.db, self.cfg, self)
        self.appts_panel.changed.connect(self.refresh)
        return self.appts_panel

    def fiches(self, *_):
        c = self.current
        self.open_documents(self.db.get(c["admission_id"]) if c and c.get("admission_id") else None, "BIO")

    def refresh_appts(self, *_):
        if self.user:
            self.appts_panel.refresh()
