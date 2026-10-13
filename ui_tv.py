"""Pilotage des écrans TV : voix, annonce défilante, pause, bandeaux d'alerte/urgence temporisés, appariement par code court."""
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QSpinBox, QVBoxLayout)

LEVELS = [("ℹ️ Information", "INFO"), ("⚠️ Alerte", "ALERTE"), ("🚨 Urgence (clignotant + signal sonore)", "URGENCE")]


def _call(parent, fn, title="Écrans TV"):
    try:
        return fn(), True
    except (ConnectionError, PermissionError, ValueError) as e:
        QMessageBox.warning(parent, title, str(e))
        return None, False


class AnnounceDialog(QDialog):
    """Diffuse un bandeau d'alerte sur les écrans (accueil, coordinateurs, responsable des urgences)."""
    def __init__(self, db, user_id, parent=None):
        super().__init__(parent)
        self.db, self.uid = db, user_id
        self.setWindowTitle("Alerte sur les écrans TV"); self.resize(480, 240)
        f = QFormLayout(self)
        self.text = QLineEdit(); self.text.setMaxLength(200); self.text.setPlaceholderText("ex : Pause de 12h00 à 13h00 — Guichet fermé")
        self.level = QComboBox()
        for label, code in LEVELS:
            self.level.addItem(label, code)
        self.secs = QSpinBox(); self.secs.setRange(5, 3600); self.secs.setValue(60); self.secs.setSuffix(" s")
        b = QPushButton("📣 Diffuser"); b.setObjectName("primary"); b.clicked.connect(self.send)
        c = QPushButton("🧹 Retirer toutes les alertes"); c.clicked.connect(lambda *_: _call(self, lambda: self.db.tv_announce_clear("*", self.uid)))
        f.addRow("Message :", self.text); f.addRow("Niveau :", self.level); f.addRow("Durée d'affichage :", self.secs); f.addRow(b); f.addRow(c)

    def send(self, *_):
        _, ok = _call(self, lambda: self.db.tv_announce(self.text.text(), self.level.currentData(), self.secs.value(), self.uid))
        if ok:
            self.accept()


class TvControlDialog(QDialog):
    def __init__(self, db, user_id, parent=None):
        super().__init__(parent)
        self.db, self.uid = db, user_id
        self.setWindowTitle("Écrans TV — flux d'affichage"); self.resize(620, 560)
        v = QVBoxLayout(self)
        st = db.tv_state()
        g1 = QGroupBox("Affichage"); l1 = QVBoxLayout(g1)
        l1.addWidget(QLabel("Annonce défilante en bas des écrans (facultatif) :"))
        self.msg = QLineEdit(st["message"]); self.msg.setMaxLength(200); l1.addWidget(self.msg)
        self.pause = QCheckBox("⏸ Mettre l'affichage des appels en pause (les écrans montrent l'annonce)"); self.pause.setChecked(st["paused"]); l1.addWidget(self.pause)
        self.voice = QCheckBox("📢 Voix de l'appel active (le bip reste toujours actif)"); self.voice.setChecked(st.get("voice", True)); l1.addWidget(self.voice)
        row = QHBoxLayout()
        b = QPushButton("✅ Appliquer"); b.setObjectName("primary"); b.clicked.connect(self.apply)
        c = QPushButton("🧹 Effacer l'historique des appels"); c.clicked.connect(lambda *_: _call(self, lambda: self.db.tv_clear(self.uid)))
        a = QPushButton("🚨 Alerte / urgence…"); a.clicked.connect(lambda *_: AnnounceDialog(self.db, self.uid, self).exec())
        for x in (b, c, a):
            row.addWidget(x)
        l1.addLayout(row); v.addWidget(g1)
        g2 = QGroupBox("Appairer un écran (sans adresse IP)"); l2 = QVBoxLayout(g2)
        l2.addWidget(QLabel("1) Sur la TV, ouvrir  http://NOM-DU-PC-HUB:5000/tv  → un code « TV-0000 » s'affiche.\n2) Saisir ce code ici et choisir l'écran :"))
        r2 = QHBoxLayout()
        self.code = QLineEdit(); self.code.setPlaceholderText("TV-4092"); self.code.setMaxLength(8)
        self.screen = QComboBox()
        for s in db.tv_screens():
            self.screen.addItem(f"{s['name']}  [{s['id']}]  — " + (",".join(s["services"]) or "tous les services"), s["id"])
        pb = QPushButton("🔗 Appairer"); pb.clicked.connect(self.pair)
        r2.addWidget(self.code); r2.addWidget(self.screen, 1); r2.addWidget(pb); l2.addLayout(r2)
        self.pairs = QLabel(""); self.pairs.setWordWrap(True); l2.addWidget(self.pairs)
        ub = QPushButton("⛓ Délier tous les écrans appairés"); ub.clicked.connect(self.unpair_all); l2.addWidget(ub)
        v.addWidget(g2)
        self._pairs()

    def _pairs(self):
        p = self.db.tv_pairs()
        self.pairs.setText(f"{len(p)} écran(s) appairé(s) : " + ", ".join(f"{x['screen']} ({x['paired_at'][5:16]})" for x in p) if p else "Aucun écran appairé.")

    def apply(self, *_):
        _, ok = _call(self, lambda: (self.db.tv_set(self.msg.text(), self.pause.isChecked(), self.uid), self.db.tv_voice(self.voice.isChecked(), self.uid)))
        if ok:
            self.accept()

    def pair(self, *_):
        if not self.screen.count():
            return QMessageBox.warning(self, "Écrans TV", "Créez d'abord un écran (Paramètres › Réseau & Écrans TV).")
        _, ok = _call(self, lambda: self.db.tv_pair(self.code.text(), self.screen.currentData(), self.uid))
        if ok:
            QMessageBox.information(self, "Écrans TV", "Écran appairé : il affiche maintenant ses services.")
            self.code.clear(); self._pairs()

    def unpair_all(self, *_):
        for p in self.db.tv_pairs():
            _call(self, lambda t=p["token"]: self.db.tv_unpair(t, self.uid))
        self._pairs()
