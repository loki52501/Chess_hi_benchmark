import chess, chess.engine, chess.pgn, subprocess, shutil, re, datetime, os, json, time
import knowledge, features, prompts   # rules.md + lessons.jsonl, what is on the board, the move prompts

STOCKFISH = r"E:\apps\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe"  # change to your stockfish path
STOCKFISH_SKILL = 10                        # 0 (weakest) .. 20 (strongest)
CLAUDE = shutil.which("claude")             # path to the Claude Code CLI
CLAUDE_MODEL = "opus"                     # sonnet / opus / haiku, or a full id like claude-opus-5-5
CLAUDE_EFFORT = "medium"                    # how hard Claude thinks: low / medium / high / xhigh / max (higher = slower)
CLAUDE_EFFORT_ENDGAME = "high"              # used instead of CLAUDE_EFFORT once the position is an endgame
CLAUDE_TIMEOUT = 300                        # seconds per answer; slower = attempt fails and Claude is asked again
TIMED_OUT = "(no answer - timed out)"       # what ask_claude returns when Claude Code took too long
GAMES_DIR = "games"                         # game_<i>.log (moves), game_<i>.pgn and claude_<i>.log (thinking) go here
LEARN_MODE = "lessons"                      # "lessons": rules.md + lessons.jsonl (learn.py); "rules": one old-style rules.md list
PROTOCOL = "full"                           # "full": forcing structure, rules + lessons for this position; "basic": the old prompt
LESSONS_PER_MOVE = 5                        # lessons retrieved for each position (full protocol)
ENDGAME_MODE = True                         # full protocol: endgame principles + reference positions once in an endgame
ENDGAME_REFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "endgame_refs.jsonl")
claude_log = None                           # Claude's thinking for the current game (opened in play_game)
models_used = set()                         # exact model ids Claude Code reported in this game
rules = ""                                  # rules.md as text (basic protocol), loaded in play_game
rule_list, lessons = [], []                 # parsed rules and lessons (full protocol), loaded in play_game
last_call = {}                              # seconds / tokens / cost of the latest ask_claude call
last_move = {}                              # what claude_move learned about its latest move (ids, EVAL, cost, ...)
EVAL_NUMBER = re.compile(r"EVAL:\s*\**\s*([+-]?\d+(?:\.\d+)?)", re.I)
TREND = re.compile(r"TREND:\s*\**\s*(better|same|worse)\b", re.I)
WHY = re.compile(r"WHY:\s*\**\s*(.+)", re.I)

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

