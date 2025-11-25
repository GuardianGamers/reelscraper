#!/usr/bin/env python3
"""
Scrape all video stories from multiple GuardianGamer stages across AWS regions.

This script:
1. Reads resource configuration from resources.json
2. Connects to each DynamoDB events table in each stage
3. Scans for all items with SK starting with "V#" (video stories)
4. Collects metadata and saves to a comprehensive output file
5. Generates a browsable HTML report

Usage:
    python3 scrape_video_stories.py [--stages dev test dev-old test-old prod-old] [--output video_stories.json]
    python3 scrape_video_stories.py --stage dev-old  # Scrape a single stage
    python3 scrape_video_stories.py --format html    # Generate HTML report
"""

import boto3
import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict


class DecimalEncoder(json.JSONEncoder):
    """Helper to convert Decimal types to int/float for JSON serialization"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super(DecimalEncoder, self).default(obj)


def load_resources_config(config_path: str = "resources.json") -> Dict[str, Any]:
    """
    Load the resources configuration file
    
    Args:
        config_path: Path to resources.json
        
    Returns:
        dict: Configuration with all stage resources
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        print(f"✅ Loaded resources configuration from {config_path}")
        return config
    except FileNotFoundError:
        print(f"❌ Configuration file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in configuration file: {e}")
        sys.exit(1)


def scan_video_stories_from_stage(stage_name: str, table_name: str, region: str) -> List[Dict[str, Any]]:
    """
    Scan DynamoDB table for all items with SK starting with "V#"
    
    Args:
        stage_name: Name of the stage (for logging)
        table_name: DynamoDB table name
        region: AWS region
        
    Returns:
        list: List of video story items
    """
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    print(f"\n🔍 Scanning stage: {stage_name}")
    print(f"   Table: {table_name}")
    print(f"   Region: {region}")
    print(f"   Looking for items with SK starting with 'V#'...")
    
    video_stories = []
    
    # Scan with filter expression
    scan_kwargs = {
        'FilterExpression': 'begins_with(SK, :sk_prefix)',
        'ExpressionAttributeValues': {
            ':sk_prefix': 'V#'
        }
    }
    
    try:
        items_scanned = 0
        # Handle pagination
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            video_stories.extend(items)
            items_scanned += response.get('ScannedCount', 0)
            
            print(f"   Scanned {items_scanned} items, found {len(video_stories)} video stories so far...")
            
            # Check if there are more items to scan
            if 'LastEvaluatedKey' not in response:
                break
            
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        print(f"✅ Stage {stage_name}: Found {len(video_stories)} video stories")
        
        # Add stage metadata to each video story
        for story in video_stories:
            story['_stage'] = stage_name
            story['_region'] = region
            story['_table'] = table_name
        
        return video_stories
        
    except Exception as e:
        print(f"❌ Error scanning table {table_name}: {e}")
        return []


