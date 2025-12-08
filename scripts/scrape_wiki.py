#!/usr/bin/env python3
"""
Scraper for the old PBworks gift wiki.
Extracts gift lists from the wiki pages and normalizes the data.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import time

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: Missing required packages. Install with:")
    print("  pip install requests beautifulsoup4")
    sys.exit(1)


BASE_URL = "http://wikichristmas.pbworks.com"
FRONTPAGE_URL = "http://wikichristmas.pbworks.com/w/page/14269056/FrontPage"


def clean_text(text):
    """Clean and normalize text."""
    if not text:
        return ""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    # Remove HTML entities
    text = text.replace('&nbsp;', ' ')
    return text


def is_navigation_text(text):
    """Check if text is likely navigation/metadata."""
    if not text or len(text) < 3:
        return True
    
    nav_keywords = [
        'log in', 'help', 'edit page', 'page history', 'printable version', 'rss feed', 'contact the owner',
        'request access', 'join this workspace', 'already have an account',
        'loading...', 'no images or files uploaded yet', 'insert a link to a new page', 'insert image from url',
        'tip: to turn text', 'navigator', 'sidebar', 'recent activity',
        'show 0 new items', 'pbworks', 'terms of use', 'privacy policy', 'gdpr',
        'about this workspace', 'gift wiki pages', 'pages & files',
        'you create your own page', 'this next step is very important',
        'lets say you want to get a gift', 'oh, no! you forgot',
        'to edit this page', 'wiki', 'gift wiki$'  # $ means end of string
    ]
    text_lower = text.lower().strip()
    # Only reject if it starts with or exactly matches navigation text
    return any(text_lower == keyword or text_lower.startswith(keyword) for keyword in nav_keywords)


def extract_list_items(soup):
    """
    Extract gift list items from a wiki page.
    Tries multiple strategies to find list items.
    """
    items = []
    
    # Remove navigation and footer elements
    for nav in soup.find_all(['nav', 'footer', 'header']):
        nav.decompose()
    
    # Remove elements with navigation classes
    for elem in soup.find_all(class_=re.compile(r'nav|footer|header|sidebar|toolbar', re.I)):
        elem.decompose()
    
    # Strategy 1: Look for strikethrough items (purchased items)
    # These are often marked with <s>, <strike>, or <del> tags
    for tag in soup.find_all(['s', 'strike', 'del']):
        text = clean_text(tag.get_text())
        if text and len(text) > 2 and not is_navigation_text(text):
            items.append({
                'name': text,
                'purchased': True,
                'raw_html': str(tag)
            })
    
    # Strategy 2: Look for list items (<li>, <ul>, <ol>)
    # This is often the most reliable method
    for ul in soup.find_all(['ul', 'ol']):
        # Skip navigation lists
        parent_classes = ' '.join(ul.get('class', []))
        if 'nav' in parent_classes.lower():
            continue
            
        for li in ul.find_all('li', recursive=False):
            text = clean_text(li.get_text())
            if text and len(text) > 2 and not is_navigation_text(text):
                # Check if it's strikethrough
                is_purchased = bool(li.find(['s', 'strike', 'del']))
                items.append({
                    'name': text,
                    'purchased': is_purchased,
                    'raw_html': str(li)
                })
    
    # Strategy 3: Look for paragraphs that might contain items
    # Often wiki pages have items as separate paragraphs
    for p in soup.find_all('p'):
        text = clean_text(p.get_text())
        # Skip if it's too short or looks like navigation/metadata
        if len(text) < 3 or is_navigation_text(text):
            continue
        # Check if it contains a colon (common pattern: "Item: description")
        # or if it's a reasonable length item
        if ((':' in text and len(text) > 10) or (len(text) > 5 and len(text) < 200)):
            is_purchased = bool(p.find(['s', 'strike', 'del']))
            items.append({
                'name': text,
                'purchased': is_purchased,
                'raw_html': str(p)
            })
    
    # Strategy 4: Look for paragraphs and divs in main content area
    # Try to find the main wiki content area
    main_content = soup.find('div', id=re.compile(r'content|main|wiki', re.I))
    if not main_content:
        # Try to find by class
        main_content = soup.find('div', class_=re.compile(r'content|main|wiki', re.I))
    if not main_content:
        # Fall back to body but skip known navigation areas
        main_content = soup.find('body')
    
    if main_content:
        # Remove known navigation sections
        for nav_section in main_content.find_all(['nav', 'header', 'footer']):
            nav_section.decompose()
        for nav_elem in main_content.find_all(class_=re.compile(r'nav|sidebar|toolbar|footer', re.I)):
            nav_elem.decompose()
        
        # Look for paragraphs
        for p in main_content.find_all('p', recursive=True):
            text = clean_text(p.get_text())
            if text and len(text) > 3 and len(text) < 500 and not is_navigation_text(text):
                is_purchased = bool(p.find(['s', 'strike', 'del']))
                items.append({
                    'name': text,
                    'purchased': is_purchased,
                    'raw_html': str(p)
                })
        
        # Look for divs that might be items (but not containers)
        for div in main_content.find_all('div', recursive=True):
            # Skip if it contains lists (it's a container)
            if div.find(['ul', 'ol']):
                continue
            text = clean_text(div.get_text())
            if text and len(text) > 3 and len(text) < 300 and not is_navigation_text(text):
                is_purchased = bool(div.find(['s', 'strike', 'del']))
                items.append({
                    'name': text,
                    'purchased': is_purchased,
                    'raw_html': str(div)
                })
    
    # Remove duplicates based on name (case-insensitive)
    seen = set()
    unique_items = []
    for item in items:
        name_lower = item['name'].lower().strip()
        if name_lower and name_lower not in seen and len(name_lower) > 2:
            seen.add(name_lower)
            unique_items.append(item)
    
    return unique_items


def normalize_item_name(item_text):
    """
    Normalize item names by extracting the main item name.
    Handles various formats like:
    - "Item name: description"
    - "Item name - description"
    - "Item name (notes)"
    """
    # Remove common prefixes/suffixes
    text = item_text.strip()
    
    # Split on colon (common pattern)
    if ':' in text:
        parts = text.split(':', 1)
        name = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""
        return name, description
    
    # Split on dash (if it looks like a separator, not a hyphenated word)
    if ' - ' in text:
        parts = text.split(' - ', 1)
        name = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""
        return name, description
    
    # Check for parenthetical notes
    if '(' in text and ')' in text:
        # Extract text before first parenthesis as name
        name = text.split('(')[0].strip()
        # Extract content in parentheses as description
        desc_match = re.search(r'\(([^)]+)\)', text)
        description = desc_match.group(1) if desc_match else ""
        return name, description
    
    # If no clear separator, use whole text as name
    return text, ""


def scrape_page(url):
    """Scrape a single wiki page and extract gift list data."""
    try:
        print(f"  Scraping: {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract page title
        title_elem = soup.find('h1') or soup.find('title')
        title = clean_text(title_elem.get_text()) if title_elem else "Untitled"
        
        # Find the main wiki content area
        main_content = soup.find('div', id='wikicontent')
        if not main_content:
            main_content = soup.find('div', class_=re.compile(r'wiki|content', re.I))
        if not main_content:
            main_content = soup
        
        # Remove navigation elements
        for nav in main_content.find_all(['nav', 'header', 'footer']):
            nav.decompose()
        for nav_elem in main_content.find_all(class_=re.compile(r'nav|sidebar|toolbar|footer|header', re.I)):
            nav_elem.decompose()
        
        # Extract items - prioritize lists in the main content
        raw_items = []
        
        # Strategy 1: Look for <ul> or <ol> lists in main content (most common format)
        for ul in main_content.find_all(['ul', 'ol']):
            # Skip navigation lists
            if ul.get('class') and any('nav' in str(c).lower() for c in ul.get('class')):
                continue
            
            for li in ul.find_all('li', recursive=False):
                text = clean_text(li.get_text())
                if text and len(text) > 2 and not is_navigation_text(text):
                    is_purchased = bool(li.find(['s', 'strike', 'del']))
                    raw_items.append({
                        'name': text,
                        'purchased': is_purchased,
                        'raw_html': str(li)
                    })
        
        # Strategy 2: Look for strikethrough items (purchased items)
        for tag in main_content.find_all(['s', 'strike', 'del']):
            text = clean_text(tag.get_text())
            if text and len(text) > 2 and not is_navigation_text(text):
                raw_items.append({
                    'name': text,
                    'purchased': True,
                    'raw_html': str(tag)
                })
        
        # Strategy 3: Look for paragraphs that might be items
        for p in main_content.find_all('p'):
            text = clean_text(p.get_text())
            if text and len(text) > 3 and len(text) < 500 and not is_navigation_text(text):
                # Skip if it looks like a comment or metadata
                if 'at ' in text and ('am on' in text or 'pm on' in text):
                    continue
                is_purchased = bool(p.find(['s', 'strike', 'del']))
                raw_items.append({
                    'name': text,
                    'purchased': is_purchased,
                    'raw_html': str(p)
                })
        
        # Remove duplicates
        seen = set()
        unique_items = []
        for item in raw_items:
            name_lower = item['name'].lower().strip()
            if name_lower and name_lower not in seen and len(name_lower) > 2:
                seen.add(name_lower)
                unique_items.append(item)
        
        # Normalize items
        normalized_items = []
        for item in unique_items:
            name, description = normalize_item_name(item['name'])
            normalized_items.append({
                'name': name,
                'description': description or item['name'],  # Use full text as description if no separate description
                'purchased': item['purchased'],
                'original_text': item['name']
            })
        
        return {
            'url': url,
            'title': title,
            'items': normalized_items,
            'item_count': len(normalized_items)
        }
        
    except requests.RequestException as e:
        print(f"  Error scraping {url}: {e}")
        return {
            'url': url,
            'title': None,
            'items': [],
            'item_count': 0,
            'error': str(e)
        }
    except Exception as e:
        print(f"  Unexpected error scraping {url}: {e}")
        return {
            'url': url,
            'title': None,
            'items': [],
            'item_count': 0,
            'error': str(e)
        }


def extract_page_links(soup, base_url):
    """Extract links to gift list pages from the front page."""
    links = []
    
    # Find the main content area - look for the "Gift Wiki Pages" section
    # PBworks typically uses specific divs or sections
    content_areas = soup.find_all(['div', 'section'], class_=re.compile(r'content|main|wiki', re.I))
    if not content_areas:
        content_areas = [soup]  # Use whole page if no specific content area
    
    # Also look for headings that might indicate the gift list section
    gift_section = None
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
        if 'gift wiki pages' in heading.get_text().lower():
            # Find the next sibling or parent container
            gift_section = heading.find_next(['div', 'ul', 'ol', 'section'])
            if gift_section:
                break
    
    if gift_section:
        content_areas = [gift_section]
    
    for area in content_areas:
        # Look for links that might be gift list pages
        for link in area.find_all('a', href=True):
            href = link.get('href')
            if not href:
                continue
            
            # Convert relative URLs to absolute
            full_url = urljoin(base_url, href)
            
            # Filter for wiki pages (not external links, not navigation)
            parsed = urlparse(full_url)
            if parsed.netloc and 'pbworks.com' not in parsed.netloc:
                continue  # Skip external links
            
            # Look for links that contain page names (often in the link text)
            link_text = clean_text(link.get_text())
            
            # Skip navigation/utility links
            skip_texts = ['log in', 'help', 'edit', 'page history', 'printable', 'rss', 'contact',
                          'request access', 'wiki', 'pages & files', 'browse']
            if any(skip in link_text.lower() for skip in skip_texts):
                continue
            
            # Skip if it's clearly not a gift list page
            if not link_text or len(link_text) < 2:
                continue
            
            # Check if URL looks like a wiki page (but not the front page or browse)
            # Accept both new format (/w/page/) and old format (direct page names)
            is_wiki_page = (
                ('/w/page/' in full_url or 
                 (parsed.path and parsed.path != '/' and 
                  not parsed.path.startswith('/w/') and 
                  parsed.path not in ['/browse', '/FrontPage', '/request_access.php'] and
                  '?' not in parsed.path))  # Old-style PBworks URLs
            ) and '/FrontPage' not in full_url and '/browse' not in full_url
            
            if is_wiki_page:
                links.append({
                    'url': full_url,
                    'text': link_text,
                    'name': link_text  # Use link text as potential name
                })
    
    # Remove duplicates (normalize URLs to handle encoding differences)
    seen_urls = set()
    unique_links = []
    for link in links:
        # Normalize URL by unquoting and re-quoting to handle encoding differences
        normalized_url = unquote(link['url']).lower()
        if normalized_url not in seen_urls:
            seen_urls.add(normalized_url)
            unique_links.append(link)
    
    return unique_links


def scrape_frontpage():
    """Scrape the front page to get all gift list page links."""
    print(f"Scraping front page: {FRONTPAGE_URL}")
    try:
        response = requests.get(FRONTPAGE_URL, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract page links
        links = extract_page_links(soup, BASE_URL)
        
        # Add known pages that might be missed (including old-style URLs)
        known_pages = [
            {'url': 'http://wikichristmas.pbworks.com/w/page/14269060/Gabe', 'text': 'Gabe', 'name': 'Gabe'},
            {'url': 'http://wikichristmas.pbworks.com/w/page/137156280/Arlo', 'text': 'Arlo', 'name': 'Arlo'},
            {'url': 'http://wikichristmas.pbworks.com/w/page/123317856/Luna%20Mae\'s%20Lavish%20List', 'text': 'Luna Mae\'s Lavish List', 'name': 'Luna Mae'},
            {'url': 'http://wikichristmas.pbworks.com/w/page/14269093/John', 'text': 'John', 'name': 'John'},
            # Old-style PBworks URLs (without /w/page/)
            {'url': 'http://wikichristmas.pbworks.com/Goodies+for+Gladys', 'text': 'Goodies for Glady', 'name': 'Glady'},
            {'url': 'http://wikichristmas.pbworks.com/Jack%27s-List', 'text': 'Jack\'s List', 'name': 'Jack'},
            {'url': 'http://wikichristmas.pbworks.com/Jim', 'text': 'Jim', 'name': 'Jim'},
            {'url': 'http://wikichristmas.pbworks.com/Joseph', 'text': 'Joseph\'s Just-So Gifts', 'name': 'Joseph'},
            {'url': 'http://wikichristmas.pbworks.com/Skippy%27s', 'text': 'Skippy\'s', 'name': 'Skippy'},
            {'url': 'http://wikichristmas.pbworks.com/Alternative-gifts', 'text': 'Alternative gifts', 'name': 'Alternative gifts'},
            {'url': 'http://wikichristmas.pbworks.com/Rachel-Ellison', 'text': 'Rachel\'s Request Box', 'name': 'Rachel'},
        ]
        
        # Add known pages if not already in links (normalize URLs for comparison)
        existing_urls = {unquote(link['url']).lower() for link in links}
        for page in known_pages:
            normalized_known = unquote(page['url']).lower()
            if normalized_known not in existing_urls:
                links.append(page)
        
        print(f"Found {len(links)} potential gift list pages")
        return links
        
    except Exception as e:
        print(f"Error scraping front page: {e}")
        return []


def main():
    """Main scraping function."""
    print("Starting wiki scraper...")
    print("=" * 60)
    
    # Scrape front page for links
    links = scrape_frontpage()
    
    if not links:
        print("No links found on front page. Exiting.")
        return
    
    # Scrape each page
    all_data = {
        'source_url': FRONTPAGE_URL,
        'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'pages': []
    }
    
    print(f"\nScraping {len(links)} pages...")
    print("=" * 60)
    
    for i, link in enumerate(links, 1):
        print(f"\n[{i}/{len(links)}] {link['text']}")
        page_data = scrape_page(link['url'])
        page_data['link_text'] = link['text']
        all_data['pages'].append(page_data)
        
        # Be polite - small delay between requests
        time.sleep(0.5)
    
    # Save results
    output_file = Path(__file__).parent.parent / 'scraped_wiki_data.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    
    # Print summary
    print("\n" + "=" * 60)
    print("Scraping complete!")
    print(f"Total pages scraped: {len(all_data['pages'])}")
    total_items = sum(page['item_count'] for page in all_data['pages'])
    print(f"Total items found: {total_items}")
    print(f"Data saved to: {output_file}")
    
    # Print pages with most items
    print("\nTop pages by item count:")
    sorted_pages = sorted(all_data['pages'], key=lambda x: x['item_count'], reverse=True)
    for page in sorted_pages[:10]:
        if page['item_count'] > 0:
            print(f"  {page.get('title', page.get('link_text', 'Unknown'))}: {page['item_count']} items")


if __name__ == '__main__':
    main()

