import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT/'deploy/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DeployTests(unittest.TestCase):
    def test_normal_exit_is_not_configured_to_restart(self):
        text = installer.render_service('robot', 'robot', 8080)
        self.assertIn('Restart=on-failure', text)
        self.assertNotIn('Restart=always', text)
        self.assertIn('User=robot', text)
        self.assertIn('SupplementaryGroups=dialout', text)
        self.assertIn('--port 8080', text)
        self.assertIn('KillSignal=SIGTERM', text)
        self.assertNotIn('@', text)

    def test_backup_is_code_complete_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'srobot'
            target.mkdir()
            (target/'original.py').write_text('original source', encoding='utf-8')
            (target/'.git').mkdir()
            (target/'.git/secret').write_text('excluded', encoding='utf-8')
            backup = installer.backup_existing(target)
            self.assertRegex(backup.name, r'^D\d{8}\.zip$')
            with ZipFile(backup) as archive:
                self.assertEqual(archive.namelist(), ['srobot/original.py'])
            with self.assertRaises(FileExistsError):
                installer.backup_existing(target)


if __name__ == '__main__':
    unittest.main()
