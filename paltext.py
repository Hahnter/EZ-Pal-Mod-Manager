"""Small wording helpers shared by the app and the command line."""


def plural(n, one, many=None):
    """'1 mod', '3 mods', '1 change', '2 changes' -- never 'mod(s)'."""
    return f"{n} {one if n == 1 else (many or one + 's')}"


def and_list(words):
    """'A', 'A and B', 'A, B and C'."""
    words = list(words)
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]
