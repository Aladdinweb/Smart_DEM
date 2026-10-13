# STATE.md — Smart DEM (Système DEM Intelligent)

> Document de référence de l'état du projet. **À mettre à jour à chaque release** (voir « Procédure de release »).

| | |
|---|---|
| **Version courante** | `1.3.0` (source unique : `version.py`) — publiées : `1.0.0`, `1.1.0`, `1.2.0` (+ `1.2.1` correctif) |
| **Statut** | Code complet de la v1.3.0. **45 tests automatiques** (base de données, migrations v1→v4, rôles/fonctions, soins, coordinateurs, relève de garde, brouillons, TV : voix/alertes/appariement, chiffrement, JWT, TLS, Hub, packaging, SemVer). **Non validé sur matériel réel** : l'interface complète, l'impression, les TV, les lecteurs de codes. La CI compile puis lance **l'exécutable lui-même** (`--selftest`) : chaque espace doit s'ouvrir. |
| **Dépôt** | https://github.com/Aladdinweb/Smart_DEM |
| **Cible** | Windows 10/11 — PyQt6 + SQLite, `Smart_DEM_Setup.exe` |

## 0. v1.3.0 face au cahier `NEXT_FEATURES.md`

| Exigence | État v1.3.0 |
|---|---|
| **20 fonctions officielles** (liste fermée) à la création / modification de compte, chacune liée à son espace | ✅ `functions.py`, formulaire à liste groupée, migration des comptes existants |
| Dossier local par agent `data/users/[SLUG]/` (`profile.json`, `activity.log`, `drafts/`) | ✅ `userdata.py` — **reflet local** : la base reste la référence ; le journal ne contient jamais de nom de patient |
| **TV** : `http://NOM-DU-PC:5000/tv` ou code `TV-4092` | ✅ code court à saisir à l'Accueil (appariement mémorisé) ; ⚠️ la TV doit pouvoir joindre le PC Hub par son nom ou son IP |
| Synthèse vocale (appel automatique) | ✅ voix **féminine française recherchée** (Hortense, Julie, Denise…) ; ⚠️ dépend des voix installées sur le PC de la TV |
| Bouton 📢 de rappel / répétition de l'appel | ✅ « 📢 Rappeler / répéter l'appel » sur chaque poste d'appel + bouton 📢 sur la TV ; **🔊 voix on/off** (TV et Accueil/coordinateurs), le bip reste actif |
| Bandeau de notifications dynamiques (alertes, urgences) | ✅ INFO / ALERTE / URGENCE (clignotant + signal), durée réglable ; accueil, coordinateurs et **RESPONSABLE URGENCES** |
| **Relève de garde** + sauvegarde instantanée des brouillons | ✅ le patient est **réservé** pour un confrère (pas remis en file), brouillon chiffré enregistré toutes les 4 s, reprise en un clic (consultation et brouillon transférés, traçé) ; aussi pour les soignants |
| **Vues globales** `COORDINATEUR DES MÉDECINS` / `COORDINATEUR DE PARAMÉDICAL` | ✅ vue d'ensemble de la garde (files, urgences, attente moyenne/plus ancienne, relèves), file globale, **réorientation** d'un patient en attente, alertes TV. Le coordinateur supervise : il n'appelle pas les patients |
| **Pharmacie réseau local** + « INDISPONIBLE ACTUELLEMENT » pour la synchro cloud | ✅ |
| *« Chaque rôle lié à son interface propre »* | ✅ nouvel espace **Soins & Triage** (constantes vitales tension / glycémie / température, orientation vers le triage médical) pour ISP, infirmier, sage-femme, ATS, paramédical, assistante médicale |

**Pas encore dans la 1.3.0** (cahier `NEXT_FEATURES.md` §4 et §9) : rendez-vous généralisés à tous les services avec **ticket de rendez-vous imprimé (QR)** et réinsertion automatique dans la file ; rendez-vous de consultation et de radiologie (seul le laboratoire en a) ; interface adaptative 4:3 / 16:9 ; DPI pour le personnel paramédical.

## 1. Fonctions officielles → espaces (RBAC)

