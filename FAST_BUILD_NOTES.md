# Fast build changes

This package is optimized for faster Render startup and resume screening.

- Image/JPG/PNG resume uploads and OCR have been removed.
- Tesseract and pytesseract have been removed from the Docker image and Python dependencies.
- Resume screening accepts text-based PDF and DOCX files only.
- Non-resume files are evaluated once by the local heuristic and excluded immediately; no second AI verification request is made.
- Files with the same hash that were already screened for the selected job in the current session are skipped automatically and are not sent to the AI provider again.
- Screening concurrency is limited to five workers to reduce provider throttling and retry delays.

Text-based PDFs and DOCX files are required for the fastest path. Scanned/image-only PDFs are not supported in this build.
