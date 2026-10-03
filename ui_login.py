"""Connexion rapide par PIN à 4 chiffres, gestion des utilisateurs (admin) et profil (griffe, PIN)."""
import base64

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QAbstractItemView, QVBoxLayout)

from branding import HeaderBar
from ui_common import USER_ROLE_LABELS, user_label

ROLE_CHOICES = [("Accueil", "accueil"), ("Médecin", "medecin"), ("Manipulateur radio", "radio"), ("Pharmacien", "pharmacie")]


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
        self.cfg, self.db, self.roles = cfg, db, list(roles)
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
            it = QListWidgetItem(f"{user_label(u)}   —   {USER_ROLE_LABELS.get(u['role'], '')}")
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
        self.pin1 = self.pin2 = None
        if user:
            self.role.setCurrentIndex(max(0, self.role.findData(user["role"])))
        else:
            self.pin1 = QLineEdit(); self.pin1.setEchoMode(QLineEdit.EchoMode.Password); self.pin1.setMaxLength(4)
            self.pin2 = QLineEdit(); self.pin2.setEchoMode(QLineEdit.EchoMode.Password); self.pin2.setMaxLength(4)
            f.addRow("PIN (4 chiffres) :", self.pin1); f.addRow("Confirmer :", self.pin2)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); f.addRow(bb)

    def _ok(self):
        err = None
        if not self.last.text().strip() or not self.first.text().strip():
            err = "Nom et prénom obligatoires."
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
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Nom", "Prénom", "Rôle", "Spécialité", "Actif"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for label, fn in (("➕ Ajouter", self.add), ("✏️ Modifier", self.edit), ("⛔ Activer / Désactiver", self.toggle),
                          ("🔑 Réinitialiser le PIN", self.reset_pin)):
            b = QPushButton(label); b.clicked.connect(lambda _=False, fn=fn: fn()); row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.users = self.db.list_users(None, False)
        self.table.setRowCount(len(self.users))
        for i, u in enumerate(self.users):
            for j, v in enumerate((u["last_name"], u["first_name"], USER_ROLE_LABELS.get(u["role"], u["role"]),
                                   u["specialty"], "oui" if u["active"] else "non")):
                self.table.setItem(i, j, QTableWidgetItem(v))

    def _selected(self):
        r = self.table.currentRow()
        return self.users[r] if 0 <= r < len(self.users) else None

    def add(self):
        d = UserForm(None, self)
        if d.exec():
            try:
                self.db.create_user(d.last.text(), d.first.text(), d.role.currentData(), d.spec.text(), d.pin1.text())
            except Exception as e:
                QMessageBox.warning(self, "Utilisateur", str(e))
            self.refresh()

    def edit(self):
        u = self._selected()
        if u:
            d = UserForm(u, self)
            if d.exec():
                self.db.update_user(u["id"], {"last_name": d.last.text(), "first_name": d.first.text(),
                                              "role": d.role.currentData(), "specialty": d.spec.text()})
                self.refresh()

    def toggle(self):
        u = self._selected()
        if u:
            self.db.update_user(u["id"], {"active": 0 if u["active"] else 1}); self.refresh()

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
    """Profil de l'utilisateur connecté : griffe / tampon (PNG transparent) et changement de PIN."""
    def __init__(self, db, user, parent=None):
        super().__init__(parent)
        self.db, self.user = db, user
        self.setWindowTitle("Mon profil"); self.resize(480, 480)
        lay = QVBoxLayout(self)
        t = QLabel(f"<b>{user_label(user)}</b><br>{user.get('specialty', '')}"); lay.addWidget(t)
        lay.addWidget(QLabel("Griffe / tampon imprimé sur les ordonnances et demandes (PNG à fond transparent) :"))
        self.preview = QLabel(); self.preview.setMinimumHeight(150); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:white;border:1px dashed #888;")
        lay.addWidget(self.preview)
        row = QHBoxLayout()
        bi = QPushButton("📂 Importer…"); bi.clicked.connect(self.import_png)
        br = QPushButton("🗑 Retirer"); br.clicked.connect(self.remove)
        row.addWidget(bi); row.addWidget(br); lay.addLayout(row)
        bp = QPushButton("🔑 Changer mon PIN"); bp.clicked.connect(self.change_pin); lay.addWidget(bp)
        self._show()

    def _show(self):
        u = self.db.get_user(self.user["id"])
        pix = QPixmap()
        if u and u.get("signature_b64"):
            pix.loadFromData(base64.b64decode(u["signature_b64"]))
        if pix.isNull():
            self.preview.setText("Aucune griffe importée")
        else:
            self.preview.setPixmap(pix.scaledToHeight(140, Qt.TransformationMode.SmoothTransformation))

    def import_png(self):
        path, _ = QFileDialog.getOpenFileName(self, "Griffe / tampon", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            return QMessageBox.warning(self, "Griffe", "Image illisible.")
        img = img.scaled(600, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")                                   # le canal alpha (transparence) est conservé
        self.db.set_signature(self.user["id"], base64.b64encode(bytes(ba)).decode())
        self._show()

    def remove(self):
        self.db.set_signature(self.user["id"], ""); self._show()

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
