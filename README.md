# ScreenBot

ScreenBot is a Go library and CLI for screen automation. It provides mouse and
keyboard control, screenshots, color scanning, saved coordinates, and pure-Go
template matching without an OpenCV installation.

## Install

Install the CLI directly:

```bash
go install github.com/Phillip-England/screenbot/cmd/screenbot@latest
```

Or build this checkout:

```bash
make install
```

On macOS, grant Accessibility permission for input control and Screen Recording
permission for screenshots. Linux builds require the X11 development libraries
used by RobotGo. Windows builds require a working C compiler because RobotGo
uses CGO for native input.

## CLI

```bash
screenbot pos
screenbot pos --json
screenbot pos --watch --interval 250ms
screenbot color
screenbot color -50
screenbot color --x 100 --y 200 --json
screenbot size
screenbot screenshot desktop.png
screenbot screenshot --square 200 selection.png
screenbot report
screenbot help
```

`color` prints the RGB and hexadecimal color at the selected point. A square
size lists every unique color, ordered by frequency. Negative square sizes are
accepted as shorthand for compatibility with the original CLI.

## Library

```bash
go get github.com/Phillip-England/screenbot
```

```go
package main

import (
    "log"
    "time"

    "github.com/Phillip-England/screenbot"
)

func main() {
    point, err := screenbot.MousePosition()
    if err != nil {
        log.Fatal(err)
    }

    _, err = screenbot.Click(point.Offset(20, 20), screenbot.ClickOptions{
        MoveOptions: screenbot.MoveOptions{Duration: 200 * time.Millisecond},
    })
    if err != nil {
        log.Fatal(err)
    }
}
```

### Mouse Movement

The zero-value options jump immediately, while the convenience functions make
the intended movement style explicit:

```go
screenbot.MoveInstant(screenbot.Point{X: 100, Y: 200})
screenbot.MoveLinear(screenbot.Point{X: 500, Y: 300}, 400*time.Millisecond)
screenbot.MoveHuman(screenbot.Point{X: 800, Y: 450}, 700*time.Millisecond)
```

Start with `HumanMoveOptions` when the path needs controlled imperfections:

```go
move := screenbot.HumanMoveOptions(900 * time.Millisecond)
move.Detours = 1
move.DetourRadius = 45
move.OvershootDistance = 12
move.JitterRadius = 3
move.PauseChance = 0.12
move.PauseMin = 20 * time.Millisecond
move.PauseMax = 90 * time.Millisecond

_, err := screenbot.MoveTo(screenbot.Point{X: 800, Y: 450}, move)
```

`CurveRadius` controls the bend, `Steps` controls path smoothness, and
`Duration` covers movement time; random pauses are additional. The same
options can be embedded in `ClickOptions` for human-style move-and-click flows.

### Percentage-Based Actions

`RunWeightedAction` chooses and runs exactly one action. The percentages must
total 100:

```go
chosen, err := screenbot.RunWeightedAction(
    screenbot.NamedPercent("open menu", 65, func() error {
        _, err := screenbot.Click(screenbot.Point{X: 300, Y: 200}, screenbot.ClickOptions{})
        return err
    }),
    screenbot.NamedPercent("scroll", 25, func() error {
        return screenbot.Scroll(-3)
    }),
    screenbot.NamedPercent("wait", 10, func() error {
        screenbot.Sleep(500 * time.Millisecond)
        return nil
    }),
)
if err != nil { log.Fatal(err) }
fmt.Println("selected action index:", chosen)
```

Use `Percent` instead of `NamedPercent` when names are unnecessary. Zero-percent
actions are allowed and will never be selected.

### Geometry And Coordinates

```go
p := screenbot.Point{X: 100, Y: 200}
box := screenbot.BoxFromXYWH(50, 60, 300, 200)

book, err := screenbot.NewCoordinateBook("coords.json")
if err != nil { log.Fatal(err) }
book.Set("download", p)
if err := book.Save(); err != nil { log.Fatal(err) }
```

### Screenshots And Colors

```go
box := screenbot.BoxFromXYWH(100, 100, 400, 300)
if err := screenbot.SaveScreenshot("region.png", &box); err != nil {
    log.Fatal(err)
}

stats, err := screenbot.GetColorStats(
    box,
    screenbot.RGB{R: 255, G: 0, B: 0},
    10,
    screenbot.ChannelMode,
)
if err != nil { log.Fatal(err) }
fmt.Println(stats.Count, stats.Percent())

_, err = screenbot.WaitForColor(
    box, screenbot.RGB{R: 255}, 10, screenbot.ChannelMode,
    5*time.Second, 100*time.Millisecond,
)
if err != nil { log.Fatal(err) }

// Wait for a red pixel near the button, then click it.
_, err = screenbot.ClickColorWhenVisible(
    screenbot.Point{X: 500, Y: 300},
    screenbot.RGB{R: 255},
    100, 10, screenbot.ChannelMode, nil,
    5*time.Second, 100*time.Millisecond,
    screenbot.ClickOptions{},
)
if err != nil { log.Fatal(err) }
```

### Template Matching

Template matching is implemented in Go and does not require OpenCV:

```go
match, err := screenbot.LocateImage("download.png", screenbot.MatchOptions{
    Confidence: 0.90,
    Grayscale:  true,
})
if err != nil { log.Fatal(err) }
if match != nil {
    _, err = screenbot.Click(match.Center(), screenbot.ClickOptions{})
}
```

Use `LocateAllImages`, `WaitForImage`, `MoveToImage`, `ClickImage`, and
`ClickImageWhenVisible` for common matching workflows. The matcher prioritizes
portability over OpenCV's speed, so narrow `SearchBox` regions are recommended
for large screens.

### Keyboard

```go
screenbot.TypeText("hello", 20*time.Millisecond)
screenbot.Hotkey(screenbot.PrimaryModifier(), "a")
screenbot.Copy()
screenbot.Paste()
screenbot.HardRefresh()
```

ScreenBot controls the real mouse and keyboard. Start with slow actions and
small test flows. The Go backend does not currently implement PyAutoGUI's
move-to-corner fail-safe; use process cancellation or an application-specific
stop mechanism for long-running automation.

## Development

```bash
make test
make vet
make build
```

The original Python implementation remains in the repository for migration
reference, but Go is now the primary library and CLI.
