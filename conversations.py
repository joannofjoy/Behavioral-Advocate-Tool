# Groups the replies made in one browser session into conversations, so the
# page can tell "a revision of this reply" apart from "an earlier, different
# comment".
#
# Every reply is stored in one list (st.session_state.history), and each
# entry carries a "thread" number. A new conversation (a new thread) starts
# when the user asks for a reply to a different comment; revising a reply,
# regenerating the same comment, or only editing their own draft all stay in
# the same conversation. Without this, switching topics made the new reply
# look like "version 2" of the old one.


def thread_for_new_entry(history, comment, revising):
    """The thread number the next reply belongs to.

    Starts at 1 for the first reply. Stays the same when revising or when
    the comment hasn't changed; goes up by one when the comment is new.
    .get() with a default covers entries saved before threads existed.
    """
    if not history:
        return 1
    last = history[-1]
    last_thread = last.get("thread", 1)
    if revising or last.get("comment", "").strip() == comment.strip():
        return last_thread
    return last_thread + 1


def split_history(history):
    """Split the history into the current conversation and earlier ones.

    Returns (current, earlier): "current" is the list of entries in the
    latest conversation, oldest first; "earlier" is a list of the previous
    conversations, each a list of entries oldest first, with the most recent
    conversation first.
    """
    if not history:
        return [], []
    current_thread = history[-1].get("thread", 1)
    current = [h for h in history if h.get("thread", 1) == current_thread]
    # A dict keeps the order things were added in, so the conversations come
    # out in the order they happened.
    earlier = {}
    for h in history:
        thread = h.get("thread", 1)
        if thread != current_thread:
            earlier.setdefault(thread, []).append(h)
    return current, list(reversed(list(earlier.values())))


def version_number(history, entry):
    """Which version of its conversation an entry is: 1 for the first reply
    to a comment, 2 for the first revision, and so on."""
    thread = entry.get("thread", 1)
    same_thread = [h for h in history if h.get("thread", 1) == thread]
    # "is" checks for the very same entry, not just an equal one, so two
    # identical replies still get different version numbers.
    return next(i for i, h in enumerate(same_thread) if h is entry) + 1
