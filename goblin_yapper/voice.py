"""Who currently "has the voice" (whose chat messages get read by TTS).

Ruleset (from Predicates.md):
  * operator presses a button -> a random chatter from a team gets the voice
  * that chatter's messages are read by TTS while active
  * operator can stop it
  * pressing again picks another person from the SAME team,
    or the operator picks a specific team, or a specific chatter
"""

from __future__ import annotations

import random

from .teams import SorterError, TeamSorter

ANY = "any"


class VoiceController:
    def __init__(self, sorter: TeamSorter, rng: random.Random | None = None):
        self.sorter = sorter
        self.rng = rng or random.Random()
        self.active: str | None = None
        self.last_team: str | None = None

    @property
    def active_team(self) -> str | None:
        return self.sorter.team_of(self.active) if self.active else None

    def pick_random(self, team: str | None = None) -> str:
        """team=None -> same team as current/last speaker (or any team if none yet);
        team='any' -> any team; otherwise that specific team."""
        if team is None:
            team = self.active_team or self.last_team or ANY
        team = team.lower()
        if team == ANY:
            candidates = [u for members in self.sorter.teams.values() for u in members]
        elif team in self.sorter.teams:
            candidates = list(self.sorter.teams[team])
        else:
            raise SorterError(f"time desconhecido: {team}")
        if len(candidates) > 1 and self.active in candidates:
            candidates.remove(self.active)  # "sorteia OUTRA pessoa"
        if not candidates:
            raise SorterError("ninguém para sortear" + ("" if team == ANY else f" no time {team}"))
        return self._set(self.rng.choice(candidates))

    def give(self, user: str) -> str:
        """Give the voice to a specific chatter (doesn't need to be in a team)."""
        return self._set(user.lower())

    def stop(self) -> str | None:
        prev, self.active = self.active, None
        return prev

    def _set(self, user: str) -> str:
        self.active = user
        self.last_team = self.sorter.team_of(user) or self.last_team
        return user
