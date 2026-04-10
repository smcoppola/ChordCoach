import sys
import os
from PySide6.QtGui import QImage, QColor

def make_transparent(input_path, output_path):
    print(f"Processing {input_path} -> {output_path}")
    image = QImage(input_path)
    if image.isNull():
        print("Error: Could not load image.")
        return False
        
    image = image.convertToFormat(QImage.Format_ARGB32)
    width = image.width()
    height = image.height()
    
    count = 0
    for y in range(height):
        for x in range(width):
            color = QColor.fromRgba(image.pixel(x, y))
            # Key out pure black or very near black
            if color.red() < 5 and color.green() < 5 and color.blue() < 5:
                image.setPixel(x, y, QColor(0, 0, 0, 0).rgba())
                count += 1
                
    if image.save(output_path, "PNG"):
        print(f"Success! Keyed out {count} pixels.")
        return True
    else:
        print("Error: Failed to save output image.")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python process_transparency.py <input> <output>")
    else:
        make_transparent(sys.argv[1], sys.argv[2])
