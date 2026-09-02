# High Priestess control migration audit

This audit maps the Magician UI before its widgets are reorganized. It is a
recovery aid for the active `feature/high-priestess` refactor.

| Existing control/behavior | High Priestess destination |
| --- | --- |
| Search field, Search button, Enter-to-search | Choose Manga — discovery |
| Volumes / Chapters mode | Choose Manga — discovery |
| Direct Link and Load | Choose Manga — discovery |
| Prefer Colored | Choose Manga — discovery; local ranking only |
| Download Language | Choose Manga — discovery/inventory context |
| Search Results and Show More | Choose Manga — left page |
| Source availability/status | Choose Manga — source-status pills |
| Selected title, author, edition, alternate titles | Choose Manga — upper right |
| Volume/chapter inventory and Select All/Clear | Choose Manga — lower right |
| Volume Range | Intentional removal |
| Portrait / Landscape and Reading Direction | Book Customization — Reading & Layout |
| Pairing Preview | Book Customization — optional inline Portrait/Landscape Live eReader Preview |
| Chapter Output and Manual Grouping | Finalization — Book Creation (Chapter mode only) |
| Zero Padding | Finalization — Naming when applicable |
| Source cover behavior | Finalization — Cover/Metadata |
| Alternate Title | Finalization — bulk Metadata |
| Title / Series / Author | Finalization — bulk Metadata |
| ComicInfo and Calibre metadata behavior | Finalization — unchanged pipeline |
| Calibre destination | Finalization — compact Destination summary |
| Review table and round Use controls | Finalization — Final Outputs |
| Final Output row selection/focus | Finalization — independent of Use inclusion |
| Review action | Replaced by Next: Finalization transition |
| Download & Add to Calibre | Finalization — primary footer action |
| Activity Log, Copy Log, Save Log | Persistent compact/expandable status area |
| Search progress and work progress | Collapsed when idle; shown only for active stage-owned work |
| Preferences, Manga Sources, About | Persistent footer actions |
| Idle Cancel/Close | Intentional removal; OS close remains |
| Active search/preview/download cancellation | Contextual operation cancellation only |
| Provider fallback | Pipeline behavior retained; Activity Log and selected source stay truthful |
| Source manager enable/disable | Footer dialog; local result filtering and notice |
| Explanatory hover-description/tooltips | Intentional removal; use stage-local inline status |
| Warnings/status/help text | Inline stage-local status surfaces and Activity Log |
| Search default-button behavior | Search button/Enter only; mode buttons never default |

No existing content/output pipeline behavior is intentionally removed by the
layout migration. The three stage bodies are owned by one stacked container, so
upstream invalidation cannot make downstream panes visible.
