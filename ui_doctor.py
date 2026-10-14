"""Poste Médecin / spécialiste : file d'attente filtrée sur SES services, ordonnance électronique, demandes d'imagerie et de biologie
envoyées en un clic, résultats reçus, dossier patient, clôture. Plusieurs médecins peuvent se relayer sur le même poste (sessions isolées)."""
from datetime import datetime

from PyQt6.QtCore import QStringListModel, Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QInputDialog, QCheckBox, QComboBox, QCompleter, QFrame, QGridLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                             QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from archive import archive_consultation
from data_structures import SERVICE_BY_CODE
from database import FMT, age_from_row, display_name
from documents import build_lab_request, build_prescription, build_radio_request
from medical_data import DURATIONS, EXAM_TYPES, LAB_ITEMS, POSOLOGIES, RADIO_STATUS, REGIONS, SIDES
from printer import print_document
from styles import TRIAGE_COLORS, TRIAGE_ICON, TRIAGE_TEXT
import userdata
from functions import ALERT_FUNCTIONS, format_vitals, honorific
from ui_common import BaseWindow, HandoverDialog, guard, open_tv
from ui_tv import AnnounceDialog
from ui_dpi import PatientSearchDialog, ResultViewer
from ui_login import ProfileDialog

BADGE = "⚠️ Patient Récurrent"
LAB_STATUS = {"PENDING": "⏳ En attente", "IN_PROGRESS": "🧪 En cours", "DONE": "✅ Terminé"}


def _item(txt):
    return QTableWidgetItem(txt)