Connexion par PIN (4 chiffres) ; l'application ouvre **uniquement l'espace de la fonction** ; la base **refuse côté serveur** toute action hors rôle (via le Hub, l'identité vient du jeton JWT).

| Fonctions | Espace |
|---|---|
| AGENT DE BUREAU, ADMINISTRATION, ASSISTANT SOCIAL | **Accueil** (enregistrement, tickets, pilotage TV, DPI limité) |
| MÉDECIN, PÉDIATRE, PSYCHOLOGUE, OPTICIEN, RESPONSABLE URGENCES | **Consultation** (file filtrée sur ses services — dentaire, diabétologie, nutrition… se cochent sur la fonction MÉDECIN) ; RESPONSABLE URGENCES peut en plus diffuser des alertes TV |
| COORDINATEUR DES MÉDECINS | **Coordination des médecins** (vue globale des services de consultation) |
| ISP, INFERMIER, SAGE FEMME, ATS, PARAMÉDICAL, ASSISTANTE MEDICAL | **Soins & Triage** |
| COORDINATEUR DE PARAMÉDICAL | **Coordination paramédicale** (vue globale des soins) |
| LABORANTIN, PRÉLÈVEMENT | **Laboratoire** (seul LABORANTIN saisit / valide les résultats ; PRÉLÈVEMENT : tickets, rendez-vous, prélèvements) |
| MANIPULATEUR | **Radiologie** |
| PHARMACIEN | **Pharmacie** (LAN ; synchro externe : « INDISPONIBLE ACTUELLEMENT ») |

Gestion des comptes (PIN administrateur) : création, modification (fonction, services), réinitialisation du PIN, désactivation, suppression si aucun historique. Après 5 PIN faux : verrouillage 60 s. Multi-comptes sur un même poste : sessions isolées.

## 2. Rappel : cahier des charges v1.2.0 (inchangé)
Voir l'historique §9 : en-tête officiel (le **fichier du logo reste à fournir**), griffe/signature avec détourage, trames en surimpression, QR + code-barres, DPI, multi-écrans par service, chiffrement AES-256, JWT, TLS 1.3 optionnel, sauvegardes, rapports DSP, synchronisation FHIR (fondations ; aucune intégration CHIFA/CNAS/CASNOS).

## 3. Architecture

| Module | Rôle |
|---|---|
| `main.py` | Contrôleur : connexion → espace du rôle → déconnexion ; sauvegardes, rapport DSP, sync, résilience |
| `database.py` · `schema.sql` | Schéma v3, migrations idempotentes, RBAC côté base, chiffrement transparent, DPI, RDV, TV, DSP, outbox |
| `hub_server.py` · `remote_db.py` · `auth.py` · `tls.py` | Hub (RPC, JWT, HTTPS/TLS 1.3 épinglé, WebSocket TV par écran) |
| `ui_common.py` · `ui_login.py` · `ui_sigeditor.py` | Fenêtre de base, connexion/utilisateurs/profil, éditeur de griffe |
| `ui_reception.py` · `ui_doctor.py` · `ui_radio.py` · `ui_lab.py` · `ui_pharmacy.py` · `ui_soins.py` · `ui_coord.py` | Les espaces (8 rôles : accueil, consultation, radiologie, laboratoire, pharmacie, soins, 2 coordinations) |
| `functions.py` · `userdata.py` · `ui_tv.py` | Fonctions officielles, dossiers locaux des agents, pilotage des écrans TV (voix, alertes, appariement) |
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

## 5. Mise à jour vers la 1.3.0 (à lire)
- **Migration automatique du schéma v3 → v4** au premier lancement (sauvegarde préalable dans `backups\`). Les comptes reçoivent une **fonction** : si la précision d'un compte *Accueil* ou *Médecin* correspond à une fonction officielle, elle est reprise — **un compte « Accueil / ATS » devient « ATS » et ouvre l'espace Soins & Triage** ; les autres reçoivent la fonction par défaut de leur rôle (AGENT DE BUREAU, MÉDECIN, MANIPULATEUR…). Corrigez-les dans « Gérer les utilisateurs » si besoin.
- Mettre à jour le **Hub avant** les postes clients. Mise à jour automatique : fonctionne avec le script corrigé (1.2.1) ; à défaut, `Smart_DEM_Setup.exe` (données conservées).
- Les TV déjà configurées par `?screen=ID` continuent de fonctionner ; sans paramètre, la TV affiche désormais un code d'appariement.

## 6. Gestion des versions (SemVer `MAJEUR.MINEUR.CORRECTIF`)
CORRECTIF = correction ; MINEUR = fonctionnalités compatibles (migration de schéma additive permise) ; MAJEUR = incompatible (Hub et clients de MAJEUR différent refusent de dialoguer). Pré-versions `X.Y.Z-rc.N` = *pre-release* GitHub.
### Procédure de release
1. `version.py` + historique (§9). 2. `git add -A && git commit && git push`. 3. Test à blanc : Actions › *Run workflow*. 4. `git tag -a vX.Y.Z -m "…" && git push origin vX.Y.Z`. 5. Le workflow vérifie tag = `v`+`version.py`, lance les tests, compile (icône, assets), publie `Smart_DEM_Setup.exe`, `Smart_DEM_update.zip`, `.sha256`.

## 7. Feuille de route
### v1.3.0 — ce document (§0) ; reste : logo officiel, validation terrain
### v1.4.0 — prochain lot
- [ ] Rendez-vous **généralisés** (consultations, dentaire, radiologie, laboratoire) : ticket de rendez-vous imprimé (identité, spécialité, date/heure, n° de passage, QR), réinsertion automatique dans la file le jour J
- [ ] Interface adaptative (4:3, 16:9, portables) sans défilement complexe
- [ ] DPI pour le personnel paramédical (constantes, passages) ; fonction « CHIRURGIEN-DENTISTE / DIABÉTOLOGUE » explicite si souhaitée (une ligne dans `functions.py`)
### v2.0.0 — propositions
- [ ] Intégration CHIFA/CNAS/CASNOS et serveur régional/national (conditionnée aux spécifications officielles) ; profils FHIR nationaux ; signature électronique légale
- [ ] Sauvegarde chiffrée avec export de clé protégé par phrase secrète ; clé liée au compte Windows (DPAPI)
- [ ] Notifications poussées (WebSocket) au lieu de l'interrogation ; Hub en service Windows ; mise à jour distribuée par le Hub
- [ ] Audit de sécurité indépendant ; interface FR/AR (RTL) ; signature de code de l'exécutable

## 8. Limites connues
Voix de la TV : celle du navigateur du PC de la TV (une voix féminine française est cherchée, sinon la première voix française) ; le signal sonore est toujours émis. Appariement : la TV doit pouvoir joindre le PC Hub par son nom (`NOM-DU-PC`, selon la résolution de noms du réseau) ou son IP. `activity.log` ne retrace que les actions faites sur le PC concerné. Vues des coordinateurs : files de leur périmètre (consultations ou soins), pas les files radiologie / laboratoire. Données de santé en clair dans les archives locales ; HTTP simple sans TLS tant que l'option n'est pas activée ; PIN à 4 chiffres (protège l'usage, pas les fichiers) ; lecteur de QR/code-barres USB en mode clavier (vérifier la disposition AZERTY) ; griffe numérique sans valeur de signature légale ; dictionnaire de médicaments = **liste de départ + import de la nomenclature officielle** (fichier JSON/CSV à fournir : non inclus) ; le Hub est un point unique ; DPI : un même patient est reconnu par N° d'identification ou par nom + sexe + année de naissance (homonymes possibles : vérifier) ; exécutable non signé (SmartScreen) ; dépôt public requis pour la mise à jour GitHub.

## 9. Historique des modifications
### [1.3.0] — en préparation
**Ajouté** : 20 fonctions officielles (liste fermée) liées aux espaces ; espace **Soins & Triage** (constantes vitales, orientation) ; vues des **coordinateurs** (globale, réorientation, alertes) ; **relève de garde** avec réservation du patient, brouillons chiffrés enregistrés en continu et reprise en un clic ; dossiers locaux `data/users/[SLUG]/` ; TV : appariement par code court, voix féminine, bouton 📢 de répétition, 🔊 voix on/off, bandeaux d'alerte/urgence temporisés ; pharmacie : mode LAN et « INDISPONIBLE ACTUELLEMENT » pour la synchronisation externe ; permissions du laboratoire par fonction (LABORANTIN / PRÉLÈVEMENT).
**Modifié** : schéma v4 (migration automatique) ; `create_user` / `update_user` par fonction ; titre « Dr » selon la fonction ; bouton « Rappeler » = « 📢 Rappeler / répéter l'appel ».
### [1.2.1] — correctif
**Corrigé** : plantage à l'ouverture de l'espace après la connexion (modules d'interface absents de l'exécutable) ; application sans fenêtre après une erreur d'ouverture ; migration de `config.json` (24 h → 72 h). **Ajouté** : `Smart_DEM.exe --selftest` + étape CI bloquante ; tests `test_packaging`. **À faire sur les postes déjà en 1.2.0** : mise à jour automatique (script corrigé) ou `Smart_DEM_Setup.exe`.
### [1.2.0] — publiée
**Ajouté** : connexion par PIN avant tout accès et routage automatique par rôle (accueil, médecin/spécialiste, radio, laboratoire, pharmacie) ; services par médecin (dentiste, diabétologie, psychologie, optique…) ; consultation multi-comptes avec relève de garde ; laboratoire (tickets, file, résultats, rendez-vous calendrier) ; demandes d'imagerie avec consignes et d'analyses envoyées en un clic, résultats/clichés renvoyés au médecin, impression locale ; DPI (recherche nom/prénom/naissance/N° d'identification) ; griffe + signature avec détourage automatique et éditeur ; trames personnalisées (surimpression), code-barres Code 128 + QR ; N° d'ordonnance ; multi-écrans TV par service, couleurs par service, annonce/pause pilotées par l'accueil, libellé de bureau ; import de la nomenclature des médicaments ; rapports DSP ; sauvegardes automatiques ; chiffrement AES-256-GCM, JWT, TLS 1.3 optionnel ; synchronisation FHIR (fondations) ; icône `.ico`.
**Modifié** : en-tête (logo à gauche, établissement dynamique, plus de badge vert provisoire) ; bannières à masquage automatique ; schéma v3 (migration automatique depuis v1/v2).
**Corrigé** : mise à jour automatique (la copie attend la fermeture réelle de l'application, journal du résultat, aucun fichier partiel) ; caractère « & » avalé dans les menus et titres (« Structure & Rôle », « Consultations Générales & Urgences »…) ; texte de patient interprété comme HTML dans l'interface.
### [1.1.0] — publiée · ### [1.0.0] — publiée
Voir l'historique Git.
