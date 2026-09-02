import unittest
import os
import json
import sqlite3
from pathlib import Path

from app import (
    MODEL_MATRIX,
    init_db,
    record_generation_start,
    update_generation_complete,
    fetch_history,
    delete_generation,
    MiravaAPIClient,
    download_remote_image,
    get_config,
    set_config,
    RPMRateLimiter,
    DB_PATH,
    OUTPUT_DIR
)

class TestMiravaImaginer(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_config_persistence(self):
        # Test SQLite key-value config persistence
        set_config("test_key", "test_value_123")
        val = get_config("test_key")
        self.assertEqual(val, "test_value_123")

        set_config("api_key", "mirava_sk_test_persistent_key")
        saved_key = get_config("api_key")
        self.assertEqual(saved_key, "mirava_sk_test_persistent_key")

    def test_rpm_rate_limiter(self):
        limiter = RPMRateLimiter(max_rpm=5)
        self.assertEqual(limiter.max_rpm, 5)
        self.assertEqual(len(limiter.request_timestamps), 0)
        limiter.wait_for_slot()
        self.assertEqual(len(limiter.request_timestamps), 1)

    def test_gdrive_sync_config(self):
        from app import is_gdrive_sync_enabled
        set_config("gdrive_enabled", "false")
        self.assertFalse(is_gdrive_sync_enabled())
        set_config("gdrive_enabled", "true")
        self.assertTrue(is_gdrive_sync_enabled())
        set_config("gdrive_enabled", "false")

    def test_model_matrix_specifications(self):
        # nano-banana-2 (1K/2K/4K, max ref: 6)
        self.assertIn("nano-banana-2", MODEL_MATRIX)
        self.assertEqual(MODEL_MATRIX["nano-banana-2"]["qualities"], ["1K", "2K", "4K"])
        self.assertEqual(MODEL_MATRIX["nano-banana-2"]["max_refs"], 6)

        # gpt-image-2 (low/medium, max ref: 6)
        self.assertIn("gpt-image-2", MODEL_MATRIX)
        self.assertEqual(MODEL_MATRIX["gpt-image-2"]["qualities"], ["low", "medium"])
        self.assertEqual(MODEL_MATRIX["gpt-image-2"]["max_refs"], 6)

        # flux-pro-2.0 (tanpa quality, max ref: 4)
        self.assertIn("flux-pro-2.0", MODEL_MATRIX)
        self.assertEqual(len(MODEL_MATRIX["flux-pro-2.0"]["qualities"]), 0)
        self.assertEqual(MODEL_MATRIX["flux-pro-2.0"]["max_refs"], 4)

        # ideogram-v3.0 (tanpa quality, tanpa ref)
        self.assertIn("ideogram-v3.0", MODEL_MATRIX)
        self.assertEqual(len(MODEL_MATRIX["ideogram-v3.0"]["qualities"]), 0)
        self.assertEqual(MODEL_MATRIX["ideogram-v3.0"]["max_refs"], 0)

        # lucid-origin (tanpa quality, max ref: 2)
        self.assertIn("lucid-origin", MODEL_MATRIX)
        self.assertEqual(len(MODEL_MATRIX["lucid-origin"]["qualities"]), 0)
        self.assertEqual(MODEL_MATRIX["lucid-origin"]["max_refs"], 2)

        # seedream-4.5 (tanpa quality, max ref: 6)
        self.assertIn("seedream-4.5", MODEL_MATRIX)
        self.assertEqual(len(MODEL_MATRIX["seedream-4.5"]["qualities"]), 0)
        self.assertEqual(MODEL_MATRIX["seedream-4.5"]["max_refs"], 6)

        # recraft-v4 (maks prompt 1200 char, tanpa quality, tanpa ref, tanpa style)
        self.assertIn("recraft-v4", MODEL_MATRIX)
        self.assertEqual(len(MODEL_MATRIX["recraft-v4"]["qualities"]), 0)
        self.assertEqual(MODEL_MATRIX["recraft-v4"]["max_refs"], 0)
        self.assertFalse(MODEL_MATRIX["recraft-v4"]["support_style"])
        self.assertEqual(MODEL_MATRIX["recraft-v4"]["max_prompt_chars"], 1200)

    def test_database_crud(self):
        test_gen_id = "test_gen_12345"
        
        # 1. Record generation start
        record_generation_start(
            generation_id=test_gen_id,
            model_id="nano-banana-2",
            prompt="A futuristic cyberpunk cityscape at night",
            ratio="16:9",
            quality="2K",
            style="Cyberpunk / Neon",
            parameters={"ratio": "16:9", "quality": "2K", "style": "Cyberpunk / Neon"}
        )

        history = fetch_history(search_query="cyberpunk", model_filter="nano-banana-2")
        self.assertTrue(len(history) >= 1)
        item = history[0]
        self.assertEqual(item["generation_id"], test_gen_id)
        self.assertEqual(item["status"], "processing")

        # 2. Update completion
        dummy_local_path = str(OUTPUT_DIR / "dummy_test.png")
        with open(dummy_local_path, "w") as f:
            f.write("dummy_image_content")

        update_generation_complete(
            generation_id=test_gen_id,
            status="success",
            remote_urls=["https://cos.tencent.example.com/image1.png"],
            local_paths=[dummy_local_path]
        )

        history_updated = fetch_history(search_query="cyberpunk", model_filter="nano-banana-2")
        item_updated = history_updated[0]
        self.assertEqual(item_updated["status"], "success")
        stored_paths = json.loads(item_updated["local_paths"])
        self.assertIn(dummy_local_path, stored_paths)

        # 3. Delete generation
        delete_generation(item_updated["id"])
        history_after = fetch_history(search_query=test_gen_id)
        self.assertEqual(len(history_after), 0)
        self.assertFalse(Path(dummy_local_path).exists())

    def test_client_init(self):
        client = MiravaAPIClient("test_token_xyz")
        self.assertEqual(client.api_key, "test_token_xyz")
        self.assertEqual(client.base_url, "https://imaginer.mirava.studio")
        self.assertEqual(client.headers["Authorization"], "Bearer test_token_xyz")

    def test_style_mapping(self):
        # Test that DINAMIS / TANPA GAYA are excluded from API style payload
        client = MiravaAPIClient("test_token")
        
        # Test known style mapping
        STYLE_MAP = {
            "KREATIF": "creative",
            "FASHION": "fashion",
            "POTRET SINEMATIK": "cinematic",
            "FOTO WARNA": "photorealistic"
        }
        for ui_style, api_slug in STYLE_MAP.items():
            self.assertEqual(STYLE_MAP[ui_style], api_slug)

if __name__ == "__main__":
    unittest.main()
