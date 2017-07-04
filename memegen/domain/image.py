import os
import hashlib
import logging

from PIL import Image as ImageFile, ImageFont, ImageDraw, ImageFilter


log = logging.getLogger(__name__)


class Image(object):
    """JPEG generated by applying text to a template."""

    def __init__(self, template, text, root=None,
                 style=None, font=None, size=None,
                 watermark="", watermark_font=None):
        self.root = root
        self.template = template
        self.style = style
        self.text = text
        self.font = font
        self.width = size.get('width') if size else None
        self.height = size.get('height') if size else None
        self.watermark = watermark
        self.watermark_font = watermark_font

    @property
    def path(self):
        if not self.root:
            return None

        base = os.path.join(self.root, self.template.key, self.text.path)
        custom = [self.style, self.font, self.watermark,
                  self.width, self.height]

        if any(custom):
            slug = self.hash(custom)
            return "{}#{}.img".format(base, slug)
        else:
            return base + ".img"

    @staticmethod
    def hash(values):
        sha = hashlib.md5()
        for index, value in enumerate(values):
            sha.update("{}:{}".format(index, value or "").encode('utf-8'))
        return sha.hexdigest()

    def save(self):
        data = _generate(
            top=self.text.top, bottom=self.text.bottom,
            font_path=self.font.path,
            background=self.template.get_path(self.style),
            width=self.width, height=self.height,
            watermark=self.watermark,
            watermark_font_path=self.watermark_font.path,
        )

        directory = os.path.dirname(self.path)
        if not os.path.isdir(directory):
            os.makedirs(directory)

        log.info("Saving image: %s", self.path)
        path = data.save(self.path, format=data.format)

        return path


def _generate(top, bottom, font_path, background, width, height,
              watermark, watermark_font_path):
    """Add text to an image and save it."""
    log.info("Loading background: %s", background)
    background_image = ImageFile.open(background)
    if background_image.mode not in ('RGB', 'RGBA'):
        if background_image.format == 'JPEG':
            background_image = background_image.convert('RGB')
            background_image.format = 'JPEG'
        else:
            background_image = background_image.convert('RGBA')
            background_image.format = 'PNG'

    # Resize to a maximum height and width
    ratio = background_image.size[0] / background_image.size[1]
    if width and height:
        if width < height * ratio:
            dimensions = width, int(width / ratio)
        else:
            dimensions = int(height * ratio), height
    elif width:
        dimensions = width, int(width / ratio)
    elif height:
        dimensions = int(height * ratio), height
    else:
        dimensions = 600, int(600 / ratio)
    image = background_image.resize(dimensions, ImageFile.LANCZOS)
    image.format = 'PNG'

    # Draw image
    draw = ImageDraw.Draw(image)

    max_font_size = int(image.size[1] / 5)
    min_font_size_single_line = int(image.size[1] / 12)
    max_text_len = image.size[0] - 20
    top_font_size, top = _optimize_font_size(
        font_path, top, max_font_size,
        min_font_size_single_line, max_text_len,
    )
    bottom_font_size, bottom = _optimize_font_size(
        font_path, bottom, max_font_size,
        min_font_size_single_line, max_text_len,
    )

    top_font = ImageFont.truetype(font_path, top_font_size)
    bottom_font = ImageFont.truetype(font_path, bottom_font_size)

    top_text_size = draw.multiline_textsize(top, top_font)
    bottom_text_size = draw.multiline_textsize(bottom, bottom_font)

    # Find top centered position for top text
    top_text_position_x = (image.size[0] / 2) - (top_text_size[0] / 2)
    top_text_position_y = 0
    top_text_position = (top_text_position_x, top_text_position_y)

    # Find bottom centered position for bottom text
    bottom_text_size_x = (image.size[0] / 2) - (bottom_text_size[0] / 2)
    bottom_text_size_y = image.size[1] - bottom_text_size[1] * (7 / 6)
    if watermark:
        bottom_text_size_y = bottom_text_size_y - 5
    bottom_text_position = (bottom_text_size_x, bottom_text_size_y)

    _draw_outlined_text(draw, top_text_position,
                        top, top_font, top_font_size)
    _draw_outlined_text(draw, bottom_text_position,
                        bottom, bottom_font, bottom_font_size)

    # Pad image if a specific dimension is requested
    if width and height:
        image = _add_blurred_background(image, background_image, width, height)

    # Add watermark
    if watermark:
        draw = ImageDraw.Draw(image)
        watermark_font = ImageFont.truetype(watermark_font_path, 15)
        _draw_outlined_text(draw, (3, image.size[1] - 20),
                            watermark, watermark_font, 15)

    return image


