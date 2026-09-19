[object Object]

def required_hc_aggregate_channel(
    workload_hours: float,
    available_hours_per_agent: float,
    occupancy_target_pct: float,
    channel: Channel,
) -> float:
    """HC moyen requis en LTF/STF après prise en compte de la simultanéité."""
    if workload_hours < 0:
        raise ValueError("workload_hours doit être >= 0.")
    if available_hours_per_agent <= 0:
        raise ValueError("available_hours_per_agent doit être > 0.")
    if occupancy_target_pct <= 0 or occupancy_target_pct > 100:
        raise ValueError("occupancy_target_pct doit être dans ]0,100].")
    adjusted_workload = workload_hours / concurrency_for_channel(channel)
    return adjusted_workload / (available_hours_per_agent * (occupancy_target_pct / 100.0))
