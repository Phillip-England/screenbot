package screenbot

import (
	"fmt"
	"math"
	"math/rand/v2"
)

// Point is a screen coordinate.
type Point struct {
	X int `json:"x"`
	Y int `json:"y"`
}

func (p Point) Offset(dx, dy int) Point { return Point{p.X + dx, p.Y + dy} }

func (p Point) DistanceTo(other Point) float64 {
	return math.Hypot(float64(p.X-other.X), float64(p.Y-other.Y))
}

// Jitter returns a random nearby point. Negative radii are treated as positive.
func (p Point) Jitter(xRadius, yRadius int, clamp bool) (Point, error) {
	xRadius = abs(xRadius)
	yRadius = abs(yRadius)
	p.X += rand.IntN(xRadius*2+1) - xRadius
	p.Y += rand.IntN(yRadius*2+1) - yRadius
	if clamp {
		return ClampPointToScreen(p)
	}
	return p, nil
}

// Box uses half-open geometry: left/top are included and right/bottom excluded.
type Box struct {
	Left   int `json:"left"`
	Top    int `json:"top"`
	Right  int `json:"right"`
	Bottom int `json:"bottom"`
}

func BoxFromXYWH(x, y, width, height int) Box {
	return Box{Left: x, Top: y, Right: x + width, Bottom: y + height}
}

func BoxAround(center Point, radius int) Box {
	return Box{center.X - radius, center.Y - radius, center.X + radius + 1, center.Y + radius + 1}
}

func (b Box) Width() int  { return b.Right - b.Left }
func (b Box) Height() int { return b.Bottom - b.Top }
func (b Box) Area() int   { return max(0, b.Width()) * max(0, b.Height()) }
func (b Box) Center() Point {
	return Point{b.Left + b.Width()/2, b.Top + b.Height()/2}
}
func (b Box) Contains(p Point) bool {
	return b.Left <= p.X && p.X < b.Right && b.Top <= p.Y && p.Y < b.Bottom
}
func (b Box) Expand(amount int) Box {
	return Box{b.Left - amount, b.Top - amount, b.Right + amount, b.Bottom + amount}
}

func (b Box) ClampToScreen() (Box, error) {
	screen, err := ScreenBox()
	if err != nil {
		return Box{}, err
	}
	return intersectBoxes(b, screen), nil
}

func (b Box) RandomPoint(margin int) (Point, error) {
	if margin < 0 || b.Width() <= margin*2 || b.Height() <= margin*2 {
		return Point{}, fmt.Errorf("box too small for margin %d: %+v", margin, b)
	}
	return Point{
		X: b.Left + margin + rand.IntN(b.Width()-margin*2),
		Y: b.Top + margin + rand.IntN(b.Height()-margin*2),
	}, nil
}

func intersectBoxes(a, b Box) Box {
	return Box{max(a.Left, b.Left), max(a.Top, b.Top), min(a.Right, b.Right), min(a.Bottom, b.Bottom)}
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}
