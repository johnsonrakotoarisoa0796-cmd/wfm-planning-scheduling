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


def normalized_workload_hours(volume_contacts: float, aht_seconds: float, channel: Channel) -> float:
    """Charge agent ajustée de la simultanéité du canal."""
    if volume_contacts < 0 or aht_seconds < 0:
        raise ValueError("volume_contacts et aht_seconds doivent être positifs ou nuls.")
    return (volume_contacts * aht_seconds / 3600.0) / concurrency_for_channel(channel)
