# WFM Calculation Engine — Rules

## Units

- AHT / ASA / talk / hold / ACW: seconds.
- Contact volume: contacts.
- Workload / paid / productive / production / overtime: agent-hours.
- Staffing: HC, with interval staffing multiplied by the logical interval duration.
- Default interval: 30 minutes = 0.5 hour, including 23:30–24:00.

## LTF / STF

Contact handling hours:

`Volume × AHT / 3600`

Agent workload hours:

`Contact handling hours / concurrency`

Net required HC:

`Agent workload hours / (available hours per agent × occupancy target)`

Gross required HC:

`Net required HC / (1 - shrinkage)`

Paid hours:

`Gross HC × contract daily hours × contractual working days`

Productive hours:

`Paid hours - shrinkage hours`

Production hours:

`Productive hours - waiting hours`

For Voice, concurrency is 1. Email and Message Us use the configured skill concurrency factor.

## Intraday

Intraday is the SLA/staffing precision layer.

Voice uses Erlang C per interval. The engine searches the minimum integer HC satisfying both Service Level and Occupancy constraints.

Async channels use workload, concurrency and occupancy; SLA for async queues is not represented as Erlang C.

Client STF overrides the modeled Required HC only for intervals covered by the current Client STF plan.

## Actuals

Actual AHT:

`(Talk + Hold + ACW) / Handled`

When the import contains `answered_within_threshold`, Service Level is measured directly from that ACD counter. Otherwise, the application may keep an estimated operational metric.

Intraday Forecast Accuracy compares actuals only against forecast for intervals that already have actual values. It never compares a partial-day actual to the full-day forecast.

## Shrinkage and breaks

The default break exposure represents 2 × 15 minutes per agent.

The default lunch exposure represents 60 minutes per agent.

Schedule-level break/lunch placement remains the source of truth for actual Scheduled HC coverage.

## Overtime

`OT Required = max(0, Required Hours - Available Hours)`

Daily, weekly and monthly plans must use the corresponding complete calendar period.

## Staffing invariants

- Coverage is capped at 100%.
- Logical 30-minute intervals always contribute exactly 0.5 agent-hour.
- Contact Handling Hours and Agent Workload Hours remain distinct metrics.
- Actualized forecast KPIs use only realized intervals.
- Client STF, Intraday, Schedule and Overtime use the same effective Required HC precedence.
