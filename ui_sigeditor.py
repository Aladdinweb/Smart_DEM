"""Éditeur de griffe / signature : suppression automatique du fond -> PNG transparent, rognage, contraste, aperçu avant enregistrement."""
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QSlider, QVBoxLayout)

import imgproc


def _checker(w, h, s=12):
    pix = QPixmap(w, h)
    p = QPainter(pix)
    for y in range(0, h, s):
        for x in range(0, w, s):
            p.fillRect(x, y, s, s, QColor("#ffffff" if (x // s + y // s) % 2 == 0 else "#d9d9d9"))
    p.end()
    return pix


def _slider(lo, hi, val):
    s = QSlider(Qt.Orientation.Horizontal); s.setRange(lo, hi); s.setValue(val)
    return s


class SignatureEditor(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(620, 720)
        self.raw, self.result_png = None, None
        v = QVBoxLayout(self)
        b = QPushButton("📂 Choisir une image (photo, scan, PNG, JPG)…"); b.clicked.connect(self.choose); v.addWidget(b)
        self.preview = QLabel("Aperçu du rendu final (fond transparent = damier)")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumHeight(260)
        self.preview.setStyleSheet("border:1px dashed #888;"); v.addWidget(self.preview)
        f = QFormLayout()
        self.thr, self.soft, self.con = _slider(0, 100, 28), _slider(10, 150, 70), _slider(50, 250, 100)
        self.cl, self.ct, self.cr, self.cb = (_slider(0, 45, 0) for _ in range(4))
        self.mono = QCheckBox("Encre unie (une seule couleur)"); self.trim = QCheckBox("Rognage automatique autour de l'encre"); self.trim.setChecked(True)
        for lab, w in (("Seuil de détection du fond", self.thr), ("Douceur des bords", self.soft), ("Contraste du tampon (%)", self.con),
                       ("Rogner à gauche (%)", self.cl), ("Rogner en haut (%)", self.ct), ("Rogner à droite (%)", self.cr), ("Rogner en bas (%)", self.cb)):
            f.addRow(lab, w); w.valueChanged.connect(self._schedule)
        f.addRow(self.mono); f.addRow(self.trim)
        self.mono.toggled.connect(self._schedule); self.trim.toggled.connect(self._schedule)
        v.addLayout(f)
        row = QHBoxLayout()
        ok = QPushButton("💾 Enregistrer"); ok.setObjectName("primary"); ok.clicked.connect(self._save)
        ko = QPushButton("Annuler"); ko.clicked.connect(self.reject)
        row.addWidget(ok); row.addWidget(ko); v.addLayout(row)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.render)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            with open(path, "rb") as f:
                self.raw = f.read()
            self.render()

    def _schedule(self, *_):
        self.timer.start(150)

    def render(self):
        if not self.raw:
            return
        try:
            self.result_png = imgproc.process(self.raw, self.thr.value(), self.soft.value(), self.con.value() / 100,
                                              (self.cl.value(), self.ct.value(), self.cr.value(), self.cb.value()), not self.mono.isChecked(), self.trim.isChecked())
        except Exception as e:
            self.result_png = None
            self.preview.setText(f"Image illisible : {e}"); return
        fg = QPixmap(); fg.loadFromData(self.result_png)
        fg = fg.scaled(560, 240, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        bg = _checker(fg.width(), fg.height())
        p = QPainter(bg); p.drawPixmap(0, 0, fg); p.end()
        self.preview.setPixmap(bg)

    def _save(self):
        if not self.result_png:
            return QMessageBox.warning(self, "Image", "Choisissez d'abord une image.")
        self.accept()
