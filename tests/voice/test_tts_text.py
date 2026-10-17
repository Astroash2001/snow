"""What is spoken (SPCH-03, T-01-43) and how a reply is chunked (SPCH-04)."""

from snow.voice.tts.text import SentenceChunker, sanitize


def test_sanitize_drops_markup_code_links_and_emoji() -> None:
    raw = (
        "## Done\n**Bold** and *soft* and `x = 1`.\n"
        "```python\nprint('hi')\n```\n"
        "See https://example.com/a?b=1 or [the docs](https://docs.example.com) "
        "now \U0001f600\n"
        "- first\n1. second"
    )
    assert sanitize(raw) == "Done Bold and soft and . See or the docs now first second"


def test_sanitize_leaves_plain_text_alone() -> None:
    assert (
        sanitize("It costs 3.5 dollars, Dr. Smith.")
        == "It costs 3.5 dollars, Dr. Smith."
    )


def test_sanitize_keeps_snake_case_words() -> None:
    assert (
        sanitize("rename my_var_name to other_name")
        == "rename my_var_name to other_name"
    )


def test_first_chunk_ends_at_the_first_clause_with_three_words() -> None:
    c = SentenceChunker()
    assert c.feed("Well, I think so, yes. ") == ["Well, I think so,", "yes."]
    assert c.feed("Next, one more thing. ") == [
        "Next, one more thing."
    ]  # first is over


def test_a_short_first_clause_waits_for_the_sentence_end() -> None:
    c = SentenceChunker()
    assert c.feed("Sure, go on. Then more") == ["Sure, go on."]
    assert c.flush() == ["Then more"]


def test_decimals_and_abbreviations_do_not_split() -> None:
    c = SentenceChunker()
    out = c.feed("Dr. Smith pays 3.5 dollars, e.g. a lot. Done! ")
    assert out == ["Dr. Smith pays 3.5 dollars,", "e.g. a lot.", "Done!"]


def test_a_boundary_needs_the_next_character() -> None:
    c = SentenceChunker()
    assert c.feed("One two three four.") == []  # could be "4.5": wait
    assert c.feed(" Five") == ["One two three four."]
    assert c.flush() == ["Five"]


def test_a_code_fence_split_across_deltas_is_never_spoken() -> None:
    c = SentenceChunker()
    out = c.feed("Try this. `")
    out += c.feed("``py\nsecret()")
    out += c.feed("\n``")
    out += c.feed("` and it works. ")
    out += c.flush()
    assert out == ["Try this.", "and it works."]


def test_flush_resets_for_the_next_reply() -> None:
    c = SentenceChunker()
    c.feed("```open fence")
    c.flush()
    assert c.feed("Hello there you, friend. ") == ["Hello there you,", "friend."]


def test_punctuation_alone_is_not_a_chunk() -> None:
    assert SentenceChunker().feed("... ?! ") == []
