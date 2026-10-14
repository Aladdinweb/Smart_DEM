"""Messagerie interne poste à poste (v1.4.0) : signalements des agents vers les coordinateurs, convocations des coordinateurs vers les agents,
accusés de réception et réponses. Les messages s'affichent UNIQUEMENT sur les ordinateurs des agents, jamais sur les écrans TV."""
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
                             QTextEdit, QVBoxLayout, QWidget)

from database import FMT

KIND = {"CONVOCATION": "📣 Convocation", "SIGNALEMENT": "🚩 Signalement", "REPONSE": "↩ Réponse"}


def fmt_ts(ts):
    try:
        return datetime.strptime(ts[:19], FMT).strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return ts or ""


def describe(m):
    """Texte complet d'un message : horodatage, émetteur, service émetteur, motif, détail."""
    lines = [f"{KIND.get(m['kind'], m['kind'])}{'  —  URGENT' if m.get('priority') == 'URGENT' else ''}",
             f"Date : {fmt_ts(m['created_at'])}", f"De : {m['from_name']} ({m.get('from_function') or ''})", f"Service émetteur : {m.get('from_service') or ''}",
             f"Motif : {m['reason']}"]
    if m.get("body"):
        lines += ["", m["body"]]
    return "\n".join(lines)


class ComposeDialog(QDialog):
    """Nouveau signalement (agent) / nouvelle convocation (coordinateur) / réponse."""
    def __init__(self, db, user, parent=None, reply_to=None):
        super().__init__(parent)
        self.reply_to = reply_to
        rec = db.message_recipients(user["id"])
        self.coordinator = rec["coordinator"]
        self.setWindowTitle("Réponse" if reply_to else ("Nouvelle convocation" if self.coordinator else "Nouveau signalement")); self.resize(520, 560)
        v = QVBoxLayout(self)
        self.lst = self.combo = None
        if reply_to:
            v.addWidget(QLabel(f"Réponse à {reply_to['from_name']} — « {reply_to['reason']} »"))
        elif self.coordinator:
            v.addWidget(QLabel("Agents à convoquer (cochez un ou plusieurs) :"))
            self.filter = QLineEdit(); self.filter.setPlaceholderText("Filtrer par nom, fonction ou service…"); self.filter.textChanged.connect(self._filter)
            self.lst = QListWidget()
            for u in rec["users"]:
                it = QListWidgetItem(f"{u['label']}  ·  {u['space']}"); it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable); it.setCheckState(Qt.CheckState.Unchecked)
                it.setData(Qt.ItemDataRole.UserRole, u["id"]); self.lst.addItem(it)
            v.addWidget(self.filter); v.addWidget(self.lst, 1)
        else:
            v.addWidget(QLabel("Destinataire :"))
            self.combo = QComboBox()
            for g in rec["groups"]:
                self.combo.addItem(f"👥 {g['label']}" + ("" if g["members"] else "  (aucun compte actif)"), ("g", g["key"]))
            for u in rec["users"]:
                self.combo.addItem(f"👤 {u['label']}", ("u", u["id"]))
            v.addWidget(self.combo)
        f = QFormLayout()
        self.reason = QLineEdit(); self.reason.setMaxLength(200); self.reason.setPlaceholderText("Motif (obligatoire)")
        self.body = QTextEdit(); self.body.setPlaceholderText("Détail (facultatif) — évitez d'y mettre des informations médicales nominatives"); self.body.setFixedHeight(110)
        self.urgent = QCheckBox("Urgent")
        f.addRow("Motif :", self.reason); f.addRow("Détail :", self.body); f.addRow("", self.urgent)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel); send = bb.addButton("📨 Envoyer", QDialogButtonBox.ButtonRole.AcceptRole)
        send.setObjectName("primary"); bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); v.addWidget(bb)

    def _filter(self, text):
        t = text.lower().strip()
        for i in range(self.lst.count()):
            self.lst.item(i).setHidden(bool(t) and t not in self.lst.item(i).text().lower())

    def _ok(self):
        if not self.reason.text().strip():
            return QMessageBox.warning(self, "Message", "Le motif est obligatoire.")
        if self.lst is not None and not self.values().get("to_user_ids"):
            return QMessageBox.warning(self, "Convocation", "Cochez au moins un agent.")
        self.accept()

    def values(self):
        d = {"reason": self.reason.text(), "body": self.body.toPlainText(), "priority": "URGENT" if self.urgent.isChecked() else "NORMAL"}
        if self.reply_to:
            d["reply_to"] = self.reply_to["id"]
        elif self.lst is not None:
            d["to_user_ids"] = [self.lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lst.count()) if self.lst.item(i).checkState() == Qt.CheckState.Checked]
        else:
            kind, val = self.combo.currentData()
            d["to_group" if kind == "g" else "to_user_ids"] = val if kind == "g" else [val]
        return d


