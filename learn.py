import chess, chess.engine, chess.pgn, glob, re
import match   # same Stockfish, Claude settings, games folder and rules file

MAX_RULES = 12        # keep the list short so Claude actually follows it
ANALYSIS_DEPTH = 14   # how deep full-strength Stockfish checks each position
LEARN_TIMEOUT = 600   # reviewing a whole game takes longer than one move

def clip(cp):   # centipawns, capped so a mate (huge number) doesn't swamp everything
    return max(-1000, min(1000, cp))

def review_moves(game):
    """Full-strength Stockfish rates every Claude (White) move: eval after it, and how much it lost vs the best move."""
    engine = chess.engine.SimpleEngine.popen_uci(match.STOCKFISH)   # no Skill Level = full strength
    board, evals, mistakes = game.board(), [], []
    for move in game.mainline_moves():
        if board.turn == chess.WHITE:
            before = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH))
            best, san, n = board.san(before["pv"][0]), board.san(move), board.fullmove_number
            board.push(move)
            after = engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH))
            ev_before = clip(before["score"].white().score(mate_score=10000))   # + = good for Claude
            ev_after = clip(after["score"].white().score(mate_score=10000))
            evals.append(f"{n}.{san} ({ev_after / 100:+.1f})")
            if ev_before - ev_after >= 100 and san != best:   # lost 1+ pawn of value
                kind = "BLUNDER" if ev_before - ev_after >= 300 else "mistake"
                mistakes.append((ev_before - ev_after, f"{n}. {san} ({kind}): eval {ev_before / 100:+.1f} -> "
                                                       f"{ev_after / 100:+.1f}, best was {best}"))
        else:
            board.push(move)
    engine.quit()
    worst = [text for _, text in sorted(mistakes, reverse=True)[:6]]
    return " ".join(evals), worst

def record():   # Claude's results over all finished games in the games folder
    results = [chess.pgn.read_headers(open(f, encoding="utf-8")).get("Result") for f in glob.glob(f"{match.GAMES_DIR}/game_*.pgn")]
    return f"{results.count('1-0')} wins, {results.count('1/2-1/2')} draws, {results.count('0-1')} losses"

def learn_from_game(i):
    match.claude_log = open(f"{match.GAMES_DIR}/learn_{i}.log", "w", encoding="utf-8")   # request + answer go here
    game = chess.pgn.read_game(open(f"{match.GAMES_DIR}/game_{i}.pgn", encoding="utf-8"))
    result, end = game.headers["Result"], game.end().board()
    how = game.headers.get("Termination") or (end.outcome().termination.name.lower() if end.outcome() else "unfinished")
    verdict = {"1-0": "WON", "0-1": "LOST", "1/2-1/2": "DREW"}.get(result, "did not finish")
    match.log(f"\n===== Learning from game {i}: Claude {verdict} ({result}, {how}) - checking moves with Stockfish =====")

    evals, worst = review_moves(game)
    old_rules = match.load_rules()
    prompt = (f"You are Claude. You just played White against Stockfish (skill {match.STOCKFISH_SKILL}) and {verdict} "
              f"({result}, {how}). Your record so far: {record()}.\n\n"
              f"Game: {chess.Board().variation_san(list(game.mainline_moves()))}\n\n"
              f"Full-strength Stockfish evaluation after each of your moves (+ = good for you, in pawns):\n{evals}\n\n"
              f"Your biggest mistakes according to Stockfish:\n" + ("\n".join(worst) or "none found") + "\n\n"
              f"Rules you followed this game:\n{old_rules or '(none yet - this was your first game)'}\n\n"
              "Task:\n"
              "1. Analyse the game: why did you win/lose/draw? Where was the turning point? "
              "What thinking errors led to your mistakes?\n"
              f"2. Write the updated rules for your next games: at most {MAX_RULES} short, concrete rules you can check "
              "while choosing a move. Keep rules that worked, rewrite vague ones, drop ones that did not help, "
              "add rules that would have prevented these mistakes.\n"
              "Put the rules between <rules> and </rules>, one per line starting with \"- \".")

    reply = match.ask_claude(prompt, timeout=LEARN_TIMEOUT)
    match.log_file(reply)
    found = re.search(r"<rules>(.*?)</rules>", reply, re.S)
    if not found:
        match.log("[!] No <rules> in Claude's answer - keeping the old rules")
    else:
        new_rules = found.group(1).strip()
        for path in (match.RULES_FILE, f"{match.GAMES_DIR}/rules_after_game_{i}.md"):   # current + history copy
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_rules + "\n")
        match.log(f"Rules updated after game {i}:\n{new_rules}")
    match.claude_log.close()
