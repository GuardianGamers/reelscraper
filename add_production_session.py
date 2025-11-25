#!/usr/bin/env python3
"""
Add production session reels for a specific gamer from yesterday
"""
import json
import os
import subprocess
import boto3
from datetime import datetime, timedelta
from pathlib import Path


def get_production_stories(gamer_id, date_str):
    """Fetch stories from production for a specific gamer and date"""
    print(f"🔍 Fetching production stories for {gamer_id} from {date_str}...")
    
    # Use AWS_PROFILE=prod for production access
    env = os.environ.copy()
    env['AWS_PROFILE'] = 'prod'
    
    # Load resources to get production bucket info
    with open('resources.json', 'r') as f:
        resources = json.load(f)
    
    if 'prod' not in resources.get('stages', {}):
        print("❌ Production stage not found in resources.json")
        return []
    
    stage_config = resources['stages']['prod']
    table_name = stage_config.get('dynamodb_table', 'GGEventsTable-prod')
    region = stage_config.get('region', 'us-east-1')
    
    print(f"   Table: {table_name}")
    print(f"   Region: {region}")
    
    # Query DynamoDB for this gamer's stories from yesterday
    # The PK is the parent ID, GSI1PK is the gamer ID
    dynamodb = boto3.client('dynamodb', region_name=region)
    
    # Format gamer ID for query
    gsi1pk = gamer_id if gamer_id.startswith('G#') else f'G#{gamer_id}'
    
    try:
        # Query using GSI1 (gamer index)
        # GSI1SK format is V#{timestamp}
        date_start = f"V#{date_str}T00:00:00.000Z"
        date_end = f"V#{date_str}T23:59:59.999Z"
        
        print(f"   Querying GSI1 for {gsi1pk} between {date_start} and {date_end}...")
        
        response = dynamodb.query(
            TableName=table_name,
            IndexName='GSI1',
            KeyConditionExpression='GSI1PK = :gamer AND GSI1SK BETWEEN :start AND :end',
            ExpressionAttributeValues={
                ':gamer': {'S': gsi1pk},
                ':start': {'S': date_start},
                ':end': {'S': date_end}
            }
        )
        
        items = response.get('Items', [])
        print(f"✅ Found {len(items)} items")
        
        # Convert DynamoDB items to regular dict
        stories = []
        for item in items:
            story = {}
            for key, value in item.items():
                # Extract value from DynamoDB format
                if 'S' in value:
                    story[key] = value['S']
                elif 'N' in value:
                    story[key] = value['N']
                elif 'BOOL' in value:
                    story[key] = value['BOOL']
                elif 'L' in value:
                    story[key] = [v.get('S', '') for v in value['L']]
            
            # Only include video stories
            if story.get('type') == 'VideoStory':
                stories.append(story)
        
        print(f"✅ Found {len(stories)} video stories")
        return stories
        
    except Exception as e:
        print(f"❌ Error querying DynamoDB: {e}")
        return []


def group_into_sessions(stories):
    """Group stories into sessions based on session_start/session_end or time proximity"""
    from collections import defaultdict
    
    # Group by session
    sessions = defaultdict(list)
    
    for story in stories:
        session_start = story.get('session_start', '')
        session_end = story.get('session_end', '')
        
        if session_start and session_end:
            session_key = (session_start, session_end)
        else:
            # Use timestamp as session key
            timestamp = story.get('timestamp', '')
            session_key = (timestamp, timestamp)
        
        sessions[session_key].append(story)
    
    return sessions


def format_story_for_demo(story, demo_id):
    """Format a production story for demo_stories.json"""
    # Extract key fields
    gamer = story.get('GSI1PK', story.get('_gamer_extracted', ''))
    timestamp = story.get('timestamp', '')
    
    # Create story ID
    gamer_formatted = gamer.replace('G#', 'G_')
    story_id = f"prod_{gamer_formatted}_{timestamp.replace(':', '_').replace('.', '_')}"
    
    return {
        'demo_id': demo_id,
        'original_story_id': story_id,
        'video_file': f"{demo_id}.mp4",
        'thumbnail_file': f"{demo_id}.jpg",
        'gamer': gamer,
        'stage': 'prod',
        'timestamp': timestamp,
        'description': story.get('description', ''),
        'group': story.get('group', ''),
        'participants': story.get('participants', []) if isinstance(story.get('participants'), list) else [gamer],
        'gameserver': story.get('gameserver_id', ''),
        'game_start': story.get('game_start', ''),
        'game_end': story.get('game_end', '')
    }


