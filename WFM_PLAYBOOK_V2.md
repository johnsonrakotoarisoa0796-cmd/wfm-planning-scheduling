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


### Dispersion STF → Daily / Intraday par pondération

Depuis le détail d'un STF, **Disperser vers Daily** ouvre le calcul de dispersion hebdomadaire. Le WFM saisit les poids de contacts du lundi au dimanche.

Exemple :
- Lundi 13%
- Mardi 14%
- Mercredi 16%
- Jeudi 17%
- Vendredi 14%
- Samedi 13%
- Dimanche 13%

La somme doit être exactement **100%**. Pour un STF de 53 200 contacts :
- lundi = 53 200 × 13% = 6 916
- mardi = 53 200 × 14% = 7 448
- mercredi = 53 200 × 16% = 8 512
- jeudi = 53 200 × 17% = 9 044
- vendredi = 53 200 × 14% = 7 448
- samedi = 53 200 × 13% = 6 916
- dimanche = 53 200 × 13% = 6 916

Le système génère ensuite **7 journées × 48 intervalles de 30 minutes = 336 intervalles**, puis calcule le HC requis par intervalle avec les hypothèses STF (AHT, SL, occupancy, shrinkage et fuseau du marché).

### Profil intraday journalier par défaut

Après la pondération STF → 7 jours, le volume de chaque journée est réparti dans un profil de 33 intervalles de 30 minutes par défaut :

| Heure | Poids |
|---|---:|
| 10:00 | 1% |
| 10:30 | 1% |
| 11:00 | 1% |
| 11:30 | 2% |
| 12:00 | 3% |
| 12:30 | 3% |
| 13:00 | 3% |
| 13:30 | 3% |
| 14:00 | 4% |
| 14:30 | 4% |
| 15:00 | 2% |
| 15:30 | 2% |
| 16:00 | 2% |
| 16:30 | 2% |
| 17:00 | 2% |
| 17:30 | 2% |
| 18:00 | 2% |
| 18:30 | 2% |
| 19:00 | 2% |
| 19:30 | 2% |
| 20:00 | 2% |
| 20:30 | 2% |
| 21:00 | 5% |
| 21:30 | 5% |
| 22:00 | 5% |
| 22:30 | 5% |
| 23:00 | 5% |
| 23:30 | 5% |
| 00:00 | 5% |
| 00:30 | 5% |
| 01:00 | 3% |
| 01:30 | 4% |
| 02:00 | 4% |

La somme est exactement 100%. Ce profil est modifiable avant la génération. Pour chaque journée calculée, le moteur applique le volume journalier multiplié par le poids intraday afin d'obtenir le volume de chaque intervalle, puis calcule le HC requis.
### Remplacement et hypothèses Daily / Intraday

Lorsqu'une dispersion STF a déjà produit des intervalles pour la semaine/campagne/skill, l'écran affiche le nombre d'intervalles existants. Pour régénérer, le WFM coche **Remplacer les intervalles existants**, puis confirme l'opération. Les anciens intervalles de cette combinaison sont supprimés puis régénérés ; le STF lui-même n'est pas supprimé.

Avant génération, les hypothèses suivantes sont modifiables :
- Handling Time / AHT utilisé par le calcul HC intraday.
- Taux d'absentéisme proposé et taux de congés proposé.
- Heures d'absentéisme et de congés proposées sont calculées sur une base de 8 h/agent/jour.
- Taux de break 15 minutes par tranche.
- Taux de lunch par tranche.

Le moteur ajoute ces indisponibilités au shrinkage STF pour calculer le HC requis de chaque intervalle. Les taux de pause sont spécifiques à chaque tranche et sont stockés avec l'intervalle pour permettre l'audit des hypothèses utilisées lors de la génération.
