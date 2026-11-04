import chess, chess.pgn, glob, json, os, re
import match, review, knowledge, features   # games folder + Claude, the review, rules.md / lessons.jsonl, position tags

MAX_RULES = 12          # "rules" mode: keep the one old-style list short
LEARN_TIMEOUT = 600     # reviewing a whole game takes longer than one move
MAX_MISTAKES = 10       # Claude's Inaccuracies/Mistakes/Blunders/Misses sent, worst first
MAX_GOOD_MOVES = 3      # Claude's Great/Best moves in hard positions sent as positive examples
MAX_SHOTS = 3           # Stockfish's Great moves against Claude
MAX_NEW = {"mistake": 2, "opponent_shot": 1, "self_assessment": 1, "good_move": 1}   # new lessons per game, per kind
UPDATE_OVERLAP = 0.5    # a new lesson sharing this share of its tags with an existing one updates that one instead
HARD_GAP = 10           # a position is "hard" when the 2nd-best move is this many win% worse
RETIRE_AFTER = 10       # a lesson cited this often with a help rate below Claude's average is retired
PROMOTE_GAMES = 3       # this many similar lessons from this many different games -> a general rule
SIMILAR_JACCARD = 0.5   # lessons are similar with the same primary motif and this share of feature tags in common
DEMOTE_AFTER_GAMES = 10 # a rule cited in this many games with a low help rate goes back to being a lesson
MISTAKE_CLASSES = ("Inaccuracy", "Mistake", "Blunder", "Miss")
KIND_OF = {"M": "mistake", "G": "good_move", "S": "opponent_shot", "D": "self_assessment"}

GOOD_LESSON = """Each lesson must have:
- rule: one sentence, 25 words or fewer, naming pieces, pawns, files or the king.
- trigger: what on the board makes this lesson apply, checkable from the position.
- rule and trigger describe the PATTERN, not the exact squares, so the lesson fires in other games too. Use relative
  terms: my king / my castled side / the enemy's half-open file toward my king / an enemy piece on my 2nd or 3rd rank /
  a knight that can fork two of my major pieces / my rook on the long diagonal of an enemy bishop / my 7th rank.
  Exact squares (b1, Qc3, a1-h8) belong in "source" only; a rule may name squares once, after "e.g.". The trigger names none.
- check: one yes/no question I can answer before moving; it must point to a specific action if the answer is wrong.
- features: 1 to 4 tags from the TAG LIST that are true in the source position (each item lists "Tags true here").
  They decide when the lesson is shown, so pick the tags that make the pattern, not incidental ones.
- phase and motifs from the allowed list.
- Don't add a lesson that says the same thing as an existing one; reword the existing one instead and give its id.
- No lessons like "be careful", "calculate more", "think harder", "play better".
Prefer fixing or merging existing lessons over adding new ones.
Bad: "With my king on b1 and a bishop on b4, play Bd4."
Good: "When my king is castled queenside and enemy pieces line up on the files in front of it, add a defender to my 2nd rank before attacking." """

def folder():
    return match.GAMES_DIR

def claude_color(game):
    return chess.WHITE if game.headers.get("White", "").startswith("Claude") else chess.BLACK

def claude_outcome(game):   # "WON" / "LOST" / "DREW" / "did not finish", from Claude's side
    result = game.headers.get("Result")
    if result == "1/2-1/2":
        return "DREW"
    if result in ("1-0", "0-1"):
        return "WON" if (result == "1-0") == (claude_color(game) == chess.WHITE) else "LOST"
    return "did not finish"

def record():   # Claude's results over all finished games in the games folder (not the _annotated copies)
    files = [f for f in glob.glob(match.games_file("game_*.pgn")) if re.search(r"game_\d+\.pgn$", f)]
    outcomes = [claude_outcome(chess.pgn.read_game(open(f, encoding="utf-8"))) for f in files]
    return f"{outcomes.count('WON')} wins, {outcomes.count('DREW')} draws, {outcomes.count('LOST')} losses"

def good_rate():   # Claude's share of Good-or-better moves over every reviewed game in the folder = the baseline
    rows = [json.loads(line) for f in glob.glob(match.games_file("review_*.jsonl")) for line in open(f, encoding="utf-8")]
    mine = [r for r in rows if r["player"] == "Claude"]
    return sum(r["cls"] in review.GOOD_OR_BETTER for r in mine) / len(mine) if mine else None

