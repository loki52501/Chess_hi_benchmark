import sys
import knowledge

# one-time: python migrate.py [games folder]
# old-style rules.md -> rules_legacy.md (backup) + new-format rules.md + rules_stats.json + empty lessons.jsonl
folder = sys.argv[1] if len(sys.argv) > 1 else "games"
if knowledge.is_new_format(folder):
    sys.exit(f"{folder}/rules.md is already in the new format - nothing to do")
for rule in knowledge.migrate(folder):
    print(f"[{rule['id']}] {rule['rule']}\n      CHECK: {rule['check']}")
print(f"\nOld rules backed up to {folder}/rules_legacy.md; lessons.jsonl is empty.")