def download_story_assets(story, demo_id, demo_dir='demo-assets'):
    """Download video and thumbnail for a story"""
    print(f"\n📥 Downloading assets for {demo_id}...")
    
    # Load resources
    with open('resources.json', 'r') as f:
        resources = json.load(f)
    
    stage_config = resources['stages']['prod']
    bucket = stage_config['s3_bucket']
    region = stage_config['region']
    
    # Use production AWS profile
    session = boto3.Session(profile_name='prod')
    s3 = session.client('s3', region_name=region)
    
    # Download video
    video_key = story.get('video_url', '')
    video_local = os.path.join(demo_dir, f"{demo_id}.mp4")
    
    if video_key:
        try:
            print(f"   📹 Downloading video from s3://{bucket}/{video_key}")
            s3.download_file(bucket, video_key, video_local)
            print(f"   ✅ Video saved: {demo_id}.mp4")
        except Exception as e:
            print(f"   ❌ Failed to download video: {e}")
            return False
    
    # Download or generate thumbnail
    thumbnail_key = story.get('thumbnail_url', '')
    thumbnail_local = os.path.join(demo_dir, f"{demo_id}.jpg")
    
    if thumbnail_key:
        try:
            print(f"   🖼️  Downloading thumbnail from s3://{bucket}/{thumbnail_key}")
            s3.download_file(bucket, thumbnail_key, thumbnail_local)
            print(f"   ✅ Thumbnail saved: {demo_id}.jpg")
            return True
        except Exception as e:
            print(f"   ⚠️  Failed to download thumbnail: {e}")
    
    # Generate thumbnail from video
    if os.path.exists(video_local):
        print(f"   🔧 Generating thumbnail from video...")
        try:
            cmd = [
                'ffmpeg',
                '-i', video_local,
                '-vframes', '1',
                '-vf', 'scale=600:400:force_original_aspect_ratio=increase,crop=600:400',
                '-q:v', '2',
                '-f', 'image2',
                '-y',
                thumbnail_local
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"   ✅ Thumbnail generated: {demo_id}.jpg")
                return True
            else:
                print(f"   ❌ Failed to generate thumbnail")
                return False
        except Exception as e:
            print(f"   ❌ Error generating thumbnail: {e}")
            return False
    
    return False


def main():
    print("🎬 Add Production Session to Demo")
    print("=" * 70)
    
    # Configuration
    gamer_id = "G#45831fea-23d9-4bba-8638-df82680f97cc"
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"\n📋 Configuration:")
    print(f"   Gamer: {gamer_id}")
    print(f"   Date: {yesterday}")
    
    # Fetch production stories
    stories = get_production_stories(gamer_id, yesterday)
    
    if not stories:
        print("\n❌ No stories found!")
        return 1
    
    # Group into sessions
    sessions = group_into_sessions(stories)
    print(f"\n📊 Found {len(sessions)} session(s)")
    
    for i, (session_key, session_stories) in enumerate(sessions.items(), 1):
        print(f"\n   Session {i}: {len(session_stories)} stories")
        print(f"      Start: {session_key[0]}")
        print(f"      End: {session_key[1]}")
    
    # Load current demo stories
    print(f"\n📖 Loading current demo_stories.json...")
    with open('demo_stories.json', 'r') as f:
        demo_stories = json.load(f)
    
    current_count = len(demo_stories)
    print(f"   Current stories: {current_count}")
    
    # Find next demo ID
    max_num = max(int(s['demo_id'].replace('demostory', '')) for s in demo_stories)
    next_num = max_num + 1
    
    print(f"   Next demo ID: demostory{next_num:03d}")
    
    # Add new stories
    new_stories = []
    demo_num = next_num
    
    for story in stories:
        demo_id = f"demostory{demo_num:03d}"
        demo_story = format_story_for_demo(story, demo_id)
        new_stories.append(demo_story)
        demo_stories.append(demo_story)
        print(f"   Added: {demo_id}")
        demo_num += 1
    
    # Save updated demo_stories.json
    print(f"\n💾 Saving updated demo_stories.json...")
    with open('demo_stories.json', 'w') as f:
        json.dump(demo_stories, f, indent=2)
    
    print(f"✅ Added {len(new_stories)} new stories")
    print(f"   Total stories: {len(demo_stories)}")
    
    # Download assets
    print(f"\n📥 Downloading assets...")
    Path('demo-assets').mkdir(exist_ok=True)
    
    success_count = 0
    for story, demo_story in zip(stories, new_stories):
        if download_story_assets(story, demo_story['demo_id']):
            success_count += 1
    
    print(f"\n{'=' * 70}")
    print(f"✅ Complete!")
    print(f"\n📊 Summary:")
    print(f"   Stories added: {len(new_stories)}")
    print(f"   Assets downloaded: {success_count}/{len(new_stories)}")
    print(f"   Total demo stories: {len(demo_stories)}")
    
    return 0


if __name__ == '__main__':
    exit(main())

