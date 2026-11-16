import os, sys, json, shutil
import chess, pytest
import match, learn, knowledge, evidence, prompts

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
REVIEWS = os.path.join(os.path.dirname(FIXTURES), "..", "games")

@pytest.fixture
def folder(tmp_path, monkeypatch):   # games 1-3 with their reviews, seed rules, principles mode
    if not os.path.exists(os.path.join(REVIEWS, "review_1.jsonl")):
        pytest.skip("needs games/review_1-3.jsonl")
    for i in (1, 2, 3):
        shutil.copy(os.path.join(FIXTURES, f"game_{i}.pgn"), tmp_path / f"game_{i}.pgn")
        shutil.copy(os.path.join(REVIEWS, f"review_{i}.jsonl"), tmp_path / f"review_{i}.jsonl")
    monkeypatch.setattr(match, "GAMES_DIR", str(tmp_path))
    monkeypatch.setattr(match, "LEARN_MODE", "principles")
    monkeypatch.setattr(match, "print", lambda *a, **k: None, raising=False)
    knowledge.init_folder(str(tmp_path), "lessons")
    match.claude_log = open(tmp_path / "test.log", "w", encoding="utf-8")
    yield tmp_path
    match.claude_log.close()

def block(*principles):
    return "<analysis>winners check more</analysis>\n<principles>\n" + "\n".join(principles) + "\n</principles>"

def one(when="An enemy knight is near my queen and rooks", do="Move the queen or a rook so no knight jump attacks two of them.",
        check="Can an enemy knight attack two of my queen, rooks or king after this move?", evidence="E1 E2", id=None):
    return (f'<principle{f" id={chr(34)}{id}{chr(34)}" if id else ""} evidence="{evidence}"><when>{when}</when>'
            f"<do>{do}</do><check>{check}</check></principle>")

def test_traits():
    board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 0 1")
    assert {"capture", "check", "queen_move"} <= set(evidence.traits(board, board.parse_san("Qxf7#")))
    assert evidence.traits(board, board.parse_san("a3")) == ["pawn_push", "quiet"]
    assert "retreat" in evidence.traits(board, board.parse_san("Bf1"))

def test_report_is_xml_over_all_games(folder):
    games = evidence.load_games(str(folder))
    xml, items = evidence.report(games)
    assert [g["game"] for g in games] == [1, 2, 3] and all(g["outcome"] == "lost" for g in games)
    for tag in ("games", "winner_vs_loser", "why_claude_lost", "weak_positions", "turning_points", "winner_moves"):
        assert f"<{tag} " in xml and f"</{tag}>" in xml
    assert len({r["game"] for k, r in items.items() if k[0] == "E"}) == 3   # turning points come from every game
    assert all(r["player"] == "Claude" and r["loss"] >= evidence.BAD_LOSS for k, r in items.items() if k[0] == "E")

def test_principles_round_trip_and_seed(folder):
    seeded = knowledge.load_principles(str(folder))   # no principles.xml yet: the seed rules, WHEN = every move
    assert seeded and seeded[0]["when"] == "Every move" and seeded[0]["id"] == "R01"
    knowledge.save_principles(str(folder), [knowledge.principle("R20", "My king & queen share a file", "Move one off it.", "Same file?", ["E1"])])
    loaded = knowledge.load_principles(str(folder))
    assert loaded[0]["when"] == "My king & queen share a file" and loaded[0]["evidence"] == ["E1"]

@pytest.mark.parametrize("bad, why", [
    (one(when="Every move", do="Be careful and think harder."), "name no piece"),
    (one(when="My king is on g1 and a knight is on f3"), "exact squares"),
    (one(check="Count the attackers"), "yes/no question"),
    (one(evidence="E1"), "different games"),
    (one(evidence="E1 E99"), "do not exist"),
    (one(do="Move the queen " + "and the rook and the king " * 6), "words")])
def test_rejects_bad_principles(folder, bad, why):
    games = evidence.load_games(str(folder))
    items = {"E1": dict(game=1), "E2": dict(game=2)}
    kept, problems = learn.parse_principles(block(bad), [], items, len(games))
    assert kept == [] and any(why in p for p in problems)