def _tbl(headers):
    t = QTableWidget(0, len(headers)); t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); t.verticalHeader().hide()
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); t.horizontalHeader().setStretchLastSection(True)
    return t


class MessagesDialog(QDialog):
    def __init__(self, db, user, station="", parent=None):
        super().__init__(parent)
        self.db, self.user, self.station, self.inbox_rows, self.out_rows = db, user, station, [], []
        self.setWindowTitle("✉ Messagerie interne"); self.resize(1000, 640)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        coord = db.message_recipients(user["id"])["coordinator"]
        new = QPushButton("📣 Nouvelle convocation" if coord else "🚩 Nouveau signalement"); new.setObjectName("primary"); new.clicked.connect(self.compose)
        self.info = QLabel(""); self.info.setWordWrap(True)
        top.addWidget(new); top.addWidget(self.info, 1); v.addLayout(top)
        self.tabs = QTabWidget(); v.addWidget(self.tabs, 1)
        w1 = QSplitter(Qt.Orientation.Vertical)
        self.t_in = _tbl(["Date", "Type", "De", "Service émetteur", "Motif", "État"]); self.t_in.itemSelectionChanged.connect(self._show_in)
        self.detail = QTextEdit(); self.detail.setReadOnly(True)
        row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0)
        self.b_ack = QPushButton("✔ Accusé de réception"); self.b_ack.clicked.connect(self.ack)
        self.b_reply = QPushButton("↩ Répondre"); self.b_reply.clicked.connect(self.reply)
        rl.addWidget(self.b_ack); rl.addWidget(self.b_reply); rl.addStretch()
        lower = QWidget(); ll = QVBoxLayout(lower); ll.setContentsMargins(0, 0, 0, 0); ll.addWidget(self.detail, 1); ll.addWidget(row)
        w1.addWidget(self.t_in); w1.addWidget(lower); w1.setSizes([320, 220])
        self.tabs.addTab(w1, "📥 Reçus")
        self.t_out = _tbl(["Date", "Type", "À", "Motif", "Lu", "Accusé"])
        self.tabs.addTab(self.t_out, "📤 Envoyés")
        self.t = QTimer(self); self.t.timeout.connect(self.refresh); self.t.start(5000)
        self.refresh()

    def _safe(self, fn, *a, **k):
        try:
            return fn(*a, **k)
        except (ConnectionError, PermissionError, ValueError) as e:
            self.info.setText(f"⚠ {e}"); return None

    def refresh(self, *_):
        sel = self._cur()
        rows = self._safe(self.db.inbox, self.user["id"])
        out = self._safe(self.db.outbox, self.user["id"])
        if rows is None or out is None:
            return
        self.inbox_rows, self.out_rows = rows, out
        self.t_in.setRowCount(len(rows))
        bold = QFont(); bold.setBold(True)
        for i, m in enumerate(rows):
            state = "✔ Accusé" if m["ack_at"] else ("Lu" if m["read_at"] else "● Nouveau")
            for j, txt in enumerate((fmt_ts(m["created_at"]), KIND.get(m["kind"], m["kind"]) + (" 🔴" if m["priority"] == "URGENT" else ""),
                                     f"{m['from_name']} ({m.get('from_function') or ''})", m.get("from_service") or "", m["reason"], state)):
                it = QTableWidgetItem(txt)
                if not m["read_at"]:
                    it.setFont(bold)
                self.t_in.setItem(i, j, it)
        self.t_out.setRowCount(len(out))
        for i, m in enumerate(out):
            read = fmt_ts(m["read_at"]) if m["read_at"] else (f"{m['n_read']} lecteur(s)" if m["to_group"] else "—")
            for j, txt in enumerate((fmt_ts(m["created_at"]), KIND.get(m["kind"], m["kind"]), m["to_label"], m["reason"], read, fmt_ts(m["ack_at"]) if m["ack_at"] else "—")):
                self.t_out.setItem(i, j, QTableWidgetItem(txt))
        if sel is not None:
            for i, m in enumerate(rows):
                if m["id"] == sel["id"]:
                    self.t_in.selectRow(i); break

    def _cur(self):
        r = self.t_in.currentRow()
        return self.inbox_rows[r] if 0 <= r < len(self.inbox_rows) else None

    def _show_in(self):
        m = self._cur()
        self.b_ack.setEnabled(bool(m) and not m["ack_at"]); self.b_reply.setEnabled(bool(m))
        self.b_ack.setText("✔ Je me présente / Reçu" if m and m["kind"] == "CONVOCATION" else "✔ Accusé de réception")
        if not m:
            return self.detail.clear()
        self.detail.setPlainText(describe(m))
        if not m["read_at"] and self._safe(self.db.message_read, m["id"], self.user["id"]):
            m["read_at"] = datetime.now().strftime(FMT)

    def ack(self, *_):
        m = self._cur()
        if m and self._safe(self.db.message_ack, m["id"], self.user["id"]):
            self.refresh()

    def reply(self, *_):
        m = self._cur()
        if m:
            self._send(ComposeDialog(self.db, self.user, self, reply_to=m))

    def compose(self, *_):
        self._send(ComposeDialog(self.db, self.user, self))

    def _send(self, dlg):
        if dlg.exec():
            r = self._safe(self.db.send_message, dlg.values(), self.user["id"], self.station)
            if r:
                self.info.setText(f"✅ Message envoyé ({len(r)} destinataire(s))."); self.refresh(); self.tabs.setCurrentIndex(1)