def enrich_video_stories(stories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Enrich video stories with computed fields for easier browsing
    
    Args:
        stories: List of raw video story items
        
    Returns:
        list: Enriched video stories
    """
    enriched = []
    
    for story in stories:
        enriched_story = dict(story)
        
        # Extract key fields
        pk = story.get('PK', 'N/A')
        sk = story.get('SK', 'N/A')
        
        # Parse SK to extract timestamp and gamer
        # Format: V#<timestamp>#<gamer_id>
        if sk.startswith('V#'):
            parts = sk.split('#')
            if len(parts) >= 3:
                enriched_story['_timestamp_extracted'] = parts[1]
                enriched_story['_gamer_extracted'] = '#'.join(parts[2:])
        
        # Parse created/timestamp
        created = story.get('timestamp', story.get('created_at', 'N/A'))
        enriched_story['_created'] = created
        
        # Extract video info
        video_url = story.get('video_url', story.get('video_key', story.get('s3_key', 'N/A')))
        enriched_story['_video_url'] = video_url
        
        # Status and metadata
        enriched_story['_viewed'] = story.get('viewed', 'False') == 'True'
        enriched_story['_description'] = story.get('description', '')
        enriched_story['_group'] = story.get('group', story.get('GSI1PK', 'N/A'))
        
        # Participants
        participants_str = story.get('participants', '[]')
        try:
            if isinstance(participants_str, str):
                enriched_story['_participants'] = json.loads(participants_str)
            else:
                enriched_story['_participants'] = participants_str
        except:
            enriched_story['_participants'] = []
        
        # Game metadata
        if 'gameserver_id' in story:
            enriched_story['_gameserver'] = story['gameserver_id']
        if 'game_start' in story:
            enriched_story['_game_start'] = story['game_start']
        if 'game_end' in story:
            enriched_story['_game_end'] = story['game_end']
        
        enriched.append(enriched_story)
    
    return enriched


def generate_summary_stats(stories: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate summary statistics for video stories
    
    Args:
        stories: List of video stories
        
    Returns:
        dict: Summary statistics
    """
    stats = {
        'total_stories': len(stories),
        'by_stage': defaultdict(int),
        'by_region': defaultdict(int),
        'unique_parents': set(),
        'unique_gamers': set(),
        'unique_groups': set(),
        'viewed_count': 0,
        'unviewed_count': 0,
        'with_description': 0,
        'with_gameserver': 0,
    }
    
    for story in stories:
        # Count by stage and region
        stage = story.get('_stage', 'unknown')
        region = story.get('_region', 'unknown')
        stats['by_stage'][stage] += 1
        stats['by_region'][region] += 1
        
        # Unique entities
        pk = story.get('PK', '')
        if pk:
            stats['unique_parents'].add(pk)
        
        gamer = story.get('GSI1PK', story.get('_gamer_extracted', ''))
        if gamer:
            stats['unique_gamers'].add(gamer)
        
        group = story.get('group', '')
        if group:
            stats['unique_groups'].add(group)
        
        # Counts
        if story.get('_viewed', False):
            stats['viewed_count'] += 1
        else:
            stats['unviewed_count'] += 1
        
        if story.get('_description'):
            stats['with_description'] += 1
        
        if story.get('_gameserver'):
            stats['with_gameserver'] += 1
    
    # Convert sets to counts
    stats['unique_parents'] = len(stats['unique_parents'])
    stats['unique_gamers'] = len(stats['unique_gamers'])
    stats['unique_groups'] = len(stats['unique_groups'])
    stats['by_stage'] = dict(stats['by_stage'])
    stats['by_region'] = dict(stats['by_region'])
    
    return stats


def save_to_json(stories: List[Dict[str, Any]], output_file: str):
    """
    Save video stories to JSON file
    
    Args:
        stories: List of video stories
        output_file: Output file path
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(stories, f, indent=2, cls=DecimalEncoder, ensure_ascii=False)
        print(f"\n💾 Saved {len(stories)} video stories to: {output_file}")
    except Exception as e:
        print(f"\n❌ Error saving to file: {e}")


def generate_html_report(stories: List[Dict[str, Any]], stats: Dict[str, Any], output_file: str):
    """
    Generate an HTML report for browsing video stories
    
    Args:
        stories: List of video stories
        stats: Summary statistics
        output_file: Output HTML file path
    """
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GuardianGamer Video Stories Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
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
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .filters input, .filters select {{
            padding: 8px;
            margin: 5px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }}
        .story-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .story-card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}
        .story-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        .story-header {{
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
            margin-bottom: 10px;
        }}
        .story-title {{
            font-weight: bold;
            color: #333;
            font-size: 16px;
        }}
        .story-meta {{
            font-size: 12px;
            color: #999;
            margin-top: 5px;
        }}
        .story-description {{
            margin: 15px 0;
            color: #666;
            line-height: 1.5;
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
        .tag.viewed {{
            background: #e8f5e9;
            color: #388e3c;
        }}
        .tag.unviewed {{
            background: #fff3e0;
            color: #f57c00;
        }}
        .video-link {{
            display: inline-block;
            margin-top: 10px;
            padding: 8px 16px;
            background: #4CAF50;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 14px;
        }}
        .video-link:hover {{
            background: #45a049;
        }}
    </style>
</head>
<body>
    <h1>🎮 GuardianGamer Video Stories Report</h1>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <div class="stats">
        <div class="stat-card">
            <h3>Total Stories</h3>
            <div class="value">{stats['total_stories']}</div>
        </div>
        <div class="stat-card">
            <h3>Unique Parents</h3>
            <div class="value">{stats['unique_parents']}</div>
        </div>
        <div class="stat-card">
            <h3>Unique Gamers</h3>
            <div class="value">{stats['unique_gamers']}</div>
        </div>
        <div class="stat-card">
            <h3>Unique Groups</h3>
            <div class="value">{stats['unique_groups']}</div>
        </div>
        <div class="stat-card">
            <h3>Viewed</h3>
            <div class="value">{stats['viewed_count']}</div>
        </div>
        <div class="stat-card">
            <h3>Unviewed</h3>
            <div class="value">{stats['unviewed_count']}</div>
        </div>
    </div>
    
    <h2>By Stage</h2>
    <div class="stats">
"""
    
    for stage, count in stats['by_stage'].items():
        html += f"""
        <div class="stat-card">
            <h3>{stage}</h3>
            <div class="value">{count}</div>
        </div>
"""
    
    html += """
    </div>
    
    <div class="filters">
        <h3>Filters</h3>
        <input type="text" id="searchInput" placeholder="Search..." onkeyup="filterStories()">
        <select id="stageFilter" onchange="filterStories()">
            <option value="">All Stages</option>
"""
    
    for stage in stats['by_stage'].keys():
        html += f'            <option value="{stage}">{stage}</option>\n'
    
    html += """
        </select>
        <select id="viewedFilter" onchange="filterStories()">
            <option value="">All</option>
            <option value="viewed">Viewed</option>
            <option value="unviewed">Unviewed</option>
        </select>
    </div>
    
    <h2>Video Stories</h2>
    <div class="story-grid" id="storyGrid">
"""
    
    for story in stories:
        pk = story.get('PK', 'N/A')
        sk = story.get('SK', 'N/A')
        stage = story.get('_stage', 'unknown')
        region = story.get('_region', 'unknown')
        video_url = story.get('_video_url', '#')
        description = story.get('_description', 'No description')
        timestamp = story.get('_created', 'N/A')
        viewed = story.get('_viewed', False)
        gamer = story.get('_gamer_extracted', 'N/A')
        group = story.get('_group', 'N/A')
        participants = story.get('_participants', [])
        
        viewed_tag = 'viewed' if viewed else 'unviewed'
        viewed_text = '✓ Viewed' if viewed else '○ Unviewed'
        
        # Truncate description if too long
        display_desc = description if len(description) <= 200 else description[:197] + '...'
        
        html += f"""
        <div class="story-card" data-stage="{stage}" data-viewed="{viewed_tag}" data-search="{pk.lower()} {gamer.lower()} {description.lower()} {group.lower()}">
            <div class="story-header">
                <div class="story-title">{gamer}</div>
                <div class="story-meta">{timestamp}</div>
            </div>
            <div class="story-description">{display_desc}</div>
            <div class="story-tags">
                <span class="tag stage">{stage}</span>
                <span class="tag">{region}</span>
                <span class="tag {viewed_tag}">{viewed_text}</span>
                <span class="tag">Group: {group[:20]}...</span>
            </div>
            <a href="{video_url}" class="video-link" target="_blank">View Video</a>
        </div>
"""
    
    html += """
    </div>
    
    <script>
        function filterStories() {
            const searchInput = document.getElementById('searchInput').value.toLowerCase();
            const stageFilter = document.getElementById('stageFilter').value;
            const viewedFilter = document.getElementById('viewedFilter').value;
            const cards = document.querySelectorAll('.story-card');
            
            let visibleCount = 0;
            
            cards.forEach(card => {
                const searchText = card.getAttribute('data-search');
                const stage = card.getAttribute('data-stage');
                const viewed = card.getAttribute('data-viewed');
                
                const matchesSearch = searchText.includes(searchInput);
                const matchesStage = !stageFilter || stage === stageFilter;
                const matchesViewed = !viewedFilter || viewed === viewedFilter;
                
                if (matchesSearch && matchesStage && matchesViewed) {
                    card.style.display = 'block';
                    visibleCount++;
                } else {
                    card.style.display = 'none';
                }
            });
            
            console.log(`Showing ${visibleCount} of ${cards.length} stories`);
        }
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
        description='Scrape video stories from multiple GuardianGamer stages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scrape_video_stories.py
  python3 scrape_video_stories.py --stages dev test
  python3 scrape_video_stories.py --stage dev-old
  python3 scrape_video_stories.py --output my_stories.json --format html
  python3 scrape_video_stories.py --format json  # JSON output only
        """
    )
    
    parser.add_argument(
        '--stages',
        nargs='+',
        help='List of stages to scrape (space-separated). If not provided, scrapes all stages.'
    )
    
    parser.add_argument(
        '--stage',
        help='Single stage to scrape (alternative to --stages)'
    )
    
    parser.add_argument(
        '--config',
        default='resources.json',
        help='Path to resources configuration file (default: resources.json)'
    )
    
    parser.add_argument(
        '--output',
        '-o',
        default='all_video_stories.json',
        help='Output JSON file path (default: all_video_stories.json)'
    )
    
    parser.add_argument(
        '--format',
        choices=['json', 'html', 'both'],
        default='both',
        help='Output format (default: both)'
    )
    
    args = parser.parse_args()
    
    print("🚀 GuardianGamer Video Stories Scraper")
    print("=" * 60)
    
    # Load configuration
    config = load_resources_config(args.config)
    
    # Determine which stages to scrape
    if args.stage:
        stages_to_scrape = [args.stage]
    elif args.stages:
        stages_to_scrape = args.stages
    else:
        stages_to_scrape = list(config['stages'].keys())
    
    print(f"\n📋 Stages to scrape: {', '.join(stages_to_scrape)}")
    
    # Scrape all stages
    all_stories = []
    
    for stage_name in stages_to_scrape:
        if stage_name not in config['stages']:
            print(f"⚠️  Stage '{stage_name}' not found in configuration, skipping...")
            continue
        
        stage_config = config['stages'][stage_name]
        table_name = stage_config['dynamodb_table']
        region = stage_config['region']
        
        stories = scan_video_stories_from_stage(stage_name, table_name, region)
        all_stories.extend(stories)
    
    print(f"\n{'=' * 60}")
    print(f"✅ Total video stories collected: {len(all_stories)}")
    
    # Enrich stories
    print("\n🔧 Enriching video stories with metadata...")
    enriched_stories = enrich_video_stories(all_stories)
    
    # Generate statistics
    print("📊 Generating statistics...")
    stats = generate_summary_stats(enriched_stories)
    
    print("\n📈 Summary Statistics:")
    print(f"   Total stories: {stats['total_stories']}")
    print(f"   Unique parents: {stats['unique_parents']}")
    print(f"   Unique gamers: {stats['unique_gamers']}")
    print(f"   Unique groups: {stats['unique_groups']}")
    print(f"   Viewed: {stats['viewed_count']}")
    print(f"   Unviewed: {stats['unviewed_count']}")
    print(f"\n   By stage:")
    for stage, count in stats['by_stage'].items():
        print(f"     - {stage}: {count}")
    
    # Save outputs
    if args.format in ['json', 'both']:
        save_to_json(enriched_stories, args.output)
    
    if args.format in ['html', 'both']:
        html_output = args.output.replace('.json', '.html')
        generate_html_report(enriched_stories, stats, html_output)
    
    print(f"\n{'=' * 60}")
    print("✅ Video story scraping complete!")
    
    return 0


if __name__ == '__main__':
    exit(main())

