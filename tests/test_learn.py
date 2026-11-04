import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # so "import learn" finds the repo files
import pytest
import match, learn, knowledge

def lesson(id, game=1, motif="king_activity", phase="endgame", retrieved=0, helped=0, status="active"):
    return dict(id=id, rule=f"Bring the king to e4 ({id}).", trigger="rook endgame", check="Is my king on e4?",
                phase=phase, motifs=[motif], source={}, kind="mistake", created_game=game,
                retrieved=retrieved, helped=helped, status=status)

def row(ply, player, cls, gap=None, loss=0.0, cited=None, why=None):
    return dict(ply=ply, side="white" if ply % 2 else "black", player=player, san=f"m{ply}", best_san="Kd5",
                best_pv_san="1. Kd5 Ke7", fen_before=f"fen{ply}", cls=cls, phase="endgame", loss=loss,
                multipv_gap=gap, cited=cited or [], why=why)

@pytest.fixture
def folder(tmp_path, monkeypatch):   # a fresh games folder with the seed rules and no lessons
    monkeypatch.setattr(match, "GAMES_DIR", str(tmp_path))
    knowledge.init_folder(str(tmp_path), "lessons")
    match.claude_log = open(tmp_path / "test.log", "w", encoding="utf-8")
    monkeypatch.setattr(match, "print", lambda *a, **k: None, raising=False)
    yield tmp_path
    match.claude_log.close()

def answer(tag, data):
    return f"some analysis\n<{tag}>{json.dumps(data)}</{tag}>"

NEW = dict(rule="In rook endgames bring the king toward the pawns before chasing checks with the rook.",
           trigger="rook endgame, my king 3+ squares from my pawns", check="Is my king closer to the pawns than the enemy king?",
           phase="endgame", motifs=["king_activity", "rook_activity"], source="M1")
FOUND = {"M1": dict(row=row(3, "Claude", "Mistake", loss=12.4), text="[M1] ...")}

# --- parsing Claude's lessons answer -----------------------------------------------------------

def test_parse_valid_add_update_retire():
    lessons = [lesson("L001"), lesson("L002")]
    changes, problems = learn.parse_changes(answer("lessons", {
        "add": [NEW], "update": [{"id": "L001", "check": "Is my king on e4 or d4?"}], "retire": ["L002", "L099"]}), lessons, FOUND)
    assert problems == [] and len(changes["add"]) == 1
    assert changes["update"] == [{"id": "L001", "check": "Is my king on e4 or d4?"}] and changes["retire"] == ["L002"]

@pytest.mark.parametrize("bad, why", [
    (dict(NEW, rule="Be careful in endgames."), "names no piece"),
    (dict(NEW, motifs=["tactics"]), "motifs"),
    (dict(NEW, trigger=""), "missing trigger"),
    (dict(NEW, source="X9"), "source"),
    (dict(NEW, rule="Bring the king " + "and keep it near the pawns " * 5 + "on e4."), "words")])
def test_parse_rejects_bad_lessons(bad, why):
    changes, problems = learn.parse_changes(answer("lessons", {"add": [bad]}), [], FOUND)
    assert changes["add"] == [] and any(why in p for p in problems)

def test_slide_lesson_needs_self_assessment_motif():
    found = {"D1": dict(row=None, slide=dict(from_move=20, fen_start="fenA", win_drop=9.5), text="[D1] ...")}
    slide = dict(NEW, source="D1")
    changes, problems = learn.parse_changes(answer("lessons", {"add": [slide]}), [], found)
    assert changes["add"] == [] and "missed slide" in problems[0]
    changes, problems = learn.parse_changes(answer("lessons", {"add": [dict(slide, motifs=["self_assessment"])]}), [], found)
    assert problems == [] and learn.apply_changes([], changes, found, 4)[0]["kind"] == "self_assessment"

def test_parse_bad_json():
    assert learn.parse_changes("<lessons>{oops</lessons>", [], FOUND)[0] is None
    assert learn.parse_changes("nothing here", [], FOUND)[0] is None

