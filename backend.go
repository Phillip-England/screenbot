package screenbot

import (
	"fmt"
	"image"
	"image/draw"
	"runtime"
	"sync"
	"time"

	"github.com/go-vgo/robotgo"
)

// Backend isolates operating-system I/O from geometry and image processing.
// Applications normally use the built-in backend; SetBackend is useful in tests.
type Backend interface {
	ScreenBounds() (image.Rectangle, error)
	MousePosition() (Point, error)
	Capture(image.Rectangle) (*image.RGBA, error)
	Move(Point, time.Duration) error
	MouseButton(button string, down bool) error
	Scroll(amount int) error
	Key(key string, down bool) error
	Type(text string, interval time.Duration) error
	ReadClipboard() (string, error)
	WriteClipboard(text string) error
}

type nativeBackend struct{}

func (nativeBackend) ScreenBounds() (image.Rectangle, error) {
	r := robotgo.GetScreenRect(0)
	if r.W <= 0 || r.H <= 0 {
		return image.Rectangle{}, fmt.Errorf("no active display")
	}
	return image.Rect(r.X, r.Y, r.X+r.W, r.Y+r.H), nil
}
func (nativeBackend) MousePosition() (Point, error) {
	x, y := robotgo.Location()
	return Point{x, y}, nil
}
func (nativeBackend) Capture(rect image.Rectangle) (*image.RGBA, error) {
	img, err := robotgo.CaptureImg(rect.Min.X, rect.Min.Y, rect.Dx(), rect.Dy())
	if err != nil {
		return nil, err
	}
	rgba := image.NewRGBA(image.Rect(0, 0, rect.Dx(), rect.Dy()))
	if img.Bounds().Dx() == rect.Dx() && img.Bounds().Dy() == rect.Dy() {
		draw.Draw(rgba, rgba.Bounds(), img, img.Bounds().Min, draw.Src)
		return rgba, nil
	}
	// HiDPI captures use physical pixels while the public API uses logical screen coordinates.
	for y := 0; y < rect.Dy(); y++ {
		for x := 0; x < rect.Dx(); x++ {
			sx := img.Bounds().Min.X + x*img.Bounds().Dx()/rect.Dx()
			sy := img.Bounds().Min.Y + y*img.Bounds().Dy()/rect.Dy()
			rgba.Set(x, y, img.At(sx, sy))
		}
	}
	return rgba, nil
}
func (nativeBackend) Move(p Point, duration time.Duration) error {
	if duration <= 0 {
		robotgo.Move(p.X, p.Y)
		return nil
	}
	start, _ := (nativeBackend{}).MousePosition()
	steps := max(1, int(duration/(10*time.Millisecond)))
	for i := 1; i <= steps; i++ {
		t := float64(i) / float64(steps)
		robotgo.Move(start.X+int(float64(p.X-start.X)*t), start.Y+int(float64(p.Y-start.Y)*t))
		time.Sleep(duration / time.Duration(steps))
	}
	return nil
}
func (nativeBackend) MouseButton(button string, down bool) error {
	state := "up"
	if down {
		state = "down"
	}
	return robotgo.Toggle(button, state)
}
func (nativeBackend) Scroll(amount int) error { robotgo.Scroll(0, amount); return nil }
func (nativeBackend) Key(key string, down bool) error {
	state := "up"
	if down {
		state = "down"
	}
	return robotgo.KeyToggle(key, state)
}
func (nativeBackend) Type(text string, interval time.Duration) error {
	for _, r := range text {
		robotgo.TypeStr(string(r))
		if interval > 0 {
			time.Sleep(interval)
		}
	}
	return nil
}
func (nativeBackend) ReadClipboard() (string, error)   { return robotgo.ReadAll() }
func (nativeBackend) WriteClipboard(text string) error { return robotgo.WriteAll(text) }

var (
	backendMu sync.RWMutex
	backend   Backend = nativeBackend{}
	pause             = 50 * time.Millisecond
)

// SetBackend replaces the OS backend and returns a restore function.
func SetBackend(next Backend) func() {
	backendMu.Lock()
	previous := backend
	backend = next
	backendMu.Unlock()
	return func() { backendMu.Lock(); backend = previous; backendMu.Unlock() }
}

func currentBackend() Backend { backendMu.RLock(); defer backendMu.RUnlock(); return backend }

// Configure sets the pause applied after generated input events.
func Configure(eventPause time.Duration) { pause = max(0, eventPause) }
func Sleep(duration time.Duration)       { time.Sleep(duration) }

func PrimaryModifier() string {
	if runtime.GOOS == "darwin" {
		return "command"
	}
	return "ctrl"
}
