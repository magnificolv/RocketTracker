"""
Semantiskais field resolver un adapter pattern (TRIZ #15: Dinamisms).

Parseris vairs nav trausls pret RL Stats API field name izmaiņām:
  1. FIELD_PATTERNS — mēģina atrast lauku pēc visiem zināmajiem nosaukumu variantiem
  2. SEMANTISKĀ MINĒŠANA — ja neviens nosaukums neatbilst, mēģina uzminēt pēc vērtības tipa

Lietošana:
    from field_resolver import FieldResolver
    name = FieldResolver.resolve(data, "attacker")          # -> str vai None
    key, val = FieldResolver.guess_by_type(data, str)        # fallback
"""
import json

# Zināmie lauku nosaukumu varianti, ko RL Stats API var sūtīt.
# Pirmie tiek mēģinātie pirmie — vissvarīgākie pirmās.
FIELD_PATTERNS = {
    "attacker": ["Attacker", "attacker", "AttackerName", "attacker_name", "AttackerId"],
    "victim":   ["Victim",   "victim",   "VictimName",   "victim_name",   "VictimId"],
    "scorer":   ["Scorer",   "scorer",   "ScorerName",   "scorer_name",   "PlayerName"],
    "assister": ["Assister", "assister", "AssisterName", "assister_name"],
    "winner":   ["WinnerTeamNum", "Winner", "winner", "winner_team_num"],
    # Stat lauki (nav saraksts, bet noder UpdateState player objektam)
    "name":         ["Name", "name", "PlayerName", "player_name"],
    "team_num":     ["TeamNum", "team_num", "Team"],
    "goal_speed":   ["GoalSpeed", "goal_speed", "Speed", "speed"],
    "time_seconds": ["TimeSeconds", "time_seconds", "Time"],
}


class FieldResolver:
    """Atrast lauku pēc semantiskā vārda vai uzminēt pēc tipa."""

    # ---------------------------------------------------------------
    # 1. RESOLVE — mēģina visus zināmos nosaukumus
    # ---------------------------------------------------------------
    @staticmethod
    def resolve(data, field_name):
        """Atgriež vērtību (izvilkto Name str, ja dict) vai None.

        Ja field_name nav FIELD_PATTERNS, mēģina tieši field_name kā atslēgu
        (tādējādi patur atpakaļejošu saderību ar jebkuru nākotnes lauku).
        """
        if not isinstance(data, dict):
            return None
        for pattern in FIELD_PATTERNS.get(field_name, [field_name]):
            if pattern in data:
                return FieldResolver._extract(data[pattern])
        return None

    @staticmethod
    def resolve_key(data, field_name):
        """Kā resolve(), bet atgriež (key, value) priekš debug/raw dump."""
        if not isinstance(data, dict):
            return None, None
        for pattern in FIELD_PATTERNS.get(field_name, [field_name]):
            if pattern in data:
                return pattern, FieldResolver._extract(data[pattern])
        return None, None

    @staticmethod
    def resolve_raw(data, field_name):
        """Kā resolve(), bet atgriež jēdo vērtību (dict/string/number) bez Name izvilkšanas.

        Noder, kad nepieciešams pilns objekts, piem. GoalScored scorerim
        ar TeamNum lauku.
        """
        if not isinstance(data, dict):
            return None
        for pattern in FIELD_PATTERNS.get(field_name, [field_name]):
            if pattern in data:
                return data[pattern]
        return None

    # ---------------------------------------------------------------
    # 2. GUESS_BY_TYPE — semantiskā minēšana, ja nosaukums neatbilst
    # ---------------------------------------------------------------
    @staticmethod
    def guess_by_type(data, expected_type=str, exclude_prefixes=("_", "Event", "MatchGuid")):
        """Atgriež (key, value) pirmo lauku, kas atbilst tipam.

        exclude_prefixes: izlaiž metadatus (Event, MatchGuid, _privātos).
        """
        if not isinstance(data, dict):
            return None, None
        for key, value in data.items():
            if any(key.startswith(p) for p in exclude_prefixes):
                continue
            if isinstance(value, expected_type) and value:
                return key, value
            if isinstance(value, dict) and ("Name" in value or "name" in value):
                return key, FieldResolver._extract(value)
        return None, None

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------
    @staticmethod
    def _extract(value):
        """No dict izvelk Name; citādi atdod kā ir (tukšo → None)."""
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get("Name") or value.get("name") or None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    # ---------------------------------------------------------------
    # 3. RAW DUMP — diagnostikai, kad nekas nestrādā
    # ---------------------------------------------------------------
    @staticmethod
    def raw_dump(data, context="UNKNOWN FORMAT"):
        """Atgriež debug string priekš log() izsaukuma."""
        try:
            return f"{context}: data={json.dumps(data, ensure_ascii=False)}"
        except (TypeError, ValueError):
            return f"{context}: data={data!r}"


__all__ = ["FieldResolver", "FIELD_PATTERNS"]
