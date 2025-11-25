# GuardianGamer Video Stories Scraper

This tool scrapes video stories/reels from multiple GuardianGamer deployment stages across AWS regions.

## Overview

GuardianGamer has multiple stages deployed across AWS regions:
- **Current stages** (us-east-1): `dev`, `test`
- **Old stages** (us-west-2): `dev-old`, `test-old`, `prod-old`

This scraper collects all video stories (items with `SK` starting with `V#`) from the DynamoDB Events tables and generates browsable reports.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure you have AWS credentials configured with access to:
   - DynamoDB tables in us-east-1 and us-west-2
   - S3 buckets (for video URLs)

## Configuration

The `resources.json` file contains the mapping of stages to their AWS resources:

```json
{
  "stages": {
    "dev": {
      "region": "us-east-1",
      "dynamodb_table": "GGEventsTable-147552928523-dev",
      "s3_bucket": "ggbucket-sam-147552928523-dev"
    },
    ...
  }
}
```

## Usage

### Scrape all stages (default):
```bash
python3 scrape_video_stories.py
```

This will:
- Scan all stages defined in `resources.json`
- Generate `all_video_stories.json` with all video stories
- Generate `all_video_stories.html` for browsing

### Scrape specific stages:
```bash
python3 scrape_video_stories.py --stages dev test
python3 scrape_video_stories.py --stage dev-old
```

### Custom output file:
```bash
python3 scrape_video_stories.py --output my_videos.json
```

### Output format options:
```bash
python3 scrape_video_stories.py --format json   # JSON only
python3 scrape_video_stories.py --format html   # HTML only
python3 scrape_video_stories.py --format both   # Both (default)
```

## Output Files

### JSON Output
Contains all video stories with enriched metadata:
- Original DynamoDB attributes
- Enriched fields (prefixed with `_`):
  - `_stage`: Which stage the story came from
  - `_region`: AWS region
  - `_created`: Timestamp
  - `_video_url`: Video URL/key
  - `_viewed`: Boolean viewed status
  - `_participants`: Parsed participants list
  - `_gamer_extracted`: Extracted gamer ID
  - etc.

### HTML Report
A browsable HTML page with:
- Summary statistics
- Filters by stage, viewed status, and search
- Card layout for easy browsing
- Direct links to video files

## Examples

### Scrape only old stages in us-west-2:
```bash
python3 scrape_video_stories.py --stages dev-old test-old prod-old --output old_stories.json
```

### Quick check of dev stage:
```bash
python3 scrape_video_stories.py --stage dev --format json
```

## AWS Resources

The scraper accesses these DynamoDB tables:

| Stage | Region | Table |
|-------|--------|-------|
| dev | us-east-1 | GGEventsTable-147552928523-dev |
| test | us-east-1 | GGEventsTable-147552928523-test |
| dev-old | us-west-2 | GGEventsTable-147552928523-dev |
| test-old | us-west-2 | GGEventsTable-147552928523-test |
| prod-old | us-west-2 | GGEventsTable-147552928523-prod |

## Video Story Structure

Video stories in DynamoDB have the following structure:
- **PK**: Parent ID (e.g., `P#<uuid>`)
- **SK**: Sort key format `V#<timestamp>#<gamer_id>`
- **GSI1PK**: Gamer ID
- **GSI1SK**: `V#<timestamp>`
- **GSI2PK**: 'VideoStory' (for global indexing)
- **Attributes**:
  - `video_url`: S3 URL or key
  - `description`: Story description
  - `group`: Group ID
  - `participants`: JSON array of participant IDs
  - `viewed`: 'True' or 'False'
  - `timestamp`: Creation timestamp
  - Optional: `gameserver_id`, `game_start`, `game_end`, `thumbnail_url`

## Troubleshooting

### Permission errors
Ensure your AWS credentials have the following permissions:
```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:Scan",
    "dynamodb:Query",
    "dynamodb:DescribeTable"
  ],
  "Resource": [
    "arn:aws:dynamodb:us-east-1:147552928523:table/GGEventsTable-*",
    "arn:aws:dynamodb:us-west-2:147552928523:table/GGEventsTable-*"
  ]
}
```

### No video stories found
- Verify the table exists: `aws dynamodb describe-table --table-name <table> --region <region>`
- Check if there are items with SK starting with 'V#' in the table

### Slow scanning
DynamoDB scan operations can be slow for large tables. The script shows progress as it scans.

## Watching Videos with Presigned URLs

The video URLs in the JSON output are S3 keys, not actual URLs. To watch the videos in your browser, you need to generate presigned URLs:

```bash
python3 generate_presigned_urls.py
```

This creates:
- `all_video_stories_presigned.json` - JSON with presigned URLs (valid for 30 days)
- `all_video_stories_presigned.html` - **Interactive webpage with embedded video players!**

Open the HTML file in your browser to watch all the videos directly.

**Key features:**
- ✅ Embedded video players - click to play
- ✅ Automatic thumbnail generation
- ✅ Shows which videos are available vs missing
- ✅ URLs valid for 30 days (default)
- ✅ Search and filter functionality

For more details, see [PRESIGNED_URLS_GUIDE.md](PRESIGNED_URLS_GUIDE.md).

### Custom expiration:
```bash
# 7 days
python3 generate_presigned_urls.py --expiration 604800

# 60 days
python3 generate_presigned_urls.py --expiration 5184000
```

## Related Scripts

See also `../backend/demo/list_video_stories.py` for the original single-stage video story lister.

