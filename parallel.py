import os, sys, time, collections
from concurrent.futures import ProcessPoolExecutor, as_completed
import match, learn   # same settings as match.py: CLAUDE_MODEL, STOCKFISH_SKILL, ...

TOTAL_GAMES = 50
PARALLEL = 4   # games running at the same time. Each one needs ~0.4 GB RAM (Claude Code + Stockfish + Python)

def run_one(i):   # runs in its own process, so every game has its own log files and Stockfish
    sys.stdout = open(os.devnull, "w")   # 50 games printing at once is unreadable - everything is in the logs
    start = time.time()
    try:
        return i, match.play_game(i=i), time.time() - start
    except Exception as e:   # one broken game shouldn't stop the others
        return i, f"error: {e}", time.time() - start

def main():
    first = match.next_game_number()   # reserve numbers up front, so two games never share one
    numbers = range(first, first + TOTAL_GAMES)
    print(f"Playing games {first}..{first + TOTAL_GAMES - 1}, {PARALLEL} at a time - "
          f"Claude [{match.CLAUDE_MODEL}] vs Stockfish [skill {match.STOCKFISH_SKILL}]")

    results = collections.Counter()
    with ProcessPoolExecutor(max_workers=PARALLEL) as pool:
        for done, job in enumerate(as_completed(pool.submit(run_one, i) for i in numbers), 1):
            i, result, seconds = job.result()
            results[result] += 1
            print(f"[{done}/{TOTAL_GAMES}] game {i}: {result}  ({seconds / 60:.1f} min)")
            # learning runs here, one game at a time, so two games never rewrite rules.md at once.
            # Games that start after this use the new rules.
            try:
                learn.learn_from_game(i)
            except Exception as e:
                print(f"[!] learning from game {i} failed: {e}")

    summary = (f"Claude [{match.CLAUDE_MODEL}] (White) vs Stockfish [skill {match.STOCKFISH_SKILL}] (Black), "
               f"games {first}..{first + TOTAL_GAMES - 1}\n"
               f"Claude wins (1-0): {results['1-0']}   draws: {results['1/2-1/2']}   Stockfish wins (0-1): {results['0-1']}\n"
               + "".join(f"other: {r} x{n}\n" for r, n in results.items() if r not in ("1-0", "0-1", "1/2-1/2")))
    print("\n" + summary)
    with open(f"{match.GAMES_DIR}/summary_{first}-{first + TOTAL_GAMES - 1}.txt", "w", encoding="utf-8") as f:
        f.write(summary)

if __name__ == "__main__":   # needed on Windows: worker processes re-import this file
    main()
