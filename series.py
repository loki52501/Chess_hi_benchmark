import time, collections
import match, learn   # same settings as match.py: CLAUDE_MODEL, STOCKFISH_SKILL, CLAUDE_COLOR, ...

TOTAL_GAMES = 50

# one game after the other: play -> learn (update the lessons) -> next game uses them
results = collections.Counter()
first = match.next_game_number()
for n in range(1, TOTAL_GAMES + 1):
    i = match.next_game_number()
    start = time.time()
    result = match.play_game(i=i)
    learn.learn_from_game(i)
    results[match.outcome(result)] += 1
    print(f"\n##### [{n}/{TOTAL_GAMES}] game {i}: {result} ({(time.time() - start) / 60:.1f} min) - "
          f"so far: {results['win']} wins, {results['draw']} draws, {results['loss']} losses #####\n")

summary = (f"{match.players()}, games {first}..{first + TOTAL_GAMES - 1}, played in sequence with learning\n"
           f"Claude wins: {results['win']}   draws: {results['draw']}   losses: {results['loss']}\n")
print(summary)
with open(f"{match.GAMES_DIR}/summary_{first}-{first + TOTAL_GAMES - 1}.txt", "w", encoding="utf-8") as f:
    f.write(summary)
