#!/usr/bin/env python3
"""
Generate presigned URLs for video stories to make them viewable in the browser.

This script:
1. Reads the video stories JSON file
2. Generates presigned S3 URLs for each video (valid for 7 days by default)
3. Updates the JSON with presigned URLs
4. Optionally generates a new HTML report with working video links

Usage:
    python3 generate_presigned_urls.py --input all_video_stories.json
    python3 generate_presigned_urls.py --input all_video_stories.json --expiration 86400  # Override to 1 day
    python3 generate_presigned_urls.py --input all_video_stories.json --html-only  # Just regenerate HTML
"""

import boto3
import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any
from botocore.exceptions import ClientError


class DecimalEncoder(json.JSONEncoder):
    """Helper to convert Decimal types to int/float for JSON serialization"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super(DecimalEncoder, self).default(obj)


def load_resources_config(config_path: str = "resources.json") -> Dict[str, Any]:
    """Load the resources configuration file"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        print(f"❌ Configuration file not found: {config_path}")
        sys.exit(1)


def load_video_stories(input_file: str) -> List[Dict[str, Any]]:
    """Load video stories from JSON file"""
    try:
        with open(input_file, 'r') as f:
            stories = json.load(f)
        print(f"✅ Loaded {len(stories)} video stories from {input_file}")
        return stories
    except FileNotFoundError:
        print(f"❌ Input file not found: {input_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in input file: {e}")
        sys.exit(1)


def generate_presigned_url(bucket_name: str, object_key: str, region: str, expiration: int = 2592000) -> str:
    """
    Generate a presigned URL for an S3 object
    
    Args:
        bucket_name: S3 bucket name
        object_key: S3 object key (path)
        region: AWS region
        expiration: URL expiration time in seconds (default: 30 days)
        
    Returns:
        str: Presigned URL or error message
    """
    try:
        s3_client = boto3.client('s3', region_name=region)
        
        # First check if the object exists
        try:
            s3_client.head_object(Bucket=bucket_name, Key=object_key)
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return f"ERROR: Object not found: s3://{bucket_name}/{object_key}"
            else:
                return f"ERROR: Cannot access object: {str(e)}"
        
        # Generate presigned URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket_name,
                'Key': object_key
            },
            ExpiresIn=expiration
        )
        
        return presigned_url
        
    except Exception as e:
        return f"ERROR: Failed to generate presigned URL: {str(e)}"