move_number = review.move_number

def boards(game):   # ply -> the board before that move, with the move history (some tags look at recent moves)
    board, found = game.board(), {}
    for ply, move in enumerate(game.mainline_moves(), 1):
        found[ply] = board.copy()
        board.push(move)
    return found

def tags_at(board_before, color):
    return features.tags(board_before, color) if board_before is not None else []

def learn_from_game(i):
    match.claude_log = open(match.games_file(f"learn_{i}.log"), "w", encoding="utf-8")   # requests + answers go here
    game = chess.pgn.read_game(open(match.games_file(f"game_{i}.pgn"), encoding="utf-8"))
    end = game.end().board()
    how = game.headers.get("Termination") or (end.outcome().termination.name.lower() if end.outcome() else "unfinished")
    verdict, color = claude_outcome(game), "White" if claude_color(game) == chess.WHITE else "Black"
    match.log(f"\n===== Learning from game {i}: Claude ({color}) {verdict} ({game.headers['Result']}, {how}) "
              f"- reviewing moves with Stockfish =====")
    rows, summary = review.review_game(i, quiet=True)
    intro = (f"You are Claude. You just played {color} against Stockfish (skill {match.STOCKFISH_SKILL}) and {verdict} "
             f"({game.headers['Result']}, {how}). Your record so far: {record()}.\n\n"
             f"Game: {chess.Board().variation_san(list(game.mainline_moves()))}\n\n")
    try:
        if match.LEARN_MODE == "rules":
            learn_rules(i, rows, intro)
        else:
            update_stats(i, rows)
            learn_lessons(i, rows, summary, intro, boards(game), claude_color(game))
            baseline = good_rate()
            retire_lessons(baseline)
            promote(i)
            demote(i, baseline)
            save_copies(i)
    finally:
        match.claude_log.close()

# --- "rules" mode: Claude rewrites one old-style list (the baseline) ----------------------------

def learn_rules(i, rows, intro):
    mine = [r for r in rows if r["player"] == "Claude"]
    evals = " ".join(f"{move_number(r)}{r['san']} ({r['cp_after'] / 100:+.1f})" for r in mine)
    worst = [f"{move_number(r)} {r['san']} ({r['cls']}): eval {r['cp_before'] / 100:+.1f} -> {r['cp_after'] / 100:+.1f}, "
             f"best was {r['best_san']}" for r in sorted((r for r in mine if r["cls"] in MISTAKE_CLASSES), key=lambda r: -r["loss"])[:6]]
    old_rules = match.load_rules()
    prompt = (intro +
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
        return
    new_rules = found.group(1).strip()
    for path in (match.games_file("rules.md"), match.games_file(f"rules_after_game_{i}.md")):   # current + history copy
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_rules + "\n")
    match.log(f"Rules updated after game {i}:\n{new_rules}")

# --- "lessons" mode -------------------------------------------------------------------------------

def update_stats(i, rows):
    """For each rule/lesson Claude cited on a move: retrieved +1, helped +1 if the move was Good or better.
    Each game is counted once, even if learning from it runs again (e.g. series.py continuing after Ctrl+C)."""
    counted_file = match.games_file("stats_counted_games.json")
    counted = json.load(open(counted_file, encoding="utf-8")) if os.path.exists(counted_file) else []
    if i in counted:
        return
    stats, lessons = knowledge.load_stats(folder()), knowledge.load_lessons(folder())
    by_id = {l["id"]: l for l in lessons}
    for r in rows:
        if r["player"] != "Claude":
            continue
        good = r["cls"] in review.GOOD_OR_BETTER
        for x in r.get("cited") or []:
            entry = stats.setdefault(x, knowledge.new_rule_stats(i)) if x.startswith("R") else by_id.get(x)
            if entry is None:
                continue
            entry["retrieved"] = entry.get("retrieved", 0) + 1
            entry["helped"] = entry.get("helped", 0) + good
            if x.startswith("R") and i not in entry["cited_games"]:
                entry["cited_games"].append(i)
    knowledge.save_stats(folder(), stats)
    knowledge.save_lessons(folder(), lessons)
    with open(counted_file, "w", encoding="utf-8") as f:
        json.dump(counted + [i], f)

