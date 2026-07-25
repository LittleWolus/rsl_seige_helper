import csv
import json
import re
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Set
from difflib import get_close_matches

try:
    import pulp
except ImportError:
    pulp = None


@dataclass
class Team:
    row_id: int
    player: str
    team_name: str
    power: float
    condition: str
    normalized_condition: str
    discord_id: Optional[str] = None  # NEW: store discord id if present


@dataclass
class Position:
    position_id: int
    name: str
    conditions: List[str]
    normalized_conditions: List[str]
    priority: int


@dataclass
class Match:
    team: Team
    position: Position
    score: float
    matched_position_condition: str


# -----------------------------
# General text normalization
# -----------------------------

def clean_text(value: str) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    value = re.sub(r"\s+", " ", value)
    return value


def canonical_key(value: str) -> str:
    value = clean_text(value).lower()

    remove_words = [
        "only",
        "allowed",
        "team",
        "teams",
        "champion",
        "champions",
        "faction",
        "factions",
        "affinity",
        "affinities",
        "role",
        "roles"
    ]

    for word in remove_words:
        value = re.sub(rf"\b{re.escape(word)}\b", "", value)

    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "", value)

    if value.endswith("s") and len(value) > 3:
        value_without_s = value[:-1]
        return value_without_s

    return value


