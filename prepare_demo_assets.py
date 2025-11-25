#!/usr/bin/env python3
"""
Prepare demo assets from favorited video stories.

This script:
1. Loads demo_favorites.json to get story IDs
2. Finds matching stories in all_video_stories_presigned.json
3. Downloads videos and thumbnails from S3
4. Generates thumbnails for videos that don't have them
5. Renames files to demostoryXXX.mp4 and demostoryXXX.jpg
6. Creates demo_stories.json with all metadata

Usage:
    python3 prepare_demo_assets.py
"""

import boto3
import json
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any


def load_favorites(favorites_file: str = "demo_favorites.json") -> List[str]:
    """Load favorite story IDs from JSON file"""
    try:
        with open(favorites_file, 'r') as f:
            data = json.load(f)
        
        # Handle both formats: list of IDs or favorites export format
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'favorites' in data:
            return [fav['id'] for fav in data['favorites']]
        else:
            print(f"❌ Unexpected format in {favorites_file}")
            return []
    except FileNotFoundError:
        print(f"❌ File not found: {favorites_file}")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        return []


def load_video_stories(stories_file: str = "all_video_stories_presigned.json") -> List[Dict[str, Any]]:
    """Load all video stories"""
    try:
        with open(stories_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ File not found: {stories_file}")
        return []


def find_stories_by_ids(all_stories: List[Dict[str, Any]], story_ids: List[str]) -> List[Dict[str, Any]]:
    """Find stories matching the favorite IDs (deduplicated)"""
    seen = {}
    matched = []
    
    # Create story ID for each story and deduplicate
    for story in all_stories:
        stage = story.get('_stage', 'unknown')
        gamer = story.get('_gamer_extracted', 'N/A')
        timestamp = story.get('_created', story.get('timestamp', 'N/A'))
        story_id = f"{stage}_{gamer}_{timestamp}".replace('#', '_').replace(':', '_').replace('.', '_')
        
        if story_id in story_ids and story_id not in seen:
            story['_computed_story_id'] = story_id
            matched.append(story)
            seen[story_id] = True
    
    return matched


def download_from_s3(bucket: str, key: str, local_path: str, region: str) -> bool:
    """Download a file from S3"""
    try:
        s3 = boto3.client('s3', region_name=region)
        s3.download_file(bucket, key, local_path)
        return True
    except Exception as e:
        print(f"   ⚠️  Failed to download s3://{bucket}/{key}: {e}")
        return False


def generate_thumbnail_from_video(video_path: str, thumbnail_path: str) -> bool:
    """Generate a thumbnail from the first frame of a video using ffmpeg"""
    try:
        # Scale to cover 600x400, then center-crop to exactly 600x400
        # This ensures consistent thumbnail size regardless of video aspect ratio
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vframes', '1',           # Extract 1 frame
            '-vf', 'scale=600:400:force_original_aspect_ratio=increase,crop=600:400',  # Scale and center-crop to 600x400
            '-q:v', '2',                # High quality JPEG (1-31, lower is better)
            '-f', 'image2',
            '-y',                       # Overwrite
            thumbnail_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            return True
        else:
            print(f"   ⚠️  ffmpeg error: {result.stderr}")
            return False
    except FileNotFoundError:
        print("   ⚠️  ffmpeg not found. Install with: brew install ffmpeg")
        return False
    except Exception as e:
        print(f"   ⚠️  Error generating thumbnail: {e}")
        return False


def prepare_demo_assets(demo_dir: str = "demo-assets"):
    """Main function to prepare demo assets"""
    print("🎬 GuardianGamer Demo Asset Preparation")
    print("=" * 70)
    
    # Create demo directory
    Path(demo_dir).mkdir(exist_ok=True)
    print(f"✅ Created directory: {demo_dir}/")
    
    # Load favorites
    print("\n📋 Loading favorites...")
    favorite_ids = load_favorites()
    if not favorite_ids:
        print("❌ No favorites found!")
        return 1
    print(f"✅ Loaded {len(favorite_ids)} favorite story IDs")
    
    # Load all stories
    print("\n📚 Loading video stories...")
    all_stories = load_video_stories()
    if not all_stories:
        print("❌ No stories found!")
        return 1
    print(f"✅ Loaded {len(all_stories)} video stories")
    
    # Find matching stories
    print("\n🔍 Matching favorites...")
    demo_stories = find_stories_by_ids(all_stories, favorite_ids)
    if not demo_stories:
        print("❌ No matching stories found!")
        return 1
    print(f"✅ Found {len(demo_stories)} matching stories")
    
    # Load resources config for bucket info
    try:
        with open('resources.json', 'r') as f:
            resources = json.load(f)
    except:
        print("❌ Could not load resources.json")
        return 1
    
    # Download videos and thumbnails
    print(f"\n📥 Downloading assets...")
    demo_metadata = []
    
    for idx, story in enumerate(demo_stories, 1):
        demo_id = f"demostory{idx:03d}"
        print(f"\n[{idx}/{len(demo_stories)}] Processing {demo_id}...")
        
        # Get S3 bucket and region
        stage = story.get('_stage', 'unknown')
        if stage not in resources['stages']:
            print(f"   ⚠️  Unknown stage: {stage}")
            continue
        
        stage_config = resources['stages'][stage]
        bucket = stage_config['s3_bucket']
        region = stage_config['region']
        
        # Download video
        video_key = story.get('_video_url', story.get('video_url', ''))
        if video_key and video_key != 'N/A':
            video_local = os.path.join(demo_dir, f"{demo_id}.mp4")
            print(f"   📹 Downloading video...")
            
            if download_from_s3(bucket, video_key, video_local, region):
                print(f"   ✅ Video saved: {demo_id}.mp4")
                story['_demo_video'] = f"{demo_id}.mp4"
                
                # Download or generate thumbnail
                thumbnail_key = story.get('thumbnail_url', '')
                thumbnail_local = os.path.join(demo_dir, f"{demo_id}.jpg")
                
                if thumbnail_key and thumbnail_key != 'N/A':
                    print(f"   🖼️  Downloading thumbnail...")
                    if download_from_s3(bucket, thumbnail_key, thumbnail_local, region):
                        print(f"   ✅ Thumbnail saved: {demo_id}.jpg")
                        story['_demo_thumbnail'] = f"{demo_id}.jpg"
                    else:
                        # Generate from video
                        print(f"   🔧 Generating thumbnail from video...")
                        if generate_thumbnail_from_video(video_local, thumbnail_local):
                            print(f"   ✅ Thumbnail generated: {demo_id}.jpg")
                            story['_demo_thumbnail'] = f"{demo_id}.jpg"
                else:
                    # No thumbnail exists, generate from video
                    print(f"   🔧 Generating thumbnail from video...")
                    if generate_thumbnail_from_video(video_local, thumbnail_local):
                        print(f"   ✅ Thumbnail generated: {demo_id}.jpg")
                        story['_demo_thumbnail'] = f"{demo_id}.jpg"
                
                # Add to metadata
                demo_metadata.append({
                    'demo_id': demo_id,
                    'original_story_id': story.get('_computed_story_id'),
                    'video_file': f"{demo_id}.mp4",
                    'thumbnail_file': f"{demo_id}.jpg",
                    'gamer': story.get('_gamer_extracted', 'N/A'),
                    'stage': stage,
                    'timestamp': story.get('_created', story.get('timestamp', 'N/A')),
                    'description': story.get('_description', story.get('description', '')),
                    'group': story.get('_group', story.get('group', '')),
                    'participants': story.get('_participants', []),
                    'gameserver': story.get('_gameserver', story.get('gameserver_id', '')),
                    'game_start': story.get('_game_start', story.get('game_start', '')),
                    'game_end': story.get('_game_end', story.get('game_end', '')),
                })
            else:
                print(f"   ❌ Failed to download video")
        else:
            print(f"   ⚠️  No video URL")
    
    # Save demo metadata
    metadata_file = os.path.join(demo_dir, "demo_stories.json")
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(demo_metadata, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'=' * 70}")
    print(f"✅ Demo preparation complete!")
    print(f"\n📊 Summary:")
    print(f"   Total stories: {len(demo_metadata)}")
    print(f"   Video files: {len([m for m in demo_metadata if m.get('video_file')])}")
    print(f"   Thumbnail files: {len([m for m in demo_metadata if m.get('thumbnail_file')])}")
    print(f"\n📂 Output:")
    print(f"   Directory: {demo_dir}/")
    print(f"   Metadata: {demo_dir}/demo_stories.json")
    print(f"   Videos: {demo_dir}/demostory001.mp4 ... demostory{len(demo_metadata):03d}.mp4")
    
    return 0


if __name__ == '__main__':
    exit(prepare_demo_assets())