def items(rows, summary, positions=None, color=chess.WHITE):
    """The labelled things Claude learns from: M = mistakes, G = good moves, S = opponent shots, D = missed slides.
    positions: ply -> board before the move (from boards()), used to list the tags true at each item."""
    by_fen = {b.fen(): b for b in (positions or {}).values()}
    mine = [r for r in rows if r["player"] == "Claude"]
    found = {}
    for n, r in enumerate(sorted((r for r in mine if r["cls"] in MISTAKE_CLASSES), key=lambda r: -r["loss"])[:MAX_MISTAKES], 1):
        found[f"M{n}"] = dict(row=r, text=(
            f"[M{n}] {move_number(r)}{r['san']} - {r['cls']}, {r['phase']}, lost {r['loss']:.1f} win%\n"
            f"     FEN before: {r['fen_before']}\n"
            f"     Best: {r['best_san']}, line: {r['best_pv_san']}\n"
            f"     Your WHY at that move: {r.get('why') or '(none)'}"))
    hard = sorted((r for r in mine if r["cls"] in ("Great", "Best") and (r.get("multipv_gap") or 0) >= HARD_GAP),
                  key=lambda r: -r["multipv_gap"])[:MAX_GOOD_MOVES]
    for n, r in enumerate(hard, 1):
        found[f"G{n}"] = dict(row=r, text=(
            f"[G{n}] {move_number(r)}{r['san']} - {r['cls']}, {r['phase']}, the 2nd-best move was {r['multipv_gap']:.1f} win% worse\n"
            f"     FEN before: {r['fen_before']}"))
    # an opponent shot = a Stockfish Great move that isn't a recapture; the shot was usually set up 1-2 moves earlier,
    # so Claude gets its own last move before the shot and the one before that
    shots = sorted(((k, r) for k, r in enumerate(rows) if k and r["player"] == "Stockfish" and r["cls"] == "Great"
                    and not r.get("recapture")), key=lambda pair: -(pair[1].get("multipv_gap") or 0))[:MAX_SHOTS]
    for n, (k, r) in enumerate(shots, 1):
        prev, earlier = rows[k - 1], (rows[k - 3] if k >= 3 else None)
        found[f"S{n}"] = dict(row=prev, text=(
            f"[S{n}] Stockfish found {move_number(r)}{r['san']}!! (its 2nd best was {r['multipv_gap']:.1f} win% worse); "
            f"line: {r['best_pv_san']}\n"
            f"     Your move just before: {move_number(prev)}{prev['san']} ({prev['cls']}) from FEN {prev['fen_before']}\n"
            + (f"     Your move before that: {move_number(earlier)}{earlier['san']} ({earlier['cls']}) from FEN {earlier['fen_before']}\n"
               if earlier else "") +
            f"     Which of these two moves allowed the shot, and what should you have seen?"))
    for n, slide in enumerate((summary.get("calibration") or {}).get("missed_slides", []), 1):
        found[f"D{n}"] = dict(row=None, slide=slide, text=(
            f"[D{n}] Moves {slide['from_move']} to {slide['to_move']}: engine win% fell {slide['win_drop']:.1f} while you said "
            f"TREND {'/'.join(slide['trends'])}\n"
            f"     FEN at the start: {slide['fen_start']}\n     FEN at the end: {slide['fen_end']}\n"
            f"     Engine's best line at the start: {slide['best_pv_start']}\n"
            f"     Your WHY lines: " + " | ".join(w or "(none)" for w in slide["whys"])))
    for item in found.values():   # the tags a lesson from this item may use: the ones true at its source position
        fen = item["row"]["fen_before"] if item.get("row") else item["slide"]["fen_start"]
        item["tags"] = tags_at(by_fen.get(fen), color)
        item["text"] += "\n     Tags true here: " + (", ".join(item["tags"]) or "(none)")
    return found

def source_of(item, i):
    if item.get("row"):
        r = item["row"]
        return dict(game=i, move=(r["ply"] + 1) // 2, fen=r["fen_before"], played=r["san"], best=r["best_san"],
                    loss=r["loss"], cls=r["cls"])
    s = item["slide"]
    return dict(game=i, move=s["from_move"], fen=s["fen_start"], played=None, best=None, loss=s["win_drop"], cls="slide")