def process_video_stories(stories: List[Dict[str, Any]], config: Dict[str, Any], 
                          expiration: int = 2592000, skip_missing: bool = True) -> List[Dict[str, Any]]:
    """
    Process video stories and generate presigned URLs
    
    Args:
        stories: List of video stories
        config: Resources configuration
        expiration: URL expiration time in seconds
        skip_missing: If True, skip videos that don't exist; if False, keep error messages
        
    Returns:
        list: Updated stories with presigned URLs
    """
    print(f"\n🔗 Generating presigned URLs (expiration: {expiration // 3600} hours)...")
    
    processed = 0
    errors = 0
    missing = 0
    reused = 0
    
    for story in stories:
        # Check if this story already has a valid presigned URL
        # Presigned URLs can use Signature V2 (AWSAccessKeyId) or V4 (X-Amz-*)
        existing_url = story.get('_presigned_url')
        if existing_url and not existing_url.startswith('ERROR:') and ('?' in existing_url) and \
           ('X-Amz-Expires=' in existing_url or 'AWSAccessKeyId=' in existing_url or 'Signature=' in existing_url):
            # URL exists and looks valid, reuse it
            reused += 1
            
            # Progress indicator - show every 100 stories
            total_processed = processed + errors + missing + reused
            if total_processed % 100 == 0 and total_processed > 0:
                percentage = (total_processed / len(stories)) * 100
                print(f"   Progress: {total_processed}/{len(stories)} ({percentage:.1f}%) - "
                      f"✓ {processed} signed, ♻️ {reused} reused, ✗ {missing} missing, ⚠ {errors} errors")
            continue
        
        # Need to generate a new presigned URL
        stage = story.get('_stage', 'unknown')
        
        # Get bucket for this stage
        if stage not in config['stages']:
            print(f"⚠️  Unknown stage: {stage}")
            errors += 1
            continue
        
        stage_config = config['stages'][stage]
        bucket_name = stage_config['s3_bucket']
        region = stage_config['region']
        
        # Get video key
        video_key = story.get('_video_url', story.get('video_url', ''))
        if not video_key or video_key == 'N/A':
            errors += 1
            continue
        
        # Generate presigned URL
        presigned_url = generate_presigned_url(bucket_name, video_key, region, expiration)
        
        if presigned_url.startswith('ERROR:'):
            if 'not found' in presigned_url:
                missing += 1
                if skip_missing:
                    story['_presigned_url'] = None
                    story['_presigned_error'] = 'Video file not found'
                else:
                    story['_presigned_url'] = presigned_url
            else:
                errors += 1
                story['_presigned_url'] = presigned_url
        else:
            story['_presigned_url'] = presigned_url
            processed += 1
        
        # Also generate presigned URL for thumbnail if present (or reuse existing)
        existing_thumbnail = story.get('_presigned_thumbnail')
        thumbnail_key = story.get('thumbnail_url', '')
        
        if existing_thumbnail and not existing_thumbnail.startswith('ERROR:') and ('?' in existing_thumbnail) and \
           ('X-Amz-Expires=' in existing_thumbnail or 'AWSAccessKeyId=' in existing_thumbnail or 'Signature=' in existing_thumbnail):
            # Reuse existing thumbnail URL
            pass
        elif thumbnail_key and thumbnail_key != 'N/A':
            # Generate new thumbnail URL
            thumbnail_presigned = generate_presigned_url(bucket_name, thumbnail_key, region, expiration)
            if not thumbnail_presigned.startswith('ERROR:'):
                story['_presigned_thumbnail'] = thumbnail_presigned
        
        # Progress indicator - show every 100 stories
        total_processed = processed + errors + missing + reused
        if total_processed % 100 == 0 and total_processed > 0:
            percentage = (total_processed / len(stories)) * 100
            print(f"   Progress: {total_processed}/{len(stories)} ({percentage:.1f}%) - "
                  f"✓ {processed} signed, ♻️ {reused} reused, ✗ {missing} missing, ⚠ {errors} errors")
    
    # Final summary
    total_processed = processed + errors + missing + reused
    total_available = processed + reused
    percentage = (total_available / len(stories)) * 100 if len(stories) > 0 else 0
    print(f"\n{'=' * 70}")
    print(f"✅ Generated {processed} new presigned URLs")
    if reused > 0:
        print(f"♻️  Reused {reused} existing presigned URLs")
    print(f"📊 Total available: {total_available}/{len(stories)} ({percentage:.1f}% success)")
    if missing > 0:
        print(f"⚠️  {missing} video files not found in S3")
    if errors > 0:
        print(f"❌ {errors} errors occurred")
    
    return stories


def save_to_json(stories: List[Dict[str, Any]], output_file: str):
    """Save video stories with presigned URLs to JSON file"""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(stories, f, indent=2, cls=DecimalEncoder, ensure_ascii=False)
        print(f"💾 Saved to: {output_file}")
    except Exception as e:
        print(f"❌ Error saving to file: {e}")


