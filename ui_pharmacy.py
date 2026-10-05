"""Poste Pharmacie : file de transit des ordonnances + validation par scan du QR Code (lecteur USB = saisie clavier)."""
import html

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ui_common import BaseWindow, guard


class PharmacyWindow(BaseWindow):
    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.cur_rx, self._queue = None, []
        body = QHBoxLayout(); self.content.addLayout(body, 1)

        left = QFrame(); left.setObjectName("card"); lv = QVBoxLayout(left)
        t = QLabel("Ordonnances reçues (file de transit)"); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.queue = QTableWidget(0, 4)
        self.queue.setHorizontalHeaderLabels(["Reçue", "Patient", "Médecin", "Lignes"])
        self.queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue.verticalHeader().hide(); self.queue.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.queue.doubleClicked.connect(lambda *_: self.open_selected())
        lv.addWidget(t); lv.addWidget(QLabel("Double-clic pour ouvrir.")); lv.addWidget(self.queue, 1)
        body.addWidget(left, 2)

        right = QFrame(); right.setObjectName("card"); rv = QVBoxLayout(right)
        h = QLabel("Validation de l'ordonnance"); h.setStyleSheet("font-size:18px;font-weight:700;")
        self.scan = QLineEdit(); self.scan.setPlaceholderText("Scannez le QR Code ou le code-barres (ou saisissez le N° d'ordonnance) puis Entrée")
        self.scan.returnPressed.connect(self.lookup)
        self.verdict = QLabel(""); self.verdict.setWordWrap(True); self.verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info = QLabel(""); self.info.setWordWrap(True)
        self.items = QTableWidget(0, 3); self.items.setHorizontalHeaderLabels(["Médicament", "Posologie", "Durée"])
        self.items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.items.verticalHeader().hide()
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.btn = QPushButton("✅ Marquer comme délivrée"); self.btn.setObjectName("primary"); self.btn.setEnabled(False)
        self.btn.clicked.connect(self.dispense)
        for x in (h, self.scan, self.verdict, self.info, self.items, self.btn):
            rv.addWidget(x)
        body.addWidget(right, 3)
        self.t = QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(3000)

    def on_login(self):
        self.scan.setFocus(); self.refresh()

    @guard
    def refresh(self, *_):
        if not self.user:
            return
        self._queue = self.db.pharmacy_queue(self.user["id"])
        if self._banner_kind == "error":
            self.hide_banner()
        self.queue.setRowCount(len(self._queue))
        for i, p in enumerate(self._queue):
            for j, txt in enumerate((p["date"][11:16], f"{p['patient']['nom']} {p['patient']['prenom']}", f"Dr {p['doctor']}", str(len(p["items"])))):
                self.queue.setItem(i, j, QTableWidgetItem(txt))

    def open_selected(self):
        r = self.queue.currentRow()
        if 0 <= r < len(self._queue):
            self.scan.setText(self._queue[r]["qr_text"]); self.lookup()

    @guard
    def lookup(self, *_):
        res = self.db.pharmacy_lookup(self.scan.text(), self.user["id"])
        self.scan.clear(); self.scan.setFocus()
        self.cur_rx = res.get("rx") if res.get("found") else None
        self.items.setRowCount(0); self.info.setText(""); self.btn.setEnabled(False)
        if not res["found"] or res["authentic"] is False:
            self.verdict.setStyleSheet("background:#c0392b;color:white;font-size:20px;font-weight:700;padding:12px;border-radius:8px;")
            self.verdict.setText("❌ NON AUTHENTIQUE\n" + res["reason"])
            if not res["found"]:
                self.cur_rx = None
                return
        elif res["authentic"] is None:
            self.verdict.setStyleSheet("background:#f5b041;color:#1b1b1b;font-size:18px;font-weight:700;padding:12px;border-radius:8px;")
            self.verdict.setText("⚠️ NON VÉRIFIÉE\n" + res["reason"])
        else:
            self.verdict.setStyleSheet("background:#27ae60;color:white;font-size:20px;font-weight:700;padding:12px;border-radius:8px;")
            self.verdict.setText("✅ ORDONNANCE AUTHENTIQUE")
        rx, p, d = self.cur_rx, self.cur_rx["patient"], self.cur_rx["doctor"]
        e = html.escape                                   # jamais de HTML issu des données (défense contre l'injection d'affichage)
        self.info.setText(f"<b>{e(p['last_name'] or '')} {e(p['first_name'] or '')}</b><br>Ordonnance n° {e(rx['number'])} — Médecin : Dr "
                          f"{e(d['last_name'] + ' ' + d['first_name']) if d else '—'}<br>Établie le {e(rx['created_at'])}<br>Statut : <b>{e(rx['status'])}</b>"
                          + (f" — délivrée le {e(rx['dispensed_at'])}" if rx["status"] == "DISPENSED" else ""))
        self.items.setRowCount(len(rx["items"]))
        for i, it in enumerate(rx["items"]):
            for j, k in enumerate(("drug", "dosage", "duration")):
                self.items.setItem(i, j, QTableWidgetItem(it[k]))
        self.btn.setEnabled(res["authentic"] is not False and rx["status"] != "DISPENSED")

    @guard
    def dispense(self, *_):
        if not self.cur_rx:
            return
        r = self.db.pharmacy_dispense(self.cur_rx["uuid"], self.user["id"])
        if r["ok"]:
            self.show_banner("✅ Ordonnance marquée comme délivrée.")
            self.btn.setEnabled(False); self.refresh()
        else:
            QMessageBox.warning(self, "Pharmacie", r["error"])
