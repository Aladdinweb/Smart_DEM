"""Connexion rapide par PIN à 4 chiffres, gestion des utilisateurs (admin) et profil (griffe, PIN)."""
import base64

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QAbstractItemView, QVBoxLayout, QCheckBox, QGridLayout as _G, QWidget)

from branding import HeaderBar
from data_structures import CONSULT_SERVICES, SERVICE_BY_CODE
from ui_common import USER_ROLE_LABELS, user_label

ROLE_CHOICES = [("Accueil", "accueil"), ("Médecin / spécialiste", "medecin"), ("Manipulateur radio", "radio"), ("Pharmacien", "pharmacie"), ("Laboratoire (secrétariat / technicien)", "labo")]


def admin_ok(cfg, parent, title="Code administrateur"):
    if not cfg.has_pin():
        return True
    pin, ok = QInputDialog.getText(parent, title, "Code PIN administrateur :", QLineEdit.EchoMode.Password)
    if ok and cfg.check_pin(pin):
        return True
    if ok:
        QMessageBox.warning(parent, title, "Code PIN incorrect.")
    return False


class LoginDialog(QDialog):
    def __init__(self, cfg, db, roles, parent=None):
        super().__init__(parent)
        self.cfg, self.db, self.roles = cfg, db, list(roles or [])
        self.user, self.quit_requested, self.pin = None, False, ""
        self.setWindowTitle("Connexion"); self.setModal(True); self.resize(560, 820)
        lay = QVBoxLayout(self)
        lay.addWidget(HeaderBar(cfg, 56))
        t = QLabel("Connexion — choisissez votre nom puis saisissez votre PIN")
        t.setStyleSheet("font-size:16px;font-weight:700;"); t.setWordWrap(True); lay.addWidget(t)
        self.users = QListWidget(); self.users.setMaximumHeight(190)
        self.users.itemSelectionChanged.connect(self._reset_pin)
        lay.addWidget(self.users)
        self.dots = QLabel("○ ○ ○ ○"); self.dots.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dots.setStyleSheet("font-size:30px;letter-spacing:6px;")
        self.msg = QLabel(""); self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg.setStyleSheet("color:#e74c3c;font-weight:600;"); self.msg.setWordWrap(True)
        lay.addWidget(self.dots); lay.addWidget(self.msg)
        pad = QGridLayout()
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "⌫"]
        for i, k in enumerate(keys):
            b = QPushButton(k); b.setMinimumHeight(54); b.setStyleSheet("font-size:20px;font-weight:700;")
            b.clicked.connect(lambda _=False, k=k: self._key(k))
            pad.addWidget(b, i // 3, i % 3)
        lay.addLayout(pad)
        row = QHBoxLayout()
        adm = QPushButton("👥 Gérer les utilisateurs (admin)"); adm.clicked.connect(self._manage)
        qt = QPushButton("⏻ Quitter (admin)"); qt.setObjectName("danger"); qt.clicked.connect(self._quit)
        row.addWidget(adm); row.addWidget(qt); lay.addLayout(row)
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)
        self._load()

    def reject(self):          # Échap ne doit pas contourner la connexion
        pass

    def _load(self):
        self.users.clear()
        try:
            users = self.db.list_users(roles=self.roles or None)
        except ConnectionError as e:
            self.msg.setText(str(e)); return
        for u in users:
            it = QListWidgetItem(f"{user_label(u)}   —   {USER_ROLE_LABELS.get(u['role'], '')}" + (f" ({u['specialty']})" if u["specialty"] else ""))
            it.setData(Qt.ItemDataRole.UserRole, u["id"])
            self.users.addItem(it)
        if self.users.count() == 1:
            self.users.setCurrentRow(0)
        elif not users:
            self.msg.setText("Aucun utilisateur pour ce poste : utilisez « Gérer les utilisateurs (admin) ».")

    def _reset_pin(self):
        self.pin = ""; self._dots()

    def _dots(self):
        self.dots.setText(" ".join("●" if i < len(self.pin) else "○" for i in range(4)))

    def _key(self, k):
        if k == "C":
            self.pin = ""
        elif k == "⌫":
            self.pin = self.pin[:-1]
        elif len(self.pin) < 4:
            if not self.users.currentItem():
                self.msg.setText("Sélectionnez d'abord votre nom."); return
            self.pin += k
        self._dots()
        if len(self.pin) == 4:
            self._submit()

    def keyPressEvent(self, e):
        if e.text().isdigit():
            self._key(e.text())
        elif e.key() == Qt.Key.Key_Backspace:
            self._key("⌫")

    def _submit(self):
        uid = self.users.currentItem().data(Qt.ItemDataRole.UserRole)
        try:
            res = self.db.verify_pin(uid, self.pin)
        except ConnectionError as e:
            self.msg.setText(str(e)); self._reset_pin(); return
        if res["ok"]:
            self.user = res["user"]
            self.accept()
        else:
            self.msg.setText(res["error"]); self._reset_pin()

    def _manage(self):
        if admin_ok(self.cfg, self):
            UsersDialog(self.db, self).exec()
            self._load()

    def _quit(self):
        if admin_ok(self.cfg, self, "Quitter l'application"):
            self.quit_requested = True
            super().reject()


