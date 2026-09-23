# WFM Planning & Scheduling

Plateforme **Workforce Management** pour construire un cycle complet de planification :
**Configuration → Workforce → LTF → STF → Daily/Intraday → Capacity → Scheduling → Overtime → Actuals → KPI / Control Tower**.

Le projet est construit autour d'un moteur de calcul centralisé afin d'éviter les formules
dupliquées dans les routes ou les écrans. Il supporte les activités **Phone, Email,
Message Us et Backoffice**, les marchés multi-pays, les agents réels ou fictifs, les
absences, les shifts, le ramp-up recrutement et le pilotage intraday.

**Stack :** FastAPI, SQLModel, PostgreSQL/Supabase, Jinja2, Chart.js, Alembic, Render.

**Repository :** https://github.com/johnsonrakotoarisoa0796-cmd/wfm-planning-scheduling

---

## 1. À quoi sert l'application ?

L'application permet de répondre à une question centrale de WFM :

> « Combien d'agents faut-il, quand faut-il les faire travailler, et comment mesurer
> l'écart entre le plan et la réalité ? »

Le parcours recommandé est :

`Marchés / Campagnes / Skills
→ Workforce / Agents
→ LTF
→ STF
→ STF Client (si le client fournit déjà le besoin intervalisé)
→ Daily / Intraday
→ Capacity Planning
→ Scheduling / Generate Schedule
→ Shrinkage / Absences
→ Overtime
→ Imports Actuals
→ Dashboard / Control Tower / Forecast Lab
`

Les données sont reliées entre elles : le **Required HC** devient un besoin de staffing,
le **Scheduled HC** est la décision de planning et l'**Actual HC** représente la réalité
observée.

---

## 2. Démarrage rapide

### Installation locale

Sous Linux/macOS :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Sous PowerShell :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

L'application est disponible sur :

`http://127.0.0.1:8000`

Test de santé :

`http://127.0.0.1:8000/health`

### Base de données

Le projet utilise PostgreSQL/Supabase et Alembic.

Avant le premier lancement local :

```bash
alembic upgrade head
```

Les déploiements Render exécutent automatiquement :

```text
alembic upgrade head && uvicorn app.main:app ...
```

---

## 3. Première connexion et sécurité

Les rôles disponibles sont :

| Rôle | Usage |
|---|---|
| `admin` | Administration, sécurité, configuration et opérations WFM |
| `wfm_analyst` | Forecast, capacité, scheduling et analyses |
| `team_lead` | Pilotage opérationnel, actuals et shrinkage |
| `viewer` | Consultation |

### Créer le premier administrateur

En local :

```bash
python -m app.scripts.create_admin
```

Le script crée le compte et fournit le secret TOTP/QR code.

Sur Render sans accès shell, définir temporairement :

```text
BOOTSTRAP_ADMIN_EMAIL
BOOTSTRAP_ADMIN_PASSWORD
```

puis redéployer.

### Connexion

`/login`

Parcours normal :

`Email + mot de passe → OTP email ou TOTP → session WFM`

Le mode de livraison OTP est configurable par les variables :

```text
OTP_DELIVERY_MODE=email
EMAIL_PROVIDER=brevo
BREVO_API_KEY=...
BREVO_FROM_EMAIL=...
```

Ne jamais commit `.env` ni une clé API.

---

# 4. Utiliser l'application — étape par étape

## Étape 1 — Configurer les marchés

Ouvrir **Marchés** (`/markets`).

Créer ou vérifier les marchés dont le WFM a besoin :

- code pays : FR, UK, DE, IN, ES, JP, NL, etc. ;
- nom ;
- langue ;
- fuseau horaire IANA, par exemple `Europe/London` ou `Europe/Paris`.

Le marché sert de référence pour le skill et les horaires.

---

## Étape 2 — Créer les campagnes et les skills

Ouvrir **Configuration** (`/settings`).

Créer une campagne, par exemple :

```text
Code : SUP-UK
Nom  : Support UK
```

Puis créer les skills associés :

```text
Message Us
Email
Phone
```

La simultanéité doit correspondre à l'activité. Par défaut, le moteur supporte notamment :

| Canal | Simultanéité |
|---|---:|
| Phone | 1 |
| Email | 3 |
| Message Us | 2 |
| Backoffice | configurable |

