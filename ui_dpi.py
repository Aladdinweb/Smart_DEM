"""Dossier Patient Informatisé : recherche globale (nom, prénom, date de naissance, N° d'identification), historique complet, résultats."""
import base64, os, tempfile
from datetime import datetime

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout)

from data_structures import SERVICE_BY_CODE
from database import FMT
from documents import build_result
from medical_data import RADIO_STATUS
from printer import print_document


def _fmt(ts):
    try:
        return datetime.strptime(ts[:19], FMT).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return ts or ""


class ResultViewer(QDialog):
    """Affiche un cliché / compte rendu / résultat ; impression locale et enregistrement possibles."""
    def __init__(self, db, user_id, result_id, cfg=None, context="", parent=None):
        super().__init__(parent)
        self.cfg, self.context = cfg, context
        r = db.get_result(result_id, user_id)
        self.setWindowTitle("Résultat — " + (r.get("filename") or "compte rendu")); self.resize(760, 760)
        v = QVBoxLayout(self)
        self.data = base64.b64decode(r["data_b64"]) if r.get("data_b64") else None
        self.mime, self.name, self.text = r.get("mime") or "", r.get("filename") or "resultat", r.get("report_text") or ""
        self.pix = None
        if self.data and self.mime.startswith("image/"):
            self.pix = QPixmap(); self.pix.loadFromData(self.data)
            lab = QLabel(); lab.setPixmap(self.pix.scaledToWidth(700, Qt.TransformationMode.SmoothTransformation))
            sc = QScrollArea(); sc.setWidget(lab); v.addWidget(sc, 3)
        elif self.data:
            v.addWidget(QLabel(f"📄 {self.name} ({len(self.data) // 1024} Ko) — ouvert avec la visionneuse du système."))
        t = QTextEdit(); t.setReadOnly(True); t.setPlainText(self.text or "(pas de compte rendu saisi)"); v.addWidget(t, 1)
        row = QHBoxLayout()
        if self.data and not self.mime.startswith("image/"):
            b = QPushButton("📂 Ouvrir"); b.clicked.connect(self.open_external); row.addWidget(b)
        if cfg is not None:
            b = QPushButton("🖨 Imprimer"); b.clicked.connect(self.print_it); row.addWidget(b)
        b = QPushButton("💾 Enregistrer sous…"); b.clicked.connect(self.save_as); row.addWidget(b)
        v.addLayout(row)

    def open_external(self):
        p = os.path.join(tempfile.mkdtemp(prefix="dem_res_"), os.path.basename(self.name))
        with open(p, "wb") as f:
            f.write(self.data)
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def print_it(self):
        html, res = build_result(self.cfg, "RÉSULTAT D'EXAMEN", self.context, "", self.name, self.text, self.pix)
        print_document(self.cfg, html, res, "a4", "resultat_" + datetime.now().strftime("%H%M%S"))

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer", self.name)
        if path and self.data:
            with open(path, "wb") as f:
                f.write(self.data)
        elif path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text)


