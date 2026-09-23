# WFM Planning & Scheduling — Mode d'emploi complet

Ce guide décrit un parcours concret de bout en bout. Pour une première utilisation,
suivre les étapes dans l'ordre.

## Parcours recommandé

```text
1. Marchés
2. Configuration
3. Workforce / Agents
4. Workforce de campagne
5. Paramètres hebdomadaires
6. LTF
7. STF
8. STF Client (facultatif)
9. Daily / Intraday
10. Capacity
11. Shifts
12. Absences / Compliance
13. Generate Schedule
14. Planner / Schedule Board
15. Shrinkage
16. Overtime
17. Imports Actuals
18. Dashboard / Control Tower
19. Forecast Lab
20. AI Copilot
```

## Exemple de scénario

Supposons une activité :

```text
Marché     : UK
Campagne   : SUP-UK
Skill      : Message Us
Agents     : 140
Contrat    : 40 h/semaine
Fuseau     : Europe/London
LTF        : 52 000 contacts
STF        : 53 200 contacts
AHT        : selon l'hypothèse de votre activité
Concurrency: 2
```

### 1. Référentiel

Dans **Marchés**, créer/vérifier UK.

Dans **Configuration**, créer :

```text
SUP-UK / Support UK
Message Us
Concurrency = 2
```

### 2. Workforce

Dans **Workforce / Agents**, générer les 140 agents fictifs pour une simulation
ou importer les agents réels.

Vérifier ensuite dans la liste :

- statut active ;
- campagne ;
- skill ;
- contrat 40 h ;
- fuseau Europe/London.

### 3. LTF

Dans **LTF Weekly**, saisir la période de référence et le volume.

Le résultat à surveiller est notamment :

```text
Handling Hours
Agent Workload Hours
Net Required HC
Gross Required HC
Paid Hours
Productive Hours
```

### 4. STF

Créer le STF pour la semaine opérationnelle.

Comparer :

```text
LTF
STF
Variance
Variance %
```

### 5. Daily / Intraday

Générer la journée à partir du STF.

Le système répartit le volume sur 30 minutes et calcule le Required HC par intervalle.

Contrôler particulièrement le pic de trafic.

### 6. Scheduling

Créer d'abord les shifts.

Exemple :

```text
07:00 → 16:00
2 × 15 min break
60 min lunch
```

Puis utiliser **Generate Schedule**.

### 7. Contrôle

Après génération :

```text
Schedule Board → couverture visuelle
Planner       → analyse par intervalle
Control Tower → Required / Scheduled / Actual
Dashboard     → synthèse KPI
```

### 8. Actuals

Après la journée, importer les actuals.

Le système peut alors comparer les valeurs forecast/actual et calculer l'accuracy
sur les intervalles réellement réalisés.

### 9. Overtime

Calculer l'OT requis et, quand il est connu, saisir l'OT réel séparément.

### 10. Forecast Lab

Analyser l'accuracy, le WAPE, le bias et la dérive AHT.

---

## Comment lire les indicateurs

### Required HC

Nombre d'agents nécessaires selon la demande, les paramètres WFM et le modèle de canal.

### Scheduled HC

Nombre d'agents placés au planning.

### Actual HC

Nombre d'agents réellement présents/staffés.

### Staffing Gap

Écart entre capacité et besoin. Toujours lire le signe avec le contexte de l'écran.

### Occupancy

Charge productive rapportée à la capacité disponible.

### Shrinkage

Part de capacité perdue pour les activités non productives ou indisponibilités.

### Forecast Accuracy

Mesure de proximité entre forecast et actual, sur les intervalles observés.

### WAPE

Erreur absolue pondérée par le volume réel. Utiliser ce KPI avec le volume de la période
et pas isolément.

---

## Quand utiliser quel module ?

| Besoin | Module |
|---|---|
| Pays / fuseau / langue | Marchés |
| Campagne / skill / canal | Configuration |
| Agents | Workforce / Agents |
| Effectif par campagne | Workforce campagne |
| Plan long terme | LTF |
| Ajustement semaine | STF |
| Staffing client par intervalle | STF Client |
| Besoin 30 min | Daily / Intraday |
| Projection HC | Capacity |
| Horaires types | Scheduling → Shifts |
| Affectation des agents | Scheduling |
| Génération automatique | Generate Schedule |
| Règles sociales | Compliance |
| Absences datées | Absences & congés |
| Pertes de capacité | Shrinkage |
| OT requis / réel | Overtime |
| Réalité ACD / opérations | Imports Actuals |
| Synthèse | Dashboard |
| Pilotage intraday | Control Tower |
| Qualité forecast | Forecast Lab |
| Analyse assistée | AI Copilot |

---

## Règle simple pour éviter les incohérences

Toujours suivre cette logique :

```text
DEMANDE
LTF → STF → STF Client / Daily

CAPACITÉ
Workforce → Absences → Capacity

PLANNING
Shifts → Scheduling → Generate Schedule

RÉALITÉ
Imports Actuals → KPI

PILOTAGE
Dashboard → Control Tower → Forecast Lab
```

Ne jamais remplacer une source par une valeur saisie manuellement dans une autre page
sans comprendre la relation entre les deux.

---

## Vérification avant de publier un planning

```text
[ ] Workforce à jour
[ ] Absences à jour
[ ] Compliance configurée
[ ] LTF actif
[ ] STF actif
[ ] STF Client chargé si applicable
[ ] Daily / Intraday généré
[ ] Shifts actifs
[ ] Generate Schedule exécuté
[ ] Couverture vérifiée
[ ] Breaks vérifiés
[ ] Schedule Board contrôlé
[ ] Overtime analysé
```

Après publication, passer au pilotage **Actuals → Dashboard → Control Tower**.
