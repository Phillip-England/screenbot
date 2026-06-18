package screenbot

import (
	"errors"
	"image"
	"image/color"
	"path/filepath"
	"testing"
	"time"
)

type fakeBackend struct {
	bounds        image.Rectangle
	img           *image.RGBA
	images        []*image.RGBA
	captures      int
	mouse         Point
	moves         []Point
	moveDurations []time.Duration
	buttonEvents  int
}

func (f *fakeBackend) ScreenBounds() (image.Rectangle, error) { return f.bounds, nil }
func (f *fakeBackend) MousePosition() (Point, error)          { return f.mouse, nil }
func (f *fakeBackend) Capture(rect image.Rectangle) (*image.RGBA, error) {
	if len(f.images) == 0 {
		return f.img, nil
	}
	index := min(f.captures, len(f.images)-1)
	f.captures++
	return f.images[index], nil
}
func (f *fakeBackend) Move(point Point, duration time.Duration) error {
	f.moves = append(f.moves, point)
	f.moveDurations = append(f.moveDurations, duration)
	f.mouse = point
	return nil
}
func (f *fakeBackend) MouseButton(string, bool) error   { f.buttonEvents++; return nil }
func (f *fakeBackend) Scroll(int) error                 { return nil }
func (f *fakeBackend) Key(string, bool) error           { return nil }
func (f *fakeBackend) Type(string, time.Duration) error { return nil }
func (f *fakeBackend) ReadClipboard() (string, error)   { return "", nil }
func (f *fakeBackend) WriteClipboard(string) error      { return nil }

func TestGeometry(t *testing.T) {
	b := BoxFromXYWH(10, 20, 30, 40)
	if b.Width() != 30 || b.Height() != 40 || b.Area() != 1200 || b.Center() != (Point{25, 40}) {
		t.Fatalf("unexpected box: %+v", b)
	}
	if !b.Contains(Point{10, 20}) || b.Contains(Point{40, 60}) {
		t.Fatal("half-open containment is incorrect")
	}
}

func TestWeightedActions(t *testing.T) {
	actions := []WeightedAction{
		NamedPercent("first", 60, func() error { return nil }),
		NamedPercent("second", 30, func() error { return nil }),
		NamedPercent("third", 10, func() error { return nil }),
	}
	tests := []struct {
		roll float64
		want int
	}{{0, 0}, {59.999, 0}, {60, 1}, {89.999, 1}, {90, 2}, {99.999, 2}}
	for _, test := range tests {
		if got := pickWeightedAction(actions, test.roll); got != test.want {
			t.Fatalf("roll %v selected %d, want %d", test.roll, got, test.want)
		}
	}

	ran := 0
	index, err := RunWeightedAction(
		Percent(100, func() error { ran++; return nil }),
		Percent(0, func() error { t.Fatal("zero-percent action ran"); return nil }),
	)
	if err != nil || index != 0 || ran != 1 {
		t.Fatalf("index=%d ran=%d err=%v", index, ran, err)
	}
}

func TestWeightedActionValidationAndErrors(t *testing.T) {
	if _, err := RunWeightedAction(Percent(100, func() error { return nil })); err == nil {
		t.Fatal("expected too-few-actions error")
	}
	if _, err := RunWeightedAction(Percent(40, func() error { return nil }), Percent(40, func() error { return nil })); err == nil {
		t.Fatal("expected percentage-total error")
	}
	if _, err := RunWeightedAction(Percent(50, nil), Percent(50, func() error { return nil })); err == nil {
		t.Fatal("expected nil-action error")
	}
	want := errors.New("failed")
	index, err := RunWeightedAction(
		NamedPercent("broken", 100, func() error { return want }),
		Percent(0, func() error { return nil }),
	)
	if index != 0 || !errors.Is(err, want) {
		t.Fatalf("index=%d err=%v", index, err)
	}
}

