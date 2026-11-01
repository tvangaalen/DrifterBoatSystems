# Mastervolt Web App v1.0.6

- Fixed the AC-limit field losing focus immediately on desktop and iPhone.
- The one-second live refresh no longer replaces the Shore Power input DOM node while that field is focused, keeping the iOS numeric keyboard open and allowing uninterrupted entry.
- Live state collection continues during editing; normal Sources rendering resumes after the field loses focus.
- Updated application/footer version and PWA cache to v1.0.6.

AC-limit validation remains restricted to whole numbers from 1 through 16. All verified device mappings, mode sequences and Engine ECU safety behavior remain unchanged.
