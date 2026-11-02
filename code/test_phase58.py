"""Phase-58 tests: a 6th monetization criterion (owner: add
one more criteria to Creator Earnings — 12 referrals). Only
QUALIFIED referrals count (qualified = the referred member
has posted, the same rule that pays referral points).
Behaviour is covered by test_phase6 (locked-state required
values + the unlock scenario grants Carol 12 qualified
referrals); these are the wiring pins."""
CFG = open("app/config.py").read()
MAIN = open("app/main.py").read()
JS = open("webapp/app.js").read()

assert '"referrals": 12' in CFG
assert '"key": "referrals", "label": "Referrals"' in MAIN
assert "referrer_id=user.telegram_id, qualified=True" in MAIN
assert '["Referral", "🔗"]' in JS
print("referral gate wiring OK")

print("PHASE-58 TESTS PASSED")