def lessons_prompt(rows, summary, intro, found, lessons, rules, stats):
    color = next((r["side"] for r in rows if r["player"] == "Claude"), "white")
    me, them = summary["sides"][color], summary["sides"]["black" if color == "white" else "white"]
    acc = lambda s, p: "-" if s["accuracy_by_phase"][p] is None else f"{s['accuracy_by_phase'][p]:.1f}"
    counts = lambda s: ", ".join(f"{c} {n}" for c, n in s["counts"].items() if n)
    section = lambda prefix: "\n".join(item["text"] for label, item in found.items() if label[0] == prefix) or "none"
    phases = {item["row"]["phase"] for item in found.values() if item.get("row")} | {"any"}
    if any(label[0] == "D" for label in found):
        phases |= {"opening", "middlegame", "endgame"}
    rate = lambda e: "-" if knowledge.help_rate(e) is None else f"{knowledge.help_rate(e):.0%}"
    rule_lines = "\n".join(f"[{r['id']}] {r['rule']} | CHECK: {r['check']}  (cited {stats.get(r['id'], {}).get('retrieved', 0)}, "
                           f"helped {rate(stats.get(r['id'], {}))})" for r in rules) or "(none)"
    lesson_lines = "\n".join(f"[{l['id']}] {l['phase']} | {', '.join(l['motifs'])} | cited {l['retrieved']}, helped {rate(l)}\n"
                             f"     rule: {l['rule']}\n     trigger: {l['trigger']}\n     check: {l['check']}\n"
                             f"     features: {', '.join(l.get('features') or []) or '(none)'}"
                             for l in lessons if l["status"] == "active" and l["phase"] in phases) or "(none yet)"
    return (intro +
            "=== ACCURACY ===\n"
            f"You: {me['accuracy']} overall, " + ", ".join(f"{p} {acc(me, p)}" for p in review.PHASES) + f"; {counts(me)}\n"
            f"Stockfish: {them['accuracy']} overall, " + ", ".join(f"{p} {acc(them, p)}" for p in review.PHASES) + f"; {counts(them)}\n\n"
            "=== MISTAKES (your Inaccuracies, Mistakes, Blunders and Misses, worst first) ===\n" + section("M") + "\n\n"
            "=== GOOD MOVES (hard positions where you found the right move) ===\n" + section("G") + "\n\n"
            "=== OPPONENT SHOTS (Stockfish's Great moves against you) ===\n" + section("S") + "\n\n"
            "=== MISSED SLIDES (your position got worse while your own TREND said same/better) ===\n" + section("D") + "\n\n"
            f"=== YOUR GENERAL RULES (always shown) ===\n{rule_lines}\n\n"
            f"=== YOUR ACTIVE LESSONS for {', '.join(sorted(phases))} ===\n{lesson_lines}\n\n"
            "=== TASK ===\n"
            "1. Briefly analyse: which patterns explain the MISTAKES? What did you do right in the GOOD MOVES? "
            "For each OPPONENT SHOT, which of your two moves before it allowed it, and what should you have seen? "
            "For each MISSED SLIDE, how should you have recognised the decline yourself?\n"
            "2. Update your lessons.\n" + GOOD_LESSON + "\n"
            "New lessons per game, by the kind of item they come from: at most 2 from MISTAKES, 1 from OPPONENT SHOTS, "
            "1 from MISSED SLIDES and 1 from GOOD MOVES. If a new lesson would share half or more of its features with an "
            "existing lesson, update that lesson instead.\n"
            f"phase: one of {', '.join(knowledge.PHASES)}. motifs: from {', '.join(knowledge.MOTIFS)}.\n"
            "Lessons from a MISSED SLIDE use the motif self_assessment or prophylaxis.\n"
            "Every new lesson names the item it comes from in \"source\" (e.g. \"M2\", \"G1\", \"S1\", \"D1\"); its features "
            "must be among that item's \"Tags true here\".\n"
            "\"update\" and \"retire\" take lesson ids (L...) only; general rules (R...) change only by promotion.\n\n"
            f"=== TAG LIST (for \"features\") ===\n{features.tag_list()}\n\n"
            "Reply with JSON between <lessons> and </lessons>, in this shape (Lxxx stands for a real lesson id from above):\n"
            "<lessons>\n"
            '{"add": [{"rule": "...", "trigger": "...", "check": "...", "phase": "middlegame", "motifs": ["king_safety"],\n'
            '          "features": ["king_castled_queenside", "my_king_attacked"], "source": "M1"}],\n'
            ' "update": [{"id": "Lxxx", "check": "..."}],\n'
            ' "retire": []}\n'
            "</lessons>")