def canonical_key_strict(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def split_conditions(raw: str) -> List[str]:
    raw = clean_text(raw)
    if not raw:
        return []

    parts = re.split(r"[;,/|]+", raw)
    return [clean_text(p) for p in parts if clean_text(p)]


# -----------------------------
# Config helpers
# -----------------------------

def load_config(path: str) -> Dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def get_known_values(config: Dict) -> Dict[str, str]:
    known = {}

    def add(value: str, official_value: Optional[str] = None):
        if value:
            known[canonical_key(value)] = official_value or value
            known[canonical_key_strict(value)] = official_value or value

    for faction in config.get("Factions", []):
        add(faction)

    for role in config.get("Roles", []):
        add(role)

    for affinity in config.get("Affinities", []):
        add(affinity)

    void_affinity = config.get("VoidAffinity")
    if void_affinity:
        add(void_affinity)

    for union_name in config.get("Unions", {}).keys():
        add(union_name)

    for restriction_name in config.get("RestrictionWeights", {}).keys():
        add(restriction_name)

    for alias, official_value in config.get("Aliases", {}).items():
        add(alias, official_value)

    add("Rare")
    add("Epic")
    add("Legendary")
    add("Void")
    add("Others")
    add("Other", "Others")

    return known


def normalize_condition(condition: str, config: Dict) -> str:
    condition = clean_text(condition)
    if not condition:
        return ""

    known = get_known_values(config)
    key = canonical_key(condition)

    if key in known:
        return known[key]

    strict_key = canonical_key_strict(condition)
    if strict_key in known:
        return known[strict_key]

    return condition


def get_position_priority(position_id: int, config: Dict) -> int:
    priorities = config.get("PositionsPriority", {})

    for priority_text, position_ids in priorities.items():
        try:
            priority = int(priority_text)
        except ValueError:
            continue

        if int(position_id) in [int(x) for x in position_ids]:
            return priority

    return 0


# -----------------------------
# CSV loading
# -----------------------------

def find_column(fieldnames: List[str], possible_names: List[str]) -> Optional[str]:
    lower_map = {name.lower().strip(): name for name in fieldnames}

    for possible in possible_names:
        key = possible.lower().strip()
        if key in lower_map:
            return lower_map[key]

    return None


def find_condition_columns(fieldnames: List[str]) -> List[str]:
    if not fieldnames:
        return []

    direct_condition_col = find_column(fieldnames, [
        "condition",
        "conditions",
        "condition_type",
        "condition type",
        "restriction",
        "restrictions"
    ])

    if direct_condition_col:
        return [direct_condition_col]

    condition_cols = []

    for name in fieldnames:
        normalized = name.lower().strip().replace(" ", "")
        if re.fullmatch(r"condition\d+", normalized):
            condition_cols.append(name)

    def condition_sort_key(col_name: str) -> int:
        normalized = col_name.lower().strip().replace(" ", "")
        match = re.search(r"\d+", normalized)
        return int(match.group(0)) if match else 999

    condition_cols.sort(key=condition_sort_key)
    return condition_cols


def load_players(path: str, config: Dict) -> List[Team]:
    teams = []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        player_col = find_column(fieldnames, [
            "player",
            "player_name",
            "player name",
            "name"
        ])

        discord_col = find_column(fieldnames, [
            "discord_id",
            "discord",
            "discordid",
            "id"
        ])

        team_col = find_column(fieldnames, [
            "team",
            "team_name",
            "team name",
            "team_id",
            "team id"
        ])

        power_col = find_column(fieldnames, [
            "power",
            "team_power",
            "team power"
        ])

        condition_col = find_column(fieldnames, [
            "condition",
            "conditions",
            "condition_type",
            "condition type",
            "faction",
            "restriction"
        ])

        if not player_col:
            raise ValueError("Players.csv is missing a player column.")
        if not condition_col:
            raise ValueError("Players.csv is missing a condition column.")

        for row_id, row in enumerate(reader, start=1):
            player = clean_text(row.get(player_col, ""))
            discord_id = clean_text(row.get(discord_col, "")) if discord_col else ""
            team_name = clean_text(row.get(team_col, "")) if team_col else f"Team {row_id}"

            power_raw = clean_text(row.get(power_col, "")) if power_col else "0"
            try:
                power = float(power_raw.replace(",", "."))
            except ValueError:
                power = 0.0

            condition = clean_text(row.get(condition_col, ""))
            normalized_condition = normalize_condition(condition, config)

            if not player or not condition:
                continue

            teams.append(
                Team(
                    row_id=row_id,
                    player=player,
                    team_name=team_name,
                    power=power,
                    condition=condition,
                    normalized_condition=normalized_condition,
                    discord_id=discord_id or None
                )
            )

    return teams


def load_positions(path: str, config: Dict) -> List[Position]:
    positions = []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        position_id_col = find_column(fieldnames, [
            "position_id",
            "position id",
            "id",
            "position"
        ])

        name_col = find_column(fieldnames, [
            "position_name",
            "position name",
            "name"
        ])

        condition_cols = find_condition_columns(fieldnames)

        if not position_id_col:
            raise ValueError("Positions.csv is missing a position id column.")

        if not condition_cols:
            raise ValueError(
                "Positions.csv is missing condition columns. "
                "Expected either 'condition'/'conditions' or columns like 'condition1', 'condition2', 'condition3'."
            )

        for row in reader:
            raw_position_id = clean_text(row.get(position_id_col, ""))
            if not raw_position_id:
                continue

            try:
                position_id = int(raw_position_id)
            except ValueError:
                continue

            name = clean_text(row.get(name_col, "")) if name_col else f"Position {position_id}"

            conditions = []

            for condition_col in condition_cols:
                raw_condition = row.get(condition_col, "")
                for condition in split_conditions(raw_condition):
                    if condition:
                        conditions.append(condition)

            normalized_conditions = [
                normalize_condition(condition, config)
                for condition in conditions
            ]

            priority = get_position_priority(position_id, config)

            positions.append(
                Position(
                    position_id=position_id,
                    name=name,
                    conditions=conditions,
                    normalized_conditions=normalized_conditions,
                    priority=priority
                )
            )

    return positions


# -----------------------------
# Restriction classification
# -----------------------------

def is_faction(value: str, config: Dict) -> bool:
    key = canonical_key(value)
    return key in {canonical_key(x) for x in config.get("Factions", [])}


def is_role(value: str, config: Dict) -> bool:
    key = canonical_key(value)
    return key in {canonical_key(x) for x in config.get("Roles", [])}


def is_affinity(value: str, config: Dict) -> bool:
    key = canonical_key(value)
    affinities = set(canonical_key(x) for x in config.get("Affinities", []))
    void = config.get("VoidAffinity")
    if void:
        affinities.add(canonical_key(void))
    return key in affinities


def is_union(value: str, config: Dict) -> bool:
    key = canonical_key(value)
    return key in {canonical_key(x) for x in config.get("Unions", {}).keys()}


def classify_condition(condition: str, config: Dict) -> str:
    normalized = normalize_condition(condition, config)
    key = canonical_key(normalized)

    if is_faction(normalized, config):
        return "Factions"

    if key == canonical_key("Rare"):
        return "Rare"

    if is_role(normalized, config):
        return "Role"

    if key == canonical_key("Epic"):
        return "Epic"

    if is_union(normalized, config):
        return "Union"

    void_affinity = config.get("VoidAffinity", "Void")
    if key == canonical_key(void_affinity):
        return "Void"

    if is_affinity(normalized, config):
        return "Affinity"

    if key == canonical_key("Legendary"):
        return "Legendary"

    return "Others"


def get_restriction_weight(condition: str, config: Dict) -> int:
    category = classify_condition(condition, config)
    weights = config.get("RestrictionWeights", {})
    return int(weights.get(category, weights.get("Others", 1)))


# -----------------------------
# Matching logic
# -----------------------------

def union_contains_faction(union_name: str, faction_name: str, config: Dict) -> bool:
    union_key = canonical_key(union_name)
    faction_key = canonical_key(faction_name)

    for configured_union, factions in config.get("Unions", {}).items():
        if canonical_key(configured_union) == union_key:
            return faction_key in {canonical_key(f) for f in factions}

    return False


def condition_matches_team(position_condition: str, team_condition: str, config: Dict) -> bool:
    pos = normalize_condition(position_condition, config)
    team = normalize_condition(team_condition, config)

    pos_key = canonical_key(pos)
    team_key = canonical_key(team)

    if not pos_key or not team_key:
        return False

    if pos_key == team_key:
        return True

    if is_faction(pos, config) or is_union(pos, config):
        return False

    pos_cat = classify_condition(pos, config)

    if pos_cat in {"Role", "Affinity", "Rare", "Epic", "Legendary", "Void"}:
        return False

    return False


def match_category_from_position_condition(position_condition: str, config: Dict) -> Tuple[str, str]:
    normalized = normalize_condition(position_condition, config)
    cat = classify_condition(normalized, config)
    key = canonical_key(normalized)

    if is_union(normalized, config):
        return "Union", key
    if is_faction(normalized, config):
        return "Faction", key

    return cat, key


def compute_match_score(team: Team, position: Position, config: Dict) -> Optional[Match]:
    if position.priority <= 0:
        return None

    best_score = None
    best_position_condition = None

    for original_condition, normalized_condition in zip(position.conditions, position.normalized_conditions):
        if not condition_matches_team(normalized_condition, team.normalized_condition, config):
            continue

        restriction_weight = get_restriction_weight(normalized_condition, config)

        score = (
            restriction_weight * 1000
            + position.priority * 100
            + team.power
        )

        if best_score is None or score > best_score:
            best_score = score
            best_position_condition = original_condition

    if best_score is None:
        return None

    return Match(
        team=team,
        position=position,
        score=best_score,
        matched_position_condition=best_position_condition or ""
    )


# -----------------------------
# Assignment solver
# -----------------------------

def solve_assignment(teams: List[Team], positions: List[Position], config: Dict) -> Tuple[List[Match], List[Position]]:
    active_positions = [p for p in positions if p.priority > 0]
    max_positions_per_player = int(config.get("MaxPositionsPerPlayer", 1))

    possible_matches: List[Match] = []
    match_meta: List[Dict] = []

    for team in teams:
        for position in active_positions:
            match = compute_match_score(team, position, config)
            if match is not None:
                possible_matches.append(match)

                category_type, category_key = match_category_from_position_condition(
                    match.matched_position_condition,
                    config
                )

                match_meta.append({
                    "player": team.player,
                    "row_id": team.row_id,
                    "position_id": position.position_id,
                    "category_type": category_type,
                    "category_key": category_key,
                })

    if not possible_matches:
        return [], active_positions

    if pulp is None:
        return solve_assignment_greedy(possible_matches, match_meta, active_positions, max_positions_per_player, config)

    return solve_assignment_pulp(possible_matches, match_meta, active_positions, max_positions_per_player, config)


def solve_assignment_greedy(
    possible_matches: List[Match],
    match_meta: List[Dict],
    active_positions: List[Position],
    max_positions_per_player: int,
    config: Dict
) -> Tuple[List[Match], List[Position]]:
    indexed = list(enumerate(possible_matches))
    indexed.sort(key=lambda t: t[1].score, reverse=True)

    used_team_rows: Set[int] = set()
    used_positions: Set[int] = set()
    player_counts: Dict[str, int] = {}
    player_factions: Dict[str, Set[str]] = {}
    player_unions: Dict[str, Set[str]] = {}

    assigned: List[Match] = []

    for idx, match in indexed:
        meta = match_meta[idx]
        team = match.team
        position = match.position
        player = team.player

        if team.row_id in used_team_rows:
            continue
        if position.position_id in used_positions:
            continue
        count = player_counts.get(player, 0)
        if count >= max_positions_per_player:
            continue

        cat_type = meta.get("category_type")
        cat_key = meta.get("category_key")

        if cat_type == "Faction":
            unions = player_unions.get(player, set())
            conflict = False
            for u_key in unions:
                for configured_union in config.get("Unions", {}).keys():
                    if canonical_key(configured_union) == u_key:
                        if cat_key in {canonical_key(f) for f in config.get("Unions", {}).get(configured_union, [])}:
                            conflict = True
                            break
                if conflict:
                    break
            if conflict:
                continue

        if cat_type == "Union":
            factions = player_factions.get(player, set())
            conflict = False
            for f_key in factions:
                for configured_union in config.get("Unions", {}).keys():
                    if canonical_key(configured_union) == cat_key:
                        if f_key in {canonical_key(f) for f in config.get("Unions", {}).get(configured_union, [])}:
                            conflict = True
                            break
                if conflict:
                    break
            if conflict:
                continue

        assigned.append(match)
        used_team_rows.add(team.row_id)
        used_positions.add(position.position_id)
        player_counts[player] = count + 1

        if cat_type == "Faction":
            player_factions.setdefault(player, set()).add(cat_key)
        elif cat_type == "Union":
            player_unions.setdefault(player, set()).add(cat_key)

    assigned_position_ids = {m.position.position_id for m in assigned}
    unassigned = [p for p in active_positions if p.position_id not in assigned_position_ids]

    assigned.sort(key=lambda m: m.position.position_id)
    return assigned, unassigned


def solve_assignment_pulp(
    possible_matches: List[Match],
    match_meta: List[Dict],
    active_positions: List[Position],
    max_positions_per_player: int,
    config: Dict
) -> Tuple[List[Match], List[Position]]:
    problem = pulp.LpProblem("RaidSiegeAssignment", pulp.LpMaximize)

    variables = {}
    for idx, match in enumerate(possible_matches):
        variables[idx] = pulp.LpVariable(f"x_{idx}", cat="Binary")

    problem += pulp.lpSum(match.score * variables[idx] for idx, match in enumerate(possible_matches))

    team_row_ids = {match.team.row_id for match in possible_matches}
    for row_id in team_row_ids:
        problem += (
            pulp.lpSum(
                variables[idx]
                for idx, match in enumerate(possible_matches)
                if match.team.row_id == row_id
            ) <= 1
        )

    position_ids = {match.position.position_id for match in possible_matches}
    for position_id in position_ids:
        problem += (
            pulp.lpSum(
                variables[idx]
                for idx, match in enumerate(possible_matches)
                if match.position.position_id == position_id
            ) <= 1
        )

    players = {match.team.player for match in possible_matches}
    for player in players:
        problem += (
            pulp.lpSum(
                variables[idx]
                for idx, match in enumerate(possible_matches)
                if match.team.player == player
            ) <= max_positions_per_player
        )

    for player in players:
        player_indices_by_faction: Dict[str, List[int]] = {}
        player_indices_by_union: Dict[str, List[int]] = {}

        for idx, meta in enumerate(match_meta):
            if meta["player"] != player:
                continue
            cat_type = meta["category_type"]
            cat_key = meta["category_key"]
            if cat_type == "Faction":
                player_indices_by_faction.setdefault(cat_key, []).append(idx)
            elif cat_type == "Union":
                player_indices_by_union.setdefault(cat_key, []).append(idx)

        for f_key, f_indices in player_indices_by_faction.items():
            for u_key, u_indices in player_indices_by_union.items():
                contains = False
                for configured_union, factions in config.get("Unions", {}).items():
                    if canonical_key(configured_union) != u_key:
                        continue
                    if f_key in {canonical_key(f) for f in factions}:
                        contains = True
                        break
                if not contains:
                    continue

                problem += (
                    pulp.lpSum(variables[idx] for idx in f_indices)
                    + pulp.lpSum(variables[idx] for idx in u_indices)
                    <= 1
                )

    solver = pulp.PULP_CBC_CMD(msg=False)
    problem.solve(solver)

    assigned = []

    for idx, match in enumerate(possible_matches):
        value = pulp.value(variables[idx])
        if value is not None and value > 0.5:
            assigned.append(match)

    assigned.sort(key=lambda m: m.position.position_id)

    assigned_position_ids = {m.position.position_id for m in assigned}
    unassigned = [
        p for p in active_positions
        if p.position_id not in assigned_position_ids
    ]

    return assigned, unassigned


# -----------------------------
# Input validation
# -----------------------------

def suggest_known_value(value: str, config: Dict) -> Optional[str]:
    known_values = list(set(get_known_values(config).values()))
    if not value:
        return None

    cleaned_value = clean_text(value).lower()

    matches = get_close_matches(
        cleaned_value,
        [v.lower() for v in known_values],
        n=1,
        cutoff=0.72
    )

    if not matches:
        return None

    lower_to_original = {v.lower(): v for v in known_values}
    return lower_to_original.get(matches[0])


def check_condition_message(
    source_type: str,
    player: Optional[str],
    team_name: Optional[str],
    position_id: Optional[int],
    original_condition: str,
    config: Dict
) -> Optional[str]:
    original = clean_text(original_condition)
    if not original:
        return None

    interpreted = normalize_condition(original, config)
    for alias, official_value in config.get("Aliases", {}).items():
        if canonical_key(original) == canonical_key(alias):
            return None

    known_values = get_known_values(config)

    original_key = canonical_key(original)
    interpreted_key = canonical_key(interpreted)

    original_known = original_key in known_values
    interpreted_known = interpreted_key in known_values

    if original_known or interpreted_known:
        return None

    suggested = suggest_known_value(original, config)

    if suggested:
        if source_type == "team":
            return (
                f"- Team '{team_name}' / player '{player}' has unknown condition "
                f"'{original}'. Did you mean '{suggested}'?"
            )

        return (
            f"- Position '{position_id}' has unknown condition "
            f"'{original}'. Did you mean '{suggested}'?"
        )

    if source_type == "team":
        return (
            f"- Team '{team_name}' / player '{player}' has unknown condition "
            f"'{original}'."
        )

    return (
        f"- Position '{position_id}' has unknown condition "
        f"'{original}'."
    )


def check_csv_row_shape(path: str, expected_columns: Optional[int] = None) -> List[str]:
    messages = []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        messages.append(f"- File '{path}' is empty.")
        return messages

    header = rows[0]
    header_len = len(header)

    for line_number, row in enumerate(rows[1:], start=2):
        if expected_columns is not None:
            expected_len = expected_columns
        else:
            expected_len = header_len

        if len(row) > expected_len:
            messages.append(
                f"- CSV row {line_number} has too many values. "
                f"Expected {expected_len}, found {len(row)}. "
                f"Possible extra comma at end of line."
            )

        elif len(row) < expected_len:
            messages.append(
                f"- CSV row {line_number} has too few values. "
                f"Expected {expected_len}, found {len(row)}."
            )

    return messages


def check_inputs(players_path: str, positions_path: str, config_path: str) -> List[str]:
    config = load_config(config_path)
    messages = []

    messages.extend(check_csv_row_shape(players_path))
    messages.extend(check_csv_row_shape(positions_path))

    teams = load_players(players_path, config)
    positions = load_positions(positions_path, config)

    seen_team_rows = set()

    for team in teams:
        duplicate_key = (
            team.player,
            team.team_name,
            team.power,
            team.condition
        )

        if duplicate_key in seen_team_rows:
            messages.append(
                f"- Team '{team.team_name}' / player '{team.player}' appears more than once with the same condition '{team.condition}'."
            )
        else:
            seen_team_rows.add(duplicate_key)

        msg = check_condition_message(
            source_type="team",
            player=team.player,
            team_name=team.team_name,
            position_id=None,
            original_condition=team.condition,
            config=config
        )

        if msg:
            messages.append(msg)

    for position in positions:
        if position.priority == 0:
            messages.append(
                f"- Position '{position.position_id}' is not listed in PositionsPriority and will be skipped."
            )

        if not position.conditions:
            messages.append(
                f"- Position '{position.position_id}' has no conditions."
            )

        for condition in position.conditions:
            msg = check_condition_message(
                source_type="position",
                player=None,
                team_name=None,
                position_id=position.position_id,
                original_condition=condition,
                config=config
            )

            if msg:
                messages.append(msg)

    if not messages:
        messages.append("No input issues found.")

    return messages


# -----------------------------
# Output formatting
# -----------------------------

def _discord_mention(player_name: str, discord_id: Optional[str]) -> str:
    """
    Return a Discord mention if discord_id looks valid (digits only), otherwise fallback to player_name.
    """
    if discord_id:
        did = str(discord_id).strip()
        return did
    return player_name


def format_assignment_output(assigned: List[Match], unassigned: List[Position]) -> str:
    lines = []

    if assigned:
        for match in sorted(assigned, key=lambda m: m.position.position_id):
            mention = _discord_mention(match.team.player, match.team.discord_id)
            # Show the position condition (the position's condition text), not the team condition,
            # for clarity. If you prefer the team's condition, change to match.team.normalized_condition.
            position_condition_display = match.matched_position_condition or ", ".join(match.position.conditions)
            lines.append(
                f"Position {match.position.position_id}, {mention}, Condition {position_condition_display}"
            )
    else:
        lines.append("No positions assigned.")

    if unassigned:
        lines.append("")
        lines.append("Unassigned positions:")
        for position in sorted(unassigned, key=lambda p: p.position_id):
            conditions = ", ".join(position.conditions) if position.conditions else "No conditions"
            lines.append(
                f"Position {position.position_id}, Conditions: {conditions}"
            )

    return "\n".join(lines)


# -----------------------------
# GUI
# -----------------------------

class RaidSiegeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RAID Siege Team Assignment Tool")
        self.root.geometry("900x650")

        self.players_path = tk.StringVar()
        self.positions_path = tk.StringVar()
        self.config_path = tk.StringVar()
        self.inputs_checked = False

        self.create_widgets()

    def create_widgets(self):
        frame = tk.Frame(self.root)
        frame.pack(fill=tk.X, padx=10, pady=10)

        self.create_file_row(frame, "Players.csv:", self.players_path, 0)
        self.create_file_row(frame, "Positions.csv:", self.positions_path, 1)
        self.create_file_row(frame, "config.json:", self.config_path, 2)

        button_frame = tk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=10, pady=5)

        check_button = tk.Button(
            button_frame,
            text="Check inputs",
            command=self.on_check_inputs
        )
        check_button.pack(side=tk.LEFT, padx=5)

        self.run_button = tk.Button(
            button_frame,
            text="Run assignment",
            command=self.on_run_assignment,
            state=tk.DISABLED
        )
        self.run_button.pack(side=tk.LEFT, padx=5)

        self.output = scrolledtext.ScrolledText(self.root, wrap=tk.WORD)
        self.output.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def create_file_row(self, parent, label_text, variable, row):
        label = tk.Label(parent, text=label_text, width=15, anchor="w")
        label.grid(row=row, column=0, sticky="w", pady=3)

        entry = tk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=3)

        button = tk.Button(
            parent,
            text="Browse",
            command=lambda: self.browse_file(variable)
        )
        button.grid(row=row, column=2, padx=5, pady=3)

        parent.grid_columnconfigure(1, weight=1)

    def browse_file(self, variable):
        path = filedialog.askopenfilename(
            filetypes=[
                ("CSV and JSON files", "*.csv *.json"),
                ("All files", "*.*")
            ]
        )

        if path:
            variable.set(path)
            self.inputs_checked = False
            self.run_button.config(state=tk.DISABLED)

    def validate_paths(self) -> bool:
        if not self.players_path.get():
            messagebox.showerror("Missing file", "Please select Players.csv.")
            return False

        if not self.positions_path.get():
            messagebox.showerror("Missing file", "Please select Positions.csv.")
            return False

        if not self.config_path.get():
            messagebox.showerror("Missing file", "Please select config.json.")
            return False

        return True

    def clear_output(self):
        self.output.delete("1.0", tk.END)

    def write_output(self, text: str):
        self.clear_output()
        self.output.insert(tk.END, text)

    def on_check_inputs(self):
        if not self.validate_paths():
            return

        try:
            messages = check_inputs(
                self.players_path.get(),
                self.positions_path.get(),
                self.config_path.get()
            )

            self.write_output("\n".join(messages))

            self.inputs_checked = True
            self.run_button.config(state=tk.NORMAL)

        except Exception as e:
            self.inputs_checked = False
            self.run_button.config(state=tk.DISABLED)
            messagebox.showerror("Error", str(e))

    def on_run_assignment(self):
        if not self.validate_paths():
            return

        if not self.inputs_checked:
            messagebox.showerror(
                "Inputs not checked",
                "Please run Check inputs before Run assignment."
            )
            return

        try:
            config = load_config(self.config_path.get())
            teams = load_players(self.players_path.get(), config)
            positions = load_positions(self.positions_path.get(), config)

            assigned, unassigned = solve_assignment(teams, positions, config)
            output_text = format_assignment_output(assigned, unassigned)

            self.write_output(output_text)

        except Exception as e:
            messagebox.showerror("Error", str(e))


def main():
    root = tk.Tk()
    app = RaidSiegeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
