from pathlib import Path
import sys

PROJECT = Path(r"C:\Users\user\Desktop\LINE-downloader-main")
sys.path.insert(0, str(PROJECT))

from tools.pipeline.process_downloads import main

raise SystemExit(main([
    "--target", "凱旋旅行社_巨匠旅遊",
    "--json",
]))
