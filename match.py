import chess, chess.engine, chess.pgn, subprocess, shutil, re, datetime, os, json, sys, time
import knowledge, features, prompts   # rules.md + lessons.jsonl, what is on the board, the move prompts

# Stockfish: the STOCKFISH environment variable, else "stockfish" on the PATH (Linux / cloud), else this Windows path
STOCKFISH = (os.environ.get("STOCKFISH") or shutil.which("stockfish")
             or r"E:\apps\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe")
STOCKFISH_SKILL = 10                        # 0 (weakest) .. 20 (strongest)
CLAUDE_COLOR = chess.WHITE                  # chess.WHITE or chess.BLACK (experiment.py alternates)
CLAUDE = shutil.which("claude")             # path to the Claude Code CLI
CLAUDE_MODEL = "opus"                     # sonnet / opus / haiku, or a full id like claude-opus-5-5
CLAUDE_EFFORT = "medium"                    # how hard Claude thinks: low / medium / high / xhigh / max (higher = slower)
CLAUDE_EFFORT_ENDGAME = "high"              # used instead of CLAUDE_EFFORT once the position is an endgame
CLAUDE_TIMEOUT = 300                        # seconds per answer; slower = attempt fails and Claude is asked again
TIMED_OUT = "(no answer - timed out)"       # what ask_claude returns when Claude Code took too long
GAMES_DIR = "games"                         # game_<i>.log (moves), game_<i>.pgn and claude_<i>.log (thinking) go here
# "principles": one ordered list of general principles (principles.xml), re-derived after every game from ALL games:
#               what the winners did, why the loser lost; a new list is only kept if it plays better on test positions
# "lessons": rules.md + position-specific lessons.jsonl; "rules": one old-style rules.md list
LEARN_MODE = os.environ.get("LEARN_MODE", "principles")
PROTOCOL = "full"                           # "full": forcing structure, rules + lessons for this position; "basic": the old prompt
LESSONS_PER_MOVE = 5                        # lessons retrieved for each position (full protocol)
ENDGAME_MODE = True                         # full protocol: endgame principles + reference positions once in an endgame
SELF_ASSESSMENT = True                      # full protocol: show Claude its own last 5 EVAL/TREND/WHY lines (never engine output)
ASSESSMENTS_SHOWN = 5
ENDGAME_REFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "endgame_refs.jsonl")
claude_log = None                           # Claude's thinking for the current game (opened in play_game)
models_used = set()                         # exact model ids Claude Code reported in this game
rules = ""                                  # rules.md as text (basic protocol), loaded in play_game
rule_list, lessons = [], []                 # parsed rules and lessons (full protocol), loaded in play_game
last_call = {}                              # seconds / tokens / cost of the latest ask_claude call
last_move = {}                              # what claude_move learned about its latest move (ids, EVAL, cost, ...)
assessments = []                            # Claude's own EVAL/TREND/WHY for each of its moves this game
EVAL_NUMBER = re.compile(r"EVAL:\s*\**\s*([+-]?\d+(?:\.\d+)?)", re.I)
TREND = re.compile(r"TREND:\s*\**\s*(better|same|worse)\b", re.I)
WHY = re.compile(r"WHY:\s*\**\s*(.+)", re.I)

def games_file(name):   # paths follow GAMES_DIR at call time, so experiment.py can switch folders
    return os.path.join(GAMES_DIR, name)

def load_rules():   # the whole rules.md as text
    path = games_file("rules.md")
    return open(path, encoding="utf-8").read().strip() if os.path.exists(path) else ""

def init_games_dir():   # a new folder starts from seeds/; an old-style rules.md is migrated in "lessons" mode
    knowledge.init_folder(GAMES_DIR, "rules" if LEARN_MODE == "rules" else "lessons")

def log(text):   # claude_<i>.log + screen (and GUI)
    log_file(text)   # the file first, so nothing is lost even if the screen can't show the text
    try:
        print(text)
    except UnicodeEncodeError:   # e.g. Claude wrote "→" and the output goes to a file in Windows' cp1252
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding))