def _optimize_font_size(font, text, max_font_size, min_font_size,
                        max_text_len):
    """Calculate the optimal font size to fit text in a given size."""

    # Check size when using smallest single line font size
    fontobj = ImageFont.truetype(font, min_font_size)
    text_size = fontobj.getsize(text)

    # Calculate font size for text, split if necessary
    if text_size[0] > max_text_len:
        phrases = _split(text)
    else:
        phrases = (text,)
    font_size = max_font_size // len(phrases)
    for phrase in phrases:
        font_size = min(_maximize_font_size(font, phrase, max_text_len),
                        font_size)

    # Rebuild text with new lines
    text = '\n'.join(phrases)

    return font_size, text


def _draw_outlined_text(draw_image, text_position, text, font, font_size):
    """Draw white text with black outline on an image."""

    # Draw black text outlines
    outline_range = max(1, font_size // 25)
    for x in range(-outline_range, outline_range + 1):
        for y in range(-outline_range, outline_range + 1):
            pos = (text_position[0] + x, text_position[1] + y)
            draw_image.multiline_text(pos, text, (0, 0, 0),
                                      font=font, align='center')

    # Draw inner white text
    draw_image.multiline_text(text_position, text, (255, 255, 255),
                              font=font, align='center')


def _add_blurred_background(foreground, background, width, height):
    """Add a blurred background to match the requested dimensions."""
    base_width, base_height = foreground.size

    border_width = min(width, base_width + 2)
    border_height = min(height, base_height + 2)
    border_dimensions = border_width, border_height
    border = ImageFile.new('RGB', border_dimensions)
    border.paste(foreground, ((border_width - base_width) // 2,
                              (border_height - base_height) // 2))

    padded_dimensions = (width, height)
    padded = background.resize(padded_dimensions, ImageFile.LANCZOS)

    darkened = padded.point(lambda p: p * 0.4)

    blurred = darkened.filter(ImageFilter.GaussianBlur(5))
    blurred.format = 'PNG'

    blurred_width, blurred_height = blurred.size
    offset = ((blurred_width - border_width) // 2,
              (blurred_height - border_height) // 2)
    blurred.paste(border, offset)

    return blurred


def _maximize_font_size(font, text, max_size):
    """Find the biggest font size that will fit."""
    font_size = max_size

    fontobj = ImageFont.truetype(font, font_size)
    text_size = fontobj.getsize(text)
    while text_size[0] > max_size and font_size > 1:
        font_size = font_size - 1
        fontobj = ImageFont.truetype(font, font_size)
        text_size = fontobj.getsize(text)

    return font_size


def _split(text):
    """Split a line of text into two similarly sized pieces.

    >>> _split("Hello, world!")
    ('Hello,', 'world!')

    >>> _split("This is a phrase that can be split.")
    ('This is a phrase', 'that can be split.')

    >>> _split("This_is_a_phrase_that_can_not_be_split.")
    ('This_is_a_phrase_that_can_not_be_split.',)

    """
    result = (text,)

    if len(text) >= 3 and ' ' in text[1:-1]:  # can split this string
        space_indices = [i for i in range(len(text)) if text[i] == ' ']
        space_proximities = [abs(i - len(text) // 2) for i in space_indices]
        for i, j in zip(space_proximities, space_indices):
            if i == min(space_proximities):
                result = (text[:j], text[j + 1:])
                break

    return result
