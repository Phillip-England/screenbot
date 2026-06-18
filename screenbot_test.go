package screenbot

import (
	"image"
	"image/color"
	"path/filepath"
	"testing"
	"time"
)

type fakeBackend struct {
	bounds image.Rectangle
	img    *image.RGBA
	mouse  Point
}

func (f *fakeBackend) ScreenBounds() (image.Rectangle, error)            { return f.bounds, nil }
func (f *fakeBackend) MousePosition() (Point, error)                     { return f.mouse, nil }
func (f *fakeBackend) Capture(rect image.Rectangle) (*image.RGBA, error) { return f.img, nil }
func (f *fakeBackend) Move(Point, time.Duration) error                   { return nil }
func (f *fakeBackend) MouseButton(string, bool) error                    { return nil }
func (f *fakeBackend) Scroll(int) error                                  { return nil }
func (f *fakeBackend) Key(string, bool) error                            { return nil }
func (f *fakeBackend) Type(string, time.Duration) error                  { return nil }
func (f *fakeBackend) ReadClipboard() (string, error)                    { return "", nil }
func (f *fakeBackend) WriteClipboard(string) error                       { return nil }

func TestGeometry(t *testing.T) {
	b := BoxFromXYWH(10, 20, 30, 40)
	if b.Width() != 30 || b.Height() != 40 || b.Area() != 1200 || b.Center() != (Point{25, 40}) {
		t.Fatalf("unexpected box: %+v", b)
	}
	if !b.Contains(Point{10, 20}) || b.Contains(Point{40, 60}) {
		t.Fatal("half-open containment is incorrect")
	}
}

func TestCoordinateBookRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "coords.json")
	book, err := NewCoordinateBook(path)
	if err != nil {
		t.Fatal(err)
	}
	book.Set("button", Point{12, 34})
	if err := book.Save(); err != nil {
		t.Fatal(err)
	}
	loaded, err := NewCoordinateBook(path)
	if err != nil {
		t.Fatal(err)
	}
	p, err := loaded.Get("button")
	if err != nil || p != (Point{12, 34}) {
		t.Fatalf("got %v, %v", p, err)
	}
}

func TestScanAndFindNearestColor(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 3, 3))
	for y := 0; y < 3; y++ {
		for x := 0; x < 3; x++ {
			img.Set(x, y, color.RGBA{1, 2, 3, 255})
		}
	}
	img.Set(1, 1, color.RGBA{10, 20, 30, 255})
	stats, err := ScanColor(img, RGB{1, 2, 3}, 0, ChannelMode)
	if err != nil || stats.Count != 8 || stats.Total != 9 {
		t.Fatalf("stats=%+v err=%v", stats, err)
	}
	fake := &fakeBackend{bounds: image.Rect(0, 0, 3, 3), img: img}
	restore := SetBackend(fake)
	defer restore()
	p, err := FindNearestColor(Point{0, 0}, RGB{10, 20, 30}, 3, 0, ChannelMode, nil)
	if err != nil || p == nil || *p != (Point{1, 1}) {
		t.Fatalf("point=%v err=%v", p, err)
	}
}

func TestMatchImage(t *testing.T) {
	hay := image.NewRGBA(image.Rect(0, 0, 4, 4))
	needle := image.NewRGBA(image.Rect(0, 0, 2, 2))
	colors := []color.RGBA{{255, 0, 0, 255}, {0, 255, 0, 255}, {0, 0, 255, 255}, {255, 255, 255, 255}}
	for i, c := range colors {
		x, y := i%2, i/2
		needle.Set(x, y, c)
		hay.Set(x+1, y+2, c)
	}
	scores, err := matchImage(hay, needle, false)
	if err != nil {
		t.Fatal(err)
	}
	best := scores[0]
	for _, s := range scores {
		if s.score > best.score {
			best = s
		}
	}
	if best.x != 1 || best.y != 2 || best.score < .999 {
		t.Fatalf("best=%+v", best)
	}
}
