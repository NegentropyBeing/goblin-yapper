"""Who currently "has the voice" (whose chat messages get read by TTS).

Ruleset (from docs/SPEC.md):
  * operator presses a button -> a random chatter from a team gets the voice
  * that chatter's messages are read by TTS while active
  * operator can stop it
  * pressing again picks another person from the SAME team,
    or the operator picks a specific team, or a specific chatter

Single mode (default): one speaker in total; giving the voice to someone takes it from the others.
Multi mode: one speaker per team at the same time (plus one chatter without a team).
A speaker's team is looked up live, so moving them to another team moves their voice slot too.
"""

from __future__ import annotations

import random

from .teams import SorterError, TeamSorter

ANY = "any"


class VoiceController:
    def __init__(self, sorter: TeamSorter, rng: random.Random | None = None, multi: bool = False):
        self.sorter = sorter
        self.rng = rng or random.Random()
        self.multi = multi
        self.users: list[str] = []  # speakers, oldest first
        self.last_team: str | None = None

    # ---- queries -------------------------------------------------------

    @property
    def active(self) -> str | None:
        """Most recent speaker (the only one in single mode)."""
        return self.users[-1] if self.users else None

    @property
    def active_team(self) -> str | None:
        return self.sorter.team_of(self.active) if self.active else None

    def is_speaker(self, user: str) -> bool:
        return user.lower() in self.users

    def speaker_of(self, team: str | None) -> str | None:
        for user in reversed(self.users):
            if self.sorter.team_of(user) == team:
                return user
        return None

    def speakers(self) -> list[tuple[str, str | None]]:
        return [(u, self.sorter.team_of(u)) for u in self.users]

    # ---- actions -------------------------------------------------------

    def pick_random(self, team: str | None = None) -> str:
        """team=None -> same team as the last speaker (or any team if none yet);
        team='any' -> any team; otherwise that specific team."""
        if team is None:
            team = self.active_team or self.last_team or ANY
        team = team.lower()
        if team == ANY:
            candidates = [u for members in self.sorter.teams.values() for u in members]
            current = self.active
        elif team in self.sorter.teams:
            candidates = list(self.sorter.teams[team])
            current = self.speaker_of(team)
        else:
            raise SorterError(f"time desconhecido: {team}")
        if len(candidates) > 1 and current in candidates:
            candidates.remove(current)  # "sorteia OUTRA pessoa"
        if not candidates:
            raise SorterError("ninguém para sortear" + ("" if team == ANY else f" no time {team}"))
        return self._set(self.rng.choice(candidates))

    def give(self, user: str) -> str:
        """Give the voice to a specific chatter (doesn't need to be in a team)."""
        return self._set(user.lower())

    def stop(self, target: str | None = None) -> list[str]:
        """Stop everyone (None), one team's speaker, or one chatter. Returns who lost the voice."""
        if target is None:
            removed, self.users = self.users, []
            return removed
        target = target.lower()
        if target in self.sorter.teams:
            removed = [u for u in self.users if self.sorter.team_of(u) == target]
        elif target in self.users:
            removed = [target]
        else:
            raise SorterError(f"{target} não tem a voz")
        self.users = [u for u in self.users if u not in removed]
        return removed

    def set_multi(self, on: bool) -> list[str]:
        """Turning multi off keeps only the most recent speaker. Returns who lost the voice."""
        self.multi = on
        if on or len(self.users) <= 1:
            return []
        removed, self.users = self.users[:-1], self.users[-1:]
        return removed

    def prune(self, keep) -> list[str]:
        """Drop speakers for whom keep(user) is False (e.g. removed from the game)."""
        removed = [u for u in self.users if not keep(u)]
        self.users = [u for u in self.users if keep(u)]
        return removed

    def _set(self, user: str) -> str:
        team = self.sorter.team_of(user)
        if self.multi:
            # one speaker per team: replace that team's current speaker
            self.users = [u for u in self.users if u != user and self.sorter.team_of(u) != team]
        else:
            self.users = []
        self.users.append(user)
        self.last_team = team or self.last_team
        return user