def tag_problems(tags, allowed=None):   # unknown tags, or (for a new lesson) tags not true at its source position
    unknown = [t for t in tags or [] if t not in features.TAGS]
    if unknown:
        return [f"unknown feature tags {unknown}; use names from the TAG LIST"]
    if allowed is not None and set(tags) - set(allowed):
        return [f"features {sorted(set(tags) - set(allowed))} are not true at the source position (true there: {', '.join(allowed) or 'none'})"]
    return []

def parse_changes(reply, lessons, found):
    """(changes, problems): changes keeps only valid entries, problems says what was wrong."""
    block = re.search(r"<lessons>(.*?)</lessons>", reply, re.S)
    data, error = None, "no JSON object between <lessons> and </lessons>"
    try:
        data = json.loads(block.group(1)) if block else None
    except json.JSONDecodeError as e:
        error = f"the JSON between <lessons> and </lessons> does not parse ({e})"
    if not isinstance(data, dict):
        return None, [error]
    active = {l["id"] for l in lessons if l["status"] == "active"}
    changes, problems = {"add": [], "update": [], "retire": []}, []
    for entry in data.get("add") or []:
        if not isinstance(entry, dict):
            problems.append(f"add entry is not an object: {entry!r}")
            continue
        bad = knowledge.problems_with(entry)
        if entry.get("source") not in found:
            bad.append(f"source {entry.get('source')!r} is not one of {', '.join(found) or '(no items)'}")
        else:
            if entry["source"].startswith("D") and not {"self_assessment", "prophylaxis"} & set(entry.get("motifs") or []):
                bad.append("a lesson from a missed slide needs the motif self_assessment or prophylaxis")
            if isinstance(entry.get("features"), list):
                bad += tag_problems(entry["features"], found[entry["source"]].get("tags", []))
        problems += [f"add {str(entry.get('rule', ''))[:60]!r}: {p}" for p in bad]
        if not bad:
            changes["add"].append(entry)
    for entry in data.get("update") or []:
        if not isinstance(entry, dict) or entry.get("id") not in active:
            problems.append(f"update of unknown or inactive lesson {entry.get('id') if isinstance(entry, dict) else entry!r}")
            continue
        fields = [f for f in knowledge.LESSON_FIELDS if f in entry]
        bad = knowledge.problems_with(entry, fields=fields)
        if isinstance(entry.get("features"), list):
            bad += tag_problems(entry["features"])
        problems += [f"update {entry['id']}: {p}" for p in bad]
        if not bad and fields:
            changes["update"].append({f: entry[f] for f in ["id"] + fields})
    changes["retire"] = [x for x in data.get("retire") or [] if x in active]
    return changes, problems

def apply_changes(lessons, changes, found, i):
    by_id = {l["id"]: l for l in lessons}
    for u in changes["update"]:
        by_id[u["id"]].update({k: v for k, v in u.items() if k != "id"})
    for x in changes["retire"]:
        by_id[x]["status"] = "retired"
    used = {}   # new lessons per kind so far
    for entry in changes["add"]:
        label = entry["source"]
        kind = KIND_OF[label[0]]
        if used.get(kind, 0) >= MAX_NEW.get(kind, 0):   # an unused slot of one kind doesn't go to another
            match.log(f"  skipped new {kind} lesson (at most {MAX_NEW.get(kind, 0)} per game): {entry['rule']}")
            continue
        used[kind] = used.get(kind, 0) + 1
        fields = {k: entry[k] for k in ("rule", "trigger", "check", "phase", "motifs", "features")}
        twin = overlapping(lessons, entry["features"])
        if twin:   # prefer updating an existing lesson about the same pattern over adding a near-copy
            match.log(f"  new lesson shares {UPDATE_OVERLAP:.0%}+ of its tags with {twin['id']}: updating {twin['id']} instead")
            twin.update(fields)
            continue
        lessons.append(dict(id=knowledge.next_lesson_id(lessons), **fields, source=source_of(found[label], i), kind=kind,
                            created_game=i, retrieved=0, helped=0, status="active"))
    return lessons

