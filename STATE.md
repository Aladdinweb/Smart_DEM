# STATE.md — Smart DEM (Système DEM Intelligent)

> Document de référence de l'état du projet. **À mettre à jour à chaque release** (voir « Procédure de release »).

| | |
|---|---|
| **Version courante** | `1.2.0` (source unique : `version.py`) — dernières versions publiées : `1.0.0`, `1.1.0` |
| **Statut** | Code complet de la v1.2.0. **Testé automatiquement (33 tests)** : base de données, migrations v1→v3 et v2→v3, rôles, chiffrement AES-256-GCM, JWT, Hub (RPC, filtrage TV), TLS 1.3 avec certificat épinglé (test réseau réel), traitement d'image, FHIR/outbox, rapports DSP, SemVer. **Non validé sur matériel réel** : interface PyQt6 complète, impression (thermique/A4, surimpression sur trame), lecteur de QR/code-barres, écrans TV réels, mise à jour automatique corrigée. Le test de fumée de l'interface s'exécute dans la CI (non bloquant au début). |
| **Dépôt** | https://github.com/Aladdinweb/Smart_DEM |
| **Cible** | Windows 10/11 — PyQt6 + SQLite, `Smart_DEM_Setup.exe` |

## 1. Espaces par rôle (RBAC) — routage automatique à la connexion

Au démarrage, **tous les utilisateurs se connectent par PIN (4 chiffres)** ; l'application ouvre **uniquement l'espace du rôle** du compte. Il n'existe aucune navigation vers un autre espace, et la base **refuse côté serveur** toute action hors rôle (même si l'interface était contournée ; via le Hub, l'identité vient du jeton JWT, jamais des arguments).

