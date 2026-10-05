"""Poste Manipulateur Radiologie : file LAN (demandes des médecins avec indications cliniques + inscriptions directes), appels,
envoi du cliché / compte rendu au médecin demandeur, impression locale, validation."""
import base64
from datetime import datetime

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                             QTextEdit, QVBoxLayout)

from archive import archive_reception
from database import FMT, age_from_row, display_name, parse_age_or_birth
from documents import build_result
from printer import print_document, print_ticket
from ui_common import BaseWindow, guard, open_tv
from ui_dpi import ResultViewer


class DirectDialog(QDialog):
    """Inscription directe d'un patient (venant de l'accueil ou se présentant directement)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inscription directe — Radiologie")
        f = QFormLayout(self)
        self.last, self.first, self.age, self.ident = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.age.setPlaceholderText("Âge ou jj/mm/aaaa"); self.ident.setPlaceholderText("facultatif")
        self.gender = QComboBox(); self.gender.addItem("Homme", "H"); self.gender.addItem("Femme", "F")
        f.addRow("Nom :", self.last); f.addRow("Prénom :", self.first); f.addRow("Âge / naissance :", self.age)
        f.addRow("N° d'identification :", self.ident); f.addRow("Genre :", self.gender)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); f.addRow(bb)

    def _ok(self):
        if len(self.last.text().strip()) < 2 or not self.first.text().strip() or not parse_age_or_birth(self.age.text()):
            QMessageBox.warning(self, "Inscription", "Nom, prénom ou âge invalide."); return
        self.accept()


class SendResultDialog(QDialog):
    """Envoi d'un cliché numérique (image / PDF) et/ou d'un compte rendu vers la session du médecin demandeur."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(520, 420)
        self.filename = self.mime = self.data_b64 = None
        v = QVBoxLayout(self)
        b = QPushButton("📂 Joindre le cliché (image ou PDF)…"); b.clicked.connect(self.pick); v.addWidget(b)
        self.lbl = QLabel("Aucun fichier joint."); v.addWidget(self.lbl)
        self.prev = QLabel(); self.prev.setAlignment(Qt.AlignmentFlag.AlignCenter); v.addWidget(self.prev)
        self.text = QTextEdit(); self.text.setPlaceholderText("Compte rendu / conclusion (facultatif si un fichier est joint)"); v.addWidget(self.text, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("📤 Envoyer au médecin")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); v.addWidget(bb)

    def pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cliché", "", "Clichés (*.png *.jpg *.jpeg *.bmp *.pdf)")
        if not path:
            return
        name = path.replace("\\", "/").split("/")[-1]
        if path.lower().endswith(".pdf"):
            with open(path, "rb") as f:
                raw = f.read()
            self.mime, self.prev_pix = "application/pdf", None
            self.prev.setText("📄 PDF")
        else:
            img = QImage(path)
            if img.isNull():
                return QMessageBox.warning(self, "Cliché", "Image illisible.")
            if max(img.width(), img.height()) > 2200:                                 # allègement pour le réseau local
                img = img.scaled(2200, 2200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, "JPEG", 88); raw = bytes(ba); self.mime = "image/jpeg"
            self.prev.setPixmap(QPixmap.fromImage(img).scaledToHeight(150, Qt.TransformationMode.SmoothTransformation))
            name = name.rsplit(".", 1)[0] + ".jpg"
        if len(raw) > 8_500_000:
            return QMessageBox.warning(self, "Cliché", "Fichier trop volumineux (maximum ≈ 8 Mo).")
        self.filename, self.data_b64 = name, base64.b64encode(raw).decode()
        self.lbl.setText(f"📎 {name} ({len(raw) // 1024} Ko)")


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
    def __init__(self, cfg, db):
        super().__init__(cfg, db)
        self.current, self._known, self._awaiting, self._pending = None, None, [], []
        b = QPushButton("➕ Inscription directe"); b.clicked.connect(self.direct); self.header_extra.addWidget(b)
        if cfg.get("tv_screen"):
            b = QPushButton("📺 Ouvrir l'écran TV"); b.clicked.connect(lambda *_: open_tv(self.cfg)); self.header_extra.addWidget(b)
        body = QHBoxLayout(); self.content.addLayout(body, 1)

        left = QFrame(); left.setObjectName("card"); lv = QVBoxLayout(left)
        t = QLabel("File d'attente Radiologie (réseau local)"); t.setStyleSheet("font-size:18px;font-weight:700;")
        self.count = QLabel(); self.count.setStyleSheet("color:#8b97a7;")
        self.queue = _table(["Passage", "Patient", "Examen", "Région / côté", "Médecin", "Origine", "Attente"])
        self.queue.itemSelectionChanged.connect(self.show_details)
        self.details = QLabel("Sélectionnez une demande pour lire les indications cliniques."); self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setStyleSheet("background:#0e141b;border:1px solid #2c3644;border-radius:8px;padding:8px;")
        self.awaiting = _table(["Passage", "Patient", "Examen", "Depuis"]); self.awaiting.setMaximumHeight(130)
        bt = QPushButton("✔ Tirage remis (marquer Terminé)"); bt.clicked.connect(self.print_done)
        for x in (t, self.count, self.queue, self.details, QLabel("🖼 En attente de tirage"), self.awaiting, bt):
            lv.addWidget(x)
        body.addWidget(left, 3)

        right = QFrame(); right.setObjectName("card"); rv = QVBoxLayout(right)
        h = QLabel("Patient en salle d'examen"); h.setStyleSheet("font-size:18px;font-weight:700;")
        self.cur_ticket = QLabel("—"); self.cur_ticket.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_ticket.setStyleSheet("font-size:54px;font-weight:800;")
        self.cur_info = QLabel("Aucun patient appelé"); self.cur_info.setWordWrap(True); self.cur_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cur_info.setTextFormat(Qt.TextFormat.PlainText)
        self.note = QLineEdit(); self.note.setPlaceholderText("Remarque pour le médecin (facultatif)")
        nxt = QPushButton("📣  Appeler le patient suivant   (Espace)"); nxt.setObjectName("primary"); nxt.clicked.connect(self.call_next)
        rec = QPushButton("🔁 Rappeler"); rec.clicked.connect(self.recall)
        snd = QPushButton("📎 Envoyer le cliché / compte rendu au médecin"); snd.clicked.connect(self.send_result)
        prt = QPushButton("🖨 Imprimer le cliché / compte rendu (patient)"); prt.clicked.connect(self.print_result)
        ok = QPushButton("✅ Examen terminé"); ok.clicked.connect(lambda *_: self.validate("DONE"))
        pr = QPushButton("🖼 En attente de tirage"); pr.clicked.connect(lambda *_: self.validate("AWAITING_PRINT"))
        for x in (h, self.cur_ticket, self.cur_info, self.note, nxt, rec, snd, prt, ok, pr):
            rv.addWidget(x)
        rv.addStretch()
        body.addWidget(right, 2)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.call_next)
        self.t = QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(2000)   # quasi temps réel (2 s)

    def on_login(self):
        self._known = None
        self.refresh()

    @staticmethod
    def _detail(r):
        return (f"{display_name(r)} — {age_from_row(r)} ans\n{r['exam_type'] or 'Inscription directe'} {r['region'] or ''} {r['side'] or ''}\n"
                f"Indications cliniques : {r['clinical_info'] or '—'}\nConsignes du médecin : {r['instructions'] or '—'}"
                + (f"\nDr {r['doc_last']} {r['doc_first'] or ''}" if r.get("doc_last") else ""))

    def show_details(self, *_):
        r = self.queue.currentRow()
        if 0 <= r < len(self._pending):
            self.details.setText(self._detail(self._pending[r]))

    @guard
    def refresh(self, *_):
        if not self.user:
            return
        sel = self.queue.currentRow()
        rows = self.db.radio_queue(self.user["id"])
        if self._banner_kind == "error":
            self.hide_banner()
        pend = [r for r in rows if r["status"] == "PENDING"]
        mine = [r for r in rows if r["status"] == "CALLED" and r["called_by"] == self.station]
        ids = {r["id"] for r in pend}
        if self._known is not None:           # notification visuelle + sonore des NOUVELLES demandes
            new = [r for r in pend if r["id"] not in self._known]
            if new:
                r = new[0]
                self.show_banner(f"📨 Nouvelle demande de radiologie : {r['ticket_label']} — {display_name(r)} ({r['exam_type'] or 'inscription directe'} "
                                 f"{r['region'] or ''})" + (" 🚨 URGENT" if r["urgent"] else ""), ms=8000)
                QApplication.beep()
        self._known = (self._known or set()) | ids
        self.current, self._pending = (mine[0] if mine else None), pend
        self.count.setText(f"{len(pend)} patient(s) en attente")
        self.queue.setRowCount(len(pend))
        for i, r in enumerate(pend):
            wait = int((datetime.now() - datetime.strptime(r["created_at"], FMT)).total_seconds() // 60)
            doc = f"Dr {r['doc_last']}" if r.get("doc_last") else "—"
            cells = [("🚨 " if r["urgent"] else "") + r["ticket_label"], display_name(r), r["exam_type"] or "—",
                     f"{r['region'] or ''} / {r['side'] or ''}".strip(" /"), doc, "Médecin" if r["source"] == "MEDECIN" else "Accueil / direct", f"{wait} min"]
            for j, txt in enumerate(cells):
                it = QTableWidgetItem(txt); it.setData(Qt.ItemDataRole.UserRole, r["id"])
                if r["urgent"]:
                    it.setBackground(QColor(231, 76, 60, 90))
                self.queue.setItem(i, j, it)
        if 0 <= sel < len(pend):
            self.queue.selectRow(sel)
        self._awaiting = self.db.radio_awaiting(self.user["id"])
        self.awaiting.setRowCount(len(self._awaiting))
        for i, r in enumerate(self._awaiting):
            for j, txt in enumerate((r["ticket_label"], display_name(r), r["exam_type"] or "—", r["done_at"] or "")):
                self.awaiting.setItem(i, j, QTableWidgetItem(txt))
        c = self.current
        self.cur_ticket.setText(c["ticket_label"] if c else "—")
        self.cur_info.setText(self._detail(c) if c else "Aucun patient appelé")

    @guard
    def call_next(self, *_):
        if not self.user:
            return
        row = self.db.radio_call_next(self.station, self.user["id"], self.room)   # l'écran concerné reçoit l'appel (service_id = RAD)
        if not row:
            return self.show_banner("Aucune demande en attente.")
        self.hide_banner(); QApplication.beep(); self.refresh()

    @guard
    def recall(self, *_):
        if self.current:
            self.db.radio_recall(self.current["id"], self.station, self.user["id"], self.room)

    def _target(self):
        """Examen visé : patient appelé, sinon ligne sélectionnée dans la liste « en attente de tirage »."""
        if self.current:
            return self.current
        r = self.awaiting.currentRow()
        return self._awaiting[r] if 0 <= r < len(self._awaiting) else None

    @guard
    def send_result(self, *_):
        t = self._target()
        if not t:
            return self.show_banner("Appelez un patient (ou sélectionnez un examen en attente de tirage).", "error")
        d = SendResultDialog(f"Envoyer au médecin — {t['ticket_label']}", self)
        if d.exec():
            self.db.add_result("radio", t["id"], d.filename, d.mime, d.data_b64, d.text.toPlainText(), self.user["id"])
            self.show_banner("📤 Résultat envoyé à la session du médecin demandeur." if t["source"] == "MEDECIN" else "📎 Résultat enregistré (inscription directe).")

    @guard
    def print_result(self, *_):
        t = self._target()
        if not t:
            return self.show_banner("Appelez un patient (ou sélectionnez un examen en attente de tirage).", "error")
        res = self.db.list_results("radio", t["id"], self.user["id"])
        if not res:
            return self.show_banner("Aucun cliché / compte rendu enregistré : utilisez d'abord « Envoyer ».", "error")
        r = self.db.get_result(res[-1]["id"], self.user["id"])
        pix = None
        if r.get("data_b64") and (r.get("mime") or "").startswith("image/"):
            pix = QPixmap(); pix.loadFromData(base64.b64decode(r["data_b64"]))
        html, resources = build_result(self.cfg, "CLICHÉ / COMPTE RENDU RADIOLOGIQUE", display_name(t), t["ticket_label"],
                                       f"{t['exam_type'] or ''} {t['region'] or ''} {t['side'] or ''}".strip(), r.get("report_text") or "", pix)
        ok, msg = print_document(self.cfg, html, resources, "a4", "cliche_" + t["ticket_label"])
        self.show_banner("Impression : " + msg, "info" if ok else "error")

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
        row = self.db.add_admission({"last_name": d.last.text(), "first_name": d.first.text(), "parsed": parse_age_or_birth(d.age.text()),
                                     "gender": d.gender.currentData(), "service_code": "RAD", "ident": d.ident.text().strip(),
                                     "user_id": self.user["id"]}, self.station)
        ok, msg = print_ticket(self.cfg, row)
        try:
            archive_reception(row)
        except OSError:
            pass
        self.refresh()
        self.show_banner(f"Patient inscrit — numéro de passage {row['ticket_label']}" + ("" if ok else f" (impression : {msg})"), "info" if ok else "error")
