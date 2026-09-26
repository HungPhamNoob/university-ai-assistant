# services/agent/tools.py
"""
Public tool registry of the agent service.

Other modules should import tools from here so the exact tool set of each
agent stays visible in one place:

- booking_agent: list_meeting_rooms, book_meeting_room, list_my_bookings,
  cancel_booking, reschedule_booking
- faq_agent:     search_uet_knowledge
- search_agent:  TavilySearchResults (name='search_web')
"""

from .agents.booking import (
    book_meeting_room,
    cancel_booking,
    list_meeting_rooms,
    list_my_bookings,
    reschedule_booking,
)
from .agents.faq import search_uet_knowledge

BOOKING_TOOLS = [
    list_meeting_rooms,
    book_meeting_room,
    list_my_bookings,
    cancel_booking,
    reschedule_booking,
]

__all__ = [
    "BOOKING_TOOLS",
    "book_meeting_room",
    "cancel_booking",
    "list_meeting_rooms",
    "list_my_bookings",
    "reschedule_booking",
    "search_uet_knowledge",
]
