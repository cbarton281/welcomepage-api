from PIL import Image
import os

def convert_webp_to_gif(webp_path, gif_path):
    """Convert animated WebP to GIF using Pillow"""
    try:
        with Image.open(webp_path) as im:
            # Remove background info if present
            im.info.pop('background', None)
            
            # Save as GIF with optimization
            im.save(gif_path, 'GIF', save_all=True, optimize=True)
            print(f"✅ Successfully converted {webp_path} to {gif_path}")
    except Exception as e:
        print(f"❌ Error converting {webp_path}: {e}")

# Batch conversion with incremental numbering
webp_files = [f for f in os.listdir('.') if f.endswith('.webp')]
webp_files.sort()  # Sort for consistent ordering

# Find the highest existing GIF number
existing_gifs = [f for f in os.listdir('.') if f.startswith('test_wave_gif') and f.endswith('.gif')]
if existing_gifs:
    # Extract numbers from existing GIF filenames
    numbers = []
    for gif in existing_gifs:
        try:
            # Extract number from "test_wave_gif{N}.gif"
            number = int(gif.replace('test_wave_gif', '').replace('.gif', ''))
            numbers.append(number)
        except ValueError:
            continue
    start_number = max(numbers) + 1 if numbers else 1
else:
    start_number = 1

print(f"Starting conversion from test_wave_gif{start_number}.gif")

for i, file in enumerate(webp_files, start_number):
    gif_name = f"test_wave_gif{i}.gif"
    convert_webp_to_gif(file, gif_name)