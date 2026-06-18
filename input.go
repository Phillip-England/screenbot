package screenbot

import (
	"fmt"
	"time"
)

type MouseButton string

type MoveStyle string

const (
	LeftButton   MouseButton = "left"
	RightButton  MouseButton = "right"
	MiddleButton MouseButton = "center"

	InstantMovement MoveStyle = "instant"
	LinearMovement  MoveStyle = "linear"
	HumanMovement   MoveStyle = "human"
)

type MoveOptions struct {
	Style             MoveStyle
	Duration          time.Duration
	JitterRadius      int
	CurveRadius       int
	Detours           int
	DetourRadius      int
	OvershootDistance int
	Steps             int
	PauseChance       float64
	PauseMin          time.Duration
	PauseMax          time.Duration
}

type ClickOptions struct {
	MoveOptions
	Button   MouseButton
	Clicks   int
	Interval time.Duration
}

func MoveTo(point Point, options MoveOptions) (Point, error) {
	p, err := point.Jitter(options.JitterRadius, options.JitterRadius, true)
	if err != nil {
		return Point{}, err
	}
	if err := movePointer(p, options); err != nil {
		return Point{}, err
	}
	time.Sleep(pause)
	return p, nil
}

// HumanMoveOptions returns practical defaults that can be selectively overridden.
func HumanMoveOptions(duration time.Duration) MoveOptions {
	return MoveOptions{
		Style:        HumanMovement,
		Duration:     duration,
		CurveRadius:  80,
		Steps:        40,
		PauseChance:  0.08,
		PauseMin:     15 * time.Millisecond,
		PauseMax:     70 * time.Millisecond,
		DetourRadius: 35,
	}
}

func MoveInstant(point Point) (Point, error) {
	return MoveTo(point, MoveOptions{Style: InstantMovement})
}

func MoveLinear(point Point, duration time.Duration) (Point, error) {
	return MoveTo(point, MoveOptions{Style: LinearMovement, Duration: duration})
}

func MoveHuman(point Point, duration time.Duration) (Point, error) {
	return MoveTo(point, HumanMoveOptions(duration))
}

func Click(point Point, options ClickOptions) (Point, error) {
	p, err := MoveTo(point, options.MoveOptions)
	if err != nil {
		return Point{}, err
	}
	button := string(options.Button)
	if button == "" {
		button = string(LeftButton)
	}
	clicks := options.Clicks
	if clicks == 0 {
		clicks = 1
	}
	if clicks < 0 {
		return Point{}, fmt.Errorf("click count cannot be negative")
	}
	for i := 0; i < clicks; i++ {
		if err := currentBackend().MouseButton(button, true); err != nil {
			return Point{}, err
		}
		if err := currentBackend().MouseButton(button, false); err != nil {
			return Point{}, err
		}
		if i+1 < clicks {
			time.Sleep(options.Interval)
		}
	}
	time.Sleep(pause)
	return p, nil
}

func DoubleClick(point Point, options ClickOptions) (Point, error) {
	options.Clicks = 2
	if options.Interval == 0 {
		options.Interval = 80 * time.Millisecond
	}
	return Click(point, options)
}

func RightClick(point Point, options ClickOptions) (Point, error) {
	options.Button = RightButton
	return Click(point, options)
}

func ClickBoxCenter(box Box, options ClickOptions) (Point, error) {
	return Click(box.Center(), options)
}

func ClickBoxRandom(box Box, margin int, options ClickOptions) (Point, error) {
	p, err := box.RandomPoint(margin)
	if err != nil {
		return Point{}, err
	}
	return Click(p, options)
}

