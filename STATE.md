# STATE.md — Smart DEM (Système DEM Intelligent)

> Document de référence de l'état du projet. **À mettre à jour à chaque release** (voir « Procédure de release »).

| | |
|---|---|
| **Version courante** | `1.0.0` (source unique : `version.py`) |
| **Statut** | Code complet de la v1.0.0 écrit ; tests unitaires de la couche données/Hub/SemVer prêts. **Interface PyQt6, impression thermique, CI et mise à jour GitHub : pas encore validés sur matériel réel.** |
| **Dépôt** | GitHub (`GITHUB_REPO` dans `version.py` — à ajuster au nom réel) |
| **Cible** | Windows 10/11 — PyQt6 + SQLite, déploiement `Smart_DEM_Setup.exe` |

## 1. Architecture

| Module | Rôle |
|---|---|
| `main.py` | Démarrage : assistant de premier lancement, choix du mode réseau, fenêtre selon le rôle |
| `ui_setup.py` · `ui_settings.py` | Assistant / Paramètres (Structure & Rôle, Imprimante & Réseau, Sécurité & Mises à jour) |
| `ui_reception.py` · `ui_doctor.py` · `ui_common.py` | Accueil & tri, Poste Dédié, Poste Médecin, en-tête / bannière / PIN |
| `database.py` · `schema.sql` | SQLite (gardes, compteurs, admissions, appels, audit) + migrations de schéma |
| `hub_server.py` · `tv_page.py` · `remote_db.py` | Hub LAN Flask + WebSocket, écran TV `/tv`, client RPC des postes distants |
| `github_updater.py` · `updater.py` · `ui_update.py` | Mise à jour GitHub (API Releases) et hors ligne (dossier/USB/ZIP) |
| `printer.py` | Ticket 80/58 mm en impression directe (repli PDF) |

**Modes réseau** (par poste, `config.json` → `net_mode`)
- `local` : poste autonome, base SQLite locale.
- `hub` : héberge la base + le serveur (port `hub_port`, 5000 par défaut) + l'écran TV `http://IP_DU_HUB:5000/tv`.
- `client` : tous les appels de données passent par le Hub (jeton partagé `lan_token`) ; accueil, postes dédiés et médecins partagent ainsi la même file d'attente.

**Données** : `%LOCALAPPDATA%\Smart_DEM\` → `dem_database.db`, `config.json`, `structures.json`, `backups\`, `tickets\`, `error.log`.
Le programme est installé dans ce même dossier ; la mise à jour **exclut** ces fichiers/dossiers par nom.

## 2. Gestion des versions (SemVer `MAJEUR.MINEUR.CORRECTIF`)

- **CORRECTIF** (1.0.0 → 1.0.1) : correction de bug, sans changement de données ni de protocole.
- **MINEUR** (1.0.x → 1.1.0) : nouvelle fonctionnalité compatible. Une migration de schéma SQLite *additive* est permise.
- **MAJEUR** (1.x → 2.0.0) : changement incompatible (protocole Hub/clients, schéma). Un Hub et des clients de **MAJEUR différent refusent de dialoguer** (message explicite) : mettre à jour tous les postes.
- Pré-versions : `1.1.0-rc.1` → publiées en *pre-release* GitHub, ignorées par `/releases/latest` donc jamais proposées aux postes.
- Schéma de base : `SCHEMA_VERSION` + `MIGRATIONS` dans `database.py` ; sauvegarde automatique avant toute migration.

### Procédure de release
1. Modifier `__version__` dans `version.py`.
2. Compléter l'historique ci-dessous (section « Historique des modifications »).
3. `git commit -am "Release 1.0.1"` puis `git tag v1.0.1` puis `git push origin main v1.0.1`.
4. Le workflow `.github/workflows/build.yml` vérifie que le tag = `v` + `version.py`, lance les tests, compile (PyInstaller), génère `Smart_DEM_Setup.exe`, `Smart_DEM_update.zip` et `Smart_DEM_update.zip.sha256`, puis publie la Release GitHub.
5. Les postes détectent la nouvelle version (vérification au démarrage ou bouton dans Paramètres), téléchargent le ZIP, vérifient le SHA-256 et l'appliquent **sans toucher à la base**.

## 3. Feuille de route

### v1.0.0 — Socle opérationnel
- [x] Assistant de premier lancement (wilaya → type → établissement → structure en cascade, rôle du poste, PIN)
- [x] Accueil Général / Poste Dédié (multi-services) / Poste Médecin
- [x] Tri médical dynamique (vert/orange/rouge) limité aux Urgences et à la Médecine Générale
- [x] Tickets par service (`LAB-001`…), remise à zéro manuelle des compteurs (nouvelle garde), pas de reset automatique à minuit
- [x] Historique, correction d'erreur (numéro de ticket conservé), réimpression
- [x] Alerte patient récurrent (24–48 h, informative, jamais bloquante)
- [x] Hub LAN Flask + WebSocket, écran TV (numéro, service, salle — jamais de nom de patient)
- [x] Mise à jour GitHub (API Releases + SHA-256) et mise à jour hors ligne ; base et `config.json` protégés
- [x] CI/CD GitHub Actions, SemVer, installateur Inno Setup
- [ ] Validation sur poste Windows réel (UI, imprimante thermique 80/58 mm, pare-feu Windows pour le port du Hub)
- [ ] Premier tag `v1.0.0` et test de bout en bout de la mise à jour (v1.0.0 → v1.0.1)

### v2.0.0 — Propositions (à valider)
- [ ] Comptes utilisateurs individuels (PIN par agent, journal d'audit par utilisateur)
- [ ] Statistiques de garde et exports (PDF/Excel), temps d'attente moyens
- [ ] Sauvegardes planifiées + restauration depuis l'interface
- [ ] Hub en service Windows (démarrage automatique) et distribution des mises à jour du Hub vers les clients du LAN (utile sans internet)
- [ ] Signature de code de l'exécutable (évite l'avertissement SmartScreen)
- [ ] Interface bilingue FR/AR (RTL)

## 4. Dépendances

| Paquet | Usage |
|---|---|
| Python 3.12 | exécution / build CI |
| PyQt6 ≥ 6.6 | interface, impression |
| Flask ≥ 3.0, flask-sock ≥ 0.7 (→ simple-websocket) | Hub LAN et WebSocket, sans client JS externe |
| PyInstaller | compilation (CI uniquement) |
| Inno Setup 6 | installateur (CI uniquement) |
| SQLite | inclus dans Python |

## 5. Limites connues
- Le Hub est un point unique : si son poste est éteint, les postes clients ne fonctionnent plus (messages d'erreur explicites, aucune perte de données).
- Le réseau local utilise du HTTP simple avec un jeton partagé : adapté à un LAN fermé de service, pas à un réseau ouvert.
- La mise à jour GitHub suppose un dépôt **public** (un dépôt privé exigerait un jeton d'accès).
- L'exécutable n'est pas signé : Windows SmartScreen peut afficher un avertissement à l'installation.

## 6. Historique des modifications

### [1.0.0] — en préparation
**Ajouté** : tout le périmètre v1.0.0 ci-dessus.