func TestMouseMovementStyles(t *testing.T) {
	fake := &fakeBackend{bounds: image.Rect(0, 0, 200, 120), mouse: Point{10, 10}}
	restore := SetBackend(fake)
	defer restore()
	Configure(0)
	defer Configure(50 * time.Millisecond)

	point, err := MoveTo(Point{20, 30}, MoveOptions{})
	if err != nil || point != (Point{20, 30}) || len(fake.moves) != 1 || fake.moveDurations[0] != 0 {
		t.Fatalf("instant point=%v moves=%v durations=%v err=%v", point, fake.moves, fake.moveDurations, err)
	}
	point, err = MoveLinear(Point{60, 40}, 200*time.Millisecond)
	if err != nil || point != (Point{60, 40}) || len(fake.moves) != 2 || fake.moveDurations[1] != 200*time.Millisecond {
		t.Fatalf("linear point=%v moves=%v durations=%v err=%v", point, fake.moves, fake.moveDurations, err)
	}
}

func TestHumanMouseMovement(t *testing.T) {
	fake := &fakeBackend{bounds: image.Rect(0, 0, 200, 120), mouse: Point{10, 10}}
	restore := SetBackend(fake)
	defer restore()
	Configure(0)
	defer Configure(50 * time.Millisecond)

	options := HumanMoveOptions(400 * time.Millisecond)
	options.Steps = 24
	options.Detours = 1
	options.DetourRadius = 20
	options.OvershootDistance = 12
	options.PauseChance = 0
	target := Point{180, 90}
	point, err := MoveTo(target, options)
	if err != nil {
		t.Fatal(err)
	}
	if point != target || len(fake.moves) < options.Steps || fake.moves[len(fake.moves)-1] != target {
		t.Fatalf("point=%v move count=%d final=%v", point, len(fake.moves), fake.moves[len(fake.moves)-1])
	}
	curved := false
	for _, move := range fake.moves[:len(fake.moves)-1] {
		if !image.Pt(move.X, move.Y).In(fake.bounds) {
			t.Fatalf("movement left screen bounds: %v", move)
		}
		// Points on the direct line from (10,10) to (180,90) have this cross product near zero.
		if abs((move.X-10)*80-(move.Y-10)*170) > 170 {
			curved = true
		}
	}
	if !curved {
		t.Fatal("human movement did not curve away from the direct path")
	}
}

func TestHumanMouseMovementValidation(t *testing.T) {
	fake := &fakeBackend{bounds: image.Rect(0, 0, 100, 100), mouse: Point{10, 10}}
	restore := SetBackend(fake)
	defer restore()
	_, err := MoveTo(Point{20, 20}, MoveOptions{Style: HumanMovement, PauseChance: 1.1})
	if err == nil {
		t.Fatal("expected invalid pause chance error")
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

func TestWaitForColorAndClickWhenVisible(t *testing.T) {
	missing := image.NewRGBA(image.Rect(0, 0, 3, 3))
	visible := image.NewRGBA(image.Rect(0, 0, 3, 3))
	target := RGB{10, 20, 30}
	visible.Set(1, 1, color.RGBA{target.R, target.G, target.B, 255})

	fake := &fakeBackend{
		bounds: image.Rect(0, 0, 3, 3),
		images: []*image.RGBA{missing, visible, visible},
	}
	restore := SetBackend(fake)
	defer restore()
	Configure(0)
	defer Configure(50 * time.Millisecond)

	stats, err := WaitForColorCount(BoxFromXYWH(0, 0, 3, 3), target, 1, 0, ChannelMode, 100*time.Millisecond, time.Millisecond)
	if err != nil || stats.Count != 1 {
		t.Fatalf("stats=%+v err=%v", stats, err)
	}
	point, err := ClickColorWhenVisible(Point{0, 0}, target, 3, 0, ChannelMode, nil, 100*time.Millisecond, time.Millisecond, ClickOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if point != (Point{1, 1}) || len(fake.moves) != 1 || fake.moves[0] != point || fake.buttonEvents != 2 {
		t.Fatalf("point=%v moves=%v button events=%d", point, fake.moves, fake.buttonEvents)
	}
}

func TestWaitValidation(t *testing.T) {
	box := BoxFromXYWH(0, 0, 1, 1)
	if _, err := WaitForColorPercent(box, RGB{}, 101, 0, ChannelMode, time.Second, time.Millisecond); err == nil {
		t.Fatal("expected invalid percentage error")
	}
	if _, err := WaitForNearestColor(Point{}, RGB{}, 1, 0, ChannelMode, nil, time.Second, 0); err == nil {
		t.Fatal("expected invalid poll interval error")
	}
	if _, err := WaitForImage("missing.png", time.Second, 0, MatchOptions{}); err == nil {
		t.Fatal("expected invalid poll interval error")
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
