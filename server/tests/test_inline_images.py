"""Welche Anhaenge Claude direkt sieht und welche beim Read-Werkzeug bleiben.

Hintergrund: Ueber das Werkzeug hing es am Modell, ob es ein Bild oeffnet. In
einem langen Chat behauptete Claude trotz Foto, das Lesen von Dateien sei
deaktiviert. Bilder gehen deshalb direkt in die Nachricht.
"""
import tempfile
from pathlib import Path
from unittest import TestCase

from pocket_claude.attachments import (
    MAX_INLINE_IMAGE_BYTES,
    build_prompt_text,
    has_binary_attachments,
    inline_images,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"\x00" * 64


class InlineImageTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _att(self, aid, filename, mime, data):
        path = Path(self.tmp.name) / filename
        path.write_bytes(data)
        return {"id": aid, "filename": filename, "mime_type": mime,
                "path": str(path), "size_bytes": len(data)}

    def test_routing(self):
        cases = [
            # (Dateiname, gemeldeter Mimetyp, Inhalt, direkt an Claude?)
            ("foto.png", "image/png", PNG, True),
            ("foto.jpg", "image/jpeg", JPEG, True),
            ("falsch.png", "image/png", HEIC, False),   # Format zaehlt, nicht der Mimetyp
            ("brief.pdf", "application/pdf", PDF, False),
            ("riesig.jpg", "image/jpeg", JPEG + b"\x00" * MAX_INLINE_IMAGE_BYTES, False),
        ]
        for filename, mime, data, inline in cases:
            with self.subTest(filename):
                a = self._att("a1", filename, mime, data)
                by_id = {"a1": a}
                blocks, ids = inline_images(["a1"], by_id)
                prompt = build_prompt_text(
                    {"content": "Was ist das?", "attachment_ids": ["a1"]}, by_id, ids)
                needs_read = has_binary_attachments(["a1"], by_id, ids)
                self.assertEqual(bool(blocks), inline)
                self.assertEqual(needs_read, not inline)
                self.assertEqual("Read" in prompt, not inline)
                self.assertIn(filename, prompt)

    def test_text_attachment_stays_inline_text(self):
        a = self._att("t1", "notiz.txt", "text/plain", b"Hallo Welt")
        by_id = {"t1": a}
        blocks, ids = inline_images(["t1"], by_id)
        self.assertEqual(blocks, [])
        self.assertIn("Hallo Welt", build_prompt_text(
            {"content": "", "attachment_ids": ["t1"]}, by_id, ids))