class UserForm(QDialog):
    def __init__(self, user=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Utilisateur")
        f = QFormLayout(self)
        self.last = QLineEdit(user["last_name"] if user else ""); self.first = QLineEdit(user["first_name"] if user else "")
        self.role = QComboBox()
        for label, code in ROLE_CHOICES:
            self.role.addItem(label, code)
        self.spec = QLineEdit(user.get("specialty", "") if user else "")
        self.spec.setPlaceholderText("ex : Médecin généraliste, Pédiatre…")
        f.addRow("Nom :", self.last); f.addRow("Prénom :", self.first); f.addRow("Rôle :", self.role); f.addRow("Spécialité :", self.spec)
        self.svc_checks = {}
        self.svc_box = QWidget()
        g = _G(self.svc_box); g.setContentsMargins(0, 0, 0, 0)
        for i, code in enumerate(CONSULT_SERVICES):
            cb = QCheckBox(f"{SERVICE_BY_CODE[code]['icon']} {SERVICE_BY_CODE[code]['name']}".replace("&", "&&"))
            cb.setChecked(code in (user.get("services", []) if user else [])); self.svc_checks[code] = cb; g.addWidget(cb, i // 2, i % 2)
        f.addRow("Services pris en charge (file d'attente visible) :", self.svc_box)
        self.role.currentIndexChanged.connect(lambda *_: self.svc_box.setVisible(self.role.currentData() == "medecin"))
        self.pin1 = self.pin2 = None
        if user:
            self.role.setCurrentIndex(max(0, self.role.findData(user["role"])))
        else:
            self.pin1 = QLineEdit(); self.pin1.setEchoMode(QLineEdit.EchoMode.Password); self.pin1.setMaxLength(4)
            self.pin2 = QLineEdit(); self.pin2.setEchoMode(QLineEdit.EchoMode.Password); self.pin2.setMaxLength(4)
            f.addRow("PIN (4 chiffres) :", self.pin1); f.addRow("Confirmer :", self.pin2)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); f.addRow(bb)
        self.svc_box.setVisible(self.role.currentData() == "medecin")

    def services(self):
        return [c for c, cb in self.svc_checks.items() if cb.isChecked()] if self.role.currentData() == "medecin" else []

    def _ok(self):
        err = None
        if not self.last.text().strip() or not self.first.text().strip():
            err = "Nom et prénom obligatoires."
        elif self.role.currentData() == "medecin" and not self.services():
            err = "Cochez au moins un service pour un médecin / spécialiste (sa file d'attente)."
        elif self.pin1 is not None and (not self.pin1.text().isdigit() or len(self.pin1.text()) != 4 or self.pin1.text() != self.pin2.text()):
            err = "Le PIN doit contenir exactement 4 chiffres, confirmés à l'identique."
        if err:
            QMessageBox.warning(self, "Utilisateur", err)
        else:
            self.accept()


class UsersDialog(QDialog):
    """Administration des utilisateurs (accès protégé par le PIN administrateur)."""
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Utilisateurs"); self.resize(720, 520)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Nom", "Prénom", "Rôle", "Spécialité", "Services", "Actif"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for label, fn in (("➕ Ajouter", self.add), ("✏️ Modifier", self.edit), ("⛔ Activer / Désactiver", self.toggle),
                          ("🗑 Supprimer", self.delete), ("🔑 Réinitialiser le PIN", self.reset_pin)):
            b = QPushButton(label); b.clicked.connect(lambda _=False, fn=fn: fn()); row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.users = self.db.list_users(None, False)
        self.table.setRowCount(len(self.users))
        for i, u in enumerate(self.users):
            for j, v in enumerate((u["last_name"], u["first_name"], USER_ROLE_LABELS.get(u["role"], u["role"]),
                                   u["specialty"], ", ".join(u["services"]), "oui" if u["active"] else "non")):
                self.table.setItem(i, j, QTableWidgetItem(v))

    def _selected(self):
        r = self.table.currentRow()
        return self.users[r] if 0 <= r < len(self.users) else None

    def add(self):
        d = UserForm(None, self)
        if d.exec():
            try:
                self.db.create_user(d.last.text(), d.first.text(), d.role.currentData(), d.spec.text(), d.pin1.text(), d.services())
            except Exception as e:
                QMessageBox.warning(self, "Utilisateur", str(e))
            self.refresh()

    def edit(self):
        u = self._selected()
        if u:
            d = UserForm(u, self)
            if d.exec():
                self.db.update_user(u["id"], {"last_name": d.last.text(), "first_name": d.first.text(),
                                              "role": d.role.currentData(), "specialty": d.spec.text(), "services": d.services()})
                self.refresh()

    def toggle(self):
        u = self._selected()
        if u:
            self.db.update_user(u["id"], {"active": 0 if u["active"] else 1}); self.refresh()

    def delete(self):
        u = self._selected()
        if u and QMessageBox.question(self, "Supprimer", f"Supprimer définitivement le compte de {user_label(u)} ?") == QMessageBox.StandardButton.Yes:
            try:
                self.db.delete_user(u["id"])
            except Exception as e:
                QMessageBox.warning(self, "Suppression", str(e))
            self.refresh()

    def reset_pin(self):
        u = self._selected()
        if u:
            pin, ok = QInputDialog.getText(self, "Nouveau PIN", f"Nouveau PIN (4 chiffres) pour {user_label(u)} :", QLineEdit.EchoMode.Password)
            if ok:
                try:
                    self.db.reset_user_pin(u["id"], pin)
                except Exception as e:
                    QMessageBox.warning(self, "PIN", str(e))


class ProfileDialog(QDialog):
    """Profil de l'utilisateur connecté : griffe (cachet), signature (éditeur avec suppression du fond), changement de PIN."""
    def __init__(self, db, user, parent=None):
        super().__init__(parent)
        self.db, self.user = db, user
        self.setWindowTitle("Mon profil"); self.resize(520, 560)
        lay = QVBoxLayout(self)
        t = QLabel(f"{user_label(user)}\n{user.get('specialty', '')}"); t.setStyleSheet("font-weight:700;"); t.setTextFormat(Qt.TextFormat.PlainText); lay.addWidget(t)
        self.previews = {}
        for kind, label in (("griffe", "Griffe / cachet"), ("signature", "Signature")):
            lay.addWidget(QLabel(f"{label} (imprimée sur ordonnances et demandes, PNG transparent) :"))
            pv = QLabel(); pv.setMinimumHeight(110); pv.setAlignment(Qt.AlignmentFlag.AlignCenter); pv.setStyleSheet("background:white;border:1px dashed #888;")
            self.previews[kind] = pv; lay.addWidget(pv)
            row = QHBoxLayout()
            bi = QPushButton("✂️ Importer / retoucher…"); bi.clicked.connect(lambda _=False, k=kind, l=label: self.edit(k, l))
            br = QPushButton("🗑 Retirer"); br.clicked.connect(lambda _=False, k=kind: self.remove(k))
            row.addWidget(bi); row.addWidget(br); lay.addLayout(row)
        bp = QPushButton("🔑 Changer mon PIN"); bp.clicked.connect(self.change_pin); lay.addWidget(bp)
        self._show()

    def _show(self):
        u = self.db.get_user(self.user["id"]) or {}
        for kind, col in (("griffe", "signature_b64"), ("signature", "sign_b64")):
            pix = QPixmap()
            if u.get(col):
                pix.loadFromData(base64.b64decode(u[col]))
            pv = self.previews[kind]
            pv.setPixmap(pix.scaledToHeight(100, Qt.TransformationMode.SmoothTransformation)) if not pix.isNull() else pv.setText("Aucune image")

    def edit(self, kind, label):
        from ui_sigeditor import SignatureEditor
        dlg = SignatureEditor(label, self)
        if dlg.exec() and dlg.result_png:
            self.db.set_user_image(self.user["id"], kind, base64.b64encode(dlg.result_png).decode())
            self._show()

    def remove(self, kind):
        self.db.set_user_image(self.user["id"], kind, ""); self._show()

    def change_pin(self):
        old, ok = QInputDialog.getText(self, "Changer le PIN", "PIN actuel :", QLineEdit.EchoMode.Password)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, "Changer le PIN", "Nouveau PIN (4 chiffres) :", QLineEdit.EchoMode.Password)
        if not ok:
            return
        try:
            res = self.db.change_own_pin(self.user["id"], old, new)
        except Exception as e:
            return QMessageBox.warning(self, "PIN", str(e))
        QMessageBox.information(self, "PIN", "PIN modifié." if res["ok"] else res["error"])