def overlapping(lessons, tags):   # the active lesson sharing the biggest share (>= UPDATE_OVERLAP) of these tags, newest on ties
    tags = set(tags or [])
    best = None
    for l in lessons:
        if l.get("status") == "active" and tags:
            share = len(tags & set(l.get("features") or [])) / len(tags)
            if share >= UPDATE_OVERLAP and (best is None or share >= best[0]):
                best = (share, l)
    return best[1] if best else None

def learn_lessons(i, rows, summary, intro, positions=None, color=chess.WHITE):
    lessons, rules, stats = knowledge.load_lessons(folder()), knowledge.load_rules(folder()), knowledge.load_stats(folder())
    found = items(rows, summary, positions, color)
    prompt = lessons_prompt(rows, summary, intro, found, lessons, rules, stats)
    reply = match.ask_claude(prompt, timeout=LEARN_TIMEOUT)
    match.log_file(reply)
    changes, problems = parse_changes(reply, lessons, found)
    if problems:   # ask once more, then keep whatever is valid
        match.log("[!] Problems in the lessons answer, asking once more:\n" + "\n".join(f"  - {p}" for p in problems))
        retry = (prompt + f"\n\nYour previous answer:\n{reply}\n\nIt had these problems:\n"
                 + "\n".join(f"- {p}" for p in problems) + "\nSend the complete corrected <lessons> JSON again.")
        reply = match.ask_claude(retry, timeout=LEARN_TIMEOUT)
        match.log_file(reply)
        changes, problems = parse_changes(reply, lessons, found)
        if problems:
            match.log("[!] Still invalid, left out:\n" + "\n".join(f"  - {p}" for p in problems))
    if changes is None:
        match.log("[!] No usable lessons in Claude's answer - keeping the old lessons")
        return
    before = len(lessons)
    lessons = apply_changes(lessons, changes, found, i)
    knowledge.save_lessons(folder(), lessons)
    match.log(f"Lessons after game {i}: +{len(lessons) - before} new, {len(changes['update'])} updated, "
              f"{len(changes['retire'])} retired by Claude")
    for l in lessons[before:]:
        match.log(f"  NEW {l['id']} [{l['kind']}, {l['phase']}, {', '.join(l['motifs'])}] {l['rule']}\n"
                  f"      When: {l['trigger']}\n      Check: {l['check']}")

# --- retirement, promotion, demotion (decided in code; Claude only words the merge) -------------

def retire_lessons(baseline):
    if baseline is None:
        return
    lessons = knowledge.load_lessons(folder())
    for l in lessons:
        rate = knowledge.help_rate(l)
        if l["status"] == "active" and l["retrieved"] >= RETIRE_AFTER and rate < baseline:
            l["status"] = "retired"
            match.log(f"RETIRED {l['id']}: cited {l['retrieved']}x, helped {rate:.0%} < Claude's average {baseline:.0%} - {l['rule']}")
    knowledge.save_lessons(folder(), lessons)

def ask_json(tag, prompt):   # one Claude call whose answer is JSON between <tag> and </tag>; None if unusable
    reply = match.ask_claude(prompt, timeout=LEARN_TIMEOUT)
    match.log_file(reply)
    block = re.search(rf"<{tag}>(.*?)</{tag}>", reply, re.S)
    try:
        return json.loads(block.group(1)) if block else None
    except json.JSONDecodeError:
        return None

def declined_file():
    return match.games_file("promotions_declined.json")

def jaccard(a, b):
    a, b = set(a or []), set(b or [])
    return len(a & b) / len(a | b) if a | b else 0.0

def similar(a, b):   # same primary motif and at least half of their feature tags shared (Jaccard)
    return bool(a["motifs"]) and bool(b["motifs"]) and a["motifs"][0] == b["motifs"][0] \
        and jaccard(a.get("features"), b.get("features")) >= SIMILAR_JACCARD