func DragTo(start, end Point, duration time.Duration, button MouseButton) (Point, Point, error) {
	if button == "" {
		button = LeftButton
	}
	if _, err := MoveTo(start, MoveOptions{}); err != nil {
		return Point{}, Point{}, err
	}
	if err := currentBackend().MouseButton(string(button), true); err != nil {
		return Point{}, Point{}, err
	}
	if err := currentBackend().Move(end, duration); err != nil {
		return Point{}, Point{}, err
	}
	if err := currentBackend().MouseButton(string(button), false); err != nil {
		return Point{}, Point{}, err
	}
	time.Sleep(pause)
	return start, end, nil
}

func Scroll(amount int) error {
	err := currentBackend().Scroll(amount)
	time.Sleep(pause)
	return err
}

func Press(key string, presses int, interval time.Duration) error {
	if presses < 0 {
		return fmt.Errorf("press count cannot be negative")
	}
	for i := 0; i < presses; i++ {
		if err := currentBackend().Key(key, true); err != nil {
			return err
		}
		if err := currentBackend().Key(key, false); err != nil {
			return err
		}
		if i+1 < presses {
			time.Sleep(interval)
		}
	}
	time.Sleep(pause)
	return nil
}

func KeyDown(key string) error { return currentBackend().Key(key, true) }
func KeyUp(key string) error   { return currentBackend().Key(key, false) }

func Hotkey(keys ...string) error {
	if len(keys) == 0 {
		return nil
	}
	for _, key := range keys {
		if err := KeyDown(key); err != nil {
			return err
		}
	}
	for i := len(keys) - 1; i >= 0; i-- {
		if err := KeyUp(keys[i]); err != nil {
			return err
		}
	}
	time.Sleep(pause)
	return nil
}

func Shortcut(key string, extra ...string) error {
	keys := append([]string{PrimaryModifier(), key}, extra...)
	return Hotkey(keys...)
}

func TypeText(text string, interval time.Duration) error {
	return currentBackend().Type(text, interval)
}

func PasteText(text string, restoreClipboard bool) error {
	var previous string
	var err error
	if restoreClipboard {
		previous, err = currentBackend().ReadClipboard()
		if err != nil {
			return err
		}
	}
	if err := currentBackend().WriteClipboard(text); err != nil {
		return err
	}
	if err := Paste(); err != nil {
		return err
	}
	if restoreClipboard {
		return currentBackend().WriteClipboard(previous)
	}
	return nil
}

func SelectAll() error       { return Shortcut("a") }
func Copy() error            { return Shortcut("c") }
func Cut() error             { return Shortcut("x") }
func Paste() error           { return Shortcut("v") }
func Undo() error            { return Shortcut("z") }
func Find() error            { return Shortcut("f") }
func Save() error            { return Shortcut("s") }
func NewTab() error          { return Shortcut("t") }
func CloseTab() error        { return Shortcut("w") }
func ReopenClosedTab() error { return Hotkey(PrimaryModifier(), "shift", "t") }
func Refresh() error         { return Shortcut("r") }
func HardRefresh() error     { return Hotkey(PrimaryModifier(), "shift", "r") }

func Enter(presses int, interval time.Duration) error  { return Press("enter", presses, interval) }
func Escape(presses int, interval time.Duration) error { return Press("esc", presses, interval) }
func Tab(presses int, interval time.Duration) error    { return Press("tab", presses, interval) }
func Backspace(presses int, interval time.Duration) error {
	return Press("backspace", presses, interval)
}
func Delete(presses int, interval time.Duration) error { return Press("delete", presses, interval) }
func Arrow(direction string, presses int, interval time.Duration) error {
	if direction != "up" && direction != "down" && direction != "left" && direction != "right" {
		return fmt.Errorf("unknown arrow direction %q", direction)
	}
	return Press(direction, presses, interval)
}
func FindText(text string, useClipboard bool) error {
	if err := Find(); err != nil {
		return err
	}
	if useClipboard {
		return PasteText(text, false)
	}
	return TypeText(text, 0)
}

func Redo() error {
	if PrimaryModifier() == "command" {
		return Hotkey("command", "shift", "z")
	}
	return Hotkey("ctrl", "y")
}
