package screenbot

import (
	"fmt"
	"image"
	"image/color"
	"image/png"
	"os"
)

type RGB struct{ R, G, B uint8 }

func (c RGB) Hex() string { return fmt.Sprintf("#%02X%02X%02X", c.R, c.G, c.B) }

func ScreenBox() (Box, error) {
	r, err := currentBackend().ScreenBounds()
	if err != nil {
		return Box{}, err
	}
	return Box{r.Min.X, r.Min.Y, r.Max.X, r.Max.Y}, nil
}

func ScreenSize() (width, height int, err error) {
	b, err := ScreenBox()
	if err != nil {
		return 0, 0, err
	}
	return b.Width(), b.Height(), nil
}

func MousePosition() (Point, error) { return currentBackend().MousePosition() }

func ClampPointToScreen(p Point) (Point, error) {
	b, err := ScreenBox()
	if err != nil {
		return Point{}, err
	}
	return Point{min(max(p.X, b.Left), b.Right-1), min(max(p.Y, b.Top), b.Bottom-1)}, nil
}

func Screenshot(box *Box) (*image.RGBA, error) {
	bounds, err := ScreenBox()
	if err != nil {
		return nil, err
	}
	if box != nil {
		bounds = intersectBoxes(bounds, *box)
	}
	if bounds.Width() <= 0 || bounds.Height() <= 0 {
		return nil, fmt.Errorf("screenshot box is empty")
	}
	return currentBackend().Capture(image.Rect(bounds.Left, bounds.Top, bounds.Right, bounds.Bottom))
}

func SaveScreenshot(path string, box *Box) error {
	img, err := Screenshot(box)
	if err != nil {
		return err
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, img)
}

func PixelColor(point Point) (RGB, error) {
	b := BoxFromXYWH(point.X, point.Y, 1, 1)
	img, err := Screenshot(&b)
	if err != nil {
		return RGB{}, err
	}
	return rgbAt(img, 0, 0), nil
}

func rgbAt(img image.Image, x, y int) RGB {
	c := color.RGBAModel.Convert(img.At(x+img.Bounds().Min.X, y+img.Bounds().Min.Y)).(color.RGBA)
	return RGB{c.R, c.G, c.B}
}
