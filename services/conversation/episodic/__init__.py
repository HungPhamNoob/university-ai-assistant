"""Episodic memory subsystem of the Conversation service.

Rolling per-thread episode summaries stored in SQL (canonical and only store).
Memory is independent per thread: each conversation summarizes its own old
messages and no episode is shared across threads.
"""
