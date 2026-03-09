import unittest
import os
import shutil
from pathlib import Path
from pl_analyst.data_analyst_agent.utils.output_manager import OutputManager

class TestOutputManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary output directory for testing
        self.test_root = Path("test_outputs").resolve()
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir()

    def tearDown(self):
        # Clean up the temporary output directory
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_run_dir_generation(self):
        dataset = "ops_metrics"
        dimension = "lob"
        dimension_value = "Line Haul"
        run_id = "test_run_123"
        
        om = OutputManager(
            dataset=dataset,
            dimension=dimension,
            dimension_value=dimension_value,
            run_id=run_id,
            root_dir=str(self.test_root)
        )
        
        expected_path = self.test_root / dataset / dimension / "Line_Haul" / run_id
        self.assertEqual(om.run_dir, expected_path)

    def test_create_run_directory(self):
        om = OutputManager(
            dataset="ds",
            dimension="dim",
            dimension_value="val",
            run_id="run_id",
            root_dir=str(self.test_root)
        )
        
        run_dir = om.create_run_directory()
        self.assertTrue(run_dir.exists())
        self.assertTrue((run_dir / "logs").exists())

    def test_save_run_metadata(self):
        om = OutputManager(
            dataset="ds",
            dimension="dim",
            dimension_value="val",
            run_id="run_id",
            root_dir=str(self.test_root)
        )
        
        cli_args = {"dataset": "ds", "metrics": "m1,m2"}
        metadata_path = om.save_run_metadata(cli_args)
        
        self.assertTrue(metadata_path.exists())
        with open(metadata_path, "r", encoding="utf-8") as f:
            import json
            metadata = json.load(f)
            self.assertEqual(metadata["run_id"], "run_id")
            self.assertEqual(metadata["cli_arguments"], cli_args)

    def test_get_file_path(self):
        om = OutputManager(
            dataset="ds",
            dimension="dim",
            dimension_value="val",
            run_id="run_id",
            root_dir=str(self.test_root)
        )
        
        file_path = om.get_file_path("results.json")
        expected_path = self.test_root / "ds" / "dim" / "val" / "run_id" / "results.json"
        self.assertEqual(file_path, expected_path)

if __name__ == "__main__":
    unittest.main()
