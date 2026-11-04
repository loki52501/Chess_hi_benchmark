"""Two layers of what Claude has learned, both kept in the games folder:
   rules.md       - at most 12 general rules, always in the move prompt:  - [R01] <rule> | CHECK: <yes/no question>
   rules_stats.json - per rule: retrieved, helped, created_game, cited_games
   lessons.jsonl  - specific lessons, one JSON object per line, retrieved only when they fit the position
"""
import json, os, re

MAX_RULES = 12
MAX_RULE_WORDS = 25
MOTIFS = ("king_activity", "passed_pawn", "opposition", "rook_activity", "pawn_race", "back_rank", "hanging_piece",
          "fork", "pin", "pawn_break", "piece_activity", "king_safety", "prophylaxis", "conversion", "self_assessment")
PHASES = ("opening", "middlegame", "endgame", "any")
KINDS = ("mistake", "good_move", "opponent_shot", "self_assessment")
LESSON_FIELDS = ("rule", "trigger", "check", "phase", "motifs", "features")   # what Claude fills in for a new lesson
SQUARE = re.compile(r"(?<![a-z])[a-h][1-8](?![0-9])")   # e4, also inside moves like Bd4 or Nxc6
EXAMPLE = re.compile(r"e\.g\.[^);]*?(?=[);]|\.\s|\.?$)")   # "e.g. ..." up to ")", ";" or the end of the sentence
SEEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds")
# a rule must name something on the board, so "be careful" style advice is rejected
CHESS_NOUN = re.compile(r"\b(kings?|queens?|rooks?|bishops?|knights?|pawns?|files?|[a-h][1-8]|[a-h]-pawn)\b", re.I)
RULE_LINE = re.compile(r"^- \[(R\d+)\] (.+?) \| CHECK: (.+)$")

def path(folder, name):
    return os.path.join(folder, name)

def words(text):
    return len(text.split())

# --- layer 1: general rules ------------------------------------------------------------------

def load_rules(folder):   # [{"id": "R01", "rule": ..., "check": ...}]; lines in another format are skipped
    p = path(folder, "rules.md")
    if not os.path.exists(p):
        return []
    return [dict(id=m.group(1), rule=m.group(2).strip(), check=m.group(3).strip())
            for line in open(p, encoding="utf-8") if (m := RULE_LINE.match(line.strip()))]

def format_rules(rules):
    return "".join(f"- [{r['id']}] {r['rule']} | CHECK: {r['check']}\n" for r in rules)

def save_rules(folder, rules):
    with open(path(folder, "rules.md"), "w", encoding="utf-8") as f:
        f.write(format_rules(rules))

