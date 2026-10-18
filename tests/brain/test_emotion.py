"""SPCH-02, D-06, D-33: the hidden reply header is parsed, validated and stripped."""

from snow.brain.emotion import HeaderParser, split_header

ALLOWED = ["neutral", "content", "calm", "curious", "sympathetic", "excited"]


def run(*chunks: str) -> tuple[HeaderParser, str]:
    parser = HeaderParser(ALLOWED, "neutral")
    out = "".join(parser.feed(c) for c in chunks) + parser.flush()
    return parser, out


def test_header_split_across_chunks_is_withheld_and_text_is_clean() -> None:
    parser = HeaderParser(ALLOWED, "neutral")
    assert parser.feed("[[cont") == ""
    assert parser.feed("ent]] Of course") == "Of course"
    assert parser.feed(", sir.") == ", sir."
    assert (parser.emotion, parser.big) == ("content", False)


def test_big_moment_flag() -> None:
    parser, out = run("[[excited|big]] Welcome back, sir.")
    assert (parser.emotion, parser.big, out) == (
        "excited",
        True,
        "Welcome back, sir.",
    )


def test_emotion_outside_the_allowed_set_falls_back_but_header_is_still_stripped() -> (
    None
):
    parser, out = run("[[furious]] Fine.")
    assert (parser.emotion, out) == ("neutral", "Fine.")


def test_no_header_keeps_all_text_and_neutral() -> None:
    parser, out = run("Good evening", ", sir.")
    assert (parser.emotion, parser.big, out) == ("neutral", False, "Good evening, sir.")
    assert not parser.found


def test_plain_text_streams_without_buffering() -> None:
    parser = HeaderParser(ALLOWED, "neutral")
    assert parser.feed("Hello") == "Hello"


def test_long_text_without_a_header_is_released_unchanged() -> None:
    text = "[[this is not a header and it just keeps going on and on"
    _, out = run(text[:10], text[10:])
    assert out == text


def test_whitespace_after_the_header_is_dropped_even_across_chunks() -> None:
    _, out = run("[[calm]]", "  ", " Right away.")
    assert out == "Right away."


def test_half_written_header_at_end_of_stream_is_dropped() -> None:
    _, out = run("[[cont")
    assert out == ""


def test_split_header_reports_whether_a_header_was_found() -> None:
    assert split_header("[[curious]] Yes?", ALLOWED, "neutral") == (
        "curious",
        False,
        True,
        "Yes?",
    )
    assert split_header("Here are some options:", ALLOWED, "neutral")[2] is False


def test_a_repeated_header_mid_reply_is_never_shown() -> None:
    _, out = run("[[calm]] I'll keep my tone steady.", "[[content]]Understood, sir.")
    assert out == "I'll keep my tone steady. Understood, sir."


def test_a_mid_reply_tag_split_across_chunks_is_held_then_stripped() -> None:
    parser, out = run("[[calm]] Done.", " [", "[exci", "ted|big]] Next.")
    assert " ".join(out.split()) == "Done. Next."
    assert parser.emotion == "calm"  # only the leading header sets the emotion


def test_brackets_that_are_not_a_tag_are_released() -> None:
    _, out = run("[[calm]] See [[this list]] and [x].", " Bye [")
    assert out == "See [[this list]] and [x]. Bye "
