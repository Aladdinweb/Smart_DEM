"""Poste Médecin : file d'attente par priorité, appel suivant (Espace), pas de reset de compteur."""
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout)

from data_structures import SERVICE_BY_CODE
from database import FMT, age_from_row
from styles import TRIAGE_COLORS, TRIAGE_ICON, TRIAGE_TEXT
from ui_common import BaseWindow, guard


class DoctorWindow(BaseWindow):
    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.services = [c for c in cfg.get("services", []) if c in SERVICE_BY_CODE]
        self.current = db.current_called(self.station)
        self.blink = False
        self.row_triage = []
        body = QHBoxLayout(); self.content.addLayout(body, 1)

        left = QFrame(); left.setObjectName("card"); lv = QVBoxLayout(left)
        names = " · ".join(f"{SERVICE_BY_CODE[c]['icon']} {SERVICE_BY_CODE[c]['name']}" for c in self.services)
        t = QLabel("File d'attente"); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.count = QLabel(); self.count.setStyleSheet("color:#8b97a7;")
        lv.addWidget(t); lv.addWidget(QLabel(names)); lv.addWidget(self.count)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Ticket", "Nom & Prénom", "Âge", "Service", "Niveau", "Attente"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # la touche Espace reste dédiée à l'appel
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        for i in range(6):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i == 1 else QHeaderView.ResizeMode.ResizeToContents)
        lv.addWidget(self.table, 1)
        self.table.itemSelectionChanged.connect(self.on_select)
        body.addWidget(left, 3)

        right = QFrame(); right.setObjectName("card"); rv = QVBoxLayout(right)
        h = QLabel("Patient en cours"); h.setStyleSheet("font-size:18px;font-weight:700;")
        self.cur_ticket = QLabel("—"); self.cur_ticket.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_ticket.setStyleSheet("font-size:54px;font-weight:800;")
        self.cur_name = QLabel(""); self.cur_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_name.setStyleSheet("font-size:18px;"); self.cur_name.setWordWrap(True)
        nxt = QPushButton("📣  Appel Suivant   (Espace)"); nxt.setObjectName("primary"); nxt.clicked.connect(self.call_next)
        rec = QPushButton("🔁 Rappeler"); rec.clicked.connect(self.recall)
        fin = QPushButton("✔ Terminer la consultation"); fin.clicked.connect(self.finish)
        for w in (h, self.cur_ticket, self.cur_name): rv.addWidget(w)
        rv.addStretch(); rv.addWidget(nxt); rv.addWidget(rec); rv.addWidget(fin)
        body.addWidget(right, 2)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.call_next)
        self.t_refresh = QTimer(self); self.t_refresh.timeout.connect(self.refresh); self.t_refresh.start(3000)
        self.t_blink = QTimer(self); self.t_blink.timeout.connect(self._blink); self.t_blink.start(600)
        self.set_current(self.current)
        self.refresh()

    @guard
    def refresh(self, *_):
        sel = self.table.currentItem().data(Qt.ItemDataRole.UserRole) if self.table.currentItem() else None
        rows = self.db.queue(self.services)
        if self._banner_kind == "error":
            self.hide_banner()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows)); self.row_triage = []
        for i, r in enumerate(rows):
            svc = SERVICE_BY_CODE[r["service_code"]]
            wait = int((datetime.now() - datetime.strptime(r["created_at"], FMT)).total_seconds() // 60)
            tri = f"{TRIAGE_ICON[r['triage_level']]} {TRIAGE_TEXT[r['triage_level']]}" if r["triage_level"] else "🟢 Standard"
            cells = [r["ticket_label"], r["full_name"], f"{age_from_row(r)} ans", f"{svc['icon']} {svc['name']}", tri, f"{wait} min"]
            for j, txt in enumerate(cells):
                it = QTableWidgetItem(txt); it.setData(Qt.ItemDataRole.UserRole, r["id"])
                self.table.setItem(i, j, it)
            self.row_triage.append(r["triage_level"] or "VERT")
            if r["id"] == sel:
                self.table.selectRow(i)
        self.table.blockSignals(False)
        self.count.setText(f"{len(rows)} patient(s) en attente")
        self._paint()

    def _paint(self):
        for i, lvl in enumerate(self.row_triage):
            col = QColor(TRIAGE_COLORS[lvl])
            col.setAlpha((230 if self.blink else 80) if lvl == "ROUGE" else 55)
            for j in range(self.table.columnCount()):
                it = self.table.item(i, j)
                if it: it.setBackground(col)

    def _blink(self):
        self.blink = not self.blink
        self._paint()

    @guard
    def on_select(self, *_):
        it = self.table.currentItem()
        if not it:
            return
        row = self.db.get(it.data(Qt.ItemDataRole.UserRole))
        parsed = {"birth_year": row["birth_year"], "birth_date": row["birth_date"]}
        rev = self.db.find_revisit(row["full_name"], row["gender"], parsed, int(self.cfg.get("revisit_check_hours", 24)), row["id"])
        self.show_revisit(rev) if rev else self.clear_revisit_banner()

    def set_current(self, row):
        self.current = row
        self.cur_ticket.setText(row["ticket_label"] if row else "—")
        self.cur_name.setText(f"{row['full_name']}\n{age_from_row(row)} ans" if row else "Aucun patient appelé")
        color = TRIAGE_COLORS.get(row["triage_level"], "") if row and row["triage_level"] else ""
        self.cur_ticket.setStyleSheet(f"font-size:54px;font-weight:800;{'color:' + color + ';' if color else ''}")

    @guard
    def call_next(self, *_):
        row = self.db.call_next(self.services, self.station)   # le Hub diffuse l'appel à l'écran TV
        if not row:
            return self.show_banner("Aucun patient en attente.")
        self.hide_banner(); self.set_current(row)
        QApplication.beep(); self.refresh()

    @guard
    def recall(self, *_):
        if self.current:
            self.db.recall(self.current["id"], self.station); QApplication.beep()

    @guard
    def finish(self, *_):
        if self.current:
            self.db.finish(self.current["id"]); self.set_current(None)