def load_stats(folder):   # {"R01": {"retrieved": 0, "helped": 0, "created_game": 0, "cited_games": []}, ...}
    p = path(folder, "rules_stats.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}

def save_stats(folder, stats):
    with open(path(folder, "rules_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

def new_rule_stats(created_game):
    return dict(retrieved=0, helped=0, created_game=created_game, cited_games=[])

def next_rule_id(rules, stats):   # never reuses an id, even of a rule that was replaced
    used = [int(x[1:]) for x in list(stats) + [r["id"] for r in rules] if re.fullmatch(r"R\d+", x)]
    return f"R{max(used, default=0) + 1:02d}"

# --- layer 2: specific lessons -----------------------------------------------------------------

def load_jsonl(p):   # one JSON object per line; [] if the file doesn't exist
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()] if os.path.exists(p) else []

def load_lessons(folder):
    return load_jsonl(path(folder, "lessons.jsonl"))

def save_lessons(folder, lessons):
    with open(path(folder, "lessons.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(lesson) + "\n" for lesson in lessons)

def next_lesson_id(lessons):   # L001, L002, ... retired and promoted lessons stay in the file, so ids are never reused
    used = [int(l["id"][1:]) for l in lessons if re.fullmatch(r"L\d+", l["id"])]
    return f"L{max(used, default=0) + 1:03d}"

def help_rate(entry):   # share of citations where the move was Good or better (None = never cited)
    return entry["helped"] / entry["retrieved"] if entry.get("retrieved") else None

# --- checking what Claude wrote --------------------------------------------------------------------

def problems_with(entry, fields=LESSON_FIELDS):
    """Why a lesson (or the given fields of an update) is not acceptable; [] = fine."""
    problems = []
    for field in fields:
        value = entry.get(field)
        if value in (None, "", []):
            problems.append(f"missing {field}")
        elif field == "phase" and value not in PHASES:
            problems.append(f"phase {value!r} is not one of {', '.join(PHASES)}")
        elif field == "motifs" and (not isinstance(value, list) or any(m not in MOTIFS for m in value)):
            problems.append(f"motifs {value!r} must be a list from: {', '.join(MOTIFS)}")
        elif field == "features" and (not isinstance(value, list) or not all(isinstance(t, str) for t in value)):
            problems.append(f"features {value!r} must be a list of tag names")
    rule = str(entry.get("rule") or "")
    if "rule" in fields and rule:
        if words(rule) > MAX_RULE_WORDS:
            problems.append(f"rule has {words(rule)} words (max {MAX_RULE_WORDS})")
        if not CHESS_NOUN.search(rule):
            problems.append("rule names no piece, pawn, square, file or king")
        problems += pattern_problems("rule", rule, examples_allowed=1)
    if "trigger" in fields and entry.get("trigger"):
        problems += pattern_problems("trigger", str(entry["trigger"]), examples_allowed=0)
    return problems

def pattern_problems(field, text, examples_allowed):
    """Rules and triggers describe the pattern, not exact squares; squares may appear once, after "e.g.", in a rule."""
    if text.count("e.g.") > examples_allowed:
        return [f"{field} may use \"e.g.\" at most {examples_allowed} time(s)"]
    squares = SQUARE.findall(EXAMPLE.sub("", text) if examples_allowed else text)
    if squares:
        return [f"{field} names exact squares ({', '.join(dict.fromkeys(squares))}); describe the pattern instead "
                f"(my king, the castled side, my 2nd rank, the long diagonal...)"
                + ("; squares are allowed once, after \"e.g.\"" if examples_allowed else "")]
    return []

# --- setting up a games folder ---------------------------------------------------------------------

def is_new_format(folder):
    p = path(folder, "rules.md")
    return os.path.exists(p) and bool(load_rules(folder))

def seed_new(folder, rules):   # new-format rules.md + stats + empty lessons.jsonl
    save_rules(folder, rules)
    save_stats(folder, {r["id"]: new_rule_stats(0) for r in rules})
    save_lessons(folder, [])

def init_folder(folder, mode):
    """A new games folder starts from seeds/: "lessons" mode gets the new rules.md, "rules" mode the old-style list."""
    os.makedirs(folder, exist_ok=True)
    if os.path.exists(path(folder, "rules.md")):
        if mode == "lessons" and not is_new_format(folder):
            migrate(folder)
        return
    if mode == "lessons":
        seed_new(folder, load_rules(SEEDS_DIR))
    else:
        with open(path(SEEDS_DIR, "rules_legacy.md"), encoding="utf-8") as src, \
             open(path(folder, "rules.md"), "w", encoding="utf-8") as dst:
            dst.write(src.read())

def migrate(folder):
    """One-time: old-style rules.md -> rules_legacy.md (backup) + new-format rules.md + empty lessons.jsonl.
    The current games/rules.md was rewritten by hand into seeds/rules.md (overlapping rules merged);
    any other old list is converted line by line with a generic CHECK."""
    p = path(folder, "rules.md")
    old = open(p, encoding="utf-8").read()
    with open(path(folder, "rules_legacy.md"), "w", encoding="utf-8") as f:
        f.write(old)
    if old.strip() == open(path(SEEDS_DIR, "rules_legacy.md"), encoding="utf-8").read().strip():
        rules = load_rules(SEEDS_DIR)
    else:
        lines = [l[2:].strip() for l in old.splitlines() if l.startswith("- ")][:MAX_RULES]
        rules = [dict(id=f"R{n:02d}", rule=line, check="Does my move follow this rule?") for n, line in enumerate(lines, 1)]
    seed_new(folder, rules)
    return rules
