"""Poste Manipulateur Radiologie : file LAN (demandes des médecins + inscriptions directes), appels, validation."""
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

from archive import archive_reception
from database import FMT, age_from_row, display_name, parse_age_or_birth
from printer import print_ticket
from ui_common import BaseWindow, guard


class DirectDialog(QDialog):
    """Inscription directe d'un patient (venant de l'accueil ou se présentant directement)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inscription directe — Radiologie")
        f = QFormLayout(self)
        self.last, self.first, self.age = QLineEdit(), QLineEdit(), QLineEdit()
        self.age.setPlaceholderText("Âge ou jj/mm/aaaa")
        self.gender = QComboBox(); self.gender.addItem("Homme", "H"); self.gender.addItem("Femme", "F")
        f.addRow("Nom :", self.last); f.addRow("Prénom :", self.first); f.addRow("Âge / naissance :", self.age); f.addRow("Genre :", self.gender)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); f.addRow(bb)

    def _ok(self):
        if len(self.last.text().strip()) < 2 or not self.first.text().strip() or not parse_age_or_birth(self.age.text()):
            QMessageBox.warning(self, "Inscription", "Nom, prénom ou âge invalide."); return
        self.accept()


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.verticalHeader().hide(); t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    hh = t.horizontalHeader(); hh.setStretchLastSection(True)
    for i in range(len(headers) - 1):
        hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    return t


class RadioWindow(BaseWindow):
    USER_ROLES = ("radio",)

    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.current, self._known, self._awaiting = None, None, []
        b = QPushButton("➕ Inscription directe"); b.clicked.connect(self.direct)
        self.header_extra.addWidget(b)
        body = QHBoxLayout(); self.content.addLayout(body, 1)

        left = QFrame(); left.setObjectName("card"); lv = QVBoxLayout(left)
        t = QLabel("File d'attente Radiologie (réseau local)"); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.count = QLabel(); self.count.setStyleSheet("color:#8b97a7;")
        self.queue = _table(["Passage", "Patient", "Examen", "Région / côté", "Médecin", "Origine", "Attente"])
        self.awaiting = _table(["Passage", "Patient", "Examen", "Depuis"]); self.awaiting.setMaximumHeight(150)
        bt = QPushButton("✔ Tirage remis (marquer Terminé)"); bt.clicked.connect(self.print_done)
        for x in (t, self.count, self.queue, QLabel("🖼 En attente de tirage"), self.awaiting, bt):
            lv.addWidget(x)
        body.addWidget(left, 3)

        right = QFrame(); right.setObjectName("card"); rv = QVBoxLayout(right)
        h = QLabel("Patient en salle d'examen"); h.setStyleSheet("font-size:18px;font-weight:700;")
        self.cur_ticket = QLabel("—"); self.cur_ticket.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_ticket.setStyleSheet("font-size:54px;font-weight:800;")
        self.cur_info = QLabel("Aucun patient appelé"); self.cur_info.setWordWrap(True); self.cur_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note = QLineEdit(); self.note.setPlaceholderText("Remarque pour le médecin (facultatif)")
        nxt = QPushButton("📣  Appeler le patient suivant   (Espace)"); nxt.setObjectName("primary"); nxt.clicked.connect(self.call_next)
        rec = QPushButton("🔁 Rappeler"); rec.clicked.connect(self.recall)
        ok = QPushButton("✅ Examen terminé"); ok.clicked.connect(lambda *_: self.validate("DONE"))
        pr = QPushButton("🖼 En attente de tirage"); pr.clicked.connect(lambda *_: self.validate("AWAITING_PRINT"))
        for x in (h, self.cur_ticket, self.cur_info, self.note, nxt, rec, ok, pr):
            rv.addWidget(x)
        rv.addStretch()
        body.addWidget(right, 2)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.call_next)
        self.t = QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(2000)   # quasi temps réel (2 s)

    def on_login(self):
        self._known = None
        self.refresh()

    @guard
    def refresh(self, *_):
        if not self.user:
            return
        rows = self.db.radio_queue()
        if self._banner_kind == "error":
            self.hide_banner()
        pend = [r for r in rows if r["status"] == "PENDING"]
        mine = [r for r in rows if r["status"] == "CALLED" and r["called_by"] == self.station]
        ids = {r["id"] for r in pend}
        if self._known is not None:           # notification visuelle + sonore des NOUVELLES demandes
            new = [r for r in pend if r["id"] not in self._known]
            if new:
                r = new[0]
                self.show_banner(f"📨 Nouvelle demande de radiologie : {r['ticket_label']} — {display_name(r)} "
                                 f"({r['exam_type'] or 'inscription directe'} {r['region'] or ''})" + (" 🚨 URGENT" if r["urgent"] else ""))
                QApplication.beep()
        self._known = (self._known or set()) | ids
        self.current = mine[0] if mine else None
        self.count.setText(f"{len(pend)} patient(s) en attente")
        self.queue.setRowCount(len(pend))
        for i, r in enumerate(pend):
            wait = int((datetime.now() - datetime.strptime(r["created_at"], FMT)).total_seconds() // 60)
            doc = f"Dr {r['doc_last']}" if r.get("doc_last") else "—"
            cells = [("🚨 " if r["urgent"] else "") + r["ticket_label"], display_name(r), r["exam_type"] or "—",
                     f"{r['region'] or ''} / {r['side'] or ''}".strip(" /"), doc,
                     "Médecin" if r["source"] == "MEDECIN" else "Accueil / direct", f"{wait} min"]
            for j, txt in enumerate(cells):
                it = QTableWidgetItem(txt); it.setData(Qt.ItemDataRole.UserRole, r["id"])
                if r["urgent"]:
                    it.setBackground(QColor(231, 76, 60, 90))
                self.queue.setItem(i, j, it)
        self._awaiting = self.db.radio_awaiting()
        self.awaiting.setRowCount(len(self._awaiting))
        for i, r in enumerate(self._awaiting):
            for j, txt in enumerate((r["ticket_label"], display_name(r), r["exam_type"] or "—", r["done_at"] or "")):
                self.awaiting.setItem(i, j, QTableWidgetItem(txt))
        c = self.current
        self.cur_ticket.setText(c["ticket_label"] if c else "—")
        self.cur_info.setText(f"{display_name(c)} — {age_from_row(c)} ans\n{c['exam_type'] or ''} {c['region'] or ''} {c['side'] or ''}\n"
                              f"{c['clinical_info'] or ''}" if c else "Aucun patient appelé")

    @guard
    def call_next(self, *_):
        if not self.user:
            return
        row = self.db.radio_call_next(self.station, self.user["id"])   # le Hub diffuse l'appel à l'écran TV
        if not row:
            return self.show_banner("Aucun patient en attente.")
        self.hide_banner(); QApplication.beep(); self.refresh()

    @guard
    def recall(self, *_):
        if self.current:
            self.db.radio_recall(self.current["id"], self.station)

    @guard
    def validate(self, status):
        if not self.current:
            return self.show_banner("Appelez d'abord un patient.", "error")
        r = self.db.radio_validate(self.current["id"], status, self.note.text().strip(), self.user["id"])
        self.note.clear()
        self.show_banner("✅ Statut envoyé au médecin traitant." if r["source"] == "MEDECIN" else "✅ Examen enregistré.")
        self.refresh()

    @guard
    def print_done(self, *_):
        r = self.awaiting.currentRow()
        if 0 <= r < len(self._awaiting):
            self.db.radio_validate(self._awaiting[r]["id"], "DONE", "", self.user["id"])
            self.refresh()

    @guard
    def direct(self, *_):
        d = DirectDialog(self)
        if not d.exec():
            return
        row = self.db.add_admission({"last_name": d.last.text(), "first_name": d.first.text(),
                                     "parsed": parse_age_or_birth(d.age.text()), "gender": d.gender.currentData(),
                                     "service_code": "RAD", "user_id": self.user["id"]}, self.station)
        ok, msg = print_ticket(self.cfg, row)
        try:
            archive_reception(row)
        except OSError:
            pass
        self.refresh()
        self.show_banner(f"Patient inscrit — numéro de passage {row['ticket_label']}" + ("" if ok else f" (impression : {msg})"),
                         "info" if ok else "error")
