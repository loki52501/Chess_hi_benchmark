import chess, chess.pgn, glob, json, os, re
import match, review, knowledge   # games folder + Claude, the post-game review, rules.md / lessons.jsonl

MAX_RULES = 12          # "rules" mode: keep the one old-style list short
LEARN_TIMEOUT = 600     # reviewing a whole game takes longer than one move
MAX_MISTAKES = 10       # Claude's Inaccuracies/Mistakes/Blunders/Misses sent, worst first
MAX_GOOD_MOVES = 3      # Claude's Great/Best moves in hard positions sent as positive examples
MAX_SHOTS = 3           # Stockfish's Great moves against Claude
MAX_NEW_LESSONS = 3     # most new lessons per game
HARD_GAP = 10           # a position is "hard" when the 2nd-best move is this many win% worse
RETIRE_AFTER = 10       # a lesson cited this often with a help rate below Claude's average is retired
PROMOTE_GAMES = 3       # this many lessons from this many different games with one idea -> a general rule
DEMOTE_AFTER_GAMES = 10 # a rule cited in this many games with a low help rate goes back to being a lesson
MISTAKE_CLASSES = ("Inaccuracy", "Mistake", "Blunder", "Miss")
KIND_OF = {"M": "mistake", "G": "good_move", "S": "opponent_shot", "D": "self_assessment"}

GOOD_LESSON = """Each lesson must have:
- rule: one sentence, 25 words or fewer, naming specific pieces, pawns, squares or the king.
- trigger: what on the board makes this lesson apply, checkable from the FEN alone.
- check: one yes/no question I can answer before moving; it must point to a specific action if the answer is wrong.
- phase and motifs from the allowed list.
- Don't add a lesson that says the same thing as an existing one; reword the existing one instead and give its id.
- No lessons like "be careful", "calculate more", "think harder", "play better".
At most 3 new lessons per game. Prefer fixing or merging existing lessons over adding new ones.
Bad: "Be careful in endgames."  Good: "When the enemy has a passed pawn on the 6th, put a piece on its promotion square before making any other plan move." """

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
            learn_lessons(i, rows, summary, intro)
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
    """For each rule/lesson Claude cited on a move: retrieved +1, helped +1 if the move was Good or better."""
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

def items(rows, summary):
    """The labelled things Claude learns from: M = mistakes, G = good moves, S = opponent shots, D = missed slides."""
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
    shots = sorted(((rows[k - 1], r) for k, r in enumerate(rows) if k and r["player"] == "Stockfish" and r["cls"] == "Great"),
                   key=lambda pair: -(pair[1].get("multipv_gap") or 0))[:MAX_SHOTS]
    for n, (prev, r) in enumerate(shots, 1):
        found[f"S{n}"] = dict(row=prev, text=(
            f"[S{n}] You played {move_number(prev)}{prev['san']} ({prev['cls']}) from FEN {prev['fen_before']}\n"
            f"     then Stockfish found {move_number(r)}{r['san']}!! (its 2nd best was {r['multipv_gap']:.1f} win% worse); "
            f"line: {r['best_pv_san']}"))
    for n, slide in enumerate((summary.get("calibration") or {}).get("missed_slides", []), 1):
        found[f"D{n}"] = dict(row=None, slide=slide, text=(
            f"[D{n}] Moves {slide['from_move']} to {slide['to_move']}: engine win% fell {slide['win_drop']:.1f} while you said "
            f"TREND {'/'.join(slide['trends'])}\n"
            f"     FEN at the start: {slide['fen_start']}\n     FEN at the end: {slide['fen_end']}\n"
            f"     Engine's best line at the start: {slide['best_pv_start']}\n"
            f"     Your WHY lines: " + " | ".join(w or "(none)" for w in slide["whys"])))
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
                             f"     rule: {l['rule']}\n     trigger: {l['trigger']}\n     check: {l['check']}"
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
            "For each OPPONENT SHOT, what should you have anticipated on your move just before it? "
            "For each MISSED SLIDE, how should you have recognised the decline yourself?\n"
            "2. Update your lessons.\n" + GOOD_LESSON + "\n"
            f"phase: one of {', '.join(knowledge.PHASES)}. motifs: from {', '.join(knowledge.MOTIFS)}.\n"
            "Lessons from a MISSED SLIDE use the motif self_assessment or prophylaxis.\n"
            "Every new lesson names the item it comes from in \"source\" (e.g. \"M2\", \"G1\", \"S1\", \"D1\").\n"
            "\"update\" and \"retire\" take lesson ids (L...) only; general rules (R...) change only by promotion.\n"
            "Reply with JSON between <lessons> and </lessons>, exactly like this:\n"
            "<lessons>\n"
            '{"add": [{"rule": "...", "trigger": "...", "check": "...", "phase": "endgame", "motifs": ["king_activity"], "source": "M2"}],\n'
            ' "update": [{"id": "L003", "check": "..."}],\n'
            ' "retire": ["L007"]}\n'
            "</lessons>")

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
        problems += [f"add {str(entry.get('rule', ''))[:60]!r}: {p}" for p in bad]
        if not bad:
            changes["add"].append(entry)
    for entry in data.get("update") or []:
        if not isinstance(entry, dict) or entry.get("id") not in active:
            problems.append(f"update of unknown or inactive lesson {entry.get('id') if isinstance(entry, dict) else entry!r}")
            continue
        fields = [f for f in knowledge.LESSON_FIELDS if f in entry]
        bad = knowledge.problems_with(entry, fields=fields)
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
    for entry in changes["add"][:MAX_NEW_LESSONS]:
        label = entry["source"]
        lessons.append(dict(id=knowledge.next_lesson_id(lessons), rule=entry["rule"], trigger=entry["trigger"],
                            check=entry["check"], phase=entry["phase"], motifs=entry["motifs"],
                            source=source_of(found[label], i), kind=KIND_OF[label[0]], created_game=i,
                            retrieved=0, helped=0, status="active"))
    return lessons

