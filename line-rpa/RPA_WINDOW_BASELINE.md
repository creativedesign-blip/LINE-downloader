# RPA LINE Window Baseline

This file records the LINE window geometry confirmed by manual navigation testing.

## Confirmed Visible Window

This is the LINE window position and size as seen on the desktop:

```text
x = 0
y = 53
width = 1024
height = 507
```

Confirmed flow:

- Search group: OK
- Open first search result: OK
- Open photos/videos menu: OK
- Groups tested from `line.XLSX`:
  - `凱旋旅行社/巨匠旅遊`
  - `可樂同業公佈欄`

## Config Coordinate System

`line_image_downloader.py` sets DPI awareness before moving and clicking windows.
Because of Windows display scaling, the matching `line-rpa/config.json` value is:

```json
"line_window": {
  "x": 0,
  "y": 80,
  "width": 1536,
  "height": 760
}
```

Do not replace this with the visible desktop size unless the RPA code is changed to run without DPI awareness.

## Photos/Videos And Image Viewer Window

The photos/videos window and the image viewer/download window must also be fixed.

Visible desktop size:

```text
x = 0
y = 0
width = 602
height = 762
```

Matching DPI-aware config values:

```json
"media_window": {
  "x": 0,
  "y": 0,
  "width": 903,
  "height": 1143
},
"viewer_window": {
  "x": 0,
  "y": 0,
  "width": 1008,
  "height": 1143
}
```

RPA now reapplies these values after opening the photos/videos page and after opening the image viewer.

The `viewer_window` value below is the confirmed successful "Save As" baseline.
Do not change it unless a new successful download test is performed.

```text
viewer_window DPI-aware:
x = 0
y = 0
width = 1008
height = 1143

viewer_window visible desktop approximation:
x = 0
y = 0
width = 672
height = 762
```

The image viewer download button is on the top toolbar:

```json
"viewer_download_button": [0.9206, 0.07],
"download_button": [0.9206, 0.07]
```

## Official Runtime Files

The external web trigger uses only:

```text
line-rpa/config.json
line-rpa/line.XLSX
```

Old test configs and spreadsheets were removed to avoid accidental reuse.
