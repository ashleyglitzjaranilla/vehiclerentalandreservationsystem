"""The rules the booking engine rests on, as pure functions.

Nothing here imports Flask, a database session or a model class. Every module
takes plain values and returns plain values, so the rules can be tested
exhaustively without fixtures and live in exactly one place -- which is what
lets the same function validate on the frontend and on the backend without two
implementations drifting apart.
"""
