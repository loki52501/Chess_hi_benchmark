import time, collections
import match, learn   # same settings as match.py: CLAUDE_MODEL, STOCKFISH_SKILL, ...

TOTAL_GAMES = 50

# one game after the other: play -> learn (update rules.md) -> next game uses the new rules
results = collections.Counter()
first = match.next_game_number()
for n in range(1, TOTAL_GAMES + 1):
    i = match.next_game_number()
    start = time.time()
    result = match.play_game(i=i)
    learn.learn_from_game(i)
    results[result] += 1
    print(f"\n##### [{n}/{TOTAL_GAMES}] game {i}: {result} ({(time.time() - start) / 60:.1f} min) - "
          f"so far: {results['1-0']} wins, {results['1/2-1/2']} draws, {results['0-1']} losses #####\n")

summary = (f"Claude [{match.CLAUDE_MODEL}] (White) vs Stockfish [skill {match.STOCKFISH_SKILL}] (Black), "
           f"games {first}..{first + TOTAL_GAMES - 1}, played in sequence with learning\n"
           f"Claude wins (1-0): {results['1-0']}   draws: {results['1/2-1/2']}   Stockfish wins (0-1): {results['0-1']}\n")
print(summary)
with open(f"{match.GAMES_DIR}/summary_{first}-{first + TOTAL_GAMES - 1}.txt", "w", encoding="utf-8") as f:
    f.write(summary)
