import chess, chess.engine, chess.pgn, subprocess, shutil, re, datetime, os, json, time
import knowledge   # rules.md + lessons.jsonl

STOCKFISH = r"E:\apps\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe"  # change to your stockfish path
STOCKFISH_SKILL = 10                        # 0 (weakest) .. 20 (strongest)
CLAUDE = shutil.which("claude")             # path to the Claude Code CLI
CLAUDE_MODEL = "opus"                     # sonnet / opus / haiku, or a full id like claude-opus-5-5
CLAUDE_EFFORT = "medium"                    # how hard Claude thinks: low / medium / high / xhigh / max (higher = slower)
CLAUDE_TIMEOUT = 300                        # seconds per answer; slower = attempt fails and Claude is asked again
TIMED_OUT = "(no answer - timed out)"       # what ask_claude returns when Claude Code took too long
GAMES_DIR = "games"                         # game_<i>.log (moves), game_<i>.pgn and claude_<i>.log (thinking) go here
LEARN_MODE = "rules"                        # "lessons": rules.md + lessons.jsonl (learn.py); "rules": one old-style rules.md list
claude_log = None                           # Claude's thinking for the current game (opened in play_game)
models_used = set()                         # exact model ids Claude Code reported in this game
rules = ""                                  # rules Claude follows this game (loaded in play_game)

def games_file(name):   # paths follow GAMES_DIR at call time, so experiment.py can switch folders
    return os.path.join(GAMES_DIR, name)

def load_rules():   # the whole rules.md as text
    path = games_file("rules.md")
    return open(path, encoding="utf-8").read().strip() if os.path.exists(path) else ""

def init_games_dir():   # a new folder starts from seeds/; an old-style rules.md is migrated in "lessons" mode
    knowledge.init_folder(GAMES_DIR, LEARN_MODE)

def log(text):   # screen (and GUI) + claude_<i>.log
    print(text)
    log_file(text)

def log_file(text):   # claude_<i>.log only - for long things like the full prompt
    claude_log.write(text + "\n"); claude_log.flush()

def next_game_number():   # 1 + highest existing game_<i>.log
    init_games_dir()
    numbers = [int(m.group(1)) for f in os.listdir(GAMES_DIR) if (m := re.fullmatch(r"game_(\d+)\.log", f))]
    return max(numbers, default=0) + 1

def save_pgn(i, board, result="*", termination=None):   # "*" = game still in progress
    game = chess.pgn.Game.from_board(board)
    game.headers.update(Event="Claude vs Stockfish", Site="Local", Date=f"{datetime.date.today():%Y.%m.%d}",
                        Round=str(i), White=f"Claude ({', '.join(sorted(models_used)) or CLAUDE_MODEL})",
                        Black=f"Stockfish (skill {STOCKFISH_SKILL})", Result=result)
    if termination:
        game.headers["Termination"] = termination
    with open(games_file(f"game_{i}.pgn"), "w", encoding="utf-8") as f:
        f.write(str(game) + "\n")