def test_apply_changes_fills_source_kind_and_id():
    lessons = learn.apply_changes([lesson("L004")], {"add": [NEW], "update": [], "retire": ["L004"]}, FOUND, i=9)
    new = lessons[-1]
    assert new["id"] == "L005" and new["kind"] == "mistake" and new["status"] == "active" and new["created_game"] == 9
    assert new["source"] == dict(game=9, move=2, fen="fen3", played="m3", best="Kd5", loss=12.4, cls="Mistake")
    assert lessons[0]["status"] == "retired"

def test_retry_once_then_keep_valid(folder, monkeypatch):
    replies = iter([answer("lessons", {"add": [dict(NEW, rule="Think harder.")]}), answer("lessons", {"add": [NEW]})])
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: next(replies))
    rows = [row(1, "Claude", "Mistake", loss=12.4), row(2, "Stockfish", "Best")]
    side = dict(accuracy=80.0, accuracy_by_phase={"opening": None, "middlegame": None, "endgame": 80.0}, counts={"Mistake": 1})
    learn.learn_lessons(1, rows, {"sides": {"white": side, "black": side}}, "INTRO\n")
    saved = knowledge.load_lessons(str(folder))
    assert [l["rule"] for l in saved] == [NEW["rule"]] and saved[0]["kind"] == "mistake"

# --- the prompt ------------------------------------------------------------------------------------

def test_prompt_sections():
    rows = [row(1, "Claude", "Great", gap=18), row(2, "Stockfish", "Best"), row(3, "Claude", "Mistake", loss=12.4, why="looked safe"),
            row(4, "Stockfish", "Great", gap=16), row(5, "Claude", "Best", gap=4)]
    side = dict(accuracy=80.0, accuracy_by_phase={"opening": None, "middlegame": None, "endgame": 80.0},
                counts={"Great": 1, "Best": 1, "Mistake": 1})
    summary = {"sides": {"white": side, "black": side},
               "calibration": {"missed_slides": [dict(from_move=20, to_move=24, win_drop=9.5, trends=["same"] * 5,
                                                      fen_start="fenA", fen_end="fenB", best_pv_start="20. Kd5", whys=["ok"] * 5)]}}
    found = learn.items(rows, summary)
    assert list(found) == ["M1", "G1", "S1", "D1"]          # gap 4 is not a hard position
    prompt = learn.lessons_prompt(rows, summary, "INTRO\n", found, [lesson("L001")], knowledge.load_rules(knowledge.SEEDS_DIR), {})
    for text in ("=== MISTAKES", "[M1] 2.m3 - Mistake, endgame, lost 12.4 win%", "Your WHY at that move: looked safe",
                 "[G1] 1.m1 - Great", "[S1] You played 2.m3 (Mistake) from FEN fen3", "Stockfish found 2...m4!!",
                 "[D1] Moves 20 to 24", "[R01]", "[L001] endgame", "No lessons like \"be careful\""):
        assert text in prompt, text

# --- stats, retirement, promotion, demotion ---------------------------------------------------

def test_update_stats_counts_citations(folder):
    knowledge.save_lessons(str(folder), [lesson("L001")])
    learn.update_stats(4, [row(1, "Claude", "Best", cited=["R01", "L001"]), row(3, "Claude", "Mistake", cited=["R01"]),
                           row(2, "Stockfish", "Best", cited=["R02"])])
    stats, lessons = knowledge.load_stats(str(folder)), knowledge.load_lessons(str(folder))
    assert stats["R01"]["retrieved"] == 2 and stats["R01"]["helped"] == 1 and stats["R01"]["cited_games"] == [4]
    assert stats["R02"]["retrieved"] == 0                    # Stockfish rows don't count
    assert lessons[0]["retrieved"] == 1 and lessons[0]["helped"] == 1

