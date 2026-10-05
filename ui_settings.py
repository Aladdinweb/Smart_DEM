"""Paramètres (accès par PIN administrateur) : Structure & Rôle | Imprimantes & Modèles | Réseau & Écrans TV | Sécurité & Données | Mises à jour."""
import csv, json, os, shutil
from datetime import date, timedelta

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import github_updater
import templates
import updater
from branding import import_logo
from config_manager import app_dir
from data_structures import SERVICE_BY_CODE
from database import now
from documents import header_html
from printer import physical_printers, print_document, print_ticket
from reports import report_csv, report_html
from styles import stylesheet
from ui_common import open_tv, quit_now, restart_app
from ui_login import UsersDialog
from ui_setup import NetworkForm, StructureRoleForm
from ui_update import CheckThread, DownloadThread
from version import GITHUB_REPO, __version__


def parse_drug_file(path):
    """Nomenclature des médicaments : JSON (liste de libellés ou d'objets nom/dci/dosage/forme) ou CSV/TXT (un médicament par ligne)."""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        out = []
        for d in data if isinstance(data, list) else data.get("medicaments", []):
            if isinstance(d, str):
                out.append(d)
            else:
                nom, dci = d.get("nom") or d.get("name") or "", d.get("dci") or d.get("dcI") or ""
                out.append(" ".join(x for x in (nom.upper() if nom else "", f"({dci})" if dci else "", d.get("dosage", ""), d.get("forme", "")) if x).strip())
        return [o for o in out if o]
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    rows = list(csv.reader(text.splitlines(), delimiter=";" if ";" in text[:2000] else ","))
    if rows and {c.strip().lower() for c in rows[0] if c.strip()} <= {"nom", "name", "dci", "dosage", "forme", "laboratoire", "designation", "désignation", "libellé", "libelle"}:
        rows = rows[1:]                                   # ligne d'en-tête
    return [" ".join(c.strip() for c in r if c.strip()) for r in rows if any(c.strip() for c in r)]


