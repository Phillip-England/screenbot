package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"image"
	"os"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/Phillip-England/screenbot"
)

const usage = `ScreenBot inspects the screen and mouse from the command line.

Usage:
  screenbot <command> [options]

Commands:
  pos         Print the current mouse position
  color       Inspect colors at or around the mouse
  size        Print the screen dimensions
  screenshot  Save a screenshot
  report      Print system diagnostics as JSON
  help        Show this help

Run "screenbot <command> --help" for command options.`

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "screenbot:", err)
		os.Exit(2)
	}
}

func run(args []string) error {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Println(usage)
		return nil
	}
	switch args[0] {
	case "pos":
		return runPos(args[1:])
	case "color":
		return runColor(args[1:])
	case "size":
		return runSize(args[1:])
	case "screenshot":
		return runScreenshot(args[1:])
	case "report":
		return runReport(args[1:])
	default:
		return fmt.Errorf("unknown command %q\n\n%s", args[0], usage)
	}
}

func flags(name string) *flag.FlagSet {
	f := flag.NewFlagSet(name, flag.ContinueOnError)
	f.SetOutput(os.Stderr)
	return f
}

func runPos(args []string) error {
	f := flags("pos")
	asJSON := f.Bool("json", false, "emit JSON")
	watch := f.Bool("watch", false, "keep printing")
	interval := f.Duration("interval", 500*time.Millisecond, "watch interval")
	if err := f.Parse(args); err != nil {
		return err
	}
	if *interval <= 0 {
		return fmt.Errorf("interval must be greater than zero")
	}
	for {
		p, err := screenbot.MousePosition()
		if err != nil {
			return err
		}
		if *asJSON {
			data, _ := json.Marshal(p)
			fmt.Println(string(data))
		} else {
			fmt.Printf("%d %d\n", p.X, p.Y)
		}
		if !*watch {
			return nil
		}
		time.Sleep(*interval)
	}
}

func pointFlags(f *flag.FlagSet) (*int, *int) {
	return f.Int("x", -1, "x coordinate"), f.Int("y", -1, "y coordinate")
}
func selectedPoint(x, y int) (screenbot.Point, error) {
	if (x < 0) != (y < 0) {
		return screenbot.Point{}, fmt.Errorf("--x and --y must be used together")
	}
	if x >= 0 {
		return screenbot.Point{X: x, Y: y}, nil
	}
	return screenbot.MousePosition()
}

func runColor(args []string) error {
	f := flags("color")
	asJSON := f.Bool("json", false, "emit JSON")
	x, y := pointFlags(f)
	var squareArg string
	filtered := make([]string, 0, len(args))
	for _, arg := range args {
		if strings.HasPrefix(arg, "-") && len(arg) > 1 {
			if _, err := strconv.Atoi(arg); err == nil {
				if squareArg != "" {
					return fmt.Errorf("color accepts at most one square size")
				}
				squareArg = strings.TrimPrefix(arg, "-")
				continue
			}
		}
		filtered = append(filtered, arg)
	}
	if err := f.Parse(filtered); err != nil {
		return err
	}
	p, err := selectedPoint(*x, *y)
	if err != nil {
		return err
	}
	if f.NArg() == 0 && squareArg == "" {
		c, err := screenbot.PixelColor(p)
		if err != nil {
			return err
		}
		if *asJSON {
			printJSON(map[string]any{"x": p.X, "y": p.Y, "rgb": []int{int(c.R), int(c.G), int(c.B)}, "hex": c.Hex()})
		} else {
			fmt.Printf("%d %d %d %s\n", c.R, c.G, c.B, c.Hex())
		}
		return nil
	}
	if f.NArg() > 1 || (f.NArg() == 1 && squareArg != "") {
		return fmt.Errorf("color accepts at most one square size")
	}
	if squareArg == "" {
		squareArg = f.Arg(0)
	}
	size, err := strconv.Atoi(squareArg)
	if err != nil || size <= 0 {
		return fmt.Errorf("square size must be greater than zero")
	}
	b := centeredSquare(p, size)
	img, err := screenbot.Screenshot(&b)
	if err != nil {
		return err
	}
	counts := palette(img)
	if *asJSON {
		colors := make([]map[string]any, 0, len(counts))
		for _, v := range counts {
			colors = append(colors, map[string]any{"rgb": []int{int(v.c.R), int(v.c.G), int(v.c.B)}, "hex": v.c.Hex(), "count": v.n})
		}
		printJSON(map[string]any{"box": b, "total_pixels": img.Bounds().Dx() * img.Bounds().Dy(), "colors": colors})
		return nil
	}
	for _, v := range counts {
		fmt.Printf("%d %d %d %s %d\n", v.c.R, v.c.G, v.c.B, v.c.Hex(), v.n)
	}
	return nil
}

