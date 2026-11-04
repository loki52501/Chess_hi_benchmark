import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # so "import learn" finds the repo files
import pytest
import match, learn, knowledge

def lesson(id, game=1, motif="king_activity", phase="endgame", retrieved=0, helped=0, status="active",
           tags=("rook_endgame", "my_passed_pawn")):
    return dict(id=id, rule=f"Bring the king toward the passed pawn ({id}).", trigger="rook endgame", check="Is my king near it?",
                phase=phase, motifs=[motif], features=list(tags), source={}, kind="mistake", created_game=game,
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
           phase="endgame", motifs=["king_activity", "rook_activity"], features=["rook_endgame"], source="M1")
FOUND = {"M1": dict(row=row(3, "Claude", "Mistake", loss=12.4), text="[M1] ...", tags=["rook_endgame", "my_passed_pawn"])}

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
    (dict(NEW, rule="Bring the king " + "and keep it near the pawns " * 5 + "on e4."), "words"),
    (dict(NEW, rule="With my king on b1, play Kc2 before the rook checks."), "exact squares"),
    (dict(NEW, features=[]), "missing features"),
    (dict(NEW, features=["rook_endgame", "kings_far_apart"]), "unknown feature tags"),
    (dict(NEW, features=["rook_endgame", "queens_off"]), "not true at the source position")])
def test_parse_rejects_bad_lessons(bad, why):
    changes, problems = learn.parse_changes(answer("lessons", {"add": [bad]}), [], FOUND)
    assert changes["add"] == [] and any(why in p for p in problems)

def test_slide_lesson_needs_self_assessment_motif():
    found = {"D1": dict(row=None, slide=dict(from_move=20, fen_start="fenA", win_drop=9.5), text="[D1] ...", tags=["rook_endgame"])}
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

def test_caps_per_kind():
    found = {f"M{n}": dict(row=row(2 * n + 1, "Claude", "Mistake", loss=10), text="", tags=[f"t{n}"]) for n in (1, 2, 3)}
    found["S1"] = dict(row=row(9, "Claude", "Best"), text="", tags=["x"])
    adds = [dict(NEW, rule=f"Push the passed pawn {n}.", source=f"M{n}", features=[f"tag_{n}"]) for n in (1, 2, 3)]
    lessons = learn.apply_changes([], {"add": adds, "update": [], "retire": []}, found, i=5)
    assert [l["rule"] for l in lessons] == ["Push the passed pawn 1.", "Push the passed pawn 2."]   # 3rd mistake: no slot
    assert all(l["kind"] == "mistake" for l in lessons)                                         # the shot slot stays unused
    shot = dict(NEW, rule="Watch the knight jump.", source="S1", features=["tag_9"])
    lessons = learn.apply_changes(lessons, {"add": [shot, dict(shot, rule="Another shot.", features=["tag_8"])],
                                            "update": [], "retire": []}, found, i=5)
    assert [l["kind"] for l in lessons] == ["mistake", "mistake", "opponent_shot"]

def test_new_lesson_with_shared_tags_updates_the_existing_one():
    old = lesson("L004", tags=["rook_endgame", "my_passed_pawn"], retrieved=6, helped=4)
    new = dict(NEW, rule="Put the rook behind the passed pawn.", features=["rook_endgame", "queens_off"])   # shares 50%
    lessons = learn.apply_changes([old], {"add": [new], "update": [], "retire": []}, FOUND, i=8)
    assert len(lessons) == 1 and lessons[0]["id"] == "L004" and lessons[0]["rule"] == "Put the rook behind the passed pawn."
    assert lessons[0]["features"] == ["rook_endgame", "queens_off"] and lessons[0]["retrieved"] == 6   # stats kept
    other = dict(NEW, rule="Trade into the pawn ending.", features=["queens_off", "pawn_endgame"])     # shares 0%
    assert len(learn.apply_changes([lesson("L004")], {"add": [other], "update": [], "retire": []}, FOUND, i=8)) == 2

def test_retry_once_then_keep_valid(folder, monkeypatch):
    monkeypatch.setattr(learn, "tags_at", lambda board, color: ["rook_endgame"])
    replies = iter([answer("lessons", {"add": [dict(NEW, rule="Think harder.")]}), answer("lessons", {"add": [NEW]})])
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: next(replies))
    rows = [row(1, "Claude", "Mistake", loss=12.4), row(2, "Stockfish", "Best")]
    side = dict(accuracy=80.0, accuracy_by_phase={"opening": None, "middlegame": None, "endgame": 80.0}, counts={"Mistake": 1})
    learn.learn_lessons(1, rows, {"sides": {"white": side, "black": side}}, "INTRO\n")
    saved = knowledge.load_lessons(str(folder))
    assert [l["rule"] for l in saved] == [NEW["rule"]] and saved[0]["kind"] == "mistake"

