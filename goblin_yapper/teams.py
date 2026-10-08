"""Team sorter: queue of chatters -> up to 4 balanced teams.

Pure logic, no I/O, so it can be driven by chat, console or a future frontend.
Users are keyed by their lowercase Twitch login; display names are kept separately.
"""

from __future__ import annotations

import random

TEAM_NAMES = ("azul", "verde", "roxo", "amarelo")
QUEUE = "fila"  # pseudo-team name meaning "back to the queue"


class SorterError(Exception):
    pass


class TeamSorter:
    def __init__(self, team_count: int = 2, auto_assign_late: bool = True, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.auto_assign_late = auto_assign_late
        self.queue: list[str] = []
        self.teams: dict[str, list[str]] = {}
        self.display: dict[str, str] = {}
        self.queue_open = False
        # True once a sort happened; late joiners then go straight into a team.
        self.sorted = False
        self.set_team_count(team_count)

    # ---- queries -------------------------------------------------------

    def team_of(self, user: str) -> str | None:
        user = user.lower()
        for name, members in self.teams.items():
            if user in members:
                return name
        return None

    def where(self, user: str) -> str | None:
        """Team name, QUEUE, or None if the user is nowhere."""
        user = user.lower()
        if user in self.queue:
            return QUEUE
        return self.team_of(user)

    def name(self, user: str) -> str:
        return self.display.get(user.lower(), user)

    def snapshot(self) -> dict:
        """Members as {"id": login, "name": display}; commands take the id."""
        def people(users):
            return [{"id": u, "name": self.name(u)} for u in users]
        return {
            "queue_open": self.queue_open,
            "sorted": self.sorted,
            "queue": people(self.queue),
            "teams": {t: people(m) for t, m in self.teams.items()},
        }

    # ---- configuration -------------------------------------------------

    def set_team_count(self, n: int) -> None:
        if not 1 <= n <= len(TEAM_NAMES):
            raise SorterError(f"número de times deve ser 1..{len(TEAM_NAMES)}")
        wanted = TEAM_NAMES[:n]
        dropped: list[str] = []
        for name in list(self.teams):
            if name not in wanted:
                dropped.extend(self.teams.pop(name))
        for name in wanted:
            self.teams.setdefault(name, [])
        # Keep the canonical color order.
        self.teams = {name: self.teams[name] for name in wanted}
        for user in dropped:
            if self.sorted:
                self.teams[self._smallest_team()].append(user)
            else:
                self.queue.append(user)

    # ---- chatter actions -----------------------------------------------

    def join(self, user: str, display: str | None = None) -> str:
        """Returns 'closed', 'already', 'queued' or the team name assigned."""
        key = user.lower()
        if self.where(key) is not None:
            return "already"
        if not self.queue_open:
            return "closed"
        self.display[key] = display or user
        if self.sorted and self.auto_assign_late:
            team = self._smallest_team()
            self.teams[team].append(key)
            return team
        self.queue.append(key)
        return "queued"

    def leave(self, user: str) -> bool:
        key = user.lower()
        if key in self.queue:
            self.queue.remove(key)
            return True
        team = self.team_of(key)
        if team:
            self.teams[team].remove(key)
            return True
        return False

    # ---- operator actions ----------------------------------------------

    def add(self, user: str) -> str:
        """Operator adds someone manually (ignores queue_open)."""
        was_open, self.queue_open = self.queue_open, True
        try:
            return self.join(user)
        finally:
            self.queue_open = was_open

    def sort(self) -> int:
        """Distribute everyone in the queue into the smallest teams. Returns how many were sorted."""
        pending = self.queue[:]
        self.rng.shuffle(pending)
        self.queue.clear()
        for user in pending:
            self.teams[self._smallest_team()].append(user)
        self.sorted = True
        return len(pending)

    def return_all_to_queue(self) -> None:
        for members in self.teams.values():
            self.queue.extend(members)
            members.clear()
        self.sorted = False

    def resort(self) -> int:
        self.return_all_to_queue()
        return self.sort()

    def clear(self) -> None:
        self.queue.clear()
        for members in self.teams.values():
            members.clear()
        self.display.clear()
        self.sorted = False

    def move(self, user: str, target: str) -> None:
        key = user.lower()
        target = target.lower()
        if target != QUEUE and target not in self.teams:
            raise SorterError(f"time desconhecido: {target} (use {', '.join(self.teams)} ou {QUEUE})")
        if not self.leave(key):
            raise SorterError(f"{user} não está na fila nem em um time")
        (self.queue if target == QUEUE else self.teams[target]).append(key)

    def remove(self, user: str) -> None:
        if not self.leave(user):
            raise SorterError(f"{user} não está na fila nem em um time")

    # ---- internals -----------------------------------------------------

    def _smallest_team(self) -> str:
        low = min(len(m) for m in self.teams.values())
        return self.rng.choice([t for t, m in self.teams.items() if len(m) == low])