def test_ids_kept_only_when_unchanged(folder):
    current = knowledge.load_principles(str(folder))
    first = current[0]
    same = one(when=first["when"], do=first["do"], check=first["check"], evidence="", id=first["id"])
    reworded = one(id=current[1]["id"])
    kept, problems = learn.parse_principles(block(same, reworded), current, {"E1": dict(game=1), "E2": dict(game=2)}, 3)
    assert problems == [] and len(kept) == 2
    final = learn.with_ids(kept, current, knowledge.load_stats(str(folder)), 3)
    assert final[0]["id"] == first["id"] and final[1]["id"] not in {p["id"] for p in current}

def answers(monkeypatch, distilled, moves):   # Claude: the distill call returns `distilled`; a move prompt returns moves(prompt)
    calls = []
    def fake(prompt, timeout=None, effort=None):
        calls.append(prompt)
        return distilled if "<current_principles" in prompt else f"PLAN: none apply\nEVAL: +0.0 | TREND: same | WHY: x\nMOVE: {moves(prompt)}"
    monkeypatch.setattr(match, "ask_claude", fake)
    return calls

def setup_validation(folder, monkeypatch):
    games = evidence.load_games(str(folder))
    positions = learn.test_positions(games)
    best = {r["fen_before"]: r["best_san"] for r in positions}
    played = {r["fen_before"]: r["san"] for r in positions}
    pick = lambda prompt, table: next(san for fen, san in table.items() if fen in prompt)
    _, items = evidence.report(games)
    e = [k for k in items if k[0] == "E"]
    two = " ".join([e[0], next(k for k in e if items[k]["game"] != items[e[0]]["game"])])
    return best, played, pick, two

def test_better_principles_are_adopted(folder, monkeypatch):
    best, played, pick, two = setup_validation(folder, monkeypatch)
    new_marker = "no knight jump attacks two of them"
    calls = answers(monkeypatch, block(one(evidence=two)),
                    lambda prompt: pick(prompt, best if new_marker in prompt else played))   # new list finds the best moves
    learn.learn_principles(3)
    saved = knowledge.load_principles(str(folder))
    assert len(saved) == 1 and new_marker in saved[0]["do"] and saved[0]["id"] == "R12"
    history = [json.loads(l) for l in open(folder / "principles_history.jsonl")]
    assert history[-1]["adopted"] and history[-1]["candidate_loss"] == 0 < history[-1]["current_loss"]
    assert "<evidence " in calls[0] and "<turning_point " in calls[0] and "<requirements>" in calls[0]
    assert "<position>" in calls[1] and "<principles" in calls[1] and "<legal_moves>" in calls[1]
    assert os.path.exists(folder / "principles_after_game_3.xml") and os.path.exists(folder / "evidence_after_game_3.xml")

def test_worse_principles_are_rejected(folder, monkeypatch):
    best, played, pick, two = setup_validation(folder, monkeypatch)
    new_marker = "no knight jump attacks two of them"
    answers(monkeypatch, block(one(evidence=two)), lambda prompt: pick(prompt, played if new_marker in prompt else best))
    before = knowledge.load_principles(str(folder))
    learn.learn_principles(3)
    assert [p["id"] for p in knowledge.load_principles(str(folder))] == [p["id"] for p in before]
    assert not os.path.exists(folder / "principles.xml") or "no knight jump" not in open(folder / "principles.xml").read()
    assert not json.loads(open(folder / "principles_history.jsonl").readlines()[-1])["adopted"]

def test_move_prompt_is_xml_in_principles_mode(folder, monkeypatch):
    monkeypatch.setattr(match, "rule_list", knowledge.load_principles(str(folder)))
    monkeypatch.setattr(match, "assessments", [dict(move_number=1, self_eval=0.3, trend="same", why="equal")])
    prompt, retrieved, shown, phase = match.build_prompt(chess.Board())
    assert retrieved == [] and "R01" in shown
    for tag in ("<task>", "<position>", "<fen>", "<principles", '<principle id="R01">', "<when>", "<check>",
                "<my_recent_assessments", "<answer_format>"):
        assert tag in prompt
    assert prompt.rstrip().endswith("</answer_format>") and "MOVE: <move copied exactly" in prompt
