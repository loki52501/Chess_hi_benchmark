import os, sys, time, collections
from concurrent.futures import ProcessPoolExecutor, as_completed
import match, learn   # same settings as match.py: CLAUDE_MODEL, STOCKFISH_SKILL, ...

TOTAL_GAMES = 50
PARALLEL = 4   # games running at the same time. Each one needs ~0.4 GB RAM (Claude Code + Stockfish + Python)

def apply(overrides):   # {"match": {"PROTOCOL": "basic"}, "learn": {...}} -> set those module constants
    for module, values in (overrides or {}).items():
        for name, value in values.items():
            setattr(sys.modules[module], name, value)

def run_one(i, overrides=None, color=None):   # runs in its own process, so every game has its own log files and Stockfish
    sys.stdout = open(os.devnull, "w")   # games printing at once is unreadable - everything is in the logs
    apply(overrides)                     # a worker process starts from the defaults, so settings are passed in
    if color is not None:
        match.CLAUDE_COLOR = color
    start = time.time()
    try:
        return i, match.play_game(i=i), match.CLAUDE_COLOR, time.time() - start
    except Exception as e:   # one broken game shouldn't stop the others
        return i, f"error: {e}", match.CLAUDE_COLOR, time.time() - start

def run_games(numbers, parallel=PARALLEL, overrides=None, colors=None):
    """Play the games in a pool; learning runs here in the main process, one game at a time, as each one finishes.
    colors: game number -> chess.WHITE / chess.BLACK (default: match.CLAUDE_COLOR). Returns {game number: outcome}."""
    apply(overrides)   # the learning below uses the same settings as the games
    outcomes = {}
    with ProcessPoolExecutor(max_workers=parallel) as pool:
        jobs = [pool.submit(run_one, i, overrides, (colors or {}).get(i)) for i in numbers]
        for done, job in enumerate(as_completed(jobs), 1):
            i, result, color, seconds = job.result()
            outcomes[i] = match.outcome(result, color)
            print(f"[{done}/{len(jobs)}] game {i} (Claude {'White' if color else 'Black'}): {result} = {outcomes[i]}  "
                  f"({seconds / 60:.1f} min)")
            # two games never rewrite rules.md / lessons.jsonl at once; games that start after this use the new knowledge
            if not str(result).startswith("error"):
                try:
                    learn.learn_from_game(i)
                except Exception as e:
                    print(f"[!] learning from game {i} failed: {e}")
    return outcomes

def main():
    first = match.next_game_number()   # reserve numbers up front, so two games never share one
    numbers = range(first, first + TOTAL_GAMES)
    print(f"Playing games {first}..{first + TOTAL_GAMES - 1}, {PARALLEL} at a time - "
          f"Claude [{match.CLAUDE_MODEL}] vs Stockfish [skill {match.STOCKFISH_SKILL}]")
    results = collections.Counter(run_games(numbers).values())
    summary = (f"{match.players()}, games {first}..{first + TOTAL_GAMES - 1}\n"
               f"Claude wins: {results['win']}   draws: {results['draw']}   losses: {results['loss']}\n"
               + "".join(f"other: {r} x{n}\n" for r, n in results.items() if r not in ("win", "draw", "loss")))
    print("\n" + summary)
    with open(f"{match.GAMES_DIR}/summary_{first}-{first + TOTAL_GAMES - 1}.txt", "w", encoding="utf-8") as f:
        f.write(summary)

if __name__ == "__main__":   # needed on Windows: worker processes re-import this file
    main()
