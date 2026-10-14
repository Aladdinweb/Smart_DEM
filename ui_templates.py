"""Modèles de documents par rôle (v1.4.0) : import depuis le PC (« Import »), gestion, et établissement / impression des certificats et fiches."""
import base64, os, tempfile
from datetime import datetime

from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout)

import doc_models
from branding import establishment
from documents import _griffe_and_signature, esc, header_html
from printer import print_document


class TemplatesDialog(QDialog):
    """Import / suppression des modèles du rôle de l'utilisateur. Les modèles sont partagés par tous les postes du même rôle (stockés sur le Hub)."""
    def __init__(self, db, user, parent=None):
        super().__init__(parent)
        self.db, self.user, self.rows = db, user, []
        self.setWindowTitle("📄 Modèles de documents"); self.resize(780, 520)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Importez ici vos modèles (txt, html, docx, png, jpg, pdf). Dans un modèle texte, les champs {{nom}}, {{prenom}}, {{naissance}}, {{age}}, "
                           "{{sexe}}, {{ident}}, {{date}}, {{medecin}}, {{fonction}}, {{service}}, {{etablissement}} sont remplis à l'impression. "
                           "Une image ou un PDF sert de trame pré-imprimée (le texte saisi est imprimé par-dessus)."))
        v.itemAt(0).widget().setWordWrap(True)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for d in db.doc_template_kinds(user["id"]):
            self.kind.addItem(d["title"], d["kind"])
        b = QPushButton("⬆ Import…"); b.setObjectName("primary"); b.clicked.connect(self.do_import)
        row.addWidget(QLabel("Type de modèle :")); row.addWidget(self.kind, 1); row.addWidget(b)
        v.addLayout(row)
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["Type", "Titre", "Fichier", "Importé le"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide(); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)
        self.msg = QLabel(""); self.msg.setWordWrap(True)
        d = QPushButton("🗑 Supprimer le modèle sélectionné"); d.clicked.connect(self.delete)
        v.addWidget(d); v.addWidget(self.msg)
        if not self.kind.count():
            b.setEnabled(False); self.msg.setText("Aucun modèle de document n'est prévu pour votre fonction.")
        self.refresh()

    def refresh(self):
        try:
            self.rows = self.db.list_doc_templates(self.user["id"])
        except (ConnectionError, PermissionError) as e:
            return self.msg.setText(f"⚠ {e}")
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for j, t in enumerate((r["kind_title"], r["title"], f"{r['filename']} ({r['size'] // 1024} Ko)", (r["created_at"] or "")[:16])):
                self.table.setItem(i, j, QTableWidgetItem(t))

    def do_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importer un modèle", "", doc_models.FILE_FILTER)
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
            doc_models.check_upload(os.path.basename(path), data)
            kind = self.kind.currentData()
            title, ok = QInputDialog.getText(self, "Titre du modèle", "Titre affiché dans la liste :", text=self.kind.currentText())
            if not ok:
                return
            self.db.import_doc_template(kind, os.path.basename(path), base64.b64encode(data).decode(), self.user["id"], title)
        except (OSError, ValueError, PermissionError, ConnectionError) as e:
            return self.msg.setText(f"⚠ {e}")
        self.msg.setText("✅ Modèle importé : il est disponible sur tous les postes de votre rôle."); self.refresh()

    def delete(self):
        r = self.table.currentRow()
        if not 0 <= r < len(self.rows):
            return self.msg.setText("Sélectionnez un modèle.")
        if QMessageBox.question(self, "Supprimer", f"Supprimer le modèle « {self.rows[r]['title']} » ?") == QMessageBox.StandardButton.Yes:
            try:
                self.db.delete_doc_template(self.rows[r]["id"], self.user["id"])
            except (ConnectionError, PermissionError, ValueError) as e:
                return self.msg.setText(f"⚠ {e}")
            self.refresh()


def template_pixmap(t):
    """QPixmap d'un modèle image / PDF (1re page) ou None."""
    data = doc_models.decode(t)
    if (t.get("mime") or "").startswith("image/"):
        pix = QPixmap(); pix.loadFromData(data)
        return None if pix.isNull() else pix
    if t.get("mime") == "application/pdf":
        try:
            from PyQt6.QtCore import QSize
            from PyQt6.QtPdf import QPdfDocument
            p = os.path.join(tempfile.mkdtemp(prefix="dem_tpl_"), "m.pdf")
            with open(p, "wb") as f:
                f.write(data)
            doc = QPdfDocument(); doc.load(p)
            pt = doc.pagePointSize(0)
            return QPixmap.fromImage(doc.render(0, QSize(1240, int(pt.height() * 1240 / pt.width()))))
        except Exception:
            return None
    return None


