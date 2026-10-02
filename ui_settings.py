"""Paramètres : Structure & Rôle | Imprimante & Réseau | Sécurité & Mises à Jour."""
import os

from PyQt6.QtPrintSupport import QPrinterInfo
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

import github_updater
import updater
from config_manager import app_dir
from database import now
from printer import print_ticket
from styles import stylesheet
from ui_common import restart_app
from ui_setup import NetworkForm, StructureRoleForm
from ui_update import CheckThread, DownloadThread
from version import GITHUB_REPO, __version__


class SettingsDialog(QDialog):
    def __init__(self, cfg, db, parent=None):
        super().__init__(parent)
        self.cfg, self.db, self._info = cfg, db, None
        self.setWindowTitle("Paramètres"); self.resize(760, 760)
        lay = QVBoxLayout(self)
        tabs = QTabWidget(); lay.addWidget(tabs, 1)

        # --- onglet 1 : Structure & Rôle ---
        t1 = QWidget(); l1 = QVBoxLayout(t1)
        self.form = StructureRoleForm(cfg); l1.addWidget(self.form)
        f = QFormLayout()
        self.revisit = QSpinBox(); self.revisit.setRange(1, 72); self.revisit.setSuffix(" h")
        self.revisit.setValue(int(cfg.get("revisit_check_hours", 24)))
        f.addRow("Fenêtre de détection des patients récurrents :", self.revisit)
        l1.addLayout(f); l1.addStretch()
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(t1)
        tabs.addTab(sc, "Structure & Rôle")

        # --- onglet 2 : Imprimante & Réseau ---
        t2 = QWidget(); l2 = QVBoxLayout(t2)
        g = QGroupBox("Imprimante thermique (impression directe)"); gf = QFormLayout(g)
        self.printer = QComboBox()
        self.printer.addItem("(Imprimante par défaut de Windows)", "")
        for n in QPrinterInfo.availablePrinterNames():
            self.printer.addItem(n, n)
        self.printer.addItem("Enregistrer en PDF (test)", "__PDF__")
        self.printer.setCurrentIndex(max(0, self.printer.findData(cfg.get("printer", ""))))
        self.paper = QComboBox(); self.paper.addItem("80 mm", 80); self.paper.addItem("58 mm", 58)
        self.paper.setCurrentIndex(0 if int(cfg.get("paper_width_mm", 80)) == 80 else 1)
        test = QPushButton("Imprimer un ticket test"); test.clicked.connect(self.test_print)
        gf.addRow("Imprimante :", self.printer); gf.addRow("Largeur du papier :", self.paper); gf.addRow(test)
        l2.addWidget(g)
        self.net = NetworkForm(cfg); l2.addWidget(self.net)
        bt = QPushButton("Tester la connexion au Hub / l'écran TV"); bt.clicked.connect(self.test_network)
        l2.addWidget(bt); l2.addStretch()
        tabs.addTab(t2, "Imprimante & Réseau")

        # --- onglet 3 : Sécurité & Mises à jour ---
        t3 = QWidget(); l3 = QVBoxLayout(t3)
        sg = QGroupBox("Sécurité & apparence"); sf = QFormLayout(sg)
        self.pin1 = QLineEdit(); self.pin1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin2 = QLineEdit(); self.pin2.setEchoMode(QLineEdit.EchoMode.Password)
        self.theme = QComboBox(); self.theme.addItem("Sombre", "dark"); self.theme.addItem("Clair", "light")
        self.theme.setCurrentIndex(0 if cfg.get("theme") != "light" else 1)
        sf.addRow("Nouveau code PIN (vide = inchangé) :", self.pin1)
        sf.addRow("Confirmer :", self.pin2); sf.addRow("Thème :", self.theme)
        l3.addWidget(sg)

        ug = QGroupBox("Mises à jour GitHub"); ul = QVBoxLayout(ug)
        ul.addWidget(QLabel(f"Version installée : <b>v{__version__}</b>"))
        self.auto = QCheckBox("Vérifier automatiquement au démarrage (si internet disponible)")
        self.auto.setChecked(bool(cfg.get("auto_update_check", True)))
        self.repo = QLineEdit(cfg.get("github_repo") or GITHUB_REPO); self.repo.setPlaceholderText("utilisateur/dépôt")
        self.upd_msg = QLabel(); self.upd_msg.setWordWrap(True)
        self.bar = QProgressBar(); self.bar.hide()
        row = QHBoxLayout()
        self.btn_check = QPushButton("Rechercher une mise à jour"); self.btn_check.clicked.connect(self.check_updates)
        self.btn_install = QPushButton("Télécharger et installer"); self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self.install_update)
        row.addWidget(self.btn_check); row.addWidget(self.btn_install)
        for w in (self.auto, self.repo): ul.addWidget(w)
        ul.addLayout(row); ul.addWidget(self.upd_msg); ul.addWidget(self.bar)
        l3.addWidget(ug)

        og = QGroupBox("Mise à jour hors ligne (USB / dossier partagé LAN)"); ol = QVBoxLayout(og)
        ol.addWidget(QLabel("Dossier ou .zip de mise à jour. La base de données et config.json ne sont jamais modifiés."))
        self.upd = QLineEdit(); ol.addWidget(self.upd)
        r2 = QHBoxLayout()
        bd, bz, ba = QPushButton("Dossier…"), QPushButton("Fichier .zip…"), QPushButton("Appliquer")
        bd.clicked.connect(lambda: self.upd.setText(QFileDialog.getExistingDirectory(self, "Dossier de mise à jour") or self.upd.text()))
        bz.clicked.connect(lambda: self.upd.setText(QFileDialog.getOpenFileName(self, "Mise à jour", "", "Archive (*.zip)")[0] or self.upd.text()))
        ba.clicked.connect(self.apply_offline)
        for b in (bd, bz, ba): r2.addWidget(b)
        ol.addLayout(r2)
        bk = QPushButton("Sauvegarder la base de données maintenant"); bk.clicked.connect(self.backup)
        ol.addWidget(bk)
        l3.addWidget(og); l3.addStretch()
        sc3 = QScrollArea(); sc3.setWidgetResizable(True); sc3.setWidget(t3)
        tabs.addTab(sc3, "Sécurité & Mises à Jour")

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save); bb.rejected.connect(self.reject); lay.addWidget(bb)

    # ---------- impression / réseau ----------
    def test_print(self):
        row = {"service_code": "LAB", "ticket_label": "TEST-000", "full_name": "TEST IMPRESSION",
               "triage_level": None, "created_at": now()}
        ok, msg = print_ticket(self.cfg, row, self.printer.currentData(), self.paper.currentData())
        QMessageBox.information(self, "Impression", "Ticket envoyé." if ok else f"Échec : {msg}")

    def test_network(self):
        v = self.net.values()
        try:
            if v["net_mode"] == "client":
                from remote_db import RemoteDatabase
                d = RemoteDatabase(v["hub_host"], v["hub_port"], v["lan_token"]).ping()
                RemoteDatabase(v["hub_host"], v["hub_port"], v["lan_token"]).current_shift("test")
                QMessageBox.information(self, "Réseau", f"Connexion OK — Hub v{d['version']} ({d['name']}).")
            elif v["net_mode"] == "hub":
                import hub_server
                if hub_server.CURRENT:
                    hub_server.CURRENT.test_call()
                    QMessageBox.information(self, "Écran TV", "Appel de test envoyé aux écrans TV connectés.")
                else:
                    QMessageBox.information(self, "Réseau", "Le Hub démarrera au prochain lancement : enregistrez, puis testez.")
            else:
                QMessageBox.information(self, "Réseau", "Mode autonome : aucun test réseau nécessaire.")
        except Exception as e:
            QMessageBox.warning(self, "Réseau", str(e))

    # ---------- sauvegarde / mises à jour ----------
    def _safe_backup(self):
        try:
            return self.db.backup(os.path.join(self.cfg.dir, "backups"))
        except ConnectionError:   # poste client : la base est sur le Hub
            return None

    def backup(self):
        p = self._safe_backup()
        QMessageBox.information(self, "Sauvegarde", f"Sauvegarde créée :\n{p}" if p else "La sauvegarde se fait sur le poste Hub.")

    def check_updates(self):
        self.btn_check.setEnabled(False); self.btn_install.setEnabled(False)
        self.upd_msg.setText("Recherche en cours…")
        self._ct = CheckThread(self.repo.text().strip() or GITHUB_REPO)
        self._ct.done.connect(self._on_checked); self._ct.start()

    def _on_checked(self, info, err):
        self.btn_check.setEnabled(True)
        if err:
            self.upd_msg.setText("⚠️ " + err); return
        self._info = info
        if info["available"]:
            self.upd_msg.setText(f"✅ Version v{info['version']} disponible (installée : v{info['current']}).\n{info['notes'][:350]}")
            self.btn_install.setEnabled(bool(info["zip_url"]))
        else:
            self.upd_msg.setText(f"Vous utilisez la dernière version (v{info['current']}).")

    def install_update(self):
        if not self._info or QMessageBox.question(self, "Mise à jour", f"Installer la version v{self._info['version']} ?\n"
                "La base de données est sauvegardée et n'est jamais modifiée.") != QMessageBox.StandardButton.Yes:
            return
        self.btn_install.setEnabled(False); self.btn_check.setEnabled(False)
        self.bar.setValue(0); self.bar.show()
        self._dt = DownloadThread(self._info)
        self._dt.progress.connect(self.bar.setValue); self._dt.done.connect(self._on_downloaded); self._dt.start()

    def _on_downloaded(self, path, err):
        self.btn_check.setEnabled(True); self.bar.hide()
        if err:
            self.upd_msg.setText("⚠️ " + err); return
        try:
            self._safe_backup()
            msg, quit_app = github_updater.install(path)
        except Exception as e:
            QMessageBox.critical(self, "Mise à jour", f"Échec : {e}"); return
        QMessageBox.information(self, "Mise à jour", msg)
        if quit_app:
            QApplication.quit()

    def apply_offline(self):
        src = self.upd.text().strip()
        if not src:
            return QMessageBox.warning(self, "Mise à jour", "Sélectionnez un dossier ou un fichier .zip.")
        if QMessageBox.question(self, "Mise à jour", "Appliquer la mise à jour ? (la base sera sauvegardée avant)") != QMessageBox.StandardButton.Yes:
            return
        try:
            self._safe_backup()
            msg, quit_app = updater.apply_update(src, app_dir())
        except Exception as e:
            return QMessageBox.critical(self, "Mise à jour", f"Échec : {e}")
        QMessageBox.information(self, "Mise à jour", msg)
        if quit_app:
            QApplication.quit()

    # ---------- enregistrement ----------
    def save(self):
        err = self.form.validate() or self.net.validate()
        if not err and self.pin1.text() and (len(self.pin1.text()) < 4 or self.pin1.text() != self.pin2.text()):
            err = "Le nouveau code PIN doit contenir 4+ caractères et être confirmé à l'identique."
        if err:
            return QMessageBox.warning(self, "Paramètres", err)
        vals = {**self.form.values(), **self.net.values()}
        changed = any(self.cfg.get(k) != v for k, v in vals.items())
        self.cfg.update(vals)
        self.cfg.update({"revisit_check_hours": self.revisit.value(), "printer": self.printer.currentData(),
                         "paper_width_mm": self.paper.currentData(), "theme": self.theme.currentData(),
                         "auto_update_check": self.auto.isChecked(), "github_repo": self.repo.text().strip()})
        if self.pin1.text():
            self.cfg.set_pin(self.pin1.text())
        self.cfg.save()
        QApplication.instance().setStyleSheet(stylesheet(self.cfg.get("theme")))
        parent = self.parent()
        self.accept()
        if changed:
            QMessageBox.information(parent, "Paramètres", "La structure, le rôle ou le réseau a changé : l'application redémarre.")
            restart_app()