def similar_groups(lessons):   # each active lesson with the lessons similar to it; biggest first, no duplicates
    active = [l for l in lessons if l["status"] == "active"]
    groups, seen = [], set()
    for seed in active:
        group = [seed] + [l for l in active if l is not seed and similar(seed, l)]
        ids = frozenset(l["id"] for l in group)
        if len(group) >= 2 and ids not in seen:
            seen.add(ids)
            groups.append(group)
    return sorted(groups, key=len, reverse=True)

def log_candidates(groups):   # what is close to being promoted, after every game
    lines = ["Promotion candidates (same primary motif, feature Jaccard >= %.1f):" % SIMILAR_JACCARD]
    for g in groups:
        shared = sorted(set.intersection(*(set(l.get("features") or []) for l in g)))
        games = sorted({l["created_game"] for l in g})
        ready = "READY" if len(g) >= PROMOTE_GAMES and len(games) >= PROMOTE_GAMES else f"needs {PROMOTE_GAMES} lessons from {PROMOTE_GAMES} games"
        lines.append(f"  {', '.join(l['id'] for l in g)} - motif {g[0]['motifs'][0]}, games {games}, "
                     f"shared tags: {', '.join(shared) or '-'} - {ready}")
    match.log("\n".join(lines) if groups else "Promotion candidates: none (no two active lessons are similar yet)")

def promotion_group(lessons):   # the largest similar group of 3+ active lessons from 3+ games not declined before
    declined = json.load(open(declined_file(), encoding="utf-8")) if os.path.exists(declined_file()) else []
    groups = similar_groups(lessons)
    log_candidates(groups)
    ready = [g for g in groups if len(g) >= PROMOTE_GAMES and len({l["created_game"] for l in g}) >= PROMOTE_GAMES
             and sorted(l["id"] for l in g) not in declined]
    return (ready[0] if ready else None), declined

def promote(i):
    lessons, rules, stats = knowledge.load_lessons(folder()), knowledge.load_rules(folder()), knowledge.load_stats(folder())
    group, declined = promotion_group(lessons)
    if not group:
        return
    replace = None
    if len(rules) >= knowledge.MAX_RULES:   # full: only replace a rule that has had a fair chance and does worst
        tried = [r for r in rules if stats.get(r["id"], {}).get("retrieved", 0) >= RETIRE_AFTER]
        if not tried:
            match.log(f"Promotion skipped: rules.md is full and no rule has been cited {RETIRE_AFTER}+ times yet")
            return
        replace = min(tried, key=lambda r: knowledge.help_rate(stats[r["id"]]))
    listing = "\n".join(f"[{l['id']}] (game {l['created_game']}) {l['rule']} | When: {l['trigger']} | Check: {l['check']} "
                        f"| features: {', '.join(l.get('features') or [])}" for l in group)
    shared = sorted(set.intersection(*(set(l.get("features") or []) for l in group)))
    prompt = (f"These {len(group)} lessons from {len({l['created_game'] for l in group})} different games describe the same "
              f"pattern (motif {group[0]['motifs'][0]}, shared feature tags: {', '.join(shared) or '-'}):\n{listing}\n\n"
              "It keeps coming back, so it becomes a general rule that is checked before every move. Write it as one rule "
              f"({knowledge.MAX_RULE_WORDS} words or fewer, a pattern naming pieces, pawns, files or the king; exact squares "
              "at most once, after \"e.g.\") plus a CHECK: one yes/no question.\n"
              "Reply with JSON between <promotion> and </promotion>, e.g.\n"
              '<promotion>{"rule": "...", "check": "...?"}</promotion>')
    ids = sorted(l["id"] for l in group)
    answer = ask_json("promotion", prompt)
    bad = knowledge.problems_with(answer or {}, fields=["rule", "check"])
    if bad:   # ask once more
        answer = ask_json("promotion", prompt + "\n\nYour previous answer had these problems:\n" + "\n".join(f"- {p}" for p in bad))
        bad = knowledge.problems_with(answer or {}, fields=["rule", "check"])
    if bad:   # remembered, so the same group isn't asked again after every game
        declined.append(ids)
        with open(declined_file(), "w", encoding="utf-8") as f:
            json.dump(declined, f)
        match.log(f"Promotion of {', '.join(ids)} skipped, the merged rule has problems: {'; '.join(bad)}")
        return
    new_id = knowledge.next_rule_id(rules, stats)
    if replace:
        rules = [r for r in rules if r["id"] != replace["id"]]
        stats[replace["id"]]["replaced_game"] = i
        match.log(f"REPLACED {replace['id']} (help rate {knowledge.help_rate(stats[replace['id']]):.0%}): {replace['rule']}")
    rules.append(dict(id=new_id, rule=answer["rule"].strip(), check=answer["check"].strip()))
    stats[new_id] = knowledge.new_rule_stats(i)
    for l in group:
        l["status"], l["promoted_to"] = "promoted", new_id
    knowledge.save_rules(folder(), rules)
    knowledge.save_stats(folder(), stats)
    knowledge.save_lessons(folder(), lessons)
    match.log(f"PROMOTED {', '.join(ids)} -> [{new_id}] {answer['rule']} | CHECK: {answer['check']}")