class PatientSearchDialog(QDialog):
    def __init__(self, db, user, cfg, parent=None):
        super().__init__(parent)
        self.db, self.user, self.cfg, self.groups = db, user, cfg, []
        self.setWindowTitle("Recherche & dossier patient (DPI)"); self.resize(1100, 700)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.q = QLineEdit(); self.q.setPlaceholderText("Nom, prénom, date de naissance (jj/mm/aaaa ou année) ou N° d'identification")
        go = QPushButton("🔎 Rechercher"); go.setObjectName("primary"); go.clicked.connect(self.search)
        self.q.returnPressed.connect(self.search)
        self.mine = QCheckBox("Mes consultations uniquement"); self.mine.setVisible(user["role"] == "medecin"); self.mine.toggled.connect(self._reload)
        top.addWidget(self.q, 1); top.addWidget(go); top.addWidget(self.mine); v.addLayout(top)
        sp = QSplitter(Qt.Orientation.Horizontal); v.addWidget(sp, 1)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Nom & Prénom", "Naissance", "Sexe", "N° identification", "Passages", "Dernier passage"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide(); self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._reload)
        sp.addWidget(self.table)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Historique du patient", ""]); self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self._open)
        sp.addWidget(self.tree); sp.setSizes([480, 620])
        self.hint = QLabel(""); v.addWidget(self.hint)
        self.hint.setTextFormat(Qt.TextFormat.PlainText)

    def search(self, *_):
        try:
            self.groups = self.db.search_patients(self.q.text(), self.user["id"])
        except (ConnectionError, PermissionError) as e:
            self.hint.setText(str(e)); return
        self.table.setRowCount(len(self.groups))
        for i, g in enumerate(self.groups):
            for j, t in enumerate((g["display"], g["birth"], "H" if g["gender"] == "H" else "F", g["ident"], str(g["visits"]), _fmt(g["last_visit"]))):
                self.table.setItem(i, j, QTableWidgetItem(t))
        self.hint.setText(f"{len(self.groups)} patient(s) trouvé(s)." + (" Double-clic sur une pièce jointe (📎) pour l'ouvrir." if self.groups else ""))
        self.tree.clear()

    def _reload(self, *_):
        r = self.table.currentRow()
        if not (0 <= r < len(self.groups)):
            return
        try:
            rec = self.db.patient_record(self.groups[r]["admission_id"], self.user["id"], self.cfg.get("station_name", ""))
        except (ConnectionError, PermissionError) as e:
            self.hint.setText(str(e)); return
        self.tree.clear()
        mine = self.mine.isChecked() and self.user["role"] == "medecin"
        for v in rec["visits"]:
            a = v["admission"]
            svc = SERVICE_BY_CODE.get(a["service_code"], {"icon": "", "name": a["service_code"]})
            node = QTreeWidgetItem([f"{_fmt(a['created_at'])} — {svc['icon']} {svc['name']} ({a['ticket_label']})", ""])
            if rec["level"] == "medecin":
                shown = False
                for c in v["consultations"]:
                    if mine and c["doctor_user_id"] != self.user["id"]:
                        continue
                    shown = True
                    n = QTreeWidgetItem(node, [f"🩺 Consultation — Dr {c['doc_last'] or ''} {c['doc_first'] or ''}", c.get("outcome") or "en cours"])
                    for lab, val in (("Diagnostic", c.get("diagnosis")), ("Observations", c.get("notes"))):
                        if val:
                            QTreeWidgetItem(n, [f"{lab} : {val}", ""])
                for rx in v["prescriptions"]:
                    if mine and rx["doctor_user_id"] != self.user["id"]:
                        continue
                    n = QTreeWidgetItem(node, [f"💊 Ordonnance n° {rx['number']}", rx["status"]])
                    for it in rx["items"]:
                        QTreeWidgetItem(n, [f"{it['drug']} — {it['dosage']} — {it['duration']}", ""])
                for l in v["lab_requests"]:
                    if mine and l["doctor_user_id"] != self.user["id"]:
                        continue
                    n = QTreeWidgetItem(node, [f"🧪 Analyses {l.get('ticket_label') or ''} : " + ", ".join(l["items"]), l["status"]])
                    self._results(n, "lab", l["id"], l.get("n_results"))
                for r_ in v["radiology"]:
                    if mine and r_["doctor_user_id"] != self.user["id"]:
                        continue
                    n = QTreeWidgetItem(node, [f"🩻 {r_['exam_type'] or 'Radiologie'} {r_['region'] or ''} {r_['side'] or ''} ({r_['ticket_label']})",
                                               RADIO_STATUS.get(r_["status"], r_["status"])])
                    self._results(n, "radio", r_["id"], r_.get("n_results"))
                if mine and not shown and not node.childCount():
                    continue
            self.tree.addTopLevelItem(node)
        self.tree.expandToDepth(0)
        if rec["level"] != "medecin":
            self.hint.setText("Accès limité (identité et passages) : le contenu médical est réservé aux médecins.")

    def _results(self, parent, kind, rid, n):
        if not n:
            return
        for res in self.db.list_results(kind, rid, self.user["id"]):
            it = QTreeWidgetItem(parent, [f"📎 {res['filename'] or 'Compte rendu'} — {_fmt(res['created_at'])}", ""])
            it.setData(0, Qt.ItemDataRole.UserRole, res["id"])

    def _open(self, item, _col):
        rid = item.data(0, Qt.ItemDataRole.UserRole)
        if rid:
            top = item
            while top.parent():
                top = top.parent()
            ResultViewer(self.db, self.user["id"], rid, self.cfg, top.text(0), self).exec()