def ask_claude(prompt, timeout=None):   # timeout: seconds, default CLAUDE_TIMEOUT
    timeout = timeout or CLAUDE_TIMEOUT
    # -p = answer once and exit, --tools "" = no tools (so it can't run Stockfish itself)
    # --strict-mcp-config + --setting-sources "" = skip MCP servers/plugins/hooks (~5s instead of ~37s per move)
    # --output-format json = reply comes with extra info, including the exact model id that answered
    log_file(f">>> REQUEST ({datetime.datetime.now():%H:%M:%S})\n{prompt}")
    start = time.time()
    try:
        result = subprocess.run([CLAUDE, "-p", prompt, "--tools", "", "--model", CLAUDE_MODEL, "--effort", CLAUDE_EFFORT,
                                 "--output-format", "json",
                                 "--no-session-persistence", "--strict-mcp-config", "--setting-sources", ""],
                                capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no pop-up console on Windows
    except subprocess.TimeoutExpired:   # Claude Code is killed and this attempt counts as failed
        log_file(f"<<< RESPONSE: none, timed out after {timeout}s")
        return TIMED_OUT
    seconds = time.time() - start
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:   # e.g. Claude Code printed an error instead of JSON
        log_file(f"<<< RESPONSE: not JSON after {seconds:.0f}s, exit code {result.returncode}\n"
                 f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}")
        return result.stdout.strip()
    models_used.update(data.get("modelUsage", {}))   # e.g. {"claude-sonnet-5-5": {...}}
    usage = data.get("usage", {})
    log_file(f"<<< RESPONSE [{', '.join(data.get('modelUsage', {}))}] {seconds:.0f}s, "
             f"{usage.get('input_tokens', 0) + usage.get('cache_read_input_tokens', 0) + usage.get('cache_creation_input_tokens', 0)} "
             f"in / {usage.get('output_tokens', 0)} out tokens, ${data.get('total_cost_usd', 0):.4f}, "
             f"stop: {data.get('stop_reason')}{', ERROR' if data.get('is_error') else ''}")
    return data.get("result", "").strip()

def claude_move(board, tries=3):
    legal = [board.san(m) for m in board.legal_moves]
    history = chess.Board().variation_san(board.move_stack) or "(none - game start)"
    prompt = (f"You are playing White in a chess game against the most strongest chess player in the world, prepare your move expecting the worst.\n"
              + (f"Rules you learned from your previous games - follow them:\n{rules}\n" if rules else "") +
              f"Moves so far: {history}\n"
              f"Board (uppercase = White, lowercase = Black):\n{board}\n"
              f"FEN: {board.fen()}\n"
              f"Legal moves: {', '.join(legal)}\n\n"
              "First think: describe the position and your thought on what you should do.\n"
              "Then finish with one last line in exactly this format:\n"
              "MOVE: <move>\n"
              "where <move> is copied exactly from the legal moves list.")

    for attempt in range(1, tries + 1):
        log(f"\n--- Move {board.fullmove_number}, attempt {attempt} ---")
        reply = ask_claude(prompt)   # writes the request + response details to claude_<i>.log
        log(reply)

        found = re.findall(r"MOVE:\s*([^\s*`]+)", reply)   # take the last "MOVE: xxx" line
        move = found[-1].strip(".") if found else None
        if move in legal:
            return board.parse_san(move)

        if reply == TIMED_OUT:
            log(f"[!] Claude took longer than {CLAUDE_TIMEOUT}s, asking again for a quicker answer")
            prompt += "\n\nYour previous answer took too long. Think briefly and answer quickly."
        else:
            log(f"[!] '{move}' is not a legal move, asking again")
            prompt += f"\n\nYour answer '{move}' was not in the legal moves list. Try again."
    return None  # gave up after all tries

def play_game(on_move=lambda board: None, i=None):   # on_move is called after every move (used by the GUI)
    global claude_log, rules                            # i = game number (parallel.py picks it; else next free one)
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH)
    engine.configure({"Skill Level": STOCKFISH_SKILL})
    board = chess.Board()
    models_used.clear()
    init_games_dir()
    rules = load_rules()   # the latest rules, so every new game uses everything learned so far

    i = i or next_game_number()
    claude_log = open(games_file(f"claude_{i}.log"), "w", encoding="utf-8")
    game_log = open(games_file(f"game_{i}.log"), "w", encoding="utf-8")
    header = (f"Game {i} - {datetime.datetime.now():%Y-%m-%d %H:%M} - "
              f"Claude [{CLAUDE_MODEL}] (White) vs Stockfish [skill {STOCKFISH_SKILL}] (Black)")
    game_log.write(header + "\n\n")
    log(f"===== {header} =====")

    result, reason = None, None
    while not board.is_game_over():
        if board.turn == chess.WHITE:
            player, move = "Claude", claude_move(board)
            if move is None: result, reason = "0-1", "Claude forfeits: no legal move"; break
        else:
            player, move = "Stockfish", engine.play(board, chess.engine.Limit(time=0.1)).move
        san = board.san(move)
        log(f">> {player} plays {san}")
        game_log.write(f"{board.fullmove_number}.{'' if board.turn == chess.WHITE else '..'} {san}  ({player})\n")
        game_log.flush()   # saved after every move, even if the game is stopped halfway
        board.push(move)
        save_pgn(i, board)
        on_move(board)

    result = result or board.result()
    save_pgn(i, board, result, reason)
    summary = (f"\nResult: {result}{f' ({reason})' if reason else ''}\n"
               f"Claude model: {', '.join(sorted(models_used)) or CLAUDE_MODEL}\n"
               f"Stockfish skill: {STOCKFISH_SKILL}\n\n"
               f"{board}\n\nPGN: {chess.Board().variation_san(board.move_stack)}")
    log(summary)
    game_log.write(summary + "\n")
    game_log.close(); claude_log.close()
    engine.quit()
    return result

if __name__ == "__main__":   # only runs with "python match.py", not when gui.py imports this file
    import learn
    i = next_game_number()
    play_game(i=i)
    learn.learn_from_game(i)   # review the game and update the rules for next time
