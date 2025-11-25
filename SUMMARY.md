# Video Stories Scraper - Summary

## Completed Tasks ✅

### 1. AWS Resources Inventory

**DynamoDB Tables by Region:**

**us-east-1 (Current stages):**
- `GGEventsTable-147552928523-dev` - Created: 2025-07-14
- `GGEventsTable-147552928523-test` - Current test

**us-west-2 (Old stages):**
- `GGEventsTable-147552928523-dev` - Created: 2024-08-23
- `GGEventsTable-147552928523-test` - Old test stage
- `GGEventsTable-147552928523-prod` - Old production

**S3 Buckets by Region:**

**us-east-1 (SAM deployments):**
- `ggbucket-sam-147552928523-dev`
- `ggbucket-sam-147552928523-test`
- `ggbucket-sam-147552928523-prod`

**us-west-2 (Old deployments):**
- `ggbucket-147552928523-dev`
- `ggbucket-147552928523-test`
- `ggbucket-147552928523-prod`

### 2. Configuration File Created

**File:** `resources.json`

Contains mapping of all 5 stages:
- `dev` - Current dev in us-east-1
- `test` - Current test in us-east-1  
- `dev-old` - Old dev in us-west-2
- `test-old` - Old test in us-west-2
- `prod-old` - Old prod in us-west-2

### 3. Scraper Script Created

**File:** `scrape_video_stories.py`

A comprehensive Python script that:
- Reads configuration from `resources.json`
- Scans DynamoDB tables for video stories (SK starting with "V#")
- Supports scraping single or multiple stages
- Enriches data with computed fields
- Generates both JSON and HTML outputs
- Provides filtering and search capabilities

### 4. Results

**Total Video Stories Found: 4,164**

Distribution by stage:
- **dev** (us-east-1): 295 stories
- **test** (us-east-1): 85 stories
- **dev-old** (us-west-2): 1,822 stories ⭐
- **test-old** (us-west-2): 0 stories
- **prod-old** (us-west-2): 1,962 stories ⭐

**Key Statistics:**
- 25 unique parents
- 33 unique gamers  
- 39 unique groups
- 1,708 viewed stories
- 2,456 unviewed stories

**Most valuable stages:** The old us-west-2 stages (`dev-old` and `prod-old`) contain the majority of video stories (3,784 out of 4,164, or 91%).

## Output Files

### 1. all_video_stories.json (6.5 MB)
Complete dataset with all 4,164 video stories including:
- Original DynamoDB attributes
- Enriched metadata fields (prefixed with `_`)
- Stage and region information

### 2. all_video_stories.html (5.3 MB)
Interactive HTML report with:
- Summary dashboard with statistics
- Stage-by-stage breakdown
- Search functionality
- Filters (stage, viewed status)
- Card-based layout for easy browsing
- Direct links to video files

### 3. README.md
Comprehensive documentation including:
- Setup instructions
- Usage examples
- AWS resource mappings
- Troubleshooting guide

## Usage Examples

### Scrape all stages:
```bash
python3 scrape_video_stories.py
```

### Scrape only old us-west-2 stages:
```bash
python3 scrape_video_stories.py --stages dev-old prod-old
```

### Scrape single stage:
```bash
python3 scrape_video_stories.py --stage dev-old
```

### Custom output:
```bash
python3 scrape_video_stories.py --output my_videos.json --format both
```

## Video Story Structure

Each video story includes:
- **Parent ID** (PK): The parent/guardian who owns the story
- **Gamer ID** (GSI1PK): The child/gamer featured in the video
- **Timestamp**: When the story was created
- **Video URL**: S3 path to the video file
- **Description**: AI-generated description of the gaming session
- **Group**: Family group ID
- **Participants**: List of gamers in the session
- **Game Metadata**: gameserver_id, game_start, game_end times
- **Session Metadata**: session_start, session_end times
- **Viewed Status**: Whether the story has been viewed

## Sample Video Story

```json
{
  "PK": "P#7c905f69-c71a-45f5-8f20-6be389d394e9",
  "SK": "V#2025-09-01T22:32:24.909Z#G#3504d3e7-8836-481b-a062-1d5c4e7a29a7",
  "GSI1PK": "G#3504d3e7-8836-481b-a062-1d5c4e7a29a7",
  "description": "Gardening Adventure (Grow a Garden) – Lente spent several minutes exploring...",
  "video_url": "sessions/.../reel_2025-09-01T22:32:24.909Z.mp4",
  "thumbnail_url": "sessions/.../reel_2025-09-01T22:32:24.909Z_thumbnail.jpg",
  "gameserver_id": "roblox126884695634066",
  "viewed": "False",
  "_stage": "dev",
  "_region": "us-east-1"
}
```

## Next Steps

1. **Open the HTML report** (`all_video_stories.html`) in a browser to browse the stories interactively
2. **Use the JSON file** (`all_video_stories.json`) for programmatic analysis
3. **Filter by stage** to focus on specific environments
4. **Search for interesting stories** using descriptions, gamer IDs, or game servers

## AWS Permissions Required

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

---

**Created:** November 19, 2025  
**Total Time:** ~30 minutes  
**Success:** ✅ All 4,164 video stories successfully scraped and catalogued

