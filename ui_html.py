# Builds the small pieces of HTML the app shows for each reply. Kept apart
# from app.py so the tests can check it directly - importing app.py would
# start the whole Streamlit app.
#
# The most important job here is safety: everything shown comes from the
# visitor or from the model (whose output is shaped by what the visitor
# typed), so all of it is escaped before going into the page. Without that,
# someone could paste HTML or a <script> into the comment box and have it
# run in the browser.

import html


def reply_card_html(label, entry, show_context=True, show_draft=True):
    """Build the HTML for one version's card.

    "entry" is one item from st.session_state.history. The card shows, in
    order: a heading, a short line saying why this version exists (e.g.
    "Revised from version 1 using your feedback"), the user's own draft if
    they gave one, the reply, and the explanation in a tinted box.

    Everything shown here comes from the visitor or from the model (whose
    output is shaped by what the visitor typed), so none of it is fully
    trusted. html.escape(...) turns characters like < and > into harmless
    text (&lt;, &gt;), so they can never be read as real HTML tags or
    scripts once inserted into the page.
    """
    parts = [f"<div class='reply-card'><h4>{html.escape(label)}</h4>"]
    # .get() returns None instead of raising an error when a key is missing,
    # which keeps this working for history entries made before these
    # fields existed.
    if show_context and entry.get("context"):
        parts.append(f"<div class='context'>{html.escape(entry['context'])}</div>")
    if show_draft and entry.get("draft"):
        parts.append(
            f"<div class='draft'><span>Your draft</span>{html.escape(entry['draft'])}</div>"
        )
    parts.append(f"<p>{html.escape(entry['reply'])}</p>")
    if entry.get("what_changed"):
        parts.append(
            f"<div class='explain changed'><strong>"
            f"{html.escape(entry.get('what_changed_label', 'What changed'))}:</strong> "
            f"{html.escape(entry['what_changed'])}</div>"
        )
    # A clarifying question has no technique to explain.
    if not entry.get("is_clarification"):
        parts.append(
            f"<div class='explain'><strong>Why this works:</strong> "
            f"{html.escape(entry['explanation'])}</div>"
        )
    # Street outreach mode only: how to say the reply face to face.
    if entry.get("delivery_tip"):
        parts.append(
            f"<div class='explain tip'><strong>Delivery tip:</strong> "
            f"{html.escape(entry['delivery_tip'])}</div>"
        )
    parts.append("</div>")
    return "".join(parts)
