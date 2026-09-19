"""Règles de capacité par canal.

Les canaux asynchrones autorisent plusieurs conversations/emails traités
simultanément par un agent. Ce facteur réduit le nombre d'agents nécessaire
pour une même charge de travail.
"""
from __future__ import annotations

from app.models.enums import Channel


CHANNEL_LABELS = {
    Channel.VOICE: "Phone",
    Channel.EMAIL: "Email",
    Channel.CHAT: "Message Us",
    Channel.BACKOFFICE: "Backoffice",
}

CHANNEL_CONCURRENCY = {
    Channel.VOICE: 1.0,
    Channel.EMAIL: 3.0,
    Channel.CHAT: 2.0,
    Channel.BACKOFFICE: 1.0,
}


def channel_label(channel: Channel) -> str:
    return CHANNEL_LABELS.get(channel, str(channel.value))


def concurrency_for_channel(channel: Channel) -> float:
    value = CHANNEL_CONCURRENCY.get(channel, 1.0)
    if value <= 0:
        raise ValueError("La simultanéité du canal doit être strictement positive.")
    return value


def normalized_workload_hours(
    volume_contacts: float,
    aht_seconds: float,
    channel: Channel,
) -> float:
    """Charge agent ajustée de la simultanéité du canal."""
    if volume_contacts < 0 or aht_seconds < 0:
        raise ValueError("volume_contacts et aht_seconds doivent être positifs ou nuls.")
    return (volume_contacts * aht_seconds / 3600.0) / concurrency_for_channel(channel)


def required_hc_for_async(
    volume_contacts: float,
    aht_seconds: float,
    interval_seconds: int,
    occupancy_target_pct: float,
    channel: Channel,
) -> float:
    """Agents requis pour Email/Message Us via charge + simultanéité."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds doit être strictement positif.")
    if occupancy_target_pct <= 0 or occupancy_target_pct > 100:
        raise ValueError("occupancy_target_pct doit être dans ]0,100].")
    workload_hours = normalized_workload_hours(volume_contacts, aht_seconds, channel)
    interval_hours = interval_seconds / 3600.0
    return workload_hours / (interval_hours * (occupancy_target_pct / 100.0))


def is_realtime_channel(channel: Channel) -> bool:
    return channel in {Channel.VOICE}


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
    return adjusted_workload / (
        available_hours_per_agent * (occupancy_target_pct / 100.0)
    )
