# WFM Planning & Scheduling — Mode d'emploi V2

## 1. Parcours quotidien recommandé

1. **Configuration** — créer campagnes, skills, marchés, shifts, rattachements agents et absences. Dans **Workforce**, renseigner Current HC, Available HC, long leave, congés, absences imprévues, training, nesting, attrition, recrutements, transferts et Required HC.
2. **Forecast** — créer le LTF, réviser avec le STF, puis générer Daily/Intraday ou charger un STF Client intervalisé.
3. **Scheduling** — utiliser Generate Schedule, contrôler le résultat dans Schedule Board, puis vérifier Planner et Break Impact.
4. **Pilotage** — ouvrir Control Tower pour surveiller les écarts intervalle par intervalle et simuler un mix de shifts.
5. **Agents** — l'administrateur lie un compte à un agent depuis Configuration. L'agent utilise ensuite /agent pour consulter son planning et déposer une demande de congé.

## 2. Chaîne de données

```text
Historical / Forecast
        ↓
      LTF
        ↓
      STF
        ↓
Daily / Intraday ou STF Client
        ↓
    Required HC
        ↓
Workforce + roster + absences
        ↓
Scheduler / Planner
        ↓
      Schedule
        ↓
   Control Tower
        ↓
      Actuals
```

## 3. KPI à lire

- Forecast Accuracy : écart forecast / actual volume.
- Required HC : besoin intervalle.
- Scheduled HC : effectif planifié.
- Actual HC : effectif réellement disponible lorsque fourni.
- Staffing Gap : capacité moins besoin.
- Coverage % : staffing disponible / Required HC.
- Shortage HC-h : sous-staffing cumulé.
- Surplus HC-h : sur-staffing cumulé.
- Projected Gap EOM : capacité workforce projetée moins besoin.

## 4. Control Tower

Elle répond à quatre questions : combien faut-il, combien est planifié, combien est réellement présent, et quelles actions peuvent être simulées.

## 5. Publication du planning

Avant publication : générer → Schedule Board → absences → pauses → Control Tower → exceptions / OT → publication.

## 6. V2 et évolutions

La plateforme est structurée pour recevoir forecasting multi-modèles, intégrations ACD/HR/payroll, Real-Time Adherence, reforecast intraday, optimisation multi-skill, préférences agents, self-swap, VTO, extra hours, simulation et reporting avancé.

## 7. Règle de gouvernance

Une recommandation du moteur n'est pas une décision. La publication reste une action WFM explicite.

> Vérification technique : la branche principale est validée par la suite pytest du repository avant publication des évolutions.


## 9. Compliance & Weekly Coverage

Le module **Compliance** permet de définir une politique par campagne, avec éventuellement une règle spécifique par skill :

- maximum de jours consécutifs travaillés ;
- maximum d'heures travaillées par jour ;
- maximum d'heures travaillées par semaine ;
- maximum d'overtime par semaine ;
- repos minimum entre deux shifts ;
- objectif de Weekly Coverage (%).

La politique est utilisée par la génération automatique du planning : un shift candidat qui vioule une règle de conformité est écarté. La saisie manuelle d'un planning applique également les règles actives.

Le contrôle hebdomadaire calcule :

```
Weekly Coverage =
  HC-hours couvertes / HC-hours requises × 100
```

Il affiche également shortage HC-hours, surplus HC-hours, écart à la cible et les violations détaillées par agent.

Le module **Generate Schedule** affiche le contrôle Compliance et Weekly Coverage après génération.