Pour chaque skill, vérifier aussi le marché associé et son état actif.

---

## Étape 3 — Préparer le Workforce / Agents

Ouvrir **Workforce / Agents** (`/workforce`).

Deux méthodes sont disponibles.

### A. Simulation avec agents fictifs

Utiliser **Créer des agents fictifs**.

Exemple :

```text
Campagne : Support UK
Skill    : Message Us
Nombre   : 140
Contrat  : 40 h/semaine
Fuseau   : Europe/London
```

Cela génère un roster de simulation sans données personnelles réelles.

### B. Agents réels

Créer un agent unitairement ou utiliser **Import CSV/XLS/XLSX**.

Colonnes obligatoires :

```text
employee_code
first_name
last_name
campaign_code
skill_name
hire_date
```

Colonnes optionnelles :

```text
termination_date
weekly_hours_contract
timezone_name
status
```

Statuts :

`active`, `leave`, `terminated`

Exemple :

```csv
employee_code,first_name,last_name,campaign_code,skill_name,hire_date,termination_date,weekly_hours_contract,timezone_name,status
UKMSG001,John,Smith,SUP-UK,Message Us,2026-01-05,,40,Europe/London,active
UKMSG002,Sarah,Jones,SUP-UK,Message Us,2026-02-02,,40,Europe/London,active
```

Pour mettre à jour un agent existant, utiliser son même `employee_code`.

---

## Étape 4 — Configurer le Workforce de la campagne

Depuis **Configuration** ou la fiche Workforce de campagne, renseigner le contexte RH :

- Current HC ;
- Available HC ;
- Long Leave ;
- Planned Leave ;
- Unplanned Absence ;
- Training ;
- Nesting ;
- autres indisponibilités ;
- Attrition ;
- Hiring ;
- Transfers In ;
- Transfers Out ;
- Required HC.

Cette vue sert à rapprocher **effectif réel**, **disponibilité** et **besoin WFM**.

---

## Étape 5 — Configurer les règles WFM hebdomadaires

Dans **Configuration**, renseigner les paramètres par semaine/campagne/skill :

- AHT ;
- Occupancy cible ;
- Service Level cible ;
- Answer Time / ASA cible ;
- Shrinkage ;
- granularité d'intervalle.

Ces paramètres constituent les hypothèses utilisées par les calculs.

---

## Étape 6 — Créer le LTF

Ouvrir **LTF Weekly** (`/ltf`).

Le LTF est le plan de référence long terme.

Pour chaque campagne/skill, saisir notamment :

- période ;
- volume forecast ;
- handling time / AHT ;
- AHT requis ;
- occupancy cible ;
- service level cible ;
- ASA cible ;
- indoor shrinkage ;
- outdoor shrinkage.

Le moteur calcule notamment :

```text
Contact Handling Hours = Volume × AHT / 3600
Agent Workload Hours   = Handling Hours / Concurrency
Net Required HC
Gross Required HC
Paid / Productive / Production Hours
```

Une nouvelle version d'un même LTF n'écrase pas l'historique : le versioning conserve
les versions précédentes.

---

## Étape 7 — Créer le STF Weekly

Ouvrir **STF Weekly** (`/stf`).

Le STF est une révision du LTF sur une semaine ISO.

Exemple :

```text
LTF = 52 000
STF = 53 200
Variance = +1 200
Variance % = +2,31 %
```

Saisir la semaine, campagne, skill, volume, AHT, occupancy, shrinkage et SLA.

Le STF dépend d'un LTF actif couvrant la période.

---

## Étape 8 — Charger un STF Client, si le client donne déjà le besoin par intervalle

Ouvrir **STF Client** (`/stf-client`).

Utiliser cette fonction lorsque le client fournit directement le staffing requis.

Format CSV/XLSX :

```text
date
interval_start
interval_end
required_hc
```

Le STF client devient alors la source opérationnelle du Required HC sur les intervalles
qu'il couvre.

Ordre de priorité :

```text
STF Client courant
      ↓ sinon
Daily / Intraday calculé
```

---

## Étape 9 — Générer Daily / Intraday

Ouvrir **Daily / Intraday** (`/daily`).

Sélectionner :

