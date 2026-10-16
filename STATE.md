# STATE.md — Smart DEM (Système DEM Intelligent)

> Document de référence de l'état du projet. **À mettre à jour à chaque release** (voir « Procédure de release »).

| | |
|---|---|
| **Version courante** | `1.5.0-a.1` (source unique : `version.py` ; lot a de la 1.5.0, pré-version SemVer) — publiées : `1.0.0`, `1.1.0`, `1.2.0` (+ `1.2.1`), `1.3.0` ; `1.4.0` = base de ce lot (à tagger si ce n'est pas fait) |
| **Statut** | Code complet de la v1.4.0 (**à tagger après validation de la CI**). **76 tests automatiques** (base de données, migrations v1→v5, rôles/fonctions, soins, coordinateurs, relève de garde, brouillons, TV, chiffrement, JWT, TLS, Hub, packaging, SemVer, **messagerie, modèles, rendez-vous + QR, DPI paramédical, traçabilité des actes, interface 4:3/16:9**). **Non validé sur matériel réel** : l'interface complète, l'impression, les TV, les lecteurs de codes. La CI compile puis lance **l'exécutable lui-même** (`--selftest`) : chaque espace doit s'ouvrir. |
| **Dépôt** | https://github.com/Aladdinweb/Smart_DEM |
| **Cible** | Windows 10/11 — PyQt6 + SQLite, `Smart_DEM_Setup.exe` |

## 00. v1.5.0-a (lot a de la 1.5.0) — administrateur vérifié par le Hub, statistiques réservées, en-tête bilingue
| Point | État |
|---|---|
| **Administrateur vérifié par le Hub** | ✅ le PIN administrateur est **contrôlé par le Hub** (`admin_login`, 5 échecs = blocage 60 s, journalisé) ; le Hub délivre un **jeton administrateur de 15 min**. Avant : le PIN n'était testé que dans l'interface et les méthodes d'administration (`create_user`, `delete_user`, `reset_user_pin`, `update_user`, `import_drugs`, `tv_set_screens`) étaient ouvertes à tout poste détenant le jeton réseau — **corrigé** (réponse 401/403 sans session administrateur). Le PIN de l'ancienne configuration du poste Hub est **repris automatiquement** au premier démarrage (`admin_adopt_pin`). Sans PIN défini : poste Hub/autonome = accès libre (historique), poste client = refus. Fermeture de l'application : repli sur le PIN local si le Hub est injoignable |
| **Statistiques réservées** | ✅ `stats_report` exige un **coordinateur (médecins ou paramédical) ou l'administrateur**, contrôlé côté Hub (identité du JWT). Bouton **« 📊 Statistiques »** dans les fenêtres des coordinateurs ; l'administrateur y accède par Paramètres. Le rapport mensuel automatique est calculé par le Hub lui-même (`stats_report_system`, non exposé au réseau). Les compteurs de garde de la barre d'état restent visibles de tous |
| **En-tête bilingue FR/AR dynamique** | ✅ 4 noms officiels tenus par le **Hub** (`meta.establishment` : tutelle FR/AR, structure FR/AR), modifiables dans **Paramètres › Établissement (FR/AR)** (administrateur) ; propagation à tous les postes **sans redémarrage** (`estab_rev` dans l'interrogation toutes les 5 s). Affichage : tutelle FR (2 lignes), tutelle AR, structure FR puis **juste dessous** structure AR ; mêmes lignes sur tickets, ticket RDV, ordonnances, certificats, rapports (texte arabe `dir=rtl`). Valeurs initiales : `assets/etablissement_defaut.json` (noms officiels de EPSP ES SENIA fournis) appliquées seulement si la structure configurée correspond, sinon noms déduits de la configuration. Logo officiel : déjà en v1.4.0 |
| **Décisions du lot** | stock négatif **autorisé avec alerte** (lot c) ; « dépréciation » = **retrait du stock** ; thermique **80 mm** ESC/POS ; A4/A5 via pilotes Windows ; clé de signature des MAJ LAN gardée hors dépôt par l'administrateur ; consommables par défaut : injection (seringue + aiguille + coton/alcool), pansement (bande + compresse stérile + bétadine), suture (fil + gants stériles + compresse), quantités modifiables |
| **À savoir à la mise à jour** | mettre à jour le **Hub en premier** ; au 1er démarrage le Hub reprend son PIN local — vérifier qu'il fonctionne (Paramètres) ; les postes clients n'ont plus besoin d'un PIN local pour l'administration (le PIN est celui du Hub). Les clients qui n'ont pas encore été mis à jour ne peuvent plus créer d'utilisateurs ni ouvrir les statistiques (refus du Hub) |

## 0. v1.4.0 — les 5 lots de la feuille de route

| Lot | État v1.4.0 |
|---|---|
| **1. Signalements & convocations internes** (poste à poste, bidirectionnel) | ✅ `ui_messages.py` + tables `messages` / `message_reads`. Coordinateurs (COORDINATEUR DES MÉDECINS, COORDINATEUR DE PARAMÉDICAL, RESPONSABLE URGENCES, **SURVEILLANT**) → **convocation** d'un ou plusieurs agents ; agents → **signalement** à un groupe de coordination ou à un coordinateur ; **réponse** et **accusé de réception** (« Je me présente ») visibles par l'émetteur. Chaque message : horodatage, nom + fonction de l'agent, **service émetteur** (espace · services · poste), motif, détail, urgence. Affichage **sur les PC uniquement** (badge ✉, bandeau, fenêtre pour convocation / urgent) — **jamais sur la TV** (testé). Motif et détail chiffrés. Interrogation toutes les 5 s |
| **2. Modèles de documents par rôle** | ✅ bouton **« 📄 Modèles »** (en-tête) = **Import** depuis le PC (txt, html, docx, png, jpg, pdf), stockés sur le Hub : partagés par tous les postes du même rôle. Catalogue `doc_models.py` : médecins (arrêt de travail, bonne santé, bilan/analyses, ECG, ordonnances types, certificat autre), **opticien** (fiche ophtalmo, ordonnance de lunettes), **chirurgien-dentiste** (fiche dentaire), **laboratoire** (fiche de prélèvement, formulaire), **radiologie** (fiche d'examen, formulaire). Établissement : « 📝 Documents et certificats » (médecin), « 📝 Fiches et formulaires » (labo, radio) ; champs `{{nom}}` `{{prenom}}` `{{age}}` `{{date}}` `{{medecin}}`… remplis ; image/PDF = trame en surimpression ; **modèle standard** fourni tant que rien n'est importé. Rôle **CHIRURGIEN-DENTISTE** ajouté (22 fonctions) |
| **3. Rendez-vous tous services + ticket QR** | ✅ `ui_appointments.py` : calendrier, n° de passage par service et par jour, ticket imprimé (identité, service, date/heure, n° de passage, **QR signé** `SDEMR1…`). **Arrivée le jour J** : scan du QR (ou bouton) → passage créé et inséré **dans la file du service à la place de l'heure du rendez-vous** (`admissions.sort_ts`), sans ressaisie. Accueil : tous les services ; labo / radio / médecin : leur service (le labo garde son onglet) ; pas de rendez-vous pour Urgences ni Salle de soins |
| **4. Interface adaptative & logo** | ✅ `ui_layout.py` : profil d'écran (4:3, 16:10, 16:9, réglable dans Paramètres › « Format d'écran »), polices/marges compactes, **en-tête sur deux lignes** (boutons du poste qui passent à la ligne), aucune fenêtre ne dépasse l'écran (1024×768 testé). Logo : l'en-tête et **toutes** les impressions (tickets, ordonnances, documents, ticket RDV) affichent `assets/logo_ministere.png` s'il existe — **logo officiel du Ministère fourni** (`assets/logo_ministere.png`, en haut à gauche, face au drapeau) ; **icône du programme** = image « SMART DEM SYSTEM » (`assets/smart_dem.ico` + `smart_dem_256.png`, coins arrondis transparents ; `tools/make_icon.py` régénère le `.ico` depuis le PNG) |
| **5. DPI paramédical & traçabilité** | ✅ personnel paramédical **autorisé** (`functions.DPI_CLINICAL_PARAMED` : ISP, INFERMIER, SAGE FEMME, COORDINATEUR DE PARAMÉDICAL, SURVEILLANT) : historique, constantes, ordonnances, analyses, imagerie, diagnostic — **sans les observations libres des médecins ni la psychologie** (réservée aux médecins) ni les pièces jointes. Autres paramédicaux : identité + passages. Journal **`acts`** (ajout seul, jamais modifié) alimenté **automatiquement** : consultation (début/fin), ordonnance, analyses, imagerie, constantes, orientation, délivrance, rendez-vous, documents établis + **actes de soins** saisis en salle de soins ; chaque ligne = auteur (nom, fonction), service, heure ; détails chiffrés. Chaque consultation du DPI reste tracée (`audit_log`, avec la fonction) |

## 0 bis. Rappel v1.3.0 face au cahier `NEXT_FEATURES.md`

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

*(Les points restants de la 1.3.0 — rendez-vous généralisés + QR, interface 4:3/16:9, DPI paramédical — sont livrés en 1.4.0, voir §0.)*

## 1. Fonctions officielles → espaces (RBAC)

Connexion par PIN (4 chiffres) ; l'application ouvre **uniquement l'espace de la fonction** ; la base **refuse côté serveur** toute action hors rôle (via le Hub, l'identité vient du jeton JWT).

| Fonctions | Espace |
|---|---|
| AGENT DE BUREAU, ADMINISTRATION, ASSISTANT SOCIAL | **Accueil** (enregistrement, tickets, pilotage TV, DPI limité) |
| MÉDECIN, PÉDIATRE, **CHIRURGIEN-DENTISTE**, PSYCHOLOGUE, OPTICIEN, RESPONSABLE URGENCES | **Consultation** (file filtrée sur ses services — dentaire, diabétologie, nutrition… se cochent sur la fonction MÉDECIN) ; RESPONSABLE URGENCES peut en plus diffuser des alertes TV |
| COORDINATEUR DES MÉDECINS | **Coordination des médecins** (vue globale des services de consultation) |
| ISP, INFERMIER, SAGE FEMME, ATS, PARAMÉDICAL, ASSISTANTE MEDICAL | **Soins & Triage** |
| COORDINATEUR DE PARAMÉDICAL, **SURVEILLANT** | **Coordination paramédicale** (vue globale des soins ; DPI paramédical ; messagerie) |
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
| `database.py` · `schema.sql` | Schéma v5, migrations idempotentes, RBAC côté base, chiffrement transparent, DPI, RDV, TV, DSP, outbox |
| `hub_server.py` · `remote_db.py` · `auth.py` · `tls.py` | Hub (RPC, JWT, HTTPS/TLS 1.3 épinglé, WebSocket TV par écran) |
| `ui_common.py` · `ui_login.py` · `ui_sigeditor.py` | Fenêtre de base, connexion/utilisateurs/profil, éditeur de griffe |
| `ui_reception.py` · `ui_doctor.py` · `ui_radio.py` · `ui_lab.py` · `ui_pharmacy.py` · `ui_soins.py` · `ui_coord.py` | Les espaces (8 rôles : accueil, consultation, radiologie, laboratoire, pharmacie, soins, 2 coordinations) |
| `functions.py` · `userdata.py` · `ui_tv.py` | Fonctions officielles, dossiers locaux des agents, pilotage des écrans TV (voix, alertes, appariement) |
| `ui_dpi.py` · `ui_settings.py` · `ui_setup.py` | DPI et résultats, paramètres, assistant |
| `ui_messages.py` · `ui_templates.py` · `ui_appointments.py` · `ui_layout.py` · `doc_models.py` | **v1.4.0** : messagerie interne, modèles / certificats, rendez-vous + QR, interface 4:3/16:9, catalogue des modèles |
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

## 5 bis. Mise à jour vers la 1.4.0 (à lire)
- **Migration automatique v4 → v5** (additive, sauvegarde préalable) : nouvelles tables `messages`, `message_reads`, `doc_templates`, `acts` ; colonnes `appointments.{service_code, number, token, doctor_user_id, admission_id, checkin_at, gender}` et `admissions.{sort_ts, appt_id}`. Les **anciens rendez-vous** deviennent des rendez-vous de **LABORATOIRE** ; ils n'ont ni n° de passage, ni QR, ni sexe : à l'arrivée, le poste demande le sexe et l'année de naissance. Le journal des actes ne contient **pas** l'historique d'avant la 1.4.0.
- Mettre à jour le **Hub avant** les postes clients (nouvelles méthodes RPC). Créer un compte **SURVEILLANT** (Gérer les utilisateurs) pour que les messages « Surveillant » aient un destinataire.
- **Hypothèses à valider sur le terrain** : « Surveillant » = fonction rattachée à la coordination paramédicale ; paramédicaux autorisés au DPI = ISP, INFERMIER, SAGE FEMME, COORDINATEUR DE PARAMÉDICAL, SURVEILLANT (modifiable en une ligne dans `functions.py`).

## 6. Gestion des versions (SemVer `MAJEUR.MINEUR.CORRECTIF`)
CORRECTIF = correction ; MINEUR = fonctionnalités compatibles (migration de schéma additive permise) ; MAJEUR = incompatible (Hub et clients de MAJEUR différent refusent de dialoguer). Pré-versions `X.Y.Z-rc.N` = *pre-release* GitHub.
### Procédure de release
1. `version.py` + historique (§9). 2. `git add -A && git commit && git push`. 3. Test à blanc : Actions › *Run workflow*. 4. `git tag -a vX.Y.Z -m "…" && git push origin vX.Y.Z`. 5. Le workflow vérifie tag = `v`+`version.py`, lance les tests, compile (icône, assets), publie `Smart_DEM_Setup.exe`, `Smart_DEM_update.zip`, `.sha256`.

## 7. Feuille de route
### v1.4.0 — ce document (§0) ; reste : validation sur matériel réel (impression des tickets QR, lecteur de QR, écrans 4:3 réels), relecture des textes des certificats standard par un médecin
- [x] Messagerie interne · [x] Modèles de documents par rôle · [x] Rendez-vous + QR · [x] 4:3 / 16:9 · [x] DPI paramédical + traçabilité
- [ ] Diabétologue / nutritionniste comme fonctions explicites si souhaité (une ligne dans `functions.py`)

### v1.5.0 — conception faite : voir **`docs/ARCHITECTURE_v1.5.0.md`** (6 lots : matériel ESC/POS/A5/lecteurs · stock & péremptions · statistiques réservées aux responsables · en-tête FR/AR · API REST « National Ready » · sauvegarde chiffrée + mise à jour LAN signée). Aucun code écrit ; **8 décisions à prendre** (§10 du document). Ordre conseillé : a (stats + bilingue) → b (sauvegarde + MAJ LAN) → c (stock) → d (matériel) → e (API).
### v2.0.0 — propositions
- [ ] Intégration CHIFA/CNAS/CASNOS et serveur régional/national (conditionnée aux spécifications officielles) ; profils FHIR nationaux ; signature électronique légale
- [ ] Sauvegarde chiffrée avec export de clé protégé par phrase secrète ; clé liée au compte Windows (DPAPI)
- [ ] Notifications poussées (WebSocket) au lieu de l'interrogation ; Hub en service Windows ; mise à jour distribuée par le Hub
- [ ] Audit de sécurité indépendant ; interface FR/AR (RTL) ; signature de code de l'exécutable

## 8. Limites connues
v1.4.0 : messages et convocations **interrogés toutes les 5 s** (pas de poussée instantanée) et conservés sur le Hub sans purge automatique ; ne mettre aucune information médicale nominative dans un message ; modèles **DOCX = texte seul** (mise en forme Word non conservée), modèles PDF/image = trame (PDF : nécessite QtPdf, sinon modèle standard) ; le journal des actes ne remonte pas avant la 1.4.0 ; l'impression des tickets QR et la lecture au lecteur USB n'ont pas été essayées sur matériel réel ; textes des certificats standard = trames génériques à faire relire par un médecin. Voix de la TV : celle du navigateur du PC de la TV (une voix féminine française est cherchée, sinon la première voix française) ; le signal sonore est toujours émis. Appariement : la TV doit pouvoir joindre le PC Hub par son nom (`NOM-DU-PC`, selon la résolution de noms du réseau) ou son IP. `activity.log` ne retrace que les actions faites sur le PC concerné. Vues des coordinateurs : files de leur périmètre (consultations ou soins), pas les files radiologie / laboratoire. Données de santé en clair dans les archives locales ; HTTP simple sans TLS tant que l'option n'est pas activée ; PIN à 4 chiffres (protège l'usage, pas les fichiers) ; lecteur de QR/code-barres USB en mode clavier (vérifier la disposition AZERTY) ; griffe numérique sans valeur de signature légale ; dictionnaire de médicaments = **liste de départ + import de la nomenclature officielle** (fichier JSON/CSV à fournir : non inclus) ; le Hub est un point unique ; DPI : un même patient est reconnu par N° d'identification ou par nom + sexe + année de naissance (homonymes possibles : vérifier) ; exécutable non signé (SmartScreen) ; dépôt public requis pour la mise à jour GitHub.

## 9. Historique des modifications
### [1.5.0-a.1] — lot a de la 1.5.0
**Ajouté** : PIN administrateur vérifié par le Hub + jeton administrateur (15 min) ; reprise automatique du PIN de la configuration ; établissement bilingue FR/AR dynamique (Paramètres › Établissement, propagation aux postes, impressions) ; bouton Statistiques des coordinateurs ; `assets/etablissement_defaut.json`.
**Sécurité** : les méthodes d'administration ne sont plus appelables avec le seul jeton réseau ; les statistiques globales sont réservées aux coordinateurs et à l'administrateur (contrôle côté Hub).
**Modifié** : `stats_report(date_from, date_to, user_id)` ; `messages_poll` renvoie `estab_rev` ; en-tête à 5 lignes (tutelle FR/AR, structure FR/AR).
### [1.4.0] — publiée avec le lot a si non tagguée séparément
**Ajouté** : messagerie interne poste à poste (signalements, convocations, accusés, réponses ; jamais sur la TV) ; import de modèles de documents par rôle (« Modèles ») et établissement de certificats / fiches (DOCX = texte seul) ; fonctions **CHIRURGIEN-DENTISTE** et **SURVEILLANT** (22 fonctions) ; rendez-vous de tous les services avec ticket QR et insertion automatique dans la file à l'arrivée ; interface adaptative 4:3 / 16:9 (+ réglage « Format d'écran ») ; DPI pour le paramédical autorisé ; journal de traçabilité des actes (`acts`) + saisie des actes de soins ; logo officiel du Ministère et icône « SMART DEM SYSTEM » intégrés ; avertissement CI si le logo manque.
**Modifié** : schéma v5 (migration automatique) ; la file est triée par heure de rendez-vous pour les patients arrivés sur rendez-vous ; en-tête sur deux lignes en 4:3 ; le médecin peut créer des rendez-vous de ses services (auparavant : laboratoire uniquement) ; onglet Rendez-vous du laboratoire remplacé par le panneau commun.
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
