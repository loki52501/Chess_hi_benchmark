import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # so "import features" finds the repo files
import chess, chess.pgn, pytest
import features, knowledge, learn, review

# games 1-3 and the lessons learned from them (L001-L009 after migrate_lessons.py), frozen as fixtures
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
LESSONS = knowledge.load_jsonl(os.path.join(FIXTURES, "lessons_migrated.jsonl"))

def source_position(lesson):   # the board (with its move history) where the lesson was created, and Claude's color
    game = chess.pgn.read_game(open(os.path.join(FIXTURES, f"game_{lesson['source']['game']}.pgn"), encoding="utf-8"))
    board = next(b for b in learn.boards(game).values() if b.fen() == lesson["source"]["fen"])
    return board, learn.claude_color(game)

@pytest.mark.parametrize("lesson", LESSONS, ids=[l["id"] for l in LESSONS])
def test_lesson_is_retrieved_at_its_own_source_position(lesson):
    board, me = source_position(lesson)
    picked = features.retrieve(LESSONS, features.tags(board, me), review.phase(board), 5)
    assert lesson["id"] in [l["id"] for l in picked]

@pytest.mark.parametrize("lesson", LESSONS, ids=[l["id"] for l in LESSONS])
def test_migrated_lesson_is_a_valid_pattern(lesson):
    assert knowledge.problems_with(lesson) == []
    assert set(lesson["features"]) <= set(features.TAGS)
    board, me = source_position(lesson)
    assert set(lesson["features"]) <= set(features.tags(board, me))   # every tag is true where the lesson came from

def test_queenside_lessons_lead_in_game_2():   # the pattern that lost game 2: king castled queenside, files open toward it
    lesson = next(l for l in LESSONS if l["id"] == "L004")
    board, me = source_position(lesson)
    top2 = [l["id"] for l in features.retrieve(LESSONS, features.tags(board, me), review.phase(board), 2)]
    assert set(top2) == {"L004", "L006"}
