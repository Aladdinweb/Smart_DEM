# STATE.md — Smart DEM (Système DEM Intelligent)

> Document de référence de l'état du projet. **À mettre à jour à chaque release** (voir « Procédure de release »).

| | |
|---|---|
| **Version courante** | `1.1.0` (source unique : `version.py`) — dernière version publiée : `1.0.0` |
| **Statut** | v1.1.0 : code complet. Testé automatiquement : couche données (utilisateurs/PIN, ordonnance + QR, radiologie, migration v1→v2), SemVer, Hub. **Interface PyQt6, impression thermique/A4, lecteur de QR, mise à jour GitHub : à valider sur poste Windows réel.** |
| **Dépôt** | https://github.com/Aladdinweb/Smart_DEM |
| **Cible** | Windows 10/11 — PyQt6 + SQLite, `Smart_DEM_Setup.exe` |

## 1. Postes (rôle choisi au premier lancement ; connexion par PIN pour les utilisateurs)

| Poste | Utilisateurs (rôle) | Fonctions |
|---|---|---|
| Accueil Général / Poste Dédié | Accueil | Nom + Prénom séparés, tri médical, ticket (impression silencieuse), historique/correction, archivage auto |
| Poste Médecin | Médecin | File priorisée + ⚠️ Patient Récurrent, ordonnance numérique (QR, griffe), demande de radiologie (LAN), demande d'analyses, clôture + archivage |
| Poste Radiologie | Manipulateur radio | File LAN (demandes + inscriptions directes), alerte visuelle/sonore, appel, validation *Terminé / En attente de tirage* renvoyée au médecin |
| Poste Pharmacie | Pharmacien | Ordonnances reçues (file de transit), scan QR → authenticité, « délivrée » |

Administration (PIN administrateur) : paramètres, gestion des utilisateurs (création, rôle, spécialité, PIN, activation), fermeture de l'application.
Utilisateur : bouton **🔒 Déconnexion** (à côté de Paramètres) → verrouille et permet de changer d'utilisateur sans fermer ; **🖋 Mon profil** (médecin) : import de la griffe (PNG transparent), changement du PIN.

## 2. Architecture