| Rôle du compte | Espace ouvert | Contenu |
|---|---|---|
| Accueil | Accueil Général (ou accueil dédié) | Enregistrement (Nom, Prénom, N° d'identification), tickets, historique/correction, **pilotage des écrans TV** (annonce, pause, effacement), DPI en lecture limitée (identité et passages, sans contenu médical), compteurs |
| Médecin / spécialiste | Consultation | **File d'attente filtrée sur SES services** (compte → services : URG, MG, PED, DENT, DIAB, NUT, OPT, PSY), ordonnance, imagerie, biologie, résultats reçus, DPI complet, profil (griffe, signature) |
| Manipulateur radio | Radiologie | File LAN avec indications cliniques et consignes, appels, envoi du cliché / compte rendu au médecin, impression locale, validation |
| Laboratoire | Laboratoire | Tickets (analyses rapides / bilans prédictifs), file d'appel, demandes des médecins, résultats, **rendez-vous (calendrier + liste globale)** |
| Pharmacien | Pharmacie | Ordonnances reçues, scan QR / code-barres, authenticité, « délivrée » |

**Multi-comptes sur un même poste** : plusieurs médecins (ou agents) se relaient ; chacun a sa session isolée (patient en cours, consultations, historique). À la déconnexion d'un médecin avec un patient en cours : *remettre en file d'attente* (la consultation est marquée « interrompue ») ou rester connecté. Gestion des comptes (création, modification, **suppression** si aucun historique, sinon désactivation, services par médecin, PIN) : Paramètres ou écran de connexion, protégé par le PIN administrateur. Après 5 PIN faux : verrouillage 60 s.

## 2. Correspondance avec le cahier des charges v1.2.0

| § | Exigence | État |
|---|---|---|
| 1 | Logo officiel à gauche, drapeau à droite (même cercle), nom de l'établissement sous « Ministère de la Santé », logo sur les documents | ✅ en place ; **le fichier du logo officiel reste à fournir** (import dans Paramètres, ou `assets/logo_ministere.png`) ; plus aucun badge provisoire |
| 1 | Icône `.ico` professionnelle | ⚠️ `assets/smart_dem.ico` **dessinée par programme** (croix verte, pastille rouge) — pas une image générée par IA ; remplaçable par tout `.ico` (même nom) |
| 2 | Isolation par rôle, interface dentiste (radio panoramique, ordonnance) et spécialités | ✅ |
| 3 | Laboratoire : tickets, RDV (prise/modif/suppression, vue jour, liste globale), TV du couloir flexible, couplage Labo+Radio | ✅ (« bilans prédictifs » est une interprétation de « Prédictifs » : renommable dans `data_structures.py`) |
| 4 | Import de trames PDF/images + impression en surimpression ; QR + code-barres | ✅ images ; **PDF via le module `QtPdf`** (sinon convertir en PNG) — à valider avec vos trames |
| 5 | Griffe/signature : suppression du fond, PNG transparent, éditeur (rognage, contraste, aperçu) | ✅ (Pillow ; rognage par curseurs en %, pas à la souris) |
| 6 | Bannières temporisées ; DPI (nom, prénom, naissance, N° d'identification) | ✅ (info 4 s, erreur 6 s, récurrence 10 s) |
| 7 | Multi-écrans TV par service, signal portant `service_id`, seule la TV concernée réagit | ✅ (`/tv?screen=ID`, filtrage côté Hub) |
| 8 | Offline-first + synchronisation ; HL7/FHIR ; CHIFA/CNAS/CASNOS | ⚠️ **Fondations seulement** : file `sync_outbox`, worker HTTPS avec reprise (désactivé par défaut), export FHIR R4 (Patient, Encounter, MedicationRequest, ServiceRequest). **Aucune intégration CHIFA/CNAS/CASNOS ni serveur national** (nécessite accords et API officiels) ; pas de profil FHIR national certifié |
| 9 | ACID, anti-crash | ✅ SQLite WAL + `synchronous=FULL`, transactions, contrôle d'intégrité au démarrage + restauration de la dernière sauvegarde, exceptions globales (aucune fermeture inattendue), `crash.log` |
| 9 | AES-256, TLS 1.3, jetons | ✅ **AES-256-GCM sur les champs cliniques** (diagnostics, observations, ordonnances, résultats, indications) ; **TLS 1.3 optionnel** Hub↔postes (certificat auto-signé épinglé) ; **jetons JWT HS256** par session (pas un serveur OAuth2 complet) |
| 9 | « Immunité totale » aux injections | ⚠️ non promettable : requêtes **toutes paramétrées**, affichages échappés / texte brut. À vérifier par un audit |
| 9 | Sauvegardes auto, rapports DSP | ✅ quotidienne + fin de garde (14 conservées) ; rapports **anonymes** jour/mois en PDF/CSV, rapport du mois précédent généré automatiquement |

## 3. Architecture

| Module | Rôle |
|---|---|
| `main.py` | Contrôleur : connexion → espace du rôle → déconnexion ; sauvegardes, rapport DSP, sync, résilience |
| `database.py` · `schema.sql` | Schéma v3, migrations idempotentes, RBAC côté base, chiffrement transparent, DPI, RDV, TV, DSP, outbox |
| `hub_server.py` · `remote_db.py` · `auth.py` · `tls.py` | Hub (RPC, JWT, HTTPS/TLS 1.3 épinglé, WebSocket TV par écran) |
| `ui_common.py` · `ui_login.py` · `ui_sigeditor.py` | Fenêtre de base, connexion/utilisateurs/profil, éditeur de griffe |
| `ui_reception.py` · `ui_doctor.py` · `ui_radio.py` · `ui_lab.py` · `ui_pharmacy.py` | Les cinq espaces |
| `ui_dpi.py` · `ui_settings.py` · `ui_setup.py` | DPI et résultats, paramètres, assistant |
| `branding.py` · `documents.py` · `printer.py` · `templates.py` · `barcode.py` · `qr.py` | En-tête officiel, documents A4, impression silencieuse + surimpression, codes |
| `crypto.py` · `imgproc.py` · `fhir.py` · `sync.py` · `reports.py` | AES-256-GCM, détourage, FHIR, synchronisation, DSP |
| `updater.py` · `github_updater.py` | Mises à jour (la copie attend désormais la **fermeture réelle** de l'application) |

**Données** `%LOCALAPPDATA%\Smart_DEM\` : `dem_database.db`, **`db.key`** (clé AES), `config.json`, `backups\`, `tickets\`, `documents\`, `archives\`, `assets\` (logo, modèles), `tls\`, `error.log`, `crash.log`. La mise à jour **exclut** ces éléments.

## 4. Sécurité — ce qui est (et n'est pas) protégé
- **Données cliniques chiffrées au repos** (AES-256-GCM). L'identité du patient, les tickets et le niveau de tri restent en clair (nécessaires à la file d'attente et à la recherche).
- **`db.key` = point critique** : sans elle, les données chiffrées sont illisibles ; une sauvegarde ne se relit pas sur un autre PC sans elle → *Paramètres › Sécurité & Données › Exporter la clé*, à conserver séparément des sauvegardes. La clé est un fichier du profil Windows : elle protège contre la copie de la base seule, pas contre un administrateur du PC.
- **Réseau** : jeton réseau partagé + JWT par utilisateur (expiration 12 h). **TLS 1.3 optionnel** (désactivé par défaut pour ne pas bloquer un déploiement) : à activer sur le Hub puis « Faire confiance au certificat du Hub » sur chaque poste après avoir comparé l'empreinte. Les écrans TV (HTTP, lecture seule) n'affichent **jamais de nom** : ticket, service, bureau.
- **Archives locales** : `archives\reception` contient l'identité (en clair), `archives\consultations` du clinique (en clair) — protéger les sessions Windows.
- Le DPI est tracé (`audit_log`).

## 5. Mise à jour vers la 1.2.0 (important)
Les versions **1.0.0 / 1.1.0 déjà installées** ont l'ancien mécanisme de mise à jour (la copie démarrait avant la fermeture de l'application : fichiers verrouillés, mise à jour partielle — constaté sur poste réel). **Pour passer en 1.2.0, exécuter une fois `Smart_DEM_Setup.exe`** (fermer l'application avant) : les données sont conservées (la base est migrée au lancement, avec sauvegarde automatique). Ensuite seulement, la mise à jour automatique fonctionne avec le nouveau script. **Mettre à jour le Hub avant les postes clients.**

## 6. Gestion des versions (SemVer `MAJEUR.MINEUR.CORRECTIF`)
CORRECTIF = correction ; MINEUR = fonctionnalités compatibles (migration de schéma additive permise) ; MAJEUR = incompatible (Hub et clients de MAJEUR différent refusent de dialoguer). Pré-versions `X.Y.Z-rc.N` = *pre-release* GitHub.
### Procédure de release
1. `version.py` + historique (§9). 2. `git add -A && git commit && git push`. 3. Test à blanc : Actions › *Run workflow*. 4. `git tag -a vX.Y.Z -m "…" && git push origin vX.Y.Z`. 5. Le workflow vérifie tag = `v`+`version.py`, lance les tests, compile (icône, assets), publie `Smart_DEM_Setup.exe`, `Smart_DEM_update.zip`, `.sha256`.

## 7. Feuille de route
### v1.2.0 — en préparation : voir §2 (reste : logo officiel, validation terrain, tests de fumée CI verts)
### v2.0.0 — propositions
- [ ] Intégration CHIFA/CNAS/CASNOS et serveur régional/national (conditionnée aux spécifications officielles)
- [ ] Profils FHIR nationaux, terminologies (CIM-10, ATC), signature électronique légale des ordonnances
- [ ] Sauvegarde chiffrée avec export de clé protégé par phrase secrète ; clé liée au compte Windows (DPAPI)
- [ ] Notifications poussées (WebSocket) au lieu de l'interrogation ; Hub en service Windows ; mise à jour distribuée par le Hub
- [ ] Rognage à la souris dans l'éditeur de griffe ; interface FR/AR (RTL) ; signature de code de l'exécutable
- [ ] Audit de sécurité indépendant (injections, XSS, durcissement)

## 8. Limites connues
Données de santé en clair dans les archives locales ; HTTP simple sans TLS tant que l'option n'est pas activée ; PIN à 4 chiffres (protège l'usage, pas les fichiers) ; lecteur de QR/code-barres USB en mode clavier (vérifier la disposition AZERTY) ; griffe numérique sans valeur de signature légale ; dictionnaire de médicaments = **liste de départ + import de la nomenclature officielle** (fichier JSON/CSV à fournir : non inclus) ; le Hub est un point unique ; DPI : un même patient est reconnu par N° d'identification ou par nom + sexe + année de naissance (homonymes possibles : vérifier) ; exécutable non signé (SmartScreen) ; dépôt public requis pour la mise à jour GitHub.

## 9. Historique des modifications
### [1.2.0] — en préparation
**Ajouté** : connexion par PIN avant tout accès et routage automatique par rôle (accueil, médecin/spécialiste, radio, laboratoire, pharmacie) ; services par médecin (dentiste, diabétologie, psychologie, optique…) ; consultation multi-comptes avec relève de garde ; laboratoire (tickets, file, résultats, rendez-vous calendrier) ; demandes d'imagerie avec consignes et d'analyses envoyées en un clic, résultats/clichés renvoyés au médecin, impression locale ; DPI (recherche nom/prénom/naissance/N° d'identification) ; griffe + signature avec détourage automatique et éditeur ; trames personnalisées (surimpression), code-barres Code 128 + QR ; N° d'ordonnance ; multi-écrans TV par service, couleurs par service, annonce/pause pilotées par l'accueil, libellé de bureau ; import de la nomenclature des médicaments ; rapports DSP ; sauvegardes automatiques ; chiffrement AES-256-GCM, JWT, TLS 1.3 optionnel ; synchronisation FHIR (fondations) ; icône `.ico`.
**Modifié** : en-tête (logo à gauche, établissement dynamique, plus de badge vert provisoire) ; bannières à masquage automatique ; schéma v3 (migration automatique depuis v1/v2).
**Corrigé** : mise à jour automatique (la copie attend la fermeture réelle de l'application, journal du résultat, aucun fichier partiel) ; caractère « & » avalé dans les menus et titres (« Structure & Rôle », « Consultations Générales & Urgences »…) ; texte de patient interprété comme HTML dans l'interface.
### [1.1.0] — publiée · ### [1.0.0] — publiée
Voir l'historique Git.
