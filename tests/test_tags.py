from src.normalize.tags import dedupe_tags, slug_tag


def test_slug_and_dedupe():
    assert slug_tag("A Coruña") == "a-coruna"
    assert slug_tag("Electrónica") == "electronica"
    assert dedupe_tags(["Rock", "rock", "Indie", ""]) == ["rock", "indie"]