- date ;
- campagne ;
- skill ;
- volume ;
- AHT.

Le moteur distribue le volume sur les intervalles de 30 minutes selon le profil
intraday.

Pour le Phone, Erlang C est appliqué intervalle par intervalle pour déterminer le
**Required HC** compatible avec le SLA et l'occupancy.

Pour Email / Message Us, le calcul utilise la charge, la simultanéité et l'occupancy.

**Important :** ne générez pas plusieurs fois silencieusement la même journée. Une
journée déjà générée doit être contrôlée avant nouvelle génération.

---

## Étape 10 — Contrôler la Capacity Planning

Ouvrir **Capacity Planning** (`/capacity`).

Le module compare l'effectif courant au besoin et projette notamment :

```text
Future HC =
Current HC
+ Recrutements
+ Transferts entrants
- Transferts sortants
- Attrition
- Absentéisme
```

Contrôler :

- Current HC ;
- Required HC ;
- Future HC ;
- Gap actuel ;
- Gap projeté.

---

## Étape 11 — Configurer les shifts

Ouvrir **Scheduling → Shifts** (`/scheduling/shifts`).

Créer des modèles d'horaires avec :

- heure de début ;
- heure de fin ;
- durée et nombre de pauses ;
- pauses payées/non payées ;
- déjeuner ;
- déjeuner payé/non payé.

Les shifts de nuit sont supportés, par exemple :

`17:00 → 02:00`

Règle de référence standard :

```text
8 h de travail payé
+ 1 h déjeuner
= 9 h de présence
```

Deux pauses de 15 minutes sont configurables.

---

## Étape 12 — Enregistrer les absences et congés

Ouvrir **Absences & congés** (`/scheduling/absences`).

Utiliser les catégories de disponibilité pertinentes :

- maternité ;
- disponibilité ;
- congé payé ;
- congé sans solde.

L'objectif est d'empêcher le générateur de compter comme disponibles des agents qui
sont déjà absents.

---

## Étape 13 — Générer le planning

Ouvrir **Generate Schedule** (`/scheduling/generate`).

Avant de générer :

1. vérifier le Required HC ;
2. vérifier le workforce disponible ;
3. vérifier les absences ;
4. vérifier les shifts ;
5. vérifier les règles Compliance.

Le générateur cherche ensuite une couverture cohérente avec le besoin intervalisé.

Après génération, contrôler :

- **Schedule Board** ;
- **Planner** ;
- **Scheduling** ;
- impact des pauses ;
- couverture par intervalle.

---

## Étape 14 — Vérifier la Compliance

Ouvrir **Compliance** (`/compliance`).

Configurer notamment :

- maximum de jours consécutifs ;
- heures maximum/jour ;
- heures maximum/semaine ;
- overtime maximum/semaine ;
- repos minimum entre shifts ;
- cible de Weekly Coverage.

La compliance sert de garde-fou au planning.

---

## Étape 15 — Enregistrer le Shrinkage

Ouvrir **Shrinkage** (`/shrinkage`).

Enregistrer les pertes de capacité par catégorie, par exemple :

- Break ;
- Meeting ;
- Personal Time ;
- Outage ;
- Project ;
- Training ;
- Leave ;
- Absenteeism.

Le rapport peut être utilisé sur une journée, une semaine ou une période plus large.

---

## Étape 16 — Calculer l'Overtime

Ouvrir **Overtime** (`/overtime`).

Le moteur distingue :

```text
OT Required = besoin calculé
OT Actual   = heures réellement faites
OT Variance = Actual - Required
```

Le principe est :

`OT Required = max(0, Required Hours - Available Hours)`

Un surplus de staffing ne doit pas être transformé en « OT négatif ».

---

## Étape 17 — Importer les Actuals

Ouvrir **Imports Actuals** (`/imports`).

Importer les données ACD/production en CSV ou Excel.

Colonnes principales :

```text
date
interval_start
campaign_id
skill_id
offered
handled
abandoned
talk_time_seconds
hold_time_seconds
acw_seconds
agents_staffed
paid_hours
```

Colonne optionnelle :

`answered_within_threshold`

Avec cette donnée, le Service Level réel peut être calculé à partir de la mesure ACD
fournie.

