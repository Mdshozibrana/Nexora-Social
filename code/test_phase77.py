"""Phase-77 tests: back stays inside the app (owner: "বটে
ব্যাক করলে বের হয়ে আসে কেনো?" — pressing back in the bot
throws me out).

Why it happened: Telegram routes the Android back button to a
Mini App only while the app shows Telegram's BackButton; the
app never showed it and kept no navigation history, so back
closed the Mini App from every screen. Now showView records a
view history (capped, de-duplicated, not fed by back steps
themselves), the BackButton is visible whenever there is
somewhere to go back to, and a back press closes whatever is
open first — design popup, sheets, the design sheet, the
sidebar — then walks the history. On the home screen (Feed,
nothing open, empty history) the button hides and back
leaves the app, as Telegram intends.
"""
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()

# --- the machinery ----------------------------------------------
for bit in ("let viewStack = [];", 'let currentView = "feed";',
            "function updateBackButton()", "function onAppBack()",
            "tg.BackButton.onClick(onAppBack)",
            "tg.BackButton.show()", "tg.BackButton.hide()",
            "function anyOverlayOpen()"):
    assert bit in JS, bit
print("back machinery OK")

# --- showView feeds (but is not fed by) the history --------------
seg = JS[JS.index("function showView(name, viaBack)"):
         JS.index("// ---------- Phase 77")]
assert "if (!viaBack && name !== currentView)" in seg
assert "viewStack.push(currentView)" in seg
assert "currentView = name;" in seg
assert "updateBackButton();" in seg
print("history OK")

# --- a back press closes open layers before navigating -----------
seg = JS[JS.index("function onAppBack()"):JS.index("if (tg.BackButton)")]
for bit in ("hideDesignPop()", "closeReelMenu()",
            "closeDesignSheet()", "closeSidebar()",
            "showView(viewStack.pop(), true)",
            'showView("feed", true)'):
    assert bit in seg, bit
print("back order OK")

# --- overlays refresh the button's visibility ---------------------
assert JS.count("updateBackButton();") >= 10
print("visibility hooks OK")

assert "app.js?v=109" in HTML and "style.css?v=109" in HTML
print("PHASE 77 OK")
