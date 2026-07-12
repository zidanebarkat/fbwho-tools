#!/usr/bin/env python3
"""Generate terminal screenshot images from fbwho output"""
from PIL import Image, ImageDraw, ImageFont
import os

def create_screenshot(text, output_path, width=800, font_size=14):
    lines = text.strip().split('\n')
    line_height = font_size + 4
    height = len(lines) * line_height + 40

    img = Image.new('RGB', (width, height), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", font_size)
    except:
        font = ImageFont.load_default()

    y = 20
    for line in lines:
        draw.text((20, y), line, fill=(0, 255, 0), font=font)
        y += line_height

    img.save(output_path)
    print(f"Created: {output_path}")

# Step 1: Help
help_text = """  ███████╗██████╗ ██╗    ██╗██╗  ██╗ ██████╗
  ██╔════╝██╔══██╗██║    ██║██║  ██║██╔═══██╗
  █████╗  ██████╔╝██║ █╗ ██║███████║██║   ██║
  ██╔══╝  ██╔══██╗██║███╗██║██╔══██║██║   ██║
  ██║     ██████╔╝╚███╔███╔╝██║  ██║╚██████╔╝
  ╚═╝     ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═╝ ╚═════╝

  Usage:
    fbwho <post-url>    - Look up by post URL
    fbwho <post-id>     - Look up by post ID
    fbwho --user <id>   - Look up by user ID
    fbwho -u <id>       - Short form
    fbwho --name <username> - Look up by username
    fbwho -n <username>     - Short form
    fbwho -g <group> -f <target> - Find user in group
    fbwho --group <id> --find <id|username>

  Auth:
    FB_ACCESS_TOKEN=<token>          Graph API token
    FB_COOKIES=/path/to/cookies.json  Saved cookies
    FB_EMAIL=<email> FB_PASSWORD=<pass> Login (auto-saves to ~/.fbwho_cookies.json)

  Examples:
    fbwho https://www.facebook.com/zuck/posts/1011234567890
    fbwho 1011234567890
    fbwho --user 4
    fbwho -u 848294561045355
    fbwho --name zuck
    fbwho -g 707350140975831 -f 4469200603347892"""

# Step 2: User lookup
user_text = """  ✓ User found!

  👤 Name:      Mark Zuckerberg
  🆔 User ID:   4
  🖼 Profile Pic: https://graph.facebook.com/4/picture?type=large"""

# Step 3: Username lookup
name_text = """  ✓ User found!

  👤 Name:      Mark Zuckerberg
  🔗 Username:  zuck
  🆔 User ID:   4
  🖼 Profile Pic: https://graph.facebook.com/4/picture?type=large

      ▄▄▄▄▄▄▄▄▄▄▄▄
    ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
  ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
 ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
▀▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▀
 ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
  ▀▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▀
    ▀▄▄▄▄▄▄▄▄▄▄▄▄▄▄▀
      ▀▀▀▄▄▄▄▄▄▀▀▀"""

# Step 4: Post lookup
post_text = """  🔍 Looking up post...
  ↳ URL: https://www.facebook.com/zuck/posts/1011234567890
  ↳ Fetching page (direct)...
  ↳ Page fetched
  ↳ Poster ID: 1011234567890

  ✓ Post found!

  👤 Poster:   Mark Zuckerberg
  🔗 Username:  zuck
  🆔 Post ID:  1011234567890
  🔗 URL:      https://www.facebook.com/zuck/posts/1011234567890"""

# Step 5: Auth setup
auth_text = """  # Option A: Access Token (Recommended)
  export FB_ACCESS_TOKEN=your_token_here
  ./fbwho --user 4

  # Option B: Cookies
  export FB_COOKIES=/path/to/cookies.json
  ./fbwho --user 4

  # Option C: Auto-Login
  export FB_EMAIL=your@email.com
  export FB_PASSWORD=your_password
  ./fbwho --user 4"""

# Step 6: Group find
group_text = """  🔍 Searching group 707350140975831 for 4469200603347892...

  ✓ Target found in group!

  👤 Name:      John Doe
  🆔 User ID:   4469200603347892
  👥 Group ID:  707350140975833"""

screenshots = [
    ("step1_help.png", help_text),
    ("step2_user.png", user_text),
    ("step3_name.png", name_text),
    ("step4_post.png", post_text),
    ("step5_auth.png", auth_text),
    ("step6_group.png", group_text),
]

for filename, text in screenshots:
    create_screenshot(text, f"screenshots/{filename}")
