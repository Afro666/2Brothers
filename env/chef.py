"""A deterministic chef whose hidden habits change what the kitchen really uses."""

import random
from dataclasses import dataclass
from datetime import timedelta

from env.catalog import PRODUCTS
from env.sim import round_to_pack


@dataclass
class Habits:
    """Persistent kitchen habits; only the chef and simulation truth may see them."""

    factor: dict
    removed: set

    @classmethod
    def for_kitchen(cls, kitchen, seed: int):
        """Choose stable habits per kitchen type so weekly experiments are comparable."""
        rng = random.Random(f"chef-{seed}-{kitchen.type.name}")
        candidates = [pid for pid in kitchen.products if PRODUCTS[pid].abc in ("A", "B")]
        too_much = rng.choice(candidates)
        too_little = rng.choice([pid for pid in candidates if pid != too_much])
        removed = rng.choice([pid for pid in kitchen.products if pid not in (too_much, too_little)])
        return cls({too_much: 0.5, too_little: 1.3}, {removed})


def apply_truth(env, habits: Habits) -> None:
    """Patch real consumption after reset while retaining the buyer's recipe belief."""
    env.believed_usage = env.kitchen.usage_per_cover

    def true_usage(day):
        return {
            pid: qty * (0.0 if pid in habits.removed else habits.factor.get(pid, 1.0))
            for pid, qty in env.believed_usage(day).items()
        }

    env.kitchen.usage_per_cover = true_usage


class Chef:
    def __init__(self, habits: Habits, seed: int, noise: float = 0.1):
        self.habits = habits
        self.noise = noise
        self.rng = random.Random(f"chef-edit-{seed}")

    def edit(self, env, proposal: dict, baseline: dict | None = None) -> tuple:
        """Apply habits first, then stock cuts and unlearnable ordering noise.

        The chef wants the true need: the engine's unlearned proposal (`baseline`) times the
        habit factor. A proposal that already learned the habit therefore needs no edit."""
        final, rows = {}, []
        delivery = env.today + timedelta(days=1)
        for pid, units in proposal.items():
            factor = 0.0 if pid in self.habits.removed else self.habits.factor.get(pid, 1.0)
            reason = None
            if pid in self.habits.removed or factor < 1.0:
                reason = "TOO_MUCH"
            elif factor > 1.0:
                reason = "TOO_LITTLE"
            base = (baseline or {}).get(pid, units)
            wanted = round_to_pack(pid, base * PRODUCTS[pid].pack * factor)
            if wanted == units and reason in ("TOO_MUCH", "TOO_LITTLE"):
                reason = None           # already right: no habit edit

            three_day_use = sum(env._expected_use(pid, delivery + timedelta(days=i)) for i in range(3))
            if three_day_use > 0 and env.state.on_hand(pid) >= three_day_use:
                wanted, reason = 0, "IN_STOCK"
            elif wanted == units and self.rng.random() < self.noise:
                wanted = round_to_pack(pid, units * PRODUCTS[pid].pack * self.rng.choice((0.8, 1.2)))
                reason = None

            final[pid] = wanted
            if wanted != units:
                rows.append({
                    "kind": "line_removed" if wanted == 0 else "qty_changed",
                    "product_id": pid,
                    "from_qty": units,
                    "to_qty": wanted,
                    "base_qty": base,
                    "reason": reason,
                    "day": delivery.isoformat(),
                })
        return final, rows
