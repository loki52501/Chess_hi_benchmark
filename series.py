import json, os, time, collections
import match, learn   # same settings as match.py: CLAUDE_MODEL, STOCKFISH_SKILL, CLAUDE_COLOR, ...

TOTAL_GAMES = 50

# one game after the other: play -> learn (update the lessons) -> next game uses them.
# games/series_checkpoint.json remembers how far the series got, so after Ctrl+C (or a crash)
# "python series.py" continues: a game stopped halfway goes on from its last position,
# a game whose learning step was interrupted is learned from again.

def checkpoint_path():
    return match.games_file("series_checkpoint.json")

def save(state):
    with open(checkpoint_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def load_or_start():
    match.init_games_dir()
    if os.path.exists(checkpoint_path()):
        state = json.load(open(checkpoint_path(), encoding="utf-8"))
        if sum(g.get("learned", False) for g in state["games"].values()) < state["total"]:
            print(f"Continuing the series from {checkpoint_path()}: games {state['first']}..{state['first'] + state['total'] - 1}")
            return state
    state = dict(first=match.next_game_number(), total=TOTAL_GAMES, started=time.strftime("%Y-%m-%d %H:%M"), games={})
    save(state)
    print(f"New series: games {state['first']}..{state['first'] + state['total'] - 1}")
    return state

def summary(state):
    results = collections.Counter(match.outcome(g["result"]) for g in state["games"].values() if "result" in g)
    return f"{results['win']} wins, {results['draw']} draws, {results['loss']} losses"

def main():
    state = load_or_start()
    i = state["first"]
    try:
        for n, i in enumerate(range(state["first"], state["first"] + state["total"]), 1):
            game = state["games"].setdefault(str(i), {})
            if game.get("learned"):
                continue
            start = time.time()
            if "result" not in game:
                game["result"] = match.play_game(i=i, resume=True)   # continues the game if it was stopped halfway
                save(state)
            learn.learn_from_game(i)
            game["learned"] = True
            save(state)
            print(f"\n##### [{n}/{state['total']}] game {i}: {game['result']} ({(time.time() - start) / 60:.1f} min) - "
                  f"so far: {summary(state)} #####\n")
    except KeyboardInterrupt:
        print(f"\nStopped. Run python series.py again to continue from game {i}.")
        raise SystemExit(1)

    last = state["first"] + state["total"] - 1
    text = f"{match.players()}, games {state['first']}..{last}, played in sequence with learning\nClaude: {summary(state)}\n"
    print(text)
    with open(match.games_file(f"summary_{state['first']}-{last}.txt"), "w", encoding="utf-8") as f:
        f.write(text)

if __name__ == "__main__":   # importing series.py (e.g. from a test) must not start a series
    main()