def ask_claude(prompt, timeout=None, effort=None):   # timeout: seconds, default CLAUDE_TIMEOUT; effort: default CLAUDE_EFFORT
    global last_call
    timeout, effort = timeout or CLAUDE_TIMEOUT, effort or CLAUDE_EFFORT
    last_call = dict(seconds=timeout, tokens_in=0, tokens_out=0, cost=0.0)
    # -p = answer once and exit, --tools "" = no tools (so it can't run Stockfish itself)
    # --strict-mcp-config + --setting-sources "" = skip MCP servers/plugins/hooks (~5s instead of ~37s per move)
    # --output-format json = reply comes with extra info, including the exact model id that answered
    log_file(f">>> REQUEST ({datetime.datetime.now():%H:%M:%S})\n{prompt}")
    start = time.time()
    try:
        result = subprocess.run([CLAUDE, "-p", prompt, "--tools", "", "--model", CLAUDE_MODEL, "--effort", effort,
                                 "--output-format", "json",
                                 "--no-session-persistence", "--strict-mcp-config", "--setting-sources", ""],
                                capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no pop-up console on Windows
    except subprocess.TimeoutExpired:   # Claude Code is killed and this attempt counts as failed
        log_file(f"<<< RESPONSE: none, timed out after {timeout}s")
        return TIMED_OUT
    seconds = time.time() - start
    last_call = dict(seconds=seconds, tokens_in=0, tokens_out=0, cost=0.0)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:   # e.g. Claude Code printed an error instead of JSON
        log_file(f"<<< RESPONSE: not JSON after {seconds:.0f}s, exit code {result.returncode}\n"
                 f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}")
        return result.stdout.strip()
    models_used.update(data.get("modelUsage", {}))   # e.g. {"claude-sonnet-5-5": {...}}
    usage = data.get("usage", {})
    tokens_in = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
    last_call = dict(seconds=seconds, tokens_in=tokens_in, tokens_out=usage.get("output_tokens", 0), cost=data.get("total_cost_usd", 0))
    log_file(f"<<< RESPONSE [{', '.join(data.get('modelUsage', {}))}] {seconds:.0f}s, effort {effort}, "
             f"{tokens_in} in / {usage.get('output_tokens', 0)} out tokens, ${data.get('total_cost_usd', 0):.4f}, "
             f"stop: {data.get('stop_reason')}{', ERROR' if data.get('is_error') else ''}")
    return data.get("result", "").strip()

def parse_assessment(reply):   # (self_eval, trend, why) from the last EVAL line; None for anything missing or malformed
    line = next((l for l in reversed(reply.splitlines()) if "EVAL:" in l.upper()), "")
    number, trend, why = EVAL_NUMBER.search(line), TREND.search(line), WHY.search(line)
    self_eval = max(-5.0, min(5.0, float(number.group(1)))) if number else None
    return self_eval, trend.group(1).lower() if trend else None, why.group(1).strip().strip("*").strip() if why else None

def parse_cited(reply, shown):   # R/L ids named in the PLAN line, only those Claude was actually shown
    line = next((l for l in reversed(reply.splitlines()) if l.strip().upper().lstrip("*").startswith("PLAN:")), "")
    return [x for x in dict.fromkeys(re.findall(r"\b([RL]\d+)\b", line)) if x in shown]

def build_prompt(board):   # (prompt, retrieved lesson ids, ids shown, phase)
    f = features.features(board, board.turn)
    if PROTOCOL == "basic":
        return prompts.basic_prompt(board, rules), [], set(), f["phase"]
    picked = features.retrieve(lessons, f, LESSONS_PER_MOVE)
    endgame = ENDGAME_MODE and f["phase"] == "endgame"
    refs = features.closest_refs(board, knowledge.load_jsonl(ENDGAME_REFS)) if endgame else []
    prompt = prompts.full_prompt(board, STOCKFISH_SKILL, rule_list, picked, features.header(f), refs, endgame)
    return prompt, [l["id"] for l in picked], {r["id"] for r in rule_list} | {l["id"] for l in picked}, f["phase"]

def claude_move(board, tries=3):
    global last_move
    legal = [board.san(m) for m in board.legal_moves]
    prompt, retrieved, shown, phase = build_prompt(board)
    effort = CLAUDE_EFFORT_ENDGAME if phase == "endgame" else CLAUDE_EFFORT
    spent = dict(seconds=0.0, tokens_in=0, tokens_out=0, cost=0.0)

    for attempt in range(1, tries + 1):
        log(f"\n--- Move {board.fullmove_number}, attempt {attempt} ---")
        reply = ask_claude(prompt, effort=effort)   # writes the request + response details to claude_<i>.log
        spent = {k: spent[k] + last_call.get(k, 0) for k in spent}
        log(reply)

        found = re.findall(r"MOVE:\s*([^\s*`]+)", reply)   # take the last "MOVE: xxx" line
        move = found[-1].strip(".") if found else None
        if move in legal:
            self_eval, trend, why = parse_assessment(reply)   # missing or malformed -> None, no retry for it
            last_move = dict(phase=phase, effort=effort, attempts=attempt, retrieved=retrieved,
                             cited=parse_cited(reply, shown), self_eval=self_eval, trend=trend, why=why, **spent)
            log(f"[move info] retrieved: {', '.join(retrieved) or '-'} | cited: {', '.join(last_move['cited']) or '-'} | "
                f"self_eval: {self_eval} | trend: {trend} | why: {why}")
            return board.parse_san(move)

        if reply == TIMED_OUT:
            log(f"[!] Claude took longer than {CLAUDE_TIMEOUT}s, asking again for a quicker answer")
            prompt += "\n\nYour previous answer took too long. Think briefly and answer quickly."
        else:
            log(f"[!] '{move}' is not a legal move, asking again")
            prompt += f"\n\nYour answer '{move}' was not in the legal moves list. Try again."
    return None  # gave up after all tries

def play_game(on_move=lambda board: None, i=None):   # on_move is called after every move (used by the GUI)
    global claude_log, rules, rule_list, lessons, last_move   # i = game number (parallel.py picks it; else next free one)
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH)
    engine.configure({"Skill Level": STOCKFISH_SKILL})
    board = chess.Board()
    models_used.clear()
    init_games_dir()
    rules = load_rules()   # the latest rules and lessons, so every new game uses everything learned so far
    rule_list, lessons = knowledge.load_rules(GAMES_DIR), knowledge.load_lessons(GAMES_DIR)

    i = i or next_game_number()
    claude_log = open(games_file(f"claude_{i}.log"), "w", encoding="utf-8")
    game_log = open(games_file(f"game_{i}.log"), "w", encoding="utf-8")
    moves_log = open(games_file(f"moves_{i}.jsonl"), "w", encoding="utf-8")   # per Claude move: ids, EVAL, cost (for review.py)
    header = (f"Game {i} - {datetime.datetime.now():%Y-%m-%d %H:%M} - "
              f"Claude [{CLAUDE_MODEL}] (White) vs Stockfish [skill {STOCKFISH_SKILL}] (Black)")
    game_log.write(header + "\n\n")
    log(f"===== {header} =====")

    result, reason = None, None
    while not board.is_game_over():
        if board.turn == chess.WHITE:
            last_move = {}
            player, move = "Claude", claude_move(board)
            if move is None: result, reason = "0-1", "Claude forfeits: no legal move"; break
        else:
            player, move = "Stockfish", engine.play(board, chess.engine.Limit(time=0.1)).move
        san = board.san(move)
        log(f">> {player} plays {san}")
        if player == "Claude":
            moves_log.write(json.dumps(dict(ply=len(board.move_stack) + 1, move_number=board.fullmove_number, san=san,
                                            **last_move)) + "\n")
            moves_log.flush()
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
    game_log.close(); claude_log.close(); moves_log.close()
    engine.quit()
    return result

if __name__ == "__main__":   # only runs with "python match.py", not when gui.py imports this file
    import learn
    i = next_game_number()
    play_game(i=i)
    learn.learn_from_game(i)   # review the game and update the rules for next time
