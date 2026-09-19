from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from server.director_workbench import (
    Asset,
    AssetKind,
    AssetPolicy,
    Episode,
    ProjectSettings,
    build_episode_package,
)


class ExportingTests(unittest.TestCase):
    def test_package_contains_documents_and_asset_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            source = data_root / "projects" / "episode-1" / "assets" / "portrait.png"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"png")
            episode = Episode(
                id="episode-1",
                title="雾城来信",
                settings=ProjectSettings(target_duration_seconds=240),
                assets={
                    "char-1": Asset(
                        id="char-1",
                        name="林雾",
                        kind=AssetKind.CHARACTER,
                        policy=AssetPolicy.LOCKED,
                        confirmed=True,
                        description="黑色短发，灰色风衣",
                        source_path="projects/episode-1/assets/portrait.png",
                        mime_type="image/png",
                    )
                },
            )

            package = build_episode_package(episode, data_root=data_root)

            with zipfile.ZipFile(io.BytesIO(package)) as archive:
                names = set(archive.namelist())
                self.assertIn("项目数据.json", names)
                self.assertIn("导演执行包.md", names)
                self.assertIn("分镜表.csv", names)
                self.assertIn("资产引用.csv", names)
                self.assertIn("资产/portrait.png", names)
                markdown = archive.read("导演执行包.md").decode("utf-8")
                self.assertIn("雾城来信", markdown)
                self.assertIn("黑色短发", markdown)


if __name__ == "__main__":
    unittest.main()
