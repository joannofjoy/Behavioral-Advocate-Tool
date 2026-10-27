# Tests for conversations.py: when a reply starts a new conversation, and how
# the history is split for display.

from conversations import split_history, thread_for_new_entry, version_number


def entry(thread, comment="plants feel pain"):
    return {"thread": thread, "comment": comment, "reply": "..."}


def test_first_reply_starts_thread_one():
    assert thread_for_new_entry([], "plants feel pain", revising=False) == 1


def test_revising_or_same_comment_stays_in_the_conversation():
    history = [entry(1)]
    assert thread_for_new_entry(history, "plants feel pain", revising=True) == 1
    assert thread_for_new_entry(history, "  plants feel pain ", revising=False) == 1


def test_new_comment_starts_a_new_conversation():
    history = [entry(1)]
    assert thread_for_new_entry(history, "vegans are weak", revising=False) == 2


def test_split_puts_current_conversation_first_and_earlier_ones_newest_first():
    a1, a2 = entry(1, "a"), entry(1, "a")
    b1 = entry(2, "b")
    c1, c2 = entry(3, "c"), entry(3, "c")
    current, earlier = split_history([a1, a2, b1, c1, c2])
    assert current == [c1, c2]
    assert earlier == [[b1], [a1, a2]]


def test_version_numbers_restart_in_each_conversation():
    a1, b1, b2 = entry(1, "a"), entry(2, "b"), entry(2, "b")
    history = [a1, b1, b2]
    assert version_number(history, a1) == 1
    assert version_number(history, b2) == 2


def test_entries_saved_before_threads_existed_count_as_one_conversation():
    old = [{"comment": "x"}, {"comment": "x"}]
    current, earlier = split_history(old)
    assert current == old and earlier == []
