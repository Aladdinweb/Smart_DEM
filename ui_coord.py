"""Vues globales multi-services des COORDINATEURS (médecins / paramédical) : supervision des files de toute la garde, urgences, temps d'attente,
relèves en cours, réorientation d'un patient en attente, alertes sur les écrans TV. Le coordinateur supervise : il n'appelle pas les patients."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTabWidget,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from data_structures import CONSULT_SERVICES, SERVICE_BY_CODE
from styles import TRIAGE_ICON, TRIAGE_TEXT
from ui_common import BaseWindow, guard, open_tv
from ui_dpi import PatientSearchDialog
from ui_tv import AnnounceDialog


def _tbl(headers):
    t = QTableWidget(0, len(headers)); t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); t.verticalHeader().hide(); t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return t


class CoordWindow(BaseWindow):
    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self._waiting = []
        for label, fn in (("🚨 Alerte sur les écrans TV", self.open_alert), ("🔊 Voix des écrans : activer / couper", self.toggle_voice)):
            b = QPushButton(label); b.clicked.connect(fn); self.header_extra.addWidget(b)
        if cfg.get("tv_screen"):
            t = QPushButton("📺 Ouvrir l'écran TV"); t.clicked.connect(lambda *_: open_tv(self.cfg)); self.header_extra.addWidget(t)
        if cfg.get("role") == "coord_para":
            d = QPushButton("🔎 Dossiers patients"); d.clicked.connect(self.open_dpi); self.header_extra.addWidget(d)
        tabs = QTabWidget(); self.content.addWidget(tabs, 1)
        w1 = QWidget(); v1 = QVBoxLayout(w1)
        self.kpi = QLabel(""); self.kpi.setStyleSheet("font-size:17px;font-weight:700;"); self.kpi.setTextFormat(Qt.TextFormat.PlainText)
        self.over = _tbl(["Service", "En attente", "En cours / appelés", "Terminés", "Urgences 🔴", "Attente moyenne", "Plus ancienne"])
        v1.addWidget(self.kpi); v1.addWidget(self.over, 1)
        tabs.addTab(w1, "📊 Vue d'ensemble")
        w2 = QWidget(); v2 = QVBoxLayout(w2)
        self.wait = _tbl(["Ticket", "Patient", "Service", "Âge", "Niveau", "Attente"])
        row = QHBoxLayout(); self.dest = QComboBox()
        b = QPushButton("↪ Réorienter le patient sélectionné vers :"); b.clicked.connect(self.reassign)
        row.addWidget(b); row.addWidget(self.dest, 1)
        v2.addWidget(self.wait, 1); v2.addLayout(row)
        tabs.addTab(w2, "👥 File globale")
        self.t = QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(3000)

    def on_login(self):
        self.dest.clear()
        for c in (["SOINS"] if self.user["role"] == "coord_para" else CONSULT_SERVICES) + (CONSULT_SERVICES if self.user["role"] == "coord_para" else ["SOINS"]):
            self.dest.addItem(f"{SERVICE_BY_CODE[c]['icon']} {SERVICE_BY_CODE[c]['name']}".replace("&", "&&"), c)
        self.refresh()

    @guard
    def refresh(self, *_):
        if not self.user:
            return
        ov = self.db.coord_overview(self.user["id"])
        if self._banner_kind == "error":
            self.hide_banner()
        self.kpi.setText(f"Garde en cours : {ov['total']} passage(s) · {sum(s['waiting'] for s in ov['by_service'])} en attente · "
                         f"{sum(s['red'] for s in ov['by_service'])} urgence(s) · {ov['handovers']} relève(s) en cours")
        self.over.setRowCount(len(ov["by_service"]))
        for i, s in enumerate(ov["by_service"]):
            svc = SERVICE_BY_CODE[s["code"]]
            for j, txt in enumerate((f"{svc['icon']} {svc['name']}", s["waiting"], s["called"], s["done"], s["red"],
                                     f"{s['avg_wait']} min" if s["avg_wait"] is not None else "—", f"{s['oldest_wait']} min" if s["waiting"] else "—")):
                self.over.setItem(i, j, QTableWidgetItem(str(txt)))
        sel = self.wait.currentRow()
        self._waiting = ov["waiting"]
        self.wait.setRowCount(len(self._waiting))
        for i, r in enumerate(self._waiting):
            tri = f"{TRIAGE_ICON[r['triage_level']]} {TRIAGE_TEXT[r['triage_level']]}" if r["triage_level"] else "—"
            for j, txt in enumerate((r["ticket_label"], r["display"], SERVICE_BY_CODE[r["service_code"]]["name"], f"{r['age']} ans", tri, f"{r['wait_min']} min")):
                self.wait.setItem(i, j, QTableWidgetItem(txt))
        if 0 <= sel < len(self._waiting):
            self.wait.selectRow(sel)

    @guard
    def reassign(self, *_):
        r = self.wait.currentRow()
        if not 0 <= r < len(self._waiting):
            return self.show_banner("Sélectionnez un patient en attente.", "error")
        p = self._waiting[r]
        try:
            self.db.reassign_admission(p["id"], self.dest.currentData(), self.user["id"])
        except ValueError as e:
            return self.show_banner(str(e), "error")
        self.log("réorientation", f"{p['ticket_label']} → {self.dest.currentData()}")
        self.show_banner(f"{p['ticket_label']} réorienté."); self.refresh()

    @guard
    def open_alert(self, *_):
        if self.user:
            AnnounceDialog(self.db, self.user["id"], self).exec()

    @guard
    def open_dpi(self, *_):
        if self.user:
            PatientSearchDialog(self.db, self.user, self.cfg, self).exec()

    @guard
    def toggle_voice(self, *_):
        st = self.db.tv_state()
        new = self.db.tv_voice(not st.get("voice", True), self.user["id"])
        self.show_banner("🔊 Voix des écrans activée." if new["voice"] else "🔇 Voix des écrans coupée (le bip reste actif).")