def generate_html_with_presigned_urls(stories: List[Dict[str, Any]], output_file: str):
    """
    Generate an HTML report with working presigned video URLs
    """
    # Deduplicate stories based on gamer + timestamp (same video shown to multiple parents)
    seen = {}
    deduplicated_stories = []
    
    for story in stories:
        gamer = story.get('GSI1PK', story.get('_gamer_extracted', ''))
        timestamp = story.get('_created', story.get('timestamp', ''))
        key = f"{gamer}_{timestamp}"
        
        if key not in seen:
            seen[key] = True
            deduplicated_stories.append(story)
    
    original_count = len(stories)
    stories = deduplicated_stories
    
    if original_count != len(stories):
        print(f"ℹ️  Deduplicated: {original_count} → {len(stories)} stories ({original_count - len(stories)} duplicates removed)")
    
    # Calculate stats
    total = len(stories)
    available = len([s for s in stories if s.get('_presigned_url') and not s['_presigned_url'].startswith('ERROR:')])
    missing = len([s for s in stories if s.get('_presigned_error')])
    
    # Get expiration info from first valid presigned URL
    expiration_hours = 720  # default 30 days
    expiration_date = None
    for story in stories:
        if story.get('_presigned_url') and not story['_presigned_url'].startswith('ERROR:'):
            # Calculate expiration (typically 7 days from now)
            from datetime import datetime, timedelta
            expiration_date = datetime.now() + timedelta(hours=expiration_hours)
            break
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GuardianGamer Video Stories - Presigned URLs</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .warning {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .warning strong {{
            color: #856404;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .stat-card h3 {{
            margin: 0 0 10px 0;
            color: #666;
            font-size: 14px;
            text-transform: uppercase;
        }}
        .stat-card .value {{
            font-size: 32px;
            font-weight: bold;
            color: #4CAF50;
        }}
        .filters {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            position: sticky;
            top: 0;
            z-index: 1000;
            border-bottom: 3px solid #4CAF50;
        }}
        .filters h3 {{
            margin-top: 0;
            margin-bottom: 10px;
            color: #333;
        }}
        .filters input, .filters select {{
            padding: 8px;
            margin: 5px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }}
        .filters input[type="text"] {{
            min-width: 200px;
        }}
        .story-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .story-card {{
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}
        .story-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        .video-container {{
            position: relative;
            width: 100%;
            padding-top: 56.25%; /* 16:9 Aspect Ratio */
            background: #000;
            cursor: pointer;
            overflow: hidden;
        }}
        .video-container video {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: none;
        }}
        .video-container video.playing {{
            display: block;
        }}
        .thumbnail-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-size: cover;
            background-position: center;
            background-color: #000;
        }}
        .thumbnail-overlay.no-thumbnail {{
            background: #1a1a1a;
        }}
        .play-button {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 80px;
            height: 80px;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        .play-button:hover {{
            background: rgba(255, 255, 255, 1);
            transform: translate(-50%, -50%) scale(1.1);
        }}
        .play-button::after {{
            content: '';
            width: 0;
            height: 0;
            border-left: 30px solid #333;
            border-top: 20px solid transparent;
            border-bottom: 20px solid transparent;
            margin-left: 8px;
        }}
        .video-missing {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #666;
            color: white;
            font-size: 14px;
        }}
        .story-content {{
            padding: 20px;
        }}
        .story-title {{
            font-weight: bold;
            color: #333;
            font-size: 16px;
            margin-bottom: 5px;
        }}
        .story-meta {{
            font-size: 12px;
            color: #999;
            margin-bottom: 10px;
        }}
        .story-description {{
            margin: 15px 0;
            color: #666;
            line-height: 1.5;
            font-size: 14px;
            max-height: 100px;
            overflow: hidden;
        }}
        .story-description.expanded {{
            max-height: none;
        }}
        .read-more {{
            color: #4CAF50;
            cursor: pointer;
            font-size: 12px;
            margin-top: 5px;
        }}
        .story-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 10px;
        }}
        .tag {{
            background: #e3f2fd;
            color: #1976d2;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
        }}
        .tag.stage {{
            background: #f3e5f5;
            color: #7b1fa2;
        }}
        .tag.available {{
            background: #e8f5e9;
            color: #388e3c;
        }}
        .tag.missing {{
            background: #ffebee;
            color: #c62828;
        }}
        .favorite-button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 36px;
            height: 36px;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 50%;
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            margin-left: 10px;
            vertical-align: middle;
        }}
        .favorite-button:hover {{
            background: rgba(255, 255, 255, 1);
            transform: scale(1.1);
        }}
        .favorite-button.favorited {{
            background: #ff4444;
        }}
        .favorite-button::before {{
            content: '♡';
            font-size: 20px;
            color: #666;
        }}
        .favorite-button.favorited::before {{
            content: '♥';
            color: white;
        }}
        .remove-gamer-button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 4px 8px;
            background: rgba(255, 100, 100, 0.9);
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            margin-left: 10px;
            font-size: 11px;
            color: white;
            font-weight: bold;
        }}
        .remove-gamer-button:hover {{
            background: rgba(255, 50, 50, 1);
            transform: scale(1.05);
        }}
        .story-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .story-header-buttons {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .favorites-controls {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .favorites-controls button {{
            padding: 10px 20px;
            margin: 5px;
            border: none;
            border-radius: 4px;
            background: #4CAF50;
            color: white;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.3s;
        }}
        .favorites-controls button:hover {{
            background: #45a049;
        }}
        .favorites-controls button.secondary {{
            background: #2196F3;
        }}
        .favorites-controls button.secondary:hover {{
            background: #0b7dda;
        }}
        .favorites-count {{
            display: inline-block;
            margin-left: 10px;
            padding: 5px 10px;
            background: #e3f2fd;
            color: #1976d2;
            border-radius: 4px;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <h1>🎮 GuardianGamer Video Stories</h1>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <div class="warning">
        <strong>⏰ Presigned URL Expiration:</strong> These video links will expire on <strong>{expiration_date.strftime('%Y-%m-%d %H:%M:%S') if expiration_date else 'N/A'}</strong>. 
        After that, you'll need to regenerate the presigned URLs using: <code>python3 generate_presigned_urls.py</code>
    </div>
    
    <div class="favorites-controls">
        <h3>⭐ Favorites <span class="favorites-count" id="favCount">0</span></h3>
        <button onclick="exportFavorites()">💾 Export Favorites to JSON</button>
        <button onclick="document.getElementById('importFile').click()" class="secondary">📂 Import Favorites</button>
        <button onclick="clearFavorites()" class="secondary">🗑️ Clear All Favorites</button>
        <input type="file" id="importFile" accept=".json" style="display:none" onchange="importFavorites(event)">
    </div>
    
    <div class="stats">
        <div class="stat-card">
            <h3>Total Stories</h3>
            <div class="value">{total}</div>
        </div>
        <div class="stat-card">
            <h3>Videos Available</h3>
            <div class="value">{available}</div>
        </div>
        <div class="stat-card">
            <h3>Videos Missing</h3>
            <div class="value">{missing}</div>
        </div>
        <div class="stat-card">
            <h3>Success Rate</h3>
            <div class="value">{(available/total*100) if total > 0 else 0:.1f}%</div>
        </div>
    </div>
    
    <div class="filters">
        <h3>Filters</h3>
        <div style="margin-bottom: 10px;">
            <input type="text" id="searchInput" placeholder="Search..." onkeyup="filterStories()">
            <select id="stageFilter" onchange="filterStories()">
                <option value="">All Stages</option>
"""
    
    # Get unique stages
    stages = sorted(set(s.get('_stage', 'unknown') for s in stories))
    for stage in stages:
        html += f'            <option value="{stage}">{stage}</option>\n'
    
    html += """
            </select>
            <select id="availabilityFilter" onchange="filterStories()">
                <option value="">All Videos</option>
                <option value="available">Available Only</option>
                <option value="missing">Missing Only</option>
            </select>
            <select id="favoriteFilter" onchange="filterStories()">
                <option value="">All Stories</option>
                <option value="favorited">⭐ Favorites Only</option>
                <option value="not-favorited">Not Favorited</option>
            </select>
        </div>
        <div style="margin-top: 10px;">
            <label style="margin-right: 10px;">
                <input type="radio" name="gamerMode" value="include" checked onchange="filterStories()"> Include
            </label>
            <label style="margin-right: 10px;">
                <input type="radio" name="gamerMode" value="exclude" onchange="filterStories()"> Exclude
            </label>
            <select id="gamerFilter" multiple size="1" onchange="filterStories()" 
                    style="min-width: 250px; max-width: 400px;">
                <option value="">All Gamers</option>
"""
    
    # Get unique gamers with their extracted names
    gamer_info = {}
    for s in stories:
        gamer_id = s.get('GSI1PK', s.get('_gamer_extracted', ''))
        gamer_name = s.get('_gamer_extracted', gamer_id).split('_')[-1] if '_' in gamer_id else gamer_id
        # Clean up the gamer name
        gamer_display = gamer_name.replace('G#', '').replace('_', ' ')
        if gamer_id and gamer_id != 'N/A':
            gamer_info[gamer_id] = gamer_display
    
    # Sort by display name
    for gamer_id, gamer_display in sorted(gamer_info.items(), key=lambda x: x[1].lower()):
        html += f'                <option value="{gamer_id}">{gamer_display} ({gamer_id[:20]}...)</option>\n'
    
    html += """
            </select>
            <span style="font-size: 12px; color: #666; margin-left: 10px;">
                (Ctrl/Cmd+Click to select multiple)
            </span>
        </div>
    </div>
    
    <h2>Video Stories</h2>
    <div class="story-grid" id="storyGrid">
"""
    
    for idx, story in enumerate(stories):
        stage = story.get('_stage', 'unknown')
        gamer = story.get('_gamer_extracted', 'N/A')
        timestamp = story.get('_created', 'N/A')
        description = story.get('_description', 'No description')
        presigned_url = story.get('_presigned_url')
        presigned_thumbnail = story.get('_presigned_thumbnail')
        group = story.get('_group', 'N/A')
        
        # Determine availability
        is_available = presigned_url and not presigned_url.startswith('ERROR:')
        availability_class = 'available' if is_available else 'missing'
        availability_text = '✓ Available' if is_available else '✗ Missing'
        
        # Truncate description
        display_desc = description if len(description) <= 300 else description[:297] + '...'
        needs_expand = len(description) > 300
        
        # Create a unique ID for this story
        story_id = f"{stage}_{gamer}_{timestamp}".replace('#', '_').replace(':', '_').replace('.', '_')
        
        gamer_id = story.get('GSI1PK', story.get('_gamer_extracted', ''))
        
        html += f"""
        <div class="story-card" data-stage="{stage}" data-availability="{availability_class}" 
             data-search="{gamer.lower()} {description.lower()} {group.lower()}"
             data-story-id="{story_id}" data-gamer-id="{gamer_id}" id="story-{story_id}">
"""
        
        # Video container with thumbnail
        if is_available:
            # Check if thumbnail is available
            thumbnail_style = ''
            thumbnail_class = 'thumbnail-overlay'
            if presigned_thumbnail:
                # HTML escape the thumbnail URL
                safe_thumbnail = presigned_thumbnail.replace("'", "&apos;").replace('"', "&quot;")
                thumbnail_style = f' style="background-image: url(&quot;{safe_thumbnail}&quot;);"'
            else:
                thumbnail_class = 'thumbnail-overlay no-thumbnail'
            
            # Use class and data attributes instead of inline onclick
            html += f"""
            <div class="video-container video-playable">
                <div class="{thumbnail_class}"{thumbnail_style}>
                    <div class="play-button"></div>
                </div>
                <video controls preload="none">
                    <source src="{presigned_url}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>
            </div>
"""
        else:
            html += f"""
            <div class="video-container">
                <div class="video-missing">
                    📹 Video Not Found
                </div>
            </div>
"""
        
        html += f"""
            <div class="story-content">
                <div class="story-header">
                    <div>
                        <div class="story-title">{gamer}</div>
                        <div class="story-meta">{timestamp}</div>
                    </div>
                    <div class="story-header-buttons">
                        <div class="remove-gamer-button" onclick="removeGamer('{gamer_id}', event)" title="Hide this gamer">🚫</div>
                        <div class="favorite-button" onclick="toggleFavorite('{story_id}', event)" id="fav-{story_id}"></div>
                    </div>
                </div>
                <div class="story-description" id="desc-{idx}">
                    {display_desc}
                </div>
"""
        
        if needs_expand:
            html += f"""
                <div class="read-more" onclick="toggleDescription({idx})">
                    Read more...
                </div>
"""
        
        html += f"""
                <div class="story-tags">
                    <span class="tag stage">{stage}</span>
                    <span class="tag {availability_class}">{availability_text}</span>
                </div>
            </div>
        </div>
"""
    
    html += """
    </div>
    
    <script>
        // Favorites management using localStorage
        const FAVORITES_KEY = 'guardianGamerFavorites';
        
        function getFavorites() {
            const stored = localStorage.getItem(FAVORITES_KEY);
            return stored ? JSON.parse(stored) : [];
        }
        
        function saveFavorites(favorites) {
            localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites));
            updateFavoritesCount();
        }
        
        function toggleFavorite(storyId, event) {
            event.stopPropagation();
            const favorites = getFavorites();
            const index = favorites.indexOf(storyId);
            const button = document.getElementById('fav-' + storyId);
            
            if (index > -1) {
                // Remove from favorites
                favorites.splice(index, 1);
                button.classList.remove('favorited');
            } else {
                // Add to favorites
                favorites.push(storyId);
                button.classList.add('favorited');
            }
            
            saveFavorites(favorites);
        }
        
        function removeGamer(gamerId, event) {
            event.stopPropagation();
            
            if (!confirm('Hide all videos from this gamer?')) {
                return;
            }
            
            // Switch to exclude mode
            const excludeRadio = document.querySelector('input[name="gamerMode"][value="exclude"]');
            if (excludeRadio) {
                excludeRadio.checked = true;
            }
            
            // Select the gamer in the dropdown
            const gamerFilter = document.getElementById('gamerFilter');
            const option = Array.from(gamerFilter.options).find(opt => opt.value === gamerId);
            
            if (option) {
                // Add to selection (don't replace existing selections)
                option.selected = true;
                
                // Trigger filter
                filterStories();
                
                // Scroll to top to show the filter bar
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        }
        
        function updateFavoritesCount() {
            const favorites = getFavorites();
            document.getElementById('favCount').textContent = favorites.length;
        }
        
        function loadFavoritesUI() {
            const favorites = getFavorites();
            favorites.forEach(storyId => {
                const button = document.getElementById('fav-' + storyId);
                if (button) {
                    button.classList.add('favorited');
                }
            });
            updateFavoritesCount();
        }
        
        function exportFavorites() {
            const favorites = getFavorites();
            
            // Collect full story data for favorites
            const favoriteStories = [];
            favorites.forEach(storyId => {
                const card = document.getElementById('story-' + storyId);
                if (card) {
                    const storyData = {
                        id: storyId,
                        stage: card.getAttribute('data-stage'),
                        availability: card.getAttribute('data-availability'),
                        timestamp: new Date().toISOString()
                    };
                    favoriteStories.push(storyData);
                }
            });
            
            const exportData = {
                exported: new Date().toISOString(),
                count: favoriteStories.length,
                favorites: favoriteStories
            };
            
            const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'favorites.json';
            a.click();
            URL.revokeObjectURL(url);
            
            alert('Exported ' + favoriteStories.length + ' favorites to favorites.json');
        }
        
        function importFavorites(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            const reader = new FileReader();
            reader.onload = function(e) {
                try {
                    const data = JSON.parse(e.target.result);
                    const importedIds = data.favorites.map(f => f.id);
                    
                    // Merge with existing favorites
                    const currentFavorites = getFavorites();
                    const merged = [...new Set([...currentFavorites, ...importedIds])];
                    
                    saveFavorites(merged);
                    loadFavoritesUI();
                    
                    alert('Imported ' + importedIds.length + ' favorites!\\nTotal favorites: ' + merged.length);
                } catch (error) {
                    alert('Error importing favorites: ' + error.message);
                }
            };
            reader.readAsText(file);
            
            // Reset file input
            event.target.value = '';
        }
        
        function clearFavorites() {
            if (confirm('Are you sure you want to clear all favorites?')) {
                localStorage.removeItem(FAVORITES_KEY);
                
                // Remove visual indicators
                document.querySelectorAll('.favorite-button.favorited').forEach(button => {
                    button.classList.remove('favorited');
                });
                
                updateFavoritesCount();
                alert('All favorites cleared!');
            }
        }
        
        const fullDescriptions = {
"""
    
    # Add full descriptions for expanding
    for idx, story in enumerate(stories):
        description = story.get('_description', 'No description').replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        if len(description) > 300:
            html += f'            {idx}: "{description}",\n'
    
    html += """
        };
        
        function playVideo(container) {
            const thumbnail = container.querySelector('.thumbnail-overlay');
            const video = container.querySelector('video');
            
            if (!video) {
                console.error('Video element not found');
                return;
            }
            
            // Pause and cleanup all other playing videos to save memory
            document.querySelectorAll('video.playing').forEach(function(otherVideo) {
                if (otherVideo !== video) {
                    otherVideo.pause();
                    otherVideo.currentTime = 0;
                    // Unload the video to free memory
                    otherVideo.load();
                    otherVideo.classList.remove('playing');
                    // Show thumbnail again for paused videos
                    const otherContainer = otherVideo.closest('.video-container');
                    if (otherContainer) {
                        const otherThumbnail = otherContainer.querySelector('.thumbnail-overlay');
                        if (otherThumbnail) {
                            otherThumbnail.style.display = 'block';
                        }
                    }
                }
            });
            
            // Hide thumbnail and show video
            if (thumbnail) {
                thumbnail.style.display = 'none';
            }
            
            // Show and play video
            video.classList.add('playing');
            video.style.display = 'block';
            
            // Play the video
            video.play().catch(function(error) {
                console.error('Error playing video:', error);
            });
            
            // When video ends, reset it to save memory
            video.addEventListener('ended', function() {
                video.pause();
                video.currentTime = 0;
                video.load();
                video.classList.remove('playing');
                if (thumbnail) {
                    thumbnail.style.display = 'block';
                }
            }, { once: true });
        }
        
        function toggleDescription(idx) {
            const desc = document.getElementById('desc-' + idx);
            if (fullDescriptions[idx]) {
                if (desc.classList.contains('expanded')) {
                    desc.innerHTML = fullDescriptions[idx].substring(0, 297) + '...';
                    desc.classList.remove('expanded');
                    desc.nextElementSibling.textContent = 'Read more...';
                } else {
                    desc.innerHTML = fullDescriptions[idx];
                    desc.classList.add('expanded');
                    desc.nextElementSibling.textContent = 'Read less';
                }
            }
        }
        
        function filterStories() {
            const searchInput = document.getElementById('searchInput').value.toLowerCase();
            const stageFilter = document.getElementById('stageFilter').value;
            const availabilityFilter = document.getElementById('availabilityFilter').value;
            const favoriteFilter = document.getElementById('favoriteFilter').value;
            const gamerFilter = document.getElementById('gamerFilter');
            const gamerMode = document.querySelector('input[name="gamerMode"]:checked').value;
            const selectedGamers = Array.from(gamerFilter.selectedOptions).map(opt => opt.value).filter(v => v !== '');
            
            const cards = document.querySelectorAll('.story-card');
            const favorites = getFavorites();
            
            let visibleCount = 0;
            
            cards.forEach(card => {
                const searchText = card.getAttribute('data-search');
                const stage = card.getAttribute('data-stage');
                const availability = card.getAttribute('data-availability');
                const storyId = card.getAttribute('data-story-id');
                const gamerInfo = card.getAttribute('data-gamer-id');
                const isFavorited = favorites.includes(storyId);
                
                const matchesSearch = searchText.includes(searchInput);
                const matchesStage = !stageFilter || stage === stageFilter;
                const matchesAvailability = !availabilityFilter || availability === availabilityFilter;
                const matchesFavorite = !favoriteFilter || 
                    (favoriteFilter === 'favorited' && isFavorited) ||
                    (favoriteFilter === 'not-favorited' && !isFavorited);
                
                // Gamer filter logic
                let matchesGamer = true;
                if (selectedGamers.length > 0) {
                    const isGamerSelected = selectedGamers.some(gamerId => gamerInfo === gamerId);
                    if (gamerMode === 'include') {
                        matchesGamer = isGamerSelected;
                    } else {
                        matchesGamer = !isGamerSelected;
                    }
                }
                
                if (matchesSearch && matchesStage && matchesAvailability && matchesFavorite && matchesGamer) {
                    card.style.display = 'block';
                    visibleCount++;
                } else {
                    card.style.display = 'none';
                }
            });
            
            console.log('Showing ' + visibleCount + ' of ' + cards.length + ' stories');
        }
        
        // Attach video player click handlers via event delegation
        document.addEventListener('click', function(e) {
            const videoContainer = e.target.closest('.video-playable');
            if (videoContainer && !e.target.closest('.favorite-button')) {
                playVideo(videoContainer);
            }
        });
        
        // Pause videos when scrolling away (optional - helps with memory on mobile)
        let scrollTimeout;
        window.addEventListener('scroll', function() {
            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(function() {
                // Pause videos that are far off screen
                document.querySelectorAll('video.playing').forEach(function(video) {
                    const rect = video.getBoundingClientRect();
                    const isVisible = rect.top < window.innerHeight + 500 && rect.bottom > -500;
                    if (!isVisible) {
                        video.pause();
                        video.currentTime = 0;
                        video.load();
                        video.classList.remove('playing');
                        // Show thumbnail again
                        const container = video.closest('.video-container');
                        if (container) {
                            const thumbnail = container.querySelector('.thumbnail-overlay');
                            if (thumbnail) {
                                thumbnail.style.display = 'block';
                            }
                        }
                    }
                });
            }, 200);
        });
        
        // Initialize favorites on page load
        window.addEventListener('DOMContentLoaded', function() {
            loadFavoritesUI();
        });
    </script>
</body>
</html>
"""
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"📄 Generated HTML report: {output_file}")
    except Exception as e:
        print(f"❌ Error generating HTML report: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate presigned URLs for video stories',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 generate_presigned_urls.py
  python3 generate_presigned_urls.py --force-regenerate  # Regenerate all URLs
  python3 generate_presigned_urls.py --expiration 86400  # Override to 1 day
  python3 generate_presigned_urls.py --html-only  # Skip presigned URL generation
        """
    )
    
    parser.add_argument(
        '--input',
        '-i',
        default='all_video_stories.json',
        help='Input JSON file with video stories (default: all_video_stories.json)'
    )
    
    parser.add_argument(
        '--output',
        '-o',
        help='Output JSON file (default: <input>_presigned.json)'
    )
    
    parser.add_argument(
        '--html',
        help='Output HTML file (default: <input>_presigned.html)'
    )
    
    parser.add_argument(
        '--config',
        default='resources.json',
        help='Path to resources configuration file (default: resources.json)'
    )
    
    parser.add_argument(
        '--expiration',
        type=int,
        default=2592000,  # 30 days
        help='URL expiration time in seconds (default: 2592000 = 30 days)'
    )
    
    parser.add_argument(
        '--skip-missing',
        action='store_true',
        default=True,
        help='Skip videos that are missing from S3 (default: True)'
    )
    
    parser.add_argument(
        '--html-only',
        action='store_true',
        help='Only regenerate HTML from existing presigned URLs (skip URL generation)'
    )
    
    parser.add_argument(
        '--force-regenerate',
        action='store_true',
        help='Force regenerate all URLs (do not reuse existing presigned URLs)'
    )
    
    args = parser.parse_args()
    
    print("🔗 Presigned URL Generator for GuardianGamer Video Stories")
    print("=" * 70)
    
    # Determine output filenames
    input_path = Path(args.input)
    if not args.output:
        output_json = input_path.stem + '_presigned.json'
    else:
        output_json = args.output
    
    if not args.html:
        output_html = input_path.stem + '_presigned.html'
    else:
        output_html = args.html
    
    # Smart input selection: if a presigned version exists and we're using the default input,
    # use the presigned version to reuse existing URLs (unless force-regenerate is set)
    actual_input = args.input
    if not args.force_regenerate and args.input == 'all_video_stories.json' and Path(output_json).exists():
        print(f"ℹ️  Found existing presigned file: {output_json}")
        print(f"ℹ️  Will reuse valid URLs from it instead of regenerating all")
        print(f"   (Use --force-regenerate to regenerate all URLs from scratch)")
        actual_input = output_json
    elif args.force_regenerate:
        print(f"🔄 Force regenerate mode: Will create all new presigned URLs")
    
    # Load video stories
    stories = load_video_stories(actual_input)
    
    if not args.html_only:
        # Load configuration
        config = load_resources_config(args.config)
        
        # Process and generate presigned URLs
        stories = process_video_stories(stories, config, args.expiration, args.skip_missing)
        
        # Save updated JSON
        save_to_json(stories, output_json)
    else:
        print("ℹ️  HTML-only mode: Using existing presigned URLs from input file")
        output_json = args.input
    
    # Generate HTML report
    print(f"\n📄 Generating HTML report...")
    generate_html_with_presigned_urls(stories, output_html)
    
    print(f"\n{'=' * 70}")
    print("✅ Presigned URL generation complete!")
    print(f"\n📂 Output files:")
    if not args.html_only:
        print(f"   JSON: {output_json}")
    print(f"   HTML: {output_html}")
    print(f"\n💡 Open {output_html} in your browser to watch the videos!")
    print(f"⏰ URLs will expire in {args.expiration // 3600} hours ({args.expiration // 86400} days)")
    
    return 0


if __name__ == '__main__':
    exit(main())

