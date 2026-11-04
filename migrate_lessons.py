import json, os, sys
import chess.pgn
import match, learn, knowledge, features

# one-time: python migrate_lessons.py [games folder] [--md before_after.md]
# Lessons written before pattern-based lessons name exact squares and have no "features" field, so they never fire.
# Claude rewrites each one (one call per lesson) into the pattern format; id, stats, source and kind are kept.

def source_position(folder, lesson):   # (board with history, Claude's color) at the lesson's source position, or (None, None)
    path = f"{folder}/game_{lesson['source'].get('game')}.pgn"
    if not os.path.exists(path):
        return None, None
    game = chess.pgn.read_game(open(path, encoding="utf-8"))
    board = next((b for b in learn.boards(game).values() if b.fen() == lesson["source"].get("fen")), None)
    return board, learn.claude_color(game)

def prompt_for(lesson, true_tags):
    s = lesson["source"]
    return (f"This is one of your chess lessons. It names exact squares, so it never fires in other games. "
            f"Rewrite it as a PATTERN.\n\n"
            f"[{lesson['id']}] ({lesson['kind']}, {lesson['phase']}, motifs: {', '.join(lesson['motifs'])})\n"
            f"rule: {lesson['rule']}\ntrigger: {lesson['trigger']}\ncheck: {lesson['check']}\n\n"
            f"It came from game {s.get('game')}, move {s.get('move')}: position (FEN) {s.get('fen')}"
            + (f", you played {s['played']}, best was {s['best']} ({s.get('cls')})" if s.get("played") else "") + "\n"
            f"Tags true in that position: {', '.join(true_tags) or '(none)'}\n\n"
            + learn.GOOD_LESSON + "\n"
            f"phase: one of {', '.join(knowledge.PHASES)}. motifs: from {', '.join(knowledge.MOTIFS)}.\n"
            "features: 1 to 4 tags from the list below, all true in the source position above.\n\n"
            f"=== TAG LIST ===\n{features.tag_list()}\n\n"
            "Keep the idea of the lesson; change only how it is described. Reply with JSON between <lesson> and </lesson>:\n"
            '<lesson>{"rule": "...", "trigger": "...", "check": "...", "phase": "middlegame", "motifs": ["..."], "features": ["..."]}</lesson>')

def problems(entry, true_tags):
    if not isinstance(entry, dict):
        return ["no JSON object between <lesson> and </lesson>"]
    return knowledge.problems_with(entry) + learn.tag_problems(entry.get("features"), true_tags)

def migrate(folder):
    lessons = knowledge.load_lessons(folder)
    match.claude_log = open(f"{folder}/migrate_lessons.log", "w", encoding="utf-8")   # every request and answer
    changed = []
    for lesson in lessons:
        if lesson.get("features"):
            continue   # already in the new format
        board, color = source_position(folder, lesson)
        true_tags = features.tags(board, color) if board is not None else []
        prompt = prompt_for(lesson, true_tags)
        entry = learn.ask_json("lesson", prompt)
        bad = problems(entry, true_tags)
        if bad:   # ask once more
            print(f"{lesson['id']}: asking again - {'; '.join(bad)}")
            entry = learn.ask_json("lesson", prompt + "\n\nYour previous answer had these problems:\n"
                                   + "\n".join(f"- {p}" for p in bad) + "\nSend the corrected <lesson> JSON.")
            bad = problems(entry, true_tags)
        if bad:
            print(f"{lesson['id']}: still invalid, left unchanged - {'; '.join(bad)}")
            continue
        before = {k: lesson[k] for k in ("rule", "trigger", "check", "phase", "motifs")}
        lesson.update({k: entry[k] for k in ("rule", "trigger", "check", "phase", "motifs", "features")})
        changed.append((lesson, before, true_tags))
        print(f"{lesson['id']}: done, features {lesson['features']}")
    knowledge.save_lessons(folder, lessons)
    match.claude_log.close()
    return changed

def write_markdown(changed, path):
    out = ["# Lesson migration: before and after\n", "Square-specific lessons rewritten as patterns, with feature tags "
           "(ids, stats, source and kind unchanged).\n"]
    for lesson, before, true_tags in changed:
        s = lesson["source"]
        out.append(f"## {lesson['id']} ({lesson['kind']}, from game {s.get('game')} move {s.get('move')})\n")
        out.append(f"Tags true at the source position: {', '.join(true_tags) or '(none)'}\n")
        out.append("| | before | after |\n|---|---|---|")
        for k in ("rule", "trigger", "check", "phase", "motifs"):
            show = lambda v: ", ".join(v) if isinstance(v, list) else str(v).replace("|", "/")
            out.append(f"| {k} | {show(before[k])} | {show(lesson[k])} |")
        out.append(f"| features | (none) | {', '.join(lesson['features'])} |\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

if __name__ == "__main__":
    args = sys.argv[1:]
    md = args[args.index("--md") + 1] if "--md" in args else "lessons_migration.md"
    folder = next((a for a in args if a != md and not a.startswith("--")), "games")
    match.GAMES_DIR = folder
    done = migrate(folder)
    write_markdown(done, md)
    print(f"{len(done)} lessons rewritten; before/after in {md}")