| Module | Rôle |
|---|---|
| `main.py` | Démarrage : assistant, mode réseau, poste selon le rôle, session PIN |
| `database.py` · `schema.sql` | SQLite : utilisateurs, gardes, admissions, consultations, ordonnances, radiologie, analyses, transit pharmacie, migrations |
| `ui_common.py` · `ui_login.py` | Fenêtre de base (en-tête officiel, session, bannière), connexion PIN, utilisateurs, profil |
| `ui_reception.py` · `ui_doctor.py` · `ui_radio.py` · `ui_pharmacy.py` | Les 4 types de poste |
| `branding.py` · `assets/` | En-tête officiel : logo (gauche), République / Ministère (centre), drapeau (droite), mêmes cercles |
| `printer.py` · `documents.py` · `qr.py` | Impression silencieuse + PDF, ordonnance/demandes A4, QR Code |
| `archive.py` | Archivage JSON local : `archives\reception\`, `archives\consultations\` |
| `hub_server.py` · `remote_db.py` · `tv_page.py` | Hub LAN (RPC + WebSocket TV), client, écran TV `/tv` |
| `github_updater.py` · `updater.py` · `ui_update.py` | Mises à jour GitHub (SHA-256) et hors ligne |

**Données** `%LOCALAPPDATA%\Smart_DEM\` : `dem_database.db`, `config.json`, `structures.json`, `backups\`, `tickets\` (PDF des tickets), `documents\` (PDF ordonnances/demandes), `archives\reception\`, `archives\consultations\`, `assets\logo_ministere.png` (optionnel), `error.log`. La mise à jour GitHub/hors ligne **exclut** ces éléments.

**Modes réseau** : `local` (autonome), `hub` (héberge base + serveur + TV), `client` (utilise la base du Hub, jeton partagé). Les utilisateurs, ordonnances, demandes de radiologie et la file pharmacie sont dans la base du Hub : tous les postes les partagent. Les postes se rafraîchissent par interrogation (médecin/pharmacie 3 s, radiologie 2 s) ; l'écran TV est poussé par WebSocket.

## 3. Modèle de données (schéma v2)

`users` (PIN haché PBKDF2, verrouillage 60 s après 5 échecs, griffe) · `admissions` (+ `last_name`, `first_name`, `created_by`) · `consultations` · `prescriptions` (contenu figé, SHA-256, signature HMAC) · `transit_queue` (JSON léger vers la pharmacie) · `radiology_requests` (passage RAD-xxx, statuts PENDING/CALLED/DONE/AWAITING_PRINT) · `lab_requests` · `drugs` (autocomplétion, s'enrichit) · `shifts`, `counters`, `calls`, `audit_log`, `meta`.
Migration v1→v2 : sauvegarde automatique puis ajout des colonnes ; les anciennes admissions gardent leur nom complet dans `last_name`.

**QR de l'ordonnance** : `SDEM1` + UUID (32 hex) + signature HMAC (16 hex), clé secrète stockée uniquement dans la base du Hub. La pharmacie détecte un QR falsifié ou un contenu altéré. Saisie manuelle du code (8 premiers caractères) possible mais « non vérifiée ».

## 4. Gestion des versions (SemVer `MAJEUR.MINEUR.CORRECTIF`)

- **CORRECTIF** : correction sans changement de données ni de protocole.
- **MINEUR** (ex. 1.1.0) : fonctionnalités compatibles ; migration de schéma *additive* permise (`MIGRATIONS`).
- **MAJEUR** : changement incompatible ; un Hub et des clients de MAJEUR différent refusent de dialoguer (message explicite).
- Pré-versions `1.2.0-rc.1` → *pre-release* GitHub, ignorées par `/releases/latest`.

### Procédure de release
1. Modifier `__version__` dans `version.py` ; compléter l'historique (§7).
2. `git add -A && git commit -m "Release X.Y.Z"` puis `git push`.
3. Test à blanc : onglet Actions › *Release Smart DEM* › *Run workflow* (rien n'est publié).
4. `git tag -a vX.Y.Z -m "Smart DEM X.Y.Z" && git push origin vX.Y.Z`.
5. Le workflow vérifie tag = `v` + `version.py`, lance les tests, compile, publie `Smart_DEM_Setup.exe`, `Smart_DEM_update.zip`, `.sha256`.
6. Les postes proposent la mise à jour (Paramètres › Sécurité & Mises à Jour) ; base et configuration restent intactes ; la base est migrée au lancement.
**Mettre à jour le Hub et les clients ensemble** (même version MAJEURE obligatoire, MINEURE recommandée).

## 5. Feuille de route

### v1.0.0 — publiée
Socle : accueil/tri/médecin, tickets, historique, récurrence, Hub LAN + TV, mises à jour GitHub, CI/CD.

### v1.1.0 — en préparation (cahier des charges « synthèse finale »)
- [x] En-tête officiel sur toutes les vues et documents (logo Ministère à gauche, drapeau à droite, cercles identiques)
- [x] Nom / Prénom séparés (saisie, recherche, correction, documents)
- [x] Impression silencieuse (PDF automatique dans `tickets\`, imprimantes virtuelles ignorées) + archivage auto de l'accueil
- [x] Connexion PIN 4 chiffres par utilisateur, identité dans l'en-tête, bouton Déconnexion
- [x] Badge ⚠️ Patient Récurrent (72 h) : file d'attente et fiche patient du médecin
- [x] Ordonnance numérique (autocomplétion, raccourcis posologie/durée, griffe, QR, envoi pharmacie)
- [x] Demande de radiologie (formulaire structuré, envoi LAN, impression papier optionnelle) + demande d'analyses
- [x] Clôture de consultation + archivage local
- [x] Poste Radiologie et Poste Pharmacie
- [ ] **À fournir** : logo officiel `logo_ministere.png` (badge provisoire sinon)
- [ ] Validation terrain : impression 80/58 mm et A4, lecteur de QR USB, Hub + 2 postes

### v2.0.0 — Propositions (à valider)
- [ ] Statistiques de garde et exports (PDF/Excel)
- [ ] Sauvegardes planifiées + restauration depuis l'interface
- [ ] Hub en service Windows ; distribution des mises à jour du Hub vers les clients (utile sans internet)
- [ ] Notifications poussées (WebSocket) au lieu de l'interrogation
- [ ] Signature de code de l'exécutable ; interface FR/AR (RTL)

## 6. Dépendances

PyQt6 ≥ 6.6 · Flask ≥ 3.0 · flask-sock ≥ 0.7 · **segno ≥ 1.6** (QR Code, pur Python) · PyInstaller et Inno Setup 6 (CI uniquement) · Python 3.12.

## 7. Limites connues et points d'attention
- **Données de santé** : bases et archives JSON/PDF sont en clair dans le profil Windows de l'utilisateur ; protéger les sessions Windows et sauvegarder. Le PIN utilisateur (4 chiffres) protège l'usage de l'application, pas les fichiers.
- **Réseau** : HTTP simple + jeton partagé sur LAN fermé ; le PIN transite en clair sur ce LAN.
- **Lecteur de QR** : lecteur USB en mode « clavier » ; vérifier la disposition (AZERTY) pour que les chiffres soient bien lus. Pas de lecture par caméra.
- **Griffe numérique** : image imprimée, **sans valeur de signature électronique légale**.
- **Dictionnaire de médicaments** : commodité de saisie, pas une référence pharmacologique ; le médecin reste responsable du contenu.
- **Hub** : point unique ; sans lui les postes clients sont inutilisables (aucune perte de données).
- **Logo officiel** : à fournir par l'établissement (usage conforme à la réglementation).
- Dépôt GitHub **public** requis pour la mise à jour automatique ; exécutable non signé (SmartScreen).

## 8. Historique des modifications

### [1.1.0] — en préparation
**Ajouté** : en-tête officiel ; Nom/Prénom ; impression silencieuse + PDF + archivage ; sessions PIN, déconnexion, gestion des utilisateurs ; badge récurrence 72 h ; ordonnance numérique (QR HMAC, griffe, pharmacie) ; demandes de radiologie et d'analyses ; clôture + archivage ; postes Radiologie et Pharmacie ; migration de schéma v2.
**Modifié** : fenêtre de détection des patients récurrents 24 h → 72 h (reprise automatique de l'ancienne valeur par défaut) ; accès base protégé par verrou sur toutes les lectures ; mise en page d'impression recalculée (ticket à hauteur de contenu).
**Corrigé** : boîte « Enregistrer sous PDF » (imprimante virtuelle par défaut) ; échelle de mise en page à l'impression.

### [1.0.0] — publiée
Socle initial (voir §5).
