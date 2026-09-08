# Turns the ratings/strategies data already sitting in Firestore into an
# actual signal: which behavioral strategies tend to show up in replies the
# user rated highly? Run by hand (python rating_correlations.py) whenever
# there's enough real usage data to be worth looking at - it doesn't touch
# anything, it only reads.
#
# Caveat: a reply usually uses several strategies at once, and the rating is
# on the whole reply, not any one strategy. So this is a rough correlational
# signal ("replies using X tend to score well"), not proof that strategy X
# alone caused the good rating.

from collections import defaultdict

from firebase_logger import fetch_rated_sessions, init_firebase


def compute_strategy_averages(sessions):
    """Group ratings by strategy title and average them.

    "sessions" is a list of Firestore session dicts, each with a "rating"
    (a number) and a "strategies" list (the strategy titles used in that
    reply). Returns a dict like {"Validate Before Redirecting": (4.2, 15)}
    - average rating and how many rated sessions that strategy appeared in.
    """
    # defaultdict(list) works just like a normal dict, except looking up a
    # key that doesn't exist yet gives you an empty list instead of an
    # error - handy here since we don't know in advance which strategy
    # titles will show up.
    ratings_by_strategy = defaultdict(list)
    for session in sessions:
        rating = session.get("rating")
        for strategy_title in session.get("strategies", []):
            ratings_by_strategy[strategy_title].append(rating)

    return {
        title: (sum(ratings) / len(ratings), len(ratings))
        for title, ratings in ratings_by_strategy.items()
    }


def print_summary(strategy_averages):
    if not strategy_averages:
        print("No rated sessions found yet - nothing to analyze.")
        return

    # ljust(40) pads short titles out to 40 characters, but doesn't truncate
    # longer ones - so a title over 40 characters would otherwise run
    # straight into the numbers with no gap. Using explicit " | " separators
    # instead means every row stays readable regardless of title length.
    print(f"{'strategy'.ljust(40)} | avg rating | sample count")
    # Sort by average rating first (best strategies at the top), then by
    # how many times it was used, so a 5.0-from-one-use doesn't outrank a
    # 4.5-from-thirty-uses at a glance.
    rows = sorted(strategy_averages.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
    for title, (avg, count) in rows:
        print(f"{title.ljust(40)} | {avg:.2f}".ljust(56) + f" | {count}")


def main():
    db = init_firebase()
    if not db:
        print("Firebase isn't configured (no firebase_key.json or st.secrets) - nothing to read.")
        return

    sessions = fetch_rated_sessions(db)
    # A handful of older logged records have a non-numeric "rating" (a
    # session ID string, an empty list) - almost certainly from a bug in an
    # earlier version of the logging code, not anything from today. Rather
    # than crash on them or silently drop them, count and report how many
    # get excluded so that's visible instead of hidden.
    numeric_sessions = [s for s in sessions if isinstance(s.get("rating"), (int, float))]
    skipped = len(sessions) - len(numeric_sessions)
    print(f"Found {len(sessions)} rated session(s) in Firestore.")
    if skipped:
        print(f"Skipped {skipped} with a non-numeric rating (likely corrupted old records).")
    print()

    strategy_averages = compute_strategy_averages(numeric_sessions)
    print_summary(strategy_averages)


if __name__ == "__main__":
    main()
