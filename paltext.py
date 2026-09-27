"""Small wording helpers shared by the app and the command line."""


def plural(n, one, many=None):
    """'1 mod', '3 mods', '1 change', '2 changes' -- never 'mod(s)'."""
    return f"{n} {one if n == 1 else (many or one + 's')}"
