from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.ingest.pdf_bronze import BronzeChunk, PageBlock, build_chunks, normalize_text


class PdfBronzeTestCase(unittest.TestCase):
    def test_normalize_text(self) -> None:
        self.assertEqual(normalize_text("A \n  B\tC"), "A B C")

    def test_build_chunks_splits_large_sequences(self) -> None:
        blocks = [
            PageBlock(page=1, block_index=0, text="A" * 300, bbox=(0, 0, 1, 1)),
            PageBlock(page=1, block_index=1, text="B" * 300, bbox=(0, 1, 1, 2)),
            PageBlock(page=2, block_index=0, text="C" * 300, bbox=(0, 2, 1, 3)),
            PageBlock(page=2, block_index=1, text="D" * 300, bbox=(0, 3, 1, 4)),
        ]
        chunks = build_chunks(blocks, report_id="demo", target_chars=700, min_chars=200)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(isinstance(item, BronzeChunk) for item in chunks))
        self.assertEqual(chunks[0].page_start, 1)
        self.assertGreaterEqual(chunks[-1].page_end, 2)


if __name__ == "__main__":
    unittest.main()
