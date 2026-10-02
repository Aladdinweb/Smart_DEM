"""Formulaire Structure + Rôle (réutilisé par l'assistant de premier lancement et les Paramètres)."""
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QGroupBox,
                             QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget)

from data_structures import SERVICES, TYPES, WILAYAS, parents, structures


def _combo(items=(), editable=False):
    c = QComboBox(); c.setEditable(editable); c.addItems(items); return c


class StructureRoleForm(QWidget):
    def __init__(self, cfg):
        super().__init__()
        lay = QVBoxLayout(self)
        g = QGroupBox("Structure de santé"); form = QFormLayout(g)
        self.wilaya = _combo(WILAYAS, True)
        self.type = _combo(TYPES)
        self.parent_ = _combo((), True)
        self.structure = _combo((), True)
        form.addRow("Wilaya :", self.wilaya)
        form.addRow("Type d'établissement :", self.type)
        form.addRow("Établissement parent :", self.parent_)
        form.addRow("Structure / Polyclinique :", self.structure)
        lay.addWidget(g)
        self.wilaya.currentTextChanged.connect(self._fill_parents)
        self.type.currentTextChanged.connect(self._fill_parents)
        self.parent_.currentTextChanged.connect(self._fill_structures)

        r = QGroupBox("Rôle du poste"); rl = QVBoxLayout(r)
        self.rb = {"accueil": QRadioButton("Accueil Général — tous les services + tri médical"),
                   "dedie": QRadioButton("Poste Dédié — un ou plusieurs services (cases à cocher)"),
                   "medecin": QRadioButton("Poste Médecin — appel et gestion des consultations")}
        grp = QButtonGroup(self)
        for k, b in self.rb.items():
            grp.addButton(b); rl.addWidget(b); b.toggled.connect(self._role_changed)
        lay.addWidget(r)

        self.svc_box = QGroupBox("Services du poste (cocher un ou plusieurs)")
        sg = QGridLayout(self.svc_box)
        self.checks = {}
        for i, s in enumerate(SERVICES):
            cb = QCheckBox(f"{s['icon']}  {s['name']}"); self.checks[s["code"]] = cb
            sg.addWidget(cb, i // 2, i % 2)
        lay.addWidget(self.svc_box)
        self.load(cfg)

    def _fill_parents(self, *_):
        cur = self.parent_.currentText()
        self.parent_.blockSignals(True); self.parent_.clear()
        self.parent_.addItems(parents(self.wilaya.currentText(), self.type.currentText()))
        self.parent_.setCurrentText(cur if cur else (self.parent_.itemText(0) if self.parent_.count() else ""))
        self.parent_.blockSignals(False)
        self._fill_structures()

    def _fill_structures(self, *_):
        self.structure.clear()
        self.structure.addItems(structures(self.wilaya.currentText(), self.type.currentText(), self.parent_.currentText()))

    def _role_changed(self, *_):
        self.svc_box.setVisible(not self.rb["accueil"].isChecked())

    def load(self, cfg):
        self.wilaya.setCurrentText(cfg.get("wilaya", "31 - Oran"))
        self.type.setCurrentText(cfg.get("type", "EPSP"))
        self._fill_parents()
        if cfg.get("parent"): self.parent_.setCurrentText(cfg.get("parent"))
        self._fill_structures()
        if cfg.get("structure"): self.structure.setCurrentText(cfg.get("structure"))
        self.rb.get(cfg.get("role", "accueil"), self.rb["accueil"]).setChecked(True)
        for code, cb in self.checks.items():
            cb.setChecked(code in cfg.get("services", []))
        self._role_changed()

    def values(self):
        role = next(k for k, b in self.rb.items() if b.isChecked())
        return {"wilaya": self.wilaya.currentText().strip(), "type": self.type.currentText(),
                "parent": self.parent_.currentText().strip(), "structure": self.structure.currentText().strip(),
                "role": role, "services": [c for c, cb in self.checks.items() if cb.isChecked()] if role != "accueil" else []}

    def validate(self):
        v = self.values()
        if not (v["wilaya"] and v["parent"] and v["structure"]):
            return "Renseignez la wilaya, l'établissement parent et la structure."
        if v["role"] in ("dedie", "medecin") and not v["services"]:
            return "Cochez au moins un service pour ce poste."
        return None


class SetupDialog(QDialog):
    """Assistant de premier lancement."""
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("Smart DEM — Configuration du premier lancement")
        self.resize(720, 760)
        lay = QVBoxLayout(self)
        t = QLabel("Configuration du poste"); t.setStyleSheet("font-size:22px;font-weight:700;")
        lay.addWidget(t)
        self.form = StructureRoleForm(cfg)
        self.net = NetworkForm(cfg)
        wrap = QWidget(); wl = QVBoxLayout(wrap); wl.addWidget(self.form); wl.addWidget(self.net)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(wrap)
        lay.addWidget(sc, 1)
        g = QGroupBox("Sécurité & identification"); f = QFormLayout(g)
        self.station = QLineEdit(cfg.get("station_name", ""))
        self.pin1 = QLineEdit(); self.pin1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin2 = QLineEdit(); self.pin2.setEchoMode(QLineEdit.EchoMode.Password)
        f.addRow("Nom du poste :", self.station)
        f.addRow("Code PIN administrateur (4+ car.) :", self.pin1)
        f.addRow("Confirmer le code PIN :", self.pin2)
        lay.addWidget(g)
        ok = QPushButton("Terminer la configuration"); ok.setObjectName("primary"); ok.clicked.connect(self.finish)
        lay.addWidget(ok)

    def finish(self):
        err = self.form.validate() or self.net.validate()
        if not err and len(self.pin1.text()) < 4:
            err = "Le code PIN doit contenir au moins 4 caractères."
        if not err and self.pin1.text() != self.pin2.text():
            err = "Les deux codes PIN ne correspondent pas."
        if err:
            QMessageBox.warning(self, "Configuration", err); return
        self.cfg.update(self.form.values())
        self.cfg.update(self.net.values())
        self.cfg.set("station_name", self.station.text().strip() or self.cfg.get("station_name"))
        self.cfg.set_pin(self.pin1.text())
        self.cfg.set("configured", True)
        self.cfg.save()
        self.accept()


class NetworkForm(QGroupBox):
    """Mode réseau du poste : Autonome / Hub / Client (réutilisé par l'assistant et les Paramètres)."""
    MODES = [("Autonome — un seul poste", "local"), ("Hub — ce poste héberge la base, le serveur et l'écran TV", "hub"),
             ("Client — se connecte à un Hub du réseau local", "client")]

    def __init__(self, cfg):
        super().__init__("Réseau local (LAN, sans internet)")
        from PyQt6.QtWidgets import QSpinBox
        self.f = QFormLayout(self)
        self.mode = QComboBox()
        for label, code in self.MODES:
            self.mode.addItem(label, code)
        self.mode.setCurrentIndex(max(0, self.mode.findData(cfg.get("net_mode", "local"))))
        self.host = QLineEdit(cfg.get("hub_host", ""))
        self.host.setPlaceholderText("IP du poste Hub, ex : 192.168.1.10")
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(int(cfg.get("hub_port", 5000)))
        self.token = QLineEdit(cfg.get("lan_token", ""))
        self.info = QLabel(); self.info.setWordWrap(True); self.info.setStyleSheet("color:#8b97a7;")
        self.f.addRow("Mode :", self.mode)
        self.f.addRow("Adresse du Hub :", self.host)
        self.f.addRow("Port :", self.port)
        self.f.addRow("Jeton réseau :", self.token)
        self.f.addRow(self.info)
        self.mode.currentIndexChanged.connect(self._sync)
        self.port.valueChanged.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        m = self.mode.currentData()
        for w, show in ((self.host, m == "client"), (self.port, m != "local"), (self.token, m != "local")):
            w.setVisible(show); self.f.labelForField(w).setVisible(show)
        from config_manager import local_ip
        self.info.setText({"local": "", "client": "Saisissez l'adresse et le jeton affichés dans les paramètres du poste Hub.",
                           "hub": f"Écran TV : http://{local_ip()}:{self.port.value()}/tv  (à ouvrir dans le navigateur de la TV).\n"
                                  "Autorisez Smart DEM dans le pare-feu Windows si demandé. Le jeton ci-dessus est à saisir sur les postes clients."}[m])
        self.info.setVisible(bool(self.info.text()))

    def values(self):
        import secrets
        m = self.mode.currentData()
        token = self.token.text().strip()
        if m == "hub" and not token:
            token = secrets.token_urlsafe(9)
            self.token.setText(token)
        return {"net_mode": m, "hub_host": self.host.text().strip(), "hub_port": self.port.value(), "lan_token": token}

    def validate(self):
        if self.mode.currentData() == "client" and not (self.host.text().strip() and self.token.text().strip()):
            return "Mode Client : renseignez l'adresse du Hub et le jeton réseau."
        return None