def log_file(text):   # claude_<i>.log only - for long things like the full prompt
    if claude_log is None or claude_log.closed:   # nothing open (e.g. building a prompt in a test)
        return
    claude_log.write(text + "\n"); claude_log.flush()

def next_game_number():   # 1 + highest existing game_<i>.log
    init_games_dir()
    numbers = [int(m.group(1)) for f in os.listdir(GAMES_DIR) if (m := re.fullmatch(r"game_(\d+)\.log", f))]
    return max(numbers, default=0) + 1

def save_pgn(i, board, result="*", termination=None):   # "*" = game still in progress
    game = chess.pgn.Game.from_board(board)
    claude, stockfish = f"Claude ({', '.join(sorted(models_used)) or CLAUDE_MODEL})", f"Stockfish (skill {STOCKFISH_SKILL})"
    white, black = (claude, stockfish) if CLAUDE_COLOR == chess.WHITE else (stockfish, claude)
    game.headers.update(Event="Claude vs Stockfish", Site="Local", Date=f"{datetime.date.today():%Y.%m.%d}",
                        Round=str(i), White=white, Black=black, Result=result)
    if termination:
        game.headers["Termination"] = termination
    with open(games_file(f"game_{i}.pgn"), "w", encoding="utf-8") as f:
        f.write(str(game) + "\n")

def outcome(result, color=None):   # "win" / "draw" / "loss" from Claude's side, or the result itself (e.g. "*", "error: ...")
    color = CLAUDE_COLOR if color is None else color
    if result == "1/2-1/2":
        return "draw"
    if result in ("1-0", "0-1"):
        return "win" if (result == "1-0") == (color == chess.WHITE) else "loss"
    return result

def players():   # "Claude [opus] (White) vs Stockfish [skill 10] (Black)"
    claude, stockfish = f"Claude [{CLAUDE_MODEL}]", f"Stockfish [skill {STOCKFISH_SKILL}]"
    return f"{claude} (White) vs {stockfish} (Black)" if CLAUDE_COLOR == chess.WHITE else f"{stockfish} (White) vs {claude} (Black)"

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

def log_retrieval(true_tags, phase, picked, top=10):   # why each lesson was or wasn't picked, in claude_<i>.log
    lines = [f"[retrieval] {phase}, tags true here: {', '.join(true_tags) or '-'}"]
    for s, l, matched in features.rank(lessons, true_tags, phase)[:top]:
        mark = "PICKED" if l in picked else "      "
        lines.append(f"  {mark} {l['id']} score {s:.2f}  matched: {', '.join(matched) or '-'}  "
                     f"(features: {', '.join(l.get('features') or []) or '-'}; phase {l['phase']})")
    log_file("\n".join(lines))

def principles_prompt(board, principles, own=()):   # the XML move prompt for this position with this list of principles
    f = features.features(board, board.turn)
    endgame = ENDGAME_MODE and f["phase"] == "endgame"
    refs = features.closest_refs(board, knowledge.load_jsonl(ENDGAME_REFS)) if endgame else []
    return prompts.xml_prompt(board, STOCKFISH_SKILL, principles, features.header(f), refs, endgame, own)

def build_prompt(board):   # (prompt, retrieved lesson ids, ids shown, phase)
    f = features.features(board, board.turn)
    if PROTOCOL == "basic":
        return prompts.basic_prompt(board, rules), [], set(), f["phase"]
    if LEARN_MODE == "principles":   # no position-specific lessons: the same principles decide every move
        own = assessments[-ASSESSMENTS_SHOWN:] if SELF_ASSESSMENT else []
        return principles_prompt(board, rule_list, own), [], {r["id"] for r in rule_list}, f["phase"]
    true_tags = features.tags(board, board.turn)
    picked = features.retrieve(lessons, true_tags, f["phase"], LESSONS_PER_MOVE)
    log_retrieval(true_tags, f["phase"], picked)
    endgame = ENDGAME_MODE and f["phase"] == "endgame"
    refs = features.closest_refs(board, knowledge.load_jsonl(ENDGAME_REFS)) if endgame else []
    own = assessments[-ASSESSMENTS_SHOWN:] if SELF_ASSESSMENT else []
    prompt = prompts.full_prompt(board, STOCKFISH_SKILL, rule_list, picked, features.header(f), refs, endgame, own)
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
            assessments.append(dict(move_number=board.fullmove_number, self_eval=self_eval, trend=trend, why=why))
            return board.parse_san(move)

        if reply == TIMED_OUT:
            log(f"[!] Claude took longer than {CLAUDE_TIMEOUT}s, asking again for a quicker answer")
            prompt += "\n\nYour previous answer took too long. Think briefly and answer quickly."
        else:
            log(f"[!] '{move}' is not a legal move, asking again")
            prompt += f"\n\nYour answer '{move}' was not in the legal moves list. Try again."
    return None  # gave up after all tries