def demote(i, baseline):
    if baseline is None:
        return
    lessons, rules, stats = knowledge.load_lessons(folder()), knowledge.load_rules(folder()), knowledge.load_stats(folder())
    weak = [r for r in rules if len(stats.get(r["id"], {}).get("cited_games", [])) >= DEMOTE_AFTER_GAMES
            and knowledge.help_rate(stats[r["id"]]) < baseline]
    if not weak:
        return
    rule = min(weak, key=lambda r: knowledge.help_rate(stats[r["id"]]))   # one per game
    rate = knowledge.help_rate(stats[rule["id"]])
    answer = ask_json("demotion", (
        f"Your general rule [{rule['id']}] {rule['rule']} | CHECK: {rule['check']}\n"
        f"was cited in {len(stats[rule['id']]['cited_games'])} games, but only {rate:.0%} of those moves were Good or better "
        f"(your average is {baseline:.0%}). It will stop being shown before every move.\n"
        "Should it become a specific lesson that is only shown when it fits the position? If yes, write the trigger: "
        "what on the board makes it apply (a pattern, no exact squares), its phase, motifs, and 1 to 4 feature tags.\n"
        f"phase: one of {', '.join(knowledge.PHASES)}. motifs: from {', '.join(knowledge.MOTIFS)}.\n"
        f"Feature tags:\n{features.tag_list()}\n"
        "Reply with JSON between <demotion> and </demotion>, e.g.\n"
        '<demotion>{"keep_as_lesson": true, "trigger": "...", "phase": "middlegame", "motifs": ["pin"], '
        '"features": ["my_piece_pinned"]}</demotion>   or   <demotion>{"keep_as_lesson": false}</demotion>'))
    rules = [r for r in rules if r["id"] != rule["id"]]
    stats[rule["id"]]["demoted_game"] = i
    lesson = dict(rule=rule["rule"], check=rule["check"],
                  **{k: (answer or {}).get(k) for k in ("trigger", "phase", "motifs", "features")})
    usable = (answer and answer.get("keep_as_lesson") and not tag_problems(lesson["features"] or ["?"])
              and not knowledge.problems_with(lesson, fields=("trigger", "phase", "motifs", "features")))
    if usable:
        lessons.append(dict(id=knowledge.next_lesson_id(lessons), **lesson, source=dict(game=i, demoted_from=rule["id"]),
                            kind="demoted_rule", created_game=i, retrieved=0, helped=0, status="active"))
        match.log(f"DEMOTED {rule['id']} (help rate {rate:.0%}) -> lesson {lessons[-1]['id']}, when: {lesson['trigger']}")
    else:
        match.log(f"DEMOTED {rule['id']} (help rate {rate:.0%}) -> dropped")
    knowledge.save_rules(folder(), rules)
    knowledge.save_stats(folder(), stats)
    knowledge.save_lessons(folder(), lessons)

def save_copies(i):   # history: what the rules and lessons looked like after game i
    with open(match.games_file(f"rules_after_game_{i}.md"), "w", encoding="utf-8") as f:
        f.write(knowledge.format_rules(knowledge.load_rules(folder())))
    with open(match.games_file(f"lessons_after_game_{i}.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(l) + "\n" for l in knowledge.load_lessons(folder()))