def learn_lessons(i, rows, summary, intro):
    lessons, rules, stats = knowledge.load_lessons(folder()), knowledge.load_rules(folder()), knowledge.load_stats(folder())
    found = items(rows, summary)
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

def promotion_group(lessons):   # the largest group of 3+ active lessons from 3+ games with the same motif + phase
    declined = json.load(open(declined_file(), encoding="utf-8")) if os.path.exists(declined_file()) else []
    groups = {}
    for l in lessons:
        if l["status"] == "active" and l["motifs"]:
            groups.setdefault((l["motifs"][0], l["phase"]), []).append(l)
    candidates = [g for g in groups.values() if len({l["created_game"] for l in g}) >= PROMOTE_GAMES
                  and sorted(l["id"] for l in g) not in declined]
    return max(candidates, key=len, default=None), declined

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
    listing = "\n".join(f"[{l['id']}] (game {l['created_game']}) {l['rule']} | When: {l['trigger']} | Check: {l['check']}" for l in group)
    answer = ask_json("promotion", (
        f"These {len(group)} lessons from {len({l['created_game'] for l in group})} different games share the motif "
        f"{group[0]['motifs'][0]} in the {group[0]['phase']} phase:\n{listing}\n\n"
        "Do they express one general idea that should be checked before every move? If yes, write it as one general rule "
        f"({knowledge.MAX_RULE_WORDS} words or fewer, naming a piece, pawn, square, file or the king) plus a CHECK: one yes/no question.\n"
        "Reply with JSON between <promotion> and </promotion>, e.g.\n"
        '<promotion>{"same_idea": true, "rule": "...", "check": "...?"}</promotion>   or   <promotion>{"same_idea": false}</promotion>'))
    ids = sorted(l["id"] for l in group)
    if not answer or not answer.get("same_idea"):
        declined.append(ids)
        with open(declined_file(), "w", encoding="utf-8") as f:
            json.dump(declined, f)
        match.log(f"Promotion declined for {', '.join(ids)}")
        return
    bad = knowledge.problems_with(answer, fields=["rule", "check"])
    if bad:
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
        "what on the board makes it apply, checkable from the FEN alone, plus its phase and motifs.\n"
        f"phase: one of {', '.join(knowledge.PHASES)}. motifs: from {', '.join(knowledge.MOTIFS)}.\n"
        "Reply with JSON between <demotion> and </demotion>, e.g.\n"
        '<demotion>{"keep_as_lesson": true, "trigger": "...", "phase": "middlegame", "motifs": ["pin"]}</demotion>   or   '
        '<demotion>{"keep_as_lesson": false}</demotion>'))
    rules = [r for r in rules if r["id"] != rule["id"]]
    stats[rule["id"]]["demoted_game"] = i
    lesson = dict(rule=rule["rule"], check=rule["check"], **{k: (answer or {}).get(k) for k in ("trigger", "phase", "motifs")})
    if answer and answer.get("keep_as_lesson") and not knowledge.problems_with(lesson):
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
