# WFM Planning & Scheduling — Phase 1 : Audit & Architecture cible

**Statut :** Document de cadrage avant implémentation (Phase 1 uniquement — aucun code n'a été écrit).
**Portée :** Nouvelle plateforme WFM (contact center) — FastAPI / SQLModel / PostgreSQL / Jinja2 / Render.

---

## 0. Hypothèse de départ — À confirmer avant la Phase 2

Le prompt demande d'auditer "le repository existant", mais aucun dépôt GitHub n'a été partagé pour ce projet WFM (ce n'est pas `mahay-toamasina`, qui est un projet distinct pour les étudiants malgaches).

**Hypothèse retenue :** ce projet WFM est un **nouveau repository, séparé de MAHAY**, construit from scratch mais en réutilisant les patterns qui fonctionnent déjà chez toi (FastAPI + SQLModel + Jinja2 + Alembic + Render, HTML server-rendered sans framework JS, commits en français, workflow `git format-patch` / `git am`).

Si un dépôt WFM existe déjà quelque part (même partiel), donne-moi le nom/l'URL et je l'audite avant de continuer — je ne veux pas écraser quoi que ce soit d'existant, conformément à la règle absolue du brief.

---

## 1. Résultat de l'audit

- Aucun code WFM existant identifié dans cette conversation.
- Aucune contrainte héritée d'un projet précédent, si ce n'est ton stack habituel (validé comme pertinent pour ce cahier des charges, qui demande explicitement FastAPI/SQLModel/Jinja2/PostgreSQL).
- Risque de régression : **nul** pour l'instant, tant qu'on part sur un nouveau repository. Le risque principal serait de développer en double si un dépôt existe déjà ailleurs (cf. section 0).

---

## 2. Architecture cible

### 2.1 Stack technique

| Couche | Choix | Justification |
|---|---|---|
| Backend | FastAPI + SQLModel + Pydantic v2 | Demandé explicitement, cohérent avec MAHAY |
| Calculs | Pandas / NumPy dans les services, jamais dans les templates | Séparation calcul/présentation (§40) |
| DB | PostgreSQL, migrations Alembic | Demandé explicitement |
| Frontend | Jinja2 + HTML/CSS/JS vanilla + Chart.js | Pas de framework JS, cohérent avec MAHAY |
| Auth | Sessions cookie + hashing bcrypt + RBAC | Cohérent avec le pattern déjà éprouvé sur MAHAY (TOTP optionnel en V1.1) |
| Déploiement | GitHub + Render + Postgres managé | Demandé explicitement |

### 2.2 Arborescence cible

```
wfm-planning-scheduling/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings), lit les env vars Render
│   │   ├── security.py            # hashing, session, RBAC dependencies
│   │   ├── database.py            # engine, session factory
│   │   └── units.py               # seconds_to_minutes(), minutes_to_hours(), hours_to_minutes()
│   ├── models/                    # SQLModel — un fichier par domaine
│   │   ├── user.py
│   │   ├── campaign.py
│   │   ├── skill.py
│   │   ├── employee.py
│   │   ├── shift.py
│   │   ├── forecast.py            # ForecastVersion, LTFForecast, STFForecast
│   │   ├── intraday.py            # DailyForecast, IntervalForecast, ActualPerformanceRaw
│   │   ├── shrinkage.py           # ShrinkageCategory, ShrinkageRecord
│   │   ├── capacity.py            # CapacityPlan
│   │   ├── overtime.py            # OvertimePlan
│   │   ├── schedule.py            # ScheduleEntry
│   │   ├── sla.py                 # SLAProfile
│   │   └── config_parameter.py    # ConfigParameter (Settings)
│   ├── schemas/                   # Pydantic I/O (request/response), un fichier miroir par modèle
│   ├── services/                  # TOUTE la logique métier vit ici
│   │   ├── forecast_service.py    # versioning LTF/STF, calcul des écarts
│   │   ├── kpi_service.py         # AHT, Occupancy, SL, ASA, Forecast Accuracy...
│   │   ├── erlang_service.py      # Erlang C pur, sans dépendance DB/framework
│   │   ├── capacity_service.py
│   │   ├── shrinkage_service.py
│   │   ├── overtime_service.py
│   │   └── scheduling_service.py
│   ├── routers/                   # un router par module de nav
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── ltf.py
│   │   ├── stf.py
│   │   ├── daily.py
│   │   ├── capacity.py
│   │   ├── scheduling.py
│   │   ├── kpi.py
│   │   ├── shrinkage.py
│   │   ├── overtime.py
│   │   ├── reports.py
│   │   ├── imports.py             # import CSV/Excel avec validation
│   │   └── settings.py
│   ├── templates/                 # un sous-dossier Jinja2 par module
│   └── static/
│       ├── css/
│       └── js/                    # Chart.js config, filtres
├── alembic/
│   └── versions/
├── tests/
│   ├── unit/                      # AHT, Erlang, Shrinkage, OT, Occupancy, SL, ASA...
│   └── integration/                # DB, API, Dashboard, Forecast
├── requirements.txt
├── render.yaml
├── .env.example
└── README.md
```

### 2.3 Convention d'unités (règle §39)

Toute variable numérique porte son unité dans le nom :
`aht_seconds`, `volume_contacts`, `interval_minutes`, `paid_hours`, `required_hc`, `shrinkage_pct`, `asa_seconds`.
Les conversions passent **toujours** par `core/units.py` (jamais de `/60` ou `*60` en dur ailleurs).

---

## 3. Modèle de données (PostgreSQL / SQLModel)

### 3.1 Référentiel

**User** — `id, email, hashed_password, role (admin/wfm_analyst/team_lead/viewer), is_active, created_at`

**Campaign** — `id, name, code, description, is_active`

**Skill** — `id, campaign_id→Campaign, name, channel (voice/chat/email/backoffice), is_active`

**Employee** — `id, first_name, last_name, employee_code, campaign_id→Campaign, hire_date, termination_date?, status (active/leave/terminated), weekly_hours_contract (default 40)`

**EmployeeSkill** (table de liaison M2M) — `employee_id, skill_id, is_primary`

**Shift** — `id, name, start_time, end_time, break_minutes, lunch_minutes, is_active`

**ScheduleEntry** — `id, employee_id→Employee, shift_id→Shift, date, campaign_id, skill_id, is_day_off, break_start?, break_end?, lunch_start?, lunch_end?`
→ Permet de calculer le "HC disponible avant/après break" par intervalle (§34).

### 3.2 Forecast — cœur du système (LTF → STF → Daily)

**ForecastVersion** (table pivot de versioning — jamais d'écrasement silencieux)
```
id
version_type        enum: LTF | STF
period_start         date
period_end           date
campaign_id          → Campaign
skill_id             → Skill
parent_version_id    → ForecastVersion (nullable ; un STF pointe vers le LTF ou le STF précédent)
label                ex: "STF Semaine 32 - 2026"
created_by           → User
created_at           timestamp
notes                text
is_current           bool (une seule version "courante" par période/campagne/skill)
```

**LTFForecast** — `id, forecast_version_id→ForecastVersion, year, month, campaign_id, skill_id, forecast_volume, forecast_aht_seconds, aht_required_seconds, occupancy_required_pct, service_level_target_pct, asa_target_seconds, headcount_required, paid_hours, productive_hours, production_hours, waiting_hours, indoor_shrinkage_pct, outdoor_shrinkage_pct, total_shrinkage_pct, available_hours, staffing_gap, overtime_required_hours`

**STFForecast** — mêmes colonnes que LTFForecast mais indexées par `(iso_year, iso_week, week_start_date)` au lieu de `(year, month)`, avec `forecast_version_id` pointant vers une version `STF`. Les écarts (`adjustment`, `adjustment_pct`) ne sont **jamais stockés** : ils sont calculés à la volée par `forecast_service.py` en comparant la STF à sa LTF parente (§9).

### 3.3 Intraday

**DailyForecast** — `id, date, campaign_id, skill_id, forecast_volume, forecast_aht_seconds, actual_volume?, actual_aht_seconds?, required_hc, scheduled_hc, actual_hc?`

**IntervalForecast** (granularité 30 min, configurable) — `id, date, interval_start, interval_end, campaign_id, skill_id, forecast_volume, actual_volume?, forecast_aht_seconds, actual_aht_seconds?, required_hc, scheduled_hc, actual_hc?, service_level_pct?, asa_seconds?, occupancy_pct?, abandon_rate_pct?, staffing_gap?, overtime_required_hours?`

**ActualPerformanceRaw** (staging pour les imports, avant agrégation) — `id, date, interval_start, campaign_id, skill_id, offered, handled, abandoned, talk_time_seconds, hold_time_seconds, acw_seconds, agents_staffed, paid_hours, import_batch_id, imported_at`

### 3.4 Shrinkage / Capacity / Overtime

**ShrinkageCategory** — `id, name, type (indoor/outdoor), code, is_active` (extensible par l'admin, §23)

**ShrinkageRecord** — `id, employee_id, category_id→ShrinkageCategory, date, hours, campaign_id, skill_id, notes`

**CapacityPlan** — `id, campaign_id, skill_id, period (month), current_hc, required_hc, hiring, transfers_in, transfers_out, attrition_pct, absenteeism_pct, projected_hc, notes, created_by`

**OvertimePlan** — `id, campaign_id, skill_id, period_type (daily/weekly/monthly), period_key, required_hours, available_hours, gap_hours, ot_required_hours, ot_actual_hours?, notes`
→ `ot_required_hours` est calculé ; `ot_actual_hours` reste nul tant qu'aucune donnée réelle (import paie/pointage ou saisie manuelle) n'est fournie — **jamais confondus** (§30).

### 3.5 Service Level vs SLA (§15 — volontairement distincts)

**SLAProfile** — `id, campaign_id, name, service_level_target_pct, answer_time_threshold_seconds, exclude_short_abandon (bool), short_abandon_threshold_seconds, extra_rules_json`
- Le **Service Level** est un KPI pur : `% répondu ≤ seuil`.
- La **SLA** est un profil configurable qui peut inclure le Service Level *et* d'autres engagements contractuels (abandon max, AHT max...) — `extra_rules_json` permet d'étendre sans migration à chaque nouvelle règle.

### 3.6 Paramétrage

**ConfigParameter** — `id, key, value, scope (global/campaign/skill), campaign_id?, skill_id?`
Valeurs initiales : `daily_hours=8`, `weekly_hours=40`, `working_days=5`, `interval_minutes=30`, `occupancy_target_pct`, `aht_target_seconds`, etc. — **jamais codées en dur** dans les services (§19, §38).

### 3.7 Index recommandés

- `IntervalForecast(date, campaign_id, skill_id)`
- `DailyForecast(date, campaign_id, skill_id)`
- `LTFForecast(year, month, campaign_id, skill_id)`
- `STFForecast(iso_year, iso_week, campaign_id, skill_id)`
- `ScheduleEntry(employee_id, date)`
- `ShrinkageRecord(employee_id, date)`
- `ForecastVersion(campaign_id, skill_id, is_current)`

---

## 4. Relation LTF → STF → Daily (versioning, §9)

```
LTFForecast (mois M)
      │  ForecastVersion(type=LTF, is_current=True)
      ▼
STFForecast (semaine 1)  ──parent_version_id──▶ Version LTF
STFForecast (semaine 2)  ──parent_version_id──▶ Version STF semaine 1 (ou LTF, selon règle retenue)
STFForecast (semaine 3)  ──...
      ▼
DailyForecast / IntervalForecast (réajustement journalier optionnel, mêmes principes)
      ▼
ActualPerformanceRaw (réalité importée)
```

- Aucune version n'est jamais écrasée : chaque révision crée une nouvelle ligne `ForecastVersion` + son flag `is_current`.
- `forecast_service.py` expose `compare_versions(version_a, version_b)` → renvoie volume/AHT/HC/shrinkage/occupancy/SL/OT avec `adjustment` et `adjustment_pct` calculés à la volée (formules §8 du brief).
- Le tableau "LTF vs STF vs Actual" (§47) est une vue calculée, pas une table stockée.

---

## 5. KPI Engine (`kpi_service.py`) — formules de référence

| KPI | Formule | Unité |
|---|---|---|
| Handle Time | `talk_time_s + hold_time_s + acw_s` | secondes |
| AHT | `total_handle_time_s / handled_contacts` | secondes |
| Occupancy | `handle_time_hours / (handle_time_hours + waiting_hours)` | % |
| Service Level | `answered_within_threshold / (offered − excluded)` | % |
| ASA | `total_wait_time_s / answered_contacts` | secondes |
| Shrinkage % | `total_shrinkage_hours / paid_hours × 100` | % |
| Paid Hours | `employees × daily_hours × working_days` (paramétrable) | heures |
| Productive Hours | `paid_hours − total_shrinkage_hours` | heures |
| Production Hours | `productive_hours − waiting_hours` | heures |
| Forecast Accuracy | `1 − ABS(forecast − actual) / actual` | % |
| Staffing Gap | `available_or_scheduled − required` | HC |

Toutes ces fonctions sont pures (entrée typée → sortie typée), testables unitairement, **jamais** dans un template Jinja ou du JS.

> ⚠️ Point à valider avec toi : la distinction *Production Hours* vs *Waiting Time* a deux lectures possibles dans l'industrie WFM (temps productif = traitement uniquement vs temps productif = traitement + attente active). J'ai retenu la définition ci-dessus par cohérence avec le reste du brief, mais elle sera **documentée et paramétrable** — dis-moi si tu veux l'autre convention.

---

## 6. Erlang C Engine (`erlang_service.py`)

Module **isolé, sans dépendance DB ni FastAPI** — fonctions pures :

```
calculate_traffic_intensity(volume, aht_seconds, interval_seconds) -> erlangs
calculate_erlang_c(erlangs, agents, aht_seconds, interval_seconds) -> probability_of_wait
find_required_agents(volume, aht_seconds, interval_seconds,
                      service_level_target_pct, answer_time_target_seconds) -> net_required_hc
apply_shrinkage(net_required_hc, shrinkage_pct) -> gross_required_hc
```

Algorithme itératif classique (incrémentation du nombre d'agents jusqu'à satisfaire le SL cible), testé unitairement sur des cas de référence connus (valeurs de table Erlang C publiques) pour garantir la fiabilité (§18, §41).

---

## 7. Overtime Engine (`overtime_service.py`)

```
daily_ot(required_hours, available_hours)   = max(0, required_hours - available_hours)
weekly_ot(daily_ot_list)                    = sum(daily_ot_list)
monthly_ot(weekly_ot_list)                  = sum(weekly_ot_list)
ot_variance(required_ot, actual_ot)         = actual_ot - required_ot
```

`OvertimePlan.ot_required_hours` est toujours calculé par le moteur ; `ot_actual_hours` provient d'un import ou d'une saisie manuelle — les deux colonnes coexistent sans jamais se confondre (§30).

---

## 8. Sécurité (§49)

- Hashing mots de passe : `passlib[bcrypt]`
- Sessions cookie signées (`itsdangerous`) + RBAC via dependency FastAPI (`require_role(...)`)
- Validation stricte des entrées via schémas Pydantic (routers n'acceptent jamais de dict brut)
- Aucune requête SQL brute : SQLModel/SQLAlchemy uniquement
- CSRF sur tous les POST HTML (cohérent avec MAHAY)
- Secrets exclusivement via variables d'environnement Render, `.env.example` versionné sans valeurs réelles

---

## 9. Déploiement Render (§50)

- `requirements.txt` : fastapi, uvicorn[standard], sqlmodel, alembic, psycopg2-binary, pydantic, pandas, numpy, jinja2, python-multipart, passlib[bcrypt], itsdangerous, python-dotenv, pytest, httpx, openpyxl
- `render.yaml` : service web (build/start command) + base Postgres managée Render
- `.env.example` : `DATABASE_URL`, `SECRET_KEY`, `ENV=production`
- Stratégie de migration : Alembic, une migration par étape fonctionnelle (comme sur MAHAY)

---

## 10. Fichiers à créer (Phase 1 → Phase 2)

Tous les fichiers listés dans l'arborescence §2.2 seront créés progressivement, phase par phase (aucun fichier à *modifier*, projet neuf).

---

## 11. Plan d'implémentation par étapes (commits séquentiels, §51)

| # | Commit | Contenu | Livrable vérifiable |
|---|---|---|---|
| 01 | Initialize WFM platform | squelette FastAPI, config, `render.yaml`, README | app démarre, `/health` répond |
| 02 | Add database models | tous les modèles SQLModel + première migration Alembic | `alembic upgrade head` OK |
| 03 | Add authentication | login/logout, hashing, sessions, RBAC | login fonctionnel, routes protégées |
| 04 | Add KPI engine | `kpi_service.py` + tests unitaires | tests verts sur AHT/Occupancy/SL/ASA/Shrinkage |
| 05 | Add Erlang engine | `erlang_service.py` isolé + tests sur valeurs de référence | tests verts |
| 06 | Add LTF monthly | modèle + router + templates + graphiques | CRUD LTF fonctionnel |
| 07 | Add STF weekly | versioning, comparaison LTF vs STF | écarts calculés correctement |
| 08 | Add Daily/Intraday | intervalles 30 min, forecast vs actual | vue intraday fonctionnelle |
| 09 | Add capacity planning | `capacity_service.py` + page dédiée | projection HC correcte |
| 10 | Add shrinkage | catégories + saisie + calculs % | rapports shrinkage OK |
| 11 | Add overtime | `overtime_service.py` + required/actual | distinction claire required vs actual |
| 12 | Add scheduling | shifts, ScheduleEntry, impact des breaks | staffing avant/après break visible |
| 13 | Add dashboard | vue consolidée avec statuts couleur | tous les KPI du §5 affichés |
| 14 | Add reporting | exports CSV/Excel respectant les filtres | export conforme aux filtres actifs |
| 15 | Add data import | import CSV/Excel avec validation/preview | rejet propre des données invalides |
| 16 | Production hardening | tests d'intégration, durcissement sécurité, déploiement Render | déploiement Render stable |

Chaque étape suit le cycle : Code → Database → API → Calculs → UI → Tests → vérification de non-régression, avant de passer à la suivante.

---

## 12. Points à confirmer avant de démarrer la Phase 2

1. **Repository** : nouveau dépôt séparé de `mahay-toamasina` — quel nom lui donner ?
2. **PostgreSQL** : base Render native, ou Supabase comme pour MAHAY ?
3. **Authentification** : sessions cookie (cohérent avec MAHAY) — TOTP 2FA dès la V1 ou plus tard ?
4. **Rôles utilisateurs** : `admin / wfm_analyst / team_lead / viewer` te conviennent, ou faut-il en ajouter/retirer ?
5. **Production Hours vs Waiting Time** : confirmer la définition retenue en §5, ou préciser l'autre convention.
6. **Format des imports historiques** : structure CSV exacte (colonnes, séparateur, encodage) si tu as déjà un export type de ton ACD/outil actuel.
7. **Workflow** : on garde le même mode opératoire que MAHAY (patches `git format-patch` appliqués via `git am`, commits en français, push direct sur `main`) ?

Dès que tu valides (ou corriges) ces points, je démarre la Phase 2 (commit 01 — squelette + config + déploiement Render de base).
