"""Authoritative MangaNana release identity.

Future milestones should update the constants in this file only. The eventual
1.0 codename is reserved as ``The World``; patch codenames may later use explicit
Roman-numeral suffixes when chosen by the project.
"""

SEMANTIC_VERSION = '0.11.0-dev'
CALIBRE_VERSION = (0, 11, 0)
CODENAME = 'The High Priestess'
FUTURE_1_0_CODENAME = 'The World'

DISPLAY_VERSION = f'MangaNana {SEMANTIC_VERSION} — {CODENAME}'
SHORT_VERSION_LABEL = f'v{SEMANTIC_VERSION} — {CODENAME}'
USER_AGENT = f'MangaNana-Calibre/{SEMANTIC_VERSION}'
