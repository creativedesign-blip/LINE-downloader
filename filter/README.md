# OCR Travel Classifier

This folder contains the OCR classifier used by the fixed RPA pipeline.

Current flow:

```text
RPA saves raw images to line-rpa/download/<group-name>/
python tools/pipeline/process_downloads.py --target "<group-name>"
filter/filter.py classifies images into travel/other/error under the same group folder
travel images are branded and indexed into config/travel_index.db
```

`line-rpa/download/<group-name>/inbox/` is still supported for compatibility,
but the standard RPA output folder is `line-rpa/download/<group-name>/`.

Direct classifier usage:

```bash
python filter/filter.py --input-dir <IN> --travel-dir <TRAVEL> --other-dir <OTHER> --error-dir <ERROR>
```

For normal OpenClaw/RPA usage, call the pipeline instead:

```bash
python tools/pipeline/process_downloads.py --target "<group-name>"
```

`travel_keywords.txt` controls strong and weak travel keywords.
