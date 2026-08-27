MangaNana 0.9.8 - Selected Manga and Footer Cleanup

New in 0.9.8:
- Simplified the empty Selected Manga card by removing redundant labels.
- Added a quiet No manga selected empty state.
- Reserved additional DPI-safe footer space for Search Results and Volumes actions.
- Reduced list minimum heights so footer actions remain fully visible on shorter/scaled displays.

Previous 0.9.7 changes:
- DPI-safe volume rows and synchronized discovery-panel heights.
- Dedicated fixed footers keep Search Results and Volumes unobstructed.
- Volume cover fallback: volume cover -> main manga cover -> MangaNana placeholder.
- Animated orange striped download progress bar above the Activity Log.
- Activity Log header remains directly attached to its expandable contents.

Previous 0.9.6 stability features remain included.

Previously in 0.9.6:
- Locks manga, volume, language, layout, metadata, and related controls while a download is active so the visible job cannot drift from the running job.
- Close is disabled during active downloads. Use Cancel to stop safely.
- Cancel now reports that it is finishing the current network/file operation before cleanup, then removes temporary partial files without importing unfinished books.
- Adds transient MangaDex/API and image-download retries with retry messages in the Activity Log.
- Performs a conservative free-temporary-disk-space check before large jobs begin.
- Prevents duplicate starts by disabling Download and Review throughout the active job.
- Strengthens final completion logging with books added/updated, skipped items, final CBZ size, and failure count.
- Successful jobs end with: Everything is complete. You can safely close MangaNana.
- Temporary job files are cleaned even if Calibre import/reporting encounters an exception.

Retained from 0.9.5:
- Standalone Chapters support for MangaDex titles without formal volume numbers.
- Pairing Preview short-sample behavior.
- Activity Log collapse/expand fixes and duplicate-message suppression.
- Adaptive Review size estimation and actual final CBZ size reporting.
- Reserved footer space below Search Results and Volumes lists.

Version: 0.9.8