Sans cette colonne, certains indicateurs restent des estimations opérationnelles
basées sur les données disponibles.

---

## Étape 18 — Utiliser le Dashboard

Ouvrir **Dashboard** (`/dashboard`).

Le Dashboard consolide :

- Forecast ;
- Actual ;
- Forecast Accuracy ;
- Service Level ;
- Occupancy ;
- AHT ;
- ASA ;
- Shrinkage ;
- Required HC ;
- Scheduled HC ;
- Actual HC ;
- Staffing Gap ;
- Capacity ;
- Overtime.

Le Dashboard ne doit pas être utilisé pour saisir une donnée déjà disponible dans un
autre module. Il assemble les données existantes.

---

## Étape 19 — Piloter l'intraday avec Control Tower

Ouvrir **Control Tower** (`/control-tower`).

Utiliser ce module lorsque la journée est en production pour comparer :

```text
Required HC
vs
Scheduled HC
vs
Actual HC
```

C'est la vue adaptée pour détecter rapidement les intervalles sous-staffés ou sur-staffés.

---

## Étape 20 — Utiliser Forecast Lab

Ouvrir **Forecast Lab** (`/forecast-lab`).

Le module aide à mesurer :

- Accuracy ;
- WAPE ;
- Bias ;
- dérive AHT ;
- run-rate et reforecast proposé.

Le reforecast proposé est non destructif : il ne remplace pas automatiquement le
forecast officiel.

---

## Étape 21 — Utiliser AI Copilot

Ouvrir **AI Copilot** (`/ai`).

Le mode local gratuit est disponible par défaut et fournit des diagnostics déterministes
à partir du snapshot WFM.

Une IA externe compatible peut être configurée séparément via :

```text
AI_PROVIDER
AI_API_BASE_URL
AI_API_KEY
AI_MODEL
```

Le Copilot analyse le contexte WFM mais ne doit pas modifier directement les données
de production.

---

# 5. Règles de calcul essentielles

## Heures de traitement

`Handling Hours = Volume × AHT / 3600`

## Charge agent

`Agent Workload Hours = Handling Hours / Concurrency`

## Required HC agrégé

`Net Required HC = Agent Workload Hours / (Available Hours per Agent × Occupancy)`

## Gross HC

`Gross Required HC = Net Required HC / (1 - Shrinkage)`

## Overtime

`OT Required = max(0, Required Hours - Available Hours)`

## Staffing

```text
Required HC  = besoin
Scheduled HC = planning
Actual HC    = réalité
Gap          = Scheduled/Actual - Required selon le contexte affiché
```

## Contrat standard

```text
40 h/semaine
5 jours
8 h/jour
+ 1 h déjeuner
= 9 h de présence
```

Deux pauses de 15 minutes sont configurables.

---

# 6. Répartition intraday

Le profil hebdomadaire par défaut est :

| Jour | Poids |
|---|---:|
| Lundi | 13 % |
| Mardi | 14 % |
| Mercredi | 16 % |
| Jeudi | 17 % |
| Vendredi | 14 % |
| Samedi | 13 % |
| Dimanche | 13 % |

Les profils 30 minutes restent éditables afin d'adapter la courbe de trafic à chaque
activité.

---

# 7. Navigation principale

| Module | URL |
|---|---|
| Dashboard | `/dashboard` |
| Control Tower | `/control-tower` |
| AI Copilot | `/ai` |
| LTF | `/ltf` |
| STF | `/stf` |
| STF Client | `/stf-client` |
| Forecast Lab | `/forecast-lab` |
| Daily / Intraday | `/daily` |
| Recruitment & Ramp-up | `/recruitment` |
| Workforce / Agents | `/workforce` |
| Capacity Planning | `/capacity` |
| Shrinkage | `/shrinkage` |
| Overtime | `/overtime` |
| Scheduling | `/scheduling` |
| Planner | `/scheduling/planner` |
| Schedule Board | `/schedule-board` |
| Generate Schedule | `/scheduling/generate` |
| Absences & congés | `/scheduling/absences` |
| Marchés | `/markets` |
| Agent Hub | `/agent` |
| Imports Actuals | `/imports` |
| Mode d'emploi | `/guide` |
| Configuration | `/settings` |

---

