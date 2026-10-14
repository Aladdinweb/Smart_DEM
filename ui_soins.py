"""Poste Soins & Triage (paramédical : ISP, infirmier, sage-femme, ATS, paramédical, assistante médicale) : tickets de soins SOI-XX,
constantes vitales (tension, glycémie, température) enregistrées dans le dossier, orientation vers le triage médical, relève de garde."""
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
                             QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout)

import userdata
from data_structures import CONSULT_SERVICES, SERVICE_BY_CODE
from database import FMT, Database, age_from_row, display_name
from functions import format_vitals
from styles import TRIAGE_COLORS, TRIAGE_ICON, TRIAGE_TEXT
from ui_common import BaseWindow, HandoverDialog, guard, open_tv
from ui_dpi import PatientSearchDialog


class SoinsWindow(BaseWindow):
    SERVICES = ["SOINS"]

    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.current, self._last_draft = None, None
        self.btn_hand = QPushButton("📥 Reprises (0)"); self.btn_hand.clicked.connect(self.open_handovers); self.header_extra.addWidget(self.btn_hand)
        b = QPushButton("🔁 Relève de garde / Changer de compte"); b.clicked.connect(self.logout); self.header_extra.addWidget(b)
        d = QPushButton("🔎 Dossiers patients"); d.clicked.connect(self.open_dpi); self.header_extra.addWidget(d)
        if cfg.get("tv_screen"):
            t = QPushButton("📺 Ouvrir l'écran TV"); t.clicked.connect(lambda *_: open_tv(self.cfg)); self.header_extra.addWidget(t)
        body = QHBoxLayout(); self.content.addLayout(body, 1)

        left = QFrame(); left.setObjectName("card"); lv = QVBoxLayout(left)
        t = QLabel("Patients en attente de soins"); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.count = QLabel(); self.count.setStyleSheet("color:#8b97a7;")
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["Ticket", "Nom & Prénom", "Âge", "Attente"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().hide(); self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for x in (t, self.count, self.table):
            lv.addWidget(x)
        body.addWidget(left, 3)

        right = QFrame(); right.setObjectName("card"); rv = QVBoxLayout(right)
        self.cur_ticket = QLabel("—"); self.cur_ticket.setAlignment(Qt.AlignmentFlag.AlignCenter); self.cur_ticket.setStyleSheet("font-size:48px;font-weight:800;")
        self.cur_name = QLabel("Aucun patient appelé"); self.cur_name.setAlignment(Qt.AlignmentFlag.AlignCenter); self.cur_name.setTextFormat(Qt.TextFormat.PlainText)
        self.cur_name.setStyleSheet("font-size:17px;"); self.cur_name.setWordWrap(True)
        row = QHBoxLayout()
        nxt = QPushButton("📣  Appeler le suivant  (Espace)"); nxt.setObjectName("primary"); nxt.clicked.connect(self.call_next)
        rec = QPushButton("📢 Rappeler / répéter l'appel"); rec.clicked.connect(self.recall)
        row.addWidget(nxt, 3); row.addWidget(rec, 1)
        for x in (self.cur_ticket, self.cur_name):
            rv.addWidget(x)
        rv.addLayout(row)

        g = QGroupBox("Constantes vitales"); gl = QVBoxLayout(g)
        r1 = QHBoxLayout()
        self.sys, self.dia = QLineEdit(), QLineEdit()
        self.sys.setPlaceholderText("Systolique"); self.dia.setPlaceholderText("Diastolique")
        self.t_unit = QComboBox(); self.t_unit.addItems(["mmHg", "cmHg"])
        for x in (QLabel("Tension :"), self.sys, QLabel("/"), self.dia, self.t_unit):
            r1.addWidget(x)
        r2 = QHBoxLayout()
        self.glyc = QLineEdit(); self.glyc.setPlaceholderText("ex : 1,10"); self.g_unit = QComboBox(); self.g_unit.addItems(["g/L", "mmol/L"])
        self.temp = QLineEdit(); self.temp.setPlaceholderText("ex : 37,2")
        for x in (QLabel("Glycémie :"), self.glyc, self.g_unit, QLabel("Température (°C) :"), self.temp):
            r2.addWidget(x)
        self.note = QLineEdit(); self.note.setPlaceholderText("Observation (facultatif)")
        sv = QPushButton("💾 Enregistrer les constantes dans le dossier"); sv.clicked.connect(self.save_vitals)
        self.hist = QLabel(""); self.hist.setWordWrap(True); self.hist.setTextFormat(Qt.TextFormat.PlainText)
        gl.addLayout(r1); gl.addLayout(r2); gl.addWidget(self.note); gl.addWidget(sv); gl.addWidget(self.hist)
        rv.addWidget(g)

        a = QGroupBox("Actes de soins (tracés dans le dossier)"); al = QHBoxLayout(a)
        self.act = QComboBox(); self.act.addItems(Database.SOIN_ACTS)
        self.act_note = QLineEdit(); self.act_note.setPlaceholderText("Précision (facultatif)")
        sa = QPushButton("🧾 Enregistrer l'acte"); sa.clicked.connect(self.save_act)
        al.addWidget(self.act, 2); al.addWidget(self.act_note, 3); al.addWidget(sa, 2)
        rv.addWidget(a)

        o = QGroupBox("Orientation vers le triage médical"); ol = QVBoxLayout(o)
        self.dest = QComboBox()
        for c in CONSULT_SERVICES:
            self.dest.addItem(f"{SERVICE_BY_CODE[c]['icon']} {SERVICE_BY_CODE[c]['name']}".replace("&", "&&"), c)
        self.dest.currentIndexChanged.connect(self._sync_triage)
        tl = QHBoxLayout(); self.tri_group = QButtonGroup(self); self.tri_btns = []
        for k in ("VERT", "ORANGE", "ROUGE"):
            tb = QPushButton(f"{TRIAGE_ICON[k]} {TRIAGE_TEXT[k]}"); tb.setCheckable(True); tb.setProperty("code", k)
            tb.setStyleSheet(f"QPushButton:checked{{background:{TRIAGE_COLORS[k]};color:white;border:none;}}")
            self.tri_group.addButton(tb); tl.addWidget(tb); self.tri_btns.append(tb)
        self.tri_btns[0].setChecked(True)
        go = QPushButton("➡ Orienter le patient vers la file du médecin"); go.setObjectName("primary"); go.clicked.connect(self.orient)
        for x in (self.dest,):
            ol.addWidget(x)
        ol.addLayout(tl); ol.addWidget(go); rv.addWidget(o); rv.addStretch()
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.Shape.NoFrame); sc.setWidget(right)      # 4:3 : la colonne défile
        body.addWidget(sc, 4)
        self._sync_triage()
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.call_next)
        self.t = QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(3000)
        self.t_draft = QTimer(self); self.t_draft.timeout.connect(self.autosave); self.t_draft.start(4000)

    def hours(self):
        return int(self.cfg.get("revisit_check_hours", 72))

    def _sync_triage(self, *_):
        triage = SERVICE_BY_CODE[self.dest.currentData()]["triage"]
        for b in self.tri_btns:
            b.setEnabled(triage)

    # ---------------- file & appels ----------------
    @guard
    def refresh(self, *_):
        if not self.user:
            return
        rows = self.db.queue(self.SERVICES, self.hours())
        if self._banner_kind == "error":
            self.hide_banner()
        self.count.setText(f"{len(rows)} patient(s) en attente")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            wait = int((datetime.now() - datetime.strptime(r["created_at"], FMT)).total_seconds() // 60)
            for j, txt in enumerate((r["ticket_label"], display_name(r), f"{age_from_row(r)} ans", f"{wait} min")):
                self.table.setItem(i, j, QTableWidgetItem(txt))
        n = len(self.db.handover_list(self.SERVICES, self.user["id"]))
        self.btn_hand.setText(f"📥 Reprises ({n})"); self.btn_hand.setStyleSheet("background:#f39c12;color:#1b1b1b;font-weight:700;" if n else "")

    def set_current(self, row):
        self.current, self._last_draft = row, None
        for x in (self.sys, self.dia, self.glyc, self.temp, self.note):
            x.clear()
        self.cur_ticket.setText(row["ticket_label"] if row else "—")
        self.cur_name.setText(f"{display_name(row)} — {age_from_row(row)} ans" if row else "Aucun patient appelé")
        self.hist.setText("")
        if row and self.user:
            d = self.db.get_draft(row["id"], "soins", self.user["id"])
            if d:
                self.sys.setText(d.get("sys", "")); self.dia.setText(d.get("dia", "")); self.glyc.setText(d.get("glyc", "")); self.temp.setText(d.get("temp", ""))
                self.note.setText(d.get("note", "")); self.t_unit.setCurrentText(d.get("tension_unit", "mmHg")); self.g_unit.setCurrentText(d.get("glyc_unit", "g/L"))
                self.show_banner("📝 Brouillon retrouvé.", ms=4000)
            self._show_hist()

    def _show_hist(self):
        vit = self.db.vitals_for_admission(self.current["id"], self.user["id"]) if self.current else []
        self.hist.setText("\n".join(f"{(v['recorded_at'] or '')[11:16]}  {v['last_name']} {v['first_name']} ({v['function']}) : {format_vitals(v)}" for v in vit))

    def on_login(self):
        self.set_current(self.db.current_called(self.station, self.user["id"]))
        self.refresh()
        n = len(self.db.handover_list(self.SERVICES, self.user["id"]))
        if n:
            self.show_banner(f"📥 {n} patient(s) en attente de reprise (bouton « Reprises »).", ms=8000)

    @guard
    def call_next(self, *_):
        if not self.user:
            return
        row = self.db.call_next(self.SERVICES, self.station, self.user["id"], self.room)    # l'écran concerné reçoit l'appel
        if not row:
            return self.show_banner("Aucun patient en attente.")
        self.hide_banner(); self.set_current(row); self.log("appel", row["ticket_label"]); QApplication.beep(); self.refresh()

    @guard
    def recall(self, *_):
        if self.current:
            self.db.recall(self.current["id"], self.station, self.user["id"], self.room); QApplication.beep()

    # ---------------- constantes, orientation ----------------
    def _form(self):
        return {"sys": self.sys.text(), "dia": self.dia.text(), "tension_unit": self.t_unit.currentText(), "glyc": self.glyc.text(),
                "glyc_unit": self.g_unit.currentText(), "temp": self.temp.text(), "note": self.note.text()}

    @guard
    def save_vitals(self, *_):
        if not self.current:
            return self.show_banner("Appelez d'abord un patient.", "error")
        try:
            self.db.record_vitals(self.current["id"], self._form(), self.user["id"])
        except ValueError as e:
            return self.show_banner(str(e), "error")
        self.log("constantes", self.current["ticket_label"])
        for x in (self.sys, self.dia, self.glyc, self.temp, self.note):
            x.clear()
        self._show_hist(); self.show_banner("✅ Constantes enregistrées dans le dossier du patient.")

    @guard
    def save_act(self, *_):
        if not self.current:
            return self.show_banner("Appelez d'abord un patient.", "error")
        try:
            self.db.record_act(self.current["id"], self.act.currentText(), self.act_note.text(), self.user["id"])
        except ValueError as e:
            return self.show_banner(str(e), "error")
        self.log("acte", f"{self.current['ticket_label']} {self.act.currentText()}")
        self.act_note.clear(); self.show_banner("✅ Acte enregistré et tracé dans le dossier.")

    @guard
    def open_dpi(self, *_):
        if self.user:
            PatientSearchDialog(self.db, self.user, self.cfg, self).exec()

    @guard
    def orient(self, *_):
        if not self.current:
            return self.show_banner("Appelez d'abord un patient.", "error")
        triage = next((b.property("code") for b in self.tri_btns if b.isChecked()), None)
        try:
            row = self.db.orient_patient(self.current["id"], self.dest.currentData(), triage, self.user["id"])
        except ValueError as e:
            return self.show_banner(str(e), "error")
        userdata.delete_draft(self.user, f"soins_{row['id']}")
        self.log("orientation", f"{row['ticket_label']} → {row['service_code']}")
        self.set_current(None); self.refresh()
        self.show_banner(f"➡ {row['ticket_label']} orienté vers {SERVICE_BY_CODE[row['service_code']]['name']}.")

    # ---------------- brouillon & relève de garde ----------------
    @guard
    def autosave(self, *_):
        if not (self.user and self.current):
            return
        d = self._form()
        if not any(v for k, v in d.items() if k not in ("tension_unit", "glyc_unit")):
            return
        key = repr(sorted(d.items()))
        if key != self._last_draft:
            self.db.save_draft(self.current["id"], "soins", d, self.user["id"]); userdata.save_draft(self.user, f"soins_{self.current['id']}", d)
            self._last_draft = key

    @guard
    def open_handovers(self, *_):
        if not self.user:
            return
        dlg = HandoverDialog(self.db, self.user, self.SERVICES, self)
        if dlg.exec() and dlg.taken:
            self.log("reprise", dlg.taken["ticket_label"]); self.set_current(self.db.get(dlg.taken["id"]))

    def before_logout(self):
        if not self.current:
            return True
        self.autosave()
        box = QMessageBox(QMessageBox.Icon.Question, "Relève de garde", f"Le patient {self.current['ticket_label']} est en cours.\nQue faire avant de changer de compte ?", parent=self)
        hand = box.addButton("🔁 Relève : réserver pour un collègue", QMessageBox.ButtonRole.AcceptRole)
        back = box.addButton("Remettre en file d'attente", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Rester connecté", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        try:
            if box.clickedButton() is hand:
                note, ok = QInputDialog.getText(self, "Relève de garde", "Consigne pour le collègue (facultatif) :")
                if not ok:
                    return False
                self.db.handover_start(self.current["id"], note, self.user["id"]); self.log("relève de garde", self.current["ticket_label"]); return True
            if box.clickedButton() is back:
                self.db.release_patient(self.current["id"], self.user["id"]); self.log("patient remis en file", self.current["ticket_label"]); return True
        except (ConnectionError, PermissionError, ValueError) as e:
            self.show_banner(str(e), "error")
        return False