def unfinished_moves(i):   # the moves of game i if its PGN says it is still in progress ("*"), else []
    path = games_file(f"game_{i}.pgn")
    if not os.path.exists(path):
        return []
    game = chess.pgn.read_game(open(path, encoding="utf-8"))
    return list(game.mainline_moves()) if game and game.headers.get("Result") == "*" else []

def restore(i, moves):
    """Resuming game i: keep the moves_<i>.jsonl lines for moves that are in the PGN, and rebuild Claude's own assessments."""
    kept = [m for m in knowledge.load_jsonl(games_file(f"moves_{i}.jsonl")) if m["ply"] <= len(moves)]
    with open(games_file(f"moves_{i}.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(m) + "\n" for m in kept)
    assessments.extend(dict(move_number=m["move_number"], self_eval=m.get("self_eval"), trend=m.get("trend"), why=m.get("why"))
                       for m in kept)

def play_game(on_move=lambda board: None, i=None, resume=False):   # on_move is called after every move (used by the GUI)
    """Play game i (default: the next free number). resume=True continues game i from its PGN if it was stopped halfway."""
    global claude_log, rules, rule_list, lessons, last_move
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH)
    engine.configure({"Skill Level": STOCKFISH_SKILL})
    files = []   # closed in finally, also when the game is stopped with Ctrl+C
    try:
        board = chess.Board()
        models_used.clear()
        assessments.clear()
        init_games_dir()
        rules = load_rules()   # the latest rules and lessons, so every new game uses everything learned so far
        rule_list, lessons = knowledge.load_rules(GAMES_DIR), knowledge.load_lessons(GAMES_DIR)
        if LEARN_MODE == "principles":
            rule_list = knowledge.load_principles(GAMES_DIR)

        i = i or next_game_number()
        earlier = unfinished_moves(i) if resume else []
        mode = "a" if earlier else "w"   # a resumed game adds to its logs
        claude_log = open(games_file(f"claude_{i}.log"), mode, encoding="utf-8")
        game_log = open(games_file(f"game_{i}.log"), mode, encoding="utf-8")
        if earlier:
            restore(i, earlier)
            for move in earlier:
                board.push(move)
        moves_log = open(games_file(f"moves_{i}.jsonl"), mode, encoding="utf-8")   # per Claude move: ids, EVAL, cost (for review.py)
        files += [claude_log, game_log, moves_log]
        header = (f"Game {i} - {datetime.datetime.now():%Y-%m-%d %H:%M} - "
                  f"{players()}" + (f" - resumed after {len(earlier)} half-moves" if earlier else ""))
        game_log.write(header + "\n\n")
        log(f"===== {header} =====")

        result, reason = None, None
        while not board.is_game_over():
            if board.turn == CLAUDE_COLOR:
                last_move = {}
                player, move = "Claude", claude_move(board)
                if move is None: result, reason = "0-1" if CLAUDE_COLOR == chess.WHITE else "1-0", "Claude forfeits: no legal move"; break
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
        return result
    finally:   # Stockfish and the log files are closed even when the game is interrupted
        engine.quit()
        for f in files:
            f.close()

if __name__ == "__main__":   # only runs with "python match.py", not when gui.py imports this file
    import learn
    i = next_game_number()
    play_game(i=i)
    learn.learn_from_game(i)   # review the game and update the rules for next time
