import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import match

@pytest.fixture(autouse=True)
def lessons_mode(monkeypatch):   # the older tests are about "lessons" mode; principles tests switch the mode themselves
    monkeypatch.setattr(match, "LEARN_MODE", "lessons")
