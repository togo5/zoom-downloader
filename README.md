# zoom-downloader

A CLI tool to download Zoom cloud recordings from shared URLs using Playwright.

## Features

- Download Zoom recordings from password-protected share URLs
- Automatically captures both screen share and face camera videos
- Extracts sharing timeline (screen share start/stop timestamps) as JSON
- Supports batch processing via CSV file

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)

## Installation

```bash
# Clone the repository
git clone https://github.com/togo5/zoom-downloader.git
cd zoom-downloader

# Install dependencies
uv sync

# Install Playwright browsers
uv run playwright install chromium
```

## Usage

### Single Recording

```bash
uv run src/main.py <base_filename> <share_url> <passcode> [output_dir]
```

**Example:**

```bash
uv run src/main.py meeting_01 "https://us06web.zoom.us/rec/share/xxxxx" "password123"
```

### Batch Processing (CSV)

```bash
uv run src/main.py --csv <csv_file> [output_dir]
```

**CSV Format:**

```csv
base_filename,url,passcode
meeting_01,https://us06web.zoom.us/rec/share/xxxxx,password123
meeting_02,https://us06web.zoom.us/rec/share/yyyyy,password456
```

**Example:**

```bash
uv run src/main.py --csv input/recordings.csv ./downloads
```

## Output

Downloaded files are saved to the `./downloads` directory (or specified output directory):

- `{base_filename}_screen_{resolution}.mp4` - Screen share video
- `{base_filename}_face_{resolution}.mp4` - Face camera video
- `{base_filename}_timeline.json` - Screen sharing timeline (start/stop timestamps)

### Timeline JSON Format

```json
[
  {"action": "Sharing Started", "time": "00:00:46", "seconds": 46},
  {"action": "Sharing Stopped", "time": "00:02:43", "seconds": 163}
]
```

## License

MIT