def test_update_stats_counts_each_game_once(folder):
    rows = [row(1, "Claude", "Best", cited=["R01"])]
    learn.update_stats(4, rows)
    learn.update_stats(4, rows)   # learning from game 4 again (e.g. series.py continuing)
    learn.update_stats(5, rows)
    assert knowledge.load_stats(str(folder))["R01"]["retrieved"] == 2

def test_retire_below_baseline(folder):
    knowledge.save_lessons(str(folder), [lesson("L001", retrieved=10, helped=3), lesson("L002", retrieved=10, helped=9),
                                         lesson("L003", retrieved=4, helped=0)])
    learn.retire_lessons(baseline=0.6)
    assert [l["status"] for l in knowledge.load_lessons(str(folder))] == ["retired", "active", "active"]

def test_promotion_adds_rule_and_marks_lessons(folder, monkeypatch):
    knowledge.save_lessons(str(folder), [lesson("L001", game=1), lesson("L002", game=2), lesson("L003", game=3),
                                         lesson("L004", game=3, motif="pin")])
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: answer("promotion", {
        "same_idea": True, "rule": "In rook endgames the king goes to the pawns first.", "check": "Is my king near the pawns?"}))
    learn.promote(5)
    rules, lessons = knowledge.load_rules(str(folder)), knowledge.load_lessons(str(folder))
    assert rules[-1]["id"] == "R12" and rules[-1]["rule"].startswith("In rook endgames")
    assert [l["status"] for l in lessons] == ["promoted"] * 3 + ["active"] and lessons[0]["promoted_to"] == "R12"

def test_promotion_needs_three_games(folder, monkeypatch):
    knowledge.save_lessons(str(folder), [lesson("L001", game=1), lesson("L002", game=1), lesson("L003", game=2)])
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: pytest.fail("should not ask"))
    learn.promote(5)

def test_promotion_replaces_weakest_tried_rule_when_full(folder, monkeypatch):
    rules = knowledge.load_rules(str(folder)) + [dict(id="R12", rule="Keep a rook on the d-file.", check="Is a rook on d?")]
    stats = knowledge.load_stats(str(folder))
    stats["R12"] = dict(knowledge.new_rule_stats(0), retrieved=10, helped=2)
    stats["R03"].update(retrieved=10, helped=6)
    knowledge.save_rules(str(folder), rules); knowledge.save_stats(str(folder), stats)
    knowledge.save_lessons(str(folder), [lesson("L001", game=1), lesson("L002", game=2), lesson("L003", game=3)])
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: answer("promotion", {
        "same_idea": True, "rule": "In rook endgames the king goes to the pawns first.", "check": "Is my king near the pawns?"}))
    learn.promote(5)
    ids = [r["id"] for r in knowledge.load_rules(str(folder))]
    assert "R12" not in ids and ids[-1] == "R13" and len(ids) == 12

def test_declined_promotion_is_not_asked_again(folder, monkeypatch):
    knowledge.save_lessons(str(folder), [lesson("L001", game=1), lesson("L002", game=2), lesson("L003", game=3)])
    calls = []
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: calls.append(1) or answer("promotion", {"same_idea": False}))
    learn.promote(5)
    learn.promote(6)
    assert len(calls) == 1 and len(knowledge.load_rules(str(folder))) == 11

def test_demotion_turns_rule_into_lesson(folder, monkeypatch):
    stats = knowledge.load_stats(str(folder))
    stats["R04"].update(retrieved=20, helped=5, cited_games=list(range(1, 11)))
    knowledge.save_stats(str(folder), stats)
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: answer("demotion", {
        "keep_as_lesson": True, "trigger": "rook on d2 or b2 and an enemy dark-squared bishop", "phase": "middlegame",
        "motifs": ["rook_activity"]}))
    learn.demote(11, baseline=0.6)
    assert "R04" not in [r["id"] for r in knowledge.load_rules(str(folder))]
    new = knowledge.load_lessons(str(folder))[-1]
    assert new["kind"] == "demoted_rule" and new["source"]["demoted_from"] == "R04" and new["trigger"].startswith("rook on d2")
