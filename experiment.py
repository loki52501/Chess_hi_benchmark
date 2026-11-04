import chess, chess.pgn, csv, json, os, re, statistics, sys
import match, learn, parallel, knowledge

GAMES_PER_CONFIG = 10
PARALLEL = 2          # games at the same time per config (RAM: ~0.4 GB each)
OUT_DIR = "experiments"

# each config is a set of overrides on match.py constants; each gets its own games_<name>/ folder,
# so rules.md and lessons.jsonl never leak from one config to another
OFF = dict(SELF_ASSESSMENT=False, ENDGAME_MODE=False, CLAUDE_EFFORT_ENDGAME=match.CLAUDE_EFFORT)
CONFIGS = {
    "baseline": {"match": dict(PROTOCOL="basic", LEARN_MODE="rules", **OFF)},     # old prompt, old-style rules list
    "review":   {"match": dict(PROTOCOL="basic", LEARN_MODE="lessons", **OFF)},   # + new learn.py (lessons + rules)
    "protocol": {"match": dict(PROTOCOL="full", LEARN_MODE="lessons", **dict(OFF, SELF_ASSESSMENT=True))},  # + full prompt
    "full":     {"match": dict(PROTOCOL="full", LEARN_MODE="lessons", SELF_ASSESSMENT=True, ENDGAME_MODE=True,
                               CLAUDE_EFFORT_ENDGAME="high")},                     # + endgame block, refs, endgame effort
}

def folder(name):
    return f"games_{name}"

def with_folder(name):   # the config's overrides plus its own games folder
    overrides = {module: dict(values) for module, values in CONFIGS[name].items()}
    overrides["match"]["GAMES_DIR"] = folder(name)
    return overrides

def run_config(name, n, parallel_games):
    overrides = with_folder(name)
    parallel.apply(overrides)
    match.init_games_dir()
    first = match.next_game_number()
    numbers = list(range(first, first + n))
    colors = {i: chess.WHITE if (i - first) % 2 == 0 else chess.BLACK for i in numbers}   # alternate colors
    print(f"\n===== config {name}: games {first}..{numbers[-1]} in {folder(name)}/, {parallel_games} at a time =====")
    return parallel.run_games(numbers, parallel_games, overrides, colors)

# --- summary ---------------------------------------------------------------------------------------

def game_numbers(games_dir):
    return sorted(int(m.group(1)) for f in os.listdir(games_dir) if (m := re.fullmatch(r"review_(\d+)\.json", f)))

def game_metrics(games_dir, i):
    review = json.load(open(f"{games_dir}/review_{i}.json", encoding="utf-8"))
    side = next(s for s in review["sides"].values() if s["player"] == "Claude")
    pgn = chess.pgn.read_game(open(f"{games_dir}/game_{i}.pgn", encoding="utf-8"))
    moves = knowledge.load_jsonl(f"{games_dir}/moves_{i}.jsonl")
    per_move = lambda key: statistics.mean(m.get(key) or 0 for m in moves) if moves else None
    cal = review.get("calibration") or {}
    return dict(outcome=learn.claude_outcome(pgn), accuracy=side["accuracy"],
                **{f"acc_{p}": side["accuracy_by_phase"][p] for p in ("opening", "middlegame", "endgame")},
                inacc_mistakes_per_40=(side["counts"]["Inaccuracy"] + side["counts"]["Mistake"]) * 40 / side["moves"] if side["moves"] else None,
                great=side["counts"]["Great"], miss=side["counts"]["Miss"], calibration_mae=cal.get("mae"),
                missed_slides=len(cal.get("missed_slides", [])),
                tokens_per_move=statistics.mean((m.get("tokens_in") or 0) + (m.get("tokens_out") or 0) for m in moves) if moves else None,
                cost_per_move=per_move("cost"), seconds_per_move=per_move("seconds"))

METRICS = ["accuracy", "acc_opening", "acc_middlegame", "acc_endgame", "inacc_mistakes_per_40", "great", "miss",
           "calibration_mae", "missed_slides", "tokens_per_move", "cost_per_move", "seconds_per_move"]

def mean_std(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    return statistics.mean(values), statistics.stdev(values) if len(values) > 1 else 0.0

def summarize(names):
    rows = []
    for name in names:
        games_dir = folder(name)
        if not os.path.isdir(games_dir) or not game_numbers(games_dir):
            continue
        games = [game_metrics(games_dir, i) for i in game_numbers(games_dir)]
        outcomes = [g["outcome"] for g in games]
        row = dict(config=name, games=len(games), wins=outcomes.count("WON"), draws=outcomes.count("DREW"),
                   losses=outcomes.count("LOST"))
        score, score_std = mean_std([{"WON": 1, "DREW": 0.5, "LOST": 0}.get(o) for o in outcomes])
        row["score"], row["score_std"] = score, score_std
        for metric in METRICS:
            row[metric], row[metric + "_std"] = mean_std([g[metric] for g in games])
        rows.append(row)
    if not rows:
        print("nothing to summarize yet")
        return rows
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    fmt = lambda r, m, digits=1: "-" if r[m] is None else f"{r[m]:.{digits}f} ± {r[m + '_std']:.{digits}f}"
    header = ["config", "games", "W/D/L", "score", "accuracy", "acc opening", "acc middlegame", "acc endgame",
              "inacc+mistakes /40", "Great /game", "Miss /game", "calibration MAE", "missed slides /game",
              "tokens /move", "cost $ /move", "seconds /move"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        lines.append("| " + " | ".join([r["config"], str(r["games"]), f"{r['wins']}/{r['draws']}/{r['losses']}", fmt(r, "score", 2),
                     fmt(r, "accuracy"), fmt(r, "acc_opening"), fmt(r, "acc_middlegame"), fmt(r, "acc_endgame"),
                     fmt(r, "inacc_mistakes_per_40"), fmt(r, "great"), fmt(r, "miss"), fmt(r, "calibration_mae", 2),
                     fmt(r, "missed_slides"), fmt(r, "tokens_per_move", 0), fmt(r, "cost_per_move", 4),
                     fmt(r, "seconds_per_move")]) + " |")
    text = ("# Experiment summary\n\nmean ± std over games; Claude's side only; cost/tokens/seconds are per Claude move "
            "(learning calls not included)\n\n" + "\n".join(lines) + "\n")
    with open(f"{OUT_DIR}/summary.md", "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    return rows

if __name__ == "__main__":   # python experiment.py [config ...] [--games N] [--parallel P] [--summary]
    args = sys.argv[1:]
    n = int(args[args.index("--games") + 1]) if "--games" in args else GAMES_PER_CONFIG
    p = int(args[args.index("--parallel") + 1]) if "--parallel" in args else PARALLEL
    names = [a for a in args if a in CONFIGS] or list(CONFIGS)
    if "--summary" not in args:
        for name in names:
            run_config(name, n, p)
    summarize(names)