class DocumentDialog(QDialog):
    """Établit un certificat / une fiche pour un patient : choix du modèle (importé ou standard), relecture, impression A4, trace dans le dossier."""
    def __init__(self, db, cfg, user, adm=None, service="", parent=None):
        super().__init__(parent)
        self.db, self.cfg, self.user, self.adm, self.service = db, cfg, user, adm, service
        self.setWindowTitle("📝 Documents & certificats"); self.resize(820, 700)
        self.full_user = db.get_user(user["id"])                 # griffe et signature
        self.tpls = db.list_doc_templates(user["id"])
        self.kinds = db.doc_template_kinds(user["id"])
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.combo = QComboBox()
        for k in self.kinds:
            self.combo.addItem(f"{k['title']} — modèle standard", ("std", k["kind"], None))
            for t in self.tpls:
                if t["kind"] == k["kind"]:
                    self.combo.addItem(f"{k['title']} — {t['title']} ({t['filename']})", ("tpl", k["kind"], t["id"]))
        self.combo.currentIndexChanged.connect(self.load)
        f.addRow("Document :", self.combo)
        self.name, self.first, self.age = QLineEdit((adm or {}).get("last_name", "")), QLineEdit((adm or {}).get("first_name", "")), QLineEdit()
        for w, ph in ((self.name, "Nom"), (self.first, "Prénom")):
            w.setPlaceholderText(ph)
        row = QHBoxLayout(); row.addWidget(self.name); row.addWidget(self.first)
        f.addRow("Patient :", row)
        v.addLayout(f)
        self.hint = QLabel(""); self.hint.setWordWrap(True); v.addWidget(self.hint)
        self.text = QTextEdit(); v.addWidget(self.text, 1)
        self.msg = QLabel(""); self.msg.setWordWrap(True)
        b = QPushButton("🖨 Imprimer (A4) et tracer dans le dossier"); b.setObjectName("primary"); b.clicked.connect(self.print_it)
        v.addWidget(b); v.addWidget(self.msg)
        self.pix = None
        if not self.kinds:
            b.setEnabled(False); self.hint.setText("Aucun document n'est prévu pour votre fonction.")
        else:
            self.load()

    def _ctx(self):
        a = dict(self.adm or {})
        a["last_name"], a["first_name"] = self.name.text().strip(), self.first.text().strip()
        return doc_models.patient_ctx(a, self.full_user or self.user, establishment(self.cfg), self.service)

    def load(self, *_):
        mode, kind, tid = self.combo.currentData()
        ctx, self.pix, self.tpl = self._ctx(), None, None
        if mode == "tpl":
            try:
                self.tpl = self.db.get_doc_template(tid, self.user["id"])
            except (ConnectionError, PermissionError, ValueError) as e:
                return self.hint.setText(f"⚠ {e}")
            body = doc_models.body_html(self.tpl, ctx)
            if body is None:
                self.pix = template_pixmap(self.tpl)
                self.hint.setText("Trame pré-imprimée : saisissez ci-dessous le texte à imprimer par-dessus (laissez vide pour ne rien ajouter)." if self.pix
                                  else "⚠ Ce modèle (PDF / image) ne peut pas être affiché ici : le texte standard sera utilisé sans trame.")
                self.text.setPlainText("")
            else:
                self.hint.setText("Modèle importé : relisez et complétez avant impression.")
                self.text.setHtml(body)
        else:
            self.hint.setText("Modèle standard (à compléter) — importez votre propre modèle avec le bouton « Modèles » de la barre d'en-tête.")
            self.text.setPlainText(doc_models.fill_fields(doc_models.DEFAULT_TEXT.get(kind, ""), ctx))

    def print_it(self):
        mode, kind, tid = self.combo.currentData()
        ctx = self._ctx()
        title = doc_models.kind_title(kind)
        res = {}
        content = self.text.toHtml() if mode == "tpl" and self.tpl and self.tpl.get("mime") != "text/plain" else "<div style='font-size:12pt;line-height:140%'>" + esc(self.text.toPlainText()).replace("\n", "<br>") + "</div>"
        if mode == "tpl" and self.tpl and self.tpl.get("mime") == "text/plain":
            content = "<div style='font-size:12pt;line-height:140%'>" + esc(self.text.toPlainText()).replace("\n", "<br>") + "</div>"
        patient = f"<p><b>{esc((ctx['nom'] + ' ' + ctx['prenom']).strip())}</b>" + (f" — {esc(ctx['age'])}" if ctx["age"] else "") + "</p>"
        if self.pix is not None:
            html = f"<div style='font-size:12pt'>{patient}{content}</div>"          # la trame fournit l'en-tête et la mise en page
        else:
            html = (f"{header_html(self.cfg)}<h2 align='center' style='margin:6px'>{esc(title.upper())}</h2>"
                    f"<table width='100%'><tr><td>{esc(ctx['medecin'])}</td><td align='right'>Le {esc(ctx['date'])}</td></tr></table>{patient}{content}<br>"
                    f"<table width='100%'><tr><td width='50%'>&nbsp;</td><td align='right'><p style='font-size:9pt'>Cachet et signature</p>{_griffe_and_signature(self.full_user, res)}</td></tr></table>")
        ok, m = print_document(self.cfg, html, res, "a4", f"document_{kind}_{datetime.now():%H%M%S}", tpl_pixmap=self.pix)
        if ok and self.adm:
            try:
                self.db.record_document_issued(self.adm["id"], title, self.user["id"])
            except (ConnectionError, PermissionError, ValueError):
                pass
        self.msg.setText(("🖨 " + m) if ok else f"⚠ Impression impossible : {m}")
