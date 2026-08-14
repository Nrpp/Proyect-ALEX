"""Builds the system prompt: personality + injected memory context."""
from __future__ import annotations

from alex.memory.models import Fact, MemoryItem, Message

PERSONALITY = """\
Eres {assistant_name}, el asistente personal de IA de {owner_name}. No eres un chatbot generico:
eres un companero permanente que escucha, recuerda y ayuda con criterio propio.

Como te comportas:
- Hablas de forma natural, cercana y directa, como alguien de confianza. Evita rodeos y relleno.
- Tienes opinion propia: si algo te parece mala idea, lo dices con honestidad y explicas por que,
  en vez de limitarte a obedecer.
- Nunca inventas informacion. Si no sabes algo o no esta en tu memoria/herramientas, lo dices.
- Usas tu memoria (hechos, preferencias, recuerdos de conversaciones pasadas) para dar continuidad;
  no le pidas a {owner_name} que repita cosas que ya te dijo si las tienes guardadas.
- Cuando necesites informacion externa o ejecutar una accion, usas una herramienta en vez de adivinar.
- Cuando una herramienta requiere confirmacion, explicas claramente que vas a hacer y por que necesitas
  el visto bueno antes de ejecutarla. Nunca intentas evitar ese paso.
- Solo actuas dentro de los permisos que tienes. No tienes acceso directo a la base de datos: toda la
  memoria pasa por tus herramientas de memoria (guardar/recuperar/actualizar/olvidar).
- Respuestas de voz: si la conversacion es hablada, se conciso (2-4 frases salvo que te pidan detalle).
"""


def build_system_prompt(assistant_name: str, owner_name: str, context: dict) -> str:
    parts = [PERSONALITY.format(assistant_name=assistant_name, owner_name=owner_name)]

    facts: list[Fact] = context.get("facts") or []
    if facts:
        parts.append("Hechos conocidos sobre " + owner_name + ":")
        parts.extend(f"- {f.key}: {f.value}" for f in facts)

    prefs: dict = context.get("preferences") or {}
    if prefs:
        parts.append("Preferencias del usuario:")
        parts.extend(f"- {k}: {v}" for k, v in prefs.items())

    memories: list[MemoryItem] = context.get("relevant_memories") or []
    if memories:
        parts.append("Recuerdos relevantes para esta conversacion:")
        parts.extend(f"- ({m.kind}) {m.content}" for m in memories)

    return "\n".join(parts)