class MessagePopup(QDialog):
    """Fenêtre non bloquante affichée sur le poste de l'agent à la réception d'une convocation / d'un message urgent."""
    def __init__(self, db, user, m, on_open, parent=None):
        super().__init__(parent)
        self.db, self.user, self.m, self.on_open = db, user, m, on_open
        self.setWindowTitle(KIND.get(m["kind"], "Message")); self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False); self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True); self.resize(460, 300)
        v = QVBoxLayout(self)
        h = QLabel(KIND.get(m["kind"], "Message") + ("  —  URGENT" if m["priority"] == "URGENT" else "")); h.setStyleSheet("font-size:20px;font-weight:800;")
        t = QLabel(describe(m).split("\n", 1)[1]); t.setWordWrap(True); t.setTextFormat(Qt.TextFormat.PlainText)
        v.addWidget(h); v.addWidget(t, 1)
        row = QHBoxLayout()
        ack = QPushButton("✔ Je me présente / Reçu" if m["kind"] == "CONVOCATION" else "✔ Reçu"); ack.setObjectName("primary"); ack.clicked.connect(self._ack)
        op = QPushButton("✉ Ouvrir la messagerie"); op.clicked.connect(self._open)
        cl = QPushButton("Fermer"); cl.clicked.connect(self.close)
        for b in (ack, op, cl):
            row.addWidget(b)
        v.addLayout(row)

    def _ack(self):
        try:
            self.db.message_ack(self.m["id"], self.user["id"])
        except (ConnectionError, PermissionError):
            pass
        self.close()

    def _open(self):
        self.close(); self.on_open()