class DoctorWindow(BaseWindow):
    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.services = []
        self.current = self.consult = self.rx = self.last_radio = None
        self.blink, self.row_triage, self._seen = False, [], {}
        self._last_draft = None
        self.btn_hand = QPushButton("📥 Reprises (0)"); self.btn_hand.clicked.connect(self.open_handovers); self.header_extra.addWidget(self.btn_hand)
        self.btn_alert = QPushButton("🚨 Alerte TV"); self.btn_alert.clicked.connect(self.open_alert); self.btn_alert.setVisible(False); self.header_extra.addWidget(self.btn_alert)
        for label, fn in (("🔁 Relève de garde / Changer de compte", self.logout), ("🔎 Dossiers patients", self.open_dpi), ("📅 Rendez-vous", self.rdv),
                          ("📝 Documents et certificats", self.documents), ("🖋 Mon profil", self.open_profile)):
            b = QPushButton(label); b.clicked.connect(fn); self.header_extra.addWidget(b)
        if cfg.get("tv_screen"):
            b = QPushButton("📺 Ouvrir l'écran TV"); b.clicked.connect(lambda *_: open_tv(self.cfg)); self.header_extra.addWidget(b)
        body = QHBoxLayout(); self.content.addLayout(body, 1)
        body.addWidget(self._build_queue(), 4 if self.prof["compact"] else 3)
        body.addWidget(self._build_workspace(), 5)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.call_next)
        self.t_refresh = QTimer(self); self.t_refresh.timeout.connect(self.refresh); self.t_refresh.start(3000)
        self.t_blink = QTimer(self); self.t_blink.timeout.connect(self._blink); self.t_blink.start(600)
        self.t_draft = QTimer(self); self.t_draft.timeout.connect(self.autosave); self.t_draft.start(4000)    # sauvegarde instantanée du brouillon
        self.set_current(None)

    def hours(self):
        return int(self.cfg.get("revisit_check_hours", 72))

    def doctor(self):
        return self.db.get_user(self.user["id"])      # inclut griffe et signature

    # ---------------- file d'attente (uniquement les services de CE médecin) ----------------
    def _build_queue(self):
        left = QFrame(); left.setObjectName("card"); lv = QVBoxLayout(left)
        t = QLabel("File d'attente"); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.svc_label = QLabel(); self.svc_label.setWordWrap(True)
        self.count = QLabel(); self.count.setStyleSheet("color:#8b97a7;")
        lv.addWidget(t); lv.addWidget(self.svc_label); lv.addWidget(self.count)
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
        if not self.user or not self.services:
            return
        sel = self.table.currentItem().data(Qt.ItemDataRole.UserRole) if self.table.currentItem() else None
        rows = self.db.queue(self.services, self.hours())
        self._update_handover_btn()
        if self._banner_kind == "error":
            self.hide_banner()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows)); self.row_triage = []
        for i, r in enumerate(rows):
            wait = int((datetime.now() - datetime.strptime(r["created_at"], FMT)).total_seconds() // 60)
            tri = f"{TRIAGE_ICON[r['triage_level']]} {TRIAGE_TEXT[r['triage_level']]}" if r["triage_level"] else "🟢 Standard"
            for j, txt in enumerate([r["ticket_label"], display_name(r), f"{age_from_row(r)} ans", tri, BADGE if r["recurrent"] else "", f"{wait} min"]):
                it = _item(txt); it.setData(Qt.ItemDataRole.UserRole, r["id"])
                if j == 4 and r["recurrent"]:
                    it.setForeground(QColor("#f39c12"))
                self.table.setItem(i, j, it)
            self.row_triage.append(r["triage_level"] or "VERT")
            if r["id"] == sel:
                self.table.selectRow(i)
        self.table.blockSignals(False)
        self.count.setText(f"{len(rows)} patient(s) en attente")
        self._paint()
        self._poll_exams()

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
        if it:
            rev = self._revisit_of(self.db.get(it.data(Qt.ItemDataRole.UserRole)))
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
        self.cur_name = QLabel(""); self.cur_name.setAlignment(Qt.AlignmentFlag.AlignCenter); self.cur_name.setTextFormat(Qt.TextFormat.PlainText)
        self.cur_name.setStyleSheet("font-size:18px;"); self.cur_name.setWordWrap(True)
        self.cur_vitals = QLabel(""); self.cur_vitals.setWordWrap(True); self.cur_vitals.setTextFormat(Qt.TextFormat.PlainText)
        self.cur_vitals.setStyleSheet("background:#0e141b;border:1px solid #2c3644;border-radius:8px;padding:6px;")
        self.cur_badge = QLabel(BADGE); self.cur_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_badge.setStyleSheet("background:#f39c12;color:#1b1b1b;font-weight:700;padding:6px;border-radius:8px;")
        nxt = QPushButton("📣  Appel Suivant   (Espace)"); nxt.setObjectName("primary"); nxt.clicked.connect(self.call_next)
        rec = QPushButton("📢 Rappeler / répéter l'appel"); rec.clicked.connect(self.recall)
        row = QHBoxLayout(); row.addWidget(nxt, 3); row.addWidget(rec, 1)
        for x in (h, self.cur_ticket, self.cur_name, self.cur_badge, self.cur_vitals):
            cv.addWidget(x)
        cv.addLayout(row)
        v.addWidget(card)
        self.tabs = QTabWidget(); v.addWidget(self.tabs, 1)
        self.tabs.addTab(self._tab_rx(), "💊 Ordonnance")
        self.tabs.addTab(self._tab_radio(), "🩻 Imagerie")
        self.tabs.addTab(self._tab_lab(), "🧪 Biologie")
        self.tabs.addTab(self._tab_close(), "✅ Clôture")
        sc.setWidget(w)
        return sc

    @staticmethod
    def _chips(items, target):
        g = QGridLayout()
        for i, t in enumerate(items):
            b = QPushButton(t.replace("&", "&&")); b.setStyleSheet("padding:4px 8px;font-size:12px;")
            b.clicked.connect(lambda _=False, t=t: target.setText(t))
            g.addWidget(b, i // 4, i % 4)
        return g

    # ----- ordonnance -----
    def _tab_rx(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.drug = QLineEdit(); self.drug.setPlaceholderText("Médicament — saisie semi-automatique (nomenclature)")
        self.drug_model = QStringListModel([])
        comp = QCompleter(self.drug_model, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive); comp.setFilterMode(Qt.MatchFlag.MatchContains)
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
        for label, fn in (("🖨 Imprimer l'ordonnance", self.print_rx), ("📤 Envoyer à la Pharmacie", self.send_pharmacy), ("🆕 Nouvelle ordonnance", self._new_rx)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        v.addLayout(row)
        self.rx_status = QLabel(""); v.addWidget(self.rx_status)
        self.drug.returnPressed.connect(self.dose.setFocus); self.dose.returnPressed.connect(self.dur.setFocus); self.dur.returnPressed.connect(self.add_item)
        return w

    def _load_drugs(self):
        self.drug_model.setStringList(self.db.list_drug_names())

    def add_item(self, *_):
        drug = self.drug.text().strip()
        if not drug or self.rx:
            return
        r = self.rx_table.rowCount(); self.rx_table.insertRow(r)
        for j, t in enumerate((drug, self.dose.text().strip(), self.dur.text().strip())):
            self.rx_table.setItem(r, j, _item(t))
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
        self.rx_status.setText(f"Ordonnance n° {self.rx['number']} enregistrée (figée, QR + code-barres).")
        self._load_drugs()
        return self.rx

    @guard
    def print_rx(self, *_):
        rx = self._ensure_rx()
        if not rx:
            return
        html, res = build_prescription(self.cfg, rx, self.current, self.doctor())
        ok, msg = print_document(self.cfg, html, res, "a4", "ordonnance_" + rx["number"], template_kind="ordonnance")
        self.log("ordonnance", rx["number"])
        self.show_banner("Ordonnance : " + msg, "info" if ok else "error")

    @guard
    def send_pharmacy(self, *_):
        rx = self._ensure_rx()
        if not rx:
            return
        self.rx = self.db.send_to_pharmacy(rx["uuid"], self.user["id"])
        self.rx_status.setText(f"Ordonnance n° {self.rx['number']} transmise à la Pharmacie.")
        self.show_banner("📤 Ordonnance envoyée à la Pharmacie.")

    # ----- imagerie -----
    def _tab_radio(self):
        w = QWidget(); f = QVBoxLayout(w)
        self.r_type = QComboBox(); self.r_type.addItems(EXAM_TYPES)
        self.r_region = QComboBox(); self.r_region.setEditable(True); self.r_region.addItems(REGIONS)
        self.r_side = QComboBox(); self.r_side.addItems(SIDES)
        self.r_info = QTextEdit(); self.r_info.setPlaceholderText("Renseignements cliniques"); self.r_info.setMaximumHeight(80)
        self.r_instr = QLineEdit(); self.r_instr.setPlaceholderText("Consignes spécifiques pour le manipulateur (incidence, protocole…)")
        self.r_urgent = QCheckBox("🚨 Urgent"); self.r_paper = QCheckBox("Imprimer aussi la demande papier")
        for lab, x in (("Type d'examen", self.r_type), ("Région anatomique", self.r_region), ("Côté", self.r_side)):
            f.addWidget(QLabel(lab)); f.addWidget(x)
        for x in (self.r_info, self.r_instr, self.r_urgent, self.r_paper):
            f.addWidget(x)
        row = QHBoxLayout()
        b1 = QPushButton("📡 Envoyer au Poste Radiologie"); b1.setObjectName("primary"); b1.clicked.connect(self.send_radio)
        b2 = QPushButton("🖨 Imprimer la dernière demande"); b2.clicked.connect(self.print_radio)
        row.addWidget(b1, 2); row.addWidget(b2, 1); f.addLayout(row)
        self.radio_table = QTableWidget(0, 4)
        self.radio_table.setHorizontalHeaderLabels(["Passage", "Examen", "Région / côté", "Statut"])
        self.radio_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.radio_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.radio_table.verticalHeader().hide(); self.radio_table.setMinimumHeight(110)
        self.radio_table.horizontalHeader().setStretchLastSection(True)
        self._radio_rows = []
        bo = QPushButton("📎 Ouvrir le cliché / compte rendu reçu"); bo.clicked.connect(lambda *_: self._open_result("radio", self.radio_table, self._radio_rows))
        f.addWidget(QLabel("Demandes de cette consultation :")); f.addWidget(self.radio_table); f.addWidget(bo)
        return w

    def _apply_specialty_defaults(self):
        if self.services == ["DENT"]:                          # chirurgien-dentiste : radio panoramique par défaut
            self.r_type.setCurrentText("Radio panoramique dentaire"); self.r_region.setCurrentText("Mâchoires (panoramique)")
            self.r_side.setCurrentText("Non applicable")

    @guard
    def send_radio(self, *_):
        if not self.consult:
            return self.show_banner("Appelez d'abord un patient.", "error")
        req = self.db.create_radio_request(self.consult["id"], self.r_type.currentText(), self.r_region.currentText(), self.r_side.currentText(),
                                           self.r_info.toPlainText().strip(), self.r_instr.text().strip(), self.r_urgent.isChecked(),
                                           self.user["id"], self.station)
        self.last_radio = req
        self.log("demande imagerie", req["ticket_label"])
        if self.r_paper.isChecked():
            self._print_radio(req)
        self.show_banner(f"📡 Demande envoyée à la Radiologie — numéro de passage {req['ticket_label']}.")
        self.r_info.clear(); self.r_instr.clear(); self.r_urgent.setChecked(False)
        self.refresh_exams()

    def _print_radio(self, req):
        html, res = build_radio_request(self.cfg, req, self.current, self.doctor())
        ok, msg = print_document(self.cfg, html, res, "a4", "radio_" + req["ticket_label"], template_kind="imagerie")
        if not ok:
            self.show_banner("Impression : " + msg, "error")

    @guard
    def print_radio(self, *_):
        if not self.last_radio:
            return self.show_banner("Envoyez d'abord une demande d'imagerie.", "error")
        self._print_radio(self.last_radio)

    # ----- biologie : envoi direct au laboratoire en un clic -----
    def _tab_lab(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.lab_list = QListWidget(); self.lab_list.setMinimumHeight(200)
        for t in LAB_ITEMS:
            it = QListWidgetItem(t); it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable); it.setCheckState(Qt.CheckState.Unchecked)
            self.lab_list.addItem(it)
        self.lab_other = QLineEdit(); self.lab_other.setPlaceholderText("Autres analyses (séparées par « ; »)")
        self.lab_info = QLineEdit(); self.lab_info.setPlaceholderText("Renseignements cliniques")
        self.lab_urgent = QCheckBox("🚨 Urgent"); self.lab_paper = QCheckBox("Imprimer aussi l'imprimé papier")
        b = QPushButton("🧪 Envoyer au Laboratoire (1 clic)"); b.setObjectName("primary"); b.clicked.connect(self.send_lab)
        for x in (self.lab_list, self.lab_other, self.lab_info, self.lab_urgent, self.lab_paper, b):
            v.addWidget(x)
        self.lab_table = QTableWidget(0, 3)
        self.lab_table.setHorizontalHeaderLabels(["N°", "Analyses", "Statut"])
        self.lab_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lab_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lab_table.verticalHeader().hide(); self.lab_table.setMinimumHeight(100); self.lab_table.horizontalHeader().setStretchLastSection(True)
        self._lab_rows = []
        bo = QPushButton("📎 Ouvrir le résultat reçu"); bo.clicked.connect(lambda *_: self._open_result("lab", self.lab_table, self._lab_rows))
        v.addWidget(QLabel("Demandes de cette consultation :")); v.addWidget(self.lab_table); v.addWidget(bo)
        return w

    @guard
    def send_lab(self, *_):
        if not self.consult:
            return self.show_banner("Appelez d'abord un patient.", "error")
        items = [self.lab_list.item(i).text() for i in range(self.lab_list.count()) if self.lab_list.item(i).checkState() == Qt.CheckState.Checked]
        items += [t.strip() for t in self.lab_other.text().split(";") if t.strip()]
        if not items:
            return self.show_banner("Sélectionnez au moins une analyse.", "error")
        lab = self.db.create_lab_request(self.consult["id"], items, self.lab_info.text().strip(), self.lab_urgent.isChecked(), self.user["id"])
        if self.lab_paper.isChecked():
            html, res = build_lab_request(self.cfg, lab, self.current, self.doctor())
            print_document(self.cfg, html, res, "a4", "bilan_" + lab["ticket_label"], template_kind="bilan")
        self.log("demande laboratoire", lab["ticket_label"])
        self.show_banner(f"🧪 Demande envoyée au Laboratoire — {lab['ticket_label']}.")
        for i in range(self.lab_list.count()):
            self.lab_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.lab_other.clear(); self.lab_info.clear(); self.lab_urgent.setChecked(False)
        self.refresh_exams()

    # ----- résultats reçus / suivi des examens -----
    @guard
    def refresh_exams(self, *_):
        if not self.consult:
            self.radio_table.setRowCount(0); self.lab_table.setRowCount(0); self._radio_rows = self._lab_rows = []
            return
        self._radio_rows = self.db.radio_for_consultation(self.consult["id"], self.user["id"])
        self.radio_table.setRowCount(len(self._radio_rows))
        for i, r in enumerate(self._radio_rows):
            for j, t in enumerate((r["ticket_label"], r["exam_type"] or "", f"{r['region'] or ''} / {r['side'] or ''}",
                                   RADIO_STATUS.get(r["status"], r["status"]) + (f"  📎 {r['n_results']}" if r["n_results"] else ""))):
                self.radio_table.setItem(i, j, _item(t))
        self._lab_rows = self.db.lab_for_consultation(self.consult["id"], self.user["id"])
        self.lab_table.setRowCount(len(self._lab_rows))
        for i, l in enumerate(self._lab_rows):
            for j, t in enumerate((l["ticket_label"] or "", ", ".join(l["items"])[:60],
                                   LAB_STATUS.get(l["status"], l["status"]) + (f"  📎 {l['n_results']}" if l["n_results"] else ""))):
                self.lab_table.setItem(i, j, _item(t))

    def _open_result(self, kind, table, rows):
        r = table.currentRow()
        if not (0 <= r < len(rows)):
            return self.show_banner("Sélectionnez d'abord une demande dans la liste.", "error")
        res = self.db.list_results(kind, rows[r]["id"], self.user["id"])
        if not res:
            return self.show_banner("Aucun résultat reçu pour cette demande pour l'instant.")
        ResultViewer(self.db, self.user["id"], res[-1]["id"], self.cfg, display_name(self.current) if self.current else "", self).exec()

    def _poll_exams(self):
        """Statut et résultats renvoyés par la radiologie et le laboratoire vers le médecin demandeur (toutes les 3 s)."""
        news = []
        for kind, rows in (("radio", self.db.radio_requests_for_doctor(self.user["id"], 24)), ("lab", self.db.lab_requests_for_doctor(self.user["id"], 24))):
            for r in rows:
                key, sig = (kind, r["id"]), (r["status"], r["n_results"])
                if key in self._seen and self._seen[key] != sig and (r["status"] in ("CALLED", "DONE", "AWAITING_PRINT", "IN_PROGRESS") or sig[1] > self._seen[key][1]):
                    news.append(f"{'Radiologie' if kind == 'radio' else 'Laboratoire'} {r['ticket_label']} — {display_name(r)} : "
                                + (f"📎 résultat reçu" if sig[1] > self._seen[key][1] else (RADIO_STATUS if kind == "radio" else LAB_STATUS).get(r["status"], r["status"])))
                self._seen[key] = sig
        if news:
            self.show_banner("📋 " + " | ".join(news[:2]), ms=8000); QApplication.beep()
        if self.consult:
            self.refresh_exams()

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
            if QMessageBox.question(self, "Ordonnance", "Des lignes d'ordonnance n'ont été ni imprimées ni enregistrées.\nClôturer quand même ?") != QMessageBox.StandardButton.Yes:
                return
        dossier = self.db.close_consultation(self.consult["id"], self.notes.toPlainText().strip(), self.diag.text().strip(), self.user["id"])
        userdata.delete_draft(self.user, f"consult_{dossier['consultation']['admission_id']}")
        self.log("clôture", dossier["patient"]["ticket_label"])
        try:
            archive_consultation(dossier)
            msg = "Consultation clôturée et archivée."
        except OSError as e:
            msg = f"Consultation clôturée (archive locale impossible : {e})."
        self.set_current(None)
        self.refresh()
        self.show_banner("✅ " + msg)

    # ---------------- brouillon de consultation (relève de garde) ----------------
    def collect_draft(self):
        if not (self.current and self.consult):
            return None
        return {"items": [] if self.rx else self._items(), "rx_notes": self.rx_notes.text(), "diag": self.diag.text(), "notes": self.notes.toPlainText(),
                "r_info": self.r_info.toPlainText(), "lab_other": self.lab_other.text(), "lab_info": self.lab_info.text()}

    def apply_draft(self, d):
        if self.rx:
            return
        for it in d.get("items", []):
            r = self.rx_table.rowCount(); self.rx_table.insertRow(r)
            for j, k in enumerate(("drug", "dosage", "duration")):
                self.rx_table.setItem(r, j, _item(it.get(k, "")))
        self.rx_notes.setText(d.get("rx_notes", "")); self.diag.setText(d.get("diag", "")); self.notes.setPlainText(d.get("notes", ""))
        self.r_info.setPlainText(d.get("r_info", "")); self.lab_other.setText(d.get("lab_other", "")); self.lab_info.setText(d.get("lab_info", ""))

    @guard
    def autosave(self, *_):
        """Enregistre le brouillon (base chiffrée + copie dans le dossier de l'agent) dès qu'il change."""
        d = self.collect_draft() if self.user else None
        if not d or not any(d.values()):
            return
        key = repr(sorted(d.items()))
        if key == self._last_draft:
            return
        self.db.save_draft(self.current["id"], "consult", d, self.user["id"])
        userdata.save_draft(self.user, f"consult_{self.current['id']}", d)
        self._last_draft = key

    # ---------------- relève de garde ----------------
    def _services_hand(self):
        return self.services

    @guard
    def open_handovers(self, *_):
        if not self.user:
            return
        dlg = HandoverDialog(self.db, self.user, self.services, self)
        if dlg.exec() and dlg.taken:
            self.log("reprise", dlg.taken["ticket_label"])
            self.set_current(self.db.get(dlg.taken["id"]))
            self.show_banner(f"📥 Patient {dlg.taken['ticket_label']} repris — brouillon retrouvé.")

    def _update_handover_btn(self):
        n = len(self.db.handover_list(self.services, self.user["id"]))
        self.btn_hand.setText(f"📥 Reprises ({n})")
        self.btn_hand.setStyleSheet("background:#f39c12;color:#1b1b1b;font-weight:700;" if n else "")
        return n

    @guard
    def open_alert(self, *_):
        if self.user:
            AnnounceDialog(self.db, self.user["id"], self).exec()

    # ---------------- patient courant ----------------
    def set_current(self, row):
        self.current, self.consult, self.last_radio = row, None, None
        self._new_rx()
        for x in (self.diag, self.notes, self.r_info):
            x.clear()
        self.radio_table.setRowCount(0); self.lab_table.setRowCount(0)
        self._last_draft = None
        self.cur_vitals.setVisible(False)
        if row and self.user:
            self.consult = self.db.start_consultation(row["id"], self.user["id"], self.station)
            draft = self.db.get_draft(row["id"], "consult", self.user["id"])
            if draft:
                self.apply_draft(draft); self.show_banner("📝 Brouillon de consultation retrouvé.", ms=5000)
            vit = self.db.vitals_for_admission(row["id"], self.user["id"])
            if vit:
                self.cur_vitals.setText("🩺 Constantes (" + (vit[0]["recorded_at"] or "")[11:16] + ") : " + format_vitals(vit[0])); self.cur_vitals.setVisible(True)
        self.cur_ticket.setText(row["ticket_label"] if row else "—")
        color = TRIAGE_COLORS.get(row["triage_level"], "") if row and row.get("triage_level") else ""
        self.cur_ticket.setStyleSheet(f"font-size:54px;font-weight:800;{'color:' + color + ';' if color else ''}")
        self.cur_name.setText(f"{display_name(row)}\n{age_from_row(row)} ans" if row else "Aucun patient appelé")
        self.cur_badge.setVisible(bool(row and self.user and self._revisit_of(row)))

    def on_login(self):
        self.services = [s for s in (self.user.get("services") or []) if s in SERVICE_BY_CODE] or ["MG"]
        self.svc_label.setText("Services : " + " · ".join(f"{SERVICE_BY_CODE[c]['icon']} {SERVICE_BY_CODE[c]['name']}" for c in self.services))
        self._seen = {}
        self._apply_specialty_defaults()
        self._load_drugs()
        self.btn_alert.setVisible(self.user.get("function") in ALERT_FUNCTIONS)
        self.set_current(self.db.current_called(self.station, self.user["id"]))
        self.refresh()
        n = self._update_handover_btn()
        if n:
            self.show_banner(f"📥 {n} consultation(s) en attente de reprise (bouton « Reprises »).", ms=8000)

    def before_logout(self):
        """Relève de garde : le patient en cours est réservé pour un confrère (brouillon conservé), remis en file, ou on reste connecté."""
        if not self.current:
            return True
        self.autosave()
        box = QMessageBox(QMessageBox.Icon.Question, "Relève de garde",
                          f"Le patient {self.current['ticket_label']} est en consultation.\nQue faire avant de changer de compte ?", parent=self)
        hand = box.addButton("🔁 Relève : réserver pour un confrère", QMessageBox.ButtonRole.AcceptRole)
        back = box.addButton("Remettre en file d'attente", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Rester connecté", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        try:
            if box.clickedButton() is hand:
                note, ok = QInputDialog.getText(self, "Relève de garde", "Consigne pour le confrère (facultatif) :")
                if not ok:
                    return False
                self.db.handover_start(self.current["id"], note, self.user["id"]); self.log("relève de garde", self.current["ticket_label"])
                return True
            if box.clickedButton() is back:
                self.db.release_patient(self.current["id"], self.user["id"]); self.log("patient remis en file", self.current["ticket_label"])
                return True
        except (ConnectionError, PermissionError, ValueError) as e:
            self.show_banner(str(e), "error")
        return False

    @guard
    def call_next(self, *_):
        if not self.user:
            return
        row = self.db.call_next(self.services, self.station, self.user["id"], self.room)   # l'écran concerné reçoit l'appel (service_id)
        if not row:
            return self.show_banner("Aucun patient en attente.")
        self.hide_banner(); self.set_current(row)
        QApplication.beep(); self.refresh()

    @guard
    def recall(self, *_):
        if self.current:
            self.db.recall(self.current["id"], self.station, self.user["id"], self.room); QApplication.beep()

    def open_profile(self, *_):
        if self.user:
            ProfileDialog(self.db, self.user, self).exec()

    @guard
    def rdv(self, *_):
        a = self.current
        self.open_appointments({"last_name": a["last_name"], "first_name": a["first_name"], "birth_year": a.get("birth_year"), "gender": a.get("gender"),
                                "ident": a.get("patient_ident") or ""} if a else None)

    @guard
    def documents(self, *_):
        self.open_documents(self.current, (self.user or {}).get("services", [""])[0] if (self.user or {}).get("services") else "")

    @guard
    def open_dpi(self, *_):
        if self.user:
            PatientSearchDialog(self.db, self.user, self.cfg, self).exec()