type colorCount struct {
	c screenbot.RGB
	n int
}

func palette(img image.Image) []colorCount {
	m := map[screenbot.RGB]int{}
	b := img.Bounds()
	for y := b.Min.Y; y < b.Max.Y; y++ {
		for x := b.Min.X; x < b.Max.X; x++ {
			r, g, bl, _ := img.At(x, y).RGBA()
			m[screenbot.RGB{R: uint8(r >> 8), G: uint8(g >> 8), B: uint8(bl >> 8)}]++
		}
	}
	out := make([]colorCount, 0, len(m))
	for c, n := range m {
		out = append(out, colorCount{c, n})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].n != out[j].n {
			return out[i].n > out[j].n
		}
		a, b := out[i].c, out[j].c
		if a.R != b.R {
			return a.R < b.R
		}
		if a.G != b.G {
			return a.G < b.G
		}
		return a.B < b.B
	})
	return out
}
func centeredSquare(p screenbot.Point, size int) screenbot.Box {
	left, top := p.X-size/2, p.Y-size/2
	return screenbot.BoxFromXYWH(left, top, size, size)
}

func runSize(args []string) error {
	f := flags("size")
	asJSON := f.Bool("json", false, "emit JSON")
	if err := f.Parse(args); err != nil {
		return err
	}
	w, h, err := screenbot.ScreenSize()
	if err != nil {
		return err
	}
	if *asJSON {
		printJSON(map[string]int{"width": w, "height": h})
	} else {
		fmt.Printf("%d %d\n", w, h)
	}
	return nil
}
func runScreenshot(args []string) error {
	f := flags("screenshot")
	square := f.Int("square", 0, "capture square centered on mouse")
	if err := f.Parse(args); err != nil {
		return err
	}
	path := "screenbot.png"
	if f.NArg() > 1 {
		return fmt.Errorf("screenshot accepts one output path")
	}
	if f.NArg() == 1 {
		path = f.Arg(0)
	}
	var box *screenbot.Box
	if *square != 0 {
		if *square < 0 {
			return fmt.Errorf("square size must be greater than zero")
		}
		p, err := screenbot.MousePosition()
		if err != nil {
			return err
		}
		b := centeredSquare(p, *square)
		box = &b
	}
	if err := screenbot.SaveScreenshot(path, box); err != nil {
		return err
	}
	fmt.Println(path)
	return nil
}
func runReport(args []string) error {
	f := flags("report")
	if err := f.Parse(args); err != nil {
		return err
	}
	w, h, err := screenbot.ScreenSize()
	if err != nil {
		return err
	}
	p, err := screenbot.MousePosition()
	if err != nil {
		return err
	}
	printJSON(map[string]any{"go": runtime.Version(), "os": runtime.GOOS, "arch": runtime.GOARCH, "screen_size": []int{w, h}, "mouse_position": p, "primary_modifier": screenbot.PrimaryModifier()})
	return nil
}
func printJSON(value any) { data, _ := json.Marshal(value); fmt.Println(string(data)) }
