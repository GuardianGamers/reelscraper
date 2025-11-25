# Presigned URLs Guide

## Why Presigned URLs?

The video stories in the JSON files contain S3 keys (paths) like:
```
sessions/G_3504d3e7.../reel/2025-09-01T22:30:21.909Z/reel_2025-09-01T22:32:24.909Z.mp4
```

These are NOT URLs you can open in a browser. You need to generate **presigned URLs** that grant temporary access to the S3 objects.

## Quick Start

### Generate presigned URLs (valid for 30 days):

```bash
python3 generate_presigned_urls.py
```

This will:
1. Read `all_video_stories.json`
2. Generate presigned URLs for each video (valid for 30 days)
3. Create `all_video_stories_presigned.json` with the URLs
4. Create `all_video_stories_presigned.html` - **Open this in your browser to watch videos!**

### Custom expiration times:

```bash
# 7 days
python3 generate_presigned_urls.py --expiration 604800

# 14 days  
python3 generate_presigned_urls.py --expiration 1209600

# 60 days (if your AWS account allows)
python3 generate_presigned_urls.py --expiration 5184000
```

### Custom input file:

```bash
python3 generate_presigned_urls.py --input my_stories.json --output my_stories_with_urls.json
```

## Output Files

### JSON File (`all_video_stories_presigned.json`)
Contains all video stories with added fields:
- `_presigned_url`: The temporary URL to watch the video
- `_presigned_thumbnail`: The temporary URL for the thumbnail (if available)
- `_presigned_error`: Error message if the video file doesn't exist

### HTML File (`all_video_stories_presigned.html`)
Interactive webpage with:
- **Embedded video players** - Click to play videos directly in the browser
- **Search and filters** - Find specific stories
- **Expiration warning** - Shows when URLs will expire
- **Availability status** - Shows which videos are available vs missing

## Important Notes

### ⏰ URL Expiration
- Default: **30 days** from generation
- After expiration, you'll need to regenerate the URLs
- The HTML file will show the expiration date at the top

### 📹 Missing Videos
Some video files may not exist in S3 (they may have been deleted or moved). The script will:
- Mark these as "Missing" in the HTML
- Skip generating presigned URLs for them
- Continue processing the rest

### 🔄 Regenerating URLs
When your presigned URLs expire, simply run the script again:

```bash
python3 generate_presigned_urls.py
```

It will generate fresh URLs valid for another 30 days.

## Examples

### Example 1: Generate URLs and open in browser
```bash
python3 generate_presigned_urls.py
open all_video_stories_presigned.html  # macOS
# or
xdg-open all_video_stories_presigned.html  # Linux
# or
start all_video_stories_presigned.html  # Windows
```

### Example 2: Process only old stages
First scrape only old stages:
```bash
python3 scrape_video_stories.py --stages dev-old prod-old --output old_stories.json
```

Then generate presigned URLs:
```bash
python3 generate_presigned_urls.py --input old_stories.json --output old_stories_presigned.json
```

### Example 3: Regenerate HTML only (if URLs still valid)
```bash
python3 generate_presigned_urls.py --html-only
```

This is useful if you want to regenerate the HTML report without creating new presigned URLs (saves time if URLs haven't expired yet).

## How It Works

1. **Reads your video stories JSON** - Gets the S3 keys for videos
2. **Looks up the correct S3 bucket** - Based on stage and region from `resources.json`
3. **Checks if video exists** - Uses S3 HeadObject to verify the file exists
4. **Generates presigned URL** - Creates a temporary URL with AWS credentials embedded
5. **Saves results** - Updates JSON and generates HTML

## Troubleshooting

### "Object not found" errors
Some videos may have been deleted or moved. This is normal. The script will skip them and continue.

### "Permission denied" errors
Ensure your AWS credentials have S3 read access:
```json
{
  "Effect": "Allow",
  "Action": [
    "s3:GetObject",
    "s3:HeadObject"
  ],
  "Resource": [
    "arn:aws:s3:::ggbucket-*/*",
    "arn:aws:s3:::ggbucket-sam-*/*"
  ]
}
```

### URLs expire quickly
AWS S3 presigned URLs have a maximum expiration of 7 days by default, but can be extended up to 36 hours for temporary credentials. If you're using IAM role credentials (like on EC2), you might hit this limit. Use IAM user credentials for longer expirations.

### Videos won't play in browser
- Check that the S3 bucket has CORS configured to allow your browser origin
- Try downloading the video instead of streaming it
- Check browser console for CORS errors

## Performance

- Processing 4,164 videos takes ~5-10 minutes
- Most time is spent checking if each video exists in S3
- The script shows progress every 100 videos

## Security Note

⚠️ **Presigned URLs contain temporary AWS credentials in the query string.** Anyone with a presigned URL can access the video until it expires. Don't share these URLs publicly unless you intend to share the videos.