def test_retire_is_applied_and_survives_the_rest_of_learning(folder, monkeypatch):
    knowledge.save_lessons(str(folder), [lesson("L001", game=1), lesson("L002", game=2, tags=["queens_off"])])
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: answer("lessons", {"add": [], "update": [], "retire": ["L002"]}))
    rows = [row(1, "Claude", "Mistake", loss=12.4), row(2, "Stockfish", "Best")]
    side = dict(accuracy=80.0, accuracy_by_phase={"opening": None, "middlegame": None, "endgame": 80.0}, counts={"Mistake": 1})
    learn.learn_lessons(3, rows, {"sides": {"white": side, "black": side}}, "INTRO\n")
    learn.retire_lessons(0.6)        # the steps that run after it in learn_from_game must not undo the retire
    learn.promote(3)
    learn.demote(3, 0.6)
    learn.save_copies(3)
    status = {l["id"]: l["status"] for l in knowledge.load_lessons(str(folder))}
    assert status == {"L001": "active", "L002": "retired"}
    copy = {l["id"]: l["status"] for l in knowledge.load_jsonl(str(folder / "lessons_after_game_3.jsonl"))}
    assert copy["L002"] == "retired"

def test_prompt_example_uses_no_real_lesson_ids():
    lessons = [lesson(f"L00{n}") for n in range(1, 10)]
    side = dict(accuracy=80.0, accuracy_by_phase={"opening": None, "middlegame": None, "endgame": 80.0}, counts={})
    prompt = learn.lessons_prompt([row(1, "Claude", "Best")], {"sides": {"white": side, "black": side}}, "", {}, lessons, [], {})
    example = prompt[prompt.index("<lessons>"):]
    assert '"retire": []' in example and '"id": "Lxxx"' in example
    assert not any(f"L00{n}" in example for n in range(1, 10))

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
                 "[G1] 1.m1 - Great", "[S1] Stockfish found 2...m4!!", "Your move just before: 2.m3 (Mistake) from FEN fen3",
                 "Your move before that: 1.m1 (Great) from FEN fen1",
                 "[D1] Moves 20 to 24", "[R01]", "[L001] endgame", "No lessons like \"be careful\""):
        assert text in prompt, text

# --- stats, retirement, promotion, demotion ---------------------------------------------------

def test_recapture_is_not_an_opponent_shot():
    shot = dict(row(4, "Stockfish", "Great", gap=40), recapture=True)
    found = learn.items([row(1, "Claude", "Best"), row(2, "Stockfish", "Best"), row(3, "Claude", "Best"), shot],
                        {"sides": {}, "calibration": {}})
    assert not any(label.startswith("S") for label in found)

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

def test_similarity_uses_tags_and_primary_motif():
    a = lesson("L001", tags=["rook_endgame", "my_passed_pawn"])
    assert learn.similar(a, lesson("L002", tags=["rook_endgame", "my_passed_pawn", "queens_off"]))   # Jaccard 2/3
    assert not learn.similar(a, lesson("L003", tags=["rook_endgame", "queens_off"]))                  # Jaccard 1/3
    assert not learn.similar(a, lesson("L004", motif="pin"))                                          # other primary motif

def test_dissimilar_lessons_are_not_promoted(folder, monkeypatch):
    knowledge.save_lessons(str(folder), [lesson("L001", game=1), lesson("L002", game=2, tags=["queens_off", "pawn_endgame"]),
                                         lesson("L003", game=3, tags=["king_castled_queenside"])])
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: pytest.fail("should not ask"))
    learn.promote(5)

def test_candidates_logged_for_pairs(folder):
    knowledge.save_lessons(str(folder), [lesson("L001", game=1), lesson("L002", game=2), lesson("L003", game=2, motif="pin")])
    learn.promote(5)
    log = (folder / "test.log").read_text(encoding="utf-8")
    assert "Promotion candidates" in log and "L001, L002 - motif king_activity, games [1, 2]" in log and "needs 3 lessons" in log

def test_invalid_merged_rule_is_asked_again_then_remembered(folder, monkeypatch):
    knowledge.save_lessons(str(folder), [lesson("L001", game=1), lesson("L002", game=2), lesson("L003", game=3)])
    calls = []
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: calls.append(1) or answer("promotion", {
        "rule": "Think harder in endgames.", "check": "Am I focused?"}))
    learn.promote(5)
    learn.promote(6)
    assert len(calls) == 2 and len(knowledge.load_rules(str(folder))) == 11   # asked twice in game 5, not again in game 6

def test_demotion_turns_rule_into_lesson(folder, monkeypatch):
    stats = knowledge.load_stats(str(folder))
    stats["R04"].update(retrieved=20, helped=5, cited_games=list(range(1, 11)))
    knowledge.save_stats(str(folder), stats)
    monkeypatch.setattr(match, "ask_claude", lambda prompt, timeout=None: answer("demotion", {
        "keep_as_lesson": True, "trigger": "my rook stands on a diagonal of an enemy bishop", "phase": "middlegame",
        "motifs": ["rook_activity"], "features": ["my_rook_on_enemy_bishop_diagonal"]}))
    learn.demote(11, baseline=0.6)
    assert "R04" not in [r["id"] for r in knowledge.load_rules(str(folder))]
    new = knowledge.load_lessons(str(folder))[-1]
    assert new["kind"] == "demoted_rule" and new["source"]["demoted_from"] == "R04" and new["features"] == ["my_rook_on_enemy_bishop_diagonal"]
