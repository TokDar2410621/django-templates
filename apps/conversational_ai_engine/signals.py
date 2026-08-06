"""Signals emitted by the conversational AI engine.

Projects connect to :data:`on_generation_complete` to wire up downstream
behaviour (billing, analytics, quota deduction). The engine itself never
imports a billing app — the contract is purely the signal.

Example wiring (in a billing app's ``apps.py::ready``):

.. code-block:: python

   from conversational_ai_engine.signals import on_generation_complete

   def deduct_credits(sender, *, user, generation, **kwargs):
       if user is None:
           return  # anonymous trial — handled by rate limit, not credits
       cost_cents = int(generation.cost_usd * 100)
       deduct(user=user, amount_cents=cost_cents, reason="ai_generation")

   on_generation_complete.connect(deduct_credits, dispatch_uid="billing")
"""
from __future__ import annotations

import django.dispatch


# Fired AFTER the Generation row is persisted. Receivers run in the same
# transaction as the view (no Celery indirection by design — projects that
# want async should connect a receiver that enqueues a task).
#
# kwargs:
#   * user        — User instance or None (anonymous trial)
#   * generation  — Generation instance (already saved)
#   * input_tokens, output_tokens, cost_usd — convenience copies
on_generation_complete = django.dispatch.Signal()