# 8. Variables d'environnement

Variables principales :

| Variable | Rôle | Défaut |
|---|---|---|
| `ENV` | environnement | `development` |
| `DATABASE_URL` | PostgreSQL/Supabase | — |
| `SECRET_KEY` | signature des sessions | — |
| `SECURE_COOKIES` | cookies HTTPS | `true` |
| `DAILY_HOURS` | heures/jour | `8` |
| `WEEKLY_HOURS` | heures/semaine | `40` |
| `WORKING_DAYS` | jours contractuels | `5` |
| `INTERVAL_MINUTES` | granularité | `30` |
| `OTP_DELIVERY_MODE` | email / totp / auto | `auto` |
| `EMAIL_PROVIDER` | Brevo / SMTP | `brevo` |
| `BREVO_API_KEY` | clé API Brevo | — |
| `BREVO_FROM_EMAIL` | expéditeur OTP | — |
| `BREVO_FROM_NAME` | nom expéditeur | `WFM Planning & Scheduling` |
| `EMAIL_OTP_TTL_SECONDS` | durée OTP | `600` |
| `EMAIL_OTP_RESEND_COOLDOWN_SECONDS` | délai de renvoi | `60` |
| `EMAIL_OTP_MAX_ATTEMPTS` | essais maximum | `5` |

Voir `render.yaml` pour la configuration Render complète.

---

# 9. Déploiement sur Render

Le service Render utilise la branche `main`.

Configuration prévue :

```text
Build:
pip install -r requirements.txt

Start:
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT

Health:
 /health
```

À chaque déploiement, Alembic applique les migrations avant le démarrage de FastAPI.

### Checklist après déploiement

1. Vérifier les logs Render.
2. Vérifier `/health`.
3. Ouvrir `/login`.
4. Vérifier l'authentification OTP/TOTP.
5. Vérifier `/settings`.
6. Vérifier `/workforce`.
7. Créer ou charger une campagne/skill.
8. Créer un LTF.
9. Créer un STF.
10. Générer une journée Daily/Intraday.
11. Vérifier Scheduling et Dashboard.

---

# 10. Tests

Tous les tests :

```bash
pytest -q
```

Tests unitaires :

```bash
pytest tests/unit
```

Tests d'intégration :

```bash
pytest tests/integration
```

Le dépôt utilise GitHub Actions pour exécuter la suite automatiquement.

---

# 11. Documentation associée

- [WFM Architecture Plan](./WFM_ARCHITECTURE_PLAN.md)
- [WFM Calculation Engine V2](./WFM_CALCULATION_ENGINE_V2.md)
- [Workforce / Agents](./WFM_WORKFORCE_AGENTS.md)
- [Mode d'emploi complet](./WFM_USER_GUIDE.md)

L'application contient également le **Mode d'emploi intégré** à `/guide`.

---

# 12. Bonnes pratiques d'utilisation

**Ne pas saisir deux fois la même information.**  
Le forecast se saisit dans LTF/STF, les agents dans Workforce, les indisponibilités dans
Absences, le planning dans Scheduling et les mesures réelles dans Actuals.

**Ne pas confondre besoin et capacité.**

```text
Required = ce qu'il faut
Scheduled = ce qui est planifié
Actual = ce qui s'est réellement passé
```

**Contrôler les breaks après chaque génération de planning.**

**Utiliser le STF Client lorsque le client fournit déjà un staffing intervalisé**, afin
que le besoin opérationnel reste cohérent entre Dashboard, Planner, pauses et Overtime.

---

# 13. Structure du projet

```text
app/
├── main.py
├── core/          # configuration, sécurité, DB, temps, unités
├── models/        # SQLModel
├── schemas/       # validation des entrées
├── services/      # moteur métier WFM
├── routers/       # routes FastAPI
├── templates/     # interface Jinja2
└── static/        # CSS / JS / Chart.js

alembic/
└── versions/      # migrations PostgreSQL

tests/
├── unit/
└── integration/
```

Principe : **les calculs métier vivent dans `services/`**, pas dans les templates ni dans
les routers.

---

## Licence / usage

Projet WFM Planning & Scheduling développé pour la planification, le capacity planning,
le forecasting, le scheduling et le pilotage opérationnel des centres de contacts.
