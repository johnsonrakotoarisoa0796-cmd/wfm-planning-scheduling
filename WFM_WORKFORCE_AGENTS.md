# Workforce / Agents

Le module **Workforce / Agents** constitue le référentiel des agents utilisés par le WFM pour Capacity Planning, Scheduling, Absences et Generate Schedule.

## Deux sources de données

### 1. Agents fictifs

Utiliser **Workforce / Agents → Créer des agents fictifs** pour tester rapidement un périmètre sans stocker de données personnelles réelles.

Exemple UK / Message Us :

- Campagne : Support UK
- Skill : Message Us
- Nombre : 140
- Contrat : 40 h/semaine
- Fuseau : Europe/London

Les agents générés sont marqués `data_source=synthetic` et reçoivent un `employee_code` de type `SYN-...`.

### 2. Données réelles

Deux chemins sont disponibles : créer un agent réel unitairement, ou importer un CSV/XLS/XLSX pour un gros effectif.

Les données importées sont validées ligne par ligne. Le fichier entier est refusé si une erreur de structure, de campagne, de skill, de date, de statut ou de doublon est détectée.

Un `employee_code` déjà présent peut être mis à jour en activant l'option **Mettre à jour les agents existants**.

## Colonnes d'import

Obligatoires : `employee_code, first_name, last_name, campaign_code, skill_name, hire_date`

Optionnelles : `termination_date, weekly_hours_contract, timezone_name, status`

Valeurs de `status` : `active`, `leave`, `terminated`.

Exemple :

```csv
employee_code,first_name,last_name,campaign_code,skill_name,hire_date,termination_date,weekly_hours_contract,timezone_name,status
UKMSG001,John,Smith,SUP-UK,Message Us,2026-01-05,,40,Europe/London,active
UKMSG002,Sarah,Jones,SUP-UK,Message Us,2026-02-02,,40,Europe/London,active
```

## Sécurité des données

Le module ne demande que les informations utiles au WFM : identifiant agent, nom/prénom, affectation, contrat, dates, statut et fuseau. Éviter d'importer des informations RH ou personnelles inutiles.

Les données fictives et réelles restent distinguées afin de ne pas confondre un scénario de simulation avec le workforce réel.

## Chaîne WFM

`Workforce / Agents → Skills → Absences → Scheduling → Generate Schedule → Interval Scheduled HC → KPI / Control Tower`

Le `ScheduleEntry` existant référence directement `employee_id`; le générateur de planning peut donc travailler sur les agents enregistrés dans ce référentiel.