class TvScreensDialog(QDialog):
    """Assigne à chaque écran TV un ou plusieurs services (vide = tous). Le signal d'appel ne va qu'à l'écran concerné."""
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Écrans TV — services affichés"); self.resize(720, 420)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Un écran par ligne. Services (codes séparés par des virgules, vide = tous) :\n" +
                           "  ".join(f"{c}={s['name']}" for c, s in SERVICE_BY_CODE.items()) + "\n"
                           "Ex : Couloir 1 → DENT,RAD   |   Couloir 2 (laboratoire) → LAB,LABP   |   Salle principale → URG,PED.\n"
                           "Le navigateur de la TV ouvre : http://IP_DU_HUB:5000/tv?screen=IDENTIFIANT"))
        self.t = QTableWidget(0, 3); self.t.setHorizontalHeaderLabels(["Identifiant", "Nom de l'écran", "Services"])
        self.t.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.t, 1)
        for s in db.tv_screens():
            self._add(s["id"], s["name"], ",".join(s["services"]))
        row = QHBoxLayout()
        for label, fn in (("➕ Ajouter un écran", lambda *_: self._add("", "", "")), ("🗑 Retirer", lambda *_: self.t.removeRow(self.t.currentRow())), ("💾 Enregistrer", self.save)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        v.addLayout(row)

    def _add(self, a, b, c):
        r = self.t.rowCount(); self.t.insertRow(r)
        for j, x in enumerate((a, b, c)):
            self.t.setItem(r, j, QTableWidgetItem(x))

    def save(self):
        cell = lambda r, c: (self.t.item(r, c).text() if self.t.item(r, c) else "").strip()
        screens = [{"id": cell(r, 0), "name": cell(r, 1) or cell(r, 0), "services": [x.strip().upper() for x in cell(r, 2).split(",") if x.strip()]}
                   for r in range(self.t.rowCount())]
        try:
            self.db.tv_set_screens(screens)
        except Exception as e:
            return QMessageBox.warning(self, "Écrans TV", str(e))
        self.accept()


class ReportDialog(QDialog):
    """Rapports statistiques anonymes pour la Direction de la Santé (DSP) : PDF et CSV."""
    def __init__(self, db, cfg, parent=None):
        super().__init__(parent)
        self.db, self.cfg = db, cfg
        self.setWindowTitle("Rapports statistiques — DSP"); self.resize(460, 260)
        f = QFormLayout(self)
        self.d1, self.d2 = QDateEdit(QDate.currentDate().addDays(-QDate.currentDate().day() + 1)), QDateEdit(QDate.currentDate())
        for d in (self.d1, self.d2):
            d.setCalendarPopup(True)
        self.preset = QComboBox(); self.preset.addItems(["Période personnalisée", "Aujourd'hui", "Mois en cours", "Mois précédent"])
        self.preset.currentIndexChanged.connect(self._preset)
        f.addRow("Période :", self.preset); f.addRow("Du :", self.d1); f.addRow("Au :", self.d2)
        row = QHBoxLayout()
        for label, fn in (("🖨 Générer le PDF", self.pdf), ("📊 Exporter en CSV", self.csv)):
            b = QPushButton(label); b.clicked.connect(fn); row.addWidget(b)
        f.addRow(row)
        f.addRow(QLabel("Données agrégées : aucune identité de patient dans ces rapports."))

    def _preset(self, i):
        t = QDate.currentDate()
        if i == 1:
            self.d1.setDate(t); self.d2.setDate(t)
        elif i == 2:
            self.d1.setDate(QDate(t.year(), t.month(), 1)); self.d2.setDate(t)
        elif i == 3:
            first = QDate(t.year(), t.month(), 1).addMonths(-1); self.d1.setDate(first); self.d2.setDate(first.addMonths(1).addDays(-1))

    def _stats(self):
        return self.db.stats_report(self.d1.date().toString("yyyy-MM-dd"), self.d2.date().toString("yyyy-MM-dd"))

    def pdf(self):
        st = self._stats()
        ok, msg = print_document(self.cfg, report_html(self.cfg, st, header_html(self.cfg)), {}, "a4", f"rapport_DSP_{st['date_from']}_{st['date_to']}")
        QMessageBox.information(self, "Rapport", msg if ok else f"Échec : {msg}")

    def csv(self):
        st = self._stats()
        path, _ = QFileDialog.getSaveFileName(self, "Exporter", f"DSP_{st['date_from']}_{st['date_to']}.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(report_csv(st))


class SettingsDialog(QDialog):
    def __init__(self, cfg, db, parent=None):
        super().__init__(parent)
        self.cfg, self.db, self._info = cfg, db, None
        self.setWindowTitle("Paramètres"); self.resize(800, 780)
        lay = QVBoxLayout(self)
        tabs = QTabWidget(); lay.addWidget(tabs, 1)
        scroll = lambda w: (lambda sc: (sc.setWidgetResizable(True), sc.setWidget(w), sc)[2])(QScrollArea())

        # ---- 1. Structure & Rôle ----
        t1 = QWidget(); l1 = QVBoxLayout(t1)
        self.form = StructureRoleForm(cfg); l1.addWidget(self.form)
        f = QFormLayout()
        self.revisit = QSpinBox(); self.revisit.setRange(1, 168); self.revisit.setSuffix(" h"); self.revisit.setValue(int(cfg.get("revisit_check_hours", 72)))
        f.addRow("Fenêtre de détection des patients récurrents :", self.revisit)
        l1.addLayout(f); l1.addStretch()
        tabs.addTab(scroll(t1), "Structure && Rôle")

        # ---- 2. Imprimantes & Modèles ----
        t2 = QWidget(); l2 = QVBoxLayout(t2)
        g = QGroupBox("Imprimantes (impression silencieuse, PDF toujours archivé)"); gf = QFormLayout(g)
        self.printer, self.docprinter = QComboBox(), QComboBox()
        for combo, key in ((self.printer, "printer"), (self.docprinter, "doc_printer")):
            combo.addItem("(Imprimante par défaut de Windows, si physique)", "")
            for n in physical_printers():
                combo.addItem(n, n)
            combo.addItem("PDF seulement (aucune impression papier)", "__PDF__")
            combo.setCurrentIndex(max(0, combo.findData(cfg.get(key, ""))))
        self.paper = QComboBox(); self.paper.addItem("80 mm", 80); self.paper.addItem("58 mm", 58)
        self.paper.setCurrentIndex(0 if int(cfg.get("paper_width_mm", 80)) == 80 else 1)
        test = QPushButton("Imprimer un ticket test"); test.clicked.connect(self.test_print)
        gf.addRow("Imprimante des tickets :", self.printer); gf.addRow("Largeur du papier :", self.paper)
        gf.addRow("Imprimante A4 (ordonnances, demandes) :", self.docprinter); gf.addRow(test)
        l2.addWidget(g)
        tg = QGroupBox("Modèles personnalisés (trame pré-imprimée — image PNG/JPG ou PDF) : impression en surimpression"); tf = QFormLayout(tg)
        self.tpl_lbl = {}
        for kind, label in templates.KINDS.items():
            row = QHBoxLayout()
            lab = QLabel(os.path.basename(cfg.get(templates.key(kind), "")) or "(modèle par défaut avec en-tête officiel)"); self.tpl_lbl[kind] = lab
            bc = QPushButton("Choisir…"); bc.clicked.connect(lambda _=False, k=kind: self.pick_tpl(k))
            br = QPushButton("Retirer"); br.clicked.connect(lambda _=False, k=kind: self.rm_tpl(k))
            row.addWidget(lab, 1); row.addWidget(bc); row.addWidget(br); tf.addRow(label + " :", row)
        self.margins = QLineEdit(cfg.get("tpl_margins_mm", "50,15,15,25")); self.margins.setToolTip("haut, gauche, droite, bas")
        tf.addRow("Marges du texte sur la trame (mm : haut,gauche,droite,bas) :", self.margins)
        l2.addWidget(tg)
        bg = QGroupBox("Logo officiel du Ministère de la Santé"); bl = QVBoxLayout(bg)
        bl.addWidget(QLabel("Importez le logo (PNG/JPG, de préférence carré) : affiché à gauche de l'en-tête et sur tous les documents imprimés."))
        bi = QPushButton("📂 Importer le logo du Ministère…"); bi.clicked.connect(self.pick_logo); bl.addWidget(bi)
        l2.addWidget(bg); l2.addStretch()
        tabs.addTab(scroll(t2), "Imprimantes && Modèles")

        # ---- 3. Réseau & Écrans TV ----
        t3 = QWidget(); l3 = QVBoxLayout(t3)
        self.net = NetworkForm(cfg); l3.addWidget(self.net)
        bt = QPushButton("Tester la connexion au Hub / l'écran TV"); bt.clicked.connect(self.test_network); l3.addWidget(bt)
        tvg = QGroupBox("Écrans TV"); tvf = QVBoxLayout(tvg)
        b_scr = QPushButton("📺 Configurer les écrans et les services affichés (Hub)…"); b_scr.clicked.connect(self.edit_screens); tvf.addWidget(b_scr)
        r2 = QFormLayout()
        self.tv_screen = QComboBox(); self.tv_screen.addItem("(aucun écran rattaché à ce PC)", "")
        try:
            for s in db.tv_screens():
                self.tv_screen.addItem(f"{s['name']}  [{s['id']}]  — " + (",".join(s["services"]) or "tous les services"), s["id"])
        except Exception:
            pass
        self.tv_screen.setCurrentIndex(max(0, self.tv_screen.findData(cfg.get("tv_screen", ""))))
        self.tv_auto = QCheckBox("Ouvrir automatiquement cet écran au démarrage de ce PC"); self.tv_auto.setChecked(bool(cfg.get("tv_autostart")))
        r2.addRow("Écran TV branché sur CE PC :", self.tv_screen); r2.addRow(self.tv_auto); tvf.addLayout(r2)
        b_open = QPushButton("Ouvrir l'écran TV maintenant (navigateur plein écran : touche F11)"); b_open.clicked.connect(self.open_tv_now); tvf.addWidget(b_open)
        l3.addWidget(tvg); l3.addStretch()
        tabs.addTab(scroll(t3), "Réseau && Écrans TV")

        # ---- 4. Sécurité & Données ----
        t4 = QWidget(); l4 = QVBoxLayout(t4)
        sg = QGroupBox("Sécurité & apparence"); sf = QFormLayout(sg)
        self.pin1 = QLineEdit(); self.pin1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin2 = QLineEdit(); self.pin2.setEchoMode(QLineEdit.EchoMode.Password)
        self.theme = QComboBox(); self.theme.addItem("Sombre", "dark"); self.theme.addItem("Clair", "light")
        self.theme.setCurrentIndex(0 if cfg.get("theme") != "light" else 1)
        sf.addRow("Nouveau PIN administrateur (vide = inchangé) :", self.pin1); sf.addRow("Confirmer :", self.pin2); sf.addRow("Thème :", self.theme)
        l4.addWidget(sg)
        dg = QGroupBox("Comptes, médicaments, données"); dl = QVBoxLayout(dg)
        crypt = getattr(getattr(db, "crypto", None), "available", None)
        dl.addWidget(QLabel("🔐 Chiffrement AES-256 des données cliniques : " + ("ACTIF" if crypt else ("INACTIF (bibliothèque absente)" if crypt is False else "géré par le poste Hub"))))
        for label, fn in (("👥 Gérer les utilisateurs (médecins, accueil, radio, laboratoire, pharmacie)…", lambda *_: UsersDialog(db, self).exec()),
                          ("💊 Importer la nomenclature des médicaments (JSON / CSV)…", self.import_drugs),
                          ("📊 Rapports statistiques DSP (PDF / CSV)…", lambda *_: ReportDialog(db, cfg, self).exec()),
                          ("💾 Sauvegarder la base maintenant", self.backup),
                          ("🔑 Exporter la clé de chiffrement (à conserver en lieu sûr)…", self.export_key)):
            b = QPushButton(label); b.clicked.connect(fn); dl.addWidget(b)
        l4.addWidget(dg)
        cg = QGroupBox("Synchronisation vers un serveur distant (hors-ligne d'abord, HTTPS, format HL7 FHIR) — expérimental"); cf = QFormLayout(cg)
        self.sync_on = QCheckBox("Activer la file de synchronisation"); self.sync_on.setChecked(bool(cfg.get("sync_enabled")))
        self.sync_url = QLineEdit(cfg.get("sync_endpoint", "")); self.sync_url.setPlaceholderText("https://… (aucun serveur national n'est encore disponible)")
        self.sync_tok = QLineEdit(cfg.get("sync_token", "")); self.sync_tok.setEchoMode(QLineEdit.EchoMode.Password)
        cf.addRow(self.sync_on); cf.addRow("Adresse du serveur :", self.sync_url); cf.addRow("Jeton d'accès :", self.sync_tok)
        l4.addWidget(cg); l4.addStretch()
        tabs.addTab(scroll(t4), "Sécurité && Données")

        # ---- 5. Mises à jour ----
        t5 = QWidget(); l5 = QVBoxLayout(t5)
        ug = QGroupBox("Mises à jour GitHub"); ul = QVBoxLayout(ug)
        ul.addWidget(QLabel(f"Version installée : <b>v{__version__}</b>"))
        self.auto = QCheckBox("Vérifier automatiquement au démarrage (si internet disponible)"); self.auto.setChecked(bool(cfg.get("auto_update_check", True)))
        self.repo = QLineEdit(cfg.get("github_repo") or GITHUB_REPO)
        self.upd_msg = QLabel(); self.upd_msg.setWordWrap(True); self.bar = QProgressBar(); self.bar.hide()
        row = QHBoxLayout()
        self.btn_check = QPushButton("Rechercher une mise à jour"); self.btn_check.clicked.connect(self.check_updates)
        self.btn_install = QPushButton("Télécharger et installer"); self.btn_install.setEnabled(False); self.btn_install.clicked.connect(self.install_update)
        row.addWidget(self.btn_check); row.addWidget(self.btn_install)
        for w in (self.auto, self.repo):
            ul.addWidget(w)
        ul.addLayout(row); ul.addWidget(self.upd_msg); ul.addWidget(self.bar)
        l5.addWidget(ug)
        og = QGroupBox("Mise à jour hors ligne (USB / dossier partagé LAN)"); ol = QVBoxLayout(og)
        ol.addWidget(QLabel("Dossier ou .zip de mise à jour. La base de données et la configuration ne sont jamais modifiées."))
        self.upd = QLineEdit(); ol.addWidget(self.upd)
        r3 = QHBoxLayout()
        bd, bz, ba = QPushButton("Dossier…"), QPushButton("Fichier .zip…"), QPushButton("Appliquer")
        bd.clicked.connect(lambda: self.upd.setText(QFileDialog.getExistingDirectory(self, "Dossier de mise à jour") or self.upd.text()))
        bz.clicked.connect(lambda: self.upd.setText(QFileDialog.getOpenFileName(self, "Mise à jour", "", "Archive (*.zip)")[0] or self.upd.text()))
        ba.clicked.connect(self.apply_offline)
        for b in (bd, bz, ba):
            r3.addWidget(b)
        ol.addLayout(r3); l5.addWidget(og); l5.addStretch()
        tabs.addTab(scroll(t5), "Mises à jour")

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save); bb.rejected.connect(self.reject); lay.addWidget(bb)

    # ---------- impressions / modèles / logo ----------
    def test_print(self):
        row = {"service_code": "LAB", "ticket_label": "TEST-000", "full_name": "TEST IMPRESSION", "triage_level": None, "created_at": now()}
        ok, msg = print_ticket(self.cfg, row, self.printer.currentData(), self.paper.currentData())
        QMessageBox.information(self, "Impression", msg if ok else f"Échec : {msg}")

    def pick_tpl(self, kind):
        path, _ = QFileDialog.getOpenFileName(self, "Modèle / trame", "", "Trame (*.png *.jpg *.jpeg *.pdf)")
        if not path:
            return
        templates.import_template(self.cfg, kind, path)
        if templates.load_template(self.cfg, kind) is None:
            self.cfg.set(templates.key(kind), "")
            return QMessageBox.warning(self, "Modèle", "Impossible de lire ce modèle (les PDF exigent le module PDF de Qt) : convertissez-le en image PNG.")
        self.tpl_lbl[kind].setText(os.path.basename(self.cfg.get(templates.key(kind))))

    def rm_tpl(self, kind):
        self.cfg.set(templates.key(kind), ""); self.tpl_lbl[kind].setText("(modèle par défaut avec en-tête officiel)")

    def pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logo du Ministère", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            try:
                import_logo(path)
                QMessageBox.information(self, "Logo", "Logo enregistré. Il apparaîtra à la prochaine ouverture d'une session (ou au redémarrage).")
            except Exception as e:
                QMessageBox.warning(self, "Logo", str(e))

    # ---------- réseau / TV ----------
    def test_network(self):
        v = self.net.values()
        try:
            if v["net_mode"] == "client":
                from remote_db import RemoteDatabase
                r = RemoteDatabase(v["hub_host"], v["hub_port"], v["lan_token"], use_tls=v["hub_tls"], tls_port=v["hub_tls_port"], cert_pem=v["hub_cert_pem"])
                d = r.ping(); r.tv_state()
                QMessageBox.information(self, "Réseau", f"Connexion OK — Hub v{d['version']} ({d['name']})" + (" — chiffrée TLS 1.3." if v["hub_tls"] else " — non chiffrée."))
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

    def edit_screens(self):
        try:
            TvScreensDialog(self.db, self).exec()
        except Exception as e:
            QMessageBox.warning(self, "Écrans TV", str(e))

    def open_tv_now(self):
        self.cfg.set("tv_screen", self.tv_screen.currentData()); open_tv(self.cfg)

    # ---------- données ----------
    def _safe_backup(self):
        try:
            return self.db.backup(os.path.join(self.cfg.dir, "backups"))
        except ConnectionError:
            return None

    def backup(self):
        p = self._safe_backup()
        QMessageBox.information(self, "Sauvegarde", f"Sauvegarde créée :\n{p}" if p else "La sauvegarde se fait sur le poste Hub.")

    def export_key(self):
        c = getattr(self.db, "crypto", None)
        if not c or not c.key_path:
            return QMessageBox.information(self, "Clé", "La clé est gérée par le poste Hub (ou le chiffrement est inactif).")
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la clé", "db.key")
        if path:
            shutil.copyfile(c.key_path, path)
            QMessageBox.information(self, "Clé", "Clé exportée. Sans elle, une sauvegarde ne peut pas être relue sur un autre PC : conservez-la en lieu sûr, séparée des sauvegardes.")

    def import_drugs(self):
        path, _ = QFileDialog.getOpenFileName(self, "Nomenclature des médicaments", "", "Nomenclature (*.json *.csv *.txt)")
        if not path:
            return
        try:
            names = parse_drug_file(path)
            n = self.db.import_drugs(names)
            QMessageBox.information(self, "Médicaments", f"{len(names)} lignes lues, {n} médicament(s) ajouté(s) à l'autocomplétion.")
        except Exception as e:
            QMessageBox.warning(self, "Médicaments", f"Fichier illisible : {e}")

    # ---------- mises à jour ----------
    def check_updates(self):
        self.btn_check.setEnabled(False); self.btn_install.setEnabled(False); self.upd_msg.setText("Recherche en cours…")
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
                "La base est sauvegardée, jamais modifiée. L'application va se fermer puis redémarrer toute seule.") != QMessageBox.StandardButton.Yes:
            return
        self.btn_install.setEnabled(False); self.btn_check.setEnabled(False); self.bar.setValue(0); self.bar.show()
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
            quit_now()

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
            quit_now()

    # ---------- enregistrement ----------
    def save(self):
        err = self.form.validate() or self.net.validate()
        if not err and self.pin1.text() and (len(self.pin1.text()) < 4 or self.pin1.text() != self.pin2.text()):
            err = "Le nouveau code PIN administrateur doit contenir 4+ caractères et être confirmé à l'identique."
        if not err and len(self.margins.text().split(",")) != 4:
            err = "Marges du modèle : 4 valeurs en mm séparées par des virgules (haut,gauche,droite,bas)."
        if not err and self.sync_on.isChecked() and not self.sync_url.text().strip().lower().startswith("https://"):
            err = "La synchronisation exige une adresse HTTPS."
        if err:
            return QMessageBox.warning(self, "Paramètres", err)
        vals = {**self.form.values(), **self.net.values()}
        changed = any(self.cfg.get(k) != v for k, v in vals.items())
        self.cfg.update(vals)
        self.cfg.update({"revisit_check_hours": self.revisit.value(), "printer": self.printer.currentData(), "doc_printer": self.docprinter.currentData(),
                         "paper_width_mm": self.paper.currentData(), "theme": self.theme.currentData(), "auto_update_check": self.auto.isChecked(),
                         "github_repo": self.repo.text().strip(), "tpl_margins_mm": self.margins.text().strip(), "tv_screen": self.tv_screen.currentData(),
                         "tv_autostart": self.tv_auto.isChecked(), "sync_enabled": self.sync_on.isChecked(), "sync_endpoint": self.sync_url.text().strip(),
                         "sync_token": self.sync_tok.text()})
        if self.pin1.text():
            self.cfg.set_pin(self.pin1.text())
        self.cfg.save()
        QApplication.instance().setStyleSheet(stylesheet(self.cfg.get("theme")))
        parent = self.parent()
        self.accept()
        if changed:
            QMessageBox.information(parent, "Paramètres", "La structure, le rôle ou le réseau a changé : l'application redémarre.")
            restart_app()
