"""Poste Médecin : file d'attente (priorité + ⚠️ patient récurrent), ordonnance numérique, demandes de radiologie / analyses,
clôture et archivage de la consultation."""
from datetime import datetime

from PyQt6.QtCore import QStringListModel, Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QFrame, QGridLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                             QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from archive import archive_consultation
from data_structures import SERVICE_BY_CODE
from database import FMT, age_from_row, display_name
from documents import build_lab_request, build_prescription, build_radio_request
from medical_data import DURATIONS, EXAM_TYPES, LAB_ITEMS, POSOLOGIES, RADIO_STATUS, REGIONS, SIDES
from printer import print_document
from styles import TRIAGE_COLORS, TRIAGE_ICON, TRIAGE_TEXT
from ui_common import BaseWindow, guard
from ui_login import ProfileDialog

BADGE = "⚠️ Patient Récurrent"


class DoctorWindow(BaseWindow):
    USER_ROLES = ("medecin",)

    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.services = [c for c in cfg.get("services", []) if c in SERVICE_BY_CODE]
        self.current = self.consult = self.rx = self.last_radio = None
        self.blink, self.row_triage, self._radio_seen = False, [], {}
        bp = QPushButton("🖋 Mon profil"); bp.clicked.connect(self.open_profile)
        self.header_extra.addWidget(bp)
        body = QHBoxLayout(); self.content.addLayout(body, 1)
        body.addWidget(self._build_queue(), 3)
        body.addWidget(self._build_workspace(), 5)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.call_next)
        self.t_refresh = QTimer(self); self.t_refresh.timeout.connect(self.refresh); self.t_refresh.start(3000)
        self.t_blink = QTimer(self); self.t_blink.timeout.connect(self._blink); self.t_blink.start(600)
        self.set_current(None)

    def hours(self):
        return int(self.cfg.get("revisit_check_hours", 72))

    def doctor(self):
        return self.db.get_user(self.user["id"])      # inclut la griffe (signature_b64)

    # ---------------- file d'attente ----------------
    def _build_queue(self):
        left = QFrame(); left.setObjectName("card"); lv = QVBoxLayout(left)
        names = " · ".join(f"{SERVICE_BY_CODE[c]['icon']} {SERVICE_BY_CODE[c]['name']}" for c in self.services)
        t = QLabel("File d'attente"); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.count = QLabel(); self.count.setStyleSheet("color:#8b97a7;")
        lv.addWidget(t); lv.addWidget(QLabel(names)); lv.addWidget(self.count)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Ticket", "Nom & Prénom", "Âge", "Niveau", "Alerte", "Attente"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)      # la touche Espace reste dédiée à l'appel
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        for i in range(6):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i == 1 else QHeaderView.ResizeMode.ResizeToContents)
        lv.addWidget(self.table, 1)
        self.table.itemSelectionChanged.connect(self.on_select)
        return left

    @guard
    def refresh(self, *_):
        if not self.user:
            return
        sel = self.table.currentItem().data(Qt.ItemDataRole.UserRole) if self.table.currentItem() else None
        rows = self.db.queue(self.services, self.hours())
        if self._banner_kind == "error":
            self.hide_banner()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows)); self.row_triage = []
        for i, r in enumerate(rows):
            wait = int((datetime.now() - datetime.strptime(r["created_at"], FMT)).total_seconds() // 60)
            tri = f"{TRIAGE_ICON[r['triage_level']]} {TRIAGE_TEXT[r['triage_level']]}" if r["triage_level"] else "🟢 Standard"
            cells = [r["ticket_label"], display_name(r), f"{age_from_row(r)} ans", tri, BADGE if r["recurrent"] else "", f"{wait} min"]
            for j, txt in enumerate(cells):
                it = QTableWidgetItem(txt); it.setData(Qt.ItemDataRole.UserRole, r["id"])
                if j == 4 and r["recurrent"]:
                    it.setForeground(QColor("#f39c12"))
                self.table.setItem(i, j, it)
            self.row_triage.append(r["triage_level"] or "VERT")
            if r["id"] == sel:
                self.table.selectRow(i)
        self.table.blockSignals(False)
        self.count.setText(f"{len(rows)} patient(s) en attente")
        self._paint()
        self._poll_radio()

    def _paint(self):
        for i, lvl in enumerate(self.row_triage):
            col = QColor(TRIAGE_COLORS[lvl])
            col.setAlpha((230 if self.blink else 80) if lvl == "ROUGE" else 55)
            for j in range(self.table.columnCount()):
                it = self.table.item(i, j)
                if it:
                    it.setBackground(col)

    def _blink(self):
        self.blink = not self.blink
        self._paint()

    @guard
    def on_select(self, *_):
        it = self.table.currentItem()
        if not it:
            return
        row = self.db.get(it.data(Qt.ItemDataRole.UserRole))
        rev = self._revisit_of(row)
        self.show_revisit(rev) if rev else self.clear_revisit_banner()

    def _revisit_of(self, row):
        return self.db.find_revisit(row.get("last_name") or row["full_name"], row.get("first_name") or "", row["gender"],
                                    {"birth_year": row["birth_year"], "birth_date": row["birth_date"]}, self.hours(), row["id"])

    # ---------------- espace de travail ----------------
    def _build_workspace(self):
        sc = QScrollArea(); sc.setWidgetResizable(True)
        w = QWidget(); v = QVBoxLayout(w)
        card = QFrame(); card.setObjectName("card"); cv = QVBoxLayout(card)
        h = QLabel("Patient en cours"); h.setStyleSheet("font-size:18px;font-weight:700;")
        self.cur_ticket = QLabel("—"); self.cur_ticket.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_name = QLabel(""); self.cur_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_name.setStyleSheet("font-size:18px;"); self.cur_name.setWordWrap(True)
        self.cur_badge = QLabel(BADGE); self.cur_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_badge.setStyleSheet("background:#f39c12;color:#1b1b1b;font-weight:700;padding:6px;border-radius:8px;")
        nxt = QPushButton("📣  Appel Suivant   (Espace)"); nxt.setObjectName("primary"); nxt.clicked.connect(self.call_next)
        rec = QPushButton("🔁 Rappeler"); rec.clicked.connect(self.recall)
        row = QHBoxLayout(); row.addWidget(nxt, 3); row.addWidget(rec, 1)
        for x in (h, self.cur_ticket, self.cur_name, self.cur_badge):
            cv.addWidget(x)
        cv.addLayout(row)
        v.addWidget(card)
        self.tabs = QTabWidget(); v.addWidget(self.tabs, 1)
        self.tabs.addTab(self._tab_rx(), "💊 Ordonnance")
        self.tabs.addTab(self._tab_radio(), "🩻 Radiologie")
        self.tabs.addTab(self._tab_lab(), "🧪 Analyses")
        self.tabs.addTab(self._tab_close(), "✅ Clôture")
        sc.setWidget(w)
        return sc

    @staticmethod
    def _chips(items, target):
        g = QGridLayout()
        for i, t in enumerate(items):
            b = QPushButton(t); b.setStyleSheet("padding:4px 8px;font-size:12px;")
            b.clicked.connect(lambda _=False, t=t: target.setText(t))
            g.addWidget(b, i // 4, i % 4)
        return g

    # ----- ordonnance -----
    def _tab_rx(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.drug = QLineEdit(); self.drug.setPlaceholderText("Médicament — saisie semi-automatique")
        self.drug_model = QStringListModel([])
        comp = QCompleter(self.drug_model, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.drug.setCompleter(comp)
        self.dose = QLineEdit(); self.dose.setPlaceholderText("Posologie (ex : 1 cp x 3/j)")
        self.dur = QLineEdit(); self.dur.setPlaceholderText("Durée du traitement")
        self.add_btn = QPushButton("➕ Ajouter à l'ordonnance"); self.add_btn.clicked.connect(self.add_item)
        for x in (self.drug, self.dose):
            v.addWidget(x)
        v.addLayout(self._chips(POSOLOGIES, self.dose)); v.addWidget(self.dur); v.addLayout(self._chips(DURATIONS, self.dur))
        v.addWidget(self.add_btn)
        self.rx_table = QTableWidget(0, 3)
        self.rx_table.setHorizontalHeaderLabels(["Médicament", "Posologie", "Durée"])
        self.rx_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rx_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rx_table.verticalHeader().hide(); self.rx_table.setMinimumHeight(140)
        self.rx_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.rx_table)
        self.rm_btn = QPushButton("🗑 Retirer la ligne sélectionnée"); self.rm_btn.clicked.connect(self.remove_item)
        self.rx_notes = QLineEdit(); self.rx_notes.setPlaceholderText("Remarques / conseils (facultatif)")
        v.addWidget(self.rm_btn); v.addWidget(self.rx_notes)
        row = QHBoxLayout()
        b1 = QPushButton("🖨 Imprimer l'ordonnance"); b1.clicked.connect(self.print_rx)
        b2 = QPushButton("📤 Envoyer à la Pharmacie"); b2.clicked.connect(self.send_pharmacy)
        b3 = QPushButton("🆕 Nouvelle ordonnance"); b3.clicked.connect(self._new_rx)
        for b in (b1, b2, b3):
            row.addWidget(b)
        v.addLayout(row)
        self.rx_status = QLabel(""); v.addWidget(self.rx_status)
        self.drug.returnPressed.connect(self.dose.setFocus)
        self.dose.returnPressed.connect(self.dur.setFocus)
        self.dur.returnPressed.connect(self.add_item)
        return w

    def _load_drugs(self):
        self.drug_model.setStringList(self.db.list_drug_names())

    def add_item(self, *_):
        drug = self.drug.text().strip()
        if not drug or self.rx:
            return
        r = self.rx_table.rowCount(); self.rx_table.insertRow(r)
        for j, t in enumerate((drug, self.dose.text().strip(), self.dur.text().strip())):
            self.rx_table.setItem(r, j, QTableWidgetItem(t))
        for x in (self.drug, self.dose, self.dur):
            x.clear()
        self.drug.setFocus()

    def remove_item(self, *_):
        if not self.rx and self.rx_table.currentRow() >= 0:
            self.rx_table.removeRow(self.rx_table.currentRow())

    def _items(self):
        def cell(r, c):
            it = self.rx_table.item(r, c); return it.text() if it else ""
        return [{"drug": cell(r, 0), "dosage": cell(r, 1), "duration": cell(r, 2)} for r in range(self.rx_table.rowCount())]

    def _lock_rx(self, locked):
        for x in (self.drug, self.dose, self.dur, self.add_btn, self.rm_btn, self.rx_notes):
            x.setEnabled(not locked)

    def _new_rx(self, *_):
        self.rx = None
        self.rx_table.setRowCount(0); self.rx_notes.clear(); self._lock_rx(False)
        self.rx_status.setText("Nouvelle ordonnance.")

    def _ensure_rx(self):
        if self.rx:
            return self.rx
        if not self.consult:
            self.show_banner("Appelez d'abord un patient.", "error"); return None
        items = self._items()
        if not items:
            self.show_banner("L'ordonnance est vide.", "error"); return None
        self.rx = self.db.create_prescription(self.consult["id"], items, self.rx_notes.text().strip(), self.user["id"])
        self._lock_rx(True)
        self.rx_status.setText(f"Ordonnance {self.rx['uuid'][:8].upper()} enregistrée (figée, signée par QR).")
        self._load_drugs()
        return self.rx

    @guard
    def print_rx(self, *_):
        rx = self._ensure_rx()
        if not rx:
            return
        html, res = build_prescription(self.cfg, rx, self.current, self.doctor())
        ok, msg = print_document(self.cfg, html, res, "a4", "ordonnance_" + rx["uuid"][:8])
        self.show_banner("Ordonnance : " + msg, "info" if ok else "error")

    @guard
    def send_pharmacy(self, *_):
        rx = self._ensure_rx()
        if not rx:
            return
        self.rx = self.db.send_to_pharmacy(rx["uuid"], self.user["id"])
        self.rx_status.setText(f"Ordonnance {self.rx['uuid'][:8].upper()} transmise à la Pharmacie ({self.rx['status']}).")
        self.show_banner("📤 Ordonnance envoyée à la Pharmacie.")

    # ----- radiologie -----
    def _tab_radio(self):
        w = QWidget(); f = QVBoxLayout(w)
        self.r_type = QComboBox(); self.r_type.addItems(EXAM_TYPES)
        self.r_region = QComboBox(); self.r_region.setEditable(True); self.r_region.addItems(REGIONS)
        self.r_side = QComboBox(); self.r_side.addItems(SIDES)
        self.r_info = QTextEdit(); self.r_info.setPlaceholderText("Renseignements cliniques"); self.r_info.setMaximumHeight(90)
        self.r_urgent = QCheckBox("🚨 Urgent"); self.r_paper = QCheckBox("Imprimer aussi la demande papier")
        for lab, x in (("Type d'examen", self.r_type), ("Région anatomique", self.r_region), ("Côté", self.r_side)):
            f.addWidget(QLabel(lab)); f.addWidget(x)
        f.addWidget(self.r_info); f.addWidget(self.r_urgent); f.addWidget(self.r_paper)
        row = QHBoxLayout()
        b1 = QPushButton("📡 Envoyer au Poste Radiologie"); b1.setObjectName("primary"); b1.clicked.connect(self.send_radio)
        b2 = QPushButton("🖨 Imprimer la dernière demande"); b2.clicked.connect(self.print_radio)
        row.addWidget(b1, 2); row.addWidget(b2, 1); f.addLayout(row)
        self.radio_table = QTableWidget(0, 4)
        self.radio_table.setHorizontalHeaderLabels(["Passage", "Examen", "Région / côté", "Statut"])
        self.radio_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.radio_table.verticalHeader().hide(); self.radio_table.setMinimumHeight(120)
        self.radio_table.horizontalHeader().setStretchLastSection(True)
        f.addWidget(QLabel("Demandes de cette consultation :")); f.addWidget(self.radio_table)
        return w

    @guard
    def send_radio(self, *_):
        if not self.consult:
            return self.show_banner("Appelez d'abord un patient.", "error")
        req = self.db.create_radio_request(self.consult["id"], self.r_type.currentText(), self.r_region.currentText(),
                                           self.r_side.currentText(), self.r_info.toPlainText().strip(),
                                           self.r_urgent.isChecked(), self.user["id"], self.station)
        self.last_radio = req
        if self.r_paper.isChecked():
            self._print_radio(req)
        self.show_banner(f"📡 Demande envoyée à la Radiologie — numéro de passage {req['ticket_label']}.")
        self.r_info.clear(); self.r_urgent.setChecked(False)
        self.refresh_radio()

    def _print_radio(self, req):
        html, res = build_radio_request(self.cfg, req, self.current, self.doctor())
        ok, msg = print_document(self.cfg, html, res, "a4", "radio_" + req["ticket_label"])
        if not ok:
            self.show_banner("Impression : " + msg, "error")

    @guard
    def print_radio(self, *_):
        if not self.last_radio:
            return self.show_banner("Envoyez d'abord une demande de radiologie.", "error")
        self._print_radio(self.last_radio)

    @guard
    def refresh_radio(self, *_):
        reqs = self.db.radio_for_consultation(self.consult["id"]) if self.consult else []
        self.radio_table.setRowCount(len(reqs))
        for i, r in enumerate(reqs):
            for j, t in enumerate((r["ticket_label"], r["exam_type"] or "", f"{r['region'] or ''} / {r['side'] or ''}",
                                   RADIO_STATUS.get(r["status"], r["status"]))):
                self.radio_table.setItem(i, j, QTableWidgetItem(t))

    def _poll_radio(self):
        """Statut renvoyé par la radiologie vers le médecin traitant (interrogation toutes les 3 s)."""
        for r in self.db.radio_requests_for_doctor(self.user["id"], 24):
            old = self._radio_seen.get(r["id"])
            if old is not None and old != r["status"] and r["status"] in ("CALLED", "DONE", "AWAITING_PRINT"):
                self.show_banner(f"📋 Radiologie {r['ticket_label']} — {display_name(r)} : {RADIO_STATUS[r['status']]}")
                QApplication.beep()
            self._radio_seen[r["id"]] = r["status"]
        if self.consult:
            self.refresh_radio()

    # ----- analyses -----
    def _tab_lab(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.lab_list = QListWidget(); self.lab_list.setMinimumHeight(220)
        for t in LAB_ITEMS:
            it = QListWidgetItem(t); it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable); it.setCheckState(Qt.CheckState.Unchecked)
            self.lab_list.addItem(it)
        self.lab_other = QLineEdit(); self.lab_other.setPlaceholderText("Autres analyses (séparées par « ; »)")
        self.lab_info = QLineEdit(); self.lab_info.setPlaceholderText("Renseignements cliniques")
        b = QPushButton("🖨 Imprimer la demande d'analyses"); b.setObjectName("primary"); b.clicked.connect(self.print_lab)
        for x in (self.lab_list, self.lab_other, self.lab_info, b):
            v.addWidget(x)
        return w

    @guard
    def print_lab(self, *_):
        if not self.consult:
            return self.show_banner("Appelez d'abord un patient.", "error")
        items = [self.lab_list.item(i).text() for i in range(self.lab_list.count())
                 if self.lab_list.item(i).checkState() == Qt.CheckState.Checked]
        items += [t.strip() for t in self.lab_other.text().split(";") if t.strip()]
        if not items:
            return self.show_banner("Sélectionnez au moins une analyse.", "error")
        lab = self.db.create_lab_request(self.consult["id"], items, self.lab_info.text().strip(), self.user["id"])
        html, res = build_lab_request(self.cfg, lab, self.current, self.doctor())
        ok, msg = print_document(self.cfg, html, res, "a4", "analyses_" + lab["uuid"][:8])
        self.show_banner("Demande d'analyses : " + msg, "info" if ok else "error")
        for i in range(self.lab_list.count()):
            self.lab_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.lab_other.clear(); self.lab_info.clear()

    # ----- clôture -----
    def _tab_close(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.diag = QLineEdit(); self.diag.setPlaceholderText("Diagnostic / motif de consultation")
        self.notes = QTextEdit(); self.notes.setPlaceholderText("Observations, conduite à tenir…")
        b = QPushButton("✅ Clôturer la consultation et archiver"); b.setObjectName("primary"); b.clicked.connect(self.close_consult)
        for x in (self.diag, self.notes, b):
            v.addWidget(x)
        return w

    @guard
    def close_consult(self, *_):
        if not self.consult:
            return self.show_banner("Aucune consultation en cours.", "error")
        if not self.rx and self._items():
            if QMessageBox.question(self, "Ordonnance", "Des lignes d'ordonnance n'ont ni été imprimées ni enregistrées.\n"
                                    "Clôturer quand même ?") != QMessageBox.StandardButton.Yes:
                return
        dossier = self.db.close_consultation(self.consult["id"], self.notes.toPlainText().strip(), self.diag.text().strip())
        try:
            archive_consultation(dossier)
            msg = "Consultation clôturée et archivée."
        except OSError as e:
            msg = f"Consultation clôturée (archive locale impossible : {e})."
        self.set_current(None)
        self.refresh()
        self.show_banner("✅ " + msg)

    # ---------------- patient courant ----------------
    def set_current(self, row):
        self.current, self.consult, self.last_radio = row, None, None
        self._new_rx()
        for x in (self.diag, self.notes, self.r_info):
            x.clear()
        self.radio_table.setRowCount(0)
        if row and self.user:
            self.consult = self.db.start_consultation(row["id"], self.user["id"], self.station)
        self.cur_ticket.setText(row["ticket_label"] if row else "—")
        color = TRIAGE_COLORS.get(row["triage_level"], "") if row and row.get("triage_level") else ""
        self.cur_ticket.setStyleSheet(f"font-size:54px;font-weight:800;{'color:' + color + ';' if color else ''}")
        self.cur_name.setText(f"{display_name(row)}\n{age_from_row(row)} ans" if row else "Aucun patient appelé")
        self.cur_badge.setVisible(bool(row and self.user and self._revisit_of(row)))

    def on_login(self):
        self._load_drugs()
        self.set_current(self.db.current_called(self.station))
        self.refresh()

    @guard
    def call_next(self, *_):
        if not self.user:
            return
        row = self.db.call_next(self.services, self.station)   # le Hub diffuse l'appel à l'écran TV
        if not row:
            return self.show_banner("Aucun patient en attente.")
        self.hide_banner(); self.set_current(row)
        QApplication.beep(); self.refresh()

    @guard
    def recall(self, *_):
        if self.current:
            self.db.recall(self.current["id"], self.station); QApplication.beep()

    def open_profile(self, *_):
        if self.user:
            ProfileDialog(self.db, self.user, self).exec()
